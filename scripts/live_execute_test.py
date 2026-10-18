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
    out = Path('artifacts/full-app-live').resolve()
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
    backend.tasks.clear()
    backend.tasks[selected_id] = {'task': TaskOccurrence.model_validate(session['task']),
        'ledger': session['ledger'], 'workflow': workflow, 'expires': time.monotonic() + 3600}
    started = time.perf_counter()
    with TestClient(backend.app) as client:
        response = client.post(f'/tasks/{selected_id}/execute', json={
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



if __name__ == '__main__':
    main()
