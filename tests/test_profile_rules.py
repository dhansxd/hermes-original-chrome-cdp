"""Service-scoped policies using synthetic original Chrome profile metadata."""
import os
from unittest.mock import patch

from gateway.session_context import clear_session_vars, set_session_vars
from test_profiles import ChromeFixture
import plugin


class ProfileRuleTests(ChromeFixture):
    def setUp(self):
        super().setUp()
        self.settings = {'profile_directory': 'Default'}
        self.provider = self.new_provider()
        self.config = {'browser': {'cloud_provider': plugin.NAME, 'auto_local_for_private_urls': False}}

    def new_provider(self):
        provider = plugin.ChromeProvider(self.settings.get, data=self.data,
                                         set_setting=self.settings.__setitem__)
        self.addCleanup(provider.unload)
        return provider

    def prepare(self, tool='browser_exec', task='A', chat='chat-A', alias='work',
                turn='turn', platform='cli', **args):
        tokens = set_session_vars(platform=platform, session_id=chat, session_key='route-' + task)
        try:
            with patch.dict(os.environ, {}, clear=True):
                result = self.provider.prepare_call(tool, {'session': alias, **args}, task,
                    session_id=chat, turn_id=turn, config=self.config)
            return result, {'session': alias, **args, **result.get('args', {})}
        finally:
            clear_session_vars(tokens)

    def control(self, action='list', task='A', chat='chat-A', **args):
        prepared, args = self.prepare(plugin.PROFILE_TOOL, task, chat, action=action, **args)
        self.assertEqual(prepared['action'], 'modify', prepared)
        return self.provider.profiles(args, task_id=task, session_id=chat)

    def selected(self, task='A', chat='chat-A', app=None, **args):
        prepared, args = self.prepare('browser_exec', task, chat, action='run', app=app, **args)
        self.assertEqual(prepared['action'], 'modify', prepared)
        choice = self.provider.profile_choices[self.provider.profile_routes[args['session']]]
        return choice.profile.id, args['session']

    def test_app_selection_and_defaults_are_independent_of_ordinary_browsing(self):
        self.assertTrue(self.control('select', app='flow', profile='Profile 2')['success'])
        self.assertEqual(self.selected(app='flow')[0], 'Profile 2')
        self.assertEqual(self.selected(app='gemini', alias='gemini-work')[0], 'Default')
        self.assertEqual(self.selected(alias='ordinary-work')[0], 'Default')
        self.assertTrue(self.control('set_default', app='gemini', profile='Profile 10')['success'])
        self.assertEqual(self.selected(app='gemini', task='B', chat='chat-B')[0], 'Profile 10')
        self.assertEqual(self.settings['profile_directory'], 'Default')
        self.assertEqual(self.selected(app='flow')[0], 'Profile 2')
        self.assertEqual(self.control(app='gemini')['default_profile'], 'Profile 10')

    def test_legacy_set_default_replaces_the_ordinary_browser_default_rule(self):
        self.control('set_rule', scope='default', mode='fixed', profile='Profile 10')
        self.control('set_default', profile='Profile 2')
        self.assertEqual(self.control()['default_profile'], 'Profile 2')
        self.assertEqual(self.selected(task='B', chat='chat-B')[0], 'Profile 2')

    def test_rules_persist_across_turns_and_provider_reloads(self):
        self.assertTrue(self.control('set_rule', app='flow', mode='fixed', profile='Profile 2')['success'])
        self.assertEqual(self.selected(app='flow')[0], 'Profile 2')
        self.provider.ended(session_id='chat-A', task_id='A')
        self.assertEqual(self.selected(app='flow', task='A-next', turn='next')[0], 'Profile 2')
        self.assertTrue(self.provider.unload())
        self.provider = self.new_provider()
        self.assertEqual(self.selected(app='flow', task='A-third', turn='third')[0], 'Profile 2')

    def test_random_is_selected_once_per_active_session_from_current_inventory(self):
        self.control('set_rule', scope='default', mode='random', app='flow')
        available = plugin.list_profiles(self.data)
        with patch('plugin.random.choice', return_value=available[1]) as choose:
            first = self.selected(app='flow')
            self.assertEqual(self.selected(app='flow'), first)
            choose.assert_called_once()
        (self.data / 'Profile 2').rmdir()
        self.assertEqual(self.prepare('browser_exec', app='flow', action='run')[0]['action'], 'block')
        with patch('plugin.random.choice', side_effect=lambda rows: rows[-1]) as choose:
            self.assertEqual(self.selected(app='flow', task='B', chat='chat-B')[0], 'Profile 10')
            self.assertNotIn('Profile 2', [row.id for row in choose.call_args.args[0]])

    def test_session_rule_overrides_agent_platform_and_service_default(self):
        self.control('set_rule', scope='default', app='flow', mode='fixed', profile='Profile 10')
        self.control('set_rule', scope='platform', target='cli', app='flow', mode='fixed', profile='Profile 2')
        self.control('set_rule', scope='agent', app='flow', mode='fixed', profile='Profile 10')
        self.control('set_rule', scope='session', app='flow', mode='fixed', profile='Default')
        self.assertEqual(self.selected(app='flow')[0], 'Default')
        self.control('clear_rule', scope='session', app='flow')
        self.assertEqual(self.selected(app='flow')[0], 'Profile 10')
        self.control('clear_rule', scope='agent', app='flow')
        self.assertEqual(self.selected(app='flow')[0], 'Profile 2')
        self.control('clear_rule', scope='platform', target='cli', app='flow')
        self.assertEqual(self.selected(app='flow')[0], 'Profile 10')

    def test_child_inherits_matching_parent_service_and_explicit_role_wins(self):
        self.control('select', profile='Profile 2')
        self.control('select', app='flow', profile='Profile 10')
        self.provider.child_started(parent_session_id='chat-A', child_session_id='child-chat', child_role='writer')
        self.assertEqual(self.selected(task='child', chat='child-chat')[0], 'Profile 2')
        self.assertEqual(self.selected(task='flow-child', chat='child-chat', app='flow')[0], 'Profile 10')
        self.assertEqual(self.selected(task='gemini-child', chat='child-chat', app='gemini')[0], 'Default')
        self.control('set_rule', scope='subagent', target='writer', app='flow', mode='fixed', profile='Profile 2')
        self.provider.child_started(parent_session_id='chat-A', child_session_id='next-child', child_role='writer')
        self.assertEqual(self.selected(task='next-child', chat='next-child', app='flow')[0], 'Profile 2')

    def test_platform_rules_override_parent_and_remain_separate(self):
        self.control('select', profile='Profile 2')
        self.control('set_rule', scope='platform', target='whatsapp', mode='fixed', profile='Profile 10')
        self.control('set_rule', scope='platform', target='telegram', mode='fixed', profile='Default')
        self.provider.child_started(parent_session_id='chat-A', child_session_id='child-chat')
        self.assertEqual(self.selected(task='child', chat='child-chat', platform='whatsapp')[0], 'Profile 10')
        self.assertEqual(self.selected(task='telegram', chat='telegram-chat', platform='telegram')[0], 'Default')
        self.assertEqual(self.selected()[0], 'Profile 2')

    def test_default_mode_and_legacy_configuration_use_profile_directory(self):
        self.settings['profile_directory'] = 'Profile 2'
        self.assertEqual(self.selected()[0], 'Profile 2')
        self.control('set_rule', scope='default', app='flow', mode='fixed', profile='Profile 10')
        self.control('set_rule', app='flow', mode='default')
        self.assertEqual(self.selected(app='flow')[0], 'Profile 2')

    def test_profile_replacement_requires_reselection_for_the_app_only(self):
        self.control('select', app='flow', profile='Profile 2')
        _, before = self.selected(app='flow')
        replacement = self.data / 'replacement'
        replacement.mkdir()
        (self.data / 'Profile 2').rmdir()
        replacement.rename(self.data / 'Profile 2')
        self.assertEqual(self.prepare('browser_exec', app='flow', action='run')[0]['action'], 'block')
        self.assertEqual(self.selected(alias='ordinary-work')[0], 'Default')
        self.control('select', app='flow', profile='Profile 2')
        self.assertNotEqual(self.selected(app='flow')[1], before)

    def test_invalid_rule_does_not_change_saved_configuration(self):
        for arguments in ({'mode': 'fixed'}, {'mode': 'unknown'}, {'mode': 'default', 'scope': 'other'}):
            with self.subTest(arguments=arguments):
                result = self.control('set_rule', **arguments)
                self.assertFalse(result['success'])
                self.assertEqual(self.settings, {'profile_directory': 'Default'})

    def test_rule_changes_wait_for_the_current_profile_cleanup(self):
        self.assertTrue(self.control('set_rule', mode='fixed', profile='Profile 2')['success'])
        _, name = self.selected()
        info = self.provider.create_session('bu-named-' + name + '@fixture-home')
        session = self.provider.sessions[info['bb_session_id']]
        snapshot = self.settings.copy()

        with patch.object(session, 'close', return_value=False):
            self.assertFalse(self.control('set_rule', mode='fixed', profile='Profile 10')['success'])
            self.assertFalse(self.control('clear_rule')['success'])
            self.assertEqual(self.settings, snapshot)
            active = self.provider.profile_choices[self.provider.profile_routes[name]]
            self.assertEqual(active.profile.id, 'Profile 2')
            self.assertIn(name, self.provider.owners)
        self.assertTrue(self.control('clear_rule')['success'])
        self.assertEqual(self.selected(alias='ordinary-work')[0], 'Default')

    def test_failed_config_write_keeps_the_previous_profile_with_a_fresh_name(self):
        _, old = self.selected()
        info = self.provider.create_session('bu-named-' + old + '@fixture-home')
        with patch.object(self.provider.rules, 'set_setting', side_effect=PermissionError('fixture denial')):
            result = self.control('set_rule', profile='Profile 2')
        self.assertFalse(result['success'])
        self.assertEqual(self.settings, {'profile_directory': 'Default'})
        self.assertNotIn(info['bb_session_id'], self.provider.sessions)
        self.assertEqual(self.provider.create_session('bu-named-' + old)['bb_session_id'], 'unloaded')
        selected, fresh = self.selected()
        self.assertEqual(selected, 'Default')
        self.assertNotEqual(fresh, old)

    def test_saved_fixed_rule_rejects_reused_profile_id_on_a_new_turn(self):
        self.assertTrue(self.control('set_rule', mode='fixed', profile='Profile 2')['success'])
        key = self.provider.rules.key('', 'session', 'chat-A', 'work')
        old_identity = self.settings[key]['identity']
        (self.data / 'Profile 2').rename(self.data / 'retired')
        (self.data / 'Profile 2').mkdir()
        self.provider.ended(session_id='chat-A', task_id='A', turn_id='turn')

        blocked, _ = self.prepare(task='B', turn='next')
        self.assertEqual(blocked['action'], 'block')
        self.assertIn('was replaced', blocked['message'])
        self.assertEqual(self.settings[key]['identity'], old_identity)
        self.assertTrue(self.control('set_rule', task='B', turn='next', profile='Profile 2')['success'])
        self.assertEqual(self.selected(task='B', turn='next')[0], 'Profile 2')
        self.assertNotEqual(self.settings[key]['identity'], old_identity)

    def test_legacy_fixed_rule_can_be_read_then_saved_with_identity(self):
        key = self.provider.rules.key('', 'session', 'chat-A', 'work')
        self.settings[key] = {'mode': 'fixed', 'profile': 'Profile 2'}
        self.assertEqual(self.selected()[0], 'Profile 2')
        self.assertNotIn('identity', self.settings[key])
        self.assertTrue(self.control('set_rule', profile='Profile 2')['success'])
        self.assertEqual(self.settings[key]['identity'], list(plugin.get_profile('Profile 2', self.data).identity))

    def test_pending_result_keeps_its_source_profile(self):
        _, name = self.selected(app='flow')
        self.provider.profile_choices[self.provider.profile_routes[name]].pending = True
        result = self.control('select', app='flow', profile='Profile 2')
        self.assertFalse(result['success'])
        self.assertEqual(self.selected(app='flow')[0], 'Default')

    def test_invalid_saved_mode_blocks_before_native_browser_dispatch(self):
        key = self.provider.rules.key('flow', 'session', 'chat-A', 'work')
        self.settings[key] = {'mode': []}
        result, _ = self.prepare('browser_exec', app='flow', action='run')
        self.assertEqual(result['action'], 'block')
        self.assertFalse(self.provider.sessions)

    def test_routed_hermes_configuration_stays_independent(self):
        self.control('set_rule', app='flow', mode='fixed', profile='Profile 2')
        second_settings = {'profile_directory': 'Default'}
        other = plugin.ChromeProvider(second_settings.get, data=self.data,
                                      set_setting=second_settings.__setitem__)
        self.addCleanup(other.unload)
        first = self.selected(app='flow')
        with patch.object(self, 'provider', other):
            second = self.selected(app='flow')
        self.assertEqual(second[0], 'Default')
        self.assertNotEqual(first[1], second[1])
