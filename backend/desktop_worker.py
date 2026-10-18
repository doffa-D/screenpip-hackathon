"""Zavora MCP worker: one long-lived process answering one JSON request per line; no xa11y runtime dependency."""
import asyncio
import json
import re
import sys
import os
from jsonschema import ValidationError
from .computer_use_mcp import ComputerUseMCP
from .overlay import TITLE as OVERLAY_TITLE, aim
from .desktop import READ_ONLY, SHELL_HOSTS, TEXT_INPUT, validate_call, zavora_window


def same_title(live, expected):
    """Window ids are the identity; a browser's unread counter "(7)" or Notepad's "*" must not break it."""
    plain = lambda title: re.sub(r'^(\(\d+\)\s*|\*)', '', str(title or ''))
    return plain(live) == plain(expected)


def whatsapp_message_status(tree, expected):
    """Correlate message content and status inside a small message container, excluding drafts."""
    normalize = lambda text: ' '.join(str(text or '').split())
    expected = normalize(expected)
    found = {}
    def visit(node, ancestors):
        if not isinstance(node, dict):
            return
        text = normalize(node.get('label'))
        match = (node.get('role') == 'AXStaticText' and text == expected) or (
            node.get('role') == 'AXButton' and expected.lower().endswith('.pdf') and expected in text)
        if match:
            for ancestor in [node, *reversed(ancestors)]:
                children = flatten(ancestor)
                if len(children) > 80 or any(c.get('role') in ('AXTextArea', 'AXTextField') for c in children):
                    break
                timestamps = [child for child in children if child.get('role') == 'AXButton'
                              and re.match(r'^\s*\d{1,2}:\d{2}\b', child.get('label', ''))]
                statuses = [child.get('label', '') for child in children if child.get('role') == 'AXButton'
                            and re.fullmatch(r'\s*\d{1,2}:\d{2}\s+(Sent|Delivered|Read)\s*', child.get('label', ''), re.I)]
                if len(statuses) == 1:
                    found[id(ancestor)] = statuses[0]
                    break
                if timestamps:
                    # This message is pending or ambiguous; never borrow a neighbour's status.
                    break
        for child in node.get('children') or []:
            visit(child, [*ancestors, node])
    visit(tree, [])
    return {'verified': len(found) == 1, 'expected_message': expected,
            'status': next(iter(found.values())) if len(found) == 1 else None, 'matching_messages': len(found)}


def elements(result):
    if isinstance(result, list):
        return result
    return result.get('elements', result.get('matches', []))


def flatten(node, out=None):
    """Every element of a get_ui_tree result, depth first."""
    out = [] if out is None else out
    if isinstance(node, dict):
        out.append(node)
        for child in node.get('children') or []:
            flatten(child, out)
    return out


def inspection_result(tree, window_id):
    """Keep small trees intact; summarize large trees instead of cutting JSON in mid-control."""
    text = json.dumps(tree, ensure_ascii=False)
    if len(text) <= 20000:
        return {'window_id': window_id, 'tree': text, 'truncated': False}
    root = tree.get('tree', tree) if isinstance(tree, dict) else tree
    if isinstance(root, str):
        try:
            root = json.loads(root)
        except ValueError:
            return {'window_id': window_id, 'tree': json.dumps({'notice': 'Tree unavailable; use find_elements.'}),
                    'truncated': True}
    nodes = flatten(root)
    # Inputs/formula fields and actionable controls outrank decorative containers.
    ranked = sorted(enumerate(nodes), key=lambda pair: (
        0 if pair[1].get('role') in ('AXTextField', 'AXTextArea', 'AXComboBox') else
        1 if pair[1].get('actions') else 2, pair[0]))
    compact = {'elements': [], 'total_elements': len(nodes), 'omitted_elements': len(nodes),
               'notice': 'Compact tree; use find_elements for omitted labels or values.'}
    for _, node in ranked:
        if not (node.get('label') or node.get('value') is not None or node.get('actions')):
            continue
        item = {k: node[k] for k in ('role', 'label', 'value', 'bounds', 'actions') if k in node}
        item = {k: v[:500] if isinstance(v, str) else v for k, v in item.items()}
        compact['elements'].append(item)
        compact['omitted_elements'] -= 1
        if len(json.dumps(compact, ensure_ascii=False)) > 19500:
            compact['elements'].pop()
            compact['omitted_elements'] += 1
            break
    return {'window_id': window_id, 'tree': json.dumps(compact, ensure_ascii=False), 'truncated': True}


