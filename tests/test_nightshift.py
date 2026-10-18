"""Night shift: routine gaps, scope guard, proposals, the overnight runner, the morning report and the API."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from itertools import count
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openai import OpenAIError
from openai.types.chat import ChatCompletionMessage
from pydantic import ValidationError
import backend.execution as execution
import backend.main as main
import backend.nightshift as night
from backend.config import Settings
from backend.execution import ExecutionManager
from backend.models import Reconstruction, RunRecord, TaskOccurrence
from backend.nightshift import ApproveProposal, NightSettings, NightShift, ReviewProposal, window
from backend.repository import Repository
from backend.routine import find_gaps
from backend.run_reports import build_report
from backend.scope import authorize
from backend.workflow_store import SaveWorkflow, UpdateWorkflow, WorkflowStore

UTC = timezone.utc
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
EVIDENCE = [{'call_id': 'e1', 'quote': 'hello world', 'source_kind': 'original_activity'}]
TITLE = 'Inbox - Google Chrome'


# ---------------------------------------------------------------- synthetic discovery state
def hm(days_ago, hour, minute=0):
    day = NOW.date() - timedelta(days=days_ago)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def occurrence(oid, start, minutes=10):
    return {'id': oid, 'title': f'Task {oid}', 'timestamp': start.isoformat(), 'ended_at': (start + timedelta(minutes=minutes)).isoformat(),
            'app': 'Google Chrome', 'window': 'Gmail', 'summary': f'Did {oid}'}


def routine_state(a_starts=None, b_starts=None, a_status='active', b_status='active'):
    """A = "Export weekly report" (09:00, 10 min), B = "Send weekly update" (10:10, one hour after A ends)."""
    a_starts = [hm(d, 9) for d in range(8)] if a_starts is None else a_starts      # newest first: a0 is today's
    b_starts = [hm(d, 10, 10) for d in range(1, 8)] if b_starts is None else b_starts
    occurrences = {f'a{i}': occurrence(f'a{i}', s) for i, s in enumerate(a_starts)}
    occurrences |= {f'b{i}': occurrence(f'b{i}', s) for i, s in enumerate(b_starts)}
    return {'patterns': {
        'pa': {'id': 'pa', 'title': 'Export weekly report', 'status': a_status, 'workflow_id': None, 'apps': ['Excel'],
               'occurrence_ids': [f'a{i}' for i in range(len(a_starts))]},
        'pb': {'id': 'pb', 'title': 'Send weekly update', 'status': b_status, 'workflow_id': None, 'apps': ['Google Chrome'],
               'occurrence_ids': [f'b{i}' for i in range(len(b_starts))]}},
        'occurrences': occurrences, 'cursor': NOW.isoformat(), 'scan': {'status': 'idle'}, 'last_attempt': None}


# ---------------------------------------------------------------- 1. routine.find_gaps
def test_gap_found_for_latest_a_without_b():
    gaps = find_gaps(routine_state(), NOW)
    assert len(gaps) == 1
    gap = gaps[0]
    assert (gap['after_pattern_id'], gap['expected_pattern_id'], gap['trigger_occurrence_id']) == ('pa', 'pb', 'a0')
    assert gap['probability'] == 1.0 and gap['support'] == 7 and gap['sample'] == 7
    assert gap['typical_lag_minutes'] == 60
    assert gap['trigger_ended_at'] == hm(0, 9, 10).isoformat()
    assert gap['baseline'] < 0.75
    assert len(gap['pair_key']) == 16 and len(gap['gap_key']) == 24
    assert find_gaps(routine_state(), NOW)[0]['gap_key'] == gap['gap_key']  # deterministic


def test_no_gap_when_b_already_followed_latest_a():
    state = routine_state(b_starts=[hm(d, 10, 10) for d in range(0, 8)])
    assert find_gaps(state, NOW) == []


def test_no_gap_when_latest_a_is_too_recent_then_gap_after_the_usual_wait():
    state = routine_state()
    assert find_gaps(state, hm(0, 9, 30)) == []           # 20 min after A: under the 30 min minimum wait
    assert find_gaps(state, hm(0, 10, 30)) == []          # 80 min: under 1.5x the usual one hour lag
    assert len(find_gaps(state, hm(0, 11, 0))) == 1       # 110 min: overdue


def test_no_gap_when_latest_a_is_older_than_the_horizon():
    state = routine_state(a_starts=[hm(d, 9) for d in range(2, 9)], b_starts=[hm(d, 10, 10) for d in range(3, 9)])
    assert find_gaps(state, NOW) == []
    assert len(find_gaps(state, hm(2, 12))) == 1  # the same history two days earlier still had a live gap


def test_no_gap_when_b_is_so_frequent_that_it_fails_the_base_rate_lift():
    hourly = [hm(d, h, 30) for d in range(7, 0, -1) for h in range(24)] + [hm(0, h, 30) for h in range(9)]
    state = routine_state(b_starts=sorted(hourly, reverse=True))
    assert find_gaps(state, NOW) == []


def test_recent_a_is_right_censored_out_of_the_sample():
    gap = find_gaps(routine_state(), NOW)[0]
    assert gap['sample'] == 7  # eight A's exist, but today's follow-up window has not closed yet
    # an A from 3 hours ago (no B yet) must not drag the probability down either
    state = routine_state(a_starts=[hm(0, 9)] + [hm(0, 8, 30)] + [hm(d, 9) for d in range(1, 8)])
    assert find_gaps(state, NOW)[0]['sample'] == 7


def test_dismissed_patterns_are_ignored():
    assert len(find_gaps(routine_state(), NOW)) == 1
    assert find_gaps(routine_state(b_status='dismissed'), NOW) == []
    assert find_gaps(routine_state(a_status='dismissed'), NOW) == []


def test_not_enough_history_means_no_gap():
    state = routine_state(a_starts=[hm(0, 9), hm(1, 9)], b_starts=[hm(1, 10, 10)])
    assert find_gaps(state, NOW) == []


# ---------------------------------------------------------------- 2. scope.authorize
def scope(**changes):
    return {'allowed_hosts': ['mail.google.com'], 'allowed_apps': ['Google Chrome'], 'may_finalize': False, 'max_actions': 5,
            'used': 0, 'window_end': (datetime.now(UTC) + timedelta(hours=1)).isoformat(), **changes}


def zav(tool, arguments=None, title=TITLE, reason='Prepare the draft'):
    return {'tool': tool, 'arguments': arguments if arguments is not None else {}, 'window_title': title, 'reason': reason}


def test_scope_allows_labelled_ax_actions_in_an_approved_app():
    s = scope()
    assert authorize(s, 'zavora', zav('click_element', {'window_id': 1, 'label': 'Compose'})) is None
    assert authorize(s, 'zavora', zav('set_value', {'window_id': 1, 'label': 'Subject', 'value': 'Weekly report'})) is None
    assert authorize(s, 'zavora', zav('fill_form', {'window_id': 1, 'fields': [{'label': 'To', 'value': 'a@b.co'}, {'label': 'Subject', 'value': 'x'}]})) is None
    act = {'window_id': 1, 'window_title': TITLE, 'role': 'AXButton', 'label': 'Compose', 'action': 'press_button', 'reason': 'Open a draft'}
    assert authorize(s, 'act', act) is None
    assert authorize(s, 'open_url', {'url': 'https://mail.google.com/mail/u/0/#inbox', 'reason': 'Open Gmail'}) is None
    assert s['used'] == 5


@pytest.mark.parametrize('label', ['Send', 'Submit', 'Delete', 'Pay now', 'Publish', 'Confirm order'])
def test_scope_blocks_final_step_labels(label):
    s = scope()
    verdict = authorize(s, 'zavora', zav('click_element', {'window_id': 1, 'label': label}, reason='Open the next screen'))
    assert verdict and verdict[0] == 'irreversible'
    act = {'window_id': 1, 'window_title': TITLE, 'role': 'AXButton', 'label': label, 'action': 'press_button', 'reason': 'Next'}
    assert authorize(s, 'act', act)[0] == 'irreversible'
    assert s['used'] == 0


def test_scope_blocks_a_final_step_named_only_in_the_reason():
    assert authorize(scope(), 'zavora', zav('click_element', {'window_id': 1, 'label': 'Compose'}, reason='Send the draft now'))[0] == 'irreversible'


@pytest.mark.parametrize('keys', ['ctrl+Return', 'ctrl+Enter', 'Ctrl+Return', 'alt+Enter'])
def test_scope_blocks_send_shortcuts(keys):
    verdict = authorize(scope(), 'zavora', zav('key', {'text': keys, 'target_window_id': 1}))
    assert verdict and verdict[0] == 'irreversible'


def test_typing_the_word_send_is_not_blocked():
    s = scope()
    assert authorize(s, 'zavora', zav('set_value', {'window_id': 1, 'label': 'Message Body', 'value': 'Please send me the report'})) is None
    assert authorize(s, 'zavora', zav('type', {'text': 'send delete submit', 'target_window_id': 1})) is None
    assert authorize(s, 'zavora', zav('key', {'text': 'Tab', 'target_window_id': 1})) is None
    assert s['used'] == 3


@pytest.mark.parametrize('url', ['https://evil.example.com/login', 'http://mail.google.com/', 'https://mail.google.com.evil.com/',
                                 'https://notmail.google.com/', 'file:///C:/Windows/System32/calc.exe'])
def test_scope_blocks_hosts_outside_the_list_and_non_https(url):
    s = scope()
    verdict = authorize(s, 'open_url', {'url': url, 'reason': 'Open the page'})
    assert verdict and verdict[0] == 'outside_scope'
    assert s['used'] == 0


def test_scope_allows_subdomains_of_an_approved_host():
    assert authorize(scope(), 'open_url', {'url': 'https://accounts.mail.google.com/x', 'reason': 'Open'}) is None


def test_scope_blocks_windows_outside_allowed_apps():
    s = scope()
    verdict = authorize(s, 'zavora', zav('click_element', {'window_id': 2, 'label': 'Compose'}, title='Untitled - Notepad'))
    assert verdict and verdict[0] == 'outside_scope' and 'Notepad' in verdict[1]
    assert s['used'] == 0


def test_scope_budget_window_end_and_unsupported_tools():
    s = scope(max_actions=2)
    click = zav('click_element', {'window_id': 1, 'label': 'Compose'})
    assert authorize(s, 'zavora', click) is None and authorize(s, 'zavora', click) is None
    assert authorize(s, 'zavora', click)[0] == 'budget'
    assert s['used'] == 2

    assert authorize(scope(window_end=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()), 'zavora', click)[0] == 'window_closed'
    soon = scope()
    assert authorize(soon, 'zavora', click, now=datetime.fromisoformat(soon['window_end']) + timedelta(seconds=1))[0] == 'window_closed'

    for tool in ('click', 'mouse_drag', 'open_application'):
        s = scope()
        assert authorize(s, 'zavora', zav(tool, {'x': 1, 'y': 2, 'target_window_id': 1}))[0] == 'unsupported'
        assert s['used'] == 0


def test_may_finalize_lets_send_through_but_not_other_limits():
    s = scope(may_finalize=True)
    assert authorize(s, 'zavora', zav('click_element', {'window_id': 1, 'label': 'Send'})) is None
    assert authorize(s, 'zavora', zav('key', {'text': 'ctrl+Return', 'target_window_id': 1})) is None
    assert s['used'] == 2
    assert authorize(s, 'open_url', {'url': 'https://evil.example.com/', 'reason': 'Open'})[0] == 'outside_scope'
    assert authorize(s, 'zavora', zav('click_element', {'window_id': 1, 'label': 'Send'}, title='Notepad'))[0] == 'outside_scope'
    assert s['used'] == 2


def test_used_counter_only_counts_allowed_actions():
    s = scope()
    assert authorize(s, 'zavora', zav('click_element', {'window_id': 1, 'label': 'Compose'})) is None
    assert authorize(s, 'zavora', zav('click_element', {'window_id': 1, 'label': 'Send'}))[0] == 'irreversible'
    assert authorize(s, 'open_url', {'url': 'https://evil.example.com/', 'reason': 'x'})[0] == 'outside_scope'
    assert authorize(s, 'zavora', zav('click', {'x': 1, 'y': 1, 'target_window_id': 1}))[0] == 'unsupported'
    assert s['used'] == 1
    assert authorize(s, 'zavora', zav('click_element', {'window_id': 1, 'label': 'Subject'})) is None
    assert s['used'] == 2


# ---------------------------------------------------------------- 3. window()
PARIS = {'timezone': 'Europe/Paris', 'window_start': '23:00', 'window_end': '06:00'}


def test_overnight_window_wraps_midnight():
    opens, closes, active = window(PARIS, datetime(2026, 10, 17, 23, 30, tzinfo=UTC))  # 01:30 in Paris
    assert active and opens == datetime(2026, 10, 17, 21, 0, tzinfo=UTC) and closes == datetime(2026, 10, 18, 4, 0, tzinfo=UTC)
    assert window(PARIS, datetime(2026, 10, 17, 21, 30, tzinfo=UTC)) == (opens, closes, True)  # 23:30 before midnight, same night
    assert window(PARIS, opens)[2] is True  # opens inclusive


def test_overnight_window_outside_gives_the_next_one():
    opens, closes, active = window(PARIS, datetime(2026, 10, 17, 10, 0, tzinfo=UTC))  # noon in Paris
    assert not active and opens == datetime(2026, 10, 17, 21, 0, tzinfo=UTC) and closes == datetime(2026, 10, 18, 4, 0, tzinfo=UTC)
    opens, closes, active = window(PARIS, datetime(2026, 10, 18, 4, 0, tzinfo=UTC))  # closes exclusive
    assert not active and opens == datetime(2026, 10, 18, 21, 0, tzinfo=UTC)


def test_window_without_wrapping():
    day = {'timezone': 'UTC', 'window_start': '09:00', 'window_end': '17:00'}
    assert window(day, datetime(2026, 10, 17, 12, tzinfo=UTC)) == (datetime(2026, 10, 17, 9, tzinfo=UTC), datetime(2026, 10, 17, 17, tzinfo=UTC), True)
    opens, closes, active = window(day, datetime(2026, 10, 17, 18, tzinfo=UTC))
    assert not active and opens == datetime(2026, 10, 18, 9, tzinfo=UTC) and closes == datetime(2026, 10, 18, 17, tzinfo=UTC)
    assert window(day, datetime(2026, 10, 17, 8, tzinfo=UTC))[:3] == (datetime(2026, 10, 17, 9, tzinfo=UTC), datetime(2026, 10, 17, 17, tzinfo=UTC), False)


def test_window_follows_the_local_clock_across_the_autumn_dst_change():
    opens, closes, active = window(PARIS, datetime(2026, 10, 25, 1, 0, tzinfo=UTC))  # night of 24 -> 25 Oct, clocks go back
    assert active and opens == datetime(2026, 10, 24, 21, 0, tzinfo=UTC) and closes == datetime(2026, 10, 25, 5, 0, tzinfo=UTC)


def test_settings_validation():
    assert NightSettings().enabled is False and NightSettings().max_actions_per_task == 40
    with pytest.raises(ValidationError):
        NightSettings(timezone='Mars/Base')
    with pytest.raises(ValidationError):
        NightSettings(window_start='23:00+02:00')
    with pytest.raises(ValidationError):
        NightSettings(max_tasks_per_night=0)


# ---------------------------------------------------------------- shared fixtures for the service
def make_workflow(workflows, title='Send weekly update', goal='Draft the weekly update in Gmail', approve=True, missing=()):
    task = TaskOccurrence(id=f'task-{title}', title=title, timestamp=NOW, summary='Weekly update', evidence=EVIDENCE)
    reconstruction = Reconstruction(goal=goal, historical_values={}, missing_values=list(missing), evidence=EVIDENCE,
        steps=[{'description': 'Open Gmail and start a draft', 'evidence': EVIDENCE}])
    saved = workflows.create(task, reconstruction, {}, SaveWorkflow(task_id=task.id))
    return workflows.approve(saved.id, saved.revision) if approve else saved


def build(tmp_path, state):
    settings = Settings(agent_overlay=False, agent_timezone='Europe/Paris', nightshift_unfinished_pass=False, nightshift_horizon_hours=24,
                        nightshift_min_support=2, nightshift_min_probability=0.6)
    repository = Repository(tmp_path / 'night')
    workflows = WorkflowStore(repository)
    executions = ExecutionManager(settings, repository)
    discovery = SimpleNamespace(state=state, kick=lambda: None, job=None)
    service = NightShift(repository, discovery, workflows, executions, settings)
    return SimpleNamespace(settings=settings, repository=repository, workflows=workflows, executions=executions, discovery=discovery, service=service)


@pytest.fixture
def rig(tmp_path):
    return build(tmp_path, routine_state())


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(night, 'utcnow', lambda: NOW)


def link(rig, workflow):
    rig.discovery.state['patterns']['pb']['workflow_id'] = workflow.id


def suggest(rig):
    asyncio.run(rig.service.analyze())
    return next(iter(rig.service.proposals.values()))


def raises(status, call, *args):
    with pytest.raises(HTTPException) as caught:
        call(*args)
    assert caught.value.status_code == status
    return caught.value


# ---------------------------------------------------------------- 4. analyze / eligibility / decisions
def test_analyze_creates_a_proposal_from_a_gap(rig, frozen):
    analysis = asyncio.run(rig.service.analyze())
    assert analysis['routine_gaps'] == 1 and analysis['new_suggestions'] == 1 and analysis['note'] is None
    [p] = rig.service.proposals.values()
    assert p['kind'] == 'missed_next_step' and p['status'] == 'suggested' and p['scope'] is None
    assert p['title'] == 'Send weekly update' and p['expected_pattern_id'] == 'pb' and p['confidence'] == 1.0
    assert p['stats']['support'] == 7 and p['stats']['sample'] == 7
    assert 'Export weekly report' in p['rationale'] and 'Send weekly update' in p['rationale']
    assert p['evidence'][0]['id'] == 'a0'
    assert p['trigger_ended_at'] == hm(0, 9, 10).isoformat()
    assert rig.repository.read('nightshift', {})['proposals'][p['id']]['title'] == 'Send weekly update'  # persisted
    again = asyncio.run(rig.service.analyze())  # idempotent
    assert again['new_suggestions'] == 0 and len(rig.service.proposals) == 1


def test_eligibility_depends_on_the_workflow(rig, frozen):
    p = suggest(rig)
    assert rig.service.listing()[0]['eligibility']['state'] == 'no_workflow'

    draft = make_workflow(rig.workflows, approve=False)
    link(rig, draft)
    p['workflow_id'] = draft.id
    assert rig.service.public(p)['eligibility']['state'] == 'needs_approval'

    rig.workflows.approve(draft.id, draft.revision)
    assert rig.service.public(p)['eligibility']['state'] == 'ready'

    rig.workflows.update(draft.id, UpdateWorkflow(expected_revision=draft.revision, title='Edited'))  # edit invalidates approval
    assert rig.service.public(p)['eligibility']['state'] == 'needs_approval'

    rig.workflows.archive(draft.id)
    assert rig.service.public(p)['eligibility']['state'] == 'archived'


def test_new_proposal_takes_its_workflow_from_the_expected_pattern(rig, frozen):
    workflow = make_workflow(rig.workflows)
    link(rig, workflow)
    p = suggest(rig)
    assert p['workflow_id'] == workflow.id and p['apps'] == ['Google Chrome']
    assert rig.service.public(p)['eligibility']['state'] == 'ready'


def test_old_unapproved_suggestions_expire(rig, frozen):
    old = NOW - timedelta(days=3)
    rig.service.add_proposal(NOW, gap_key='old', pair_key='pk', kind='missed_next_step', title='Old', rationale='r', confidence=0.9,
        workflow_id=None, expected_pattern_id='other', apps=[], trigger_ended_at=old.isoformat(), evidence=[], stats={})
    asyncio.run(rig.service.analyze())
    assert rig.service.proposals['old']['status'] == 'expired'
    assert rig.service.proposals['old']['outcome']['kind'] == 'expired'


def test_approve_is_409_when_not_ready(rig, frozen):
    p = suggest(rig)  # no workflow behind it
    raises(409, rig.service.approve, p['id'], ApproveProposal())
    assert p['status'] == 'suggested'
    draft = make_workflow(rig.workflows, approve=False)
    p['workflow_id'] = draft.id
    raises(409, rig.service.approve, p['id'], ApproveProposal())
    raises(404, rig.service.approve, 'missing', ApproveProposal())


def test_approve_builds_a_scope_with_the_default_host(rig, frozen):
    workflow = make_workflow(rig.workflows)
    link(rig, workflow)
    p = suggest(rig)
    view = rig.service.approve(p['id'], ApproveProposal())
    assert view['status'] == 'approved' and view['approved_at']
    s = p['scope']
    assert s['allowed_hosts'] == ['mail.google.com'] and s['allowed_apps'] == ['Google Chrome']
    assert s['may_finalize'] is False and s['max_actions'] == 40 and s['used'] == 0
    assert s['workflow_id'] == workflow.id and s['workflow_revision'] == workflow.revision and s['proposal_id'] == p['id']
    assert s['window_start'] == '2026-10-17T21:00:00+00:00' and s['window_end'] == '2026-10-18T04:00:00+00:00'  # tonight, 23:00-06:00 Paris
    raises(409, rig.service.approve, p['id'], ApproveProposal())  # only a new suggestion can be approved


def test_approve_normalises_and_validates_hosts(rig, frozen):
    link(rig, make_workflow(rig.workflows))
    p = suggest(rig)
    for bad in (['not a host'], ['localhost'], ['https://mail.google.com'], ['mail.google.com/path'], ['']):
        raises(422, rig.service.approve, p['id'], ApproveProposal(allowed_hosts=bad))
        assert p['status'] == 'suggested' and p['scope'] is None
    rig.service.approve(p['id'], ApproveProposal(allowed_hosts=[' Mail.Google.COM. ', 'mail.google.com', 'docs.example.org'],
                                                allowed_apps=['Google Chrome', '  '], may_finalize=True))
    assert p['scope']['allowed_hosts'] == ['docs.example.org', 'mail.google.com']
    assert p['scope']['allowed_apps'] == ['Google Chrome'] and p['scope']['may_finalize'] is True


def test_revoke_takes_an_approval_back(rig, frozen):
    link(rig, make_workflow(rig.workflows))
    p = suggest(rig)
    raises(409, rig.service.revoke, p['id'])  # nothing to take back yet
    rig.service.approve(p['id'], ApproveProposal())
    view = rig.service.revoke(p['id'])
    assert view['status'] == 'suggested' and p['scope'] is None and p['approved_at'] is None


def test_dismiss_suppresses_the_pair_for_fourteen_days(rig, frozen, monkeypatch):
    p = suggest(rig)
    rig.service.dismiss(p['id'])
    assert p['status'] == 'dismissed' and p['scope'] is None
    assert rig.service.suppressed(p['pair_key'], NOW + timedelta(days=13))
    assert not rig.service.suppressed(p['pair_key'], NOW + timedelta(days=15))
    raises(409, rig.service.dismiss, p['id'])
    # the user does A again later the same day: a NEW gap (different trigger) for the same pair must stay quiet
    rig.discovery.state['occurrences']['a-late'] = occurrence('a-late', hm(0, 13))
    rig.discovery.state['patterns']['pa']['occurrence_ids'].insert(0, 'a-late')
    later = NOW + timedelta(hours=4)
    gaps = find_gaps(rig.discovery.state, later)
    assert len(gaps) == 1 and gaps[0]['pair_key'] == p['pair_key'] and gaps[0]['gap_key'] != p['gap_key']  # the control: it IS a new gap
    monkeypatch.setattr(night, 'utcnow', lambda: later)
    rig.discovery.state['cursor'] = later.isoformat()  # history has been scanned up to the new moment
    analysis = asyncio.run(rig.service.analyze())
    assert analysis['routine_gaps'] == 1 and analysis['new_suggestions'] == 0
    assert len(rig.service.proposals) == 1
    rig.service.state['suppressed'].clear()
    assert asyncio.run(rig.service.analyze())['new_suggestions'] == 1  # without the dismissal it would have been suggested


def test_dismissing_an_approved_proposal_clears_the_scope(rig, frozen):
    link(rig, make_workflow(rig.workflows))
    p = suggest(rig)
    rig.service.approve(p['id'], ApproveProposal())
    rig.service.dismiss(p['id'])
    assert p['status'] == 'dismissed' and p['scope'] is None


# ---------------------------------------------------------------- 4b. unfinished-work pass
@pytest.fixture
def unfinished(tmp_path, monkeypatch):
    state = {'patterns': {'pu': {'id': 'pu', 'title': 'Weekly update', 'status': 'active', 'occurrence_ids': ['u1', 'u2'], 'workflow_id': None, 'apps': ['Google Chrome']}},
             'occurrences': {'u1': occurrence('u1', NOW - timedelta(hours=5)), 'u2': occurrence('u2', NOW - timedelta(hours=4))},
             'cursor': None, 'scan': {'status': 'idle'}, 'last_attempt': None}
    rig = build(tmp_path, state)
    rig.settings.nightshift_unfinished_pass = True
    rig.workflow = make_workflow(rig.workflows)
    state['patterns']['pu']['workflow_id'] = rig.workflow.id
    rig.calls, rig.answer = [], None

    async def ask(messages):
        rig.calls.append(messages)
        if isinstance(rig.answer, Exception):
            raise rig.answer
        return rig.answer
    monkeypatch.setattr(rig.service, 'ask_model', ask)
    monkeypatch.setattr(night, 'utcnow', lambda: NOW)
    return rig


def finding(rig, **changes):
    return {'occurrence_ids': ['u1'], 'unfinished': 'Draft never sent', 'why': 'Compose window left open',
            'workflow_id': rig.workflow.id, 'confidence': 0.85, **changes}


def test_unfinished_pass_valid_finding_creates_a_proposal(unfinished):
    unfinished.answer = json.dumps({'findings': [finding(unfinished)]})
    assert asyncio.run(unfinished.service.unfinished_pass(NOW)) is None
    [p] = unfinished.service.proposals.values()
    assert p['kind'] == 'unfinished_work' and p['status'] == 'suggested' and p['workflow_id'] == unfinished.workflow.id
    assert p['expected_pattern_id'] == 'pu' and p['apps'] == ['Google Chrome'] and p['confidence'] == 0.85
    assert 'Draft never sent' in p['rationale'] and [e['id'] for e in p['evidence']] == ['u1']
    assert p['trigger_ended_at'] == (NOW - timedelta(hours=5) + timedelta(minutes=10)).isoformat()
    assert unfinished.service.public(p)['eligibility']['state'] == 'ready'
    payload = json.loads(unfinished.calls[0][1]['content'])
    assert {o['id'] for o in payload['occurrences']} == {'u1', 'u2'} and [w['id'] for w in payload['workflows']] == [unfinished.workflow.id]


@pytest.mark.parametrize('changes', [
    {'occurrence_ids': ['does-not-exist']}, {'occurrence_ids': ['u1', 'ghost']}, {'workflow_id': 'unknown-workflow'},
    {'workflow_id': None}, {'confidence': 0.3}], ids=['unknown-occurrence', 'partly-unknown-occurrence', 'unknown-workflow', 'no-workflow', 'low-confidence'])
def test_unfinished_pass_drops_unverifiable_findings(unfinished, changes):
    unfinished.answer = json.dumps({'findings': [finding(unfinished, **changes)]})
    assert asyncio.run(unfinished.service.unfinished_pass(NOW)) is None
    assert unfinished.service.proposals == {}
    assert len(unfinished.calls) == 1


@pytest.mark.parametrize('answer', ['not json at all', '{"findings": "x"}', '[]', '{"findings":[{"unfinished":"x"}]}', OpenAIError('boom')])
def test_unfinished_pass_tolerates_malformed_output(unfinished, answer):
    unfinished.answer = answer
    note = asyncio.run(unfinished.service.unfinished_pass(NOW))
    assert note and 'unavailable' in note
    assert unfinished.service.proposals == {}
    # a failed pass is not remembered, so the next scan can try again
    unfinished.answer = json.dumps({'findings': [finding(unfinished)]})
    assert asyncio.run(unfinished.service.unfinished_pass(NOW)) is None and len(unfinished.service.proposals) == 1


def test_unfinished_pass_malformed_output_does_not_break_analyze(unfinished):
    unfinished.answer = '{oops'
    analysis = asyncio.run(unfinished.service.analyze())
    assert 'unavailable' in analysis['note'] and analysis['new_suggestions'] == 0


def test_unfinished_pass_does_not_ask_again_for_unchanged_history(unfinished):
    unfinished.answer = json.dumps({'findings': []})
    asyncio.run(unfinished.service.unfinished_pass(NOW))
    asyncio.run(unfinished.service.unfinished_pass(NOW + timedelta(hours=1)))
    assert len(unfinished.calls) == 1
    asyncio.run(unfinished.service.unfinished_pass(NOW + timedelta(hours=7)))
    assert len(unfinished.calls) == 2


def test_unfinished_pass_needs_an_approved_workflow_and_the_setting(unfinished):
    unfinished.answer = json.dumps({'findings': [finding(unfinished)]})
    unfinished.settings.nightshift_unfinished_pass = False
    assert asyncio.run(unfinished.service.unfinished_pass(NOW)) is None and unfinished.calls == []
    unfinished.settings.nightshift_unfinished_pass = True
    unfinished.workflows.update(unfinished.workflow.id, UpdateWorkflow(expected_revision=1, title='Edited'))  # no longer approved
    assert asyncio.run(unfinished.service.unfinished_pass(NOW)) is None and unfinished.calls == []


def test_unfinished_pass_skips_a_workflow_that_already_has_an_open_proposal(unfinished):
    unfinished.answer = json.dumps({'findings': [finding(unfinished)]})
    asyncio.run(unfinished.service.unfinished_pass(NOW))
    unfinished.answer = json.dumps({'findings': [finding(unfinished, occurrence_ids=['u2'])]})
    asyncio.run(unfinished.service.unfinished_pass(NOW + timedelta(hours=7)))
    assert len(unfinished.service.proposals) == 1


# ---------------------------------------------------------------- 5. the night runner
def call(name, arguments, _ids=count(1)):
    return ChatCompletionMessage(role='assistant', tool_calls=[{'id': f'call-{next(_ids)}', 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(arguments)}}])


def say(outcome, summary):
    return ChatCompletionMessage(role='assistant', content=json.dumps({'outcome': outcome, 'summary': summary}))


class Client:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=next(self.messages))])

    async def close(self):
        pass


class HangingClient(Client):
    def __init__(self):
        super().__init__([])

    async def create(self, **kwargs):
        await asyncio.Event().wait()


def zv(tool, arguments, reason='Prepare the draft', title=TITLE):
    return call('zavora', {'tool': tool, 'arguments': arguments, 'window_title': title, 'reason': reason})


def look():
    return [call('list_apps', {}), zv('get_ui_tree', {'window_id': 1}, 'Read the page')]


def compose_and_verify():
    return [zv('click_element', {'window_id': 1, 'label': 'Compose'}, 'Open a new draft'),
            call('verify_text', {'window_id': 1, 'window_title': TITLE, 'role': 'AXButton', 'label': 'Compose', 'property': 'label', 'expected': 'Compose'})]


@pytest.fixture
def shift(tmp_path, monkeypatch):
    """A real service + real ExecutionManager; the model and the desktop are scripted. The night window is open right now."""
    rig = build(tmp_path, {'patterns': {'pb': {'id': 'pb', 'title': 'Send weekly update', 'status': 'active', 'occurrence_ids': [],
                                               'workflow_id': None, 'apps': ['Google Chrome']}},
                           'occurrences': {}, 'cursor': None, 'scan': {'status': 'idle'}, 'last_attempt': None})
    rig.client, rig.performed, rig.opened, rig.unlocked = Client([]), [], [], True
    monkeypatch.setattr(execution.Agent, 'create_client', lambda self: rig.client)

    async def desktop(name, args, timeout):
        rig.performed.append((name, args.get('tool')))
        return {'verified': True} if name == 'verify_text' else {'ok': True}

    async def fake_open(url):
        rig.opened.append(url)
        return {'opened': url}

    async def refreshed():
        rig.refreshed = getattr(rig, 'refreshed', 0) + 1
    monkeypatch.setattr(execution, 'call_desktop', desktop)
    monkeypatch.setattr(execution, 'open_url', fake_open)
    monkeypatch.setattr(night, 'desktop_unlocked', lambda: rig.unlocked)
    monkeypatch.setattr(rig.service, 'refresh_context', refreshed)
    rig.set_window = lambda **changes: rig.service.update_settings(NightSettings(**{'enabled': True, 'timezone': 'UTC', **changes}))
    real = datetime.now(UTC)
    rig.set_window(window_start=(real - timedelta(hours=2)).time(), window_end=(real + timedelta(hours=2)).time())
    rig.workflow = make_workflow(rig.workflows)
    rig.discovery.state['patterns']['pb']['workflow_id'] = rig.workflow.id
    return rig


def approved(rig, key='k1', confidence=0.9, **fields):
    p = rig.service.add_proposal(datetime.now(UTC), gap_key=key, pair_key=f'pair-{key}', kind='missed_next_step', title='Send weekly update',
        rationale='After “Export” you usually do “Send weekly update”.', confidence=confidence, workflow_id=rig.workflow.id,
        expected_pattern_id='pb', apps=['Google Chrome'], trigger_ended_at=(datetime.now(UTC) - timedelta(hours=3)).isoformat(),
        evidence=[], stats={}, **fields)
    rig.service.approve(key, ApproveProposal())
    return p


async def night_tick(rig, key='k1'):
    await rig.service.tick()
    p = rig.service.proposals[key]
    worker = rig.executions.workers.get(p['run_id']) if p['run_id'] else None
    if worker:
        await worker
    await rig.service.tick()  # reap
    return p, rig.executions.runs.get(p['run_id'] or '')


def test_in_scope_actions_are_auto_approved_and_the_run_completes(shift):
    p = approved(shift)
    shift.client = Client([*look(), *compose_and_verify(), say('completed', 'Draft is ready')])
    p, run = asyncio.run(night_tick(shift))
    assert run['status'] == 'completed' and run['triggered_by'] == 'night' and run['proposal_id'] == p['id'] and run['notify'] is False
    assert run['workflow_id'] == shift.workflow.id and run['pending_action'] is None
    approvals = [e for e in run['events'] if e['kind'] == 'approval']
    assert approvals and {e['title'] for e in approvals} == {'Inside the approved overnight scope'}  # nobody was asked
    assert any(e['kind'] == 'approved' and e['detail']['auto'] == 'scope' for e in run['events'])
    assert ('zavora', 'click_element') in shift.performed and not shift.executions.decisions
    assert run['scope']['used'] == 1 and p['scope']['used'] == 1
    assert p['status'] == 'done' and p['outcome']['kind'] == 'completed' and p['night_of'] and p['finished_at']
    assert p['outcome']['actions_completed'] == 1 and p['outcome']['checks_passed'] == 1 and p['outcome']['checks_failed'] == 0
    assert shift.service.note is None and shift.refreshed == 1  # context was refreshed before starting
    RunRecord.model_validate(run)


@pytest.mark.parametrize('final', [
    zv('click_element', {'window_id': 1, 'label': 'Send'}, 'Send the draft'),
    zv('key', {'text': 'ctrl+Return', 'target_window_id': 1}, 'Use the keyboard shortcut')], ids=['send-button', 'ctrl-return'])
def test_final_step_stops_the_run_and_the_proposal_is_prepared(shift, final):
    p = approved(shift)
    shift.client = Client([*look(), *compose_and_verify(), final, say('completed', 'must never be reached')])
    p, run = asyncio.run(night_tick(shift))
    assert run['status'] == 'blocked' and run['scope_stop']['kind'] == 'irreversible'
    assert ('zavora', 'key') not in shift.performed and p['scope']['used'] == 1
    assert p['status'] == 'done' and p['outcome']['kind'] == 'prepared' and 'Everything before the final step is ready' in p['outcome']['summary']
    assert any(e['kind'] == 'scope' for e in run['events'])
    assert run['report']['scope_stop']['kind'] == 'irreversible'
    record = RunRecord.model_validate(run)
    assert record.triggered_by == 'night' and record.scope_stop['kind'] == 'irreversible' and record.proposal_id == p['id']


def test_may_finalize_lets_the_night_run_press_send(shift):
    p = approved(shift)
    p['scope']['may_finalize'] = True
    shift.client = Client([*look(), *compose_and_verify(),
                           zv('click_element', {'window_id': 1, 'label': 'Send'}, 'Send the draft'),
                           call('verify_text', {'window_id': 1, 'window_title': TITLE, 'role': 'AXStaticText', 'label': 'Message sent', 'property': 'label', 'expected': 'Message sent'}),
                           say('completed', 'Sent')])
    p, run = asyncio.run(night_tick(shift))
    assert run['status'] == 'completed' and p['outcome']['kind'] == 'completed' and p['scope']['used'] == 2


def test_out_of_scope_open_url_blocks(shift):
    approved(shift)
    shift.client = Client([call('open_url', {'url': 'https://evil.example.com/login', 'reason': 'Open the site'}), say('completed', 'unreachable')])
    p, run = asyncio.run(night_tick(shift))
    assert run['status'] == 'blocked' and run['scope_stop']['kind'] == 'outside_scope' and 'evil.example.com' in run['scope_stop']['reason']
    assert shift.opened == [] and shift.executions.decisions == {}
    assert p['status'] == 'done' and p['outcome']['kind'] == 'needs_you'


def test_in_scope_open_url_is_opened_without_asking(shift):
    approved(shift)

    async def no_sleep(_):
        pass
    shift.client = Client([call('open_url', {'url': 'https://mail.google.com/mail/u/0/#inbox', 'reason': 'Gmail is not the active tab'}),
                           say('blocked', 'stop here')])
    import backend.execution as module
    original = module.asyncio.sleep
    module.asyncio.sleep = no_sleep
    try:
        p, run = asyncio.run(night_tick(shift))
    finally:
        module.asyncio.sleep = original
    assert shift.opened == ['https://mail.google.com/mail/u/0/#inbox'] and run['scope']['used'] == 1
    assert [e for e in run['events'] if e['kind'] == 'approval'][0]['title'] == 'Inside the approved overnight scope'


def test_window_outside_the_approved_apps_blocks(shift):
    approved(shift)
    shift.client = Client([call('list_apps', {}), zv('get_ui_tree', {'window_id': 2}, 'Read', title='Untitled - Notepad'),
                           zv('click_element', {'window_id': 2, 'label': 'Text editor'}, 'Type in Notepad', title='Untitled - Notepad'),
                           say('completed', 'unreachable')])
    p, run = asyncio.run(night_tick(shift))
    assert run['status'] == 'blocked' and run['scope_stop']['kind'] == 'outside_scope'
    assert p['outcome']['kind'] == 'needs_you' and ('zavora', 'click_element') not in shift.performed


def test_action_budget_stops_the_run(shift):
    p = approved(shift)
    p['scope']['max_actions'] = 1
    shift.client = Client([*look(), *compose_and_verify(), zv('click_element', {'window_id': 1, 'label': 'Subject'}, 'Focus the subject'), say('completed', 'unreachable')])
    p, run = asyncio.run(night_tick(shift))
    assert run['status'] == 'blocked' and run['scope_stop']['kind'] == 'budget' and p['scope']['used'] == 1


def test_model_blocked_without_scope_stop_needs_you(shift):
    approved(shift)
    shift.client = Client([say('blocked', 'A sign-in page appeared')])
    p, run = asyncio.run(night_tick(shift))
    assert run['status'] == 'blocked' and 'scope_stop' not in run
    assert p['outcome']['kind'] == 'needs_you' and p['outcome']['summary'] == 'A sign-in page appeared'


def test_locked_desktop_leaves_the_proposal_approved_then_runs_once_unlocked(shift):
    p = approved(shift)
    shift.unlocked = False
    asyncio.run(shift.service.tick())
    assert p['status'] == 'approved' and shift.executions.runs == {}
    assert shift.service.note.startswith('Waiting') and 'locked' in shift.service.note
    assert shift.service.status()['note'] == shift.service.note
    shift.unlocked = True
    shift.client = Client([say('blocked', 'nothing to do')])
    p, run = asyncio.run(night_tick(shift))
    assert run is not None and p['status'] == 'done' and shift.service.note is None


def test_already_done_follow_up_is_skipped(shift):
    p = approved(shift)
    done_at = datetime.now(UTC) - timedelta(hours=1)
    shift.discovery.state['occurrences']['mine'] = occurrence('mine', done_at)
    shift.discovery.state['patterns']['pb']['occurrence_ids'].append('mine')
    p, run = asyncio.run(night_tick(shift))
    assert run is None and shift.executions.runs == {}
    assert p['status'] == 'skipped' and p['outcome']['kind'] == 'skipped' and 'already did this yourself' in p['outcome']['summary']


def test_workflow_edited_after_approval_is_skipped(shift):
    p = approved(shift)
    shift.workflows.update(shift.workflow.id, UpdateWorkflow(expected_revision=shift.workflow.revision, title='Renamed after approval'))
    p, run = asyncio.run(night_tick(shift))
    assert run is None and shift.executions.runs == {}
    assert p['status'] == 'skipped' and 'changed after you approved' in p['outcome']['summary']


def test_archived_workflow_is_skipped(shift):
    approved(shift)
    shift.workflows.archive(shift.workflow.id)
    p, run = asyncio.run(night_tick(shift))
    assert run is None and p['status'] == 'skipped' and 'archived' in p['outcome']['summary']


def test_window_that_passed_without_a_start_is_missed(shift):
    p = approved(shift)
    p['scope']['window_end'] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    p, run = asyncio.run(night_tick(shift))
    assert run is None and p['status'] == 'missed' and p['outcome']['kind'] == 'missed' and shift.executions.runs == {}
    assert 'Nothing was changed' in p['outcome']['summary']


def test_nothing_starts_outside_the_window_or_while_disabled(shift):
    real = datetime.now(UTC)
    p = approved(shift)
    config = shift.service.config
    inside = dict(config)
    config.update(window_start=(real + timedelta(hours=3)).strftime('%H:%M:00'), window_end=(real + timedelta(hours=5)).strftime('%H:%M:00'))
    asyncio.run(shift.service.tick())
    assert p['status'] == 'approved' and shift.executions.runs == {}
    config.update(inside, enabled=False)
    asyncio.run(shift.service.tick())
    assert p['status'] == 'approved' and shift.executions.runs == {}


def test_moving_the_window_takes_every_approval_back(shift):
    real = datetime.now(UTC)
    p = approved(shift)
    shift.set_window(window_start=(real + timedelta(hours=3)).time(), window_end=(real + timedelta(hours=5)).time())
    assert p['status'] == 'suggested' and p['scope'] is None


def test_a_partial_settings_patch_keeps_the_other_fields(shift):
    from backend.nightshift import NightSettingsPatch
    before = dict(shift.service.config)
    shift.service.update_settings(NightSettingsPatch(max_tasks_per_night=2))
    assert shift.service.config == {**before, 'max_tasks_per_night': 2}


def test_window_start_and_end_must_differ():
    with pytest.raises(ValueError):
        NightSettings(window_start='23:00', window_end='23:00')


def test_only_the_most_confident_proposal_starts_and_one_at_a_time(shift):
    approved(shift, 'low', confidence=0.7)
    approved(shift, 'high', confidence=0.95)
    shift.client = HangingClient()

    async def scenario():
        await shift.service.tick()
        await asyncio.sleep(0)
        await shift.service.tick()  # a live run: nothing else may start
        assert shift.service.proposals['high']['status'] == 'running' and shift.service.proposals['low']['status'] == 'approved'
        assert len(shift.executions.runs) == 1
        await shift.executions.stop(shift.service.proposals['high']['run_id'])
    asyncio.run(scenario())


def test_disabling_night_shift_stops_an_active_run(shift):
    p = approved(shift)
    shift.client = HangingClient()

    async def scenario():
        await shift.service.tick()
        for _ in range(5):
            await asyncio.sleep(0)
        run = shift.executions.runs[p['run_id']]
        assert p['status'] == 'running' and run['status'] == 'running'
        shift.service.update_settings(NightSettings(**{**shift.service.config, 'enabled': False}))
        await shift.service.tick()
        return run
    run = asyncio.run(scenario())
    assert run['status'] == 'cancelled' and p['status'] == 'done' and p['finished_at']
    assert shift.service.running() is None


def test_run_now_requires_night_shift_to_be_enabled(shift):
    p = approved(shift)
    shift.set_window(enabled=False, window_start=shift.service.config['window_start'], window_end=shift.service.config['window_end'])
    error = raises(409, lambda k: asyncio.run(shift.service.run_now(k)), p['id'])
    assert 'Turn on Night shift' in error.detail and p['status'] == 'approved' and shift.executions.runs == {}


def test_run_now_starts_an_approved_proposal_for_forty_five_minutes(shift):
    p = approved(shift)
    shift.client = Client([say('blocked', 'Needs a sign-in')])

    async def scenario():
        view = await shift.service.run_now(p['id'])
        await shift.executions.workers[p['run_id']]
        return view
    view = asyncio.run(scenario())
    assert view['status'] == 'running' and p['night_of']
    left = datetime.fromisoformat(p['scope']['window_end']) - datetime.now(UTC)
    assert timedelta(minutes=44) < left <= timedelta(minutes=45)
    raises(409, lambda k: asyncio.run(shift.service.run_now(k)), p['id'])  # no longer approved
    raises(404, lambda k: asyncio.run(shift.service.run_now(k)), 'missing')


def test_run_now_refuses_while_another_overnight_task_runs(shift):
    first, second = approved(shift, 'a'), approved(shift, 'b')
    shift.client = HangingClient()

    async def scenario():
        await shift.service.run_now('a')
        with pytest.raises(HTTPException) as caught:
            await shift.service.run_now('b')
        await shift.executions.stop(first['run_id'])
        return caught.value
    assert asyncio.run(scenario()).status_code == 409 and second['status'] == 'approved'


# ---------------------------------------------------------------- 6. report, review, restart
def finished(service, key, status, kind, summary='', finished_at='2026-10-18T05:00:00+00:00', **outcome):
    p = service.add_proposal(NOW, gap_key=key, pair_key=f'pair-{key}', kind='missed_next_step', title=f'Task {key}', rationale=f'Noticed {key}',
        confidence=0.9, workflow_id='w', expected_pattern_id='pb', apps=[], trigger_ended_at=NOW.isoformat(), evidence=[], stats={})
    p.update(status=status, finished_at=finished_at, outcome={'kind': kind, 'summary': summary, **outcome})
    return p


def test_empty_report(rig):
    report = rig.service.report()
    assert report['items'] == [] and report['headline'] == 'Nothing happened overnight that needs your review.'
    assert set(report['counts'].values()) == {0}


def test_report_headline_counts_and_items(rig):
    s = rig.service
    finished(s, 'c', 'done', 'completed', 'Draft sent', '2026-10-18T05:00:00+00:00', actions_attempted=3, actions_completed=3, checks_passed=2, checks_failed=0)
    finished(s, 'p', 'done', 'prepared', 'Ready to send', '2026-10-18T04:00:00+00:00')
    finished(s, 'n', 'done', 'needs_you', 'Sign in', '2026-10-18T03:00:00+00:00')
    finished(s, 'f', 'done', 'failed', 'Crashed', '2026-10-18T02:00:00+00:00')
    finished(s, 's', 'skipped', 'skipped', 'You did it', '2026-10-18T01:00:00+00:00')
    finished(s, 'm', 'missed', 'missed', 'Window ended', '2026-10-18T00:00:00+00:00')
    s.add_proposal(NOW, gap_key='open', pair_key='x', kind='missed_next_step', title='Still open', rationale='r', confidence=0.9, workflow_id='w',
                   expected_pattern_id='pb', apps=[], trigger_ended_at=NOW.isoformat(), evidence=[], stats={})
    report = s.report()
    assert report['counts'] == {'completed': 1, 'prepared': 1, 'needs_you': 1, 'failed': 1, 'skipped': 1, 'missed': 1}
    assert report['headline'] == 'While you were away: 2 tasks done or prepared, 1 need you, 1 failed, 1 skipped, 1 did not run.'
    assert [i['id'] for i in report['items']] == ['c', 'p', 'n', 'f', 's', 'm']  # newest first; the open suggestion is not a result
    by = {i['id']: i for i in report['items']}
    assert by['c']['noticed'] == 'Noticed c' and by['c']['did'] == 'Draft sent' and by['c']['steps']['actions_completed'] == 3
    assert [by[k]['needs_attention'] for k in 'cpnfsm'] == [False, True, True, True, False, False]
    assert by['p']['next_step'] == 'Take a look, then finish the last step yourself (for example press Send).' and by['m']['scope'] is None
    s.review('c', ReviewProposal(verdict='looks_good'))
    assert s.report()['counts']['completed'] == 0 and len(s.report()['items']) == 5  # reviewed items leave the morning list


def test_report_headline_singular(rig):
    finished(rig.service, 'c', 'done', 'completed', 'ok')
    assert rig.service.report()['headline'] == 'While you were away: 1 task done or prepared.'


def run_record(status='completed', **extra):
    return {'id': 'r1', 'task_id': 't', 'title': 'Send weekly update', 'status': status, 'started_at': NOW.isoformat(), 'finished_at': NOW.isoformat(),
            'elapsed_seconds': 1.0, 'summary': 'ok', 'pending_action': None, 'events': [], 'request': {}, **extra}


def test_review_stores_feedback_on_the_run(rig, frozen):
    p = finished(rig.service, 'c', 'done', 'completed', 'ok', run_id=None)
    p['run_id'] = 'r1'
    rig.executions.runs['r1'] = run_record()
    view = rig.service.review('c', ReviewProposal(verdict='looks_good', notes='Perfect'))
    assert view['status'] == 'reviewed' and p['review']['verdict'] == 'looks_good' and p['review']['notes'] == 'Perfect'
    feedback = rig.executions.runs['r1']['feedback']
    assert feedback['verdict'] == 'looks_good' and feedback['notes'] == 'Perfect'
    assert rig.repository.read('runs', {})['r1']['feedback']['verdict'] == 'looks_good'
    assert not rig.service.suppressed(p['pair_key'], NOW)
    raises(409, rig.service.review, 'c', ReviewProposal(verdict='looks_good'))  # only once


def test_review_something_wrong_suppresses_the_pair(rig, frozen):
    p = finished(rig.service, 'w', 'done', 'prepared', 'Ready')
    p['run_id'] = 'r1'
    rig.executions.runs['r1'] = run_record('blocked')
    rig.service.review('w', ReviewProposal(verdict='something_wrong', notes='Wrong recipient'))
    assert rig.executions.runs['r1']['feedback']['verdict'] == 'something_wrong'
    assert rig.service.suppressed(p['pair_key'], NOW + timedelta(days=13)) and not rig.service.suppressed(p['pair_key'], NOW + timedelta(days=15))


def test_review_rules(rig):
    p = finished(rig.service, 'x', 'done', 'completed', 'ok')
    suggested = rig.service.add_proposal(NOW, gap_key='sug', pair_key='sp', kind='missed_next_step', title='t', rationale='r', confidence=0.9,
        workflow_id='w', expected_pattern_id='pb', apps=[], trigger_ended_at=NOW.isoformat(), evidence=[], stats={})
    raises(409, rig.service.review, suggested['id'], ReviewProposal(verdict='looks_good'))
    raises(404, rig.service.review, 'missing', ReviewProposal(verdict='looks_good'))
    assert rig.service.review('x', ReviewProposal(verdict='looks_good'))['status'] == 'reviewed'  # no run record: still reviewable
    with pytest.raises(ValidationError):
        ReviewProposal(verdict='great')


def test_reap_after_restart_finalizes_a_running_proposal(tmp_path):
    first = build(tmp_path, routine_state())
    first.executions.runs['r1'] = run_record('running', pending_action=None)
    first.executions.persist()
    p = finished(first.service, 'live', 'running', 'x')
    p.update(run_id='r1', finished_at=None, outcome=None)
    ghost = finished(first.service, 'ghost', 'running', 'x')
    ghost.update(run_id='nope', finished_at=None, outcome=None)
    first.service.save()

    restarted_executions = ExecutionManager(first.settings, first.repository)  # a restart interrupts every active run
    assert restarted_executions.runs['r1']['status'] == 'interrupted'
    service = NightShift(first.repository, first.discovery, first.workflows, restarted_executions, first.settings)
    live, lost = service.proposals['live'], service.proposals['ghost']
    assert live['status'] == 'done' and live['outcome']['kind'] == 'failed' and live['finished_at']
    assert 'Server restarted' in live['outcome']['run_summary']
    assert lost['status'] == 'done' and lost['outcome']['kind'] == 'failed' and 'missing' in lost['outcome']['summary']
    assert service.running() is None
    assert NightShift(first.repository, first.discovery, first.workflows, restarted_executions, first.settings).proposals['live']['status'] == 'done'  # persisted


def test_reap_leaves_a_genuinely_active_run_alone(rig):
    p = finished(rig.service, 'live', 'running', 'x')
    p.update(run_id='r1', finished_at=None, outcome=None)
    rig.executions.runs['r1'] = run_record('running')
    rig.service.reap()
    assert p['status'] == 'running'
    rig.executions.runs['r1']['status'] = 'completed'
    rig.service.reap()
    assert p['status'] == 'done' and p['outcome']['kind'] == 'completed'


# ---------------------------------------------------------------- 7. API
def api_proposal(key='api', workflow_id=None):
    return main.nightshift.add_proposal(datetime.now(UTC), gap_key=key, pair_key=f'pair-{key}', kind='missed_next_step', title='Send weekly update',
        rationale='r', confidence=0.9, workflow_id=workflow_id, expected_pattern_id='pb', apps=['Google Chrome'],
        trigger_ended_at=datetime.now(UTC).isoformat(), evidence=[], stats={})


def test_api_status_and_settings(monkeypatch):
    monkeypatch.setattr(night, 'desktop_unlocked', lambda: True)
    with TestClient(main.app) as client:
        status = client.get('/nightshift/status')
        assert status.status_code == 200
        body = status.json()
        assert body['settings']['enabled'] is False and body['window']['opens_at'] and body['counts']['suggested'] == 0 and body['desktop_unlocked'] is True
        assert body['limits']
        patched = client.patch('/nightshift/settings', json={'enabled': True, 'timezone': 'Europe/Paris', 'window_start': '22:00',
                                                            'window_end': '05:00', 'max_tasks_per_night': 2, 'max_actions_per_task': 30})
        assert patched.status_code == 200
        assert patched.json()['settings']['enabled'] is True and patched.json()['settings']['window_start'] == '22:00:00'
        assert main.nightshift.config['max_tasks_per_night'] == 2
        assert main.repository.read('nightshift', {})['settings']['enabled'] is True
        for bad in ({'timezone': 'Mars/Base'}, {'window_start': '25:00'}, {'max_tasks_per_night': 0}, {'unknown': 1}):
            assert client.patch('/nightshift/settings', json=bad).status_code == 422
        assert main.nightshift.config['enabled'] is True  # rejected bodies changed nothing
        assert client.patch('/nightshift/settings', json={'enabled': False}).json()['settings']['enabled'] is False


def test_api_proposals_report_and_404s():
    with TestClient(main.app) as client:
        assert client.get('/nightshift/proposals').json() == []
        report = client.get('/nightshift/report').json()
        assert report['items'] == [] and report['headline'].startswith('Nothing happened')
        api_proposal('one')
        listed = client.get('/nightshift/proposals').json()
        assert [p['id'] for p in listed] == ['one'] and listed[0]['eligibility']['state'] == 'no_workflow' and listed[0]['run_status'] is None
        assert client.get('/nightshift/proposals', params={'status': 'approved'}).json() == []
        assert client.get('/nightshift/proposals', params={'status': 'suggested'}).json()[0]['id'] == 'one'
        for action in ('approve', 'revoke', 'dismiss', 'run-now', 'review'):
            body = {'verdict': 'looks_good'} if action == 'review' else {}
            assert client.post(f'/nightshift/proposals/missing/{action}', json=body).status_code == 404, action
        assert client.post('/nightshift/proposals/one/approve', json={}).status_code == 409  # no workflow behind it
        assert client.post('/nightshift/proposals/one/review', json={'verdict': 'looks_good'}).status_code == 409  # not finished
        assert client.post('/nightshift/proposals/one/review', json={'verdict': 'bogus'}).status_code == 422
        assert client.post('/nightshift/proposals/one/revoke').status_code == 409


def test_api_approve_revoke_dismiss_and_review_flow():
    workflow = make_workflow(main.workflows)
    with TestClient(main.app) as client:
        api_proposal('flow', workflow.id)
        assert client.get('/nightshift/proposals').json()[0]['eligibility']['state'] == 'ready'
        assert client.post('/nightshift/proposals/flow/approve', json={'allowed_hosts': ['not a host']}).status_code == 422
        approved_view = client.post('/nightshift/proposals/flow/approve', json={}).json()
        assert approved_view['status'] == 'approved' and approved_view['scope']['allowed_hosts'] == ['mail.google.com']
        assert approved_view['scope']['may_finalize'] is False
        assert client.post('/nightshift/proposals/flow/run-now').status_code == 409  # Night shift is off
        assert client.post('/nightshift/proposals/flow/revoke').json()['status'] == 'suggested'
        assert client.post('/nightshift/proposals/flow/dismiss').json()['status'] == 'dismissed'
        assert client.post('/nightshift/proposals/flow/dismiss').status_code == 409
        # a finished result is reviewed through the API and the verdict lands on the run
        done = api_proposal('fin')
        done.update(status='done', finished_at=NOW.isoformat(), run_id='r-fin', outcome={'kind': 'completed', 'summary': 'ok'})
        main.executions.runs['r-fin'] = run_record('completed', id='r-fin')
        assert [i['id'] for i in client.get('/nightshift/report').json()['items']] == ['fin']
        reviewed = client.post('/nightshift/proposals/fin/review', json={'verdict': 'looks_good', 'notes': 'Nice'})
        assert reviewed.status_code == 200 and reviewed.json()['status'] == 'reviewed'
        assert main.executions.runs['r-fin']['feedback']['notes'] == 'Nice'
        assert client.get('/nightshift/report').json()['items'] == []


def test_api_serialises_a_night_run_with_scope_fields():
    stop = {'kind': 'irreversible', 'reason': 'Stopped before a final step', 'target': 'Send', 'at': NOW.isoformat()}
    night_scope = {'allowed_hosts': ['mail.google.com'], 'allowed_apps': ['Google Chrome'], 'may_finalize': False, 'max_actions': 40, 'used': 2,
                   'workflow_id': 'w', 'workflow_revision': 1, 'window_start': NOW.isoformat(), 'window_end': NOW.isoformat(), 'proposal_id': 'k1'}
    run = run_record('blocked', id='r-night', workflow_id='w', workflow_revision=1, triggered_by='night', notify=False, proposal_id='k1',
                     scope=night_scope, scope_stop=stop,
                     events=[{'id': 'e1', 'timestamp': NOW.isoformat(), 'kind': 'scope', 'title': 'Stopped: outside the approved overnight scope', 'detail': stop}],
                     request={'values': {}, 'missing_values': {}, 'instructions': '', 'auto_approve': False})
    run['report'] = build_report(run)
    main.executions.runs['r-night'] = run
    with TestClient(main.app) as client:
        response = client.get('/runs/r-night')
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['triggered_by'] == 'night' and body['proposal_id'] == 'k1' and body['notify'] is False
        assert body['scope']['used'] == 2 and body['scope_stop']['kind'] == 'irreversible'
        listed = [r for r in client.get('/runs').json() if r['id'] == 'r-night'][0]
        assert listed['triggered_by'] == 'night' and listed['proposal_id'] == 'k1'
        report = client.get('/runs/r-night/report')
        assert report.status_code == 200 and report.json()['scope_stop']['target'] == 'Send'
        assert any('Unattended run' in line for line in report.json()['limitations'])
        feedback = client.post('/runs/r-night/feedback', json={'verdict': 'looks_good'})
        assert feedback.status_code == 200 and feedback.json()['feedback']['verdict'] == 'looks_good'


# ---- fail-closed guard rules added after the adversarial review ----
SCOPE = {'allowed_hosts': ['mail.google.com'], 'allowed_apps': ['Chrome'], 'may_finalize': False, 'max_actions': 10, 'used': 0,
         'window_end': (NOW + timedelta(hours=3)).isoformat()}


def verdict(name, args, **scope):
    return authorize({**SCOPE, 'used': 0, **scope}, name, args, NOW)


def click(label, **extra):
    return {'tool': 'click_element', 'window_title': 'Inbox - Gmail - Google Chrome', 'reason': 'Open the compose box',
            'arguments': {'window_id': 3, 'label': label}, **extra}


def test_a_mutation_without_a_named_window_is_refused():
    args = click('Compose')
    del args['window_title']
    assert verdict('zavora', args)[0] == 'outside_scope'
    assert verdict('zavora', click('Compose')) is None


def test_no_approved_apps_means_nothing_is_allowed():
    assert verdict('zavora', click('Compose'), allowed_apps=[])[0] == 'outside_scope'


def test_a_control_with_no_label_is_refused():
    args = click('Compose')
    args['arguments'] = {'window_id': 3}
    assert verdict('zavora', args)[0] == 'unsupported'


def test_final_step_labels_in_french_spanish_and_german_are_blocked():
    for label in ('Envoyer', 'Supprimer le brouillon', 'Valider', 'Enviar', 'Eliminar', 'Senden', 'Löschen', 'Approve', 'Archive'):
        assert verdict('zavora', click(label))[0] == 'irreversible', label
    assert verdict('zavora', click('Envoyer'), may_finalize=True) is None


def test_only_editing_keys_are_allowed_while_preparing():
    def key(text):
        return {'tool': 'key', 'window_title': 'Gmail - Google Chrome', 'reason': 'Move to the next field', 'arguments': {'text': text, 'target_window_id': 3}}
    for ok in ('Tab', 'shift+Tab', 'ctrl+a', 'Backspace'):
        assert verdict('zavora', key(ok)) is None, ok
    for bad in ('Return', 'Enter', 'space', 'alt+s', 'ctrl+Return'):
        assert verdict('zavora', key(bad))[0] == 'irreversible', bad
    assert verdict('zavora', key('Return'), may_finalize=True) is None


def test_an_option_that_changes_desktop_safety_checks_is_refused():
    args = click('Compose')
    args['arguments']['override_user_guard'] = True
    assert verdict('zavora', args)[0] == 'unsupported'


def test_activating_another_app_is_refused():
    args = {'tool': 'activate_app', 'window_title': 'Gmail - Google Chrome', 'reason': 'Switch', 'arguments': {'app': 'cmd'}}
    assert verdict('zavora', args)[0] == 'outside_scope'


def test_lookalike_and_odd_urls_are_not_on_the_approved_list():
    for url in ('https://mail.google.com@evil.example/', 'https://evil.example/mail.google.com', 'https://mail.google.com.evil.example/',
                'https://mail.google.com:8443/', 'https://mail.google.com\@evil.example/', 'http://mail.google.com/', 'https://user:pw@mail.google.com/'):
        assert verdict('open_url', {'url': url, 'reason': 'Open Gmail'})[0] == 'outside_scope', url
    assert verdict('open_url', {'url': 'https://mail.google.com/mail/u/0/#inbox', 'reason': 'Open Gmail'}) is None



def test_an_unattended_run_never_starts_a_program():
    result = verdict('launch_app', {'app': 'notepad', 'reason': 'Notepad is not open'})
    assert result[0] == 'unsupported' and 'program' in result[1]
