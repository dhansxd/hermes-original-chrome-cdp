"""Generic rolling and request recovery through the normal app entry point."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from test_profiles import ChromeFixture
import browser_apps
import plugin


class RollingTests(ChromeFixture):
    def setUp(self):
        super().setUp()
        self.settings = {'apps_directory': str(self.data / 'packages'), 'profile_directory': 'Default'}
        self.directory = self.data / 'packages' / 'fixture'
        self.directory.mkdir(parents=True)
        shutil.copyfile(Path(__file__).parent / 'fixtures/rolling_app.py', self.directory / 'app.py')
        (self.directory / 'app.json').write_text(json.dumps({
            'api_version': 1, 'id': 'fixture', 'profile_policy': 'rotate_on_limit',
            'operations': {'generate': {'parameters': {'type': 'object'}}}}))
        self.scenario = {'profiles': {profile: {} for profile in self.rows}}
        self.save_scenario()
        self.config = {'browser': {'cloud_provider': plugin.NAME, 'auto_local_for_private_urls': False}}
        self.install()

    def install(self):
        self.provider = plugin.ChromeProvider(self.settings.get, data=self.data,
                                              set_setting=self.settings.__setitem__)
        self.addCleanup(self.provider.unload)
        self.host = browser_apps.AppHost(self.provider, self.settings.get, Mock(), plugin.prepare_code,
                                         lambda: self.data / 'plugin-data')

    def save_scenario(self):
        (self.directory / 'scenario.json').write_text(json.dumps(self.scenario))

    def events(self, kind=None):
        path = self.directory / 'events.jsonl'
        values = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [value for value in values if kind is None or value['kind'] == kind]

    def invoke(self, params=None, job=None, task='A', chat='chat-A', alias='work', turn='turn',
               target_profile=None):
        args = {'action': 'run', 'app': 'fixture', 'operation': 'generate', 'session': alias,
                'params': params or {'prompt': 'fixture', 'project': 'source-project'}}
        if job:
            args['job'] = job
        if target_profile is not None:
            args['target_profile'] = target_profile
        with patch.dict(os.environ, {}, clear=True):
            prepared = self.host.prepare_call('browser_app', args, task, session_id=chat,
                session_key='route-' + task, turn_id=turn, config=self.config)
        self.assertEqual(prepared['action'], 'modify', prepared)
        return json.loads(self.host.handle({**args, **prepared['args']}, task_id=task, session_id=chat))

    def enable_handoff_modes(self):
        path = self.directory / 'app.json'
        metadata = json.loads(path.read_text())
        metadata['handoff_mode'] = 'manual'
        path.write_text(json.dumps(metadata))

    def enable_source_retry(self):
        self.enable_handoff_modes()
        with (self.directory / 'app.py').open('a') as stream:
            stream.write("""

def prepare_source_retry(context, packet):
    event(context, 'prepare_source_retry', packet=packet)
    return {'status': 'ok', 'params': {**packet['params'],
            'project': packet['checkpoint']['project'],
            'count': packet['remaining'].get('remaining_count', 1)}}
