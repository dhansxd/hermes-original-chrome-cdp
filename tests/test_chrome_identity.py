import unittest,sys,tempfile
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import consent
class ChromeIdentityTests(unittest.TestCase):
 def test_same_native_sheet_reported_by_two_windows_is_one_candidate(self):
  s={'key':(42,7),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow']}
  try:value=consent.select_sheet([s,dict(s)],set(),{42})
  except consent.ConsentError as e:self.fail(str(e))
  self.assertEqual(value,s)
  other=dict(s,key=(42,8))
  with self.assertRaisesRegex(consent.ConsentError,'ambiguous'):consent.select_sheet([s,other],set(),{42})
 def test_signing_clone_recognized_only_after_equivalence_check(self):
  exe='/private/var/folders/aa/bb/X/com.google.Chrome.code_sign_clone/code_sign_clone.Test/Google Chrome.app.bundle/Contents/MacOS/Google Chrome'
  plist={'CFBundleIdentifier':'com.google.Chrome','CFBundleExecutable':'Google Chrome'}
  with patch('consent.verify_chrome_executable',create=True,return_value=True):self.assertEqual(consent.host_identity(exe,plist,'/root'),'main')
  with patch('consent.verify_chrome_executable',create=True,return_value=False):self.assertIsNone(consent.host_identity(exe,plist,'/root'))
 def test_valid_google_signed_old_clone_not_required_to_match_updated_disk_bytes(self):
  exe=Path('/private/var/folders/aa/bb/X/com.google.Chrome.code_sign_clone/code_sign_clone.Test/Google Chrome.app.bundle/Contents/MacOS/Google Chrome')
  stamp=Mock(st_mode=0o100755,st_ino=7,st_size=100,st_mtime_ns=9,st_ctime_ns=10,st_uid=501)
  with patch('pathlib.Path.stat',return_value=stamp),patch('pathlib.Path.read_bytes',side_effect=lambda p=None:b'old signed' if p==exe else b'updated signed',autospec=True),patch('consent.subprocess.run',return_value=Mock(returncode=0)):
   self.assertTrue(consent.verify_chrome_executable(str(exe)))
  with patch('pathlib.Path.stat',return_value=stamp),patch('consent.subprocess.run',return_value=Mock(returncode=1)):
   self.assertFalse(consent.verify_chrome_executable(str(exe)))
if __name__=='__main__':unittest.main()
