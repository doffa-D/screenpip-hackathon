"""Real Azure/Zavora supervised pipeline smoke test in a unique Notepad fixture.

No email is sent and no file is saved. The test harness approves only set_value
to 'hello world' in its own freshly opened window; the product gates remain on.
Run from the project root: .venv/Scripts/python.exe -m scripts.live_seeded_pipeline_test
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen
from urllib.error import URLError
from uuid import uuid4


def main():
    # Do not compete with a desktop run in the user's app.
    for port in (8765, 8000):
        try:
            with urlopen(f'http://127.0.0.1:{port}/runs', timeout=3) as response:
                if any(r['status'] in ('running','awaiting_approval','stopping') for r in json.load(response)):
                    raise RuntimeError('Finish the current desktop run before running this test.')
        except URLError:
            pass
    out=Path('artifacts/seeded-real-execution') / uuid4().hex[:12]
    out=out.resolve();out.mkdir(parents=True)
    os.environ['DATA_DIR']=str(out / 'state')
    os.environ['DISCOVERY_ENABLED']='false'
    from fastapi.testclient import TestClient
    import backend.main as backend
    from backend.desktop import call_desktop
    from backend.execution import ExecutionManager
    from scripts.seed_demo_data import seed
    from backend.workflow_store import WorkflowStore
    seed(backend.repository)
    backend.workflows.records=WorkflowStore(backend.repository).records
    backend.memory_sync.index.records=backend.repository.read('memories',{})
    backend.hotkeys.start=lambda:None
    fixture=out / f'melon-seeded-{uuid4().hex[:8]}.txt'
    fixture.write_text('hello word',encoding='utf-8')
    subprocess.Popen(['notepad.exe',str(fixture)])
    target=None
    for _ in range(20):
        windows=asyncio.run(call_desktop('list_apps',{},30))['apps']
        matches=[w for w in windows if fixture.name in (w.get('title') or '')]
        if len(matches)==1:
            target=matches[0];break
        time.sleep(.5)
    if target is None:raise RuntimeError('Unique Notepad test window not found.')
    wid='demo:workflow:notepad'
    started=time.perf_counter()
    with TestClient(backend.app) as client:
        def post(path,body):
            response=client.post(path,json=body);response.raise_for_status();return response.json()
        workflow=client.get(f'/workflows/{wid}').json()
        request=workflow['run_defaults']
        request['instructions']=(f'Use ONLY the Notepad window containing {fixture.name}, '
            f'window ID {target["windowId"]}. Replace the entire editor value with exactly hello world. '
            'Verify the exact editor value. No saving, no other windows or changes.')
        response=client.patch(f'/workflows/{wid}',json={'expected_revision':workflow['revision'],'run_defaults':request})
        response.raise_for_status();workflow=response.json()
        approved=post(f'/workflows/{wid}/approve',{'expected_revision':workflow['revision']})
        approval_seconds=round(time.perf_counter()-started,3)
        tick=time.perf_counter()
        run=post(f'/workflows/{wid}/execute',request);rid=run['id']
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            run=client.get(f'/runs/{rid}').json()
            if run['status']=='awaiting_approval':
                action=run['pending_action'];args=action['arguments']
                allowed=(args.get('window_id')==target['windowId'] and fixture.name in args.get('window_title','')
                    and args.get('action')=='set_value' and args.get('value')=='hello world')
                post(f'/runs/{rid}/approval',{'action_id':action['id'],'approve':allowed})
                print('Approved fixture-only edit' if allowed else 'Declined unexpected change',flush=True)
            if run['status'] not in ('running','awaiting_approval','stopping') and run.get('report'):break
            time.sleep(.25)
        else:
            run=post(f'/runs/{rid}/stop',{})
        execution_seconds=round(time.perf_counter()-tick,3)
        (out/'run.json').write_text(json.dumps(run,indent=2,ensure_ascii=False),encoding='utf-8')
        response=client.get(f'/runs/{rid}/report');response.raise_for_status();report=response.json()
        (out/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        if run['status']!='completed':raise RuntimeError(f'Execution {run["status"]}: {run["summary"]}. Artifacts: {out}')
        windows=asyncio.run(call_desktop('list_apps',{},30))['apps']
        current=next(w for w in windows if w['windowId']==target['windowId'])
        verified=asyncio.run(call_desktop('verify_text',{'window_id':current['windowId'],'window_title':current['title'],
            'role':'AXWebArea','label':'Text editor','property':'value','expected':'hello world'},30))
        if not verified['verified']:raise RuntimeError('Independent verification failed.')
        reviewed=post(f'/runs/{rid}/feedback',{'verdict':'looks_good',
            'notes':'TEST HARNESS verdict after an independent fresh Zavora verification; not a human review.'})
        (out/'run.json').write_text(json.dumps(reviewed,indent=2,ensure_ascii=False),encoding='utf-8')
        persisted=ExecutionManager(backend.settings,backend.repository).runs[rid]
        assert persisted['feedback']==reviewed['feedback'] and persisted['report']==report
        assert persisted['workflow_id']==approved['id'] and persisted['workflow_revision']==approved['approved_revision']
        result={'status':run['status'],'workflow_id':wid,'run_id':rid,'approval_seconds':approval_seconds,
            'execution_seconds':execution_seconds,'total_seconds':round(time.perf_counter()-started,3),
            'actions_attempted':len(report['actions_attempted']),'actions_completed':len(report['actions_completed']),
            'verification':verified,'feedback':reviewed['feedback'],'artifacts':str(out)}
        (out/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
