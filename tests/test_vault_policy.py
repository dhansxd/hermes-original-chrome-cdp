"""Public registered-handler boundary; no native vault or browser access."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plugin


class VaultPolicyTests(unittest.TestCase):
    def register(self, *, available=True, is_async=False):
        self.ctx = Mock()
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.ctx.state.data_dir=Path(temporary.name)
        self.ctx.has_capability.return_value = True
        self.native = Mock(return_value='{"success":true,"synthetic":true}')
        self.schema = json.loads((plugin.ROOT / 'vault_schema.json').read_text())
        entry = SimpleNamespace(handler=self.native, schema=self.schema,
            toolset='synthetic-native-vault', is_async=is_async) if available else None
        with patch('tools.registry.registry.get_entry', side_effect=lambda name: entry if name=='browser_vault' else None), \
             patch('plugin.ChromeProvider') as provider:
            plugin.register(self.ctx)
        self.provider = provider.return_value
        call = next(c.kwargs for c in self.ctx.register_tool.call_args_list
                    if c.kwargs['name'] == 'browser_vault')
        self.assertTrue(call['override'])
        self.assertEqual(call['schema'], self.schema)
        self.assertIsNot(call['schema'], self.schema)
        return call['handler']

    def invoke(self, handler, args, **kwargs):
        with patch('plugin.browser_config', return_value={
                'backend': 'browser-use', 'cloud_provider': plugin.NAME}):
            return json.loads(handler(args, **kwargs))

    def test_page_actions_refuse_without_native_or_provider_access(self):
        handler = self.register()
        for action in ('fill', 'save_login', 'enter_code', 'unknown', None):
            with self.subTest(action=action):
                result = self.invoke(handler, {'action': action, 'handle': 'SYNTHETIC'})
                self.assertFalse(result['success'])
                self.assertEqual(result['error_type'], 'vault_page_actions_unavailable')
                self.assertFalse(result['fallback_used'])
                self.assertFalse(result['action_replayed'])
        self.native.assert_not_called()
        self.provider.execute.assert_not_called()
        self.provider.endpoint.assert_not_called()

    def test_nonpage_actions_forward_exactly_once_to_captured_handler(self):
        handler = self.register()
        before = copy.deepcopy(self.schema)
        for action in ('list', 'unlock'):
            self.native.reset_mock()
            args = {'action': action, 'backend': 'synthetic'}
            # A replacement registered after load is never selected as fallback.
            with patch('tools.registry.registry.get_entry', side_effect=AssertionError('lookup after load')):
                result = self.invoke(handler, args, task_id='fixture')
            self.assertTrue(result['synthetic'])
            self.native.assert_called_once_with(args, task_id='fixture')
        self.assertEqual(self.schema, before)

    def test_missing_or_async_native_handler_refuses_all_nonpage_actions(self):
        for available, is_async in ((False, False), (True, True)):
            handler = self.register(available=available, is_async=is_async)
            for action in ('list', 'unlock'):
                result = self.invoke(handler, {'action': action})
                self.assertEqual(result['error_type'], 'vault_handler_unavailable')
            self.native.assert_not_called()

    def test_direct_dispatch_rechecks_grant_and_route(self):
        handler = self.register()
        self.ctx.has_capability.return_value = False
        self.assertFalse(self.invoke(handler, {'action': 'list'})['success'])
        self.ctx.has_capability.return_value = True
        with patch('plugin.browser_config', return_value={'cloud_provider': plugin.NAME, 'backend': 'off'}):
            self.assertFalse(json.loads(handler({'action': 'list'}))['success'])
        self.native.assert_not_called()

    def test_config_and_native_failure_never_leak_error_or_retry(self):
        handler = self.register()
        with patch('plugin.browser_config', side_effect=RuntimeError('SYNTHETIC-SECRET')):
            result = handler({'action': 'list'})
        self.assertNotIn('SYNTHETIC-SECRET', result)
        self.native.assert_not_called()
        self.native.side_effect = RuntimeError('SYNTHETIC-SECRET')
        result = self.invoke(handler, {'action': 'unlock'})
        self.assertFalse(result['success'])
        self.assertNotIn('SYNTHETIC-SECRET', json.dumps(result))
        self.native.assert_called_once()

    def test_unselected_provider_preserves_captured_native_dispatch(self):
        handler = self.register()
        with patch('plugin.browser_config', return_value={'cloud_provider': 'other'}):
            result = json.loads(handler({'action': 'fill'}, task_id='fixture'))
        self.assertTrue(result['synthetic'])
        self.native.assert_called_once_with({'action': 'fill'}, task_id='fixture')


if __name__ == '__main__':
    unittest.main()
