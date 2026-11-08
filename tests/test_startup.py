import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import startup


class StartupTests(unittest.TestCase):
    def chrome(self, data):
        proc = Mock(pid=42)
        proc.name.return_value = 'Google Chrome'
        proc.as_dict.return_value = {'name': 'Google Chrome', 'exe': '/fixture/Chrome',
            'cmdline': ['--user-data-dir=' + str(data)], 'create_time': 1}
        proc.create_time.return_value = 1
        proc.net_connections.return_value = [Mock(status='LISTEN', laddr=Mock(port=12345, ip='127.0.0.1'))]
        return proc

    def test_protected_unrelated_process_is_never_queried_for_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / 'DevToolsActivePort').write_text('12345\n/devtools/browser/current\n')
            unrelated = Mock()
            unrelated.name.return_value = 'kernel_task'
            unrelated.as_dict.side_effect = PermissionError('protected process')
            with patch('psutil.process_iter', return_value=[unrelated, self.chrome(data)]), \
                    patch('startup.chrome_executable', return_value=True):
                self.assertEqual(startup.endpoint_identity(data)['pid'], 42)
            unrelated.as_dict.assert_not_called()

    def test_unreadable_chrome_arguments_are_not_default_profile_proof(self):
        proc = self.chrome(Path('/fixture'))
        proc.as_dict.return_value['cmdline'] = None
        self.assertIsNone(startup._chrome_process_info(proc))
        with self.assertRaisesRegex(RuntimeError, 'identity_unavailable'):
            startup._chrome_process_info(proc, strict_named=True)

    def test_wrapped_permission_error_is_handled_but_other_system_errors_propagate(self):
        proc = self.chrome(Path('/fixture'))
        error = SystemError('psutil')
        error.__cause__ = PermissionError('denied')
        proc.as_dict.side_effect = error
        self.assertIsNone(startup._chrome_process_info(proc))
        proc.as_dict.side_effect = SystemError('different bug')
        with self.assertRaises(SystemError):
            startup._chrome_process_info(proc)

    def test_windowless_chrome_waits_for_exact_new_window_without_relaunch(self):
        identity = {'pid': 42, 'started': 1, 'endpoint': 'ws://127.0.0.1:12345/devtools/browser/current'}
        with patch('startup.gui_launch') as launch, patch('startup.endpoint_identity', return_value=identity), \
                patch('startup.seed_window_ready', side_effect=[False, True]), patch('startup.time.sleep'):
            self.assertEqual(startup.launch('/fixture', 'Profile 2', 'file:///fixture.html'), identity['endpoint'])
            launch.assert_called_once_with(Path('/fixture'), 'file:///fixture.html', profile_directory='Profile 2')


if __name__ == '__main__':
    unittest.main()
