import asyncio
import time
from collections import OrderedDict
from uuid import uuid4
from types import SimpleNamespace
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from openai import OpenAIError
from .config import Settings
from .models import SearchRequest, SearchResult, TaskOccurrence, Reconstruction, ExecutionRequest, ApprovalRequest
from .models import RunRecord, RunSummary, RunReport, RunFeedback
from .run_reports import build_report, store_feedback
from .mcp_client import ScreenpipeMCP, MCPError
from .agent import Agent, AgentError
from .repository import Repository
from .execution import ExecutionManager
from .desktop import call_desktop
from .workflow_store import WorkflowStore, SavedWorkflow, SaveWorkflow, UpdateWorkflow, RevisionConflict, ApproveWorkflow
from .recordings import RecordingService, router as recording_router
from .refine import refine
from .preferences import router as preferences_router
from .scheduler import Scheduler, router as scheduler_router
from .discovery import router as discovery_router
from .autonomous_discovery import DiscoveryService, router as autonomous_discovery_router
from .memory_sync import MemorySync, router as memory_sync_router
from .hotkeys import Hotkeys
from .nightshift import NightShift, router as nightshift_router

settings = Settings()
repository = Repository(settings.data_dir)
executions = ExecutionManager(settings, repository)
workflows = WorkflowStore(repository)
scheduler = Scheduler(repository, workflows, executions)


@asynccontextmanager
async def lifespan(app):
    scheduler.worker = asyncio.create_task(scheduler.loop())
    discovery.worker = asyncio.create_task(memory_sync.loop())
    nightshift.apply_demo_setting()
    nightshift.worker = asyncio.create_task(nightshift.loop())
    hotkeys.start()
    yield
    await hotkeys.close()
    await nightshift.close()
    await discovery.close()
    await scheduler.close()
    await recordings.close()
    await executions.close()


