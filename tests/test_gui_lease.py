"""Offline cooperative leases; no Chrome, native permissions or network."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import gui_lease


class GuiLeases(unittest.TestCase):
 def setUp(self):
  self.home=tempfile.TemporaryDirectory();self.addCleanup(self.home.cleanup)
  self.patch=patch.object(gui_lease.Path,'home',return_value=Path(self.home.name));self.patch.start();self.addCleanup(self.patch.stop)
  self.profile=Path(self.home.name)/'Chrome/Default'
 def test_reentrant_batch_excludes_another_thread_until_final_close(self):
  outer=gui_lease.acquire(self.profile,'https://flow.google.com');inner=gui_lease.acquire(self.profile,'https://flow.google.com')
  result=[]
  def attempt():
   try:
    with gui_lease.acquire(self.profile,'https://flow.google.com',timeout=.01):result.append('entered')
   except gui_lease.GuiResourceBusy as exc:result.append((exc.code,exc.retryable))
  inner.close();thread=threading.Thread(target=attempt);thread.start();thread.join(1)
  self.assertEqual(result,[('gui_resource_busy',True)])
  outer.close();thread=threading.Thread(target=attempt);thread.start();thread.join(1)
  self.assertEqual(result[-1],'entered')
 def test_other_original_profile_can_work_while_flow_batch_is_held(self):
  errors=[]
  def other():
   try:
    with gui_lease.acquire(self.profile.parent/'Profile 2','https://flow.google.com',timeout=0):pass
   except Exception as exc:errors.append(exc)
  with gui_lease.acquire(self.profile,'https://flow.google.com'):
   thread=threading.Thread(target=other);thread.start();thread.join(1)
   self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
 def test_exception_releases_lease_and_only_hashes_are_written(self):
  with self.assertRaisesRegex(ValueError,'fixture'):
   with gui_lease.acquire(self.profile,'https://flow.google.com'):raise ValueError('fixture')
  with gui_lease.acquire(self.profile,'https://flow.google.com'):pass
  files=list(gui_lease._folder().iterdir());self.assertEqual(len(files),1)
  self.assertEqual(len(files[0].stem),64);self.assertEqual(files[0].read_bytes(),b'')
  self.assertEqual(files[0].stat().st_mode&0o777,0o600)
 def test_origin_policy_excludes_unrelated_google_and_userinfo(self):
  self.assertEqual(gui_lease.origin_for_url('https://flow.google.com/project/fixture'),'https://flow.google.com')
  for url in ('https://FLOW.GOOGLE.COM:443/project/fixture','https://labs.google:443/fx/tools/flow/project/fixture','https://labs.google/flow'):
   self.assertEqual(gui_lease.origin_for_url(url),'https://flow.google.com')
  for url in ('https://google.com','https://labs.google/fx/tools/music','https://flow.google.com.evil.invalid/','https://'+'user@'+'flow.google.com/','http://flow.google.com/'):
   self.assertIsNone(gui_lease.origin_for_url(url))
 def test_aliases_are_one_reentrant_resource_and_exclude_another_thread(self):
  blocked=[]
  def other():
   try:
    with gui_lease.acquire(self.profile,'https://labs.google',timeout=0):blocked.append(False)
   except gui_lease.GuiResourceBusy:blocked.append(True)
  with gui_lease.acquire(self.profile,'https://flow.google.com')as first:
   with gui_lease.acquire(self.profile,'https://labs.google')as second:self.assertEqual(first.key,second.key)
   thread=threading.Thread(target=other);thread.start();thread.join(1)
   self.assertEqual(blocked,[True])
 def test_symlink_lock_cannot_redirect_lease_writes(self):
  lease=gui_lease.acquire(self.profile,'https://flow.google.com');lease.close()
  file=next(gui_lease._folder().iterdir());file.unlink()
  target=Path(self.home.name)/'unrelated';target.write_text('unchanged');file.symlink_to(target)
  with self.assertRaises(OSError):gui_lease.acquire(self.profile,'https://flow.google.com')
  self.assertEqual(target.read_text(),'unchanged')


if __name__=='__main__':unittest.main()
