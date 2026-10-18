import asyncio
import json
from types import SimpleNamespace
import pytest
from openai.types.chat import ChatCompletionMessage
from backend.config import Settings
from backend.models import ExecutionRequest, Reconstruction, TaskOccurrence
from backend.repository import Repository
from backend.execution import ExecutionManager
from backend.desktop import validate_call, call_desktop
import backend.desktop as desktop
import backend.execution as execution

EVIDENCE = [{'call_id': 'e1', 'quote': 'hello world', 'source_kind': 'original_activity'}]
TASK = TaskOccurrence(id='chosen', title='Edit Notepad', timestamp='2026-10-16T20:03:40+02:00',
    summary='Edited hello world', evidence=EVIDENCE)
WORKFLOW = Reconstruction(goal='Write hello world', historical_values={},
    steps=[{'description': 'Write hello world', 'evidence': EVIDENCE}], missing_values=[], evidence=EVIDENCE)


def call(name, arguments):
    return ChatCompletionMessage(role='assistant', tool_calls=[{'id': name, 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(arguments)}}])


class Client:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=next(self.messages))])

    async def close(self):
        pass


def test_approval_precedes_mutation_and_verification_precedes_completion(tmp_path, monkeypatch):
    async def scenario():
        client = Client([
            call('inspect_app', {'window_id': 1, 'window_title': 'Test'}),
            call('act', {'window_id': 1, 'window_title': 'Test', 'role': 'AXWebArea', 'label': 'Editor', 'action': 'set_value',
                         'value': 'hello world', 'reason': 'Write the selected text'}),
            ChatCompletionMessage(role='assistant', content='{"outcome":"completed","summary":"Too early"}'),
            call('verify_text', {'window_id': 1, 'window_title': 'Test', 'role': 'AXWebArea', 'label': 'Editor', 'property': 'value', 'expected': 'hello world'}),
            ChatCompletionMessage(role='assistant', content='{"outcome":"completed","summary":"Text verified"}')])
        monkeypatch.setattr(execution.Agent, 'create_client', lambda self: client)
        performed = []
        async def desktop(name, args, timeout):
            performed.append(name)
            return {'verified': True} if name == 'verify_text' else {'tree': 'text_field'}
        monkeypatch.setattr(execution, 'call_desktop', desktop)
        manager = ExecutionManager(Settings(), Repository(tmp_path))
        run = manager.start(TASK, WORKFLOW, ExecutionRequest())
        for _ in range(100):
            if run['status'] == 'awaiting_approval':
                break
            await asyncio.sleep(0)
        assert performed == ['inspect_app']
        pending = run['pending_action']['id']
        with pytest.raises(ValueError):
            manager.decide(run['id'], 'stale-token', True)
        manager.decide(run['id'], pending, True)
        with pytest.raises(ValueError):
            manager.decide(run['id'], pending, True)
        await manager.workers[run['id']]
        assert performed == ['inspect_app', 'act', 'verify_text']
        assert run['status'] == 'completed'
        assert run['summary'] == 'Text verified'
        restored = ExecutionManager(Settings(), Repository(tmp_path))
        assert restored.runs[run['id']]['status'] == 'completed'
    asyncio.run(scenario())


def test_decline_and_stop_never_apply_pending_action(tmp_path, monkeypatch):
    async def scenario():
        performed = []
        async def desktop(name, args, timeout):
            performed.append(name)
            return {}
        monkeypatch.setattr(execution, 'call_desktop', desktop)
        for approve_or_stop in ('decline', 'stop'):
            client = Client([call('inspect_app', {'window_id': 1, 'window_title': 'Test'}), call('act', {
                'window_id': 1, 'window_title': 'Test', 'role': 'AXButton', 'label': 'OK', 'action': 'press_button', 'reason': 'Test'})])
            monkeypatch.setattr(execution.Agent, 'create_client', lambda self: client)
            manager = ExecutionManager(Settings(), Repository(tmp_path / approve_or_stop))
            run = manager.start(TASK, WORKFLOW, ExecutionRequest())
            for _ in range(100):
                if run['status'] == 'awaiting_approval':
                    break
                await asyncio.sleep(0)
            with pytest.raises(ValueError, match='active'):
                manager.start(TASK, WORKFLOW, ExecutionRequest())
            worker = manager.workers[run['id']]
            if approve_or_stop == 'decline':
                manager.decide(run['id'], run['pending_action']['id'], False)
                await worker
            else:
                await manager.stop(run['id'])
            assert run['status'] == 'cancelled'
            assert 'act' not in performed
    asyncio.run(scenario())


