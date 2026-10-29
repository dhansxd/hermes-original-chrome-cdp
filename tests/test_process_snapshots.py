"""Process.info is shared mutable cache, not an invocation-local snapshot."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path.home() / '.hermes/hermes-agent')]
import hermes_bootstrap
import plugin
import consent


class ProcessSnapshotTests(unittest.TestCase):
    def test_consent_scan_does_not_read_replaced_shared_info(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / 'Chrome.app/Contents/MacOS/Google Chrome'
            exe.parent.mkdir(parents=True)
            (exe.parents[1] / 'Info.plist').write_bytes(b'fixture')
            snapshot = {'pid': 42, 'exe': str(exe), 'create_time': 10,
                        'cmdline': ['--user-data-dir=' + directory]}
            proc = Mock(pid=42, info={'exe': str(exe), 'cmdline': snapshot['cmdline']})
            proc.as_dict.return_value = snapshot
            backend = consent.MacConsent(directory, 5000)
            backend.ax = Mock()
            backend.ax.trusted.return_value = True
            backend.ax.sheets.return_value = []
            with patch('psutil.process_iter', return_value=[proc]), \
                    patch('consent.plistlib.loads', return_value={}), \
                    patch('consent.host_identity', return_value='main'), \
                    patch('consent.subprocess.run', return_value=NS(returncode=0)):
                error = None
                try:
                    backend.scan()
                except Exception as exc:
                    error = str(exc)
            self.assertIsNone(error, 'a peer replacing cached Process.info must not break preflight')
            self.assertEqual(backend.processes[42]['started'], 10)

    def test_gui_launch_uses_its_own_snapshot_not_a_peer_info_dict(self):
        proc = Mock(pid=42, info={})
        proc.as_dict.return_value = {'name': 'Google Chrome', 'exe': '/fixture/Chrome',
                                     'cmdline': ['--user-data-dir=/fixture'], 'create_time': 10}
        with patch('psutil.process_iter', return_value=[proc]), \
                patch('plugin.gui_identity', return_value=(501, 7)), \
                patch('plugin.chrome_executable', return_value=True), \
                patch('plugin.subprocess.run', return_value=NS(returncode=0)) as run:
            error = None
            try:
                plugin.gui_launch(Path('/fixture'), 'file:///fixture/seed.html')
            except Exception as exc:
                error = str(exc)
        self.assertIsNone(error, 'GUI admission must not depend on another scan\'s attr list')
        run.assert_called_once()

    def test_endpoint_uses_complete_local_metadata_before_returning_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / 'DevToolsActivePort').write_text('12345\n/devtools/browser/current\n')
            snapshot = {'name': 'Google Chrome', 'exe': '/fixture/Chrome',
                        'cmdline': ['--user-data-dir=' + directory], 'create_time': 1}
            proc = Mock(pid=42, info={k: v for k, v in snapshot.items() if k != 'create_time'})
            proc.as_dict.return_value = snapshot
            proc.create_time.return_value = 1
            proc.net_connections.return_value = [NS(status='LISTEN', laddr=NS(port=12345, ip='127.0.0.1'))]
            provider = plugin.ChromeProvider(data=data, workspace=data / 'work')
            error = None
            endpoint = None
            with patch('psutil.process_iter', return_value=[proc]), \
                    patch('plugin.gui_launch'), patch('plugin.seed_window_ready', return_value=True), patch('plugin.chrome_executable', return_value=True):
                try:
                    endpoint = provider.endpoint(entry={})
                except Exception as exc:
                    error = str(exc)
            self.assertIsNone(error, 'endpoint metadata was replaced by a concurrent scan')
            self.assertEqual(endpoint, 'ws://127.0.0.1:12345/devtools/browser/current')

    def test_cleanup_process_scan_uses_local_metadata(self):
        proc = Mock(pid=42, info={})
        proc.as_dict.return_value = {'name': 'Google Chrome', 'exe': '/fixture/Chrome',
                                     'cmdline': ['--user-data-dir=/fixture']}
        provider = plugin.ChromeProvider(data='/fixture')
        with patch('psutil.process_iter', return_value=[proc]), \
                patch('plugin.chrome_executable', return_value=True):
            error = None
            found = []
            try:
                found = provider._chrome_processes()
            except Exception as exc:
                error = str(exc)
        self.assertIsNone(error, 'cleanup inventory must not use another scan\'s info dict')
        self.assertEqual(found, [proc])

    def test_native_dialog_host_uses_local_process_metadata(self):
        from native_dialog import NativeDialogs
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / 'DevToolsActivePort').write_text('12345\n/devtools/browser/current\n')
            proc = Mock(pid=42, info={})
            proc.as_dict.return_value = {'name': 'Google Chrome', 'cmdline': ['--user-data-dir=' + directory]}
            proc.exe.return_value = '/fixture/Chrome'
            proc.create_time.return_value = 10
            proc.net_connections.return_value = [NS(status='LISTEN', laddr=NS(port=12345))]
            helper = NativeDialogs(data, 'ws://127.0.0.1:12345/devtools/browser/current')
            error = None
            with patch('psutil.process_iter', return_value=[proc]), \
                    patch('psutil.Process', return_value=proc), \
                    patch('plugin.chrome_executable', return_value=True), patch('native_dialog.NativeAX'):
                try:
                    helper._host()
                except Exception as exc:
                    error = str(exc)
            self.assertIsNone(error, 'native dialog host must not read another caller\'s info dict')
            self.assertEqual(helper.process, (42, 10, '/fixture/Chrome'))


if __name__ == '__main__':
    unittest.main()
