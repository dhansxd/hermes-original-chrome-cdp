"""Gemini package discovery and inspection through the browser host's session contract."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

from test_profiles import ChromeFixture
import browser_apps
import plugin


class GeminiAppTests(ChromeFixture):
    def setUp(self):
        super().setUp()
        settings = {'apps_directory': str(self.data / 'packages'), 'profile_directory': 'Default'}
        self.provider = plugin.ChromeProvider(settings.get, data=self.data, set_setting=settings.__setitem__)
        self.addCleanup(self.provider.unload)
        self.dispatch = Mock(side_effect=self.native)
        self.js = Mock()
        self.navigate = Mock()
        self.click = Mock()
        self.type_text = Mock()
        self.host = browser_apps.AppHost(self.provider, settings.get, self.dispatch, lambda code: code,
                                         lambda: self.data / 'plugin-data',
                                         bundled_source=Path(browser_apps.__file__).parent / 'site_apps')
        self.config = {'browser': {'cloud_provider': plugin.NAME, 'auto_local_for_private_urls': False}}

    def native(self, tool, args, **context):
        self.assertEqual(tool, 'browser_exec')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(args['code'], {'js': self.js, 'goto_url': self.navigate,
                                'click_at_xy': self.click, 'type_text': self.type_text})
        return {'success': True, 'output': output.getvalue()}

    def call(self, tool, **args):
        args = {'app': 'gemini', 'session': 'inspection', **args}
        with patch.dict(os.environ, {}, clear=True):
            prepared = self.host.prepare_call(tool, args, 'agent', session_id='chat',
                                              turn_id='turn', config=self.config)
        self.assertEqual(prepared['action'], 'modify', prepared)
        args.update(prepared['args'])
        if tool == plugin.PROFILE_TOOL:
            return self.provider.profiles(args, task_id='agent', session_id='chat')
        return json.loads(self.host.handle(args, task_id='agent', session_id='chat'))

    def test_bundled_inspect_is_discoverable_with_its_guide(self):
        listing = json.loads(self.host.handle({'action': 'list'}))
        entry = next(app for app in listing['apps'] if app['id'] == 'gemini')
        self.assertTrue(entry['enabled'])
        self.assertEqual(entry['operations'], ['inspect', 'reply'])
        details = json.loads(self.host.handle({'action': 'describe', 'app': 'gemini'}))
        self.assertIn('Choose an existing Chrome profile', details['guide'])
        self.assertNotIn('profile_policy', details['app'])
        self.dispatch.assert_not_called()

    def test_uses_selected_profile_and_reports_only_masked_account(self):
        self.assertTrue(self.call(plugin.PROFILE_TOOL, action='select', profile='Profile 2')['success'])
        email = 'fixture@example.test'
        self.js.side_effect = [{'origin': 'null', 'path': 'blank'},
                               {'page': 'ready', 'account': {'status': 'identified', 'email': email},
                                'model': 'Fixture model', 'controls': {'send': {'status': 'disabled'}},
                                'quota': {'status': 'unknown', 'notices': []}}]
        result = self.call(browser_apps.APP_TOOL, action='run', operation='inspect')
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['profile'], 'Profile 2')
        self.assertEqual(result['data']['account'], {
            'status': 'identified', 'id': hashlib.sha256(email.encode()).hexdigest(), 'hint': 'f…@example.test'})
        self.assertNotIn(email, json.dumps(result))
        self.assertEqual(result['data']['quota']['status'], 'unknown')
        self.assertEqual(self.dispatch.call_args.args[1]['session'], result['session'])
        self.navigate.assert_called_once_with('https://gemini.google.com/app')

    def test_inspection_keeps_an_open_gemini_chat_document(self):
        self.js.side_effect = [{'origin': 'https://gemini.google.com', 'path': '/u/0/app/fixture-chat'},
                               {'page': 'ready', 'account': {'status': 'unknown'}, 'model': None,
                                'chat_id': 'c_fixture-chat'},
                               {'page': 'ready', 'account': {'status': 'unknown'}, 'model': 'Hydrogen Tinggi',
                                'chat_id': 'c_fixture-chat'}]
        with patch('time.sleep') as sleep:
            result = self.call(browser_apps.APP_TOOL, action='run', operation='inspect',
                               params={'chat': 'fixture-chat'})
        self.assertTrue(result['success'], result)
        self.assertEqual(result['data']['model'], 'Hydrogen Tinggi')
        self.assertEqual(result['data']['chat_id'], 'c_fixture-chat')
        self.assertEqual(self.js.call_count, 3)
        self.dispatch.assert_called_once()
        sleep.assert_called_once_with(0.25)
        self.navigate.assert_not_called()

    def test_inspection_opens_only_the_requested_chat_in_the_selected_profile(self):
        self.assertTrue(self.call(plugin.PROFILE_TOOL, action='select', profile='Profile 2')['success'])
        self.js.side_effect = [{'origin': 'null', 'path': 'blank'},
                               {'page': 'ready', 'account': {'status': 'unknown'},
                                'model': 'Fixture model', 'chat_id': 'c_fixture-chat'}]
        result = self.call(browser_apps.APP_TOOL, action='run', operation='inspect',
                           params={'chat': 'c_fixture-chat'})
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['profile'], 'Profile 2')
        self.assertEqual(result['data']['chat_id'], 'c_fixture-chat')
        self.navigate.assert_called_once_with('https://gemini.google.com/app/fixture-chat')

    def test_inspection_does_not_confirm_a_redirect_to_a_different_chat(self):
        self.js.side_effect = [{'origin': 'null', 'path': 'blank'},
                               {'page': 'ready', 'account': {'status': 'unknown'},
                                'model': 'Fixture model', 'chat_id': 'c_other-chat'}]
        with patch('time.monotonic', side_effect=[0.0, 8.0]):
            result = self.call(browser_apps.APP_TOOL, action='run', operation='inspect',
                               params={'chat': 'c_fixture-chat'})
        self.assertEqual(result['status'], 'failed', result)
        self.assertIn('could not be confirmed', result['message'])
        self.navigate.assert_called_once_with('https://gemini.google.com/app/fixture-chat')

    def test_returns_ready_without_a_readable_model_at_the_deadline(self):
        state = {'page': 'ready', 'account': {'status': 'unknown'}, 'model': None,
                 'controls': {'model_picker': {'status': 'visible', 'label': None}}}
        self.js.side_effect = [{'origin': 'https://gemini.google.com', 'path': '/app'},
                               state, state]
        with patch('time.monotonic', side_effect=[0.0, 7.75, 8.0]), patch('time.sleep') as sleep:
            result = self.call(browser_apps.APP_TOOL, action='run', operation='inspect')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['data'], state)
        sleep.assert_called_once_with(0.25)

    def test_signed_out_does_not_wait_for_a_model(self):
        state = {'page': 'signed_out', 'account': {'status': 'signed_out'}, 'model': None}
        self.js.side_effect = [{'origin': 'https://gemini.google.com', 'path': '/app'}, state]
        with patch('time.sleep') as sleep:
            result = self.call(browser_apps.APP_TOOL, action='run', operation='inspect')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['data'], state)
        sleep.assert_not_called()
        self.navigate.assert_not_called()

    def test_profile_cannot_be_changed_through_inspect_parameters(self):
        result = self.call(browser_apps.APP_TOOL, action='run', operation='inspect',
                           params={'profile': 'Profile 2'})
        self.assertEqual(result['status'], 'failed')
        self.dispatch.assert_not_called()

    def test_rejects_chat_ids_that_are_not_safe_route_segments(self):
        for chat in ('https://example.test/app/chat', '../chat', 'c_', ''):
            with self.subTest(chat=chat):
                result = self.call(browser_apps.APP_TOOL, action='run', operation='inspect',
                                   params={'chat': chat})
                self.assertEqual(result['status'], 'failed', result)
        self.dispatch.assert_not_called()

    def test_unparseable_browser_result_fails_cleanly(self):
        self.dispatch.side_effect = None
        self.dispatch.return_value = {'success': True, 'output': 'GEMINI_INSPECT=not-json'}
        result = self.call(browser_apps.APP_TOOL, action='run', operation='inspect')
        self.assertEqual(result['status'], 'failed')
        self.assertIn('invalid inspection snapshot', result['message'])

    @staticmethod
    def reply_states():
        route = {'origin': 'https://gemini.google.com', 'path': '/app/fixture-chat'}
        previous = {'prompt': 'Prior prompt', 'answer': 'Prior answer', 'finished': True}
        base = {'chat_id': 'c_fixture-chat', 'email': 'fixture@example.test', 'document': 100,
                'model': 'Fixture model', 'editor': '', 'focused': False, 'busy': False,
                'media': False, 'users': 1, 'answers': 1, 'latest': previous, 'previous': None,
                'point': [10, 20]}
        focused = {**base, 'focused': True}
        draft = {**focused, 'editor': 'Next question', 'point': [30, 40]}
        complete = {**base, 'users': 2, 'answers': 2, 'previous': previous,
                    'latest': {'prompt': 'Next question', 'answer': 'New answer', 'finished': True}}
        return route, base, focused, draft, complete

    def reply(self, request='request-one', **params):
        return self.call(browser_apps.APP_TOOL, action='run', operation='reply', params={
            'chat': 'fixture-chat', 'prompt': 'Next question', 'request_id': request, **params})

    def test_reply_sends_once_and_reuses_a_completed_request(self):
        route, base, focused, draft, complete = self.reply_states()
        self.assertTrue(self.call(plugin.PROFILE_TOOL, action='select', profile='Profile 2')['success'])
        self.js.side_effect = [route, base, base, focused, draft, complete]
        result = self.reply()
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['profile'], 'Profile 2')
        self.assertEqual(result['data']['answer'], 'New answer')
        self.assertEqual([item.args for item in self.click.call_args_list], [(10, 20), (30, 40)])
        self.type_text.assert_called_once_with('Next question')
        self.assertEqual(self.reply()['data'], result['data'])
        self.assertEqual(self.dispatch.call_count, 2)
        self.navigate.assert_not_called()

    def test_reply_recovers_from_lost_send_result_without_resending(self):
        route, base, focused, draft, complete = self.reply_states()
        self.js.side_effect = [route, base, base, focused, draft]
        self.click.side_effect = [None, RuntimeError('lost after sending')]
        self.assertEqual(self.reply()['status'], 'needs_inspection')
        self.assertEqual(self.reply(request='different')['status'], 'failed')
        self.assertEqual(self.reply(prompt='Changed prompt')['status'], 'failed')
        self.assertTrue(self.call(plugin.PROFILE_TOOL, action='select', profile='Profile 2',
                                  session='other-profile')['success'])
        wrong_profile = self.call(browser_apps.APP_TOOL, action='run', operation='reply',
                                  session='other-profile', params={
                                      'chat': 'fixture-chat', 'prompt': 'Next question',
                                      'request_id': 'request-one'})
        self.assertEqual(wrong_profile['status'], 'failed', wrong_profile)
        self.assertEqual(self.dispatch.call_count, 2)
        unrelated = {**complete, 'latest': {**complete['latest'], 'prompt': 'Unrelated question'}}
        self.js.side_effect = [route, unrelated]
        with patch('time.monotonic', side_effect=[0, 46]):
            self.assertEqual(self.reply()['status'], 'needs_inspection')
        self.js.side_effect = [route, {**complete, 'document': 200}]
        result = self.reply()
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['data']['answer'], 'New answer')
        self.assertEqual(self.click.call_count, 2)
        self.type_text.assert_called_once()

    def test_reply_keeps_an_existing_draft(self):
        route, base, _, _, _ = self.reply_states()
        self.js.side_effect = [route, {**base, 'editor': 'Existing user draft'}]
        result = self.reply()
        self.assertEqual(result['status'], 'failed', result)
        self.assertIn('unsent draft', result['message'])
        self.click.assert_not_called()
        self.type_text.assert_not_called()
