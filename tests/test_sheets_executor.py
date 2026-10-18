import asyncio
import json
from types import SimpleNamespace

import pytest

from backend import sheets_executor as sheets
from backend.config import Settings
from backend.execution import ExecutionManager
from backend.models import ExecutionRequest
from backend.repository import Repository
from tests.test_execution import TASK, WORKFLOW

URL = 'https://docs.google.com/spreadsheets/d/test_id/edit?gid=0#gid=0'
VALUES = dict(execution_mode=sheets.MODE, spreadsheet_url=URL, sheet_gid='0', target_cell='G10',
              source_range='G3:G9', formula='=SUM(G3:G9)')


class Manager:
    settings = SimpleNamespace(desktop_timeout_seconds=10)
    overlay = SimpleNamespace(show=lambda *a: None)
    permission = lambda self: True
    def __init__(self):
        self.approved = []
        self.events = []
    async def approval(self, run, args, tool):
        self.approved.append((tool, args))
    def event(self, *args):
        self.events.append(args)


async def simulate(monkeypatch, fail=None, manager=None):
    async def sleep(*args): pass
    monkeypatch.setattr(sheets.asyncio, 'sleep', sleep)
    manager = manager or Manager()
    calls = []
    async def desktop(name, args, timeout):
        if name == 'zavora':
            assert ('zavora', args) in manager.approved
        calls.append((name, args))
        if name == 'list_apps':
            return {'apps': [dict(bundleId='chrome.exe', title='Budget - Google Sheets - Google Chrome', windowId=7)]}
        if name == 'inspect_app':
            return {'tree': json.dumps({'elements': [
                dict(role='AXTextField', label='Address and search bar', value=URL if fail != 'url' else URL.replace('test_id','other')),
                dict(role='AXTextField', label='', value='=SUM(G3:G9)\n' if fail != 'formula' else '')]})}
        if name == 'verify_text':
            return {'verified': fail != 'selection', 'actual': args['expected']}
        if name == 'find_elements':
            return {'elements': [] if fail == 'save' else [dict(role='AXButton', label='Document status: Saved to Drive.')]}
        return {}
    async def opened(url):
        assert manager.approved[0][0] == 'open_url'
        return {'opened': url}
    try:
        result = await sheets.execute(manager, {}, ExecutionRequest(values=VALUES), desktop, opened, {})
        return result, calls, manager
    except Exception as exc:
        return exc, calls, manager


def test_normal_path_is_bounded_and_approvals_precede_every_change(monkeypatch):
    result, calls, manager = asyncio.run(simulate(monkeypatch))
    assert isinstance(result, str) and 'Saved to Drive verified' in result
    assert len(calls) == 14
    inputs = [args['arguments']['text'] for name,args in calls if name == 'zavora' and args['tool'] in ('key','type')]
    assert inputs == ['ctrl+j','G10','=SUM(G3:G9)','ctrl+j','G10']
    assert not any(x in inputs for x in ['ctrl+z','f2'])
    assert len(manager.approved) == 7  # open, activate, two selections, one formula
    assert any(args.get('expected') == '=SUM(G3:G9)\n' for _,args in calls)


@pytest.mark.parametrize('failure', ['url','selection','formula','save'])
def test_failed_checks_stop_without_retrying_or_undo(monkeypatch, failure):
    result, calls, _ = asyncio.run(simulate(monkeypatch, failure))
    assert isinstance(result, ValueError)
    mutations = [args for name,args in calls if name == 'zavora']
    entered = [a for a in mutations if a['tool'] == 'type' and a['arguments']['text'].startswith('=')]
    assert len(entered) == (0 if failure in ('url','selection') else 1)
    assert not any(a['arguments'].get('text') == 'ctrl+z' for a in mutations)
    assert len([1 for name,_ in calls if name == 'find_elements']) <= 3


def test_disabled_permission_prevents_opening(monkeypatch):
    manager = Manager()
    manager.permission = lambda: False
    result, calls, _ = asyncio.run(simulate(monkeypatch, manager=manager))
    assert isinstance(result, PermissionError)
    assert not calls


