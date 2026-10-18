import asyncio
import copy
from datetime import datetime, timedelta, timezone
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.config import Settings
from backend.repository import Repository
from backend.workflow_store import WorkflowStore
from backend.autonomous_discovery import DiscoveryService, ScanResult
from backend.memory_sync import MemorySync, router
from backend.models import TaskOccurrence, Reconstruction

@pytest.fixture
def anyio_backend():
    return 'asyncio'


BASE = datetime(2026, 10, 16, tzinfo=timezone.utc)


def batch(frames=(1, 2), existing=None, goal='Follow up', app='Mail'):
    members, ledger = [], {}
    for frame in frames:
        when = (BASE + timedelta(minutes=frame)).isoformat()
        quote = f'{when}\nApp: {app}\nSource: screenpipe://frame/{frame}\nSent follow-up {frame}'
        evidence = [{'call_id': f'e{frame}', 'quote': quote, 'source_kind': 'original_activity'}]
        members.append(dict(title=goal, timestamp=when, summary=goal, app=app, evidence=evidence))
        ledger[f'e{frame}'] = {'tool': 'search-content', 'text': quote, 'arguments': {}}
    return ScanResult.model_validate({'groups': [dict(existing_pattern_id=existing, title=goal, summary=goal,
        goal=goal, action_structure=['Compose', 'Send'], confidence=.93, explanation='Same observed goal and steps',
        tags=['email'], occurrences=members)], 'coverage_notes': 'Sample of original activity.'}), ledger


def service(tmp_path, investigate=None, **config):
    repo = Repository(tmp_path)
    settings = Settings(discovery_enabled=False, sync_startup_delay_seconds=0, **config)
    discovery = DiscoveryService(repo, investigate, settings, WorkflowStore(repo))
    return MemorySync(repo, discovery, settings)


def ingest(s, frames=(1, 2), **kwargs):
    out, ledger = batch(frames, **kwargs)
    s.discovery.commit(s.discovery.merge(out, ledger, BASE, BASE + timedelta(days=1)))
    s.project()
    return next(iter(s.discovery.state['patterns']))


def test_singletons_appear_as_memories_without_suggested_workflows(tmp_path):
    s = service(tmp_path)
    ingest(s, (1,))
    assert len(s.index.listing()) == 1
    assert not s.discovery.listing()
    assert s.index.listing()[0]['apps'] == ['Mail']
    assert 'ledger' not in s.index.listing()[0]
    assert not s.discovery.workflows.list()


def test_replay_restart_and_new_occurrences_preserve_ids_and_created_at(tmp_path):
    s = service(tmp_path)
    pattern = ingest(s)
    before = copy.deepcopy(s.index.records)
    ingest(s, existing=pattern)
    assert s.index.records == before
    s = service(tmp_path)
    ingest(s, (2, 3), existing=pattern)
    assert len(s.index.records) == 3
    for key, old in before.items():
        assert s.index.records[key] == old
    assert s.discovery.listing()[0]['occurrence_count'] == 3


def test_different_goals_in_same_app_remain_separate_and_decisions_survive(tmp_path):
    s = service(tmp_path)
    key = ingest(s)
    s.discovery.decision(key, 'dismissed')
    ingest(s, (3, 4), goal='Send invoice')
    restored = service(tmp_path)
    assert len(restored.index.records) == 4
    assert restored.discovery.get(key)['status'] == 'dismissed'
    assert len(restored.discovery.listing()) == 1


@pytest.mark.anyio
async def test_startup_worker_indexes_without_manual_search(tmp_path, monkeypatch):
    import backend.autonomous_discovery as module
    monkeypatch.setattr(module, 'utcnow', lambda: BASE + timedelta(hours=2))
    calls = []
    async def investigate(request, output_type):
        calls.append(request)
        return batch()
    s = service(tmp_path, investigate)
    s.settings.discovery_enabled = True
    worker = asyncio.create_task(s.loop())
    for _ in range(30):
        await asyncio.sleep(.01)
        if len(s.index.records) == 2:
            break
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)
    assert len(s.index.records) == 2
    assert len(calls) == 1
    assert s.status()['status'] == 'ready'
    assert s.status()['last_successful_sync']
    assert s.repository.read('sync_state', {})['memory_count'] == 2


