"""Opt-in source-only repair acceptance, entirely disposable empty GUI Chrome."""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
from plugin import ChromeProvider
from worker import Wire

def main():
    work=Path(tempfile.mkdtemp(prefix='chrome-repair-',dir=Path.home()/'.hermes/cache/scratch'))
    data=work/'data';data.mkdir()
    p=ChromeProvider(data=data,workspace=work/'workspace')
    receipt={'work':str(work),'personal_profile_used':False,'evidence_level':'source adapter, real empty GUI/CDP; not installed/native chat','checks':{}}
    def execute(code,task='fixture',timeout=30):
        result=json.loads(p.execute({'code':code,'timeout_s':timeout},task_id=task))
        return result
    try:
        first=execute('print(page_info())')
        receipt['first']=first
        assert first['success'],first
        receipt['checks']['real_no_dialog_page_info']=True
        entry=p.states[('fixture','default')];control=Wire(entry['endpoint'])
        try:
            mid=control('Target.createTarget',{'url':'about:blank','newWindow':True,'browserContextId':entry['state']['context']})['targetId']
            manual=next(t for t in control('Target.getTargets')['targetInfos'] if t['targetId']==mid)
            manual_window=control('Browser.getWindowForTarget',{'targetId':mid})['windowId']
            # First-call timeout: mutation once, ownership published before user code.
            timed=execute('js("window.repairCounter=(window.repairCounter||0)+1")\nimport time;time.sleep(9)',task='first-timeout',timeout=5)
            assert not timed['success'] and 'uncertain' in timed['error'],timed
            first_state=p.states[('first-timeout','default')]['state']
            sid=control('Target.attachToTarget',{'targetId':first_state['current'],'flatten':True})['sessionId']
            value=control('Runtime.evaluate',{'expression':'window.repairCounter','returnByValue':True},sid)['result']['value']
            assert value==1,value
            again=execute('js("window.repairCounter++")',task='first-timeout')
            assert not again['success'] and 'uncertain' in again['error'],again
            assert p.close_session('first-timeout'),p.last_cleanup
            receipt['checks']['first_call_timeout_mutated_once_cleanup_and_no_replay']=True
            # Later timeout after explicit new_tab and opener popup.
            timed=execute('new_tab()\ncdp("Runtime.evaluate",expression="window.open(\'about:blank\');1",userGesture=True)\nimport time;time.sleep(.2)\nprint(js("1"))\nimport time;time.sleep(9)',timeout=5)
            assert not timed['success'] and 'uncertain' in timed['error'],timed
            owned=set(p.states[('fixture','default')]['state']['owned'])
            live={t['targetId'] for t in control('Target.getTargets')['targetInfos']}
            assert len(owned)>=3,(owned,live)
            assert p.close_session('fixture'),p.last_cleanup
            live={t['targetId'] for t in control('Target.getTargets')['targetInfos']}
            assert not owned & live,(owned,live)
            assert mid in live
            receipt['checks']['later_timeout_new_tab_and_popup_exact_cleanup']=True
            # Parent-owned pending seed after GUI succeeds but preflight fails.
            from unittest.mock import patch
            def fail_preflight(*a,**k):raise RuntimeError('injected preflight failure after seed GUI launch')
            with patch.object(p,'_worker',fail_preflight):
                failed=execute('pass',task='preflight')
            assert not failed['success'],failed
            assert p.states[('preflight','default')]['state']['pending_seed']
            assert p.close_session('preflight'),p.last_cleanup
            receipt['checks']['preflight_failure_pending_seed_cleanup_without_profile_navigation']=True
            m=next(t for t in control('Target.getTargets')['targetInfos'] if t['targetId']==mid)
            assert m['url']==manual['url'] and control('Browser.getWindowForTarget',{'targetId':mid})['windowId']==manual_window
            receipt['checks']['independent_control_url_and_window_preserved']=True
        finally:control.close()
        # Real Network events/session metadata, with a background owned tab isolated.
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path.startswith('/slow'):time.sleep(.6)
                body=b'<title>Network fixture</title>network'
                self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/'
            network=execute(f'new_tab({url!r})\nwait_for_load()\nother=new_tab({url!r})\nwait_for_load()\nswitch_tab(other)\njs("void fetch(\'/slow\')")\nactive=new_tab({url!r})\nwait_for_load()\njs("void fetch(\'/slow\')")\nimport time\nstart=time.monotonic()\nassert wait_for_network_idle(timeout=4,idle_ms=150)\nprint(time.monotonic()-start)\nevents=drain_events()\nprint(page_info())')
            receipt['network']=network
            assert network['success'],network
            assert float(network['stdout'].splitlines()[0])>=.45,network
            receipt['checks']['real_network_idle_delayed_fetch_and_session']=True
        finally:server.shutdown();server.server_close();serving.join()
        for kind in ('alert','confirm'):
            same=execute(f'new_tab()\njs("setTimeout(() => {kind}(\'same-call\'), 50); 1")\nimport time; time.sleep(.15)\nprint(page_info())\ncdp("Page.handleJavaScriptDialog", accept=False)\nprint(page_info())')
            assert same['success'] and 'same-call' in same['stdout'] and "'url':" in same['stdout'],same
            opened=execute(f'js("setTimeout(() => {kind}(\'repair-{kind}\'), 50); 1")\nimport time; time.sleep(.15)\nprint(page_info())')
            assert opened['success'] and f'repair-{kind}' in opened['stdout'],opened
            resumed=execute('print(page_info())')
            receipt[kind+'_across_workers']=resumed
            assert resumed['success'] and f'repair-{kind}' in resumed['stdout'],resumed
            dismissed=execute('cdp("Page.handleJavaScriptDialog", accept=False)')
            receipt[kind+'_raw_dismiss_held_observer']=dismissed
            assert dismissed['success'],dismissed
            receipt['checks'][kind+'_real_events_same_call_and_cross_call_held_observer']=True
    except Exception as exc:
        receipt['error']=str(exc)
        raise
    finally:
        # Exact disposable endpoint even if setup fails before returning state.
        try:
            lines=(data/'DevToolsActivePort').read_text().splitlines()
            wire=Wire(f'ws://127.0.0.1:{int(lines[0])}{lines[1]}')
            try:wire('Browser.close')
            finally:wire.close()
        except Exception as exc:receipt['fixture_close_error']=str(exc)
        deadline=time.monotonic()+8
        while True:
            processes=subprocess.run(['/bin/ps','-axo','pid=,command='],capture_output=True,text=True,timeout=10).stdout.splitlines()
            receipt['process_residue']=[line.strip() for line in processes if str(data) in line]
            if not receipt['process_residue'] or time.monotonic()>deadline:break
            time.sleep(.2)
        (ROOT/'REPAIR-GUI-RESULT.json').write_text(json.dumps(receipt,indent=2))
        print(json.dumps(receipt,indent=2))
        assert not receipt['process_residue'],receipt['process_residue']

if __name__=='__main__':main()
