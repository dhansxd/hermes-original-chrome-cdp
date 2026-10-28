"""Idle/failed-observer/new named sessions, disposable real Chrome only."""
import json, sys, tempfile, time, threading, traceback, os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [os.environ.get('TIMEOUT_SOURCE_ROOT',str(ROOT)), str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
import psutil
from plugin import ChromeProvider
from worker import Wire

class Handler(BaseHTTPRequestHandler):
    idle_loaded = threading.Event()
    def log_message(self, format, *args): pass
    def do_GET(self):
        body = b'<title>Idle fixture ready</title><p>ready</p>'
        if self.path=='/idle-control':body += b'<script>fetch("/idle-loaded")</script>'
        if self.path=='/idle-loaded':self.idle_loaded.set()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)


def main():
    label = sys.argv[1] if len(sys.argv)>1 else 'green'
    work = Path(tempfile.mkdtemp(prefix='chrome-idle-', dir=Path.home()/'.hermes/cache/scratch'))
    data = work/'data'; data.mkdir()
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    server_thread = threading.Thread(target=server.serve_forever,daemon=True); server_thread.start()
    url = 'http://127.0.0.1:'+str(server.server_port)
    p = ChromeProvider(data=data, workspace=work/'work'); w = None
    out = {'level':'source provider.execute with bounded workers, not native chat', 'work':str(work), 'cases':[]}
    def ex(name, code):
        result = json.loads(p.execute({'session':name,'code':code,'timeout_s':30},task_id='idle-fixture'))
        assert result['success'], result
        return result
    try:
        ex('first', 'new_tab('+repr(url)+'); wait_for_load(); print(js("document.title"))')
        entry = p.states[('idle-fixture','first')]; held = entry['observer']
        w = Wire(entry['endpoint']); context = entry['state']['context']
        # A separate newly created page must load even before another tool call.
        idle_control=w('Target.createTarget',{'url':url+'/idle-control','newWindow':True,'browserContextId':context})['targetId']
        script_ran=Handler.idle_loaded.wait(1)
        idle_info=next(t for t in w('Target.getTargets')['targetInfos'] if t['targetId']==idle_control)
        out['cases'].append({'name':'new_page_before_next_tool','success':script_ran,'script_ran':script_ran,'url':idle_info['url']})
        ex('first', 'print(js("window.actionCount=1;window.noise=setInterval(()=>fetch(\'/tick\').catch(()=>{}),30);true"))')
        start=time.monotonic()
        time.sleep(45)  # Beyond the production 20s ping interval + 20s timeout.
        try:
            read=ex('first','print(js("clearInterval(window.noise);JSON.stringify({count:actionCount,title:document.title})"))')
            assert json.loads(read['stdout']) == {'count':1,'title':'Idle fixture ready'},read
            out['cases'].append({'name':'45s_idle_network_burst','success':True,'seconds':round(time.monotonic()-start,2)})
        except Exception as exc:
            out['cases'].append({'name':'45s_idle_network_burst','success':False,'error':str(exc)})
        # A GUI/user-like external target must not stay debugger-paused while no tool runs.
        control=w('Target.createTarget',{'url':url+'/control','newWindow':True,'browserContextId':context})['targetId']
        time.sleep(1)
        control_info=next(t for t in w('Target.getTargets')['targetInfos'] if t['targetId']==control)
        out['cases'].append({'name':'unrelated_target_resumes_while_idle','success':control_info['url']==url+'/control','url':control_info['url']})
        # Simulated network loss is explicit; old action must never be replayed.
        held.wire.ws.close()
        lost=json.loads(p.execute({'session':'first','code':'js("window.actionCount++")','timeout_s':10},task_id='idle-fixture'))
        assert not lost['success'],lost
        again=json.loads(p.execute({'session':'first','code':'js("window.actionCount++")','timeout_s':10},task_id='idle-fixture'))
        assert not again['success'] and 'uncertain' in again['error'],again
        for name in ('second','third'):
            try:
                r=ex(name,'new_tab('+repr(url+'/'+name)+');wait_for_load();print(js("document.title"))')
                assert 'Idle fixture ready' in r['stdout'],r
                out['cases'].append({'name':'new_session_after_loss_'+name,'success':True})
            except Exception as exc:
                out['cases'].append({'name':'new_session_after_loss_'+name,'success':False,'error':str(exc)})
        # Independent exact-target read of the original action counter, not adopted.
        sid=w('Target.attachToTarget',{'targetId':entry['state']['current'],'flatten':True})['sessionId']
        count=w('Runtime.evaluate',{'expression':'window.actionCount','returnByValue':True},sid)['result']['value']
        w('Target.detachFromTarget',{'sessionId':sid})
        out['no_replay_counter']=count; assert count==1,count
        out['cleanup_success']=p.close_session('idle-fixture')
        out['control_preserved']=any(t['targetId']==control for t in w('Target.getTargets')['targetInfos'])
        assert out['control_preserved']
        out['success']=all(c['success'] for c in out['cases']) and out['cleanup_success']
    except Exception:
        out['failure']=traceback.format_exc(); out['success']=False
    finally:
        for entry in list(p.states.values()):p._release_observer(entry)
        if w is None and (data/'DevToolsActivePort').exists():
            lines=(data/'DevToolsActivePort').read_text().splitlines();w=Wire('ws://127.0.0.1:'+lines[0]+lines[1])
        if w:
            try:w('Browser.close')
            except Exception:pass
            w.close()
        server.shutdown();server.server_close();server_thread.join()
        deadline=time.monotonic()+5
        while True:
            residue=[x.pid for x in psutil.process_iter(['cmdline']) if '--user-data-dir='+str(data) in (x.info['cmdline'] or [])]
            if not residue or time.monotonic()>deadline:break
            time.sleep(.1)
        out['process_residue']=residue
        (ROOT/('TIMEOUT-IDLE-'+label.upper()+'.json')).write_text(json.dumps(out,indent=2))
        print(json.dumps(out,indent=2),flush=True)
    assert out.get('success') and not residue,out

if __name__=='__main__':main()
