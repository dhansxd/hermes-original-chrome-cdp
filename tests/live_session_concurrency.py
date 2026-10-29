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
    (home/'config.yaml').write_text('browser:\n  backend: browser-use\n  cloud_provider: original-chrome-default\nagent:\n  disabled_toolsets: [browser, browser-use]\n')
    report={'level':'registered-host + bounded worker + disposable GUI; not chat-native','checks':{},'raw':{}}
    report_lock=threading.RLock()
    manager=None;provider=None;inventory_url=None
    def save():
        with report_lock:(out/'result.json').write_text(json.dumps(report,indent=2))
    def check(name,value):
        report['checks'][name]=bool(value);save();print(json.dumps({'check':name,'pass':bool(value)}),flush=True)
        assert value,name
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,format,*args):pass
        def do_GET(self):
            body=b'<!doctype html><title>Session fixture</title><button id="inc">increment</button><input id="pw" type="password"><script>window.count=0;document.querySelector("#inc").onclick=()=>++window.count;</script>'
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
    url=f'http://127.0.0.1:{server.server_port}/'
    def dispatch(name,code,timeout=20):
        raw=registry.dispatch('browser_original_chrome_exec',{'code':code,'timeout_s':timeout},scope=str(home),task_id='fixture-'+name,session_id='chat-'+name,session_key='route-'+name)
        assert isinstance(raw,str)
        result=json.loads(raw)
        with report_lock:report['raw'].setdefault(name,[]).append(result);save()
        return result
    def read(name):
        result=dispatch(name,'import json;print(json.dumps(js("({marker:window.marker,count:window.count})")))')
        assert result.get('success'),result
        return json.loads(result['stdout'])
    def inventory():
        assert inventory_url
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
        manager._load_plugin(PluginManifest(name='original-chrome-default',source='user',path=str(ROOT),capabilities=[]))
        loaded=manager._plugins['original-chrome-default'];check('namespaced_registration',loaded.enabled)
        registered=registry.get_entry('browser_original_chrome_exec',scope=str(home));assert registered is not None
        handler=registered.handler
        provider=inspect.getclosurevars(handler).nonlocals['provider'];provider.data=data.resolve();provider.workspace=out/'workspaces'
        for name in ('a','b'):
            setup=dispatch(name,'goto_url('+repr(url)+');wait_for_load();js('+repr('window.marker='+json.dumps(name)) +');print(page_info())')
            check('setup_'+name,setup.get('success'))
        entries={name:provider.states[('fixture-'+name,'default')] for name in ('a','b')}
        check('independent_observers',entries['a']['observer'] is not entries['b']['observer'])
        port=int((data/'DevToolsActivePort').read_text().splitlines()[0]);inventory_url=f'http://127.0.0.1:{port}/json/list'
        owned={name:set(entry['state']['owned']) for name,entry in entries.items()}
        check('unique_owned_targets',not (owned['a']&owned['b']))
        # Barrier at an actual outbound CDP command, not Python sleep overlap.
        sent=threading.Event();observer=entries['a']['observer'];send=observer.wire.ws.send
        def observed_send(text,*args,**kwargs):
            value=json.loads(text)
            result=send(text,*args,**kwargs)
            if value['method']=='Runtime.evaluate' and 'parallelProbe' in value.get('params',{}).get('expression',''):sent.set()
            return result
        observer.wire.ws.send=observed_send
        with cf.ThreadPoolExecutor(max_workers=2) as pool:
            pending=pool.submit(dispatch,'a','print(js("new Promise(resolve=>{window.parallelProbe=Date.now();setTimeout(()=>resolve(Date.now()),2500)})"))')
            check('actual_cdp_command_inflight',sent.wait(5))
            started=time.monotonic();peer=read('b');finished=time.monotonic()
            check('peer_finishes_before_pending_response',not pending.done() and peer=={'marker':'b','count':0})
            result=pending.result(10);check('pending_result_exact',result.get('success'))
            report['parallel_timing']={'peer_elapsed_s':finished-started,'pending_finished_after_peer':True};save()
        observer.wire.ws.send=send
        failed=dispatch('a','print(js("++window.count;new Promise(resolve=>setTimeout(()=>resolve(window.count),6500))"))',5)
        check('inflight_timeout',not failed.get('success') and 'browser_exec_timeout' in failed.get('error',''))
        # The send may have succeeded: independent disposable-target readback,
        # never replay through the quarantined session, proves the side effect.
        peer_observer=entries['b']['observer']
        with peer_observer._lock:
            raw=peer_observer.wire
            sid=raw('Target.attachToTarget',{'targetId':entries['a']['state']['current'],'flatten':True})['sessionId']
            try:value=raw('Runtime.evaluate',{'expression':'window.count','returnByValue':True},sid)['result']['value']
            finally:raw('Target.detachFromTarget',{'sessionId':sid})
        check('timed_out_action_executed_once',value==1)
        check('peer_survives_timeout',read('b')=={'marker':'b','count':0})
        refused=dispatch('a','print(js("++window.count"))')
        check('uncertain_action_not_replayed',not refused.get('success') and 'uncertain' in refused.get('error',''))
        cleaned=dispatch('a','print(finish_browser())')
        check('quarantined_cleanup',cleaned.get('success'))
        live=inventory();check('failed_target_absent',not (owned['a']&set(live)))
        check('peer_target_preserved',owned['b']<=set(live))
        check('peer_read_after_cleanup',read('b')=={'marker':'b','count':0})
        # More than ten callers: no design cap, unique state and one increment.
        names=['b']+['n'+str(i) for i in range(11)]
        barrier=threading.Barrier(11)
        def setup_named(name):
            barrier.wait(10)
            return name,dispatch(name,'goto_url('+repr(url)+');wait_for_load();js('+repr('window.marker='+json.dumps(name))+')',40)
        with cf.ThreadPoolExecutor(max_workers=11) as pool:created=dict(pool.map(setup_named,names[1:]))
        check('eleven_simultaneous_new_sessions',all(v.get('success') for v in created.values()))
        snapshots={name:provider.states[('fixture-'+name,'default')]['state'] for name in names}
        all_owned=[set(s['owned']) for s in snapshots.values()]
        check('twelve_unique_session_targets',len(set().union(*all_owned))==sum(map(len,all_owned))==12)
        barrier=threading.Barrier(len(names))
        def increment(name):
            barrier.wait(10)
            r=dispatch(name,'import json;js("document.querySelector(\'#inc\').click()");print(json.dumps(js("({marker:window.marker,count:window.count})")))')
            return name,r
        with cf.ThreadPoolExecutor(max_workers=len(names)) as pool:incremented=dict(pool.map(increment,names))
        check('twelve_parallel_single_increments',all(r.get('success') and json.loads(r['stdout'])=={'marker':n,'count':1} for n,r in incremented.items()))
        original_b=set(snapshots['b']['owned']);cancelled=set(snapshots['n0']['owned'])
        barrier=threading.Barrier(3)
        def mixed(kind):
            barrier.wait(10)
            if kind=='finish':return dispatch('b','print(finish_browser())').get('success')
            if kind=='cancel':manager.invoke_hook('agent_loop_stopped',session_key='route-n0');return ('fixture-n0','default') not in provider.states
            return read('n1')=={'marker':'n1','count':1}
        with cf.ThreadPoolExecutor(max_workers=3) as pool:mixed_results=list(pool.map(mixed,['finish','cancel','read']))
        check('parallel_finish_cancel_read',all(mixed_results))
        live=inventory();check('finish_cancel_targets_absent',not (original_b&set(live)) and not (cancelled&set(live)))
        check('ten_peer_targets_preserved',all(set(snapshots[n]['owned'])<=set(live) for n in names if n not in ('b','n0')))
        for name in names:
            if name not in ('b','n0'):
                check('final_read_'+name,read(name)=={'marker':name,'count':1})
                check('final_finish_'+name,dispatch(name,'print(finish_browser())').get('success'))
        check('session_lock_slots_released',not provider._session_locks)

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
