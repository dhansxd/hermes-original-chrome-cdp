"""Opt-in finish/reconnect regression on an empty approval-mode shared browser.

A controlled .75-second LaunchServices delivery skew makes listener-only readiness
fail HTTP403. Real GUI identity, consent and scoped execution remain unchanged.
Run with the managed Hermes Python. All receipts/profile state stay in scratch.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import time
import threading
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(tempfile.mkdtemp(prefix='finish-reconnect-regression-',dir=Path.home()/'.hermes/cache/scratch'))
sys.path[:0]=[str(ROOT),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
import psutil
import plugin,consent,observer,worker
from binding import BoundBrowser

DATA=OUT/'approval-data';DATA.mkdir()
(DATA/'Default').mkdir()
(DATA/'Local State').write_text(json.dumps({'devtools':{'remote_debugging':{'user-enabled':True}},'profile':{'last_used':'Default'}}))
report={'level':'source fixture: disposable approval-mode/shared lifecycle; controlled GUI delivery skew; not native chat',
        'events':[],'checks':{},'calls':[],'personal_actions':False}
start=time.monotonic();run=subprocess.run;old_launch=plugin.gui_launch
old_connect=consent._connect_with_consent;report['handshakes']=0
original_request=observer.ScopedObserver._request
original_event=worker.Wire.event
p=plugin.ChromeProvider(DATA,OUT/'workspace');inventory=None;ready_first=True
launch_count=0;dispatches=[]

def log(kind,**fields):
    row={'t':round(time.monotonic()-start,6),'kind':kind,**fields}
    report['events'].append(row)
    with (OUT/'events.jsonl').open('a')as f:f.write(json.dumps(row)+'\n')

def mains():
    result=[]
    for process in psutil.process_iter():
        try:
            info=process.as_dict(attrs=['exe','cmdline'])
            if Path(info['exe']or'').name=='Google Chrome'and '--user-data-dir='+str(DATA)in(info['cmdline']or[]):result.append(process)
        except psutil.Error:pass
    return result

def windows():
    ax=consent.AX();result=[]
    try:
        for process in mains():
            app=ax.ax.AXUIElementCreateApplication(process.pid);ax.refs.append(app)
            ax.ax.AXUIElementSetMessagingTimeout(app,.25)
            values=ax.attr(app,'AXWindows')
            if values:
                for i in range(ax.cf.CFArrayGetCount(values)):
                    node=ax.cf.CFArrayGetValueAtIndex(values,i)
                    result.append({'pid':process.pid,'title':ax.text(node,'AXTitle'),'document':ax.text(node,'AXDocument')})
    finally:ax.clear()
    return result

def bounded(fn,description,seconds=8):
    deadline=time.monotonic()+seconds
    while True:
        try:value=fn()
        except consent.ConsentError as exc:
            if str(exc)not in{'consent_ax_read:-25202','consent_ax_read:-25204'}:raise
            value=None
        if value:return value
        if time.monotonic()>=deadline:raise TimeoutError(description)
        time.sleep(.05)

def recorded_run(argv,**kwargs):
    global launch_count
    if argv and argv[0]=='/usr/bin/open':
        assert '--user-data-dir='+str(DATA)in argv
        assert argv.count('--remote-debugging-port=0')==1
        argv=[x for x in argv if x!='--remote-debugging-port=0']
    if argv and argv[0]=='/usr/bin/open':
        launch_count+=1
        if launch_count==2:
            # A controlled LaunchServices delivery skew; no guard/consent bypass.
            def deliver():
                time.sleep(.75)
                outcome=run(argv,**kwargs)
                log('delayed_dispatch_completed',returncode=outcome.returncode)
            thread=threading.Thread(target=deliver);dispatches.append(thread);thread.start()
            log('gui_delivery_deferred',seconds=.75)
            return subprocess.CompletedProcess(argv,0,'','')
    result=run(argv,**kwargs)
    if argv[:2]==['osascript','-e']and argv[2]==consent.PRESS_SCRIPT:
        log('consent_press',returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)
    return result

def launch(data,seed_url=None):
    global ready_first
    log('launch_requested',first=ready_first)
    old_launch(data,seed_url)
    if ready_first:
        bounded(lambda:any(w['document']==seed_url for w in windows()),'first owned seed ready')
        ready_first=False
    log('launch_returned') # Do not let optional AX diagnostics abort before the real dial.

def recorded_connect(endpoint,data_root,connect,**kwargs):
    def dial(*args,**kw):
        report['handshakes']+=1
        log('handshake_begin',number=report['handshakes'])
        return connect(*args,**kw)
    return old_connect(endpoint,data_root,dial,**kwargs)


def request(self,req,state):
    try:
        result=original_request(self,req,state)
        if req['method']in{'Target.closeTarget','Target.getTargets','Browser.getWindowForTarget'}:
            log('cdp_response',method=req['method'],params=req.get('params'),result=result.get('value'),sessions=copy.deepcopy(self.sessions),closed=self.closed)
        return result
    except Exception as exc:
        log('cdp_error',method=req['method'],params=req.get('params'),error=type(exc).__name__+': '+str(exc),sessions=copy.deepcopy(self.sessions),closed=self.closed)
        raise

def event(self,response):
    if response.get('method','').startswith('Target.'):
        log('cdp_event',event=copy.deepcopy(response))
    return original_event(self,response)

original_finish=p._finish_browser_locked

def shared_finish(entry):
    # Only the shared-root shutdown policy is mapped to the disposable fixture.
    # Account binding/setup still use the ordinary nonpersonal root path.
    with patch.object(plugin,'PERSONAL',DATA):return original_finish(entry)
p._finish_browser_locked=shared_finish

def execute(code):
    result=json.loads(p.execute({'code':code,'timeout_s':30},task_id='finish-reconnect'))
    report['calls'].append(result);log('execute',code=code,result=result)
    return result

try:
    with patch.object(plugin.subprocess,'run',side_effect=recorded_run),patch.object(plugin,'gui_launch',side_effect=launch),patch.object(observer.ScopedObserver,'_request',request),patch.object(worker.Wire,'event',event),patch.object(consent,'_connect_with_consent',recorded_connect):
        first=execute("new_tab('about:blank');js(\"document.title='Disposable finish reconnect';document.body.innerHTML='<input id=check>';window.checkCount=1\");fill_input('#check','finish-ok');print(js(\"JSON.stringify({value:document.querySelector('#check').value,count:window.checkCount})\"))")
        assert first['success'],first
        entry=p.states[('finish-reconnect','default')]
        before_owned=list(entry['state']['owned']);endpoint=entry['endpoint']
        inventory=worker.Wire(endpoint,str(DATA))
        report['independent_before']=inventory('Target.getTargets')['targetInfos']
        log('before_finish_windows',windows=windows())
        second=execute("print(js(\"JSON.stringify({value:document.querySelector('#check').value,count:window.checkCount})\"));print(finish_browser())")
        report['state_after_finish']=copy.deepcopy(p.states.get(('finish-reconnect','default'),{}).get('state'))
        report['independent_after']=inventory('Target.getTargets')['targetInfos']
        after_ids={t['targetId']for t in report['independent_after']}
        report['checks']['all_owned_gone']=not(set(before_owned)&after_ids)
        log('after_finish_windows',windows=windows())
        inventory.close();inventory=None
        report['checks']['finish_reports_success']=second.get('success')and "'success': True"in second.get('stdout','')
        report['checks']['provider_released_entry']=not p.states
        third=execute('print(page_info())')
        report['checks']['fresh_session_succeeds']=third.get('success',False)
        for thread in dispatches:thread.join(5)
        report['windows_after_new_session']=bounded(lambda:windows(),'delayed seed window after attempt')
        report['checks']['one_handshake_per_explicit_connection']=report['handshakes']==3
        final=execute('print(finish_browser())') if third.get('success') else {}
        report['checks']['fresh_session_finish']=bool(final.get('success') and not p.states)
        report['success']=all(report['checks'].values())
except Exception as exc:
    report.update(success=False,error=type(exc).__name__+': '+str(exc));log('failure',error=report['error'])
finally:
    # Preserve adapter outcome before disposable-only hygiene.
    report['remaining_owned_before_teardown']={str(k):copy.deepcopy(e.get('state'))for k,e in p.states.items()}
    if inventory:
        try:inventory.close()
        except Exception:pass
    for entry in p.states.values():
        if entry.get('observer'):entry['observer'].close()
    for thread in dispatches:thread.join(5)
    procs=mains()
    for proc in procs:
        try:proc.terminate()
        except psutil.Error:pass
    _,left=psutil.wait_procs(procs,timeout=4)
    for proc in left:
        try:proc.kill()
        except psutil.Error:pass
    psutil.wait_procs(left,timeout=2)
    report['process_residue']=[proc.pid for proc in mains()]
    (OUT/'result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'success':report.get('success'),'error':report.get('error'),'checks':report['checks'],'call_success':[r.get('success')for r in report['calls']],'process_residue':report['process_residue'],'evidence':str(OUT/'result.json')},indent=2))
sys.exit(0 if report.get('success')else 1)
