"""Original Chrome as a native Hermes browser provider, without tool replacements."""
import atexit
import hashlib
import logging
import os
import re
import sys
import threading
import uuid
import subprocess
from pathlib import Path

from agent.browser_provider import BrowserProvider

if __package__:
    from .input_guard import prepare_code
    from .relay import ChromeSession
    from .startup import CHROME, PERSONAL
else:
    from input_guard import prepare_code
    from relay import ChromeSession
    from startup import CHROME, PERSONAL

NAME = 'original-chrome-default'


def profile_directory(value):
    value = value or 'Default'
    if (not isinstance(value, str) or not value.isprintable() or len(value) > 128
            or value in {'.', '..', 'Guest Profile', 'System Profile'} or '/' in value or '\\' in value):
        raise ValueError('Choose an existing Chrome profile directory, e.g. Default or Profile 2.')
    return value


class ChromeProvider(BrowserProvider):
    name = NAME
    display_name = 'Original Chrome · CDP'

    def __init__(self, get_setting=lambda key: None, *, data=PERSONAL):
        self.get_setting, self.data = get_setting, data
        self.sessions = {}
        self.owners = {}
        self.waiting = {}
        self.finishing = set()
        self.lock = threading.RLock()
        self.unloading = False
        # Retain failed cleanup across host unload, until it succeeds or the process exits.
        atexit.register(self.unload)

    def is_available(self):
        return sys.platform == 'darwin' and CHROME.exists()

    def get_setup_schema(self):
        return {'name': self.display_name, 'badge': 'local',
                'tag': 'Your signed-in Chrome; separate agent windows; no profile copy', 'env_vars': []}

    def create_session(self, task_id):
        # Return a local endpoint before starting Chrome. Startup failures become CDP
        # errors instead of triggering Hermes's fallback to packaged Chromium.
        with self.lock:
            name = task_id.removeprefix('bu-named-').split('@', 1)[0]
            # Finalization removes the hook's admission for this exact native name.
            if (self.unloading or name in self.finishing
                    or (task_id.startswith('bu-named-') and name not in self.owners)):
                # Native Hermes falls back to Chromium on create_session exceptions.
                # Retired providers and closing sessions fail at CDP without a new listener.
                return {'session_name': NAME + '-unloaded', 'bb_session_id': 'unloaded',
                        'cdp_url': 'ws://original-chrome-provider-unloaded.invalid/devtools/browser/unloaded',
                        'features': {'original_chrome': True}}
            session = ChromeSession(self.data, profile_directory(self.get_setting('profile_directory')))
            session.cache_key = task_id
            identifier = uuid.uuid4().hex
            self.sessions[identifier] = session
        return {'session_name': 'original-chrome-' + identifier, 'bb_session_id': identifier,
                'cdp_url': session.url, 'features': {'original_chrome': True}}

    def close_session(self, session_id):
        with self.lock:
            session = self.sessions.get(session_id)
            peers = list(self.sessions.values())
        if session is None:
            return True
        daemon_stopped = True
        try:
            stop_native_daemon(session.cache_key)
        except Exception:
            daemon_stopped = False
        try:
            peer_wire = next((p.wire for p in peers if p is not session and p.wire and not p.wire.closed
                              and (not session.owned or p.identity == session.identity)), None)
            success = session.close(cleanup_wire=peer_wire) and daemon_stopped
        except Exception:
            success = False
        if success:
            with self.lock:
                self.sessions.pop(session_id, None)
        else:
            logging.getLogger(__name__).warning('Original Chrome session cleanup is not confirmed.')
        return success

    def emergency_cleanup(self, session_id):
        self.close_session(session_id)

    def unload(self):
        with self.lock:
            self.unloading = True
        self.finish(completed=True, interrupted=True)
        with self.lock:
            identifiers = list(self.sessions)
        for identifier in identifiers:
            self.close_session(identifier)
        with self.lock:
            complete = not self.sessions and not self.owners
            if complete:
                self.waiting.clear()
                atexit.unregister(self.unload)
            else:
                logging.getLogger(__name__).warning(
                    'Original Chrome unload has pending cleanup (%d sessions, %d agents).',
                    len(self.sessions), len(self.owners))
        return complete

    def prepare_call(self, tool_name, args, task_id, session_id='', session_key='', **kwargs):
        with self.lock:
            if self.unloading:
                if tool_name == 'browser_exec':
                    return {'action': 'block', 'message': 'Original Chrome provider is unloading.'}
                return None
            result = prepare_call(tool_name, args, task_id, session_id=session_id, **kwargs)
            if result and result.get('action') == 'modify':
                name = result['args']['session']
                if name in self.finishing:
                    return {'action': 'block', 'message': 'Original Chrome session is closing.'}
                from tools.approval_context import get_current_session_key
                route = session_key or get_current_session_key(default='') or session_id
                self.owners[name] = (task_id, session_id, route)
        return result

    def finish(self, task_id=None, session_id=None, completed=False, failed=False, interrupted=False,
               session_name=None, **kwargs):
        with self.lock:
            if not (completed or failed or interrupted) or (self.waiting.get(session_id) and not interrupted):
                return
            names = [name for name, owner in self.owners.items()
                     if (task_id is None or owner[0] == task_id) and (session_id is None or owner[1] == session_id)
                     and (session_name is None or name == session_name)]
        if not names:
            return
        from tools.browser_session_lifecycle import cleanup_browser
        from tools.browser_session_cdp import stop_cdp_supervisor
        for name in names:
            with self.lock:
                owner = self.owners.get(name)
                if owner is None or name in self.finishing:
                    continue
                self.finishing.add(name)
            cache_key = 'bu-named-' + name
            try:
                # Native teardown can wait on I/O. Keep other agents' admission available.
                stop_cdp_supervisor(owner[0])
                cleanup_browser(cache_key)
                with self.lock:
                    # Native cleanup can forget a session even when close_session returns False.
                    identifiers = [identifier for identifier, session in self.sessions.items()
                                   if session.cache_key.split('@', 1)[0] == cache_key]
                closed = [self.close_session(identifier) for identifier in identifiers]
                with self.lock:
                    if all(closed) and self.owners.get(name) == owner:
                        self.owners.pop(name, None)
            except Exception:
                logging.getLogger(__name__).warning('Original Chrome agent cleanup is not confirmed.')
            finally:
                with self.lock:
                    self.finishing.discard(name)

    def finalize(self, session_id=None, **kwargs):
        if session_id:
            self.finish(session_id=session_id, completed=True, interrupted=True)

    def stopped(self, session_key='', **kwargs):
        """Match Hermes's Stop route to the browser names admitted in that context."""
        if not session_key:
            return
        with self.lock:
            names = [name for name, owner in self.owners.items() if owner[-1] == session_key]
        for name in names:
            self.finish(session_name=name, interrupted=True)

    def human_wait(self, session_id=None, request_id='pending', **kwargs):
        with self.lock:
            self.waiting.setdefault(session_id, set()).add(request_id)

    def human_resume(self, session_id=None, request_id='pending', **kwargs):
        with self.lock:
            self.waiting.get(session_id, set()).discard(request_id)