async def tree_elements(call, window_id):
    """The whole live tree as a flat list. The native search misses long labels and unlabeled fields (Sheets' Name box
    "Name box (Ctrl + J)", its formula bar), and inspect_app cuts the tree at 20000 characters."""
    tree = await call('get_ui_tree', {'window_id': window_id, 'max_depth': 20})
    if isinstance(tree, dict) and isinstance(tree.get('tree'), (dict, str)):
        tree = tree['tree']
    if isinstance(tree, str):
        tree = json.loads(tree)
    return flatten(tree)


def mentions(element, query, role=None):
    text = query.casefold()
    return (not role or element.get('role') == role) and (
        text in str(element.get('label') or '').casefold() or text in str(element.get('value') or '').casefold())


async def execute(operation, args):
    validate_call(operation, args)
    async with ComputerUseMCP().connect() as client:
        return await execute_connected(client, operation, args)


async def point_at(call, values):
    """Glide the on-screen pointer to what is about to be touched, then give the eye a moment to follow."""
    try:
        if 'x' in values and 'y' in values:
            aimed = aim({'x': values['x'], 'y': values['y'], 'width': 0, 'height': 0})
        elif values.get('window_id') and values.get('label'):
            query = {k: values[k] for k in ('window_id', 'role', 'label') if k in values}
            found = elements(await call('find_element', {**query, 'max_results': 1}))
            aimed = bool(found) and aim(found[0].get('bounds'))
        else:
            aimed = False
        if aimed:
            await asyncio.sleep(0.7)
    except Exception:
        pass  # the pointer is decoration; never let it affect the action


async def run_zavora(call, client, windows, args):
    """Generic passthrough to any Zavora tool. Approval and the tool allowlist are enforced by the caller
    (execution.py / validate_call); here we pin the target window and refuse typing into shells."""
    name, values = args['tool'], dict(args.get('arguments') or {})
    if name not in client.tools:
        raise ValueError(f'Zavora has no tool named {name}. Available: ' + ', '.join(sorted(client.tools)))
    window_id = zavora_window(args)
    if window_id is not None:
        match = [w for w in windows if w['windowId'] == window_id]
        if len(match) != 1:
            raise ValueError('Window not found. Refresh list_apps and inspect the current window.')
        if args.get('window_title') and not same_title(match[0].get('title'), args['window_title']):
            raise ValueError('Window identity changed. Refresh list_apps and inspect the current window.')
        host = f"{match[0].get('bundleId', '')} {match[0].get('title', '')}".lower()
        if name in TEXT_INPUT and any(s in host for s in SHELL_HOSTS):
            raise ValueError('Typing into a terminal or shell window is not allowed')
    if name not in READ_ONLY:
        await point_at(call, values)
    result = await call(name, values)
    if name == 'get_ui_tree':
        return {'tool': name, 'result': inspection_result(result, window_id)}
    text = json.dumps(result, ensure_ascii=False)
    return {'tool': name, 'result': result if len(text) <= 20000 else {'truncated': text[:20000]}}


