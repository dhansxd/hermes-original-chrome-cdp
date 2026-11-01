"""A protected unrelated macOS PID cannot break positive Chrome ownership proof."""
import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path.home()/'.hermes/hermes-agent')]
import hermes_bootstrap
import plugin


class ProcessInspectionTests(unittest.TestCase):
 def chrome(self,data):
  proc=Mock(pid=42);proc.name.return_value='Google Chrome'
  proc.as_dict.return_value={'name':'Google Chrome','exe':str(plugin.CHROME/'Contents/MacOS/Google Chrome'),
                            'cmdline':['--user-data-dir='+str(data)],'create_time':1}
  proc.create_time.return_value=1
  proc.net_connections.return_value=[Mock(status='LISTEN',laddr=Mock(port=12345,ip='127.0.0.1'))]
  return proc
 def test_unrelated_protected_cmdline_is_not_read(self):
  with tempfile.TemporaryDirectory() as d:
   data=Path(d);(data/'DevToolsActivePort').write_text('12345\n/devtools/browser/current\n')
   denied=Mock();denied.name.return_value='kernel_task'
   denied.as_dict.side_effect=PermissionError('protected PID')
   chrome=self.chrome(data)
   provider=plugin.ChromeProvider(data=data,workspace=data/'work')
   with patch('psutil.process_iter',return_value=[denied,chrome]):
    result=provider._endpoint_identity()
   self.assertEqual(result['pid'],42);denied.as_dict.assert_not_called()
 def test_unreadable_chrome_cmdline_is_not_default_root_authority(self):
  proc=self.chrome(Path('/fixture'))
  proc.as_dict.return_value['cmdline']=None
  self.assertIsNone(plugin._chrome_process_info(proc))
 def test_permission_wrapped_system_error_is_unreadable_but_other_system_errors_propagate(self):
  proc=Mock();proc.name.return_value='Google Chrome'
  try:
   try:raise PermissionError('protected PID')
   except PermissionError as cause:raise SystemError('macOS proc_cmdline failed') from cause
  except SystemError as error:wrapped=error
  proc.as_dict.side_effect=wrapped
  self.assertIsNone(plugin._chrome_process_info(proc))
  proc.as_dict.side_effect=SystemError('unrelated interpreter failure')
  with self.assertRaises(SystemError):plugin._chrome_process_info(proc)
 def test_no_positive_current_chrome_owner_never_returns_an_endpoint(self):
  with tempfile.TemporaryDirectory() as d:
   data=Path(d);(data/'DevToolsActivePort').write_text('12345\n/devtools/browser/current\n')
   proc=Mock();proc.name.side_effect=PermissionError('unreadable name')
   proc.as_dict.side_effect=PermissionError('unreadable command')
   provider=plugin.ChromeProvider(data=data,workspace=data/'work')
   with patch('psutil.process_iter',return_value=[proc]):
    with self.assertRaises(ValueError):provider._endpoint_identity()
 def test_named_unreadable_chrome_blocks_gui_dispatch_and_cleanup_inventory(self):
  proc=Mock();proc.name.return_value='Google Chrome'
  proc.as_dict.side_effect=PermissionError('unreadable Chrome command')
  with patch('psutil.process_iter',return_value=[proc]),patch('plugin.gui_identity',return_value=(501,1)),patch('plugin.subprocess.run') as dispatch:
   with self.assertRaisesRegex(RuntimeError,'chrome_process_identity_unavailable'):
    plugin.gui_launch(Path('/fixture'))
   dispatch.assert_not_called()
   provider=plugin.ChromeProvider(data='/fixture')
   with self.assertRaisesRegex(RuntimeError,'chrome_process_identity_unavailable'):
    provider._chrome_processes()
  proc.terminate.assert_not_called();proc.kill.assert_not_called()
 def test_malformed_positive_chrome_metadata_is_not_authority(self):
  for field,value in [('exe',None),('cmdline',None),('cmdline',['chrome',None]),('create_time',True),('create_time',float('nan')),('create_time',0)]:
   with self.subTest(field=field,value=value):
    proc=self.chrome(Path('/fixture'));proc.as_dict.return_value[field]=value
    self.assertIsNone(plugin._chrome_process_info(proc))


if __name__=='__main__':unittest.main()