def test_open_url_needs_approval_then_agent_continues(tmp_path, monkeypatch):
    async def scenario():
        client = Client([
            call('open_url', {'url': 'https://mail.google.com/mail/u/0/#inbox', 'reason': 'Gmail is not the active tab'}),
            call('list_apps', {}),
            ChatCompletionMessage(role='assistant', content='{"outcome":"blocked","summary":"stop here"}')])
        monkeypatch.setattr(execution.Agent, 'create_client', lambda self: client)
        opened, performed = [], []
        async def fake_open(url):
            opened.append(url)
            return {'opened': url}
        async def desktop(name, args, timeout):
            performed.append(name)
            return {'apps': []}
        original_sleep = asyncio.sleep
        async def no_sleep(_):
            await original_sleep(0)  # still yield to the execution worker
        monkeypatch.setattr(execution, 'open_url', fake_open)
        monkeypatch.setattr(execution, 'call_desktop', desktop)
        monkeypatch.setattr(execution.asyncio, 'sleep', no_sleep)
        manager = ExecutionManager(Settings(), Repository(tmp_path))
        run = manager.start(TASK, WORKFLOW, ExecutionRequest())
        while run['status'] != 'awaiting_approval':
            await asyncio.sleep(0)
        assert opened == [] and run['pending_action']['tool'] == 'open_url'
        manager.decide(run['id'], run['pending_action']['id'], True)
        await manager.workers[run['id']]
        assert opened == ['https://mail.google.com/mail/u/0/#inbox'] and performed == ['list_apps']
        assert run['status'] == 'blocked'
    asyncio.run(scenario())


def test_open_url_rejects_non_http_schemes():
    for bad in ('file:///C:/Windows/System32/calc.exe', 'javascript:alert(1)', 'calc.exe'):
        with pytest.raises(Exception):
            validate_call('open_url', {'url': bad, 'reason': 'x'})


def test_launch_app_needs_approval_then_agent_continues(tmp_path, monkeypatch):
    async def scenario():
        client = Client([
            call('launch_app', {'app': 'notepad', 'reason': 'Notepad is not open'}),
            call('list_apps', {}),
            ChatCompletionMessage(role='assistant', content='{"outcome":"blocked","summary":"stop here"}')])
        monkeypatch.setattr(execution.Agent, 'create_client', lambda self: client)
        launched, performed = [], []
        async def fake_launch(app):
            launched.append(app)
            return {'launched': app}
        async def desktop(name, args, timeout):
            performed.append(name)
            return {'apps': []}
        original_sleep = asyncio.sleep
        async def no_sleep(_):
            await original_sleep(0)
        monkeypatch.setattr(execution, 'launch_app', fake_launch)
        monkeypatch.setattr(execution, 'call_desktop', desktop)
        monkeypatch.setattr(execution.asyncio, 'sleep', no_sleep)
        manager = ExecutionManager(Settings(), Repository(tmp_path))
        run = manager.start(TASK, WORKFLOW, ExecutionRequest())
        while run['status'] != 'awaiting_approval':
            await asyncio.sleep(0)
        assert launched == [] and run['pending_action']['tool'] == 'launch_app'
        manager.decide(run['id'], run['pending_action']['id'], True)
        await manager.workers[run['id']]
        assert launched == ['notepad'] and performed == ['list_apps']
    asyncio.run(scenario())


