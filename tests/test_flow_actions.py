"""Participating helper boundaries while a Flow job renders; no real Chrome."""
import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import flow_reservation as guard
from browser_actions import public_helpers


class FlowActions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name); self.profile = self.home/'Default'
        home = patch.object(guard.Path, 'home', return_value=self.home)
        home.start(); self.addCleanup(home.stop)
        real = guard.acquire_browser
        quick = patch('browser_actions.flow_reservation.acquire_browser',
                      side_effect=lambda profile, **kw: real(profile, timeout=0))
        quick.start(); self.addCleanup(quick.stop)

    def helpers(self, url, stack):
        browser = Mock()
        browser.info.return_value = {'url': url, 'targetId': 'owned'}
        browser.cdp.return_value = {}
        trusted = {name: Mock() for name in (
            'page_info', 'type_text', 'press_key', 'scroll', 'list_tabs', 'current_tab',
            'activate_tab', 'close_tab', 'ensure_real_tab', 'js', 'switch_tab', 'finish_browser')}
        trusted['finish_browser'].return_value = {'success': True}
        return browser, trusted, public_helpers(browser, trusted, self.home,
            profile=self.profile, lease_stack=stack)

    def test_destination_and_current_document_are_both_guarded(self):
        pairs = [('https://example.com', 'https://flow.google.com/'),
                 ('https://flow.google.com/project/x', 'https://example.com'),
                 ('https://example.com', 'https://accounts.google.com/Logout'),
                 ('https://accounts.google.com/', 'https://example.com')]
        with guard.acquire_job(self.profile, self.home/'job'):
            for source, destination in pairs:
                with self.subTest(source=source), contextlib.ExitStack() as stack:
                    browser, _, actions = self.helpers(source, stack)
                    with self.assertRaises(guard.FlowResourceBusy):
                        actions['goto_url'](destination)
                    browser.cdp.assert_not_called()

    def test_render_blocks_flow_inputs_but_other_site_work_continues(self):
        with guard.acquire_job(self.profile, self.home/'job') as job:
            job.update(spent=True, phase='rendering')
            with contextlib.ExitStack() as stack:
                browser, trusted, actions = self.helpers('https://flow.google.com/project/x', stack)
                with self.assertRaises(guard.FlowResourceBusy):
                    actions['fill_input']('#prompt', 'must not submit')
                trusted['js'].assert_not_called(); browser.cdp.assert_not_called()
            with contextlib.ExitStack() as stack:
                browser, trusted, actions = self.helpers('https://example.com', stack)
                actions['goto_url']('https://example.com/search')
                actions['page_info']()
                browser.cdp.assert_called_once(); trusted['page_info'].assert_called_once()
            job.update(resolved=True)

    def test_switch_activation_and_new_flow_tab_cannot_bypass_reservation(self):
        with guard.acquire_job(self.profile, self.home/'job'):
            for name, args in [('switch_tab', ('owned',)), ('activate_tab', ('owned',)),
                               ('new_tab', ('https://flow.google.com/',))]:
                with self.subTest(helper=name), contextlib.ExitStack() as stack:
                    browser, trusted, actions = self.helpers('https://flow.google.com/project/x', stack)
                    with self.assertRaises(guard.FlowResourceBusy):
                        actions[name](*args)
                    browser.create.assert_not_called()
                    trusted['activate_tab'].assert_not_called()
                    trusted['switch_tab'].assert_not_called()

    def test_owned_cleanup_and_blank_escape_tab_remain_available(self):
        with guard.acquire_job(self.profile, self.home/'job'):
            with contextlib.ExitStack() as stack:
                browser, trusted, actions = self.helpers('https://flow.google.com/project/x', stack)
                self.assertTrue(actions['finish_browser']()['cleanup_complete'])
                actions['close_tab']('owned')
                actions['new_tab']('https://example.com')
                trusted['finish_browser'].assert_called_once()
                trusted['close_tab'].assert_called_once()
                browser.create.assert_called_once_with('https://example.com')

    def test_parent_rejects_protected_command_before_wire_or_native_probe(self):
        from observer import ScopedObserver
        wire = Mock(events=[], dialogs={}, event_gaps={}, detached_sessions=set())
        state = {'current':'owned', 'context':'ctx', 'owned':{'owned':1}, 'verified':True}
        with patch('observer.Wire', return_value=wire), patch('observer.BoundBrowser') as browser:
            browser.return_value.info.return_value = {'url':'https://flow.google.com/project/x'}
            observer = ScopedObserver('fixture', self.profile)
            observer.sessions = {'owned':'sid'}
            observer._check_detached = Mock()
            with guard.acquire_job(self.profile, self.home/'job'):
                with self.assertRaises(guard.FlowResourceBusy):
                    observer.request({'method':'Runtime.evaluate', 'params':{
                        'expression':'document.title', 'returnByValue':True}, 'session':'sid'}, state)
            wire.assert_not_called()

    def test_parent_revalidates_account_after_worker_wait_before_wire(self):
        from observer import ScopedObserver
        wire=Mock(events=[],dialogs={},event_gaps={},detached_sessions=set())
        state={'current':'owned','context':'ctx','owned':{'owned':1},'verified':True}
        with patch('observer.Wire',return_value=wire),patch('observer.BoundBrowser') as browser:
            browser.return_value.info.return_value={'url':'https://flow.google.com/project/x'}
            observer=ScopedObserver('fixture',self.profile,account_key='a'*64,account_validator=lambda:'b'*64)
            observer.sessions={'owned':'sid'}; observer._check_detached=Mock()
            with self.assertRaisesRegex(RuntimeError,'account_binding_changed'):
                observer.request({'method':'Runtime.evaluate','params':{'expression':'document.title','returnByValue':True},'session':'sid'},state)
            wire.assert_not_called()

    def test_missing_production_key_refuses_protected_helper_before_navigation(self):
        original=self.home/'Library/Application Support/Google/Chrome/Default'
        with contextlib.ExitStack() as stack:
            browser,trusted,_=self.helpers('https://example.com',stack)
            actions=public_helpers(browser,trusted,self.home,profile=original,lease_stack=stack)
            with self.assertRaises(guard.FlowRecoveryRequired):actions['goto_url']('https://flow.google.com/')
            browser.cdp.assert_not_called()

    def test_site_busy_preserves_partial_findings_without_batch_retry(self):
        from recovery import recovery_plan
        from public_result import model_result
        result = {'success':False, 'error':'flow_resource_busy: private details',
                  'stdout':'earlier page finding', 'action_replayed':False}
        plan = recovery_plan("print(read_page())", result, session_verified=True,
                             transport_usable=True, remaining_s=60)
        self.assertEqual(plan['action'], 'site_in_use')
        self.assertFalse(plan['replay_actions'])
        result['recovery'] = {'status':plan['action']}
        public = model_result(result)
        self.assertEqual(public['error_code'], 'browser_site_busy')
        self.assertEqual(public['stdout'], 'earlier page finding')
        self.assertIn('other websites', public['recovery']['next_action'])
        self.assertNotIn('private details', str(public))

    def test_tab_dict_aliases_are_normalized_before_guard_and_trusted_call(self):
        for target in ({'targetId':'owned'}, {'target_id':'owned'}):
            for name in ('switch_tab', 'activate_tab'):
                with self.subTest(target=target, helper=name), contextlib.ExitStack() as stack:
                    browser, trusted, actions = self.helpers('https://example.com', stack)
                    actions[name](target)
                    self.assertEqual(browser.info.call_args_list[0].args, ('owned',))
                    self.assertEqual(trusted[name].call_args.args, ('owned',))
            with guard.acquire_job(self.profile, self.home/'job'), contextlib.ExitStack() as stack:
                browser, trusted, actions = self.helpers('https://flow.google.com/', stack)
                with self.assertRaises(guard.FlowResourceBusy):actions['switch_tab'](target)
                trusted['switch_tab'].assert_not_called()
