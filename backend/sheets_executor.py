"""Opt-in, bounded single-cell SUM replay. No model decisions or blind retries."""
import asyncio
import json
import re
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

MODE = 'sheets_sum_v1'
TOTALS_MODE = 'sheets_totals_v1'


def total_row(values):
    """A small adjacent total row, with formulas generated from validated bounds."""
    source = re.fullmatch(r'([A-Z])([1-9]\d*):([A-Z])([1-9]\d*)', values.get('source_range', ''))
    target = re.fullmatch(r'([A-Z])([1-9]\d*):([A-Z])([1-9]\d*)', values.get('target_range', ''))
    if (not source or not target or source[1] != target[1] or source[3] != target[3]
            or not 0 <= ord(source[3]) - ord(source[1]) < 12
            or int(source[2]) > int(source[4])
            or int(target[2]) != int(source[4]) + 1 or target[2] != target[4]):
        raise ValueError('Use up to 12 source columns with a matching total row directly below them.')
    formulas = {f'{chr(c)}{target[2]}': f'=SUM({chr(c)}{source[2]}:{chr(c)}{source[4]})'
                for c in range(ord(source[1]), ord(source[3]) + 1)}
    return formulas


def specification(values):
    url = values.get('spreadsheet_url', '')
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'docs.google.com'
            or not re.fullmatch(r'/spreadsheets/d/[\w-]+/edit', parsed.path)):
        raise ValueError('Use an exact Google Sheets edit URL.')
    gid = str(values.get('sheet_gid', ''))
    if not gid.isdigit() or parse_qs(parsed.fragment).get('gid', parse_qs(parsed.query).get('gid')) != [gid]:
        raise ValueError('The spreadsheet URL must select the configured sheet gid.')
    if 'gid' in parse_qs(parsed.query) and parse_qs(parsed.query)['gid'] != [gid]:
        raise ValueError('Conflicting sheet gid in URL.')
    if values.get('execution_mode') == TOTALS_MODE:
        formulas = total_row(values)
        return url, gid, values['target_range'], formulas
    formula = values.get('formula', '')
    match = re.fullmatch(r'=SUM\(([A-Z]{1,3})([1-9]\d*):\1([1-9]\d*)\)', formula)
    if not match or int(match[2]) > int(match[3]):
        raise ValueError('This demo supports one SUM over a single column range.')
    target = values.get('target_cell', '')
    if target != f'{match[1]}{int(match[3]) + 1}':
        raise ValueError('The total cell must be directly below the source range.')
    if values.get('source_range') != f'{match[1]}{match[2]}:{match[1]}{match[3]}':
        raise ValueError('The source range must match the SUM formula.')
    return url, gid, target, formula


def nodes(tree):
    if isinstance(tree, str):
        tree = json.loads(tree)
    if isinstance(tree, list):
        return [node for item in tree for node in nodes(item)]
    if not isinstance(tree, dict):
        return []
    return [tree] + nodes(tree.get('elements', [])) + nodes(tree.get('children', []))


