import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.config import Settings
import backend.activity as activity


def test_activity_preserves_coverage_and_explicit_timezone(monkeypatch):
    captured = {}
    class MCP:
        def __init__(self, settings): pass
        @asynccontextmanager
        async def connect(self): yield self
    async def execute(mcp, name, args, limit):
        captured.update(args)
        assert name == 'activity-summary'
        return 'Data status: ok\nAuthoritative active time: 157.4 min\nCapture observations: 3054 frames', False
    monkeypatch.setattr(activity, 'ScreenpipeMCP', MCP)
    monkeypatch.setattr(activity, 'execute', execute)
    app = FastAPI(); app.include_router(activity.router(Settings()))
    with TestClient(app) as client:
        response = client.get('/activity/summary?period=Today')
        assert response.status_code == 200
        data = response.json()
        assert data['data_status'] == 'ok'
        assert '3054' in data['summary']
        assert 'proof of completed tasks' in data['limitations']
        assert captured['start_time'].endswith('+02:00')
        assert client.get('/activity/summary?period=unsupported').status_code == 422


def test_activity_failure_does_not_report_no_recordings(monkeypatch):
    class MCP:
        def __init__(self, settings): pass
        @asynccontextmanager
        async def connect(self):
            raise activity.MCPError('unreachable')
            yield
    monkeypatch.setattr(activity, 'ScreenpipeMCP', MCP)
    app = FastAPI(); app.include_router(activity.router(Settings()))
    with TestClient(app) as client:
        response = client.get('/activity/summary')
        assert response.status_code == 502
        assert 'does not mean no recordings' in response.json()['detail']
