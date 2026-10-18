"""Optional Zavora MCP session; discovering a tool does not authorize execution.

Kept separate from the approval-gated xa11y executor while evaluated.
"""
import asyncio
import json
import os
import shutil
from contextlib import asynccontextmanager

from jsonschema import validate
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import PaginatedRequestParams

PACKAGE = '@zavora-ai/computer-use-mcp@7.6.1'


class ComputerUseMCP:
    def __init__(self, timeout=60):
        self.timeout = timeout
        self.tools = {}
        self.session = None

    @asynccontextmanager
    async def connect(self):
        command = shutil.which('npx')
        if not command:
            raise RuntimeError('Node.js/npx is required')
        env = dict(os.environ, COMPUTER_USE_PROFILE='ax')
        params = StdioServerParameters(command=command, args=['-y', PACKAGE], env=env)
        body_error = None
        try:
            async with stdio_client(params) as streams:
                async with ClientSession(*streams, read_timeout_seconds=self.timeout) as session:
                    self.session = session
                    self.tools.clear()
                    async with asyncio.timeout(self.timeout):
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
        except Exception:
            if body_error is not None:
                raise body_error
            raise
        finally:
            self.session = None

    async def call(self, name, arguments):
        if not self.session or name not in self.tools:
            raise ValueError(f'Tool unavailable: {name}')
        validate(arguments, self.tools[name].input_schema)
        async with asyncio.timeout(self.timeout):
            result = await self.session.call_tool(name, arguments)
        data = result.model_dump(mode='json', by_alias=True, exclude_none=True)
        if data.get('isError'):
            raise RuntimeError(f'{name}: {data.get("content")}')
        if 'structuredContent' in data:
            return data['structuredContent']
        text = '\n'.join(item.get('text', '') for item in data.get('content', []) if item['type'] == 'text')
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {'text': text}
