import unittest
from unittest.mock import patch
from types import SimpleNamespace
import subprocess

import native_windows


class NativeWindowCleanupTests(unittest.TestCase):
    def test_chrome_about_event_check_accepts_an_empty_result(self):
        with patch.object(native_windows.subprocess, 'run', return_value=SimpleNamespace(stdout='Timestamp\n')) as run:
            native_windows.verify_no_chrome_about_events(0)
        self.assertTrue(run.call_args.kwargs['check'])

    def test_chrome_about_event_check_rejects_an_unexpected_event(self):
        output = 'Timestamp\nRECEIVED:(aevt,abtm) target=Google Chrome\n'
        with patch.object(native_windows.subprocess, 'run', return_value=SimpleNamespace(stdout=output)):
            with self.assertRaisesRegex(AssertionError, 'unexpected_chrome_about_this_mac_events'):
                native_windows.verify_no_chrome_about_events(0)

    def test_unreadable_chrome_about_event_log_fails_verification(self):
        with patch.object(native_windows.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'log')):
            with self.assertRaises(subprocess.CalledProcessError):
                native_windows.verify_no_chrome_about_events(0)

    def test_original_windows_must_be_preserved(self):
        before = {(1, 10)}
        with patch.object(native_windows, 'window_keys', return_value=before):
            native_windows.verify_cleanup(before)

    def test_native_window_left_after_zero_cdp_sessions_fails(self):
        with patch.object(native_windows, 'window_keys', return_value={(1, 20)}):
            with self.assertRaisesRegex(AssertionError, 'native_windows_added'):
                native_windows.verify_cleanup(set(), timeout=0)

    def test_transient_window_close_is_observed_to_completion(self):
        before = {(1, 10)}
        with patch.object(native_windows, 'window_keys', side_effect=[before | {(1, 20)}, before]), \
                patch.object(native_windows.time, 'sleep'):
            native_windows.verify_cleanup(before)

    def test_unreadable_native_inventory_cannot_pass_as_no_windows(self):
        with patch.object(native_windows, 'window_keys', side_effect=RuntimeError('AX unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'AX unavailable'):
                native_windows.verify_cleanup(set())

    def test_transient_accessibility_read_requires_a_successful_inventory_before_passing(self):
        before = {(1, 10)}
        with patch.object(native_windows, 'window_keys', side_effect=[
                native_windows.ConsentError('consent_ax_read:-25204'), before]) as read, \
                patch.object(native_windows.time, 'sleep'):
            native_windows.verify_cleanup(before)
        self.assertEqual(read.call_count, 2)

    def test_persistent_accessibility_read_error_fails_at_the_existing_deadline(self):
        with patch.object(native_windows, 'window_keys',
                          side_effect=native_windows.ConsentError('consent_ax_read:-25204')):
            with self.assertRaises(native_windows.ConsentError):
                native_windows.verify_cleanup(set(), timeout=0)


if __name__ == '__main__':
    unittest.main()
