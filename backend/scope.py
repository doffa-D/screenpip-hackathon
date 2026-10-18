"""Deterministic guard for unattended (overnight) runs.

The user approves a scope once; this module then answers, per proposed desktop change, "is this inside it?".
It never asks a model, and it fails closed: a change it cannot classify (no window named, a control with no label,
an unknown tool or shortcut) is refused, so an unattended run stops and reports instead of guessing.
It is a filter on what the agent says it is touching, not a sandbox. Typed text is never inspected.
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

# Controls whose effect cannot be undone from the desktop afterwards (English, French, Spanish, German).
IRREVERSIBLE = re.compile(
    r'\b(send|submit|publish|post|share|delete|remove|erase|discard|trash|pay|purchase|buy|order|checkout|confirm|'
    r'transfer|subscribe|unsubscribe|sign ?out|log ?out|install|uninstall|format|reply all|approve|archive|accept|'
    r'envoyer|envoi|soumettre|publier|partager|supprimer|effacer|jeter|payer|acheter|commander|valider|confirmer|'
    r'transf[eé]rer|d[eé]connecter|installer|archiver|accepter|approuver|'
    r'enviar|eliminar|borrar|descartar|pagar|comprar|publicar|compartir|confirmar|aceptar|'
    r'senden|absenden|abschicken|l[oö]schen|entfernen|verwerfen|bezahlen|kaufen|ver[oö]ffentlichen|teilen|best[aä]tigen|akzeptieren)\b',
    re.I)
SEND_SHORTCUT = re.compile(r'(ctrl|control|cmd|command|alt|meta|win)\s*\+.*\b(enter|return)\b', re.I)
LABEL_KEYS = {'label', 'name', 'title', 'description', 'element_label', 'button', 'target'}
# AX-first tools plus plain input. Coordinate clicks and drags have no label, so they cannot be judged.
NIGHT_TOOLS = {'click_element', 'set_value', 'fill_form', 'press_button', 'type', 'key', 'scroll',
               'activate_window', 'activate_app'}
NEEDS_LABEL = {'click_element', 'press_button', 'set_value', 'fill_form'}
# While preparing (not finishing) only editing keys are allowed: a bare Enter/Space can press a focused Send button.
SAFE_KEYS = re.compile(r'^(tab|shift\+tab|up|down|left|right|home|end|page ?up|page ?down|backspace|delete|'
                       r'(ctrl|control)\+(a|c|v|x|y|z|home|end))$', re.I)
OVERRIDES = re.compile(r'override|bypass|force|ignore|unsafe|skip|disable|presence', re.I)


def labels(value, found=None):
    """Every control label mentioned by an action, wherever the tool nests it."""
    found = [] if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            if key in LABEL_KEYS and isinstance(item, str):
                found.append(item)
            elif isinstance(item, (dict, list)):
                labels(item, found)
    elif isinstance(value, list):
        for item in value:
            labels(item, found)
    return found


def keys(value, found=None):
    found = [] if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            found.append(str(key))
            keys(item, found)
    elif isinstance(value, list):
        for item in value:
            keys(item, found)
    return found


def normal_app(value):
    return re.sub(r'\.exe$', '', str(value).strip().casefold())


def host_allowed(url, hosts):
    if re.search(r'[\\\s\x00-\x1f]', url):
        return False
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or '').casefold()
    if parsed.scheme != 'https' or parsed.username or parsed.password or port not in (None, 443):
        return False
    return any(host == h or host.endswith('.' + h) for h in map(str.casefold, hosts))


def window_allowed(title, apps):
    """An approved app must appear in the window title. No title or no approved apps means no."""
    title = (title or '').casefold()
    return bool(title) and any(app and app in title for app in map(normal_app, apps))


def irreversible_reason(tool, args):
    inner = args.get('arguments') or {}
    if tool == 'key':
        pressed = str(inner.get('text') or inner.get('key') or inner.get('keys') or '').strip()
        if SEND_SHORTCUT.search(pressed):
            return f'the keyboard shortcut “{pressed}” is a send/submit shortcut'
        if not SAFE_KEYS.match(pressed):
            return f'the key “{pressed or "(none)"}” can activate a focused control'
    named = labels(args) + labels(inner)
    for label in named:
        match = IRREVERSIBLE.search(label)
        if match:
            return f'“{label.strip()[:80]}” looks like a final step ({match[0].lower()})'
    match = IRREVERSIBLE.search(str(args.get('reason', '')))
    if match:
        return f'the stated reason mentions “{match[0].lower()}”'
    return None


def authorize(scope, name, args, now=None):
    """None when the change is inside the approved scope, otherwise (kind, human reason).

    Counts allowed changes in scope['used'] so the action budget survives retries inside one run.
    """
    now = now or datetime.now(timezone.utc)
    if now >= datetime.fromisoformat(scope['window_end']):
        return 'window_closed', 'The overnight window has ended, so Melon stopped before touching your screen again.'
    if scope.get('used', 0) >= scope['max_actions']:
        return 'budget', f"The action budget for this task ({scope['max_actions']}) is used up."
    if name == 'launch_app':
        return 'unsupported', 'Starting a program is not allowed without supervision. Open the app before the overnight window.'
    if name == 'open_url':
        if not host_allowed(args['url'], scope.get('allowed_hosts', [])):
            return 'outside_scope', f"{urlparse(args['url']).hostname or 'That address'} is not on the approved list of websites."
    else:
        inner = args.get('arguments') or {}
        tool = args['tool'] if name == 'zavora' else args.get('action')
        if name == 'zavora':
            if tool not in NIGHT_TOOLS:
                return 'unsupported', f'“{tool}” cannot be checked safely without supervision.'
            if any(OVERRIDES.search(k) for k in keys(inner)):
                return 'unsupported', 'The action carries an option that changes the desktop safety checks.'
            if tool in NEEDS_LABEL and not (labels(args) + labels(inner)):
                return 'unsupported', 'The control has no readable label, so Melon cannot tell what it does.'
        title = args.get('window_title') or inner.get('window_title')
        if not window_allowed(title, scope.get('allowed_apps', [])):
            return 'outside_scope', f'The window “{str(title or "(not named)")[:80]}” is not one of the approved apps.'
        target = inner.get('app') or inner.get('app_name')
        if tool in ('activate_app', 'activate_window') and target and not window_allowed(str(target), scope.get('allowed_apps', [])):
            return 'outside_scope', f'“{str(target)[:80]}” is not one of the approved apps.'
    if not scope.get('may_finalize'):
        why = irreversible_reason(args['tool'] if name == 'zavora' else name, args)
        if why:
            return 'irreversible', f'Stopped before a final step: {why}. Everything before it was prepared for your review.'
    scope['used'] = scope.get('used', 0) + 1
    return None
