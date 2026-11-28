"""Local controls learned from confirmed clicks in owned Chrome pages."""
from collections import deque
from contextlib import closing, contextmanager
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit


LEARNED_ACTIONS = ('list_learned_controls', 'click')
STATES = ('aria-expanded', 'aria-pressed', 'aria-checked', 'aria-selected')

# Reuse an unambiguous control with a repeatable, verifiable outcome.
BUTTONS = r"""
const selector = 'button,[role="button"]';
const linkSelector = 'a[href]';
const label = element => (element.getAttribute('aria-label') || element.textContent || '')
    .trim().replace(/\s+/g, ' ');
const visible = element => {
    if (!element.isConnected || !element.getClientRects().length ||
        element.closest('[inert],[hidden],[aria-hidden="true"]')) return false;
    const style = getComputedStyle(element);
    return style.visibility === 'visible' && style.display !== 'none';
};
const usable = element => visible(element) && !element.matches(':disabled,[aria-disabled="true"]');
const linkPath = element => {
    if (!element.matches(linkSelector) || element.hasAttribute('download')) return null;
    const target = element.target || document.querySelector('base[target]')?.target || '_self';
    if (target.toLowerCase() !== '_self') return null;
    try {
        const url = new URL(element.href);
        return url.origin === location.origin && url.pathname !== location.pathname &&
            !url.search && !url.hash && url.pathname.length <= 2048 ? url.pathname : null;
    } catch {
        return null;
    }
};
const panelId = element => {
    const id = element.getAttribute('aria-controls') || element.getAttribute('popovertarget') || '';
    return id.length <= 128 && id && !/\s/.test(id) ? id : null;
};
const panelVisible = id => {
    const panels = document.querySelectorAll('#' + CSS.escape(id));
    return panels.length === 1 && usable(panels[0]);
};
const matchingControl = (kind, text) => [...document.querySelectorAll(kind)]
    .filter(item => label(item) === text && usable(item));
const knownLink = entry => {
    const candidates = matchingControl(linkSelector, entry.label);
    return candidates.length === 1 && candidates[0].id === entry.element_id ? candidates[0] : null;
};
const unobscured = element => {
    const rect = element.getBoundingClientRect();
    const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return element.contains(top);
};
const visibleMatching = selector => [...document.querySelectorAll(selector)].some(visible);
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
    const reportLocation = () => send({url:locationKey()});
    reportLocation();
    window.navigation?.addEventListener('currententrychange', reportLocation);
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
        const button = event.target instanceof Element && event.target.closest(selector + ',' + linkSelector);
        if (!button || !usable(button)) return;
        const text = label(button);
        if (!text || text.length > 100 || button.id.length > 128) return;
        const destination = linkPath(button);
        const kind = destination ? linkSelector : selector;
        if (!button.matches(kind)) return;
        const matches = matchingControl(kind, text);
        if (matches.length !== 1 || matches[0] !== button) return;
        const url = locationKey();
        const element = button.id;
        const observation = event.isTrusted ? documentId + '-' + (++sequence) : null;
        if (destination) {
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            const receipt = observation ? {observation, ...pointer} : {};
            send({url, label:text, element, state:'navigation', value:destination, ...receipt});
            return;
        }
        const before = states.map(name => button.getAttribute(name));
        const panel = panelId(button);
        const panelWasHidden = panel && !panelVisible(panel);
        const inspect = () => {
            if (!button.isConnected || url[0] !== location.origin || url[1] !== location.pathname) return null;
            for (const [index, name] of states.entries()) {
                const after = button.getAttribute(name);
                if (['true', 'false'].includes(before[index]) &&
                    ['true', 'false'].includes(after) && before[index] !== after) {
                    return {state:name, value:after};
                }
            }
            if (panelWasHidden && panelId(button) === panel && panelVisible(panel)) {
                return {state:'panel-visible', value:panel};
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

_FIND_LINK = r"""
((entry, origin, path) => {
    if (location.origin !== origin || location.pathname !== path) return null;
    const element = knownLink(entry);
    return element && linkPath(element);
})(ENTRY, ORIGIN, ROUTE)
"""

_DESCRIBE_LINKS = r"""
((entries, origin, path) => {
    if (location.origin !== origin || location.pathname !== path) return {};
    const clean = text => text.trim().replace(/\s+/g, ' ');
    return Object.fromEntries(entries.flatMap(entry => {
        const element = knownLink(entry);
        const destination = element && linkPath(element);
        if (!destination) return [];
        const references = (element.getAttribute('aria-labelledby') || '').trim().split(/\s+/);
        const referenced = clean(references.map(id => document.getElementById(id)?.textContent || '').join(' '));
        const own = clean(element.getAttribute('aria-label') || '');
        const lines = (element.innerText || '').split('\n').map(clean).filter(Boolean);
        const visible = [...new Set(lines)].join(' ');
        const iconNames = [...new Set([...element.querySelectorAll('svg title')]
            .filter(title => !title.closest('[aria-hidden="true"]'))
            .map(title => clean(title.textContent)).filter(Boolean))];
        const iconLabel = iconNames.length === 1 ? iconNames[0] : '';
        return [[entry.id, {label: (referenced || own || visible || iconLabel || entry.label).slice(0, 100), destination}]];
    }));
})(ENTRY, ORIGIN, ROUTE)
"""

_CLICK = r"""
((entry, origin, path) => {
    if (location.origin !== origin || location.pathname !== path) return 'wrong_page';
    const candidates = entry.selector ? [...document.querySelectorAll(entry.selector)].filter(usable)
        : matchingControl(entry.state === 'navigation' ? linkSelector : selector, entry.label);
    if (candidates.length !== 1 || candidates[0].id !== entry.element_id) return 'unmatched';
    const button = candidates[0];
    if (label(button) !== entry.label) return 'unmatched';
    if (!unobscured(button)) return 'obscured';
    if (entry.state === 'navigation') {
        if (linkPath(button) !== entry.value) return 'unmatched';
        button.click();
        return 'navigation_dispatched';
    }
    if (entry.state === 'panel-visible') {
        if (panelId(button) !== entry.value) return 'unmatched';
        if (panelVisible(entry.value)) return 'state_changed';
        button.click();
        return button.isConnected && panelVisible(entry.value) ? 'verified' : 'unconfirmed';
    }
    if (entry.state === 'selector-visible') {
        if (visibleMatching(entry.value)) return 'state_changed';
        button.click();
        return visibleMatching(entry.value) ? 'verified' : 'panel_open_dispatched';
    }
    if (entry.state === 'unverified') {
        button.click();
        return 'unconfirmed';
    }
    const before = button.getAttribute(entry.state);
    if (!['true', 'false'].includes(before) || before === entry.value) return 'state_changed';
    button.click();
    return button.isConnected && button.getAttribute(entry.state) === entry.value
        ? 'verified' : 'unconfirmed';
})(ENTRY, ORIGIN, ROUTE)
"""

_CHECK_OPEN_EFFECT = r"""
((target, origin, path) => location.origin === origin && location.pathname === path &&
    visibleMatching(target))(ENTRY, ORIGIN, ROUTE)
