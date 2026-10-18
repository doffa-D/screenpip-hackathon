"""Run from project root: python -m scripts.probe_mcp."""
import asyncio
import json
from datetime import datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path
from backend.config import Settings
from backend.mcp_client import ScreenpipeMCP


async def main():
    settings = Settings()
    async with ScreenpipeMCP(settings).connect() as mcp:
        schemas = [t.model_dump(mode='json', exclude_none=True, by_alias=True) for t in mcp.tools.values()]
        Path('docs/mcp-tools.json').write_text(json.dumps(schemas, indent=2), encoding='utf-8')
        print('Discovered tools:', ', '.join(mcp.tools))
        health = next((n for n in mcp.tools if n.replace('_', '-') == 'health-check'), None)
        if health:
            result = await mcp.call_tool(health, {})
            status = json.loads(result['content'][0]['text'])
            print('Recorder health:', status.get('status'), 'version:', status.get('version'))
        if 'search-content' in mcp.tools:
            now = datetime.now(ZoneInfo(settings.agent_timezone))
            start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
            result = await mcp.call_tool('search-content', {
                'start_time': start.isoformat(), 'end_time': now.isoformat(),
                'content_type': 'ocr', 'limit': 1, 'max_content_length': 0})
            print('Bounded original-content search:',
                  'tool error' if result.get('isError') else 'completed',
                  '(history contents withheld from console)')


if __name__ == '__main__':
    asyncio.run(main())
