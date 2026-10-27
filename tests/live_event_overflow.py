"""Exact idle-overflow helper route on disposable Chrome, never personal Chrome."""
import json, os, sys, tempfile, time, traceback
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
    url='data:text/html,<title>Overflow fixture</title><p>ready</p>'
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
        setup=record('start_burst',call('first', '''print(js("window.__idleProbe={start:Date.now(),ok:0,failed:0,count:1};window.__noise=setInterval(()=>fetch('data:text/plain,idle-probe').then(r=>r.text()).then(()=>__idleProbe.ok++).catch(()=>__idleProbe.failed++),30);setTimeout(()=>{clearInterval(__noise);__idleProbe.stopped=true},52000);true"))'''))
        assert setup['success'],setup
        start=time.monotonic();time.sleep(55) # No provider calls: beyond the real heartbeat window.
        with observer._lock:
            out['idle']={'seconds':time.monotonic()-start,'buffer_length':len(observer.wire.events),'overflow':observer.wire.event_overflow,'observer_closed':observer.closed}
        assert out['idle']['overflow'] and out['idle']['buffer_length']<=4000,out['idle']
        read=record('same_session_read_wait_page_info',call('first','print(js("JSON.stringify({...__idleProbe,title:document.title,ready:document.readyState,elapsedMs:Date.now()-__idleProbe.start})")); assert wait_for_load(); print(page_info())'))
        record('fresh_named_session_navigation_wait_page_info',call('second',f'new_tab({url!r});assert wait_for_load();print(page_info());print(js("document.readyState"));print(wait_for_network_idle(timeout=3,idle_ms=100))'))
        out['same_shared_observer']=provider.states[('overflow-fixture','second')]['observer'] is observer
        assert out['same_shared_observer']
        history=record('old_session_history_gap',call('first','print(drain_events())'))
        out['history_gap_explicit']=not history['success'] and 'event_buffer_overflow' in history.get('error','') and not history.get('action_replayed')
        # Current metadata must still work after an explicit history refusal.
        record('metadata_after_history_refusal',call('first','assert wait_for_load();print(page_info());print(js("__idleProbe.count"))'))
        # Current dialog state is independent of evicted history; answer exactly once.
        record('schedule_dialog',call('first','print(js("setTimeout(()=>alert(\'overflow dialog\'),100);true"))'))
        time.sleep(.3)
        dialog=record('dialog_after_overflow',call('first','print(page_info())'))
        if dialog['success']:
            out['dialog_visible']='overflow dialog' in dialog['stdout']
            record('answer_dialog',call('first','cdp("Page.handleJavaScriptDialog",accept=True);print(page_info())'))
        out['cleanup_success']=provider.close_session('overflow-fixture')
        remaining=wire('Target.getTargets')['targetInfos']
        out['control_preserved']=any(t['targetId']==control for t in remaining)
        out['success']=(all(c['result']['success'] for c in out['cases'] if c['name']!='old_session_history_gap') and out['history_gap_explicit'] and out.get('dialog_visible') and out['cleanup_success'] and out['control_preserved'])
    except Exception:
        out['failure']=traceback.format_exc();out['success']=False
    finally:
        if provider._observer:provider._observer.close()
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
        receipt.write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2),flush=True)
    assert out.get('success') and not residue,out

if __name__=='__main__':main()
