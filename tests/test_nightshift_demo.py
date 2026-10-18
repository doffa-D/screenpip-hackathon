import asyncio
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import backend.main as main


def loaded(client):
    assert client.post('/nightshift/demo').json()['proposals'] == 9
    return {p['id']: p for p in client.get('/nightshift/proposals').json()}


def test_demo_data_fills_every_part_of_the_page_and_is_marked():
    with TestClient(main.app) as client:
        items = loaded(client)
        assert all(p['origin'] == 'demo' for p in items.values())
        status = {}
        for p in items.values():
            status.setdefault(p['status'], []).append(p['id'])
        assert len(status['suggested']) == 3 and len(status['approved']) == 1
        assert len(status['done']) == 3 and len(status['skipped']) == 1 and len(status['reviewed']) == 1
        report = client.get('/nightshift/report').json()
        assert {i['state'] for i in report['items']} == {'completed', 'prepared', 'needs_you', 'skipped'}
        assert all(i['origin'] == 'demo' for i in report['items'])
        assert 'prepared' in report['headline'] or 'done' in report['headline']
        # one suggestion shows the "save it as a workflow first" state, the others can be approved
        eligibility = {p['id']: p['eligibility']['state'] for p in items.values() if p['status'] == 'suggested'}
        assert sorted(eligibility.values()) == ['no_workflow', 'ready', 'ready']


def test_loading_twice_does_not_duplicate_and_clearing_removes_only_demo():
    with TestClient(main.app) as client:
        loaded(client)
        main.nightshift.proposals['real'] = {'id': 'real', 'status': 'suggested', 'created_at': '2026-01-01T00:00:00+00:00'}
        loaded(client)
        assert client.delete('/nightshift/demo').json() == {'removed': 9}
        assert list(main.nightshift.proposals) == ['real']


def test_demo_suggestion_can_be_approved_taken_back_and_reviewed_but_never_runs():
    with TestClient(main.app) as client:
        loaded(client)
        approved = client.post('/nightshift/proposals/demo:weekly-status/approve', json={}).json()
        assert approved['status'] == 'approved' and approved['scope']['allowed_hosts'] == ['mail.google.com']
        assert approved['scope']['may_finalize'] is False
        assert client.post('/nightshift/proposals/demo:backup/approve', json={}).status_code == 409  # no workflow saved
        assert client.post('/nightshift/proposals/demo:weekly-status/run-now').status_code == 409
        assert client.post('/nightshift/proposals/demo:weekly-status/revoke').json()['status'] == 'suggested'
        reviewed = client.post('/nightshift/proposals/demo:invoice/review', json={'verdict': 'looks_good', 'notes': 'ok'}).json()
        assert reviewed['status'] == 'reviewed'
        assert 'demo:invoice' not in [i['id'] for i in client.get('/nightshift/report').json()['items']]


def test_the_night_runner_ignores_demo_proposals():
    with TestClient(main.app):
        now = datetime.now(timezone.utc)
        main.nightshift.config.update(enabled=True, timezone='UTC', window_start=(now - timedelta(hours=2)).strftime('%H:%M:00'),
                                      window_end=(now + timedelta(hours=2)).strftime('%H:%M:00'))
        main.nightshift.seed_demo()
        # even an approved demo proposal whose window is active and whose window already closed must stay untouched
        main.nightshift.proposals['demo:weekly-report']['scope']['window_end'] = (now - timedelta(hours=1)).isoformat()
        asyncio.run(main.nightshift.tick())
        assert main.nightshift.proposals['demo:weekly-report']['status'] == 'approved'
        assert main.executions.runs == {}


def test_demo_examples_load_at_startup_and_never_replace_real_proposals(monkeypatch):
    monkeypatch.setattr(main.settings, 'nightshift_demo', True)
    with TestClient(main.app) as client:
        assert len(client.get('/nightshift/proposals').json()) == 9  # nothing to click: it is simply there
    main.nightshift.proposals['real'] = {'id': 'real', 'status': 'suggested', 'created_at': '2026-01-01T00:00:00+00:00'}
    before = len(main.nightshift.proposals)
    with TestClient(main.app):
        assert len(main.nightshift.proposals) == before  # real work present: demo is left alone, not reseeded


def test_turning_the_demo_setting_off_removes_the_examples(monkeypatch):
    main.nightshift.seed_demo()
    monkeypatch.setattr(main.settings, 'nightshift_demo', False)
    with TestClient(main.app) as client:
        assert client.get('/nightshift/proposals').json() == []
