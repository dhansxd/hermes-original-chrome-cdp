import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observer import ScopedObserver


class ObserverTests(unittest.TestCase):
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
