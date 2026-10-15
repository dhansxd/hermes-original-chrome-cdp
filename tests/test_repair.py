import copy, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plugin import ChromeProvider
from binding import BoundBrowser

class OwnershipTests(unittest.TestCase):
    def test_pending_cleanup_closes_exact_seed_without_profile_probe(self):
        import worker
        calls=[]
        class Wire:
            def __init__(self,*args):pass
            def close(self):pass
            def __call__(self,method,params=None,session=None):
                calls.append((method,params))
                if method=='Target.getTargets':return {'targetInfos':[{'targetId':'seed','type':'page','browserContextId':'ctx','url':'file:///exact-seed'}]}
                if method=='Browser.getWindowForTarget':return {'windowId':1}
                if method=='Target.closeTarget':return {'success':True}
                raise AssertionError('cleanup must not navigate/attach: '+method)
        with patch('worker.Wire',Wire):
            result=worker.run({'endpoint':'ws://fixture','profile':'/fixture/Default','state':{'pending_seed':'file:///exact-seed','owned':{}},'cleanup':True})
        self.assertTrue(result['success'],result)
        self.assertIn(('Target.closeTarget',{'targetId':'seed'}),calls)

    def test_seed_attempt_is_parent_owned_before_gui_preflight_fails(self):
        with tempfile.TemporaryDirectory() as root:
            p=ChromeProvider(data=Path(root)/'data',workspace=Path(root)/'work')
            seen=[]
            def launch(*args):
                seen.append(copy.deepcopy(p.states))
                raise RuntimeError('injected GUI failure')
            with patch('plugin.gui_launch',launch):
                first=json.loads(p.execute({'code':'pass'},task_id='fixture'))
                second=json.loads(p.execute({'code':'pass'},task_id='fixture'))
            self.assertFalse(first['success'])
            self.assertEqual(len(seen),1)
            self.assertTrue(seen[0][('fixture','default')]['state']['pending_seed'].startswith('file:'))
            self.assertFalse(p.close_session('fixture'))
            self.assertIn('uncertain',second['error'])

class ProgressTests(unittest.TestCase):
    def test_wire_timeout_result_quarantines_session_without_replay(self):
        p=ChromeProvider(data='/synthetic-empty-root');p.endpoint=lambda:'ws://fixture'
        calls=[]
        def worker(*args):
            calls.append(True)
            return {'success':False,'uncertain':True,'state':{'owned':{'old':1},'verified':True},'error':'CDP_response_timeout'}
        p._worker=worker
        p.execute({'code':'pass'},task_id='fixture')
        again=json.loads(p.execute({'code':'pass'},task_id='fixture'))
        self.assertEqual(len(calls),1)
        self.assertIn('uncertain',again['error'])

    def test_unknown_create_response_remains_unresolved_after_known_cleanup(self):
        state={'current':'old','context':'ctx','owned':{'old':1}}
        live=[{'targetId':'old','browserContextId':'ctx'}]
        def wire(method,params=None,session=None):
            if method=='Target.getTargets':return {'targetInfos':live}
            if method=='Browser.getWindowForTarget':return {'windowId':1}
            if method=='Target.createTarget':raise TimeoutError('response unknown')
            if method=='Target.closeTarget':live.clear();return {'success':True}
            raise AssertionError(method)
        browser=BoundBrowser(wire,state)
        with self.assertRaises(TimeoutError):browser.create()
        result=browser.cleanup()
        self.assertFalse(result['success'],result)
        self.assertTrue(result['unresolved_creation'])

    def test_initialize_publishes_exact_seed_before_profile_probe(self):
        from worker import initialize
        seen=[]
        def wire(method,params=None,session=None):
            if method=='Target.getTargets':return {'targetInfos':[{'targetId':'seed','type':'page','browserContextId':'ctx','url':'file:///exact-seed'}]}
            if method=='Browser.getWindowForTarget':raise RuntimeError('window lookup failed')
            raise AssertionError(method)
        wire.checkpoint=lambda state:seen.append(copy.deepcopy(state))
        with self.assertRaisesRegex(RuntimeError,'window lookup failed'):
            initialize(wire,'/fixture/Default','file:///exact-seed')
        self.assertTrue(seen,'no ownership published before window lookup')
        self.assertEqual(seen[0]['owned'],{'seed':None})
        self.assertFalse(seen[0]['verified'])

    def test_successful_worker_does_not_leave_descendant_pipe_open(self):
        import time
        with tempfile.TemporaryDirectory() as root:
            script=Path(root)/'worker.py'
            script.write_text('import json,subprocess,sys\njson.load(sys.stdin)\nsubprocess.Popen([sys.executable,"-c","import time;time.sleep(1.5)"])\nprint(json.dumps({"result":{"success":True,"stdout":"actual-output"}}),flush=True)\n')
            p=ChromeProvider(data=root);p._active_entry={'state':None}
            start=time.monotonic()
            with patch('plugin.ROOT',Path(root)):
                result=p._worker({},1)
            self.assertEqual(result['stdout'],'actual-output')
            self.assertLess(time.monotonic()-start,.8)

    def test_worker_deadline_does_not_wait_for_descendant_stdout(self):
        import subprocess,time
        with tempfile.TemporaryDirectory() as root:
            script=Path(root)/'worker.py'
            script.write_text('import subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c","import time;time.sleep(1.5)"])\ntime.sleep(5)\n')
            p=ChromeProvider(data=root);p._active_entry={'state':None}
            start=time.monotonic()
            with patch('plugin.ROOT',Path(root)):
                with self.assertRaises(subprocess.TimeoutExpired):p._worker({},.1)
            self.assertLess(time.monotonic()-start,.8)

    def test_parent_retains_checkpoint_on_timeout_and_reaps_worker(self):
        import subprocess
        with tempfile.TemporaryDirectory() as root:
            script=Path(root)/'worker.py'
            script.write_text('import json,sys,time,os\njson.load(sys.stdin)\nprint(json.dumps({"checkpoint":{"current":"new","context":"ctx","owned":{"old":1,"new":None}},"pid":os.getpid()}),flush=True)\ntime.sleep(10)\n')
            p=ChromeProvider(data=root);entry={'endpoint':'ws://fixture','state':{'owned':{'old':1}}}
            p._active_entry=entry
            with patch('plugin.ROOT',Path(root)):
                with self.assertRaises(subprocess.TimeoutExpired):p._worker({},.15)
            self.assertEqual(entry['state']['owned'],{'old':1,'new':None})

    def test_created_target_is_published_before_window_lookup_failure(self):
        snapshots=[]
        def wire(method,params=None,session=None):
            if method=='Target.getTargets':return {'targetInfos':[{'targetId':'old','browserContextId':'ctx'}]}
            if method=='Target.createTarget':return {'targetId':'new'}
            if method=='Browser.getWindowForTarget':
                if params['targetId']=='new':raise RuntimeError('window lookup failed')
                return {'windowId':1}
            raise AssertionError(method)
        state={'current':'old','context':'ctx','owned':{'old':1}}
        browser=BoundBrowser(wire,state)
        browser.checkpoint=lambda: snapshots.append(copy.deepcopy(state))
        with self.assertRaisesRegex(RuntimeError,'window lookup failed'):browser.create()
        self.assertTrue(any(s['owned'].get('new','missing') is None for s in snapshots))

