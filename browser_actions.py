"""Named GUI actions exposed to browser scripts. No raw JS/CDP or host I/O API."""
import base64
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

if __package__:
    from .execution_policy import HELPERS, PolicyError
    from .cdp_policy import validate_navigation_url
    from . import gui_lease, flow_reservation
else:
    from execution_policy import HELPERS, PolicyError
    from cdp_policy import validate_navigation_url
    import gui_lease
    import flow_reservation


def navigation_url(value):
    if type(value) is not str or len(value) > 8192:
        raise PolicyError('browser_url_not_allowed')
    try:
        validate_navigation_url(value)
    except RuntimeError:
        raise PolicyError('browser_url_not_allowed: use HTTP(S) or about:blank') from None
    return value


def bounded_number(value, lower, upper):
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
        raise PolicyError('browser_argument_out_of_range')
    return value


def selector_text(value):
    if type(value) is not str or not value or len(value) > 4096:
        raise PolicyError('browser_selector_invalid')
    return value


def public_helpers(browser, trusted, workspace, profile=None, lease_stack=None, *, account_key=None):
    """The interpreter sees only these callables and their plain-data results."""
    workspace = Path(workspace)
    leases = {}
    activity = None

    def reserve_origin(url):
        nonlocal activity
        deadline=time.monotonic()+15
        # Always acquire account activity BEFORE the short GUI mutex. Reversing
        # these would block the running job from restoring/downloading its clip.
        if flow_reservation.protected_url(url) and activity is None:
            if profile is None or lease_stack is None:
                raise PolicyError('browser_profile_unverified_for_shared_gui')
            activity = lease_stack.enter_context(flow_reservation.acquire_browser(profile, timeout=15,account_key=account_key))
        if activity is not None:
            activity.check_binding()
        origin = gui_lease.origin_for_url(url)
        if origin is None or origin in leases:
            return
        if profile is None or lease_stack is None:
            raise PolicyError('browser_profile_unverified_for_shared_gui')
        leases[origin] = lease_stack.enter_context(gui_lease.acquire(profile, origin, timeout=max(0,deadline-time.monotonic())))

    def page_guard():
        url=browser.info().get('url','')
        if not url:
            # TargetInfo may omit URL during a renderer swap. Read the same
            # owned page's main frame, never infer safety from the destination.
            tree=browser.cdp('Page.getFrameTree')
            url=(tree.get('frameTree') or {}).get('frame',{}).get('url','')
        try:navigation_url(url)
        except PolicyError:
            # Operator diagnostics distinguish stale setup/error documents from
            # rejected caller URLs without exposing the document's address.
            scheme=url.partition(':')[0].lower() if isinstance(url,str) and ':' in url else 'missing'
            if scheme not in {'http','https','about','chrome','chrome-error','chrome-untrusted',
                              'chrome-extension','devtools','file','data','javascript','missing'}:
                scheme='other'
            raise PolicyError('browser_document_not_allowed: scheme='+scheme) from None
        reserve_origin(url)

    def wrap_page(fn):
        def guarded(*args, **kwargs):
            page_guard()
            return fn(*args, **kwargs)
        return guarded

    def goto_url(url):
        url=navigation_url(url)
        page_guard()
        reserve_origin(url)
        result=browser.cdp('Page.navigate', url=url)
        if not isinstance(result,dict):raise RuntimeError('browser_navigation_failed: invalid_response')
        if result.get('errorText'):
            error=result['errorText']
            code=error if isinstance(error,str) and re.fullmatch(r'(?:net::)?ERR_[A-Z0-9_]{1,80}',error) else 'navigation_error'
            raise RuntimeError('browser_navigation_failed: '+code)
        return result

    def new_tab(url='about:blank'):
        url=navigation_url(url)
        reserve_origin(url)
        return browser.create(url)

    def read_page(selector='body', limit=12000):
        selector = selector_text(selector)
        if type(limit) is not int:
            raise PolicyError('browser_argument_out_of_range')
        bounded_number(limit, 1, 20000)
        # Caller-controlled strings are data literals, never JS expressions.
        return trusted['js']("""(()=>{
          const roots=document.querySelectorAll(SELECTOR);
          if(roots.length!==1) throw Error('page_selector_not_unique');
          const root=roots[0];
          const visible=e=>!!e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
          const css=e=>{const parts=[];for(let n=e;n&&n.nodeType===1;n=n.parentElement){
            let p=n.localName;
            if(n.id){p+='#'+CSS.escape(n.id);parts.unshift(p);break;}
            const peers=n.parentElement?Array.from(n.parentElement.children).filter(x=>x.localName===n.localName):[];
            if(peers.length>1)p+=':nth-of-type('+(peers.indexOf(n)+1)+')';
            parts.unshift(p);
          }return parts.join(' > ');};
          const controls=Array.from(root.querySelectorAll('a,button,input:not([type=hidden]),textarea,select,[role=button]'))
            .filter(visible).slice(0,40).map(e=>({selector:css(e).slice(0,512),tag:e.localName,
              type:(e.getAttribute('type')||'').slice(0,40),text:(e.innerText||'').slice(0,120),
              label:(e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').slice(0,120),
              disabled:!!e.disabled}));
          return {url:location.href.slice(0,8192),title:document.title.slice(0,500),
            text:visible(root)?(root.innerText||'').slice(0,LIMIT):'',controls};
        })()""".replace('LIMIT', str(limit)).replace('SELECTOR', json.dumps(selector)))

    def click_element(selector):
        selector = selector_text(selector)
        # Reuse real input dispatch after a fixed DOM lookup. Never evaluate an
        # agent-supplied function, URL or event handler as source code.
        point = trusted['js']("""(()=>{
          const xs=document.querySelectorAll(SELECTOR);
          if(xs.length!==1)throw Error('click_selector_not_unique');
          const e=xs[0];if(e.disabled)throw Error('element_disabled');
          e.scrollIntoView({block:'center',inline:'center'});
          const r=e.getBoundingClientRect();
          if(!r.width||!r.height||getComputedStyle(e).visibility==='hidden')throw Error('element_not_visible');
          const x=r.left+r.width/2,y=r.top+r.height/2,hit=document.elementFromPoint(x,y);
          if(!hit||!(hit===e||e.contains(hit)))throw Error('element_obscured');
          return {x,y};
        })()""".replace('SELECTOR', json.dumps(selector)))
        return click_at_xy(point['x'], point['y'])

    def click_at_xy(x, y, button='left', clicks=1):
        bounded_number(x, 0, 100000)
        bounded_number(y, 0, 100000)
        if button not in ('left', 'right', 'middle') or type(clicks) is not int or not 1 <= clicks <= 3:
            raise PolicyError('browser_argument_out_of_range')
        for event in ('mousePressed', 'mouseReleased'):
            browser.cdp('Input.dispatchMouseEvent', type=event, x=x, y=y, button=button, clickCount=clicks)

    def capture_screenshot(full=False):
        if type(full) is not bool:
            raise PolicyError('browser_argument_out_of_range')
        response = browser.cdp('Page.captureScreenshot', format='png', captureBeyondViewport=full)
        if type(response.get('data')) is not str or len(response['data']) > 24 * 1024 * 1024:
            raise PolicyError('browser_screenshot_size_limit')
        data = base64.b64decode(response['data'], validate=True)
        # A generated exclusive file has no caller-supplied path or symlink to
        # overwrite. The workspace is host-owned, never a script variable.
        workspace.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='shot-', suffix='.png', dir=workspace)
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
        return name

    def wait(seconds=1):
        return trusted['wait'](bounded_number(seconds, 0, 30))

    def wait_for_load(timeout=15):
        return trusted['wait_for_load'](bounded_number(timeout, 0, 30))

    def wait_for_element(selector, timeout=10, visible=False):
        if type(visible) is not bool:
            raise PolicyError('browser_argument_out_of_range')
        return trusted['wait_for_element'](selector_text(selector), bounded_number(timeout, 0, 30), visible)

    def wait_for_network_idle(timeout=10, idle_ms=500):
        return trusted['wait_for_network_idle'](bounded_number(timeout, 0, 30), bounded_number(idle_ms, 0, 30000))

    def fill_input(selector, text, clear_first=True, timeout=0):
        if type(text) is not str or len(text) > 10000 or type(clear_first) is not bool:
            raise PolicyError('browser_argument_out_of_range')
        return trusted['fill_input'](selector_text(selector), text, clear_first, bounded_number(timeout, 0, 30))

    def press_key(key):
        if type(key) is not str or not (len(key) == 1 or key in {
            'Enter', 'Tab', 'Backspace', 'Escape', 'Delete', 'ArrowLeft',
            'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'}):
            raise PolicyError('browser_key_not_allowed')
        return trusted['press_key'](key)

    def answer_dialog(accept, prompt_text=None):
        if type(accept) is not bool or prompt_text is not None and type(prompt_text) is not str:
            raise PolicyError('browser_dialog_answer_invalid')
        params = {'accept': accept}
        if prompt_text is not None:
            params['promptText'] = prompt_text
        return browser.cdp('Page.handleJavaScriptDialog', **params)

    def drain_events():
        # Network events can carry Cookie/Set-Cookie headers. Scripts get event
        # names only; trusted network-idle helpers consume their own metadata.
        return [{'method': event['method']} for event in trusted['drain_events']()]

    def target_guard(target):
        if isinstance(target,dict):target=target.get('targetId') or target.get('target_id')
        if not isinstance(target,str) or not target or len(target)>512:
            raise PolicyError('browser_argument_out_of_range')
        url=browser.info(target).get('url','')
        # A renderer swap is not evidence that the destination is unrelated.
        navigation_url(url)
        reserve_origin(url)
        return target

    def switch_tab(target,activate=False):
        if type(activate) is not bool:raise PolicyError('browser_argument_out_of_range')
        target=target_guard(target)
        trusted['switch_tab'](target,activate=activate)
        return {'tab_id':browser.info()['targetId']}

    def activate_tab(target):
        target=target_guard(target)
        return trusted['activate_tab'](target)

    def finish_browser(retain=()):
        result=trusted['finish_browser'](retain)
        complete=result.get('success') is True
        public={'success':complete,'cleanup_complete':complete}
        if not complete:
            public['remaining_tabs']=len(result.get('remaining_owned_targets') or [])
            public['notice']='Some browser tabs could not be confirmed closed.'
        return public

    actions = {name: trusted[name] for name in (
        'page_info', 'type_text', 'press_key', 'scroll', 'list_tabs', 'current_tab',
        'activate_tab', 'close_tab', 'ensure_real_tab')}
    actions.update(goto_url=goto_url, new_tab=new_tab, read_page=read_page,
                   click_element=click_element, click_at_xy=click_at_xy,
                   capture_screenshot=capture_screenshot, wait=wait,
                   wait_for_load=wait_for_load, wait_for_element=wait_for_element,
                   wait_for_network_idle=wait_for_network_idle, fill_input=fill_input,
                   press_key=press_key, answer_dialog=answer_dialog, drain_events=drain_events,
                   switch_tab=switch_tab,activate_tab=activate_tab,finish_browser=finish_browser)
    for name in ('page_info', 'read_page', 'click_element', 'click_at_xy',
                 'capture_screenshot', 'type_text', 'fill_input', 'press_key',
                 'scroll', 'wait_for_load', 'wait_for_element', 'wait_for_network_idle',
                 'answer_dialog'):
        actions[name] = wrap_page(actions[name])
    assert set(actions) == HELPERS
    return actions
