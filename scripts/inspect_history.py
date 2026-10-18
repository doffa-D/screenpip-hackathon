import asyncio,json
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from backend.config import Settings
from backend.mcp_client import ScreenpipeMCP
async def main():
 s=Settings();now=datetime.now(ZoneInfo(s.agent_timezone));start=now.replace(hour=0,minute=0,second=0,microsecond=0)
 async with ScreenpipeMCP(s).connect() as m:
  out={}
  for name,args in [('activity-summary',{'start_time':start.isoformat(),'end_time':now.isoformat()}),('search-content',{'start_time':start.isoformat(),'end_time':now.isoformat(),'content_type':'ocr','limit':3,'max_content_length':0})]:
   r=await m.call_tool(name,args);out[name]=r
   print(name,json.dumps(r,ensure_ascii=True)[:12000],flush=True)
  Path('artifacts/history-diagnostic.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
asyncio.run(main())
