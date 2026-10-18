import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage

import backend.execution as execution
import backend.sheets_executor as sheets
from backend.sheets_delivery import Delivery, MODE
from backend.models import ExecutionRequest
from backend.repository import Repository
from backend.config import Settings
from tests.test_execution import TASK, WORKFLOW, Client, call

def write_pdf(path, text='Test table'):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'):font})})
    content = DecodedStreamObject()
    content.set_data(('BT /F1 12 Tf 50 700 Td (' + text + ') Tj ET').encode('ascii'))
    page[NameObject('/Contents')] = content
    writer.write(path)


RUN_ID = 'cc962ae9-e8fe-4bc5-a493-11466945de84'
VALUES = dict(execution_mode=MODE, whatsapp_recipient='+212 684-899395',
    spreadsheet_url='https://docs.google.com/spreadsheets/d/test/edit?gid=0#gid=0',
    sheet_gid='0', source_range='B3:G9', target_range='B10:G10')


def verify(delivery, text, title='WhatsApp - Google Chrome', label=''):
    delivery.observe('verify_text', dict(expected=text, window_title=title, label=label), {'verified': True})


def test_fresh_pdf_and_ordered_delivery_checks(tmp_path, monkeypatch):
    import backend.sheets_delivery as module
    import datetime as dt
    frozen = dt.datetime.now(dt.timezone.utc)
    monkeypatch.setattr(module, 'datetime', SimpleNamespace(now=lambda tz:frozen.astimezone(tz)))
    delivery = Delivery(VALUES, RUN_ID, tmp_path)
    with pytest.raises(ValueError, match='not been saved'):
        delivery.check_export()
    delivery.path.write_bytes(b'not a pdf' * 5)
    with pytest.raises(ValueError, match='complete PDF'):
        delivery.check_export()
    write_pdf(delivery.path)
    export = delivery.check_export()
    assert export['filename'] == delivery.path.name
    assert len(export['sha256']) == 64
    verify(delivery, 'Sent')
    assert not delivery.sent_checked
    verify(delivery, delivery.path.name)
    verify(delivery, '+212 684-899395', label='Address and search bar')
    assert not delivery.recipient_checked
    verify(delivery, '+212 684-899395', title='Notepad')
    assert not delivery.recipient_checked
    verify(delivery, '+212 684-899395')
    verify(delivery, 'Send')
    assert not delivery.sent_checked
    verify(delivery, 'Sent')
    assert delivery.sent_checked
    delivery.before_change('act', {'window_title': 'WhatsApp', 'label': 'Send'})
    assert not delivery.sent_checked
    verify(delivery, 'Delivered')
    assert delivery.sent_checked
    with pytest.raises(ValueError, match='already has an export'):
        Delivery(VALUES, RUN_ID, tmp_path)


def test_invalid_recipient_and_unverified_send(tmp_path):
    with pytest.raises(ValueError, match='international'):
        Delivery({**VALUES, 'whatsapp_recipient':'684899395'}, RUN_ID, tmp_path)
    delivery = Delivery(VALUES, RUN_ID, tmp_path)
    with pytest.raises(ValueError, match='before Send'):
        delivery.before_change('act', {'window_title':'WhatsApp', 'label':'Send'})
    with pytest.raises(ValueError, match='before Send'):
        delivery.before_change('zavora', {'window_title':'WhatsApp', 'tool':'key', 'arguments':{'text':'Return'}})
    delivery.before_change('zavora', {'window_title':'Save As', 'tool':'key', 'arguments':{'text':'Return'}})


@pytest.mark.parametrize('totals_fail', [True, False])
def test_delivery_handoff_preserves_fast_totals_and_blocks_false_completion(tmp_path, monkeypatch, totals_fail):
    created = []
    class TestDelivery(Delivery):
        def __init__(self, values, run_id):
            super().__init__(values, run_id, tmp_path / 'exports')
    monkeypatch.setattr('backend.sheets_delivery.Delivery', TestDelivery)
    async def fixed(manager, run, request, desktop, opened, state):
        assert request.values['execution_mode'] == sheets.TOTALS_MODE
        state['changed'] = True
        if totals_fail:
            raise ValueError('Totals verification failed')
        state['export_range_verified'] = True
        return 'All formulas and saving verified.'
    monkeypatch.setattr(sheets, 'execute', fixed)
    class RecordingClient(Client):
        async def create(self, **kwargs):
            created.append(kwargs)
            return await super().create(**kwargs)
    client = RecordingClient([ChatCompletionMessage(role='assistant', content='{"outcome":"completed","summary":"Claimed sent"}')])
    monkeypatch.setattr(execution.Agent, 'create_client', lambda self: client)
    async def scenario():
        manager = execution.ExecutionManager(Settings(), Repository(tmp_path / 'state'))
        run = manager.start(TASK, WORKFLOW, ExecutionRequest(values=VALUES))
        await manager.workers[run['id']]
        assert run['status'] == 'blocked'
        if totals_fail:
            assert not created
            assert run['summary'] == 'Totals verification failed'
        else:
            assert len(created) == 1
            assert 'not fully verified' in run['summary']
            assert 'verify_pdf_export' in [t['function']['name'] for t in created[0]['tools']]
            assert 'Do NOT re-enter formulas' in created[0]['messages'][2]['content']
            assert '+212684899395' in created[0]['messages'][2]['content']
        assert run['report']
    asyncio.run(scenario())


