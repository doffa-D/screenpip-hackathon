import time,json,httpx
from pathlib import Path
start=time.perf_counter()
try:
    with httpx.Client(timeout=310) as client:
        print('health',client.get('http://127.0.0.1:8765/health').status_code,flush=True)
        response=client.post('http://127.0.0.1:8765/chat/message',json={'message':'can you tell me what i did today ?'})
        Path('artifacts/chat-today-reproduction.json').write_text(response.text,encoding='utf-8')
        print('response',response.status_code,'seconds',round(time.perf_counter()-start,3),flush=True)
        print('health_after',client.get('http://127.0.0.1:8765/health').status_code,flush=True)
except Exception as exc:
    print(type(exc).__name__,str(exc),round(time.perf_counter()-start,3),flush=True)
