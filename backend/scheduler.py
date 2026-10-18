"""Single-process persistent scheduler. Missed slots never catch up silently."""
import asyncio
import calendar
import sys
from datetime import datetime, timedelta, timezone, date, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import uuid4
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import Field, field_validator
from .models import Model, ExecutionRequest


def desktop_unlocked():
    if sys.platform != 'win32':
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    desktop = user32.OpenInputDesktop(0, False, 0x0100)
    if not desktop:
        return False
    try:
        return bool(user32.SwitchDesktop(desktop))
    finally:
        user32.CloseDesktop(desktop)


class ScheduleInput(Model):
    workflow_id: str
    frequency: Literal['once', 'daily', 'weekly', 'monthly']
    local_date: date
    local_time: time
    timezone: str = 'Europe/Paris'
    enabled: bool = True
    notifications: bool = True

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError('Use a valid IANA timezone') from None
        return value

    @field_validator('local_time')
    @classmethod
    def wall_clock(cls, value):
        if value.tzinfo:
            raise ValueError('Time must be local without an offset')
        return value


def next_occurrence(rule, after):
    zone = ZoneInfo(rule.timezone)
    first = rule.local_date
    start = max(first, after.astimezone(zone).date())
    for offset in range(3700):
        day = start + timedelta(days=offset)
        if rule.frequency == 'once' and day != first:
            return None
        if rule.frequency == 'weekly' and day.weekday() != first.weekday():
            continue
        if rule.frequency == 'monthly' and day.day != min(first.day, calendar.monthrange(day.year, day.month)[1]):
            continue
        local = datetime.combine(day, rule.local_time).replace(tzinfo=zone, fold=0)
        utc = local.astimezone(timezone.utc)
        # Nonexistent spring times are skipped; autumn duplicates use first fold only.
        if utc.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
            continue
        if utc > after:
            return utc.isoformat()
    return None


class Scheduler:
    def __init__(self, repository, workflows, executions):
        self.repository, self.workflows, self.executions = repository, workflows, executions
        self.records = repository.read('schedules', {})
        for record in self.records.values():
            record.setdefault('notifications', True)
        self.occurrences = repository.read('schedule_occurrences', {})
        for occurrence in self.occurrences.values():
            if occurrence['status'] == 'dispatching':
                occurrence.update(status='interrupted', explanation='Server restarted during dispatch; no automatic retry.')
        self.worker = None

    def persist(self):
        self.repository.write('schedules', self.records)
        self.repository.write('schedule_occurrences', self.occurrences)

    def create(self, body, key=None):
        workflow = self.workflows.get(body.workflow_id)
        previous = self.records.get(key)
        if previous and previous['workflow_id'] == body.workflow_id:
            from .workflow_store import SavedWorkflow
            workflow = SavedWorkflow.model_validate(previous['workflow_snapshot'])
        stamp = datetime.now(timezone.utc)
        record = {'id': key or str(uuid4()), **body.model_dump(mode='json'),
                  'workflow_revision': workflow.revision, 'title': workflow.title,
                  'workflow_snapshot': workflow.model_dump(mode='json'),
                  'next_run_at': next_occurrence(body, stamp),
                  'origin': workflow.origin, 'source_kind': workflow.source_kind,
                  'tags': ['demo'] if workflow.origin == 'demo' else []}
        if body.enabled and not record['next_run_at']:
            raise ValueError('Choose a future occurrence')
        self.records[record['id']] = record
        self.persist()
        return record

    async def tick(self, startup=False):
        now = datetime.now(timezone.utc)
        for record in list(self.records.values()):
            if not record['enabled'] or not record['next_run_at']:
                continue
            due = datetime.fromisoformat(record['next_run_at'])
            if due > now:
                continue
            key = record['id'] + ':' + record['next_run_at']
            if key not in self.occurrences:
                occurrence = {'id': key, 'schedule_id': record['id'], 'scheduled_at': record['next_run_at'],
                              'status': 'dispatching', 'run_id': None, 'explanation': ''}
                self.occurrences[key] = occurrence
                self.persist()  # claim BEFORE creating a desktop run
                if startup or (now - due).total_seconds() > 60:
                    occurrence.update(status='missed', explanation='Server unavailable at scheduled time. No catch-up run started.')
                else:
                    try:
                        if not desktop_unlocked():
                            raise ValueError('Interactive desktop is unavailable or locked')
                        self.workflows.get(record['workflow_id'])
                        from .workflow_store import SavedWorkflow
                        snapshot = SavedWorkflow.model_validate(record['workflow_snapshot'])
                        run = self.executions.start(snapshot.task, snapshot.reconstruction, snapshot.run_defaults, saved=snapshot, allow_auto=False)
                        run.update(workflow_id=snapshot.id, workflow_revision=snapshot.revision, triggered_by='schedule',
                                   notify=record.get('notifications', True))
                        self.executions.event(run, 'schedule', 'Scheduled workflow revision selected',
                                              {'schedule_id': record['id'], 'revision': snapshot.revision})
                        occurrence.update(status='started', run_id=run['id'])
                    except (ValueError, KeyError):
                        occurrence.update(status='blocked', explanation='Workflow unavailable, missing values, desktop disabled, or another run active.')
            record['next_run_at'] = next_occurrence(ScheduleInput.model_validate({k: record[k] for k in ScheduleInput.model_fields}), now)
            if not record['next_run_at']:
                record['enabled'] = False
            self.persist()

    async def loop(self):
        await self.tick(startup=True)
        while True:
            await asyncio.sleep(2)
            await self.tick()

    async def close(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)


def router(service):
    routes = APIRouter()

    @routes.get('/schedules')
    async def listing():
        return list(service.records.values())

    @routes.post('/schedules/preview')
    async def preview(body: ScheduleInput):
        return {'next_run_at': next_occurrence(body, datetime.now(timezone.utc))}

    @routes.post('/schedules', status_code=201)
    async def create(body: ScheduleInput):
        try:
            return service.create(body)
        except (KeyError, ValueError) as exc:
            raise HTTPException(409, 'Choose a saved workflow and a future occurrence') from None

    @routes.patch('/schedules/{key}')
    async def update(key: str, body: ScheduleInput):
        if key not in service.records:
            raise HTTPException(404, 'Schedule not found')
        try:
            return service.create(body, key)
        except (KeyError, ValueError):
            raise HTTPException(409, 'Choose a saved workflow and a future occurrence') from None

    @routes.delete('/schedules/{key}', status_code=204)
    async def delete(key: str):
        if key not in service.records:
            raise HTTPException(404, 'Schedule not found')
        del service.records[key]
        service.persist()

    @routes.get('/schedules/{key}/occurrences')
    async def occurrences(key: str):
        return [v for v in service.occurrences.values() if v['schedule_id'] == key]

    return routes
