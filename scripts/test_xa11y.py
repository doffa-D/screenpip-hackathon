"""Live xa11y smoke test: list apps, inspect one, or edit a new Notepad fixture.

Run with python -m scripts.test_xa11y --help. No model credentials required.
"""
import argparse
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--app', help='Exact running app name; capture its accessibility tree')
    mode.add_argument('--demo', action='store_true', help='Open a new Notepad test file and edit its text')
    parser.add_argument('--output-dir', type=Path, default=Path('artifacts/xa11y-test'))
    parser.add_argument('--depth', type=int, default=6, choices=range(1, 13))
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(),
              'mode': 'demo' if args.demo else 'inspect' if args.app else 'list',
              'operations': [], 'success': False}
    started = time.perf_counter()

    def timed(label, action):
        tick = time.perf_counter()
        record = {'operation': label}
        try:
            result = action()
            record['success'] = True
            return result
        except Exception:
            record['success'] = False
            raise
        finally:
            record['seconds'] = round(time.perf_counter() - tick, 4)
            report['operations'].append(record)

    try:
        import xa11y
        report['xa11y_version'] = version('xa11y')
        xa11y.set_default_timeout(10)
        apps = timed('enumerate_apps', xa11y.App.list)
        report['apps'] = [{'pid': app.pid, 'name': app.name} for app in apps]
        for app in report['apps']:
            print(f"{app['pid']}: {app['name']}")
        if args.demo:
            if sys.platform != 'win32':
                raise RuntimeError('--demo currently requires Windows Notepad')
            fixture = output / f'xa11y-demo-{uuid.uuid4().hex[:12]}.txt'
            fixture.write_text('hello wor', encoding='utf-8')
            report['fixture'] = str(fixture)
            timed('launch_notepad', lambda: subprocess.Popen(['notepad.exe', str(fixture)]))
            # Modern Notepad may hand off to another PID; find our unique window.
            app = timed('attach_test_window', lambda: xa11y.App.find(
                lambda candidate: any(fixture.name in (window.name or '')
                                      for window in candidate.windows()), timeout=15))
            scope = f'window[name*="{fixture.name}"]'
            def snapshot(name):
                tree = app.locator(scope).tree(max_depth=args.depth)
                (output / name).write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding='utf-8')
            timed('snapshot_before', lambda: snapshot('before.json'))
            # Discover the editable control from observed roles and exact fixture value.
            matches = []
            for role in ('web_area', 'text_field', 'text_area', 'document'):
                locator = app.locator(f'{scope} {role}')
                elements = locator.elements()
                if len(elements) == 1 and elements[0].value == 'hello wor':
                    matches.append(locator)
            if len(matches) != 1:
                raise RuntimeError(f'Expected one unambiguous test editor, found {len(matches)}')
            editor = matches[0]
            report['before'] = timed('read_before', lambda: editor.elements()[0].value)
            timed('set_value', lambda: editor.set_value('hello world'))
            report['after'] = timed('read_after', lambda: editor.elements()[0].value)
            if report['after'] != 'hello world':
                raise RuntimeError('Fresh accessibility read did not confirm the edit')
            timed('snapshot_after', lambda: snapshot('after.json'))
            report['note'] = 'Test window left open. UI text verified; disk save not tested.'
        elif args.app:
            app = timed('attach_app', lambda: xa11y.App.by_name(args.app, timeout=10))
            tree = timed('read_tree', lambda: app.tree(max_depth=args.depth))
            (output / 'tree.json').write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding='utf-8')
        report['success'] = True
    except Exception as exc:
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        report['elapsed_seconds'] = round(time.perf_counter() - started, 4)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print('Report:', output / 'report.json')
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
