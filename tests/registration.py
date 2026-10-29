"""Real public plugin registration in a disposable profile, no browser access."""
import copy,inspect,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path.home()/'.hermes/hermes-agent'))
scratch=Path.home()/'.hermes/cache/scratch';scratch.mkdir(parents=True,exist_ok=True)
home=Path(tempfile.mkdtemp(prefix='native-chrome-reg-',dir=scratch)).resolve()
os.environ['HERMES_HOME']=str(home)
(home/'config.yaml').write_text('browser:\n  backend: browser-use\n  cloud_provider: original-chrome-default\nplugins:\n  entries:\n    original-chrome-default:\n      granted_capabilities: [tools.override]\n')
from hermes_cli.plugins import PluginContext,PluginManager
from hermes_cli.plugins_manifest import PluginManifest
from tools.registry import registry
from plugin import register,ChromeProvider
from unittest.mock import patch
native_calls=[]
def synthetic_native(args,**kwargs):
    native_calls.append((args,kwargs))
    return '{"success":true,"synthetic":true}'
synthetic_schema=json.loads((ROOT/'vault_schema.json').read_text())
registry.register('browser_vault','browser',synthetic_schema,synthetic_native,override=True,scope=str(home))
browser_schema=json.loads((ROOT/'browser_schema.json').read_text())
registry.register('browser_exec','browser-use',browser_schema,lambda args,**kw:'{"success":true}',override=True,scope=str(home))
manager=PluginManager(scope_key=str(home))
manager._load_plugin(PluginManifest(name='original-chrome-default',source='user',path=str(ROOT),capabilities=['tools.override']))
loaded=manager._plugins['original-chrome-default']
assert loaded.enabled,loaded.error
assert loaded.module.__name__.startswith('hermes_plugins.')
handler=registry.get_entry('browser_exec',scope=str(home)).handler
provider=inspect.getclosurevars(handler).nonlocals['provider']
assert provider.__class__.__module__.startswith(loaded.module.__name__+'.')
registered_schema=registry.get_entry('browser_exec',scope=str(home)).schema
parameters=copy.deepcopy(registered_schema['parameters'])
parameters['properties']['code']['description']=browser_schema['parameters']['properties']['code']['description']
assert parameters==browser_schema['parameters']
assert registry.get_entry('browser_vault',scope=str(home)).schema==synthetic_schema
for action in ['list','unlock']:
    args={'action':action,'backend':'synthetic'}
    result=registry.dispatch('browser_vault',args,scope=str(home))
    assert json.loads(result)['synthetic']
    assert native_calls[-1][0]==args
assert len(native_calls)==2

for action in ['fill','save_login','enter_code']:
    result=json.loads(registry.dispatch('browser_vault',{'action':action,'handle':'no-real-vault-item'},scope=str(home)))
    assert result['error_type']=='vault_page_actions_unavailable',result
class HeldObserver:
    closed=False
    def close(self):self.closed=True
held=HeldObserver()
provider.states[('fixture','default')]={'observer':held,'state':None,'endpoint':None}
for action in ['fill','save_login','enter_code']:
    result=json.loads(registry.dispatch('browser_vault',{'action':action,'handle':'no-real-vault-item'},scope=str(home)))
    assert result['error_type']=='vault_page_actions_unavailable',result
provider.unload()
assert held.closed
from hermes_cli.tools_config_providers import _plugin_browser_providers
rows=_plugin_browser_providers()
assert any(row['browser_provider']=='original-chrome-default' for row in rows),rows
manager.unload()
assert registry.get_entry('browser_exec',scope=str(home)).handler is not handler
print(json.dumps({'namespaced_plugin_manager_loaded':True,'unload_restores_original':True,'schema_preserved':True,'unrelated_held_observer_does_not_replace_missing_binding':True,'observer_unload_closes':True,'vault_write_tools_refuse_before_secret_access':True,'real_picker_row_available':True,'isolated_home':str(home)},indent=2))
