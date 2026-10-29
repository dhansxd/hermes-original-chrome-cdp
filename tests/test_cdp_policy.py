"""Offline policy tests. No sockets, browser, native UI, or profile data."""
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binding import BoundBrowser
from cdp_policy import validate_cdp, validate_navigation_url
from observer import ScopedObserver


class FakeWire:
    def __init__(self):
        self.calls = []
        self.events = []
        self.dialogs = {}
        self.event_gaps = {}
        self.detached_sessions = set()
        self.event_overflow = False
        self.context = 'ctx'

    def __call__(self, method, params=None, session=None):
        self.calls.append((method, params, session))
        if method == 'Target.getTargets':
            return {'targetInfos': [{'targetId': 'owned', 'browserContextId': self.context, 'type': 'page'}]}
        if method == 'Browser.getWindowForTarget':
            return {'windowId': 7}
        if method == 'Target.attachToTarget':
            return {'sessionId': 'held'}
        if method == 'Target.createTarget':
            return {'targetId': 'created'}
        if method == 'Browser.getVersion':
            return {'userAgent': 'fixture'}
        return {}

    def pump(self):
        pass

    def close(self):
        pass


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.state = {'current': 'owned', 'context': 'ctx', 'owned': {'owned': 7}, 'verified': True}
        self.wire = FakeWire()
        self.browser = BoundBrowser(self.wire, self.state)
        self.browser.sessions = {'owned': 'held'}
        self.native = Mock(bindings={7: 'native'})
        for name, value in [('Wire', self.wire), ('NativeDialogs', self.native)]:
            patched = patch('observer.' + name, return_value=value)
            patched.start()
            self.addCleanup(patched.stop)
        guard = patch('observer.consent_guard', return_value=nullcontext())
        guard.start()
        self.addCleanup(guard.stop)
        self.observer = ScopedObserver('fixture', '/fixture/Default')
        self.observer.sessions = {'owned': 'held'}
        self.addCleanup(self.observer.close)

    def assert_rejected_without_effects(self, method, params=None, session=None):
        params = {} if params is None else params
        self.wire.calls.clear()
        with self.assertRaises(RuntimeError):
            self.browser.cdp(method, session_id=session, **params)
        self.assertEqual(self.wire.calls, [])
        with self.assertRaises(RuntimeError):
            self.observer.request({'method': method, 'params': params, 'session': session}, self.state)
        self.assertEqual(self.wire.calls, [])
        self.native.scan.assert_not_called()

    def test_cookie_storage_browserwide_and_unknown_methods_fail_closed(self):
        for method in (
            'Network.getCookies', 'Network.getAllCookies', 'Network.setCookie',
            'Network.setCookies', 'Network.deleteCookies', 'Network.clearBrowserCookies',
            'Network.clearBrowserCache', 'Network.getResponseBody', 'Network.futureMethod',
            'Storage.getCookies', 'Storage.setCookies', 'Storage.clearDataForOrigin',
            'DOMStorage.getDOMStorageItems', 'IndexedDB.requestData',
            'Browser.close', 'Browser.crash', 'Browser.setDownloadBehavior',
            'Browser.setPermission', 'Browser.resetPermissions', 'Browser.setWindowBounds',
            'Target.createBrowserContext', 'Target.disposeBrowserContext',
            'Target.setAutoAttach', 'Target.autoAttachRelated', 'Target.detachFromTarget',
            'Fetch.enable', 'Debugger.enable', 'DOM.setFileInputFiles', 'Page.disable',
        ):
            with self.subTest(method=method):
                self.assert_rejected_without_effects(method)

    def test_target_and_session_routing_cannot_reach_another_entry(self):
        self.observer.sessions['foreign'] = 'other-session'
        for method in ('Target.closeTarget', 'Target.activateTarget', 'Target.attachToTarget',
                       'Target.getTargetInfo', 'Browser.getWindowForTarget'):
            with self.subTest(method=method):
                self.assert_rejected_without_effects(method, {'targetId': 'foreign'})
        for method, params in [('Runtime.evaluate', {'expression': 'document.title'}),
                               ('Page.navigate', {'url': 'https://example.test'})]:
            self.assert_rejected_without_effects(method, params, 'other-session')
        self.assert_rejected_without_effects('Browser.getVersion', session='held')

    def test_runtime_context_and_transport_injection_parameters_are_rejected(self):
        for key in ('contextId', 'uniqueContextId', 'objectId', 'sessionId', 'targetId'):
            with self.subTest(key=key):
                self.assert_rejected_without_effects('Runtime.evaluate', {'expression': 'document.title', key: 'foreign'}, 'held')

    def test_transport_requires_explicit_target_and_held_page_session(self):
        for method in ('Target.closeTarget', 'Target.activateTarget', 'Target.attachToTarget',
                       'Target.getTargetInfo', 'Browser.getWindowForTarget'):
            with self.subTest(method=method), self.assertRaisesRegex(RuntimeError, 'cdp_target_required'):
                self.observer.request({'method': method}, self.state)
        with self.assertRaisesRegex(RuntimeError, 'session_not_owned'):
            self.observer.request({'method': 'Runtime.evaluate', 'params': {'expression': 'document.title'}}, self.state)
        self.assertEqual(self.wire.calls, [])

    def test_creation_has_exact_owned_context_and_background_window_shape(self):
        self.assert_rejected_without_effects('Target.createTarget', {'browserContextId': 'foreign'})
        self.assert_rejected_without_effects('Target.createTarget', {'newWindow': False})
        self.assert_rejected_without_effects('Target.createTarget', {'forTab': True})
        for params in ({'url': 'https://example.test'}, {'url': 'about:blank'},
                       {'url': 'about:blank', 'browserContextId': 'ctx', 'newWindow': True, 'background': False}):
            with self.assertRaisesRegex(RuntimeError, 'cdp_creation_not_owned'):
                self.observer.request({'method': 'Target.createTarget', 'params': params}, self.state)
        self.assertEqual(self.wire.calls, [])
        params = {'url': 'about:blank', 'browserContextId': 'ctx', 'newWindow': True, 'background': True}
        self.observer.request({'method': 'Target.createTarget', 'params': params}, self.state)
        self.assertEqual(self.wire.calls[-1], ('Target.createTarget', params, None))

    def test_valid_gui_helpers_reach_only_owned_page(self):
        for method, params in (
            ('Runtime.evaluate', {'expression': 'document.title', 'returnByValue': True, 'awaitPromise': True}),
            ('Page.navigate', {'url': 'https://example.test/path'}),
            ('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False}),
            ('Input.insertText', {'text': 'hello'}),
            ('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': 10, 'y': 20, 'button': 'left', 'clickCount': 1}),
        ):
            with self.subTest(method=method):
                self.browser.cdp(method, **params)
                self.assertEqual(self.wire.calls[-1], (method, params, 'held'))
                self.observer.request({'method': method, 'params': params, 'session': 'held'}, self.state)
                self.assertEqual(self.wire.calls[-1], (method, params, 'held'))
        self.browser.cdp('Browser.getVersion')
        self.assertEqual(self.wire.calls[-1], ('Browser.getVersion', {}, None))

    def test_live_context_change_rejected_before_watchers_or_native_probe(self):
        self.wire.context = 'different-profile'
        self.native.bindings = {}
        with self.assertRaisesRegex(RuntimeError, 'binding_unavailable'):
            self.observer.request({'method': 'Runtime.evaluate', 'params': {'expression': 'document.title'}, 'session': 'held'}, self.state)
        self.assertEqual([c[0] for c in self.wire.calls], ['Target.getTargets'])
        self.native.scan.assert_not_called()

    def test_privileged_profile_verification_is_not_general_navigation(self):
        for url in ('chrome://version/', 'chrome://settings', 'file:///fixture',
                    'javascript:document.cookie', 'data:text/html,hello',
                    ' https://example.test', 'https://example.test:invalid'):
            with self.subTest(url=url):
                self.assert_rejected_without_effects('Page.navigate', {'url': url}, 'held')
                with self.assertRaisesRegex(RuntimeError, 'cdp_navigation_not_allowed'):
                    self.browser.create(url)
                self.assertEqual(self.wire.calls, [])
        self.state['verified'] = False
        self.browser.cdp('Page.navigate', url='chrome://version/')
        self.observer.request({'method': 'Page.navigate', 'params': {'url': 'chrome://version/'}, 'session': 'held'}, self.state)
        self.assertEqual(self.wire.calls[-1], ('Page.navigate', {'url': 'chrome://version/'}, 'held'))

    def test_malformed_requests_fail_before_wire(self):
        for params in ([], '', False, 0):
            with self.subTest(params=params), self.assertRaisesRegex(RuntimeError, 'cdp_request_invalid'):
                self.observer.request({'method': 'Target.getTargets', 'params': params}, self.state)
        with self.assertRaisesRegex(RuntimeError, 'cdp_request_invalid'):
            validate_cdp('Target.getTargets', {}, [])
        self.assertEqual(self.wire.calls, [])

    def test_browser_exit_requires_parent_disposable_empty_scope(self):
        self.assert_rejected_without_effects('Browser.close')
        for state in ({'owned': {'owned': 7}}, {'owned': {}, 'unresolved_creation': True}):
            with self.assertRaisesRegex(RuntimeError, 'browser_close_not_authorized'):
                self.observer.close_disposable_browser(state)
        self.observer.entries = [{'state': {'owned': {'another': 9}}}]
        with self.assertRaisesRegex(RuntimeError, 'browser_close_not_authorized'):
            self.observer.close_disposable_browser({'owned': {}})
        self.observer.entries = []
        self.observer.data_root = Path.home() / 'Library/Application Support/Google/Chrome'
        with self.assertRaisesRegex(RuntimeError, 'browser_close_not_authorized'):
            self.observer.close_disposable_browser({'owned': {}})
        self.assertEqual(self.wire.calls, [])
        self.observer.data_root = Path('/fixture')
        self.observer.close_disposable_browser({'owned': {}})
        self.assertEqual(self.wire.calls, [('Browser.close', {}, None)])


if __name__ == '__main__':
    unittest.main()
