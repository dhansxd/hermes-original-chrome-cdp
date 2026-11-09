import json
import os
import sys
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

    def test_profile_directory_validation(self):
        for invalid in ('../Default', '/tmp/profile', 'a\\b', 'Guest Profile', 'System Profile'):
            with self.assertRaises(ValueError):
                plugin.profile_directory(invalid)
        self.assertEqual(plugin.profile_directory('Profile 2'), 'Profile 2')


if __name__ == '__main__':
    unittest.main()
