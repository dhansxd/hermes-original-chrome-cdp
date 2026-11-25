"""Local, declarative controls learned from DOM clicks in owned Chrome pages."""
from collections import deque
from contextlib import closing, contextmanager
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
from urllib.parse import urlsplit


LEARNED_ACTIONS = ('list_learned_controls', 'click_learned_control')
STATES = ('aria-expanded', 'aria-pressed', 'aria-checked', 'aria-selected')

# Limit automatic reuse to an unambiguous button with a visible, repeatable state change.
BUTTONS = r"""
const selector = 'button,[role="button"]';
const label = element => (element.getAttribute('aria-label') || element.textContent || '')
    .trim().replace(/\s+/g, ' ');
const usable = element => {
    if (!element.isConnected || !element.getClientRects().length ||
        element.closest('[inert],[hidden],[aria-hidden="true"]') ||
        element.matches(':disabled,[aria-disabled="true"]')) return false;
    const style = getComputedStyle(element);
    return style.visibility === 'visible' && style.display !== 'none';
};
"""

_OBSERVER = r"""
(() => {
    if (window !== window.top || globalThis.hermesLearningStarted ||
        typeof globalThis[BINDING] !== 'function') return;
    globalThis.hermesLearningStarted = true;
    const states = STATES;
    const locationKey = () => [location.origin, location.pathname];
    const send = result => globalThis[BINDING](JSON.stringify(result));
    send({url:locationKey()});
    window.addEventListener('click', event => {
        // This stage learns DOM click() calls. User clicks and coordinate input are distinct.
        if (event.isTrusted) return;
        const button = event.target instanceof Element && event.target.closest(selector);
        if (!button || !usable(button)) return;
        const text = label(button);
        if (!text || text.length > 100 || button.id.length > 128) return;
        const matches = [...document.querySelectorAll(selector)]
            .filter(item => label(item) === text && usable(item));
        if (matches.length !== 1 || matches[0] !== button) return;
        const url = locationKey();
        const before = states.map(name => button.getAttribute(name));
        queueMicrotask(() => {
            if (!button.isConnected || url[0] !== location.origin || url[1] !== location.pathname) return;
            for (const [index, name] of states.entries()) {
                const after = button.getAttribute(name);
                if (['true', 'false'].includes(before[index]) &&
                    ['true', 'false'].includes(after) && before[index] !== after) {
                    send({url, label:text, element:button.id, state:name, value:after});
                    return;
                }
            }
            send({url, label:text, element:button.id, state:'', value:''});
        });
    }, {capture:true, passive:true});
})()
"""

_CLICK = r"""
((entry, origin, path) => {
    if (location.origin !== origin || location.pathname !== path) return 'wrong_page';
    const candidates = [...document.querySelectorAll(selector)]
        .filter(item => label(item) === entry.label && usable(item));
    if (candidates.length !== 1 || candidates[0].id !== entry.element_id) return 'unmatched';
    const button = candidates[0];
    const rect = button.getBoundingClientRect();
    const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (!button.contains(top)) return 'obscured';
    const before = button.getAttribute(entry.state);
    if (!['true', 'false'].includes(before) || before === entry.value) return 'state_changed';
    button.click();
    return button.isConnected && button.getAttribute(entry.state) === entry.value
        ? 'verified' : 'unconfirmed';
})(ENTRY, ORIGIN, ROUTE)
"""


def page_key(url):
    if not isinstance(url, list) or len(url) != 2 or not all(isinstance(part, str) for part in url):
        raise ValueError('A current HTTP(S) page is required.')
    origin, path = url
    parsed = urlsplit(origin)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
            or parsed.path or parsed.query or parsed.fragment or not path.startswith('/')
            or len(origin) > 512 or len(path) > 4096):
        raise ValueError('A current HTTP(S) page is required.')
    return origin, hashlib.sha256(path.encode()).hexdigest()


