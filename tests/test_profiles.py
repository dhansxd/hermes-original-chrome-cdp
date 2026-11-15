"""Dynamic inventory and profile routing with synthetic Chrome metadata."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plugin
import profiles
import relay


class ChromeFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.rows = {'Default': {'name': 'First'}, 'Profile 2': {'name': 'Second'},
                     'Profile 10': {'name': 'Third'}}
        for identifier in self.rows:
            (self.data / identifier).mkdir()
        self.save_metadata()

    def save_metadata(self):
        (self.data / 'Local State').write_text(json.dumps({'profile': {'info_cache': self.rows}}))


class InventoryTests(ChromeFixture):
    def test_fresh_add_remove_and_display_name_change(self):
        first = profiles.get_profile('Default', self.data)
        self.rows['Default']['name'] = 'Renamed'
        self.rows['Profile 3'] = {'name': 'Added'}
        (self.data / 'Profile 3').mkdir()
        (self.data / 'Profile 2').rmdir()
        self.save_metadata()
        current = profiles.list_profiles(self.data)
        self.assertEqual([item.id for item in current], ['Default', 'Profile 3', 'Profile 10'])
        self.assertEqual(profiles.verify_profile(first, self.data).name, 'Renamed')

    def test_recreated_directory_requires_selection_again(self):
        previous = profiles.get_profile('Profile 2', self.data)
        replacement = self.data / 'replacement'
        replacement.mkdir()
        (self.data / 'Profile 2').rmdir()
        replacement.rename(self.data / 'Profile 2')
        with self.assertRaisesRegex(RuntimeError, 'replaced'):
            profiles.verify_profile(previous, self.data)
        self.assertNotEqual(profiles.get_profile('Profile 2', self.data).identity, previous.identity)

    def test_deleted_profile_is_absent_and_cannot_be_selected(self):
        (self.data / 'Profile 2').rmdir()
        self.assertNotIn('Profile 2', [item.id for item in profiles.list_profiles(self.data)])
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            profiles.get_profile('Profile 2', self.data)

    def test_regular_existing_profiles_only(self):
        extra = {'Guest Profile': {}, 'System Profile': {}, 'Locked': {'force_signin_profile_locked': True},
                 'Transient': {'is_ephemeral': True}, 'Linked': {}, 'File': {}, '../outside': {}}
        for identifier in ['Guest Profile', 'System Profile', 'Locked', 'Transient']:
            (self.data / identifier).mkdir()
        (self.data / 'Linked').symlink_to(self.data / 'Default', target_is_directory=True)
        (self.data / 'File').write_text('fixture')
        self.rows.update(extra)
        self.save_metadata()
        self.assertEqual([item.id for item in profiles.list_profiles(self.data)],
                         ['Default', 'Profile 2', 'Profile 10'])

    def test_metadata_link_and_pipe_are_rejected(self):
        metadata = self.data / 'Local State'
        saved = self.data / 'saved'
        metadata.rename(saved)
        metadata.symlink_to(saved)
        with self.assertRaises(OSError):
            profiles.list_profiles(self.data)
        metadata.unlink()
        os.mkfifo(metadata)
        with self.assertRaisesRegex(RuntimeError, 'metadata ownership'):
            profiles.list_profiles(self.data)

    def test_metadata_replacement_during_read_is_reported(self):
        load = json.load
        def replace_metadata(stream):
            result = load(stream)
            replacement = self.data / 'new-state'
            replacement.write_text(json.dumps(result))
            replacement.replace(self.data / 'Local State')
            return result
        with patch('profiles.json.load', side_effect=replace_metadata):
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                profiles.list_profiles(self.data)
        self.assertEqual(len(profiles.list_profiles(self.data)), 3)


class ProfileRoutingTests(ChromeFixture):
    def setUp(self):
        super().setUp()
        self.settings = {'profile_directory': 'Default'}
        self.provider = plugin.ChromeProvider(self.settings.get, data=self.data,
                                              set_setting=self.settings.__setitem__)
        self.addCleanup(self.provider.unload)
        self.config = {'browser': {'cloud_provider': plugin.NAME, 'auto_local_for_private_urls': False}}

    def prepare(self, task='A', alias='same', tool='browser_exec', turn='turn', **arguments):
        args = {'session': alias, **arguments}
        with patch.dict(os.environ, {}, clear=True):
            result = self.provider.prepare_call(tool, args, task, session_id='chat-' + task,
                                                session_key='route-' + task, turn_id=turn, config=self.config)
        return result, {**args, **result.get('args', {})}

    def control(self, action='list', profile=None, task='A', alias='same', turn='turn'):
        result, args = self.prepare(task, alias, plugin.PROFILE_TOOL, turn,
                                    action=action, profile=profile)
        self.assertEqual(result['action'], 'modify', result)
        return self.provider.profiles(args, task_id=task, session_id='chat-' + task)

    def browser(self, task='A', alias='same', turn='turn'):
        result, args = self.prepare(task, alias, turn=turn)
        self.assertEqual(result['action'], 'modify', result)
        name = args['session']
        info = self.provider.create_session('bu-named-' + name + '@fixture-home')
        self.assertNotEqual(info['bb_session_id'], 'unloaded')
        return name, info, self.provider.sessions[info['bb_session_id']]

    def test_listing_reads_fresh_inventory_without_opening_a_browser(self):
        with patch('relay.startup.launch') as launch:
            first = self.control()
            (self.data / 'Profile 2').rmdir()
            second = self.control()
        self.assertEqual(first['default_profile'], 'Default')
        self.assertEqual(len(first['profiles']), 3)
        self.assertEqual(len(second['profiles']), 2)
        self.assertFalse(self.provider.sessions)
        launch.assert_not_called()

    def test_registered_control_returns_native_json_text(self):
        ctx = Mock()
        ctx.get_config = self.settings.get
        ctx.set_config = self.settings.__setitem__
        plugin.register(ctx)
        provider = ctx.register_browser_provider.call_args.args[0]
        provider.data = self.data
        self.addCleanup(provider.unload)
        handler = ctx.register_tool.call_args.kwargs['handler']
        result = provider.prepare_call(plugin.PROFILE_TOOL, {'action': 'list'}, 'A', session_id='chat-A')
        text = handler({'action': 'list', **result['args']}, task_id='A', session_id='chat-A')
        self.assertIsInstance(text, str)
        self.assertTrue(json.loads(text)['success'])

    def test_same_profile_agents_have_distinct_names_and_endpoints(self):
        a_name, a_info, a = self.browser('A')
        b_name, b_info, b = self.browser('B')
        self.assertEqual(a.profile, b.profile)
        self.assertNotEqual(a_name, b_name)
        self.assertNotEqual(a_info['cdp_url'], b_info['cdp_url'])

    def test_different_profiles_and_named_sessions_are_independent(self):
        self.assertTrue(self.control('select', 'Profile 2', task='A', alias='research')['success'])
        self.assertTrue(self.control('select', 'Profile 10', task='B')['success'])
        self.assertEqual(self.browser('A', 'research')[2].profile, 'Profile 2')
        self.assertEqual(self.browser('A', 'other')[2].profile, 'Default')
        self.assertEqual(self.browser('B')[2].profile, 'Profile 10')

    def test_default_changes_apply_to_new_sessions_and_preserve_explicit_choices(self):
        a_name, _, a = self.browser('A')
        self.control('select', 'Profile 10', task='C')
        self.assertTrue(self.control('set_default', 'Profile 2')['success'])
        result, args = self.prepare('A')
        self.assertEqual(result['action'], 'modify')
        self.assertEqual(args['session'], a_name)
        self.assertEqual(a.profile, 'Default')
        self.assertEqual(self.browser('B')[2].profile, 'Profile 2')
        self.assertEqual(self.browser('C')[2].profile, 'Profile 10')

    def test_list_before_default_change_uses_current_default_when_browser_starts(self):
        self.control(task='A')
        self.control('set_default', 'Profile 2', task='B')
        self.assertEqual(self.browser('A')[2].profile, 'Profile 2')

    def test_repeated_selection_reuses_the_existing_session(self):
        name, _, session = self.browser()
        with patch.object(self.provider, 'close_session', wraps=self.provider.close_session) as close:
            self.assertTrue(self.control('select', 'Default')['success'])
            close.assert_not_called()
        result, args = self.prepare()
        self.assertEqual(args['session'], name)
        self.assertFalse(session.closed)

    def test_turn_end_releases_the_current_name_after_a_profile_switch(self):
        self.browser('A')
        self.control('select', 'Profile 2')
        name, _, session = self.browser('A')
        self.provider.ended(session_id='chat-A', task_id='A')
        self.assertTrue(session.closed)
        self.assertFalse(self.provider.owners)
        self.assertFalse(self.provider.profile_choices)
        self.assertEqual(self.provider.create_session('bu-named-' + name + '@fixture-home')['bb_session_id'], 'unloaded')

    def test_round_trip_retires_connections_and_preserves_peer(self):
        first, first_info, original = self.browser('A')
        peer_name, _, peer = self.browser('B')
        self.assertTrue(self.control('select', 'Profile 2', alias=first)['success'])
        second, _, middle = self.browser('A', first)
        self.assertTrue(original.closed)
        self.assertEqual(middle.profile, 'Profile 2')
        self.assertEqual(self.provider.create_session('bu-named-' + first + '@fixture-home')['bb_session_id'], 'unloaded')
        self.assertTrue(self.control('select', 'Default', alias=second)['success'])
        third, _, current = self.browser('A', second)
        self.assertTrue(middle.closed)
        self.assertEqual(current.profile, 'Default')
        self.assertEqual(len({first, second, third}), 3)
        self.assertNotIn(first_info['bb_session_id'], self.provider.sessions)
        self.assertFalse(peer.closed)
        self.assertIn(peer_name, self.provider.owners)
        self.assertEqual(self.prepare('A', first)[1]['session'], third)

    def test_deletion_and_replacement_require_fresh_selection(self):
        self.control('select', 'Profile 2')
        name, _, session = self.browser()
        replacement = self.data / 'replacement'
        replacement.mkdir()
        (self.data / 'Profile 2').rmdir()
        self.assertEqual(self.prepare()[0]['action'], 'block')
        replacement.rename(self.data / 'Profile 2')
        self.assertEqual(self.prepare()[0]['action'], 'block')
        self.assertTrue(self.control('select', 'Profile 2')['success'])
        new_name, _, selected = self.browser()
        self.assertNotEqual(name, new_name)
        self.assertTrue(session.closed)
        self.assertEqual(selected.profile, 'Profile 2')

    def test_display_name_change_refreshes_without_new_connection(self):
        name, _, session = self.browser()
        self.rows['Default']['name'] = 'Renamed'
        self.save_metadata()
        self.assertEqual(self.prepare()[1]['session'], name)
        self.assertEqual(next(iter(self.provider.profile_choices.values())).profile.name, 'Renamed')
        self.assertFalse(session.closed)

    def test_missing_default_can_be_repaired_through_profile_control(self):
        self.settings['profile_directory'] = 'Profile 99'
        self.assertEqual(self.prepare()[0]['action'], 'block')
        self.assertEqual(len(self.control()['profiles']), 3)
        self.assertTrue(self.control('set_default', 'Profile 2')['success'])
        self.assertEqual(self.browser()[2].profile, 'Profile 2')

    def test_invalid_selection_preserves_current_profile(self):
        name, _, session = self.browser()
        self.assertFalse(self.control('select', 'Profile 99')['success'])
        self.assertEqual(self.prepare()[1]['session'], name)
        self.assertFalse(session.closed)

    def test_failed_cleanup_can_be_retried_before_switch(self):
        name, _, session = self.browser()
        with patch.object(session, 'close', return_value=False):
            result = self.control('select', 'Profile 2')
        self.assertFalse(result['success'])
        self.assertIn(name, self.provider.owners)
        self.assertEqual(next(iter(self.provider.profile_choices.values())).profile.id, 'Default')
        self.assertTrue(self.control('select', 'Profile 2')['success'])
        self.assertEqual(self.browser()[2].profile, 'Profile 2')

    def test_finish_cleans_profile_choices_without_browser_creation(self):
        self.control('select', 'Profile 2')
        self.provider.stopped(session_key='route-A')
        self.assertFalse(self.provider.profile_choices)
        self.assertFalse(self.provider.profile_routes)

    def test_another_agent_cannot_use_a_control_context(self):
        result, args = self.prepare(tool=plugin.PROFILE_TOOL, action='select', profile='Profile 2')
        self.assertEqual(result['action'], 'modify')
        self.assertFalse(self.provider.profiles(args, task_id='B', session_id='chat-B')['success'])

    def test_switch_cleanup_preserves_peer_calls_and_stop_cancels_switch(self):
        self.browser('A')
        peer_name, _, peer = self.browser('B')
        entered, release = threading.Event(), threading.Event()
        results = {}
        def stop(_):
            entered.set()
            self.assertTrue(release.wait(3))
        def switch():
            results['switch'] = self.control('select', 'Profile 2')
        with patch('tools.browser_supervisor.SUPERVISOR_REGISTRY.stop', side_effect=stop):
            worker = threading.Thread(target=switch)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(self.prepare('B')[1]['session'], peer_name)
                self.assertEqual(self.prepare('A')[0]['action'], 'block')
                self.provider.stopped(session_key='route-A')
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(results['switch']['success'])
        self.assertFalse(peer.closed)
        self.assertFalse(any(choice.owner[0] == 'A' for choice in self.provider.profile_choices.values()))

    def test_startup_checks_the_selected_directory_identity_before_gui_launch(self):
        _, _, session = self.browser()
        replacement = self.data / 'replacement'
        replacement.mkdir()
        (self.data / 'Default').rmdir()
        replacement.rename(self.data / 'Default')
        with patch('relay.startup.launch') as launch:
            with self.assertRaisesRegex(RuntimeError, 'replaced'):
                session._start()
        launch.assert_not_called()
        self.assertTrue(session.close())


if __name__ == '__main__':
    unittest.main()