"""

_CLICK_TITLED_LINK = r"""
((request, origin, path) => {
    if (location.origin !== origin || location.pathname !== path) return {reason:'wrong_page'};
    const cards = [...document.querySelectorAll(request.card)].filter(card => {
        const title = card.querySelector(request.title);
        return title && visible(title) && title.textContent.trim().replace(/\s+/g, ' ') === request.target;
    });
    if (cards.length !== 1) return {reason:cards.length ? 'ambiguous' : 'unmatched'};
    const links = [...cards[0].querySelectorAll(request.selector)].filter(usable);
    if (links.length !== 1) return {reason:links.length ? 'ambiguous' : 'unmatched'};
    const link = links[0];
    const destination = linkPath(link);
    if (!destination?.startsWith(request.destination_prefix)) return {reason:'unmatched'};
    link.scrollIntoView({block:'nearest', inline:'nearest', behavior:'instant'});
    if (!unobscured(link)) return {reason:'obscured'};
    if (request.probe) return true;
    link.click();
    return {destination};
})(ENTRY, ORIGIN, ROUTE)
"""


_FIND_DOM_CONTROL = r"""
((request, origin, path) => {
    if (location.origin !== origin || location.pathname !== path) return {reason:'wrong_page'};
    const candidates = request.selector ? [...document.querySelectorAll(request.selector)].filter(usable)
        : matchingControl(selector + ',' + linkSelector, request.target);
    if (candidates.length !== 1) return {reason:'unmatched'};
    const button = candidates[0];
    if (!unobscured(button)) return {reason:'obscured'};
    const info = {label:label(button), element_id:button.id};
    const destination = linkPath(button);
    if (destination) return {...info, state:'navigation', value:destination};
    if (!button.matches(selector)) return {reason:'unmatched'};
    if (request.opens) {
        if (visibleMatching(request.opens)) return {reason:'state_changed'};
        return {...info, state:'selector-visible', value:request.opens};
    }
    for (const state of CLICK_STATES) {
        const before = button.getAttribute(state);
        if (before === 'true' || before === 'false') {
            return {...info, state, value:before === 'true' ? 'false' : 'true'};
        }
    }
    const panel = panelId(button);
    if (panel && !panelVisible(panel)) return {...info, state:'panel-visible', value:panel};
    return {...info, state:'unverified', value:''};
})(ENTRY, ORIGIN, ROUTE)
""".replace("CLICK_STATES", json.dumps(STATES))


VISUAL_FRAME = r"""
from hashlib import sha256
import json
from pathlib import Path
from PIL import Image


