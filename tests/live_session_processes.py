"""Independent registered hosts sharing only a disposable Chrome root.

Not native-chat, personal-profile, consent-prompt or Google Flow API acceptance.
Run via the managed Hermes interpreter; output is kept in scratch, never Git.
"""
import concurrent.futures as cf
import inspect
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
import psutil


def child(home,data):
    from hermes_cli.plugins import PluginManager
    from hermes_cli.plugins_manifest import PluginManifest
    from tools.registry import registry
    home=Path(home);home.mkdir();data=Path(data)
    os.environ['HERMES_HOME']=str(home)
    (home/'config.yaml').write_text('browser:\n  backend: browser-use\n  cloud_provider: original-chrome-default\nagent:\n  disabled_toolsets: [browser, browser-use]\n')
    manager=PluginManager(scope_key=str(home))
    manager._load_plugin(PluginManifest(name='original-chrome-default',source='user',path=str(ROOT),capabilities=[]))
    loaded=manager._plugins['original-chrome-default'];assert loaded.enabled,loaded.error
    registered=registry.get_entry('browser_original_chrome_exec',scope=str(home));assert registered is not None
    provider=inspect.getclosurevars(registered.handler).nonlocals['provider']
    provider.data=data.resolve();provider.workspace=home/'workspaces'
    # Wholly disposable root, but preserve its shared process exactly as the
    # production PERSONAL branch does. Each child owns only its known targets.
    module=sys.modules[provider.__class__.__module__]
    setattr(module,'PERSONAL',data.resolve())
    setattr(module,'verify_account',lambda *a:None)
    try:
        for line in sys.stdin:
            request=json.loads(line)
            if request.get('quit'):break
            result=registry.dispatch('browser_original_chrome_exec',request,scope=str(home),task_id='process-'+home.name,session_id='chat-'+home.name,session_key='route-'+home.name)
            assert isinstance(result,str)
            print(result,flush=True)
    finally:manager.unload()


def main():
    from plugin import gui_launch
    from worker import Wire
    out=Path(tempfile.mkdtemp(prefix='chrome-process-isolation-',dir=Path.home()/'.hermes/cache/scratch'))
    data=out/'chrome';data.mkdir();control=None;children=[]
    report={'level':'two independent registered-host processes; disposable root; not native chat','checks':{}}
    def check(name,value):
        report['checks'][name]=bool(value);print(json.dumps({'check':name,'pass':bool(value)}),flush=True)
        (out/'result.json').write_text(json.dumps(report,indent=2));assert value,name
    def processes():
        result=[]
        for p in psutil.process_iter(['name']):
            if p.info['name']!='Google Chrome':continue
            try:
                if '--user-data-dir='+str(data) in p.cmdline():result.append(p)
            except psutil.NoSuchProcess:continue
        return result
    def call(proc,code,timeout=20):
        proc.stdin.write(json.dumps({'code':code,'timeout_s':timeout})+'\n');proc.stdin.flush()
        line=proc.stdout.readline();assert line,'child exited without response'
        return json.loads(line)
    try:
        gui_launch(data,'about:blank')
        deadline=time.monotonic()+10
        while not (data/'DevToolsActivePort').exists() and time.monotonic()<deadline:time.sleep(.1)
        port,path=(data/'DevToolsActivePort').read_text().splitlines()[:2]
        endpoint='ws://127.0.0.1:'+port+path
        control=Wire(endpoint,str(data))
        before=control('Target.getTargets')['targetInfos']
        manual={t['targetId'] for t in before if t.get('type')=='page'}
        inventory_url='http://127.0.0.1:'+port+'/json/list'
        def inventory():
            with urlopen(inventory_url,timeout=5) as response:return {t['id']:t for t in json.loads(response.read()) if t.get('type')=='page'}

        for name in ('one','two'):
            children.append(subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--child',str(out/name),str(data)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True))
        a,b=children
        with cf.ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(call,p,'js('+repr('window.marker='+json.dumps(n)+';window.count=0')+');print(cdp("Target.getTargets"))') for p,n in [(a,'one'),(b,'two')]]
            setup=[job.result(30) for job in jobs]
        report['setup']=setup;check('independent_process_setup',all(r.get('success') for r in setup))
        owned=set(inventory())-manual;check('two_unique_owned_targets',len(owned)==2)
        with cf.ThreadPoolExecutor(max_workers=2) as pool:
            pending=pool.submit(call,a,'print(js("++window.count;new Promise(resolve=>setTimeout(()=>resolve(window.count),6500))"))',5)
            time.sleep(.3)
            quick=call(b,'print(js("window.marker"))')
            check('peer_completes_while_other_process_waits',quick.get('success') and quick['stdout'].strip()=='two' and not pending.done())
            failed=pending.result(15)
        report['timeout']=failed;check('timeout_stays_in_own_process',not failed.get('success') and 'timeout' in failed.get('error',''))
        check('peer_after_timeout',call(b,'print(js("window.marker"))').get('success'))
        # Close the healthy peer while the failed owner still needs cleanup.
        finished=call(b,'print(finish_browser())');check('peer_finish',finished.get('success'))
        check('failed_owner_still_has_target',len(set(inventory())-manual)==1)
        cleaned=call(a,'print(finish_browser())');check('failed_owner_cleanup',cleaned.get('success'))
        check('only_manual_target_remains',set(inventory())==manual)
        check('shared_disposable_process_preserved',bool(processes()))
        report['success']=True
    except Exception as exc:report.update(success=False,error_type=type(exc).__name__,error=str(exc))
    finally:
        for p in children:
            try:p.stdin.write('{"quit":true}\n');p.stdin.flush();p.wait(15)
            except Exception:p.kill();p.wait(5)
            if p.stdin:p.stdin.close()
            if p.stdout:p.stdout.close()
        if control:
            try:control('Browser.close')
            except Exception:pass
            control.close()
        deadline=time.monotonic()+5
        while processes() and time.monotonic()<deadline:time.sleep(.1)
        remaining=processes()
        report['fixture_residue_before_hygiene']=[p.pid for p in remaining]
        if remaining:report['success']=False
        for p in remaining:
            try:p.terminate()
            except psutil.NoSuchProcess:pass
        psutil.wait_procs(remaining,timeout=3)
        (out/'result.json').write_text(json.dumps(report,indent=2))
        print(json.dumps({'success':report.get('success'),'error':report.get('error'),'evidence':str(out/'result.json')}),flush=True)
    return 0 if report.get('success') else 1


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child':child(sys.argv[2],sys.argv[3])
    else:sys.exit(main())
