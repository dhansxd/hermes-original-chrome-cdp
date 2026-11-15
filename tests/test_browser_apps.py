import concurrent.futures
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import browser_apps
import plugin


class BrowserAppTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = {'apps_directory': str(self.root / 'packages'), 'profile_directory': 'Default'}
        self.provider = plugin.ChromeProvider(self.settings.get)
        self.addCleanup(self.provider.unload)
        profile = plugin.ChromeProfile('Default', 'Fixture', (1, 2, 3))
        reader = patch('plugin.get_profile', return_value=profile)
        verifier = patch('plugin.verify_profile', side_effect=lambda value, data: value)
        reader.start()
        verifier.start()
        self.addCleanup(reader.stop)
        self.addCleanup(verifier.stop)
        self.dispatch = Mock(return_value=json.dumps({'success': True, 'output': 'fixture'}))
        self.host = browser_apps.AppHost(
            self.provider, self.settings.get, self.dispatch, plugin.prepare_code,
            lambda: self.root / 'data')
        self.config = {'browser': {'cloud_provider': plugin.NAME,
                                   'auto_local_for_private_urls': False}}

    def package(self, identifier='fixture', source=None, **metadata):
        directory = self.root / 'packages' / identifier
        directory.mkdir(parents=True, exist_ok=True)
        data = {'api_version': 1, 'id': identifier, 'name': 'Fixture package',
                'operations': {'inspect': {'parameters': {'type': 'object'}}}, **metadata}
        (directory / 'app.json').write_text(json.dumps(data))
        (directory / 'app.py').write_text(source or 'def run(context, operation, params):\n    return params\n')
        return directory

    def invoke(self, identifier='fixture', task='A', chat='chat-A', turn='turn', alias='same', **arguments):
        args = {'action': 'run', 'app': identifier, 'operation': 'inspect',
                'session': alias, **arguments}
        with patch.dict(os.environ, {}, clear=True):
            prepared = self.provider.prepare_call(
                browser_apps.APP_TOOL, args, task, session_id=chat,
                session_key='route-' + task, turn_id=turn, config=self.config)
        self.assertEqual(prepared['action'], 'modify', prepared)
        args.update(prepared['args'])
        result = json.loads(self.host.handle(args, task_id=task, session_id=chat))
        return result

    def test_catalog_and_guide_do_not_execute_package(self):
        directory = self.package(source='raise RuntimeError("must not execute on discovery")')
        (directory / 'SKILL.md').write_text('Panduan paket terbaru')
        listing = json.loads(self.host.handle({'action': 'list'}))
        self.assertTrue(listing['apps'][0]['available'])
        details = json.loads(self.host.handle({'action': 'describe', 'app': 'fixture'}))
        self.assertEqual(details['guide'], 'Panduan paket terbaru')
        self.assertEqual(details['app']['operations'], {'inspect': {'parameters': {'type': 'object'}}})
        self.dispatch.assert_not_called()
        self.assertFalse(self.provider.owners)

    def test_missing_directory_is_an_empty_catalog(self):
        result = json.loads(self.host.handle({'action': 'list'}))
        self.assertEqual(result['apps'], [])

    def test_bad_package_does_not_hide_healthy_packages(self):
        self.package('healthy')
        self.package('bad', api_version=2)
        listing = json.loads(self.host.handle({'action': 'list'}))
        states = {entry['id']: entry['available'] for entry in listing['apps']}
        self.assertEqual(states, {'bad': False, 'healthy': True})
        self.assertTrue(self.invoke('healthy')['success'])

    def test_new_package_is_available_without_registering_again(self):
        self.assertEqual(json.loads(self.host.handle({}))['apps'], [])
        self.package('new-site')
        result = self.invoke('new-site', params={'new': True})
        self.assertEqual(result['data'], {'new': True})

    def test_metadata_contract_errors(self):
        for metadata in [dict(api_version=True), dict(id='another'), dict(operations=[]),
                         dict(operations={'inspect': {'parameters': {'type': 'array'}}})]:
            with self.subTest(metadata=metadata):
                self.package(**metadata)
                result = json.loads(self.host.handle({'action': 'describe', 'app': 'fixture'}))
                self.assertFalse(result['success'])

    def test_identifier_cannot_traverse_the_package_directory(self):
        result = json.loads(self.host.handle({'action': 'describe', 'app': '../outside'}))
        self.assertFalse(result['success'])
        self.assertEqual(result['error']['type'], 'ValueError')

    def test_unknown_operation_is_rejected_before_package_code(self):
        self.package(source='raise AssertionError("executed")')
        result = self.invoke(operation='missing')
        self.assertEqual(result['error']['type'], 'ValueError')

    def test_missing_entrypoint_is_reported_and_an_update_recovers(self):
        self.package(source='run = None\n')
        result = self.invoke()
        self.assertFalse(result['success'])
        self.assertEqual(result['error']['type'], 'ValueError')
        self.package()
        self.assertTrue(self.invoke()['success'])

    def test_parameter_object_is_forwarded_without_filtering(self):
        self.package()
        params = {'text': '  preserve whitespace  ', 'files': ['a', 'b'], 'count': 17}
        self.assertEqual(self.invoke(params=params)['data'], params)
        self.assertFalse(self.invoke(params=[])['success'])

    def test_extension_result_status_is_preserved(self):
        self.package(source='def run(context, operation, params):\n    return {"status": "quota_exhausted", "data": params}\n')
        result = self.invoke(params={'provider_message': 'fixture quota'})
        self.assertEqual(result['status'], 'quota_exhausted')
        self.assertFalse(result['success'])
        self.assertEqual(result['data']['provider_message'], 'fixture quota')

    def test_invalid_result_and_code_error_are_reported_with_type(self):
        self.package(source='def run(context, operation, params):\n    raise LookupError("fixture failure")\n')
        result = self.invoke()
        self.assertEqual(result['error']['type'], 'LookupError')
        self.assertEqual((result['app'], result['operation']), ('fixture', 'inspect'))
        self.package(source='def run(context, operation, params):\n    return {"status": "unknown"}\n')
        self.assertEqual(self.invoke()['error']['type'], 'ValueError')

    def test_rapid_same_size_entrypoint_edit_is_loaded(self):
        source = 'def run(context, operation, params):\n    return "first"\n'
        directory = self.package(source=source)
        stamp = (directory / 'app.py').stat().st_mtime_ns
        self.assertEqual(self.invoke()['data'], 'first')
        (directory / 'app.py').write_text(source.replace('first', 'other'))
        os.utime(directory / 'app.py', ns=(stamp, stamp))
        self.assertEqual(self.invoke()['data'], 'other')

    def test_relative_imports_reload_without_stale_bytecode(self):
        directory = self.package(source='from .helpers import value\ndef run(context, operation, params):\n    return value\n')
        helper = directory / 'helpers.py'
        helper.write_text('value = "first"\n')
        stamp = helper.stat().st_mtime_ns
        self.assertEqual(self.invoke()['data'], 'first')
        helper.write_text('value = "other"\n')
        os.utime(helper, ns=(stamp, stamp))
        self.assertEqual(self.invoke()['data'], 'other')
        self.assertFalse(list(directory.rglob('*.pyc')))

    def test_loaded_operation_keeps_its_function_after_source_update(self):
        directory = self.package(source='def run(context, operation, params):\n    return "old"\n')
        with browser_apps.loaded_package(directory, (directory / 'app.py').read_bytes()) as old:
            self.package(source='def run(context, operation, params):\n    return "new"\n')
            self.assertEqual(self.invoke()['data'], 'new')
            self.assertEqual(old.run(None, 'inspect', {}), 'old')

    def test_package_import_names_are_released_even_after_failure(self):
        previous = {name for name in sys.modules if name.startswith('_original_chrome_app_')}
        self.package(source='from .helpers import value\nraise ValueError("fixture")\n')
        (self.root / 'packages/fixture/helpers.py').write_text('value = 1\n')
        self.assertFalse(self.invoke()['success'])
        current = {name for name in sys.modules if name.startswith('_original_chrome_app_')}
        self.assertEqual(previous, current)

    def test_native_dispatch_receives_exact_owner_and_prepared_code(self):
        self.package(source='def run(context, operation, params):\n    return {"ids": [context.task_id, context.session_id, context.turn_id], "native": context.browser_exec("print(page_info())"), "profile": context.profile}\n')
        result = self.invoke(task='child-A', chat='child-chat', turn='child-turn')
        self.assertEqual(result['data']['ids'], ['child-A', 'child-chat', 'child-turn'])
        call = self.dispatch.call_args
        self.assertEqual(call.args[0], 'browser_exec')
        self.assertEqual(call.args[1]['session'], result['session'])
        self.assertIn('print(page_info())', call.args[1]['code'])
        self.assertEqual(call.kwargs, {'task_id': 'child-A', 'session_id': 'child-chat', 'parent_agent': None})
        self.assertEqual(result['profile'], 'Default')
        self.dispatch.assert_called_once()

    def test_apps_agents_and_browser_have_separate_names(self):
        self.package('first')
        self.package('second')
        a = self.invoke('first')
        self.assertEqual(a['session'], self.invoke('first', alias=a['session'])['session'])
        b = self.invoke('second')
        child = self.invoke('first', task='child', chat='child-chat')
        with patch.dict(os.environ, {}, clear=True):
            normal = self.provider.prepare_call('browser_exec', {'session': 'same'}, 'A',
                                                session_id='chat-A', turn_id='turn', config=self.config)
        self.assertEqual(len({a['session'], b['session'], child['session'], normal['args']['session']}), 4)

    def test_context_cannot_be_reused_after_run(self):
        captured = []
        original = browser_apps.AppContext
        def capture(*args):
            context = original(*args)
            captured.append(context)
            return context
        self.package()
        with patch.object(browser_apps, 'AppContext', side_effect=capture):
            self.assertTrue(self.invoke()['success'])
        with self.assertRaisesRegex(RuntimeError, 'active calling browser session'):
            captured[0].browser_exec('print(1)')
        self.dispatch.assert_not_called()

    def test_native_inspection_reuses_only_this_callers_app_session(self):
        self.package()
        app = self.invoke()
        with patch.dict(os.environ, {}, clear=True):
            inspect = self.provider.prepare_call('browser_exec', {'session': app['session']},
                'A', session_id='chat-A', turn_id='turn', config=self.config)
            other = self.provider.prepare_call('browser_exec', {'session': app['session']},
                'B', session_id='chat-B', turn_id='turn', config=self.config)
            replacement = self.provider.prepare_call('browser_exec', {'session': app['session']},
                'A', session_id='chat-A', turn_id='new-turn', config=self.config)
        self.assertEqual(inspect['args']['session'], app['session'])
        self.assertNotEqual(other['args']['session'], app['session'])
        self.assertNotEqual(replacement['args']['session'], app['session'])
        self.assertEqual(self.invoke()['session'], app['session'])

    def test_data_directory_is_scoped_to_app_and_owner(self):
        source = 'def run(context, operation, params):\n    return str(context.directory)\n'
        self.package('first', source)
        self.package('second', source)
        paths = [self.invoke('first')['data'], self.invoke('second')['data'],
                 self.invoke('first', task='B', chat='chat-B')['data']]
        self.assertEqual(len(set(paths)), 3)
        self.assertTrue(all(Path(path).is_dir() for path in paths))

    def test_two_callers_execute_a_package_in_independent_modules(self):
        self.package(source='from pathlib import Path\nvalue = None\ndef run(context, operation, params):\n    global value\n    value = context.task_id\n    context.directory.joinpath("ready").touch()\n    params["barrier"].wait(3)\n    return value\n')
        barrier = threading.Barrier(2)
        # Invoke the native module entry directly so the test barrier stays local.
        def execute(task):
            prepared = self.provider.prepare_call(browser_apps.APP_TOOL,
                {'app': 'fixture', 'action': 'run', 'session': 'same'}, task,
                session_id=task, turn_id='turn', config=self.config)
            context = browser_apps.AppContext(self.host, 'fixture', prepared['args']['session'], task, task)
            directory, _, source = browser_apps.read_package(self.host.root, 'fixture')
            with browser_apps.loaded_package(directory, source) as module:
                return module.run(context, 'inspect', {'barrier': barrier})
        with patch.dict(os.environ, {}, clear=True), concurrent.futures.ThreadPoolExecutor() as pool:
            futures = [pool.submit(execute, task) for task in ('A', 'B')]
            self.assertEqual([future.result(timeout=5) for future in futures], ['A', 'B'])

    def test_unprepared_direct_dispatch_cannot_start_a_browser(self):
        self.package(source='def run(context, operation, params):\n    return context.browser_exec("print(1)")\n')
        result = json.loads(self.host.handle({'action': 'run', 'app': 'fixture',
            'operation': 'inspect', 'session': 'same'}, task_id='A', session_id='chat-A'))
        self.assertFalse(result['success'])
        self.dispatch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
