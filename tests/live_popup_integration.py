"""Scoped source popup comparisons, account-free disposable GUI only."""
import sys,json,tempfile,time,threading,os
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
h=Path.home();a=Path(__file__).resolve().parents[1];sys.path[:0]=[str(a),str(h/'.hermes/hermes-agent')]
import hermes_bootstrap
from plugin import ChromeProvider
from observer import ScopedObserver
from unittest.mock import patch
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
out={'level':'SOURCE provider, disposable GUI, NOT installed/native','cases':[],'work':str(root),'success':False}
attachments=[];original_attached=ScopedObserver._attached
def attached(observer,params):
 attachments.append((params.get('targetInfo',{}).get('targetId'),bool(params.get('waitingForDebugger'))))
 return original_attached(observer,params)
attachment_probe=patch.object(ScopedObserver,'_attached',attached);attachment_probe.start()
def ex(code,task):return json.loads(p.execute({'code':code,'timeout_s':12},task_id=task))
def inventory():
 assert w is not None
 return {t['targetId']:t for t in w('Target.getTargets')['targetInfos']}
try:
 setup=ex('new_tab('+repr(base+'/plain')+');wait_for_load()','setup');assert setup['success'],setup
 e=p.states[('setup','default')];w=Wire(e['endpoint']);ctx=e['state']['context']
 comparator=w('Target.createTarget',{'url':base+'/plain','newWindow':True,'browserContextId':ctx})['targetId'];win=w('Browser.getWindowForTarget',{'targetId':comparator})['windowId']
 comparator_before=inventory()[comparator]
 cases=[('plain_blank','window.open("about:blank");true'),('write_plain','let w=window.open("about:blank");w.document.write("<p>plain</p>");true'),('page_plain','window.open('+json.dumps(base+'/plain')+');true'),('page_alert','window.open('+json.dumps(base+'/alert')+');true'),('write_alert','let w=window.open("about:blank");w.document.write('+json.dumps('<script>window.before=1;window.answer=prompt("write-prompt","initial");window.after=1</script>')+');true')]
 case_filter=os.environ.get('POPUP_CASE')
 if case_filter:
  cases=[case for case in cases if case[0]==case_filter]
  assert cases,'unknown POPUP_CASE'
 out['expected_cases']=[name for name,expression in cases]
 for name,expression in cases:
  task='case-'+name;row={'name':name,'success':False,'errors':[]};out['cases'].append(row)
  parents=set();children=[];events=[];e=None;original=None
  try:
   start=ex('new_tab('+repr(base+'/plain')+');wait_for_load()',task);assert start['success'],start
   e=p.states[(task,'default')];parents=set(e['state']['owned']);parent=e['state']['current'];original=e['observer'].wire.event
   def observe(msg,original=original,events=events):
    if msg.get('method')=='Page.javascriptDialogOpening':events.append(msg.get('params',{}))
    return original(msg)
   with e['observer']._lock:e['observer'].wire.event=observe
   expression='window.popupCount=(window.popupCount||0)+1;'+expression
   t=time.monotonic();r=ex('print(cdp("Runtime.evaluate",expression='+repr(expression)+',userGesture=True));import time;time.sleep(.25)',task)
   children=[x for x in inventory().values() if x.get('openerId')in parents]
   row.update(action_success=r['success'],error=r.get('error'),stdout=r.get('stdout'),seconds=round(time.monotonic()-t,2),child_count=len(children),dialog_events=events)
   assert len(children)==1,row
   assert r['success'] or 'dialog_pending' in r.get('error',''),row
   info=ex('switch_tab('+repr(children[0]['targetId'])+');print(page_info())',task)
   row.update(inspect_success=info['success'],inspect_stdout=info.get('stdout'),inspect_error=info.get('error'))
   assert info['success'],row
   if name in ('page_alert','write_alert'):
    assert events and "'dialog':" in info.get('stdout',''),row
    row['answer']=ex('cdp("Page.handleJavaScriptDialog",accept=True,promptText="integration-answer");print(js("JSON.stringify({before:window.before,after:window.after,answer:window.answer,opener:!!window.opener})"))',task)
    assert row['answer']['success'],row
    value=json.loads(row['answer']['stdout'])
    assert value=={'before':1,'after':1,'answer':'integration-answer','opener':True},value
   counter=ex('switch_tab('+repr(parent)+');print(js("window.popupCount"))',task)
   row['parent_counter']=counter.get('stdout','').strip()
   assert counter['success'] and row['parent_counter']=='1',row
  except Exception as exc:
   row['errors'].append(type(exc).__name__+': '+str(exc))
  finally:
   # A failing case must not suppress the next stimulus or its cleanup receipt.
   try:
    row['cleanup']=p.close_session(task)
    if not row['cleanup']:row['errors'].append('provider_cleanup_failed')
   except Exception as exc:row['errors'].append('cleanup: '+type(exc).__name__+': '+str(exc))
   try:
    live=inventory();owned=parents|{x['targetId'] for x in children}
    if e is not None:owned.update((e.get('state') or {}).get('owned',{}))
    row['remaining_case_targets']=sorted(owned&set(live))
    row['comparator_preserved']=comparator in live and all(live[comparator].get(k)==comparator_before.get(k) for k in ('url','browserContextId','attached')) and w('Browser.getWindowForTarget',{'targetId':comparator})['windowId']==win
    if row['remaining_case_targets']:row['errors'].append('independent_inventory_found_case_targets')
    row['foreign_attachments']=[waiting for target,waiting in attachments if target==comparator]
    if not row['comparator_preserved'] or row['foreign_attachments']:row['errors'].append('comparator_changed_or_attached')
   except Exception as exc:row['errors'].append('inventory: '+type(exc).__name__+': '+str(exc))
   if e is not None and original is not None:
    with e['observer']._lock:e['observer'].wire.event=original
   row['success']=not row['errors'];print(json.dumps(row),flush=True)
 out['completed']=len(out['cases'])==len(cases)
 out['comparator_preserved']=all(row.get('comparator_preserved',False) for row in out['cases'])
 out['success']=out['completed'] and all(row['success'] for row in out['cases'])
finally:
 for task in {k[0]for k in p.states}:
  try:p.close_session(task)
  except Exception as exc:out.setdefault('teardown_errors',[]).append(type(exc).__name__)
 attachment_probe.stop()
 if w:
  try:w('Browser.close')
  except Exception:pass
  w.close()
 server.shutdown();server.server_close();thread.join(3)
 deadline=time.monotonic()+5
 while True:
  residue=[x.pid for x in psutil.process_iter(['cmdline'])if '--user-data-dir='+str(data)in(x.info['cmdline']or[])]
  if not residue or time.monotonic()>deadline:break
  time.sleep(.1)
 out['fixture_process_residue']=residue
 if residue or thread.is_alive() or out.get('teardown_errors'):out['success']=False
 (a/'POPUP-INTEGRATION-RESULT.json').write_text(json.dumps(out,indent=2));print(json.dumps({'completed':out.get('completed'),'success':out['success'],'residue':residue,'comparator_preserved':out.get('comparator_preserved')}))
assert out['success'],{'failed_cases':[row['name'] for row in out['cases'] if not row['success']],'fixture_process_residue':out['fixture_process_residue']}
