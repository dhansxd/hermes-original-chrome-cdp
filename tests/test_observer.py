import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observer import ScopedObserver


class ObserverTests(unittest.TestCase):
    def test_autoattached_child_is_armed_before_resume_and_other_page_is_released(self):
        from unittest.mock import Mock
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_overflow=False;wire.event_gaps={};wire.detached_sessions=set()
        wire.return_value={'windowId':7}
        state={'current':'parent','context':'ctx','owned':{'parent':1},'baseline':['manual'],'verified':True}
        with patch('observer.Wire',return_value=wire):
            obs=ScopedObserver('fixture','/fixture/Default');obs.state=state
            callback=getattr(obs,'_attached',None)
            self.assertTrue(callable(callback),'missing child pre-script setup')
            callback({'sessionId':'child-s','targetInfo':{'targetId':'child','type':'page','browserContextId':'ctx','openerId':'parent'},'waitingForDebugger':True})
            self.assertEqual(obs.sessions['child'],'child-s')
            self.assertEqual(state['owned']['child'],7)
            calls=[c.args[0] for c in wire.call_args_list]
            self.assertLess(calls.index('Page.enable'),calls.index('Runtime.runIfWaitingForDebugger'))
            wire.reset_mock()
            callback({'sessionId':'manual-s','targetInfo':{'targetId':'manual','type':'page','browserContextId':'ctx'},'waitingForDebugger':False})
            self.assertEqual([c.args[0]for c in wire.call_args_list],['Target.detachFromTarget'])

    def test_finishing_one_entry_preserves_other_entry_transport(self):
        from plugin import ChromeProvider
        from unittest.mock import Mock
        provider=ChromeProvider(data='/fixture')
        observer=Mock();first={'observer':observer};second={'observer':observer}
        observer.entries=[first,second];provider.states={('a','default'):first,('b','default'):second}
        provider._release_observer(first)
        observer.close.assert_not_called()
        self.assertEqual(observer.entries,[second])
        provider.states.pop(('a','default'))
        provider._release_observer(second)
        observer.close.assert_called_once()

    def test_explicit_attach_is_not_treated_as_unknown_autoattach(self):
        import json
        from worker import Wire
        from unittest.mock import Mock
        class Socket:
            def send(self,text):
                m=json.loads(text);self.frames=[{'method':'Target.attachedToTarget','params':{'sessionId':'direct','targetInfo':{'targetId':'exact'}}},{'id':m['id'],'result':{'sessionId':'direct'}}]
            def recv(self,timeout):return json.dumps(self.frames.pop(0))
        w=Wire.__new__(Wire);w.ws=Socket();w.counter=0;w.on_attached=Mock()
        self.assertEqual(w('Target.attachToTarget',{'targetId':'exact'}),{'sessionId':'direct'})
        w.on_attached.assert_not_called()

    def test_detached_held_session_is_loss_not_fabricated_no_dialog(self):
        class Wire:
            events=[];dialogs={};event_overflow=False;closed=False
            def __init__(self,*args):pass
            def __call__(self,method,params=None,session=None):
                if method=='Target.getTargets':return {'targetInfos':[{'targetId':'owned','browserContextId':'ctx','type':'page'}]}
                if method=='Browser.getWindowForTarget':return {'windowId':1}
                if method=='Target.attachToTarget':return {'sessionId':'held'}
                return {}
            def pump(self):self.events=[{'method':'Target.detachedFromTarget','params':{'sessionId':'held'},'session_id':None}]
            def close(self):self.closed=True
        state={'current':'owned','context':'ctx','owned':{'owned':1}}
        with patch('observer.Wire',Wire):
            observer=ScopedObserver('fixture','/fixture/Default')
            observer.request({'method':'Target.attachToTarget','params':{'targetId':'owned','flatten':True}},state)
            with self.assertRaisesRegex(RuntimeError,'observer_lost'):
                observer.request({'method':'__pump__'},state)
            self.assertTrue(observer.closed)
            with self.assertRaisesRegex(RuntimeError,'observer_lost'):
                observer.request({'method':'Target.getTargets'},state)

    def test_delayed_detach_after_confirmed_close_does_not_abort_next_cleanup(self):
        class Wire:
            def __init__(self,*args):self.events=[];self.dialogs={};self.event_overflow=False;self.pending=False
            def __call__(self,method,params=None,session=None):
                if method=='Target.getTargets':
                    if self.pending:
                        self.events.append({'method':'Target.detachedFromTarget','params':{'sessionId':'held'},'session_id':None})
                        self.pending=False
                    return {'targetInfos':[{'targetId':'owned','browserContextId':'ctx','type':'page'}]}
                if method=='Browser.getWindowForTarget':return {'windowId':1}
                if method=='Target.attachToTarget':return {'sessionId':'held'}
                if method=='Target.closeTarget':self.pending=True;return {'success':True}
                return {}
            def close(self):pass
        state={'current':'owned','context':'ctx','owned':{'owned':1}}
        with patch('observer.Wire',Wire):
            observer=ScopedObserver('fixture','/fixture/Default')
            observer.request({'method':'Target.attachToTarget','params':{'targetId':'owned'}},state)
            observer.request({'method':'Target.closeTarget','params':{'targetId':'owned'}},state)
            try:observer.request({'method':'Target.getTargets'},state)
            except RuntimeError as e:self.fail(str(e))
            self.assertFalse(observer.closed)
            self.assertNotIn('owned',observer.sessions)

    def test_failed_close_does_not_retire_held_session(self):
        from unittest.mock import Mock
        state={'current':'owned','context':'ctx','owned':{'owned':1}}
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_overflow=False;wire.event_gaps={};wire.detached_sessions=set()
        wire.return_value={'success':False}
        with patch('observer.Wire',return_value=wire):
            observer=ScopedObserver('fixture','/fixture/Default');observer.sessions={'owned':'held'}
            observer.request({'method':'Target.closeTarget','params':{'targetId':'owned'}},state)
            self.assertEqual(observer.sessions,{'owned':'held'})

    def test_held_wire_is_secret_silent_from_connection_creation(self):
        import logging
        import vault_adapter
        from unittest.mock import Mock
        logger=logging.getLogger('websockets.client')
        before=(logger.level,logger.propagate,list(logger.handlers))
        connect=Mock(return_value=object())
        def consent(endpoint,data,connector):
            return connector(endpoint)
        with patch.object(vault_adapter,'connect',connect), patch.object(vault_adapter,'connect_with_consent',consent):
            observer=ScopedObserver('fixture','/fixture/Default')
        silent=connect.call_args.kwargs['logger']
        self.assertFalse(silent.propagate)
        self.assertFalse(silent.isEnabledFor(logging.DEBUG))
        self.assertEqual((logger.level,logger.propagate,list(logger.handlers)),before)

    def test_missing_window_identity_refuses_observer_attachment(self):
        class Wire:
            def __init__(self,*args):pass
            def close(self):pass
            def __call__(self,method,params=None,session=None):
                if method=='Target.getTargets':return {'targetInfos':[{'targetId':'owned','browserContextId':'ctx','type':'page'}]}
                if method=='Target.attachToTarget':self.fail='attached';return {'sessionId':'sid'}
                return {}
        state={'current':'owned','context':'ctx','owned':{'owned':None}}
        with patch('observer.Wire',Wire):
            observer=ScopedObserver('fixture','/fixture/Default')
            with self.assertRaisesRegex(RuntimeError,'window_binding_unverified'):
                observer.request({'method':'Target.attachToTarget','params':{'targetId':'owned','flatten':True}},state)
            self.assertFalse(hasattr(observer.wire,'fail'))

    def test_existing_owned_attachment_is_not_resumed_when_not_waiting(self):
        from unittest.mock import Mock
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_overflow=False
        wire.event_gaps={};wire.detached_sessions=set()
        def respond(method,params=None,session=None):
            if method=='Runtime.runIfWaitingForDebugger':
                raise TimeoutError('nonwaiting renderer must not receive resume')
            if method=='Browser.getWindowForTarget':return {'windowId':1}
            return {}
        wire.side_effect=respond
        state={'current':'owned','context':'ctx','owned':{'owned':1},'baseline':[],'verified':True}
        with patch('observer.Wire',return_value=wire):
            observer=ScopedObserver('fixture','/fixture/Default');observer.state=state
        try:
            try:
                observer._attached({'sessionId':'held','waitingForDebugger':False,
                    'targetInfo':{'targetId':'owned','type':'page','browserContextId':'ctx'}})
            except TimeoutError as exc:self.fail(str(exc))
            self.assertEqual(observer.sessions,{'owned':'held'})
            self.assertEqual([c.args[0]for c in wire.call_args_list],
                ['Browser.getWindowForTarget','Page.enable','Network.enable'])
        finally:observer.close()

    def test_cleanup_retires_gone_owned_target_before_observer_attachment(self):
        from binding import BoundBrowser
        class Wire:
            def __init__(self,*args):
                self.events=[];self.dialogs={};self.event_overflow=False
                self.event_gaps={};self.detached_sessions=set();self.calls=[]
            def __call__(self,method,params=None,session=None):
                self.calls.append((method,params,session))
                if method=='Target.autoAttachRelated':
                    raise RuntimeError("{'code': -32602, 'message': 'No target with given id found'}")
                if method=='Target.getTargets':
                    return {'targetInfos':[{'targetId':'manual','type':'page','browserContextId':'ctx'}]}
                raise AssertionError('unexpected target action: '+method)
            def close(self):pass
        state={'current':'already-closed','context':'ctx','owned':{'already-closed':17},
               'baseline':['manual'],'verified':True}
        wire=Wire()
        with patch('observer.Wire',return_value=wire):observer=ScopedObserver('fixture','/fixture/Default')
        def transport(method,params=None,session=None):
            return observer.request({'method':method,'params':params,'session':session},state)['value']
        try:
            try:result=BoundBrowser(transport,state).cleanup()
            except RuntimeError as exc:self.fail('gone-target cleanup must succeed: '+str(exc))
            self.assertEqual(result,{'remaining_owned_targets':[],'unresolved_creation':False,'success':True})
            self.assertEqual(state['owned'],{})
            self.assertEqual(observer.watched,set())
            self.assertTrue(wire.calls)
            self.assertTrue(all(method=='Target.getTargets' for method,params,session in wire.calls))
        finally:observer.close()

    def test_live_attachment_errors_are_not_forgotten_after_cleanup_failure(self):
        from binding import BoundBrowser
        for message in ('unexpected attachment rejection','No target with given id found'):
            with self.subTest(message=message):
                class Wire:
                    def __init__(self,*args):
                        self.events=[];self.dialogs={};self.event_overflow=False
                        self.event_gaps={};self.detached_sessions=set();self.calls=[]
                    def __call__(self,method,params=None,session=None):
                        self.calls.append((method,params,session))
                        if method=='Target.getTargets':
                            return {'targetInfos':[{'targetId':'owned','type':'page','browserContextId':'ctx'},
                                                   {'targetId':'foreign','type':'page','browserContextId':'ctx'}]}
                        if method=='Target.autoAttachRelated':
                            assert params is not None
                            if params['targetId']!='owned':raise AssertionError('foreign target driven')
                            raise RuntimeError(message)
                        raise AssertionError('unexpected target action: '+method)
                    def close(self):pass
                state={'current':'owned','context':'ctx','owned':{'owned':17},'baseline':['foreign'],'verified':True}
                wire=Wire()
                with patch('observer.Wire',return_value=wire):observer=ScopedObserver('fixture','/fixture/Default')
                def transport(method,params=None,session=None):
                    return observer.request({'method':method,'params':params,'session':session},state)['value']
                try:
                    with self.assertRaisesRegex(RuntimeError,message):BoundBrowser(transport,state).cleanup()
                    self.assertEqual(state['owned'],{'owned':17})
                    with self.assertRaisesRegex(RuntimeError,message):observer.request({'method':'Target.getTargets'},state)
                    self.assertEqual(state['owned'],{'owned':17})
                    self.assertEqual([params['targetId'] for method,params,session in wire.calls
                                      if method=='Target.autoAttachRelated'],['owned','owned'])
                finally:observer.close()

    def test_observer_attachment_keeps_verified_window_bound_ownership_scope(self):
        class Wire:
            def __init__(self):
                self.events=[];self.dialogs={};self.event_overflow=False
                self.event_gaps={};self.detached_sessions=set();self.calls=[]
            def __call__(self,method,params=None,session=None):
                self.calls.append((method,params,session))
                if method=='Target.getTargets':
                    return {'targetInfos':[{'targetId':'owned','type':'page','browserContextId':'ctx'},
                                           {'targetId':'foreign','type':'page','browserContextId':'ctx'}]}
                if method=='Target.autoAttachRelated':return {}
                raise AssertionError('unexpected target action: '+method)
            def close(self):pass
        for verified,window in ((False,17),(True,None),(True,17)):
            with self.subTest(verified=verified,window=window):
                state={'current':'owned','context':'ctx','owned':{'owned':window},'baseline':['foreign'],'verified':verified}
                wire=Wire()
                with patch('observer.Wire',return_value=wire):observer=ScopedObserver('fixture','/fixture/Default')
                try:
                    observer.request({'method':'Target.getTargets'},state)
                    attached=[params for method,params,session in wire.calls if method=='Target.autoAttachRelated']
                    expected=[{'targetId':'owned','waitForDebuggerOnStart':True,
                               'filter':[{'type':'page'},{'exclude':True}]}] if verified and window is not None else []
                    self.assertEqual(attached,expected)
                    self.assertEqual(observer.watched,{'owned'} if expected else set())
                    self.assertEqual(state['owned'],{'owned':window})
                finally:observer.close()

if __name__=='__main__':unittest.main()
