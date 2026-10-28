"""Session fault isolation through real bounded worker pipes; no personal Chrome."""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from plugin import ChromeProvider


class SessionIsolationTests(unittest.TestCase):
    def test_timeout_during_parent_cdp_response_preserves_peer_connection(self):
        class Wire:
            def __init__(self,*args):
                self.closed=False;self.events=[];self.dialogs={};self.event_gaps={}
                self.event_overflow=False;self.detached_sessions=set()
                self.release=threading.Event()
            def __call__(self,method,params=None,session=None):
                if method=='Fixture.block':
                    self.release.wait(2)
                    if self.closed:raise OSError('transport closed while awaiting response')
                return {'marker':'peer'}
            def pump(self):pass
            def close(self):self.closed=True;self.release.set()

        with tempfile.TemporaryDirectory() as root:
            script=Path(root)/'worker.py'
            script.write_text('import json,sys\nr=json.loads(sys.stdin.readline())\n'
                'print(json.dumps({"cdp":{"method":r["method"]}}),flush=True)\n'
                'response=json.loads(sys.stdin.readline())\n'
                'print(json.dumps({"result":{"success":"error" not in response,"response":response}}),flush=True)\n')
            provider=ChromeProvider(data=root)
            first={'state':{'owned':{'a':1}}};peer={'state':{'owned':{'b':2}}}
            provider.states={('a','default'):first,('b','default'):peer}
            def request(entry,method,timeout):
                provider._active_entry=entry
                return provider._worker({'endpoint':'ws://fixture','profile':root+'/Default','method':method},timeout)
            with patch('plugin.ROOT',Path(root)),patch('observer.Wire',Wire):
                try:
                    self.assertTrue(request(peer,'Fixture.read',2)['success'])
                    with self.assertRaises(subprocess.TimeoutExpired):request(first,'Fixture.block',.2)
                    self.assertFalse(peer['observer'].closed,'one worker timeout closed its peer observer')
                    self.assertTrue(request(peer,'Fixture.read',2)['success'])
                    self.assertIsNot(first['observer'],peer['observer'])
                finally:
                    for entry in (first,peer):
                        if entry.get('observer'):entry['observer'].close()


if __name__=='__main__':unittest.main()
