"""Real public plugin registration in a disposable profile, no browser access."""
import copy,inspect,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path.home()/'.hermes/hermes-agent'))
import hermes_bootstrap
scratch=Path.home()/'.hermes/cache/scratch';scratch.mkdir(parents=True,exist_ok=True)
home=Path(tempfile.mkdtemp(prefix='native-chrome-reg-',dir=scratch)).resolve()
os.environ['HERMES_HOME']=str(home)
(home/'config.yaml').write_text('browser:\n  backend: browser-use\n  cloud_provider: original-chrome-default\nplugins:\n  entries:\n    original-chrome-default:\n      granted_capabilities: [tools.override]\n')
from hermes_cli.plugins import PluginContext,PluginManager
from hermes_cli.plugins_manifest import PluginManifest
from tools.registry import registry
from tools.browser_use_cli import BROWSER_EXEC_SCHEMA
from plugin import register,ChromeProvider
from unittest.mock import patch
manager=PluginManager(scope_key=str(home))
manager._load_plugin(PluginManifest(name='original-chrome-default',source='user',path=str(ROOT),capabilities=['tools.override']))
loaded=manager._plugins['original-chrome-default']
assert loaded.enabled,loaded.error
assert loaded.module.__name__.startswith('hermes_plugins.')
handler=registry.get_entry('browser_exec',scope=str(home)).handler
provider=inspect.getclosurevars(handler).nonlocals['provider']
assert provider.__class__.__module__.startswith(loaded.module.__name__+'.')
assert registry.get_entry('browser_exec',scope=str(home)).schema==BROWSER_EXEC_SCHEMA
from tools import browser_vault_tool as native
assert registry.get_entry('browser_vault',scope=str(home)).schema==native.BROWSER_VAULT_SCHEMA
for action, function, arguments in [('list','browser_vault_list',{}),('unlock','browser_vault_unlock',{'backend':'synthetic'})]:
    with patch.object(native,function,return_value='{"success":true,"synthetic":true}') as called:
        result=registry.dispatch('browser_vault',dict(action=action,**arguments),scope=str(home))
        assert json.loads(result)['synthetic']
        called.assert_called_once()

for action in ['fill','save_login','enter_code']:
    result=json.loads(registry.dispatch('browser_vault',{'action':action,'handle':'no-real-vault-item'},scope=str(home)))
    assert result['error_type']=='vault_binding_unavailable',result
class HeldObserver:
    closed=False
    def close(self):self.closed=True
held=HeldObserver()
provider.states[('fixture','default')]={'observer':held,'state':None,'endpoint':None}
for action in ['fill','save_login','enter_code']:
    result=json.loads(registry.dispatch('browser_vault',{'action':action,'handle':'no-real-vault-item'},scope=str(home)))
    assert result['error_type']=='vault_binding_unavailable',result
provider.unload()
assert held.closed
from hermes_cli.tools_config_providers import _plugin_browser_providers
rows=_plugin_browser_providers()
assert any(row['browser_provider']=='original-chrome-default' for row in rows),rows
manager.unload()
assert registry.get_entry('browser_exec',scope=str(home)).handler is not handler
print(json.dumps({'namespaced_plugin_manager_loaded':True,'unload_restores_original':True,'schema_preserved':True,'unrelated_held_observer_does_not_replace_missing_binding':True,'observer_unload_closes':True,'vault_write_tools_refuse_before_secret_access':True,'real_picker_row_available':True,'isolated_home':str(home)},indent=2))