app = FastAPI(title='Melon — Memory to Action', lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', '[::1]', 'testserver'])
# One worker owns the desktop and local JSON storage.
tasks = OrderedDict()
gate = asyncio.Semaphore(2)


def load_tasks():
    for key, record in repository.read('tasks', {}).items():
        remaining = record['expires_at'] - time.time()
        if remaining > 0:
            tasks[key] = {'task': TaskOccurrence.model_validate(record['task']),
                          'ledger': record['ledger'], 'expires': time.monotonic() + remaining,
                          'workflow': record.get('workflow')}


def persist_tasks():
    repository.write('tasks', {key: {'task': record['task'].model_dump(mode='json'),
        'ledger': record['ledger'], 'workflow': record.get('workflow'),
        'expires_at': time.time() + record['expires'] - time.monotonic()}
        for key, record in tasks.items()})


load_tasks()


@app.middleware('http')
async def local_origin(request, call_next):
    # Block cross-site writes to a service with desktop control. No permissive CORS.
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and origin != getattr(app.state, 'desktop_origin', None) and origin not in {'http://localhost:8000', 'http://127.0.0.1:8000',
                                     'http://localhost:5173', 'http://127.0.0.1:5173'}:
            return JSONResponse({'detail': 'Only the local app may change desktop state'}, status_code=403)
    return await call_next(request)


def prune():
    now = time.monotonic()
    for key in list(tasks):
        if tasks[key]['expires'] <= now:
            del tasks[key]
    while len(tasks) > settings.max_stored_tasks:
        tasks.popitem(last=False)


def find_task(task_id):
    prune()
    if task_id in tasks:
        return tasks[task_id]
    if task_id in memory_sync.index.records:
        memory = memory_sync.index.get(task_id)
        task = TaskOccurrence.model_validate({key: memory[key] for key in TaskOccurrence.model_fields if key in memory})
        tasks[task_id] = {'task': task, 'ledger': memory['ledger'], 'workflow': memory.get('workflow'),
                          'expires': time.monotonic() + settings.task_ttl_seconds}
        return tasks[task_id]
    for record in recordings.records.values():
        if record.get('task_id') == task_id and record.get('workflow'):
            workflow = Reconstruction.model_validate(record['workflow'])
            task = TaskOccurrence(id=task_id, title=record['title'], timestamp=record['started_at'],
                                  summary=workflow.goal, evidence=workflow.evidence)
            publish_recording(task, workflow, record['ledger'])
            return tasks[task_id]
    for group in repository.read('workflow_groups', {}).values():
        if not group.get('ledger'):
            continue
        for member in group['members']:
            if member['id'] == task_id:
                publish_discovery(TaskOccurrence.model_validate(member), group['ledger'])
                return tasks[task_id]
    raise HTTPException(404, 'Unknown or expired task; search again and select a returned id')


async def investigate(request, output_type, ledger=None):
    try:
        # Validate credentials before launching an MCP child.
        agent = Agent(settings)
        client = agent.create_client()
        await client.close()
        async with asyncio.timeout(settings.request_timeout_seconds):
            async with gate:
                if isinstance(request, dict) and request.get('evidence_only') and ledger:
                    return await agent.run(SimpleNamespace(tools={}), request, output_type, ledger)
                async with ScreenpipeMCP(settings).connect() as mcp:
                    return await agent.run(mcp, request, output_type, ledger)
    except TimeoutError:
        raise HTTPException(504, 'Investigation timed out') from None
    except AgentError as exc:
        raise HTTPException(503, str(exc)) from None
    except MCPError as exc:
        raise HTTPException(502, str(exc)) from None
    except OpenAIError:
        raise HTTPException(502, 'Model provider request failed; check credentials, deployment and quota') from None


def publish_recording(task, workflow, ledger):
    tasks[task.id] = {'task': task, 'workflow': workflow.model_dump(mode='json'),
                      'ledger': ledger, 'expires': time.monotonic() + settings.task_ttl_seconds}
    prune()
    persist_tasks()


recordings = RecordingService(repository, investigate, publish_recording)


async def capture_health():
    async with asyncio.timeout(30):
        async with ScreenpipeMCP(settings).connect() as mcp:
            result = await mcp.call_tool('health-check', {})
            payload = result.get('structuredContent')
            if payload is None:
                payload = json.loads(next(b['text'] for b in result['content'] if b['type'] == 'text'))
            return f"Screenpipe reports {payload.get('status', 'unknown')} capture health. Screenpipe records independently."


recordings.health_check = capture_health
hotkeys = Hotkeys(recordings, workflows)
app.include_router(recording_router(recordings))
app.include_router(preferences_router(settings, repository, executions))
app.include_router(scheduler_router(scheduler))


def publish_discovery(task, ledger):
    tasks[task.id] = {'task': task, 'ledger': ledger,
                      'expires': time.monotonic() + settings.task_ttl_seconds}
    prune()
    persist_tasks()


app.include_router(discovery_router(repository, investigate, publish_discovery))
discovery = DiscoveryService(repository, investigate, settings, workflows)
app.include_router(autonomous_discovery_router(discovery))
memory_sync = MemorySync(repository, discovery, settings)
app.include_router(memory_sync_router(memory_sync))
nightshift = NightShift(repository, discovery, workflows, executions, settings)
app.include_router(nightshift_router(nightshift))


@app.get('/shortcuts')
async def shortcut_status():
    return hotkeys.status


@app.get('/system/activity')
async def activity_state():
    return {'scheduler_running': scheduler.worker is not None and not scheduler.worker.done(),
        'enabled_schedules': sum(bool(s['enabled']) for s in scheduler.records.values()),
        'active_recordings': sum(r['status'] == 'recording' for r in recordings.records.values()),
        'processing_recordings': sum(r['status'] == 'processing' for r in recordings.records.values()),
        'night_shift_enabled': nightshift.config['enabled'],
        'active_runs': sum(r['status'] in ('running', 'awaiting_approval', 'stopping') for r in executions.runs.values()),
        'saved_workflows': len(workflows.list())}


@app.get('/health')
async def health():
    return {'status': 'ok', 'storage': 'local-json', 'mcp': 'checked on request',
            'desktop_available': shutil.which('npx') is not None,
            'desktop_provider': 'zavora', 'desktop_status': 'checked on request',
            'model_configured': bool(settings.azure_openai_api_key if settings.ai_provider == 'azure' else settings.openai_api_key)}


@app.get('/tasks', response_model=list[TaskOccurrence])
async def saved_tasks():
    prune()
    return [record['task'] for record in reversed(list(tasks.values()))]


@app.post('/tasks/search', response_model=list[TaskOccurrence])
async def search(body: SearchRequest):
    request = body.message
    if body.period or body.source:
        request = {'message': body.message, 'source_filter': body.source}
        if body.period:
            current = datetime.now(ZoneInfo(settings.agent_timezone))
            start = current.replace(hour=0, minute=0, second=0, microsecond=0)
            end = current
            if body.period == 'Yesterday':
                end = start
                start -= timedelta(days=1)
            elif body.period == 'This week':
                start -= timedelta(days=current.weekday())
            request.update(start_time=start.isoformat(), end_time=end.isoformat(), strict_interval=True)
    output, ledger = await investigate(request, SearchResult)
    results = [TaskOccurrence(id=str(uuid4()), **task.model_dump()) for task in output.tasks]
    prune()
    for task in results:
        tasks[task.id] = {'task': task, 'ledger': ledger,
                          'expires': time.monotonic() + settings.task_ttl_seconds}
    prune()
    persist_tasks()
    memory_sync.index_search(results, ledger)
    return results


@app.post('/tasks/{task_id}/reconstruct', response_model=Reconstruction)
async def reconstruct(task_id: str):
    selected = find_task(task_id)
    if selected['task'].origin == 'demo':
        if not selected.get('workflow'):
            raise HTTPException(409, 'Demo reconstruction unavailable; reseed offline.')
        return selected['workflow']
    output, ledger = await investigate({'selected_task': selected['task'].model_dump(mode='json'),
        'instruction': 'Reconstruct only this selected occurrence. Inspect original surrounding history.'},
        Reconstruction, selected['ledger'])
    output, _ = await refine(investigate, output, ledger)
    selected.update(workflow=output.model_dump(mode='json'), ledger=ledger,
                    expires=time.monotonic() + settings.task_ttl_seconds)
    persist_tasks()
    if task_id in memory_sync.index.records:
        memory_sync.index.save_reconstruction(task_id, output.model_dump(mode='json'), ledger)
    return output


@app.get('/tasks/{task_id}', response_model=TaskOccurrence)
async def read_task(task_id: str):
    return find_task(task_id)['task']


@app.get('/tasks/{task_id}/workflow', response_model=Reconstruction)
async def saved_workflow(task_id: str):
    record = find_task(task_id)
    if not record or not record.get('workflow'):
        raise HTTPException(404, 'No saved workflow. Select and reconstruct this task first.')
    return record['workflow']


@app.post('/tasks/{task_id}/execute', status_code=202, response_model=RunRecord)
async def execute_task(task_id: str, body: ExecutionRequest):
    prune()
    record = tasks.get(task_id)
    if not record or not record.get('workflow'):
        raise HTTPException(409, 'Reconstruct the selected task before execution')
    try:
        client = Agent(settings).create_client()
        await client.close()
        return executions.start(record['task'], Reconstruction.model_validate(record['workflow']), body)
    except AgentError as exc:
        raise HTTPException(503, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.get('/runs', response_model=list[RunSummary])
async def list_runs():
    return [{key: value for key, value in run.items() if key in RunSummary.model_fields}
            for run in reversed(list(executions.runs.values()))]


@app.post('/workflows', response_model=SavedWorkflow, status_code=201)
async def save_workflow(body: SaveWorkflow):
    try:
        record = find_task(body.task_id)
    except HTTPException:
        record = None
    if not record or not record.get('workflow'):
        raise HTTPException(409, 'Select and reconstruct a task before saving it')
    return workflows.create(record['task'], Reconstruction.model_validate(record['workflow']),
                            record['ledger'], body)


@app.get('/workflows', response_model=list[SavedWorkflow])
async def list_workflows():
    return workflows.list()


def get_workflow(workflow_id):
    try:
        return workflows.get(workflow_id)
    except KeyError:
        raise HTTPException(404, 'Saved workflow not found') from None


@app.get('/workflows/{workflow_id}', response_model=SavedWorkflow)
async def read_workflow(workflow_id: str):
    return get_workflow(workflow_id)


@app.patch('/workflows/{workflow_id}', response_model=SavedWorkflow)
async def update_workflow(workflow_id: str, body: UpdateWorkflow):
    get_workflow(workflow_id)
    try:
        return workflows.update(workflow_id, body)
    except RevisionConflict as exc:
        raise HTTPException(409, str(exc)) from None


@app.post('/workflows/{workflow_id}/approve', response_model=SavedWorkflow)
async def approve_workflow(workflow_id: str, body: ApproveWorkflow):
    get_workflow(workflow_id)
    try:
        return workflows.approve(workflow_id, body.expected_revision)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.delete('/workflows/{workflow_id}', status_code=204)
async def archive_workflow(workflow_id: str):
    get_workflow(workflow_id)
    workflows.archive(workflow_id)
    for record in scheduler.records.values():
        if record['workflow_id'] == workflow_id:
            record['enabled'] = False
    scheduler.persist()


@app.post('/workflows/{workflow_id}/execute', status_code=202, response_model=RunRecord)
async def execute_workflow(workflow_id: str, body: ExecutionRequest):
    record = get_workflow(workflow_id)
    # Defaults are presented for review by clients, never applied invisibly here.
    try:
        client = Agent(settings).create_client()
        await client.close()
        run = executions.start(record.task, record.reconstruction, body, saved=record)
        run.update(workflow_id=record.id, workflow_revision=record.revision, triggered_by='manual')
        executions.event(run, 'workflow', 'Saved workflow revision selected',
                         {'workflow_id': record.id, 'revision': record.revision})
        return run
    except AgentError as exc:
        raise HTTPException(503, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


def get_run(run_id):
    if run_id not in executions.runs:
        raise HTTPException(404, 'Run not found')
    return executions.runs[run_id]


@app.get('/runs/{run_id}', response_model=RunRecord)
async def run_status(run_id: str):
    return get_run(run_id)


@app.get('/runs/{run_id}/report', response_model=RunReport)
async def run_report(run_id: str):
    run = get_run(run_id)
    if run['status'] in ('running', 'awaiting_approval', 'stopping'):
        raise HTTPException(409, 'The final report is available when this run finishes.')
    try:
        return run.get('report') or build_report(run)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.post('/runs/{run_id}/feedback', response_model=RunRecord)
async def validate_run(run_id: str, body: RunFeedback):
    get_run(run_id)
    try:
        return store_feedback(executions, run_id, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.post('/runs/{run_id}/approval')
async def approve_action(run_id: str, body: ApprovalRequest):
    get_run(run_id)
    try:
        executions.decide(run_id, body.action_id, body.approve)
        return {'accepted': True}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.post('/runs/{run_id}/stop', response_model=RunRecord)
async def stop_run(run_id: str):
    get_run(run_id)
    return await executions.stop(run_id)


@app.get('/desktop/apps')
async def desktop_apps():
    try:
        return await call_desktop('list_apps', {}, settings.desktop_timeout_seconds)
    except Exception as exc:
        raise HTTPException(503, f'Desktop access unavailable ({type(exc).__name__}). Check Node.js 20+ and the Zavora MCP connection.') from None


# Built frontend is served by FastAPI; development uses Vite's local API proxy.
frontend = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
if (frontend / 'assets').is_dir():
    app.mount('/assets', StaticFiles(directory=frontend / 'assets'), name='assets')


@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    fav = frontend / 'favicon.ico'
    if fav.exists():
        return FileResponse(fav)
    raise HTTPException(404)


@app.get('/melon-logo.png', include_in_schema=False)
async def melon_logo_img():
    logo = frontend / 'melon-logo.png'
    if not logo.exists():
        logo = Path(__file__).resolve().parent.parent / 'melon-logo.png'
    if logo.exists():
        return FileResponse(logo)
    raise HTTPException(404)


@app.get('/', include_in_schema=False)
async def index():
    if (frontend / 'index.html').exists():
        return FileResponse(frontend / 'index.html')
    return JSONResponse({'message': 'Build the frontend: cd frontend; npm install; npm run build',
                         'api_docs': '/docs'})

from .activity import router as activity_router
app.include_router(activity_router(settings))

from .chat import router as chat_router
app.include_router(chat_router(app, settings))


@app.get('/demo/patterns', tags=['Demo'])
async def demo_patterns():
    return list(repository.read('demo_patterns', {}).values())
