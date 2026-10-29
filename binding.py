"""Scoped CDP helper boundary. Not an arbitrary-Python sandbox."""
import time


class BoundBrowser:
    def __init__(self, wire, state, checkpoint=None):
        self.wire, self.state, self.sessions = wire, state, {}
        self.checkpoint=checkpoint or (lambda: None)
        if hasattr(wire,'pump'):wire.on_event=self._event

    def _event(self,event):
        if event['method']=='Target.targetCreated':
            info=event.get('params',{}).get('targetInfo',{});tid=info.get('targetId')
            if (tid and tid not in self.state['owned'] and tid not in self.state.get('baseline',[])
                and info.get('type')=='page' and info.get('browserContextId')==self.state.get('context')
                and info.get('openerId') in self.state['owned']):
                self.state['owned'][tid]=None;self.checkpoint()
        target=next((t for t,s in self.sessions.items() if s==event.get('session_id')),None)
        if not target:return
        if event['method']=='Page.javascriptDialogOpening':
            self.state.setdefault('dialogs',{})[target]=event['params']
            self.checkpoint()
        elif event['method']=='Page.javascriptDialogClosed':
            self.state.setdefault('dialogs',{}).pop(target,None)
            self.checkpoint()

    def info(self, target=None):
        target = target or self.state['current']
        if target not in self.state['owned']:
            raise RuntimeError('target_not_owned')
        infos = self.wire('Target.getTargets')['targetInfos']
        info = next((t for t in infos if t['targetId']==target), None)
        if not info or info.get('browserContextId') != self.state['context']:
            raise RuntimeError('binding_unavailable: owned target disappeared; no personal-tab recovery')
        if self.state['owned'][target] is not None and self.wire('Browser.getWindowForTarget', {'targetId':target})['windowId'] != self.state['owned'][target]:
            raise RuntimeError('window_binding_changed')
        return info

    def session(self, target=None):
        target = target or self.state['current']
        self.info(target)
        if target not in self.sessions:
            self.sessions[target] = self.wire('Target.attachToTarget', {'targetId':target,'flatten':True})['sessionId']
            if hasattr(self.wire,'event_gaps'):self.wire.event_gaps.setdefault(self.sessions[target],False)
            if hasattr(self.wire,'pump') and not getattr(self.wire,'observation_scope',None) and not self.state.get('dialogs',{}).get(target):
                self.wire('Page.enable',{},self.sessions[target])
                self.wire('Network.enable',{},self.sessions[target])
        return self.sessions[target]

    def create(self, url='about:blank'):
        self.info()
        # Each explicit new tab gets a separate owned window: no last-active-window heuristic.
        self.state['unresolved_creation']=True;self.checkpoint()
        target = self.wire('Target.createTarget', {'url':'about:blank','newWindow':True,'background':True,'browserContextId':self.state['context']})['targetId']
        self.state['owned'][target] = None
        self.state.pop('unresolved_creation',None)
        self.checkpoint()
        window = self.wire('Browser.getWindowForTarget', {'targetId':target})['windowId']
        self.state['owned'][target] = window
        self.checkpoint()
        self.state['current'] = target
        self.checkpoint()
        if getattr(self.wire,'observation_scope',None):self.session(target)
        if url != 'about:blank': self.cdp('Page.navigate',url=url)
        return target

    def cdp(self, method, session_id=None, _response_timeout=None, **params):
        if session_id is not None and session_id not in self.sessions.values():
            raise RuntimeError('session_not_owned')
        if method == 'Target.getTargets':
            return {'targetInfos':[self.info(t) for t in list(self.state['owned'])]}
        if method == 'Target.createTarget': return {'targetId':self.create(params.get('url','about:blank'))}
        if method in ('Target.closeTarget','Target.activateTarget','Target.attachToTarget','Target.getTargetInfo','Browser.getWindowForTarget'):
            target=params.get('targetId',self.state['current']);self.info(target)
            if method=='Target.attachToTarget': return {'sessionId':self.session(target)}
            result=self.wire(method,{**params,'targetId':target})
            if method=='Target.closeTarget' and result.get('success'):
                self.state['owned'].pop(target,None);self.checkpoint()
            return result
        if method in ('Browser.close','Browser.setDownloadBehavior') or method.startswith(('Storage.','Target.','BrowserContext.')):
            raise RuntimeError('browser_wide_operation_not_supported')
        result=self.wire(method,params,session_id or self.session())
        if method=='Page.handleJavaScriptDialog':
            target=next((t for t,s in self.sessions.items() if s==session_id),self.state['current'])
            self.state.setdefault('dialogs',{}).pop(target,None);self.checkpoint()
            # Arming the deferred child watcher may replace its held attachment.
            self.sessions[target]=self.wire('Target.attachToTarget',{'targetId':target,'flatten':True})['sessionId']
            self.wire('Page.enable',{},self.sessions[target])
            self.wire('Network.enable',{},self.sessions[target])
        return result

    def send(self, req, response_timeout=None):
        meta=req.get('meta')
        if meta in ('session','pending_dialog','drain_events'):
            if not hasattr(self.wire,'pump'):raise RuntimeError('unsupported_helper_meta: event observation unavailable')
            sid=self.session()
            self.wire.pump()
            if meta=='session':return {'session_id':sid,'target_id':self.state['current'],'observation_scope':getattr(self.wire,'observation_scope','current worker attachment only')}
            if meta=='pending_dialog':
                dialog=getattr(self.wire,'dialogs',{}).get(sid)
                if not dialog and self.state.get('dialogs',{}).get(self.state['current']):
                    raise RuntimeError('dialog_observation_uncertain: prior worker observed '+str(self.state['dialogs'][self.state['current']])+'; Chrome does not replay existing dialog events on reattachment; raw dismissal may report no dialog')
                return {'dialog':dialog,'observation_scope':getattr(self.wire,'observation_scope','current attachment plus last observed dialog; no event history between workers')}
            # History gaps persist for the held attachment, not current metadata.
            # Neither a drain nor a new Python worker invents complete history.
            gaps=getattr(self.wire,'event_gaps',None)
            if (gaps.get(sid,False) if gaps is not None else getattr(self.wire,'event_overflow',False)):
                raise RuntimeError('event_buffer_overflow: observation incomplete for this held session; no action replay')
            events=[e for e in getattr(self.wire,'events',[]) if e.get('session_id')==sid]
            self.wire.events=[e for e in getattr(self.wire,'events',[]) if e.get('session_id')!=sid]
            return {'events':events,'observation_scope':getattr(self.wire,'observation_scope','current worker attachment only')}
        if meta=='current_tab': return self.info()
        if meta=='set_session':
            self.info(req['target_id']);self.state['current']=req['target_id'];return {}
        raise RuntimeError('unsupported_helper_meta: '+str(meta))

    def track_popups(self):
        targets=self.wire('Target.getTargets')['targetInfos']
        added=[]
        # Positive opener provenance only, never window/title/URL similarity.
        for _ in range(len(targets)):
            changed=False
            for target in targets:
                tid=target['targetId']
                if (tid not in self.state['owned'] and tid not in self.state.get('baseline',[])
                    and target.get('type')=='page' and target.get('browserContextId')==self.state['context']
                    and target.get('openerId') in self.state['owned']):
                    self.state['owned'][tid]=None
                    self.checkpoint()
                    self.state['owned'][tid]=self.wire('Browser.getWindowForTarget',{'targetId':tid})['windowId']
                    self.checkpoint()
                    added.append(tid);changed=True
            if not changed:break
        for target in targets:
            tid=target['targetId']
            if tid in self.state['owned'] and self.state['owned'][tid] is None:
                self.info(tid) # Validate recorded identity/context before completing its window binding.
                self.state['owned'][tid]=self.wire('Browser.getWindowForTarget',{'targetId':tid})['windowId']
                self.checkpoint()
        return added

    def cleanup(self, retain=()):
        self.track_popups()
        remaining=[];errors={};closing=set()
        live={t['targetId'] for t in self.wire('Target.getTargets')['targetInfos']}
        for target in list(self.state['owned']):
            if target in retain:remaining.append(target);continue
            if target in live:
                try:
                    self.info(target)
                    if not self.wire('Target.closeTarget',{'targetId':target}).get('success',False):
                        remaining.append(target);errors[target]={'code':'close_rejected'};continue
                except Exception as exc:
                    # Exceptions can contain page data/expressions. Preserve a
                    # bounded category, never echo the transport payload.
                    remaining.append(target);errors[target]={'code':'close_failed','error_type':type(exc).__name__};continue
                closing.add(target)
            else:self.state['owned'].pop(target,None)
        # Chrome acknowledges a close before destruction completes. Poll on the
        # same transport for one shared second; never resend the close. Each
        # inventory call still has its existing transport/worker I/O deadline.
        deadline=time.monotonic()+1
        while closing:
            try:live={t['targetId'] for t in self.wire('Target.getTargets')['targetInfos']}
            except Exception as exc:
                for target in closing:
                    remaining.append(target);errors[target]={'code':'close_observation_failed','error_type':type(exc).__name__}
                break
            gone=closing-live
            for target in gone:self.state['owned'].pop(target,None)
            closing-=gone
            if not closing:break
            if time.monotonic()>=deadline:
                for target in closing:
                    remaining.append(target);errors[target]={'code':'close_not_observed'}
                break
            time.sleep(.05)
        self.checkpoint()
        unresolved=self.state.get('unresolved_creation',False)
        result={'remaining_owned_targets':remaining,'unresolved_creation':unresolved,'success':not remaining and not unresolved}
        if errors:result['cleanup_errors']=errors
        return result
