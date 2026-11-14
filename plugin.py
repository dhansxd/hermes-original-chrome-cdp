"""Original Chrome as a native Hermes browser provider, without tool replacements."""
import atexit
import hashlib
import json
import logging
import os
import re
import sys
import threading
import uuid
from dataclasses import dataclass

from agent.browser_provider import BrowserProvider

if __package__:
    from .input_guard import prepare_code
    from .relay import ChromeSession
    from .startup import CHROME, PERSONAL
    from .profiles import ChromeProfile, get_profile, list_profiles, profile_directory, verify_profile
else:
    from input_guard import prepare_code
    from relay import ChromeSession
    from startup import CHROME, PERSONAL
    from profiles import ChromeProfile, get_profile, list_profiles, profile_directory, verify_profile

NAME = 'original-chrome-default'
PROFILE_TOOL = 'chrome_profiles'


@dataclass
class SessionProfile:
    owner: tuple
    profile: ChromeProfile | None = None
    browser_name: str | None = None
    switching: bool = False
    finished: bool = False


class ChromeProvider(BrowserProvider):
    name = NAME
    display_name = 'Original Chrome · CDP'

    def __init__(self, get_setting=lambda key: None, *, data=PERSONAL, set_setting=None):
        self.get_setting, self.data = get_setting, data
        self.set_setting = set_setting
        self.instance_id = uuid.uuid4().hex
        self.sessions = {}
        self.owners = {}
        self.waiting = {}
        self.finishing = set()
        self.profile_choices = {}
        self.profile_routes = {}
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
            choice = self.profile_choices.get(self.profile_routes.get(name))
            profile = choice.profile if choice and choice.browser_name == name else None
            directory = profile.id if profile else profile_directory(self.get_setting('profile_directory'))
            session = ChromeSession(self.data, directory,
                                    profile_identity=profile.identity if profile else None)
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
        supervisor_stopped = True
        try:
            from tools.browser_supervisor import SUPERVISOR_REGISTRY
            SUPERVISOR_REGISTRY.stop(session.cache_key)
        except Exception:
            supervisor_stopped = False
        try:
            peer_wire = next((p.wire for p in peers if p is not session and p.wire and not p.wire.closed
                              and (not session.owned or p.identity == session.identity)), None)
            success = session.close(cleanup_wire=peer_wire) and supervisor_stopped
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
        if tool_name not in {'browser_exec', PROFILE_TOOL}:
            return None
        with self.lock:
            if self.unloading:
                return {'action': 'block', 'message': 'Original Chrome provider is unloading.'}
            try:
                if tool_name == PROFILE_TOOL:
                    name = private_session_name(args.get('session'), task_id, session_id,
                                                kwargs.get('turn_id', ''), self.instance_id)
                    result = {'action': 'modify', 'args': {'session': name}}
                else:
                    result = prepare_call(tool_name, args, task_id, session_id=session_id,
                                          provider_id=self.instance_id, **kwargs)
            except ValueError as error:
                return {'action': 'block', 'message': str(error)}
            if result and result.get('action') == 'modify':
                name = result['args']['session']
                base = self.profile_routes.get(name, name)
                from gateway.session_context import get_session_env
                route = session_key or get_session_env('HERMES_SESSION_KEY', '') or session_id
                owner = (task_id, session_id, route)
                choice = self.profile_choices.setdefault(base, SessionProfile(owner))
                if choice.finished or choice.switching:
                    return {'action': 'block', 'message': 'This browser session is finishing or changing Chrome profile.'}
                choice.owner = owner
                if tool_name == PROFILE_TOOL:
                    result['args']['session'] = base
                    return result
                try:
                    if choice.profile is None:
                        choice.profile = get_profile(self.get_setting('profile_directory'), self.data)
                        choice.browser_name = base
                        self.profile_routes[base] = base
                    else:
                        choice.profile = verify_profile(choice.profile, self.data)
                except (OSError, ValueError, RuntimeError, KeyError) as error:
                    return {'action': 'block', 'message': 'Original Chrome profile selection failed: ' + str(error)}
                name = choice.browser_name
                if name in self.finishing:
                    return {'action': 'block', 'message': 'Original Chrome session is closing.'}
                self.owners[name] = owner
                result['args']['session'] = name
        return result

    def profiles(self, args, task_id='', session_id='', **kwargs):
        """Manage this caller's profile choice and the plugin's default."""
        base = args.get('session')
        try:
            with self.lock:
                choice = self.profile_choices.get(base)
                if self.unloading or choice is None or choice.owner[:2] != (task_id, session_id):
                    raise RuntimeError('Chrome profile control requires the calling agent session.')
                if choice.finished or choice.switching:
                    raise RuntimeError('This browser session is finishing or changing Chrome profile.')
                action = args.get('action', 'list')
                if action == 'list':
                    profiles = list_profiles(self.data)
                    return {'success': True, 'session': base,
                            'default_profile': profile_directory(self.get_setting('profile_directory')),
                            'selected_profile': choice.profile.id if choice.profile else None,
                            'profiles': [{'id': item.id, 'name': item.name} for item in profiles]}
                if action not in {'select', 'set_default'}:
                    raise ValueError('Choose list, select or set_default.')
                if not args.get('profile'):
                    raise ValueError('Choose a profile directory ID from chrome_profiles.')
                profile = get_profile(args['profile'], self.data)
                if action == 'set_default':
                    if self.set_setting is None:
                        raise RuntimeError('The plugin configuration writer is unavailable.')
                    self.set_setting('profile_directory', profile.id)
                    return {'success': True, 'default_profile': profile.id}
                if choice.profile and choice.profile.id == profile.id and choice.profile.identity == profile.identity:
                    choice.profile = profile
                    return {'success': True, 'session': base, 'selected_profile': profile.id}
                choice.switching = True
                previous = choice.browser_name
            try:
                if previous:
                    self.finish(session_name=previous, interrupted=True, keep_profile=True)
                with self.lock:
                    if self.unloading or choice.finished or self.profile_choices.get(base) is not choice:
                        raise RuntimeError('The calling browser session has finished.')
                    if previous in self.owners:
                        raise RuntimeError('Previous browser cleanup is pending. Retry this profile selection.')
                    name = base if previous is None else base + '-' + uuid.uuid4().hex[:12]
                    choice.profile = profile
                    choice.browser_name = name
                    self.profile_routes[name] = base
            finally:
                with self.lock:
                    choice.switching = False
                if choice.finished:
                    self.forget_profiles(session_name=base)
            return {'success': True, 'session': base, 'selected_profile': profile.id}
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            return {'success': False, 'error': str(error)}

    def forget_profiles(self, task_id=None, session_id=None, session_name=None):
        with self.lock:
            forgotten = {base for base, choice in self.profile_choices.items()
                         if (task_id is None or choice.owner[0] == task_id)
                         and (session_id is None or choice.owner[1] == session_id)
                         and (session_name is None or session_name in {base, choice.browser_name})
                         and choice.browser_name not in self.owners}
            for base in forgotten:
                self.profile_choices.pop(base)
            self.profile_routes = {name: base for name, base in self.profile_routes.items() if base not in forgotten}

    def finish(self, task_id=None, session_id=None, completed=False, failed=False, interrupted=False,
               session_name=None, keep_profile=False, **kwargs):
        with self.lock:
            if not (completed or failed or interrupted) or (self.waiting.get(session_id) and not interrupted):
                return
            if not keep_profile:
                for base, choice in self.profile_choices.items():
                    if ((task_id is None or choice.owner[0] == task_id)
                            and (session_id is None or choice.owner[1] == session_id)
                            and (session_name is None or session_name in {base, choice.browser_name})):
                        choice.finished = True
            names = [name for name, owner in self.owners.items()
                     if (task_id is None or owner[0] == task_id) and (session_id is None or owner[1] == session_id)
                     and (session_name is None or name == session_name)]
        if not names:
            if not keep_profile:
                self.forget_profiles(task_id, session_id, session_name)
            return
        for name in names:
            with self.lock:
                owner = self.owners.get(name)
                if owner is None or name in self.finishing:
                    continue
                self.finishing.add(name)
                identifiers = [identifier for identifier, session in self.sessions.items()
                               if session.cache_key.split('@', 1)[0] == 'bu-named-' + name]
            try:
                # Release this provider's resources. Hermes owns its driver and session cache.
                closed = [self.close_session(identifier) for identifier in identifiers]
                with self.lock:
                    if all(closed) and self.owners.get(name) == owner:
                        self.owners.pop(name, None)
            except Exception:
                logging.getLogger(__name__).warning('Original Chrome agent cleanup is not confirmed.')
            finally:
                with self.lock:
                    self.finishing.discard(name)
        if not keep_profile:
            self.forget_profiles(task_id, session_id, session_name)

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
        with self.lock:
            unused = [base for base, choice in self.profile_choices.items()
                      if choice.owner[-1] == session_key and choice.browser_name not in self.owners]
        for base in unused:
            self.forget_profiles(session_name=base)

    def human_wait(self, session_id=None, request_id='pending', **kwargs):
        with self.lock:
            self.waiting.setdefault(session_id, set()).add(request_id)

    def human_resume(self, session_id=None, request_id='pending', **kwargs):
        with self.lock:
            self.waiting.get(session_id, set()).discard(request_id)


