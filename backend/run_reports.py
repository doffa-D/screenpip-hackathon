"""Deterministic reports from actual executor events; no model-written outcomes."""
from datetime import datetime, timezone
from .models import RunReport, RunFeedback

ACTIVE = {'running', 'awaiting_approval', 'stopping'}


def build_report(run):
    if run.get('origin') == 'demo' or run.get('source_kind') == 'seeded_demo':
        raise ValueError('Simulated history has no real execution report.')
    attempts, completed, checks, errors = [], [], [], []
    events = run.get('events', [])
    for event in events:
        detail = event.get('detail') or {}
        if event['kind'] == 'tool' and detail.get('tool_name') in ('act', 'zavora_act', *(('open_url',) if run.get('scope') else ())):
            attempts.append({'event_id': event['id'], 'timestamp': event['timestamp'],
                'call_id': detail.get('tool_call_id'), 'arguments': {
                    k: v for k, v in detail.items() if k not in ('tool_name', 'tool_call_id')}})
        if event['kind'] in ('result', 'verified') and detail.get('tool') in ('act', 'zavora_act', *(('open_url',) if run.get('scope') else ())):
            completed.append({'event_id': event['id'], 'timestamp': event['timestamp'],
                'call_id': detail.get('tool_call_id'), 'result': detail.get('result')})
        if event['kind'] in ('result', 'verified') and detail.get('tool') in ('verify_text', 'verify_whatsapp_message'):
            checks.append({'event_id': event['id'], 'timestamp': event['timestamp'],
                'arguments': detail.get('arguments'), 'result': detail.get('result')})
        if event['kind'] in ('error', 'failed', 'blocked', 'interrupted', 'denied', 'cancelled'):
            errors.append({'event_id': event['id'], 'timestamp': event['timestamp'],
                'message': event['title'], 'detail': detail})
    limitations = ['Applied actions mean the desktop tool returned successfully; only the listed live checks were verified.',
        'No screenshot evidence is captured. Unattempted workflow steps are not automatically classified as skipped.',
        'Visible text verification does not by itself prove an email was delivered or a file was saved.']
    if run.get('scope'):
        limitations.append('Unattended run: each change was allowed by an approved scope (apps, websites, action budget'
            + (', final steps allowed for this night' if run['scope'].get('may_finalize') else ', no final steps') + '), not by a person watching.')
        limitations.append('The run summary is the agent’s own account; the verification results are the checks that actually ran.')
    if run.get('effective_values') is None:
        limitations.append('Legacy run: a complete input snapshot was not captured.')
    if any(e['kind'] == 'tool' and (e.get('detail') or {}).get('action')
           and not (e.get('detail') or {}).get('tool_name') for e in events):
        limitations.append('Legacy action events lack correlation IDs; attempted-action totals may be incomplete.')
    return RunReport(run_id=run['id'], workflow_name=run['title'],
        workflow_id=run.get('workflow_id'), workflow_revision=run.get('workflow_revision'),
        started_at=run['started_at'], finished_at=run.get('finished_at'), final_status=run['status'],
        summary=run.get('summary', ''), values_used=run.get('effective_values'),
        instructions=run.get('request', {}).get('instructions', ''),
        actions_attempted=attempts, actions_completed=completed, verification_results=checks,
        errors=errors, limitations=limitations, scope=run.get('scope'),
        scope_stop=run.get('scope_stop')).model_dump(mode='json')


def store_feedback(manager, run_id, body: RunFeedback):
    run = manager.runs[run_id]
    if run['status'] in ACTIVE:
        raise ValueError('Wait until this run finishes before reviewing its result.')
    if run.get('origin') == 'demo' or run.get('source_kind') == 'seeded_demo':
        raise ValueError('Simulated history cannot receive real result validation.')
    feedback = {**body.model_dump(), 'reviewed_at': datetime.now(timezone.utc).isoformat()}
    # Publish only after the atomic write succeeds.
    records = {**manager.runs, run_id: {**run, 'feedback': feedback}}
    manager.repository.write('runs', records)
    run['feedback'] = feedback
    return run
