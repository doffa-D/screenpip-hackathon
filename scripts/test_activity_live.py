import asyncio,json,time
from pathlib import Path
from backend.main import app,settings
from backend.chat import ChatService,ChatRequest
async def main():
 start=time.perf_counter()
 result=await ChatService(app,settings).turn(ChatRequest(message='can you tell me what i did today ?'))
 Path('artifacts/chat-activity-fixed.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
 print(json.dumps({'message':result['message'],'seconds':round(time.perf_counter()-start,3),'operations':[r['operation'] for r in result['results']]},ensure_ascii=True),flush=True)
if __name__ == '__main__':
    asyncio.run(main())
