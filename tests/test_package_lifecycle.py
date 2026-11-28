import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import package_lifecycle


class PackageLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        source = Path(temporary.name)
        self.source = source / 'site_apps'
        # A historical fixture remains fixed when the installed site's UI code changes later.
        for app in ('flow', 'gemini'):
            package = self.source / app
            package.mkdir(parents=True)
            (package / 'app.py').write_bytes(b'old package')
        digest = '325af01ccda316cdbe4e90eae1c95a2d2ca4518def31bc7bd3ba2f1eb09f655e'
        (source / 'legacy-package-digests.json').write_text(json.dumps(
            {app: {digest: 'fixture revision'} for app in ('flow', 'gemini')}))
        location = patch.object(package_lifecycle, '__file__', str(source / 'package_lifecycle.py'))
        location.start()
        self.addCleanup(location.stop)

    def test_upgrade_removes_only_recognized_legacy_copies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'browser-apps'
            shutil.copytree(self.source, root, ignore=shutil.ignore_patterns('__pycache__'))
            (root / '.install.lock').touch()
            (root / 'gemini' / 'app.py').write_text('# custom source')
            external = root / 'my-site'
            external.mkdir()
            package_lifecycle.retire_legacy_packages(root)
            self.assertFalse((root / 'flow').exists())
            self.assertTrue(external.is_dir())
            self.assertEqual((root / 'gemini' / 'app.py').read_text(), '# custom source')
            package_lifecycle.retire_legacy_packages(root)
            self.assertTrue((root / 'gemini').is_dir())

    def test_migration_never_follows_a_link_or_touches_an_unseeded_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'browser-apps'
            root.mkdir()
            (root / 'gemini').symlink_to(self.source / 'gemini', target_is_directory=True)
            shutil.copytree(self.source / 'flow', root / 'flow', ignore=shutil.ignore_patterns('__pycache__'))
            package_lifecycle.retire_legacy_packages(root)
            self.assertTrue((root / 'flow').is_dir())
            (root / '.install.lock').touch()
            package_lifecycle.retire_legacy_packages(root)
            self.assertTrue((root / 'gemini').is_symlink())
            self.assertFalse((root / 'flow').exists())

    def test_retiring_last_seed_copy_removes_old_package_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'browser-apps'
            shutil.copytree(self.source, root, ignore=shutil.ignore_patterns('__pycache__'))
            (root / '.install.lock').touch()
            package_lifecycle.retire_legacy_packages(root)
            self.assertFalse(root.exists())

    def test_full_uninstall_purges_only_plugin_state_after_manager_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            data = home / 'plugin-data/agent-plugin-original-chrome-default-31c84a78'
            data.mkdir(parents=True)
            (data / 'learned-controls.sqlite3').touch()
            other = home / 'plugin-data/other'
            other.mkdir()
            install = home / 'plugins/original-chrome-default'
            install.mkdir(parents=True)

            def manager(*args, **kwargs):
                if 'remove' in args[0]:
                    install.rmdir()
                return subprocess.CompletedProcess(args, 0)
            with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'remove')):
                with self.assertRaises(subprocess.CalledProcessError):
                    package_lifecycle.remove_installation(['hermes'], home, home / 'browser-apps')
                self.assertTrue(data.is_dir())
            with patch('subprocess.run', side_effect=manager):
                package_lifecycle.remove_installation(['hermes'], home, home / 'browser-apps')
            self.assertFalse(data.exists())
            self.assertTrue(other.is_dir())

    def test_explicit_last_installation_cleanup_protects_another_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            account = Path(temporary)
            home = account / '.hermes'
            peer = home / 'profiles/other/plugins/original-chrome-default'
            peer.mkdir(parents=True)
            cache = account / '.cache/original-chrome-default'
            cache.mkdir(parents=True)
            with patch.object(Path, 'home', return_value=account), self.assertRaises(ValueError):
                package_lifecycle.remove_installation(['hermes'], home, home / 'browser-apps', last_installation=True)
            self.assertTrue(cache.is_dir())

    def test_migration_preserves_difference_between_old_disable_and_remove(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'browser-apps'
            shutil.copytree(self.source / 'gemini', root / 'gemini', ignore=shutil.ignore_patterns('__pycache__'))
            (root / '.install.lock').touch()
            settings = {'apps_disabled.gemini': True, 'apps_disabled.flow': True}
            package_lifecycle.retire_legacy_packages(root, settings.get, settings.__setitem__)
            self.assertEqual(settings, {'apps_disabled.gemini': True, 'apps_disabled.flow': 'removed'})
