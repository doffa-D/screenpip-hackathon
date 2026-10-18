import asyncio
from backend.models import Reconstruction, HistoricalValue
from backend.recordings import RecordingService
from backend.refine import Resolution, refine
from backend.repository import Repository

EVIDENCE = [{'call_id': 'e1', 'quote': 'Opened s.txt in Notepad and typed hello', 'source_kind': 'original_activity'}]
QUESTIONS = ['The exact method used to open s.txt.', 'Which Melon control was clicked at the end.', 'Recipient address']


def reconstruction(**changes):
    base = dict(goal='Edit s.txt', historical_values={}, steps=[{'description': 'Open s.txt', 'evidence': EVIDENCE}],
                missing_values=list(QUESTIONS), evidence=EVIDENCE)
    return Reconstruction.model_validate({**base, **changes})


def found(value, quote=None):
    return HistoricalValue.model_validate({'value': value, 'evidence': [{**EVIDENCE[0], 'quote': quote or EVIDENCE[0]['quote']}]})


def refined(resolution, output=None):
    async def investigate(request, output_type, ledger=None):
        assert request['evidence_only'] and request['questions'] == QUESTIONS
        return resolution, ledger
    return asyncio.run(refine(investigate, output or reconstruction(), {'e1': {'text': EVIDENCE[0]['quote']}}))


def test_only_questions_the_recording_cannot_answer_are_left():
    output, summary = refined(Resolution(resolved={QUESTIONS[0]: found('Notepad', 'in Notepad')}, not_inputs=[QUESTIONS[1]], still_missing=[QUESTIONS[2]]))
    assert output.missing_values == [QUESTIONS[2]]
    assert output.historical_values[QUESTIONS[0]].value == 'Notepad'
    assert summary == {'filled': [QUESTIONS[0]], 'not_needed': [QUESTIONS[1]], 'still_missing': [QUESTIONS[2]]}


def test_a_value_the_evidence_does_not_contain_is_never_accepted():
    output, summary = refined(Resolution(resolved={QUESTIONS[2]: found('boss@example.com')}, not_inputs=[], still_missing=[QUESTIONS[0], QUESTIONS[1]]))
    assert output.missing_values == QUESTIONS and not output.historical_values and summary['filled'] == []


def test_questions_the_model_forgot_to_sort_stay_questions():
    output, _ = refined(Resolution(resolved={}, not_inputs=[QUESTIONS[0]], still_missing=[]))
    assert output.missing_values == QUESTIONS[1:]


def test_invented_names_and_existing_values_are_ignored():
    output, summary = refined(Resolution(resolved={'Something new': found('typed hello', 'typed hello'), QUESTIONS[0]: found('typed hello', 'typed hello')},
                                         not_inputs=['Not asked'], still_missing=[]),
                              reconstruction(historical_values={QUESTIONS[0]: found('kept')}))
    assert output.historical_values[QUESTIONS[0]].value == 'kept'
    assert 'Something new' not in output.historical_values and 'Not asked' not in summary['not_needed']


def test_nothing_is_asked_of_the_model_when_there_are_no_questions():
    async def investigate(*args):
        raise AssertionError('should not be called')
    output, summary = asyncio.run(refine(investigate, reconstruction(missing_values=[]), {}))
    assert output.missing_values == [] and summary is None


def test_a_failing_second_pass_keeps_the_reconstruction_and_its_questions():
    async def investigate(*args):
        raise RuntimeError('provider down')
    output, summary = asyncio.run(refine(investigate, reconstruction(), {}))
    assert output.missing_values == QUESTIONS and summary is None


def test_recording_publishes_the_refined_workflow(tmp_path):
    published = []

    async def investigate(request, output_type, ledger=None):
        if output_type is Resolution:
            return Resolution(resolved={QUESTIONS[0]: found('Notepad', 'in Notepad')}, not_inputs=[QUESTIONS[1]], still_missing=[QUESTIONS[2]]), ledger
        return reconstruction(), {'e1': {'text': EVIDENCE[0]['quote']}}

    async def exercise():
        service = RecordingService(Repository(tmp_path), investigate, lambda task, output, ledger: published.append(output))
        record = service.start('Edit s.txt')
        record['ended_at'] = record['started_at']
        job = {'id': 'j', 'status': 'queued', 'started_at': '', 'finished_at': None, 'error': None}
        service.jobs['j'] = job
        await service.run(record, job)
        assert record['status'] == 'ready'
        assert record['workflow']['missing_values'] == [QUESTIONS[2]]
        assert record['auto_filled']['filled'] == [QUESTIONS[0]]
        assert published[0].missing_values == [QUESTIONS[2]]
    asyncio.run(exercise())


def test_the_recording_prompt_asks_for_every_step_and_app(tmp_path):
    seen = []

    async def investigate(request, output_type, ledger=None):
        seen.append(request['instruction'])
        return reconstruction(missing_values=[]), {'e1': {'text': EVIDENCE[0]['quote']}}

    async def exercise():
        service = RecordingService(Repository(tmp_path), investigate, lambda *args: None)
        record = service.start('Edit s.txt')
        record['ended_at'] = record['started_at']
        job = {'id': 'j', 'status': 'queued', 'started_at': '', 'finished_at': None, 'error': None}
        service.jobs['j'] = job
        await service.run(record, job)
    asyncio.run(exercise())
    assert 'COMPLETE ordered list' in seen[0] and 'app_switch' in seen[0] and 'WhatsApp' in seen[0]
    assert 'Name box' in seen[0] and 'formula bar' in seen[0] and 'never as "review"' in seen[0] and 'URL' in seen[0]


def test_yes_no_questions_about_the_past_are_never_left_as_inputs():
    asked = ['Whether the new desktop text file was opened or edited', 'Was the file saved?', 'Recipient address']
    output = reconstruction(missing_values=asked)

    async def investigate(request, output_type, ledger=None):
        return Resolution(resolved={}, not_inputs=[], still_missing=asked), ledger
    refined_output, summary = asyncio.run(refine(investigate, output, {}))
    assert refined_output.missing_values == ['Recipient address']
    assert summary['not_needed'] == asked[:2]


def test_hedged_placeholder_questions_are_dropped():
    asked = ['Typed text, if any', 'Recipient address']

    async def investigate(request, output_type, ledger=None):
        return Resolution(resolved={}, not_inputs=[], still_missing=asked), ledger
    refined_output, summary = asyncio.run(refine(investigate, reconstruction(missing_values=asked), {}))
    assert refined_output.missing_values == ['Recipient address']