class EventTests(unittest.TestCase):
    def test_helper_event_drain_excludes_other_owned_and_manual_sessions(self):
        state={'current':'a','context':'ctx','owned':{'a':1,'b':2}}
        class Wire:
            events=[{'method':'Network.loadingFinished','session_id':s,'params':{}} for s in ('a','b','manual')]
            dialogs={};event_overflow=False
            def pump(self):pass
            def __call__(self,method,params=None,session=None):
                if method=='Target.getTargets':return {'targetInfos':[{'targetId':t,'browserContextId':'ctx'} for t in ('a','b')]}
                if method=='Browser.getWindowForTarget':return {'windowId':1 if params['targetId']=='a' else 2}
                if method=='Target.attachToTarget':return {'sessionId':params['targetId']}
                return {}
        browser=BoundBrowser(Wire(),state)
        result=browser.send({'meta':'drain_events'})
        self.assertEqual([e['session_id'] for e in result['events']],['a'])
        browser.send({'meta':'set_session','target_id':'b'})
        self.assertEqual(browser.send({'meta':'session'})['session_id'],'b')
        self.assertEqual([e['session_id'] for e in browser.send({'meta':'drain_events'})['events']],['b'])

    def test_popup_creation_event_publishes_before_more_user_code(self):
        state={'current':'old','context':'ctx','owned':{'old':1},'baseline':['manual']}
        class Wire:
            def pump(self):pass
        wire=Wire();seen=[]
        browser=BoundBrowser(wire,state,lambda:seen.append(copy.deepcopy(state)))
        self.assertTrue(hasattr(wire,'on_event'))
        wire.on_event({'method':'Target.targetCreated','params':{'targetInfo':{'targetId':'popup','type':'page','browserContextId':'ctx','openerId':'old'}},'session_id':None})
        self.assertEqual(state['owned'],{'old':1,'popup':None})
        self.assertEqual(seen[-1]['owned'],state['owned'])

    def test_wire_keeps_real_scoped_dialog_events_and_pumps_idle_socket(self):
        from worker import Wire
        class Socket:
            def __init__(self):self.frames=[]
            def send(self,msg):
                self.frames += [{'method':'Page.javascriptDialogOpening','sessionId':'owned','params':{'type':'alert','message':'fixture'}},{'id':json.loads(msg)['id'],'result':{}}]
            def recv(self,timeout):
                if not self.frames:raise TimeoutError()
                return json.dumps(self.frames.pop(0))
        wire=Wire.__new__(Wire);wire.ws=Socket();wire.counter=0
        wire('Page.enable',{},'owned')
        self.assertTrue(hasattr(wire,'events'),'events were discarded')
        self.assertEqual(wire.dialogs['owned']['message'],'fixture')
        wire.ws.frames=[{'method':'Page.javascriptDialogClosed','sessionId':'owned','params':{}}]
        wire.pump()
        self.assertIsNone(wire.dialogs.get('owned'))
        self.assertEqual(len(wire.events),2)

if __name__=='__main__':unittest.main()
