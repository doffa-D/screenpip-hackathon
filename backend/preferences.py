import asyncio
import shutil
import time
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse
from pydantic import Field, field_validator
from fastapi import APIRouter, HTTPException
from .models import Model
from .agent import Agent
from .mcp_client import ScreenpipeMCP
from .desktop import call_desktop


class Preferences(Model):
    theme: Literal['light', 'dark', 'system'] = 'light'
    accent: Literal['indigo', 'pink', 'green'] = 'indigo'
    desktop_enabled: bool = True
    notifications: bool = False


class ProviderUpdate(Model):
    provider: Literal['azure', 'openai']
    endpoint: str
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, min_length=1, max_length=4000)

    @field_validator('endpoint')
    @classmethod
    def safe_endpoint(cls, value):
        url = urlparse(value)
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Use a valid provider endpoint without credentials, query, or fragment')
        if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost')):
            raise ValueError('Use HTTPS, or HTTP on localhost')
        return value.rstrip('/')


def router(settings, repository, executions):
    routes = APIRouter()
    state = Preferences.model_validate(repository.read('preferences', {}))
    executions.permission = lambda: state.desktop_enabled
    checks = {}
    for key, value in repository.read('provider', {}).items():
        if key in {'ai_provider', 'azure_openai_endpoint', 'azure_openai_deployment', 'azure_openai_api_key',
                   'openai_base_url', 'openai_model', 'openai_api_key'}:
            setattr(settings, key, value)

    @routes.get('/settings')
    async def read():
        return {**state.model_dump(), 'provider': settings.ai_provider,
                'model': settings.azure_openai_deployment if settings.ai_provider == 'azure' else settings.openai_model,
                'endpoint': settings.azure_openai_endpoint if settings.ai_provider == 'azure' else settings.openai_base_url}

    @routes.patch('/settings/provider')
    async def provider(body: ProviderUpdate):
        if any(run['status'] in ('running', 'awaiting_approval', 'stopping') for run in executions.runs.values()):
            raise HTTPException(409, 'Finish the current desktop run before changing providers')
        values = repository.read('provider', {})
        values['ai_provider'] = body.provider
        if body.provider == 'azure':
            values.update(azure_openai_endpoint=body.endpoint, azure_openai_deployment=body.model)
            if body.api_key is not None:
                values['azure_openai_api_key'] = body.api_key
        else:
            values.update(openai_base_url=body.endpoint, openai_model=body.model)
            if body.api_key is not None:
                values['openai_api_key'] = body.api_key
        repository.write('provider', values)
        for key, value in values.items():
            setattr(settings, key, value)
        checks.pop('model', None)
        return await read()

    @routes.patch('/settings')
    async def update(body: Preferences):
        nonlocal state
        repository.write('preferences', body.model_dump())
        state = body
        if not body.desktop_enabled:
            for key, run in list(executions.runs.items()):
                if run['status'] in ('running', 'awaiting_approval', 'stopping'):
                    await executions.stop(key)
        return await read()

    @routes.get('/system/status')
    async def system():
        path = Path(settings.data_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return {'data_directory': str(path), 'free_bytes': shutil.disk_usage(path).free,
                'storage': 'Local JSON', 'capture_settings': 'Managed in Screenpipe; Melon only bookmarks intervals.'}

    @routes.get('/capabilities')
    async def capabilities():
        return {name: checks.get(name, {'status': 'unchecked', 'checked_at': None,
                'explanation': 'Run a live connection test.'}) for name in ('screenpipe', 'model', 'desktop')}

    @routes.post('/connections/{name}/test')
    async def test(name: Literal['screenpipe', 'model', 'desktop']):
        started = time.perf_counter()
        try:
            async with asyncio.timeout(90):
                if name == 'screenpipe':
                    async with ScreenpipeMCP(settings).connect() as mcp:
                        if 'health-check' not in mcp.tools:
                            raise RuntimeError('Health tool unavailable')
                        result = await mcp.call_tool('health-check', {})
                        if result.get('isError'):
                            raise RuntimeError('Capture health failed')
                        detail = {'health': result, 'tool_count': len(mcp.tools)}
                        health_payload = result.get('structuredContent')
                        if health_payload is None:
                            for block in result.get('content', []):
                                if block.get('type') == 'text':
                                    try:
                                        health_payload = json.loads(block['text'])
                                        break
                                    except (ValueError, TypeError):
                                        continue
                        if not isinstance(health_payload, dict) or 'status' not in health_payload:
                            raise RuntimeError('Unrecognized capture health response')
                elif name == 'desktop':
                    detail = await call_desktop('list_apps', {}, settings.desktop_timeout_seconds)
                else:
                    async with Agent(settings).create_client() as client:
                        kwargs = {'model': settings.azure_openai_deployment if settings.ai_provider == 'azure' else settings.openai_model,
                                  'messages': [{'role': 'user', 'content': 'Reply OK.'}], 'max_completion_tokens': 32}
                        if settings.reasoning_effort:
                            kwargs['reasoning_effort'] = settings.reasoning_effort
                        await client.chat.completions.create(**kwargs)
                    detail = {'message': 'Provider responded successfully'}
            status = {'status': 'connected', 'checked_at': datetime.now(timezone.utc).isoformat(),
                      'elapsed_seconds': round(time.perf_counter() - started, 3), 'explanation': 'Live test completed.', 'details': detail}
            if name == 'screenpipe' and health_payload['status'] not in ('ok', 'healthy'):
                status.update(status='degraded', explanation='MCP is reachable; Screenpipe reports degraded capture health. Inspect connection details.')
        except Exception:
            status = {'status': 'error', 'checked_at': datetime.now(timezone.utc).isoformat(),
                      'elapsed_seconds': round(time.perf_counter() - started, 3),
                      'explanation': 'Connection test failed. Check the local service, credentials and logs.'}
        checks[name] = status
        return status

    return routes
