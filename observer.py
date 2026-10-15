"""One consent-checked parent transport; no listener, worker or durable state."""
import copy
from contextlib import contextmanager
from websockets.exceptions import ConnectionClosed
from pathlib import Path
if __package__:
    from .binding import BoundBrowser
    from .vault_adapter import Wire
else:
    from binding import BoundBrowser
    from vault_adapter import Wire


class ScopedObserver:
    def __init__(self, endpoint, profile):
        self.wire=Wire(endpoint,str(Path(profile).parent))
        self.sessions={};self.closed=False

    def request(self, request, state):
        if self.closed:raise RuntimeError('observer_lost: release session; no reconnect or action replay')
        try:
            method=request['method'];params=request.get('params') or {};sid=request.get('session')
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
                        self.wire('Page.enable',{},self.sessions[target])
                        self.wire('Network.enable',{},self.sessions[target])
                    result={'sessionId':self.sessions[target]}
                else:result=self.wire(method,params,sid)
            events=getattr(self.wire,'events',[]);self.wire.events=[]
            for event in events:
                if (event['method']=='Target.detachedFromTarget' and event.get('params',{}).get('sessionId') in self.sessions.values()
                    and next((t for t,s in self.sessions.items() if s==event['params']['sessionId']),None) in (state or {}).get('owned',{})
                    and not (method=='Target.closeTarget' and self.sessions.get(params.get('targetId'))==event['params']['sessionId'])):
                    self.close()
                    raise RuntimeError('observer_lost: owned session detached; no callback reconstruction or reconnect')
            return {'value':result,'events':events,'dialogs':copy.deepcopy(getattr(self.wire,'dialogs',{})),
                    'event_overflow':getattr(self.wire,'event_overflow',False)}
        except (TimeoutError, OSError, ConnectionClosed) as exc:
            self.close()
            raise RuntimeError('observer_lost: '+str(exc)+'; no reconnect or action replay') from exc

    @contextmanager
    def borrow(self, state):
        """Vault-only parent use: never attach, reconnect or consume event history."""
        target=state.get('current')
        if (self.closed or target not in self.sessions
            or state.get('owned',{}).get(target) is None or state.get('verified') is False):
            raise RuntimeError('vault_observer_binding_unavailable')
        previous=getattr(self.wire,'on_event',None)
        try:
            self.wire.pump()
            browser=BoundBrowser(self.wire,state)
            browser.sessions={target:self.sessions[target]}
            browser.info()
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
            self.closed=True;self.wire.close()
