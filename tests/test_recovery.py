"""Bounded recovery never promotes a research-looking mutation batch to a retry."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from recovery import classify_script,recovery_plan


class RecoveryTests(unittest.TestCase):
    def plan(self,source,**kwargs):
        result=kwargs.pop('result',{'success':False,'error':'browser_exec_timeout: uncertain','uncertain':True})
        settings={'remaining_s':20,'session_verified':True,'transport_usable':True}
        settings.update(kwargs)
        return recovery_plan(source,result,**settings)

    def test_pure_observations_allow_one_bounded_retry_with_positive_evidence(self):
        source="page=read_page()\nprint(page['text'])"
        self.assertEqual(classify_script(source)['kind'],'read_only')
        plan=self.plan(source)
        self.assertEqual(plan['action'],'retry_read')
        self.assertLessEqual(plan['retry_timeout_s'],10)
        self.assertFalse(plan['replay_actions'])
        self.assertEqual(self.plan(source,attempts=1)['action'],'fresh_session')
        for evidence in ({'remaining_s':4},{'session_verified':False},{'transport_usable':False}):
            with self.subTest(evidence=evidence):self.assertNotEqual(self.plan(source,**evidence)['action'],'retry_read')

    def test_navigation_and_hidden_mutations_are_never_retried(self):
        for source in ("goto_url('https://example.test/logout')\nprint(read_page())",
                       "click_element('button')\nprint(read_page())",
                       "if False:\n type_text('x')\nprint(read_page())",
                       "print(read_page())\nfinish_browser()",
                       "print(capture_screenshot())",
                       "print(drain_events())"):
            with self.subTest(source=source):
                self.assertEqual(classify_script(source)['kind'],'actions')
                self.assertEqual(self.plan(source)['action'],'fresh_session')

    def test_known_setup_network_and_lost_transport_errors_are_not_replayed(self):
        for error,expected in [('consent_deadline','operator_attention'),
                               ('account_binding_mismatch','operator_attention'),
                               ('observer_lost: connection closed','fresh_session'),
                               ('browser_navigation_failed: net::ERR_FAILED','continue_current_session')]:
            result={'success':False,'error':error,'uncertain':error.startswith('observer_lost')}
            with self.subTest(error=error):self.assertEqual(self.plan('print(read_page())',result=result)['action'],expected)

    def test_overlong_or_dynamic_wait_batch_is_not_retried(self):
        for source in ("wait(30)\nprint(read_page())",
                       "wait(5)\nprint(read_page())",
                       "n=1\nwait(n)\nprint(read_page())",
                       "for x in range(2):\n wait(1)\nprint(read_page())"):
            with self.subTest(source=source):self.assertNotEqual(self.plan(source,remaining_s=5)['action'],'retry_read')

    def test_invalid_script_and_pure_data_are_not_read_retries(self):
        self.assertEqual(self.plan('import os')['action'],'correct_script')
        self.assertEqual(classify_script('print(1)')['kind'],'data_only')
        self.assertNotEqual(self.plan('print(1)')['action'],'retry_read')

    def test_unclassified_error_does_not_authorize_retry(self):
        result={'success':False,'error':'unexpected custom timeout','error_type':'RuntimeError'}
        self.assertEqual(self.plan('print(read_page())',result=result)['action'],'continue_current_session')


if __name__=='__main__':unittest.main()
