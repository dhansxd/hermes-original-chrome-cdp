import errno
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import startup


class GuiLaunchTests(unittest.TestCase):
    def setUp(self):
        self.data = Path('/fixture')
        self.destination = (501, 77)
        self.process = Mock(pid=42)
        self.process.name.return_value = 'Google Chrome'
        self.process.as_dict.return_value = {
            'name': 'Google Chrome', 'exe': '/fixture/Chrome',
            'cmdline': ['--user-data-dir=/fixture'], 'create_time': 1,
        }
        for target, value in [('startup.gui_identity', self.destination),
                              ('startup.chrome_executable', True)]:
            fixture = patch(target, return_value=value)
            fixture.start()
            self.addCleanup(fixture.stop)

    def test_running_chrome_receives_arguments_without_another_application_launch(self):
        with patch('psutil.process_iter', return_value=[self.process]), \
                patch('startup.notify_running_chrome') as notify, \
                patch('startup.subprocess.run') as launch:
            startup.gui_launch(self.data, 'file:///seed.html', profile_directory='Profile 2')
        launch.assert_not_called()
        notify.assert_called_once()
        data, identity, arguments = notify.call_args.args
        self.assertEqual(data, self.data)
        self.assertEqual(identity, (42, 1))
        self.assertIn('--profile-directory=Profile 2', arguments)
        self.assertEqual(arguments[-2:], ['--new-window', 'file:///seed.html'])

    def test_stopped_chrome_uses_launchservices_without_a_forced_new_instance(self):
        with patch('psutil.process_iter', side_effect=[[], [self.process]]), \
                patch('startup.notify_running_chrome') as notify, \
                patch('startup.subprocess.run') as launch:
            startup.gui_launch(self.data, 'file:///seed.html', profile_directory='Profile 2')
        notify.assert_not_called()
        launch.assert_called_once()
        arguments = launch.call_args.args[0]
        self.assertEqual(arguments[:4], ['/usr/bin/open', '-g', '-a', str(startup.CHROME)])
        self.assertNotIn('-n', arguments)
        self.assertIn('--profile-directory=Profile 2', arguments)

    def test_failed_notification_is_not_replayed_through_a_new_chrome_process(self):
        with patch('psutil.process_iter', return_value=[self.process]), \
                patch('startup.notify_running_chrome',
                      side_effect=RuntimeError('unconfirmed request')) as notify, \
                patch('startup.subprocess.run') as launch:
            with self.assertRaisesRegex(RuntimeError, 'unconfirmed request'):
                startup.gui_launch(self.data, 'file:///seed.html')
        notify.assert_called_once()
        launch.assert_not_called()

    def test_ambiguous_running_processes_are_rejected_before_notifying(self):
        with patch('psutil.process_iter', return_value=[self.process, self.process]), \
                patch('startup.notify_running_chrome') as notify, \
                patch('startup.subprocess.run') as launch:
            with self.assertRaisesRegex(RuntimeError, 'destination ambiguous'):
                startup.gui_launch(self.data, 'file:///seed.html')
        notify.assert_not_called()
        launch.assert_not_called()


class SingletonNotificationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        remote = self.data / 'runtime'
        remote.mkdir()
        self.address = remote / 'SingletonSocket'
        self.address.touch()
        (self.data / 'SingletonSocket').symlink_to(self.address)
        for parent in (self.data, remote):
            (parent / 'SingletonCookie').symlink_to('fixture-nonce')
        self.arguments = ['/fixture/Chrome', '--profile-directory=Profile 2',
                          '--new-window', 'file:///seed.html']
        self.channel = Mock()
        self.channel.getsockopt.return_value = 42
        self.channel.recv.side_effect = [b'A', b'CK', b'']
        factory = patch('socket.socket')
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        self.factory.return_value.__enter__.return_value = self.channel
        alive = patch('startup.process_alive', return_value=True)
        self.alive = alive.start()
        self.addCleanup(alive.stop)

    def notify(self):
        startup.notify_running_chrome(self.data, (42, 1), self.arguments)

    def replace_nonce(self, parent):
        (parent / 'SingletonCookie').unlink()
        (parent / 'SingletonCookie').symlink_to('replacement-nonce')

    def test_fragmented_ack_and_exact_arguments_use_a_short_private_socket_alias(self):
        aliases = []
        def connected(value):
            alias = Path(value)
            self.assertEqual(alias.resolve(), self.address.resolve())
            self.assertLess(len(str(alias).encode()), 104)
            self.assertEqual(alias.parent.stat().st_mode & 0o777, 0o700)
            aliases.append(alias)
        self.channel.connect.side_effect = connected
        self.notify()
        expected = ['START', str(self.data), *self.arguments]
        self.assertEqual(self.channel.sendall.call_args.args[0].split(b'\0'),
                         [part.encode() for part in expected])
        self.channel.getsockopt.assert_called_once_with(0, 0x002)
        self.alive.assert_called_once_with({'pid': 42, 'started': 1})
        self.channel.shutdown.assert_called_once_with(socket.SHUT_WR)
        self.assertFalse(aliases[0].parent.exists())

    def test_wrong_nonce_is_rejected_before_connecting(self):
        self.replace_nonce(self.address.parent)
        with self.assertRaisesRegex(RuntimeError, 'identity is unavailable'):
            self.notify()
        self.channel.connect.assert_not_called()
        self.channel.sendall.assert_not_called()

    def test_long_chrome_socket_paths_use_the_short_private_alias(self):
        parent = self.data / ('long-chrome-runtime-' + 'x' * 100)
        parent.mkdir()
        self.address = parent / 'SingletonSocket'
        self.address.touch()
        (parent / 'SingletonCookie').symlink_to('fixture-nonce')
        (self.data / 'SingletonSocket').unlink()
        (self.data / 'SingletonSocket').symlink_to(self.address)
        self.assertGreater(len(str(self.address).encode()), 104)
        def connected(value):
            self.assertLess(len(value.encode()), 104)
            self.assertEqual(Path(value).resolve(), self.address.resolve())
        self.channel.connect.side_effect = connected
        self.notify()
        self.channel.sendall.assert_called_once()

    def test_connected_peer_must_be_the_verified_browser_pid(self):
        self.channel.getsockopt.return_value = 99
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            self.notify()
        self.channel.sendall.assert_not_called()

    def test_reused_browser_pid_is_rejected_before_sending(self):
        self.alive.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            self.notify()
        self.channel.sendall.assert_not_called()

    def test_remote_nonce_replacement_during_connect_is_rejected(self):
        self.channel.connect.side_effect = lambda value: self.replace_nonce(self.address.parent)
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            self.notify()
        self.channel.sendall.assert_not_called()

    def test_profile_nonce_replacement_during_connect_is_rejected(self):
        self.channel.connect.side_effect = lambda value: self.replace_nonce(self.data)
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            self.notify()
        self.channel.sendall.assert_not_called()

    def test_missing_ack_has_one_send_and_no_relaunch(self):
        self.channel.recv.side_effect = socket.timeout('fixture timeout')
        with patch('startup.subprocess.run') as launch:
            with self.assertRaises(socket.timeout):
                self.notify()
        self.channel.sendall.assert_called_once()
        self.factory.assert_called_once()
        launch.assert_not_called()

    def test_early_peer_close_still_accepts_the_buffered_ack(self):
        self.channel.shutdown.side_effect = OSError(errno.ENOTCONN, 'fixture peer closed')
        self.notify()
        self.channel.sendall.assert_called_once()

    def test_other_shutdown_errors_propagate(self):
        self.channel.shutdown.side_effect = OSError(errno.EBADF, 'fixture invalid socket')
        with self.assertRaises(OSError) as result:
            self.notify()
        self.assertEqual(result.exception.errno, errno.EBADF)
        self.channel.recv.assert_not_called()

    def test_shutdown_response_is_reported_without_replaying_the_request(self):
        self.channel.recv.side_effect = [b'SHUTDOWN']
        with self.assertRaisesRegex(RuntimeError, 'not acknowledged'):
            self.notify()
        self.channel.sendall.assert_called_once()

    def test_socket_alias_is_removed_when_connect_fails(self):
        aliases = []
        def failed(value):
            aliases.append(Path(value))
            raise ConnectionRefusedError('fixture refusal')
        self.channel.connect.side_effect = failed
        with self.assertRaises(ConnectionRefusedError):
            self.notify()
        self.assertFalse(aliases[0].parent.exists())
        self.channel.sendall.assert_not_called()


if __name__ == '__main__':
    unittest.main()