@pytest.mark.parametrize('overrides', [dict(target_cell='G11'),dict(formula='=SUM(F3:F9)'),
    dict(spreadsheet_url=URL.replace('docs.google.com','evil.example')),dict(sheet_gid='1'),
    dict(source_range='G3:G10')])
def test_invalid_spec_is_rejected(overrides):
    with pytest.raises(ValueError):
        sheets.specification({**VALUES, **overrides})


@pytest.mark.parametrize('run_mode', [sheets.MODE, sheets.TOTALS_MODE])
def test_opt_in_executor_uses_no_model_and_keeps_final_report(tmp_path, monkeypatch, run_mode):
    import backend.execution as execution
    from backend.agent import Agent
    def forbidden(self):
        raise AssertionError('No model client should be created')
    monkeypatch.setattr(Agent, 'create_client', forbidden)
    async def fixed(manager, run, request, desktop, opened, state):
        state['changed'] = True
        return 'Formula and saving verified.'
    monkeypatch.setattr(sheets, 'execute', fixed)
    async def scenario():
        manager = ExecutionManager(Settings(), Repository(tmp_path))
        run = manager.start(TASK, WORKFLOW, ExecutionRequest(values=VALUES if run_mode == sheets.MODE else ROW_VALUES))
        await manager.workers[run['id']]
        assert run['status'] == 'completed'
        assert run['report']['summary'] == 'Formula and saving verified.'
        assert run['events'][-1]['detail']['desktop_changed']
    asyncio.run(scenario())


ROW_VALUES = dict(execution_mode=sheets.TOTALS_MODE, spreadsheet_url=URL, sheet_gid='0',
                  source_range='B3:G9', target_range='B10:G10')


@pytest.mark.parametrize('overrides', [dict(target_range='B9:G9'),dict(target_range='C10:G10'),
    dict(source_range='G3:B9'),dict(target_range='B10:G11'),dict(source_range='B3:Z9',target_range='B10:Z10')])
def test_total_row_bounds_rejected(overrides):
    with pytest.raises(ValueError):
        sheets.specification({**ROW_VALUES, **overrides})


@pytest.mark.parametrize('bad_cell', [None, 'D10'])
def test_total_row_pastes_once_and_checks_each_cell(monkeypatch, bad_cell):
    async def scenario():
        async def sleep(*args): pass
        monkeypatch.setattr(sheets.asyncio, 'sleep', sleep)
        selected = 'A1'
        pasted = []
        verified = []
        manager = Manager()
        expected = sheets.total_row(ROW_VALUES)
        async def desktop(name, args, timeout):
            nonlocal selected
            if name == 'list_apps':
                return {'apps':[dict(bundleId='chrome.exe',title='Budget - Google Sheets - Google Chrome',windowId=7)]}
            if name == 'zavora':
                assert ('zavora',args) in manager.approved
                native=args['arguments']
                if args['tool']=='type':
                    if native['text'].startswith('='):
                        pasted.append(native['text'])
                    else:
                        selected=native['text']
                return {}
            if name == 'inspect_app':
                return {'tree':json.dumps({'elements':[
                    dict(role='AXTextField',label='Address and search bar',value=URL),
                    dict(role='AXTextField',label='',value=selected),
                    dict(role='AXTextField',label='',value='WRONG' if selected==bad_cell else expected.get(selected,''))]})}
            if name == 'verify_text':
                if args['expected'].startswith('='):
                    verified.append(args['expected'])
                return {'verified':True}
            if name == 'find_elements':
                return {'elements':[dict(role='AXButton',label='Document status: Saved to Drive.')]}
            raise AssertionError(name)
        async def opened(url): return {'opened':url}
        if bad_cell:
            with pytest.raises(ValueError,match='D10'):
                await sheets.execute(manager,{},ExecutionRequest(values=ROW_VALUES),desktop,opened,{})
            assert len(verified)==2
        else:
            result=await sheets.execute(manager,{},ExecutionRequest(values=ROW_VALUES),desktop,opened,{})
            assert '6 SUM formulas' in result
            assert verified==list(expected.values())
        assert pasted==['\t'.join(expected.values())+'\n']
        assert not any(args.get('arguments',{}).get('text')=='ctrl+z' for _,args in manager.approved)
    asyncio.run(scenario())
