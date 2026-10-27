"""Plugin-owned helper smoke test on local, account-free disposable GUI Chrome."""
import json, sys, tempfile, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
from plugin import ChromeProvider

class Page(BaseHTTPRequestHandler):
    def log_message(self,format,*args):pass
    def do_GET(self):
        body=b'''<title>Helper fixture</title><input id="text" value="old"><input type="file" id="file"><button onclick="window.clicks=(window.clicks||0)+1">click</button><div style="height:3000px">scroll</div>'''
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)

def main():
    work=Path(tempfile.mkdtemp(prefix='resilience-helpers-',dir=Path.home()/'.hermes/cache/scratch'))
    data=work/'data';data.mkdir()
    p=ChromeProvider(data=data,workspace=work/'workspace')
    server=ThreadingHTTPServer(('127.0.0.1',0),Page)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}/'
    out={'level':'installed plugin source + bounded workers, disposable Chrome; not native chat','checks':{}}
    def ex(code):
        r=json.loads(p.execute({'code':code,'timeout_s':30},task_id='helpers'))
        assert r['success'],r
        return r
    try:
        result=ex('''import json, math
new_tab('''+repr(url)+''')
assert wait_for_load() and wait_for_element('#text',visible=True)
assert page_info()['title']=='Helper fixture'
assert js('const x=7; return x')==7
assert js('12345678901234567890n')==12345678901234567890
assert math.isnan(js('NaN'))
fill_input('#text','Hello ! 42')
assert js('document.querySelector("#text").value')=='Hello ! 42'
press_key('End');type_text('X')
assert js('document.querySelector("#text").value').endswith('X')
js('document.querySelector("#text").addEventListener("keypress",e=>window.domKey=e.key)')
dispatch_key('#text','Enter')
assert js('window.domKey')=='Enter'
rect=js('(()=>{let r=document.querySelector("button").getBoundingClientRect();return {x:r.x+5,y:r.y+5}})()')
click_at_xy(rect['x'],rect['y'])
assert js('window.clicks')==1
scroll(600,400,dy=300);wait(.2)
assert js('scrollY')>0
upload=AGENT_WORKSPACE/'upload.txt';upload.write_text('synthetic upload fixture')
upload_file('#file',str(upload))
assert js('document.querySelector("#file").files[0].name')=='upload.txt'
assert cdp('Accessibility.getFullAXTree')['nodes']
shot=Path(capture_screenshot(full=True,max_dim=600))
assert shot.read_bytes().startswith(b'\\x89PNG\\r\\n\\x1a\\n')
assert wait_for_network_idle(timeout=3,idle_ms=100)
assert isinstance(drain_events(),list)
assert 'Helper fixture' in http_get('''+repr(url)+''')
one=current_tab();assert any(t['targetId']==one['targetId'] for t in list_tabs())
two=new_tab();switch_tab(one);assert current_tab()['targetId']==one['targetId']
activate_tab(one);assert ensure_real_tab()['targetId']==one['targetId']
close_tab(two);assert two not in [t['targetId'] for t in list_tabs()]
assert iframe_target('absent') is None
record=Path(start_recording('fixture-recording'))
assert recording_dir()==str(record)
assert stop_recording()==str(record) and recording_dir() is None
frames=list(record.glob('*.jpg'));assert len(frames)==2
assert all(frame.read_bytes().startswith(b'\\xff\\xd8') for frame in frames)
assert all('frame_error' not in json.loads(line) for line in (record/'events.jsonl').read_text().splitlines())
print(json.dumps({'navigation_js_input_keys_scroll_upload_ax_screenshot_network_http_tabs':True}))
''')
        out['checks'].update(json.loads(result['stdout'].splitlines()[-1]))
        out['checks']['recording_start_stop_bound_frames']=True
        # Existing per-session custom helper import and fresh Python state persist as before.
        workspace=Path(result['workspace'])
        (workspace/'agent_helpers.py').write_text('def fixture_title():\n    return js("document.title")\n')
        assert ex('print(fixture_title())')['stdout'].strip()=='Helper fixture'
        out['checks']['session_workspace_helper_autoimport']=True
        finish=json.loads(ex('import json;print(json.dumps(finish_browser()))')['stdout'])
        assert finish['success'] and finish['browser_closed'],finish
        out['success']=True
    finally:
        p.unload()
        for proc in p._chrome_processes():proc.terminate()
        server.shutdown();server.server_close();thread.join()
        deadline=time.monotonic()+5
        while p._chrome_processes() and time.monotonic()<deadline:time.sleep(.1)
        out['process_residue']=[proc.pid for proc in p._chrome_processes()]
        (ROOT/'RESILIENCE-HELPERS-RESULT.json').write_text(json.dumps(out,indent=2))
        print(json.dumps(out,indent=2))
        assert not out['process_residue']
if __name__=='__main__':main()