class ClickCatalog:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def open(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.path.exists():
            os.close(os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600))
        with closing(sqlite3.connect(self.path, timeout=.25)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('CREATE TABLE IF NOT EXISTS sites (origin TEXT PRIMARY KEY, name TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS controls (
                id TEXT PRIMARY KEY, origin TEXT, page TEXT, label TEXT, element_id TEXT,
                state TEXT, value TEXT, revision TEXT, active INTEGER
            )''')
            yield db

    def record(self, observations):
        if not observations:
            return
        with self.open() as db:
            for origin, page, control in observations:
                db.execute('INSERT OR IGNORE INTO sites VALUES (?, ?)', (origin, urlsplit(origin).hostname))
                if control is None:
                    continue
                label, element, state, value = control
                key = hashlib.sha256(json.dumps([origin, page, label]).encode()).hexdigest()[:24]
                db.execute('''INSERT INTO controls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET element_id=excluded.element_id,
                    state=excluded.state, value=excluded.value, revision=excluded.revision, active=1
                    WHERE excluded.active=1''',
                           (key, origin, page, label, element, state, value, secrets.token_hex(8), bool(state)))

    def list(self, origin, page, label=None):
        with self.open() as db:
            return [dict(row) for row in db.execute(
                '''SELECT id, label FROM controls WHERE origin=? AND page=? AND active=1
                AND (? IS NULL OR label=?) ORDER BY label LIMIT 25''', (origin, page, label, label))]

    def get(self, control_id, origin, page):
        with self.open() as db:
            row = db.execute('SELECT * FROM controls WHERE id=? AND origin=? AND page=? AND active=1',
                             (control_id, origin, page)).fetchone()
            return dict(row) if row is not None else None

    def stale(self, entry):
        with self.open() as db:
            db.execute('UPDATE controls SET active=0 WHERE id=? AND revision=?',
                       (entry['id'], entry['revision']))


class PageLearning:
    """Observe only script-driven clicks while a native evaluation owns this attachment."""
    def __init__(self, catalog):
        self.catalog = catalog
        self.binding = 'hermesObserve_' + secrets.token_hex(8)
        self.world = self.binding
        self.lock = threading.Lock()
        self.attached = {}
        self.evaluating = set()
        self.observations = deque(maxlen=128)

    def attach(self, wire, sid):
        with self.lock:
            self.attached[sid] = None
        try:
            wire.call('Runtime.addBinding', {'name': self.binding, 'executionContextName': self.world}, sid, timeout=.5)
            source = _OBSERVER.replace('BINDING', json.dumps(self.binding)).replace('STATES', json.dumps(STATES))
            result = wire.call('Page.addScriptToEvaluateOnNewDocument',
                               {'source': '(() => {' + BUTTONS + source + '})()',
                                'worldName': self.world, 'runImmediately': True},
                               sid, timeout=.5)
            if not isinstance(result, dict) or not isinstance(result.get('identifier'), str):
                raise RuntimeError('The observation script was not registered.')
            with self.lock:
                self.attached[sid] = result['identifier']
        except (ConnectionError, OSError, RuntimeError, TimeoutError, KeyError):
            self.detach(wire, sid)

    def detach(self, wire, sid):
        with self.lock:
            if sid not in self.attached:
                return
            script = self.attached.pop(sid)
            self.evaluating.discard(sid)
        try:
            if script is not None:
                wire.call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': script}, sid, timeout=.5)
            wire.call('Runtime.removeBinding', {'name': self.binding}, sid, timeout=.5)
        except (ConnectionError, OSError, RuntimeError, TimeoutError):
            pass  # The target may already be closed.

    def evaluate(self, wire, method, params, sid):
        with self.lock:
            if sid in self.attached:
                self.evaluating.add(sid)
        try:
            return wire.call(method, params, sid, timeout=None)
        finally:
            with self.lock:
                self.evaluating.discard(sid)

    def event(self, sid, params):
        if params.get('name') != self.binding:
            return False
        with self.lock:
            if sid not in self.attached:
                return True
            payload = params.get('payload')
            if not isinstance(payload, str) or len(payload) > 5800:
                return True
            try:
                data = json.loads(payload)
                if not isinstance(data, dict):
                    return True
                origin, page = page_key(data.get('url'))
            except (ValueError, UnicodeError):
                return True
            if set(data) == {'url'}:
                self.observations.append((origin, page, None))
            elif sid in self.evaluating and set(data) == {'url', 'label', 'element', 'state', 'value'}:
                label, element = data['label'], data['element']
                state, value = data['state'], data['value']
                if (isinstance(label, str) and 0 < len(label) <= 100 and label.isprintable()
                        and isinstance(element, str) and len(element) <= 128 and (not element or element.isprintable())
                        and ((state in STATES and value in ('true', 'false')) or (state == value == ''))):
                    self.observations.append((origin, page, (label, element, state, value)))
        return True

    def flush(self):
        with self.lock:
            pending = list(self.observations)
            self.observations.clear()
        try:
            self.catalog.record(pending)
        except (OSError, sqlite3.Error, UnicodeError):
            pass  # Catalog I/O cannot interrupt native browsing.


def cached_action(catalog, command, run_expression):
    """Use the current native tab and dispatch at most one explicit DOM click."""
    params = command.get('params', {})
    action = command['action']
    if (not isinstance(params, dict)
            or (action == 'list_learned_controls' and
                (set(params) - {'label'} or ('label' in params and
                 (not isinstance(params['label'], str) or not 0 < len(params['label']) <= 100))))
            or (action == 'click_learned_control' and
                (set(params) != {'control'} or not isinstance(params['control'], str)
                 or not re.fullmatch(r'[0-9a-f]{24}', params['control'])))):
        raise ValueError('Pass an optional exact label to list_learned_controls or a listed control ID to click_learned_control.')
    url = run_expression('[location.origin, location.pathname]')
    origin, page = page_key(url)
    if action == 'list_learned_controls':
        return {'success': True, 'status': 'ok', 'site': origin, 'site_name': urlsplit(origin).hostname,
                'controls': catalog.list(origin, page, params.get('label'))}
    entry = catalog.get(params['control'], origin, page)
    if entry is None:
        return fallback('unmatched', dispatched=False)
    data = {key: entry[key] for key in ('label', 'element_id', 'state', 'value')}
    expression = _CLICK.replace('(ENTRY, ORIGIN, ROUTE)', '(' + ', '.join(
        json.dumps(item, ensure_ascii=True) for item in (data, origin, url[1])) + ')')
    status = run_expression('(() => {' + BUTTONS + ' return ' + expression.strip() + '})()', click=True)
    if status == 'verified':
        return {'success': True, 'status': 'ok', 'control': entry['id'], 'dispatched': True}
    no_click = status in ('unmatched', 'wrong_page', 'obscured', 'state_changed')
    if status == 'unmatched' or not no_click:
        catalog.stale(entry)
    return fallback(status if isinstance(status, str) else 'unconfirmed', dispatched=not no_click)


def fallback(reason, *, dispatched):
    return {'success': False, 'status': 'needs_inspection', 'reason': reason,
            'dispatched': dispatched, 'next': ('Check the current page before repeating the click.'
                                              if dispatched else 'Use native DOM, then screenshot if needed.')}
