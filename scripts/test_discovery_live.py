"""Real discovery smoke test, isolated storage; never saves or executes a workflow.
Run: .venv/Scripts/python.exe scripts/test_discovery_live.py --hours 8
"""
import argparse
import asyncio
import json
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import Settings
from backend.agent import Agent
from backend.mcp_client import ScreenpipeMCP
from backend.repository import Repository
from backend.workflow_store import WorkflowStore
from backend.autonomous_discovery import DiscoveryService, utcnow


async def main(hours):
    settings = Settings()
    tools = []
    calls = []
    async def investigate(request, output_type, ledger=None):
        async with asyncio.timeout(settings.request_timeout_seconds):
            async with ScreenpipeMCP(settings).connect() as mcp:
                tools[:] = sorted(mcp.tools)
                result, evidence = await Agent(settings).run(mcp, request, output_type, ledger)
                calls.extend({'tool': e['tool'], 'arguments': e['arguments'], 'truncated': e.get('truncated', False)} for e in evidence.values())
                return result, evidence
    with tempfile.TemporaryDirectory(prefix='melon-discovery-test-') as directory:
        repository = Repository(directory)
        service = DiscoveryService(repository, investigate, settings, WorkflowStore(repository))
        service.state['cursor'] = (utcnow() - timedelta(hours=hours) + timedelta(minutes=settings.discovery_overlap_minutes)).isoformat()
        started = time.perf_counter()
        service.kick()
        await service.job
        elapsed = round(time.perf_counter() - started, 3)
        report = {'elapsed_seconds': elapsed, 'status': service.status(), 'available_tools': tools, 'calls': calls,
                  'patterns': [service.public(p, True) for p in service.state['patterns'].values()],
                  'occurrence_count': len(service.state['occurrences']), 'saved_workflows': len(service.workflows.list())}
        path = Path('artifacts/autonomous-discovery-live.json')
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({'elapsed_seconds': elapsed, 'status': report['status'], 'patterns': len(report['patterns']),
                          'occurrences': report['occurrence_count'], 'tool_calls': len(calls), 'artifact': str(path)}))
        if report['status']['status'] != 'completed':
            raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--hours', type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.hours <= 168:
        parser.error('--hours must be between 1 and 168')
    asyncio.run(main(args.hours))
