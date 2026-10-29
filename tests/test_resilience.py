"""Missing optional native vault cannot roll back real namespaced registration."""
import builtins
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class RegistrationResilienceTests(unittest.TestCase):
    def test_missing_vault_registration_does_not_rollback_browser(self):
        self.check_registration(False)

    def test_native_vault_module_is_never_imported(self):
        self.check_registration(True)

    def check_registration(self, prohibit_native):
        from hermes_cli.plugins import PluginManager
        from hermes_cli.plugins_manifest import PluginManifest
        from tools.registry import registry
        original_get = registry.get_entry
        real_import = builtins.__import__

        def checked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if prohibit_native and (name in ('tools.browser_use_cli','tools.approval_context') or 'browser_vault_tool' in name or
                    'browser_vault_tool' in (fromlist or ()) or 'vault_adapter' in name):
                raise AssertionError('private native vault import')
            return real_import(name, globals, locals, fromlist, level)

        with tempfile.TemporaryDirectory(prefix='vault-policy-registration-') as home:
            home = str(Path(home).resolve())
            Path(home, 'config.yaml').write_text(json.dumps({
                'agent': {'disabled_toolsets': ['browser','browser-use']},
                'browser': {'backend': 'browser-use', 'cloud_provider': 'original-chrome-default'},
                'plugins': {'entries': {'original-chrome-default': {
                    'settings': {}}}}}))
            with patch.dict(os.environ, HERMES_HOME=home):
                manager = PluginManager(scope_key=home)
                manifest = PluginManifest(name='original-chrome-default', source='user',
                    path=str(ROOT), capabilities=[])
                try:
                    with patch('builtins.__import__', side_effect=checked_import), \
                         patch.object(registry, 'get_entry', side_effect=lambda name, **kw:
                            None if name == 'browser_vault' else original_get(name, **kw)):
                        manager._load_plugin(manifest)
                    loaded = manager._plugins['original-chrome-default']
                    self.assertTrue(loaded.enabled, loaded.error)
                    self.assertTrue(loaded.module.__name__.startswith('hermes_plugins.'))
                    browser = registry.get_entry('browser_original_chrome_exec', scope=home)
                    self.assertIsNotNone(browser)
                    self.assertIn('code', browser.schema['parameters']['properties'])
                    for action in ('list', 'unlock', 'fill', 'save_login', 'enter_code'):
                        with patch.object(registry,'get_entry',side_effect=lambda name,**kw:
                                None if name=='browser_vault' else original_get(name,**kw)):
                            result=json.loads(registry.dispatch('browser_original_chrome_vault',{'action':action},scope=home))
                        if action in ('list','unlock'):
                            self.assertIn('Unknown tool: browser_vault',result['error'])
                        else:
                            self.assertFalse(result['success'])
                            self.assertEqual(result['error_type'],'vault_page_actions_unavailable')
                finally:
                    manager.unload()


if __name__ == '__main__':
    unittest.main()
