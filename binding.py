"""Scoped CDP helper boundary. Not an arbitrary-Python sandbox."""
class BoundBrowser:
    def __init__(self, wire, state):
        self.wire, self.state, self.sessions = wire, state, {}

    def info(self, target=None):
        target = target or self.state['current']
        if target not in self.state['owned']:
            raise RuntimeError('target_not_owned')
        infos = self.wire('Target.getTargets')['targetInfos']
        info = next((t for t in infos if t['targetId']==target), None)
        if not info or info.get('browserContextId') != self.state['context']:
            raise RuntimeError('binding_unavailable: owned target disappeared; no personal-tab recovery')
        if self.wire('Browser.getWindowForTarget', {'targetId':target})['windowId'] != self.state['owned'][target]:
            raise RuntimeError('window_binding_changed')
        return info

    def session(self, target=None):
        target = target or self.state['current']
        self.info(target)
        if target not in self.sessions:
            self.sessions[target] = self.wire('Target.attachToTarget', {'targetId':target,'flatten':True})['sessionId']
        return self.sessions[target]

    def create(self, url='about:blank'):
        self.info()
        # Each explicit new tab gets a separate owned window: no last-active-window heuristic.
        target = self.wire('Target.createTarget', {'url':'about:blank','newWindow':True,'background':True,'browserContextId':self.state['context']})['targetId']
        window = self.wire('Browser.getWindowForTarget', {'targetId':target})['windowId']
        self.state['owned'][target] = window
        self.state['current'] = target
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
            if method=='Target.closeTarget': self.state['owned'].pop(target,None)
            return result
        if method in ('Browser.close','Browser.setDownloadBehavior') or method.startswith(('Storage.','Target.','BrowserContext.')):
            raise RuntimeError('browser_wide_operation_not_supported')
        return self.wire(method,params,session_id or self.session())

    def send(self, req, response_timeout=None):
        meta=req.get('meta')
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
                    self.state['owned'][tid]=self.wire('Browser.getWindowForTarget',{'targetId':tid})['windowId']
                    added.append(tid);changed=True
            if not changed:break
        return added

    def cleanup(self, retain=()):
        self.track_popups()
        remaining=[]
        live={t['targetId'] for t in self.wire('Target.getTargets')['targetInfos']}
        for target in list(self.state['owned']):
            if target in retain: remaining.append(target);continue
            if target in live:
                try:
                    self.info(target)
                    if not self.wire('Target.closeTarget',{'targetId':target}).get('success',False):
                        remaining.append(target);continue
                except Exception:
                    remaining.append(target);continue
            self.state['owned'].pop(target,None)
        return {'remaining_owned_targets':remaining,'success':not remaining}
