"""Real file-lock coordination and crash receipts; no browser/network/account access."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import flow_reservation as guard


class FlowReservations(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.profile = self.home / 'Chrome/Default'
        self.job = self.home / 'job'
        mock = patch.object(guard.Path, 'home', return_value=self.home)
        mock.start()
        self.addCleanup(mock.stop)

    def test_other_sites_are_not_sensitive_but_flow_identity_and_http_aliases_are(self):
        for url in ('https://flow.google.com/project/x', 'http://FLOW.GOOGLE.COM/',
                    'https://flow.google.com./', 'https://labs.google/fx/tools/flow',
                    'https://accounts.google.com/Logout', 'https://myaccount.google.com/',
                    'https://www.google.com/accounts/Logout'):
            self.assertTrue(guard.protected_url(url), url)
        for url in ('https://example.com', 'https://www.google.com/search?q=test',
                    'https://flow.google.com.evil.invalid/', 'about:blank'):
            self.assertFalse(guard.protected_url(url), url)

    def test_live_job_excludes_browser_and_other_job_after_gui_is_yielded(self):
        with guard.acquire_job(self.profile, self.job) as held:
            held.update(project_id='11111111-1111-4111-8111-111111111111',
                        dirty=False, spent=True, phase='rendering')
            for acquire in (lambda: guard.acquire_browser(self.profile, timeout=0),
                            lambda: guard.acquire_job(self.profile, self.home/'other', timeout=0)):
                with self.assertRaises(guard.FlowResourceBusy):
                    acquire()
            with guard.acquire_browser(self.profile.parent/'Profile 2', timeout=0):
                pass
            held.update(resolved=True, phase='completed')
        with guard.acquire_browser(self.profile, timeout=0):
            pass

    def test_browser_batch_excludes_job_without_creating_durable_marker(self):
        with guard.acquire_browser(self.profile):
            with self.assertRaises(guard.FlowResourceBusy):
                guard.acquire_job(self.profile, self.job, timeout=0)
        self.assertEqual(list(guard._folder().glob('*.json')), [])

    def test_clean_pre_submit_exception_does_not_leave_account_blocked(self):
        with self.assertRaisesRegex(ValueError, 'fixture'):
            with guard.acquire_job(self.profile, self.job):
                raise ValueError('fixture')
        with guard.acquire_browser(self.profile, timeout=0):
            pass

    def test_dirty_settings_survive_close_even_when_video_is_resolved(self):
        with guard.acquire_job(self.profile, self.job) as held:
            held.update(dirty=True, resolved=True)
        self.assertTrue(held.pending)
        with self.assertRaises(guard.FlowRecoveryRequired):
            guard.acquire_browser(self.profile, timeout=0)
        with guard.acquire_job(self.profile, self.job, resume=True) as recovery:
            self.assertTrue(recovery.record['dirty'])
            recovery.update(resolved=True)
        self.assertTrue(recovery.pending)
        with self.assertRaises(guard.FlowRecoveryRequired):
            guard.acquire_browser(self.profile, timeout=0)
        with guard.acquire_job(self.profile, self.job, resume=True) as recovery:
            recovery.update(dirty=False)
        with guard.acquire_browser(self.profile, timeout=0):
            pass

    def test_process_death_never_expires_a_potentially_billed_job(self):
        script = ('import os,sys; from pathlib import Path; import flow_reservation as g; '
                  'g.Path.home=lambda:Path(sys.argv[1]); '
                  'x=g.acquire_job(Path(sys.argv[2]),Path(sys.argv[3])); '
                  'x.update(spent=True,phase="submitted"); os._exit(7)')
        result = subprocess.run([sys.executable, '-c', script, str(self.home),
                                 str(self.profile), str(self.job)], cwd=Path(guard.__file__).parent)
        self.assertEqual(result.returncode, 7)
        for acquire in (lambda: guard.acquire_browser(self.profile, timeout=0),
                        lambda: guard.acquire_job(self.profile, self.home/'other', timeout=0),
                        lambda: guard.acquire_job(self.profile, self.job, timeout=0)):
            with self.assertRaises(guard.FlowRecoveryRequired):
                acquire()
        with guard.acquire_job(self.profile, self.job, resume=True, timeout=0) as recovery:
            recovery.update(resolved=True)
        self.assertFalse(recovery.pending)
        with guard.acquire_browser(self.profile, timeout=0):
            pass

    def test_corrupt_or_symlink_receipt_is_never_ignored_or_overwritten(self):
        with guard.acquire_job(self.profile, self.job) as held:
            held.update(spent=True)
        record = next(guard._folder().glob('*.json'))
        record.write_text('not json')
        with self.assertRaises(guard.FlowRecoveryRequired):
            guard.acquire_browser(self.profile, timeout=0)
        record.unlink()
        outside = self.home/'outside'; outside.write_text('unchanged')
        record.symlink_to(outside)
        with self.assertRaises((OSError, RuntimeError)):
            guard.acquire_browser(self.profile, timeout=0)
        self.assertEqual(outside.read_text(), 'unchanged')

    def test_state_is_private_bounded_metadata_not_profile_or_prompt(self):
        with guard.acquire_job(self.profile, self.job) as held:
            held.update(spent=True)
        record = next(guard._folder().glob('*.json'))
        data = record.read_text()
        self.assertNotIn(str(self.profile), data)
        self.assertNotIn(str(self.job), data)
        self.assertLess(len(data), 4096)
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        with guard.acquire_job(self.profile, self.job, resume=True) as recovery:
            recovery.update(resolved=True)

    def test_repeated_contention_and_close_do_not_leak_file_descriptors(self):
        baseline = len(os.listdir('/dev/fd'))
        for _ in range(40):
            with guard.acquire_job(self.profile, self.job):
                with self.assertRaises(guard.FlowResourceBusy):
                    guard.acquire_browser(self.profile, timeout=0)
        self.assertEqual(len(os.listdir('/dev/fd')), baseline)

    def test_fifo_receipt_is_rejected_within_a_bounded_child_deadline(self):
        with guard.acquire_job(self.profile, self.job) as job:
            job.update(spent=True)
        record = next(guard._folder().glob('*.json'))
        record.unlink(); os.mkfifo(record, 0o600)
        script = '''import sys
from pathlib import Path
import flow_reservation as g
g.Path.home=lambda:Path(sys.argv[1])
try:g.acquire_browser(Path(sys.argv[2]),timeout=0)
except g.FlowRecoveryRequired:sys.exit(0)
sys.exit(2)
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.home), str(self.profile)],
                                cwd=Path(guard.__file__).parent, timeout=2)
        self.assertEqual(result.returncode, 0)

    def test_unsubmitted_review_requires_existing_unspent_exact_job_atomically(self):
        with self.assertRaises(guard.FlowRecoveryRequired):
            guard.acquire_job(self.profile, self.job, resume=True, require_unsubmitted=True)
        self.assertEqual(list(guard._folder().glob('*.json')), [])
        with guard.acquire_job(self.profile, self.job) as job:
            job.update(dirty=True)
        with guard.acquire_job(self.profile, self.job, resume=True, require_unsubmitted=True) as review:
            self.assertFalse(review.record['spent'])
            review.update(dirty=False)
        with guard.acquire_job(self.profile, self.job) as job:
            job.update(spent=True)
        with self.assertRaises(guard.FlowRecoveryRequired):
            guard.acquire_job(self.profile, self.job, resume=True, require_unsubmitted=True)
        with guard.acquire_job(self.profile, self.job, resume=True) as recovery:
            self.assertTrue(recovery.record['spent'])
            recovery.update(resolved=True)
