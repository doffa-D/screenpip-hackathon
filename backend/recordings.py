"""Timestamp bookmarks over Screenpipe history; never controls capture."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from pydantic import Field
from .models import Model, Reconstruction, TaskOccurrence
from .refine import refine


def now():
    return datetime.now(timezone.utc).isoformat()


class StartRecording(Model):
    title: str = Field(default='Recorded workflow', min_length=1, max_length=300)


class Marker(Model):
    label: str = Field(default='', max_length=300)


class RecordingService:
    def __init__(self, repository, investigate, publish):
        self.repository = repository
        self.investigate = investigate
        self.publish = publish
        self.records = repository.read('recordings', {})
        self.jobs = repository.read('jobs', {})
        self.workers = {}
        self.health_check = None
        for job in self.jobs.values():
            if job['status'] in ('queued', 'running'):
                job.update(status='interrupted', error='Server restarted. Retry processing the saved interval.', finished_at=now())
        for record in self.records.values():
            if record['status'] == 'processing':
                record['status'] = 'interrupted'
        self.persist()

    def persist(self):
        self.repository.write('recordings', self.records)
        self.repository.write('jobs', self.jobs)

    def get(self, key):
        if key not in self.records:
            raise HTTPException(404, 'Recording segment not found')
        return self.records[key]

    def start(self, title):
        if any(r['status'] == 'recording' for r in self.records.values()):
            raise HTTPException(409, 'A recording segment is already active')
        record = {'id': str(uuid4()), 'title': title, 'started_at': now(), 'ended_at': None,
                  'markers': [], 'status': 'recording', 'job_id': None, 'task_id': None,
                  'workflow': None, 'capture_status': 'Not checked. Screenpipe must be recording independently.'}
        self.records[record['id']] = record
        self.persist()
        if self.health_check:
            task = asyncio.create_task(self.check_health(record))
            self.workers['health:' + record['id']] = task
        return record

    async def check_health(self, record):
        try:
            record['capture_status'] = await self.health_check()
        except Exception:
            record['capture_status'] = 'Screenpipe health could not be checked. The interval is saved; history may be missing.'
        self.persist()

    def process(self, record):
        if record['status'] == 'processing':
            raise HTTPException(409, 'Processing is already running')
        job = {'id': str(uuid4()), 'recording_id': record['id'], 'status': 'queued',
               'started_at': now(), 'finished_at': None, 'error': None}
        record.update(status='processing', job_id=job['id'])
        self.jobs[job['id']] = job
        self.persist()
        self.workers[job['id']] = asyncio.create_task(self.run(record, job))
        return record

    async def run(self, record, job):
        try:
            job['status'] = 'running'
            self.persist()
            request = {
                'instruction': 'Reconstruct the workflow actually performed in this bounded recording segment. '
                'Retrieve original activity with MCP, inspect context and paginate as needed. '
                'Only use evidence timestamped inside the exact interval. Do not use surrounding activity as facts. '
                'If no original activity is available, report failure rather than inventing a workflow. '
                'Markers are user bookmarks, not proof that an action happened. Missing input details stay missing. '
                'Write the steps as a COMPLETE ordered list, one step per user action, never a short summary: every app or window '
                'the user moved to (app_switch and window_focus input events), every menu or button clicked with its label '
                '(for example a desktop right-click menu choice such as "Text Document"), typing, saving, and every web page '
                'reached in a browser (for example WhatsApp in Chrome). Cover all apps seen in the interval, not only the first. '
                'Leave out the Melon window itself (starting or stopping the recording, clicks inside Melon, switching back to Melon) '
                'and never write a step that nothing on screen supports. '
                'Keystrokes are NOT captured, but their RESULT is: compare the on-screen state across frames (search-elements for '
                'text fields, the Name box, the formula bar, the document title, the status bar). A cell reference in the Name box '
                '(for example B26), a formula or value in the formula bar (for example =SUM(B19:B25)), a selected range (B26:G26), '
                '"Saving..." or "Last edit was seconds ago", a new or changed document title, or an unsaved marker all prove the user '
                'ENTERED or CHANGED something. Write that as a step ("Selected cell B26 and entered the formula =SUM(B19:B25)") and '
                'record the cell, the formula and the tab name in historical_values. '
                'State the goal as what the user achieved or changed, never as "review" or "view" when an edit is visible. '
                'Record the full address (URL) of every web page reached, and the exact name of the sheet tab or page section used. '
                'Record every value you can see (file names, typed text, apps, button labels) in historical_values. '
                'For any message, chat or email the user sent, record the recipient or chat and the exact message text (shown in the conversation or in the chat-list preview) in historical_values. '
                'Use missing_values ONLY for data the user must supply that is genuinely absent from the interval, named as the data itself '
                '(for example "Message text", "Recipient"), never as a yes/no question about whether something was intended, sent or done; '
                'never list how something was done (how a file was opened or saved, which control was clicked, whether recording stopped).',
                'start_time': record['started_at'], 'end_time': record['ended_at'],
                'strict_interval': True,
                'title': record['title'], 'markers': record['markers']}
            for attempt in range(2):
                job['attempt'] = attempt + 1
                self.persist()
                try:
                    output, ledger = await self.investigate(request, Reconstruction)
                    break
                except HTTPException as exc:
                    if attempt or exc.status_code not in (502, 503, 504):
                        raise
                    # Let pending captures ingest once, retaining exactly the same bounds.
                    await asyncio.sleep(3)
            if not any(e.source_kind == 'original_activity' for e in output.evidence):
                raise ValueError('No original activity evidence was recovered for this interval')
            output, auto = await refine(self.investigate, output, ledger)
            task = TaskOccurrence(id=str(uuid4()), title=record['title'], timestamp=record['started_at'],
                                  summary=output.goal, evidence=output.evidence)
            self.publish(task, output, ledger)
            record.update(status='ready', task_id=task.id, workflow=output.model_dump(mode='json'), ledger=ledger, auto_filled=auto)
            job.update(status='completed', finished_at=now())
        except asyncio.CancelledError:
            job.update(status='interrupted', error='Processing stopped. Retry the saved interval.', finished_at=now())
            record['status'] = 'interrupted'
            raise
        except Exception as exc:
            # Never persist provider request bodies or arbitrary upstream exception text.
            message = exc.detail if isinstance(exc, HTTPException) else 'No verified workflow could be reconstructed. Check capture availability and retry.'
            job.update(status='failed', error=message, finished_at=now())
            record['status'] = 'failed'
        finally:
            self.persist()

    async def close(self):
        workers = list(self.workers.values())
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


def router(service):
    routes = APIRouter()

    @routes.get('/recordings')
    async def list_recordings():
        return [{**{k: v for k, v in record.items() if k not in ('ledger', 'workflow')},
                 'step_count': len(record['workflow']['steps']) if record.get('workflow') else None,
                 'summary': record['workflow']['goal'] if record.get('workflow') else None}
                for record in reversed(list(service.records.values()))]

    @routes.post('/recordings/start', status_code=201)
    async def start(body: StartRecording):
        return service.start(body.title)

    @routes.get('/recordings/{key}')
    async def read(key: str):
        return service.get(key)

    @routes.post('/recordings/{key}/markers')
    async def mark(key: str, body: Marker):
        record = service.get(key)
        if record['status'] != 'recording':
            raise HTTPException(409, 'Markers require an active recording segment')
        record['markers'].append({'timestamp': now(), 'label': body.label})
        service.persist()
        return record

    @routes.post('/recordings/{key}/stop', status_code=202)
    async def stop(key: str):
        record = service.get(key)
        if record['status'] != 'recording':
            raise HTTPException(409, 'This segment has already ended')
        record['ended_at'] = now()
        return service.process(record)

    @routes.post('/recordings/{key}/retry-processing', status_code=202)
    async def retry(key: str):
        record = service.get(key)
        if not record['ended_at']:
            raise HTTPException(409, 'Stop the segment before processing')
        return service.process(record)

    @routes.get('/jobs/{key}')
    async def job(key: str):
        if key not in service.jobs:
            raise HTTPException(404, 'Job not found')
        return service.jobs[key]

    return routes
