import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from backend.repository import Repository
from backend.recordings import RecordingService
from backend.scheduler import ScheduleInput, next_occurrence, Scheduler
import backend.main as main


def rule(**changes):
    return ScheduleInput.model_validate({'workflow_id':'w', 'frequency':'daily',
        'local_date':'2026-03-28', 'local_time':'02:30', 'timezone':'Europe/Paris', **changes})


def test_dst_skips_nonexistent_time_and_uses_first_fold():
    before = datetime(2026,3,28,23,tzinfo=timezone.utc)
    assert next_occurrence(rule(), before) == '2026-03-30T00:30:00+00:00'
    assert next_occurrence(rule(local_date='2026-10-24'), datetime(2026,10,24,23,tzinfo=timezone.utc)) == '2026-10-25T00:30:00+00:00'


def test_month_end_and_once():
    assert next_occurrence(rule(frequency='monthly', local_date='2026-01-31'), datetime(2026,2,1,tzinfo=timezone.utc)) == '2026-02-28T01:30:00+00:00'
    assert next_occurrence(rule(frequency='once'), datetime(2026,4,1,tzinfo=timezone.utc)) is None
    assert next_occurrence(rule(frequency='weekly', local_date='2026-10-16', local_time='10:00'),
                           datetime(2026,10,17,tzinfo=timezone.utc)) == '2026-10-23T08:00:00+00:00'


def test_recording_api_persists_markers_and_exact_stop_bounds(monkeypatch):
    captured = []
    monkeypatch.setattr(main.recordings, 'health_check', None)
    async def investigate(request, output_type):
        captured.append(request)
        raise ValueError('No source in the test interval')
    monkeypatch.setattr(main.recordings, 'investigate', investigate)
    with TestClient(main.app) as client:
        record = client.post('/recordings/start', json={'title':'Bounded segment'}).json()
        key = record['id']
        marked = client.post(f'/recordings/{key}/markers', json={'label':'Important change'}).json()
        assert marked['markers'][0]['label'] == 'Important change'
        stopped = client.post(f'/recordings/{key}/stop').json()
        assert stopped['started_at'] == record['started_at']
        assert stopped['ended_at']
        assert main.repository.read('recordings', {})[key]['markers'] == marked['markers']
        assert captured[0]['start_time'] == stopped['started_at']
        assert captured[0]['end_time'] == stopped['ended_at']
        assert captured[0]['markers'] == marked['markers']


def test_disabled_schedule_never_dispatches(tmp_path):
    class Executor:
        def start(self, *args, **kwargs):
            raise AssertionError('Disabled schedule must not dispatch')
    scheduler = Scheduler(Repository(tmp_path), None, Executor())
    scheduler.records['s'] = {**rule(enabled=False).model_dump(mode='json'),
        'id':'s', 'next_run_at':'2026-01-01T01:30:00+00:00'}
    asyncio.run(scheduler.tick())
    assert not scheduler.occurrences


def test_due_schedule_uses_real_run_store_and_persists_approval(tmp_path, monkeypatch):
    import backend.scheduler as module
    from backend.execution import ExecutionManager
    from backend.config import Settings
    from backend.models import TaskOccurrence, Reconstruction
    from backend.workflow_store import WorkflowStore, SaveWorkflow
    repo = Repository(tmp_path)
    workflows = WorkflowStore(repo)
    evidence = [{'call_id':'e1','quote':'test evidence','source_kind':'original_activity'}]
    task = TaskOccurrence(id='task', title='Chosen task', timestamp=datetime.now(timezone.utc), summary='Task', evidence=evidence)
    workflow = Reconstruction(goal='Observed action', historical_values={}, missing_values=[], steps=[], evidence=evidence)
    saved = workflows.create(task, workflow, {}, SaveWorkflow(task_id=task.id))
    executions = ExecutionManager(Settings(), repo)
    async def propose(run, workflow, request):
        run.update(status='awaiting_approval', pending_action={'id':'proposed','tool':'act','arguments':{'value':'proposed value'}})
        executions.persist()
    monkeypatch.setattr(executions, '_run', propose)
    monkeypatch.setattr(module, 'desktop_unlocked', lambda: True)
    scheduler = Scheduler(repo, workflows, executions)
    now = datetime.now(timezone.utc)
    scheduler.create(rule(workflow_id=saved.id, frequency='once', local_date=now.date().isoformat(),
        local_time=now.strftime('%H:%M'), enabled=False))
    record = next(iter(scheduler.records.values()))
    record.update(enabled=True, next_run_at=now.isoformat())
    async def scenario():
        await scheduler.tick()
        await asyncio.gather(*executions.workers.values())
    asyncio.run(scenario())
    run = next(iter(executions.runs.values()))
    assert run['status'] == 'awaiting_approval'
    assert run['triggered_by'] == 'schedule'
    assert run['workflow_id'] == saved.id
    assert repo.read('runs', {})[run['id']]['status'] == 'awaiting_approval'
    assert next(iter(scheduler.occurrences.values()))['run_id'] == run['id']


