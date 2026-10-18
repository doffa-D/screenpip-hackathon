"""Evidence-backed grouping; members always remain individually selectable."""
from datetime import datetime, timezone
from uuid import uuid4
from pydantic import Field, model_validator
from fastapi import APIRouter, HTTPException
from .models import Model, TaskCandidate, TaskOccurrence


class DiscoveryRequest(Model):
    start_time: datetime
    end_time: datetime

    @model_validator(mode='after')
    def bounded(self):
        if not self.start_time.tzinfo or not self.end_time.tzinfo or self.end_time <= self.start_time:
            raise ValueError('Supply an ordered interval with timezone offsets')
        if (self.end_time - self.start_time).days > 31:
            raise ValueError('Choose at most 31 days')
        return self


class GroupCandidate(Model):
    title: str
    summary: str
    members: list[TaskCandidate] = Field(min_length=2)


class DiscoveryResult(Model):
    groups: list[GroupCandidate]
    coverage_notes: str


def router(repository, investigate, publish):
    routes = APIRouter()
    groups = repository.read('workflow_groups', {})

    @routes.get('/workflow-groups')
    async def listing():
        return list(groups.values())

    @routes.post('/workflows/discover')
    async def discover(body: DiscoveryRequest):
        output, ledger = await investigate({'instruction':
            'Find repeated workflows in this bounded interval. Inspect original app activity. '
            'Group only distinct occurrences of the same goal, never repeated frames of one occurrence. '
            'Each member must have original_activity evidence and a distinct real timestamp. '
            'Keep occurrence details individually addressable. Do not group discussion mentions. '
            'Disclose pagination/coverage limitations. Counts are observed, not exhaustive.',
            'start_time': body.start_time.isoformat(), 'end_time': body.end_time.isoformat(),
            'strict_interval': True}, DiscoveryResult)
        result = []
        for candidate in output.groups:
            seen = set()
            members = []
            for member in candidate.members:
                if not member.timestamp.tzinfo or not body.start_time <= member.timestamp <= body.end_time:
                    raise HTTPException(502, 'Discovery returned an occurrence outside the selected interval')
                if not any(e.source_kind == 'original_activity' for e in member.evidence):
                    raise HTTPException(502, 'Discovery member lacks original activity evidence')
                # Identical evidence cannot be counted as a second occurrence.
                identity = tuple(sorted((e.call_id, e.quote) for e in member.evidence))
                if identity in seen or any(m.timestamp == member.timestamp for m in members):
                    continue
                seen.add(identity)
                task = TaskOccurrence(id=str(uuid4()), **member.model_dump())
                publish(task, ledger)
                members.append(task)
            if len(members) < 2:
                continue
            group = {'id': str(uuid4()), 'title': candidate.title, 'summary': candidate.summary,
                     'members': [m.model_dump(mode='json') for m in members],
                     'observed_count': len(members), 'start_time': body.start_time.isoformat(),
                     'end_time': body.end_time.isoformat(), 'coverage_notes': output.coverage_notes,
                     'created_at': datetime.now(timezone.utc).isoformat()}
            group['ledger'] = ledger
            groups[group['id']] = group
            result.append(group)
        repository.write('workflow_groups', groups)
        return result

    @routes.get('/workflow-groups/{key}')
    async def read(key: str):
        if key not in groups:
            raise HTTPException(404, 'Workflow group not found')
        return groups[key]

    @routes.delete('/workflow-groups/{key}/members/{task_id}')
    async def remove(key: str, task_id: str):
        group = await read(key)
        group['members'] = [m for m in group['members'] if m['id'] != task_id]
        group['observed_count'] = len(group['members'])
        repository.write('workflow_groups', groups)
        return group

    return routes
