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
   proc.as_dict.side_effect=lambda **kw:dict(proc.info)
   proc.create_time.return_value=started
   proc.net_connections.return_value=[Mock(status='LISTEN',laddr=Mock(port=12345,ip='127.0.0.1'))]
   def refresh(*a):
    calls.append(True);f.write_text('12345\n/devtools/browser/new\n')
    import os
    os.utime(f,(started+1,started+1))
   with patch('plugin.gui_launch'),patch('plugin.seed_window_ready',return_value=True),patch('psutil.process_iter',return_value=[proc]),patch('plugin.time.sleep',side_effect=refresh):
    endpoint=provider.endpoint(entry=entry)
   self.assertEqual(endpoint,'ws://127.0.0.1:12345/devtools/browser/new')
   self.assertEqual(len(calls),1)
 def test_current_listener_waits_for_exact_new_seed_window_before_returning(self):
  with tempfile.TemporaryDirectory() as d:
   data=Path(d);(data/'DevToolsActivePort').write_text('12345\n/devtools/browser/current\n')
   provider=ChromeProvider(data=data,workspace=data/'work');entry={}
   proc=Mock(pid=42)
   proc.as_dict.return_value={'name':'Google Chrome','exe':str(CHROME/'Contents/MacOS/Google Chrome'),
                             'cmdline':['--user-data-dir='+str(data)],'create_time':1}
   proc.create_time.return_value=1
   proc.net_connections.return_value=[Mock(status='LISTEN',laddr=Mock(port=12345,ip='127.0.0.1'))]
   with patch('plugin.gui_launch') as launch,patch('psutil.process_iter',return_value=[proc]), \
        patch('plugin.seed_window_ready',create=True,side_effect=[False,False,True]) as ready, \
        patch('plugin.time.sleep'):
    endpoint=provider.endpoint(entry=entry)
   self.assertEqual(ready.call_count,3,'current TCP listener must not bypass GUI seed readiness')
   self.assertEqual(endpoint,'ws://127.0.0.1:12345/devtools/browser/current')
   launch.assert_called_once_with(data.resolve(),entry['state']['pending_seed'])
   self.assertTrue(all(call.args==(42,entry['state']['pending_seed'])for call in ready.call_args_list))

 def test_missing_seed_window_expires_without_returning_endpoint_or_relaunch(self):
  with tempfile.TemporaryDirectory() as d:
   data=Path(d);(data/'DevToolsActivePort').write_text('12345\n/devtools/browser/current\n')
   provider=ChromeProvider(data=data,workspace=data/'work');entry={}
   proc=Mock(pid=42)
   proc.as_dict.return_value={'name':'Google Chrome','exe':str(CHROME/'Contents/MacOS/Google Chrome'),
                             'cmdline':['--user-data-dir='+str(data)],'create_time':1}
   proc.create_time.return_value=1
   proc.net_connections.return_value=[Mock(status='LISTEN',laddr=Mock(port=12345,ip='127.0.0.1'))]
   with patch('plugin.gui_launch') as launch,patch('psutil.process_iter',return_value=[proc]), \
        patch('plugin.seed_window_ready',create=True,return_value=False), \
        patch('plugin.time.monotonic',side_effect=[0,0,21]),patch('plugin.time.sleep'):
    with self.assertRaisesRegex(RuntimeError,'Default_seed_window_unavailable'):
     provider.endpoint(entry=entry)
   launch.assert_called_once()
   self.assertFalse(entry['state']['verified'])
   self.assertEqual(entry['state']['owned'],{})
   self.assertIn('pending_seed',entry['state'])

class SeedWindowTests(unittest.TestCase):
 def test_readiness_requires_one_exact_document_in_a_standard_window(self):
  from plugin import seed_window_ready
  seed='file:///owned-seed.html'
  for rows,expected in (([],False),([('AXStandardWindow','file:///foreign')],False),
                        ([('AXDialog',seed)],False),([('AXStandardWindow',seed)]*2,False),
                        ([('AXStandardWindow',seed),('AXStandardWindow','file:///foreign')],True)):
   with self.subTest(rows=rows):
    ax=Mock();ax.refs=[];ax.trusted.return_value=True
    ax.ax.AXUIElementCreateApplication.return_value='app';ax.attr.return_value='windows'
    ax.cf.CFArrayGetCount.return_value=len(rows)
    ax.cf.CFArrayGetValueAtIndex.side_effect=lambda values,index:index
    ax.text.side_effect=lambda node,name:rows[node][0 if name=='AXSubrole' else 1]
    with patch('consent.AX',return_value=ax):self.assertIs(seed_window_ready(42,seed),expected)
    ax.ax.AXUIElementCreateApplication.assert_called_once_with(42)
    ax.ax.AXUIElementPerformAction.assert_not_called()
    ax.clear.assert_called_once()

 def test_invalid_or_busy_ax_snapshot_waits_but_other_errors_stay_explicit(self):
  from consent import ConsentError
  from plugin import seed_window_ready
  for code in (-25202,-25204,-25200):
   with self.subTest(code=code):
    ax=Mock();ax.refs=[];ax.trusted.return_value=True
    ax.attr.side_effect=ConsentError('consent_ax_read:'+str(code))
    with patch('consent.AX',return_value=ax):
     if code in (-25202,-25204):self.assertFalse(seed_window_ready(42,'file:///owned'))
     else:
      with self.assertRaisesRegex(ConsentError,'consent_ax_read:-25200'):seed_window_ready(42,'file:///owned')
    ax.clear.assert_called_once()

 def test_missing_accessibility_refuses_without_reading_or_requesting_permission(self):
  from consent import ConsentError
  from plugin import seed_window_ready
  ax=Mock();ax.refs=[];ax.trusted.return_value=False
  with patch('consent.AX',return_value=ax):
   with self.assertRaisesRegex(ConsentError,'consent_accessibility'):seed_window_ready(42,'file:///owned')
  ax.attr.assert_not_called();ax.ax.AXUIElementCreateApplication.assert_not_called()
  ax.clear.assert_called_once()

if __name__=='__main__':unittest.main()
