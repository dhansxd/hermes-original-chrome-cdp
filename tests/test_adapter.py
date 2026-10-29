import json, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class AdapterTest(unittest.TestCase):
    def test_failure_reports_without_silent_fallback_or_replay(self):
        from plugin import ChromeProvider
        p=ChromeProvider(data='/synthetic-adapter-fixture')
        def fail(*a,**k):raise RuntimeError('GUI unavailable')
        p.endpoint=fail
        result=json.loads(p.execute({'code':'print(1)'},task_id='fixture'))
        self.assertFalse(result['success'])
        self.assertIn('GUI unavailable',result['error'])
        self.assertFalse(result['fallback_used'])
        self.assertFalse(result['action_replayed'])
        self.assertIn('Chrome',p.get_setup_schema()['name'])

    def test_first_call_timeout_is_quarantined_without_replay(self):
        import subprocess
        from plugin import ChromeProvider
        p=ChromeProvider(data='/synthetic-adapter-fixture');p.endpoint=lambda **kw:'ws://fixture'
        p._prepare_observer=lambda *args,**kwargs:None # The worker below is synthetic.
        calls=[]
        def timeout(*a,**kw):
            calls.append(True)
            raise subprocess.TimeoutExpired('fixture',5)
        p._worker=timeout
        first=json.loads(p.execute({'code':'print(1)'},task_id='fixture'))
        second=json.loads(p.execute({'code':'print(1)'},task_id='fixture'))
        self.assertIn('uncertain',second['error'])
        self.assertEqual(len(calls),1)

class SelectionTest(unittest.TestCase):
    def test_failed_exec_does_not_keep_previous_vault_selection(self):
        from plugin import ChromeProvider
        p=ChromeProvider(data='/synthetic-test-only')
        p.endpoint=lambda **kw:'ws://synthetic'
        p._prepare_observer=lambda *args,**kwargs:None # The worker below is synthetic.
        p._worker=lambda *a,**k:{'success':True,'state':{'owned':{'a':1}}}
        p.execute({'code':'pass','session':'one'},task_id='fixture')
        self.assertEqual(p.last_sessions,{'fixture':'one'})
        p._worker=lambda *a,**k:{'success':False,'error':'injected'}
        p.execute({'code':'pass','session':'two'},task_id='fixture')
        self.assertNotIn('fixture',p.last_sessions)

if __name__=='__main__':unittest.main()
