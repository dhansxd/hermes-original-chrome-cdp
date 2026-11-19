import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plugin


class ProviderTests(unittest.TestCase):
    def setUp(self):
        def fixture_profile(identifier, data):
            return plugin.ChromeProfile(plugin.profile_directory(identifier), 'Fixture profile', (1, 2, 3))
        reader = patch('plugin.get_profile', side_effect=fixture_profile)
        verifier = patch('plugin.verify_profile', side_effect=lambda profile, data: profile)
        reader.start()
        verifier.start()
        self.addCleanup(reader.stop)
        self.addCleanup(verifier.stop)

    def config(self):
        return {'browser': {'cloud_provider': plugin.NAME, 'auto_local_for_private_urls': False}}

    def call(self, task, alias='', **extra):
        with patch.dict(os.environ, {}, clear=True):
            return plugin.prepare_call('browser_exec', {'session': alias, **extra}, task,
                                       session_id='chat', config=self.config())

    def test_same_alias_is_private_to_each_agent(self):
        for alias in ('', 'default', 'research'):
            a, b = self.call('agent-a', alias), self.call('agent-b', alias)
            self.assertEqual(a['action'], 'modify')
            self.assertNotEqual(a['args']['session'], b['args']['session'])
            self.assertEqual(a, self.call('agent-a', alias))
            self.assertEqual(a, self.call('agent-a', a['args']['session']))

    def test_native_turn_identity_keeps_replacement_separate_from_stopped_turn(self):
        with patch.dict(os.environ, {}, clear=True):
            old = plugin.prepare_call('browser_exec', {'session': 'same'}, 'A',
                                      session_id='chat', turn_id='old-turn', config=self.config())
            current = plugin.prepare_call('browser_exec', {'session': 'same'}, 'A',
                                          session_id='chat', turn_id='current-turn', config=self.config())
            repeated = plugin.prepare_call('browser_exec', {'session': 'same'}, 'A',
                                           session_id='chat', turn_id='current-turn', config=self.config())
        self.assertNotEqual(old['args']['session'], current['args']['session'])
        self.assertEqual(current, repeated)

    def test_reload_keeps_session_names_separate_from_retired_provider(self):
        previous = plugin.ChromeProvider()
        current = plugin.ChromeProvider()
        self.addCleanup(previous.unload)
        self.addCleanup(current.unload)
        with patch.dict(os.environ, {}, clear=True):
            old = previous.prepare_call('browser_exec', {}, 'A', session_id='chat',
                                         turn_id='same-turn', config=self.config())
            new = current.prepare_call('browser_exec', {}, 'A', session_id='chat',
                                       turn_id='same-turn', config=self.config())
            repeated = current.prepare_call('browser_exec', {}, 'A', session_id='chat',
                                            turn_id='same-turn', config=self.config())
        self.assertNotEqual(old['args']['session'], new['args']['session'])
        self.assertEqual(new, repeated)

    def test_registered_stop_uses_native_route_payload_and_preserves_peer(self):
        from gateway.session_context import scoped_session_key
        ctx = Mock()
        ctx.get_config.return_value = None
        plugin.register(ctx)
        provider = ctx.register_browser_provider.call_args.args[0]
        self.addCleanup(provider.unload)
        hooks = {call.args[0]: call.args[1] for call in ctx.register_hook.call_args_list}
        names = {}
        with patch.dict(os.environ, {}, clear=True):
            for task in ('A', 'B'):
                with scoped_session_key('route-' + task):
                    names[task] = provider.prepare_call('browser_exec', {}, task,
                                                        session_id='history-' + task,
                                                        config=self.config())['args']['session']
                provider.create_session('bu-named-' + names[task] + '@fixture-home')
        with patch('tools.browser_supervisor.SUPERVISOR_REGISTRY.stop') as stop:
            hooks['agent_loop_stopped'](session_key='route-A', platform='tui',
                                        reason='user_stop', invalidation_reason='session_interrupt')
            stop.assert_called_once_with('bu-named-' + names['A'] + '@fixture-home')
            self.assertNotIn(names['A'], provider.owners)
            self.assertIn(names['B'], provider.owners)

    def test_stop_without_matching_route_preserves_all_owners(self):
        ctx = Mock()
        plugin.register(ctx)
        provider = ctx.register_browser_provider.call_args.args[0]
        self.addCleanup(provider.unload)
        provider.owners['fixture'] = ('A', 'history-A', 'route-A')
        hooks = {call.args[0]: call.args[1] for call in ctx.register_hook.call_args_list}
        with patch('tools.browser_supervisor.SUPERVISOR_REGISTRY.stop') as stop:
            for key in ('', 'another-route'):
                hooks['agent_loop_stopped'](session_key=key, platform='tui', reason='user_stop')
            stop.assert_not_called()
            self.assertIn('fixture', provider.owners)

    def test_stop_snapshot_preserves_replacement_admitted_before_cleanup(self):
        ctx = Mock()
        ctx.get_config.return_value = None
        plugin.register(ctx)
        provider = ctx.register_browser_provider.call_args.args[0]
        self.addCleanup(provider.unload)
        hooks = {call.args[0]: call.args[1] for call in ctx.register_hook.call_args_list}
        old = provider.prepare_call('browser_exec', {}, 'A', session_id='chat', session_key='route',
                                    turn_id='old-turn', config=self.config())['args']['session']
        provider.create_session('bu-named-' + old + '@fixture-home')
        finish = provider.finish
        replacements = []

        def replace_then_finish(**kwargs):
            replacements.append(provider.prepare_call('browser_exec', {}, 'A', session_id='chat',
                                                       session_key='route', turn_id='current-turn',
                                                       config=self.config())['args']['session'])
            finish(**kwargs)

        with patch.object(provider, 'finish', side_effect=replace_then_finish), \
                patch('tools.browser_supervisor.SUPERVISOR_REGISTRY.stop') as stop:
            hooks['agent_loop_stopped'](session_key='route', platform='tui', reason='user_stop')
            stop.assert_called_once_with('bu-named-' + old + '@fixture-home')
            self.assertNotIn(old, provider.owners)
            self.assertIn(replacements[0], provider.owners)

    def test_late_turn_end_closes_only_the_ended_turn(self):
        provider = plugin.ChromeProvider()
        self.addCleanup(provider.unload)
        old, replacement = (
            provider.prepare_call('browser_exec', {}, 'A', session_id='chat',
                                  turn_id=turn, config=self.config())['args']['session']
            for turn in ('old', 'replacement')
        )
        previous_info = provider.create_session('bu-named-' + old + '@fixture-home')
        replacement_info = provider.create_session('bu-named-' + replacement + '@fixture-home')
        with patch('tools.browser_supervisor.SUPERVISOR_REGISTRY.stop') as stop:
            provider.ended(session_id='chat', task_id='A', turn_id='old', interrupted=True)
        stop.assert_called_once_with('bu-named-' + old + '@fixture-home')
        self.assertNotIn(previous_info['bb_session_id'], provider.sessions)
        self.assertIn(replacement_info['bb_session_id'], provider.sessions)
        self.assertIn(replacement, provider.owners)

    def test_disconnected_session_retires_exact_name_before_replacement(self):
        provider = plugin.ChromeProvider()
        self.addCleanup(provider.unload)

        def prepare(task):
            return provider.prepare_call('browser_exec', {}, task, session_id='chat',
                                         turn_id='turn', config=self.config())

        old = prepare('A')['args']['session']
        peer = prepare('B')['args']['session']
        old_id = provider.create_session('bu-named-' + old + '@fixture-home')['bb_session_id']
        peer_id = provider.create_session('bu-named-' + peer + '@fixture-home')['bb_session_id']
        session = provider.sessions[old_id]
        session.identity = {'pid': 42, 'started': 1}
        session.wire = Mock(closed=True)
        session.ready = True
        session.owned.add('old-target')
        with patch('relay.startup.process_alive', side_effect=[True, False]), \
                patch('relay.startup.launch') as launch:
            pending = prepare('A')
            self.assertEqual(pending['action'], 'block')
            self.assertIn('cleanup is pending', pending['message'])
            self.assertIn(old, provider.owners)
            retired = prepare('A')
            self.assertEqual(retired['action'], 'block')
            self.assertIn('was not replayed', retired['message'])
            self.assertNotIn(old_id, provider.sessions)
            self.assertEqual(provider.create_session('bu-named-' + old)['bb_session_id'], 'unloaded')
            new = prepare('A')['args']['session']
            self.assertNotEqual(new, old)
            info = provider.create_session('bu-named-' + new + '@fixture-home')
            self.assertEqual(provider.sessions[info['bb_session_id']].profile, session.profile)
            self.assertFalse(provider.sessions[peer_id].closed)
            launch.assert_not_called()

    def test_finalized_native_session_stays_retired_after_replacement_is_admitted(self):
        from tools import browser_session
        provider = plugin.ChromeProvider()
        self.addCleanup(provider.unload)
        with patch.dict(os.environ, {}, clear=True):
            old_name = provider.prepare_call('browser_exec', {'session': 'same'}, 'A',
                                             session_id='chat', turn_id='old-turn',
                                             config=self.config())['args']['session']
            provider.finalize(session_id='chat')
            with patch.object(browser_session, '_create_local_session') as local, \
                    patch('plugin.ChromeSession') as create:
                for replacement in (False, True):
                    if replacement:
                        new_name = provider.prepare_call('browser_exec', {'session': 'same'}, 'A',
                                                         session_id='chat', turn_id='current-turn',
                                                         config=self.config())['args']['session']
                        self.assertIn(new_name, provider.owners)
                    info = browser_session._create_cloud_session_or_fallback(
                        'bu-named-' + old_name + '@fixture-home', provider)
                    self.assertEqual(info['bb_session_id'], 'unloaded')
                local.assert_not_called()
                create.assert_not_called()
                self.assertFalse(provider.sessions)
            current = provider.create_session('bu-named-' + new_name + '@fixture-home')
            self.assertIn(current['bb_session_id'], provider.sessions)

    def test_other_backends_and_tools_are_unchanged(self):
        self.assertIsNone(plugin.prepare_call('browser_exec', {}, 'a', config={'browser': {'cloud_provider': 'local'}}))
        self.assertIsNone(plugin.prepare_call('terminal', {}, 'a', config=self.config()))

    def test_focus_check_is_loaded_from_plugin_through_native_hook(self):
        code = "fill_input('#hidden', 'fixture')"
        result = self.call('agent-a', code=code)
        native = Mock()
        namespace = {'fill_input': native, 'js': Mock(return_value=False), 'wait_for_element': Mock()}
        with self.assertRaisesRegex(RuntimeError, 'not focused'):
            exec(result['args']['code'], namespace)
        native.assert_not_called()
        self.assertTrue(result['args']['code'].endswith(code))

    def test_no_profile_copy_or_endpoint_override(self):
        self.assertEqual(self.call('a', local=True)['action'], 'block')
        self.assertEqual(self.call('')['action'], 'block')
        with patch.dict(os.environ, {'BROWSER_CDP_URL': 'ws://other'}):
            self.assertEqual(plugin.prepare_call('browser_exec', {}, 'a', config=self.config())['action'], 'block')

    def test_provider_profile_control_and_namespace_hook_are_registered(self):
        ctx = Mock()
        plugin.register(ctx)
        ctx.register_browser_provider.assert_called_once()
        registered = {call.kwargs['name']: call.kwargs for call in ctx.register_tool.call_args_list}
        self.assertEqual(set(registered), {'chrome_profiles', 'browser_app'})
        self.assertTrue(all('override' not in entry for entry in registered.values()))
        provider = ctx.register_browser_provider.call_args.args[0]
        hooks = {call.args[0]: call.args[1] for call in ctx.register_hook.call_args_list}
        self.assertIs(hooks['pre_tool_call'].__self__.provider, provider)
        self.assertEqual(provider.get_setup_schema()['name'], 'Original Chrome · CDP')

    def test_finish_cleans_only_the_calling_agents_native_names(self):
        provider = plugin.ChromeProvider()
        self.addCleanup(provider.unload)
        with patch.dict(os.environ, {}, clear=True):
            a = provider.prepare_call('browser_exec', {}, 'A', session_id='chat', config=self.config())['args']['session']
            b = provider.prepare_call('browser_exec', {}, 'B', session_id='chat', config=self.config())['args']['session']
        a_info = provider.create_session('bu-named-' + a + '@fixture-home')
        b_info = provider.create_session('bu-named-' + b + '@fixture-home')
        with patch('tools.browser_supervisor.SUPERVISOR_REGISTRY.stop') as stop:
            provider.human_wait(session_id='chat')
            provider.finish(task_id='A', session_id='chat', completed=True)
            stop.assert_not_called()
            provider.human_resume(session_id='chat')
            provider.finish(task_id='A', session_id='chat', completed=True)
            stop.assert_called_once_with('bu-named-' + a + '@fixture-home')
            self.assertNotIn(a_info['bb_session_id'], provider.sessions)
            self.assertIn(b_info['bb_session_id'], provider.sessions)
            self.assertIn(b, provider.owners)

    def test_provider_creates_endpoint_without_launching_chrome(self):
        provider = plugin.ChromeProvider()
        with patch('relay.startup.launch') as launch:
            info = provider.create_session('agent-a')
            self.assertTrue(info['cdp_url'].startswith('ws://127.0.0.1:'))
            launch.assert_not_called()
            self.assertTrue(provider.close_session(info['bb_session_id']))
            self.assertFalse(provider.sessions)

    def test_slow_cleanup_leaves_other_agents_hooks_available(self):
        provider = plugin.ChromeProvider()
        self.addCleanup(provider.unload)
        config = self.config()
        with patch.dict(os.environ, {}, clear=True):
            name = provider.prepare_call('browser_exec', {}, 'A', session_id='chat', config=config)['args']['session']
            provider.create_session('bu-named-' + name + '@fixture-home')
            entered, release, prepared = threading.Event(), threading.Event(), threading.Event()
            results = {}

            def stop(task):
                entered.set()
                self.assertTrue(release.wait(3))

            def prepare():
                results['peer'] = provider.prepare_call('browser_exec', {}, 'B', session_id='chat', config=config)
                results['closing'] = provider.prepare_call('browser_exec', {}, 'A', session_id='chat', config=config)
                prepared.set()

            closer = threading.Thread(target=lambda: provider.finish(task_id='A', completed=True))
            peer = threading.Thread(target=prepare)
            try:
                with patch('tools.browser_supervisor.SUPERVISOR_REGISTRY.stop', side_effect=stop):
                    closer.start()
                    self.assertTrue(entered.wait(3))
                    peer.start()
                    self.assertTrue(prepared.wait(1), 'A cleanup blocked B pre_tool_call')
                    self.assertEqual(results['peer']['action'], 'modify')
                    self.assertEqual(results['closing']['action'], 'block')
                    release.set()
                    closer.join(3)
                    peer.join(3)
                self.assertFalse(closer.is_alive() or peer.is_alive())
                self.assertNotIn(name, provider.owners)
            finally:
                release.set()
                closer.join(3)
                if peer.ident is not None:
                    peer.join(3)

    def test_closing_agent_refuses_late_native_session_without_fallback(self):
        provider = plugin.ChromeProvider()
        self.addCleanup(provider.unload)
        provider.finishing.add('fixture-a')
        with patch('plugin.ChromeSession') as create:
            info = provider.create_session('bu-named-fixture-a@fixture-home')
        create.assert_not_called()
        self.assertEqual(info['bb_session_id'], 'unloaded')

    def test_unload_rejects_new_sessions_and_stale_tool_hooks(self):
        provider = plugin.ChromeProvider()
        provider.create_session('agent-a')
        entered, release = threading.Event(), threading.Event()
        original_close = provider.close_session

        def delayed_close(identifier):
            entered.set()
            self.assertTrue(release.wait(3))
            return original_close(identifier)

        try:
            with patch.object(provider, 'close_session', side_effect=delayed_close), \
                    patch('plugin.ChromeSession', wraps=plugin.ChromeSession) as create:
                worker = threading.Thread(target=provider.unload)
                worker.start()
                self.assertTrue(entered.wait(3))
                result = provider.create_session('agent-b')
                self.assertEqual(result['bb_session_id'], 'unloaded')
                create.assert_not_called()
                result = provider.prepare_call('browser_exec', {}, 'agent-b', config=self.config())
                self.assertEqual(result['action'], 'block')
                release.set()
                worker.join(3)
                self.assertFalse(worker.is_alive())
            self.assertFalse(provider.sessions)
        finally:
            release.set()
            for identifier in list(provider.sessions):
                original_close(identifier)

    def test_late_native_session_creation_cannot_fall_back_to_chromium(self):
        from tools import browser_session
        provider = plugin.ChromeProvider()
        self.assertTrue(provider.unload())
        with patch.object(browser_session, '_create_local_session') as local, \
                patch('plugin.ChromeSession') as create:
            info = browser_session._create_cloud_session_or_fallback('agent-a', provider)
        local.assert_not_called()
        create.assert_not_called()
        self.assertEqual(info['cdp_url'],
                         'ws://original-chrome-provider-unloaded.invalid/devtools/browser/unloaded')
        self.assertNotIn('fallback_from_cloud', info)
        self.assertTrue(provider.close_session(info['bb_session_id']))
        self.assertFalse(provider.sessions)

    def test_finish_retains_owner_after_supervisor_failure_and_retries(self):
        provider = plugin.ChromeProvider()
        self.addCleanup(provider.unload)
        provider.owners['fixture-a'] = ('agent-a', 'chat')
        provider.create_session('bu-named-fixture-a@fixture-home')
        with patch('tools.browser_supervisor.SUPERVISOR_REGISTRY.stop',
                   side_effect=[RuntimeError('fixture failure'), None]) as stop:
            provider.finish(task_id='agent-a', session_id='chat', completed=True)
            self.assertIn('fixture-a', provider.owners)
            provider.finish(task_id='agent-a', session_id='chat', completed=True)
            self.assertFalse(provider.owners)
            self.assertEqual(stop.call_count, 2)

    def test_finish_retries_unconfirmed_provider_cleanup(self):
        provider = plugin.ChromeProvider()
        provider.owners['fixture-a'] = ('agent-a', 'chat')
        info = provider.create_session('bu-named-fixture-a@fixture-home')
        identifier = info['bb_session_id']
        original_close = provider.close_session
        try:
            with patch.object(provider, 'close_session', return_value=False):
                provider.finish(task_id='agent-a', session_id='chat', completed=True)
                self.assertIn('fixture-a', provider.owners)
                self.assertIn(identifier, provider.sessions)
            provider.finish(task_id='agent-a', session_id='chat', completed=True)
            self.assertFalse(provider.owners)
            self.assertFalse(provider.sessions)
        finally:
            original_close(identifier)

    def test_unload_keeps_failed_cleanup_registered_for_process_exit(self):
        with patch('plugin.atexit.register') as register, patch('plugin.atexit.unregister') as unregister:
            provider = plugin.ChromeProvider()
            info = provider.create_session('agent-a')
            identifier = info['bb_session_id']
            try:
                with patch.object(provider, 'close_session', return_value=False):
                    self.assertFalse(provider.unload())
                self.assertIn(identifier, provider.sessions)
                unregister.assert_not_called()
                callback = register.call_args.args[0]
                self.assertTrue(callback())
                self.assertFalse(provider.sessions)
                unregister.assert_called_once_with(provider.unload)
            finally:
                provider.close_session(identifier)

    def test_profile_directory_validation(self):
        for invalid in ('../Default', '/tmp/profile', 'a\\b', 'Guest Profile', 'System Profile'):
            with self.assertRaises(ValueError):
                plugin.profile_directory(invalid)
        self.assertEqual(plugin.profile_directory('Profile 2'), 'Profile 2')


if __name__ == '__main__':
    unittest.main()
