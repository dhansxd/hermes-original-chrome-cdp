"""Model egress preserves browser work, not transport/configuration internals."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from public_result import model_result


class PublicResultTests(unittest.TestCase):
    def test_output_keeps_stdout_and_preserves_private_input_unchanged(self):
        result={'success':True,'stdout':'Page says: Chrome /workspace/example\n雪',
            'backend':'private-backend','workspace':'/private/workspace',
            'limitations':['private implementation'],'state':{'owned':{'private-target':7}},
            'automatic_cleanup':'private policy','browser_cleanup':[{'task_id':'private-task'}],
            'metadata':{'endpoint':'ws://private-endpoint'},'fallback_used':False}
        before=copy.deepcopy(result)
        public=model_result(result)
        self.assertEqual(public,{'success':True,'stdout':result['stdout'],
                                 'fallback_used':False,'action_replayed':False})
        self.assertEqual(result,before)

    def test_uncertain_failure_is_explicit_and_never_invites_action_replay(self):
        public=model_result({'success':False,'uncertain':True,
            'error':'browser_exec_timeout: private CDP details','stdout':'partial page output'})
        self.assertFalse(public['success']);self.assertTrue(public['uncertain'])
        self.assertFalse(public['action_replayed'])
        self.assertEqual(public['error_code'],'browser_outcome_unknown')
        self.assertIn('Do not repeat',public['error'])
        self.assertNotIn('CDP',str(public));self.assertEqual(public['stdout'],'partial page output')

    def test_setup_errors_are_generic_but_operator_result_is_not_modified(self):
        for code in ('consent_press_timeout','safe_GUI_launch_unavailable',
                     'accessibility_permission_required','account_binding_mismatch',
                     'browser_backend_unsupported','plugin_capability_required'):
            result={'success':False,'error':code+': private operator detail','uncertain':True}
            before=copy.deepcopy(result)
            with self.subTest(code=code):
                public=model_result(result)
                self.assertEqual(public['error_code'],'browser_unavailable')
                self.assertNotIn(code,json.dumps(public))
                self.assertEqual(result,before)
                self.assertTrue(public['uncertain'])

    def test_page_dialog_and_argument_errors_remain_actionable(self):
        for error,expected in [('dialog_pending: Runtime.evaluate sent once','dialog_pending'),
                              ('JavaScript evaluation failed: element_obscured; private-expression','browser_element_unavailable'),
                              ('browser_url_not_allowed: private URL','browser_url_not_allowed')]:
            public=model_result({'success':False,'error':error})
            self.assertEqual(public['error_code'],expected)
            self.assertNotIn('private',str(public))

    def test_cleanup_notice_hides_ids_and_payload_without_hiding_failure(self):
        reports=[{'success':False,'task_id':'private-task','results':[{'error':'private-transport'}]}]
        before=copy.deepcopy(reports)
        public=model_result({'success':True,'stdout':'page task done'},reports)
        self.assertTrue(public['success']);self.assertFalse(public['cleanup_complete'])
        self.assertNotIn('private',json.dumps(public))
        self.assertEqual(reports,before)

    def test_image_bytes_survive_text_scrub_and_private_text_is_replaced(self):
        image={'type':'image_url','image_url':{'url':'data:image/png;base64,secret-image-bytes'}}
        result={'success':True,'stdout':'visible secret','_multimodal':True,
            'text_summary':'private backend details','content':[{'type':'text','text':'private path'},image],
            'meta':{'workspace':'/private'}}
        before=copy.deepcopy(result)
        public=model_result(result,scrub=lambda text:text.replace('secret','[redacted]'))
        self.assertTrue(public['_multimodal'])
        self.assertEqual(public['content'][1],image)
        self.assertEqual(public['stdout'],'visible [redacted]')
        self.assertNotIn('private',public['text_summary'])
        self.assertNotIn('meta',public)
        self.assertEqual(result,before)

    def test_fresh_session_recovery_continues_research_without_claiming_original_success(self):
        public=model_result({'success':False,'uncertain':True,'stdout':'first finding\n',
            'error':'browser_exec_timeout','recovery':{'status':'fresh_session_ready',
                'cleanup_complete':True,'partial_output_preserved':True,'session':'research',
                'read_retry_count':0,'private_state':{'endpoint':'ws://private'}}})
        self.assertFalse(public['success']);self.assertTrue(public['uncertain'])
        self.assertEqual(public['stdout'],'first finding\n')
        self.assertEqual(public['recovery']['status'],'fresh_session_ready')
        self.assertIn('Continue research',public['recovery']['next_action'])
        self.assertIn('same session name',public['recovery']['next_action'])
        self.assertNotIn('private',json.dumps(public))

    def test_unconfirmed_cleanup_cannot_be_advertised_as_fresh_session_ready(self):
        public=model_result({'success':False,'recovery':{'status':'fresh_session_ready',
            'cleanup_complete':False,'session':'../private-path','read_retry_count':99}})
        self.assertEqual(public['recovery']['status'],'fresh_session_required')
        self.assertNotIn('session',public['recovery'])
        self.assertNotIn('read_retry_count',public['recovery'])

    def test_successful_read_retry_still_reports_only_bounded_observation_recovery(self):
        public=model_result({'success':True,'stdout':'recovered finding','action_replayed':False,
            'recovery':{'status':'read_retry_succeeded','read_retry_count':1}})
        self.assertTrue(public['success']);self.assertFalse(public['action_replayed'])
        self.assertEqual(public['recovery']['read_retry_count'],1)
        self.assertIn('read-only',public['recovery']['next_action'])


if __name__=='__main__':unittest.main()