@pytest.mark.anyio
async def test_incremental_scan_only_new_window_with_small_overlap_and_failure_retry(tmp_path, monkeypatch):
    import backend.autonomous_discovery as module
    now = BASE + timedelta(hours=2)
    monkeypatch.setattr(module, 'utcnow', lambda: now)
    requests = []
    fail = False
    async def investigate(request, output_type):
        requests.append(request)
        if fail:
            raise ValueError('Test unavailable')
        return batch() if len(requests)==1 else (ScanResult(groups=[], coverage_notes='New interval inspected'), {})
    s = service(tmp_path, investigate)
    s.kick()
    await s.discovery.job
    s.project()
    cursor = s.discovery.state['cursor']
    now += timedelta(minutes=30)
    fail = True
    s.kick()
    await s.discovery.job
    s.project()
    assert s.discovery.state['cursor'] == cursor
    assert s.status()['status'] == 'error'
    assert datetime.fromisoformat(requests[-1]['start_time']) == datetime.fromisoformat(cursor) - timedelta(minutes=5)
    fail = False
    s.kick()
    await s.discovery.job
    s.project()
    assert requests[-1]['start_time'] == requests[-2]['start_time']
    assert len(s.index.records) == 2
    assert s.status()['status'] == 'ready'


def test_corrupt_projection_retained_and_rebuilt_from_original_discovery(tmp_path):
    s = service(tmp_path)
    ingest(s)
    (tmp_path / 'memories.json').write_text('{broken', encoding='utf-8')
    restored = service(tmp_path)
    assert len(restored.index.records) == 2
    assert len(list(tmp_path.glob('memories.corrupt-*.json'))) == 1
    assert restored.status()['warnings']


def test_memory_api_filters_and_private_ledger(tmp_path):
    s = service(tmp_path)
    ingest(s)
    app = FastAPI()
    app.include_router(router(s))
    client = TestClient(app)
    rows = client.get('/memories').json()
    assert rows[0]['timestamp'] > rows[1]['timestamp']
    assert client.get('/memories?q=missing').json() == []
    assert client.get('/memories?app=Mail&tag=email').json() == rows
    assert client.get('/memories?app=Other').json() == []
    assert client.get('/memories?source_kind=discussion').json() == []
    assert client.get('/memories?start_time=2026-10-17T00:00:00Z').json() == []
    assert client.get('/memories?start_time=2026-10-17T00:00:00').status_code == 422
    assert 'ledger' not in client.get('/memories/' + rows[0]['id']).json()
    assert client.get('/memories/absent').status_code == 404


@pytest.mark.anyio
async def test_manual_sync_deduplicates_concurrent_requests(tmp_path):
    ready = asyncio.Event()
    async def investigate(request, output_type):
        await ready.wait()
        return ScanResult(groups=[], coverage_notes='Empty sample'), {}
    s = service(tmp_path, investigate)
    first = s.kick()
    job = s.discovery.job
    s.kick()
    assert s.discovery.job is job
    assert first['scan_status'] == 'queued'
    ready.set()
    await job


def test_dynamic_search_merges_only_original_anchored_occurrences(tmp_path):
    s = service(tmp_path)
    out, ledger = batch()
    tasks = [TaskOccurrence(id=str(i), **{k: getattr(m, k) for k in ('title','timestamp','summary','evidence')})
             for i, m in enumerate(out.groups[0].occurrences)]
    s.index_search(tasks, ledger)
    s.index_search(tasks, ledger)
    assert len(s.index.records) == 2
    out, ledger = batch((3,), app='ChatGPT')
    m = out.groups[0].occurrences[0]
    s.index_search([TaskOccurrence(id='discussion', **{k: getattr(m,k) for k in ('title','timestamp','summary','evidence')})], ledger)
    assert len(s.index.records) == 2


