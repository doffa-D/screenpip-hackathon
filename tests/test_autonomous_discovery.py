import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.autonomous_discovery import DiscoveryService, ScanResult, SaveDraft, WorkflowDraft, router
from backend.config import Settings
from backend.repository import Repository
from backend.workflow_store import WorkflowStore

@pytest.fixture
def anyio_backend():
    return 'asyncio'


BASE = datetime(2026, 10, 16, tzinfo=timezone.utc)


def batch(frames=(1, 2), goal='Follow up with clients', existing=None, confidence=.92, app='Gmail', window='Inbox'):
    ledger, members = {}, []
    for frame in frames:
        stamp = (BASE + timedelta(hours=frame)).isoformat()
        quote = f'{stamp}\nApp: {app}\nWindow: {window}\nSource: screenpipe://frame/{frame}\nSent client follow-up {frame}'
        evidence = [{'call_id': f'e{frame}', 'quote': quote, 'source_kind': 'original_activity'}]
        ledger[f'e{frame}'] = {'text': quote, 'tool': 'search-content', 'arguments': {}}
        members.append(dict(title=goal, timestamp=stamp, summary=goal, app=app, window=window, evidence=evidence))
    return ScanResult.model_validate({'groups': [dict(existing_pattern_id=existing, title=goal, summary=goal,
        goal=goal, action_structure=['Open pending client conversation', 'Compose follow-up', 'Send'],
        confidence=confidence, explanation='Same goal and observed action structure', occurrences=members)],
        'coverage_notes': 'Bounded sample, not exhaustive'}), ledger


def service(tmp_path, investigate=None):
    repo = Repository(tmp_path)
    return DiscoveryService(repo, investigate, Settings(discovery_enabled=False), WorkflowStore(repo))


def ingest(s, output, ledger):
    s.commit(s.merge(output, ledger, BASE, BASE + timedelta(days=2)))
    return next(iter(s.state['patterns']))


def test_repeated_semantic_goal_grouped_different_goal_same_app_separate(tmp_path):
    s = service(tmp_path)
    key = ingest(s, *batch())
    assert s.listing()[0]['occurrence_count'] == 2
    ingest(s, *batch((3, 4), goal='Send invoice'))
    assert len(s.listing()) == 2
    assert s.get(key)['goal'] == 'Follow up with clients'


def test_discussion_is_not_counted_even_if_model_labels_original(tmp_path):
    s = service(tmp_path)
    ingest_args = batch(app='Chrome', window='ChatGPT')
    s.commit(s.merge(*ingest_args, BASE, BASE + timedelta(days=2)))
    assert not s.state['occurrences'] and not s.listing()


def test_incremental_count_deduplicates_frame_ids_across_changed_calls(tmp_path):
    s = service(tmp_path)
    key = ingest(s, *batch())
    output, ledger = batch((2, 3), existing=key)
    # Change call IDs, preserving Screenpipe source identities.
    for member in output.groups[0].occurrences:
        old = member.evidence[0].call_id
        member.evidence[0].call_id = 'new_' + old
    ledger = {'new_' + k: v for k, v in ledger.items()}
    ingest(s, output, ledger)
    assert s.listing()[0]['occurrence_count'] == 3
    ingest(s, output, ledger)
    assert s.listing()[0]['occurrence_count'] == 3
    assert len(s.state['patterns']) == 1


def test_overlapping_frames_of_one_occurrence_not_repetition(tmp_path):
    s = service(tmp_path)
    output, ledger = batch()
    first, second = output.groups[0].occurrences
    first.ended_at = second.timestamp
    first.evidence.extend(second.evidence)
    ingest(s, output, ledger)
    assert not s.listing()
    assert len(s.state['occurrences']) == 1


def test_low_confidence_hidden_and_medium_not_high(tmp_path):
    s = service(tmp_path)
    ingest(s, *batch(confidence=.4))
    assert s.listing() == []
    ingest(s, *batch((3, 4), goal='Other goal', confidence=.72))
    assert len(s.listing()) == 1
    assert s.listing()[0]['confidence_label'] == 'medium'


