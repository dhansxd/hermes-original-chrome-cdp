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

if __name__=='__main__':unittest.main()
