"""Durable original task occurrences; private ledgers never leave this store."""
import copy
import hashlib
from datetime import datetime, timezone
from typing import Literal
from pydantic import Field
from .models import Model, TaskOccurrence


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Memory(TaskOccurrence):
    end_timestamp: datetime | None = None
    apps: list[str]
    source_kind: Literal['original_activity', 'seeded_demo'] = 'original_activity'
    confidence: float | None = Field(default=None, ge=0, le=1)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


def same_occurrence(a, b):
    if a.get('source_kind') == 'seeded_demo' or b.get('source_kind') == 'seeded_demo':
        return False
    if set(a['source_ids']) & set(b['source_ids']):
        return True
    start_a, start_b = (datetime.fromisoformat(m['timestamp']) for m in (a, b))
    if start_a == start_b:
        return True
    if not set(a['apps']) & set(b['apps']):
        return False
    end_a = datetime.fromisoformat(a.get('end_timestamp') or a['timestamp'])
    end_b = datetime.fromisoformat(b.get('end_timestamp') or b['timestamp'])
    return max(start_a, start_b) <= min(end_a, end_b)


class MemoryIndex:
    def __init__(self, repository):
        self.repository = repository
        def validate(records):
            if not isinstance(records, dict):
                raise ValueError('Invalid memory index')
            for key, record in records.items():
                memory = Memory.model_validate(self.public(record))
                if memory.id != key or not isinstance(record['ledger'], dict) or not isinstance(record['source_ids'], list):
                    raise ValueError('Invalid memory identity or private source ledger')
        self.records = repository.read_recoverable('memories', {}, validate)
        if not (repository.directory / 'memories.json').exists():
            repository.write('memories', self.records)

    @staticmethod
    def public(record):
        return {k: v for k, v in record.items() if k not in ('ledger', 'source_ids', 'workflow')}

    def get(self, key):
        return self.records[key]

    def merge(self, occurrences, metadata=None):
        records = copy.deepcopy(self.records)
        changed = False
        for occurrence in occurrences:
            now = stamp()
            meta = (metadata or {}).get(occurrence['id'], {})
            data = {k: occurrence[k] for k in ('title', 'timestamp', 'summary', 'evidence', 'ledger', 'source_ids')}
            data.update(id='memory:' + hashlib.sha256('|'.join(sorted(data['source_ids'])).encode()).hexdigest()[:24],
                apps=[occurrence['app']], end_timestamp=occurrence.get('ended_at'),
                source_kind='original_activity', confidence=meta.get('confidence'), tags=meta.get('tags', []),
                created_at=now, updated_at=now)
            key = next((key for key, old in records.items() if same_occurrence(old, data)), data['id'])
            old = records.get(key)
            if old:
                # A replay must not rewrite timestamps or replace a reconstructed workflow.
                # Retain the first verified occurrence; enrich only server-owned pattern metadata.
                data = copy.deepcopy(old)
                if meta:
                    data.update(confidence=meta.get('confidence'), tags=meta.get('tags', []))
                if data == old:
                    continue
                data['updated_at'] = now
            Memory.model_validate(self.public(data))
            records[key] = data
            changed = True
        if changed:
            self.repository.write('memories', records)
            self.records = records
        return changed

    def listing(self, q='', start=None, end=None, app=None, source=None, limit=100, offset=0, tag=None):
        values = []
        for record in self.records.values():
            when = datetime.fromisoformat(record['timestamp'])
            if start and when < start or end and when >= end:
                continue
            if app and app.casefold() not in [a.casefold() for a in record['apps']]:
                continue
            if source and source != record['source_kind']:
                continue
            if tag and tag.casefold() not in [t.casefold() for t in record['tags']]:
                continue
            text = ' '.join([record['title'], record['summary'], *record['apps'], *record['tags']]).casefold()
            if q and not all(word in text for word in q.casefold().split()):
                continue
            values.append(self.public(record))
        values.sort(key=lambda m: datetime.fromisoformat(m['timestamp']), reverse=True)
        return values[offset:offset + limit]

    def save_reconstruction(self, key, workflow, ledger):
        records = copy.deepcopy(self.records)
        records[key].update(workflow=workflow, ledger=ledger, updated_at=stamp())
        self.repository.write('memories', records)
        self.records = records
