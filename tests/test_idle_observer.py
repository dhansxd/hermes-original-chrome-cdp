"""Real loopback WebSocket regression: bounded queues must drain between tools."""
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from websockets.sync.client import connect
from websockets.sync.server import serve
from observer import ScopedObserver


class IdleObserverTests(unittest.TestCase):
    def test_idle_detach_releases_shared_autoattach_before_next_action(self):
        from unittest.mock import Mock
        wire = Mock(); wire.events = []; wire.dialogs = {}; wire.event_overflow = False; wire.event_gaps = {}; wire.detached_sessions = set()
        detached = threading.Event()
        def pump():
            wire.events.append({'method':'Target.detachedFromTarget', 'params':{'sessionId':'held'}, 'session_id':None})
            detached.set()
        wire.pump.side_effect = pump
        with patch('observer.Wire', return_value=wire):
            observer = ScopedObserver('fixture', '/fixture/Default')
        observer.sessions = {'owned':'held'}
        observer.bind({'state':{'owned':{'owned':1}, 'verified':True}})
        try:
            self.assertTrue(detached.wait(1))
            deadline = time.monotonic()+1
            while not observer.closed and time.monotonic()<deadline: time.sleep(.01)
            self.assertTrue(observer.closed, 'lost held session retained browser-wide autoattach while idle')
            with self.assertRaisesRegex(RuntimeError, 'observer_lost'):
                observer.request({'method':'Runtime.evaluate','params':{'expression':'counter++'},'session':'held'}, {'owned':{'owned':1}})
            wire.assert_not_called()
        finally:
            observer.close()
        assert observer._idle is not None
        self.assertFalse(observer._idle.is_alive())

    def test_finish_browser_serializes_with_idle_reader(self):
        from plugin import ChromeProvider
        from unittest.mock import Mock
        class CheckedObserver:
            closed = False
            def __init__(self):
                self.calls = []
            def wire(self, *args):
                raise AssertionError('finish bypassed serialized observer request')
            def request(self, request, state):
                self.calls.append(request['method'])
                return {'value': {}}
            def close(self): self.closed = True
        observer = CheckedObserver()
        provider = ChromeProvider(data='/fixture')
        entry = {'observer': observer, 'state': {'owned': {}}}
        with patch.object(provider, '_chrome_processes', return_value=[]), patch('psutil.wait_procs', return_value=([], [])):
            result = provider._finish_browser(entry)
        self.assertTrue(result['browser_closed'], result)
        self.assertEqual(observer.calls, ['Browser.close'])

    def test_idle_event_burst_does_not_starve_keepalive(self):
        burst = threading.Event()
        def peer(ws):
            try:
                for raw in ws:
                    msg = json.loads(raw)
                    ws.send(json.dumps({'id': msg['id'], 'result': {'product': 'fixture'}}))
                    if not burst.is_set():
                        # More than websockets' default 16-frame high-water mark.
                        for i in range(80):
                            ws.send(json.dumps({'method': 'Network.dataReceived', 'sessionId': 'held',
                                                'params': {'requestId': str(i)}}))
                        burst.set()
            except Exception:
                pass
        server = serve(peer, '127.0.0.1', 0, ping_interval=None)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        observer = None
        try:
            endpoint = 'ws://127.0.0.1:' + str(server.socket.getsockname()[1])
            # Same library/queue as production, shorter heartbeat for a tight test.
            def connection(url, data, connector):
                return connector(url, ping_interval=.1, ping_timeout=.2, close_timeout=.2)
            with patch('vault_adapter.connect_with_consent', connection):
                observer = ScopedObserver(endpoint, '/fixture/Default')
            state={'owned':{'owned':1}}
            observer.sessions={'owned':'held'}
            observer.bind({'state':state})
            observer.request({'method': 'Browser.getVersion'}, state)
            self.assertTrue(burst.wait(1))
            time.sleep(.8)  # No tool calls or application recv during this interval.
            try:
                result = observer.request({'method': 'Browser.getVersion'}, state)
            except RuntimeError as exc:
                self.fail('idle observer lost its live peer: ' + str(exc))
            self.assertEqual(result['value']['product'], 'fixture')
            self.assertEqual(len(result['events']), 80)
            self.assertFalse(observer.closed)
        finally:
            if observer:
                observer.close()
            server.shutdown()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
