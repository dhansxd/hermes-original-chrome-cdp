"""One bounded execution subprocess; plugin-owned helpers, private bindings."""
import contextlib, io, json, sys, time
from pathlib import Path
from websockets.sync.client import connect
if __package__:
    from .binding import BoundBrowser
    from .consent import connect_with_consent
    from .execution_policy import validate_source, execute_source
    from .browser_actions import public_helpers
else:
    from binding import BoundBrowser
    from consent import connect_with_consent
    from execution_policy import validate_source, execute_source
    from browser_actions import public_helpers

class Wire:
    def __init__(self, endpoint, data_root=None):
        self.ws=connect_with_consent(endpoint,data_root,connect) if data_root else connect(endpoint,open_timeout=15)
        self.counter=0
    def event(self,response):
        if not hasattr(self,'events'):self.events=[];self.dialogs={};self.event_overflow=False;self.event_gaps={};self.detached_sessions=set()
        if not response.get('method'):return
        event={'method':response['method'],'params':response.get('params',{}),'session_id':response.get('sessionId')}
        if len(self.events)>=4000:
            self.event_overflow=True
            lost=self.events.pop(0).get('session_id')
            if lost in self.event_gaps:self.event_gaps[lost]=True
        self.events.append(event)
        sid=event['session_id']
        if event['method']=='Target.detachedFromTarget':
            detached=event['params'].get('sessionId')
            if detached in self.event_gaps:self.detached_sessions.add(detached)
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
        deadline=time.monotonic()+20
        while True:
            try:
                if command_id in self.responses:response=self.responses.pop(command_id)
                else:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError()
                    probe=getattr(self,'native_dialog_probe',None)
                    try:response=json.loads(self.ws.recv(timeout=min(remaining,.15) if callable(probe) else remaining))
                    except TimeoutError:
                        if callable(probe) and probe():
                            self.pending_responses[command_id]=method
                            raise RuntimeError('dialog_pending: '+method+' sent once; native dialog requires explicit answer; do not replay action')
                        if callable(probe) and time.monotonic()<deadline:continue
                        raise
            except TimeoutError as exc:
                # The action was sent once. Retire any eventual reply by ID,
                # never confuse it with a later command or silently resend it.
                self.pending_responses[command_id]=method
                raise TimeoutError('CDP_response_timeout: '+method) from exc
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
        self.protocol=protocol;self.source=source;self.events=[];self.dialogs={};self.event_overflow=False;self.event_gaps={}
    def __call__(self, method, params=None, session=None):
        self.protocol.write(json.dumps({'cdp':{'method':method,'params':params,'session':session,
            'event_gaps':[sid for sid,gap in self.event_gaps.items() if gap]}})+'\n');self.protocol.flush()
        line=self.source.readline()
        if not line:raise RuntimeError('observer_lost: parent pipe closed')
        response=json.loads(line)
        if 'error' in response:raise RuntimeError(response['error'])
        self.dialogs=response['dialogs'];self.event_overflow=self.event_overflow or response['event_overflow']
        self.event_gaps={sid:gap or self.event_gaps.get(sid,False) for sid,gap in response.get('event_gaps',{}).items()}
        for event in response['events']:
            if len(self.events)>=4000:
                self.event_overflow=True
                lost=self.events.pop(0).get('session_id')
                if lost in self.event_gaps:self.event_gaps[lost]=True
            self.events.append(event)
            callback=getattr(self,'on_event',None)
            if callback:callback(event)
        if any(gap and not response.get('event_gaps',{}).get(sid,False) for sid,gap in self.event_gaps.items()):
            self('__history_gap__') # Publish even if this was the worker's last command.
        return response['value']
    def pump(self):self('__pump__')
    def close(self):pass # Parent owns the actual Chrome connection.


