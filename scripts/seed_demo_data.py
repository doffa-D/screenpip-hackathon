"""Offline, idempotent demo fixtures. Never connects to Screenpipe or the desktop."""
import argparse
import copy
import json
import socket
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from backend.config import Settings
from backend.repository import Repository
from backend.memory_index import Memory, MemoryIndex
from backend.models import Evidence, TaskOccurrence, Reconstruction, ExecutionRequest, RunRecord
from backend.workflow_store import WorkflowStore, SavedWorkflow
from backend.scheduler import ScheduleInput, next_occurrence

BODY = "Hi,\n\nJust a quick reminder to review the latest project update when you have a moment.\n\nPlease let me know if you have any questions or if anything needs to be updated.\n\nBest,\nHoussam"
SPECS = [
    ('gmail', 'Send project reminder email', ['Gmail', 'Chrome'],
     'Opened Gmail, composed a reminder email, entered the recipient, subject and message, then sent it.',
     {'recipient': 'mzbakasta@gmail.com', 'subject': 'Reminder: Project Update', 'message_body': BODY},
     ['Open Gmail.', 'Start a new email.', 'Enter recipient: mzbakasta@gmail.com.', 'Enter subject: Reminder: Project Update.', 'Enter the email body.', 'Review the message.', 'Send after explicit approval.', 'Verify that Gmail shows a successful sent state.'],
     'Verify that Gmail indicates the email was sent successfully.', 12, 'Daily email follow-up'),
    ('notepad', 'Edit Notepad text', ['Notepad'],
     'Opened a Notepad document and changed the text from "hello word" to "hello world".',
     {'starting_text': 'hello word', 'resulting_text': 'hello world'},
     ['Open or inspect the selected Notepad document.', 'Find the main editor.', 'Replace "hello word" with "hello world".', 'Verify that the editor contains exactly "hello world".'],
     'The visible editor contains exactly "hello world". Saving is not part of this workflow.', 5, 'Notepad text update'),
    ('report', 'Create weekly project report', ['Google Docs', 'Chrome'],
     'Opened a document, created a weekly report, added project progress and next steps, and completed the document.',
     {'report_title': 'Weekly Project Report', 'progress_section': 'Project progress is on track. Core implementation is complete and testing is continuing.', 'next_steps': 'Finish end-to-end testing, review remaining issues, and prepare the final demo.'},
     ['Open the target document.', 'Add the title "Weekly Project Report".', 'Add a section called "Project Progress".', 'Enter the progress text.', 'Add a section called "Next Steps".', 'Enter the next-steps text.', 'Review the completed document.', 'Verify the expected title and sections appear in the document.'],
     'Verify that the document contains the expected title and sections.', 4, 'Weekly report'),
]
STORES = ('memories', 'workflows', 'schedules', 'runs', 'demo_patterns')


def guard_offline():
    # These are the supported native/development ports. Stale in-memory stores
    # would overwrite an external seed, so maintenance is deliberately offline.
    for port in (8765, 8000):
        with socket.socket() as connection:
            connection.settimeout(.3)
            if connection.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Close Melon and its local backend on port {port} before changing stored data.')


def is_demo(key, value):
    return value.get('origin') == 'demo' and value.get('source_kind') == 'seeded_demo'