def test_declined_launch_starts_nothing(tmp_path, monkeypatch):
    async def scenario():
        client = Client([call('launch_app', {'app': 'notepad', 'reason': 'Notepad is not open'})])
        monkeypatch.setattr(execution.Agent, 'create_client', lambda self: client)
        launched = []
        async def fake_launch(app):
            launched.append(app)
            return {}
        monkeypatch.setattr(execution, 'launch_app', fake_launch)
        manager = ExecutionManager(Settings(), Repository(tmp_path))
        run = manager.start(TASK, WORKFLOW, ExecutionRequest())
        while run['status'] != 'awaiting_approval':
            await asyncio.sleep(0)
        manager.decide(run['id'], run['pending_action']['id'], False)
        await manager.workers[run['id']]
        assert launched == [] and run['status'] == 'cancelled'
    asyncio.run(scenario())


def test_launch_app_only_allows_listed_programs_without_arguments():
    for bad in ('cmd', 'powershell.exe', 'notepad.exe C:\\secret.txt', 'calc'):
        with pytest.raises(Exception):
            validate_call('launch_app', {'app': bad, 'reason': 'x'})
    with pytest.raises(Exception):
        validate_call('launch_app', {'app': 'notepad', 'reason': 'x', 'arguments': 'C:\\secret.txt'})
    validate_call('launch_app', {'app': 'notepad', 'reason': 'x'})
    validate_call('launch_app', {'app': 'file_explorer', 'reason': 'x'})


def test_the_prompt_lets_the_agent_recover_from_a_closed_app():
    assert 'launch_app' in execution.PROMPT and 'NEVER a reason to block' in execution.PROMPT
    assert 'The user opens the target application' not in execution.PROMPT


def test_missing_values_and_interrupted_recovery(tmp_path):
    repository = Repository(tmp_path)
    workflow = WORKFLOW.model_copy(update={'missing_values': ['Recipient']})
    manager = ExecutionManager(Settings(), repository)
    with pytest.raises(ValueError, match='Recipient'):
        manager.start(TASK, workflow, ExecutionRequest())
    repository.write('runs', {'run': {'status': 'awaiting_approval'}})
    recovered = ExecutionManager(Settings(), repository)
    assert recovered.runs['run']['status'] == 'interrupted'
    assert recovered.runs['run']['pending_action'] is None


def test_desktop_schema_blocks_unknown_tools_and_missing_text():
    with pytest.raises(ValueError):
        validate_call('shell', {'command': 'whoami'})
    with pytest.raises(ValueError, match='require'):
        validate_call('act', {'window_id': 1, 'window_title': 'Test', 'role': 'AXWebArea', 'label': 'Editor', 'action': 'set_value', 'reason': 'Test'})


class FakeProcess:
    """Stands in for the worker process: replies to each request line with the next canned reply."""
    pid = 123456

    def __init__(self, replies=(), hang=False):
        self.replies, self.hang, self.returncode, self.killed, self.sent = list(replies), hang, None, False, []
        self.stdin = SimpleNamespace(write=lambda data: self.sent.append(json.loads(data)), drain=self.drain)
        self.stdout = SimpleNamespace(readline=self.readline)

    async def drain(self):
        pass

    async def readline(self):
        if self.hang:
            await asyncio.sleep(100)
        return (json.dumps(self.replies.pop(0)) + chr(10)).encode()

    def kill(self):
        self.killed, self.returncode = True, -1

    async def wait(self):
        self.returncode = -1


def fake_spawn(monkeypatch, *processes):
    spawned = []
    queue = list(processes)

    async def spawn(*args, **kwargs):
        if args[0] == 'taskkill':
            return FakeProcess()
        spawned.append(args)
        return queue.pop(0)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(desktop, 'WORKER', desktop.Worker())
    return spawned


def test_desktop_timeout_kills_worker(monkeypatch):
    process = FakeProcess(hang=True)
    fake_spawn(monkeypatch, process)
    with pytest.raises(TimeoutError):
        asyncio.run(call_desktop('list_apps', {}, timeout=.01))
    assert process.killed and desktop.WORKER.process is None


