"""A session's CDP endpoint. Hermes keeps its native browser driver and helpers.

Only target discovery, target creation and browser-wide commands need mediation.
Page CDP (DOM, Runtime, Input, screenshots, frames, etc.) passes through unchanged.
This separates cooperative browser sessions; it is not a Python or web security sandbox.
"""
import concurrent.futures
import json
import logging
import secrets
import threading
import time
import tempfile
from pathlib import Path

from websockets.sync.client import connect
from websockets.sync.server import serve
from websockets.exceptions import ConnectionClosed

if __package__:
    from .consent import connect_with_consent, consent_guard
    from . import startup
else:
    from consent import connect_with_consent, consent_guard
    import startup


class CDPError(RuntimeError):
    def __init__(self, error):
        self.error = error
        super().__init__(error.get('message', 'CDP command failed'))


class Connection:
    """One reader, independent outstanding requests; dialogs never block the reader."""
    def __init__(self, ws, on_event):
        self.ws, self.on_event = ws, on_event
        self.lock = threading.Lock()
        self.pending = {}
        self.counter = 0
        self.closed = False
        self.reader = threading.Thread(target=self._read, daemon=True, name='chrome-cdp-reader')
        self.reader.start()

    def _read(self):
        try:
            while True:
                raw = self.ws.recv()
                message = json.loads(raw)
                if 'id' in message:
                    with self.lock:
                        future = self.pending.pop(message['id'], None)
                    if future is not None:
                        future.set_result(message)
                else:
                    self.on_event(message)
        except (ConnectionClosed, OSError):
            pass
        finally:
            with self.lock:
                self.closed = True
                pending, self.pending = self.pending, {}
            for future in pending.values():
                future.set_exception(ConnectionError('Chrome CDP disconnected; command was not replayed.'))

    def call(self, method, params=None, session=None, timeout=30):
        future = concurrent.futures.Future()
        with self.lock:
            if self.closed:
                raise ConnectionError('Chrome CDP disconnected.')
            self.counter += 1
            identifier = self.counter
            self.pending[identifier] = future
            message = {'id': identifier, 'method': method, 'params': params or {}}
            if session:
                message['sessionId'] = session
            self.ws.send(json.dumps(message))
        try:
            result = future.result(timeout)
        finally:
            with self.lock:
                self.pending.pop(identifier, None)
        if 'error' in result:
            raise CDPError(result['error'])
        return result.get('result', {})

    def close(self):
        self.ws.close()
        if threading.current_thread() is not self.reader:
            self.reader.join(2)


