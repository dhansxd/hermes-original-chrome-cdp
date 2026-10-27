"""Reentrant setup must not depend on a nonwaiting unrelated renderer."""
import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observer import ScopedObserver
from worker import Wire

class ResumeSetupTests(unittest.TestCase):
    def test_nonwaiting_unresponsive_unrelated_page_does_not_poison_setup(self):
        class Socket:
            def __init__(self):self.frames=[];self.sent=[];self.closed=False
            def send(self,text):
                m=json.loads(text);self.sent.append(m)
                if m['method']=='Target.autoAttachRelated':
                    self.frames.append({'method':'Target.attachedToTarget','params':{'sessionId':'unrelated-s','waitingForDebugger':False,'targetInfo':{'targetId':'unrelated','browserContextId':'ctx','type':'page','url':'https://private.invalid/not-recorded'}}})
                # A frozen/nonresponsive renderer does not acknowledge Runtime.
                if m['method']=='Runtime.runIfWaitingForDebugger':return
                result={'targetInfos':[{'targetId':'owned','browserContextId':'ctx','type':'page'}]} if m['method']=='Target.getTargets' else {}
                self.frames.append({'id':m['id'],'result':result})
            def recv(self,timeout):
                if not self.frames:raise TimeoutError()
                return json.dumps(self.frames.pop(0))
            def close(self):self.closed=True
        wire=Wire.__new__(Wire);wire.ws=Socket();wire.counter=0
        state={'verified':True,'context':'ctx','owned':{'owned':1},'baseline':['unrelated']}
        with patch('observer.Wire',return_value=wire):
            obs=ScopedObserver('fixture','/fixture/Default')
            try:
                result=obs.request({'method':'Target.getTargets'},state)
            except RuntimeError as e:self.fail(str(e))
            self.assertEqual(result['value'],{'targetInfos':[{'targetId':'owned','browserContextId':'ctx','type':'page'}]})
            self.assertFalse(obs.closed)
            self.assertEqual([m['method'] for m in wire.ws.sent],['Target.getTargets','Target.autoAttachRelated','Target.detachFromTarget','Target.getTargets'])
            self.assertNotIn('unrelated',obs.sessions)
            obs.close()

    def test_waiting_unrelated_page_is_detached_without_driving_it(self):
        from unittest.mock import Mock
        wire=Mock();wire.events=[]
        with patch('observer.Wire',return_value=wire):
            obs=ScopedObserver('fixture','/fixture/Default')
            obs._attached({'sessionId':'s','waitingForDebugger':True,'targetInfo':{'targetId':'unrelated','type':'page','browserContextId':'other'}})
            self.assertEqual([c.args[0] for c in wire.call_args_list],['Target.detachFromTarget'])
            obs.close()

if __name__=='__main__':unittest.main()
