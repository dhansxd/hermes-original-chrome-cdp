"""Cold empty-profile launch with a deliberately stale endpoint file."""
import sys,json,tempfile,time,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
import psutil
from plugin import ChromeProvider
from worker import Wire
work=Path(tempfile.mkdtemp(prefix='chrome-endpoint-ready-',dir=Path.home()/'.hermes/cache/scratch'));data=work/'data';data.mkdir()
portfile=data/'DevToolsActivePort';portfile.write_text('12345\n/devtools/browser/stale-fixture\n');os.utime(portfile,(1,1))
p=ChromeProvider(data=data,workspace=work/'workspace');wire=None
result={'personal_profile_used':False,'level':'source adapter real empty GUI, not native chat'}
def run(code):
 r=json.loads(p.execute({'code':code,'timeout_s':20},task_id='readiness-fixture'))
 assert r.get('success'),r
 return r
try:
 first=run('print(page_info())')
 endpoint=p.states[('readiness-fixture','default')]['endpoint'];assert 'stale-fixture' not in endpoint
 result['stale_file_not_returned']=True
 run('js(\'window.once=0;setTimeout(()=>{once++;confirm("readiness-dialog")},100);true\')\nimport time;time.sleep(.2)\nprint(page_info())')
 seen=run('print(page_info())');assert 'readiness-dialog' in seen['stdout']
 handled=run('cdp("Page.handleJavaScriptDialog",accept=False)\nprint(js("window.once"))');assert handled['stdout'].strip()=='1'
 result['dialog_cross_call_once']=True
 end=run('print(finish_browser())');assert "'success': True" in end['stdout']
 result['exact_cleanup']=True
 # Separate cleanup-only transport after observer release, wholly disposable root.
 lines=portfile.read_text().splitlines();wire=Wire('ws://127.0.0.1:'+lines[0]+lines[1]);wire('Browser.close');wire.close();wire=None
 # Retain a known stale port file explicitly before restarting same empty root.
 portfile.write_text('12345\n/devtools/browser/stale-fixture\n');os.utime(portfile,(1,1))
 p2=ChromeProvider(data=data,workspace=work/'workspace2')
 again=json.loads(p2.execute({'code':'print(page_info())\nprint(finish_browser())','timeout_s':20},task_id='second-cold'))
 assert again.get('success'),again
 result['second_cold_stale_file_refused']=True
 result['success']=True
finally:
 if portfile.exists():
  try:
   ls=portfile.read_text().splitlines();wire=Wire('ws://127.0.0.1:'+ls[0]+ls[1]);wire('Browser.close');wire.close()
  except Exception:pass
 deadline=time.monotonic()+6
 while True:
  result['process_residue']=[p.pid for p in psutil.process_iter(['cmdline'])if '--user-data-dir='+str(data)in(p.info['cmdline']or[])]
  if not result['process_residue']or time.monotonic()>=deadline:break
  time.sleep(.1)
 (ROOT/'ENDPOINT-READINESS-GUI-RESULT.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
assert not result['process_residue']
