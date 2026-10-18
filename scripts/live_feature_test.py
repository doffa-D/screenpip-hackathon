"""Replay the explicitly user-selected hello-world occurrence in a NEW test file.

Uses actual Azure and Zavora MCP through the real API. Only a set_value to hello world
in this script's unique fixture is automatically approved; other changes stop.
Historical source files come from the earlier real Screenpipe test.
"""
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
import backend.main as backend
from backend.models import TaskOccurrence
from backend.repository import Repository
from backend.execution import ExecutionManager


def main():
    out = Path('artifacts/real-features/live').resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = Path('artifacts/notepad-occurrences')
    selected_id = 'edba6f9c-ca66-43ce-8181-ab5806842c50'
    session = json.loads((source / 'session.json').read_text(encoding='utf-8'))[selected_id]
    workflow = json.loads((source / 'workflow.json').read_text(encoding='utf-8'))['response']
    fixture = out / f'replay-{uuid4().hex[:12]}.txt'
    fixture.write_text('hello wor', encoding='utf-8')
    subprocess.Popen(['notepad.exe', str(fixture)])
    import asyncio
    from backend.desktop import call_desktop
    target = None
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        windows = asyncio.run(call_desktop('list_apps', {}, 30))['apps']
        matches = [w for w in windows if fixture.name in (w.get('title') or '')]
        if len(matches) == 1:
            target = matches[0]
            break
        time.sleep(.3)
    if target is None:
        raise RuntimeError('Unique test window not found')
    backend.repository = Repository(out / 'state')
    backend.executions = ExecutionManager(backend.settings, backend.repository)
    from backend.workflow_store import WorkflowStore
    backend.workflows = WorkflowStore(backend.repository)
    backend.recordings.repository = backend.repository
    backend.recordings.records = {}
    backend.recordings.jobs = {}
    backend.recordings.workers = {}
    backend.scheduler.repository = backend.repository
    backend.scheduler.records = {}
    backend.scheduler.occurrences = {}
    backend.scheduler.executions = backend.executions
    backend.scheduler.workflows = backend.workflows
    backend.hotkeys.start = lambda: None
    backend.tasks.clear()
    backend.tasks[selected_id] = {'task': TaskOccurrence.model_validate(session['task']),
        'ledger': session['ledger'], 'workflow': workflow, 'expires': time.monotonic() + 3600}
    started = time.perf_counter()
    with TestClient(backend.app) as client:
        segment = client.post('/recordings/start', json={'title': 'Isolated Notepad edit acceptance test'}).json()
        saved = client.post('/workflows', json={'task_id': selected_id})
        saved.raise_for_status()
        workflow_id = saved.json()['id']
        backend.tasks.clear()  # Prove a saved workflow runs independently of expired search tasks.
        response = client.post(f'/workflows/{workflow_id}/execute', json={
            'missing_values': {name: 'Exact keystrokes are unnecessary. Reproduce the observed final text hello world.'
                               for name in workflow['missing_values']},
            'instructions': f'Use ONLY the new Notepad test document window containing {fixture.name}, window ID {target['windowId']}. '
                'Set its editor text to hello world and verify the exact value. No saving or other changes. '
                'The historical text before/after describes an edit, not multiple content fields to enter.'})
        if response.status_code != 202:
            raise RuntimeError(response.text)
        run_id = response.json()['id']
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            run = client.get(f'/runs/{run_id}').json()
            if run['status'] == 'awaiting_approval':
                action = run['pending_action']
                args = action['arguments']
                allowed = (args.get('window_id') == target['windowId'] and fixture.name in args.get('window_title', '')
                           and args.get('action') == 'set_value' and args.get('value') == 'hello world')
                response = client.post(f'/runs/{run_id}/approval', json={
                    'action_id': action['id'], 'approve': allowed})
                response.raise_for_status()
                print('Approved fixture-only edit' if allowed else 'Declined non-fixture action', flush=True)
            if run['status'] not in ('running', 'awaiting_approval', 'stopping'):
                break
            time.sleep(.25)
        else:
            run = client.post(f'/runs/{run_id}/stop', json={}).json()
        (out / 'run.json').write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': run['status'], 'summary': run['summary'],
                          'seconds': round(time.perf_counter() - started, 3),
                          'events': len(run['events']), 'report': str(out / 'run.json')}, indent=2))
        if run['status'] != 'completed':
            raise SystemExit(1)
        windows = asyncio.run(call_desktop('list_apps', {}, 30))['apps']
        current = next(w for w in windows if w['windowId'] == target['windowId'])
        verified = asyncio.run(call_desktop('verify_text', {
            'window_id': current['windowId'], 'window_title': current['title'],
            'role': 'AXWebArea', 'label': 'Text editor', 'property': 'value', 'expected': 'hello world'}, 30))
        if not verified['verified']:
            raise RuntimeError('Separate final MCP session verification failed')
        execution_seconds = round(time.perf_counter() - started, 3)
        client.post(f"/recordings/{segment['id']}/markers", json={'label':'Edit independently verified'}).raise_for_status()
        stopped = client.post(f"/recordings/{segment['id']}/stop", json={})
        stopped.raise_for_status()
        processing_started = time.perf_counter()
        while time.perf_counter() - processing_started < 260:
            segment = client.get(f"/recordings/{segment['id']}").json()
            if segment['status'] != 'processing':
                break
            time.sleep(.5)
        result = {'execution_seconds': execution_seconds, 'record_processing_seconds':round(time.perf_counter()-processing_started,3),
                  'recording_status':segment['status'],'saved_workflow_id':workflow_id,'run_id':run_id}
        (out/'recording.json').write_text(json.dumps(segment,ensure_ascii=False,indent=2),encoding='utf8')
        (out/'timings.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        print(json.dumps(result,indent=2),flush=True)
        if segment['status'] != 'ready':
            print(client.get(f"/jobs/{segment['job_id']}").json())
            raise SystemExit(2)
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        scheduled_fixture = out / f'scheduled-{uuid4().hex[:12]}.txt'
        scheduled_fixture.write_text('hello wor', encoding='utf8')
        subprocess.Popen(['notepad.exe', str(scheduled_fixture)])
        time.sleep(2)
        windows = asyncio.run(call_desktop('list_apps', {}, 30))['apps']
        target = next(w for w in windows if scheduled_fixture.name in w.get('title', ''))
        defaults = {'values': {}, 'missing_values': {name:'Reproduce the final text hello world; exact keystrokes are unnecessary.' for name in workflow['missing_values']},
                    'instructions': f'Use ONLY the new Notepad test document window containing {scheduled_fixture.name}. Set its editor text to hello world and verify. Do not save or make other changes.'}
        client.patch(f'/workflows/{workflow_id}', json={'expected_revision':1,'run_defaults':defaults}).raise_for_status()
        due = datetime.now(ZoneInfo('Europe/Paris')) + timedelta(seconds=8)
        schedule = client.post('/schedules', json={'workflow_id':workflow_id,'frequency':'once',
            'local_date':due.date().isoformat(),'local_time':due.time().replace(microsecond=0).isoformat(),'timezone':'Europe/Paris'})
        schedule.raise_for_status()
        schedule_id = schedule.json()['id']
        tick = time.perf_counter()
        observed_approval = False
        try:
            deadline = time.monotonic()+180
            while time.monotonic()<deadline:
                occurrences = client.get(f'/schedules/{schedule_id}/occurrences').json()
                if occurrences and occurrences[0]['run_id']:
                    scheduled_run = client.get('/runs/'+occurrences[0]['run_id']).json()
                    if scheduled_run['status']=='awaiting_approval':
                        action=scheduled_run['pending_action']; args=action['arguments']
                        allowed=args.get('window_id')==target['windowId'] and scheduled_fixture.name in args.get('window_title','') and args.get('action')=='set_value' and args.get('value')=='hello world'
                        client.post('/runs/'+scheduled_run['id']+'/approval',json={'action_id':action['id'],'approve':allowed}).raise_for_status()
                        observed_approval = observed_approval or allowed
                    if scheduled_run['status'] not in ('running','awaiting_approval','stopping'):
                        break
                time.sleep(.25)
            else:
                raise RuntimeError('Scheduled test timed out')
            result.update(schedule_seconds=round(time.perf_counter()-tick,3), scheduled_status=scheduled_run['status'],
                          scheduled_approval=observed_approval, occurrence_count=len(occurrences))
            (out/'scheduled-run.json').write_text(json.dumps(scheduled_run,ensure_ascii=False,indent=2),encoding='utf8')
            (out/'timings.json').write_text(json.dumps(result,indent=2),encoding='utf8')
            print(json.dumps(result,indent=2),flush=True)
            assert scheduled_run['status']=='completed' and observed_approval and len(occurrences)==1
        finally:
            client.delete(f'/schedules/{schedule_id}').raise_for_status()



if __name__ == '__main__':
    main()