def test_recording_boundaries_and_failed_job(tmp_path):
    requests = []
    async def investigate(request, model):
        requests.append(request)
        raise RuntimeError('provider secret must not be persisted')
    async def exercise():
        service = RecordingService(Repository(tmp_path), investigate, lambda *a: None)
        record = service.start('Test')
        with pytest.raises(Exception):
            service.start('Second')
        start = record['started_at']
        record['ended_at'] = '2026-10-17T21:00:00+00:00'
        service.process(record)
        await asyncio.gather(*service.workers.values())
        assert requests[0]['start_time'] == start
        assert requests[0]['end_time'] == record['ended_at']
        assert requests[0]['strict_interval'] is True
        assert record['status'] == 'failed'
        assert 'secret' not in str(service.jobs)
        restored = RecordingService(Repository(tmp_path), investigate, lambda *a: None)
        assert restored.get(record['id'])['started_at'] == start
    asyncio.run(exercise())


def test_restart_marks_processing_interrupted(tmp_path):
    repo = Repository(tmp_path)
    repo.write('recordings', {'r': {'status':'processing'}})
    repo.write('jobs', {'j': {'status':'running'}})
    service = RecordingService(repo, None, None)
    assert service.records['r']['status'] == 'interrupted'
    assert service.jobs['j']['status'] == 'interrupted'


def test_missed_schedule_no_dispatch_or_duplicate(tmp_path):
    class Executor:
        def start(self, *args, **kwargs):
            raise AssertionError('Missed occurrence must not run')
    scheduler = Scheduler(Repository(tmp_path), None, Executor())
    scheduler.records['s'] = {**rule(frequency='once', local_date='2026-01-01').model_dump(mode='json'),
        'id':'s', 'next_run_at':'2026-01-01T01:30:00+00:00'}
    asyncio.run(scheduler.tick(startup=True))
    asyncio.run(scheduler.tick())
    assert len(scheduler.occurrences) == 1
    assert next(iter(scheduler.occurrences.values()))['status'] == 'missed'


def test_workflow_api_survives_expired_task_and_revision_conflict():
    from backend.models import TaskOccurrence
    import time
    evidence = [{'call_id':'e1','quote':'hello','source_kind':'original_activity'}]
    task = TaskOccurrence(id='t', title='Test task', timestamp='2026-10-17T10:00:00Z', summary='Test',evidence=evidence)
    main.tasks['t'] = {'task':task,'ledger':{},'expires':time.monotonic()+10,
        'workflow':{'goal':'Edit','historical_values':{},'steps':[],'missing_values':[],'evidence':evidence}}
    client = TestClient(main.app)
    response = client.post('/workflows',json={'task_id':'t'})
    assert response.status_code == 201
    key = response.json()['id']
    main.tasks.clear()
    assert client.get(f'/workflows/{key}').status_code == 200
    assert client.patch(f'/workflows/{key}',json={'expected_revision':1,'title':'Changed'}).status_code == 200
    assert client.patch(f'/workflows/{key}',json={'expected_revision':1,'title':'Stale'}).status_code == 409
    assert client.post('/workflows',json={'task_id':'t'}).status_code == 409
    assert client.delete(f'/workflows/{key}').status_code == 204
    assert client.get(f'/workflows/{key}').status_code == 404