async def execute_connected(client, operation, args):
    async def call(name, values):
        result = await client.call(name, values)
        if isinstance(result, dict) and (result.get('ok') is False or result.get('success') is False):
            raise RuntimeError(f'{name} refused or failed: {result}')
        return result

    windows = [w for w in (await call('list_windows', {}))['windows'] if w.get('title') != OVERLAY_TITLE]
    if operation == 'list_apps':
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            get_owner = ctypes.windll.user32.GetWindow
            get_owner.argtypes = [wintypes.HWND, wintypes.UINT]
            get_owner.restype = wintypes.HWND
            for window in windows:
                owners, owner = [], window.get('windowId')
                for _ in range(8):
                    owner = get_owner(owner, 4) if owner else None  # GW_OWNER
                    if not owner or owner in owners:
                        break
                    owners.append(int(owner))
                window['ownerWindowIds'] = owners
        return {'apps': windows, 'provider': 'zavora'}
    if operation == 'zavora':
        return await run_zavora(call, client, windows, args)
    matches = [w for w in windows if w['windowId'] == args['window_id']
               and same_title(w.get('title'), args['window_title'])]
    if len(matches) != 1:
        raise ValueError('Window identity changed. Refresh list_apps and inspect the current window.')
    window_id = args['window_id']
    if operation == 'verify_whatsapp_message':
        if 'whatsapp' not in args['window_title'].lower():
            raise ValueError('Select the live WhatsApp window to verify an outgoing message.')
        tree = await call('get_ui_tree', {'window_id': window_id, 'max_depth': 20})
        if isinstance(tree, dict) and 'tree' in tree:
            tree = tree['tree']
        if isinstance(tree, str):
            tree = json.loads(tree)
        return {**whatsapp_message_status(tree, args['expected_message']), 'window_id': window_id}
    if operation == 'inspect_app':
        tree = await call('get_ui_tree', {'window_id': window_id, 'max_depth': args.get('depth', 10)})
        return inspection_result(tree, window_id)
    if operation == 'find_elements':
        query = {'window_id': window_id, 'label': args['query'], 'max_results': 40}
        if args.get('role'):
            query['role'] = args['role']
        matches = elements(await call('find_element', query))
        if not matches:
            matches = [e for e in await tree_elements(call, window_id) if mentions(e, args['query'], args.get('role'))][:40]
        if matches:
            aim(matches[0].get('bounds'))
        return {'window_id': window_id, 'count': len(matches), 'elements': [
            {'role': m.get('role'), 'label': m.get('label'), 'value': str(m.get('value'))[:200] if m.get('value') else None}
            for m in matches[:40]]}
    if operation == 'verify_text' and not args['label']:
        # An unlabeled field (Sheets' formula bar): read every unlabeled element of that role and compare the property.
        blank = [e for e in await tree_elements(call, window_id)
                 if e.get('role') == args['role'] and not e.get('label')]
        actual = next((e.get(args['property']) for e in blank if e.get(args['property']) == args['expected']), None)
        if actual is None and blank:
            actual = blank[0].get(args['property'])
        return {'verified': actual == args['expected'] and actual is not None, 'actual': actual,
                'expected': args['expected'], 'window_id': window_id,
                'candidates': [str(e.get(args['property']))[:80] for e in blank[:6]]}
    found = elements(await call('find_element', {'window_id': window_id,
        'role': args['role'], 'label': args['label'], 'max_results': 100}))
    # MCP search is substring-based; require a single result with exact role/label.
    # A broader native action matcher must also see only that one candidate.
    if operation == 'verify_text':
        # Reading is harmless: substring noise (other tabs, partial labels) must not hide the one exact element.
        found = [f for f in found if f.get('role') == args['role'] and f.get('label') == args['label']]
    if len(found) != 1 or found[0].get('role') != args['role'] or found[0].get('label') != args['label']:
        raise ValueError('Target must match exactly one element with the exact role and label')
    if operation == 'verify_text':
        actual = found[0].get(args['property'])
        return {'verified': actual == args['expected'], 'actual': actual,
                'expected': args['expected'], 'window_id': window_id}
    if aim(found[0].get('bounds')):
        await asyncio.sleep(0.7)
    native = {'window_id': window_id, 'label': args['label'], 'focus_strategy': 'strict'}
    action = args['action']
    if action != 'press_button':
        native['role'] = args['role']
    else:
        buttons = elements(await call('find_element', {'window_id': window_id,
            'label': args['label'], 'max_results': 100}))
        if len(buttons) != 1:
            raise ValueError('Button label is ambiguous')
    if action == 'set_value':
        native['value'] = args['value']
    result = await call(action, native)
    return {'performed': action, 'result': result, 'note': 'Verify the resulting state separately.'}


async def serve():
    """Start Zavora once, then answer requests until stdin closes. After an unexpected failure (a broken MCP
    connection, a timeout) the worker says so and exits, so the caller starts a fresh one."""
    loop = asyncio.get_running_loop()
    async with ComputerUseMCP().connect() as client:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line.strip():
                if line:
                    continue
                return
            fatal = False
            try:
                request = json.loads(line)
                validate_call(request['operation'], request['arguments'])
                reply = {'ok': True, 'result': await execute_connected(client, request['operation'], request['arguments'])}
            except (ValueError, RuntimeError, ValidationError) as exc:
                reply = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
            except Exception as exc:
                reply, fatal = {'ok': False, 'error': f'{type(exc).__name__}: {exc}', 'fatal': True}, True
            print(json.dumps(reply, ensure_ascii=False), flush=True)
            if fatal:
                return


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        asyncio.run(serve())
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': f'{type(exc).__name__}: {exc}', 'fatal': True}, ensure_ascii=False), flush=True)
        sys.exit(1)