def test_the_worker_is_started_once_and_reused(monkeypatch):
    process = FakeProcess([{'ok': True, 'result': {'n': 1}}, {'ok': True, 'result': {'n': 2}}])
    spawned = fake_spawn(monkeypatch, process)

    async def scenario():
        first = await call_desktop('list_apps', {}, 5)
        second = await call_desktop('list_apps', {}, 5)
        await desktop.close_desktop()
        return first, second
    assert asyncio.run(scenario()) == ({'n': 1}, {'n': 2})
    assert len(spawned) == 1 and len(process.sent) == 2 and process.killed


def test_a_fatal_worker_reply_restarts_it_on_the_next_call(monkeypatch):
    broken = FakeProcess([{'ok': False, 'error': 'TimeoutError: ', 'fatal': True}])
    fresh = FakeProcess([{'ok': True, 'result': {'n': 2}}])
    spawned = fake_spawn(monkeypatch, broken, fresh)

    async def scenario():
        with pytest.raises(RuntimeError, match='TimeoutError'):
            await call_desktop('list_apps', {}, 5)
        result = await call_desktop('list_apps', {}, 5)
        await desktop.close_desktop()
        return result
    assert asyncio.run(scenario()) == {'n': 2}
    assert len(spawned) == 2 and broken.killed


def test_an_ordinary_error_keeps_the_worker(monkeypatch):
    process = FakeProcess([{'ok': False, 'error': 'ValueError: Target must match'}, {'ok': True, 'result': {}}])
    spawned = fake_spawn(monkeypatch, process)

    async def scenario():
        with pytest.raises(RuntimeError, match='Target must match'):
            await call_desktop('list_apps', {}, 5)
        assert not process.killed
        await call_desktop('list_apps', {}, 5)
        assert not process.killed
        await desktop.close_desktop()
    asyncio.run(scenario())
    assert len(spawned) == 1 and process.killed


def test_window_titles_tolerate_a_changing_unread_counter_and_the_edit_star():
    from backend.desktop_worker import same_title
    assert same_title('(6) WhatsApp - Google Chrome', '(7) WhatsApp - Google Chrome')
    assert same_title('report.txt - Notepad', '*report.txt - Notepad')
    assert not same_title('WhatsApp - Google Chrome', 'Gmail - Google Chrome')


def test_saving_does_not_force_a_content_verification(tmp_path, monkeypatch):
    async def scenario():
        client = Client([
            call('inspect_app', {'window_id': 1, 'window_title': 'report.txt - Notepad'}),
            call('verify_text', {'window_id': 1, 'window_title': 'report.txt - Notepad', 'role': 'AXWebArea', 'label': 'Text editor', 'property': 'value', 'expected': 'hello world'}),
            call('zavora', {'tool': 'key', 'arguments': {'text': 'ctrl+s', 'target_window_id': 1}, 'window_title': 'report.txt - Notepad', 'reason': 'Save'}),
            call('list_apps', {}),
            ChatCompletionMessage(role='assistant', content='{"outcome":"completed","summary":"Saved"}')])
        monkeypatch.setattr(execution.Agent, 'create_client', lambda self: client)
        performed = []
        async def fake_desktop(name, args, timeout):
            performed.append(name)
            return {'verified': True} if name == 'verify_text' else {'tree': 'x', 'apps': []}
        monkeypatch.setattr(execution, 'call_desktop', fake_desktop)
        manager = ExecutionManager(Settings(), Repository(tmp_path))
        run = manager.start(TASK, WORKFLOW, ExecutionRequest(auto_approve=True))
        await manager.workers[run['id']]
        assert run['status'] == 'completed', run['summary']
        assert performed == ['inspect_app', 'verify_text', 'zavora', 'list_apps']
    asyncio.run(scenario())


def test_api_origin_and_selection_guards():
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as client:
        assert client.post('/tasks/missing/execute', json={}).status_code == 409
        assert client.get('/runs/missing').status_code == 404
        assert client.post('/runs/missing/stop', json={}, headers={'origin': 'https://foreign.example'}).status_code == 403
        assert client.get('/health', headers={'host': 'foreign.example'}).status_code == 400


