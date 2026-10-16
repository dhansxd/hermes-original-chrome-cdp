import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plugin import ChromeProvider

class FinishBrowserTests(unittest.TestCase):
    def run_finish(self, other=None, owned=None, close_error=None, alive=None):
        with tempfile.TemporaryDirectory(dir=Path.home()/'.hermes/cache/scratch') as root:
            Path(root,'worker.py').write_text('import sys,json\nr=json.loads(sys.stdin.readline())\nprint(json.dumps({"cdp":{"method":"__finish_browser__"}}),flush=True)\nv=json.loads(sys.stdin.readline())\nprint(json.dumps({"result":v}),flush=True)\n')
            p=ChromeProvider(data=root);obs=Mock();obs.closed=False
            obs.request.return_value={'error':'unknown_meta'}
            if close_error:obs.wire.side_effect=close_error
            entry={'observer':obs,'state':{'owned':owned or {},'verified':True}}
            p.states={('task','default'):entry};p._active_entry=entry
            if other is not None:p.states[('other','default')]=other
            with patch('plugin.ROOT',Path(root)),patch.object(p,'_chrome_processes',return_value=[],create=True),patch('psutil.wait_procs',return_value=([],alive or [])):
                result=p._worker({'endpoint':'fixture','profile':root},3)
            return result,obs

    def test_last_finished_session_requests_normal_browser_exit(self):
        result,obs=self.run_finish()
        self.assertTrue(result.get('value',{}).get('browser_closed'),result)
        obs.wire.assert_called_once_with('Browser.close')

    def test_active_other_session_defers_browser_exit(self):
        result,obs=self.run_finish(other={'state':{'owned':{'other':1}}})
        self.assertEqual(result.get('value',{}).get('browser_close_deferred'),'other_sessions_active',result)
        obs.wire.assert_not_called()

    def test_retained_or_failed_target_prevents_exit(self):
        result,obs=self.run_finish(owned={'retained':1})
        self.assertFalse(result.get('value',{}).get('browser_closed'),result)
        obs.wire.assert_not_called()

    def test_failed_close_is_not_reported_as_browser_closed(self):
        result,obs=self.run_finish(close_error=OSError('fixture failure'))
        self.assertFalse(result['value']['browser_closed'])
        self.assertEqual(result['value']['browser_close_error'],'OSError')

    def test_still_running_browser_is_not_reported_as_closed(self):
        result,obs=self.run_finish(alive=[object()])
        self.assertFalse(result['value']['browser_closed'])
        self.assertEqual(result['value']['browser_close_error'],'Chrome_process_still_running')

if __name__=='__main__':unittest.main()
