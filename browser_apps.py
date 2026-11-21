"""User-owned site packages executed through the provider's native browser session."""
import ast
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
from copy import copy
from pathlib import Path
from time import monotonic, sleep

from hermes_constants import get_hermes_home

if __package__:
    from .site_apps.flow.downloads import verify as verify_media
    from .rolling import HANDOFF_MODES, JobStore, RollingJob
else:
    from site_apps.flow.downloads import verify as verify_media
    from rolling import HANDOFF_MODES, JobStore, RollingJob


STATUSES = {'ok', 'running', 'quota_exhausted', 'needs_inspection', 'failed'}
OBSERVATION_INTERVAL = 15


CONTROL_ACTIONS = ('list', 'describe', 'run', 'observe', 'record_missing_control', 'enable', 'disable', 'remove')
CONTROL_FIELDS = {'action', 'app', 'operation', 'params', 'job', 'target_profile', 'session'}
CONTROL_SCHEMA = {
    'type': ['string', 'null'],
    'description': 'A JSON request for an installed site; leave empty for ordinary Python. '
                   'Examples: {"action":"list"}, {"action":"describe","app":"gemini"}, '
                   '{"app":"gemini","operation":"click","params":{"control":"tools_menu"}}. '
                   'Each installed site defines its own params.',
}


def has_site_request(args):
    control = args.get('site_control')
    if isinstance(control, str):
        control = control.strip()
        if not control or control == 'null':
            return False
        return control != '{}' or not args.get('code')
    return control is not None and (bool(control) or not args.get('code'))


def reads_site_progress(node):
    if isinstance(node, ast.Subscript):
        slice_nodes = (ast.Slice, ast.Constant, ast.UnaryOp, ast.UAdd, ast.USub)
        return all(isinstance(part, slice_nodes) for part in ast.walk(node.slice)) and reads_site_progress(node.value)
    if not isinstance(node, ast.Call) or node.keywords:
        return False
    if isinstance(node.func, ast.Attribute):
        return (node.func.attr in {'split', 'strip'}
                and all(isinstance(arg, ast.Constant) for arg in node.args)
                and reads_site_progress(node.func.value))
    if not isinstance(node.func, ast.Name):
        return False
    if node.func.id in {'dom', 'page_info'}:
        return not node.args
    return (node.func.id == 'js' and len(node.args) == 1 and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in ('document.body.innerText', 'document.body.textContent'))


