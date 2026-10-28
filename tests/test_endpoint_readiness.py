"""Endpoint freshness before connect; never launch real personal Chrome."""
import sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
from plugin import ChromeProvider,CHROME
class ReadinessTests(unittest.TestCase):
 def test_stale_file_is_not_returned_before_new_listener_publishes_endpoint(self):
  with tempfile.TemporaryDirectory() as d:
   data=Path(d);f=data/'DevToolsActivePort';f.write_text('12345\n/devtools/browser/old\n')
   provider=ChromeProvider(data=data,workspace=data/'work');entry={}
   started=f.stat().st_mtime+1;calls=[]
   proc=Mock(pid=42,info={'name':'Google Chrome','exe':str(CHROME/'Contents/MacOS/Google Chrome'),'cmdline':['--user-data-dir='+str(data)],'create_time':started})
   proc.create_time.return_value=started
   proc.net_connections.return_value=[Mock(status='LISTEN',laddr=Mock(port=12345,ip='127.0.0.1'))]
   def refresh(*a):
    calls.append(True);f.write_text('12345\n/devtools/browser/new\n')
    import os
    os.utime(f,(started+1,started+1))
   with patch('plugin.gui_launch'),patch('psutil.process_iter',return_value=[proc]),patch('plugin.time.sleep',side_effect=refresh):
    endpoint=provider.endpoint(entry=entry)
   self.assertEqual(endpoint,'ws://127.0.0.1:12345/devtools/browser/new')
   self.assertEqual(len(calls),1)
if __name__=='__main__':unittest.main()
