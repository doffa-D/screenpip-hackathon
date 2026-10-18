import asyncio
import time
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from openai.types.chat import ChatCompletionMessage
import backend.main as main
import backend.execution as execution
from backend.repository import Repository
from backend.execution import ExecutionManager
from backend.models import ExecutionRequest, RunRecord, RunFeedback
from backend.workflow_store import WorkflowStore, UpdateWorkflow, require_definition_approval
from backend.run_reports import build_report, store_feedback
from scripts.seed_demo_data import seed
from tests.test_execution import Client, call


def seed_app():
    seed(main.repository)
    main.workflows.records = WorkflowStore(main.repository).records
    main.memory_sync.index.records = main.repository.read('memories', {})


def test_seeded_workflow_real_manager_report_and_feedback(monkeypatch):
    seed_app()
    model = Client([
        call('inspect_app', {'window_id':1,'window_title':'Fixture'}),
        call('act', {'window_id':1,'window_title':'Fixture','role':'AXWebArea','label':'Editor',
                     'action':'set_value','value':'reviewed value','reason':'Apply reviewed text'}),
        call('verify_text', {'window_id':1,'window_title':'Fixture','role':'AXWebArea','label':'Editor',
                             'property':'value','expected':'reviewed value'}),
        ChatCompletionMessage(role='assistant', content='{"outcome":"completed","summary":"Text verified"}')])
    monkeypatch.setattr(execution.Agent, 'create_client', lambda self:model)
    calls=[]
    async def desktop(name,args,timeout):
        calls.append(name)
        return {'verified':True,'actual':'reviewed value'} if name=='verify_text' else {'ok':True}
    monkeypatch.setattr(execution,'call_desktop',desktop)
    wid='demo:workflow:notepad'
    body={'values':{'resulting_text':'reviewed value'},'missing_values':{},'instructions':'Fixture only'}
    with TestClient(main.app) as client:
        assert client.post(f'/workflows/{wid}/execute',json=body).status_code==409
        assert client.post('/tasks/demo:memory:notepad/execute',json=body).status_code==409
        saved=client.patch(f'/workflows/{wid}',json={'expected_revision':1,'run_defaults':body}).json()
        approved=client.post(f'/workflows/{wid}/approve',json={'expected_revision':saved['revision']})
        assert approved.status_code==200
        assert approved.json()['approved_revision']==2
        assert client.post(f'/workflows/{wid}/execute',json={**body,'instructions':'Changed'}).status_code==409
        response=client.post(f'/workflows/{wid}/execute',json=body)
        assert response.status_code==202
        rid=response.json()['id']
        for _ in range(100):
            run=client.get(f'/runs/{rid}').json()
            if run['status']=='awaiting_approval': break
            time.sleep(.01)
        assert calls==['inspect_app']
        assert client.get(f'/runs/{rid}/report').status_code==409
        assert client.post(f'/runs/{rid}/feedback',json={'verdict':'looks_good'}).status_code==409
        assert client.post(f'/runs/{rid}/approval',json={'action_id':run['pending_action']['id'],'approve':True}).status_code==200
        for _ in range(100):
            run=client.get(f'/runs/{rid}').json()
            if run.get('report'): break
            time.sleep(.01)
        assert run['status']=='completed'
        assert run['origin']=='real' and run['source_kind']=='execution'
        assert run['workflow_id']==wid and run['workflow_revision']==2
        assert run['workflow_snapshot']['id']==wid
        assert run['workflow_snapshot']['approved_revision']==2
        report=client.get(f'/runs/{rid}/report').json()
        assert report['workflow_name']=='Edit Notepad text'
        assert report['values_used']['resulting_text']=='reviewed value'
        assert len(report['actions_attempted'])==len(report['actions_completed'])==1
        assert report['verification_results'][0]['result']['verified'] is True
        reviewed=client.post(f'/runs/{rid}/feedback',json={'verdict':'looks_good','notes':'Checked editor'}).json()
        assert reviewed['feedback']['notes']=='Checked editor'
        restored=ExecutionManager(main.settings,main.repository)
        assert restored.runs[rid]['report']==report
        assert restored.runs[rid]['feedback']==reviewed['feedback']
        assert client.get('/runs').status_code==200
        updated=client.patch(f'/workflows/{wid}',json={'expected_revision':2,'title':'Changed title'}).json()
        assert updated['approved_revision'] is None
        assert client.post(f'/workflows/{wid}/approve',json={'expected_revision':2}).status_code==409
        assert client.post(f'/workflows/{wid}/execute',json=body).status_code==409


def test_approval_persists_and_missing_inputs_block(tmp_path):
    repo=Repository(tmp_path);seed(repo);store=WorkflowStore(repo)
    saved=store.get('demo:workflow:notepad')
    store.approve(saved.id,1)
    restored=WorkflowStore(repo).get(saved.id)
    require_definition_approval(restored,restored.run_defaults)
    with pytest.raises(ValueError): require_definition_approval(restored,ExecutionRequest())
    saved.reconstruction.missing_values=['target']
    saved.approved_revision=None
    store.commit(saved)
    with pytest.raises(ValueError,match='missing'): store.approve(saved.id,1)


def test_failure_report_does_not_claim_applied_or_verified():
    run={'id':'r','title':'Send email','started_at':'2026-10-17T10:00:00Z',
         'finished_at':'2026-10-17T10:01:00Z','status':'failed','summary':'Timeout',
         'effective_values':{'recipient':'user@example.com'},'events':[
            {'id':'a','timestamp':'2026-10-17T10:00:01Z','kind':'tool','title':'Apply',
             'detail':{'tool_name':'act','tool_call_id':'c','action':'press_button','label':'Send'}},
            {'id':'b','timestamp':'2026-10-17T10:00:02Z','kind':'error','title':'Timeout','detail':{'error':'Timed out'}}]}
    report=build_report(run)
    assert len(report['actions_attempted'])==1
    assert report['actions_completed']==report['verification_results']==[]
    assert len(report['errors'])==1
    with pytest.raises(ValueError,match='Simulated'):build_report({**run,'origin':'demo'})


def test_feedback_rejects_simulation_and_failed_write_does_not_publish(tmp_path,monkeypatch):
    manager=SimpleNamespace(repository=Repository(tmp_path),runs={'r':{'status':'completed','origin':'demo'}})
    with pytest.raises(ValueError,match='Simulated'):store_feedback(manager,'r',RunFeedback(verdict='looks_good'))
    manager.runs['r']['origin']='real'
    def fail(*args):raise OSError('disk full')
    monkeypatch.setattr(manager.repository,'write',fail)
    with pytest.raises(OSError):store_feedback(manager,'r',RunFeedback(verdict='something_wrong'))
    assert 'feedback' not in manager.runs['r']
