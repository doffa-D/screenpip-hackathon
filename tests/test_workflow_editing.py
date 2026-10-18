import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import backend.main as main
from backend.config import Settings
from backend.execution import ExecutionManager
from backend.models import ExecutionRequest, WorkflowStep
from backend.repository import Repository
from backend.workflow_store import WorkflowDefinition, WorkflowStore, UpdateWorkflow, require_definition_approval
from scripts.seed_demo_data import seed


def test_edit_preserves_history_and_requires_approval(tmp_path):
    repo = Repository(tmp_path)
    seed(repo)
    store = WorkflowStore(repo)
    original = store.get('demo:workflow:notepad')
    store.approve(original.id, 1)
    edited = store.update(original.id, UpdateWorkflow(expected_revision=1,
        definition=WorkflowDefinition(goal='Write a new greeting', steps=['Inspect the editor', 'Write good morning']),
        run_defaults=ExecutionRequest(values={'resulting_text': 'good morning'})))
    assert edited.id == original.id and edited.revision == 2
    assert edited.reconstruction == original.reconstruction
    assert edited.task == original.task and edited.ledger == original.ledger
    assert edited.approved_revision is None and edited.approved_at is None
    assert edited.execution_plan().steps[1].description == 'Write good morning'
    assert edited.execution_plan().steps[1].evidence == []
    assert edited.execution_plan().steps[1].source == 'user'
    assert store.get(original.id).revisions[-1]['definition'] is None
    restored = WorkflowStore(repo).get(original.id)
    assert restored.definition == edited.definition
    # Even real history now requires approval of the explicitly edited plan.
    restored.origin = 'real'
    with pytest.raises(ValueError, match='approve'):
        require_definition_approval(restored, restored.run_defaults)
    approved = store.approve(edited.id, 2)
    require_definition_approval(approved, approved.run_defaults)
    with pytest.raises(ValueError, match='exact values'):
        require_definition_approval(approved, ExecutionRequest(instructions='Changed'))
    # Reconstruction produced by the memory agent must still cite real evidence.
    with pytest.raises(ValidationError):
        WorkflowStep(description='Made up history', evidence=[])


def test_api_definition_validation_and_stale_revision():
    seed(main.repository)
    main.workflows.records = WorkflowStore(main.repository).records
    wid = 'demo:workflow:notepad'
    with TestClient(main.app) as client:
        before = client.get(f'/workflows/{wid}').json()
        for definition in [dict(goal=' ', steps=['A']), dict(goal='Goal', steps=[]),
                           dict(goal='Goal', steps=[' ']), dict(goal='Goal', steps=['x' * 4001])]:
            assert client.patch(f'/workflows/{wid}', json={'expected_revision': 1, 'definition': definition}).status_code == 422
        saved = client.patch(f'/workflows/{wid}', json={'expected_revision': 1,
            'definition': {'goal': 'New goal', 'steps': ['Second', 'First']},
            'user_notes': 'Edited by user'}).json()
        assert saved['reconstruction'] == before['reconstruction']
        assert saved['definition']['steps'] == ['Second', 'First']
        assert client.patch(f'/workflows/{wid}', json={'expected_revision': 1, 'title': 'Stale'}).status_code == 409
        assert client.get(f'/workflows/{wid}').json()['definition'] == saved['definition']


def test_execution_receives_approved_user_plan(tmp_path, monkeypatch):
    repo = Repository(tmp_path)
    seed(repo)
    store = WorkflowStore(repo)
    original = store.get('demo:workflow:notepad')
    edited = store.update(original.id, UpdateWorkflow(expected_revision=1,
        definition=WorkflowDefinition(goal='User goal', steps=['Only the edited step'])))
    approved = store.approve(edited.id, 2)
    manager = ExecutionManager(Settings(data_dir=str(tmp_path)), repo)
    seen = []

    async def capture(run, plan, request):
        seen.append(plan)
        run['status'] = 'completed'
    monkeypatch.setattr(manager, '_run', capture)

    async def scenario():
        # This is the same shared start() used by manual and scheduled dispatch.
        run = manager.start(approved.task, approved.reconstruction, approved.run_defaults, saved=approved)
        await manager.workers[run['id']]
        assert seen[0].goal == 'User goal'
        assert [step.description for step in seen[0].steps] == ['Only the edited step']
        assert run['workflow_snapshot']['definition']['steps'] == ['Only the edited step']
        assert run['workflow_snapshot']['reconstruction'] == original.reconstruction.model_dump(mode='json')
    asyncio.run(scenario())
