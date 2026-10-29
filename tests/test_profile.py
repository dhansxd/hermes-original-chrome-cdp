import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class ProfileTest(unittest.TestCase):
    def test_missing_account_configuration_refuses_before_metadata_or_launch(self):
        from plugin import verify_account
        from unittest.mock import patch
        with patch.object(Path, 'read_text', side_effect=AssertionError('must not inspect an unconfigured profile')):
            for expected in (None, '', '   ', 123, {}):
                with self.subTest(expected=expected), self.assertRaisesRegex(RuntimeError, 'account_binding_unconfigured'):
                    verify_account('/synthetic-unconfigured-profile', expected)

    def test_provider_reads_expected_account_from_profile_local_settings(self):
        from plugin import ChromeProvider, PERSONAL, NAME, APPROVED_ACCOUNT
        from unittest.mock import Mock,patch
        get_setting=Mock(return_value=APPROVED_ACCOUNT)
        with patch('plugin.verify_account',side_effect=RuntimeError('identity gate reached')) as verify:
            provider=ChromeProvider(data=PERSONAL,get_setting=get_setting,
                read_browser_config=lambda:{'cloud_provider':NAME,'backend':'browser-use'},native_browser_disabled=lambda:True)
            result=json.loads(provider.execute({'code':'pass'},task_id='configuration-test'))
        self.assertFalse(result['success'])
        get_setting.assert_called_once_with('expected_account')
        verify.assert_called_once_with(PERSONAL.resolve(),APPROVED_ACCOUNT)

    def test_provider_missing_setting_never_reads_profile_or_launches(self):
        from plugin import ChromeProvider, PERSONAL
        from unittest.mock import patch
        with patch('hermes_cli.config.load_config_readonly',side_effect=AssertionError('no ambient config fallback')), patch('plugin.gui_launch',side_effect=AssertionError('must not launch')) as launch:
            result=json.loads(ChromeProvider(data=PERSONAL).execute({'code':'pass'},task_id='unconfigured-test'))
        self.assertFalse(result['success'])
        self.assertIn('account_binding_unconfigured',result['error'])
        launch.assert_not_called()

    def test_account_mismatch_refuses_before_launch(self):
        from plugin import verify_account
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);(p/'Default').mkdir()
            (p/'Local State').write_text(json.dumps({'profile':{'info_cache':{'Default':{'user_name':'other@example.com'}}}}))
            (p/'Default/Preferences').write_text(json.dumps({'account_info':[{'email':'other@example.com'}]}))
            with self.assertRaisesRegex(RuntimeError,'account_binding_mismatch'):
                verify_account(p,'approved@example.test')
            (p/'Local State').write_text(json.dumps({'profile':{'info_cache':{'Default':{'user_name':'approved@example.test'}}}}))
            (p/'Default/Preferences').write_text(json.dumps({'account_info':[{'email':'approved@example.test'}]}))
            verify_account(p,'approved@example.test')

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
            nonlocal url
            calls.append((method,params))
            if method=='Target.getTargets':return {'targetInfos':[{'targetId':'other','type':'page','browserContextId':'other-context','url':'about:blank'},{'targetId':'seed','type':'page','browserContextId':'default-context','url':url}]}
            if method=='Browser.getWindowForTarget':return {'windowId':2}
            if method=='Target.attachToTarget':return {'sessionId':'sid'}
            if method=='Runtime.evaluate':return {'result':{'value':'/fixture/Default'}}
            if method=='Page.navigate':url=params['url'];return {'frameId':'seed'}
            return {}
        state=initialize(wire,'/fixture/Default',seed_url=url)
        self.assertEqual(state['context'],'default-context')
        self.assertEqual(state['owned'],{'seed':2})
        self.assertFalse(any(m=='Target.createTarget' for m,p in calls))
        self.assertFalse(any(p.get('targetId')=='other' for m,p in calls if isinstance(p,dict)))

    def test_profile_not_verified_until_blank_navigation_is_observed(self):
        import copy
        from unittest.mock import patch
        from worker import initialize
        url='file:///owned-seed';pending=0;checkpoints=[];navigations=[]
        def wire(method,params=None,session=None):
            nonlocal url,pending
            if method=='Target.getTargets':
                if pending:
                    pending-=1
                    if not pending:url='about:blank'
                return {'targetInfos':[{'targetId':'seed','type':'page','browserContextId':'ctx','url':url}]}
            if method=='Browser.getWindowForTarget':return {'windowId':2}
            if method=='Target.attachToTarget':return {'sessionId':'sid'}
            if method=='Runtime.evaluate':return {'result':{'value':'/fixture/Default'}}
            if method=='Page.navigate':
                navigations.append(params['url'])
                if params['url']=='about:blank':pending=3
                else:url=params['url']
                return {'frameId':'seed'}
            return {}
        wire.checkpoint=lambda state:checkpoints.append((copy.deepcopy(state),url))
        with patch('worker.time.sleep') as sleep:
            state=initialize(wire,'/fixture/Default',seed_url=url)
        self.assertTrue(state['verified']);self.assertGreaterEqual(sleep.call_count,2)
        self.assertEqual(navigations,['chrome://version/','about:blank'])
        self.assertTrue(all(url=='about:blank' for snapshot,url in checkpoints if snapshot['verified']))

if __name__=='__main__':unittest.main()
