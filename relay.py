"""A session's CDP endpoint. Hermes keeps its native browser driver and helpers.

Only target discovery, target creation and browser-wide commands need mediation.
Page CDP (DOM, Runtime, Input, screenshots, frames, etc.) passes through unchanged,
except window activation and mirrored native keyboard codes on shared macOS Chrome.
This separates cooperative browser sessions; it is not a Python or web security sandbox.
"""
import concurrent.futures
import json
import logging
import re
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
    from .profiles import get_profile
else:
    from consent import connect_with_consent, consent_guard
    import startup
    from profiles import get_profile


DISCONNECTED = 'Chrome CDP disconnected. The previous browser command was not replayed.'


def task_targets(infos, owned, seed_url, context):
    owned.update(t['targetId'] for t in infos if t.get('type') == 'page'
                 and seed_url and t.get('url') == seed_url)
    # Popups in the same Chrome profile inherit ownership from their opener.
    for _ in range(len(infos)):
        added = {t['targetId'] for t in infos if t.get('type') == 'page'
                 and t.get('browserContextId') == context and t.get('openerId') in owned}
        if added <= owned:
            break
        owned.update(added)
    return [t for t in infos if t['targetId'] in owned]


def close_task_targets(wire, inventory):
    for info in inventory():
        if info.get('type') == 'page':
            wire.call('Target.closeTarget', {'targetId': info['targetId']})
    deadline = time.monotonic() + 3
    remaining = {t['targetId'] for t in inventory()}
    while remaining and time.monotonic() < deadline:
        time.sleep(.05)
        remaining = {t['targetId'] for t in inventory()}
    return remaining


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
                future.set_exception(ConnectionError(DISCONNECTED))

    def call(self, method, params=None, session=None, timeout=30):
        future = concurrent.futures.Future()
        with self.lock:
            if self.closed:
                raise ConnectionError(DISCONNECTED)
            self.counter += 1
            identifier = self.counter
            self.pending[identifier] = future
            message = {'id': identifier, 'method': method, 'params': params or {}}
            if session:
                message['sessionId'] = session
            try:
                self.ws.send(json.dumps(message))
            except (ConnectionClosed, OSError) as exc:
                self.pending.pop(identifier, None)
                raise ConnectionError(DISCONNECTED) from exc
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
    def __init__(self, data, profile, *, profile_identity=None, desktop=None, check_device=lambda: None):
        self.desktop = desktop
        self.check_device = check_device
        self.data = desktop.guard_key if desktop else Path(data).resolve()
        self.profile = profile
        self.profile_identity = profile_identity
        self.lock = threading.RLock()
        self.start_lock = threading.Lock()
        self.wire = None
        self.ready = False
        self.error = None
        self.closed = False
        self.owned = set()
        self.context = None
        self.initial_target = None
        self.kept_target = None
        self.download_page = None
        self.download_page_shared = False
        self.seed_dir = None
        self.seed_url = None
        self.seed_title = None
        self.identity = None
        self.cleanup_complete = False
        self.cleanup_file = None
        self.clients = {}
        self.learning = None
        self.uploads = {}
        self.path = '/devtools/browser/' + secrets.token_urlsafe(32)
        # No page data in websocket debug logs.
        self.logger = logging.Logger('original-chrome-cdp', logging.CRITICAL + 1)
        self.server = serve(self._client, '127.0.0.1', 0, origins=[None],
                            logger=self.logger, max_size=64 * 1024 * 1024, close_timeout=1)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True,
                                       name='chrome-session-endpoint')
        self.thread.start()
        self.url = f'ws://127.0.0.1:{self.server.socket.getsockname()[1]}{self.path}'

    def set_learning(self, catalog):
        if __package__:
            from .site_learning import PageLearning
        else:
            from site_learning import PageLearning
        if catalog is not None:
            self.learning = PageLearning(catalog)

    @property
    def disconnected(self):
        return self.ready and self.wire.closed

    def stage_upload(self, source, digest, check_owner):
        key = (source, digest)
        with self.lock:
            if self.closed:
                raise RuntimeError('The owning Chrome session has closed.')
            if key in self.uploads:
                return self.uploads[key].path
        staged = self.desktop.stage_upload(source, digest, check_owner)
        with self.lock:
            kept = None if self.closed else self.uploads.setdefault(key, staged)
        if kept is not staged:
            staged.close()
        if kept is None:
            raise RuntimeError('The owning Chrome session closed during upload.')
        return kept.path

    def release_upload(self, source, digest):
        key = (source, digest)
        with self.lock:
            staged = self.uploads.get(key)
        if staged is None:
            return True
        if not staged.close():
            logging.getLogger(__name__).warning('Windows Chrome upload cleanup is not confirmed.')
            return False
        with self.lock:
            self.uploads.pop(key, None)
        return True

    def owned_window(self):
        """Identify a single owned Chrome window before promising to keep it open."""
        with self.start_lock:
            if self.closed or not self.ready or self.disconnected:
                raise RuntimeError('Open the Chrome page before keeping its window.')
            pages = [page for page in self._inventory() if page['type'] == 'page']
            if not pages:
                raise RuntimeError('This Chrome window has already closed.')
            windows = {self.wire.call('Browser.getWindowForTarget', {'targetId': page['targetId']})['windowId']
                       for page in pages}
            if len(windows) != 1:
                raise RuntimeError('The browser session has more than one Chrome window.')
            page = next((page for page in pages if page['targetId'] == self.kept_target), pages[0])
            return page['targetId'], page.get('title', '')

    def kept_window_exists(self):
        with self.lock:
            return not self.closed and self.ready and not self.disconnected and self.kept_target in self.owned

    def unique_download_page(self, expected=None):
        """Chrome History identifies the tab URL, so require a single source window."""
        pages = self.wire.call('Target.getTargets')['targetInfos']
        with self.lock:
            owned = [p for p in pages if p.get('type') == 'page' and p['targetId'] in self.owned]
            if len(owned) != 1 or not owned[0].get('url', '').startswith('https://'):
                return None
            page = owned[0]
            url = page['url']
            identity = (page['targetId'], url)
            if expected is None:
                self.download_page = identity
                self.download_page_shared = False
            elif expected != url or identity != self.download_page:
                return None
            self.download_page_shared |= any(self._other_download_page(p) for p in pages)
            return None if self.download_page_shared else url

    def _other_download_page(self, info):
        target, url = self.download_page
        return (info.get('type') == 'page' and info.get('browserContextId') == self.context
                and info.get('url') == url and info.get('targetId') != target)

    def _profile(self):
        return self.desktop.profile(self.profile, refresh=True) if self.desktop else get_profile(self.profile, self.data)

    def _identity(self):
        return self.desktop.identity() if self.desktop else startup.endpoint_identity(self.data)

    def _open_seed(self):
        if self.desktop:
            self.seed_url = self.desktop.seed()
            self.identity = self.desktop.launch(self.profile, self.seed_url, self.profile_identity, prepare_attach=True)
            return self.desktop.connect(self.identity, logger=self.logger, max_size=64 * 1024 * 1024)
        self.seed_dir = tempfile.TemporaryDirectory(prefix='hermes-chrome-window-')
        seed_file = Path(self.seed_dir.name) / 'start.html'
        self.seed_title = 'Hermes browser session ' + secrets.token_hex(12)
        seed_file.write_text('<!doctype html><title>' + self.seed_title + '</title>')
        self.seed_url = seed_file.as_uri()
        try:
            endpoint = startup.launch(self.data, self.profile, self.seed_url)
        except startup.ChromeLaunchNotDispatched:
            self.seed_url = None
            self.seed_title = None
            raise
        self.identity = self._identity()
        if self.identity['endpoint'] != endpoint:
            raise RuntimeError('Chrome changed during startup.')
        return connect_with_consent(endpoint, self.data,
            lambda *a, **kw: connect(*a, **kw, logger=self.logger, max_size=64 * 1024 * 1024))

    def _start(self):
        with self.start_lock:
            self.check_device()
            if self.closed:
                raise RuntimeError('Browser session is closed.')
            if self.error:
                raise RuntimeError(self.error)
            if self.wire:
                if self.wire.closed:
                    raise ConnectionError(DISCONNECTED)
                return
            try:
                with consent_guard(self.data, timeout=150 if self.desktop else 60):
                    self.check_device()
                    if (self.profile_identity is not None
                            and self._profile().identity != self.profile_identity):
                        raise RuntimeError('The selected Chrome profile was replaced before startup.')
                    self.wire = Connection(self._open_seed(), self._event)
                    deadline = time.monotonic() + (6 if self.desktop else 0)
                    while True:
                        targets = self.wire.call('Target.getTargets')['targetInfos']
                        seeds = [t for t in targets if t.get('type') == 'page' and t.get('url') == self.seed_url]
                        if seeds or time.monotonic() >= deadline:
                            break
                        time.sleep(.1)
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
                    matches = actual and (self.desktop.profile_matches(actual, self.profile) if self.desktop
                                          else Path(actual).resolve() == self.data / self.profile)
                    if not matches:
                        raise RuntimeError('Chrome opened a different profile; no browsing was performed.')
                    self.wire.call('Page.navigate', {'url': 'about:blank'}, sid)
                    deadline = time.monotonic() + 6
                    while self.wire.call('Target.getTargetInfo', {'targetId': target})['targetInfo'].get('url') != 'about:blank':
                        if time.monotonic() >= deadline:
                            raise RuntimeError('The startup page has not finished its initial navigation.')
                        time.sleep(.05)
                    self.wire.call('Target.detachFromTarget', {'sessionId': sid})
                    self.wire.call('Target.setDiscoverTargets', {'discover': True})
                    self.initial_target = target
                    self.ready = True
                    self._retry_windows_cleanup()
            except Exception as exc:
                self.error = str(exc)
                if self.seed_url and self.identity is None:
                    try:
                        self.identity = self._identity()
                    except Exception:
                        pass  # Cleanup retains the unresolved seed until ownership can be verified.
                self._save_windows_cleanup()
                raise

    def _inventory(self, wire=None):
        infos = (wire or self.wire).call('Target.getTargets')['targetInfos']
        with self.lock:
            return task_targets(infos, self.owned, self.seed_url, self.context)

    def _create_profile_target(self, params):
        """Open a page in the selected persistent profile through Chrome's own singleton."""
        if not self.seed_url or self._identity() != self.identity:
            raise RuntimeError('Chrome identity changed before profile window creation.')
        if (self.profile_identity is not None
                and self._profile().identity != self.profile_identity):
            raise RuntimeError('The selected Chrome profile was replaced before window creation.')
        if self.desktop:
            if self.desktop.launch(self.profile, self.seed_url, self.profile_identity) != self.identity:
                raise RuntimeError('Chrome changed during profile window creation.')
        else:
            arguments = [str(startup.CHROME / 'Contents/MacOS/Google Chrome'),
                         f'--user-data-dir={self.data}', f'--profile-directory={self.profile}',
                         '--new-window', self.seed_url]
            startup.notify_running_chrome(self.data, (self.identity['pid'], self.identity['started']), arguments)
        deadline = time.monotonic() + 20
        while True:
            matches = [t for t in self._inventory() if t.get('url') == self.seed_url]
            if matches:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('The requested profile window is unresolved. Inspect this session before creating another window.')
            time.sleep(.05)
        if len(matches) != 1 or matches[0].get('browserContextId') != self.context:
            raise RuntimeError('Chrome opened a different or ambiguous profile window.')
        target = matches[0]['targetId']
        attached = self.wire.call('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
        try:
            self.wire.call('Page.navigate', {'url': params.get('url') or 'about:blank'}, attached)
            while any(t['targetId'] == target and t.get('url') == self.seed_url for t in self._inventory()):
                if time.monotonic() >= deadline:
                    raise RuntimeError('The new profile window has not finished its initial navigation.')
                time.sleep(.05)
        finally:
            self.wire.call('Target.detachFromTarget', {'sessionId': attached})
        bounds = {key: params[key] for key in ('left', 'top', 'width', 'height') if key in params}
        if bounds or 'windowState' in params:
            window = self.wire.call('Browser.getWindowForTarget', {'targetId': target})['windowId']
            if bounds:
                self.wire.call('Browser.setWindowBounds', {'windowId': window, 'bounds': bounds})
            if 'windowState' in params:
                self.wire.call('Browser.setWindowBounds', {'windowId': window,
                               'bounds': {'windowState': params['windowState']}})
        return {'targetId': target}

    def _event(self, message):
        method, params = message.get('method'), message.get('params', {})
        sid = message.get('sessionId')
        info = params.get('targetInfo', {})
        target = info.get('targetId') or params.get('targetId')
        if self.learning and method == 'Runtime.bindingCalled' and self.learning.event(sid, params):
            return
        with self.lock:
            if self.download_page and info:
                owner, url = self.download_page
                self.download_page_shared |= (self._other_download_page(info)
                                              or target == owner and info.get('url') != url)
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
            if method == 'Target.targetDestroyed':
                self.owned.discard(target)

    def command(self, client, method, params, sid=None):
        self._start()
        with self.lock:
            if self.closed:
                raise RuntimeError('Browser session is closed.')
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
            bootstrap = (params.get('url') == 'about:blank' and not params.get('newWindow')
                         and set(params) <= {'url', 'background', 'browserContextId', 'newWindow'})
            if self.desktop and bootstrap and self.initial_target:
                # Returning our existing page does not start Chrome or change
                # consent while another Windows session is still attaching.
                targets = self._inventory()
                with self.lock:
                    initial = self.initial_target
                    if (not self.closed and initial and not self.kept_target and
                            any(t['targetId'] == initial and t.get('url') == 'about:blank' and
                                t.get('browserContextId') == self.context for t in targets)):
                        self.initial_target = None
                        return {'targetId': initial}
            with consent_guard(self.data):
                self.check_device()
                # Cleanup uses this same guard. A queued create must recheck admission
                # after acquiring it so no window can appear after the final inventory.
                if self.closed:
                    raise RuntimeError('Browser session is closed.')
                targets = self._inventory()
                if self.kept_target and bootstrap and not sessions:
                    if any(t['targetId'] == self.kept_target for t in targets):
                        return {'targetId': self.kept_target}
                    raise RuntimeError('The kept Chrome window has closed.')
                if self.seed_url and any(t.get('url') == self.seed_url for t in targets):
                    raise RuntimeError('Inspect the original pending profile window before creating another window.')
                # The named native driver requests its first dedicated page here.
                # This endpoint already owns an exclusive, verified startup page.
                initial, self.initial_target = self.initial_target, None
                if (bootstrap
                        and any(t['targetId'] == initial and t.get('type') == 'page'
                                and t.get('url') == 'about:blank' and t.get('browserContextId') == self.context
                                for t in targets)):
                    return {'targetId': initial}
                creation = dict(params, newWindow=True, background=True)
                if self.context:
                    creation['browserContextId'] = self.context
                try:
                    result = self.wire.call(method, creation)
                except CDPError as error:
                    # Chromium resolves persistent context IDs against the last-used profile.
                    # This exact refusal precedes creation, so the native profile launch is safe.
                    if (not self.context or error.error.get('code') != -32000
                            or error.error.get('message') != 'Failed to find browser context with id ' + self.context
                            or any(params.get(key) for key in ('forTab', 'hidden', 'enableBeginFrameControl'))):
                        raise
                    result = self._create_profile_target(params)
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
            if method == 'Target.activateTarget':
                # Native provider helpers also serve cloud browsers and activate tabs.
                # Owned CDP attachments work while real Chrome stays in the background.
                return {}
            if method == 'Target.closeTarget':
                with consent_guard(self.data):
                    if target == self.kept_target:
                        raise RuntimeError('Use close_window to close the kept Chrome window.')
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
                if self.learning and target in self.owned:
                    self.learning.attach(self.wire, result['sessionId'])
            return result
        if method == 'Target.detachFromTarget':
            if params.get('sessionId') not in sessions:
                raise RuntimeError('CDP session does not belong to this connection.')
            if self.learning:
                self.learning.detach(self.wire, params['sessionId'])
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
        if (not self.desktop and method == 'Input.dispatchKeyEvent' and 'nativeVirtualKeyCode' in params
                and params['nativeVirtualKeyCode'] == params.get('windowsVirtualKeyCode')):
            # The native helper mirrors Win32 codes into this macOS-only field.
            # Omit that encoding so unhandled page keys cannot reach Cocoa menus.
            params = {key: value for key, value in params.items() if key != 'nativeVirtualKeyCode'}
        if method == 'Page.bringToFront':
            return {}
        # The native client owns the operation deadline. A resource download or
        # awaited script may legitimately exceed the transport's setup budget.
        if self.learning and method == 'Runtime.evaluate':
            return self.learning.evaluate(self.wire, method, params, sid)
        return self.wire.call(method, params, sid, timeout=None)

    def _client(self, ws):
        if ws.request.path != self.path:
            ws.close(1008, 'Unknown browser session')
            return
        with self.lock:
            closed = self.closed
            if not closed:
                self.clients[ws] = {}
        if closed:
            ws.close(1001, 'Browser session is closed.')
            return
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
                if self.learning:
                    self.learning.flush()
                ws.send(json.dumps(reply))
        finally:
            with self.lock:
                sessions = self.clients.pop(ws, {})
            if self.wire and not self.wire.closed:
                for sid in sessions:
                    try:
                        if self.learning:
                            self.learning.detach(self.wire, sid)
                        self.wire.call('Target.detachFromTarget', {'sessionId': sid}, timeout=2)
                    except Exception:
                        pass

    def _save_windows_cleanup(self):
        if self.cleanup_file is None or not (self.owned or self.seed_url):
            return
        path = self.cleanup_file
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
                    temporary = Path(output.name)
                    json.dump({'identity': self.identity, 'seed': self.seed_url,
                               'targets': sorted(self.owned), 'context': self.context}, output)
                temporary.replace(path)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
        except OSError:
            logging.getLogger(__name__).warning('Could not save pending Windows Chrome window cleanup.')

    def _retry_windows_cleanup(self):
        if self.cleanup_file is None:
            return
        # Only failed or closing sessions write records. Reuse this approved connection.
        for path in self.cleanup_file.parent.glob('*.json'):
            if path == self.cleanup_file or path.is_symlink() or not re.fullmatch('[a-f0-9]{32}', path.stem):
                continue
            try:
                record = json.loads(path.read_text())
                identity, seed, targets = record['identity'], record['seed'], record['targets']
                if (not isinstance(targets, list)
                        or any(not isinstance(t, str) or not re.fullmatch('[a-f0-9A-F]{32}', t) for t in targets)
                        or (seed is not None and (not isinstance(seed, str)
                            or not re.fullmatch('data:text/plain,Hermes-Chrome-[a-f0-9]{32}', seed)))
                        or (identity is not None and not isinstance(identity, dict))
                        or (targets and identity is None)
                        or (seed is not None and seed == self.seed_url) or self.owned.intersection(targets)):
                    continue
                if identity is not None and identity != self.identity:
                    cleared = not self.desktop.process_alive(identity)
                else:
                    owned = set(targets)

                    def inventory():
                        infos = self.wire.call('Target.getTargets')['targetInfos']
                        return task_targets(infos, owned, seed, record['context'])

                    cleared = not close_task_targets(self.wire, inventory)
                if cleared:
                    path.unlink(missing_ok=True)
            except (OSError, ValueError, KeyError, TypeError, RuntimeError, TimeoutError):
                continue  # Leave the record for another verified connection.

    def _recover_windows_cleanup(self):
        with consent_guard(self.data):
            if self.identity and not self.desktop.process_alive(self.identity):
                return True
            current = self.desktop.identity()
            if self.identity is not None and current != self.identity:
                return False
            if not self.owned:
                return self.desktop.close_seed(current, self.seed_url)
            if self.identity is None:
                return False
            # These target IDs came from a previously approved CDP connection.
            wire = Connection(self.desktop.connect_cleanup(
                current, logger=self.logger, max_size=64 * 1024 * 1024), lambda event: None)
            try:
                return not close_task_targets(wire, lambda: self._inventory(wire))
            finally:
                wire.close()

    def close(self, cleanup_wire=None):
        with self.start_lock:
            if self.cleanup_complete:
                return True
            with self.lock:
                self.closed = True
                uploads = list(self.uploads)
                self._save_windows_cleanup()
            success = True
            wire = self.wire if self.wire and not self.wire.closed else cleanup_wire
            if wire:
                try:
                    with consent_guard(self.data):
                        remaining = close_task_targets(wire, lambda: self._inventory(wire))
                        with self.lock:
                            self.owned.intersection_update(remaining)
                        success = not self.owned
                except Exception:
                    success = False
            if self.desktop and (self.owned or self.seed_url) and (wire is None or not success and wire.closed):
                try:
                    success = self._recover_windows_cleanup()
                except Exception:
                    success = False
            elif wire is None and (self.owned or self.seed_url):
                try:
                    success = bool(self.identity and not startup.process_alive(self.identity))
                    if not success and not self.owned:
                        with consent_guard(self.data):
                            success = startup.close_seed_tab(self.data,self.identity,self.seed_url,self.seed_title)
                except Exception:
                    success = False
            if success:
                # The seed is gone even if a later local transport close needs another attempt.
                self.owned.clear()
                self.seed_url = None
                if self.cleanup_file is not None:
                    try:
                        self.cleanup_file.unlink(missing_ok=True)
                    except OSError:
                        success = False
            for source, digest in uploads:
                success = self.release_upload(source, digest) and success
            with self.lock:
                clients = list(self.clients)
            for client in clients:
                try:
                    client.close()
                except Exception:
                    success = False
            if self.wire and not self.wire.closed:
                try:
                    self.wire.close()
                except Exception:
                    success = False
            try:
                self.server.shutdown()
                self.thread.join(2)
                success = success and not self.thread.is_alive()
            except Exception:
                success = False
            if success and self.seed_dir:
                try:
                    self.seed_dir.cleanup()
                except Exception:
                    success = False
            if self.learning:
                self.learning.flush()
            self.cleanup_complete = success
            return success