def test_export_check_tool_and_live_sent_checks_complete_delivery(tmp_path, monkeypatch):
    instances = []
    class TestDelivery(Delivery):
        def __init__(self, values, run_id):
            super().__init__(values, run_id, tmp_path / 'exports')
            instances.append(self)
    monkeypatch.setattr('backend.sheets_delivery.Delivery', TestDelivery)
    async def fixed(*args):
        write_pdf(instances[0].path)
        args[-1]['export_range_verified'] = True
        return 'Totals verified.'
    monkeypatch.setattr(sheets, 'execute', fixed)
    class DeliveryClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=self)
            self.index = 0
        async def create(self, **kwargs):
            d = instances[0]
            texts = ['+212 684-899395', d.path.name, 'Sent']
            if self.index == 0:
                message = call('verify_pdf_export', {})
            elif self.index <= 3:
                message = call('verify_text', {'window_id':1, 'window_title':'WhatsApp - Google Chrome',
                    'role':'AXStaticText', 'label':texts[self.index-1], 'property':'label', 'expected':texts[self.index-1]})
            else:
                message = ChatCompletionMessage(role='assistant',content='{"outcome":"completed","summary":"PDF sent; Sent status verified."}')
            self.index += 1
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])
        async def close(self): pass
    monkeypatch.setattr(execution.Agent, 'create_client', lambda self: DeliveryClient())
    async def desktop(*args): return {'verified':True}
    monkeypatch.setattr(execution, 'call_desktop', desktop)
    async def scenario():
        manager = execution.ExecutionManager(Settings(), Repository(tmp_path / 'state'))
        run = manager.start(TASK, WORKFLOW, ExecutionRequest(values=VALUES))
        await manager.workers[run['id']]
        assert run['status'] == 'completed'
        assert run['pdf_export']['filename'] == instances[0].path.name
        assert any(e['kind']=='artifact' for e in run['events'])
        assert len(run['report']['verification_results']) == 3
    asyncio.run(scenario())


def test_pdf_must_include_full_table_labels(tmp_path):
    delivery = Delivery({**VALUES, 'pdf_required_labels':'["Category", "Total"]'}, RUN_ID, tmp_path)
    write_pdf(delivery.path, 'Total')
    with pytest.raises(ValueError, match='missing table content: Category'):
        delivery.check_export()
    write_pdf(delivery.path, 'Category Total')
    assert delivery.check_export()['table_labels_verified'] == ['Category', 'Total']


def test_only_focused_same_process_chrome_file_dialog_handoff():
    from backend.sheets_delivery import dialog_handoff
    parent=dict(windowId=1,pid=100,bundleId='chrome.exe',kind='main')
    child=dict(windowId=2,pid=100,bundleId='chrome.exe',kind='dialog',isFocused=True,title='Save Print Output As')
    assert dialog_handoff([parent,child],1,2)
    for change in [dict(pid=101),dict(bundleId='notepad.exe'),dict(kind='main'),dict(isFocused=False),dict(title='Unrelated dialog')]:
        assert not dialog_handoff([parent,{**child,**change}],1,2)


@pytest.mark.parametrize('name', ['../report', 'C:\\report', 'bad:name', 'CON', ''])
def test_pdf_name_cannot_escape_desktop(tmp_path, name):
    with pytest.raises(ValueError, match='PDF name'):
        Delivery({**VALUES, 'pdf_name':name}, RUN_ID, tmp_path)


def test_named_pdf_uses_resolved_desktop_and_exact_file(tmp_path, monkeypatch):
    monkeypatch.setattr('backend.sheets_delivery.desktop_folder', lambda: tmp_path / 'RedirectedDesktop')
    delivery = Delivery({**VALUES, 'pdf_name':'Full table.PDF','pdf_save_location':'Desktop'}, RUN_ID)
    assert delivery.path.parent == tmp_path / 'RedirectedDesktop'
    assert delivery.path.name.startswith('Full table - 20')
    assert delivery.path.name.endswith('.pdf')
    assert RUN_ID not in delivery.path.name
    with pytest.raises(ValueError, match='Desktop only'):
        Delivery({**VALUES, 'pdf_save_location':'Downloads'}, RUN_ID, tmp_path)


def test_pdf_config_changes_are_rejected_but_save_is_allowed(tmp_path):
    delivery = Delivery(VALUES, RUN_ID, tmp_path)
    for label,role in [('Fit to width','AXMenuItem'),('Scale','AXList'),('Landscape','AXRadioButton'),('Destination','AXComboBox'),('Print','AXList')]:
        with pytest.raises(ValueError, match='settings unchanged'):
            delivery.before_change('act', {'window_title':'Sheets', 'label':label,'role':role})
    delivery.before_change('act', {'window_title':'Sheets', 'label':'Print','role':'AXButton'})
    delivery.before_change('act', {'window_title':'Save Print Output As', 'label':'File name:','role':'AXTextField'})
    delivery.before_change('act', {'window_title':'Save Print Output As', 'label':'Save','role':'AXButton'})


