"""One monotonic CDP response budget; exact late-ID retirement, no replay."""
import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class ResponseDeadlineTests(unittest.TestCase):
    def test_events_do_not_renew_response_deadline_and_late_reply_is_not_replayed(self):
        from worker import Wire
        clock=[0.0]
        class Socket:
            def __init__(self):self.sent=[];self.receives=[];self.frames=[]
            def send(self,text):
                message=json.loads(text);self.sent.append(message)
                if message['id']==2:
                    self.frames=[{'id':1,'result':{'value':'late'}},{'id':2,'result':{'value':'peer'}}]
            def recv(self,timeout):
                self.receives.append(timeout)
                if self.frames:return json.dumps(self.frames.pop(0))
                clock[0]+=8
                if clock[0]>32:raise TimeoutError('fixture guard: unbounded event receive')
                return json.dumps({'method':'Network.dataReceived','sessionId':'held','params':{}})
        wire=Wire.__new__(Wire);wire.counter=0;wire.ws=Socket()
        with patch('worker.time.monotonic',side_effect=lambda:clock[0]):
            with self.assertRaises(TimeoutError):wire('Runtime.evaluate',{},'held')
            self.assertLessEqual(clock[0],24,'unsolicited events renewed the 20-second response budget')
            self.assertEqual(wire('Runtime.evaluate',{},'held'),{'value':'peer'})
        self.assertEqual(len(wire.ws.sent),2,'timed-out command was sent again')
        self.assertEqual(wire.pending_responses,{})
        self.assertEqual(wire.responses,{})

if __name__=='__main__':unittest.main()
