"""Real MCP + actual backend/model calls. No mocks or fabricated history.

python -m scripts.live_test [--interactive]
Interactive mode lets a human choose a returned task for reconstruction.
"""
import argparse
import asyncio
import json
import logging
import time as clock
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from backend.config import Settings
from backend.main import app, tasks
from backend.models import TaskOccurrence
from backend.mcp_client import ScreenpipeMCP

OUT = Path('artifacts/live-test')


def save(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


async def recorder_checks():
    s = Settings()
    now = datetime.now(ZoneInfo(s.agent_timezone))
    bounds = {'start_time': datetime.combine(now.date(), time.min, tzinfo=now.tzinfo).isoformat(),
              'end_time': now.isoformat()}
    report = {}
    async with ScreenpipeMCP(s).connect() as mcp:
        for label, tool, args in [
            ('activity-summary', 'activity-summary', bounds),
            ('original-data', 'search-content', {**bounds, 'content_type': 'ocr',
                                               'limit': 5, 'max_content_length': 0}),
        ]:
            try:
                response = await mcp.call_tool(tool, args)
                save(label + '.json', {'tool': tool, 'arguments': args, 'response': response})
                report[label] = {'tool_error': response.get('isError', False),
                                 'content_blocks': len(response.get('content', []))}
            except Exception as exc:
                report[label] = {'error': str(exc)}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--message', help='Run one specific search instead of the default three')
    parser.add_argument('--skip-recorder-checks', action='store_true')
    parser.add_argument('--output-dir', default='artifacts/live-test')
    parser.add_argument('--reconstruct-id', help='Explicit id from this output directory\'s saved session')
    args = parser.parse_args()
    global OUT
    OUT = Path(args.output_dir)
    OUT.mkdir(parents=True, exist_ok=True)
    logging.getLogger('backend.agent').setLevel(logging.INFO)
    logging.getLogger('backend.agent').addHandler(logging.FileHandler(
        OUT / 'tool-trace.log', encoding='utf-8'))
    if args.reconstruct_id:
        state = json.loads((OUT / 'session.json').read_text(encoding='utf-8'))
        selected = state[args.reconstruct_id]
        tasks[args.reconstruct_id] = {
            'task': TaskOccurrence.model_validate(selected['task']),
            'ledger': selected['ledger'], 'expires': clock.monotonic() + 3600}
        with TestClient(app) as client:
            started = clock.perf_counter()
            response = client.post(f'/tasks/{args.reconstruct_id}/reconstruct')
            elapsed = round(clock.perf_counter() - started, 3)
            save('workflow.json', {'selected_task_id': args.reconstruct_id,
                                   'status': response.status_code, 'elapsed_seconds': elapsed, 'response': response.json()})
            print('Reconstruction -> HTTP', response.status_code, '| seconds:', elapsed)
        return
    report = {'recorder': {} if args.skip_recorder_checks else asyncio.run(recorder_checks()), 'searches': []}
    with TestClient(app) as client:
        report['health'] = client.get('/health').status_code
        for index, question in enumerate([args.message] if args.message else [
            'Find all emails I sent today',
            'Find the Notepad tasks I did yesterday',
            'Find the tasks I performed today and summarize each distinct occurrence using original activity',
        ], 1):
            started = clock.perf_counter()
            response = client.post('/tasks/search', json={'message': question})
            elapsed = round(clock.perf_counter() - started, 3)
            data = response.json()
            save(f'search-{index}.json', {'question': question, 'status': response.status_code, 'elapsed_seconds': elapsed, 'response': data})
            save('session.json', {key: {'task': value['task'].model_dump(mode='json'),
                                      'ledger': value['ledger']} for key, value in tasks.items()})
            report['searches'].append({'question': question, 'status': response.status_code,
                'elapsed_seconds': elapsed, 'task_count': len(data) if response.is_success else None,
                'error': None if response.is_success else data})
            print(question, '-> HTTP', response.status_code, '| seconds:', elapsed)
            if response.is_success and data and args.interactive:
                for task in data:
                    print(task['id'], task['title'], task['timestamp'], task['summary'])
                try:
                    chosen = input('Enter a displayed task id to reconstruct, or Enter to skip: ').strip()
                except EOFError:
                    chosen = ''
                    print('No interactive input; session saved for --reconstruct-id.')
                if chosen:
                    if chosen not in {task['id'] for task in data}:
                        raise ValueError('Choose an id from this response')
                    reconstructed = client.post(f'/tasks/{chosen}/reconstruct')
                    save(f'workflow-{index}.json', {'selected_task_id': chosen,
                        'status': reconstructed.status_code, 'response': reconstructed.json()})
                    print('Reconstruction -> HTTP', reconstructed.status_code)
    report['reconstruction'] = 'Only run after explicit human selection in --interactive mode'
    save('report.json', report)
    print(json.dumps(report, indent=2))
    print('Real response files:', OUT.resolve())


if __name__ == '__main__':
    main()
