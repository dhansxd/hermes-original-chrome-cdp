"""Original Chrome as a native Hermes browser provider, without tool replacements."""
import atexit
import hashlib
import json
import logging
import os
import random
import re
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from agent.browser_provider import BrowserProvider

if __package__:
    from .input_guard import prepare_code
    from .relay import ChromeSession, DISCONNECTED
    from .startup import CHROME, PERSONAL
    from .profiles import ChromeProfile, get_profile, list_profiles, profile_directory, verify_profile
    from .browser_apps import AppHost, CONTROL_SCHEMA, app_identifier
    from .profile_rules import ProfileRules
else:
    from input_guard import prepare_code
    from relay import ChromeSession, DISCONNECTED
    from startup import CHROME, PERSONAL
    from profiles import ChromeProfile, get_profile, list_profiles, profile_directory, verify_profile
    from browser_apps import AppHost, CONTROL_SCHEMA, app_identifier
    from profile_rules import ProfileRules

NAME = 'original-chrome-default'
PROFILE_TOOL = 'chrome_profiles'


@dataclass
class SessionProfile:
    owner: tuple
    profile: ChromeProfile | None = None
    browser_name: str | None = None
    switching: bool = False
    finished: bool = False
    app_id: str = ''
    turn_id: str = ''
    alias: str = 'default'
    platform: str = ''
    pending: bool = False
    retained: bool = False
    running: tuple[str, str | None] | None = None
    can_read_result: bool = False
    running_since: float = 0.0
    last_observation: float = 0.0
    active: int = 0
    directory_key: str = ''


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
        self.rules = ProfileRules(get_setting, set_setting)
        self.parents = {}
        self.app_instances = {}
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
                self.parents.clear()
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
            from gateway.session_context import get_session_env
            route = session_key or get_session_env('HERMES_SESSION_KEY', '') or session_id
            app_id = ''
            try:
                app_id = app_identifier(args.get('app')) if args.get('app') else ''
                alias = args.get('session') or 'default'
                owner = (task_id, session_id, route)
                turn = kwargs.get('turn_id', '')
                existing = self.profile_choices.get(self.profile_routes.get(alias)) if isinstance(alias, str) else None
                if existing is None:
                    existing = next((item for item in self.profile_choices.values()
                                     if item.owner == owner and item.turn_id == turn and item.alias == alias
                                     and item.browser_name in self.owners and not item.finished), None)
                reuse = existing is not None and (
                    (existing.owner == owner and existing.turn_id == turn)
                    or (existing.retained and existing.owner[1:] == owner[1:]
                        and bool(session_id) and alias == existing.browser_name))
                if tool_name == PROFILE_TOOL and app_id and existing and existing.app_id != app_id:
                    reuse = False  # Independent profile rules apply when starting a new task window.
                if kwargs.get('require_existing') and (not reuse or existing.app_id not in ('', app_id)):
                    return {'action': 'block', 'message': 'Record the missing control in its current owned site window.'}
                if reuse:
                    if existing.active and existing.owner != owner:
                        return {'action': 'block', 'message': 'The previous extension operation is still returning.'}
                    if app_id and existing.app_id and app_id != existing.app_id and (existing.pending or existing.active):
                        return {'action': 'block', 'message': 'Finish the active site operation in this window first.'}
                    app_id = app_id or existing.app_id
                if app_id and self.get_setting('apps_disabled.' + app_id):
                    return {'action': 'block', 'message': 'This website extension is disabled.'}
                namespace = self.instance_id
                if app_id:
                    namespace += '\0app\0' + app_id + '\0' + self.app_instances.get(app_id, '')
                if tool_name == PROFILE_TOOL:
                    name = private_session_name(alias, task_id, session_id, kwargs.get('turn_id', ''), namespace)
                    result = {'action': 'modify', 'args': {'session': name}}
                else:
                    result = prepare_call('browser_exec', args, task_id, session_id=session_id,
                                          provider_id=namespace, **kwargs)
            except ValueError as error:
                return {'action': 'block', 'message': str(error)}
            if result and result.get('action') == 'modify':
                name = result['args']['session']
                base = self.profile_routes.get(existing.browser_name if reuse else name, name)
                if app_id and not reuse:
                    retained = next(((key, item) for key, item in self.profile_choices.items()
                                     if item.app_id == app_id and item.owner[1:] == owner[1:]
                                     and item.alias == alias and item.retained and not item.finished), None)
                    if retained:
                        base, existing = retained
                        if existing.active:
                            return {'action': 'block', 'message': 'The previous extension operation is still returning.'}
                choice = self.profile_choices.setdefault(base, SessionProfile(owner, alias=alias))
                if choice.finished or choice.switching:
                    return {'action': 'block', 'message': 'This browser session is finishing or changing Chrome profile.'}
                choice.owner = owner
                choice.retained = False
                if choice.app_id != app_id:
                    choice.directory_key = ''
                choice.app_id = app_id
                choice.turn_id = kwargs.get('turn_id', '')
                choice.platform = get_session_env('HERMES_SESSION_PLATFORM', '')
                if tool_name == PROFILE_TOOL:
                    result['args']['session'] = base
                    return result
                try:
                    if app_id and kwargs.get('defer_profile'):
                        if choice.browser_name is None:
                            choice.browser_name = base
                            self.profile_routes[base] = base
                    elif choice.profile is None:
                        choice.profile = self.choose_profile(choice)
                        choice.browser_name = base
                        self.profile_routes[base] = base
                    else:
                        choice.profile = verify_profile(choice.profile, self.data)
                except (OSError, ValueError, RuntimeError, KeyError) as error:
                    return {'action': 'block', 'message': 'Original Chrome profile selection failed: ' + str(error)}
                name = choice.browser_name
                if name in self.finishing:
                    return {'action': 'block', 'message': 'Original Chrome session is closing.'}
                # A pending site operation owns its original document. Ordinary browsing
                # can start a new window after the exact old session has been retired.
                if app_id or not any(session.disconnected
                                     for session in self.sessions.values()
                                     if session.cache_key.split('@', 1)[0] == 'bu-named-' + name):
                    self.owners[name] = owner
                    result['args']['session'] = name
                    return result
                choice.switching = True
            else:
                return result
        try:
            self._replace_browser(base, choice, choice.profile)
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            return {'action': 'block', 'message': DISCONNECTED + ' ' + str(error)}
        return {'action': 'block', 'message': DISCONNECTED +
                ' Call browser_exec again to open a new window. Verify the result of any interrupted action.'}

    def choose_profile(self, choice, *, proposed=None):
        rule, _ = self.rules.resolve(choice.app_id, choice.owner, choice.alias,
                                     choice.platform, self.parents.get(choice.owner[1]), proposed=proposed)
        if rule['mode'] == 'random':
            available = list_profiles(self.data)
            if not available:
                raise ValueError('No Chrome profiles are available.')
            return random.choice(available)
        directory = rule.get('profile') if rule['mode'] == 'fixed' else self.get_setting('profile_directory')
        profile = get_profile(directory, self.data)
        if rule.get('identity') is not None and profile.identity != tuple(rule['identity']):
            raise RuntimeError('The profile in this Chrome rule was replaced. Select and save it again.')
        return profile

    def child_started(self, parent_session_id='', child_session_id='', child_role='', **kwargs):
        if parent_session_id and child_session_id:
            with self.lock:
                self.parents[child_session_id] = {
                    'session_id': parent_session_id, 'role': child_role or '*',
                    'profiles': {(choice.app_id, choice.alias): choice.profile
                                 for choice in self.profile_choices.values()
                                 if choice.owner[1] == parent_session_id and choice.profile and not choice.finished}}

    def profiles(self, args, task_id='', session_id='', **kwargs):
        """Manage this caller's profile choice and the plugin's default."""
        base = args.get('session')
        rule_change = None
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
                    rule, source = self.rules.resolve(choice.app_id, choice.owner, choice.alias,
                                                      choice.platform, self.parents.get(session_id))
                    default = self.rules.read(choice.app_id, 'default', '*') or {'mode': 'default'}
                    default_profile = default.get('profile') if default['mode'] == 'fixed' else None
                    if default['mode'] == 'default':
                        default_profile = profile_directory(self.get_setting('profile_directory'))
                    return {'success': True, 'session': base,
                            'default_profile': default_profile, 'default_rule': default,
                            'selected_profile': choice.profile.id if choice.profile else None,
                            'app': choice.app_id or None,
                            'rule': rule, 'rule_source': source,
                            'profiles': [{'id': item.id, 'name': item.name} for item in profiles]}
                if action in {'set_rule', 'clear_rule'}:
                    scope = args.get('scope', 'session')
                    if not isinstance(scope, str):
                        raise ValueError('Choose a profile rule scope.')
                    parent = self.parents.get(session_id)
                    targets = {'session': session_id, 'agent': task_id, 'platform': choice.platform,
                               'subagent': parent['role'] if parent else '*', 'default': '*'}
                    target = args.get('target') or targets.get(scope)
                    rule = None
                    if action == 'set_rule':
                        rule = {'mode': args.get('mode', 'fixed')}
                        if rule['mode'] == 'fixed':
                            if not args.get('profile'):
                                raise ValueError('A fixed profile rule needs a Chrome directory ID.')
                            selected = get_profile(args.get('profile'), self.data)
                            rule.update(profile=selected.id, identity=list(selected.identity))
                    rule_change = self.rules.prepare_change(choice.app_id, scope, target,
                                                            choice.alias if scope == 'session' else '', rule)
                    if scope == 'default' or target != targets.get(scope):
                        return {'success': True, 'rule': self.rules.apply(rule_change),
                                'applied_to_current_session': False}
                    profile = self.choose_profile(choice, proposed=rule_change)
                    if choice.pending:
                        return {'success': True, 'rule': self.rules.apply(rule_change),
                                'applied_to_current_session': False,
                                'pending_source_profile': choice.profile.id}
                elif action in {'select', 'set_default'}:
                    if not args.get('profile'):
                        raise ValueError('Choose a profile directory ID from chrome_profiles.')
                    profile = get_profile(args['profile'], self.data)
                else:
                    raise ValueError('Choose list, select, set_default, set_rule or clear_rule.')
                if action == 'set_default':
                    if choice.app_id:
                        self.rules.change(choice.app_id, 'default', '*', '',
                                          {'mode': 'fixed', 'profile': profile.id, 'identity': list(profile.identity)})
                        return {'success': True, 'app': choice.app_id, 'default_profile': profile.id}
                    if self.set_setting is None:
                        raise RuntimeError('The plugin configuration writer is unavailable.')
                    self.set_setting('profile_directory', profile.id)
                    if self.rules.read('', 'default', '*') is not None:
                        self.rules.change('', 'default', '*', '', None)
                    return {'success': True, 'default_profile': profile.id}
                if choice.profile and choice.profile.id == profile.id and choice.profile.identity == profile.identity:
                    if rule_change is not None:
                        self.rules.apply(rule_change)
                    choice.profile = profile
                    return {'success': True, 'session': base, 'selected_profile': profile.id}
                if choice.pending:
                    raise RuntimeError('This app is still observing a result in its source profile. '
                                       'Finish that result or stop its session before switching this alias.')
                choice.switching = True
            self._replace_browser(base, choice, profile, rule_change=rule_change)
            return {'success': True, 'session': base, 'selected_profile': profile.id}
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            return {'success': False, 'error': str(error)}

    def _replace_browser(self, base, choice, profile, *, rule_change=None):
        """Retire the old native name outside the provider's lock before handing out a new one."""
        previous = choice.browser_name
        try:
            if previous:
                self.finish(session_name=previous, interrupted=True, keep_profile=True)
            with self.lock:
                if self.unloading or choice.finished or self.profile_choices.get(base) is not choice:
                    raise RuntimeError('The calling browser session has finished.')
                if previous in self.owners:
                    raise RuntimeError('Previous browser cleanup is pending. Retry after it completes.')
                if previous is not None:
                    # The native cache may still have the retired name if saving fails.
                    choice.browser_name = base + '-' + uuid.uuid4().hex[:12]
                    self.profile_routes[choice.browser_name] = base
                profile = verify_profile(profile, self.data)
                if rule_change is not None:
                    self.rules.apply(rule_change)
                choice.profile = profile
                if previous is None:
                    choice.browser_name = base
                    self.profile_routes[base] = base
        finally:
            with self.lock:
                choice.switching = False
            if choice.finished:
                self.forget_profiles(session_name=base)

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
               session_name=None, keep_profile=False, expected_turn=None, **kwargs):
        with self.lock:
            if not (completed or failed or interrupted) or (self.waiting.get(session_id) and not interrupted):
                return
            if expected_turn is not None:
                choice = self.profile_choices.get(session_name)
                if (choice is None or choice.turn_id != expected_turn
                        or (choice.pending and not interrupted)):
                    return
                session_name = choice.browser_name or session_name
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
            with self.lock:
                self.parents.pop(session_id, None)

    def ended(self, session_id=None, task_id=None, turn_id=None, interrupted=False,
              failed=False, turn_exit_reason=None, **kwargs):
        if not session_id:
            return
        terminal_failure = failed or turn_exit_reason == 'guardrail_halt'
        with self.lock:
            for choice in self.profile_choices.values():
                if (choice.pending and choice.owner[1] == session_id
                        and (task_id is None or choice.owner[0] == task_id)
                        and (turn_id is None or choice.turn_id == turn_id)):
                    choice.retained = True
            turns = [(base, choice.turn_id, interrupted or (terminal_failure and choice.running is not None))
                     for base, choice in self.profile_choices.items()
                     if choice.owner[1] == session_id and (task_id is None or choice.owner[0] == task_id)
                     and (turn_id is None or choice.turn_id == turn_id)
                     and (interrupted or not choice.pending or (terminal_failure and choice.running is not None))]
        for base, expected, abandon in turns:
            self.finish(session_name=base, expected_turn=expected, completed=True, interrupted=abandon)

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


