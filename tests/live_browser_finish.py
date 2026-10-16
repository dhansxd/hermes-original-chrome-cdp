"""Source-only normal quit, active-session deferral and same-root reopen proof."""
from pathlib import Path
import sys,json,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
from plugin import ChromeProvider
import psutil
class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):pass
    def do_GET(self):
        body=b'<title>Finish fixture</title><p>quit/reopen</p>'
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)
def main():
    work=Path(tempfile.mkdtemp(prefix='chrome-finish-proof-',dir=Path.home()/'.hermes/cache/scratch'))
    data=work/'data';data.mkdir();provider=ChromeProvider(data=data,workspace=work/'work')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/'
    out={'level':'source disposable GUI; not installed/native; no real credentials','checks':{}}
    def ex(code,session):
        r=json.loads(provider.execute({'code':code,'session':session,'timeout_s':25},task_id='finish'))
        assert r['success'],r
        return r
    try:
        ex('new_tab('+repr(url)+');wait_for_load();js("localStorage.setItem(\'finish-proof\',\'preserved\');document.cookie=\'finishproof=kept; max-age=3600; path=/\'")','a')
        ex('new_tab('+repr(url)+');wait_for_load();js("window.activeMarker=123")','b')
        pids=[p.pid for p in provider._chrome_processes()];assert pids,pids
        first=json.loads(ex('import json;print(json.dumps(finish_browser()))','a')['stdout'])
        assert first['success'] and not first['browser_closed'] and first['browser_close_deferred']=='other_sessions_active',first
        assert ex('print(js("window.activeMarker"))','b')['stdout'].strip()=='123'
        out['checks']['active_session_deferral']=first
        last=json.loads(ex('import json;print(json.dumps(finish_browser()))','b')['stdout'])
        assert last['success'] and last['browser_closed'],last
        assert not provider._chrome_processes()
        out['checks']['last_finish_quits_chrome']=last
        ex('new_tab('+repr(url)+');wait_for_load();print(js("JSON.stringify({storage:localStorage.getItem(\'finish-proof\'),cookie:document.cookie})"))','reopen')
        readback=json.loads(ex('print(js("JSON.stringify({storage:localStorage.getItem(\'finish-proof\'),cookie:document.cookie})"))','reopen')['stdout'])
        assert readback['storage']=='preserved' and 'finishproof=kept' in readback['cookie'],readback
        assert all(p.pid not in pids for p in provider._chrome_processes())
        out['checks']['same_root_reopen_storage_cookie_preserved']=True
        final=json.loads(ex('import json;print(json.dumps(finish_browser()))','reopen')['stdout'])
        assert final['browser_closed'] and final['success'],final
        out['success']=True
    finally:
        provider.unload()
        for proc in provider._chrome_processes():proc.terminate() # Exact disposable root cleanup only.
        server.shutdown();server.server_close();thread.join()
        deadline=time.monotonic()+5
        while True:
            residue=[p.pid for p in psutil.process_iter(['cmdline']) if '--user-data-dir='+str(data) in (p.info['cmdline']or[])]
            if not residue or time.monotonic()>deadline:break
            time.sleep(.1)
        out['process_residue']=residue
        (ROOT/'BROWSER-FINISH-RESULT.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
        assert not residue
if __name__=='__main__':main()
