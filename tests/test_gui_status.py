"""Operator GUI-state fixtures, without live processes, AX, or Chrome calls."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gui_status import chrome_gui_snapshot


class GuiStatusTests(unittest.TestCase):
    def process(self,pid=42,root='/fixture',exe='/fixture/Chrome'):
        process=Mock(pid=pid);process.name.return_value='Google Chrome'
        process.as_dict.return_value={'exe':exe,'cmdline':['--user-data-dir='+root],'create_time':10}
        process.create_time.return_value=10;process.exe.return_value=exe
        return process

    def ax(self,rows):
        ax=Mock();ax.refs=[];ax.trusted.return_value=True
        ax.ax.AXUIElementCreateApplication.return_value='app';ax.attr.return_value='windows'
        ax.cf.CFArrayGetCount.return_value=len(rows)
        ax.cf.CFArrayGetValueAtIndex.side_effect=lambda array,index:index
        ax.text.side_effect=lambda index,key:rows[index][0 if key=='AXSubrole' else 1]
        return ax

    def snapshot(self,processes,ax=None,*,fresh=None):
        with patch('gui_status.psutil.process_iter',return_value=processes),\
             patch('gui_status.psutil.Process',return_value=fresh or (processes[0] if processes else Mock())),\
             patch('gui_status.AX',return_value=ax) as native:
            result=chrome_gui_snapshot('/fixture',lambda exe:exe=='/fixture/Chrome')
        return result,native

    def test_stopped_requires_process_inventory_and_does_not_request_accessibility(self):
        result,native=self.snapshot([])
        self.assertFalse(result['running']);self.assertEqual(result['status'],'stopped')
        self.assertEqual((result['window_count'],result['document_window_count']),(0,0));native.assert_not_called()

    def test_running_without_windows_requires_positive_empty_ax_array(self):
        ax=self.ax([]);result,_=self.snapshot([self.process()],ax)
        self.assertTrue(result['running']);self.assertEqual(result['status'],'running_no_windows')
        self.assertEqual((result['window_count'],result['document_window_count']),(0,0))
        ax.clear.assert_called_once();ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_standard_and_document_counts_do_not_expose_titles_or_urls(self):
        ax=self.ax([('AXStandardWindow','https://private.example/account'),
                    ('AXStandardWindow',''),('AXFloatingWindow','https://private.example/popup')])
        result,_=self.snapshot([self.process()],ax)
        self.assertEqual(result['status'],'running_with_windows')
        self.assertEqual((result['window_count'],result['document_window_count']),(2,1))
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('https',json.dumps(result))
        ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_untrusted_missing_inventory_or_ax_error_never_implies_zero_windows(self):
        for condition in ('untrusted','missing','error'):
            with self.subTest(condition=condition):
                ax=self.ax([])
                if condition=='untrusted':ax.trusted.return_value=False
                elif condition=='missing':ax.attr.return_value=None
                else:ax.attr.side_effect=RuntimeError('fixture AX unavailable')
                result,_=self.snapshot([self.process()],ax)
                self.assertEqual(result['status'],'unknown');self.assertTrue(result['running'])
                self.assertIsNone(result['window_count']);self.assertIsNone(result['document_window_count'])
                ax.clear.assert_called_once();ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_multiple_matching_processes_do_not_choose_arbitrary_window_host(self):
        result,native=self.snapshot([self.process(),self.process(43)])
        self.assertEqual(result['status'],'unknown');self.assertEqual(result['pids'],[42,43])
        self.assertIsNone(result['window_count']);native.assert_not_called()

    def test_foreign_root_is_ignored_but_unverified_matching_executable_is_unknown(self):
        result,native=self.snapshot([self.process(root='/other-profile')])
        self.assertEqual(result['status'],'stopped');native.assert_not_called()
        result,native=self.snapshot([self.process(exe='/untrusted/chrome')])
        self.assertEqual(result['status'],'unknown');self.assertIsNone(result['running'])
        self.assertIsNone(result['window_count']);native.assert_not_called()

    def test_process_generation_changed_during_inventory_keeps_counts_unknown(self):
        fresh=self.process();fresh.create_time.return_value=20
        result,_=self.snapshot([self.process()],self.ax([]),fresh=fresh)
        self.assertEqual(result['status'],'unknown');self.assertEqual(result['reason'],'chrome_generation_changed')
        self.assertIsNone(result['window_count'])

    def test_unreadable_candidate_is_not_reported_stopped(self):
        import psutil
        process=self.process();process.as_dict.side_effect=psutil.AccessDenied(42)
        result,native=self.snapshot([process])
        self.assertEqual(result['status'],'unknown');self.assertIsNone(result['window_count']);native.assert_not_called()


if __name__=='__main__':unittest.main()
