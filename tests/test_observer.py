import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observer import ScopedObserver


class ObserverTests(unittest.TestCase):
    def test_autoattached_child_is_armed_before_resume_and_other_page_is_released(self):
        from unittest.mock import Mock
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_overflow=False
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
            self.assertEqual([c.args[0]for c in wire.call_args_list],['Runtime.runIfWaitingForDebugger','Target.detachFromTarget'])

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
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_overflow=False
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

if __name__=='__main__':unittest.main()
