
import os, sys, json, tempfile, logging, time, threading, concurrent.futures, uuid
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
logging.basicConfig(level=logging.WARNING)
import hermes_bootstrap
if '--require-unmodified-harness' in sys.argv:
 import base64, hashlib, importlib.metadata
 distribution=importlib.metadata.distribution('browser-harness')
 checked=0
 for file in distribution.files:
  if str(file).startswith('browser_harness/') and str(file).endswith('.py'):
   assert file.hash and file.hash.mode=='sha256',file
   actual=base64.urlsafe_b64encode(hashlib.sha256(file.locate().read_bytes()).digest()).rstrip(b'=').decode()
   assert actual==file.hash.value,('Native package modified',str(file))
   checked+=1
 assert checked>0
 print('UNMODIFIED_NATIVE_PACKAGE_PASS',checked,flush=True)
sys._hermes_pin_default_home=False
from hermes_constants import set_hermes_home_override
box=tempfile.TemporaryDirectory(prefix='hermes-native-acceptance-');home=Path(box.name)
(home/'config.yaml').write_text("""browser:
  cloud_provider: original-chrome-default
  auto_local_for_private_urls: false
  allow_private_urls: true
  inactivity_timeout: 600
plugins:
  enabled: [original-chrome-default]
""")
os.environ['HERMES_HOME']=str(home)
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  body="""<!doctype html><title>Hermes isolated fixture</title>
<input id="user"><input id="password" type="password"><button id="go" onclick="document.querySelector('#result').textContent='clicked'">Click</button><p id="result"></p>
<div id="shadow"></div><iframe src="/frame"></iframe><iframe src="http://localhost:CROSS_PORT/frame"></iframe><a id="popup" target="_blank" href="/child">Popup</a>
<script>document.querySelector('#shadow').attachShadow({mode:'open'}).innerHTML='<input id="nested">';</script>"""
  body=body.replace('CROSS_PORT',str(self.server.server_port))
  if self.path=='/frame':body='<input id="framed">'
  if self.path=='/child':body='<title>Owned popup</title>'
  self.send_response(200);self.send_header('Content-Type','text/html')
  self.end_headers();self.wfile.write(body.encode())
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{server.server_port}'
from hermes_cli.plugins import get_plugin_manager,_dispatch_pre_tool_call_hooks
from hermes_cli.plugins_manifest import parse_manifest_file
from tools.registry import registry
import tools.browser_use_cli as native
from tools.browser_session_lifecycle import cleanup_browser,cleanup_profile_browsers
source=Path(__file__).resolve().parents[1];results=[]
with set_hermes_home_override(home):
 manager=get_plugin_manager();manager._load_plugin(parse_manifest_file(source/'plugin.yaml',source,'user',''))
 from agent.browser_registry import get_provider
 provider=get_provider('original-chrome-default')
 def call(task,code,timeout=60):
  with set_hermes_home_override(home):
   args={'code':code,'session':'same','timeout_s':timeout}
   blocked,modified=_dispatch_pre_tool_call_hooks('browser_exec',args,task_id=task,session_id=task+'-chat',tool_call_id=uuid.uuid4().hex)
   assert not blocked,blocked
   result=registry.dispatch('browser_exec',modified or args,scope=str(home),task_id=task)
   result=json.loads(result) if isinstance(result,str) else result
   results.append({'task':task,'result':result});print(json.dumps(results[-1]),flush=True)
   assert result.get('success'),result
   return result
 try:
  with concurrent.futures.ThreadPoolExecutor() as pool:
   futures=[pool.submit(call,agent,f'goto_url({base!r}); print(js("document.title")); print(js("window.agentMarker="+{agent!r}.__repr__()))') for agent in ('A','B','C','D')]
   for f in futures:f.result()
  sessions=list(provider.sessions.values())
  observer=sessions[0].wire
  all_owned=set().union(*({t['targetId'] for t in s._inventory()} for s in sessions))
  manual_before={t['targetId'] for t in observer.call('Target.getTargets')['targetInfos'] if t.get('type')=='page'}-all_owned
  agent_windows=[]
  for session in sessions:
   windows={observer.call('Browser.getWindowForTarget',{'targetId':target['targetId']})['windowId']
            for target in session._inventory() if target.get('type')=='page'}
   assert windows,'Agent has no Chrome window'
   assert all(windows.isdisjoint(peer) for peer in agent_windows),'Agents share a Chrome window'
   agent_windows.append(windows)
  manual_windows={observer.call('Browser.getWindowForTarget',{'targetId':target})['windowId'] for target in manual_before}
  assert all(windows.isdisjoint(manual_windows) for windows in agent_windows),'Agent shares a manual Chrome window'
  print('DISTINCT_AGENT_WINDOWS_PASS',len(agent_windows),flush=True)
  call('A',"""fill_input('#user','fixture-user')
fill_input('#password','FIXTURE_ONLY')
assert js("document.querySelector('#user').value==='fixture-user' && document.querySelector('#password').value==='FIXTURE_ONLY'")
print(js("(()=>{const r=document.querySelector('#go').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()"))
r=js("(()=>{const r=document.querySelector('#go').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
click_at_xy(r['x'],r['y'])
assert js("document.querySelector('#result').textContent") == 'clicked'
assert js("document.querySelector('iframe').contentDocument.querySelector('#framed')!==null")
assert js("document.querySelector('#shadow').shadowRoot.querySelector('#nested')!==null")
frame=iframe_target('localhost:')
assert frame, 'cross-origin iframe target not exposed'
assert js(\"document.querySelector('#framed')!==null\",target_id=frame)
print(capture_screenshot())
js("document.querySelector('#popup').click()")
""")
  call('A',"print([(t['type'], t.get('title')) for t in cdp('Target.getTargets')['targetInfos']])")
  start=time.monotonic()
  with concurrent.futures.ThreadPoolExecutor() as pool:
   slow=pool.submit(call,'A','print(js("new Promise(r=>setTimeout(()=>r(window.agentMarker),3000))"))')
   time.sleep(.3)
   fast=[pool.submit(call,agent,f'assert js("window.agentMarker")=={agent!r}') for agent in ('B','C','D')]
   for f in fast:f.result()
   fast_ms=round((time.monotonic()-start)*1000);slow.result()
  print('PEER_READ_MS',fast_ms,flush=True);assert fast_ms<2500,fast_ms
  from tools.browser_session import get_session_info
  a_args=_dispatch_pre_tool_call_hooks('browser_exec',{'code':'pass','session':'same'},task_id='A',session_id='A-chat')[1]
  a_info=get_session_info(native._backend_cache_key('A',a_args['session']))
  a_session=provider.sessions[a_info['bb_session_id']]
  owned_a={t['targetId'] for t in a_session._inventory()}
  from hermes_cli.plugins import invoke_hook
  with set_hermes_home_override(home):invoke_hook('agent_loop_stopped',task_id='A',session_id='A-chat',completed=True)
  assert a_info['bb_session_id'] not in provider.sessions,'A cleanup not confirmed'
  peer=next(iter(provider.sessions.values()))
  remaining={t['targetId'] for t in peer.wire.call('Target.getTargets')['targetInfos']}
  assert not owned_a & remaining,'A targets remain after cleanup'
  assert manual_before <= remaining,'pre-existing manual targets changed'
  print('EXACT_CLEANUP_AND_MANUAL_PRESERVATION','PASS',flush=True)
  call('B','print(js("window.agentMarker"))')
  for agent in ('C','D'):call(agent,f'assert js("window.agentMarker")=={agent!r}')
  call('A','print(js("document.readyState"))')
  if '--check-native-focus' in sys.argv:
   call('A',"""assert getattr(fill_input, '_original_chrome_focus_guard', False) is True
js("document.body.innerHTML='<input id=previous value=KEEP><input id=disabled disabled><input id=hidden hidden><input id=readonly readonly><input id=visible>'")
for target in ('disabled','hidden','readonly','visible'):
    js("document.querySelector('#previous').value='KEEP';document.querySelector('#previous').focus()")
    rejected=False
    try:fill_input('#'+target,'DUMMY')
    except RuntimeError:rejected=True
    assert js("document.querySelector('#previous').value") == 'KEEP'
    assert rejected == (target!='visible')
    assert js("document.querySelector('#"+target+"').value") == ('DUMMY' if target=='visible' else '')
    print(target, 'PASS')
""")
  call('B',f"goto_url({base!r}); assert js('document.title') == 'Hermes isolated fixture'; print('LOCAL_FIXTURE_PASS')")
  print('NATIVE_ENTRYPOINT',registry.get_entry('browser_exec').handler.__module__,flush=True)
 finally:
  with set_hermes_home_override(home):provider.finish(completed=True,interrupted=True)
  with set_hermes_home_override(home):cleanup_profile_browsers(str(home))
  provider.unload();manager.unload('original-chrome-default')
  server.shutdown()
  print('REMAINING_PROVIDER_SESSIONS',len(provider.sessions),flush=True)
