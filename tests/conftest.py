import pytest
import backend.main as main
from backend.repository import Repository
from backend.execution import ExecutionManager


@pytest.fixture(autouse=True)
def isolated_local_storage(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_OVERLAY', 'false')  # includes managers built with a fresh Settings()
    repository = Repository(tmp_path)
    monkeypatch.setattr(main.settings, 'nightshift_demo', False)  # tests start with an empty Night shift
    monkeypatch.setattr(main.settings, 'agent_overlay', False)  # tests must never pop up the on-screen pointer
    monkeypatch.setattr(main, 'repository', repository)
    monkeypatch.setattr(main, 'executions', ExecutionManager(main.settings, repository))
    monkeypatch.setattr(main.workflows, 'repository', repository)
    monkeypatch.setattr(main.workflows, 'records', {})
    monkeypatch.setattr(main.recordings, 'repository', repository)
    monkeypatch.setattr(main.recordings, 'records', {})
    monkeypatch.setattr(main.recordings, 'jobs', {})
    monkeypatch.setattr(main.recordings, 'workers', {})
    monkeypatch.setattr(main.scheduler, 'repository', repository)
    monkeypatch.setattr(main.scheduler, 'records', {})
    monkeypatch.setattr(main.scheduler, 'occurrences', {})
    monkeypatch.setattr(main.scheduler, 'executions', main.executions)
    monkeypatch.setattr(main.hotkeys, 'start', lambda: None)
    monkeypatch.setattr(main.discovery, 'repository', repository)
    monkeypatch.setattr(main.discovery, 'state', {'patterns': {}, 'occurrences': {}, 'cursor': None,
        'scan': {'status': 'idle'}, 'last_attempt': None})
    monkeypatch.setattr(main.discovery, 'closing', False)
    monkeypatch.setattr(main.discovery, 'job', None)
    monkeypatch.setattr(main.settings, 'discovery_enabled', False)
    monkeypatch.setattr(main.nightshift, 'repository', repository)
    monkeypatch.setattr(main.nightshift, 'executions', main.executions)
    monkeypatch.setattr(main.nightshift, 'workflows', main.workflows)
    monkeypatch.setattr(main.nightshift, 'state', {'settings': main.nightshift.state['settings'] | {'enabled': False}, 'proposals': {},
        'suppressed': {}, 'analysis': None, 'unfinished_seen': None, 'unfinished_at': None})
    monkeypatch.setattr(main.nightshift, 'note', None)
    monkeypatch.setattr(main.memory_sync, 'repository', repository)
    monkeypatch.setattr(main.memory_sync.index, 'repository', repository)
    monkeypatch.setattr(main.memory_sync.index, 'records', {})
    monkeypatch.setattr(main.memory_sync, 'state', {'last_successful_sync': None, 'last_scan_id': None})
    main.tasks.clear()
    yield
    main.tasks.clear()
