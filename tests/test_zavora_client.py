import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jsonschema import ValidationError

from backend.computer_use_mcp import ComputerUseMCP


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def client_with_result(data):
    client = ComputerUseMCP(timeout=.01)
    client.tools = {'read': SimpleNamespace(input_schema={
        'type': 'object', 'properties': {}, 'additionalProperties': False})}
    result = SimpleNamespace(model_dump=lambda **kwargs: data)
    client.session = SimpleNamespace(call_tool=AsyncMock(return_value=result))
    return client


@pytest.mark.anyio
async def test_validates_before_calling_native_server():
    client = client_with_result({})
    with pytest.raises(ValueError, match='unavailable'):
        await client.call('unknown', {})
    with pytest.raises(ValidationError):
        await client.call('read', {'unexpected': 1})
    client.session.call_tool.assert_not_called()


@pytest.mark.anyio
async def test_preserves_array_results_and_surfaces_tool_errors():
    client = client_with_result({'content': [{'type': 'text', 'text': '[{"value":"hello"}]'}]})
    assert await client.call('read', {}) == [{'value': 'hello'}]
    client = client_with_result({'isError': True, 'content': [{'type': 'text', 'text': 'refused'}]})
    with pytest.raises(RuntimeError, match='refused'):
        await client.call('read', {})


@pytest.mark.anyio
async def test_call_timeout_cancels_wait():
    client = client_with_result({})
    async def stalled(*args):
        await asyncio.sleep(10)
    client.session.call_tool.side_effect = stalled
    with pytest.raises(TimeoutError):
        await client.call('read', {})
