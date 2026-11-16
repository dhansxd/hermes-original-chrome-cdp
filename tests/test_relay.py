import concurrent.futures
from contextlib import contextmanager
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from websockets.sync.client import connect
from websockets.sync.server import serve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import relay


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.session = relay.ChromeSession(Path('/fixture'), 'Default')
        self.addCleanup(self.session.close)
        self.wire = Mock(closed=False)
        self.session.wire = self.wire
        self.session.context = 'original-profile'
        self.session.owned = {'owned'}
        self.client, self.other = Mock(), Mock()
        self.session.clients = {self.client: {'page-sid': 'owned'}, self.other: {}}
        self.targets = [self.info('manual'), self.info('owned')]
        def call(method, params=None, sid=None, **kw):
            if method == 'Target.getTargets':
                return {'targetInfos': list(self.targets)}
            if method == 'Target.createTarget':
                self.targets.append(self.info('new'))
                return {'targetId': 'new'}
            if method == 'Target.attachToTarget':
                return {'sessionId': 'new-sid'}
            if method == 'Target.closeTarget':
                self.targets[:] = [t for t in self.targets if t['targetId'] != params['targetId']]
                return {'success': True}
            if method == 'Browser.getWindowForTarget':
                return {'windowId': 'window-' + params['targetId']}
            return {'native': True}
        self.wire.call.side_effect = call

    def info(self, target, opener=None, context='original-profile'):
        return {'targetId': target, 'type': 'page', 'browserContextId': context,
                'url': 'https://fixture.invalid', 'openerId': opener}

    def command(self, method, params=None, sid=None):
        return self.session.command(self.client, method, params or {}, sid)

    def test_discovery_only_contains_owned_targets_and_popups(self):
        self.targets += [self.info('popup', 'owned'), self.info('foreign-popup', 'manual'),
                         self.info('other-profile', 'owned', 'other-profile')]
        self.assertEqual({t['targetId'] for t in self.command('Target.getTargets')['targetInfos']}, {'owned', 'popup'})

    def test_foreign_attach_close_activate_are_refused_before_forwarding(self):
        for method in ('Target.attachToTarget', 'Target.closeTarget', 'Target.activateTarget'):
            with self.assertRaisesRegex(RuntimeError, 'does not belong'):
                self.command(method, {'targetId': 'manual'})
            self.assertFalse(any(c.args[0] == method for c in self.wire.call.call_args_list))

    def test_page_commands_remain_native(self):
        params = {'expression': 'document.querySelector("widget").shadowRoot.innerHTML', 'returnByValue': True}
        self.assertEqual(self.command('Runtime.evaluate', params, 'page-sid'), {'native': True})
        self.wire.call.assert_called_with('Runtime.evaluate', params, 'page-sid', timeout=None)
        with self.assertRaisesRegex(RuntimeError, 'does not belong'):
            self.session.command(self.other, 'Runtime.evaluate', params, 'page-sid')

    def test_new_tabs_use_original_context_and_owned_windows(self):
        self.command('Target.createTarget', {'url': 'about:blank', 'newWindow': False, 'background': False})
        self.wire.call.assert_called_with('Target.createTarget', {
            'url': 'about:blank', 'newWindow': True, 'background': True, 'browserContextId': 'original-profile'})
        self.assertIn('new', self.session.owned)

    def profile_refusal(self):
        self.session.identity = {'pid': 42, 'started': 1, 'endpoint': 'ws://fixture'}
        self.session.seed_url = 'file:///fixture/unique-seed.html'
        original = self.wire.call.side_effect

        def call(method, params=None, sid=None, **kwargs):
            if method == 'Target.createTarget':
                raise relay.CDPError({'code': -32000,
                    'message': 'Failed to find browser context with id original-profile'})
            if method == 'Page.navigate':
                next(t for t in self.targets if t['targetId'] == 'native-new')['url'] = params['url']
            return original(method, params, sid, **kwargs)

        self.wire.call.side_effect = call

        def launch(*args):
            self.targets.append(dict(self.info('native-new'), url=self.session.seed_url))
        return launch

    def test_context_refusal_opens_exact_profile_window_and_owns_it(self):
        launch = self.profile_refusal()
        with patch('relay.startup.endpoint_identity', return_value=self.session.identity), \
                patch('relay.startup.notify_running_chrome', side_effect=launch) as notify:
            result = self.command('Target.createTarget', {'url': 'https://fixture.invalid/requested'})
        self.assertEqual(result, {'targetId': 'native-new'})
        self.assertIn('native-new', self.session.owned)
        arguments = notify.call_args.args[2]
        self.assertIn('--profile-directory=Default', arguments)
        self.assertEqual(arguments[-2:], ['--new-window', self.session.seed_url])
        self.assertEqual(notify.call_args.args[1], (42, 1))
        self.assertEqual(next(t for t in self.targets if t['targetId'] == 'native-new')['url'],
                         'https://fixture.invalid/requested')

    def test_other_native_errors_do_not_launch_profile_windows(self):
        self.profile_refusal()
        original = self.wire.call.side_effect

        def call(method, *args, **kwargs):
            if method == 'Target.createTarget':
                raise relay.CDPError({'code': -32000, 'message': 'Different error'})
            return original(method, *args, **kwargs)

        self.wire.call.side_effect = call
        with patch('relay.startup.notify_running_chrome') as notify:
            with self.assertRaisesRegex(relay.CDPError, 'Different error'):
                self.command('Target.createTarget')
        notify.assert_not_called()

    def test_changed_browser_identity_is_rejected_before_window_launch(self):
        self.profile_refusal()
        with patch('relay.startup.endpoint_identity', return_value={'pid': 99}), \
                patch('relay.startup.notify_running_chrome') as notify:
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                self.command('Target.createTarget')
        notify.assert_not_called()

    def test_pending_profile_window_is_discovered_without_another_create(self):
        self.profile_refusal()
        self.targets.append(dict(self.info('pending'), url=self.session.seed_url))
        with patch('relay.startup.notify_running_chrome') as notify:
            with self.assertRaisesRegex(RuntimeError, 'original pending'):
                self.command('Target.createTarget')
        self.assertIn('pending', self.session.owned)
        notify.assert_not_called()
        self.assertFalse(any(c.args[0] == 'Target.createTarget' for c in self.wire.call.call_args_list))

    def test_unacknowledged_profile_window_is_retained_for_cleanup(self):
        launch = self.profile_refusal()

        def uncertain(*args):
            launch(*args)
            raise RuntimeError('Acknowledgement lost')

        with patch('relay.startup.endpoint_identity', return_value=self.session.identity), \
                patch('relay.startup.notify_running_chrome', side_effect=uncertain) as notify:
            with self.assertRaisesRegex(RuntimeError, 'Acknowledgement lost'):
                self.command('Target.createTarget')
            self.assertIn('native-new', {t['targetId'] for t in self.command('Target.getTargets')['targetInfos']})
            with self.assertRaisesRegex(RuntimeError, 'original pending'):
                self.command('Target.createTarget')
        self.assertEqual(notify.call_count, 1)
        self.assertTrue(self.session.close())
        self.assertEqual([t['targetId'] for t in self.targets], ['manual'])

    def test_different_profile_window_is_owned_for_cleanup_before_rejection(self):
        self.profile_refusal()

        def different(*args):
            self.targets.append(dict(self.info('native-new', context='different-profile'), url=self.session.seed_url))

        with patch('relay.startup.endpoint_identity', return_value=self.session.identity), \
                patch('relay.startup.notify_running_chrome', side_effect=different):
            with self.assertRaisesRegex(RuntimeError, 'different or ambiguous'):
                self.command('Target.createTarget')
        self.assertIn('native-new', self.session.owned)
        self.assertFalse(any(c.args[0] == 'Page.navigate' for c in self.wire.call.call_args_list))

    def test_profile_window_bounds_and_state_are_applied_to_the_owned_window(self):
        launch = self.profile_refusal()
        with patch('relay.startup.endpoint_identity', return_value=self.session.identity), \
                patch('relay.startup.notify_running_chrome', side_effect=launch):
            self.command('Target.createTarget', {'url': 'about:blank', 'width': 800,
                                                'height': 600, 'windowState': 'minimized'})
        bounds = [c.args[1] for c in self.wire.call.call_args_list if c.args[0] == 'Browser.setWindowBounds']
        self.assertEqual(bounds, [
            {'windowId': 'window-native-new', 'bounds': {'width': 800, 'height': 600}},
            {'windowId': 'window-native-new', 'bounds': {'windowState': 'minimized'}}])

    def test_profile_replacement_is_rejected_before_native_window_creation(self):
        self.profile_refusal()
        self.session.profile_identity = ('original',)
        with patch('relay.startup.endpoint_identity', return_value=self.session.identity), \
                patch('relay.get_profile', return_value=Mock(identity=('replacement',))), \
                patch('relay.startup.notify_running_chrome') as notify:
            with self.assertRaisesRegex(RuntimeError, 'profile was replaced'):
                self.command('Target.createTarget')
        notify.assert_not_called()

    def test_special_target_modes_preserve_the_original_protocol_error(self):
        self.profile_refusal()
        with patch('relay.startup.notify_running_chrome') as notify:
            for field in ('hidden', 'forTab', 'enableBeginFrameControl'):
                with self.assertRaises(relay.CDPError):
                    self.command('Target.createTarget', {field: True})
        notify.assert_not_called()

    def test_owned_window_activation_preserves_manual_focus(self):
        self.assertEqual(self.command('Target.activateTarget', {'targetId': 'owned'}), {})
        self.assertEqual(self.command('Page.bringToFront', sid='page-sid'), {})
        forwarded = [call.args[0] for call in self.wire.call.call_args_list]
        self.assertNotIn('Target.activateTarget', forwarded)
        self.assertNotIn('Page.bringToFront', forwarded)

    def test_create_queued_before_cleanup_cannot_leave_a_late_window(self):
        entered, release = threading.Event(), threading.Event()
        original_guard = relay.consent_guard

        @contextmanager
        def delayed_guard(*args, **kwargs):
            if threading.current_thread() is creator:
                entered.set()
                self.assertTrue(release.wait(3))
            with original_guard(*args, **kwargs):
                yield

        errors = []

        def create():
            try:
                self.command('Target.createTarget', {'url': 'about:blank'})
            except RuntimeError as error:
                errors.append(str(error))

        creator = threading.Thread(target=create)
        try:
            with patch('relay.consent_guard', side_effect=delayed_guard):
                creator.start()
                self.assertTrue(entered.wait(3))
                self.assertTrue(self.session.close())
                release.set()
                creator.join(3)
                self.assertFalse(creator.is_alive())
            self.assertEqual(errors, ['Browser session is closed.'])
            self.assertEqual([target['targetId'] for target in self.targets], ['manual'])
            self.assertFalse(self.session.owned)
        finally:
            release.set()
            creator.join(3)

    def test_cleanup_includes_window_creation_already_in_flight(self):
        entered, release = threading.Event(), threading.Event()
        original_call = self.wire.call.side_effect
        results = {}

        def call(method, *args, **kwargs):
            if method == 'Target.createTarget':
                entered.set()
                self.assertTrue(release.wait(3))
            return original_call(method, *args, **kwargs)

        creator = threading.Thread(target=lambda: results.update(created=self.command('Target.createTarget')))
        closer = threading.Thread(target=lambda: results.update(closed=self.session.close()))
        try:
            self.wire.call.side_effect = call
            creator.start()
            self.assertTrue(entered.wait(3))
            closer.start()
            deadline = time.monotonic() + 2
            while not self.session.closed and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(self.session.closed)
            release.set()
            creator.join(3)
            closer.join(3)
            self.assertFalse(creator.is_alive() or closer.is_alive())
            self.assertEqual(results, {'created': {'targetId': 'new'}, 'closed': True})
            self.assertEqual([target['targetId'] for target in self.targets], ['manual'])
            self.assertFalse(self.session.owned)
        finally:
            release.set()
            creator.join(3)
            if closer.ident is not None:
                closer.join(3)

    def test_closed_endpoint_refuses_late_client_registration(self):
        self.assertTrue(self.session.close())
        late = Mock()
        late.request.path = self.session.path
        self.session._client(late)
        late.close.assert_called_once_with(1001, 'Browser session is closed.')
        self.assertNotIn(late, self.session.clients)

    def test_browser_wide_shutdown_and_foreign_windows_are_refused(self):
        for method in ('Browser.close', 'Browser.setDownloadBehavior', 'Network.clearBrowserCookies'):
            with self.assertRaises(RuntimeError):
                self.command(method, sid='page-sid')
        with self.assertRaises(RuntimeError):
            self.command('Browser.setWindowBounds', {'windowId': 'manual-window'})

    def test_frame_auto_attachment_is_owned_and_events_are_private(self):
        event = {'method': 'Target.attachedToTarget', 'sessionId': 'page-sid',
                 'params': {'sessionId': 'frame-sid', 'targetInfo': {'targetId': 'frame', 'type': 'iframe'}}}
        self.session._event(event)
        self.assertIn('frame-sid', self.session.clients[self.client])
        self.client.send.assert_called_once()
        self.other.send.assert_not_called()
        self.command('Runtime.evaluate', {'expression': 'document.title'}, 'frame-sid')

    def test_cleanup_preserves_manual_target_and_never_quits_chrome(self):
        self.targets.append(self.info('popup', 'owned'))
        self.assertTrue(self.session.close())
        self.assertEqual([t['targetId'] for t in self.targets], ['manual'])
        self.assertFalse(any(c.args[0] == 'Browser.close' for c in self.wire.call.call_args_list))

    def test_start_failure_stays_a_cdp_error_on_the_same_endpoint(self):
        session = relay.ChromeSession(Path('/fixture'), 'Default')
        self.addCleanup(session.close)
        with patch('relay.startup.launch', side_effect=RuntimeError('fixture startup failure')) as launch:
            with connect(session.url, proxy=None) as ws:
                for identifier in (1, 2):
                    ws.send(json.dumps({'id': identifier, 'method': 'Target.getTargets'}))
                    self.assertIn('fixture startup failure', json.loads(ws.recv())['error']['message'])
            self.assertEqual(launch.call_count, 1)

    def test_rejected_handshake_cleanup_is_not_falsely_reported_as_complete(self):
        session = relay.ChromeSession(Path('/fixture'), 'Default')
        session.seed_url = 'file:///exact-session-seed.html'
        self.assertFalse(session.close())
        self.assertFalse(session.close())
        seed = dict(self.info('failed-start'), url=session.seed_url)
        self.targets.append(seed)
        self.assertTrue(session.close(cleanup_wire=self.wire))
        self.assertEqual({t['targetId'] for t in self.targets}, {'manual', 'owned'})

    def test_failed_start_without_cdp_closes_only_its_exact_seed_tab(self):
        session=relay.ChromeSession(Path('/fixture'),'Default')
        self.addCleanup(session.close)
        session.identity={'pid':42,'started':1}
        session.seed_url='file:///fixture/owned-start.html'
        session.seed_title='Hermes browser session fixture'
        with patch('relay.startup.process_alive',return_value=True), \
                patch('relay.startup.close_seed_tab',return_value=True) as close:
            self.assertTrue(session.close())
        close.assert_called_once_with(session.data,session.identity,
                                      'file:///fixture/owned-start.html',session.seed_title)

    def test_unacknowledged_launch_retains_verified_identity_for_exact_seed_cleanup(self):
        session = relay.ChromeSession(Path('/fixture'), 'Default')
        self.addCleanup(session.close)
        identity = {'pid': 42, 'started': 1, 'endpoint': 'ws://fixture'}
        with patch('relay.startup.launch', side_effect=RuntimeError('unconfirmed startup')), \
                patch('relay.startup.endpoint_identity', return_value=identity):
            with self.assertRaisesRegex(RuntimeError, 'unconfirmed startup'):
                session._start()
        self.assertEqual(session.identity, identity)
        with patch('relay.startup.process_alive', return_value=True), \
                patch('relay.startup.close_seed_tab', return_value=True) as close:
            self.assertTrue(session.close())
        self.assertEqual(close.call_args.args[1], identity)
        self.assertEqual(close.call_args.args[3], session.seed_title)

    def test_disconnected_browser_cleanup_requires_process_exit_proof(self):
        self.session.identity = {'pid': 42, 'started': 1}
        self.wire.closed = True
        with patch('relay.startup.process_alive', return_value=True):
            self.assertFalse(self.session.close())
        with patch('relay.startup.process_alive', return_value=False):
            self.assertTrue(self.session.close())

    def test_native_seed_cleanup_failure_still_stops_local_endpoint(self):
        session = relay.ChromeSession(Path('/fixture'), 'Default')
        self.addCleanup(session.close)
        session.identity = {'pid': 42, 'started': 1}
        session.seed_url = 'file:///fixture/owned-start.html'
        with patch('relay.startup.process_alive', return_value=True), \
                patch('relay.startup.close_seed_tab', side_effect=RuntimeError('fixture failure')):
            self.assertFalse(session.close())
        self.assertFalse(session.thread.is_alive())
        self.assertEqual(session.seed_url, 'file:///fixture/owned-start.html')
        with patch('relay.startup.process_alive', return_value=False):
            self.assertTrue(session.close())

    def test_client_close_failure_does_not_leave_endpoint_running(self):
        self.client.close.side_effect = RuntimeError('fixture failure')
        self.assertFalse(self.session.close())
        self.assertFalse(self.session.thread.is_alive())
        self.other.close.assert_called_once()
        self.wire.close.assert_called_once()
        self.client.close.side_effect = None
        self.assertTrue(self.session.close())


class TransportTests(unittest.TestCase):
    def test_slow_request_does_not_block_another_response_or_event(self):
        first = threading.Event()
        def handler(ws):
            requests = [json.loads(ws.recv()), json.loads(ws.recv())]
            ws.send(json.dumps({'method': 'Page.testEvent', 'params': {}}))
            for request in reversed(requests):
                ws.send(json.dumps({'id': request['id'], 'result': {'method': request['method']}}))
            first.wait(2)
        server = serve(handler, '127.0.0.1', 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        events = []
        wire = relay.Connection(connect(f'ws://127.0.0.1:{server.socket.getsockname()[1]}', proxy=None), events.append)
        try:
            with concurrent.futures.ThreadPoolExecutor() as pool:
                a, b = [pool.submit(wire.call, method) for method in ('Runtime.evaluate', 'Page.handleJavaScriptDialog')]
                self.assertEqual(a.result()['method'], 'Runtime.evaluate')
                self.assertEqual(b.result()['method'], 'Page.handleJavaScriptDialog')
            self.assertEqual(len(events), 1)
        finally:
            first.set()
            wire.close()
            server.shutdown()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
