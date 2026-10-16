"""One bounded execution subprocess; existing harness helpers, private bindings."""
import contextlib, io, json, sys, time, types
from pathlib import Path
from websockets.sync.client import connect
if __package__:
    from .binding import BoundBrowser
    from .consent import connect_with_consent
else:
    from binding import BoundBrowser
    from consent import connect_with_consent

class Wire:
    def __init__(self, endpoint, data_root=None):
        self.ws=connect_with_consent(endpoint,data_root,connect) if data_root else connect(endpoint,open_timeout=15)
        self.counter=0
    def event(self,response):
        if not hasattr(self,'events'):self.events=[];self.dialogs={};self.event_overflow=False
        if not response.get('method'):return
        event={'method':response['method'],'params':response.get('params',{}),'session_id':response.get('sessionId')}
        if len(self.events)>=4000:self.event_overflow=True;self.events.pop(0)
        self.events.append(event)
        sid=event['session_id']
        if event['method']=='Page.javascriptDialogOpening':self.dialogs[sid]=event['params']
        elif event['method']=='Page.javascriptDialogClosed':self.dialogs.pop(sid,None)
        if (event['method']=='Target.attachedToTarget' and callable(getattr(self,'on_attached',None))
            and event['params'].get('targetInfo',{}).get('targetId')!=getattr(self,'explicit_attach_target',None)):
            self.on_attached(event['params'])
        callback=getattr(self,'on_event',None)
        if callback:callback(event)
    def pump(self):
        deadline=time.monotonic()+.05
        while time.monotonic()<deadline:
            try:response=json.loads(self.ws.recv(timeout=0))
            except TimeoutError:return
            self.event(response)
            getattr(self,'pending_responses',{}).pop(response.get('id'),None)
        raise RuntimeError('event_pump_overrun: observation incomplete')
    def __call__(self,method,params=None,session=None):
        previous=getattr(self,'explicit_attach_target',None)
        if method=='Target.attachToTarget':self.explicit_attach_target=(params or {}).get('targetId')
        try:return self._command(method,params,session)
        finally:self.explicit_attach_target=previous

    def _command(self,method,params=None,session=None):
        self.counter+=1
        command_id=self.counter
        if not hasattr(self,'pending_responses'):self.pending_responses={}
        if not hasattr(self,'responses'):self.responses={}
        msg={'id':command_id,'method':method,'params':params or {}}
        if session:msg['sessionId']=session
        known_dialogs=set(getattr(self,'dialogs',{}))
        self.ws.send(json.dumps(msg))
        while True:
            try:response=self.responses.pop(command_id) if command_id in self.responses else json.loads(self.ws.recv(timeout=20))
            except TimeoutError as exc:raise TimeoutError('CDP_response_timeout: '+method) from exc
            self.event(response)
            new_dialogs=set(getattr(self,'dialogs',{}))-known_dialogs
            if (session is not None and new_dialogs & getattr(self,'dialog_yield_sessions',set())
                and method not in ('Page.enable','Network.enable','Page.handleJavaScriptDialog','Runtime.runIfWaitingForDebugger')):
                self.pending_responses[command_id]=method
                raise RuntimeError('dialog_pending: '+method+' sent once; inspect dialog and answer; do not replay action')
            if response.get('id') in self.pending_responses:
                self.pending_responses.pop(response['id'])
            elif response.get('id')==command_id:
                if 'error' in response:raise RuntimeError(str(response['error']))
                return response.get('result',{})
            elif 'id' in response:self.responses[response['id']]=response
    def close(self):self.ws.close()


class PipeWire:
    """Synchronous commands over this bounded worker's existing stdio pipes."""
    observation_scope='held parent session; from owned attachment until release/loss'
    def __init__(self, protocol, source):
        self.protocol=protocol;self.source=source;self.events=[];self.dialogs={};self.event_overflow=False
    def __call__(self, method, params=None, session=None):
        self.protocol.write(json.dumps({'cdp':{'method':method,'params':params,'session':session}})+'\n');self.protocol.flush()
        line=self.source.readline()
        if not line:raise RuntimeError('observer_lost: parent pipe closed')
        response=json.loads(line)
        if 'error' in response:raise RuntimeError(response['error'])
        self.dialogs=response['dialogs'];self.event_overflow=response['event_overflow']
        for event in response['events']:
            if len(self.events)>=4000:self.event_overflow=True;self.events.pop(0)
            self.events.append(event)
            callback=getattr(self,'on_event',None)
            if callback:callback(event)
        return response['value']
    def pump(self):self('__pump__')
    def close(self):pass # Parent owns the actual Chrome connection.


