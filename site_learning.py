"""Local, declarative controls learned from clicks in owned Chrome pages."""
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
    const documentId = crypto.getRandomValues(new Uint32Array(2)).join('-');
    let sequence = 0;
    let pending = null;
    globalThis[BINDING + 'Effect'] = id => {
        if (pending?.id !== id) return null;
        const {inspect} = pending;
        pending = null;
        return inspect();
    };
    const locationKey = () => [location.origin, location.pathname];
    const send = result => globalThis[BINDING](JSON.stringify(result));
    send({url:locationKey()});
    window.addEventListener('click', event => {
        // A pointer click is learned only when the relay matches it to native CDP input.
        if (event.isTrusted && (event.button !== 0 || event.detail !== 1)) return;
        const pointer = {};
        if (event.isTrusted) {
            pointer.points = [[event.clientX, event.clientY]];
            const viewport = window.visualViewport;
            if (viewport && (viewport.offsetLeft || viewport.offsetTop)) {
                pointer.points.push([event.clientX - viewport.offsetLeft,
                                     event.clientY - viewport.offsetTop]);
            }
        }
        const button = event.target instanceof Element && event.target.closest(selector);
        if (!button || !usable(button)) return;
        const text = label(button);
        if (!text || text.length > 100 || button.id.length > 128) return;
        const matches = [...document.querySelectorAll(selector)]
            .filter(item => label(item) === text && usable(item));
        if (matches.length !== 1 || matches[0] !== button) return;
        const url = locationKey();
        const element = button.id;
        const before = states.map(name => button.getAttribute(name));
        const observation = event.isTrusted ? documentId + '-' + (++sequence) : null;
        const inspect = () => {
            if (!button.isConnected || url[0] !== location.origin || url[1] !== location.pathname) return null;
            for (const [index, name] of states.entries()) {
                const after = button.getAttribute(name);
                if (['true', 'false'].includes(before[index]) &&
                    ['true', 'false'].includes(after) && before[index] !== after) {
                    return {state:name, value:after};
                }
            }
            return null;
        };
        if (observation) {
            // Match the target during the click. The relay checks its effect after the release.
            pending = {id:observation, inspect};
            send({url, label:text, element, state:'', value:'', observation, ...pointer});
        } else {
            queueMicrotask(() => {
                const proof = inspect() || {state:'', value:''};
                if (button.isConnected && url[0] === location.origin && url[1] === location.pathname) {
                    send({url, label:text, element, ...proof});
                }
            });
        }
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


def valid_point(point):
    return (isinstance(point, (list, tuple)) and len(point) == 2
            and all(type(value) in (int, float) and -1_000_000 < value < 1_000_000 for value in point))


class PageLearning:
    """Correlate page events with native commands on the exact owned attachment."""
    def __init__(self, catalog):
        self.catalog = catalog
        self.binding = 'hermesObserve_' + secrets.token_hex(8)
        self.world = self.binding
        self.lock = threading.Lock()
        self.confirmation_ready = threading.Condition(self.lock)
        self.attached = {}
        self.evaluating = set()
        self.pressed = {}
        self.releasing = {}
        self.awaiting_confirmation = {}
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
            self.pressed.pop(sid, None)
            self.releasing.pop(sid, None)
            self.awaiting_confirmation.pop(sid, None)
            self.confirmation_ready.notify_all()
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

    def pointer(self, wire, method, params, sid):
        phase = params.get('type')
        point = (params.get('x'), params.get('y'))
        single = params.get('button') == 'left' and params.get('clickCount') == 1 and valid_point(point)
        with self.lock:
            pressed = self.pressed.pop(sid, None)
            tracking = single and sid in self.attached
            matched_release = tracking and phase == 'mouseReleased' and pressed == point
            if matched_release:
                self.releasing[sid] = point
        try:
            result = wire.call(method, params, sid, timeout=None)
            if tracking and phase == 'mousePressed':
                with self.lock:
                    if sid in self.attached:
                        self.pressed[sid] = point
            elif matched_release:
                self._confirm(wire, sid)
            return result
        finally:
            with self.lock:
                self.releasing.pop(sid, None)
                self.awaiting_confirmation.pop(sid, None)

    def _matches_click(self, sid, data):
        fields = {'url', 'label', 'element', 'state', 'value'}
        if set(data) == fields:
            return sid in self.evaluating
        if (set(data) != fields | {'points', 'observation'} or data['state'] != '' or data['value'] != ''
                or not isinstance(data['observation'], str)
                or not re.fullmatch(r'[0-9-]{1,40}', data['observation'])):
            return False
        point = self.releasing.get(sid)
        reported = data['points']
        if (point is None or not isinstance(reported, list) or not 1 <= len(reported) <= 2
                or not any(valid_point(item) and all(abs(a - b) <= 1 for a, b in zip(point, item))
                           for item in reported)):
            return False
        self.releasing.pop(sid, None)
        return True

    def _confirm(self, wire, sid):
        with self.confirmation_ready:
            # Chrome can acknowledge the release before delivering its binding event.
            self.confirmation_ready.wait_for(
                lambda: sid in self.awaiting_confirmation or sid not in self.attached, timeout=.15,
            )
            observed = self.awaiting_confirmation.pop(sid, None)
        if observed is None:
            return
        origin, page, label, element, observation, context = observed
        expression = 'globalThis[' + json.dumps(self.binding + 'Effect') + '](' + json.dumps(observation) + ')'
        try:
            result = wire.call('Runtime.evaluate', {'expression': expression, 'contextId': context,
                                                     'returnByValue': True}, sid, timeout=.4)
            value = result.get('result') if isinstance(result, dict) else None
            proof = value.get('value') if isinstance(value, dict) else None
        except (ConnectionError, OSError, RuntimeError, TimeoutError):
            return  # The original click has already been sent. Let native browsing continue.
        if (isinstance(proof, dict) and proof.get('state') in STATES
                and proof.get('value') in ('true', 'false')):
            with self.lock:
                self.observations.append((origin, page, (label, element, proof['state'], proof['value'])))

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
            elif self._matches_click(sid, data):
                label, element = data['label'], data['element']
                state, value = data['state'], data['value']
                if (isinstance(label, str) and 0 < len(label) <= 100 and label.isprintable()
                        and isinstance(element, str) and len(element) <= 128 and (not element or element.isprintable())
                        and ((state in STATES and value in ('true', 'false')) or (state == value == ''))):
                    self.observations.append((origin, page, (label, element, state, value)))
                    context = params.get('executionContextId')
                    if 'observation' in data and type(context) is int and context > 0:
                        self.awaiting_confirmation[sid] = (origin, page, label, element, data['observation'], context)
                        self.confirmation_ready.notify_all()
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