def test_native_worker_refuses_ambiguous_target():
    from backend.desktop_worker import execute_connected
    class MCP:
        async def call(self, name, args):
            if name == 'list_windows':
                return {'windows': [{'windowId': 1, 'title': 'Test'}]}
            if name == 'find_element':
                return [{'role': 'AXWebArea', 'label': 'Editor'}] * 2
            pytest.fail('Ambiguous action must not run')
    with pytest.raises(ValueError, match='exactly one'):
        asyncio.run(execute_connected(MCP(), 'act', {'window_id': 1, 'window_title': 'Test',
            'role': 'AXWebArea', 'label': 'Editor', 'action': 'set_value', 'value': 'hello world'}))


def test_atomic_store_and_task_expiry_roundtrip(tmp_path, monkeypatch):
    import time
    import backend.main as main
    repository = Repository(tmp_path)
    monkeypatch.setattr(main, 'repository', repository)
    main.tasks['chosen'] = {'task': TASK, 'ledger': {'e1': {'text': 'hello world'}},
        'workflow': WORKFLOW.model_dump(mode='json'), 'expires': time.monotonic() + 60}
    main.persist_tasks()
    main.tasks.clear()
    main.load_tasks()
    assert main.tasks['chosen']['task'] == TASK
    assert main.tasks['chosen']['workflow']['goal'] == WORKFLOW.goal
    assert 0 < main.tasks['chosen']['expires'] - time.monotonic() <= 60
    assert not list(tmp_path.glob('*.tmp'))


def test_zavora_worker_refuses_changed_window_identity():
    from backend.desktop_worker import execute_connected
    class MCP:
        async def call(self, name, args):
            assert name == 'list_windows'
            return {'windows': [{'windowId': 1, 'title': 'Different document'}]}
    with pytest.raises(ValueError, match='identity changed'):
        asyncio.run(execute_connected(MCP(), 'act', {'window_id': 1, 'window_title': 'Test',
            'role': 'AXWebArea', 'label': 'Editor', 'action': 'set_value', 'value': 'hello world'}))


def test_zavora_worker_rejects_substring_label_match():
    from backend.desktop_worker import execute_connected
    class MCP:
        async def call(self, name, args):
            if name == 'list_windows':
                return {'windows': [{'windowId': 1, 'title': 'Test'}]}
            if name == 'find_element':
                return [{'role': 'AXWebArea', 'label': 'Editor for another field'}]
            pytest.fail('Substring match must not mutate')
    with pytest.raises(ValueError, match='exact role and label'):
        asyncio.run(execute_connected(MCP(), 'act', {'window_id': 1, 'window_title': 'Test',
            'role': 'AXWebArea', 'label': 'Editor', 'action': 'set_value', 'value': 'hello world'}))


def run_script(tmp_path, monkeypatch, script, desktop_replies):
    """Drive one run with canned model messages; return (run, names of desktop calls performed, tool errors)."""
    async def scenario():
        client = Client(script)
        monkeypatch.setattr(execution.Agent, 'create_client', lambda self: client)
        performed = []

        async def fake_desktop(name, args, timeout):
            performed.append(name)
            return desktop_replies(name, args)
        monkeypatch.setattr(execution, 'call_desktop', fake_desktop)
        manager = ExecutionManager(Settings(), Repository(tmp_path))
        run = manager.start(TASK, WORKFLOW, ExecutionRequest(auto_approve=True))
        await manager.workers[run['id']]
        return run, performed, [e['detail']['error'] for e in run['events'] if e['kind'] == 'error']
    return asyncio.run(scenario())


CLICK = call('act', {'window_id': 1, 'window_title': 'Test', 'role': 'AXButton', 'label': 'OK', 'action': 'press_button', 'reason': 'Press OK'})
INSPECT = call('inspect_app', {'window_id': 1, 'window_title': 'Test'})
APPS = lambda name, args: {'apps': [{'windowId': 1, 'title': 'Test'}]} if name == 'list_apps' else {'tree': 'x', 'verified': True}


