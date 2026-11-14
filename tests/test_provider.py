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

    def test_only_provider_and_namespace_hook_are_registered(self):
        ctx = Mock()
        plugin.register(ctx)
        ctx.register_browser_provider.assert_called_once()
        ctx.register_tool.assert_not_called()
        provider = ctx.register_browser_provider.call_args.args[0]
        ctx.register_hook.assert_any_call('pre_tool_call', provider.prepare_call)
        self.assertEqual(provider.get_setup_schema()['name'], 'Original Chrome · CDP')

    def test_finish_cleans_only_the_calling_agents_native_names(self):
        provider = plugin.ChromeProvider()
        with patch.dict(os.environ, {}, clear=True):
            a = provider.prepare_call('browser_exec', {}, 'A', session_id='chat', config=self.config())['args']['session']
            b = provider.prepare_call('browser_exec', {}, 'B', session_id='chat', config=self.config())['args']['session']
        with patch('tools.browser_session_lifecycle.cleanup_browser') as cleanup, \
                patch('tools.browser_session_cdp.stop_cdp_supervisor'):
            provider.human_wait(session_id='chat')
            provider.finish(task_id='A', session_id='chat', completed=True)
            cleanup.assert_not_called()
            provider.human_resume(session_id='chat')
            provider.finish(task_id='A', session_id='chat', completed=True)
            cleanup.assert_called_once_with('bu-named-' + a)
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
                with patch('tools.browser_session_cdp.stop_cdp_supervisor', side_effect=stop), \
                        patch('tools.browser_session_lifecycle.cleanup_browser'):
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
        provider.owners['fixture-a'] = ('agent-a', 'chat')
        with patch('tools.browser_session_cdp.stop_cdp_supervisor',
                   side_effect=[RuntimeError('fixture failure'), None]) as stop, \
                patch('tools.browser_session_lifecycle.cleanup_browser') as cleanup:
            provider.finish(task_id='agent-a', session_id='chat', completed=True)
            self.assertIn('fixture-a', provider.owners)
            cleanup.assert_not_called()
            provider.finish(task_id='agent-a', session_id='chat', completed=True)
            self.assertFalse(provider.owners)
            self.assertEqual(stop.call_count, 2)
            cleanup.assert_called_once_with('bu-named-fixture-a')

    def test_finish_retries_provider_sessions_even_after_native_cache_forgets_them(self):
        provider = plugin.ChromeProvider()
        provider.owners['fixture-a'] = ('agent-a', 'chat')
        info = provider.create_session('bu-named-fixture-a@fixture-home')
        identifier = info['bb_session_id']
        original_close = provider.close_session
        try:
            with patch('tools.browser_session_cdp.stop_cdp_supervisor'), \
                    patch('tools.browser_session_lifecycle.cleanup_browser'), \
                    patch.object(provider, 'close_session', return_value=False):
                provider.finish(task_id='agent-a', session_id='chat', completed=True)
                self.assertIn('fixture-a', provider.owners)
                self.assertIn(identifier, provider.sessions)
            with patch('tools.browser_session_cdp.stop_cdp_supervisor'), \
                    patch('tools.browser_session_lifecycle.cleanup_browser'):
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
