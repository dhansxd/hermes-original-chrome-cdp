"""User-owned site packages executed through the provider's native browser session."""
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import types
import uuid
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep

from hermes_constants import get_hermes_home

if __package__:
    from .site_apps.flow.downloads import verify as verify_media
    from .rolling import HANDOFF_MODES, JobStore, RollingJob
    from .remote_downloads import collect as collect_remote_download
else:
    from site_apps.flow.downloads import verify as verify_media
    from rolling import HANDOFF_MODES, JobStore, RollingJob
    from remote_downloads import collect as collect_remote_download


STATUSES = {'ok', 'running', 'quota_exhausted', 'needs_inspection', 'failed'}
OBSERVATION_INTERVAL = 15


if __package__:
    from .site_learning import LEARNED_ACTIONS, cached_action, fallback
else:
    from site_learning import LEARNED_ACTIONS, cached_action, fallback


WINDOW_ACTIONS = ('keep_window', 'list_windows', 'close_window')
CONTROL_ACTIONS = ('list', 'describe', 'run', 'observe', 'record_missing_control', 'enable', 'disable', 'remove',
                   *WINDOW_ACTIONS, *LEARNED_ACTIONS)
CONTROL_FIELDS = {'action', 'app', 'operation', 'params', 'job', 'target_profile', 'session'}
CONTROL_SCHEMA = {
    'type': ['string', 'null'],
    'description': 'A JSON request for an installed site or a kept Chrome window; leave empty for ordinary Python. '
                   'Examples: {"action":"list"}, {"action":"describe","app":"gemini"}, '
                   '{"app":"gemini","operation":"click","params":{"control":"tools_menu"}}. '
                   'Each installed site defines its own params. Window actions are keep_window, list_windows and close_window. '
                   'Use the current browser session for keep_window and the returned session ID for close_window.',
}


def has_site_request(args):
    control = args.get('site_control')
    if isinstance(control, str):
        control = control.strip()
        if not control or control == 'null':
            return False
        return control != '{}' or not args.get('code')
    return control is not None and (bool(control) or not args.get('code'))


def progress_control(app, can_read_result):
    return {'app': app, 'operation': 'read_result'} if can_read_result else {'app': app, 'action': 'observe'}


def site_request(args):
    command = args['site_control']
    if isinstance(command, str):
        try:
            command = json.loads(command)
        except ValueError as error:
            raise ValueError('Pass the site request as JSON text in site_control.') from error
    if not isinstance(command, dict) or set(command) - CONTROL_FIELDS:
        raise ValueError('Use action, app, operation, params, job, target_profile or session in the site request.')
    command = {key: value for key, value in command.items() if value is not None and value != ''}
    action = command.get('action', 'run' if 'operation' in command else 'list')
    if action not in CONTROL_ACTIONS:
        raise ValueError('Choose an action from the site_control schema.')
    if action in WINDOW_ACTIONS and set(command) - {'action', 'session'}:
        raise ValueError('Window actions accept only action and session.')
    if action in LEARNED_ACTIONS and set(command) - {'action', 'session', 'params'}:
        raise ValueError('Learned controls apply to the currently owned page.')
    return {**command, 'action': action}


def app_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value):
        raise ValueError('Choose an extension ID from the site control catalog.')
    return value


def uses_rolling(metadata, args):
    if metadata.get('profile_policy') != 'rotate_on_limit':
        return False
    parameters = metadata.get('rolling_parameters')
    if parameters is None:
        return True
    operation = args.get('operation')
    parameter = parameters.get(operation) if isinstance(operation, str) else None
    params = args.get('params', {})
    return parameter is not None and (args.get('job') is not None
        or args.get('target_profile') is not None or (isinstance(params, dict) and parameter in params))