def helper_namespace(browser):
    # A reviewed local snapshot, not executable behavior from host internals.
    # Each call has independent globals (workspace, input state and custom helpers).
    source=Path(__file__).resolve().parent/'vendor/helpers.py'
    ns={'__name__':'__browser_exec__','cdp':browser.cdp,'_send':browser.send,'AGENT_WORKSPACE':None}
    exec(compile(source.read_text(),str(source),'exec'),ns)
    # All expressions are now plugin-owned. The vendor's arbitrary-JS syntax
    # retry can replay a side effect on page-controlled error text; never use it.
    ns['js']=lambda expression:ns['_runtime_evaluate'](expression,await_promise=True)
    ns['ensure_real_tab']=lambda:browser.info()
    ns['new_tab']=browser.create
    def finish(retain=()):
        try:
            result=browser.cleanup(retain)
            if result['success']:
                result.update(browser.wire('__finish_browser__'))
                if result.get('browser_close_error'):result['success']=False
            else:result['browser_closed']=False
            return result
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
    # Page.navigate acknowledges the request before target metadata necessarily
    # leaves chrome://version. Keep setup private until that navigation commits;
    # model helpers must never run against the verification document.
    blank_deadline=time.monotonic()+5
    while browser.info().get('url')!='about:blank':
        if time.monotonic()>=blank_deadline:
            raise RuntimeError('Default_seed_navigation_unconfirmed: no agent page action sent')
        time.sleep(.05)
    state['verified']=True
    checkpoint(state)
    return state


class ProgressOutput(io.StringIO):
    """Publish bounded completed output writes independently of the final result."""
    def __init__(self,progress=None):
        super().__init__();self.progress=progress
    def write(self,text):
        written=len(text)
        tail=(self.getvalue()+text)[-20000:]
        self.seek(0);self.truncate(0);super().write(tail)
        if callable(self.progress):self.progress({'stdout':tail})
        return written


def run(request, publish=lambda state:None, transport=None, progress=None):
    wire=None;state=request.get('state');out=ProgressOutput(progress)
    def checkpoint(value):
        nonlocal state
        state=value;publish(state)
    try:
        if not request.get('cleanup'):
            validate_source(request.get('code', ''))
        wire=transport or Wire(request['endpoint'],str(Path(request['profile']).parent))
        wire.checkpoint=checkpoint
        if not state or not state.get('context'):
            state=initialize(wire,request['profile'],(state or {}).get('pending_seed') or request.get('seed_url'),cleanup=request.get('cleanup',False))
        browser=BoundBrowser(wire,state,lambda:checkpoint(state))
        if request.get('cleanup'):return {'state':state,**browser.cleanup(request.get('retain',[]))}
        if state.get('verified') is not True:raise RuntimeError('profile_binding_unverified: cleanup only')
        checkpoint(state)
        wire('Target.setDiscoverTargets',{'discover':True})
        browser.info()
        if transport:browser.session() # Arm Page before any user code, including delayed JS.
        browser.track_popups()
        ns=helper_namespace(browser)
        ns['__name__']='__browser_exec__'
        workspace=Path(request['workspace']);workspace.mkdir(parents=True,exist_ok=True)
        # Trusted helper implementation is private; scripts receive only named
        # GUI operations through the data-only interpreter, never this namespace.
        ns['AGENT_WORKSPACE']=workspace
        with contextlib.ExitStack() as leases, contextlib.redirect_stdout(out):
            execute_source(request['code'], public_helpers(browser,ns,workspace,
                profile=request['profile'],lease_stack=leases),out)
        return {'success':True,'stdout':out.getvalue()[-20000:],'state':state,'backend':'original-chrome-default','workspace':str(workspace)}
    except Exception as exc:
        return {'success':False,'error':str(exc),'error_type':type(exc).__name__,'retryable':False,'uncertain':isinstance(exc,TimeoutError) or 'observer_lost' in str(exc) or bool((state or {}).get('unresolved_creation')),'stdout':out.getvalue()[-20000:],'state':state,'backend':'original-chrome-default','action_replayed':False}
    finally:
        if wire:wire.close()

if __name__=='__main__':
    protocol=sys.stdout
    def publish(state):
        protocol.write(json.dumps({'checkpoint':state})+'\n');protocol.flush()
    def progress(value):
        protocol.write(json.dumps({'progress':value})+'\n');protocol.flush()
    try:
        request=json.loads(sys.stdin.readline())
        result=run(request,publish,PipeWire(protocol,sys.stdin) if request.get('parent_transport') else None,progress)
    except Exception as exc:result={'success':False,'error':str(exc),'error_type':type(exc).__name__,'action_replayed':False}
    protocol.write(json.dumps({'result':result})+'\n');protocol.flush()
