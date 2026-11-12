import concurrent.futures
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
        self.command('Target.createTarget', {'url': 'about:blank'})
        self.wire.call.assert_called_with('Target.createTarget', {
            'url': 'about:blank', 'newWindow': True, 'background': True, 'browserContextId': 'original-profile'})
        self.assertIn('new', self.session.owned)

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
        close.assert_called_once_with(session.data,session.identity,session.seed_url,session.seed_title)

    def test_disconnected_browser_cleanup_requires_process_exit_proof(self):
        self.session.identity = {'pid': 42, 'started': 1}
        self.wire.closed = True
        with patch('relay.startup.process_alive', return_value=True):
            self.assertFalse(self.session.close())
        with patch('relay.startup.process_alive', return_value=False):
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