SITE_HELP = ('Use browser_exec directly for Gemini Web and Google Flow, including requests called '
             'browser_app in older chats. To open Gemini pass site_control as JSON text: '
             '{"app":"gemini","operation":"open_chat"}. To see a site guide use action describe with its app ID. '
             'Use code with site_control omitted or null for DOM inspection, screenshots and ordinary '
             'browsing in the same session.')


def with_site_controls(schema):
    parameters = schema['parameters']
    fields = parameters['properties']
    code = {**fields['code'], 'description': fields['code']['description'] + ' Omit this field when using site_control.'}
    return {**schema, 'description': SITE_HELP + '\n\n' + schema['description'], 'parameters': {
        **parameters, 'properties': {**fields, 'code': code, 'site_control': CONTROL_SCHEMA},
        'required': [key for key in parameters.get('required', []) if key != 'code'],
    }}


def register_site_controls(ctx, apps):
    from tools.registry import discover_builtin_tools, registry
    native = registry.snapshot_registration('browser_exec')
    if native is None:
        discover_builtin_tools()
        native = registry.snapshot_registration('browser_exec')
    active = registry.get_entry('browser_exec')
    if native is None or (active is not native and getattr(active.handler, '__module__', '') != __name__):
        raise RuntimeError('Original Chrome site controls require the native Hermes browser_exec handler.')

    def browser_control(args, **context):
        return apps.execute(args, native.handler, **context)

    def browser_schema():
        overrides = native.dynamic_schema_overrides() if native.dynamic_schema_overrides else {}
        from hermes_cli.config import load_config_readonly
        if load_config_readonly().get('browser', {}).get('cloud_provider') != NAME:
            return {**native.schema, **overrides}
        return with_site_controls({**native.schema, **overrides})

    ctx.register_tool(name='browser_exec', toolset=native.toolset, schema=with_site_controls(native.schema),
                      handler=browser_control, check_fn=native.check_fn, emoji=native.emoji, override=True)
    # These registry fields belong to this plugin's scoped entry. Restore the native
    # runtime help, compatibility arguments and deadlines on the delegated tool.
    entry = registry.get_entry('browser_exec')
    if entry is not None and entry.handler is browser_control:
        entry.dynamic_schema_overrides = browser_schema
        entry.compat_args = native.compat_args
        entry.deadline_floor = native.deadline_floor
        entry.execution_timeout = native.execution_timeout
        entry.max_result_size_chars = native.max_result_size_chars
        entry.self_checked_args = native.self_checked_args