def seed(repository, now=None):
    now = (now or datetime.now(ZoneInfo('Europe/Paris'))).astimezone(ZoneInfo('Europe/Paris'))
    originals = {name: repository.read(name, {}) for name in STORES}
    stores = copy.deepcopy(originals)
    # Retire the previous presentation-only run history. Real executions of
    # seeded workflows have origin=real/source_kind=execution and are preserved.
    stores['runs'] = {key: value for key, value in stores['runs'].items() if not is_demo(key, value)}
    timestamps = [datetime.combine(now.date(), time(10, 5), now.tzinfo),
                  datetime.combine(now.date(), time(9, 40), now.tzinfo),
                  datetime.combine(now.date() - timedelta(days=1), time(16, 30), now.tzinfo)]
    for index, (slug, title, apps, summary, values, steps, check, count, pattern_title) in enumerate(SPECS):
        mid, wid, rid = f'demo:memory:{slug}', f'demo:workflow:{slug}', f'demo:run:{slug}'
        timestamp = timestamps[index]
        evidence = [Evidence(call_id=f'demo-{slug}-1', quote='DEMO SEEDED EXAMPLE — supplied by the user, not observed or executed. ' + summary, source_kind='seeded_demo')]
        task = TaskOccurrence(id=mid, title=title, timestamp=timestamp, summary='Demo scenario: ' + summary, evidence=evidence, origin='demo')
        workflow = Reconstruction(goal=title, historical_values={name: {'value': value, 'evidence': evidence} for name, value in values.items()}, steps=[{'description': step, 'evidence': evidence} for step in steps], missing_values=[], evidence=evidence)
        defaults = ExecutionRequest(values=values, instructions='Completion check: ' + check + ' Inspect the current target; block if ambiguous. Every desktop mutation requires the existing approval flow.')
        memory = Memory(**task.model_dump(), apps=apps, source_kind='seeded_demo', tags=['demo'], created_at=now, updated_at=now)
        saved = SavedWorkflow(id=wid, title=title, created_at=now, updated_at=now, task=task, reconstruction=workflow, ledger={}, run_defaults=defaults, tags=['demo'], origin='demo', source_kind='seeded_demo', user_notes='Seeded demonstration, not Screenpipe evidence or an executed task. ' + check)
        memory_data = {**memory.model_dump(mode='json'), 'ledger': {}, 'source_ids': [], 'workflow': workflow.model_dump(mode='json')}
        records = {'memories': (mid, memory_data), 'workflows': (wid, saved.model_dump(mode='json')), 'demo_patterns': (f'demo:pattern:{slug}', {'id': f'demo:pattern:{slug}', 'title': pattern_title, 'demo_occurrence_count': count, 'workflow_id': wid, 'origin': 'demo', 'source_kind': 'seeded_demo', 'tags': ['demo'], 'summary': 'Synthetic discovery example. Review and approve this saved workflow to execute it for real.'})}
        if slug != 'notepad':
            day = now.date() if slug == 'gmail' else now.date() + timedelta(days=(0-now.weekday()) % 7)
            rule = ScheduleInput(workflow_id=wid, frequency='daily' if slug == 'gmail' else 'weekly', local_date=day, local_time=time(19) if slug == 'gmail' else time(9), timezone='Europe/Paris', enabled=False)
            sid = f'demo:schedule:{slug}'
            records['schedules'] = (sid, {'id': sid, **rule.model_dump(mode='json'), 'title': pattern_title, 'workflow_revision': 1, 'workflow_snapshot': saved.model_dump(mode='json'), 'next_run_at': next_occurrence(rule, now), 'origin': 'demo', 'source_kind': 'seeded_demo', 'tags': ['demo']})
        for name, (key, value) in records.items():
            existing = stores[name].get(key)
            if existing is not None:
                if not is_demo(key, existing):
                    raise ValueError(f'Refusing to replace non-demo record: {name}/{key}')
                continue  # Preserve edits, schedule choices, and original timestamps on replay.
            stores[name][key] = value
    # Validate all typed output before the first atomic write.
    for value in stores['memories'].values():
        Memory.model_validate(MemoryIndex.public(value))
    for value in stores['workflows'].values():
        SavedWorkflow.model_validate(value)
    for value in stores['runs'].values():
        RunRecord.model_validate(value)
    for name in STORES:
        if stores[name] != originals[name]:
            repository.write(name, stores[name])
    return {name: sum(is_demo(k, v) for k, v in stores[name].items()) for name in STORES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default=None)
    args = parser.parse_args()
    guard_offline()
    print(json.dumps(seed(Repository(args.data_dir or Settings().data_dir)), indent=2))


if __name__ == '__main__':
    main()