async def execute(manager, run, request, desktop, open_page, state):
    """Every change passes the same approval and permission gate as agent actions."""
    url, gid, target, formula = specification(request.values)
    batch = isinstance(formula, dict)
    if run.get('scope'):
        raise ValueError('The Sheets demo executor supports manual runs only.')

    async def call(name, args, change=False):
        if change:
            await manager.approval(run, args, name)
            if not getattr(manager, 'permission', lambda: True)():
                raise PermissionError('Desktop control was disabled; action cancelled.')
        cid = str(uuid4())
        event_tool = 'zavora_act' if name == 'zavora' and change else name
        manager.overlay.show(args.get('reason', 'Checking the spreadsheet'))
        manager.event(run, 'tool', args.get('reason', 'Checking the spreadsheet'),
                      {**args, 'tool_name': event_tool, 'tool_call_id': cid})
        if change:
            state['changed'] = True
        result = await open_page(args['url']) if name == 'open_url' else await desktop(
            name, args, manager.settings.desktop_timeout_seconds)
        manager.event(run, 'verified' if name == 'verify_text' and result.get('verified') else 'result',
                      'Result verified' if name == 'verify_text' and result.get('verified') else 'Desktop response',
                      {'tool': event_tool, 'tool_call_id': cid, 'arguments': args, 'result': result})
        return result

    await call('open_url', {'url': url, 'reason': 'Open the selected spreadsheet'}, True)
    await asyncio.sleep(2)
    apps = (await call('list_apps', {}))['apps']
    candidates = [w for w in apps if str(w.get('bundleId', '')).lower() == 'chrome.exe'
                  and 'Google Sheets' in w.get('title', '')]
    matches = []
    for window in candidates:
        args = {'window_id': window['windowId'], 'window_title': window['title']}
        tree = await call('inspect_app', {**args, 'depth': 15})
        fields = nodes(tree['tree'])
        urls = [str(n.get('value', '')) for n in fields
                if n.get('role') == 'AXTextField' and n.get('label') == 'Address and search bar']
        expected = urlparse(url)
        for address in urls:
            actual = urlparse(address if '://' in address else 'https://' + address)
            if (actual.netloc == expected.netloc and actual.path == expected.path
                    and parse_qs(actual.fragment).get('gid', parse_qs(actual.query).get('gid')) == [gid]):
                matches.append(args)
                break
    if len(matches) != 1:
        raise ValueError('Could not identify exactly one Chrome window with the requested spreadsheet and sheet. No cell was edited.')
    window = matches[0]

    async def native(tool, args, reason):
        return await call('zavora', {'tool': tool, 'arguments': args,
                                     'window_title': window['window_title'], 'reason': reason}, True)

    async def select(address=target):
        await native('key', {'target_window_id': window['window_id'], 'text': 'ctrl+j'}, 'Focus the cell address box')
        await native('type', {'target_window_id': window['window_id'], 'text': address, 'press_enter': True}, f'Select {address}')

    await native('activate_window', {'window_id': window['window_id']}, 'Bring the spreadsheet forward')
    await select()
    check = await call('verify_text', {**window, 'role': 'AXTextField', 'label': '',
                                     'property': 'value', 'expected': target})
    if not check.get('verified'):
        raise ValueError(f'Could not confirm {target}. No formula was entered.')
    # A terminal newline makes this a tabular paste, rather than individual Tab keystrokes.
    # Google Sheets pastes this single TSV row into the selected output range.
    payload = '\t'.join(formula.values()) + '\n' if batch else formula
    await native('type', {'target_window_id': window['window_id'], 'text': payload, 'press_enter': not batch},
                 f'Fill {target} with SUM formulas' if batch else f'Enter {formula} in {target}')
    expected_formulas = formula if batch else {target: formula}
    for address, expected_formula in expected_formulas.items():
        await select(address)  # Verify each destination, never the row after Enter.
        if not batch:
            check = await call('verify_text', {**window, 'role': 'AXTextField', 'label': '',
                                             'property': 'value', 'expected': address})
            if not check.get('verified'):
                raise ValueError(f'Formula entry attempted, but {address} could not be reselected. No retry or Undo was performed.')
        tree = await call('inspect_app', {**window, 'depth': 15})
        fields = [n for n in nodes(tree['tree']) if n.get('role') == 'AXTextField' and not n.get('label')]
        if batch and not any(n.get('value') == address for n in fields):
            raise ValueError(f'Could not confirm {address} during verification. No repeat paste or Undo was performed.')
        field = next((n for n in fields if str(n.get('value', '')).rstrip('\r\n') == expected_formula), None)
        if field is None:
            raise ValueError(f'Formula entry attempted, but the live formula in {address} is unverified. No retry or Undo was performed.')
        check = await call('verify_text', {**window, 'role': 'AXTextField', 'label': '',
                                         'property': 'value', 'expected': field['value']})
        if not check.get('verified'):
            raise ValueError(f'The formula in {address} changed during verification. No retry was performed.')
    # Saving can lag behind the edit. Three bounded read-only polls, no desktop mutations.
    for attempt in range(3):
        found = await call('find_elements', {**window, 'query': 'Saved to Drive'})
        status = next((n for n in found.get('elements', []) if n.get('label') == 'Document status: Saved to Drive.'), None)
        if status:
            saved = await call('verify_text', {**window, 'role': status['role'], 'label': status['label'],
                                             'property': 'label', 'expected': status['label']})
            if saved.get('verified'):
                if state.get('export_range'):
                    await select(state['export_range'])
                    selected = await call('verify_text', {**window, 'role': 'AXTextField', 'label': '',
                        'property': 'value', 'expected': state['export_range']})
                    if not selected.get('verified'):
                        raise ValueError('Totals verified, but the full table could not be selected for PDF export.')
                    state['export_range_verified'] = True
                if batch:
                    return f'Filled {target} with {len(formula)} SUM formulas. All formulas and Saved to Drive verified. Numeric totals were not independently read.'
                return f'{target} contains {formula}. Formula and Saved to Drive verified. The numeric total was not independently read.'
        if attempt < 2:
            await asyncio.sleep(1)
    raise ValueError(f'{target} formula verified, but Saved to Drive could not be confirmed. No repeat edit was performed.')
