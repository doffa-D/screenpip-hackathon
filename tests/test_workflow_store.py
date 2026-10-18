import pytest
from backend.repository import Repository
from backend.models import TaskOccurrence, Reconstruction
from backend.workflow_store import WorkflowStore, SaveWorkflow, UpdateWorkflow, RevisionConflict


def test_durable_snapshot_revisions_and_archive(tmp_path):
    repo = Repository(tmp_path)
    evidence = [{'call_id': 'e1', 'quote': 'hello world', 'source_kind': 'original_activity'}]
    task = TaskOccurrence(id='expiring-task', title='Notepad edit', timestamp='2026-10-17T20:03:00Z',
                          summary='Edited text', evidence=evidence)
    workflow = Reconstruction(goal='Edit text', historical_values={}, steps=[], missing_values=[], evidence=evidence)
    store = WorkflowStore(repo)
    saved = store.create(task, workflow, {'e1': {'text': 'hello world'}}, SaveWorkflow(task_id=task.id))
    restored = WorkflowStore(repo)
    updated = restored.update(saved.id, UpdateWorkflow(expected_revision=1, title='My reusable edit'))
    assert updated.revision == 2
    assert updated.revisions[0]['title'] == 'Notepad edit'
    assert updated.reconstruction == workflow
    assert updated.task.title == 'Notepad edit'
    with pytest.raises(RevisionConflict):
        restored.update(saved.id, UpdateWorkflow(expected_revision=1, title='Stale edit'))
    assert WorkflowStore(repo).get(saved.id).title == 'My reusable edit'
    restored.archive(saved.id)
    assert WorkflowStore(repo).list() == []
    with pytest.raises(KeyError):
        restored.get(saved.id)


def test_corrupt_storage_is_not_replaced(tmp_path):
    (tmp_path / 'workflows.json').write_text('{broken', encoding='utf8')
    with pytest.raises(ValueError):
        WorkflowStore(Repository(tmp_path))


def test_failed_write_keeps_previous_revision(tmp_path, monkeypatch):
    store = WorkflowStore(Repository(tmp_path))
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(store.repository, 'write', fail)
    with pytest.raises(OSError):
        store.commit(type('Record', (), {'id': 'x', 'model_dump': lambda *a, **k: {}})())
    assert store.records == {}


def test_schedule_edits_keep_pinned_revision(tmp_path):
    from backend.scheduler import Scheduler, ScheduleInput
    repo = Repository(tmp_path)
    store = WorkflowStore(repo)
    evidence = [{'call_id':'e1','quote':'hello','source_kind':'original_activity'}]
    task = TaskOccurrence(id='t',title='Original',timestamp='2026-10-17T10:00:00Z',summary='Task',evidence=evidence)
    workflow = Reconstruction(goal='Edit',historical_values={},steps=[],missing_values=[],evidence=evidence)
    saved = store.create(task,workflow,{},SaveWorkflow(task_id='t'))
    scheduler = Scheduler(repo,store,None)
    rule = ScheduleInput(workflow_id=saved.id,frequency='daily',local_date='2099-01-01',local_time='10:00')
    schedule = scheduler.create(rule)
    store.update(saved.id,UpdateWorkflow(expected_revision=1,title='Edited'))
    scheduler.create(rule,schedule['id'])
    assert scheduler.records[schedule['id']]['workflow_revision'] == 1