def test_search_uses_current_mcp_row_metadata_from_same_timestamp(tmp_path):
    s = service(tmp_path)
    when = (BASE + timedelta(minutes=3)).isoformat()
    raw = f'[Screen·a11y] Editor.exe | Note.txt\n{when}\nSource: frame_id=44; screenpipe://frame/44\nChanged text'
    task = TaskOccurrence(id='searched', title='Edit note', timestamp=when, summary='Changed note text',
        evidence=[{'call_id':'e1','quote':'Changed text','source_kind':'original_activity'}])
    ledger = {'e1':{'tool':'search-content','text':raw,'arguments':{}}}
    s.index_search([task], ledger)
    assert s.index.listing()[0]['apps'] == ['Editor.exe']
    assert len(s.index.listing()[0]['evidence']) == 2
    task.timestamp += timedelta(hours=1)
    s.index_search([task], ledger)
    assert len(s.index.records) == 1


def test_same_semantic_identity_reuses_pattern_when_model_omits_existing_id(tmp_path):
    s = service(tmp_path)
    key = ingest(s)
    s.discovery.decision(key, 'dismissed')
    ingest(s, (3, 4))
    assert len(s.discovery.state['patterns']) == 1
    assert s.discovery.get(key)['status'] == 'dismissed'
    assert len(s.index.records) == 4


def test_model_cannot_lump_distant_or_different_document_edits():
    from backend.autonomous_discovery import ObservedOccurrence
    data = batch((1,))[0].groups[0].occurrences[0].model_dump()
    def evidence(file, when, frame):
        return {'call_id':'e1','quote':f'[Screen·a11y] Editor | {file}.txt - Editor\n{when}\nSource: frame_id={frame}',
                'source_kind':'original_activity'}
    data['evidence'] = [evidence('first',BASE.isoformat(),1), evidence('second',(BASE+timedelta(minutes=1)).isoformat(),2)]
    with pytest.raises(ValueError, match='Different document'):
        ObservedOccurrence.model_validate(data)
    data['evidence'] = [evidence('first',BASE.isoformat(),1), evidence('first',(BASE+timedelta(hours=1)).isoformat(),2)]
    with pytest.raises(ValueError, match='distant episodes'):
        ObservedOccurrence.model_validate(data)


def test_schema_damaged_index_is_preserved_and_recovered(tmp_path):
    s = service(tmp_path)
    ingest(s)
    (tmp_path / 'memories.json').write_text('[]', encoding='utf-8')
    restored = service(tmp_path)
    assert len(restored.index.records) == 2
    assert list(tmp_path.glob('memories.corrupt-*.json'))


def test_schema_damaged_sync_state_is_preserved_without_losing_memories(tmp_path):
    s = service(tmp_path)
    ingest(s)
    (tmp_path / 'sync_state.json').write_text('[]', encoding='utf-8')
    restored = service(tmp_path)
    assert len(restored.index.records) == 2
    assert list(tmp_path.glob('sync_state.corrupt-*.json'))
    assert restored.status()['warnings']


def test_settings_runtime_counts_are_real():
    import backend.main as main
    result = TestClient(main.app).get('/system/activity').json()
    assert result['active_recordings'] == len([r for r in main.recordings.records.values() if r['status']=='recording'])
    assert result['enabled_schedules'] == len([r for r in main.scheduler.records.values() if r['enabled']])
    assert result['saved_workflows'] == len(main.workflows.list())


def test_indexed_memory_reconstructs_after_cache_expiry_and_restart(tmp_path, monkeypatch):
    import backend.main as main
    s = main.memory_sync
    ingest(s)
    memory = s.index.listing()[0]
    original = s.index.records[memory['id']]
    evidence = memory['evidence']
    async def investigate(request, output_type, ledger=None):
        assert request['selected_task']['id'] == memory['id']
        assert ledger == original['ledger']
        return Reconstruction(goal='Follow up', historical_values={}, missing_values=[],
            steps=[{'description':'Send follow-up', 'evidence':evidence}], evidence=evidence), ledger
    monkeypatch.setattr(main, 'investigate', investigate)
    main.tasks.clear()
    client = TestClient(main.app)
    assert client.post(f"/tasks/{memory['id']}/reconstruct").status_code == 200
    main.tasks.clear()
    assert client.get(f"/tasks/{memory['id']}/workflow").json()['goal'] == 'Follow up'
    assert client.post('/workflows', json={'task_id':memory['id']}).status_code == 201
    assert len(main.workflows.list()) == 1
