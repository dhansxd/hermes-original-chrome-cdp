"""Compatibility faults exercised through the real namespaced plugin loader."""
import json
import builtins
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class RegistrationResilienceTests(unittest.TestCase):
    def test_missing_vault_registration_does_not_rollback_browser(self):
        self.check_registration('missing')

    def test_vault_import_failure_does_not_rollback_browser(self):
        self.check_registration('import')

    def test_adapter_import_failure_never_falls_back(self):
        self.check_registration('adapter')

    def check_registration(self, failure):
        from hermes_cli.plugins import PluginManager
        from hermes_cli.plugins_manifest import PluginManifest
        from tools.registry import registry
        from tools import browser_vault_tool as native
        from tools.browser_use_cli import BROWSER_EXEC_SCHEMA
        original_get = registry.get_entry
        real_import = builtins.__import__
        def injected_import(name, globals=None, locals=None, fromlist=(), level=0):
            if (failure=='import' and name=='tools' and 'browser_vault_tool' in fromlist
                    or failure=='adapter' and name.endswith('vault_adapter')):
                raise ImportError('synthetic compatibility fault')
            return real_import(name,globals,locals,fromlist,level)
        with tempfile.TemporaryDirectory(dir=Path.home()/'.hermes/cache/scratch') as home:
            home = str(Path(home).resolve())
            Path(home, 'config.yaml').write_text('browser:\n  cloud_provider: original-chrome-default\nplugins:\n  entries:\n    original-chrome-default:\n      granted_capabilities: [tools.override]\n')
            with patch.dict(os.environ, HERMES_HOME=home):
                manager = PluginManager(scope_key=home)
                manifest = PluginManifest(name='original-chrome-default', source='user',
                    path=str(ROOT), capabilities=['tools.override'])
                try:
                    with patch('builtins.__import__',side_effect=injected_import), patch.object(registry, 'get_entry', side_effect=lambda name, **kw:
                            None if name == 'browser_vault' and failure=='missing' else original_get(name, **kw)):
                        manager._load_plugin(manifest)
                    loaded = manager._plugins['original-chrome-default']
                    self.assertTrue(loaded.enabled, loaded.error)
                    assert loaded.module is not None
                    self.assertTrue(loaded.module.__name__.startswith('hermes_plugins.'))
                    browser = registry.get_entry('browser_exec', scope=home)
                    assert browser is not None
                    self.assertEqual(browser.schema, BROWSER_EXEC_SCHEMA)
                    for action, function in ([] if failure=='import' else [('list','browser_vault_list'),('unlock','browser_vault_unlock')]):
                        with patch.object(native,function,return_value='{"success":true,"synthetic":true}') as called:
                            result=json.loads(registry.dispatch('browser_vault',{'action':action,'backend':'synthetic'},scope=home))
                        self.assertTrue(result.get('synthetic'),result)
                        called.assert_called_once()
                    for action in ['fill', 'save_login', 'enter_code']:
                        with patch('builtins.__import__',side_effect=injected_import), patch.object(native, '_ensure_supervisor', side_effect=AssertionError('unsafe fallback')):
                            result = json.loads(registry.dispatch('browser_vault', {'action':action}, scope=home))
                        self.assertFalse(result['success'])
                        self.assertEqual(result['error_type'], 'vault_compatibility_unavailable')
                finally:
                    manager.unload()


if __name__ == '__main__':
    unittest.main()
