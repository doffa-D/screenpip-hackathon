"""Minimal live provider diagnostic; never prints credentials."""
import asyncio
from backend.agent import Agent
from backend.config import Settings
from backend.mcp_client import ScreenpipeMCP
from backend.screenpipe_tools import openai_tools


async def main():
    s = Settings()
    client = Agent(s).create_client()
    try:
        async with ScreenpipeMCP(s).connect() as mcp:
            response = await client.chat.completions.create(model=s.azure_openai_deployment,
                messages=[{'role': 'user', 'content': 'Return JSON. Inspect Screenpipe health with a tool.'}],
                tools=openai_tools(mcp), response_format={'type': 'json_object'},
                **({'reasoning_effort': s.reasoning_effort} if s.reasoning_effort else {}))
            print('Model response:', response.choices[0].message)
    except Exception as exc:
        print(type(exc).__name__, str(exc).replace(s.azure_openai_api_key, '[REDACTED]'))
    finally:
        await client.close()


if __name__ == '__main__':
    asyncio.run(main())
