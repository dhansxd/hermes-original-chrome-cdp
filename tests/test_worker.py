import json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class WorkerTest(unittest.TestCase):
    def test_reuses_harness_helpers_in_private_namespace(self):
        sys.path.insert(0,str(ROOT))
        from worker import helper_namespace
        class Browser:
            def cdp(self,method,**params):
                if method=='Runtime.evaluate':return {'result':{'value':'bound page'}}
                raise AssertionError(method)
            def send(self,req,**kw):return {'dialog':None}
            def create(self,url='about:blank'):return 'agent'
        ns=helper_namespace(Browser())
        self.assertEqual(ns['js']('document.title'),'bound page')
        import browser_harness.helpers as original
        self.assertIsNot(original.cdp,ns['cdp'])
        self.assertEqual(original.cdp.__module__,'browser_harness.helpers')
        self.assertIn('finish_browser',ns)

class HelperResilienceTest(unittest.TestCase):
    def test_preflight_navigation_with_domain_skills_has_workspace(self):
        from unittest.mock import patch
        import os
        sys.path.insert(0,str(ROOT))
        from worker import helper_namespace
        class Browser:
            def cdp(self,method,**params):return {}
            def send(self,*a,**kw):return {}
            def create(self,*a):return 'agent'
        with patch.dict(os.environ,BH_DOMAIN_SKILLS='1'):
            ns=helper_namespace(Browser())
            try:
                self.assertEqual(ns['goto_url']('chrome://version/'),{})
            except NameError as exc:
                self.fail(str(exc))

    def test_helpers_work_without_importing_installed_harness(self):
        from unittest.mock import patch
        import builtins
        sys.path.insert(0,str(ROOT))
        from worker import helper_namespace
        real_import = builtins.__import__
        def no_harness(name,*args,**kwargs):
            if name.startswith('browser_harness'):
                raise ImportError('simulated harness update removed internal module')
            return real_import(name,*args,**kwargs)
        class Browser:
            def cdp(self,method,**params):
                return {'result':{'value':'bound page'}}
            def send(self,req,**kw):return {'dialog':None}
            def create(self,url='about:blank'):return 'agent'
        with patch('builtins.__import__',side_effect=no_harness):
            try:
                ns=helper_namespace(Browser())
                result=ns['js']('document.title')
            except ImportError as exc:
                self.fail(str(exc))
        self.assertEqual(result,'bound page')
        expected = {'drain_events','goto_url','page_info','click_at_xy','type_text',
            'fill_input','press_key','scroll','capture_screenshot','list_tabs','current_tab',
            'activate_tab','switch_tab','new_tab','close_tab','ensure_real_tab','iframe_target',
            'wait','wait_for_load','wait_for_element','wait_for_network_idle','js',
            'dispatch_key','upload_file','http_get','start_recording','stop_recording',
            'recording_dir','finish_browser','cdp'}
        self.assertTrue(expected.issubset(ns))
        self.assertTrue(all(callable(ns[name]) for name in expected))

if __name__=='__main__':unittest.main()
