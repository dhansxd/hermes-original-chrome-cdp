"""Scoped real personal-profile production-route diagnostic; no browser finish.
Records only protocol method/opaque target IDs/type/URL scheme/waiting flag.
Never inspects personal documents, reconnects, or retries uncertain actions.
"""
import hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import plugin,observer
label=sys.argv[1]
receipt=ROOT/('RESUME-PRODUCTION-'+label+'.json')
if receipt.exists():raise RuntimeError('receipt exists')
trace=[];metadata={};started=time.monotonic()
OriginalWire=observer.Wire
class TracedWire(OriginalWire):
    def event(self,response):
        if response.get('method')=='Target.attachedToTarget':
            p=response['params'];i=p.get('targetInfo',{})
            safe={'target':i.get('targetId'),'type':i.get('type'),'url_kind':i.get('url','').split(':',1)[0], 'waitingForDebugger':p.get('waitingForDebugger')}
            metadata[p['sessionId']]=safe
            trace.append({'event':'attached','t':round(time.monotonic()-started,3),**safe})
        return super().event(response)
    def _command(self,method,params=None,session=None):
        record={'method':method,'t':round(time.monotonic()-started,3)}
        if session:record['attachment']=metadata.get(session,{'explicit':True})
        trace.append(record)
        try:
            value=super()._command(method,params,session)
            if method=='Target.getTargets':
                record['inventory']=[{'target':i['targetId'],'type':i.get('type'),'url_kind':i.get('url','').split(':',1)[0],'attached':i.get('attached')} for i in value['targetInfos']]
            record['ok']=True
            return value
        except Exception as e:
            record['error']=str(e);raise
observer.Wire=TracedWire
provider=plugin.ChromeProvider(workspace=Path.home()/'.hermes/cache/scratch/resume-production'/label)
report={'label':label,'source_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in ('observer.py','worker.py','plugin.py')},'trace':trace}
try:
    report['first']=json.loads(provider.execute({'session':'resume-diagnostic','timeout_s':90,'code':"new_tab('https://example.com');wait_for_load();print(page_info());print(js('({title:document.title,ready:document.readyState})'))"},task_id='resume-diagnostic'))
    report['ownership']=[{'state':e.get('state'),'uncertain':e.get('uncertain',False)} for e in provider.states.values()]
    if report['first'].get('success'):
        report['second']=json.loads(provider.execute({'session':'resume-diagnostic','timeout_s':30,'code':"print(js('({title:document.title,ready:document.readyState})'))"},task_id='resume-diagnostic'))
        # close_session only closes exact known targets; unlike finish_browser it
        # never requests Browser.close. No cleanup of a historical failed session.
        report['cleanup']=provider.close_session('resume-diagnostic')
finally:
    if provider._observer:provider._observer.close()
    receipt.write_text(json.dumps(report,indent=2))
    print(json.dumps({'receipt':str(receipt),'first':report.get('first'),'second':report.get('second'),'cleanup':report.get('cleanup'),'failed_commands':[r for r in trace if 'error' in r]},indent=2))
