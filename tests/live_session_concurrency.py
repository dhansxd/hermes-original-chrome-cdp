"""Real registered tool, bounded workers and disposable GUI; never personal Chrome.

Run with the Hermes Python interpreter. Evidence goes to a fresh scratch directory.
This is registered-host acceptance, not a native-chat or real-account test.
"""
import concurrent.futures as cf
import inspect
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
import psutil
from hermes_cli.plugins import PluginManager
from hermes_cli.plugins_manifest import PluginManifest
from tools.registry import registry


def main():
    out=Path(tempfile.mkdtemp(prefix='chrome-session-isolation-',dir=Path.home()/'.hermes/cache/scratch'))
    home=out/'host';home.mkdir();data=out/'chrome';data.mkdir()
    os.environ['HERMES_HOME']=str(home)
    (home/'config.yaml').write_text('browser:\n  backend: browser-use\n  cloud_provider: original-chrome-default\nplugins:\n  entries:\n    original-chrome-default:\n      granted_capabilities: [tools.override]\n')
    report={'level':'registered-host + bounded worker + disposable GUI; not chat-native','checks':{},'raw':{}}
    manager=None;provider=None;inventory_url=None
    def save():(out/'result.json').write_text(json.dumps(report,indent=2))
    def check(name,value):
        report['checks'][name]=bool(value);save();print(json.dumps({'check':name,'pass':bool(value)}),flush=True)
        assert value,name
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            body=b'<!doctype html><title>Session fixture</title><button id="inc">increment</button><input id="pw" type="password"><script>window.count=0;document.querySelector("#inc").onclick=()=>++window.count;</script>'
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
    url=f'http://127.0.0.1:{server.server_port}/'
    def dispatch(name,code,timeout=20):
        result=json.loads(registry.dispatch('browser_exec',{'code':code,'timeout_s':timeout},scope=str(home),task_id='fixture-'+name,session_id='chat-'+name,session_key='route-'+name))
        report['raw'].setdefault(name,[]).append(result);save();return result
    def read(name):
        result=dispatch(name,'import json;print(json.dumps(js("({marker:window.marker,count:window.count})")))')
        assert result.get('success'),result
        return json.loads(result['stdout'])
    def inventory():
        with urlopen(inventory_url,timeout=5) as response:return {t['id']:t for t in json.loads(response.read())}
    def exact_processes():
        found=[]
        for process in psutil.process_iter(['name']):
            if process.info['name']!='Google Chrome':continue
            try:
                if '--user-data-dir='+str(data) in process.cmdline():found.append(process)
            except psutil.NoSuchProcess:continue
        return found
    try:
        manager=PluginManager(scope_key=str(home))
        manager._load_plugin(PluginManifest(name='original-chrome-default',source='user',path=str(ROOT),capabilities=['tools.override']))
        loaded=manager._plugins['original-chrome-default'];check('namespaced_registration',loaded.enabled)
        handler=registry.get_entry('browser_exec',scope=str(home)).handler
        provider=inspect.getclosurevars(handler).nonlocals['provider'];provider.data=data.resolve();provider.workspace=out/'workspaces'
        for name in ('a','b'):
            setup=dispatch(name,'goto_url('+repr(url)+');wait_for_load();js('+repr('window.marker='+json.dumps(name)) +');print(page_info())')
            check('setup_'+name,setup.get('success'))
        entries={name:provider.states[('fixture-'+name,'default')] for name in ('a','b')}
        check('independent_observers',entries['a']['observer'] is not entries['b']['observer'])
        port=int((data/'DevToolsActivePort').read_text().splitlines()[0]);inventory_url=f'http://127.0.0.1:{port}/json/list'
        owned={name:set(entry['state']['owned']) for name,entry in entries.items()}
        check('unique_owned_targets',not (owned['a']&owned['b']))
        failed=dispatch('a','print(js("new Promise(resolve=>setTimeout(()=>resolve(++window.count),6500))"))',5)
        check('inflight_timeout',not failed.get('success') and 'browser_exec_timeout' in failed.get('error',''))
        check('peer_survives_timeout',read('b')=={'marker':'b','count':0})
        refused=dispatch('a','print(js("++window.count"))')
        check('uncertain_action_not_replayed',not refused.get('success') and 'uncertain' in refused.get('error',''))
        cleaned=dispatch('a','print(finish_browser())')
        check('quarantined_cleanup',cleaned.get('success'))
        live=inventory();check('failed_target_absent',not (owned['a']&set(live)))
        check('peer_target_preserved',owned['b']<=set(live))
        check('peer_read_after_cleanup',read('b')=={'marker':'b','count':0})
        check('peer_finish',dispatch('b','print(finish_browser())').get('success'))
        check('states_empty',not provider.states)
        # Last explicit finish closes the wholly disposable root; shared original
        # Chrome is never addressed by this fixture.
        check('fixture_browser_closed',not exact_processes())
        report['success']=True
    except Exception as exc:
        report.update(success=False,error_type=type(exc).__name__,error=str(exc));save()
    finally:
        if provider is not None:
            try:provider.unload()
            except Exception as exc:report['cleanup_error']=type(exc).__name__
        if manager is not None:
            try:manager.unload()
            except Exception as exc:report['manager_cleanup_error']=type(exc).__name__
        # Hygiene only: killing a disposable browser is not adapter acceptance.
        processes=exact_processes()
        for process in processes:
            try:process.terminate()
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(processes,timeout=5)
        for process in alive:
            try:process.kill()
            except psutil.NoSuchProcess:pass
        psutil.wait_procs(alive,timeout=3)
        server.shutdown();server.server_close();serving.join(3)
        report['process_residue']=[p.pid for p in exact_processes()]
        if report['process_residue']:report['success']=False
        save();print(json.dumps({'success':report.get('success'),'error':report.get('error'),'evidence':str(out/'result.json')}),flush=True)
    return 0 if report.get('success') else 1


if __name__=='__main__':sys.exit(main())
