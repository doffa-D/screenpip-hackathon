"""Timed real Screenpipe/Azure indexing in isolated storage. No desktop actions."""
import asyncio
import json
import sys
import tempfile
import time
import shutil
import logging
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import Settings
from backend.agent import Agent
from backend.mcp_client import ScreenpipeMCP
from backend.repository import Repository
from backend.workflow_store import WorkflowStore
from backend.autonomous_discovery import DiscoveryService, utcnow
from backend.memory_sync import MemorySync
from fastapi import HTTPException
from backend.agent import AgentError


async def main():
    settings = Settings()
    logging.basicConfig(filename='artifacts/memory-sync-live-diagnostics.log', level=logging.INFO,
                        format='%(asctime)s %(name)s %(message)s', encoding='utf-8')
    calls, tools = [], []
    async def investigate(request, output_type, ledger=None):
        async with asyncio.timeout(settings.request_timeout_seconds):
            async with ScreenpipeMCP(settings).connect() as mcp:
                tools[:] = sorted(mcp.tools)
                original_call = mcp.call_tool
                async def tracked(name, arguments):
                    calls.append({'tool':name,'arguments':arguments})
                    return await original_call(name, arguments)
                mcp.call_tool = tracked
                try:
                    output, evidence = await Agent(settings).run(mcp, request, output_type, ledger)
                except AgentError as exc:
                    raise HTTPException(503, str(exc)) from None
                return output, evidence
    with tempfile.TemporaryDirectory(prefix='melon-memory-live-') as directory:
        repo = Repository(directory)
        discovery = DiscoveryService(repo, investigate, settings, WorkflowStore(repo))
        sync = MemorySync(repo, discovery, settings)
        discovery.state['cursor'] = (utcnow() - timedelta(hours=24)).isoformat()
        start = time.perf_counter()
        sync.kick()
        await discovery.job
        sync.project()
        elapsed = round(time.perf_counter()-start, 3)
        report = {'elapsed_seconds':elapsed, 'status':sync.status(), 'available_tools':tools,
            'calls':calls, 'memories':sync.index.listing(limit=500), 'patterns':discovery.listing(),
            'saved_workflows':len(discovery.workflows.list())}
        # Preserve the actual isolated store for API/browser verification (private local files).
        destination = Path('artifacts/memory-sync-live-store')
        destination.mkdir(parents=True, exist_ok=True)
        for source in Path(directory).glob('*.json'):
            shutil.copy2(source, destination / source.name)
        artifact = Path('artifacts/memory-sync-live.json')
        artifact.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'elapsed_seconds':elapsed,'status':report['status'], 'tool_calls':len(calls),
            'memories':len(report['memories']), 'patterns':len(report['patterns']), 'artifact':str(artifact)}))
        if discovery.status()['status'] != 'completed':
            raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
