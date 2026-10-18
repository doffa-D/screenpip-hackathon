"""Broad activity coverage, separate from selectable/replayable task discovery."""
import asyncio
import re
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .mcp_client import ScreenpipeMCP, MCPError
from .screenpipe_tools import execute


class ActivityOverview(BaseModel):
    start_time: str
    end_time: str
    timezone: str
    data_status: str
    source: str = 'Screenpipe MCP activity-summary'
    summary: str
    truncated: bool
    limitations: str = ('Activity is observed usage, not proof of completed tasks. Window titles and URLs may be stale or mismatched. '
                        'Capture counts are volume, not duration. Context is bounded and may include discussions or summaries.')


def router(settings):
    routes = APIRouter(tags=['Activity'])

    @routes.get('/activity/summary', response_model=ActivityOverview,
                summary='Overview of recorded activity, apps and coverage. Use FIRST for what did I do today/yesterday/this week; an empty task search does not mean no recordings.')
    async def overview(period: Literal['Today', 'Yesterday', 'This week'] = 'Today'):
        end = datetime.now(ZoneInfo(settings.agent_timezone))
        start = end.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == 'Yesterday':
            end = start
            start -= timedelta(days=1)
        elif period == 'This week':
            start -= timedelta(days=end.weekday())
        try:
            async with asyncio.timeout(90):
                async with ScreenpipeMCP(settings).connect() as mcp:
                    text, truncated = await execute(mcp, 'activity-summary',
                        {'start_time': start.isoformat(), 'end_time': end.isoformat()}, 24000)
            match = re.search(r'^Data status:\s*(.*)$', text, re.MULTILINE)
            return ActivityOverview(start_time=start.isoformat(), end_time=end.isoformat(),
                timezone=settings.agent_timezone, data_status=match.group(1).strip() if match else 'unknown',
                summary=text, truncated=truncated)
        except TimeoutError:
            raise HTTPException(504, 'Screenpipe activity overview timed out. Recording coverage is unknown.') from None
        except (MCPError, ValueError):
            raise HTTPException(502, 'Screenpipe activity overview could not be read. This does not mean no recordings exist.') from None
    return routes
