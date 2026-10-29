"""Offline helper diagnostics: never run AppleScript, Chrome or an AX press."""
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import consent


class PressDiagnosticTests(unittest.TestCase):
    sheet={'pid':42,'bundle':'com.google.Chrome'}

    def test_helper_timeout_is_bounded_and_does_not_expose_script_or_payload(self):
        failure=subprocess.TimeoutExpired(['osascript','-e',consent.PRESS_SCRIPT,'private-argument'],3,
                                         output='private stdout',stderr='private stderr')
        ax=object.__new__(consent.AX)
        with patch('consent.subprocess.run',side_effect=failure) as run:
            with self.assertRaises(consent.ConsentError) as caught:ax.press(self.sheet)
        self.assertEqual(str(caught.exception),'consent_press_timeout: helper deadline; press outcome unknown; no retry')
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs['timeout'],3)
        self.assertLess(len(str(caught.exception)),160)
        self.assertNotIn('private',str(caught.exception))
        self.assertNotIn('on headings',str(caught.exception))

    def test_helper_start_failure_omits_private_os_error(self):
        ax=object.__new__(consent.AX)
        with patch('consent.subprocess.run',side_effect=OSError('private executable path')) as run:
            with self.assertRaises(consent.ConsentError) as caught:ax.press(self.sheet)
        self.assertEqual(str(caught.exception),'consent_press_unavailable: helper could not start; no retry')
        run.assert_called_once()

    def test_helper_receipts_use_only_allowlisted_status_and_numeric_exit(self):
        ax=object.__new__(consent.AX)
        for status,returncode,expected in [('stale-host',0,'stale-host'),('not-found',0,'not-found'),
                                           ('private stdout',1,'unrecognized'),('clicked',1,'clicked')]:
            with self.subTest(status=status,returncode=returncode):
                with patch('consent.subprocess.run',return_value=Mock(returncode=returncode,stdout=status,stderr='private stderr')) as run:
                    with self.assertRaises(consent.ConsentError) as caught:ax.press(self.sheet)
                self.assertEqual(str(caught.exception),
                    f'consent_press_not_confirmed: helper_status={expected}; returncode={returncode}; press outcome unknown; no retry')
                self.assertNotIn('private',str(caught.exception))
                run.assert_called_once()


class HandshakeDiagnosticTests(unittest.TestCase):
    def test_helper_timeout_is_terminal_within_the_same_pending_handshake(self):
        # Fake transport and subprocess only: no real socket, permission or press.
        connected=threading.Event();release=threading.Event();order=[]
        sheet={'key':(42,1),'pid':42,'bundle':'com.google.Chrome',
               'name':'Allow remote debugging?','headings':[],'buttons':['Allow']}
        ax=object.__new__(consent.AX)
        class Backend:
            def scan(self):return [sheet] if connected.is_set() else []
            def hosts(self):return {42}
            def correlate(self):return True
            def press(self,sheet,*,pending):
                if pending():
                    order.append('press')
                    try:ax.press(sheet)
                    finally:release.set()
        def attach(*args,**kwargs):
            order.append('connect');connected.set()
            if not release.wait(1):raise TimeoutError('fixture barrier failed')
            # Keep the same handshake pending through further observation ticks.
            threading.Event().wait(.2)
            raise TimeoutError('fixture handshake denied')
        failure=subprocess.TimeoutExpired(['osascript','-e',consent.PRESS_SCRIPT],3,stderr='private details')
        with patch('consent.subprocess.run',side_effect=failure) as run:
            with self.assertRaises(consent.ConsentError) as caught:
                consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/fixture','/fixture',attach,backend=Backend(),timeout=1)
        self.assertEqual(str(caught.exception),'consent_attach_failed: consent_press_timeout: helper deadline; press outcome unknown; no retry')
        self.assertEqual(order,['connect','press'])
        run.assert_called_once()
        self.assertNotIn('private',str(caught.exception))


if __name__=='__main__':unittest.main()