def register(ctx):
    provider = ChromeProvider(ctx.get_config, set_setting=ctx.set_config)
    ctx.register_browser_provider(provider)
    root = Path(__file__).parent
    apps = AppHost(provider, ctx.get_config, ctx.dispatch_tool, prepare_code,
                   lambda: ctx.state.data_dir, bundled_source=root / 'site_apps')
    apps.controls_enabled = bool(ctx.has_capability('tools.override'))
    if apps.controls_enabled:
        register_site_controls(ctx, apps)
    if hasattr(ctx, 'register_middleware'):
        ctx.register_middleware('llm_execution', apps.continue_running)
    if hasattr(ctx, 'register_skill'):
        ctx.register_skill('site-controls', root / 'skills' / 'site-controls' / 'SKILL.md',
                           description='Use browser_exec.site_control for Gemini Web and Google Flow tasks, '
                                       'including images, video, Deep Research, chats and downloads.',
                           frontmatter={'platforms': ['macos'],
                                        'metadata': {'hermes': {'requires_toolsets': ['browser']}}})

    def profile_control(args, **context):
        return json.dumps(provider.profiles(args, **context), ensure_ascii=False)

    ctx.register_tool(name=PROFILE_TOOL, toolset='browser', handler=profile_control,
                      check_fn=provider.is_available, schema={
        'name': PROFILE_TOOL,
        'description': 'Control profile selection for the Original Chrome CDP provider and each agent\'s '
                       'named browser_exec sessions. For Gemini Web and Google Flow actions from older '
                       'browser_app conversations, call browser_exec with site_control. '
                       'list refreshes directory IDs and display names from Chrome, reflecting profile additions, '
                       'removals and renames. Agents can share a profile or choose different profiles with separate '
                       'windows. select stores a choice for your session. Switching to a different profile closes '
                       'that session\'s current windows and tabs. The next browser_exec using the same session alias '
                       'opens the chosen profile directly. A session uses the saved default on its first '
                       'browser_exec, with explicit selections taking precedence. '
                       'Pass app to manage a website extension independently of ordinary browsing. '
                       'set_rule persists fixed/default/random policy for a session, agent, subagent '
                       'role, platform or default. Rules resolve in that order, followed by parent '
                       'inheritance and the service default. Random is chosen once for an active session. '
                       'clear_rule restores inherited policy. Defaults affect new sessions. '
                       'A pending app result keeps its source profile until observed or stopped.',
        'parameters': {'type': 'object', 'properties': {
            'action': {'type': 'string', 'enum': ['list', 'select', 'set_default', 'set_rule', 'clear_rule'], 'default': 'list',
                       'description': 'list returns current profiles. select chooses or switches your named '
                                      'session. set_default persists the default for new, unselected sessions. '
                                      'Use select to switch an existing session.'},
            'profile': {'type': 'string',
                        'description': 'For select and set_default, pass a profile\'s id field from list, '
                                       'such as Default or Profile 2.'},
            'app': {'type': 'string', 'description': 'Website package ID. Omit for ordinary browser sessions.'},
            'mode': {'type': 'string', 'enum': ['fixed', 'default', 'random'],
                     'description': 'For set_rule. fixed needs profile. default uses profile_directory. random chooses from fresh inventory.'},
            'scope': {'type': 'string', 'enum': ['session', 'agent', 'subagent', 'platform', 'default'],
                      'default': 'session', 'description': 'Policy scope. session persists for this conversation and alias. agent targets the current task. subagent targets a role or *. platform targets a channel. default is specific to app or ordinary browsing.'},
            'target': {'type': 'string', 'description': 'Optional scope target. Defaults to the caller conversation/task/platform, current child role or *, or * for default.'},
            'session': {'type': 'string',
                        'description': 'Your session alias, defaulting to default. Use the same alias in '
                                       'chrome_profiles and browser_exec. Each agent selects its own session '
                                       'and may reuse an alias used by other agents.'},
        }},
    })
    ctx.register_hook('pre_tool_call', apps.prepare_call)
    ctx.register_hook('agent_loop_stopped', provider.stopped)
    ctx.register_hook('on_session_finalize', provider.finalize)
    ctx.register_hook('on_session_end', provider.ended)
    ctx.register_hook('subagent_start', provider.child_started)
    ctx.register_hook('on_human_input_request', provider.human_wait)
    ctx.register_hook('on_human_input_resolved', provider.human_resume)
    ctx.on_unload(provider.unload)