def private_session_name(alias, task_id, session_id='', turn_id='', provider_id=''):
    if not task_id:
        raise ValueError('A Hermes task identity is required for a private browser session.')
    alias = alias or 'default'
    if not isinstance(alias, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', alias):
        raise ValueError('Invalid browser session name.')
    identity = f'{provider_id}\0{session_id}\0{task_id}\0{turn_id}'
    prefix = 'hc-' + hashlib.sha256(identity.encode()).hexdigest()[:20] + '-'
    return alias if alias.startswith(prefix) else prefix + hashlib.sha256(alias.encode()).hexdigest()[:20]


def prepare_call(tool_name, args, task_id, *, session_id='', turn_id='', provider_id='', config=None, **kwargs):
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
    # Replacements and reloaded providers must stay separate from retired driver sessions.
    try:
        name = private_session_name(args.get('session'), task_id, session_id, turn_id, provider_id)
    except ValueError as error:
        return {'action': 'block', 'message': str(error)}
    changes = {'session': name}
    if 'code' in args:
        changes['code'] = prepare_code(args['code'])
    return {'action': 'modify', 'args': changes}


def register(ctx):
    provider = ChromeProvider(ctx.get_config, set_setting=ctx.set_config)
    ctx.register_browser_provider(provider)

    def profile_control(args, **context):
        return json.dumps(provider.profiles(args, **context), ensure_ascii=False)

    ctx.register_tool(name=PROFILE_TOOL, toolset='browser', handler=profile_control,
                      check_fn=provider.is_available, schema={
        'name': PROFILE_TOOL,
        'description': 'List current original Chrome profiles, select a profile for your named browser_exec session, '
                       'or set the default for new sessions. Select uses your own window and preserves other agents.',
        'parameters': {'type': 'object', 'properties': {
            'action': {'type': 'string', 'enum': ['list', 'select', 'set_default'], 'default': 'list'},
            'profile': {'type': 'string', 'description': 'Directory ID from list, such as Default or Profile 2.'},
            'session': {'type': 'string', 'description': 'Your browser_exec session alias. Defaults to default.'},
        }},
    })
    ctx.register_hook('pre_tool_call', provider.prepare_call)
    ctx.register_hook('agent_loop_stopped', provider.stopped)
    ctx.register_hook('on_session_finalize', provider.finalize)
    ctx.register_hook('on_session_end', provider.finalize)
    ctx.register_hook('on_human_input_request', provider.human_wait)
    ctx.register_hook('on_human_input_resolved', provider.human_resume)
    ctx.on_unload(provider.unload)
