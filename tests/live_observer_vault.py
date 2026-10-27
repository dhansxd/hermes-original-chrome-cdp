"""Empty GUI fixture: native login fill only, random in-memory synthetic password."""
import json, os, secrets, sys, tempfile, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
import psutil
from plugin import ChromeProvider
from vault_adapter import invoke, Wire
from tools import browser_vault_tool as native

class Form(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<html><title>Synthetic login</title><label>Password<input id="pw" type="password" autocomplete="current-password"></label></html>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, format, *args):pass

def main():
    work = Path(tempfile.mkdtemp(prefix='observer-vault-', dir=Path.home()/'.hermes/cache/scratch')).resolve()
    data = work/'chrome'; data.mkdir()
    home = work/'hermes'; home.mkdir()
    os.environ['HERMES_HOME'] = str(home)
    (home/'config.yaml').write_text('browser:\n  backend: browser-use\n')
    server = ThreadingHTTPServer(('127.0.0.1',0),Form)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin = 'http://127.0.0.1:'+str(server.server_port)
    p = ChromeProvider(data=data, workspace=work/'workspace')
    wire = None; secret = 'synthetic-only-'+secrets.token_hex(32)
    out = {'level':'source provider + bounded workers + native login fill; synthetic backend; not native chat',
           'personal_profile_used':False,'real_credentials_used':False,'checks':{}}
    def execute(code):
        value = json.loads(p.execute({'code':code,'timeout_s':12},task_id='fixture'))
        if not value.get('success'):raise RuntimeError('fixture_browser_execution_failed')
        return value
    try:
        execute('goto_url('+repr(origin+'/login')+'); wait_for_load(); print(page_info())')
        entry = p.states[('fixture','default')]
        observer = entry['observer']; wire = observer.wire
        def held(method, params=None, session=None):
            # Fixture-only raw comparator access shares the production reader lock.
            with observer._lock:return observer.wire(method, params, session)
        agent = entry['state']['current']; sid = observer.sessions[agent]
        # Comparator setup uses this same parent transport, no extra CDP peer.
        manual = held('Target.createTarget',{'url':origin+'/login','newWindow':True,'browserContextId':entry['state']['context']})['targetId']
        ms = held('Target.attachToTarget',{'targetId':manual,'flatten':True})['sessionId']
        before = held('Browser.getWindowForTarget',{'targetId':manual})['windowId']
        for _ in range(40):
            if held('Runtime.evaluate',{'expression':'!!document.getElementById("pw")','returnByValue':True},ms)['result'].get('value'):break
            time.sleep(.1)
        if os.environ.get('OVERFLOW_VAULT')=='1':
            execute('js("window.noise=setInterval(()=>fetch(\'data:text/plain,vault-gap\'),5);setTimeout(()=>clearInterval(noise),8000);true")')
            time.sleep(9)
            with observer._lock:
                assert wire.event_overflow and wire.event_gaps[sid] and len(wire.events)<=4000
            execute('print(page_info())')
            out['checks']['real_network_overflow_before_vault'] = True
        meta = SimpleNamespace(kind='login',origin=origin,allowed_origins=[origin],has_otp=False,label='synthetic',id='synthetic-handle')
        backend = SimpleNamespace(name='synthetic',needs_unlock=False,get_meta=lambda h:meta,resolve_password=lambda h:secret)
        callback = getattr(wire,'on_event',None)
        # Any attempt to reopen a peer or invoke a worker within vault fill fails.
        with patch('vault_adapter.Wire',side_effect=RuntimeError('new_peer_forbidden')), patch.object(p,'_worker',side_effect=RuntimeError('worker_forbidden')), patch('agent.vault_backends.backend_for_handle',return_value=backend), patch.object(native,'_bot_desktop_browser_session',return_value=False), patch.object(native,'_fenced_page_op',side_effect=lambda task,fn:fn()):
            raw = invoke(p,native._handle_vault,{'action':'fill','handle':'synthetic-handle'},{'task_id':'fixture'})
        if secret in raw:raise RuntimeError('response_redaction_failure')
        filled = json.loads(raw)
        if not filled.get('success') or filled.get('filled_fields') != 1:raise RuntimeError('native_fill_failed')
        # Password expression never enters worker pipes, argv, logs or output.
        ok = held('Runtime.evaluate',{'expression':'document.getElementById("pw").value === '+json.dumps(secret),'returnByValue':True},sid)['result'].get('value')
        untouched = held('Runtime.evaluate',{'expression':'document.getElementById("pw").value === ""','returnByValue':True},ms)['result'].get('value')
        if not ok or not untouched:raise RuntimeError('target_binding_failure')
        if observer.closed or observer.sessions[agent] != sid or getattr(wire,'on_event',None) is not callback:raise RuntimeError('borrow_side_effect')
        out['checks'].update(native_login_filled_exact_held_target=True,same_origin_manual_empty=True,no_second_peer_or_worker_during_vault=True,secret_absent_from_result=True,held_session_callback_preserved=True)
        execute('js("setTimeout(()=>alert(\'after-vault\'),100);true")')
        time.sleep(.2)
        if 'after-vault' not in execute('print(page_info())')['stdout']:raise RuntimeError('observer_continuity_failure')
        execute('cdp("Page.handleJavaScriptDialog",accept=True)')
        out['checks']['next_worker_observed_and_dismissed_alert'] = True
        if not p.close_session('fixture'):raise RuntimeError('owned_cleanup_failure')
        # Observation is now released; separate fixture teardown/readback only.
        wire = Wire(entry['endpoint'],str(data))
        if wire('Browser.getWindowForTarget',{'targetId':manual})['windowId'] != before:raise RuntimeError('manual_window_changed')
        out['checks']['owned_cleanup_preserved_manual'] = True
        out['success'] = True
    except Exception:
        # No exception text/tracebacks: command exceptions may contain secret JS.
        out['success'] = False
        out['error'] = 'Synthetic observer/vault fixture failed; no secret-bearing diagnostics emitted.'
    finally:
        # Cleanup uses only this wholly disposable browser root.
        secret = None
        try:p.close_session('fixture')
        except Exception:pass
        try:
            if wire is None and (data/'DevToolsActivePort').exists():
                port,path = (data/'DevToolsActivePort').read_text().splitlines()[:2]
                wire = Wire('ws://127.0.0.1:'+port+path,str(data))
            elif wire is not None and getattr(getattr(wire.ws,'state',None),'name',None) == 'CLOSED':
                port,path = (data/'DevToolsActivePort').read_text().splitlines()[:2]
                wire = Wire('ws://127.0.0.1:'+port+path,str(data))
            if wire:wire('Browser.close')
        except Exception:pass
        if wire:
            try:wire.close()
            except Exception:pass
        server.shutdown();server.server_close()
        deadline = time.monotonic()+5
        while True:
            residue = [x.pid for x in psutil.process_iter(['cmdline']) if '--user-data-dir='+str(data) in (x.info['cmdline'] or [])]
            if not residue or time.monotonic() >= deadline:break
            time.sleep(.1)
        out['process_residue'] = residue
        if residue:out['success'] = False
        print(json.dumps(out,indent=2))
    return 0 if out.get('success') else 1

if __name__ == '__main__':sys.exit(main())
