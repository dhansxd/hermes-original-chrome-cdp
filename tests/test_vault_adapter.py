"""Synthetic-only native vault adapter contract tests; never opens a real vault."""
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock

try:
    from vault_adapter import invoke
except ImportError:
    invoke = None


class VaultAdapterTests(unittest.TestCase):
    def test_missing_binding_refuses_before_native_handler(self):
        self.assertIsNotNone(invoke, 'exact-target adapter is missing')
        provider = SimpleNamespace(lock=threading.RLock(), states={}, last_sessions={})
        def forbidden(*a, **kw):
            self.fail('unbound native handler called')
        result = json.loads(invoke(provider, forbidden, {}, {'task_id':'test'}))
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'vault_binding_unavailable')


class SyntheticWire:
    """Inert CDP fixture: two same-origin targets, no browser or real secrets."""
    def __init__(self, *a):
        self.calls = []
        self.changed = False
        self.secret_failure = False
        self.href = 'https://synthetic.invalid/login'
        self.closed = False
        self.otp = False
        self.writes = 0
    def close(self):
        self.closed = True
    def __call__(self, method, params=None, session=None):
        params = params or {}
        self.calls.append((method, session))  # NEVER retain expression/secret text.
        if method == 'Target.getTargets':
            return {'targetInfos':[{'targetId':t, 'type':'page', 'browserContextId':'context', 'url':self.href} for t in ('manual', 'agent')]}
        if method == 'Browser.getWindowForTarget':
            return {'windowId': 2 if params['targetId']=='agent' else 1}
        if method == 'Target.attachToTarget':
            return {'sessionId':params['targetId']}
        if method == 'Runtime.evaluate':
            if session != 'agent':
                raise AssertionError('manual target touched')
            expression = params['expression']
            if expression.startswith('Object.defineProperty'):
                value = True
            elif self.changed:
                value = {'__vault_document_changed':True}
            elif expression.endswith('return (true);})()'):
                value = True
            elif expression == 'window.location.href' or 'return (window.location.href);' in expression:
                value = self.href
            elif 'document.querySelectorAll' in expression and 'expectedOrigin' not in expression and 'filled' not in expression:
                value = [{'index':0, 'type':'text' if self.otp else 'password', 'autocomplete':'one-time-code' if self.otp else 'current-password', 'name':'otp' if self.otp else 'password', 'label':'Code' if self.otp else 'Password'}]
            else:
                self.writes += 1
                if self.secret_failure:
                    raise RuntimeError(self.synthetic_secret)
                value = json.dumps({'filled':1, 'unexpected':'discard me'})
            return {'result':{'value':value}}
        raise AssertionError('unexpected CDP method')


