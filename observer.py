"""One consent-checked parent transport; no listener, worker or durable state."""
import copy
import threading
from contextlib import contextmanager,nullcontext
from websockets.exceptions import ConnectionClosed
from pathlib import Path
if __package__:
    from .consent import consent_guard
    from .binding import BoundBrowser
    from .vault_adapter import Wire
else:
    from consent import consent_guard
    from binding import BoundBrowser
    from vault_adapter import Wire


class ScopedObserver:
    def __init__(self, endpoint, profile):
        self.data_root=Path(profile).parent
        self.wire=Wire(endpoint,str(self.data_root))
        self.sessions={};self.closed=False;self.state=None;self.auto_attached=False;self.entries=[];self.watched=set()
        self._lock=threading.RLock();self._stop=threading.Event();self._idle=None
        self.wire.on_attached=self._attached

    def bind(self, entry):
        with self._lock:
            if not any(e is entry for e in self.entries):self.entries.append(entry)
            if self._idle is None and not self.closed:
                self._idle=threading.Thread(target=self._drain_idle,name='chrome-observer-idle',daemon=True)
                self._idle.start()

    def _drain_idle(self):
        # websockets' bounded frame queue otherwise blocks its pong reader while
        # tools are idle. Also release auto-attached pages before their next script.
        # The same lock covers requests and vault borrowing: exactly one CDP reader.
        while not self._stop.wait(.02):
            if not self._lock.acquire(timeout=.05):continue
            try:
                if self.closed:return
                self.wire.pump()
                self._check_detached()
            except Exception:
                # Never reconnect/replay on background observation loss. Closing
                # releases this connection's browser-wide auto-attach ownership.
                self.close()
                return
            finally:self._lock.release()

    def _check_detached(self):
        states=[e.get('state') or {} for e in self.entries]+[self.state or {}]
        held={sid for target,sid in self.sessions.items() if any(target in s.get('owned',{}) for s in states)}
        if (held & getattr(self.wire,'detached_sessions',set()) or
            any(e['method']=='Target.detachedFromTarget' and e.get('params',{}).get('sessionId') in held
                for e in getattr(self.wire,'events',[]))):
            self.close()
            raise RuntimeError('observer_lost: owned session detached; no callback reconstruction or reconnect')

    def _attached(self, params):
        info=params['targetInfo'];target=info['targetId'];sid=params['sessionId']
        states=[e.get('state') or {} for e in self.entries]+[self.state or {}]
        state=next((s for s in states if info.get('browserContextId')==s.get('context') and
                    (target in s.get('owned',{}) or (target not in s.get('baseline',[]) and info.get('openerId') in s.get('owned',{})))),{})
        owned=state.get('owned',{})
        belongs=(info.get('browserContextId')==state.get('context') and
                 (target in owned or (target not in state.get('baseline',[]) and info.get('openerId') in owned)))
        if not belongs:
            # Detaching releases this attachment without driving a foreign renderer.
            self.wire('Target.detachFromTarget',{'sessionId':sid})
            return
        owned.setdefault(target,None)
        owned[target]=self.wire('Browser.getWindowForTarget',{'targetId':target})['windowId']
        old=self.sessions.get(target)
        if old and old!=sid:
            self.wire('Target.detachFromTarget',{'sessionId':old})
            getattr(self.wire,'event_gaps',{}).pop(old,None)
            getattr(self.wire,'detached_sessions',set()).discard(old)
            getattr(self.wire,'dialogs',{}).pop(old,None)
        self.sessions[target]=sid
        if not hasattr(self.wire,'event_gaps'):self.wire.event_gaps={}
        self.wire.event_gaps.setdefault(sid,False)
        self.wire('Page.enable',{},sid)
        self.wire('Network.enable',{},sid)
        self.wire.dialog_yield_sessions=set(self.sessions.values())
        if params.get('waitingForDebugger'):self.wire('Runtime.runIfWaitingForDebugger',{},sid)

    def request(self, request, state):
        guard=consent_guard(self.data_root) if request['method']=='Target.closeTarget' else nullcontext()
        with guard,self._lock:return self._request(request,state)

    def _request(self, request, state):
        if self.closed:raise RuntimeError('observer_lost: release session; no reconnect or action replay')
        try:
            self.state=state
            self._check_detached()
            method=request['method'];params=request.get('params') or {};sid=request.get('session')
            # Preserve worker-local gaps across workers, scoped to caller ownership.
            owned_sids={s for t,s in self.sessions.items() if t in (state or {}).get('owned',{})}
            gaps=getattr(self.wire,'event_gaps',{})
            for lost in request.get('event_gaps',[]):
                if lost in owned_sids:gaps[lost]=True
            if method=='__history_gap__':
                # Metadata acknowledgement only: never a browser action or drain.
                return {'value':{},'events':[],'dialogs':copy.deepcopy(getattr(self.wire,'dialogs',{})),
                        'event_overflow':getattr(self.wire,'event_overflow',False),
                        'event_gaps':{s:gaps.get(s,False) for s in owned_sids}}
            if (state or {}).get('verified'):
                live=None
                for target in list(state.get('owned',{})):
                    if target not in self.watched and state['owned'][target] is not None:
                        # Let cleanup retire vanished IDs without attaching them.
                        if live is None:live={t['targetId'] for t in self.wire('Target.getTargets')['targetInfos']}
                        if target not in live:continue
                        # Browser-wide auto-attach also pauses API/manual pages.
                        # Watch only positively owned roots and their descendants.
                        self.wire('Target.autoAttachRelated',{'targetId':target,'waitForDebuggerOnStart':True,'filter':[{'type':'page'},{'exclude':True}]})
                        self.watched.add(target)
                self.auto_attached=bool(self.watched)
            browser=BoundBrowser(self.wire,state or {})
            if method=='__pump__':self.wire.pump();result={}
            else:
                if sid:
                    target=next((t for t,s in self.sessions.items() if s==sid),None)
                    if not target:raise RuntimeError('session_not_owned')
                    browser.info(target)
                if method=='Page.disable':raise RuntimeError('observer_disable_not_supported')
                if method=='Target.attachToTarget':
                    target=params['targetId'];browser.info(target)
                    if state['owned'][target] is None:raise RuntimeError('window_binding_unverified: observer not armed')
                    if target not in self.sessions:
                        self.sessions[target]=self.wire(method,params)['sessionId']
                        if not hasattr(self.wire,'event_gaps'):self.wire.event_gaps={}
                        self.wire.event_gaps.setdefault(self.sessions[target],False)
                        self.wire('Page.enable',{},self.sessions[target])
                        self.wire('Network.enable',{},self.sessions[target])
                    result={'sessionId':self.sessions[target]}
                else:
                    self.wire.dialog_yield_sessions=set(self.sessions.values())
                    result=self.wire(method,params,sid)
                if method=='Target.closeTarget' and result.get('success'):
                    # A confirmed close can emit its detach during a later request.
                    closed_sid=self.sessions.pop(params.get('targetId'),None)
                    getattr(self.wire,'dialogs',{}).pop(closed_sid,None)
                    getattr(self.wire,'event_gaps',{}).pop(closed_sid,None)
                    getattr(self.wire,'detached_sessions',set()).discard(closed_sid)
            self._check_detached()
            owned_sids={s for t,s in self.sessions.items() if t in (state or {}).get('owned',{})}
            # B must not consume A's history; global target events still reach
            # the worker ownership callback. Retention remains bounded at 4000.
            events=[e for e in getattr(self.wire,'events',[]) if e.get('session_id') is None or e.get('session_id') in owned_sids]
            self.wire.events=[e for e in getattr(self.wire,'events',[]) if e.get('session_id') is not None and e.get('session_id') not in owned_sids]
            for event in events:
                if (event['method']=='Target.detachedFromTarget' and event.get('params',{}).get('sessionId') in self.sessions.values()
                    and next((t for t,s in self.sessions.items() if s==event['params']['sessionId']),None) in (state or {}).get('owned',{})
                    and not (method=='Target.closeTarget' and self.sessions.get(params.get('targetId'))==event['params']['sessionId'])):
                    self.close()
                    raise RuntimeError('observer_lost: owned session detached; no callback reconstruction or reconnect')
            return {'value':result,'events':events,'dialogs':copy.deepcopy(getattr(self.wire,'dialogs',{})),
                    'event_overflow':getattr(self.wire,'event_overflow',False),
                    'event_gaps':{s:getattr(self.wire,'event_gaps',{}).get(s,False) for s in owned_sids}}
        except (TimeoutError, OSError, ConnectionClosed) as exc:
            self.close()
            raise RuntimeError('observer_lost: '+str(exc)+'; no reconnect or action replay') from exc

    @contextmanager
    def borrow(self, state):
        with self._lock:
            with self._borrow(state) as browser:yield browser

    @contextmanager
    def _borrow(self, state):
        """Vault-only parent use: never attach, reconnect or consume event history."""
        target=state.get('current')
        if (self.closed or target not in self.sessions
            or state.get('owned',{}).get(target) is None or state.get('verified') is False):
            raise RuntimeError('vault_observer_binding_unavailable')
        previous=getattr(self.wire,'on_event',None)
        try:
            self._check_detached()
            self.wire.pump()
            self._check_detached()
            browser=BoundBrowser(self.wire,state)
            browser.sessions={target:self.sessions[target]}
            browser.info()
            self._check_detached()
            if any(e['method']=='Target.detachedFromTarget'
                   and e.get('params',{}).get('sessionId') in self.sessions.values()
                   for e in getattr(self.wire,'events',[])):
                self.close()
                raise RuntimeError('observer_lost')
            yield browser
        except (TimeoutError, OSError, ConnectionClosed):
            self.close()
            raise RuntimeError('observer_lost') from None
        finally:
            self.wire.on_event=previous

    def close(self):
        if not self.closed:
            self.closed=True;self._stop.set();self.wire.close()
        if self._idle and self._idle is not threading.current_thread():self._idle.join(1)
