"""Scoped source popup comparisons, account-free disposable GUI only."""
import sys,json,tempfile,time,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
h=Path.home();a=Path(__file__).resolve().parents[1];sys.path[:0]=[str(a),str(h/'.hermes/hermes-agent')]
import hermes_bootstrap
from plugin import ChromeProvider
from worker import Wire
import psutil
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  body=(b'<title>Popup fixture</title><script>window.before=1;window.answer=prompt("popup-load-prompt","initial");window.after=1</script>' if self.path=='/alert' else b'<title>Popup plain</title><p>plain</p>')
  self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
base='http://127.0.0.1:'+str(server.server_port)
root=Path(tempfile.mkdtemp(prefix='popup-comparison-',dir=h/'.hermes/cache/scratch'));data=root/'data';data.mkdir();p=ChromeProvider(data=data,workspace=root/'work');w=None
out={'level':'SOURCE provider, disposable GUI, NOT installed/native','cases':[],'work':str(root)}
def ex(code,task):return json.loads(p.execute({'code':code,'timeout_s':12},task_id=task))
try:
 setup=ex('new_tab('+repr(base+'/plain')+');wait_for_load()','setup');assert setup['success'],setup
 e=p.states[('setup','default')];w=Wire(e['endpoint']);ctx=e['state']['context']
 comparator=w('Target.createTarget',{'url':base+'/plain','newWindow':True,'browserContextId':ctx})['targetId'];win=w('Browser.getWindowForTarget',{'targetId':comparator})['windowId']
 cases=[('plain_blank','window.open("about:blank");true'),('write_plain','let w=window.open("about:blank");w.document.write("<p>plain</p>");true'),('page_plain','window.open('+json.dumps(base+'/plain')+');true'),('page_alert','window.open('+json.dumps(base+'/alert')+');true'),('write_alert','window.popupCount=(window.popupCount||0)+1;let w=window.open("about:blank");w.document.write('+json.dumps('<script>window.before=1;window.answer=prompt("write-prompt","initial");window.after=1</script>')+');true')]
 for name,expression in cases:
  task='case-'+name;start=ex('new_tab('+repr(base+'/plain')+');wait_for_load()',task);assert start['success'],start
  e=p.states[(task,'default')];parents=set(e['state']['owned']);parent=e['state']['current'];events=[];original=e['observer'].wire.event
  def observe(msg,original=original,events=events):
   if msg.get('method')=='Page.javascriptDialogOpening':events.append(msg.get('params',{}))
   return original(msg)
  e['observer'].wire.event=observe
  t=time.monotonic();r=ex('print(cdp("Runtime.evaluate",expression='+repr(expression)+',userGesture=True));import time;time.sleep(.25)',task)
  targets=w('Target.getTargets')['targetInfos'];children=[x for x in targets if x.get('openerId')in parents]
  row={'name':name,'action_success':r['success'],'error':r.get('error'),'stdout':r.get('stdout'),'seconds':round(time.monotonic()-t,2),'child_count':len(children),'dialog_events':events}
  if (r['success'] or 'dialog_pending' in r.get('error','')) and children:
   info=ex('switch_tab('+repr(children[0]['targetId'])+');print(page_info())',task);row['inspect_success']=info['success'];row['inspect_stdout']=info.get('stdout');row['inspect_error']=info.get('error')
   if info['success'] and "'dialog':" in info.get('stdout',''):
    row['answer']=ex('cdp("Page.handleJavaScriptDialog",accept=True,promptText="integration-answer");print(js("JSON.stringify({before:window.before,after:window.after,answer:window.answer,opener:!!window.opener})"))',task)
  if name in ('page_alert','write_alert'):
   assert row.get('answer',{}).get('success'),row
   value=json.loads(row['answer']['stdout'])
   assert value=={'before':1,'after':1,'answer':'integration-answer','opener':True},value
  else:assert row.get('inspect_success'),row
  if name=='write_alert':
   row['parent_counter']=ex('switch_tab('+repr(parent)+');print(js("window.popupCount"))',task)['stdout'].strip()
   assert row['parent_counter']=='1',row
  row['cleanup']=p.close_session(task);assert row['cleanup'],row
  out['cases'].append(row);print(json.dumps(row),flush=True)
 out['comparator_preserved']=w('Browser.getWindowForTarget',{'targetId':comparator})['windowId']==win
 out['completed']=True
finally:
 for task in {k[0]for k in p.states}:p.close_session(task)
 if w:
  try:w('Browser.close')
  except Exception:pass
  w.close()
 server.shutdown();server.server_close();thread.join()
 deadline=time.monotonic()+5
 while True:
  residue=[x.pid for x in psutil.process_iter(['cmdline'])if '--user-data-dir='+str(data)in(x.info['cmdline']or[])]
  if not residue or time.monotonic()>deadline:break
  time.sleep(.1)
 out['fixture_process_residue']=residue
 (a/'POPUP-INTEGRATION-RESULT.json').write_text(json.dumps(out,indent=2));print(json.dumps({'completed':out.get('completed'),'residue':residue,'comparator_preserved':out.get('comparator_preserved')}))