def observe_page(context, selector):
    """Inspect the live owned page without navigating or submitting work."""
    expression = """(selector => {
        const visible = element => element.getClientRects().length > 0 &&
            element.checkVisibility({visibilityProperty: true, opacityProperty: true});
        const text = element => (element.innerText || element.getAttribute('aria-label') || '').trim();
        const root = document.querySelector('main, [role="main"]') || document.body;
        const status = Array.from(document.querySelectorAll('[role="status"], [role="progressbar"], [aria-busy="true"]'))
            .filter(visible).slice(-5).map(text).join(' ').slice(-600);
        const result = selector ? Array.from(document.querySelectorAll(selector)).filter(visible) : [];
        const node = result.length === 1 ? result[0] : null;
        let evidence = null;
        if (node && !node.closest('[aria-busy="true"]') && !node.matches('html, body, main, [role="main"]')) {
            if (node instanceof HTMLImageElement) evidence = node.complete && node.naturalWidth ? node.tagName : null;
            else evidence = text(node).slice(-1200) || null;
        }
        return {visible: [status, root ? text(root).slice(-1800) : ''].filter(Boolean).join('\\n'),
                result: evidence};
    })""" + '(' + json.dumps(selector) + ')'
    response = context.browser_exec('import json\nprint(json.dumps(js(' + repr(expression) + ')))')
    if not response.get('success') or response.get('exit_code', 0):
        raise RuntimeError(response.get('error') or response.get('output') or 'Could not inspect the current page.')
    page = json.loads(response['output'])
    if not isinstance(page, dict) or 'result' not in page or not isinstance(page.get('visible'), str):
        raise ValueError('The current page did not return a DOM observation.')
    return page


def read_package(root, identifier):
    directory = root / app_identifier(identifier)
    path = directory / 'app.json'
    original = path.read_bytes()
    metadata = json.loads(original)
    if not isinstance(metadata, dict) or metadata.get('id') != identifier:
        raise ValueError('Extension metadata must identify its directory.')
    if type(metadata.get('api_version')) is not int or metadata['api_version'] != 1:
        raise ValueError('This extension requires a supported api_version of 1.')
    operations = metadata.get('operations')
    if metadata.get('profile_policy') is not None and metadata['profile_policy'] != 'rotate_on_limit':
        raise ValueError('Supported profile_policy is rotate_on_limit, or omit it for ordinary execution.')
    if ('handoff_mode' in metadata and (metadata['handoff_mode'] not in HANDOFF_MODES
                                       or metadata.get('profile_policy') != 'rotate_on_limit')):
        raise ValueError('handoff_mode must be manual or automatic and requires rotate_on_limit.')
    rolling_parameters = metadata.get('rolling_parameters')
    if 'rolling_parameters' in metadata and (not isinstance(rolling_parameters, dict) or not rolling_parameters
            or metadata.get('profile_policy') != 'rotate_on_limit'):
        raise ValueError('rolling_parameters must map operations to opt-in parameters for rotate_on_limit.')
    if not isinstance(operations, dict):
        raise ValueError('Extension operations must be an object.')
    for name, details in operations.items():
        if not isinstance(name, str) or not name or not isinstance(details, dict):
            raise ValueError('Each extension operation needs a name and metadata object.')
        parameters = details.get('parameters', {'type': 'object'})
        if not isinstance(parameters, dict) or parameters.get('type') != 'object':
            raise ValueError('Operation parameters must describe an object.')
    for operation, parameter in (rolling_parameters or {}).items():
        parameter_schema = operations.get(operation, {}).get('parameters', {}).get('properties', {})
        if not isinstance(parameter, str) or not isinstance(parameter_schema, dict) or parameter not in parameter_schema:
            raise ValueError('Each rolling_parameters entry must name a declared operation parameter.')
    source = (directory / 'app.py').read_bytes()
    if path.read_bytes() != original:
        raise RuntimeError('Extension metadata changed while loading. Inspect the updated package.')
    return directory, metadata, source