def stop_native_daemon(cache_key):
    """Use the harness's own identity-checked reload for this session only."""
    match = re.match(r'^bu-named-(hc-[a-f0-9-]+)(?:@|$)', cache_key)
    if not match:
        return
    import browser_harness
    from hermes_constants import get_hermes_home_override, hermes_home_key
    from tools.browser_session import build_browser_env
    from tools.browser_harness_dirs import namespace_harness_dirs, fit_default_socket_dir
    env = build_browser_env()
    env.pop('PYTHONHOME', None)
    env['PYTHONPATH'] = str(Path(browser_harness.__file__).parent.parent)
    namespace_harness_dirs(env, hermes_home_key() if get_hermes_home_override() is not None else '')
    env['BU_NAME'] = match[1]
    fit_default_socket_dir(env)
    subprocess.run([sys.executable, '-m', 'browser_harness.run', '--reload'], env=env,
                   capture_output=True, text=True, timeout=15, check=True)


def prepare_call(tool_name, args, task_id, *, session_id='', turn_id='', config=None, **kwargs):
    """Keep native browser_exec, with per-agent names and a plugin-owned focus check."""
    if config is None:
        from hermes_cli.config import load_config_readonly
        config = load_config_readonly()
    browser = config.get('browser', {})
    if tool_name != 'browser_exec' or browser.get('cloud_provider') != NAME:
        return None
    if not task_id:
        return {'action': 'block', 'message': 'A Hermes task identity is required for a private browser session.'}
    if (args.get('local') or browser.get('use_real_profile') or browser.get('cdp_url')
            or any(os.environ.get(key) for key in ('BROWSER_CDP_URL', 'BU_CDP_WS', 'BU_CDP_URL'))):
        return {'action': 'block', 'message': 'Original Chrome is selected, but a different browser/profile override is active.'}
    if browser.get('auto_local_for_private_urls', True):
        return {'action': 'block', 'message': 'Set browser.auto_local_for_private_urls=false for the Original Chrome provider.'}
    alias = args.get('session') or 'default'
    if not isinstance(alias, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', alias):
        return {'action': 'block', 'message': 'Invalid browser session name.'}
    # A replacement turn must keep a different native cache key from a stopped turn.
    identity = f'{session_id}\0{task_id}\0{turn_id}'
    prefix = 'hc-' + hashlib.sha256(identity.encode()).hexdigest()[:20] + '-'
    name = alias if alias.startswith(prefix) else prefix + hashlib.sha256(alias.encode()).hexdigest()[:20]
    changes = {'session': name}
    if 'code' in args:
        changes['code'] = prepare_code(args['code'])
    return {'action': 'modify', 'args': changes}


def register(ctx):
    provider = ChromeProvider(ctx.get_config)
    ctx.register_browser_provider(provider)
    ctx.register_hook('pre_tool_call', provider.prepare_call)
    ctx.register_hook('agent_loop_stopped', provider.stopped)
    ctx.register_hook('on_session_finalize', provider.finalize)
    ctx.register_hook('on_session_end', provider.finalize)
    ctx.register_hook('on_human_input_request', provider.human_wait)
    ctx.register_hook('on_human_input_resolved', provider.human_resume)
    ctx.on_unload(provider.unload)