def test_dismissal_and_acceptance_persist_across_incremental_scan_and_reload(tmp_path):
    s = service(tmp_path)
    key = ingest(s, *batch())
    s.decision(key, 'dismissed')
    ingest(s, *batch((3,), existing=key))
    restored = service(tmp_path)
    assert restored.listing() == []
    assert restored.listing(include_dismissed=True)[0]['occurrence_count'] == 3
    restored.decision(key, 'accepted')
    assert service(tmp_path).get(key)['status'] == 'accepted'


@pytest.mark.anyio
async def test_accepted_pattern_draft_compares_all_then_explicit_save(tmp_path):
    seen = []
    async def investigate(request, output_type, ledger):
        seen.append(request)
        evidence = [e for member in request['occurrences'] for e in member['evidence']]
        return WorkflowDraft.model_validate({'title': 'Client follow-up', 'reconstruction': {
            'goal': 'Follow up', 'historical_values': {}, 'steps': [{'description': 'Compose follow-up', 'evidence': evidence}],
            'missing_values': ['client'], 'evidence': evidence}, 'variable_inputs': [dict(name='client',
            description='Recipient', observed_values=[], evidence=evidence)], 'comparison_notes': 'Compared both occurrences'}), ledger
    s = service(tmp_path, investigate)
    key = ingest(s, *batch())
    s.decision(key, 'accepted')
    draft = await s.draft(key)
    assert len(seen[0]['occurrences']) == 2 and seen[0]['evidence_only']
    assert draft['reconstruction']['missing_values'] == ['client']
    assert not s.workflows.list()
    saved = s.save(key, SaveDraft())
    assert saved.task.id == 'discovery:' + key
    assert s.get(key)['status'] == 'saved_as_workflow'
    assert s.save(key, SaveDraft()).id == saved.id
    assert len(s.workflows.list()) == 1


@pytest.mark.anyio
async def test_background_incremental_bounds_and_duplicate_runs(tmp_path):
    calls = []
    async def investigate(request, output_type):
        calls.append(request)
        return ScanResult(groups=[], coverage_notes='No supported matches in bounded sample'), {}
    s = service(tmp_path, investigate)
    s.settings.discovery_lookback_days = 1
    s.kick()
    same = s.kick()
    assert same['status'] == 'queued'
    await s.job
    first_cursor = s.state['cursor']
    s.kick()
    await s.job
    assert len(calls) == 2
    assert calls[0]['strict_interval'] and calls[1]['strict_interval']
    assert datetime.fromisoformat(calls[1]['start_time']) == datetime.fromisoformat(first_cursor) - timedelta(minutes=5)
    assert s.status()['status'] == 'completed'
    assert s.listing() == []


@pytest.mark.anyio
async def test_failed_scan_does_not_advance_cursor_and_can_retry(tmp_path):
    async def fail(*args):
        raise ValueError('Unanchored timestamp')
    s = service(tmp_path, fail)
    s.kick()
    await s.job
    assert s.status()['status'] == 'failed' and s.state['cursor'] is None
    assert s.status()['error'] == 'Unanchored timestamp'
    s.state['scan']['status'] = 'running'
    s.commit(s.state)
    assert service(tmp_path).status()['status'] == 'interrupted'


def test_invalid_source_times_and_unknown_patterns_fail_closed(tmp_path):
    s = service(tmp_path)
    output, ledger = batch()
    output.groups[0].occurrences[0].timestamp += timedelta(minutes=1)
    with pytest.raises(ValueError, match='anchored'):
        ingest(s, output, ledger)
    output, ledger = batch(existing='invented')
    with pytest.raises(ValueError, match='Unknown'):
        ingest(s, output, ledger)
    assert s.listing() == []


