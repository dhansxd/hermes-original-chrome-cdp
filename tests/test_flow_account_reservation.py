"""Cross-profile identity/debt coordination with real locks and synthetic accounts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

import flow_reservation as guard
import profile_probe


ACCOUNT = hashlib.sha256(b'synthetic-google-account-a').hexdigest()
OTHER = hashlib.sha256(b'synthetic-google-account-b').hexdigest()


class AccountReservations(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.profile = self.home/'Chrome/Default'; self.peer = self.home/'Chrome/Profile 2'
        self.job = self.home/'job'
        home = patch.object(guard.Path, 'home', return_value=self.home)
        home.start(); self.addCleanup(home.stop)

    def browser(self, profile=None, account=ACCOUNT, **kwargs):
        return guard.acquire_browser(profile or self.profile, account_key=account, timeout=0, **kwargs)

    def test_same_account_two_profiles_are_exclusive(self):
        with guard.acquire_job(self.profile, self.job, account_key=ACCOUNT):
            with self.assertRaises(guard.FlowResourceBusy): self.browser(self.peer)
            with self.browser(self.peer, OTHER): pass

    def test_two_browser_batches_share_account_exclusion_without_records(self):
        with self.browser():
            with self.assertRaises(guard.FlowResourceBusy): self.browser(self.peer)
        self.assertEqual(list(guard._folder().glob('*.json')), [])
        with self.browser(self.peer): pass

    def test_same_profile_cannot_bypass_profile_lock_with_other_account(self):
        with self.browser():
            with self.assertRaises(guard.FlowResourceBusy): self.browser(account=OTHER)

    def test_account_debt_survives_process_death(self):
        code = '''import os,sys
from pathlib import Path
import flow_reservation as g
g.Path.home=lambda:Path(sys.argv[1])
x=g.acquire_job(Path(sys.argv[2]),Path(sys.argv[3]),account_key=sys.argv[4])
x.update(spent=True,phase='submitted')
os._exit(7)
'''
        child = subprocess.run([sys.executable, '-c', code, str(self.home), str(self.profile), str(self.job), ACCOUNT], cwd=Path(guard.__file__).parent, timeout=10)
        self.assertEqual(child.returncode, 7)
        with self.assertRaises(guard.FlowRecoveryRequired): self.browser(self.peer)
        with self.assertRaises(guard.FlowRecoveryRequired):
            guard.acquire_job(self.peer, self.job, account_key=ACCOUNT, resume=True, timeout=0)
        with guard.acquire_job(self.profile, self.job, account_key=ACCOUNT, resume=True, timeout=0) as recovery:
            recovery.update(resolved=True)
        with self.browser(self.peer): pass

    def test_changed_account_cannot_resume_or_erase_debt(self):
        with guard.acquire_job(self.profile, self.job, account_key=ACCOUNT) as job: job.update(dirty=True)
        record = next(guard._folder().glob('*.json')); before = record.read_bytes()
        for resume in (False, True):
            with self.assertRaises(guard.FlowRecoveryRequired):
                guard.acquire_job(self.profile, self.job, account_key=OTHER, resume=resume, timeout=0)
        self.assertEqual(record.read_bytes(), before)
        with self.assertRaises(guard.FlowRecoveryRequired): self.browser(self.peer)

    def test_single_private_record_contains_immutable_digests(self):
        with guard.acquire_job(self.profile, self.job, account_key=ACCOUNT) as held:
            records = list(guard._folder().glob('*.json')); self.assertEqual(len(records), 1)
            data = json.loads(records[0].read_text())
            self.assertEqual(data['version'], 2); self.assertEqual(data['account'], ACCOUNT)
            self.assertEqual(data['profile'], guard._key(self.profile))
            for fields in ({'account': OTHER}, {'profile': guard._key(self.peer)}):
                with self.assertRaises(ValueError): held.update(**fields)
            self.assertNotIn(str(self.profile), records[0].read_text())
            self.assertEqual(records[0].stat().st_mode & 0o777, 0o600)

    def test_unknown_legacy_debt_blocks_even_own_resume_without_rewriting(self):
        with guard.acquire_job(self.profile, self.job) as old: old.update(spent=True)
        record = next(guard._folder().glob('*.json')); before = record.read_bytes()
        for profile, account in ((self.profile, ACCOUNT), (self.peer, ACCOUNT), (self.peer, OTHER)):
            with self.assertRaises(guard.FlowRecoveryRequired):
                guard.acquire_job(profile, self.job, account_key=account, resume=True, timeout=0)
        self.assertEqual(record.read_bytes(), before)

    def test_corrupt_other_record_fails_closed(self):
        folder = guard._folder(); other = folder/(guard._key(self.peer)+'.json')
        other.write_text('{'); other.chmod(0o600)
        with self.assertRaises(guard.FlowRecoveryRequired): self.browser()
        self.assertEqual(other.read_text(), '{')

    def test_unsafe_other_record_is_never_followed_or_opened_blocking(self):
        folder = guard._folder(); record = folder/(guard._key(self.peer)+'.json')
        outside = self.home/'outside'; outside.write_text('unchanged')
        record.symlink_to(outside)
        with self.assertRaises(guard.FlowRecoveryRequired): self.browser()
        record.unlink(); os.mkfifo(record, 0o600)
        start=time.monotonic()
        with self.assertRaises(guard.FlowRecoveryRequired): self.browser()
        self.assertLess(time.monotonic()-start, .5)
        self.assertEqual(outside.read_text(), 'unchanged')

    def test_account_less_api_refuses_production_original_profile(self):
        original = self.home/'Library/Application Support/Google/Chrome/Default'
        with self.assertRaises(guard.FlowRecoveryRequired): guard.acquire_browser(original, timeout=0)
        original.parent.mkdir(parents=True)
        original.symlink_to(self.peer)
        with self.assertRaises(guard.FlowRecoveryRequired): guard.acquire_browser(original, timeout=0)

    def test_invalid_key_refuses_without_leaking_descriptors(self):
        before = len(os.listdir('/dev/fd'))
        for value in ('', 'x', 'F'*64, True, ['a'*64]):
            with self.assertRaises((ValueError, guard.FlowRecoveryRequired)): self.browser(account=value)
        self.assertEqual(len(os.listdir('/dev/fd')), before)

    def test_registry_enumeration_counts_non_record_entries(self):
        folder=guard._folder()
        for n in range(4): (folder/(str(n)+'.unrelated')).touch()
        with patch.object(guard, 'MAX_ENTRIES', 3):
            with self.assertRaises(guard.FlowRecoveryRequired): self.browser()

    def test_repeated_contention_closes_account_and_profile_descriptors(self):
        before=len(os.listdir('/dev/fd'))
        for _ in range(30):
            with self.browser():
                with self.assertRaises(guard.FlowResourceBusy): self.browser(self.peer)
                with self.assertRaises(guard.FlowResourceBusy): self.browser(account=OTHER)
        self.assertEqual(len(os.listdir('/dev/fd')), before)

    def test_account_then_profile_wait_share_one_deadline(self):
        release_account=threading.Event(); release_profile=threading.Event()
        account_ready=threading.Event(); profile_ready=threading.Event()
        def account_owner():
            with self.browser(self.peer): account_ready.set(); release_account.wait(2)
        def profile_owner():
            with guard.acquire_browser(self.profile): profile_ready.set(); release_profile.wait(2)
        threads=[threading.Thread(target=account_owner),threading.Thread(target=profile_owner)]
        for thread in threads:thread.start()
        timer=None
        try:
            self.assertTrue(account_ready.wait(1) and profile_ready.wait(1))
            timer=threading.Timer(.12,release_account.set); timer.start()
            start=time.monotonic()
            with self.assertRaises(guard.FlowResourceBusy):
                guard.acquire_browser(self.profile, account_key=ACCOUNT, timeout=.2)
            elapsed=time.monotonic()-start
            self.assertGreaterEqual(elapsed,.15); self.assertLess(elapsed,.29)
        finally:
            release_account.set(); release_profile.set()
            if timer:timer.join(1)
            for thread in threads:thread.join(2); self.assertFalse(thread.is_alive())

    def test_replaced_account_lock_is_detected_before_next_action(self):
        with self.browser() as held:
            path=guard._folder()/('account-'+ACCOUNT+'.lock')
            path.unlink(); path.touch(mode=0o600)
            with self.assertRaises(guard.FlowRecoveryRequired):held.check_binding()

    def test_relay_thread_can_only_validate_not_mutate_reservation(self):
        results=[]
        with guard.acquire_job(self.profile,self.job,account_key=ACCOUNT) as held:
            def relay():
                held.check_binding(); results.append('validated')
                with self.assertRaisesRegex(RuntimeError,'wrong_owner'):held.update(dirty=True)
                with self.assertRaisesRegex(RuntimeError,'wrong_owner'):held.close()
            thread=threading.Thread(target=relay); thread.start(); thread.join(2)
            self.assertFalse(thread.is_alive()); self.assertEqual(results,['validated'])
            self.assertFalse(held.record['dirty'])

    def test_registry_replacement_during_scan_fails_closed(self):
        with guard.acquire_job(self.peer,self.home/'other-job',account_key=OTHER) as other:other.update(spent=True)
        folder=guard._folder(); read=guard._read; replaced=False
        def replacing(path,**kwargs):
            nonlocal replaced
            record=read(path,**kwargs)
            if kwargs.get('directory') is not None and not replaced:
                folder.rename(folder.with_name('old-registry')); folder.mkdir(mode=0o700); replaced=True
            return record
        with patch.object(guard,'_read',side_effect=replacing):
            with self.assertRaises(guard.FlowRecoveryRequired):self.browser()
        self.assertTrue(replaced)


class AccountIdentity(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'Chrome'; self.root.mkdir()
        root=patch.object(profile_probe.base, 'PERSONAL', self.root)
        root.start(); self.addCleanup(root.stop)

    def write(self, profile, email, gaia='123456789012345678901'):
        child=self.root/profile; child.mkdir(exist_ok=True)
        (child/'Preferences').write_text(json.dumps({'account_info':[{'email':email,'gaia':gaia}]}))
        path=self.root/'Local State'; state=json.loads(path.read_text()) if path.exists() else {'profile':{'info_cache':{}}}
        state['profile']['info_cache'][profile]={'user_name':email,'gaia_id':gaia,'is_ephemeral':False,'force_signin_profile_locked':False}
        path.write_text(json.dumps(state)); return child

    def test_email_aliases_with_same_required_gaia_have_same_key(self):
        a=self.write('Default','first@example.invalid'); b=self.write('Profile 2','alias@example.invalid')
        key=profile_probe.flow_account_key(a,'first@example.invalid')
        self.assertRegex(key, r'^[0-9a-f]{64}$')
        self.assertEqual(key, profile_probe.flow_account_key(b,'alias@example.invalid'))
        self.assertNotEqual(key, profile_probe.flow_account_key(self.write('Profile 3','other@example.invalid','123456789012345678902'),'other@example.invalid'))

    def test_missing_mismatched_or_ambiguous_gaia_has_no_email_fallback(self):
        for entry in ({'email':'first@example.invalid'}, {'email':'first@example.invalid','gaia':'123456789012345678902'}, {'email':'first@example.invalid','gaia':True}):
            child=self.write('Default','first@example.invalid')
            (child/'Preferences').write_text(json.dumps({'account_info':[entry]}))
            with self.assertRaises(RuntimeError): profile_probe.flow_account_key(child,'first@example.invalid')
        child=self.write('Default','first@example.invalid')
        entry={'email':'first@example.invalid','gaia':'123456789012345678901'}
        (child/'Preferences').write_text(json.dumps({'account_info':[entry,entry]}))
        with self.assertRaises(RuntimeError): profile_probe.flow_account_key(child,'first@example.invalid')

    def test_wrong_primary_email_or_symlink_metadata_refuses(self):
        child=self.write('Default','first@example.invalid')
        with self.assertRaises(RuntimeError): profile_probe.flow_account_key(child,'wrong@example.invalid')
        outside=self.root/'outside'; outside.write_bytes((child/'Preferences').read_bytes())
        (child/'Preferences').unlink(); (child/'Preferences').symlink_to(outside)
        with self.assertRaises(RuntimeError): profile_probe.flow_account_key(child,'first@example.invalid')
