"""Owned target focus/creation must wait for other clients' consent handshakes."""
from contextlib import contextmanager
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock,patch
from observer import ScopedObserver


class SharedConsentFocus(unittest.TestCase):
 def test_creation_and_activation_wait_but_read_only_requests_do_not(self):
  state={'owned':{'owned':7},'context':'profile-context','current':'owned'}
  requests=[{'method':'Target.activateTarget','params':{'targetId':'owned'}},
            {'method':'Target.createTarget','params':{'url':'about:blank','browserContextId':'profile-context','newWindow':True,'background':True}}]
  for request in requests:
   with self.subTest(method=request['method']):
    entered=threading.Event();release=threading.Event();errors=[]
    @contextmanager
    def guard(*args,**kwargs):
     entered.set();release.wait(1);yield
    observer=object.__new__(ScopedObserver);observer.closed=False;observer.sessions={}
    observer.data_root=Path('/synthetic-chrome');observer._lock=threading.RLock()
    observer._request=Mock(return_value={'ok':True})
    def invoke():
     try:observer.request(request,state)
     except Exception as exc:errors.append(exc)
    with patch('observer.consent_guard',guard):
     thread=threading.Thread(target=invoke);thread.start()
     try:
      self.assertTrue(entered.wait(.3));observer._request.assert_not_called()
      self.assertEqual(observer.request({'method':'Browser.getVersion'},state),{'ok':True})
      observer._request.assert_called_once()
     finally:release.set();thread.join(1)
    self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
    self.assertEqual(observer._request.call_count,2)


if __name__=='__main__':unittest.main()