def test_chrome_out_of_process_picker_requires_actual_owner():
    from backend.sheets_delivery import dialog_handoff
    parent=dict(windowId=1,pid=100,bundleId='chrome.exe')
    picker=dict(windowId=2,pid=200,bundleId='chrome.exe',kind='main',isFocused=True,title='Open',ownerWindowIds=[1])
    assert dialog_handoff([parent,picker],1,2)
    assert not dialog_handoff([parent,{**picker,'ownerWindowIds':[9]}],1,2)


def test_whatsapp_timestamp_status_and_selected_send_button(tmp_path):
    delivery = Delivery(VALUES, RUN_ID, tmp_path)
    with pytest.raises(ValueError, match='before Send'):
        delivery.before_change('act', {'window_title':'WhatsApp', 'label':'Send 1 selected'})
    write_pdf(delivery.path)
    delivery.check_export()
    verify(delivery, '+212 684-899395 (You) Message yourself')
    verify(delivery, delivery.path.name)
    delivery.before_change('act', {'window_title':'WhatsApp', 'label':'Send 1 selected'})
    verify(delivery, '23:51 Read ')
    assert delivery.sent_checked


def test_report_follows_pdf_and_requires_its_own_message_and_status(tmp_path):
    delivery = Delivery({**VALUES, 'whatsapp_recipient':'+33 6 52 50 88 57',
        'whatsapp_report':'Updated table attached. PDF: {pdf_filename}'}, RUN_ID, tmp_path)
    assert delivery.url.endswith('phone=33652508857')
    write_pdf(delivery.path)
    delivery.check_export()
    verify(delivery, '+33 6 52 50 88 57')
    verify(delivery, delivery.path.name)
    with pytest.raises(ValueError, match='PDF was sent'):
        delivery.before_change('act', {'window_title':'WhatsApp','action':'set_value','value':delivery.report_text})
    verify(delivery, '10:01 Sent ')
    assert delivery.pdf_sent_checked and not delivery.sent_checked
    with pytest.raises(ValueError, match='exact report text'):
        delivery.before_change('act', {'window_title':'WhatsApp','label':'Send'})
    delivery.observe('verify_text', {'window_title':'WhatsApp','role':'AXTextArea',
        'label':'Type a message','expected':delivery.report_text}, {'verified':True})
    assert delivery.report_input_checked and not delivery.report_message_checked
    delivery.before_change('act', {'window_title':'WhatsApp','label':'Send'})
    verify(delivery, '10:01 Sent ')
    assert not delivery.sent_checked
    delivery.observe('verify_text', {'window_title':'WhatsApp','role':'AXStaticText',
        'label':delivery.report_text,'expected':delivery.report_text}, {'verified':True})
    verify(delivery, '10:02 Delivered ')
    assert delivery.report_sent_checked and delivery.sent_checked
    assert delivery.path.name in delivery.report_text


def test_new_recipient_does_not_accept_old_number(tmp_path):
    delivery = Delivery({**VALUES, 'whatsapp_recipient':'+33652508857'}, RUN_ID, tmp_path)
    verify(delivery, '+212 684-899395 (You) Message yourself')
    assert not delivery.recipient_checked
    verify(delivery, '+33 6 52 50 88 57')
    assert delivery.recipient_checked


def test_report_verification_correlates_its_own_status_and_excludes_drafts():
    from backend.desktop_worker import whatsapp_message_status
    def message(text, status):
        return {'role':'AXGroup','children':[{'role':'AXStaticText','label':text}, {'role':'AXButton','label':status}]}
    tree={'role':'AXGroup','children':[message('table.pdf','10:01 Read '),message('Updated table report','10:01 Pending ')]}
    assert not whatsapp_message_status(tree,'Updated table report')['verified']
    tree['children'][1]['children'][1]['label']='10:01 Delivered '
    result=whatsapp_message_status(tree,'Updated table report')
    assert result['verified'] and result['status']=='10:01 Delivered '
    tree['children'][1]['children'][0]['role']='AXTextArea'
    assert not whatsapp_message_status(tree,'Updated table report')['verified']


def test_correlated_message_check_completes_only_after_pdf(tmp_path):
    delivery=Delivery({**VALUES,'whatsapp_report':'Updated table: {pdf_filename}'}, RUN_ID,tmp_path)
    write_pdf(delivery.path);delivery.check_export()
    verify(delivery,'+212 684-899395');verify(delivery,delivery.path.name)
    args={'window_title':'WhatsApp','expected_message':delivery.report_text}
    delivery.observe('verify_whatsapp_message',args,{'verified':True})
    assert not delivery.sent_checked
    delivery.observe('verify_whatsapp_message',{'window_title':'WhatsApp','expected_message':delivery.path.name},{'verified':True})
    assert delivery.pdf_sent_checked and not delivery.sent_checked
    delivery.observe('verify_whatsapp_message',args,{'verified':True})
    assert delivery.report_sent_checked and delivery.sent_checked
