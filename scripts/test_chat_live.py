import asyncio, json
from pathlib import Path
from backend.main import app, settings
from backend.chat import ChatService, ChatRequest, ChatAction

async def main():
    service = ChatService(app, settings)
    read = await service.turn(ChatRequest(message='Check the real Melon health and list my saved workflows. Tell me the count. Use the tools.'))
    proposal = await service.turn(ChatRequest(session_id=read['session_id'], message='Start a recording segment now.'))
    assert any(a['path'] == '/recordings/start' for a in proposal['actions']), proposal['message']
    for action in proposal['actions']:
        await service.decide(ChatAction(session_id=read['session_id'], action_id=action['id'], confirm=False))
    Path('artifacts/chat-live.json').write_text(json.dumps({'read':read,'recording_proposal':proposal,'note':'Recording proposal dismissed; no recording changed.'},indent=2,default=str),encoding='utf-8')
    print(json.dumps({'read_seconds':read['elapsed_seconds'],'read_message':read['message'],'read_operations':[r['operation'] for r in read['results']],'proposal_seconds':proposal['elapsed_seconds'],'proposal_message':proposal['message'],'proposed_paths':[a['path'] for a in proposal['actions']]}))
if __name__ == '__main__':
    asyncio.run(main())