""")

    def test_manual_handoff_keeps_partial_results_until_explicit_target_after_reload(self):
        self.enable_handoff_modes()
        self.scenario['profiles']['Default'].update(mode='partial', reset_at='2030-01-01')
        self.save_scenario()
        first = self.invoke(params={'prompt': 'fixture', 'count': 3})
        self.assertTrue(first['awaiting_profile'], first)
        self.assertEqual(first['source_profile'], 'Default')
        self.assertEqual(first['quota']['reset_at'], '2030-01-01')
        self.assertEqual(first['handoff']['remaining_count'], 2)
        self.assertEqual([event['profile'] for event in self.events('identify')], ['Default'])
        self.assertFalse(self.events('handoff'))

        self.provider.unload()
        self.install()
        described = json.loads(self.host.handle({'action': 'describe', 'app': 'fixture'}, session_id='chat-A'))
        self.assertEqual(described['jobs'][0]['phase'], 'awaiting_profile')
        self.settings['handoff_mode.fixture'] = 'automatic'
        self.assertTrue(self.invoke(job=first['job'])['awaiting_profile'])
        alternative = self.invoke(params={'prompt': 'another'})
        self.assertEqual(alternative['job'], first['job'])
        self.assertEqual(alternative['status'], 'needs_inspection')

        done = self.invoke(job=first['job'], target_profile='Profile 10')
        self.assertTrue(done['success'], done)
        self.assertEqual([event['profile'] for event in self.events('run')], ['Default', 'Profile 10'])
        self.assertEqual(self.events('run')[-1]['params']['count'], 2)
        packet = self.events('handoff')[0]['packet']
        self.assertEqual(packet['remaining'], first['handoff'])
        self.assertEqual(Path(packet['remaining']['files'][0]).read_text(), 'preserve completed fixture')
        self.assertTrue(self.invoke(job=first['job'])['cached'])

    def test_manual_handoff_rejects_missing_job_and_wrong_owner_or_alias(self):
        self.enable_handoff_modes()
        self.assertEqual(self.invoke(target_profile='Profile 2')['status'], 'failed')
        self.assertFalse(self.events())
        self.scenario['profiles']['Default']['available'] = False
        self.save_scenario()
        first = self.invoke()
        self.assertTrue(first['awaiting_profile'], first)
        self.assertFalse(self.events('run'))
        for request in ({'task': 'B', 'chat': 'chat-B'}, {'alias': 'other'}):
            result = self.invoke(job=first['job'], target_profile='Profile 2', **request)
            self.assertEqual(result['status'], 'failed')
        self.assertFalse(self.events('handoff'))

    def test_manual_handoff_probes_only_explicit_profile_and_rejects_same_account(self):
        self.enable_handoff_modes()
        self.scenario['profiles']['Default'].update(account='same', mode='quota')
        self.scenario['profiles']['Profile 2'].update(account='same', available=True)
        self.save_scenario()
        job = self.invoke()['job']
        for target in ('Default', 'Profile 42', 'Profile 2'):
            result = self.invoke(job=job, target_profile=target)
            self.assertTrue(result['awaiting_profile'], result)
            self.assertEqual(result['source_profile'], 'Default')
        described = json.loads(self.host.handle({'action': 'describe', 'app': 'fixture'}, session_id='chat-A'))
        self.assertEqual(described['jobs'][0]['profile'], 'Default')
        self.assertEqual([event['profile'] for event in self.events('identify')], ['Default', 'Profile 2'])
        self.assertFalse(self.events('handoff'))

    def test_manual_handoff_stops_after_target_quota_rejection(self):
        self.enable_handoff_modes()
        for profile in ('Default', 'Profile 2'):
            self.scenario['profiles'][profile]['mode'] = 'quota'
        self.save_scenario()
        first = self.invoke()
        second = self.invoke(job=first['job'], target_profile='Profile 2')
        self.assertTrue(second['awaiting_profile'], second)
        self.assertEqual(second['source_profile'], 'Profile 2')
        self.assertEqual([event['profile'] for event in self.events('run')], ['Default', 'Profile 2'])
        done = self.invoke(job=first['job'], target_profile='Profile 10')
        self.assertTrue(done['success'], done)

    def test_manual_target_cannot_move_an_unresolved_request(self):
        self.enable_handoff_modes()
        self.scenario['profiles']['Default'].update(mode='accepted', resume='quota')
        self.save_scenario()
        pending = self.invoke()
        target = self.invoke(job=pending['job'], target_profile='Profile 2')
        self.assertEqual(target['status'], 'needs_inspection')
        self.assertFalse(self.events('resume'))
        check = self.invoke(job=pending['job'])
        self.assertEqual(check['status'], 'needs_inspection')
        self.assertFalse(self.events('handoff'))
        self.assertEqual([event['profile'] for event in self.events('resume')], ['Default'])
        self.assertEqual([event['profile'] for event in self.events('run')], ['Default'])

    def test_automatic_handoff_uses_only_configured_profiles_in_order(self):
        self.enable_handoff_modes()
        self.settings.update({'handoff_mode.fixture': 'automatic', 'rolling_profiles.fixture': ['Profile 10']})
        for profile in ('Default', 'Profile 10'):
            self.scenario['profiles'][profile]['mode'] = 'quota'
        self.save_scenario()
        result = self.invoke()
        self.assertEqual(result['status'], 'quota_exhausted', result)
        self.assertEqual(result['source_profile'], 'Profile 10')
        waiting = self.invoke(job=result['job'])
        self.assertEqual(waiting['status'], 'quota_exhausted', waiting)
        self.assertEqual([event['profile'] for event in self.events('run')], ['Default', 'Profile 10'])
        self.assertEqual(self.events('handoff')[0]['packet']['target']['profile'], 'Profile 10')

    def test_automatic_handoff_skips_same_account_and_continues_remaining_outputs(self):
        self.enable_handoff_modes()
        self.settings.update({'handoff_mode.fixture': 'automatic',
                              'rolling_profiles.fixture': ['Profile 2', 'Profile 10', 'Default']})
        self.scenario['profiles']['Default'].update(account='same', mode='partial')
        self.scenario['profiles']['Profile 2'].update(account='same', available=True)
        self.save_scenario()
        result = self.invoke(params={'prompt': 'fixture', 'count': 3})
        self.assertTrue(result['success'], result)
        self.assertEqual([event['profile'] for event in self.events('identify')], ['Default', 'Profile 2', 'Profile 10'])
        self.assertEqual([event['profile'] for event in self.events('run')], ['Default', 'Profile 10'])
        self.assertEqual(self.events('run')[-1]['params']['count'], 2)

    def test_automatic_handoff_requires_confirmed_quota(self):
        self.enable_handoff_modes()
        self.settings.update({'handoff_mode.fixture': 'automatic', 'rolling_profiles.fixture': ['Profile 2']})
        self.scenario['profiles']['Default']['unavailable'] = True
        self.save_scenario()
        result = self.invoke()
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual([event['profile'] for event in self.events('identify')], ['Default'])
        self.assertFalse(self.events('handoff'))
        self.assertFalse(self.events('run'))

    def test_automatic_exhausted_job_reuses_refilled_last_source_project(self):
        self.enable_source_retry()
        self.settings.update({'handoff_mode.fixture': 'automatic', 'rolling_profiles.fixture': ['Profile 2']})
        self.scenario['profiles']['Default']['mode'] = 'quota'
        self.scenario['profiles']['Profile 2']['mode'] = 'partial'
        self.save_scenario()
        first = self.invoke(params={'prompt': 'fixture', 'project': 'original', 'count': 3})
        self.assertEqual(first['status'], 'quota_exhausted', first)
        self.assertEqual(first['source_profile'], 'Profile 2')
        self.assertFalse(self.events('prepare_source_retry'))
        self.scenario['profiles']['Profile 2'].update(mode='complete', available=True)
        self.save_scenario()
        done = self.invoke(job=first['job'])
        self.assertTrue(done['success'], done)
        self.assertEqual(done['job'], first['job'])
        runs = self.events('run')
        self.assertEqual([item['profile'] for item in runs], ['Default', 'Profile 2', 'Profile 2'])
        self.assertEqual(runs[-1]['params']['project'], runs[-2]['params']['project'])
        self.assertEqual(runs[-1]['params']['count'], 2)
        self.assertEqual(len(self.events('handoff')), 1)

    def test_manual_source_resume_needs_explicit_selection_and_same_account(self):
        self.enable_source_retry()
        self.scenario['profiles']['Default'].update(mode='partial', account='original')
        self.save_scenario()
        first = self.invoke(params={'prompt': 'fixture', 'project': 'source', 'count': 3})
        self.assertTrue(first['awaiting_profile'], first)
        self.assertTrue(self.invoke(job=first['job'])['awaiting_profile'])
        self.scenario['profiles']['Default'].update(mode='complete', available=True, account='different')
        self.save_scenario()
        changed = self.invoke(job=first['job'], target_profile='Default')
        self.assertEqual(changed['status'], 'needs_inspection', changed)
        self.assertFalse(self.events('prepare_source_retry'))
        self.assertEqual(len(self.events('run')), 1)
        self.scenario['profiles']['Default']['account'] = 'original'
        self.save_scenario()
        success = self.invoke(job=first['job'], target_profile='Default')
        self.assertTrue(success['success'], success)
        self.assertEqual(self.events('run')[-1]['params']['count'], 2)
        self.assertFalse(self.events('handoff'))

    def test_source_retry_with_accepted_request_only_observes_same_attempt(self):
        self.enable_source_retry()
        self.scenario['profiles']['Default']['mode'] = 'partial'
        self.save_scenario()
        first = self.invoke(params={'prompt': 'fixture', 'project': 'source', 'count': 3})
        self.scenario['profiles']['Default'].update(mode='accepted', available=True)
        self.save_scenario()
        pending = self.invoke(job=first['job'], target_profile='Default')
        self.assertEqual(pending['status'], 'running', pending)
        done = self.invoke(job=first['job'])
        self.assertTrue(done['success'], done)
        self.assertEqual(done['request']['id'], pending['request']['id'])
        self.assertEqual(len(self.events('run')), 2)
        self.assertEqual(len(self.events('resume')), 1)

    def test_existing_job_still_recovers_after_package_enables_modes(self):
        self.scenario['profiles']['Default']['mode'] = 'accepted'
        self.save_scenario()
        pending = self.invoke()
        self.enable_handoff_modes()
        result = self.invoke(job=pending['job'])
        self.assertTrue(result['success'], result)
        self.assertEqual(result['profile'], 'Default')
        self.assertEqual(result['request']['id'], pending['request']['id'])
        self.assertFalse(self.events('handoff'))

    def test_a_b_c_rolling_maps_destination_context(self):
        self.scenario['profiles']['Default']['mode'] = 'quota'
        self.scenario['profiles']['Profile 2']['mode'] = 'quota'
        self.save_scenario()
        result = self.invoke()
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual([event['profile'] for event in self.events('run')], ['Default', 'Profile 2', 'Profile 10'])
        self.assertEqual(self.events('run')[-1]['params']['project'], 'destination-Profile 10')
        self.assertEqual(self.settings['profile_directory'], 'Default')

    def test_partial_outputs_and_portable_files_are_preserved(self):
        self.scenario['profiles']['Default']['mode'] = 'partial'
        self.save_scenario()
        result = self.invoke(params={'prompt': 'fixture', 'count': 3})
        self.assertTrue(result['success'], result)
        packet = self.events('handoff')[0]['packet']
        self.assertEqual(self.events('run')[-1]['params']['count'], 2)
        self.assertEqual(Path(packet['remaining']['files'][0]).read_text(), 'preserve completed fixture')
        self.assertEqual(packet['source']['profile'], 'Default')
        self.assertEqual(packet['target']['profile'], 'Profile 2')

    def test_same_service_account_is_not_submitted_twice_in_a_round(self):
        self.scenario['profiles']['Default'].update(account='same', mode='quota')
        self.scenario['profiles']['Profile 2'].update(account='same', mode='quota')
        self.save_scenario()
        result = self.invoke()
        self.assertTrue(result['success'], result)
        self.assertEqual([event['profile'] for event in self.events('run')], ['Default', 'Profile 10'])

    def test_all_exhausted_then_fresh_availability_restarts_at_a(self):
        for item in self.scenario['profiles'].values():
            item['mode'] = 'quota'
        self.save_scenario()
        first = self.invoke()
        self.assertEqual(first['status'], 'quota_exhausted', first)
        before = len(self.events('run'))
        waiting = self.invoke(job=first['job'])
        self.assertEqual(waiting['status'], 'quota_exhausted')
        self.assertEqual(len(self.events('run')), before)
        self.scenario['profiles']['Default'].update(mode='complete', available=True)
        self.save_scenario()
        done = self.invoke(job=first['job'])
        self.assertTrue(done['success'], done)
        self.assertEqual(self.events('run')[-1]['profile'], 'Default')

    def test_timeout_reconciles_original_and_never_calls_run_again(self):
        self.scenario['profiles']['Default']['mode'] = 'timeout'
        self.save_scenario()
        first = self.invoke()
        self.assertEqual(first['status'], 'needs_inspection', first)
        self.provider.ended(session_id='chat-A', task_id='A')
        second = self.invoke(job=first['job'], task='A-next', turn='next')
        self.assertTrue(second['success'], second)
        self.assertEqual(len(self.events('run')), 1)
        self.assertEqual(self.events('resume')[0]['profile'], 'Default')

    def test_selector_and_unproven_quota_errors_do_not_rotate(self):
        for mode in ('selector', 'invalid_quota'):
            with self.subTest(mode=mode):
                self.scenario['profiles']['Default']['mode'] = mode
                self.save_scenario()
                result = self.invoke(alias=mode)
                self.assertEqual(result['status'], 'needs_inspection', result)
                self.assertEqual(self.events('run')[-1]['profile'], 'Default')
                self.assertFalse(self.events('handoff'))

    def test_accepted_request_retains_its_source_during_peer_rolling(self):
        self.scenario['profiles']['Default']['mode'] = 'accepted'
        self.save_scenario()
        pending = self.invoke(alias='source')
        self.assertEqual(pending['status'], 'running', pending)
        self.scenario['profiles']['Default']['mode'] = 'quota'
        self.save_scenario()
        peer = self.invoke(alias='peer')
        self.assertEqual(peer['profile'], 'Profile 2')
        source = self.invoke(job=pending['job'], alias='source')
        self.assertTrue(source['success'], source)
        self.assertEqual(source['profile'], 'Default')
        self.assertEqual(source['request']['id'], pending['request']['id'])

    def test_wrong_request_and_changed_account_cannot_complete_the_source_job(self):
        self.scenario['profiles']['Default'].update(mode='accepted', resume='wrong_id')
        self.save_scenario()
        first = self.invoke()
        wrong = self.invoke(job=first['job'])
        self.assertEqual(wrong['status'], 'needs_inspection')
        self.scenario['profiles']['Default'].update(account='changed', resume='complete')
        self.save_scenario()
        changed = self.invoke(job=first['job'])
        self.assertEqual(changed['status'], 'needs_inspection')
        self.assertEqual(len(self.events('run')), 1)

    def test_pending_quota_message_is_not_a_rejection_of_accepted_work(self):
        self.scenario['profiles']['Default'].update(mode='accepted', resume='quota')
        self.save_scenario()
        first = self.invoke()
        result = self.invoke(job=first['job'])
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertFalse(self.events('handoff'))
        self.assertEqual(len(self.events('run')), 1)

    def test_completed_job_is_idempotent_and_owner_bound(self):
        first = self.invoke()
        self.assertTrue(first['success'], first)
        cached = self.invoke(job=first['job'])
        self.assertTrue(cached['cached'])
        self.assertEqual(len(self.events('run')), 1)
        foreign = self.invoke(job=first['job'], task='B', chat='chat-B')
        self.assertFalse(foreign['success'])

    def test_describe_discovers_recoverable_job_after_reload(self):
        self.scenario['profiles']['Default']['mode'] = 'accepted'
        self.save_scenario()
        first = self.invoke()
        self.provider.unload()
        self.install()
        described = json.loads(self.host.handle({'action': 'describe', 'app': 'fixture'}, session_id='chat-A'))
        self.assertEqual(described['jobs'][0]['job'], first['job'])
        done = self.invoke(job=first['job'], turn='new')
        self.assertTrue(done['success'], done)
        self.assertEqual(len(self.events('run')), 1)

    def test_preflight_exhaustion_still_prepares_destination_references(self):
        self.scenario['profiles']['Default']['available'] = False
        self.save_scenario()
        result = self.invoke()
        self.assertTrue(result['success'], result)
        self.assertEqual(self.events('run')[0]['profile'], 'Profile 2')
        self.assertEqual(self.events('run')[0]['params']['project'], 'destination-Profile 2')

    def test_unavailable_profiles_are_probed_without_generation(self):
        for item in self.scenario['profiles'].values():
            item['unavailable'] = True
        self.save_scenario()
        result = self.invoke()
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertFalse(self.events('run'))

    def test_unavailable_accounts_after_exhaustion_report_current_login_state(self):
        for item in self.scenario['profiles'].values():
            item['mode'] = 'quota'
        self.save_scenario()
        first = self.invoke()
        for item in self.scenario['profiles'].values():
            item['unavailable'] = True
        self.save_scenario()
        result = self.invoke(job=first['job'])
        self.assertEqual(result['status'], 'needs_inspection', result)
        self.assertEqual(len(self.events('run')), 3)

    def test_missing_default_uses_current_inventory_and_explicit_handoff(self):
        (self.data / 'Default').rmdir()
        result = self.invoke()
        self.assertTrue(result['success'], result)
        self.assertEqual(self.events('run')[0]['profile'], 'Profile 2')
        self.assertEqual(self.events('handoff')[0]['packet']['source']['profile'], 'Default')

    def test_deleted_fixed_start_keeps_its_source_in_the_handoff(self):
        self.provider.rules.change('fixture', 'default', '*', '', {'mode': 'fixed', 'profile': 'Profile 2'})
        (self.data / 'Profile 2').rmdir()
        result = self.invoke()
        self.assertTrue(result['success'], result)
        self.assertEqual(result['profile'], 'Default')
        self.assertEqual(self.events('handoff')[0]['packet']['source']['profile'], 'Profile 2')

    def test_source_directory_replacement_blocks_recovery(self):
        self.scenario['profiles']['Default']['mode'] = 'accepted'
        self.save_scenario()
        first = self.invoke()
        self.provider.unload()
        replacement = self.data / 'replacement'
        replacement.mkdir()
        (self.data / 'Default').rmdir()
        replacement.rename(self.data / 'Default')
        self.install()
        result = self.invoke(job=first['job'])
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual(len(self.events('run')), 1)

    def test_proven_absence_allows_one_safe_resubmission(self):
        self.scenario['profiles']['Default'].update(mode='timeout', resume='not_submitted')
        self.save_scenario()
        first = self.invoke()
        self.scenario['profiles']['Default']['mode'] = 'complete'
        self.save_scenario()
        done = self.invoke(job=first['job'])
        self.assertTrue(done['success'], done)
        self.assertEqual(len(self.events('run')), 2)

    def test_busy_alias_does_not_execute_package_code(self):
        store = self.host.jobs('fixture')
        with store.lease('chat-A', 'work') as acquired:
            self.assertTrue(acquired)
            result = self.invoke()
        self.assertEqual(result['status'], 'running')
        self.assertFalse(self.events())

    def test_live_inventory_addition_and_removal_are_seen_before_the_next_candidate(self):
        self.scenario['profiles']['Default']['mode'] = 'quota'
        self.save_scenario()
        read = plugin.list_profiles
        calls = 0
        def inventory(data):
            nonlocal calls
            calls += 1
            if calls == 2:
                (self.data / 'Profile 2').rmdir()
                (self.data / 'Profile 3').mkdir()
                self.rows['Profile 3'] = {'name': 'Added during rolling'}
                self.save_metadata()
                self.scenario['profiles']['Profile 3'] = {}
                self.save_scenario()
            return read(data)
        with patch('rolling.list_profiles', side_effect=inventory):
            result = self.invoke()
        self.assertTrue(result['success'], result)
        self.assertEqual([event['profile'] for event in self.events('run')], ['Default', 'Profile 3'])

    def test_preferred_order_and_selected_start_are_respected(self):
        self.settings['profile_directory'] = 'Profile 10'
        self.settings['rolling_profiles.fixture'] = ['Profile 10', 'Default']
        self.scenario['profiles']['Profile 10']['mode'] = 'quota'
        self.scenario['profiles']['Default']['mode'] = 'quota'
        self.save_scenario()
        result = self.invoke()
        self.assertTrue(result['success'], result)
        self.assertEqual([event['profile'] for event in self.events('run')], ['Profile 10', 'Default', 'Profile 2'])

    def test_quota_cache_is_operation_scoped_and_has_reset_evidence(self):
        for item in self.scenario['profiles'].values():
            item.update(mode='quota', reset_at='2099-01-01T00:00:00Z')
        self.save_scenario()
        exhausted = self.invoke()
        self.assertEqual(len(exhausted['exhausted']), 3)
        self.assertEqual(exhausted['exhausted'][0]['reset_at'], '2099-01-01T00:00:00Z')
        self.scenario['profiles']['Default'].update(scope='image', mode='complete')
        self.save_scenario()
        image = self.invoke(params={'model': 'image'}, alias='image')
        self.assertTrue(image['success'], image)
        self.assertEqual(image['profile'], 'Default')

    def test_interrupted_handoff_reconciles_destination_before_submit(self):
        self.scenario['profiles']['Default']['mode'] = 'quota'
        self.scenario['profiles']['Profile 2']['resume'] = 'not_submitted'
        self.scenario['handoff_timeout'] = True
        self.save_scenario()
        first = self.invoke()
        self.assertEqual(first['status'], 'needs_inspection', first)
        self.assertEqual(len(self.events('run')), 1)
        done = self.invoke(job=first['job'])
        self.assertTrue(done['success'], done)
        self.assertEqual(self.events('run')[-1]['params']['project'], 'destination-Profile 2')

    def test_missing_handoff_file_never_submits_on_the_destination(self):
        self.scenario['profiles']['Default']['mode'] = 'partial'
        self.save_scenario()
        with patch('rolling.os.path.isfile', return_value=False):
            result = self.invoke()
        self.assertEqual(result['status'], 'needs_inspection', result)
        self.assertEqual(len(self.events('run')), 1)

    def test_stop_preserves_receipt_and_resume_observes_without_replay(self):
        self.scenario['profiles']['Default']['mode'] = 'accepted'
        self.save_scenario()
        first = self.invoke()
        self.provider.stopped(session_key='route-A')
        self.assertFalse(self.provider.owners)
        result = self.invoke(job=first['job'], turn='after-stop')
        self.assertTrue(result['success'], result)
        self.assertEqual(result['request']['id'], first['request']['id'])
        self.assertEqual(len(self.events('run')), 1)

    def test_next_turn_keeps_the_current_account_until_its_quota_is_exhausted(self):
        self.scenario['profiles']['Default']['mode'] = 'quota'
        self.save_scenario()
        first = self.invoke()
        self.assertEqual(first['profile'], 'Profile 2')
        self.provider.ended(session_id='chat-A', task_id='A')
        self.scenario['profiles']['Default'].update(mode='complete', available=True)
        self.save_scenario()
        second = self.invoke(params={'prompt': 'next'}, turn='next', task='next')
        self.assertEqual(second['profile'], 'Profile 2')
        self.assertEqual(self.events('run')[-1]['profile'], 'Profile 2')

    def test_changed_profile_policy_takes_precedence_over_the_saved_cursor(self):
        self.scenario['profiles']['Default']['mode'] = 'quota'
        self.save_scenario()
        self.invoke()
        self.provider.ended(session_id='chat-A', task_id='A')
        self.settings['profile_directory'] = 'Profile 10'
        changed = self.invoke(params={'prompt': 'new default'}, turn='next')
        self.assertEqual(changed['profile'], 'Profile 10')

    def test_exhausting_a_continued_round_returns_to_its_original_first_profile(self):
        self.scenario['profiles']['Default']['mode'] = 'quota'
        self.save_scenario()
        self.assertEqual(self.invoke()['profile'], 'Profile 2')
        self.provider.ended(session_id='chat-A', task_id='A')
        for item in self.scenario['profiles'].values():
            item['mode'] = 'quota'
        self.save_scenario()
        exhausted = self.invoke(params={'prompt': 'second job'}, turn='next')
        self.assertEqual(exhausted['status'], 'quota_exhausted', exhausted)
        self.scenario['profiles']['Default'].update(mode='complete', available=True)
        self.save_scenario()
        self.assertEqual(self.invoke(job=exhausted['job'], turn='next')['profile'], 'Default')

    def test_disable_releases_a_rolling_session_and_keeps_its_receipt(self):
        self.scenario['profiles']['Default']['mode'] = 'accepted'
        self.save_scenario()
        first = self.invoke()
        disabled = json.loads(self.host.handle({'action': 'disable', 'app': 'fixture'}))
        self.assertFalse(disabled['cleanup_pending'], disabled)
        self.assertFalse(self.provider.owners)
        self.assertFalse(self.provider.profile_choices)
        self.host.handle({'action': 'enable', 'app': 'fixture'})
        restored = self.invoke(job=first['job'])
        self.assertTrue(restored['success'], restored)
        self.assertEqual(len(self.events('run')), 1)

    def test_acceptance_during_destination_preparation_prevents_another_submit(self):
        self.scenario['profiles']['Default']['mode'] = 'quota'
        self.save_scenario()
        path = self.directory / 'app.py'
        path.write_text(path.read_text().replace(
            "event(context, 'handoff', packet=packet)",
            "event(context, 'handoff', packet=packet)\n    context.accepted('already-accepted-during-preparation')"))
        result = self.invoke()
        self.assertEqual(result['status'], 'needs_inspection', result)
        self.assertEqual(result['request']['id'], 'already-accepted-during-preparation')
        self.assertEqual(len(self.events('run')), 1)

    def test_real_process_exit_preserves_receipt_and_releases_lease(self):
        self.scenario['profiles']['Default']['mode'] = 'crash'
        self.save_scenario()
        import agent.browser_provider
        code = '''import json, sys
from pathlib import Path
sys.path[:0] = json.loads(sys.argv[1])
import hermes_bootstrap
import browser_apps, plugin
root=Path(sys.argv[2])
settings={'apps_directory':str(root/'packages'),'profile_directory':'Default'}
provider=plugin.ChromeProvider(settings.get,data=root,set_setting=settings.__setitem__)
host=browser_apps.AppHost(provider,settings.get,lambda *a,**k:None,plugin.prepare_code,lambda:root/'plugin-data')
args={'action':'run','app':'fixture','operation':'generate','session':'work','params':{'prompt':'fixture'}}
prepared=host.prepare_call('browser_app',args,'A',session_id='chat-A',turn_id='turn',config={'browser':{'cloud_provider':plugin.NAME,'auto_local_for_private_urls':False}})
host.handle({**args,**prepared['args']},task_id='A',session_id='chat-A')
'''
        paths = [str(Path(__file__).resolve().parents[1]), str(Path(agent.browser_provider.__file__).resolve().parents[1])]
        child = subprocess.run([sys.executable, '-c', code, json.dumps(paths), str(self.data)],
                               capture_output=True, text=True, timeout=20)
        self.assertEqual(child.returncode, 23, child.stderr)
        described = json.loads(self.host.handle({'action': 'describe', 'app': 'fixture'}, session_id='chat-A'))
        job = described['jobs'][0]['job']
        result = self.invoke(job=job)
        self.assertTrue(result['success'], result)
        self.assertEqual(len(self.events('run')), 1)
