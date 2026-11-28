"""Expose native browser operations through the existing owned Chrome session."""
import json
import math
from pathlib import Path
from urllib.parse import urlsplit


NATIVE_ACTIONS = ('page_info', 'inspect', 'scroll', 'press_key', 'wait', 'tabs', 'events')
KEY_TARGET = 'CHROME_KEY_TARGET='


def browser_url(url):
    if (not isinstance(url, str) or not url.isprintable()
            or any(char.isspace() for char in url) or '\\' in url):
        raise ValueError('Pass an absolute HTTP or HTTPS URL.')
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('Pass an absolute HTTP or HTTPS URL.')
    return url


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def selector(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Pass a CSS selector.')
    return value


def json_code(expression):
    return f'import json\nprint(json.dumps({expression}))'


def read_dom_code(expression, frame=None):
    if frame is None:
        return json_code(f'js({expression!r})')
    frame = selector(frame)
    identify = r'''(query => {
        const frames = document.querySelectorAll(query);
        const node = frames[0];
        if (frames.length !== 1 || !node.matches('iframe,frame')) return null;
        return {local: !!node.contentDocument, url: node.src};
    })(QUERY)'''.replace('QUERY', json.dumps(frame))
    local = ('(function(document) { return (' + expression.strip() + '); })('
             'window.document.querySelector(' + json.dumps(frame) + ').contentDocument)')
    return f'''import json
_frame = js({identify!r})
if not _frame:
    raise RuntimeError('Select one iframe in the current tab.')
if _frame['local']:
    print(json.dumps(js({local!r})))
else:
    _frames = [row for row in cdp('Target.getTargets')['targetInfos']
               if row.get('type') == 'iframe' and row.get('url') == _frame['url']]
    if len(_frames) != 1 or iframe_target(_frame['url']) != _frames[0]['targetId']:
        raise RuntimeError('Could not identify one attached iframe for that selector.')
    print(json.dumps(js({expression!r}, target_id=_frames[0]['targetId'])))'''


_INSPECT = r'''((query, limit) => {
    const attributes = ['id','role','type','name','aria-label','aria-expanded','aria-checked',
        'aria-selected','title','href','src','placeholder','accept','multiple','disabled','hidden'];
    const all = [...document.querySelectorAll(query)];
    return {title:document.title,count:all.length,elements:all.slice(0,limit).map(e=>({
        tag:e.localName,visible:e.checkVisibility({visibilityProperty:true,opacityProperty:true}),
        attributes:Object.fromEntries(attributes.filter(a=>e.hasAttribute(a)).map(a=>[a,e.getAttribute(a)])),
        text:(e.innerText || '').trim().slice(0,300),
    }))};
})(QUERY, LIMIT)'''
_FOCUSED_ACTIVATION = r'''(key => {
    let active = document.activeElement;
    while (active?.matches('iframe,frame')) {
        if (!active.contentDocument) return '';
        active = active.contentDocument.activeElement;
    }
    if (!active?.matches('button,a[href],summary,[role=button],[role=tab],[role=menuitem],[role=option],'
            + 'input[type=button],input[type=submit],input[type=reset],input[type=checkbox],input[type=radio]')) return null;
    if (key === ' ' && active.matches('a[href]:not([role=button])')) return null;
    if (key === 'Enter' && active.matches('input[type=checkbox],input[type=radio]')) return null;
    if (active.closest('[inert]') || active.matches(':disabled,[aria-disabled=true]')) return null;
    return (active.getAttribute('aria-label') || active.innerText || active.labels?.[0]?.innerText ||
        active.getAttribute('title') || '').trim().replace(/\s+/g,' ');
})(KEY)'''

_EVENT_SUMMARY = '''import json
observations = []
for event in drain_events():
    params = event.get('params') or {}
    item = {'method': event.get('method')}
    for name in ('frameId', 'requestId', 'loaderId', 'timestamp', 'type', 'canceled', 'errorText'):
        if name in params:
            item[name] = params[name]
    if isinstance(params.get('response'), dict):
        item.update({name: params['response'][name] for name in ('status', 'mimeType') if name in params['response']})
    observations.append(item)
print(json.dumps({'events': observations}))'''

_OPEN_TAB = '''import json, uuid
from time import monotonic
_parent = current_tab()['target_id']
_window = cdp('Browser.getWindowForTarget', targetId=_parent)['windowId']
_blank = 'about:blank#original-chrome-' + uuid.uuid4().hex
_scope = cdp('Page.createIsolatedWorld', frameId=cdp('Page.getFrameTree')['frameTree']['frame']['id'])
_opened = cdp('Runtime.evaluate', contextId=_scope['executionContextId'], userGesture=True,
              expression='Boolean(window.open(' + json.dumps(_blank) + ', "_blank"))', returnByValue=True)
if not _opened.get('result', {}).get('value'):
    raise RuntimeError('Chrome did not open a tab in the task window.')
_deadline = monotonic() + 4
while True:
    _tabs = [tab for tab in list_tabs() if tab['url'] == _blank]
    if len(_tabs) == 1:
        break
    if monotonic() >= _deadline:
        raise RuntimeError('Verify the task window before opening another tab.')
    wait(.1)
_target = _tabs[0]['target_id']
if cdp('Browser.getWindowForTarget', targetId=_target)['windowId'] != _window:
    close_tab(_target)
    raise RuntimeError('Chrome placed the new tab outside the task window.')
switch_tab(_target)
'''


def tab_code(params):
    mode = params.get('mode', 'list')
    allowed = {
        'list': {'include_chrome'}, 'current': set(), 'ensure': set(),
        'open': {'url'}, 'switch': {'target_id'}, 'close': {'target_id'},
    }
    if not isinstance(mode, str) or mode not in allowed or set(params) - {'mode'} - allowed[mode]:
        raise ValueError('Use tabs with mode list, current, ensure, open, switch or close.')
    if mode == 'list':
        include = params.get('include_chrome', True)
        if not isinstance(include, bool):
            raise ValueError('include_chrome must be a boolean.')
        return json_code(f'{{"tabs": list_tabs(include_chrome={include!r})}}')
    if mode == 'current':
        return json_code('current_tab()')
    if mode == 'ensure':
        return json_code('ensure_real_tab()')
    if mode == 'open':
        code = _OPEN_TAB
        if 'url' in params:
            code += f'goto_url({browser_url(params["url"])!r})\n'
        return code + 'print(json.dumps(current_tab()))'
    target = params.get('target_id')
    if ((mode == 'switch' or 'target_id' in params)
            and (not isinstance(target, str) or not target or not target.isalnum())):
        raise ValueError('Pass a target_id from the task tab list.')
    if mode == 'switch':
        return f'switch_tab({target!r})\n' + json_code('current_tab()')
    return f'close_tab({target!r})\n' + json_code('{"closed": True}')


def wait_code(params):
    mode = params.get('mode', 'load')
    allowed = {'load': {'timeout'}, 'element': {'timeout', 'selector', 'visible'},
               'network_idle': {'timeout', 'idle_ms'}, 'seconds': {'seconds'}}
    if not isinstance(mode, str) or mode not in allowed or set(params) - {'mode'} - allowed[mode]:
        raise ValueError('Use wait with mode load, element, network_idle or seconds.')
    timeout = params.get('timeout', 15 if mode == 'load' else 10)
    if not number(timeout) or timeout <= 0:
        raise ValueError('Pass a positive wait timeout.')
    if mode == 'seconds':
        seconds = params.get('seconds')
        if not number(seconds) or seconds < 0:
            raise ValueError('Pass the number of seconds to wait.')
        return f'wait({seconds!r})\n' + json_code('{"ready": True}')
    if mode == 'element':
        query = selector(params.get('selector'))
        visible = params.get('visible', False)
        if not isinstance(visible, bool):
            raise ValueError('visible must be a boolean.')
        expression = f'wait_for_element({query!r}, timeout={timeout!r}, visible={visible!r})'
    elif mode == 'network_idle':
        idle = params.get('idle_ms', 500)
        if type(idle) is not int or idle <= 0:
            raise ValueError('Pass a positive idle_ms.')
        expression = f'wait_for_network_idle(timeout={timeout!r}, idle_ms={idle!r})'
    else:
        expression = f'wait_for_load(timeout={timeout!r})'
    return json_code(f'{{"ready": {expression}}}')


def screenshot_code(params):
    if set(params) - {'full', 'max_dim', 'path'}:
        raise ValueError('Pass optional full, max_dim or path.')
    full, max_dim = params.get('full', False), params.get('max_dim', 1200)
    if not isinstance(full, bool) or (max_dim is not None and (type(max_dim) is not int or max_dim <= 0)):
        raise ValueError('Pass full as a boolean and max_dim as a positive integer or null.')
    if not params:
        return 'print(capture_screenshot(max_dim=1200))'
    arguments = f'full={full!r}, max_dim={max_dim!r}'
    if 'path' not in params:
        return f'print(capture_screenshot({arguments}))'
    try:
        output = Path(selector(params['path'])).expanduser()
    except RuntimeError as error:
        raise ValueError('Pass an absolute PNG output path.') from error
    if not output.is_absolute() or output.suffix.lower() != '.png' or '\x00' in str(output):
        raise ValueError('Pass an absolute PNG output path.')
    return f'''from pathlib import Path
_output = Path({str(output)!r})
with _output.open('xb'):
    pass
try:
    print(capture_screenshot(str(_output), {arguments}))
except Exception:
    _output.unlink(missing_ok=True)
    raise'''


def native_action_code(action, params):
    if action == 'tabs':
        return tab_code(params)
    if action == 'wait':
        return wait_code(params)
    if action == 'page_info' and not params:
        return json_code('page_info()')
    if action == 'events' and not params:
        return _EVENT_SUMMARY
    if action == 'inspect' and set(params) <= {'selector', 'frame', 'limit'}:
        query = selector(params.get('selector', 'button,a[href],input,textarea,select,iframe,[role=button]'))
        limit = params.get('limit', 50)
        if type(limit) is not int or limit <= 0:
            raise ValueError('Pass a positive element limit.')
        return read_dom_code(_INSPECT.replace('QUERY, LIMIT', f'{json.dumps(query)}, {limit}'), params.get('frame'))
    if action == 'scroll' and set(params) <= {'x', 'y', 'dx', 'dy'}:
        if not all(number(value) for value in params.values()):
            raise ValueError('Pass finite scroll coordinates and distances.')
        x, y = params.get('x', 'innerWidth/2'), params.get('y', 'innerHeight/2')
        dx, dy = params.get('dx', 0), params.get('dy', 300)
        return f'_x, _y = js("[{x},{y}]")\nscroll(_x, _y, dy={dy!r}, dx={dx!r})'
    if action == 'press_key' and set(params) <= {'key', 'modifiers'}:
        key, modifiers = params.get('key'), params.get('modifiers', 0)
        if (not isinstance(key, str) or not key or not key.isprintable()
                or type(modifiers) is not int or not 0 <= modifiers <= 15):
            raise ValueError('Pass a keyboard key and optional native modifier bitmask.')
        key = ' ' if key in {'Space', 'Spacebar'} else key
        code = f'press_key({key!r}, modifiers={modifiers!r})'
        if key not in {'Enter', ' '}:
            return code
        focus = _FOCUSED_ACTIVATION.replace('(KEY)', '(' + json.dumps(key) + ')')
        return (f'import json\n_focused = js({focus!r})\n'
                f'if _focused is not None:\n    print({KEY_TARGET!r} + json.dumps(_focused))\n'
                f'else:\n    {code}')
    raise ValueError('Pass parameters for this browser action.')


def key_target(result):
    if isinstance(result, dict) and result.get('success'):
        for line in (result.get('output') or '').splitlines():
            if line.startswith(KEY_TARGET):
                return json.loads(line[len(KEY_TARGET):])
    return None
