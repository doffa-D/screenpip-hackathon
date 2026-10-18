import asyncio
from fastapi import FastAPI
from backend.chat import ChatService, ChatAction, catalogue
from backend.config import Settings


def test_chat_catalogue_and_single_use_confirmation():
    app = FastAPI()
    changes = []
    @app.get('/health')
    async def health(): return {'status': 'ok'}
    @app.post('/recordings/start')
    async def start():
        changes.append('started')
        return {'started': True}
    @app.post('/runs/{id}/approval')
    async def approve(id: str): return {}
    @app.patch('/settings/provider')
    async def provider(): return {}
    @app.get('/unrelated')
    async def unrelated(): return {}
    service = ChatService(app, Settings())
    ops = catalogue(app)
    assert {o['path'] for o in ops.values()} == {'/health', '/recordings/start'}
    async def exercise():
        health_op = next(o for o in ops.values() if o['path'] == '/health')
        assert (await service.invoke(health_op, {}))['data']['status'] == 'ok'
        key, state = service.session()
        state['actions']['one'] = {'id':'one','path':'/recordings/start','method':'POST','arguments':{}}
        assert changes == []
        result = await service.decide(ChatAction(session_id=key, action_id='one', confirm=True))
        assert result['status'] == 200 and changes == ['started']
        from fastapi import HTTPException
        try:
            await service.decide(ChatAction(session_id=key, action_id='one', confirm=True))
            assert False
        except HTTPException as exc:
            assert exc.status_code == 409
        state['actions']['two'] = {'id':'two','path':'/recordings/start','method':'POST','arguments':{}}
        await service.decide(ChatAction(session_id=key, action_id='two', confirm=False))
        assert changes == ['started']
    asyncio.run(exercise())

def test_recording_fast_path_does_not_use_model():
    from backend.chat import ChatRequest
    app = FastAPI()
    changes = []
    @app.post('/recordings/start')
    async def start(body: dict):
        changes.append(body)
        return {}
    service = ChatService(app, Settings(azure_openai_api_key='', openai_api_key=''))
    async def exercise():
        reply = await service.turn(ChatRequest(message='Start a recording segment now.'))
        assert reply['timings']['model_calls'] == 0
        assert reply['actions'][0]['path'] == '/recordings/start'
        assert not changes
    asyncio.run(exercise())
