"""Fail-closed CDP surface for trusted GUI helpers and their worker transport.

Runtime.evaluate is reserved for plugin-owned helper expressions; this policy
does not make arbitrary JavaScript safe. The model-facing interpreter must not
expose raw JavaScript, CDP, Python objects, or the transport.
"""
from urllib.parse import urlsplit


# Deliberately list methods and parameters. A newly added CDP domain or command
# must not silently inherit access to the user's browser/profile.
_BROWSER_PARAMS = {
    'Browser.getVersion': set(),
    'Target.getTargets': set(),
    'Target.getTargetInfo': {'targetId'},
    'Target.closeTarget': {'targetId'},
    'Target.activateTarget': {'targetId'},
    'Target.attachToTarget': {'targetId', 'flatten'},
    'Browser.getWindowForTarget': {'targetId'},
    'Target.createTarget': {'url', 'browserContextId', 'newWindow', 'background'},
    'Target.setDiscoverTargets': {'discover'},
}
_PAGE_PARAMS = {
    'Runtime.evaluate': {'expression', 'returnByValue', 'awaitPromise'},
    'Runtime.runIfWaitingForDebugger': set(),
    'Page.enable': set(),
    'Network.enable': set(),
    'Page.navigate': {'url'},
    'Page.getFrameTree': set(),
    'Page.captureScreenshot': {'format', 'quality', 'clip', 'fromSurface', 'captureBeyondViewport'},
    'Page.handleJavaScriptDialog': {'accept', 'promptText'},
    'Input.insertText': {'text'},
    'Input.dispatchMouseEvent': {
        'type', 'x', 'y', 'button', 'buttons', 'clickCount', 'deltaX', 'deltaY', 'modifiers',
    },
    'Input.dispatchKeyEvent': {
        'type', 'key', 'code', 'text', 'unmodifiedText', 'modifiers',
        'windowsVirtualKeyCode', 'nativeVirtualKeyCode', 'autoRepeat', 'isKeypad',
        'location', 'commands',
    },
}
_TARGET_METHODS = {
    'Target.getTargetInfo', 'Target.closeTarget', 'Target.activateTarget',
    'Target.attachToTarget', 'Browser.getWindowForTarget',
}
_INTERNAL_META = {'__pump__', '__history_gap__'}


def validate_navigation_url(url, *, allow_profile_verification=False):
    """Permit web navigation and the one trusted profile-verification document."""
    if not isinstance(url, str) or not url or url != url.strip() or any(ord(c) < 32 for c in url):
        raise RuntimeError('cdp_navigation_not_allowed')
    if url == 'about:blank':
        return
    if allow_profile_verification and url in {'chrome://version', 'chrome://version/'}:
        return
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in {'http', 'https'} and bool(parsed.hostname) and not parsed.username and not parsed.password
        parsed.port  # Invalid ports are not valid navigation input.
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError('cdp_navigation_not_allowed')


def _owned_target(state, target):
    if not isinstance(target, str) or not target or target not in state.get('owned', {}):
        raise RuntimeError('target_not_owned')
    if not isinstance(state.get('context'), str) or not state['context']:
        raise RuntimeError('cdp_context_unverified')
    return target


def validate_cdp(method, params, state, sessions=None, session_id=None, *, transport=False):
    """Validate before any observation, attachment, watcher, or action is sent.

    Return the owned target to revalidate against live inventory when applicable.
    ``transport`` requires an already-held page session; helper calls may resolve
    their current owned page only after this static check succeeds.
    """
    if not isinstance(method, str) or not isinstance(params, dict):
        raise RuntimeError('cdp_request_invalid')
    state = {} if state is None else state
    sessions = {} if sessions is None else sessions
    if not isinstance(state, dict) or not isinstance(sessions, dict) or not isinstance(state.get('owned', {}), dict):
        raise RuntimeError('cdp_request_invalid')
    if transport and method in _INTERNAL_META:
        if params or session_id is not None:
            raise RuntimeError('cdp_parameters_not_allowed')
        return None
    allowed = _BROWSER_PARAMS.get(method, _PAGE_PARAMS.get(method))
    if allowed is None:
        raise RuntimeError('cdp_method_not_allowed: ' + method)
    if set(params) - allowed:
        raise RuntimeError('cdp_parameters_not_allowed: ' + method)
    if method in _BROWSER_PARAMS:
        if session_id is not None:
            raise RuntimeError('cdp_browser_session_not_allowed')
        if method in _TARGET_METHODS:
            if transport and 'targetId' not in params:
                raise RuntimeError('cdp_target_required')
            target = _owned_target(state, params.get('targetId', state.get('current')))
            if method == 'Target.attachToTarget' and params.get('flatten', True) is not True:
                raise RuntimeError('cdp_parameters_not_allowed: ' + method)
            return target
        if method == 'Target.createTarget':
            target = _owned_target(state, state.get('current'))
            if 'browserContextId' in params and params['browserContextId'] != state['context']:
                raise RuntimeError('cdp_context_not_owned')
            if transport:
                expected = {'url': 'about:blank', 'browserContextId': state['context'], 'newWindow': True, 'background': True}
                if params != expected:
                    raise RuntimeError('cdp_creation_not_owned')
            else:
                validate_navigation_url(params.get('url', 'about:blank'))
                if params.get('newWindow', True) is not True or params.get('background', True) is not True:
                    raise RuntimeError('cdp_creation_not_owned')
            return target
        if method == 'Target.setDiscoverTargets':
            if not transport or params != {'discover': True}:
                raise RuntimeError('cdp_parameters_not_allowed: ' + method)
            return _owned_target(state, state.get('current'))
        return None

    if session_id is None:
        if transport:
            raise RuntimeError('session_not_owned')
        target = _owned_target(state, state.get('current'))
    else:
        target = next((target for target, sid in sessions.items() if sid == session_id), None)
        if target is None:
            raise RuntimeError('session_not_owned')
        _owned_target(state, target)
    if method == 'Page.navigate':
        validate_navigation_url(params.get('url'), allow_profile_verification=state.get('verified') is False)
    elif method == 'Runtime.evaluate' and not isinstance(params.get('expression'), str):
        raise RuntimeError('cdp_parameters_not_allowed: ' + method)
    elif method == 'Page.handleJavaScriptDialog':
        if type(params.get('accept')) is not bool or ('promptText' in params and not isinstance(params['promptText'], str)):
            raise RuntimeError('cdp_parameters_not_allowed: ' + method)
    return target
