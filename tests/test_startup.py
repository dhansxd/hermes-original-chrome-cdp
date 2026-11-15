import ctypes
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import startup
from consent import ConsentError
from test_consent_diagnostics import fake_clock


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


class SeedCleanupTests(unittest.TestCase):
    def setUp(self):
        self.identity={'pid':42,'started':1,'endpoint':'ws://fixture'}
        self.seed='file:///fixture/seed.html'
        self.title='Hermes browser session fixture'
        self.data={
            1:{'AXRole':'AXWindow','AXSubrole':'AXStandardWindow','AXDocument':self.seed},
            2:{'AXRole':'AXTabGroup'},
            3:{'AXRole':'AXRadioButton','AXSubrole':'AXTabButton','AXTitle':self.title},
            4:{'AXRole':'AXButton'},
            6:{'AXRole':'AXRadioButton','AXSubrole':'AXTabButton','AXTitle':'Manual tab'},
            7:{'AXRole':'AXButton'},
        }
        self.children={1:[2],2:[3,6],3:[4],6:[7]}
        parents={2:1,3:2,4:3,6:2,7:6}
        def within(node,ancestor):
            while node in parents:
                node=parents[node]
                if node==ancestor:return True
            return False
        ax=self.ax=Mock()
        ax.refs=[];ax.c=ctypes;ax.trusted.return_value=True
        def pid(node,out):
            out._obj.value=42
            return 0
        ax.ax.AXUIElementGetPid.side_effect=pid
        ax.ax.AXUIElementCreateApplication.return_value=0
        ax.attr.side_effect=lambda node,key:[1] if node==0 and key=='AXWindows' else None
        ax.cf.CFArrayGetCount.side_effect=len
        ax.cf.CFArrayGetValueAtIndex.side_effect=lambda values,index:values[index]
        ax.text.side_effect=lambda node,key:self.data.get(node,{}).get(key,'')
        ax.children.side_effect=lambda node:list(self.children.get(node,[]))
        ax.within.side_effect=within
        ax.string.side_effect=lambda value:value
        def press(node,action):
            self.children[2].remove(3)
            return 0
        ax.ax.AXUIElementPerformAction.side_effect=press
        self.ax_patch=patch('consent.AX',return_value=ax)
        self.ax_patch.start();self.addCleanup(self.ax_patch.stop)
        self.identity_patch=patch('startup.endpoint_identity',return_value=self.identity)
        self.endpoint=self.identity_patch.start();self.addCleanup(self.identity_patch.stop)

    def close(self):
        return startup.close_seed_tab(Path('/fixture'),self.identity,self.seed,self.title)

    def test_failed_attach_closes_exact_seed_tab_and_preserves_manual_tab(self):
        self.assertTrue(self.close())
        self.ax.ax.AXUIElementPerformAction.assert_called_once_with(4,'AXPress')
        self.assertEqual(self.children[2],[6])
        self.ax.clear.assert_called_once()

    def test_absent_seed_is_confirmed_without_an_action(self):
        self.children[2]=[6]
        self.assertTrue(self.close())
        self.ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_unavailable_tab_tree_is_unconfirmed(self):
        self.children[1]=[]
        self.assertFalse(self.close())
        self.ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_background_seed_does_not_close_the_active_manual_tab(self):
        self.data[1]['AXDocument']='https://fixture.invalid/manual'
        self.assertFalse(self.close())
        self.ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_ambiguous_seed_title_is_unconfirmed(self):
        self.data[6]['AXTitle']=self.title
        self.assertFalse(self.close())
        self.ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_replaced_chrome_before_action_is_unconfirmed(self):
        self.endpoint.side_effect=[self.identity,dict(self.identity,started=2)]
        self.assertFalse(self.close())
        self.ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_foreign_accessibility_process_is_unconfirmed(self):
        self.ax.ax.AXUIElementGetPid.side_effect=lambda node,out:0
        self.assertFalse(self.close())
        self.ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_unknown_press_is_observed_without_repeating_the_action(self):
        self.ax.ax.AXUIElementPerformAction.side_effect=None
        self.ax.ax.AXUIElementPerformAction.return_value=-25202
        with fake_clock():
            self.assertFalse(self.close())
        self.ax.ax.AXUIElementPerformAction.assert_called_once_with(4,'AXPress')

    def test_transient_post_close_window_read_is_observed_again(self):
        original = self.ax.attr.side_effect
        reads = 0
        def read(node, key):
            nonlocal reads
            if node == 0 and key == 'AXWindows':
                reads += 1
                if reads == 2:
                    raise ConsentError('consent_ax_read:-25204')
            return original(node, key)
        self.ax.attr.side_effect = read
        self.assertTrue(self.close())
        self.assertGreaterEqual(reads, 3)
        self.ax.ax.AXUIElementPerformAction.assert_called_once_with(4, 'AXPress')

    def test_other_post_close_read_errors_remain_unconfirmed(self):
        original = self.ax.attr.side_effect
        def read(node, key):
            if node == 0 and key == 'AXWindows' and 3 not in self.children[2]:
                raise ConsentError('consent_ax_read:-25201')
            return original(node, key)
        self.ax.attr.side_effect = read
        self.assertFalse(self.close())
        self.ax.ax.AXUIElementPerformAction.assert_called_once_with(4, 'AXPress')


if __name__ == '__main__':
    unittest.main()