def helper_namespace(browser):
    import browser_harness.helpers as helpers
    # Clone functions into a PRIVATE globals mapping. No module/global monkeypatch.
    ns=dict(vars(helpers))
    for name,fn in vars(helpers).items():
        if isinstance(fn,types.FunctionType) and fn.__module__==helpers.__name__:
            cloned=types.FunctionType(fn.__code__,ns,fn.__name__,fn.__defaults__,fn.__closure__)
            cloned.__kwdefaults__=fn.__kwdefaults__;ns[name]=cloned
    ns.update(cdp=browser.cdp,_send=browser.send)
    ns['ensure_real_tab']=lambda:browser.info()
    ns['new_tab']=browser.create
    def finish(retain=()):
        try:return browser.cleanup(retain)
        finally:
            browser.state['observer_released']=True;browser.checkpoint()
    ns['finish_browser']=finish
    ns['switch_tab']=lambda target,activate=False: switch(browser,target,activate)
    return ns


def switch(browser,target,activate=False):
    target=target.get('targetId',target.get('target_id')) if isinstance(target,dict) else target
    browser.info(target);browser.state['current']=target
    if activate:browser.cdp('Target.activateTarget',targetId=target)
    return browser.session(target)


def initialize(wire,profile,seed_url=None,cleanup=False):
    deadline=time.monotonic()+5
    while True:
        initial=wire('Target.getTargets')['targetInfos']
        seeds=[t for t in initial if seed_url and t.get('type')=='page' and t.get('url')==seed_url]
        if seeds or time.monotonic()>=deadline:break
        time.sleep(.05) # Existing GUI seed may still be navigating after auto-resume.

    if len(seeds)!=1 or not seeds[0].get('browserContextId'):
        raise RuntimeError('Default_seed_unavailable: no context search or other-profile fallback')
    target=seeds[0]['targetId'];context=seeds[0]['browserContextId']
    state={'current':target,'context':context,'owned':{target:None},'verified':False,'baseline':[t['targetId'] for t in initial if t['targetId']!=target]}
    checkpoint=getattr(wire,'checkpoint',lambda state:None)
    checkpoint(state)
    state['owned'][target]=wire('Browser.getWindowForTarget',{'targetId':target})['windowId']
    checkpoint(state)
    if cleanup:return state
    browser=BoundBrowser(wire,state);ns=helper_namespace(browser)
    # Only the explicitly GUI-created seed is inspected, never another profile.
    ns['goto_url']('chrome://version/')
    actual=''
    for _ in range(60):
        actual=ns['js']('document.getElementById("profile_path")?.textContent || ""')
        if actual:break
        time.sleep(.1)
    if not actual or Path(actual).resolve()!=Path(profile).resolve():
        wire('Target.closeTarget',{'targetId':target})
        raise RuntimeError('Default_profile_binding_mismatch: explicit seed was not requested Default')
    ns['goto_url']('about:blank')
    state['verified']=True
    checkpoint(state)
    return state


def run(request, publish=lambda state:None, transport=None):
    wire=None;state=request.get('state');out=io.StringIO()
    def checkpoint(value):
        nonlocal state
        state=value;publish(state)
    try:
        wire=transport or Wire(request['endpoint'],str(Path(request['profile']).parent))
        wire.checkpoint=checkpoint
        if not state or not state.get('context'):
            state=initialize(wire,request['profile'],(state or {}).get('pending_seed') or request.get('seed_url'),cleanup=request.get('cleanup',False))
        browser=BoundBrowser(wire,state,lambda:checkpoint(state))
        if request.get('cleanup'):return {'state':state,**browser.cleanup(request.get('retain',[]))}
        if state.get('verified') is False:raise RuntimeError('profile_binding_unverified: cleanup only')
        checkpoint(state)
        wire('Target.setDiscoverTargets',{'discover':True})
        browser.info()
        if transport:browser.session() # Arm Page before any user code, including delayed JS.
        browser.track_popups()
        ns=helper_namespace(browser)
        ns['__name__']='__browser_exec__'
        workspace=Path(request['workspace']);workspace.mkdir(parents=True,exist_ok=True)
        # Existing helper workspace globals are private to this namespace.
        ns['AGENT_WORKSPACE']=workspace
        local=workspace/'agent_helpers.py'
        with contextlib.redirect_stdout(out):
            if local.exists():exec(compile(local.read_text(),str(local),'exec'),ns)
            exec(compile(request['code'],'<browser_exec>','exec'),ns)
        return {'success':True,'stdout':out.getvalue()[-20000:],'state':state,'backend':'original-chrome-default','workspace':str(workspace)}
    except Exception as exc:
        return {'success':False,'error':str(exc),'error_type':type(exc).__name__,'uncertain':isinstance(exc,TimeoutError) or 'observer_lost' in str(exc) or bool((state or {}).get('unresolved_creation')),'stdout':out.getvalue()[-20000:],'state':state,'backend':'original-chrome-default','action_replayed':False}
    finally:
        if wire:wire.close()

if __name__=='__main__':
    protocol=sys.stdout
    def publish(state):
        protocol.write(json.dumps({'checkpoint':state})+'\n');protocol.flush()
    try:
        request=json.loads(sys.stdin.readline())
        result=run(request,publish,PipeWire(protocol,sys.stdin) if request.get('parent_transport') else None)
    except Exception as exc:result={'success':False,'error':str(exc),'error_type':type(exc).__name__,'action_replayed':False}
    protocol.write(json.dumps({'result':result})+'\n');protocol.flush()
