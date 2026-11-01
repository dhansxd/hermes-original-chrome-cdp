"""Explicit Flow probe extension never widens registered Default provider policy."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plugin
from ownership_journal import JournalError, OwnershipJournal


class ProfileProbeProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'chrome'
        self.root.mkdir(mode=0o700)
        (self.root / 'Profile 7').mkdir(mode=0o700)
        (self.root / 'Local State').write_text(json.dumps({'profile': {'info_cache': {
            'Profile 7': {'user_name': 'probe@example.test'}}}}))
        (self.root / 'Profile 7' / 'Preferences').write_text(json.dumps({
            'account_info': [{'email': 'probe@example.test'}]}))
        self.enterContext(patch.object(plugin, 'PERSONAL', self.root))

    def provider(self, account='probe@example.test', profile='Profile 7'):
        from profile_probe import ProfileProbeProvider
        return ProfileProbeProvider(profile, account, self.root.parent / 'work',
            read_browser_config=lambda: {'cloud_provider': plugin.NAME},
            native_browser_disabled=lambda: True)

    def test_explicit_profile_is_used_in_launch_and_provenance_only(self):
        provider = self.provider()
        provider.require_ready()
        self.assertEqual(provider.profile_path, self.root / 'Profile 7')
        with patch.object(plugin, 'gui_launch') as launch:
            provider._launch_seed('file:///fixture/seed.html')
        launch.assert_called_once_with(self.root, 'file:///fixture/seed.html', profile_directory='Profile 7')
        record = provider._journal().begin_seed()
        self.assertEqual(record['profile'], str(self.root / 'Profile 7'))
        with self.assertRaises(JournalError):
            OwnershipJournal(provider.workspace / 'ownership', self.root).records()

    def test_wrong_account_missing_directory_and_symlink_refuse_without_launch(self):
        for account, profile in [('wrong@example.test', 'Profile 7'), ('probe@example.test', 'Profile 8')]:
            with self.subTest(account=account, profile=profile), patch.object(plugin, 'gui_launch') as launch:
                with self.assertRaises(RuntimeError): self.provider(account, profile).require_ready()
                launch.assert_not_called()
        path = self.root / 'Profile 7' / 'Preferences'
        path.rename(path.with_name('real-prefs'))
        path.symlink_to('real-prefs')
        with self.assertRaises(RuntimeError): self.provider().require_ready()

    def test_registered_provider_still_rejects_another_account(self):
        provider = plugin.ChromeProvider(get_setting=lambda key: 'probe@example.test',
            read_browser_config=lambda: {'cloud_provider': plugin.NAME}, native_browser_disabled=lambda: True)
        with self.assertRaisesRegex(RuntimeError, 'account_binding_not_approved'):
            provider.require_ready()
        self.assertEqual(provider.profile_path, self.root / 'Default')

    def test_probe_provider_cannot_be_used_as_registered_execution_tool(self):
        with self.assertRaisesRegex(RuntimeError, 'profile_probe_only'):
            self.provider().execute({'code': 'pass'}, task_id='fixture')

    def test_invalid_profile_ids_are_rejected_before_directory_creation(self):
        for profile in ('../escape', '/tmp/other', 'Guest Profile', 'System Profile', 'bad\nrow'):
            with self.subTest(profile=profile), self.assertRaises((RuntimeError, ValueError)):
                self.provider(profile=profile)
        self.assertFalse((self.root / 'Default').exists())

    def test_journal_cannot_bind_profile_outside_root(self):
        with self.assertRaises(JournalError):
            OwnershipJournal(self.root.parent / 'journal', self.root, profile_path=self.root.parent / 'other')

    def test_replaced_directory_after_preparation_never_reaches_gui_launch(self):
        provider=self.provider()
        provider.require_ready()
        original=self.root/'Profile 7'
        original.rename(self.root/'retired-profile')
        original.mkdir(mode=0o700)
        (original/'Preferences').write_text((self.root/'retired-profile/Preferences').read_text())
        with patch.object(plugin,'gui_launch') as launch:
            with self.assertRaisesRegex(RuntimeError,'binding_unavailable'):
                provider._launch_seed('file:///fixture/seed.html')
            launch.assert_not_called()

    def test_root_replaced_during_metadata_read_is_rejected(self):
        import profile_probe
        read=profile_probe._read
        def changing(directory,name):
            value=read(directory,name)
            if name=='Preferences':
                self.root.rename(self.root.parent/'retired-root')
                self.root.mkdir(mode=0o700)
            return value
        with patch.object(profile_probe,'_read',side_effect=changing),self.assertRaisesRegex(RuntimeError,'binding_unavailable'):
            self.provider().require_ready()

    def test_cleanup_worker_uses_selected_profile_without_registered_execution(self):
        from unittest.mock import Mock
        provider=self.provider()
        provider._worker=Mock(return_value={'success':False,'error':'synthetic cleanup refusal'})
        entry={'endpoint':'ws://127.0.0.1:1/devtools/browser/fixture',
               'state':{'owned':{'our-seed':1},'context':'fixture','verified':False}}
        provider._cleanup_entry(entry)
        self.assertEqual(provider._worker.call_args.args[0]['profile'],str(provider.profile_path))