class NativeSyntheticTests(unittest.TestCase):
    def setUp(self):
        import vault_adapter
        from tools import browser_vault_tool as native
        self.native = native
        self.wire = SyntheticWire()
        self.provider = SimpleNamespace(lock=threading.RLock(), data='/synthetic-empty-root',
            states={('synthetic-task','named'):{'endpoint':'ws://synthetic.invalid', 'state':{
                'current':'agent', 'context':'context', 'owned':{'agent':2}, 'baseline':['manual']}}},
            last_sessions={'synthetic-task':'named'})
        self.meta = SimpleNamespace(kind='login', origin='https://synthetic.invalid',
            allowed_origins=['https://synthetic.invalid'], has_otp=False, label='SYNTHETIC', id='synthetic-handle')
        self.fixture_secret = 'SYNTHETIC-ONLY-' + __import__('secrets').token_hex(16)
        self.wire.synthetic_secret = self.fixture_secret
        self.backend = SimpleNamespace(name='synthetic', needs_unlock=False,
            get_meta=lambda h:self.meta, resolve_password=lambda h:self.fixture_secret)
        self.patches = [patch.object(vault_adapter, 'Wire', return_value=self.wire),
            patch('agent.vault_backends.backend_for_handle', return_value=self.backend),
            patch.object(native, '_fenced_page_op', side_effect=lambda tid, fn:fn()),
            patch.object(native, '_bot_desktop_browser_session', return_value=False)]
        for p in self.patches:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])
        self.hold_observer()
    def call(self, handler=None, args=None):
        raw = invoke(self.provider, handler or self.native._handle_vault,
                     args or {'action':'fill','handle':'synthetic-handle'}, {'task_id':'synthetic-task'})
        self.assertNotIn(self.fixture_secret, raw)
        return json.loads(raw)
    def hold_observer(self):
        from observer import ScopedObserver
        with patch('observer.Wire', return_value=self.wire):
            observer = ScopedObserver('ws://synthetic.invalid', '/synthetic-empty-root/Default')
        observer.sessions = {'agent':'agent'}
        observer.closed = False
        self.wire.pump = lambda:None
        self.wire.events = []
        self.wire.dialogs = {}
        self.wire.on_event = lambda event:None
        self.provider.states[('synthetic-task','named')]['observer'] = observer
        return observer

    def test_registered_fill_reuses_valid_selected_observer(self):
        import os, tempfile
        from pathlib import Path
        import plugin
        from hermes_cli.plugins import PluginContext, PluginManager
        from hermes_cli.plugins_manifest import PluginManifest
        from tools.registry import registry
        observer = self.hold_observer()
        provider = plugin.ChromeProvider(data='/synthetic-empty-root')
        provider.states = self.provider.states
        provider.last_sessions = self.provider.last_sessions
        self.provider = provider
        self.provider.unload = lambda:None
        callback = self.wire.on_event
        with tempfile.TemporaryDirectory(dir=Path.home()/'.hermes/cache/scratch') as home:
            Path(home,'config.yaml').write_text('browser:\n  cloud_provider: original-chrome-default\n')
            with patch.dict(os.environ,HERMES_HOME=home), patch.object(plugin,'ChromeProvider',return_value=self.provider):
                manager = PluginManager(scope_key=home)
                ctx = PluginContext(PluginManifest(name=plugin.NAME,source='user',capabilities=['tools.override']),manager)
                # Registration uses the real scoped registry and capability grant.
                Path(home,'config.yaml').write_text('browser:\n  cloud_provider: original-chrome-default\nplugins:\n  entries:\n    original-chrome-default:\n      granted_capabilities: [tools.override]\n')
                plugin.register(ctx)
                try:
                    raw = registry.dispatch('browser_vault',{'action':'fill','handle':'synthetic-handle'},task_id='synthetic-task',scope=home)
                    self.assertNotIn(self.fixture_secret,raw)
                    result = json.loads(raw)
                    self.assertTrue(result['success'],result)
                    self.assertEqual(result['filled_fields'],1)
                    self.assertIs(self.wire.on_event,callback)
                    self.assertFalse(observer.closed)
                    self.assertFalse(self.wire.closed)
                    self.assertFalse(any(m=='Target.attachToTarget' for m,s in self.wire.calls))
                finally:
                    # Dispose tool registrations without running provider teardown.
                    manager.unload()

    def test_held_transport_never_opens_peer_or_runs_worker(self):
        import vault_adapter, plugin
        with patch.object(vault_adapter,'Wire',side_effect=AssertionError('new peer')), patch.object(plugin.ChromeProvider,'_worker',side_effect=AssertionError('worker secret path')):
            self.assertTrue(self.call()['success'])
        self.assertFalse(any(m in ('Target.attachToTarget','Target.detachFromTarget') for m,s in self.wire.calls))

    def test_closed_observer_refuses_before_secret_resolution(self):
        self.provider.states[('synthetic-task','named')]['observer'].closed = True
        self.backend.resolve_password = Mock(side_effect=AssertionError('secret resolution'))
        self.assertFalse(self.call()['success'])
        self.assertEqual(self.wire.calls,[])
        self.backend.resolve_password.assert_not_called()

    def test_missing_selected_attachment_refuses_before_secret_resolution(self):
        self.provider.states[('synthetic-task','named')]['observer'].sessions = {'other':'other'}
        self.backend.resolve_password = Mock(side_effect=AssertionError('secret resolution'))
        self.assertFalse(self.call()['success'])
        self.assertEqual(self.wire.calls,[])
        self.backend.resolve_password.assert_not_called()

    def test_other_held_session_does_not_change_selected_target(self):
        other = SimpleNamespace(closed=False,borrow=lambda state:self.fail('other observer borrowed'))
        self.provider.states[('other-task','named')] = {'observer':other}
        self.assertTrue(self.call()['success'])
        self.assertFalse(any(m=='Runtime.evaluate' and s!='agent' for m,s in self.wire.calls))

    def test_no_selected_observer_never_borrows_other_entry(self):
        entry = self.provider.states[('synthetic-task','named')]
        self.provider.states[('other-task','named')] = dict(entry)
        entry.pop('observer')
        self.backend.resolve_password = Mock(side_effect=AssertionError('secret resolution'))
        self.assertEqual(self.call()['error_type'],'vault_binding_unavailable')
        self.assertEqual(self.wire.calls,[])
        self.backend.resolve_password.assert_not_called()

    def test_window_or_context_change_refuses_before_secret_resolution(self):
        self.backend.resolve_password = Mock(side_effect=AssertionError('secret resolution'))
        state = self.provider.states[('synthetic-task','named')]['state']
        for key,value in [('owned',{'agent':99}),('context','other-context')]:
            old = state[key];state[key] = value
            self.assertFalse(self.call()['success'])
            self.assertEqual(self.wire.writes,0)
            self.backend.resolve_password.assert_not_called()
            state[key] = old

    def test_detached_observer_refuses_before_secret_resolution(self):
        observer = self.provider.states[('synthetic-task','named')]['observer']
        self.wire.events = [{'method':'Target.detachedFromTarget','params':{'sessionId':'agent'}}]
        self.backend.resolve_password = Mock(side_effect=AssertionError('secret resolution'))
        self.assertFalse(self.call()['success'])
        self.assertTrue(observer.closed)
        self.assertFalse(any(m=='Runtime.evaluate' for m,s in self.wire.calls))
        self.backend.resolve_password.assert_not_called()

    def test_callback_and_events_preserved_after_secret_exception(self):
        self.wire.secret_failure = True
        callback = self.wire.on_event
        events = self.wire.events
        self.assertFalse(self.call()['success'])
        self.assertIs(self.wire.on_event,callback)
        self.assertIs(self.wire.events,events)
        self.assertEqual(self.provider.states[('synthetic-task','named')]['observer'].sessions,{'agent':'agent'})
        self.assertFalse(self.wire.closed)

    def test_native_fill_only_touches_selected_same_origin_target(self):
        result = self.call()
        self.assertTrue(result['success'], result)
        self.assertEqual(result['filled_fields'], 1)
        self.assertFalse(self.wire.closed)
        self.assertNotIn(('Runtime.evaluate','manual'), self.wire.calls)
    def test_wrong_origin_refuses_before_secret_resolution(self):
        self.wire.href = 'https://other-synthetic.invalid/'
        def forbidden(h):
            self.fail('secret resolved for wrong origin')
        self.backend.resolve_password = forbidden
        self.assertEqual(self.call()['error_type'], 'origin_mismatch')
        self.assertEqual(self.wire.writes, 0)
    def test_uncertain_session_refuses_before_connect(self):
        self.provider.states[('synthetic-task','named')]['uncertain'] = True
        self.assertEqual(self.call()['error_type'], 'vault_binding_unavailable')
        self.assertEqual(self.wire.calls, [])
    def test_payment_decline_does_not_resolve_secret(self):
        self.meta.kind = 'payment'
        self.backend.resolve_secret = lambda h:self.fail('payment secret resolved')
        with patch.object(self.native, '_confirm_payment_fill', return_value=False):
            self.assertEqual(self.call()['error_type'], 'payment_declined')
        self.assertEqual(self.wire.writes, 0)
    def test_lost_target_never_adopts_manual(self):
        self.provider.states[('synthetic-task','named')]['state']['current'] = 'missing'
        self.assertFalse(self.call()['success'])
        self.assertFalse(any(method == 'Runtime.evaluate' for method, session in self.wire.calls))
    def test_secret_response_discards_unexpected_fields(self):
        from vault_adapter import _Transport
        transport = _Transport.__new__(_Transport)
        transport.evaluate = lambda *a: {'success':True, 'result':json.dumps({'filled':1,'error':self.fixture_secret})}
        raw = json.dumps(transport.evaluate_runtime('synthetic expression'))
        self.assertNotIn(self.fixture_secret, raw)
        self.assertEqual(json.loads(json.loads(raw)['result']), {'filled':1})
    def test_transport_exception_cannot_echo_secret(self):
        self.wire.secret_failure = True
        self.assertFalse(self.call()['success'])
    def test_native_save_success_uses_prompt_and_immediate_fill(self):
        from agent.vault_backends import unlock
        answer = {'identifier':'synthetic-user','password':self.fixture_secret}
        with patch.object(unlock,'can_prompt_here',return_value=True), patch.object(unlock,'get_save_login_prompt_callback',return_value=lambda *a:answer), patch('agent.vault_store.get_vault_store',return_value=SimpleNamespace(add_item=lambda *a,**kw:self.meta)):
            result = self.call(self.native._handle_vault, {'action':'save_login','label':'SYNTHETIC'})
        self.assertTrue(result['success'])
        self.assertTrue(result['fill']['success'])
        self.assertEqual(answer,{})
    def test_navigation_during_code_prompt_refuses_write(self):
        from agent.vault_backends import unlock
        self.wire.otp = True
        def prompt(*a):
            self.wire.changed = True
            return self.fixture_secret
        with patch.object(unlock,'can_prompt_here',return_value=True), patch.object(unlock,'get_code_prompt_callback',return_value=prompt):
            self.assertFalse(self.call(self.native._handle_vault, {'action':'enter_code','handle':''})['success'])
        self.assertEqual(self.wire.writes, 0)
    def test_navigation_during_save_prompt_refuses_operation(self):
        from agent.vault_backends import unlock
        def prompt(*a):
            self.wire.changed = True
            return {'identifier':'synthetic-user','password':self.fixture_secret}
        with patch.object(unlock,'can_prompt_here',return_value=True), patch.object(unlock,'get_save_login_prompt_callback',return_value=prompt), patch('agent.vault_store.get_vault_store',return_value=SimpleNamespace(add_item=lambda *a,**kw:self.meta)):
            self.assertFalse(self.call(self.native._handle_vault, {'action':'save_login','label':'SYNTHETIC'})['success'])
        self.assertEqual(self.wire.writes, 0)
    def test_native_source_drift_refuses_without_invoking_handler(self):
        import vault_adapter
        with patch.object(vault_adapter, 'NATIVE_SHA256', 'not-this-version', create=True):
            self.assertFalse(self.call()['success'])
        self.assertEqual(self.wire.writes, 0)
    def test_native_code_success_reuses_redaction(self):
        from agent.vault_backends import unlock
        from agent.redact import redact_registered_vault_values
        self.wire.otp = True
        with patch.object(unlock,'can_prompt_here',return_value=True), patch.object(unlock,'get_code_prompt_callback',return_value=lambda *a:self.fixture_secret):
            self.assertTrue(self.call(self.native._handle_vault, {'action':'enter_code','handle':''})['success'])
        normalized_code = self.fixture_secret.replace('-', '')
        self.assertNotEqual(redact_registered_vault_values(normalized_code), normalized_code)
    def test_original_module_functions_stay_unchanged(self):
        before = {k:v for k,v in vars(self.native).items() if callable(v)}
        self.call()
        self.assertTrue(all(vars(self.native)[k] is v for k,v in before.items()))
    def test_native_save_exception_cannot_echo_prompt_secret(self):
        from agent.vault_backends import unlock
        answer = {'identifier':'synthetic-user','password':self.fixture_secret}
        def fail(*a, **kw):
            raise RuntimeError(self.fixture_secret)
        with patch.object(unlock,'can_prompt_here',return_value=True), patch.object(unlock,'get_save_login_prompt_callback',return_value=lambda *a:answer), patch('agent.vault_store.get_vault_store',return_value=SimpleNamespace(add_item=fail)):
            self.assertFalse(self.call(self.native._handle_vault, {'action':'save_login','label':'SYNTHETIC'})['success'])
        self.assertEqual(answer,{})


if __name__ == '__main__':
    unittest.main()
