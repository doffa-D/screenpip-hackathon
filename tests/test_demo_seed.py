from datetime import datetime
from zoneinfo import ZoneInfo
from backend.repository import Repository
from backend.memory_index import MemoryIndex, same_occurrence
from backend.workflow_store import WorkflowStore
from scripts.seed_demo_data import seed, BODY, STORES
from scripts.clear_demo_data import clear


def test_seed_replay_cleanup_preserves_real(tmp_path):
    repo = Repository(tmp_path)
    for name in ('schedules', 'demo_patterns'):
        repo.write(name, {'real': {'id': 'real', 'origin': 'real'}})
    now = datetime(2026, 10, 17, 12, tzinfo=ZoneInfo('Europe/Paris'))
    counts = seed(repo, now)
    assert counts == dict(memories=3, workflows=3, schedules=2, runs=0, demo_patterns=3)
    before = {name: repo.read(name, {}) for name in STORES}
    seed(repo, now)
    assert before == {name: repo.read(name, {}) for name in STORES}
    index = MemoryIndex(repo)
    assert len(index.listing(source='seeded_demo')) == 3
    assert not same_occurrence(index.get('demo:memory:gmail'), index.get('demo:memory:gmail'))
    workflow = WorkflowStore(repo).get('demo:workflow:gmail')
    assert workflow.run_defaults.values['message_body'] == BODY
    assert workflow.reconstruction.historical_values['recipient'].value == 'mzbakasta@gmail.com'
    assert all(e.source_kind == 'seeded_demo' for e in workflow.reconstruction.evidence)
    assert all(not s['enabled'] for k,s in before['schedules'].items() if k != 'real')
    assert all(r['pending_action'] is None and not any(e['kind']=='verified' for e in r['events']) for r in before['runs'].values())
    assert clear(repo)['memories'] == 3
    assert repo.read('schedules', {}) == {'real': {'id': 'real', 'origin': 'real'}}
    assert repo.read('demo_patterns', {}) == {'real': {'id': 'real', 'origin': 'real'}}
    assert clear(repo)['memories'] == 0
    assert seed(repo, now) == counts


def test_seed_collision_does_not_write(tmp_path):
    repo = Repository(tmp_path)
    repo.write('schedules', {'demo:schedule:gmail': {'origin':'real'}})
    import pytest
    with pytest.raises(ValueError, match='non-demo'):
        seed(repo)
    assert not (tmp_path / 'memories.json').exists()


def test_reseed_retires_simulated_runs_preserving_real_execution(tmp_path):
    from backend.models import RunRecord, ExecutionRequest
    repo = Repository(tmp_path)
    real = RunRecord(id='real-run',task_id='demo:memory:notepad',title='Real execution',status='completed',
        started_at='2026-10-17T10:00:00Z',finished_at='2026-10-17T10:01:00Z',elapsed_seconds=60,
        summary='Actual desktop run',pending_action=None,events=[],request=ExecutionRequest()).model_dump(mode='json')
    fake = {**real,'id':'demo:run:notepad','origin':'demo','source_kind':'seeded_demo'}
    repo.write('runs',{'real-run':real,'demo:run:notepad':fake})
    assert seed(repo)['runs'] == 0
    assert repo.read('runs',{}) == {'real-run':real}


def test_demo_review_api_does_not_call_history(monkeypatch):
    import backend.main as main
    from fastapi.testclient import TestClient
    seed(main.repository)
    main.memory_sync.index.records = main.repository.read('memories', {})
    main.workflows.records = WorkflowStore(main.repository).records
    async def forbidden(*args, **kwargs):
        raise AssertionError('Demo reconstruction must not consult Screenpipe')
    monkeypatch.setattr(main, 'investigate', forbidden)
    client = TestClient(main.app)
    assert len(client.get('/memories?source_kind=seeded_demo').json()) == 3
    response = client.post('/tasks/demo:memory:gmail/reconstruct')
    assert response.status_code == 200
    assert response.json()['historical_values']['message_body']['value'] == BODY
    saved = client.post('/workflows', json={'task_id':'demo:memory:gmail'})
    assert saved.status_code == 201
    assert saved.json()['origin'] == 'demo'
    assert saved.json()['source_kind'] == 'seeded_demo'
    assert client.get('/discovery/patterns').json() == []
    assert len(client.get('/demo/patterns').json()) == 3
