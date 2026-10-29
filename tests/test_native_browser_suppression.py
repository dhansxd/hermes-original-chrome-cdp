"""Actual host selection, search, delegation and plugin removal remain fail closed."""
import json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import plugin


class NativeBrowserSuppressionTests(unittest.TestCase):
    def test_route_and_suppression_use_effective_profile_configuration(self):
        effective={'browser':{'cloud_provider':plugin.NAME},
                   'agent':{'disabled_toolsets':['browser','browser-use']}}
        with patch('hermes_cli.config.load_config_readonly',return_value=effective) as load, \
             patch('hermes_cli.config.read_raw_config',side_effect=AssertionError('raw files omit managed configuration')) as raw:
            self.assertEqual(plugin.browser_config(),effective['browser'])
            self.assertTrue(plugin.native_browser_tools_disabled())
        self.assertEqual(load.call_count,2)
        raw.assert_not_called()

    def test_policy_requires_both_native_toolsets_and_rejects_malformed_values(self):
        valid=[['browser','browser-use'],['web','browser-use','browser'],
               '["browser", "browser-use"]',"['browser', 'browser-use']"]
        invalid=[None,{},'browser,browser-use','[browser, browser-use]',
                 ['browser'],['browser-use'],['browser','browser-use',None],
                 {'browser':True,'browser-use':True},'__import__("os")',
                 "('browser', 'browser-use')",[' browser','browser-use'],
                 ['browser','browser-use '],'[" browser", "browser-use"]']
        for value in valid+invalid:
            with self.subTest(value=value),patch('hermes_cli.config.load_config_readonly',
                    return_value={'agent':{'disabled_toolsets':value}}):
                self.assertEqual(plugin.native_browser_tools_disabled(),value in valid)
        with patch('hermes_cli.config.load_config_readonly',side_effect=ValueError('unreadable')):
            self.assertFalse(plugin.native_browser_tools_disabled())

    def test_real_host_keeps_unique_browser_tools_and_cannot_rediscover_native_routes(self):
        import model_tools
        from hermes_constants import set_hermes_home_override,reset_hermes_home_override
        from hermes_cli.plugins import PluginManager,PluginManifest
        from tools.registry import registry
        from toolsets import resolve_toolset
        from tools.tool_search import (dispatch_tool_search,resolve_underlying_call,
            session_tool_names,ToolSearchConfig)
        from tools.delegate_tool_toolsets import _resolve_child_toolsets
        unique={'browser_original_chrome_exec','browser_original_chrome_vault'}
        disabled=['browser','browser-use']
        enabled=disabled+['original_chrome']
        with tempfile.TemporaryDirectory(prefix='chrome-host-suppression-') as temporary:
            home=Path(temporary).resolve()
            (home/'config.yaml').write_text(json.dumps({'browser':{'cloud_provider':plugin.NAME},
                'agent':{'disabled_toolsets':disabled}}))
            token=set_hermes_home_override(home)
            manager=PluginManager(scope_key=str(home))
            try:
                with patch.dict(os.environ,HERMES_HOME=str(home),HERMES_DISABLE_LAZY_INSTALLS='1'), \
                     patch('subprocess.Popen',side_effect=AssertionError('host schema probe cannot launch processes')):
                    native=set(resolve_toolset('browser'))|set(resolve_toolset('browser-use'))
                    self.assertTrue({'browser_exec','browser_cdp','browser_dialog','browser_vault'}<=native)
                    baselines={name:registry.get_entry(name,scope=str(home)) for name in native}
                    manager._load_plugin(PluginManifest(name=plugin.NAME,source='user',path=str(ROOT)))
                    loaded=manager._plugins[plugin.NAME]
                    self.assertTrue(loaded.enabled,loaded.error)
                    for name,entry in baselines.items():
                        self.assertIs(registry.get_entry(name,scope=str(home)),entry,name)
                    defs=model_tools.get_tool_definitions(enabled,disabled,quiet_mode=True,skip_tool_search_assembly=True)
                    self.assertEqual(set(session_tool_names(defs)),unique)
                    for bundles in (['hermes-cli','original_chrome'],None):
                        selected=model_tools._select_tool_names(bundles,disabled,True)
                        self.assertTrue(unique<=selected)
                        self.assertFalse(native&selected)
                    search=json.loads(dispatch_tool_search({'queries':['browser','vault'],'limit':20},
                        current_tool_defs=defs,config=ToolSearchConfig.from_raw({})))
                    self.assertEqual(set(search['tools']),unique)
                    for name in native:
                        resolved,args,error=resolve_underlying_call({'name':name,'arguments':{}},
                            session_tool_names=session_tool_names(defs))
                        self.assertIsNone(resolved);self.assertTrue(error)
                    parent=SimpleNamespace(enabled_toolsets=enabled,disabled_toolsets=disabled)
                    for desired in (None,enabled):
                        child_enabled,child_disabled=_resolve_child_toolsets(parent,desired,'worker')
                        selected=model_tools._select_tool_names(child_enabled,child_disabled,True)
                        self.assertEqual(selected,unique)
                        self.assertTrue(set(disabled)<=set(child_disabled))
                    manager.unload()
                    after=model_tools.get_tool_definitions(enabled,disabled,quiet_mode=True,skip_tool_search_assembly=True)
                    self.assertEqual(set(session_tool_names(after)),set())
                    for name,entry in baselines.items():
                        self.assertIs(registry.get_entry(name,scope=str(home)),entry,name)
                    self.assertEqual(json.loads((home/'config.yaml').read_text())['agent']['disabled_toolsets'],disabled)
            finally:
                manager.unload()
                reset_hermes_home_override(token)


if __name__=='__main__':unittest.main()