def waits_for_site_progress(tree):
    """Recognize the plain sleep-and-read scripts emitted for an already running site task."""
    if len(tree.body) < 3:
        return False
    source, wait, *reads = tree.body
    if isinstance(source, ast.Import) and [(name.name, name.asname) for name in source.names] == [('time', None)]:
        sleep_name = 'time.sleep'
    elif (isinstance(source, ast.ImportFrom) and source.level == 0 and source.module == 'time'
          and [(name.name, name.asname) for name in source.names] == [('sleep', None)]):
        sleep_name = 'sleep'
    else:
        return False
    call = wait.value if isinstance(wait, ast.Expr) else None
    if (not isinstance(call, ast.Call) or ast.unparse(call.func) != sleep_name or call.keywords
            or len(call.args) != 1 or not isinstance(call.args[0], ast.Constant)
            or type(call.args[0].value) not in (int, float) or call.args[0].value < OBSERVATION_INTERVAL):
        return False
    for read in reads:
        call = read.value if isinstance(read, ast.Expr) else None
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != 'print'
                or call.keywords or len(call.args) != 1 or not reads_site_progress(call.args[0])):
            return False
    return True


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
            return choice

    @property
    def profile(self):
        return self._choice().profile.id

    @property
    def directory(self):
        choice = self._choice()
        if not choice.directory_key:
            choice.directory_key = hashlib.sha256(
                f'{self.task_id}\0{self.session_id}\0{self.session}'.encode()).hexdigest()
        owner = choice.directory_key
        path = self.host.data_dir() / 'browser-apps' / self.app / owner
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    @property
    def chrome_profile_directory(self):
        return self.host.provider.data / self.profile

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

    def jobs(self, identifier):
        return JobStore(self.data_dir() / 'browser-apps' / identifier / 'jobs', write_json)

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
            prepared = self.provider.prepare_call(tool_name, args, task_id, **context)
            if tool_name != 'browser_exec' or not prepared or prepared['action'] != 'modify' or not args.get('code'):
                return prepared
            session = prepared['args']['session']
            work = self.running_work(task_id, context.get('session_id'), context.get('turn_id')).get(session)
            if work:
                try:
                    wait = waits_for_site_progress(ast.parse(args['code']))
                except (TypeError, SyntaxError):
                    wait = False
                if wait:
                    app, _, can_read_result = work
                    # Classify the caller's original script, before the provider adds its input guard.
                    prepared['args'].update(code='', site_control=json.dumps(progress_control(app, can_read_result)))
            return prepared
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

    def native_fallback(self, args, native, context, choice):
        code = args.get('code', '')
        try:
            tree = ast.parse(code)
        except (TypeError, SyntaxError):
            return native(args, **context)
        calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        method = ('screenshot' if 'screenshot' in calls else 'dom' if calls.intersection({'js', 'dom', 'page_info', 'click'})
                  else choice.last_ui_inspection)
        marker = ''
        if method and ('click' in code or 'press_key' in calls):
            try:
                directory, _, source = read_package(self.root, choice.app_id)
                with loaded_package(directory, source) as module:
                    observer = getattr(module, 'FALLBACK_CLICK_OBSERVER', None)
                    selectors = getattr(module, 'FALLBACK_CLICK_SELECTORS', {})
            except Exception:
                # Ordinary native browsing remains available if a site's optional observer cannot load.
                return native(args, **context)
            if observer:
                token = uuid.uuid4().hex
                marker = 'HERMES_UI_' + token + '='
                begin = observer + '("begin",' + json.dumps(token) + ',' + json.dumps(selectors) + ')'
                end = observer + '("finish",' + json.dumps(token) + ',{})'
                # Keep the module docstring and future imports before the observation hook.
                split = int(ast.get_docstring(tree) is not None)
                while split < len(tree.body) and isinstance(tree.body[split], ast.ImportFrom) and tree.body[split].module == '__future__':
                    split += 1
                if split == len(tree.body):
                    return native(args, **context)
                setup = ast.parse(f'try:\n    js({begin!r})\nexcept Exception:\n    pass').body
                cleanup = ast.parse(f'try:\n    print({marker!r} + __import__("json").dumps(js({end!r})))'
                                    '\nexcept Exception:\n    pass').body
                tree.body[split:] = [*setup, ast.Try(body=tree.body[split:], handlers=[], orelse=[], finalbody=cleanup)]
                args = {**args, 'code': ast.unparse(tree)}
        response = native(args, **context)
        if not (method or marker):
            return response
        try:
            result = json.loads(response) if isinstance(response, str) else response
        except ValueError:
            return response
        if not isinstance(result, dict):
            return response
        if result.get('success') and not result.get('exit_code', 0):
            choice.last_ui_inspection = method
        if not marker:
            return response
        output, separator, tail = (result.get('output') or '').rpartition(marker)
        if not separator:
            return response
        result['output'] = output
        try:
            findings = [(row['page_or_mode'], row['control']) for row in (json.loads(tail) or [])]
        except (ValueError, TypeError, KeyError):
            findings = []
        for mode, label in findings:
            try:
                self.record_missing_control({'app': choice.app_id, 'session': args['session'], 'params': {
                    'page_or_mode': mode, 'control': label, 'fallback': method}}, context['task_id'], context['session_id'])
            except (OSError, ValueError, RuntimeError) as error:
                # The click has already happened. Report the recording error independently.
                result['missing_control_error'] = str(error)
                break
        return json.dumps(result, ensure_ascii=False) if isinstance(response, str) else result

    def execute(self, args, native, **context):
        if not has_site_request(args):
            session = args.get('session')
            with self.provider.lock:
                choice = self.provider.profile_choices.get(self.provider.profile_routes.get(session)) if isinstance(session, str) else None
                owned = (choice and not choice.finished and not choice.active and choice.app_id
                         and choice.owner[:2] == (context.get('task_id'), context.get('session_id')))
            return self.native_fallback(args, native, context, choice) if owned else native(args, **context)
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
        result = self.handle({**command, 'session': args.get('session')}, **context)
        if command['action'] == 'record_missing_control' and args.get('code') and json.loads(result).get('success'):
            return native({k: v for k, v in args.items() if k != 'site_control'}, **context)
        return result

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

    def continue_running(self, request, next_call, task_id='', session_id='', turn_id='', api_mode='', **kwargs):
        response = next_call(request)
        if not turn_id or api_mode != 'chat_completions' or not getattr(response, 'choices', None):
            return response
        choice = response.choices[0]
        message = getattr(choice, 'message', None)
        if (str(choice.finish_reason or 'stop').lower() != 'stop' or not getattr(message, 'content', None)
                or getattr(message, 'tool_calls', None) or getattr(message, 'refusal', None)):
            return response
        work = self.running_work(task_id, session_id, turn_id)
        if not work:
            return response
        session, (app, _, can_read_result) = next(iter(work.items()))
        offered = {(tool.get('function') or {}).get('name') for tool in request.get('tools') or []}
        control = progress_control(app, can_read_result)
        arguments = {'site_control': json.dumps(control), 'session': session}
        tool_name = 'browser_exec'
        if tool_name not in offered:
            if 'tool_call' not in offered:
                return response
            tool_name = 'tool_call'
            arguments = {'calls': [{'name': 'browser_exec', 'arguments': arguments}]}
        # Observe through the same paced tool path without repeating the submission.
        from openai.types.chat.chat_completion_message_function_tool_call import ChatCompletionMessageFunctionToolCall
        call = ChatCompletionMessageFunctionToolCall(
            id='call_' + uuid.uuid4().hex[:24], type='function',
            function={'name': tool_name, 'arguments': json.dumps(arguments)})
        response, choice, message = copy(response), copy(choice), copy(message)
        message.content = None
        message.tool_calls = [call]
        choice.message = message
        choice.finish_reason = 'tool_calls'
        response.choices = [choice, *response.choices[1:]]
        return response

    def handle(self, args, task_id='', session_id='', **kwargs):
        context = None
        try:
            if self.bundled_source:
                self.seed_packages(self.bundled_source)
            action = args.get('action', 'list')
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
                            result['jobs'] = self.jobs(identifier).summaries(session_id)
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
                        return json.dumps(self.observe_running(context, params, observed_work, can_read), ensure_ascii=False)
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

    def observe_running(self, context, params, observed_work, can_read):
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
                if can_read and not selector:
                    choice.can_read_result = True
                    result['next_control'] = {'app': context.app, 'operation': 'read_result'}
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
