"""Exact idle-overflow helper route on disposable Chrome, never personal Chrome."""
import json, os, sys, tempfile, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[os.environ.get('OVERFLOW_SOURCE_ROOT',str(ROOT)),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
import psutil
from plugin import ChromeProvider
from worker import Wire


def main():
    label=sys.argv[1]
    receipt=ROOT/('EVENT-OVERFLOW-'+label.upper()+'.json')
    if receipt.exists():raise RuntimeError('refusing to overwrite receipt')
    work=Path(tempfile.mkdtemp(prefix='chrome-overflow-',dir=Path.home()/'.hermes/cache/scratch'))
    data=work/'data';data.mkdir()
    provider=ChromeProvider(data=data,workspace=work/'work');wire=None
    out={'level':'real disposable Chrome; source provider.execute + bounded worker, NOT native chat','work':str(work),'cases':[]}
    requests=[];burst_done=threading.Event()
    class Page(BaseHTTPRequestHandler):
        def log_message(self,format,*args):pass
        def do_GET(self):
            if self.path.startswith('/noise/'):
                requests.append(self.path)
                time.sleep(.01) # Pace real network events below the idle pump budget.
                body=b'noise'
            else:body=b'<!doctype html><title>Overflow fixture</title><p>ready</p>'
            self.send_response(200);self.send_header('Content-Type','text/html')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
            if self.path=='/noise/999':burst_done.set()
    server=ThreadingHTTPServer(('127.0.0.1',0),Page)
    serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
    url=f'http://127.0.0.1:{server.server_port}/'
    def call(name,code):
        result=json.loads(provider.execute({'session':name,'code':code,'timeout_s':30},task_id='overflow-fixture'))
        return {k:v for k,v in result.items() if k not in ('limitations',)}
    def record(name,result):
        out['cases'].append({'name':name,'result':result});return result
    try:
        first=record('first_navigation',call('first',f'new_tab({url!r}); assert wait_for_load(); print(page_info()); print(js("document.readyState"))'))
        assert first['success'],first
        entry=provider.states[('overflow-fixture','first')];observer=entry['observer']
        wire=Wire(entry['endpoint'])
        control=wire('Target.createTarget',{'url':'data:text/html,<title>Comparator</title>','newWindow':True,'browserContextId':entry['state']['context']})['targetId']
        # A bounded sequential chain avoids background setInterval throttling.
        setup=record('start_burst',call('first', '''print(js("window.__idleProbe={start:Date.now(),ok:0,failed:0,count:1};(async()=>{try{for(let i=0;i<1000;i++){await (await fetch('/noise/'+i,{cache:'no-store'})).text();__idleProbe.ok++}}catch(e){__idleProbe.failed++}finally{__idleProbe.stopped=true}})();true"))'''))
        assert setup['success'],setup
        start=time.monotonic();time.sleep(55) # No provider calls: beyond the real heartbeat window.
        stimulus_complete=burst_done.wait(45) # Bounded stimulus completion, not a plugin timeout change.
        with observer._lock:
            out['idle']={'seconds':time.monotonic()-start,'buffer_length':len(observer.wire.events),'overflow':observer.wire.event_overflow,'observer_closed':observer.closed,'server_requests':len(requests),'stimulus_complete':stimulus_complete}
        assert stimulus_complete and len(requests)==1000 and out['idle']['overflow'] and out['idle']['buffer_length']==4000 and not out['idle']['observer_closed'],out['idle']
        read=record('same_session_read_wait_page_info',call('first','print(js("JSON.stringify({...__idleProbe,title:document.title,ready:document.readyState,elapsedMs:Date.now()-__idleProbe.start})")); assert wait_for_load(); print(page_info())'))
        probe=json.loads(read['stdout'].splitlines()[0])
        assert probe['ok']==1000 and probe['failed']==0 and probe['count']==1 and probe['stopped'] and probe['ready']=='complete',probe
        record('fresh_named_session_navigation_wait_page_info',call('second',f'new_tab({url!r});assert wait_for_load();print(page_info());print(js("document.readyState"));print(wait_for_network_idle(timeout=3,idle_ms=100))'))
        out['independent_session_observer']=provider.states[('overflow-fixture','second')]['observer'] is not observer
        assert out['independent_session_observer']
        history=record('old_session_history_gap',call('first','print(drain_events())'))
        out['history_gap_explicit']=not history['success'] and 'event_buffer_overflow' in history.get('error','') and not history.get('action_replayed')
        network=record('old_session_network_history_gap',call('first','print(wait_for_network_idle(timeout=3,idle_ms=100))'))
        out['network_history_gap_explicit']=not network['success'] and 'event_buffer_overflow' in network.get('error','') and not network.get('action_replayed')
        # Current metadata must still work after an explicit history refusal.
        record('metadata_after_history_refusal',call('first','assert wait_for_load();print(page_info());print(js("__idleProbe.count"))'))
        # Current dialog state is independent of evicted history; answer exactly once.
        record('schedule_dialog',call('first','print(js("setTimeout(()=>alert(\'overflow dialog\'),100);true"))'))
        deadline=time.monotonic()+3;opening=False
        while time.monotonic()<deadline:
            with observer._lock:opening=any(d.get('message')=='overflow dialog' for d in observer.wire.dialogs.values())
            if opening:break
            time.sleep(.05)
        out['dialog_opening_observed']=opening
        assert opening,'dialog stimulus did not open within 3 seconds'
        dialog=record('dialog_after_overflow',call('first','print(page_info())'))
        out['dialog_visible']=dialog['success'] and 'overflow dialog' in dialog['stdout']
        assert out['dialog_visible'],dialog
        record('answer_dialog',call('first','cdp("Page.handleJavaScriptDialog",accept=True);print(page_info())'))
        out['cleanup_success']=provider.close_session('overflow-fixture')
        remaining=wire('Target.getTargets')['targetInfos']
        out['control_preserved']=any(t['targetId']==control for t in remaining)
        out['only_control_remains']={t['targetId'] for t in remaining if t.get('type')=='page'}=={control}
        out['success']=(all(c['result']['success'] for c in out['cases'] if c['name'] not in ('old_session_history_gap','old_session_network_history_gap')) and out['history_gap_explicit'] and out['network_history_gap_explicit'] and out.get('dialog_visible') and out['cleanup_success'] and out['control_preserved'] and out['only_control_remains'])
    except Exception:
        out['failure']=traceback.format_exc();out['success']=False
    finally:
        for entry in list(provider.states.values()):provider._release_observer(entry)
        if wire is None and (data/'DevToolsActivePort').exists():
            lines=(data/'DevToolsActivePort').read_text().splitlines();wire=Wire('ws://127.0.0.1:'+lines[0]+lines[1])
        if wire:
            try:wire('Browser.close')
            except Exception:pass
            wire.close()
        deadline=time.monotonic()+5
        while True:
            residue=[p.pid for p in psutil.process_iter(['cmdline']) if '--user-data-dir='+str(data) in (p.info['cmdline'] or [])]
            if not residue or time.monotonic()>deadline:break
            time.sleep(.1)
        out['process_residue']=residue
        server.shutdown();server.server_close();serving.join(2)
        out['server_stopped']=not serving.is_alive()
        receipt.write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2),flush=True)
    assert out.get('success') and not residue and out['server_stopped'],out

if __name__=='__main__':main()
