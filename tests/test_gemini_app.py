"""Gemini package discovery and inspection through the browser host's session contract."""

import contextlib
import hashlib
import io
import json
import os
import sqlite3
import time
from pathlib import Path
from unittest.mock import Mock, patch

from test_profiles import ChromeFixture
import browser_apps
import plugin
from rolling import RollingJob


class GeminiAppTests(ChromeFixture):
    def setUp(self):
        super().setUp()
        self.settings = settings = {'apps_directory': str(self.data / 'packages'), 'profile_directory': 'Default'}
        self.provider = plugin.ChromeProvider(settings.get, data=self.data, set_setting=settings.__setitem__)
        self.addCleanup(self.provider.unload)
        self.dispatch = Mock(side_effect=self.native)
        self.js = Mock()
        self.navigate = Mock()
        self.click = Mock()
        self.type_text = Mock()
        self.press_key = Mock()
        self.host = browser_apps.AppHost(self.provider, settings.get, self.dispatch, lambda code: code,
                                         lambda: self.data / 'plugin-data',
                                         bundled_source=Path(browser_apps.__file__).parent / 'site_apps')
        self.config = {'browser': {'cloud_provider': plugin.NAME, 'auto_local_for_private_urls': False}}

    def native(self, tool, args, **context):
        self.assertEqual(tool, 'browser_exec')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(args['code'], {'js': self.js, 'goto_url': self.navigate,
                                'click_at_xy': self.click, 'type_text': self.type_text,
                                'press_key': self.press_key})
        return {'success': True, 'output': output.getvalue()}

    def call(self, tool='browser_exec', **args):
        args = {'app': 'gemini', 'session': 'inspection', **args}
        with patch.dict(os.environ, {}, clear=True):
            request = args if tool == plugin.PROFILE_TOOL else {'site_control': json.dumps(args), 'session': args['session']}
            prepared = self.host.prepare_call(tool, request, 'agent', session_id='chat',
                                              turn_id='turn', config=self.config)
        self.assertEqual(prepared['action'], 'modify', prepared)
        args.update(prepared['args'])
        if tool == plugin.PROFILE_TOOL:
            return self.provider.profiles(args, task_id='agent', session_id='chat')
        with patch('hermes_cli.config.load_config_readonly', return_value=self.config):
            return json.loads(self.host.execute({**request, **prepared['args']}, self.native,
                task_id='agent', session_id='chat', turn_id='turn'))

    def test_bundled_inspect_is_discoverable_with_its_guide(self):
        listing = json.loads(self.host.handle({'action': 'list'}))
        entry = next(app for app in listing['apps'] if app['id'] == 'gemini')
        self.assertTrue(entry['enabled'])
        self.assertEqual(entry['operations'], [
            'open_chat', 'type_prompt', 'click', 'select_model', 'read_result', 'inspect', 'reply',
        ])
        details = json.loads(self.host.handle({'action': 'describe', 'app': 'gemini'}))
        self.assertIn('Choose an existing Chrome profile', details['guide'])
        self.assertEqual(details['app']['handoff_mode'], 'manual')
        self.assertEqual(details['app']['rolling_parameters'], {'reply': 'continuation'})
        self.dispatch.assert_not_called()

    def test_open_chat_returns_only_the_confirmed_chat_id(self):
        self.js.side_effect = [
            {'origin': 'null', 'path': 'blank'},
            {'reason': 'ready', 'chat_id': 'c_fixture-chat'},
        ]
        result = self.call(action='run', operation='open_chat',
                           params={'chat': 'c_fixture-chat'})
        self.assertEqual(result['data'], {'chat_id': 'c_fixture-chat'})
        self.navigate.assert_called_once_with('https://gemini.google.com/app/fixture-chat')
        self.dispatch.assert_called_once()

    def test_send_click_uses_one_owned_native_call(self):
        self.js.return_value = {'reason': 'ready', 'point': [62, 37]}
        result = self.call(action='run', operation='click',
                           params={'control': 'send'})
        self.assertEqual(result['status'], 'running')
        self.assertEqual(result['data'], {'control': 'send', 'clicked': True})
        self.click.assert_called_once_with(62, 37)
        self.navigate.assert_not_called()
        self.dispatch.assert_called_once()
        self.assertIn(result['session'], self.provider.owners)
        self.provider.ended(session_id='chat', task_id='agent', turn_id='turn')
        self.assertNotIn(result['session'], self.provider.owners)

    def test_blocked_control_keeps_the_native_fallback_session(self):
        self.js.return_value = {'reason': 'obscured'}
        result = self.call(action='run', operation='click',
                           params={'control': 'send'})
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual(result['data'], {'control': 'send', 'reason': 'obscured'})
        self.click.assert_not_called()
        with patch.dict(os.environ, {}, clear=True):
            fallback = self.provider.prepare_call(
                'browser_exec', {'session': result['session']}, 'agent', session_id='chat',
                turn_id='turn', config=self.config)
        self.assertEqual(fallback['args']['session'], result['session'])

    def test_unmapped_control_returns_fallback_without_browser_snapshot(self):
        result = self.call(action='run', operation='click',
                           params={'control': 'unmapped'})
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual(result['data']['reason'], 'unmapped_control')
        self.assertIn('session', result)
        self.dispatch.assert_not_called()

    def test_tool_click_uses_an_already_open_menu(self):
        self.js.side_effect = [
            {'reason': 'missing'},
            {'reason': 'missing'},
            {'reason': 'ready', 'expanded': True},
            {'reason': 'ready', 'expanded': False, 'point': [15, 20]},
            {'reason': 'ready', 'point': [35, 40]},
            {'reason': 'ready'},
        ]
        result = self.call(action='run', operation='click',
                           params={'control': 'deep_research'})
        self.assertTrue(result['success'], result)
        self.assertEqual([entry.args for entry in self.click.call_args_list], [(15, 20), (35, 40)])
        self.dispatch.assert_called_once()

    def test_nested_menu_only_uses_the_keyboard_on_its_focused_trigger(self):
        more = {'reason': 'ready', 'expanded': False, 'point': [15, 20],
                'document': 123, 'chat_id': None}
        for focused in [{**more, 'focused': True}, {**more, 'focused': False}]:
            with self.subTest(focused=focused['focused']):
                self.press_key.reset_mock()
                self.js.side_effect = [
                    {'reason': 'missing'}, {'reason': 'missing'}, {'reason': 'ready', 'expanded': True}, more,
                    {'reason': 'missing'}, focused, {'reason': 'ready', 'point': [35, 40]},
                    {'reason': 'ready'},
                ]
                with patch('time.monotonic', side_effect=[0, 1, 2, 3]):
                    result = self.call(action='run', operation='click',
                                       params={'control': 'deep_research'})
                self.assertTrue(result['success'], result)
                if focused['focused']:
                    self.press_key.assert_called_once_with('ArrowRight')
                else:
                    self.press_key.assert_not_called()

    def test_unconfirmed_research_selection_keeps_send_guard(self):
        self.js.side_effect = [{'reason': 'missing'}, {'reason': 'ready', 'point': [1, 1]},
                               {'reason': 'missing'}]
        with patch('time.monotonic', side_effect=[0, 3]):
            selection = self.call(action='run', operation='click', params={'control': 'deep_research'})
        self.assertEqual(selection['data']['reason'], 'deep_research_selection_unconfirmed')
        self.js.side_effect = None
        self.js.return_value = {'reason': 'deep_research_not_active'}
        sent = self.call(action='run', operation='click', params={'control': 'send'})
        self.assertEqual(sent['data']['reason'], 'deep_research_not_active')
        self.assertIn('"selected"', self.js.call_args.args[0].splitlines()[-1])
        self.click.assert_called_once_with(1, 1)

    def test_active_research_selection_is_idempotent_and_send_binds_reader(self):
        self.js.return_value = {'reason': 'ready'}
        selection = self.call(action='run', operation='click', params={'control': 'deep_research'})
        self.assertEqual(selection['data'], {'control': 'deep_research', 'clicked': False, 'mode_active': True})
        self.click.assert_not_called()
        self.js.side_effect = [self.research_send_state(), {'reason': 'ready', 'mode_active': True, 'point': [2, 3]}]
        self.assertTrue(self.call(action='run', operation='click', params={'control': 'send'})['data']['mode_active'])
        self.js.side_effect = None
        self.js.return_value = {'reason': 'running', 'stage': 'awaiting_response', 'chat_id': 'c_test'}
        with patch('browser_apps.OBSERVATION_INTERVAL', 0):
            self.assertEqual(self.call(operation='read_result')['data']['stage'], 'awaiting_response')
        self.assertIn('"submitted"', self.js.call_args.args[0].splitlines()[-1])

    def test_research_reader_restores_only_a_verified_receipt_from_its_session(self):
        prepared = self.research_send_state()
        intent = prepared['_research_intent']

        def verify_checkpoint(x, y):
            persisted, = (self.data / 'plugin-data/browser-apps/gemini').glob('*/checkpoint.json')
            self.assertEqual(json.loads(persisted.read_text()), {'research_submission': intent})
        self.click.side_effect = verify_checkpoint
        self.js.side_effect = [prepared, {'reason': 'ready', 'mode_active': True, 'point': [2, 3]}]
        self.call(action='run', operation='click', params={'control': 'send'})
        self.js.side_effect = None
        receipt = {'chat': 'c_fixture', 'id': 'verified-topic'}
        with patch('browser_apps.OBSERVATION_INTERVAL', 0):
            self.js.return_value = {'reason': 'running', 'stage': 'planning', 'chat_id': 'c_fixture',
                                    '_research_receipt': receipt}
            result = self.call(operation='read_result')
            self.assertNotIn('_research_receipt', result)
            self.assertNotIn('verified-topic', self.js.call_args.args[0])
            self.assertIn(json.dumps(intent), self.js.call_args.args[0])
            persisted, = (self.data / 'plugin-data/browser-apps/gemini').glob('*/checkpoint.json')
            self.assertEqual(json.loads(persisted.read_text()), {'research_submission': receipt})
            self.js.return_value = {'reason': 'running', 'stage': 'plan_ready', 'chat_id': 'c_fixture',
                                    'control': 'start_research', '_research_receipt': receipt}
            resumed = self.call(operation='read_result')
            self.assertIn(json.dumps(receipt), self.js.call_args.args[0])
            self.assertEqual(resumed['next_control']['params']['control'], 'start_research')
        self.assertEqual(resumed['session'], result['session'])
        self.click.assert_called_once_with(2, 3)
        self.navigate.assert_not_called()

    @staticmethod
    def research_send_state():
        return {'reason': 'ready', 'mode_active': True, 'point': [2, 3], '_research_intent': {
            'chat': None, 'home': '/app', 'previous': None, 'document': 42,
            'prompt_hash': hashlib.sha256(b'Fixture topic').hexdigest(),
        }}

    def test_ambiguous_research_click_keeps_intent_for_reading(self):
        prepared = self.research_send_state()
        self.js.side_effect = [prepared, {'reason': 'ready', 'mode_active': True, 'point': [2, 3]}]

        def lose_click_result(tool, args, **context):
            result = self.native(tool, args, **context)
            return {'success': False} if self.click.called else result

        self.dispatch.side_effect = lose_click_result
        result = self.call(operation='click', params={'control': 'send'})
        self.assertEqual(result['data']['reason'], 'action_unconfirmed')
        persisted, = (self.data / 'plugin-data/browser-apps/gemini').glob('*/checkpoint.json')
        self.assertEqual(json.loads(persisted.read_text())['research_submission'], prepared['_research_intent'])
        self.click.assert_called_once_with(2, 3)

    def test_changed_research_composer_withholds_click_and_discards_intent(self):
        self.js.side_effect = [self.research_send_state(), {'reason': 'research_composer_changed'}]
        result = self.call(operation='click', params={'control': 'send'})
        self.assertEqual(result['data']['reason'], 'research_composer_changed')
        self.assertNotIn('_send_not_dispatched', result)
        persisted, = (self.data / 'plugin-data/browser-apps/gemini').glob('*/checkpoint.json')
        self.assertIsNone(json.loads(persisted.read_text())['research_submission'])
        self.click.assert_not_called()

    def test_type_prompt_verifies_focus_and_preserves_send(self):
        ready = {'reason': 'ready', 'point': [10, 20], 'value': '', 'document': 10, 'chat_id': 'c_fixture'}
        self.js.side_effect = [ready, {**ready, 'focused': True}, {**ready, 'value': 'Fixture prompt'}]
        result = self.call(action='run', operation='type_prompt',
                           params={'text': 'Fixture prompt'})
        self.assertTrue(result['success'], result)
        self.click.assert_called_once_with(10, 20)
        self.type_text.assert_called_once_with('Fixture prompt')

    def test_type_prompt_leaves_an_existing_draft_unmodified(self):
        self.js.return_value = {'reason': 'ready', 'value': 'Previous draft'}
        result = self.call(action='run', operation='type_prompt',
                           params={'text': 'Fixture prompt'})
        self.assertEqual(result['data']['reason'], 'existing_draft')
        self.click.assert_not_called()
        self.type_text.assert_not_called()

    def test_select_model_opens_picker_and_clicks_the_exact_option(self):
        self.js.side_effect = [
            {'reason': 'missing'},
            {'reason': 'ready', 'expanded': False, 'point': [22, 26]},
            {'reason': 'ready', 'point': [24, 55]},
        ]
        result = self.call(action='run', operation='select_model',
                           params={'model': 'Fixture model'})
        self.assertTrue(result['success'], result)
        self.assertIn('Fixture model', self.js.call_args.args[0])
        self.assertEqual([entry.args for entry in self.click.call_args_list], [(22, 26), (24, 55)])

    def test_native_video_receipt_ignores_other_chats_and_reuses_verified_download(self):
        from site_apps.gemini import video
        context = Mock(directory=self.data / 'task', chrome_profile_directory=self.data, profile='Default')
        context.directory.mkdir()
        history = sqlite3.connect(self.data / 'History')
        self.addCleanup(history.close)
        history.execute('CREATE TABLE downloads (guid, target_path, state, received_bytes, total_bytes, tab_url, start_time)')
        file = self.data / 'generated.mp4'
        file.write_bytes(b'fixture file')
        selected = {'url': 'https://gemini.google.com/app/one', 'key': 'one/result', 'width': 12, 'height': 8}
        context.verify_video.return_value = {'duration': '10', 'streams': [{'codec_type': 'video', 'width': 12, 'height': 8}]}
        def button(owner, key=None):
            if key:
                start = time.time_ns() // 1000 + 11644473600000000
                for guid, url in [('other', selected['url'] + '-other'), ('own', selected['url'])]:
                    history.execute('INSERT INTO downloads VALUES (?, ?, 1, 12, 12, ?, ?)', (guid, str(file), url, start))
                history.commit()
            return selected
        pending = context.directory / 'pending.json'
        with patch.object(video, 'button', side_effect=button) as clicked:
            result = video.download(context, pending)
            repeated = video.download(context, pending)
        self.assertEqual(result, repeated)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(Path(result['data']['file']['path']).read_bytes(), file.read_bytes())
        self.assertEqual(sum(len(call.args) == 2 for call in clicked.call_args_list), 1)
        self.assertFalse(pending.exists())
        history.execute("UPDATE downloads SET tab_url=?", (selected['url'],))
        history.commit()
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            video.receipt(self.data / 'History', {**selected, 'start': 0})

    def test_html_with_mp4_name_cannot_be_published_as_video(self):
        from site_apps.gemini import video
        file = self.data / 'invalid.mp4'
        file.write_text('<!doctype html><html>Login</html>')
        context = Mock(directory=self.data)
        context.verify_video.side_effect = ValueError('Media decode failed')
        with self.assertRaisesRegex(ValueError, 'decode'):
            video.publish(context, file, file.stat().st_size, {'guid': 'invalid'})
        self.assertFalse(list((self.data / 'results').iterdir()))

    def test_research_plan_offers_one_mapped_confirmation_and_stays_pending(self):
        self.js.side_effect = [
            {'reason': 'running', 'chat_id': 'c_fixture', 'stage': 'planning'},
            {'reason': 'running', 'chat_id': 'c_fixture', 'stage': 'plan_ready', 'control': 'start_research'},
            {'reason': 'clicked'}, {'reason': 'already_clicked'},
        ]
        with patch('browser_apps.OBSERVATION_INTERVAL', 0):
            planning = self.call(operation='read_result')
            self.assertEqual(planning['data']['stage'], 'planning')
            ready = self.call(operation='read_result')
            self.assertEqual(ready['status'], 'running')
            self.assertEqual(ready['next_control']['params']['control'], 'start_research')
            first = self.call(operation='click', params={'control': 'start_research'})
            retry = self.call(operation='click', params={'control': 'start_research'})
        self.assertTrue(first['data']['clicked'])
        self.assertFalse(retry['data']['clicked'])
        self.assertEqual(first['session'], planning['session'])

    def test_read_result_reports_generation_in_progress_without_clicking(self):
        self.js.return_value = {'reason': 'running', 'chat_id': 'c_fixture'}
        result = self.call(action='run', operation='read_result')
        self.assertEqual((result['status'], result['data']), ('running', {'chat_id': 'c_fixture'}))
        self.click.assert_not_called()

    def test_research_text_without_plan_is_failed_and_preserves_response(self):
        self.js.return_value = {'reason': 'research_no_plan', 'chat_id': 'c_fixture',
                                'text': 'Saya hanya model bahasa.', 'truncated': False}
        result = self.call(operation='read_result')
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['success'])
        self.assertEqual(result['data'], self.js.return_value)
        self.click.assert_not_called()

    def test_uses_selected_profile_and_reports_only_masked_account(self):
        self.assertTrue(self.call(plugin.PROFILE_TOOL, action='select', profile='Profile 2')['success'])
        email = 'fixture@example.test'
        self.js.side_effect = [{'origin': 'null', 'path': 'blank'},
                               {'page': 'ready', 'account': {'status': 'identified', 'email': email},
                                'model': 'Fixture model', 'controls': {'send': {'status': 'disabled'}},
                                'quota': {'status': 'unknown', 'notices': []}}]
        result = self.call(action='run', operation='inspect')
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
            result = self.call(action='run', operation='inspect',
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
        result = self.call(action='run', operation='inspect',
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
            result = self.call(action='run', operation='inspect',
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
            result = self.call(action='run', operation='inspect')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['data'], state)
        sleep.assert_called_once_with(0.25)

    def test_signed_out_does_not_wait_for_a_model(self):
        state = {'page': 'signed_out', 'account': {'status': 'signed_out'}, 'model': None}
        self.js.side_effect = [{'origin': 'https://gemini.google.com', 'path': '/app'}, state]
        with patch('time.sleep') as sleep:
            result = self.call(action='run', operation='inspect')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['data'], state)
        sleep.assert_not_called()
        self.navigate.assert_not_called()

    def test_profile_cannot_be_changed_through_inspect_parameters(self):
        result = self.call(action='run', operation='inspect',
                           params={'profile': 'Profile 2'})
        self.assertEqual(result['status'], 'failed')
        self.dispatch.assert_not_called()

    def test_rejects_chat_ids_that_are_not_safe_route_segments(self):
        for chat in ('https://example.test/app/chat', '../chat', 'c_', ''):
            with self.subTest(chat=chat):
                result = self.call(action='run', operation='inspect',
                                   params={'chat': chat})
                self.assertEqual(result['status'], 'failed', result)
        self.dispatch.assert_not_called()

    def test_unparseable_browser_result_fails_cleanly(self):
        self.dispatch.side_effect = None
        self.dispatch.return_value = {'success': True, 'output': 'GEMINI_INSPECT=not-json'}
        result = self.call(action='run', operation='inspect')
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
        return self.call(action='run', operation='reply', params={
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
        wrong_profile = self.call(action='run', operation='reply',
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

    @staticmethod
    def account_snapshot(state):
        return {'page': 'ready', 'account': {'status': 'identified', 'email': state['email']},
                'model': state['model'], 'chat_id': state['chat_id']}

    def quota_states(self):
        route, base, focused, draft, _ = self.reply_states()
        self.notice = {"evidence": "You've reached your limit on Fixture model until 9 PM.",
                       "reset_text": "until 9 PM."}
        blocked = {**draft, 'point': None, 'send_disabled': True, 'quota': {'notices': [self.notice]}}
        return [route, self.account_snapshot(base), route, base, base, focused, blocked]

    def destination_states(self, *, document=200, email='destination@example.test'):
        _, source, _, _, _ = self.reply_states()
        route = {'origin': 'https://gemini.google.com', 'path': '/app/other-account-chat'}
        base = {**source, 'chat_id': None, 'email': email, 'document': 200,
                'users': 0, 'answers': 0, 'latest': None}
        inspect = self.account_snapshot({**base, 'chat_id': 'c_other-account-chat'})
        focused = {**base, 'focused': True}
        prompt = ('Continue the task using the following user-provided checkpoint as prior context.\n\n'
                  'Checkpoint:\nPortable context\n\nCurrent request:\nNext question')
        draft = {**focused, 'editor': prompt, 'point': [50, 60]}
        final = {**base, 'chat_id': 'c_destination', 'document': document, 'users': 1, 'answers': 1,
                 'latest': {'prompt': prompt, 'answer': 'Continued answer', 'finished': True}}
        return [route, inspect, route, base, base, focused, draft, final]

    def wrong_model_states(self):
        route, inspect, navigation, base, *_ = self.destination_states(email='other@example.test')
        return [route, inspect, navigation, {**base, 'model': 'Different model'}]

    def portable_reply(self):
        return self.reply(continuation={'model': 'Fixture model', 'checkpoint': 'Portable context'})

    def managed_job(self, job, *, target=None):
        args = {'action': 'run', 'operation': 'reply', 'job': job}
        if target is not None:
            args['target_profile'] = target
        return self.call(**args)

    def test_manual_handoff_waits_and_opens_a_fresh_destination_chat(self):
        self.js.side_effect = self.quota_states()
        blocked = self.portable_reply()
        self.assertTrue(blocked['awaiting_profile'], blocked)
        self.assertEqual(blocked['profile'], 'Default')
        self.assertEqual(blocked['quota']['reset_text'], self.notice['reset_text'])
        self.assertEqual(blocked['handoff']['source_chat'], 'c_fixture-chat')
        self.assertEqual([call.args for call in self.click.call_args_list], [(10, 20)])
        self.type_text.assert_called_once_with('Next question')
        waiting = self.managed_job(blocked['job'])
        self.assertTrue(waiting['awaiting_profile'])
        self.assertEqual(self.dispatch.call_count, 3)

        self.js.side_effect = self.destination_states()
        result = self.managed_job(blocked['job'], target='Profile 2')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['profile'], 'Profile 2')
        self.assertEqual(result['data']['chat_id'], 'c_destination')
        self.assertEqual(result['data']['answer'], 'Continued answer')
        self.navigate.assert_called_once_with('https://gemini.google.com/app')
        self.assertEqual([call.args for call in self.click.call_args_list], [(10, 20), (10, 20), (50, 60)])
        self.assertTrue(self.managed_job(blocked['job'])['cached'])

    def test_automatic_handoff_respects_configured_order_and_same_account(self):
        self.settings.update({'handoff_mode.gemini': 'automatic',
                              'rolling_profiles.gemini': ['Profile 10', 'Profile 2']})
        source = self.quota_states()
        self.js.side_effect = [*source, *source[:2], *self.destination_states()]
        result = self.portable_reply()
        self.assertTrue(result['success'], result)
        self.assertEqual(result['profile'], 'Profile 2')
        self.assertEqual(result['profiles_tried'], ['Default', 'Profile 10', 'Profile 2'])
        self.assertEqual(result['data']['chat_id'], 'c_destination')
        self.assertEqual(self.type_text.call_count, 2)
        self.assertEqual(self.click.call_count, 3)

    def test_manual_handoff_can_choose_another_profile_after_wrong_model(self):
        self.js.side_effect = self.quota_states()
        original = self.portable_reply()
        self.js.side_effect = self.wrong_model_states()
        waiting = self.managed_job(original['job'], target='Profile 2')
        self.assertTrue(waiting['awaiting_profile'], waiting)
        self.assertEqual(waiting['job'], original['job'])
        self.assertEqual(waiting['quota'], original['quota'])
        self.assertEqual(waiting['handoff'], original['handoff'])
        self.assertEqual(waiting['source_profile'], 'Default')
        self.assertIn('selected model', waiting['message'])
        self.assertEqual(self.click.call_count, 1)
        self.assertTrue(self.managed_job(original['job'])['awaiting_profile'])

        self.js.side_effect = self.destination_states()
        result = self.managed_job(original['job'], target='Profile 10')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['profile'], 'Profile 10')
        self.assertEqual(result['data']['chat_id'], 'c_destination')
        self.assertEqual(self.click.call_count, 3)

    def test_manual_handoff_can_retry_a_corrected_destination_model(self):
        self.js.side_effect = self.quota_states()
        original = self.portable_reply()
        self.js.side_effect = self.wrong_model_states()
        first = self.managed_job(original['job'], target='Profile 2')
        self.assertTrue(first['awaiting_profile'], first)
        self.js.side_effect = self.destination_states(email='other@example.test')
        result = self.managed_job(original['job'], target='Profile 2')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['profile'], 'Profile 2')
        self.assertEqual(self.type_text.call_count, 2)

    def test_automatic_handoff_skips_a_destination_that_proved_no_send(self):
        self.settings.update({'handoff_mode.gemini': 'automatic',
                              'rolling_profiles.gemini': ['Profile 2', 'Profile 10']})
        self.js.side_effect = [*self.quota_states(), *self.wrong_model_states(), *self.destination_states()]
        result = self.portable_reply()
        self.assertTrue(result['success'], result)
        self.assertEqual(result['profiles_tried'], ['Default', 'Profile 2', 'Profile 10'])
        self.assertEqual(result['profile'], 'Profile 10')
        self.assertEqual(self.click.call_count, 3)

    def test_recovery_reads_saved_destination_block_before_trying_next_profile(self):
        self.settings.update({'handoff_mode.gemini': 'automatic',
                              'rolling_profiles.gemini': ['Profile 2', 'Profile 10']})
        wrong_model = self.wrong_model_states()
        self.js.side_effect = [*self.quota_states(), *wrong_model]
        outcome = RollingJob.outcome

        def interrupted(job, value):
            if value.get('status') == 'failed' and job.not_submitted(value):
                raise RuntimeError('Interrupted before saving host outcome')
            return outcome(job, value)

        with patch.object(RollingJob, 'outcome', interrupted):
            pending = self.portable_reply()
        self.assertEqual(pending['status'], 'needs_inspection', pending)
        self.assertEqual(pending['profiles_tried'], ['Default', 'Profile 2'])
        self.assertEqual(self.click.call_count, 1)
        self.js.side_effect = [*wrong_model[:2], *self.destination_states()]
        result = self.managed_job(pending['job'])
        self.assertTrue(result['success'], result)
        self.assertEqual(result['profiles_tried'], ['Default', 'Profile 2', 'Profile 10'])
        self.assertEqual(self.click.call_count, 3)

    def test_automatic_handoff_reconciles_uncertain_send_on_its_destination(self):
        self.settings.update({'handoff_mode.gemini': 'automatic',
                              'rolling_profiles.gemini': ['Profile 2', 'Profile 10']})
        *destination, final = self.destination_states()
        self.js.side_effect = [*self.quota_states(), *destination]
        self.click.side_effect = [None, None, RuntimeError('Lost connection after clicking Send')]
        pending = self.portable_reply()
        self.assertEqual(pending['status'], 'needs_inspection', pending)
        self.assertEqual(pending['profiles_tried'], ['Default', 'Profile 2'])

        route = {'origin': 'https://gemini.google.com', 'path': '/app/destination'}
        self.js.side_effect = [route, self.account_snapshot(final), final]
        result = self.managed_job(pending['job'])
        self.assertTrue(result['success'], result)
        self.assertEqual(result['profiles_tried'], ['Default', 'Profile 2'])
        self.assertEqual(result['data']['answer'], 'Continued answer')
        self.assertEqual(self.click.call_count, 3)
        self.assertEqual(self.type_text.call_count, 2)

    def test_quota_banner_with_enabled_send_stays_on_original_profile(self):
        self.settings.update({'handoff_mode.gemini': 'automatic', 'rolling_profiles.gemini': ['Profile 2']})
        frames = self.quota_states()
        *_, draft, complete = self.reply_states()
        frames[-1] = {**draft, 'quota': {'notices': [self.notice]}}
        self.js.side_effect = [*frames, complete]
        result = self.portable_reply()
        self.assertTrue(result['success'], result)
        self.assertEqual(result['profile'], 'Default')
        self.assertEqual(result['profiles_tried'], ['Default'])

    def test_wrong_model_or_generic_banner_does_not_authorize_handoff(self):
        self.settings.update({'handoff_mode.gemini': 'automatic', 'rolling_profiles.gemini': ['Profile 2']})
        frames = self.quota_states()
        frames[-1]['quota'] = {'notices': [{'evidence': "You've reached your limit on Another model."},
                                         {'evidence': 'Gemini usage limits apply.'}]}
        self.js.side_effect = frames
        with patch('time.monotonic', side_effect=[0, 0, 0, 6]):
            result = self.portable_reply()
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['profiles_tried'], ['Default'])
        self.assertEqual(self.click.call_count, 1)

    def test_original_request_can_only_authorize_one_job_to_move(self):
        frames = self.quota_states()
        self.js.side_effect = frames
        first = self.portable_reply()
        self.assertTrue(first['awaiting_profile'])
        self.js.side_effect = frames[:2]
        duplicate = self.call(action='run', operation='reply', session='other',
                              params={'chat': 'fixture-chat', 'prompt': 'Next question', 'request_id': 'request-one',
                                      'continuation': {'model': 'Fixture model', 'checkpoint': 'Portable context'}})
        self.assertEqual(duplicate['status'], 'failed', duplicate)
        self.assertIn('original site operation job', duplicate['message'])
        self.assertEqual(self.click.call_count, 1)

    def test_fresh_destination_needs_its_original_document_to_confirm_result(self):
        self.js.side_effect = self.quota_states()
        first = self.portable_reply()
        self.assertTrue(first['awaiting_profile'])
        self.js.side_effect = self.destination_states(document=201)
        result = self.managed_job(first['job'], target='Profile 2')
        self.assertEqual(result['status'], 'needs_inspection', result)
        self.assertEqual(result['profile'], 'Profile 2')
        self.assertNotIn('answer', result['provider_result']['data'])
        self.assertEqual(self.type_text.call_count, 2)
        self.assertEqual(self.click.call_count, 3)

    def test_unconfirmed_after_send_reconciles_the_original_chat(self):
        self.settings.update({'handoff_mode.gemini': 'automatic', 'rolling_profiles.gemini': ['Profile 2']})
        frames = self.quota_states()
        route, base, _, draft, complete = self.reply_states()
        self.js.side_effect = [*frames[:-1], draft]
        self.click.side_effect = [None, RuntimeError('lost after sending')]
        pending = self.portable_reply()
        self.assertEqual(pending['status'], 'needs_inspection', pending)
        self.assertEqual(self.managed_job(pending['job'], target='Profile 2')['status'], 'needs_inspection')
        self.js.side_effect = [route, self.account_snapshot(base), route, {**complete, 'document': 201}]
        result = self.managed_job(pending['job'])
        self.assertTrue(result['success'], result)
        self.assertEqual(result['data']['chat_id'], 'c_fixture-chat')
        self.assertEqual(result['profiles_tried'], ['Default'])
        self.type_text.assert_called_once_with('Next question')
        self.assertEqual(self.click.call_count, 2)
