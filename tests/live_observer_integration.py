"""Actual source provider, bounded workers, disposable destination-safe GUI only."""
import sys,json,time,tempfile,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
import psutil
from plugin import ChromeProvider
from worker import Wire


def main():
    work=Path(tempfile.mkdtemp(prefix='chrome-observer-integration-',dir=Path.home()/'.hermes/cache/scratch'))
    data=work/'data';data.mkdir()
    p=ChromeProvider(data=data,workspace=work/'workspace');wire=None
    out={'level':'source provider.execute + actual bounded subprocesses; not installed/native chat','personal_profile_used':False,'cases':[]}
    task='observer-integration'
    def execute(code):
        result=json.loads(p.execute({'code':code,'timeout_s':12},task_id=task))
        assert result['success'],result
        return result
    try:
        execute('print(page_info())')
        entry=p.states[(task,'default')]
        # Independent comparator is fixture setup only, never adopted by adapter.
        wire=Wire(entry['endpoint'])
        context=entry['state']['context'];target=entry['state']['current']
        control=wire('Target.createTarget',{'url':'about:blank','newWindow':True,'browserContextId':context})['targetId']
        control_before=next(t for t in wire('Target.getTargets')['targetInfos'] if t['targetId']==control)
        for kind,accept,expected in [('alert',True,'undefined'),('confirm',False,False),('prompt',True,'integration-answer')]:
            message='integration-'+kind
            call=kind+'('+json.dumps(message)+(',"initial"' if kind=='prompt' else '')+')'
            expression='window.probe={before:0,after:0};setTimeout(()=>{probe.before++;const r='+call+';probe.result=r===undefined?"undefined":r;probe.after++},150);true'
            one=execute('print(js('+repr(expression)+')); import time; time.sleep(.25); print(page_info())')
            assert message in one['stdout'],one # Dialog opens before this bounded worker exits.
            time.sleep(.3)
            # This is the actual next execute helper path, not a harness observer.
            two=execute('print(page_info())')
            assert message in two['stdout'],two
            answer=execute('print(cdp("Page.handleJavaScriptDialog",accept='+repr(accept)+',promptText="integration-answer"))')
            observed=json.loads(execute('print(js("JSON.stringify(window.probe)"))')['stdout'].strip())
            assert observed=={'before':1,'after':1,'result':expected},observed
            assert p.states[(task,'default')]['state']['current']==target
            out['cases'].append({'kind':kind,'dialog_in_actual_page_info':True,'decision':accept,'result':observed})
        wrong=json.loads(p.execute({'code':'switch_tab('+repr(control)+')'},task_id=task))
        assert not wrong['success'] and 'target_not_owned' in wrong['error'],wrong
        out['wrong_target_refused']=True
        execute('new_tab(); print(js("setTimeout(()=>alert(\'new-tab-armed\'),150);true"))')
        time.sleep(.3)
        assert 'new-tab-armed' in execute('print(page_info())')['stdout']
        execute('cdp("Page.handleJavaScriptDialog",accept=True)')
        out['new_tab_armed']=True
        # Dialog closed externally between workers must clear held observation.
        execute('print(js("setTimeout(()=>alert(\'external-close\'),150);true"))')
        time.sleep(.3)
        assert 'external-close' in execute('print(page_info())')['stdout']
        observer=p.states[(task,'default')]['observer']
        sid=observer.sessions[p.states[(task,'default')]['state']['current']]
        observer.wire('Page.handleJavaScriptDialog',{'accept':True},sid)
        assert 'external-close' not in execute('print(page_info())')['stdout']
        out['external_close_clears_observation']=True
        held=p.states[(task,'default')]['observer']
        execute('print(finish_browser(retain=[cdp("Target.getTargets")["targetInfos"][0]["targetId"]]))')
        assert held.closed,'explicit finish must release observer even when retaining a result target'
        assert p.close_session(task),p.last_cleanup
        control_after=next(t for t in wire('Target.getTargets')['targetInfos'] if t['targetId']==control)
        assert control_before==control_after,(control_before,control_after)
        out['manual_comparator_preserved']=True
        execute('print(page_info())')
        entry=p.states[(task,'default')];held=entry['observer'];held.wire.ws.close()
        lost=json.loads(p.execute({'code':'print(page_info())'},task_id=task))
        assert not lost['success'] and 'observer_lost' in lost['error'],lost
        again=json.loads(p.execute({'code':'print(page_info())'},task_id=task))
        assert not again['success'] and 'uncertain' in again['error'],again
        assert p.close_session(task),p.last_cleanup
        assert held.closed
        out['observer_loss_explicit_no_replay']=True
        from plugin import BrowserLifecycle
        class Context:
            def emit(self,*args):pass
        lifecycle=BrowserLifecycle(Context(),p)
        for reason in ('cancel','finalize','unload'):
            execute('print(page_info())')
            held=p.states[(task,'default')]['observer']
            lifecycle.bind(task_id=task,session_id='fixture-session',session_key='fixture-route')
            if reason=='cancel':lifecycle.cancel(session_key='fixture-route')
            elif reason=='finalize':lifecycle.finalize(session_id='fixture-session')
            else:p.unload()
            assert held.closed and (task,'default') not in p.states,p.last_cleanup
            out[reason+'_closes_observer']=True
        out['success']=True
    finally:
        p.close_session(task)
        if not wire and (data/'DevToolsActivePort').exists():
            x=(data/'DevToolsActivePort').read_text().splitlines();wire=Wire('ws://127.0.0.1:'+x[0]+x[1])
        if wire:
            try:wire('Browser.close') # Wholly disposable fixture, never personal Chrome.
            except Exception:pass
            wire.close()
        deadline=time.monotonic()+5
        while True:
            out['process_residue']=[x.pid for x in psutil.process_iter(['cmdline']) if '--user-data-dir='+str(data) in (x.info['cmdline']or[])]
            if not out['process_residue'] or time.monotonic()>=deadline:break
            time.sleep(.1)
        out['caller_manager']=subprocess.run(['/bin/launchctl','managername'],capture_output=True,text=True).stdout.strip()
        (ROOT/'OBSERVER-INTEGRATION-RESULT.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
    assert not out['process_residue']
if __name__=='__main__':main()