class _FreshSource(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        # mtime/size bytecode caches miss rapid edits with the same file size.
        return self.source_to_code(self.get_data(self.path), self.path)


class _PackageImports(importlib.abc.MetaPathFinder):
    def __init__(self, name, directory):
        self.name, self.directory = name, directory

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(self.name + '.'):
            return None
        relative = fullname[len(self.name) + 1:].split('.')
        location = self.directory.joinpath(*relative)
        package = location / '__init__.py'
        source = package if package.is_file() else location.with_suffix('.py')
        if not source.is_file():
            return None
        return importlib.util.spec_from_file_location(
            fullname, source, loader=_FreshSource(fullname, str(source)),
            submodule_search_locations=[str(location)] if source == package else None)


@contextmanager
def loaded_package(directory, source):
    name = '_original_chrome_app_' + uuid.uuid4().hex
    module = types.ModuleType(name)
    module.__file__ = str(directory / 'app.py')
    module.__package__ = name
    module.__path__ = [str(directory)]
    finder = _PackageImports(name, directory)
    sys.modules[name] = module
    sys.meta_path.insert(0, finder)
    try:
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
        if not callable(getattr(module, 'run', None)):
            raise ValueError('Extension app.py must define run(context, operation, params).')
        yield module
    finally:
        sys.meta_path.remove(finder)
        for key in list(sys.modules):
            if key == name or key.startswith(name + '.'):
                sys.modules.pop(key, None)


class AppContext:
    def __init__(self, host, identifier, session, task_id, session_id):
        self.host, self.app, self.session = host, identifier, session
        self.task_id, self.session_id = task_id, session_id
        self.active = True
        self.turn_id = self._choice().turn_id

    def _choice(self):
        provider = self.host.provider
        with provider.lock:
            base = provider.profile_routes.get(self.session, self.session)
            choice = provider.profile_choices.get(base)
            if (not self.active or provider.unloading or self.session in provider.finishing
                    or self.host.get_setting('apps_disabled.' + self.app)
                    or choice is None or choice.finished or choice.switching
                    or choice.app_id != self.app
                    or choice.owner[:2] != (self.task_id, self.session_id)
                    or choice.browser_name != self.session
                    or (hasattr(self, 'turn_id') and choice.turn_id != self.turn_id)
                    or self.session not in provider.owners):
                raise RuntimeError('This extension requires its active calling browser session.')
            provider.require_device(choice.device)
            return choice

    @property
    def profile(self):
        return self._choice().profile.id

    @property
    def device(self):
        return self._choice().device

    @property
    def directory(self):
        choice = self._choice()
        if not choice.directory_key:
            choice.directory_key = hashlib.sha256(
                f'{self.task_id}\0{self.session_id}\0{self.session}'.encode()).hexdigest()
        owner = choice.directory_key
        path = self.host.app_data(self.app, choice.device) / owner
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    @property
    def chrome_profile_directory(self):
        return self.host.provider.data / self.profile

    def _remote_download_record(self, identifier):
        key = hashlib.sha256(identifier.encode()).hexdigest()
        return self.directory / 'downloads' / (key + '.json')

    def remote_download_started(self, identifier):
        record = self._remote_download_record(identifier)
        if not record.is_file():
            return False
        state = json.loads(record.read_text())
        return bool(state.get('clicked') or state.get('file'))

    def remote_download(self, identifier, action, execute, *, timeout=60):
        record = self._remote_download_record(identifier)
        return collect_remote_download(self, record, action, execute, write_json, timeout)

    def _remote_browser(self):
        provider = self.host.provider
        with provider.lock:
            choice = self._choice()
            desktop = provider.desktop(choice.device)
            sessions = [session for _, session in provider._browser_sessions(self.session)
                        if session.ready and not session.closed and not session.disconnected
                        and session.desktop is desktop and session.profile == choice.profile.id]
        if desktop is None or len(sessions) != 1:
            raise RuntimeError('The extension needs its active Windows Chrome session for file upload.')
        return sessions[0]

    def stage_reference(self, source, digest):
        return self._remote_browser().stage_upload(source, digest, self._choice)

    def release_reference(self, source, digest):
        self._remote_browser().release_upload(source, digest)

    def verify_video(self, path):
        checked = verify_media({'path': str(path)})
        if not any(stream['codec_type'] == 'video' for stream in checked['media']['streams']):
            raise ValueError('The Chrome download contains no video stream.')
        return checked['media']

    def checkpoint(self, value):
        """Save the package's last known work position outside its source directory."""
        path = write_json(self.directory / 'checkpoint.json', value)
        if getattr(self, '_rolling', None) is not None:
            self._rolling.checkpoint(value)
        return path

    @property
    def job_id(self):
        return self._rolling.record['id'] if getattr(self, '_rolling', None) is not None else None

    def accepted(self, request_id, data=None):
        """Record the provider receipt immediately after a submission is accepted."""
        self._choice()
        if getattr(self, '_rolling', None) is None:
            raise RuntimeError('accepted requires a rotate_on_limit job context.')
        self._rolling.accepted(request_id, data)

    def select_profile(self, profile):
        provider = self.host.provider
        with provider.lock:
            self._choice()
            base = provider.profile_routes[self.session]
        result = provider.profiles({'action': 'select', 'profile': profile, 'session': base},
                                   task_id=self.task_id, session_id=self.session_id)
        if not result.get('success'):
            raise RuntimeError(result.get('error', 'App profile selection failed.'))
        with provider.lock:
            choice = provider.profile_choices.get(base)
            if (choice is None or choice.finished or provider.unloading
                    or choice.owner[:2] != (self.task_id, self.session_id)
                    or choice.turn_id != self.turn_id):
                raise RuntimeError('The calling app session has finished.')
            self.session = choice.browser_name
            provider.owners[self.session] = choice.owner
            self._choice()

    def browser_exec(self, code, *, timeout_s=120):
        self._choice()
        result = self.host.dispatch('browser_exec', {
            'session': self.session, 'code': self.host.prepare_code(code),
            'timeout_s': timeout_s,
        }, task_id=self.task_id, session_id=self.session_id, parent_agent=None)
        return json.loads(result) if isinstance(result, str) else result


class AppHost:
    def __init__(self, provider, get_setting, dispatch, prepare_code, data_dir, *, bundled_source=None):
        self.provider, self.get_setting, self.dispatch = provider, get_setting, dispatch
        self.prepare_code, self.data_dir = prepare_code, data_dir
        self.controls_enabled = True
        self.active = set()
        self.changing = set()
        self.bundled_source = bundled_source

    def app_data(self, identifier, device='local'):
        root = self.data_dir() / 'browser-apps' / identifier
        if device != 'local':
            root /= 'device-' + hashlib.sha256(device.encode()).hexdigest()[:24]
        return root

    def jobs(self, identifier, device='local'):
        return JobStore(self.app_data(identifier, device) / 'jobs', write_json)

    def record_missing_control(self, args, task_id, session_id):
        identifier = app_identifier(args.get('app'))
        session = args.get('session')
        if not isinstance(session, str) or not session:
            raise ValueError('Pass the exact app session used for the fallback.')
        params = args.get('params', {})
        if not isinstance(params, dict) or set(params) != {'page_or_mode', 'control', 'fallback'}:
            raise ValueError('Provide page_or_mode, control, and fallback.')
        finding = {'app': identifier}
        for field in ('page_or_mode', 'control'):
            value = params[field]
            if not isinstance(value, str) or not 0 < len(value.strip()) <= 200:
                raise ValueError(f'{field} must be a short description (1–200 characters).')
            finding[field] = value.strip()
        if params['fallback'] not in ('dom', 'screenshot'):
            raise ValueError('fallback must be dom or screenshot.')
        finding['fallback'] = params['fallback']
        with self.provider.lock:
            # Validate the existing owner without opening a browser or calling the package.
            AppContext(self, identifier, session, task_id, session_id)
            directory = self.data_dir() / 'browser-apps' / identifier
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = directory / 'missing-controls.jsonl'
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, 'a', encoding='utf-8') as stream:
                stream.write(json.dumps(finding, ensure_ascii=False) + '\n')
        return {'success': True, 'status': 'ok', 'finding': finding, 'path': str(path)}

    def seed_packages(self, source):
        """Install missing bundled packages, preserving user source and lifecycle choices."""
        import fcntl
        source = Path(source)
        if not source.is_dir() or source.resolve() == self.root.resolve():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / '.install.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for directory in sorted(source.iterdir()):
                if not directory.is_dir() or directory.name.startswith('.'):
                    continue
                identifier = app_identifier(directory.name)
                destination = self.root / identifier
                if os.path.lexists(destination) or self.get_setting('apps_disabled.' + identifier):
                    continue
                read_package(source, identifier)
                temporary = Path(tempfile.mkdtemp(prefix='.install-', dir=self.root))
                try:
                    shutil.copytree(directory, temporary, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                    temporary.rename(destination)
                finally:
                    shutil.rmtree(temporary, ignore_errors=True)

    def prepare_call(self, tool_name, args, task_id, **context):
        if tool_name != 'browser_exec' or not has_site_request(args):
            return self.provider.prepare_call(tool_name, args, task_id, **context)
        config = context.get('config')
        if config is None:
            from hermes_cli.config import load_config_readonly
            config = load_config_readonly()
        if config.get('browser', {}).get('cloud_provider') != self.provider.name:
            return None
        if not self.controls_enabled:
            return {'action': 'block', 'message': 'Enable the plugin’s tools.override capability in Hermes to use site controls.'}
        try:
            command = site_request(args)
        except ValueError as error:
            return {'action': 'block', 'message': str(error)}
        if 'session' in command:
            if args.get('session') and args['session'] != command['session']:
                return {'action': 'block', 'message': 'Use one browser session for this control.'}
            args = {**args, 'session': command['session']}
        if command['action'] in LEARNED_ACTIONS:
            if args.get('code'):
                return {'action': 'block', 'message': 'Call a learned control or run native code separately.'}
            return self.provider.prepare_call(tool_name, {'session': args.get('session')}, task_id,
                                              require_existing=True, allow_current_app=True, **context)
        if command['action'] not in {'run', 'observe', 'record_missing_control'}:
            # Catalog and lifecycle commands do not acquire a browser or choose a profile.
            return {'action': 'modify', 'args': {'session': args.get('session') or 'default'}}
        if command['action'] == 'run':
            try:
                if self.bundled_source:
                    self.seed_packages(self.bundled_source)
                _, metadata, _ = read_package(self.root, app_identifier(command.get('app')))
                context['defer_profile'] = uses_rolling(metadata, command)
            except (OSError, ValueError, RuntimeError):
                pass  # handle() returns the package error to Hermes.
        context['require_existing'] = command['action'] in {'observe', 'record_missing_control'}
        route = {'session': args.get('session'), 'app': command.get('app'), 'local': args.get('local')}
        if command['action'] == 'record_missing_control' and args.get('code'):
            route['code'] = args['code']
        return self.provider.prepare_call(tool_name, route, task_id, **context)

    def execute(self, args, native, **context):
        if not has_site_request(args):
            return native(args, **context)
        from hermes_cli.config import load_config_readonly
        config = load_config_readonly()
        if config.get('browser', {}).get('cloud_provider') != self.provider.name:
            return native(args, **context)
        if not self.controls_enabled:
            return json.dumps({'success': False, 'error': 'Site controls require the enabled Original Chrome provider.'})
        if not context.get('task_id') or not context.get('session_id'):
            return json.dumps({'success': False, 'error': 'Site controls require the owning Hermes task and session.'})
        if args.get('local'):
            return json.dumps({'success': False, 'error': 'Site controls use the selected Original Chrome provider.'})
        try:
            command = site_request(args)
        except ValueError as error:
            return json.dumps({'success': False, 'error': str(error)})
        if command['action'] in LEARNED_ACTIONS:
            return self.execute_learned(command, args, native, context)
        result = self.handle({**command, 'session': args.get('session')}, **context)
        if command['action'] == 'record_missing_control' and args.get('code') and json.loads(result).get('success'):
            return native({k: v for k, v in args.items() if k != 'site_control'}, **context)
        return result

    def execute_learned(self, command, args, native, context):
        import sqlite3
        attempted = False

        def run_expression(expression, *, click=False, until=None):
            nonlocal attempted
            attempted |= click
            code = 'import json\n'
            if until is None:
                code += 'print(json.dumps(js(' + repr(expression) + ')))'
            else:
                code += (
                    'for _attempt in range(15):\n'
                    '    try:\n'
                    '        _observed = js(' + repr(expression) + ')\n'
                    '    except Exception:\n'
                    '        _observed = None\n'
                    '    if _observed == ' + repr(until) + ':\n'
                    '        break\n'
                    '    wait(.1)\n'
                    'print(json.dumps(_observed))'
                )
            result = native({'session': args['session'], 'code': code}, **context)
            data = json.loads(result) if isinstance(result, str) else result
            if not isinstance(data, dict) or not data.get('success'):
                raise RuntimeError('Could not verify the current page.')
            return json.loads(data['output'].strip())

        try:
            catalog = self.provider.learning_catalog()
            if catalog is None:
                raise RuntimeError('Learned controls are available on local Chrome.')
            result = cached_action(catalog, command, run_expression, package_control=self.click_mapping)
            if (command['action'] == 'click' and not result.get('dispatched')
                    and result.get('reason') in {'unmatched', 'obscured'}):
                shot = native({'session': args['session'], 'code': 'print(capture_screenshot(max_dim=1200))'},
                              **context)
                shot = json.loads(shot) if isinstance(shot, str) else shot
                if isinstance(shot, dict):
                    source = shot.get('meta', {}) if shot.get('_multimodal') else shot
                    path = source.get('screenshot_path')
                    if path:
                        result.update(source='screenshot', screenshot_path=path,
                                      next='Locate the requested target in this screenshot before dispatching.')
                        if shot.get('_multimodal'):
                            summary = json.dumps(result, ensure_ascii=False)
                            images = [item for item in shot.get('content', []) if item.get('type') == 'image_url']
                            return {**shot, 'text_summary': summary,
                                    'content': [{'type': 'text', 'text': summary}, *images]}
        except (KeyError, TypeError, OSError, sqlite3.Error, ValueError, RuntimeError) as error:
            result = fallback(str(error), dispatched=attempted)
        return json.dumps(result, ensure_ascii=False)

    def click_mapping(self, origin, target):
        """Find the enabled package for the current site without executing it."""
        if self.bundled_source:
            self.seed_packages(self.bundled_source)
        matches = []
        for manifest in sorted(self.root.glob('*/app.json')):
            identifier = manifest.parent.name
            if identifier in self.changing or self.get_setting('apps_disabled.' + identifier):
                continue
            try:
                _, metadata, _ = read_package(self.root, identifier)
            except (OSError, RuntimeError, ValueError):
                continue
            mapping = metadata.get('click_targets')
            if not isinstance(mapping, dict) or mapping.get('origin') != origin:
                continue
            controls = mapping.get('controls')
            spec = controls.get(target) if isinstance(controls, dict) else None
            if (not isinstance(spec, dict) or 'selector' not in spec or set(spec) - {'selector', 'opens'}
                    or not all(isinstance(value, str) and 0 < len(value) <= 512
                               and value.isprintable() for value in spec.values())):
                continue
            matches.append(spec)
        return matches[0] if len(matches) == 1 else None

    def manage(self, action, identifier):
        directory = self.root / identifier
        with self.provider.lock:
            if self.provider.unloading:
                raise RuntimeError('Original Chrome provider is unloading.')
            if identifier in self.changing:
                return {'status': 'running', 'success': True, 'app': identifier,
                        'cleanup_pending': True}
            if action == 'enable':
                read_package(self.root, identifier)
                if not self.get_setting('apps_disabled.' + identifier):
                    return {'status': 'ok', 'success': True, 'app': identifier, 'enabled': True}
            elif not directory.is_dir() and not self.get_setting('apps_disabled.' + identifier):
                raise ValueError('Choose a package from the site control catalog.')
            if self.provider.set_setting is None:
                raise RuntimeError('The plugin configuration writer is unavailable.')
            self.changing.add(identifier)
            if action != 'enable':
                try:
                    self.provider.set_setting('apps_disabled.' + identifier, True)
                except Exception:
                    self.changing.discard(identifier)
                    raise
            names = [choice.browser_name or base for base, choice in self.provider.profile_choices.items()
                     if choice.app_id == identifier]
        try:
            for name in names:
                self.provider.finish(session_name=name, interrupted=True)
            with self.provider.lock:
                pending = any(context.app == identifier for context in self.active)
                pending |= any(choice.app_id == identifier for choice in self.provider.profile_choices.values())
                result = {'status': 'running' if pending else 'ok', 'success': True,
                          'app': identifier, 'enabled': False, 'cleanup_pending': pending,
                          'data_directory': str(self.data_dir() / 'browser-apps' / identifier)}
                if pending:
                    return result
                if action == 'enable':
                    self.provider.app_instances[identifier] = uuid.uuid4().hex
                    self.provider.set_setting('apps_disabled.' + identifier, False)
                    result['enabled'] = True
            if action == 'remove':
                if directory.is_symlink():
                    directory.unlink()
                elif directory.exists():
                    shutil.rmtree(directory)
                result['removed'] = True
            return result
        finally:
            with self.provider.lock:
                self.changing.discard(identifier)

    @property
    def root(self):
        configured = self.get_setting('apps_directory')
        if configured is None or configured == '':
            return get_hermes_home() / 'browser-apps'
        if not isinstance(configured, str):
            raise ValueError('apps_directory must name the user extension directory.')
        return Path(configured).expanduser().resolve()

    def running_work(self, task_id, session_id, turn_id=None):
        if not (task_id and session_id):
            return {}
        with self.provider.lock:
            return {choice.browser_name: (choice.app_id, choice.running, choice.can_read_result)
                    for choice in self.provider.profile_choices.values()
                    if not choice.finished and choice.pending and choice.running is not None
                    and choice.owner[:2] == (task_id, session_id)
                    and (turn_id is None or choice.turn_id == turn_id)}

    def handle(self, args, task_id='', session_id='', **kwargs):
        context = None
        try:
            action = args.get('action', 'list')
            if action in WINDOW_ACTIONS:
                result = self.provider.window_control(action, args.get('session'), task_id, session_id,
                                                      session_key=kwargs.get('session_key', ''))
                return json.dumps(result, ensure_ascii=False)
            if self.bundled_source:
                self.seed_packages(self.bundled_source)
            if action == 'list':
                entries = []
                directories = sorted(self.root.iterdir()) if self.root.exists() else []
                for directory in directories:
                    if not directory.is_dir() or directory.name.startswith('.'):
                        continue
                    try:
                        _, metadata, _ = read_package(self.root, directory.name)
                        entries.append({'id': directory.name, 'available': True,
                                        'enabled': not bool(self.get_setting('apps_disabled.' + directory.name)),
                                        'name': metadata.get('name', directory.name),
                                        'operations': list(metadata['operations'])})
                    except (OSError, ValueError, RuntimeError) as error:
                        entries.append({'id': directory.name, 'available': False,
                                        'error': str(error)})
                result = {'success': True, 'status': 'ok', 'directory': str(self.root), 'apps': entries}
            elif action in {'enable', 'disable', 'remove'}:
                result = self.manage(action, app_identifier(args.get('app')))
            elif action == 'record_missing_control':
                result = self.record_missing_control(args, task_id, session_id)
            elif action in {'describe', 'run', 'observe'}:
                identifier = app_identifier(args.get('app'))
                directory, metadata, source = read_package(self.root, identifier)
                if action == 'describe':
                    guide = directory / 'SKILL.md'
                    result = {'success': True, 'status': 'ok', 'app': metadata,
                              'enabled': not bool(self.get_setting('apps_disabled.' + identifier)),
                              'data_directory': str(self.data_dir() / 'browser-apps' / identifier),
                              'guide': guide.read_text() if guide.exists() else ''}
                    if metadata.get('profile_policy') == 'rotate_on_limit':
                        try:
                            device = self.provider.default_device()
                            result['jobs'] = self.jobs(identifier, device).summaries(session_id)
                        except (OSError, ValueError) as error:
                            result['jobs_error'] = str(error)
                    session = args.get('session')
                    if isinstance(session, str):
                        active = self.running_work(task_id, session_id, kwargs.get('turn_id')).get(session)
                        if active and active[0] == identifier:
                            operation, job = active[1]
                            result['running_work'] = {'status': 'running', 'session': session,
                                'operation': operation, 'job': job,
                                'message': 'Continue checking this existing work in this turn. Use the same '
                                           'session and job, without submitting again. Verify the outcome '
                                           'and finish any requested delivery before the final response.'}
                            result['running_work']['next_control'] = progress_control(identifier, active[2])
                else:
                    operation = args.get('operation')
                    reader = metadata['operations'].get('read_result')
                    can_read = reader is not None and not reader.get('parameters', {}).get('required')
                    if action == 'run' and (not isinstance(operation, str) or operation not in metadata['operations']):
                        raise ValueError('Choose an operation from the site guide.')
                    params = args.get('params', {})
                    if not isinstance(params, dict):
                        raise ValueError('Extension params must be an object.')
                    with self.provider.lock:
                        if identifier in self.changing:
                            raise RuntimeError('This extension is changing lifecycle state.')
                        context = AppContext(self, identifier, args.get('session', ''), task_id, session_id)
                        context._binding = context._choice()
                        if action == 'observe':
                            # Hermes supplies the turn in pre_tool_call; its native handler can omit it.
                            if not context._binding.running or kwargs.get('turn_id', context.turn_id) != context.turn_id:
                                raise ValueError('No running work in this turn and site session.')
                            observed_work = (context._binding.running, context._binding.running_since)
                        context._binding.active += 1
                        self.active.add(context)
                    # Pace observations of work in progress and allow Stop to invalidate the context.
                    while True:
                        with self.provider.lock:
                            choice = context._choice()
                            observe = (choice.running is not None
                                       and (action == 'observe' or operation == 'read_result'
                                            or (choice.running[1] and args.get('job') == choice.running[1])))
                            remaining = choice.last_observation + OBSERVATION_INTERVAL - monotonic() if observe else 0
                        if remaining <= 0:
                            break
                        sleep(min(remaining, 0.25))
                    if action == 'observe':
                        return json.dumps(self.observe_running(context, params, observed_work), ensure_ascii=False)
                    with loaded_package(directory, source) as module:
                        rolling = uses_rolling(metadata, args)
                        if rolling:
                            mode = metadata.get('handoff_mode')
                            if mode is not None:
                                configured = self.get_setting('handoff_mode.' + identifier)
                                if configured is not None:
                                    mode = configured
                                if mode not in HANDOFF_MODES:
                                    raise ValueError('handoff_mode.' + identifier + ' must be manual or automatic.')
                            result = RollingJob(self, context, module, mode=mode).execute(
                                operation, params, args.get('job'), target_profile=args.get('target_profile'))
                        else:
                            if args.get('job') or args.get('target_profile') is not None:
                                raise ValueError('Job recovery requires a rotate_on_limit package.')
                            value = module.run(context, operation, params)
                            if not isinstance(value, dict) or 'status' not in value:
                                value = {'status': 'ok', 'data': value}
                            if value['status'] not in STATUSES:
                                raise ValueError('Extension result must use a documented status.')
                            result = {**value, 'success': value['status'] in {'ok', 'running'},
                                      'app': identifier, 'operation': operation,
                                      'session': context.session, 'profile': context.profile}
                            with self.provider.lock:
                                context._choice().pending = value['status'] in {'running', 'needs_inspection'}
                                write_json(context.directory / 'result.json', result)
                    with self.provider.lock:
                        choice = context._choice()
                        if result['status'] == 'running':
                            now = monotonic()
                            if choice.running is None:
                                choice.running_since = now
                                choice.result_selector = ''
                            choice.running = (result.get('operation', operation), result.get('job'))
                            choice.can_read_result = can_read and not rolling
                            choice.last_observation = now
                            result['running_seconds'] = int(now - choice.running_since)
                            if not choice.running[1]:
                                result.setdefault('next_control', progress_control(identifier, choice.can_read_result))
                        elif choice.running is not None:
                            active_operation, active_job = choice.running
                            if active_job:
                                observed = active_job == result.get('job')
                            else:
                                observed = (operation == 'read_result'
                                            or (active_operation != 'click' and operation == active_operation))
                            if observed and result['status'] == 'needs_inspection' and not active_job:
                                choice.can_read_result = False
                                result['next_control'] = {'app': identifier, 'action': 'observe'}
                            elif observed:
                                choice.running = None
                        if choice.running is not None:
                            choice.pending = True
            else:
                raise ValueError('Choose an action from the site control schema.')
            return json.dumps(result, ensure_ascii=False)
        except Exception as error:
            return json.dumps({'success': False, 'status': 'failed',
                               'app': args.get('app'), 'operation': args.get('operation'),
                               'error': {'type': type(error).__name__, 'message': str(error)}},
                              ensure_ascii=False)
        finally:
            if context is not None:
                with self.provider.lock:
                    if context in self.active:
                        self.active.remove(context)
                        context._binding.active -= 1
                    context.active = False

    def observe_running(self, context, params, observed_work):
        choice = context._choice()
        selector = params.get('result_selector', choice.result_selector)
        if set(params) - {'result_selector'} or not isinstance(selector, str):
            raise ValueError('Use an optional CSS result_selector for the visible, finished result of this request.')
        page = observe_page(context, selector)
        with self.provider.lock:
            choice = context._choice()
            if (choice.running, choice.running_since) != observed_work:
                raise RuntimeError('The observed work changed during the page read.')
            operation, job = choice.running
            now = monotonic()
            choice.last_observation = now
            choice.result_selector = selector
            result = {'success': True, 'status': 'running', 'session': context.session, 'page': page,
                      'app': context.app, 'operation': operation, 'running_seconds': int(now - choice.running_since)}
            if job:
                result.update(job=job, next_control={'app': context.app, 'operation': operation, 'job': job},
                              message='Check the existing job using its job ID to verify its result.')
            elif selector and page['result'] is not None:
                result['status'] = 'ok'
                write_json(context.directory / 'result.json', {
                    'success': True, 'status': 'ok', 'app': context.app, 'session': context.session,
                    'operation': operation, 'data': {'result': page['result']},
                })
                choice.pending = False
                choice.running = None
            else:
                result['next_control'] = progress_control(context.app, choice.can_read_result and not selector)
                result['message'] = ('Continue this task in the same session. Supply params.result_selector on '
                                     'observe when you identify the unique finished result for this submission. '
                                     'Use DOM or screenshot as needed. Finish the requested delivery.')
            return result


def write_json(path, value):
    encoded = json.dumps(value, ensure_ascii=False)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(encoded)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(path)