def test_looking_at_the_changed_window_again_unblocks_the_next_step(tmp_path, monkeypatch):
    run, performed, errors = run_script(tmp_path, monkeypatch, [
        INSPECT, CLICK, INSPECT, CLICK,
        ChatCompletionMessage(role='assistant', content='{"outcome":"blocked","summary":"done for now"}')], APPS)
    assert errors == [] and performed.count('act') == 2


def test_an_unchecked_change_still_blocks_the_next_one(tmp_path, monkeypatch):
    run, performed, errors = run_script(tmp_path, monkeypatch, [
        INSPECT, CLICK, CLICK,
        ChatCompletionMessage(role='assistant', content='{"outcome":"blocked","summary":"stop"}')], APPS)
    assert any('Verify the previous change' in e for e in errors) and performed.count('act') == 1


def test_finishing_still_needs_a_successful_verification_after_the_last_change(tmp_path, monkeypatch):
    run, performed, errors = run_script(tmp_path, monkeypatch, [
        INSPECT, CLICK, INSPECT,
        ChatCompletionMessage(role='assistant', content='{"outcome":"completed","summary":"Too early"}'),
        ChatCompletionMessage(role='assistant', content='{"outcome":"blocked","summary":"gave up"}')], APPS)
    assert run['status'] == 'blocked' and run['summary'] == 'gave up'


def test_a_closed_window_does_not_leave_the_run_waiting_for_a_check(tmp_path, monkeypatch):
    gone = lambda name, args: {'apps': [{'windowId': 2, 'title': 'Other'}]} if name == 'list_apps' else {'tree': 'x'}
    launched = []

    async def fake_launch(app):
        launched.append(app)
        return {'launched': app}
    monkeypatch.setattr(execution, 'launch_app', fake_launch)
    run, performed, errors = run_script(tmp_path, monkeypatch, [
        INSPECT, CLICK, call('list_apps', {}),
        call('launch_app', {'app': 'notepad', 'reason': 'Open Notepad'}),
        ChatCompletionMessage(role='assistant', content='{"outcome":"blocked","summary":"stop"}')],
        gone)
    assert not any('Verify the previous change' in e for e in errors) and launched == ['notepad']


def test_the_prompt_ignores_melon_window_steps_and_skips_explorer_for_new_files():
    assert 'Ignore any step about the Melon window' in execution.PROMPT
    assert 'do NOT use File Explorer or the desktop' in execution.PROMPT


KEY = lambda text: call('zavora', {'tool': 'key', 'arguments': {'text': text, 'target_window_id': 1}, 'window_title': 'Test', 'reason': 'Press ' + text})
TYPE = lambda text: call('zavora', {'tool': 'type', 'arguments': {'text': text, 'press_enter': True, 'target_window_id': 1}, 'window_title': 'Test', 'reason': 'Type ' + text})


def test_keystrokes_into_one_window_follow_each_other_without_a_check(tmp_path, monkeypatch):
    # Sheets: ctrl+j (Name box), the cell reference, then the formula are one typed sequence.
    run, performed, errors = run_script(tmp_path, monkeypatch, [
        INSPECT, KEY('ctrl+j'), TYPE('B26'), TYPE('=SUM(B19:B25)'),
        ChatCompletionMessage(role='assistant', content='{"outcome":"blocked","summary":"stop"}')], APPS)
    assert errors == [] and performed.count('zavora') == 3


def test_another_kind_of_change_after_typing_still_needs_a_check(tmp_path, monkeypatch):
    run, performed, errors = run_script(tmp_path, monkeypatch, [
        INSPECT, TYPE('hello'), CLICK,
        ChatCompletionMessage(role='assistant', content='{"outcome":"blocked","summary":"stop"}')], APPS)
    assert any('Verify the previous change' in e for e in errors) and performed.count('act') == 0


def test_the_prompt_teaches_entering_a_formula_in_sheets():
    text = ' '.join(execution.PROMPT.split())
    assert 'ctrl+j' in text and 'review-only result is not completed' in text


