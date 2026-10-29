"""Capability denial is metadata-only, never a privileged fallback."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plugin


class RegistrationCapabilityTests(unittest.TestCase):
    def test_missing_grant_registers_only_nonconflicting_refusal_metadata(self):
        ctx=Mock()
        ctx.has_capability.return_value=False
        with patch('plugin.ChromeProvider') as provider:
            plugin.register(ctx)
        ctx.has_capability.assert_called_once_with('tools.override')
        provider.assert_not_called()
        ctx.register_browser_provider.assert_not_called()
        ctx.register_hook.assert_not_called()
        calls=[c.kwargs for c in ctx.register_tool.call_args_list]
        self.assertEqual({c['name'] for c in calls},{'original_chrome_default_browser_exec','original_chrome_default_browser_vault'})
        for call in calls:
            self.assertFalse(call.get('override',False))
            self.assertEqual(call['schema']['name'],call['name'])
            result=json.loads(call['handler']({'code':'new_tab()','action':'fill'}))
            self.assertFalse(result['success'])
            self.assertEqual(result['error_type'],'plugin_capability_required')
            self.assertFalse(result['fallback_used'])

    def test_real_grant_still_registers_native_names_as_overrides(self):
        ctx=Mock()
        ctx.has_capability.return_value=True
        with patch('plugin.ChromeProvider'):
            plugin.register(ctx)
        ctx.has_capability.assert_called_once_with('tools.override')
        ctx.register_browser_provider.assert_called_once()
        calls=[c.kwargs for c in ctx.register_tool.call_args_list]
        self.assertEqual({c['name'] for c in calls},{'browser_exec','browser_vault'})
        self.assertTrue(all(c['override'] for c in calls))


if __name__=='__main__':unittest.main()
