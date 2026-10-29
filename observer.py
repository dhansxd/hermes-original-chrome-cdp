"""One consent-checked parent transport with optional parent checkpoint hooks."""
import copy
import threading
from contextlib import contextmanager,nullcontext
from websockets.exceptions import ConnectionClosed
from pathlib import Path
if __package__:
    from .consent import consent_guard
    from .binding import BoundBrowser
    from .transport import Wire
    from .native_dialog import NativeDialogs
    from .cdp_policy import validate_cdp
else:
    from consent import consent_guard
    from binding import BoundBrowser
    from transport import Wire
    from native_dialog import NativeDialogs
    from cdp_policy import validate_cdp


class ScopedObserver:
    def __init__(self, endpoint, profile):
        self.data_root=Path(profile).parent
        self.wire=Wire(endpoint,str(self.data_root))
        self.sessions={};self.closed=False;self.state=None;self.auto_attached=False;self.entries=[];self.watched=set();self.closing_targets=set()
        self.confirmed_absent=set();self.rejected_closes=set()
        self._lock=threading.RLock();self._stop=threading.Event();self._idle=None
        self.wire.on_attached=self._attached
        self.native=NativeDialogs(self.data_root,endpoint);self.native_pending={}
        self.wire.native_dialog_probe=self._probe_native

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
        pending=self.closing_targets | {target for state in states for target in state.get('pending_closes',{})}
        held={sid for target,sid in self.sessions.items() if target not in pending and any(target in s.get('owned',{}) for s in states)}
        if (held & getattr(self.wire,'detached_sessions',set()) or
            any(e['method']=='Target.detachedFromTarget' and e.get('params',{}).get('sessionId') in held
                for e in getattr(self.wire,'events',[]))):
            self.close()
            raise RuntimeError('observer_lost: owned session detached; no callback reconstruction or reconnect')

    def _known_owned(self):
        states=[e.get('state') or {} for e in self.entries]+[self.state or {}]
        return {target for state in states for target in state.get('owned',{})}

    def _retire_closed_sessions(self,live,known_before=None):
        # A close ACK permits no assumptions about destruction. Keep the held
        # mapping until an inventory on the same connection proves disappearance.
        known_before=self._known_owned() if known_before is None else known_before
        absent=known_before-live
        self.confirmed_absent.update(absent)
        self.rejected_closes.difference_update(absent)
        if len(self.confirmed_absent)>4096:
            self.close()
            raise RuntimeError('observer_lost: ownership observation limit reached')
        states=[e.get('state') or {} for e in self.entries]+[self.state or {}]
        pending=self.closing_targets | {target for state in states for target in state.get('pending_closes',{})}
        for target in pending & absent:
            sid=self.sessions.pop(target,None)
            self.closing_targets.discard(target)
            self.watched.discard(target)
            self.native_pending.pop(target,None)
            if sid is not None:
                getattr(self.wire,'dialogs',{}).pop(sid,None)
                getattr(self.wire,'event_gaps',{}).pop(sid,None)
                getattr(self.wire,'detached_sessions',set()).discard(sid)
        self.wire.dialog_yield_sessions=set(self.sessions.values())

    def _checkpoint_ownership(self,state):
        # Caller holds only the observer lock. The parent callback must persist
        # this state without acquiring the provider lock (avoids lock inversion).
        entries=[entry for entry in self.entries if entry.get('state') is state]
        try:
            if not entries and any(callable(entry.get('_checkpoint')) for entry in self.entries):
                raise RuntimeError('ownership_checkpoint_entry_unbound')
            for entry in entries:
                callback=entry.get('_checkpoint')
                if callback is not None:callback(state)
        except Exception:
            try:self.close()
            except Exception:pass
            raise RuntimeError('ownership_checkpoint_failed: no further page action sent') from None

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
        if target in self.confirmed_absent:
            self.close()
            raise RuntimeError('observer_lost: retired target reappeared')
        if target not in owned:
            owned[target]=None
            self._checkpoint_ownership(state)
        window=self.wire('Browser.getWindowForTarget',{'targetId':target})['windowId']
        if owned[target]!=window:
            owned[target]=window
            self._checkpoint_ownership(state)
        old=self.sessions.get(target)
        if old and old!=sid:
            self.wire('Target.detachFromTarget',{'sessionId':old})
            getattr(self.wire,'event_gaps',{}).pop(old,None)
            getattr(self.wire,'detached_sessions',set()).discard(old)
            getattr(self.wire,'dialogs',{}).pop(old,None)
        self.sessions[target]=sid
        if not hasattr(self.wire,'event_gaps'):self.wire.event_gaps={}
        self.wire.event_gaps.setdefault(sid,False)
        if target not in self.native_pending:
            try:
                self.wire('Page.enable',{},sid)
                self.wire('Network.enable',{},sid)
            except RuntimeError as exc:
                # A load-time prompt may appear after setup starts. Preserve the
                # real attachment; only its verified native dialog defers setup.
                if target not in self.native_pending or not str(exc).startswith('dialog_pending:'):raise
        self.wire.dialog_yield_sessions=set(self.sessions.values())
        if params.get('waitingForDebugger'):self.wire('Runtime.runIfWaitingForDebugger',{},sid)

    def _probe_native(self):
        state=self.state
        if not state or not state.get('verified'):return False
        previous=self.wire.native_dialog_probe
        self.wire.native_dialog_probe=None # Browser metadata inside the probe must not recurse.
        try:
            found=self.native.scan(state,self.wire)
            self.native_pending=found
            for target,pending in found.items():
                # Chrome cancels an un-debugged prompt when a peer takes focus.
                # select_dialogs already proved this exact opener-linked window.
                # Attach now, but defer Page.enable until the explicit AX answer.
                if target not in state['owned']:
                    state['owned'][target]=pending['window_id']
                    self._checkpoint_ownership(state)
                if target not in self.sessions:
                    self.sessions[target]=self.wire('Target.attachToTarget',{'targetId':target,'flatten':True})['sessionId']
                    self.wire.event_gaps.setdefault(self.sessions[target],False)
            self.wire.dialog_yield_sessions=set(self.sessions.values())
            return bool(found)
        finally:self.wire.native_dialog_probe=previous

    def request(self, request, state):
        if self.closed:raise RuntimeError('observer_lost: release session; no reconnect or action replay')
        if not isinstance(request,dict):raise RuntimeError('cdp_request_invalid')
        params=request.get('params')
        validate_cdp(request.get('method'),{} if params is None else params,state,self.sessions,request.get('session'),transport=True)
        guard=consent_guard(self.data_root) if request['method']=='Target.closeTarget' else nullcontext()
        with guard,self._lock:return self._request(request,state)

    def _request(self, request, state):
        if self.closed:raise RuntimeError('observer_lost: release session; no reconnect or action replay')
        method=request.get('method');params=request.get('params');sid=request.get('session')
        if params is None:params={}
        target=validate_cdp(method,params,state,self.sessions,sid,transport=True)
        pending=self.closing_targets | set((state or {}).get('pending_closes',{}))
        if target in pending and method not in ('Target.closeTarget','Target.getTargetInfo','Browser.getWindowForTarget'):
            raise RuntimeError('target_close_pending: inspect or finish; no action replay')
        try:
            self.state=state
            self._check_detached()
            # Reject a stale/foreign context before arming watchers or probing UI.
            if target is not None:BoundBrowser(self.wire,state).info(target)
            if (state or {}).get('verified') and method in ('Runtime.evaluate','Page.navigate','Input.dispatchMouseEvent','Input.dispatchKeyEvent'):
                if any(w is not None and w not in self.native.bindings for w in state.get('owned',{}).values()):
                    self._probe_native()
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
                    if target not in pending and target not in self.watched and target not in self.native_pending and state['owned'][target] is not None:
                        # Let cleanup retire vanished IDs without attaching them.
                        if live is None:live={t['targetId'] for t in self.wire('Target.getTargets')['targetInfos']}
                        if target not in live:continue
                        # Browser-wide auto-attach also pauses API/manual pages.
                        # Watch only positively owned roots and their descendants.
                        try:
                            self.wire('Target.autoAttachRelated',{'targetId':target,'waitForDebuggerOnStart':True,'filter':[{'type':'page'},{'exclude':True}]})
                        except RuntimeError as exc:
                            if target not in self.native_pending or not str(exc).startswith('dialog_pending:'):raise
                            continue # The actual watcher acknowledgement is still pending.
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
                        if target not in self.native_pending:
                            self.wire('Page.enable',{},self.sessions[target])
                            self.wire('Network.enable',{},self.sessions[target])
                    result={'sessionId':self.sessions[target]}
                else:
                    self.wire.dialog_yield_sessions=set(self.sessions.values())
                    target=next((t for t,s in self.sessions.items() if s==sid),None)
                    if method=='Page.handleJavaScriptDialog' and target in self.native_pending:
                        result=self.native.answer(target,self.native_pending[target],params,state,self.wire)
                        self.native_pending.pop(target,None)
                    else:
                        if method=='Target.closeTarget':
                            close_target=params['targetId']
                            if close_target in self.closing_targets:
                                raise RuntimeError('target_close_pending: close already sent; do not replay')
                            self.closing_targets.add(close_target)
                            self.rejected_closes.discard(close_target)
                        # The response may deliver a new child attachment before
                        # its inventory. That later child is not proven absent
                        # by an inventory requested before it was known.
                        known_before=self._known_owned() if method=='Target.getTargets' else None
                        result=self.wire(method,params,sid)
                        if method=='Target.closeTarget' and result.get('success') is not True:
                            self.closing_targets.discard(params['targetId'])
                            self.rejected_closes.add(params['targetId'])
                        if method=='Target.getTargets':
                            self._retire_closed_sessions({t['targetId'] for t in result['targetInfos']},known_before)
            self._check_detached()
            owned_sids={s for t,s in self.sessions.items() if t in (state or {}).get('owned',{})}
            # B must not consume A's history; global target events still reach
            # the worker ownership callback. Retention remains bounded at 4000.
            events=[e for e in getattr(self.wire,'events',[]) if e.get('session_id') is None or e.get('session_id') in owned_sids]
            self.wire.events=[e for e in getattr(self.wire,'events',[]) if e.get('session_id') is not None and e.get('session_id') not in owned_sids]
            for event in events:
                if (event['method']=='Target.detachedFromTarget' and event.get('params',{}).get('sessionId') in self.sessions.values()
                    and next((t for t,s in self.sessions.items() if s==event['params']['sessionId']),None) in (state or {}).get('owned',{})
                    and next((t for t,s in self.sessions.items() if s==event['params']['sessionId']),None) not in
                        (self.closing_targets | set((state or {}).get('pending_closes',{})))):
                    self.close()
                    raise RuntimeError('observer_lost: owned session detached; no callback reconstruction or reconnect')
            dialogs=copy.deepcopy(getattr(self.wire,'dialogs',{}))
            for target,pending in self.native_pending.items():
                if self.sessions.get(target) in owned_sids:
                    dialogs[self.sessions[target]]={k:pending['dialog'][k] for k in ('type','message','defaultPrompt')} | {'native':True}
            return {'value':result,'events':events,'dialogs':dialogs,
                    'event_overflow':getattr(self.wire,'event_overflow',False),
                    'event_gaps':{s:getattr(self.wire,'event_gaps',{}).get(s,False) for s in owned_sids}}
        except (TimeoutError, OSError, ConnectionClosed) as exc:
            self.close()
            raise RuntimeError('observer_lost: '+str(exc)+'; no reconnect or action replay') from exc

    def close_disposable_browser(self, state):
        """Parent-only fixture teardown; never available through worker requests."""
        personal=Path.home()/'Library/Application Support/Google/Chrome'
        with self._lock:
            states=[state]+[entry.get('state') or {} for entry in self.entries]
            if (self.data_root.resolve()==personal.resolve()
                or any(not isinstance(s,dict) or s.get('owned') or s.get('unresolved_creation') for s in states)):
                raise RuntimeError('browser_close_not_authorized')
            if self.closed:raise RuntimeError('observer_lost')
            return self.wire('Browser.close',{})

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
            self.native.close()
        if self._idle and self._idle is not threading.current_thread():self._idle.join(1)
