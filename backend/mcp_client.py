"""Request-scoped stdio sessions: enter and exit in the same async task."""
import asyncio
import os
import shutil
from contextlib import asynccontextmanager
from mcp import ClientSession, StdioServerParameters
from mcp.types import PaginatedRequestParams
from mcp.client.stdio import stdio_client
from dotenv import dotenv_values
from .config import Settings


class MCPError(RuntimeError):
    pass


class ScreenpipeMCP:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = None
        self.tools = {}

    @asynccontextmanager
    async def connect(self):
        command = shutil.which(self.settings.mcp_command)
        if not command:
            raise MCPError(f'MCP command unavailable: {self.settings.mcp_command}')
        child_env = {k: v for k, v in dotenv_values('.env').items()
                     if k.startswith('SCREENPIPE_') and v is not None}
        child_env.update(os.environ)
        params = StdioServerParameters(command=command, args=self.settings.mcp_args,
                                       env=child_env)
        body_error = None
        try:
            async with stdio_client(params) as streams:
                async with ClientSession(*streams, read_timeout_seconds=self.settings.mcp_timeout_seconds) as session:
                    self.session = session
                    async with asyncio.timeout(self.settings.mcp_timeout_seconds):
                        await session.initialize()
                        cursor = None
                        while True:
                            page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
                            self.tools.update({tool.name: tool for tool in page.tools})
                            cursor = page.next_cursor
                            if not cursor:
                                break
                    try:
                        yield self
                    except Exception as exc:
                        body_error = exc
                        raise
        except Exception as exc:
            if body_error is not None:
                raise body_error
            raise MCPError('Screenpipe MCP connection/request failed; check npx and Screenpipe logs') from exc
        finally:
            self.session = None

    async def call_tool(self, name: str, arguments: dict):
        if self.session is None or name not in self.tools:
            raise MCPError('MCP tool unavailable')
        try:
            async with asyncio.timeout(self.settings.mcp_timeout_seconds):
                result = await self.session.call_tool(name, arguments)
            return result.model_dump(mode='json', exclude_none=True, by_alias=True)
        except Exception as exc:
            raise MCPError(f'MCP tool {name} failed or timed out') from exc
