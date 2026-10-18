"""Run polling must continue after a PDF export is added to persisted run data."""
import pytest
from fastapi.testclient import TestClient
import backend.main as main
from backend.execution import ExecutionManager

PDF = {
    'path': r'C:\Users\Doffa\Desktop\CA HT - Full table - 2026-10-17_23-54-54.pdf',
    'filename': 'CA HT - Full table - 2026-10-17_23-54-54.pdf',
    'bytes': 264739,
    'sha256': '7ddce3d08327e3f0d68e1aefd3319b9eb18748add3ae19e9600775385f6d7ea0',
    'pages': 1,
    'table_labels_verified': [],
    'content_check': 'Image-only PDF: A1:G10 was verified selected in Sheets; PDF cell text was not independently read.'
}


def seed_run(status='completed', exported=True):
    run = dict(id='pdf-run', task_id='chosen', title='Send PDF', status=status,
        started_at='2026-10-18T00:00:00+02:00',
        finished_at='2026-10-18T00:01:00+02:00' if status=='completed' else None,
        elapsed_seconds=60 if status=='completed' else None,
        summary='PDF saved; delivery not asserted by this API test.', pending_action=None,
        events=[], request={'values':{}, 'missing_values':{}, 'instructions':'', 'auto_approve':False})
    if exported:
        run['pdf_export'] = PDF.copy()
    main.executions.runs[run['id']] = run
    return run


@pytest.mark.parametrize('status', ['running','completed'])
def test_run_status_accepts_pdf_export_and_preserves_metadata(status):
    seed_run(status)
    response = TestClient(main.app).get('/runs/pdf-run')
    assert response.status_code == 200
    assert response.json()['pdf_export'] == PDF
    assert response.json()['status'] == status


def test_saved_pdf_run_can_reload_stop_and_receive_feedback(monkeypatch):
    seed_run()
    main.executions.persist()
    restored = ExecutionManager(main.settings, main.repository)
    monkeypatch.setattr(main, 'executions', restored)
    client = TestClient(main.app)
    assert client.get('/runs/pdf-run').json()['pdf_export'] == PDF
    assert client.get('/runs').status_code == 200
    stopped = client.post('/runs/pdf-run/stop')
    assert stopped.status_code == 200
    assert stopped.json()['pdf_export'] == PDF
    reviewed = client.post('/runs/pdf-run/feedback', json={'verdict':'looks_good','notes':'API regression only'})
    assert reviewed.status_code == 200
    assert reviewed.json()['pdf_export'] == PDF


def test_legacy_run_without_pdf_remains_readable():
    seed_run(exported=False)
    response = TestClient(main.app).get('/runs/pdf-run')
    assert response.status_code == 200
    assert response.json().get('pdf_export') is None
