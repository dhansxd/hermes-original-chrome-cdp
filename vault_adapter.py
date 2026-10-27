"""Exact selected-target vault transport; native algorithms stay in core (read-only).

Version-specific function-namespace copies, NOT a public native vault transport API.
Only the public plugin tool override should call invoke(). No worker receives secrets.
"""
import copy
import hashlib
import json
import logging
import secrets
import types
from pathlib import Path

if __package__:
    from .binding import BoundBrowser
    from .worker import Wire as _Wire
    from .consent import connect_with_consent
else:
    from binding import BoundBrowser
    from worker import Wire as _Wire
    from consent import connect_with_consent
from websockets.sync.client import connect

NATIVE_SHA256 = 'ea1ac6458b5cf542a203c51168ae6fb4c6e9c7b1eae3854cc28852d57b0fc651'


class Wire(_Wire):
    def __init__(self, endpoint, data_root):
        # A private non-propagating logger prevents websocket DEBUG frame logs
        # from recording secret-bearing Runtime.evaluate payloads.
        logger = logging.Logger('native-vault-transport', level=logging.CRITICAL + 1)
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        self.ws = connect_with_consent(endpoint, data_root,
            lambda *a, **kw: connect(*a, **kw, logger=logger))
        self.counter = 0


def _failure(kind='vault_binding_unavailable'):
    return json.dumps({'success': False, 'error_type': kind,
                       'error': 'Exact selected vault target unavailable or changed; no fallback or replay.'})


def invoke(provider, original_handler, args, kwargs):
    """Public override wrapper; caller must route only when this provider is selected.

    provider.last_sessions maps str(task_id or 'default') -> named browser session.
    A prior successful browser_exec must set it. Never infer a session by origin.
    """
    try:
        with provider.lock:
            task = str(kwargs.get('task_id') or 'default')
            selected = provider.last_sessions.get(task)
            entry = provider.states.get((task, selected)) if selected else None
            if not entry or entry.get('uncertain') or not entry.get('state'):
                return _failure()
            # Copy pins target even if an external callback modifies provider state.
            state = copy.deepcopy(entry['state'])
            observer = entry.get('observer')
            if observer is None:
                return _failure()
            with observer.borrow(state) as browser:
                adapter = _Transport(browser)
                namespace = _namespace(original_handler, adapter)
                result = json.loads(namespace[original_handler.__name__](args, **kwargs))
                if not adapter.evaluate(task, 'true').get('success'):
                    return _failure('vault_document_changed')
            # Native save errors can stringify the backend before password
            # redaction registration. Do not expose free-text error fields.
            def scrub_errors(value):
                if isinstance(value, dict):
                    return {k: ('Vault operation refused or failed; no retry.' if k == 'error' else scrub_errors(v)) for k, v in value.items()}
                if isinstance(value, list):
                    return [scrub_errors(v) for v in value]
                return value
            from agent.redact import redact_registered_vault_values
            return redact_registered_vault_values(json.dumps(scrub_errors(result)))
    except Exception:
        # Never stringify a transport/backend exception: it may contain secret JS.
        return _failure('vault_operation_failed')


def _namespace(handler, transport):
    from tools import browser_vault_tool as native
    if (not isinstance(handler, types.FunctionType)
            or handler.__globals__ is not vars(native)
            or handler.__name__ != '_handle_vault'):
        raise RuntimeError('unsupported_native_vault_version')
    if hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest() != NATIVE_SHA256:
        raise RuntimeError('unsupported_native_vault_version')
    namespace = dict(vars(native))
    for name, fn in vars(native).items():
        if isinstance(fn, types.FunctionType) and fn.__module__ == native.__name__:
            clone = types.FunctionType(fn.__code__, namespace, fn.__name__, fn.__defaults__, fn.__closure__)
            clone.__kwdefaults__ = fn.__kwdefaults__
            namespace[name] = clone
    namespace['_eval_js'] = transport.evaluate
    # Retain native _eval_js_secret's Bot Desktop re-admission; its private
    # supervisor facade can evaluate only this exact pinned target.
    namespace['_ensure_supervisor'] = lambda task: transport
    namespace['_focus_bound_origin'] = lambda task, origin, kind: (
        found if (found := namespace['_current_page_origin'](task)) and (not origin or origin == found) else None)
    return namespace


class _Transport:
    def __init__(self, browser):
        self.browser = browser
        self.marker = '__hermes_vault_' + secrets.token_hex(16)
        self.token = secrets.token_hex(16)
        self.href = self._raw('window.location.href')
        if not isinstance(self.href, str):
            raise RuntimeError('document_pin_failed')
        expression = ('Object.defineProperty(globalThis,' + json.dumps(self.marker)
                      + ',{value:' + json.dumps(self.token) + '}); true')
        if self._raw(expression) is not True:
            raise RuntimeError('document_pin_failed')

    def _raw(self, expression):
        response = self.browser.cdp('Runtime.evaluate', expression=expression,
                                    returnByValue=True, awaitPromise=False)
        if response.get('exceptionDetails'):
            raise RuntimeError('vault_evaluation_failed')
        return response.get('result', {}).get('value')

    def evaluate(self, task, expression):
        try:
            # Same synchronous JS turn checks the document and executes native JS.
            script = ('(() => {if(globalThis[' + json.dumps(self.marker) + '] !== '
                      + json.dumps(self.token) + ' || window.location.href !== ' + json.dumps(self.href)
                      + ') return {__vault_document_changed:true};'
                      + 'return (' + expression + ');})()')
            value = self._raw(script)
            if isinstance(value, dict) and value.get('__vault_document_changed'):
                return {'success': False, 'error_type': 'document_changed', 'error': 'Vault document changed; nothing written.'}
            return {'success': True, 'result': value}
        except Exception:
            return {'success': False, 'error_type': 'vault_transport_failed', 'error': 'Exact vault target evaluation failed.'}

    def evaluate_runtime(self, expression):
        result = self.evaluate(None, expression)
        # The native secret expression returns counts only. Discard every other
        # field, including hostile transport error text or unexpected page data.
        if not result.get('success'):
            return {'ok': False, 'error': 'Exact vault target/document changed or unavailable.'}
        value = result.get('result')
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
            if not isinstance(parsed, dict):
                raise ValueError()
            if parsed.get('refused') == 'origin_changed':
                safe = {'refused': 'origin_changed'}
            else:
                count = parsed.get('filled', 0)
                if type(count) is not int or not 0 <= count <= 1000:
                    raise ValueError()
                safe = {'filled': count}
            return {'ok': True, 'result': json.dumps(safe)}
        except Exception:
            return {'ok': False, 'error': 'Unexpected vault fill result; no retry.'}
