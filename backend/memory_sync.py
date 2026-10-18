"""One coordinator reuses semantic discovery for both memories and patterns."""
import asyncio
import re
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Query
from .memory_index import Memory, MemoryIndex
from .autonomous_discovery import ObservedOccurrence
from .models import Evidence


class MemorySync:
    def __init__(self, repository, discovery, settings):
        self.repository, self.discovery, self.settings = repository, discovery, settings
        self.index = MemoryIndex(repository)
        def validate_state(data):
            if not isinstance(data, dict):
                raise ValueError('Invalid sync state')
            for field in ('last_successful_sync', 'last_scanned_timestamp'):
                if data.get(field) and not datetime.fromisoformat(data[field]).tzinfo:
                    raise ValueError('Sync timestamps need a timezone')
        self.state = repository.read_recoverable('sync_state', {'last_successful_sync': None, 'last_scan_id': None}, validate_state)
        self.publication_error = None
        self._projected_state = None
        # Start with recent history so the first useful data does not wait for a week of backfill.
        discovery.initial_lookback_days = settings.sync_initial_lookback_days
        self.project()

    def project(self):
        if self._projected_state is not self.discovery.state:
            metadata = {oid: {'confidence': p['confidence'], 'tags': p['tags']}
                        for p in self.discovery.state['patterns'].values() for oid in p['occurrence_ids']}
            self.index.merge(self.discovery.state['occurrences'].values(), metadata)
            patterns = {key: self.discovery.public(p) for key, p in self.discovery.state['patterns'].items()}
            # Derived views are repairable from discovery.json after an interrupted publication.
            if not (self.repository.directory / 'patterns.json').exists() or self.repository.read_recoverable('patterns', {}) != patterns:
                self.repository.write('patterns', patterns)
            self._projected_state = self.discovery.state
        scan = self.discovery.state['scan']
        if scan.get('status') == 'completed' and scan.get('id') != self.state.get('last_scan_id'):
            self.state = {**self.state, 'last_successful_sync': scan['finished_at'],
                          'last_scan_id': scan.get('id')}
        updated = {**self.state, 'last_scanned_timestamp': self.discovery.state['cursor'],
                   'error': scan.get('error'), 'memory_count': len(self.index.records),
                   'pattern_count': len(self.discovery.listing())}
        if updated != self.repository.read_recoverable('sync_state', {}):
            self.repository.write('sync_state', updated)
        self.state = updated
        self.publication_error = None

    def refresh(self):
        try:
            self.project()
        except (OSError, ValueError):
            self.publication_error = 'The local memory index could not be updated. Existing data was preserved; check storage access and retry sync.'

    def status(self):
        scan = self.discovery.status()
        busy = scan['status'] in ('queued', 'running')
        status = ('syncing' if self.state.get('last_successful_sync') else 'preparing') if busy else (
            'error' if scan['status'] in ('failed', 'interrupted') else
            'ready' if self.state.get('last_successful_sync') else 'preparing')
        if self.publication_error:
            status = 'error'
        return {**self.state, 'status': status, 'scan_status': scan['status'],
            'error': self.publication_error or scan.get('error'), 'enabled': scan['enabled'], 'interval_minutes': scan['interval_minutes'],
            'start_time': scan.get('start_time'), 'end_time': scan.get('end_time'),
            'coverage_notes': scan.get('coverage_notes'), 'catching_up': scan.get('catching_up', False),
            'memory_count': len(self.index.records), 'pattern_count': len(self.discovery.listing()),
            'apps': sorted({app for m in self.index.records.values() for app in m['apps']}),
            'warnings': self.repository.recovery_warnings,
            'screenpipe_status': 'last_sync_succeeded' if self.state.get('last_successful_sync') and status != 'error' else 'unchecked',
            'screenpipe_checked_at': self.state.get('last_successful_sync'),
            'note': 'Verified tasks from inspected history. A successful sync can be partial; empty results do not mean Screenpipe has no recordings.'}

    def kick(self):
        self.discovery.kick()
        return self.status()

    async def loop(self):
        await asyncio.sleep(self.settings.sync_startup_delay_seconds)
        first = True
        while not self.discovery.closing:
            try:
                if self.settings.discovery_enabled:
                    last = self.discovery.state.get('last_attempt')
                    catching_up = self.discovery.state['scan'].get('catching_up') and self.discovery.state['scan']['status'] == 'completed'
                    if first or catching_up or not last or (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() >= self.settings.discovery_interval_minutes * 60:
                        self.discovery.kick()
                first = False
                # Also publish manually requested /discovery/run scans, using the same job.
                if self.discovery.job:
                    await asyncio.shield(self.discovery.job)
                    self.refresh()
            except (OSError, ValueError):
                self.publication_error = 'Local sync state could not be saved. Check storage access. The worker will retry.'
            await asyncio.sleep(2)

    def index_search(self, tasks, ledger):
        occurrences = []
        for task in tasks:
            originals = [e.quote for e in task.evidence if e.source_kind == 'original_activity']
            text = '\n'.join(originals)
            # App metadata must be present literally in the cited original excerpts.
            app = re.search(r'(?:App:|app_name["\s]*[:=])\s*"?([^"\n,]+)', text, re.I)
            app_name = app[1].strip() if app else None
            evidence = list(task.evidence)
            if not app_name:
                # The current MCP renders original rows as [Screen·a11y] App | Window.
                # Attach the literal metadata prefix from the SAME timestamped source row,
                # never infer an app from a task title or an unrelated result in the call.
                for e in task.evidence:
                    entry = ledger.get(e.call_id, {})
                    if e.source_kind != 'original_activity' or entry.get('tool') != 'search-content':
                        continue
                    for block in entry.get('text', '').split('\n---\n'):
                        header = re.search(r'\[Screen[^\]]*\]\s+([^|\n]+)\s*\|[^\n]*\n(\d{4}-\d\d-\d\dT[^\n]+)\nSource:[^\n]*', block)
                        if not header or e.quote not in block:
                            continue
                        try:
                            when = datetime.fromisoformat(header[2].strip().replace('Z','+00:00'))
                        except ValueError:
                            continue
                        if abs((when-task.timestamp).total_seconds()) >= 1:
                            continue
                        app_name = header[1].strip()
                        evidence.append(Evidence(call_id=e.call_id, quote=header[0], source_kind='original_activity'))
                        break
                    if app_name:
                        break
            if not app_name:
                continue
            try:
                candidate = ObservedOccurrence(title=task.title, timestamp=task.timestamp,
                    summary=task.summary, app=app_name, evidence=evidence)
                data = self.discovery.validated(candidate, ledger,
                    task.timestamp - timedelta(seconds=1), task.timestamp + timedelta(seconds=1))
                if data:
                    data['id'] = task.id
                    occurrences.append(data)
            except ValueError:
                continue  # Search remains usable; insufficient provenance is never promoted to durable memory.
        self.index.merge(occurrences)
        return tasks


def router(service):
    routes = APIRouter(tags=['Memories and sync'])

    @routes.get('/sync/status')
    async def status():
        service.refresh()
        return service.status()

    @routes.post('/sync/run', status_code=202)
    async def run():
        return service.kick()

    @routes.get('/memories', response_model=list[Memory])
    async def listing(q: str = Query('', max_length=4000), start_time: datetime | None = None,
                      end_time: datetime | None = None, app: str | None = None,
                      source_kind: str | None = None, tag: str | None = None, limit: int = Query(100, ge=1, le=500),
                      offset: int = Query(0, ge=0)):
        if any(t and not t.tzinfo for t in (start_time, end_time)):
            raise HTTPException(422, 'Memory filters need timezone-aware timestamps')
        if start_time and end_time and end_time <= start_time:
            raise HTTPException(422, 'End must be after start')
        service.refresh()
        return service.index.listing(q, start_time, end_time, app, source_kind, limit, offset, tag)

    @routes.get('/memories/{key}', response_model=Memory)
    async def read(key: str):
        try:
            return service.index.public(service.index.get(key))
        except KeyError:
            raise HTTPException(404, 'Memory not found') from None

    return routes
