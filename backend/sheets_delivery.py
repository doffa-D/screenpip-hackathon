"""Explicit manual-only Sheets export/delivery handoff, with fresh-file checks."""
import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from pypdf import PdfReader

MODE = 'sheets_totals_pdf_whatsapp_v1'
EXPORT_TOOL = {'type': 'function', 'function': {
    'name': 'verify_pdf_export',
    'description': 'Check the one server-assigned PDF export path for this run. No path arguments. Call after saving, before attaching.',
    'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}}}


def desktop_folder():
    """Resolve the actual Windows Desktop, including OneDrive redirection."""
    if os.name == 'nt':
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0:
            return Path(buffer.value)
        raise ValueError('Windows Desktop folder could not be resolved.')
    return Path.home() / 'Desktop'


def dialog_handoff(windows, previous, current):
    """Only a freshly observed, focused Chrome file dialog in the changed process."""
    parent = next((w for w in windows if w.get('windowId') == previous), {})
    dialog = next((w for w in windows if w.get('windowId') == current), {})
    related = (previous in dialog.get('ownerWindowIds', []) or
               (parent.get('pid') and parent.get('pid') == dialog.get('pid') and dialog.get('kind') == 'dialog'))
    return bool(related and parent.get('windowId')
        and parent.get('bundleId', '').lower() == dialog.get('bundleId', '').lower() == 'chrome.exe'
        and dialog.get('isFocused')
        and dialog.get('title', '').lower() in ('save print output as', 'save as', 'open'))


class Delivery:
    def __init__(self, values, run_id, root=None):
        phone = re.sub(r'[\s()-]', '', values.get('whatsapp_recipient', ''))
        if not re.fullmatch(r'\+[1-9]\d{7,14}', phone):
            raise ValueError('Supply the WhatsApp recipient as an international number, including +.')
        if not re.fullmatch(r'[a-f0-9-]{36}', run_id):
            raise ValueError('Invalid export run identifier.')
        self.phone = phone
        self.required_labels = json.loads(values.get('pdf_required_labels', '[]'))
        if (not isinstance(self.required_labels, list) or len(self.required_labels) > 30
                or any(not isinstance(label, str) or not label.strip() or len(label) > 150 for label in self.required_labels)):
            raise ValueError('PDF table labels must be a list of up to 30 nonempty strings.')
        self.url = 'https://web.whatsapp.com/send?phone=' + phone[1:]
        self.started = time.time()
        if values.get('pdf_save_location', 'Desktop') != 'Desktop':
            raise ValueError('This workflow saves its named PDF on the Desktop only.')
        name = re.sub(r'\.pdf$', '', values.get('pdf_name', 'CA HT - Full table'), flags=re.I).strip()
        if (not name or len(name) > 80 or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
                or name.endswith(('.', ' ')) or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', name, re.I)):
            raise ValueError('Choose a PDF name without folder paths or Windows filename punctuation.')
        folder = Path(root) if root else desktop_folder()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(ZoneInfo('Europe/Paris')).strftime('%Y-%m-%d_%H-%M-%S')
        self.path = folder / f'{name} - {stamp}.pdf'
        if self.path.exists():
            raise ValueError('This timestamp already has an export. Start a new run a second later; never overwrite or send a stale PDF.')
        self.export = None
        self.range_verified = False
        self.recipient_checked = self.attachment_checked = self.sent_checked = False
        self.pdf_sent_checked = self.report_input_checked = self.report_message_checked = self.report_sent_checked = False
        self.report_text = values.get('whatsapp_report', '').replace('{pdf_filename}', self.path.name).strip()
        if len(self.report_text) > 2000:
            raise ValueError('Keep the WhatsApp report below 2000 characters.')

    def check_export(self):
        # Only this run's generated filename is readable; model cannot select another file.
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError('The PDF has not been saved at the assigned export path.')
        stat = self.path.stat()
        if stat.st_mtime < self.started - 2 or not 20 <= stat.st_size <= 25 * 1024 * 1024:
            raise ValueError('The PDF is stale, empty, or exceeds the 25 MB workflow limit.')
        with self.path.open('rb') as stream:
            data = stream.read(25 * 1024 * 1024 + 1)
        if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-2048:]:
            raise ValueError('The export is not a complete PDF. Wait for saving to finish.')
        try:
            reader = PdfReader(self.path)
            if not 1 <= len(reader.pages) <= 10:
                raise ValueError('Expected a short table PDF of at most 10 pages.')
            text = '\n'.join(page.extract_text() or '' for page in reader.pages)
            normalize = lambda value: ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
            missing = [label for label in self.required_labels if normalize(label) not in normalize(text)]
            image_only = not text.strip() and self.range_verified and all(len(page.images) for page in reader.pages)
            if missing and not image_only:
                raise ValueError('The PDF is missing table content: ' + ', '.join(missing))
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('The PDF could not be parsed. Save a complete PDF before attaching.') from exc
        self.export = {'path': str(self.path), 'filename': self.path.name,
                       'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                       'pages': len(reader.pages), 'table_labels_verified': [] if image_only else self.required_labels,
                       'content_check': ('Image-only PDF: A1:G10 was verified selected in Sheets; PDF cell text was not independently read.'
                                         if image_only else 'Configured table labels checked in PDF text.')}
        return self.export

    def observe(self, name, args, result):
        if name not in ('verify_text', 'verify_whatsapp_message') or not result.get('verified'):
            return
        if 'whatsapp' not in args.get('window_title', '').lower():
            return
        if name == 'verify_whatsapp_message':
            if not (self.export and self.recipient_checked and self.attachment_checked):
                return
            content = ' '.join(args.get('expected_message', '').split())
            if content == self.path.name:
                self.pdf_sent_checked = True
            elif self.pdf_sent_checked and self.report_text and content == ' '.join(self.report_text.split()):
                self.report_message_checked = self.report_sent_checked = True
            self.sent_checked = self.pdf_sent_checked and (not self.report_text or self.report_sent_checked)
            return
        text = args.get('expected', '')
        # Address bar verification is not proof of the actual conversation recipient.
        if args.get('label') == 'Address and search bar':
            return
        if self.phone[1:] in re.sub(r'\D', '', text):
            self.recipient_checked = True
        if self.export and self.path.name in text:
            self.attachment_checked = True
        if self.pdf_sent_checked and self.report_text and ' '.join(self.report_text.split()) in ' '.join(text.split()):
            if args.get('role') in ('AXTextField', 'AXTextArea'):
                self.report_input_checked = True
            else:
                self.report_message_checked = True
        if (self.export and self.recipient_checked and self.attachment_checked
                and re.fullmatch(r'\s*(?:\d{1,2}:\d{2}\s+)?(?:sent|delivered|read)(?:[.\s]*)', text, re.I)):
            if self.pdf_sent_checked and self.report_message_checked:
                self.report_sent_checked = True
            self.pdf_sent_checked = True
            self.sent_checked = not self.report_text or self.report_sent_checked

    def before_change(self, name, args):
        self.sent_checked = False
        native = args.get('arguments', {}) if name == 'zavora' else args
        label = str(native.get('label', ''))
        if not self.export:
            setting = re.search(r'^(scale|fit to |landscape|portrait|margins|paper|destination|current sheet|selected cells|workbook|headers|footers)', label, re.I)
            print_scope = label.lower() == 'print' and native.get('role') in ('AXList', 'AXComboBox')
            if setting or print_scope or (name == 'zavora' and args.get('tool') in ('click', 'double_click', 'scroll')):
                raise ValueError('Keep existing PDF settings unchanged. Only proceed with Next/Save/Print and enter the assigned filename.')
        if 'whatsapp' not in args.get('window_title', '').lower():
            return
        key = str(native.get('text', '')).lower() if args.get('tool') == 'key' else ''
        typed = native.get('text') if args.get('tool') == 'type' else native.get('value')
        if self.report_text and typed == self.report_text and not self.pdf_sent_checked:
            raise ValueError('Verify the PDF was sent before composing the report.')
        sending = bool(re.fullmatch(r'\s*send(?:\s+\d+\s+selected)?\s*', label, re.I)) or key in (
            'enter', 'return', 'ctrl+enter', 'ctrl+return')
        if sending and not (self.export and self.recipient_checked and self.attachment_checked):
            raise ValueError('Verify the fresh PDF, actual recipient number, and attachment filename before Send.')
        if sending and self.report_text and self.pdf_sent_checked and not self.report_input_checked:
            raise ValueError('Verify the exact report text in the message composer before sending it.')

    def instructions(self, totals_summary):
        report = (f'''AFTER the outgoing PDF status is verified, send one separate short report to the SAME verified conversation.
Use exactly this report text (do not add guessed numeric totals):
<report_text>{self.report_text}</report_text>
Focus the observed message composer, type this text, and verify_text its exact value BEFORE Send.
Send ONCE. Then verify the exact report text exists as an outgoing message (not just inside the composer),
and verify the timestamp/status button belonging to THAT report message. The PDF status alone is not completion.
Prefer verify_whatsapp_message(expected_message=the exact report text) to correlate text and status within the same message group, even when timestamps repeat.
If the PDF succeeded but the report failed, say PDF sent, report unverified; never resend the PDF.
''' if self.report_text else '')
        return f'''TOTALS PHASE FINISHED: {totals_summary}
Do NOT re-enter formulas or repeat the totals phase. Your remaining task is PDF export and WhatsApp delivery.
For THIS explicitly authorized workflow only, exporting the updated spreadsheet as a PDF through Chrome's UI is allowed.
No other downloads, shell, scripts, clipboard access, credential entry, or file reading are allowed.
Export the FULL Sheet1 table A1:G10: title, column headers, ALL seven category rows, ALL columns A through G, and completed total row 10.
The controlled phase has ALREADY selected and verified A1:G10. Do NOT reselect it, type cell addresses, or edit any cells.
Open Print and KEEP ALL EXISTING PDF SETTINGS UNCHANGED. Do not touch scale, orientation, margins, paper size, print scope or destination.
Only click the existing Next/Save/Print control to proceed to saving. Before Print, confirm the existing destination is Save as PDF or Microsoft Print to PDF.
If the existing destination is a physical printer, stop blocked; do not print or change it.
Save the PDF at exactly: {self.path}
This assigns the PDF a readable name and saves it on the user's Desktop. Keep that exact name when attaching it later.
The generated filename includes the date and time in Europe/Paris. Windows may show Save Print Output As or Save As. This is the expected save step, NOT a reason to block.
Inspect the live dialog (it can appear inside Chrome's tree), set its observed AXTextField labeled File name: to the FULL assigned path,
verify that field value, then press the observed Save button. If AX set_value fails, click the field then ctrl+a and type the path.
Refresh list_apps after navigation/title changes. Raw key/type need target_window_id. Raw click uses coordinate:[x,y], NOT x/y arguments.
Do not send screenshots or a spreadsheet URL instead of the PDF. Call verify_pdf_export after saving; fix an incomplete save before continuing.
Then use open_url to open a NEW active Chrome tab at {self.url}.
If WhatsApp requires a QR login, sign-in, or reports an invalid/unavailable number, stop blocked and explain. Never choose another contact.
If the matching number is labeled (You) or Message yourself, it IS a valid requested recipient. Continue normally; do not block just because this is the user's own chat.
Confirm the ACTUAL conversation recipient is {self.phone}: inspect header/contact info and verify_text its observed phone number.
The address bar alone is not recipient proof. Do not send until the number matches.
Attach ONLY {self.path} using WhatsApp Attach > Document and the file picker. Never type the path as a chat message.
Verify the exact filename in the WhatsApp attachment preview with verify_text, then send ONCE through its observed Send control.
If sending is uncertain, inspect this outgoing attachment; never click Send again without proving it was not sent.
After send, verify_text the observed Sent, Delivered, or Read status belonging to THIS outgoing PDF message.
Prefer verify_whatsapp_message(expected_message=the exact PDF filename) for a correlated outgoing attachment/status check.
WhatsApp may label the attachment send button "Send 1 selected". Use its exact observed label.
For final verification prefer the unique timestamp/status button in THIS PDF's message group (for example "23:51 Read "), not a repeated global Read label from older messages.
{report}
Only report completed once the PDF, recipient, filename and outgoing sent status are verified. If a status is not accessible, report blocked/unverified rather than guessing.
Keep the report concise: totals verification, PDF path, recipient and observed delivery status; never claim the recipient read it unless observed.
'''
