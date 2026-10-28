import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from worker import Wire

class PendingDialogTests(unittest.TestCase):
    def test_blocked_command_yields_dialog_then_accept_without_replay(self):
        class Socket:
            def __init__(self):self.frames=[];self.sent=[]
            def send(self,text):
                m=json.loads(text);self.sent.append(m)
                if m['method']=='Page.navigate':
                    self.frames.append({'method':'Page.javascriptDialogOpening','sessionId':'held','params':{'type':'beforeunload','message':''}})
                else:
                    self.frames.extend([{'id':1,'result':{'frameId':'f'}},{'id':m['id'],'result':{}}])
            def recv(self,timeout):
                if not self.frames:raise TimeoutError()
                return json.dumps(self.frames.pop(0))
        w=Wire.__new__(Wire);w.ws=Socket();w.counter=0;w.dialog_yield_sessions={'held'}
        try:w('Page.navigate',{'url':'about:blank'},'held')
        except Exception as exc:self.assertIn('dialog_pending',str(exc))
        else:self.fail('blocked command did not yield dialog')
        self.assertEqual(w('Page.handleJavaScriptDialog',{'accept':False},'held'),{})
        self.assertEqual([x['method']for x in w.ws.sent],['Page.navigate','Page.handleJavaScriptDialog'])
        self.assertEqual(w.pending_responses,{})

class NestedResponseTests(unittest.TestCase):
    def test_child_setup_does_not_lose_opener_response(self):
        class Socket:
            def __init__(self):self.frames=[];self.sent=[]
            def send(self,text):
                m=json.loads(text);self.sent.append(m)
                if m['method']=='Runtime.evaluate':
                    self.frames += [{'method':'Target.attachedToTarget','params':{'sessionId':'child','targetInfo':{'targetId':'child'}}},{'id':m['id'],'result':{'done':True}}]
                else:self.frames.append({'id':m['id'],'result':{}})
            def recv(self,timeout):
                if not self.frames:raise TimeoutError()
                return json.dumps(self.frames.pop(0))
        w=Wire.__new__(Wire);w.ws=Socket();w.counter=0
        w.on_attached=lambda params:w('Page.enable',{},params['sessionId'])
        try:result=w('Runtime.evaluate',{},'parent')
        except Exception as exc:self.fail(str(exc))
        self.assertEqual(result,{'done':True})
        self.assertEqual([m['method']for m in w.ws.sent],['Runtime.evaluate','Page.enable'])

class ResumeDialogTests(unittest.TestCase):
    def test_resume_completes_setup_even_if_child_dialog_opens_before_ack(self):
        class Socket:
            def send(self,text):self.frames=[{'method':'Page.javascriptDialogOpening','sessionId':'child','params':{'type':'prompt'}},{'id':json.loads(text)['id'],'result':{}}]
            def recv(self,timeout):return json.dumps(self.frames.pop(0))
        w=Wire.__new__(Wire);w.ws=Socket();w.counter=0;w.dialog_yield_sessions={'child'}
        try:result=w('Runtime.runIfWaitingForDebugger',{},'child')
        except Exception as exc:self.fail(str(exc))
        self.assertEqual(result,{})
        self.assertEqual(w.dialogs['child']['type'],'prompt')

class NestedDialogTests(unittest.TestCase):
    def test_dialog_inside_child_resume_yields_outer_action_without_losing_it(self):
        class Socket:
            def __init__(self):self.frames=[]
            def send(self,text):
                m=json.loads(text)
                if m['method']=='Runtime.evaluate':self.frames.append({'method':'Target.attachedToTarget','params':{'sessionId':'child','targetInfo':{'targetId':'child'}}})
                else:self.frames.extend([{'method':'Page.javascriptDialogOpening','sessionId':'child','params':{'type':'prompt'}},{'id':m['id'],'result':{}}])
            def recv(self,timeout):
                if not self.frames:raise TimeoutError()
                return json.dumps(self.frames.pop(0))
        w=Wire.__new__(Wire);w.ws=Socket();w.counter=0;w.dialog_yield_sessions={'child'}
        w.on_attached=lambda params:w('Runtime.runIfWaitingForDebugger',{},'child')
        try:w('Runtime.evaluate',{},'parent')
        except Exception as exc:self.assertIn('dialog_pending',str(exc))
        else:self.fail('outer command should yield')

class PendingPumpTests(unittest.TestCase):
    def test_idle_pump_retires_late_action_response(self):
        class Socket:
            frames=[json.dumps({'id':1,'result':{}})]
            def recv(self,timeout):
                if not self.frames:raise TimeoutError()
                return self.frames.pop(0)
        w=Wire.__new__(Wire);w.ws=Socket();w.counter=1;w.pending_responses={1:'Page.navigate'}
        w.pump()
        self.assertEqual(w.pending_responses,{})

class DialogReadTests(unittest.TestCase):
    def test_browser_metadata_read_with_queued_dialog_still_succeeds(self):
        class Socket:
            def __init__(self):self.frames=[]
            def send(self,text):self.frames=[{'method':'Page.javascriptDialogOpening','sessionId':'held','params':{'type':'alert'}},{'id':json.loads(text)['id'],'result':{'targetInfos':[]}}]
            def recv(self,timeout):return json.dumps(self.frames.pop(0))
        w=Wire.__new__(Wire);w.ws=Socket();w.counter=0;w.dialog_yield_sessions={'held'}
        try:r=w('Target.getTargets')
        except Exception as exc:self.fail(str(exc))
        self.assertEqual(r,{'targetInfos':[]})

class WorkerTimeoutTests(unittest.TestCase):
    def test_slow_parent_response_does_not_replace_deadline_with_broken_pipe(self):
        import tempfile,time,subprocess
        from unittest.mock import patch
        from plugin import ChromeProvider
        class Observer:
            closed=False
            def request(self,*args):time.sleep(.15);return {'value':{}}
            def close(self):self.closed=True
        with tempfile.TemporaryDirectory(dir=Path.home()/'.hermes/cache/scratch') as root:
            Path(root,'worker.py').write_text('import sys,json\njson.loads(sys.stdin.readline())\nprint(json.dumps({"cdp":{"method":"fixture"}}),flush=True)\nsys.stdin.readline()\n')
            p=ChromeProvider(data=root);entry={'observer':Observer(),'state':{}}
            with patch('plugin.ROOT',Path(root)):
                try:p._worker({'endpoint':'fixture','profile':'fixture'},.05,entry=entry)
                except Exception as exc:self.assertIsInstance(exc,subprocess.TimeoutExpired)
                else:self.fail('worker should time out')

if __name__=='__main__':unittest.main()
