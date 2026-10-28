"""Destination GUI admission, never real browser launches."""
import sys,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path.home()/'.hermes/hermes-agent'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hermes_bootstrap
import plugin
GUI='gui/501 = {\n session = Aqua\n security context = {\n uid = 501\n asid = 100002\n }\n}'
class DestinationTests(unittest.TestCase):
 def test_background_caller_dispatches_to_verified_destination(self):
  commands=[]
  def run(argv,**kwargs):
   commands.append((argv,kwargs))
   if argv==['/bin/launchctl','managername']:return Mock(returncode=0,stdout='Background')
   return Mock(returncode=0,stdout=GUI.replace('gui/501','pid/42') if argv[-1]=='pid/42' else GUI)
  proc=Mock(pid=42,info={'name':'Google Chrome','exe':str(plugin.CHROME/'Contents/MacOS/Google Chrome'),'cmdline':['--user-data-dir=/fixture'],'create_time':10})
  proc.as_dict.side_effect=lambda **kw:dict(proc.info)
  with patch('plugin.subprocess.run',side_effect=run),patch('plugin.ctypes.CDLL') as lib,patch('plugin.os.getuid',return_value=501),patch('plugin.os.geteuid',return_value=501),patch('plugin.os.stat',return_value=Mock(st_uid=501)):
   def info(request,sid,flags):
    sid._obj.value=100002;flags._obj.value=0x10 if int(request.value)==100002 else 0;return 0
   lib.return_value.SessionGetInfo.side_effect=info
   # Independent browser inventory boundary: this test checks dispatch, GUI integration checks process.
   with patch('psutil.process_iter',return_value=[proc]):plugin.gui_launch(Path('/fixture'), 'file:///fixture/seed.html')
  opens=[(a,k)for a,k in commands if a[0]=='/usr/bin/open']
  self.assertEqual(len(opens),1)
  self.assertIn('-n',opens[0][0]);self.assertIn('-g',opens[0][0])
  self.assertEqual(set(opens[0][1]['env']),{'HOME','PATH','TMPDIR'})

 def test_running_chrome_in_other_security_session_never_dispatches(self):
  calls=[]
  def run(argv,**kw):
   calls.append(argv)
   text=GUI.replace('gui/501','pid/42').replace('100002','100024') if argv[-1]=='pid/42' else GUI
   return Mock(returncode=0,stdout=text)
  proc=Mock(pid=42,info={'name':'Google Chrome','exe':str(plugin.CHROME/'Contents/MacOS/Google Chrome'),'cmdline':['--user-data-dir=/fixture'],'create_time':10})
  proc.as_dict.side_effect=lambda **kw:dict(proc.info)
  with patch('plugin.subprocess.run',side_effect=run),patch('plugin.ctypes.CDLL') as lib,patch('plugin.os.getuid',return_value=501),patch('plugin.os.geteuid',return_value=501),patch('plugin.os.stat',return_value=Mock(st_uid=501)),patch('psutil.process_iter',return_value=[proc]):
   def info(request,sid,flags):
    sid._obj.value=request.value;flags._obj.value=0x10;return 0
   lib.return_value.SessionGetInfo.side_effect=info
   with self.assertRaisesRegex(RuntimeError,'Chrome destination mismatch'):plugin.gui_launch(Path('/fixture'))
  self.assertFalse(any(a[0]=='/usr/bin/open'for a in calls))

 def test_invalid_destination_never_dispatches(self):
  calls=[]
  def run(argv,**kw):
   calls.append(argv);return Mock(returncode=0,stdout=GUI.replace('Aqua','Background'))
  with patch('plugin.subprocess.run',side_effect=run),patch('plugin.os.getuid',return_value=501),patch('plugin.os.geteuid',return_value=501),patch('plugin.os.stat',return_value=Mock(st_uid=501)):
   with self.assertRaisesRegex(RuntimeError,'safe_GUI_launch_unavailable'):plugin.gui_launch(Path('/fixture'))
  self.assertFalse(any(a[0]=='/usr/bin/open'for a in calls))
if __name__=='__main__':unittest.main()