def visual_state():
    return [
        current_tab()['targetId'],
        js('[location.href, performance.timeOrigin, devicePixelRatio]'),
        cdp('Page.getLayoutMetrics')['cssVisualViewport'],
    ]


def visual_frame(path):
    before = visual_state()
    capture_screenshot(str(path), max_dim=1200)
    if before != visual_state():
        return None
    with Image.open(path) as image:
        image = image.convert('RGB')
        digest = sha256(json.dumps([before, image.size], sort_keys=True).encode())
        digest.update(image.tobytes())
    viewport = before[2]
    return {'fingerprint': digest.hexdigest(),
            'viewport': [viewport['clientWidth'], viewport['clientHeight']]}
"""


def visual_capture_code(identifier):
    return VISUAL_FRAME + (
        'import os\n'
        f"path = Path(os.environ['BH_AGENT_WORKSPACE']) / {'visual-click-' + identifier + '.png'!r}\n"
        'frame = visual_frame(path)\n'
        'print("VISUAL_CLICK=" + json.dumps({"frame": frame, "path": str(path)}))\n'
        'if frame is not None:\n'
        '    print(path)\n'
    )


def visual_check_code(frame):
    return VISUAL_FRAME + (
        'from tempfile import TemporaryDirectory\n'
        'def visual_matches():\n'
        '    with TemporaryDirectory() as scratch:\n'
        f'        return visual_frame(Path(scratch) / "check.png") == {frame!r}\n'
    )


def visual_dispatch_code(frame, point):
    x, y = (ratio * span for ratio, span in zip(point, frame['viewport']))
    return visual_check_code(frame) + (
        'if not visual_matches():\n'
        '    print("VISUAL_CLICK=stale_screenshot")\n'
        'else:\n'
        f'    click_at_xy({x!r}, {y!r})\n'
        '    print("VISUAL_CLICK=dispatched")\n'
    )


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
                '''SELECT id, label, element_id, state, value FROM controls WHERE origin=? AND page=? AND active=1
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


def valid_proof(state, value):
    if state == 'panel-visible':
        return isinstance(value, str) and 0 < len(value) <= 128 and value.isprintable() and not any(
            letter.isspace() for letter in value)
    return state in STATES and value in ('true', 'false')


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
        self.pending_routes = {}
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
            self.pending_routes.pop(sid, None)
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

    def discard_navigation(self, sid):
        with self.lock:
            self.pending_routes.pop(sid, None)

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
        if (set(data) != fields | {'points', 'observation'}
                or not (data['state'] == 'navigation' or data['state'] == data['value'] == '')
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
                lambda: sid not in self.releasing, timeout=.15,
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
        if isinstance(proof, dict) and valid_proof(proof.get('state'), proof.get('value')):
            with self.lock:
                self.observations.append((origin, page, (label, element, proof['state'], proof['value'])))

    def _record_location(self, sid, origin, page):
        self.observations.append((origin, page, None))
        route = self.pending_routes.get(sid)
        if route is None:
            return
        source, before, label, element, destination, deadline = route
        expired = time.monotonic() > deadline
        if expired or (origin, page) != (source, before):
            self.pending_routes.pop(sid, None)
            if not expired and (origin, page) == (source, destination):
                self.observations.append((origin, before, (label, element, 'navigation', destination)))

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
                self._record_location(sid, origin, page)
            elif self._matches_click(sid, data):
                self.pending_routes.pop(sid, None)
                self.confirmation_ready.notify_all()
                label, element = data['label'], data['element']
                state, value = data['state'], data['value']
                if not (isinstance(label, str) and 0 < len(label) <= 100 and label.isprintable()
                        and isinstance(element, str) and len(element) <= 128 and (not element or element.isprintable())):
                    return True
                if state == 'navigation':
                    if isinstance(value, str) and 0 < len(value) <= 2048 and value.startswith('/'):
                        _, destination = page_key([origin, value])
                        if page != destination:
                            self.pending_routes[sid] = (origin, page, label, element, destination, time.monotonic() + 2)
                elif valid_proof(state, value) or state == value == '':
                    self.observations.append((origin, page, (label, element, state, value)))
                    context = params.get('executionContextId')
                    if 'observation' in data and type(context) is int and context > 0:
                        self.awaiting_confirmation[sid] = (origin, page, label, element, data['observation'], context)
        return True

    def flush(self):
        with self.lock:
            pending = list(self.observations)
            self.observations.clear()
        try:
            self.catalog.record(pending)
        except (OSError, sqlite3.Error, UnicodeError):
            pass  # Catalog I/O cannot interrupt native browsing.


def page_expression(template, value, url):
    arguments = ', '.join(json.dumps(item, ensure_ascii=True) for item in (value, *url))
    script = template.replace('(ENTRY, ORIGIN, ROUTE)', '(' + arguments + ')')
    return '(() => {' + BUTTONS + ' return ' + script.strip() + '})()'


def controls_on_page(catalog, url, page, label, run_expression):
    origin = url[0]
    entries = catalog.list(origin, page, label)
    if label and not entries:
        entries = catalog.list(origin, page)
    links = [{key: entry[key] for key in ('id', 'label', 'element_id')}
             for entry in entries if entry['state'] == 'navigation']
    details = run_expression(page_expression(_DESCRIBE_LINKS, links, url)) if links else {}
    details = details if isinstance(details, dict) else {}
    controls = []
    suggestions = []
    for entry in entries:
        item = {key: entry[key] for key in ('id', 'label')}
        if entry['state'] == 'navigation':
            link = details.get(entry['id'])
            if not isinstance(link, dict):
                continue
            destination = link.get('destination')
            try:
                _, route_hash = page_key([origin, destination])
            except (ValueError, UnicodeError):
                continue
            if route_hash != entry['value']:
                continue
            display = link.get('label')
            if isinstance(display, str) and 0 < len(display) <= 100 and display.isprintable():
                item['label'] = display
            item['destination'] = destination if len(destination) <= 180 else destination[:179] + '…'
            suggestions.append(item)
        if label is None or label in (entry['label'], item['label']):
            controls.append(item)
    result = {'success': True, 'status': 'ok', 'site': origin, 'site_name': urlsplit(origin).hostname,
              'controls': controls}
    if label and not controls and suggestions:
        result['suggestions'] = suggestions
    return result


def replay_control(entry, url, run_expression):
    """Send at most one click and verify the result on the same page attachment."""
    origin = url[0]
    data = {key: entry[key] for key in ('label', 'element_id', 'state', 'value')}
    if entry.get('selector'):
        data['selector'] = entry['selector']

    if data['state'] == 'navigation':
        destination = run_expression(page_expression(_FIND_LINK, data, url))
        if (not isinstance(destination, str) or not destination.startswith('/')
                or page_key([origin, destination])[1] != data['value']):
            return 'unmatched'
        data['value'] = destination
    status = run_expression(page_expression(_CLICK, data, url), click=True)
    if status == 'navigation_dispatched':
        expected = [origin, data['value']]
        reached = run_expression('[location.origin, location.pathname]', until=expected)
        status = 'verified' if reached == expected else 'unconfirmed'
    if status == 'panel_open_dispatched':
        opened = run_expression(page_expression(_CHECK_OPEN_EFFECT, data['value'], url), until=True)
        status = 'verified' if opened is True else 'unconfirmed'
    return status if isinstance(status, str) else 'unconfirmed'


CLICK_NOT_SENT = ('unmatched', 'wrong_page', 'obscured', 'state_changed')


def catalog_outcome(catalog, entry, status):
    if status == 'verified':
        return {'success': True, 'status': 'ok', 'control': entry['id'], 'dispatched': True}
    if status == 'unmatched' or status not in CLICK_NOT_SENT:
        catalog.stale(entry)
    return fallback(status, dispatched=status not in CLICK_NOT_SENT)


def attempt_dom_control(url, target, run_expression, *, mapping=None, opens=None, previous=None):
    request = {'target': target, **(mapping or {})}
    if opens:
        request['opens'] = opens
    candidate = run_expression(page_expression(_FIND_DOM_CONTROL, request, url))
    if not isinstance(candidate, dict):
        return None, 'unmatched'
    if candidate.get('reason'):
        return None, candidate['reason']
    if candidate['state'] == 'navigation':
        _, candidate['value'] = page_key([url[0], candidate['value']])
    if previous and (candidate['state'], candidate['value']) != (previous['state'], previous['value']):
        # Check the verified effect before retrying under a changed DOM.
        return None, 'state_changed'
    if mapping:
        candidate['selector'] = mapping['selector']
    return candidate, replay_control(candidate, url, run_expression)


def click_titled_link(url, target, mapping, run_expression):
    request = {**mapping, 'target': ' '.join(target.split())}
    expression = page_expression(_CLICK_TITLED_LINK, request, url)
    result = run_expression(expression, click=True)
    if result.get('reason') == 'obscured':
        # Flow can render its cards while the loading layer still covers the link.
        probe = page_expression(_CLICK_TITLED_LINK, {**request, 'probe': True}, url)
        if run_expression(probe, until=True) is True:
            result = run_expression(expression, click=True)
    reason = result.get('reason')
    if reason in CLICK_NOT_SENT:
        return None
    if reason == 'ambiguous':
        return {**fallback('Multiple controls have this title.', dispatched=False), 'source': 'package'}
    expected = [url[0], result['destination']]
    reached = run_expression('[location.origin, location.pathname]', until=expected)
    if reached != expected:
        return {**fallback('unconfirmed', dispatched=True), 'source': 'package'}
    return {'success': True, 'status': 'ok', 'source': 'package', 'dispatched': True}


def click_by_target(catalog, url, page, target, run_expression, package_control):
    """Prefer a verified mapping, then inspect for the same target in the owned tab."""
    origin = url[0]
    controls = catalog.list(origin, page, target) if catalog is not None else []
    if catalog is not None and not controls:
        controls = controls_on_page(catalog, url, page, target, run_expression)['controls']
    entry = catalog.get(controls[0]['id'], origin, page) if len(controls) == 1 else None
    if entry is not None:
        status = replay_control(entry, url, run_expression)
        if status not in ('unmatched', 'obscured'):
            return {**catalog_outcome(catalog, entry, status), 'source': 'catalog'}
        if status == 'unmatched':
            catalog.stale(entry)

    # Use the original label for lookups after the display name of a cached link was resolved.
    target = entry['label'] if entry else target
    mapped = package_control(origin, target, url[1]) if package_control else None
    if mapped and 'card' in mapped:
        outcome = click_titled_link(url, target, mapped, run_expression)
        if outcome is not None:
            return outcome
        mapped = None
    opens = entry['value'] if entry and entry['state'] == 'selector-visible' else None
    source = 'package'
    candidate, status = None, 'unmatched'
    if mapped and not entry:
        candidate, status = attempt_dom_control(url, target, run_expression, mapping=mapped)
        opens = mapped.get('opens')
    if status in ('unmatched', 'obscured'):
        source = 'dom'
        candidate, status = attempt_dom_control(url, target, run_expression, opens=opens, previous=entry)
    if status != 'verified':
        return {**fallback(status, dispatched=status not in CLICK_NOT_SENT), 'source': source}
    result = {'success': True, 'status': 'ok', 'source': source, 'dispatched': True}
    label = candidate['label']
    if catalog is None or not label or len(label) > 100 or not label.isprintable():
        return result
    proof = (candidate['label'], candidate['element_id'], candidate['state'], candidate['value'])
    catalog.record([(origin, page, proof)])
    learned, = catalog.list(origin, page, candidate['label'])
    return {**result, 'control': learned['id'], 'repaired': entry is not None and source == 'dom'}


def cached_action(catalog, command, run_expression, *, package_control=None, package_action=None):
    params = command.get('params', {})
    action = command['action']
    if not isinstance(params, dict):
        raise ValueError('Browser action params must be an object.')
    if action == 'click':
        target = params.get('target')
        if (set(params) != {'target'} or not isinstance(target, str)
                or not 0 < len(target.strip()) <= 100 or not target.strip().isprintable()):
            raise ValueError('Pass one short visible target label to click.')
        url = run_expression('[location.origin, location.pathname]')
        _, page = page_key(url)
        target = target.strip()
        if package_action:
            result = package_action(url[0], target)
            if result is not None:
                return result
        return click_by_target(catalog, url, page, target, run_expression, package_control)
    if (action != 'list_learned_controls' or set(params) - {'label'} or
            ('label' in params and (not isinstance(params['label'], str) or not 0 < len(params['label']) <= 100))):
        raise ValueError('Pass an optional exact label to list_learned_controls.')
    url = run_expression('[location.origin, location.pathname]')
    origin, page = page_key(url)
    if catalog is None:
        return {'success': True, 'status': 'ok', 'site': origin, 'controls': []}
    return controls_on_page(catalog, url, page, params.get('label'), run_expression)


def fallback(reason, *, dispatched):
    return {'success': False, 'status': 'needs_inspection', 'reason': reason,
            'dispatched': dispatched, 'next': ('Check the current page before repeating the click.'
                                              if dispatched else 'Inspect the current page and use a named click for the requested control.')}