class ChromeSession:
    def __init__(self, data, profile):
        self.data, self.profile = Path(data).resolve(), profile
        self.lock = threading.RLock()
        self.start_lock = threading.Lock()
        self.wire = None
        self.error = None
        self.closed = False
        self.owned = set()
        self.context = None
        self.seed_dir = None
        self.seed_url = None
        self.identity = None
        self.cleanup_complete = False
        self.clients = {}
        self.path = '/devtools/browser/' + secrets.token_urlsafe(32)
        # No page data in websocket debug logs.
        self.logger = logging.Logger('original-chrome-cdp', logging.CRITICAL + 1)
        self.server = serve(self._client, '127.0.0.1', 0, origins=[None],
                            logger=self.logger, max_size=64 * 1024 * 1024, close_timeout=1)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True,
                                       name='chrome-session-endpoint')
        self.thread.start()
        self.url = f'ws://127.0.0.1:{self.server.socket.getsockname()[1]}{self.path}'

    def _start(self):
        with self.start_lock:
            if self.closed:
                raise RuntimeError('Browser session is closed.')
            if self.error:
                raise RuntimeError(self.error)
            if self.wire:
                return
            self.seed_dir = tempfile.TemporaryDirectory(prefix='hermes-chrome-window-')
            seed_file = Path(self.seed_dir.name) / 'start.html'
            seed_file.write_text('<!doctype html><title>Hermes browser session</title>')
            seed = self.seed_url = seed_file.as_uri()
            try:
                with consent_guard(self.data, timeout=60):
                    endpoint = startup.launch(self.data, self.profile, seed)
                    self.identity = startup.endpoint_identity(self.data)
                    if self.identity['endpoint'] != endpoint:
                        raise RuntimeError('Chrome changed during startup.')
                    ws = connect_with_consent(endpoint, self.data,
                        lambda *a, **kw: connect(*a, **kw, logger=self.logger, max_size=64 * 1024 * 1024))
                    self.wire = Connection(ws, self._event)
                    targets = self.wire.call('Target.getTargets')['targetInfos']
                    seeds = [t for t in targets if t.get('type') == 'page' and t.get('url') == seed]
                    if len(seeds) != 1:
                        raise RuntimeError('The requested Chrome window could not be identified.')
                    target = seeds[0]['targetId']
                    self.owned.add(target)
                    self.context = seeds[0].get('browserContextId')
                    sid = self.wire.call('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
                    self.wire.call('Page.navigate', {'url': 'chrome://version/'}, sid)
                    deadline = time.monotonic() + 6
                    actual = ''
                    while time.monotonic() < deadline:
                        actual = self.wire.call('Runtime.evaluate', {
                            'expression': 'document.getElementById("profile_path")?.textContent || ""',
                            'returnByValue': True}, sid).get('result', {}).get('value', '')
                        if actual:
                            break
                        time.sleep(.05)
                    if not actual or Path(actual).resolve() != self.data / self.profile:
                        raise RuntimeError('Chrome opened a different profile; no browsing was performed.')
                    self.wire.call('Page.navigate', {'url': 'about:blank'}, sid)
                    self.wire.call('Target.detachFromTarget', {'sessionId': sid})
                    self.wire.call('Target.setDiscoverTargets', {'discover': True})
            except Exception as exc:
                self.error = str(exc)
                raise

    def _inventory(self, wire=None):
        infos = (wire or self.wire).call('Target.getTargets')['targetInfos']
        with self.lock:
            # Follow positive opener provenance, never names, URLs or the active window.
            for _ in range(len(infos)):
                added = {t['targetId'] for t in infos if t.get('type') == 'page'
                         and t.get('browserContextId') == self.context and t.get('openerId') in self.owned}
                if added <= self.owned:
                    break
                self.owned.update(added)
            return [t for t in infos if t['targetId'] in self.owned]

    def _event(self, message):
        method, params = message.get('method'), message.get('params', {})
        sid = message.get('sessionId')
        info = params.get('targetInfo', {})
        target = info.get('targetId') or params.get('targetId')
        with self.lock:
            if (method == 'Target.targetCreated' and info.get('type') == 'page'
                    and info.get('browserContextId') == self.context and info.get('openerId') in self.owned):
                self.owned.add(target)
            clients = list(self.clients.items())
            for ws, sessions in clients:
                if sid in sessions and method == 'Target.attachedToTarget':
                    sessions[params['sessionId']] = target
                    self.owned.add(target)
                visible = sid in sessions if sid else target in self.owned
                if visible:
                    try:
                        ws.send(json.dumps(message))
                    except Exception:
                        pass

    def command(self, client, method, params, sid=None):
        self._start()
        with self.lock:
            sessions = self.clients[client]
            if sid and sid not in sessions:
                raise RuntimeError('CDP session does not belong to this connection.')
        if method in {'Browser.close', 'Browser.crash', 'Browser.crashGpuProcess',
                      'Browser.setDownloadBehavior', 'Browser.resetPermissions', 'Browser.grantPermissions',
                      'Browser.setPermission', 'Network.clearBrowserCookies', 'Network.clearBrowserCache'}:
            raise RuntimeError('This browser-wide operation would affect other Chrome users.')
        if method == 'Target.getTargets':
            return {'targetInfos': self._inventory()}
        if method == 'Target.getBrowserContexts':
            return {'browserContextIds': [self.context] if self.context else []}
        if method == 'Target.setDiscoverTargets':
            return {}  # Already enabled on our upstream connection; events are filtered.
        if method == 'Target.createTarget':
            if params.get('browserContextId', self.context) != self.context:
                raise RuntimeError('Cannot create a target in another Chrome profile.')
            with consent_guard(self.data):
                creation = dict(params, newWindow=True, background=True)
                if self.context:
                    creation['browserContextId'] = self.context
                result = self.wire.call(method, creation)
                with self.lock:
                    self.owned.add(result['targetId'])
                return result
        if method in {'Target.attachToTarget', 'Target.getTargetInfo', 'Target.closeTarget',
                      'Target.activateTarget', 'Browser.getWindowForTarget'}:
            target = params.get('targetId') or sessions.get(sid)
            if target not in {t['targetId'] for t in self._inventory()}:
                # Frame targets discovered through this client's page attachment also belong to it.
                if target not in sessions.values():
                    raise RuntimeError('Chrome target does not belong to this browser session.')
            params = dict(params, targetId=target)
            if method == 'Target.attachToTarget':
                params['flatten'] = True
            if method in {'Target.closeTarget', 'Target.activateTarget'}:
                with consent_guard(self.data):
                    result = self.wire.call(method, params)
            else:
                result = self.wire.call(method, params)
            if method == 'Target.attachToTarget':
                with self.lock:
                    sessions[result['sessionId']] = target
                # Keep cross-origin iframe targets discoverable to native helpers.
                # This attaches children of this page, never other browser windows.
                self.wire.call('Target.setAutoAttach', {
                    'autoAttach': True, 'waitForDebuggerOnStart': False, 'flatten': True,
                    'filter': [{'type': 'iframe'}, {'exclude': True}]}, result['sessionId'])
            return result
        if method == 'Target.detachFromTarget':
            if params.get('sessionId') not in sessions:
                raise RuntimeError('CDP session does not belong to this connection.')
            return self.wire.call(method, params)
        if method.startswith('Target.'):
            if method == 'Target.setAutoAttach' and sid:
                return self.wire.call(method, params, sid)
            raise RuntimeError('Use an owned page attachment for this Target operation.')
        if method.startswith('Browser.'):
            if method not in {'Browser.getVersion', 'Browser.getWindowBounds', 'Browser.setWindowBounds'}:
                raise RuntimeError('Unsupported browser-wide operation on shared Chrome.')
            if method != 'Browser.getVersion':
                windows = {self.wire.call('Browser.getWindowForTarget', {'targetId': t['targetId']})['windowId']
                           for t in self._inventory() if t.get('type') == 'page'}
                if params.get('windowId') not in windows:
                    raise RuntimeError('Chrome window does not belong to this browser session.')
            return self.wire.call(method, params)
        if not sid:
            raise RuntimeError('This command requires an owned page attachment.')
        # The native client owns the operation deadline. A resource download or
        # awaited script may legitimately exceed the transport's setup budget.
        return self.wire.call(method, params, sid, timeout=None)

    def _client(self, ws):
        if ws.request.path != self.path:
            ws.close(1008, 'Unknown browser session')
            return
        with self.lock:
            self.clients[ws] = {}
        try:
            for raw in ws:
                request = json.loads(raw)
                reply = {'id': request.get('id')}
                try:
                    reply['result'] = self.command(ws, request['method'], request.get('params') or {},
                                                   request.get('sessionId'))
                except CDPError as exc:
                    reply['error'] = exc.error
                except Exception as exc:
                    reply['error'] = {'code': -32000, 'message': str(exc)}
                if request.get('sessionId'):
                    reply['sessionId'] = request['sessionId']
                ws.send(json.dumps(reply))
        finally:
            with self.lock:
                sessions = self.clients.pop(ws, {})
            if self.wire and not self.wire.closed:
                for sid in sessions:
                    try:
                        self.wire.call('Target.detachFromTarget', {'sessionId': sid}, timeout=2)
                    except Exception:
                        pass

    def close(self, cleanup_wire=None):
        with self.start_lock:
            if self.cleanup_complete:
                return True
            was_closed = self.closed
            self.closed = True
            success = True
            wire = self.wire if self.wire and not self.wire.closed else cleanup_wire
            if wire:
                try:
                    with consent_guard(self.data):
                        # A rejected handshake can still leave the exact GUI seed tab.
                        # An already approved peer connection may close that tab; never
                        # open another handshake or close a whole shared window here.
                        infos = wire.call('Target.getTargets')['targetInfos']
                        seeds = [t for t in infos if t.get('type') == 'page'
                                 and self.seed_url and t.get('url') == self.seed_url]
                        self.owned.update(t['targetId'] for t in seeds)
                        for info in self._inventory(wire):
                            if info.get('type') == 'page':
                                wire.call('Target.closeTarget', {'targetId': info['targetId']})
                        deadline = time.monotonic() + 3
                        remaining = {t['targetId'] for t in self._inventory(wire)}
                        while remaining and time.monotonic() < deadline:
                            time.sleep(.05)
                            remaining = {t['targetId'] for t in self._inventory(wire)}
                        self.owned.intersection_update(remaining)
                        success = not self.owned
                except Exception:
                    success = False
            elif self.owned or self.seed_url:
                success = bool(self.identity and not startup.process_alive(self.identity))
            with self.lock:
                clients = list(self.clients)
            for client in clients:
                client.close()
            if self.wire and not self.wire.closed:
                self.wire.close()
            if not was_closed:
                self.server.shutdown()
                self.thread.join(2)
            if success and self.seed_dir:
                self.seed_dir.cleanup()
            self.cleanup_complete = success
            return success
