"""Dismiss known informational overlays in the owned Chrome tab."""
import json
from textwrap import indent


SITE_ORIGINS = {'flow': 'https://flow.google.com', 'elevenlabs': 'https://elevenlabs.io'}
MARKER = 'ORIGINAL_CHROME_POPUP='

_OVERLAY = r"""(function (sites, expected) {
    const page = [location.origin, location.pathname, performance.timeOrigin];
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    if (expected && !same(page, expected.page)) return {changed: true};
    const visible = e => e.getClientRects().length &&
        e.checkVisibility({visibilityProperty: true, opacityProperty: true});
    const clean = text => (text || '').trim().replace(/\s+/g, ' ').toLowerCase();
    const label = e => clean(e.getAttribute('aria-label') || e.innerText);
    const all = (root, selector) => [...root.querySelectorAll(selector)].filter(visible);
    const controls = 'button, [role="button"]';
    const headings = 'h1, h2, h3, h4, [role="heading"]';
    const matching = (root, labels) => all(root, controls).filter(e => labels.includes(label(e)));

    function nearby(mark, labels, text = '') {
        let root = mark.parentElement;
        for (let depth = 0; root && root !== document.body && depth < 6; depth++, root = root.parentElement) {
            if (text && !clean(root.innerText).includes(text)) continue;
            const buttons = matching(root, labels);
            if (buttons.length) return buttons;
        }
        return [];
    }

    function inspect() {
        if (page[0] === sites.flow && page[1].startsWith('/project/')) {
            const dialogs = all(document, 'mat-dialog-container, [role="dialog"]')
                .filter(e => all(e, 'iframe[src*="/changelogs/"], a[href*="changelog"]').length ||
                    all(e, headings).some(h => ['yang baru', "what's new", 'what’s new'].includes(label(h))));
            if (dialogs.length) return ['flow-changelog', dialogs.flatMap(e => matching(e, ['mulai', 'get started']))];
        }
        if (page[0] === sites.elevenlabs && page[1].startsWith('/app/')) {
            const intro = all(document, headings).filter(e => label(e) === 'introducing eleven v4');
            if (intro.length) return ['elevenlabs-intro', intro.flatMap(e => nearby(e, ['got it']))];
            const studio = matching(document, ['try studio']);
            if (studio.length) {
                const close = studio.flatMap(e => nearby(e, ['close popup']));
                if (close.length) return ['elevenlabs-studio', close];
            }
            const links = all(document, 'a[href]');
            for (const [kind, link, heading] of [
                ['elevenlabs-offer', 'get the offer', 'black friday'],
                ['elevenlabs-v4', 'try it out', 'eleven v4 is here']
            ]) {
                const dismiss = links.filter(e => label(e) === link)
                    .flatMap(e => nearby(e, ['dismiss'], heading));
                if (dismiss.length) return [kind, dismiss];
            }
        }
        return null;
    }

    const overlay = inspect();
    if (!overlay) return null;
    const [kind, matches] = overlay;
    const buttons = [...new Set(matches)];
    const button = buttons.length === 1 ? buttons[0] : null;
    const observed = {page, kind, label: button ? label(button) : null};
    if (!expected) return observed;
    if (kind !== expected.kind || observed.label !== expected.label) return {changed: true};
    if (!button || button.matches(':disabled, [aria-disabled="true"]')) return observed;
    const bounds = button.getBoundingClientRect();
    if (!button.contains(document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2))) {
        return observed;
    }
    button.click();
    return {...observed, clicked: true};
})"""


def guarded_code(code, *, target='', after=False):
    """Keep popup handling inside the current native execution and page attachment."""
    probe = f'{_OVERLAY}({json.dumps(SITE_ORIGINS)}, null)'
    click = f'{_OVERLAY}({json.dumps(SITE_ORIGINS)}, '
    guard = f'''import json as _popup_json

def _resolve_site_popup():
    _page_expression = '[location.origin, location.pathname, performance.timeOrigin]'
    _known = js(_page_expression)
    if not _known or _known[0] not in {tuple(SITE_ORIGINS.values())!r}:
        return None
    if {after!r}:
        wait(.35)
    _overlay = js({probe!r})
    _closed = set()
    _target_closed = False
    while _overlay and _overlay['kind'] not in _closed:
        _clicked = js({click!r} + _popup_json.dumps(_overlay) + ')')
        if not _clicked or not _clicked.get('clicked'):
            if not _clicked and js(_page_expression) == _overlay['page']:
                _overlay = js({probe!r})
            break
        _kind = _overlay['kind']
        _closed.add(_kind)
        for _check in range(8):
            wait(.1)
            _overlay = js({probe!r})
            if _overlay is None and _check == 0:
                continue
            if _overlay is None or _overlay['kind'] != _kind:
                break
        if js(_page_expression) != _clicked['page']:
            _overlay = {{'kind': 'page_changed_during_popup'}}
            break
        if _overlay is None or _overlay['kind'] != _kind:
            _target_closed |= _clicked['label'] == {target!r}
    if _overlay:
        return {{'success': False, 'status': 'needs_inspection', 'source': 'popup',
                'reason': _overlay['kind'], 'dispatched': {after!r},
                'next': 'Inspect the visible popup in this window before continuing.'}}
    if _target_closed:
        return {{'success': True, 'status': 'ok', 'source': 'popup', 'dispatched': True}}

_popup_result = _resolve_site_popup()
if _popup_result is not None:
    print({MARKER!r} + _popup_json.dumps(_popup_result))'''
    if after:
        return f'{code}\n{guard}'
    return f'{guard}\nelse:\n{indent(code, "    ")}'


def popup_result(native_result):
    if not isinstance(native_result, dict) or not native_result.get('success'):
        return None
    for line in (native_result.get('output') or '').splitlines():
        if line.startswith(MARKER):
            return json.loads(line[len(MARKER):])
    return None
