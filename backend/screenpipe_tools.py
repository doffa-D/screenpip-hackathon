"""Reviewed read operations from screenpipe-mcp 0.20.3; schemas stay dynamic.

New tools fail closed until reviewed. No notifications, pipes, or memory writes.
"""
import json
from jsonschema import validate

READ_TOOLS = {
    'health-check', 'activity-summary', 'search-content', 'keyword-search',
    'frame-context', 'search-elements', 'get-frame-elements',
    'list-meetings', 'get-meeting',
}


def available_tools(mcp):
    return {name: tool for name, tool in mcp.tools.items() if name in READ_TOOLS}


def openai_tools(mcp):
    return [{'type': 'function', 'function': {
        'name': name, 'description': tool.description or '',
        'parameters': tool.input_schema,
    }} for name, tool in available_tools(mcp).items()]


async def execute(mcp, name, arguments, max_chars):
    tool = available_tools(mcp).get(name)
    if not tool:
        raise ValueError('Tool is not an enabled history read operation')
    validate(arguments, tool.input_schema)
    if arguments.get('include_frames'):
        raise ValueError('Screenshots are not enabled in this text-only milestone')
    if name == 'search-content' and 'max_content_length' in tool.input_schema.get('properties', {}):
        # 0.20.3 truncates JavaScript strings at UTF-16 code units, which can
        # split emoji and emit lone-surrogate JSON rejected by the Python SDK.
        # Bound rows at source and truncate valid decoded text locally instead.
        arguments = {**arguments, 'max_content_length': 0,
                     'limit': min(arguments.get('limit', 5), 20)}
    result = await mcp.call_tool(name, arguments)
    if result.get('isError'):
        raise ValueError('Screenpipe tool reported an error')
    text = '\n'.join(block['text'] for block in result.get('content', [])
                     if block.get('type') == 'text')
    if result.get('structuredContent') is not None:
        text += '\n' + json.dumps(result['structuredContent'], ensure_ascii=False)
    # Keep only the prefix the model actually sees, so it cannot cite unseen content.
    return text[:max_chars], len(text) > max_chars