SHEET_TREE = {'role': 'AXWindow', 'label': 'Sheet', 'value': None, 'children': [
    {'role': 'AXGroup', 'label': 'Name box (Ctrl + J)', 'value': None, 'children': []},
    {'role': 'AXTextField', 'label': '', 'value': 'B26', 'children': []},
    {'role': 'AXTextField', 'label': '', 'value': '=SUM(B19:B25)', 'children': []}]}


class SheetMCP:
    async def call(self, name, args):
        if name == 'list_windows':
            return {'windows': [{'windowId': 1, 'title': 'Test'}]}
        if name == 'find_element':
            return []  # the native search misses long labels and unlabeled fields
        assert name == 'get_ui_tree'
        return SHEET_TREE


def test_finding_elements_falls_back_to_the_whole_tree_by_label_or_value():
    from backend.desktop_worker import execute_connected
    found = asyncio.run(execute_connected(SheetMCP(), 'find_elements', {'window_id': 1, 'window_title': 'Test', 'query': 'name box'}))
    assert [e['label'] for e in found['elements']] == ['Name box (Ctrl + J)']
    by_value = asyncio.run(execute_connected(SheetMCP(), 'find_elements', {'window_id': 1, 'window_title': 'Test', 'query': '=sum(', 'role': 'AXTextField'}))
    assert [e['value'] for e in by_value['elements']] == ['=SUM(B19:B25)']


def test_an_unlabeled_field_can_be_verified_by_its_value():
    from backend.desktop_worker import execute_connected
    ask = lambda expected: asyncio.run(execute_connected(SheetMCP(), 'verify_text', {
        'window_id': 1, 'window_title': 'Test', 'role': 'AXTextField', 'label': '', 'property': 'value', 'expected': expected}))
    assert ask('=SUM(B19:B25)')['verified'] is True
    wrong = ask('=SUM(B1:B2)')
    assert wrong['verified'] is False and '=SUM(B19:B25)' in wrong['candidates']


def test_sheets_run_repairs_model_titles_and_search_before_approval(tmp_path, monkeypatch):
    async def scenario():
        title = 'Budget - Google Sheets - Google Chrome'
        short = 'Budget - Google Chrome'
        client = Client([
            call('list_apps', {}),
            call('inspect_app', {'window_id': 7, 'window_title': short}),
            call('zavora', {'tool': 'find_element', 'arguments': {'window_id': 7, 'query': 'Name box'},
                            'window_title': short, 'reason': 'Locate the name box'}),
            call('zavora', {'tool': 'type', 'arguments': {'target_window_id': 7, 'text': '=SUM(B19:B25)', 'press_enter': True},
                            'window_title': short, 'reason': 'Set the selected total cell'}),
            call('verify_text', {'window_id': 7, 'window_title': short, 'role': 'AXTextField',
                                 'label': '', 'property': 'value', 'expected': '=SUM(B19:B25)'}),
            ChatCompletionMessage(role='assistant', content='{"outcome":"completed","summary":"Formula verified"}')])
        monkeypatch.setattr(execution.Agent, 'create_client', lambda self: client)
        performed = []
        async def desktop(name, args, timeout):
            performed.append((name, args))
            if name == 'list_apps':
                return {'apps': [{'windowId': 7, 'title': title}]}
            assert args['window_title'] == title
            return {'verified': True} if name == 'verify_text' else {'tree': '{}', 'elements': []}
        monkeypatch.setattr(execution, 'call_desktop', desktop)
        manager = ExecutionManager(Settings(), Repository(tmp_path))
        run = manager.start(TASK, WORKFLOW, ExecutionRequest(auto_approve=True))
        await manager.workers[run['id']]
        assert run['status'] == 'completed'
        assert [name for name, _ in performed] == ['list_apps', 'inspect_app', 'find_elements', 'zavora', 'verify_text']
        approval = next(e for e in run['events'] if e['kind'] == 'approval')
        assert approval['detail']['arguments']['window_title'] == title
        assert not any(e['kind'] == 'error' for e in run['events'])
    asyncio.run(scenario())
