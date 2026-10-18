"""Validated tool definitions and killable desktop calls, without shell access."""
import asyncio
import json
import sys
import os
import subprocess
import webbrowser
from pathlib import Path
from jsonschema import validate


def schema(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required,
            'additionalProperties': False}


TARGET = {'window_id': {'type': 'integer', 'minimum': 1},
          'window_title': {'type': 'string', 'minLength': 1, 'maxLength': 2000}}
ELEMENT = {'role': {'type': 'string', 'minLength': 1, 'maxLength': 100},
           'label': {'type': 'string', 'minLength': 1, 'maxLength': 1000}}
TOOLS = {
    'verify_whatsapp_message': ('Verify one outgoing WhatsApp message by its exact text, or a unique PDF filename, and the Sent/Delivered/Read status inside the same message group. Read-only; use this when timestamp/status labels repeat.',
        schema({**TARGET, 'expected_message': {'type': 'string', 'minLength': 1, 'maxLength': 2500}},
               [*TARGET, 'expected_message'])),
    'list_apps': ('List live desktop windows, with windowId, pid and exact title.', schema({}, [])),
    'inspect_app': ('Read the live Zavora accessibility tree of one window. Use observed AX roles and labels.',
        schema({**TARGET, 'depth': {'type': 'integer', 'minimum': 1, 'maximum': 15}}, list(TARGET))),
    'find_elements': ('Search one window for elements whose label OR value contains the query (optionally one role), '
                      'case-insensitive, over the whole tree. '
                      'Prefer this to inspect_app on large web pages like Gmail or Sheets: the full tree gets truncated. '
                      'Returns exact roles, labels and values to use with act and verify_text.',
        schema({**TARGET, 'query': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                'role': {'type': 'string', 'minLength': 1, 'maxLength': 100}}, [*TARGET, 'query'])),
    'act': ('Propose one Zavora desktop change; exact arguments require user approval. '
            'Use the current exact window title and a unique observed role/label. No CSS selectors.',
        schema({**TARGET, **ELEMENT,
                'action': {'type': 'string', 'enum': ['set_value', 'press_button', 'click_element']},
                'value': {'type': 'string', 'maxLength': 20000},
                'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1000}},
               [*TARGET, *ELEMENT, 'action', 'reason'])),
    'zavora': ('Call ANY tool of the Zavora computer-use server (name + its own arguments). Read-only tools '
               '(list_windows, get_ui_tree, find_element, wait, get_focused_element...) run immediately. '
               'Every tool that changes the desktop (click_element, set_value, fill_form, press_button, '
               'type, key, click, scroll, activate_window...) needs one user approval with a clear reason. '
               'Prefer AX tools (click_element, set_value, fill_form, press_button) over raw type/key/click; '
               'raw input tools must include target_window_id. Pass window_title when the call has a window.',
        schema({'tool': {'type': 'string', 'minLength': 1, 'maxLength': 80},
                'arguments': {'type': 'object'},
                'window_title': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
                'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1000}}, ['tool', 'arguments', 'reason'])),
    'open_url': ('Propose opening an http(s) page in the default browser, to bring a web app such as Gmail '
                 'to the active tab. Requires user approval. Call list_apps afterwards.',
        schema({'url': {'type': 'string', 'minLength': 8, 'maxLength': 2000, 'pattern': '^https?://'},
                'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1000}}, ['url', 'reason'])),
    'launch_app': ('Start Notepad or File Explorer when the workflow needs it and it is not open. Requires user approval. '
                   'Call list_apps afterwards and inspect the new window. Other programs cannot be started.',
        schema({'app': {'type': 'string', 'enum': ['notepad', 'file_explorer']},
                'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1000}}, ['app', 'reason'])),
    'verify_text': ('Read a unique live element through Zavora and compare exact value or label. '
                    'Use the CURRENT window title; Notepad may prepend * after an edit. Some fields have no label '
                    '(the Google Sheets formula bar is an unlabeled AXTextField): pass label "" and property value.',
        schema({**TARGET, **ELEMENT, 'label': {'type': 'string', 'maxLength': 1000},
                'property': {'type': 'string', 'enum': ['value', 'label']},
                'expected': {'type': 'string', 'maxLength': 20000}},
               [*TARGET, *ELEMENT, 'property', 'expected'])),
}


# Zavora tools that only observe. Anything else the server offers is treated as a desktop change.
READ_ONLY = {'list_windows', 'get_ui_tree', 'find_element', 'get_window', 'get_focused_element', 'get_frontmost_app',
             'list_running_apps', 'discover_applications', 'get_target', 'set_target', 'control_status', 'wait',
             'wait_for_window', 'get_display_size', 'list_displays', 'cursor_position', 'get_cursor_window',
             'get_app_capabilities', 'get_tool_guide', 'get_tool_metadata', 'agent_pointer'}
# Never available: they start arbitrary programs or move data out of band (no shell, no clipboard, no images).
DENIED = {'open_application', 'select_menu_item', 'read_clipboard', 'write_clipboard', 'screenshot', 'zoom',
          'doctor', 'policy_status', 'hold_key'}
# Raw input goes to whatever window is in front unless a target window is named, so one is required.
RAW_INPUT = {'click', 'double_click', 'triple_click', 'left_click', 'right_click', 'middle_click', 'type', 'key',
             'scroll', 'mouse_move', 'mouse_drag', 'left_click_drag', 'left_mouse_down', 'left_mouse_up'}
TEXT_INPUT = {'type', 'key'}
SHELL_HOSTS = ('powershell', 'pwsh', 'cmd.exe', 'windowsterminal', 'conhost', 'wt.exe', 'wsl', 'bash')
# Changes that do not act inside an already-inspected window.
NO_INSPECT = {'activate_window', 'activate_app', 'hide_app', 'unhide_app', 'resize_window'}


def zavora_window(args):
    values = args.get('arguments') or {}
    return values.get('window_id', values.get('target_window_id'))


def tools():
    return [{'type': 'function', 'function': {'name': name, 'description': description,
             'parameters': parameters}} for name, (description, parameters) in TOOLS.items()]


def validate_call(name, args):
    if name not in TOOLS:
        raise ValueError('Unknown desktop tool')
    validate(args, TOOLS[name][1])
    if name == 'zavora':
        if args['tool'] in DENIED:
            raise ValueError(f"Tool {args['tool']} is not available to the agent")
        if args['tool'] in RAW_INPUT and (args['arguments'] or {}).get('target_window_id') is None:
            raise ValueError(f"{args['tool']} needs target_window_id so input cannot land in the wrong window")
    if name == 'act' and args['action'] == 'set_value' and 'value' not in args:
        raise ValueError('Text actions require a value')
    if name == 'act' and args['action'] == 'press_button' and args['role'] != 'AXButton':
        raise ValueError('press_button requires an AXButton')


async def open_url(url):
    """Open an already-approved http(s) URL in the default browser (a new tab becomes the active one)."""
    validate_call('open_url', {'url': url, 'reason': 'open'})
    if not await asyncio.to_thread(webbrowser.open, url, 2):
        raise RuntimeError('No browser could be opened')
    return {'opened': url}


# The only programs the agent may start, with no arguments, so it can never run a script or open an arbitrary file.
LAUNCHABLE = {'notepad': 'notepad.exe', 'file_explorer': 'explorer.exe'}


async def launch_app(app):
    """Start an already-approved, allow-listed program with no arguments."""
    validate_call('launch_app', {'app': app, 'reason': 'launch'})
    await asyncio.to_thread(subprocess.Popen, [LAUNCHABLE[app]])
    return {'launched': app}


IDLE_SECONDS = 60


class Worker:
    """One long-lived Zavora worker, so the server starts once instead of on every call (about 2 s each).

    Safety is unchanged: a timeout, a cancel or a stop kills the whole process tree, and the next call starts a
    fresh one. It also exits by itself after a minute without use.
    """
    def __init__(self):
        self.process = None
        self.loop = None
        self.lock = None
        self.timer = None

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'backend.desktop_worker',
            cwd=str(Path(__file__).resolve().parent.parent), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=2 ** 24)

    async def kill(self):
        process, self.process = self.process, None
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if process is None or process.returncode is not None:
            return
        if os.name == 'nt':
            killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(process.pid),
                '/T', '/F', stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await killer.wait()
        if process.returncode is None:
            process.kill()
        await process.wait()
        try:
            process.stdin.close()
        except Exception:
            pass

    def reap_later(self, loop):
        self.timer = loop.call_later(IDLE_SECONDS, lambda: setattr(self, 'reaper', loop.create_task(self.kill())))

    async def call(self, request, timeout):
        loop = asyncio.get_running_loop()
        if self.loop is not loop:
            # A new event loop cannot reuse the old process objects.
            if self.process is not None and self.process.returncode is None:
                self.process.kill()
            self.process, self.loop, self.lock, self.timer = None, loop, asyncio.Lock(), None
        async with self.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None
            try:
                async with asyncio.timeout(timeout):
                    if self.process is None or self.process.returncode is not None:
                        await self.start()
                    self.process.stdin.write((json.dumps(request, ensure_ascii=False) + chr(10)).encode('utf-8'))
                    await self.process.stdin.drain()
                    line = await self.process.stdout.readline()
                if not line:
                    raise RuntimeError('The desktop worker stopped unexpectedly')
                response = json.loads(line.decode('utf-8'))
            except BaseException:
                # Cancellation/timeout kills the native call, preventing delayed future actions.
                await asyncio.shield(self.kill())
                raise
            if response.get('fatal'):
                await self.kill()
            else:
                self.reap_later(loop)
            if not response.get('ok'):
                raise RuntimeError(response.get('error', 'Desktop call failed'))
            return response['result']


WORKER = Worker()


async def close_desktop():
    """Stop the worker (end of a run, shutdown)."""
    await WORKER.kill()


async def call_desktop(name, args, timeout=20):
    validate_call(name, args)
    return await WORKER.call({'operation': name, 'arguments': args}, timeout)
