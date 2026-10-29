"""Source-removal observation uses temporary files and inert callbacks only."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from resource_watch import SourceRemovalWatch


class SourceRemovalWatchTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.markers=[self.root/'plugin.yaml',self.root/'worker.py']
        for marker in self.markers:marker.write_text('synthetic source')

    def watcher(self,callback,**kwargs):
        watch=SourceRemovalWatch(self.markers,callback,poll_interval=.01,grace_s=.025,**kwargs)
        self.addCleanup(watch.stop)
        return watch

    def test_construction_and_idle_stop_never_start_thread_or_invoke_callback(self):
        callback=Mock()
        with patch('resource_watch.threading.Thread') as thread:
            watch=self.watcher(callback)
            self.assertTrue(watch.stopped);self.assertFalse(watch.is_running)
            self.assertTrue(watch.stop());self.assertFalse(watch.start())
        thread.assert_not_called();callback.assert_not_called()

    def test_persistent_removal_calls_once_on_daemon_then_stops(self):
        called=threading.Event();calls=[]
        def callback():
            calls.append((threading.current_thread().name,threading.current_thread().daemon))
            called.set()
        watch=self.watcher(callback)
        self.assertTrue(watch.start());self.assertFalse(watch.start())
        self.markers[0].unlink()
        self.assertTrue(called.wait(1))
        self.assertTrue(watch.stop())
        self.assertEqual(calls,[('chrome-source-removal-watch',True)])
        self.assertTrue(watch.removal_detected);self.assertFalse(watch.callback_failed)
        self.assertFalse(watch.is_running);self.assertFalse(watch.start())

    def test_atomic_content_replacement_does_not_trigger_cleanup(self):
        callback=Mock();watch=self.watcher(callback);watch.start()
        for index in range(8):
            replacement=self.root/'replacement'
            replacement.write_text('changed source '+str(index))
            os.replace(replacement,self.markers[index%2])
            time.sleep(.005)
        watch.stop();callback.assert_not_called()
        self.assertFalse(watch.removal_detected)

    def test_brief_missing_marker_resets_after_reappearance(self):
        callback=Mock();watch=self.watcher(callback)
        observed_missing=threading.Event();original=watch._present
        def present():
            value=original()
            if not value:observed_missing.set()
            return value
        watch._present=present;watch.start();self.markers[0].unlink()
        self.assertTrue(observed_missing.wait(1))
        self.markers[0].write_text('replacement after brief absence')
        time.sleep(.06);watch.stop()
        callback.assert_not_called();self.assertFalse(watch.removal_detected)

    def test_symbolic_link_to_valid_source_is_not_a_regular_marker(self):
        called=threading.Event();watch=self.watcher(called.set)
        destination=self.root/'other-source';destination.write_text('valid content')
        self.markers[0].unlink();self.markers[0].symlink_to(destination)
        self.assertFalse(watch._present())
        watch.start();self.assertTrue(called.wait(1));watch.stop()
        self.assertTrue(destination.is_file())

    def test_callback_can_stop_its_own_watcher_without_joining_itself(self):
        called=threading.Event();calls=[];watch=None
        def callback():
            calls.append(watch.stop());called.set()
        watch=self.watcher(callback);self.markers[1].unlink();watch.start()
        self.assertTrue(called.wait(1));self.assertTrue(watch.stop())
        self.assertEqual(calls,[False]) # Callback is still executing when self-stop returns.
        self.assertFalse(watch.callback_failed)

    def test_callback_error_does_not_retry_or_leave_watcher_running(self):
        called=threading.Event();calls=[]
        def callback():
            calls.append(True);called.set();raise RuntimeError('synthetic cleanup failure')
        watch=self.watcher(callback);self.markers[0].unlink();watch.start()
        self.assertTrue(called.wait(1));self.assertTrue(watch.stop())
        self.assertTrue(watch.callback_failed);self.assertEqual(calls,[True])
        self.assertFalse(watch.is_running)

    def test_stop_wait_is_bounded_even_while_cleanup_callback_is_busy(self):
        entered=threading.Event();release=threading.Event()
        self.addCleanup(release.set)
        def callback():entered.set();release.wait(1)
        watch=self.watcher(callback);self.markers[0].unlink();watch.start()
        self.assertTrue(entered.wait(1))
        start=time.monotonic()
        self.assertFalse(watch.stop(join_timeout=.01))
        self.assertLess(time.monotonic()-start,.2)
        release.set();self.assertTrue(watch.stop())


if __name__=='__main__':unittest.main()
