"""Ownership is persisted before child renderer actions; fake transport only."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observer import ScopedObserver


class ObserverCheckpointTests(unittest.TestCase):
    def observer(self,checkpoint):
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_gaps={};wire.detached_sessions=set()
        wire.return_value={'windowId':7,'sessionId':'child-session'}
        with patch('observer.Wire',return_value=wire),patch('observer.NativeDialogs'):
            observer=ScopedObserver('fixture','/fixture/Default')
        state={'context':'ctx','current':'root','owned':{'root':1},'verified':True}
        observer.state=state;observer.entries=[{'state':state,'_checkpoint':checkpoint}]
        self.addCleanup(observer.close)
        return observer,wire,state

    def child(self):
        return {'sessionId':'child-session','waitingForDebugger':True,
                'targetInfo':{'targetId':'child','type':'page','openerId':'root','browserContextId':'ctx'}}

    def test_opener_child_identity_and_window_are_persisted_before_renderer_resume(self):
        events=[]
        observer,wire,state=self.observer(lambda state:events.append(('checkpoint',copy.deepcopy(state['owned']))))
        def respond(method,*args):
            events.append((method,None));return {'windowId':7}
        wire.side_effect=respond
        observer._attached(self.child())
        self.assertEqual(events[:3],[('checkpoint',{'root':1,'child':None}),
                                    ('Browser.getWindowForTarget',None),
                                    ('checkpoint',{'root':1,'child':7})])
        self.assertGreater(next(i for i,event in enumerate(events) if event[0]=='Page.enable'),2)
        self.assertEqual(events[-1][0],'Runtime.runIfWaitingForDebugger')

    def test_failed_provisional_or_window_checkpoint_stops_before_page_actions(self):
        for failed_call in (1,2):
            with self.subTest(failed_call=failed_call):
                calls=[]
                def checkpoint(state):
                    calls.append(copy.deepcopy(state['owned']))
                    if len(calls)==failed_call:raise OSError('fixture disk full')
                observer,wire,state=self.observer(checkpoint)
                if failed_call==2:wire.close.side_effect=OSError('fixture disconnect during shutdown')
                with self.assertRaisesRegex(RuntimeError,'ownership_checkpoint_failed'):
                    observer._attached(self.child())
                self.assertTrue(observer.closed);wire.close.assert_called_once()
                methods=[call.args[0] for call in wire.call_args_list]
                self.assertEqual(methods,[] if failed_call==1 else ['Browser.getWindowForTarget'])

    def test_native_child_checkpoint_precedes_attachment_and_failure_blocks_attach(self):
        for fail in (False,True):
            with self.subTest(fail=fail):
                events=[]
                def checkpoint(state):
                    events.append(('checkpoint',copy.deepcopy(state['owned'])))
                    if fail:raise OSError('fixture disk failure')
                observer,wire,state=self.observer(checkpoint)
                observer.native.scan.return_value={'child':{'window_id':7}}
                wire.side_effect=lambda method,*args:events.append((method,None)) or {'sessionId':'child-session'}
                if fail:
                    with self.assertRaisesRegex(RuntimeError,'ownership_checkpoint_failed'):observer._probe_native()
                    self.assertTrue(observer.closed);wire.assert_not_called()
                else:
                    self.assertTrue(observer._probe_native())
                    self.assertEqual(events,[('checkpoint',{'root':1,'child':7}),('Target.attachToTarget',None)])

    def test_missing_entry_identity_does_not_checkpoint_another_session(self):
        callback=Mock();observer,wire,state=self.observer(callback)
        observer.entries[0]['state']={'context':'other','owned':{'foreign':9}}
        with self.assertRaisesRegex(RuntimeError,'ownership_checkpoint_failed'):observer._attached(self.child())
        self.assertTrue(observer.closed);callback.assert_not_called();wire.assert_not_called()


if __name__=='__main__':unittest.main()
