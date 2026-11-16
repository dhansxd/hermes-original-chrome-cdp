import unittest
from unittest.mock import patch

import native_windows


class NativeWindowCleanupTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
