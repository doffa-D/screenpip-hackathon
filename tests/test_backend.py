import asyncio
import json
from types import SimpleNamespace
from contextlib import asynccontextmanager
import pytest
from fastapi.testclient import TestClient
from openai.types.chat import ChatCompletionMessage
from backend.agent import Agent, validate_evidence
from backend.config import Settings
from backend.models import SearchResult
from backend.screenpipe_tools import execute
import backend.main as main


class FakeMCP:
    def __init__(self, settings=None):
        schema = {'type': 'object', 'properties': {'q': {'type': 'string'}}}
        self.tools = {n: SimpleNamespace(description='Read history', input_schema=schema)
                      for n in ['search-content', 'frame-context', 'update-memory']}
        self.calls = []

    @asynccontextmanager
    async def connect(self):
        yield self

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        text = ('Sent at 2026-10-17T09:00:00+02:00 to alice: Budget approved. '
                'Sent at 2026-10-17T10:00:00+02:00 to bob: Budget approved.')
        return {'content': [{'type': 'text', 'text': text}]}


def tool_message(name):
    return ChatCompletionMessage(role='assistant', tool_calls=[{
        'id': name, 'type': 'function', 'function': {'name': name, 'arguments': '{}'}}])


def search_output():
    return {'tasks': [{'title': f'Email to {person}',
        'timestamp': f'2026-10-17T{hour}:00:00+02:00', 'summary': 'Sent budget approval email',
        'evidence': [{'call_id': 'e2', 'quote': f'to {person}: Budget approved.',
                      'source_kind': 'original_activity'}]}
        for person, hour in [('alice', '09'), ('bob', '10')]]}


class FakeClient:
    def __init__(self, messages):
        self.responses = iter(messages)
        self.chat = SimpleNamespace(completions=self)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=next(self.responses))])


def test_iterative_search_keeps_distinct_occurrences():
    client = FakeClient([tool_message('search-content'), tool_message('frame-context'),
        ChatCompletionMessage(role='assistant', content=json.dumps(search_output()))])
    mcp = FakeMCP()
    result, ledger = asyncio.run(Agent(Settings(), client).run(
        mcp, 'Find all emails I sent today', SearchResult))
    assert len(result.tasks) == 2
    assert len(ledger) == 2
    assert [n for n, _ in mcp.calls] == ['search-content', 'frame-context']
    assert 'update-memory' not in str(client.requests[0]['tools'])


def test_fabricated_evidence_rejected():
    result = SearchResult.model_validate(search_output())
    with pytest.raises(ValueError, match='quote'):
        validate_evidence(result, {'e2': {'text': 'unrelated'}})


def test_final_output_has_bounded_quote_repair_without_new_tools():
    invalid = search_output()
    for task in invalid['tasks']:
        task['evidence'][0]['call_id'] = 'e1'
        task['evidence'][0]['quote'] = 'invented joined source'
    valid = search_output()
    for task in valid['tasks']:
        task['evidence'][0]['call_id'] = 'e1'
    client = FakeClient([tool_message('search-content'),
        ChatCompletionMessage(role='assistant', content=json.dumps(invalid)),
        ChatCompletionMessage(role='assistant', content=json.dumps(valid))])
    mcp = FakeMCP()
    output, _ = asyncio.run(Agent(Settings(max_agent_rounds=2), client).run(mcp, 'Find emails', SearchResult))
    assert len(output.tasks) == 2
    assert len(mcp.calls) == 1
    assert client.requests[-1]['tool_choice'] == 'none'


def test_write_tools_rejected():
    with pytest.raises(ValueError, match='not an enabled'):
        asyncio.run(execute(FakeMCP(), 'update-memory', {}, 1000))


def test_scoped_search_only_offers_bounded_tools_and_overrides_bounds():
    mcp = FakeMCP()
    mcp.tools['search-content'].input_schema = {'type':'object', 'properties':{
        'q':{'type':'string'}, 'start_time':{'type':'string'}, 'end_time':{'type':'string'}}}
    client = FakeClient([tool_message('search-content'),
        ChatCompletionMessage(role='assistant', content=json.dumps(search_output()).replace('e2', 'e1'))])
    result, ledger = asyncio.run(Agent(Settings(), client).run(mcp,
        {'message':'Find emails', 'strict_interval':True, 'start_time':'2026-10-17T00:00:00Z',
         'end_time':'2026-10-18T00:00:00Z'}, SearchResult))
    assert len(result.tasks) == 2
    assert [t['function']['name'] for t in client.requests[0]['tools']] == ['search-content']
    assert mcp.calls[0][1]['start_time'] == '2026-10-17T00:00:00Z'
    assert mcp.calls[0][1]['end_time'] == '2026-10-18T00:00:00Z'


def test_http_search_and_explicit_selection(monkeypatch):
    main.tasks.clear()
    async def investigate(request, output_type, ledger=None):
        return SearchResult.model_validate(search_output()), {'e2': {'text': 'test'}}
    monkeypatch.setattr(main, 'investigate', investigate)
    with TestClient(main.app) as client:
        assert client.get('/health').status_code == 200
        response = client.post('/tasks/search', json={'message': 'Find all emails I sent today'})
        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) == 2 and tasks[0]['id'] != tasks[1]['id']
        assert client.post('/tasks/unknown/reconstruct').status_code == 404
        assert client.post('/tasks/search', json={'message': ' '}).status_code == 422
    main.tasks.clear()


def test_reconstruction_endpoint_uses_selected_task(monkeypatch):
    from backend.models import Reconstruction, TaskOccurrence
    import time
    task = TaskOccurrence(id='chosen', **search_output()['tasks'][0])
    main.tasks['chosen'] = {'task': task, 'ledger': {'e2': {'text': 'original'}},
                            'expires': time.monotonic() + 60}
    async def investigate(request, output_type, ledger=None):
        assert request['selected_task']['id'] == 'chosen'
        assert ledger['e2']['text'] == 'original'
        return Reconstruction(goal='Send email', historical_values={}, steps=[],
            missing_values=['Recipient address masked'], evidence=task.evidence), ledger
    monkeypatch.setattr(main, 'investigate', investigate)
    with TestClient(main.app) as client:
        response = client.post('/tasks/chosen/reconstruct')
        assert response.status_code == 200
        assert response.json()['missing_values'] == ['Recipient address masked']
    main.tasks.clear()


def test_missing_credentials_returns_actionable_error(monkeypatch):
    monkeypatch.setattr(main, 'settings', Settings(_env_file=None,
        azure_openai_api_key='', azure_openai_endpoint='', azure_openai_deployment=''))
    with TestClient(main.app) as client:
        response = client.post('/tasks/search', json={'message': 'Find all emails I sent today'})
        assert response.status_code == 503
        assert 'AZURE_OPENAI' in response.json()['detail']


def test_final_round_returns_answer_and_forwards_reasoning_setting():
    client = FakeClient([tool_message('search-content'),
        ChatCompletionMessage(role='assistant', content='{"tasks": []}')])
    result, _ = asyncio.run(Agent(Settings(max_agent_rounds=2,
        reasoning_effort='none'), client).run(FakeMCP(), 'Find emails', SearchResult))
    assert result.tasks == []
    assert client.requests[0]['tool_choice'] == 'auto'
    assert client.requests[-1]['tool_choice'] == 'none'
    assert client.requests[0]['reasoning_effort'] == 'none'
