import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class ProfileTest(unittest.TestCase):
    def test_account_mismatch_refuses_before_launch(self):
        from plugin import verify_account
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);(p/'Default').mkdir()
            (p/'Local State').write_text(json.dumps({'profile':{'info_cache':{'Default':{'user_name':'other@example.com'}}}}))
            (p/'Default/Preferences').write_text(json.dumps({'account_info':[{'email':'other@example.com'}]}))
            with self.assertRaisesRegex(RuntimeError,'account_binding_mismatch'):
                verify_account(p,'developer@example.invalid')
            (p/'Local State').write_text(json.dumps({'profile':{'info_cache':{'Default':{'user_name':'developer@example.invalid'}}}}))
            (p/'Default/Preferences').write_text(json.dumps({'account_info':[{'email':'developer@example.invalid'}]}))
            verify_account(p,'developer@example.invalid')

    def test_initialize_missing_seed_never_creates_in_any_context(self):
        from worker import initialize
        calls=[]
        def wire(method,params=None,session=None):
            calls.append(method)
            if method=='Target.getTargets':return {'targetInfos':[{'targetId':'other','type':'page','browserContextId':'other-context','url':'about:blank'}]}
            raise AssertionError('must not inspect or create a candidate: '+method)
        from unittest.mock import patch
        with patch('worker.time.monotonic',side_effect=[0,6]), self.assertRaisesRegex(RuntimeError,'Default_seed_unavailable'):
            initialize(wire,'/fixture/Default',seed_url='data:text/html,unique-seed')
        self.assertEqual(calls,['Target.getTargets'])

    def test_initialize_waits_for_same_seed_url_without_relaunch(self):
        from worker import initialize
        from unittest.mock import patch
        responses=[{'targetInfos':[{'targetId':'seed','type':'page','browserContextId':'ctx','url':'about:blank'}]}, {'targetInfos':[{'targetId':'seed','type':'page','browserContextId':'ctx','url':'file:///exact-seed'}]}]
        def wire(method,params=None,session=None):
            if method=='Target.getTargets':return responses.pop(0)
            if method=='Browser.getWindowForTarget':return {'windowId':2}
            raise AssertionError(method)
        with patch('worker.time.sleep'):
            state=initialize(wire,'/fixture/Default','file:///exact-seed',cleanup=True)
        self.assertEqual(state['owned'],{'seed':2})
        self.assertEqual(responses,[])

    def test_initialize_only_verifies_explicit_seed(self):
        from worker import initialize
        calls=[];url='data:text/html,unique-seed'
        def wire(method,params=None,session=None):
            calls.append((method,params))
            if method=='Target.getTargets':return {'targetInfos':[{'targetId':'other','type':'page','browserContextId':'other-context','url':'about:blank'},{'targetId':'seed','type':'page','browserContextId':'default-context','url':url}]}
            if method=='Browser.getWindowForTarget':return {'windowId':2}
            if method=='Target.attachToTarget':return {'sessionId':'sid'}
            if method=='Runtime.evaluate':return {'result':{'value':'/fixture/Default'}}
            return {}
        state=initialize(wire,'/fixture/Default',seed_url=url)
        self.assertEqual(state['context'],'default-context')
        self.assertEqual(state['owned'],{'seed':2})
        self.assertFalse(any(m=='Target.createTarget' for m,p in calls))
        self.assertFalse(any(p.get('targetId')=='other' for m,p in calls if isinstance(p,dict)))

if __name__=='__main__':unittest.main()
