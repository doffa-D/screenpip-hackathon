"""Real Zavora MCP smoke test. --demo changes only a newly created Notepad fixture."""
import argparse
import asyncio
import json
import subprocess
import time
import uuid
from pathlib import Path

from backend.computer_use_mcp import ComputerUseMCP, PACKAGE


async def run(demo, output):
    output.mkdir(parents=True, exist_ok=True)
    report = {'package': PACKAGE, 'success': False, 'operations': []}
    start = time.perf_counter()

    async def call(client, name, args):
        tick = time.perf_counter()
        record = {'tool': name, 'arguments': args}
        try:
            result = await client.call(name, args)
            record['result'] = result
            return result
        finally:
            record['seconds'] = round(time.perf_counter() - tick, 4)
            report['operations'].append(record)

    try:
        client = ComputerUseMCP()
        async with client.connect():
            report['connection_seconds'] = round(time.perf_counter() - start, 4)
            report['tool_count'] = len(client.tools)
            (output / 'tools.json').write_text(json.dumps([t.model_dump(mode='json', by_alias=True)
                for t in client.tools.values()], indent=2), encoding='utf-8')
            report['diagnostics'] = await call(client, 'doctor', {})
            if demo:
                fixture = output.resolve() / f'zavora-demo-{uuid.uuid4().hex[:10]}.txt'
                fixture.write_text('hello wor', encoding='utf-8')
                report['fixture'] = str(fixture)
                subprocess.Popen(['notepad.exe', str(fixture)])
                deadline = time.monotonic() + 15
                while True:
                    windows = (await call(client, 'list_windows', {}))['windows']
                    matches = [w for w in windows if fixture.name in (w.get('title') or '')]
                    if len(matches) == 1:
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError('Unique test window not found')
                    await asyncio.sleep(.3)
                window = matches[0]['windowId']
                report['before_tree'] = await call(client, 'get_ui_tree', {'window_id': window})
                found = await call(client, 'find_element', {'window_id': window, 'value': 'hello wor'})
                report['editor_candidates'] = found
                # Exact role/label are discovered from the live result, never assumed.
                elements = found if isinstance(found, list) else found.get('elements', found.get('matches', []))
                editors = [e for e in elements if e.get('value') == 'hello wor']
                if len(editors) != 1:
                    raise RuntimeError('Expected exactly one editor containing fixture text')
                editor = editors[0]
                await call(client, 'set_value', {'window_id': window, 'role': editor['role'],
                    'label': editor.get('label', ''), 'value': 'hello world', 'focus_strategy': 'strict'})
                after = await call(client, 'find_element', {'window_id': window, 'value': 'hello world'})
                report['after'] = after
                elements = after if isinstance(after, list) else after.get('elements', after.get('matches', []))
                if not any(e.get('value') == 'hello world' for e in elements):
                    raise RuntimeError('Fresh MCP read did not confirm hello world')
                # Independent observer verifies the MCP did change the live editor.
                import xa11y
                app = xa11y.App.by_pid(matches[0]['pid'])
                actual = app.locator(f'window[name*="{fixture.name}"] web_area[name="Text editor"]').elements()
                report['independent_value'] = actual[0].value if len(actual) == 1 else None
                if report['independent_value'] != 'hello world':
                    raise RuntimeError('Independent accessibility verification failed')
                report['note'] = 'New test document left open; UI verified, not saved.'
            report['success'] = True
    except Exception as exc:
        report['error'] = repr(exc)
    finally:
        report['elapsed_seconds'] = round(time.perf_counter() - start, 4)
        (output / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k not in
            ('operations', 'before_tree', 'after', 'editor_candidates', 'diagnostics')}, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=Path('artifacts/computer-use-mcp'))
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.demo, args.output_dir)))