def test_api_list_sort_detail_decisions_and_manual_background(tmp_path):
    async def investigate(*args):
        return ScanResult(groups=[], coverage_notes='Sampled'), {}
    s = service(tmp_path, investigate)
    key = ingest(s, *batch())
    app = FastAPI()
    app.include_router(router(s))
    with TestClient(app) as client:
        assert client.get('/discovery/patterns?sort=confidence').json()[0]['occurrence_count'] == 2
        assert len(client.get('/discovery/patterns/' + key).json()['occurrences']) == 2
        assert client.post(f'/discovery/patterns/{key}/accept').json()['status'] == 'accepted'
        assert client.post(f'/discovery/patterns/{key}/save-workflow', json={}).status_code == 409
        assert client.post(f'/discovery/patterns/{key}/dismiss').status_code == 200
        assert client.get('/discovery/patterns').json() == []
        assert client.get('/discovery/patterns?sort=wrong').status_code == 422
        assert client.get('/discovery/patterns/missing').status_code == 404
        assert client.post('/discovery/run').status_code == 202



@pytest.mark.anyio
async def test_background_overlapping_scan_keeps_existing_count(tmp_path, monkeypatch):
    import backend.autonomous_discovery as module
    monkeypatch.setattr(module, 'utcnow', lambda: BASE + timedelta(hours=2, minutes=2))
    outputs = [batch(), batch((2,))]
    async def investigate(*args):
        return outputs.pop(0)
    s = service(tmp_path, investigate)
    s.settings.discovery_lookback_days = 1
    for _ in range(2):
        s.kick()
        await s.job
        assert s.status()['status'] == 'completed'
    assert s.listing()[0]['occurrence_count'] == 2
    assert len(service(tmp_path).state['occurrences']) == 2


def test_overview_cannot_be_relabelled_as_original_evidence(tmp_path):
    s = service(tmp_path)
    output, ledger = batch()
    for entry in ledger.values():
        entry['tool'] = 'activity-summary'
    with pytest.raises(ValueError, match='Summaries'):
        ingest(s, output, ledger)
    assert not s.state['occurrences']


def test_disk_failure_does_not_publish_new_suggestions(tmp_path, monkeypatch):
    s = service(tmp_path)
    output, ledger = batch()
    state = s.merge(output, ledger, BASE, BASE + timedelta(days=2))
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(s.repository, 'write', fail)
    with pytest.raises(OSError):
        s.commit(state)
    assert not s.listing()


@pytest.mark.anyio
async def test_draft_rejects_steps_supported_by_only_one_occurrence(tmp_path):
    async def investigate(request, output_type, ledger):
        evidence = request['occurrences'][0]['evidence']
        return WorkflowDraft.model_validate({'title': 'Unsafe generalization', 'reconstruction': {
            'goal': 'Compose', 'historical_values': {}, 'steps': [{'description': 'Compose', 'evidence': evidence}],
            'missing_values': [], 'evidence': evidence}, 'variable_inputs': [], 'comparison_notes': 'Only one source'}), ledger
    s = service(tmp_path, investigate)
    key = ingest(s, *batch())
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await s.draft(key)
    assert error.value.status_code == 422
    assert s.get(key)['draft'] is None
    assert not s.workflows.list()

def test_evidence_only_draft_synthesis_needs_no_mcp_tools():
    import asyncio
    import json
    from types import SimpleNamespace
    from openai.types.chat import ChatCompletionMessage
    from backend.agent import Agent
    from backend.models import Reconstruction
    from test_backend import FakeClient
    evidence = [{'call_id': 'o0_e1', 'quote': 'Sent follow-up', 'source_kind': 'original_activity'}]
    payload = {'goal': 'Follow up', 'historical_values': {}, 'steps': [], 'missing_values': [], 'evidence': evidence}
    client = FakeClient([ChatCompletionMessage(role='assistant', content=json.dumps(payload))])
    output, ledger = asyncio.run(Agent(Settings(), client).run(SimpleNamespace(tools={}),
        {'evidence_only': True, 'instruction': 'Compare saved excerpts'}, Reconstruction,
        {'o0_e1': {'text': 'Sent follow-up'}}))
    assert output.goal == 'Follow up'
    assert 'tools' not in client.requests[0]
    assert ledger['o0_e1']['text'] == 'Sent follow-up'
