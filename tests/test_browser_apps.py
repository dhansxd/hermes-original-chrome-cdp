import concurrent.futures
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from hermes_constants import reset_hermes_home_override, set_hermes_home_override

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import browser_apps
import plugin


class BrowserAppTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = {'apps_directory': str(self.root / 'packages'), 'profile_directory': 'Default'}
        self.provider = plugin.ChromeProvider(self.settings.get, set_setting=self.settings.__setitem__)
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
                'browser_exec', args, task, session_id=chat,
                session_key='route-' + chat.removeprefix('chat-'), turn_id=turn, config=self.config)
        self.assertEqual(prepared['action'], 'modify', prepared)
        args.update(prepared['args'])
        result = json.loads(self.host.handle(args, task_id=task, session_id=chat, turn_id=turn))
        return result

    def dispatch_native(self, args, native, **owner):
        identity = {key: value for key, value in owner.items() if key != 'task_id'}
        with patch('hermes_cli.config.load_config_readonly', return_value=self.config):
            prepared = self.host.prepare_call('browser_exec', args, owner['task_id'],
                                              session_key='route-' + owner['session_id'].removeprefix('chat-'),
                                              **identity)
            self.assertEqual(prepared['action'], 'modify', prepared)
            return self.host.execute({**args, **prepared['args']}, native, **owner)

    def test_records_only_ui_details_for_the_owned_extension_session(self):
        self.package()
        self.package('other')
        opened = self.invoke()
        args = {'action': 'record_missing_control', 'app': 'fixture', 'session': opened['session'],
                'params': {'page_or_mode': 'Project settings', 'control': 'Click Show details', 'fallback': 'dom'}}
        path = self.root / 'data/browser-apps/fixture/missing-controls.jsonl'

        wrong_owner = json.loads(self.host.handle(args, task_id='B', session_id='chat-B'))
        wrong_app = json.loads(self.host.handle({**args, 'app': 'other'}, task_id='A', session_id='chat-A'))
        invalid = json.loads(self.host.handle({**args, 'params': {**args['params'], 'fallback': 'guess'}},
                                              task_id='A', session_id='chat-A'))
        self.assertFalse(wrong_owner['success'])
        self.assertFalse(wrong_app['success'])
        self.assertFalse(invalid['success'])
        self.assertFalse(path.exists())

        expected = [{'app': 'fixture', **args['params']},
                    {'app': 'fixture', **args['params'], 'control': 'Click Advanced', 'fallback': 'screenshot'}]
        for finding in expected:
            params = {key: value for key, value in finding.items() if key != 'app'}
            result = json.loads(self.host.handle({**args, 'params': params}, task_id='A', session_id='chat-A'))
            self.assertTrue(result['success'], result)
            self.assertEqual(result['finding'], finding)
            self.assertEqual(Path(result['path']), path)

        self.provider.ended(session_id='chat-A', task_id='A', turn_id='turn')
        self.dispatch.assert_not_called()
        self.assertFalse(self.provider.owners)
        self.assertEqual([json.loads(line) for line in path.read_text().splitlines()], expected)
        after_cleanup = json.loads(self.host.handle(args, task_id='A', session_id='chat-A'))
        self.assertFalse(after_cleanup['success'])

    def test_unknown_control_and_unrelated_native_read_are_not_a_confirmed_finding(self):
        self.package()
        detail = {'reason': 'unmapped_control', 'control': 'Show credits', 'page_or_mode': 'Settings'}
        session = self.invoke(params={'status': 'needs_inspection', 'data': detail})['session']
        path = self.root / 'data/browser-apps/fixture/missing-controls.jsonl'
        self.assertFalse(path.exists())
        native = Mock(return_value=json.dumps({'success': True, 'output': 'Settings'}))
        args = {'session': session, 'code': 'print(js("document.title"))'}
        ctx = {'task_id': 'A', 'session_id': 'chat-A', 'turn_id': 'turn'}
        self.host.execute(args, native, **ctx)
        self.host.execute(args, native, **ctx)
        self.assertFalse(path.exists())

    def test_declared_missing_control_and_native_screenshot_in_one_owned_call(self):
        self.package()
        session = self.invoke()['session']
        command = {'action': 'record_missing_control', 'app': 'fixture',
                   'params': {'page_or_mode': 'Settings', 'control': 'Show credits', 'fallback': 'screenshot'}}
        args = {'site_control': json.dumps(command), 'session': session, 'code': 'screenshot()'}
        native = Mock(return_value='screenshot result')
        with patch('hermes_cli.config.load_config_readonly', return_value=self.config):
            self.assertEqual(self.host.execute(args, native, task_id='A', session_id='chat-A'), 'screenshot result')
            wrong = self.host.execute(args, native, task_id='B', session_id='chat-B')
        self.assertFalse(json.loads(wrong)['success'])
        self.assertEqual(native.call_count, 1)
        self.assertEqual(native.call_args.args[0], {'session': session, 'code': 'screenshot()'})
        self.assertTrue((self.root / 'data/browser-apps/fixture/missing-controls.jsonl').is_file())

    def test_terminal_guardrail_halt_releases_only_the_running_owner(self):
        self.package()
        own = self.invoke(params={'status': 'running'})
        peer = self.invoke(task='B', chat='chat-B', params={'status': 'running'})
        self.provider.ended(session_id='chat-A', task_id='A', turn_id='turn',
                            turn_exit_reason='guardrail_halt')
        self.assertNotIn(own['session'], self.provider.owners)
        self.assertIn(peer['session'], self.provider.owners)

    def test_registration_preserves_native_message_and_tool_execution(self):
        context = Mock()
        context.has_capability.return_value = True
        with patch.object(plugin, 'register_site_controls') as register_browser:
            plugin.register(context)
        installed = context.register_browser_provider.call_args.args[0]
        self.addCleanup(installed.unload)
        register_browser.assert_called_once()
        context.register_middleware.assert_not_called()
        self.assertIn('agent_loop_stopped', [call.args[0] for call in context.register_hook.call_args_list])

    def test_browser_skill_is_in_fresh_prompt_when_native_browser_exec_is_available(self):
        from agent.prompt_builder import build_skills_system_prompt

        context = Mock()
        context.has_capability.return_value = True
        with patch.object(plugin, 'register_site_controls'):
            plugin.register(context)
        self.addCleanup(context.register_browser_provider.call_args.args[0].unload)
        skill = f'{plugin.NAME}:{context.register_skill.call_args.args[0]}'
        metadata = context.register_skill.call_args.kwargs
        manager = Mock()
        manager.list_plugin_skill_metadata.return_value = [{'name': skill, **metadata}]
        skills_dir = self.root / 'skills'
        skills_dir.mkdir()
        settings = {
            'available_toolsets': {'browser-use', 'skills'},
            'skills_dir_override': skills_dir,
        }
        with (patch('hermes_cli.plugins.discover_plugins'),
              patch('hermes_cli.plugins.get_plugin_manager', return_value=manager)):
            self.assertIn(skill, build_skills_system_prompt(available_tools={'browser_exec', 'skill_view'}, **settings))
            self.assertNotIn(skill, build_skills_system_prompt(available_tools={'skill_view'}, **settings))

    def test_running_site_does_not_replace_explicit_native_browser_code(self):
        self.package(source='''FALLBACK_CLICK_OBSERVER = "legacy observer"
def fallback_send_pending(context):
    return True
def run(context, operation, params):
    return params
''')
        started = self.invoke(params={'status': 'running'})
        native = Mock(return_value=json.dumps({'success': True, 'output': 'browser output'}))
        for script in ('import time\ntime.sleep(120)\nprint(page_info())',
                       'js("document.querySelector(\'#send\').click()")'):
            with self.subTest(script=script):
                result = self.dispatch_native({'session': started['session'], 'code': script}, native,
                                              task_id='A', session_id='chat-A', turn_id='turn')
                self.assertEqual(result, native.return_value)
                self.assertEqual(native.call_args.args[0]['code'], plugin.prepare_code(script))
                self.assertEqual(native.call_args.args[0]['session'], started['session'])
        self.dispatch.assert_not_called()

    def test_basic_browser_action_reuses_site_window_and_native_timeout(self):
        self.package()
        opened = self.invoke()
        owner = dict(task_id='A', session_id='chat-A', turn_id='turn')
        native = Mock(return_value=json.dumps({'success': True, 'output': ''}))
        for action, params, helper in (
            ('navigate', {'url': 'https://example.com/?a=1&b=2'}, 'goto_url'),
            ('type', {'selector': '#field', 'text': 'Hello'}, 'fill_input'),
        ):
            with self.subTest(action=action):
                request = json.dumps({'action': action, 'params': params})
                result = self.dispatch_native({'session': opened['session'], 'site_control': request,
                                               'timeout_s': 27}, native, **owner)
                self.assertEqual(result, native.return_value)
                routed = native.call_args.args[0]
                self.assertEqual(routed['session'], opened['session'])
                self.assertEqual(routed['timeout_s'], 27)
                self.assertNotIn('site_control', routed)
                self.assertIn(helper + '(', routed['code'])
        self.assertEqual(native.call_count, 2)

    def test_invalid_basic_browser_actions_do_not_allocate_a_window(self):
        invalid = [
            ({'action': 'navigate', 'params': {'url': '/relative'}}, {}),
            ({'action': 'navigate', 'params': {'url': 'https://example.com'}}, {'code': 'print(1)'}),
            ({'action': 'type', 'params': {'selector': '#field', 'text': 18}}, {}),
            ({'action': 'type', 'params': {'selector': '#field', 'text': 'test', 'clear_first': 'false'}}, {}),
            ({'action': 'type', 'params': {'selector': '#field', 'text': 'test'}}, {'local': True}),
        ]
        with patch('hermes_cli.config.load_config_readonly', return_value=self.config):
            for command, extra in invalid:
                args = {'site_control': json.dumps(command), **extra}
                with self.subTest(command=command, extra=extra):
                    result = self.host.prepare_call('browser_exec', args, 'A',
                                                    session_id='chat-A', turn_id='turn')
                    self.assertEqual(result['action'], 'block')
                    self.assertFalse(self.provider.owners)

    def test_unconfirmed_mapped_result_keeps_the_request_pending_for_dom(self):
        self.package(operations={'click': {}, 'read_result': {}})
        with patch('browser_apps.OBSERVATION_INTERVAL', 0):
            session = self.invoke(operation='click', params={'status': 'running'})['session']
            inspect = self.invoke(operation='read_result', params={'status': 'needs_inspection'})
            self.dispatch.return_value = json.dumps({'success': True, 'output': json.dumps({
                'visible': 'Research still in progress', 'result': None})})
            follow = json.loads(self.host.handle(inspect['next_control'] | {'session': session},
                task_id='A', session_id='chat-A', turn_id='turn'))
        work = self.host.running_work('A', 'chat-A', 'turn')
        self.assertIn(session, work)
        self.assertFalse(work[session][2])
        self.assertEqual(inspect['next_control'], {'app': 'fixture', 'action': 'observe'})
        self.assertEqual(follow['next_control'], inspect['next_control'])
        self.assertEqual(inspect['session'], session)

    def test_stop_during_dom_observation_preserves_peer_and_prevents_page_read(self):
        self.package()
        session = self.invoke(params={'status': 'running'})['session']
        peer = self.invoke(task='B', chat='chat-B')['session']
        args = {'action': 'observe', 'app': 'fixture', 'session': session}
        wrong_turn = json.loads(self.host.handle(args, task_id='A', session_id='chat-A', turn_id='old'))
        self.assertFalse(wrong_turn['success'])
        with patch('browser_apps.sleep', side_effect=lambda _: self.provider.stopped(session_key='route-A')):
            result = json.loads(self.host.handle(args, task_id='A', session_id='chat-A', turn_id='turn'))
        self.assertFalse(result['success'])
        self.dispatch.assert_not_called()
        self.assertNotIn(session, self.provider.owners)
        self.assertIn(peer, self.provider.owners)

    def test_bundled_site_packages_default_to_the_current_hermes_profile(self):
        self.settings.pop('apps_directory')
        self.host.bundled_source = Path(browser_apps.__file__).parent / 'site_apps'
        for profile in (self.root / 'profile-a', self.root / 'profile-b'):
            token = set_hermes_home_override(profile)
            try:
                result = json.loads(self.host.handle({'action': 'list'}))
            finally:
                reset_hermes_home_override(token)
            self.assertTrue(result['success'], result)
            self.assertEqual(Path(result['directory']), profile / 'browser-apps')
            self.assertTrue((profile / 'browser-apps' / 'gemini' / 'app.json').is_file())
            self.assertTrue((profile / 'browser-apps' / 'flow' / 'app.json').is_file())

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

    def test_bundled_packages_install_once_and_preserve_user_edits(self):
        source = self.root / 'bundled'
        package = source / 'sample'
        package.mkdir(parents=True)
        (package / 'app.json').write_text(json.dumps({
            'api_version': 1, 'id': 'sample', 'operations': {'inspect': {}}}))
        (package / 'app.py').write_text('def run(context, operation, params): return params\n')
        self.host.seed_packages(source)
        installed = self.host.root / 'sample' / 'app.py'
        installed.write_text('user-owned source\n')
        (package / 'app.py').write_text('updated bundle\n')
        self.host.seed_packages(source)
        self.assertEqual(installed.read_text(), 'user-owned source\n')
        self.assertEqual([entry['id'] for entry in json.loads(self.host.handle({}))['apps']], ['sample'])

    def test_bundled_removed_package_stays_removed_and_disabled_stays_disabled(self):
        source = self.package()
        self.settings['apps_disabled.fixture'] = True
        self.settings['apps_directory'] = str(self.root / 'fresh')
        self.host.seed_packages(source.parent)
        self.assertFalse((self.host.root / 'fixture').exists())
        self.settings['apps_disabled.fixture'] = False
        self.host.seed_packages(source.parent)
        self.assertTrue((self.host.root / 'fixture').is_dir())
        self.settings['apps_disabled.fixture'] = True
        self.host.seed_packages(source.parent)
        self.assertTrue(self.settings['apps_disabled.fixture'])

    def test_bundled_install_preserves_an_existing_user_symlink(self):
        source = self.package()
        self.settings['apps_directory'] = str(self.root / 'fresh')
        self.host.root.mkdir()
        (self.host.root / 'fixture').symlink_to(self.root / 'missing')
        self.host.seed_packages(source.parent)
        self.assertTrue((self.host.root / 'fixture').is_symlink())

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

    def test_site_controls_and_general_browsing_share_only_the_owners_window(self):
        self.package('first')
        self.package('second')
        a = self.invoke('first')
        self.assertEqual(a['session'], self.invoke('first', alias=a['session'])['session'])
        b = self.invoke('second')
        child = self.invoke('first', task='child', chat='child-chat')
        with patch.dict(os.environ, {}, clear=True):
            normal = self.provider.prepare_call('browser_exec', {'session': 'same'}, 'A',
                                                session_id='chat-A', session_key='route-A', turn_id='turn', config=self.config)
        self.assertEqual(a['session'], b['session'])
        self.assertEqual(normal['args']['session'], a['session'])
        self.assertNotEqual(child['session'], a['session'])

    def test_ordinary_browser_then_mapped_control_then_dom_share_one_window(self):
        self.package(source="def run(context, operation, params): return context.browser_exec('print(42)')")
        identity = dict(task_id='A', session_id='chat-A', session_key='route-A', turn_id='turn')
        def call(**operation):
            args = {'session': 'same', **operation}
            changes = self.host.prepare_call('browser_exec', args, config=self.config, **identity)
            self.assertEqual(changes['action'], 'modify', changes)
            with patch('hermes_cli.config.load_config_readonly', return_value=self.config):
                self.host.execute({**args, **changes['args']}, lambda args, **kw: self.dispatch('browser_exec', args), **identity)
            return changes['args']['session']
        ordinary = call(code='print(page_info())')
        mapped = call(site_control=json.dumps({'app': 'fixture', 'operation': 'inspect'}))
        screenshot = call(code='capture_screenshot()')
        self.assertEqual([ordinary, mapped, screenshot], [ordinary] * 3)
        self.assertEqual([entry.args[1]['session'] for entry in self.dispatch.call_args_list], [ordinary] * 3)
        self.assertEqual(set(self.provider.owners), {ordinary})

    def test_invalid_site_arguments_do_not_allocate_a_window_or_run_code(self):
        for args in ({'site_control': 'click'}, {'site_control': {'action': ['run']}}):
            with self.subTest(args=args):
                result = self.host.prepare_call('browser_exec', args, 'A', config=self.config)
                self.assertEqual(result['action'], 'block')
                self.assertFalse(self.provider.owners)
                self.dispatch.assert_not_called()

    def test_model_supplied_optional_fields_do_not_change_the_requested_action(self):
        args = {'code': 'print("unused")', 'site_control': {'app': 'fixture', 'operation': 'inspect',
                'action': '', 'job': '', 'target_profile': '', 'session': None, 'params': {}}}
        self.assertTrue(browser_apps.has_site_request(args))
        self.assertEqual(browser_apps.site_request(args), {'app': 'fixture', 'operation': 'inspect',
                                                           'action': 'run', 'params': {}})
        for control in [None, '', 'null', '{}']:
            ordinary = {'code': 'print(page_info())', 'site_control': control}
            self.host.execute(ordinary, self.dispatch)
            self.dispatch.assert_called_with(ordinary)

    def test_site_commands_respect_the_provider_and_permission(self):
        args = {'site_control': {'action': 'list'}}
        other = {'browser': {'cloud_provider': 'another'}}
        self.host.controls_enabled = False
        self.assertIsNone(self.host.prepare_call('browser_exec', args, 'A', config=other))
        self.assertEqual(self.host.prepare_call('browser_exec', args, 'A', config=self.config)['action'], 'block')
        self.assertFalse(self.provider.owners)
        with patch('hermes_cli.config.load_config_readonly', return_value=other):
            self.host.execute(args, self.dispatch, task_id='A')
        self.dispatch.assert_called_once_with(args, task_id='A')

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
                'A', session_id='chat-A', session_key='route-A', turn_id='turn', config=self.config)
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

    def test_turn_end_retires_a_pending_window_before_native_fallback(self):
        self.package(source='def run(context, operation, params): return {"status": "running"}\n')
        app = self.invoke()
        self.provider.ended(session_id='chat-A', task_id='A', turn_id='turn',
                            completed=True, turn_exit_reason='text_response')
        self.assertNotIn(app['session'], self.provider.owners)

        def prepare(session, chat, route):
            with patch.dict(os.environ, {}, clear=True):
                rule = self.provider.prepare_call('browser_exec', {'session': session}, 'B',
                    session_id=chat, session_key=route, turn_id='next-turn', config=self.config)
            return rule['args']['session']

        self.assertNotEqual(prepare('same', 'chat-A', 'route-A'), app['session'])
        self.assertNotEqual(prepare(app['session'], 'chat-B', 'route-A'), app['session'])
        self.assertNotEqual(prepare(app['session'], 'chat-A', 'route-B'), app['session'])
        self.assertNotEqual(prepare(app['session'], 'chat-A', 'route-A'), app['session'])
        self.assertNotEqual(self.invoke(task='B', turn='next-turn')['session'], app['session'])

    def test_two_callers_execute_a_package_in_independent_modules(self):
        self.package(source='from pathlib import Path\nvalue = None\ndef run(context, operation, params):\n    global value\n    value = context.task_id\n    context.directory.joinpath("ready").touch()\n    params["barrier"].wait(3)\n    return value\n')
        barrier = threading.Barrier(2)
        # Invoke the native module entry directly so the test barrier stays local.
        def execute(task):
            prepared = self.provider.prepare_call('browser_exec',
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

    def manage(self, action, identifier='fixture'):
        return json.loads(self.host.handle({'action': action, 'app': identifier}))

    def test_disable_is_persistent_and_preserves_another_package(self):
        self.package()
        self.package('peer')
        first, peer = self.invoke(), self.invoke('peer', task='B', chat='chat-B')
        result = self.manage('disable')
        self.assertFalse(result['enabled'])
        self.assertFalse(result['cleanup_pending'])
        self.assertNotIn(first['session'], self.provider.owners)
        self.assertIn(peer['session'], self.provider.owners)
        self.assertTrue(self.settings['apps_disabled.fixture'])
        catalog = json.loads(self.host.handle({'action': 'list'}))
        self.assertFalse(next(row for row in catalog['apps'] if row['id'] == 'fixture')['enabled'])
        blocked = self.provider.prepare_call('browser_exec', {'action': 'run', 'app': 'fixture'}, 'A')
        self.assertEqual(blocked['action'], 'block')

    def test_enable_is_idempotent_and_reenable_gets_a_fresh_native_name(self):
        self.package()
        first = self.invoke()
        self.assertTrue(self.manage('enable')['enabled'])
        self.assertEqual(self.invoke()['session'], first['session'])
        self.assertTrue(self.manage('disable')['success'])
        self.assertTrue(self.manage('enable')['enabled'])
        self.assertNotEqual(self.invoke()['session'], first['session'])

    def test_remove_retains_artifacts_checkpoints_and_receipts(self):
        self.package(source='''def run(context, operation, params):
    context.checkpoint({'job': 'fixture-job', 'phase': 'downloaded'})
    (context.directory / 'artifact.txt').write_text('fixture output')
    return str(context.directory)
''')
        result = self.invoke()
        artifacts = Path(result['data'])
        removed = self.manage('remove')
        self.assertTrue(removed['removed'])
        self.assertFalse((self.host.root / 'fixture').exists())
        self.assertEqual((artifacts / 'artifact.txt').read_text(), 'fixture output')
        self.assertEqual(json.loads((artifacts / 'checkpoint.json').read_text())['job'], 'fixture-job')
        self.assertEqual(json.loads((artifacts / 'result.json').read_text())['profile'], 'Default')
        self.assertTrue(self.settings['apps_disabled.fixture'])

    def test_broken_package_can_be_removed_without_executing_it(self):
        directory = self.package(source='raise AssertionError("must not run")')
        (directory / 'app.json').write_text('broken metadata')
        self.assertTrue(self.manage('remove')['removed'])
        self.assertFalse(directory.exists())

    def test_remove_a_linked_package_removes_its_entry_only(self):
        directory = self.package('source')
        (self.host.root / 'fixture').symlink_to(directory, target_is_directory=True)
        self.assertTrue(self.manage('remove')['removed'])
        self.assertFalse((self.host.root / 'fixture').is_symlink())
        self.assertTrue((directory / 'app.py').is_file())

    def test_remove_during_active_code_waits_and_rejects_late_browser_access(self):
        self.package(source='''def run(context, operation, params):
    context.checkpoint({'phase': 'waiting'})
    params['entered'].set()
    params['release'].wait(3)
    return context.browser_exec('print("late")')
''')
        entered, release = threading.Event(), threading.Event()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(self.invoke, params={'entered': entered, 'release': release})
            try:
                self.assertTrue(entered.wait(3))
                result = self.manage('remove')
                self.assertTrue(result['cleanup_pending'])
                self.assertTrue((self.host.root / 'fixture').is_dir())
                self.assertFalse(self.manage('enable')['enabled'])
            finally:
                release.set()
            self.assertFalse(future.result(timeout=3)['success'])
        self.dispatch.assert_not_called()
        self.assertTrue(self.manage('remove')['removed'])
        checkpoints = list((self.root / 'data/browser-apps/fixture').glob('*/checkpoint.json'))
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(json.loads(checkpoints[0].read_text()), {'phase': 'waiting'})

    def test_failed_native_cleanup_retains_source_until_retry(self):
        self.package()
        result = self.invoke()
        native = self.provider.create_session('bu-named-' + result['session'] + '@fixture')
        session = self.provider.sessions[native['bb_session_id']]
        with patch.object(session, 'close', return_value=False):
            pending = self.manage('remove')
        self.assertTrue(pending['cleanup_pending'])
        self.assertTrue((self.host.root / 'fixture/app.py').is_file())
        self.assertTrue(self.manage('remove')['removed'])

    def test_pending_operation_keeps_its_window_during_turn_and_saves_artifacts(self):
        self.package(source='''def run(context, operation, params):
    context.checkpoint({'job': 'fixture', 'status': params.get('status', 'running')})
    return {'status': params.get('status', 'running'), 'data': str(context.directory)}
''')
        first = self.invoke()
        continued = self.invoke()
        self.assertEqual(continued['session'], first['session'])
        self.assertEqual(continued['data'], first['data'])
        self.assertIn(first['session'], self.provider.owners)
        self.provider.ended(session_id='chat-A', task_id='A')
        self.assertNotIn(first['session'], self.provider.owners)
        self.assertTrue(Path(first['data'], 'checkpoint.json').is_file())
        second = self.invoke(task='next-task', chat='chat-A', turn='next-turn', alias=first['session'])
        self.assertNotEqual(second['session'], first['session'])
        self.assertNotEqual(second['data'], first['data'])
        self.provider.ended(session_id='chat-A', task_id='next-task')
        self.assertNotIn(second['session'], self.provider.owners)

    def test_removing_a_large_package_does_not_lock_other_agents(self):
        self.package()
        self.package('peer')
        entered, release = threading.Event(), threading.Event()
        remove = browser_apps.shutil.rmtree
        def slow_remove(path):
            entered.set()
            self.assertTrue(release.wait(3))
            remove(path)
        with patch('browser_apps.shutil.rmtree', side_effect=slow_remove), \
                concurrent.futures.ThreadPoolExecutor() as pool:
            removal = pool.submit(self.manage, 'remove')
            try:
                self.assertTrue(entered.wait(3))
                peer = pool.submit(self.invoke, identifier='peer', task='B', chat='chat-B')
                self.assertTrue(peer.result(timeout=1)['success'])
            finally:
                release.set()
            self.assertTrue(removal.result(timeout=3)['removed'])

    def test_stop_and_finalize_release_pending_sessions(self):
        self.package(source='def run(context, operation, params):\n    return {"status": "running"}\n')
        self.package('peer')
        first = self.invoke()
        peer = self.invoke('peer', task='B', chat='chat-B')
        self.provider.stopped(session_key='route-A')
        self.assertNotIn(first['session'], self.provider.owners)
        self.assertIn(peer['session'], self.provider.owners)
        next_run = self.invoke(turn='next-turn')
        self.provider.finalize(session_id='chat-A')
        self.assertNotIn(next_run['session'], self.provider.owners)
        self.assertIn(peer['session'], self.provider.owners)

    def test_guide_edits_and_optional_guide_are_read_fresh(self):
        directory = self.package()
        def guide():
            return json.loads(self.host.handle({'action': 'describe', 'app': 'fixture'}))['guide']
        self.assertEqual(guide(), '')
        (directory / 'SKILL.md').write_text('first')
        self.assertEqual(guide(), 'first')
        (directory / 'SKILL.md').write_text('newer')
        self.assertEqual(guide(), 'newer')
        self.dispatch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
