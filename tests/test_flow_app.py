import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_apps import loaded_package


class FlowAppTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).resolve().parents[1] / 'site_apps/flow'
        self.package = loaded_package(self.directory, (self.directory / 'app.py').read_bytes())
        self.app = self.package.__enter__()
        self.addCleanup(self.package.__exit__, None, None, None)

    def test_project_urls_accept_only_canonical_flow_projects(self):
        self.assertEqual(self.app.project_url('native-id'), 'https://flow.google.com/project/native-id')
        for value in ['https://example.com/project/id', '../Default', 'id/edit/other', 'id?token=private']:
            with self.assertRaises(ValueError):
                self.app.project_url(value)

    def test_native_result_key_preserves_poster_binding_after_edit_id_discovery(self):
        tile = {'key': 'native-poster', 'id': 'edit-id', 'src': 'poster'}
        self.assertEqual(self.app.tile_key(tile), 'native-poster')

    def test_selected_agent_controls_retain_actual_count_and_approval(self):
        settings = {'mode': 'agent', 'groups': [
            {'options': [{'value': '9:16', 'selected': True}]},
            {'options': [{'value': 'x2', 'selected': True}]},
            {'options': [{'value': '16:9', 'selected': True}]},
            {'options': [{'value': 'x3', 'selected': True}]}],
            'models': [{'value': 'Current model'}], 'duration': None, 'approval': '2'}
        self.assertEqual(self.app.selected_settings(settings, 'image')['count'], 2)
        self.assertEqual(self.app.selected_settings(settings, 'video')['count'], 3)
        self.assertEqual(self.app.selected_settings(settings, 'video')['approval'], '2')

    def test_classic_reads_selected_count_when_caller_omits_count(self):
        value = self.app.selected_settings({'mode': 'classic', 'groups': [
            {'label': 'Jumlah output', 'options': [{'value': 'x4', 'selected': True}]}],
            'models': [], 'duration': None, 'approval': None}, 'image')
        self.assertEqual(value['count'], 4)

    def test_account_projects_are_kept_per_profile(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root))
            self.app.save_state(context, {'projects': {'Default': 'one', 'Profile 2': 'two'}})
            self.assertEqual(self.app.local_state(context)['projects'], {'Default': 'one', 'Profile 2': 'two'})

    def test_inspect_reuses_the_requested_project_and_preserves_composer_settings(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Profile 2')
            ui = Mock()
            ui.read.return_value = 'https://flow.google.com/project/native-id/?hl=id#editor'
            ui.snapshot.return_value = {
                'url': ui.read.return_value, 'mode': 'agent', 'approval': '1',
                'models': [{'selector': 'video', 'value': 'Video'}, {'selector': 'image', 'value': 'Image'}]}
            with patch.object(self.app, 'UI', return_value=ui):
                result = self.app.run(context, 'inspect', {
                    'project': 'native-id', 'mode': 'classic', 'kind': 'video'})
            self.assertEqual(result['status'], 'ok', result)
            self.assertEqual(result['data']['project_id'], 'native-id')
            self.assertEqual(result['data']['mode'], 'agent')
            self.assertEqual(result['data']['requested_mode'], 'classic')
            self.assertEqual(result['data']['approval'], '1')
            self.assertEqual(result['data']['models'], [{'selector': 'video', 'value': 'Video'}])
            self.assertIn('https://flow.google.com/project/native-id', ui.wait.call_args.args[0])
            ui.execute.assert_not_called()
            ui.click.assert_not_called()
            ui.mode.assert_not_called()
            ui.settings.assert_not_called()

    def test_inspect_probes_the_requested_project_before_any_saved_project(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Profile 2')
            self.app.save_state(context, {'projects': {'Default': 'other', 'Profile 2': 'old'}})
            ui = Mock()
            target = self.app.project_url('requested')
            ui.read.side_effect = ['https://flow.google.com/', 'fixture@example.test', target]
            ui.snapshot.return_value = {'url': target, 'mode': 'classic', 'models': []}
            with patch.object(self.app, 'UI', return_value=ui):
                probe = self.app.identify(context, 'inspect', {'project': 'requested'})
                result = self.app.run(context, 'inspect', {'project': 'requested'})
            self.assertEqual(probe['status'], 'ok', probe)
            self.assertEqual(result['data']['project_id'], 'requested')
            ui.execute.assert_called_once_with(f'goto_url({target!r})')
            self.assertEqual(self.app.local_state(context)['projects'], {'Default': 'other', 'Profile 2': target})

    def test_inspect_refuses_a_different_project_without_saving_selection(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Default')
            ui = Mock()
            ui.read.return_value = 'https://flow.google.com/'
            ui.snapshot.return_value = {'url': self.app.project_url('unrelated')}
            with patch.object(self.app, 'UI', return_value=ui):
                result = self.app.run(context, 'inspect', {'project': 'requested'})
            self.assertEqual(result['status'], 'failed', result)
            self.assertIn('could not be confirmed', result['message'])
            self.assertEqual(self.app.local_state(context), {})

    def test_inspection_can_read_an_open_account_panel_without_accepting_upload_terms(self):
        ui = Mock()
        ui.read.side_effect = ['', True, 'fixture@example.test']
        with patch.object(self.app, 'acknowledge_upload') as acknowledge:
            result = self.app.account(ui, credits=False, inspect_only=True)
        self.assertEqual(result['id'], hashlib.sha256(b'fixture@example.test').hexdigest())
        acknowledge.assert_not_called()
        ui.click.assert_not_called()
        ui.execute.assert_not_called()

    def test_no_submit_after_invalid_prompt(self):
        ui = Mock()
        with self.assertRaises(ValueError):
            self.app.generate(Mock(), ui, 'generate_video', {'prompt': ''})
        ui.click.assert_not_called()

    def test_generation_redirect_stops_before_preparing_or_saving_project(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Default')
            ui = Mock()
            ui.read.return_value = 'https://flow.google.com/'
            ui.wait.side_effect = RuntimeError('Project readiness timed out after redirect')
            project = self.app.project_url('expected')
            with patch.object(self.app, 'UI', return_value=ui), \
                    patch.object(self.app, 'configure') as configure, \
                    patch.object(self.app.shutil, 'which', return_value='/tool'):
                result = self.app.run(context, 'generate_image', {'project': 'expected', 'prompt': 'scene'})
            self.assertEqual(result['status'], 'failed', result)
            self.assertEqual(result['request']['state'], 'rejected')
            self.assertIn(project, ui.wait.call_args.args[0])
            ui.execute.assert_called_once_with(f'goto_url({project!r})')
            configure.assert_not_called()
            ui.fill.assert_not_called()
            ui.click.assert_not_called()
            self.assertEqual(self.app.local_state(context), {})

    def test_generation_clears_unsubmitted_checkpoint_if_click_guard_rejects_route(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Default', job_id='job')
            project = self.app.project_url('expected')
            current = project + '/?hl=id'
            ui = Mock()
            ui.read.side_effect = [current, 'editor', 'editor', 'scene']
            ui.snapshot.return_value = {'url': current, 'ingredients': [], 'references': [],
                                        'frames': [], 'tiles': [], 'notices': []}
            ui.click.return_value = False
            checkpoints = []
            context.checkpoint.side_effect = lambda record: checkpoints.append(record.copy())
            settings = {'mode': 'classic', 'groups': [], 'models': [], 'duration': None, 'approval': None}
            with patch.object(self.app, 'UI', return_value=ui), \
                    patch.object(self.app, 'configure', return_value=settings), \
                    patch.object(self.app, 'account', return_value={'credits': 10}), \
                    patch.object(self.app, 'observe_generation') as observe, \
                    patch.object(self.app.shutil, 'which', return_value='/tool'):
                result = self.app.run(context, 'generate_video', {'project': 'expected', 'prompt': 'scene'})
            self.assertEqual(result['status'], 'failed', result)
            self.assertIn('changed before Generate', result['message'])
            self.assertEqual(result['request']['state'], 'rejected')
            ui.execute.assert_not_called()
            ui.click.assert_called_once_with('flow-generate-icon-button button', project=project)
            self.assertEqual([record['submit_intent'] for record in checkpoints], [True, False])
            self.assertTrue(all(record['project'] == project for record in checkpoints))
            observe.assert_not_called()

    def test_resume_observes_source_without_generation(self):
        context = Mock(job_id='job')
        source = self.app.project_url('source')
        record = {'params': {}, 'attempts': [{'request_id': 'native'}], 'checkpoint': {
            'job': 'job', 'submit_intent': True, 'request_id': 'native', 'project': source + '/?hl=id'}}
        with patch.object(self.app, 'ensure') as ensure, \
                patch.object(self.app, 'observe_generation', return_value={'status': 'running'}) as observe, \
                patch.object(self.app, 'generate') as generate:
            self.assertEqual(self.app.resume(context, record)['status'], 'running')
            ensure.assert_called_once_with(context, {'project': source}, inspect_only=True)
            observe.assert_called_once()
            generate.assert_not_called()

    def test_checkpoint_from_another_job_does_not_resume_its_generation(self):
        context = Mock(job_id='new')
        record = {'params': {}, 'attempts': [{}], 'checkpoint': {
            'job': 'old', 'submit_intent': True, 'project': 'old-project'}}
        with patch.object(self.app, 'ensure') as ensure, patch.object(self.app, 'observe_generation') as observe:
            self.assertEqual(self.app.resume(context, record)['status'], 'needs_inspection')
            ensure.assert_called_once_with(context, {})
            observe.assert_not_called()

    def test_inspecting_agent_model_closes_menu_with_selected_model(self):
        ui = self.app.UI(Mock())
        ui.snapshot = Mock(return_value={'models': [{'selector': 'video', 'value': 'Native model'}]})
        ui.click = Mock()
        ui.read = Mock(return_value=[{'value': 'Native model', 'disabled': False}])
        ui.execute = Mock()
        ui.wait = Mock()
        ui.model('agent', 'video')
        self.assertEqual(ui.click.call_args.args, ('[role=menuitem]', 'Native model'))
        ui.execute.assert_not_called()

    def test_result_open_uses_direct_container_when_nested_prompt_has_container(self):
        ui = Mock()
        project = self.app.project_url('id')
        asset = project + '/edit/native'
        ui.read.side_effect = [asset + '?hl=id', ['exact prompt']]
        self.assertEqual(self.app.open_output(ui, {'kind': 'image', 'id': 'media'},
                                             'exact prompt', 'classic', project), asset)
        ui.click.assert_called_once_with('flow-image-tile:has([data-media-id="media"]) > .container',
                                         project=project)

    def test_result_edit_redirect_does_not_read_prompt_from_another_project(self):
        ui = Mock()
        ui.read.return_value = self.app.project_url('wrong') + '/edit/native'
        with self.assertRaisesRegex(RuntimeError, 'outside the original project'):
            self.app.open_output(ui, {'kind': 'image', 'id': 'media'}, 'scene', 'classic',
                                 self.app.project_url('source'))
        ui.read.assert_called_once_with('location.href')

    def test_resume_does_not_observe_a_project_that_cannot_be_verified(self):
        context = Mock(job_id='job')
        record = {'params': {}, 'attempts': [{'request_id': 'native'}], 'checkpoint': {
            'job': 'job', 'submit_intent': True, 'request_id': 'native', 'project': 'source'}}
        with patch.object(self.app, 'ensure', side_effect=RuntimeError('Unexpected project')) as ensure, \
                patch.object(self.app, 'observe_generation') as observe:
            result = self.app.resume(context, record)
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual(result['request'], {'state': 'accepted', 'id': 'native'})
        ensure.assert_called_once_with(context, {'project': self.app.project_url('source')}, inspect_only=True)
        observe.assert_not_called()

    def test_pending_tile_refreshes_readiness_without_overwriting_it_from_checkpoint(self):
        ui = Mock()
        ui.snapshot.return_value = {'url': self.app.project_url('source'), 'notices': [],
                                    'tiles': [{'kind': 'image', 'id': 'native', 'ready': True}]}
        context = Mock()
        checkpoint = {'baseline': [], 'kind': 'image', 'request_id': 'native', 'count': 2,
                      'outputs': [{'kind': 'image', 'id': 'native', 'ready': False}],
                      'project': 'source', 'settings': {'mode': 'classic'}}
        self.assertEqual(self.app.observe_generation(context, ui, checkpoint)['status'], 'running')
        self.assertTrue(checkpoint['outputs'][0]['ready'])

    def test_source_output_identity_survives_gaining_an_id_after_a_poster_url(self):
        ui = Mock()
        poster = 'https://assets.example.test/poster'
        tile = {'kind': 'image', 'id': 'native', 'src': poster, 'ready': False}
        ui.snapshot.return_value = {'url': self.app.project_url('source'), 'tiles': [tile], 'notices': []}
        checkpoint = {'project': 'source', 'kind': 'image', 'count': 2, 'baseline': [], 'settings': {},
                      'outputs': [{**tile, 'id': None}], 'notices_before': []}
        result = self.app.observe_generation(Mock(), ui, checkpoint)
        self.assertEqual(result['status'], 'running')
        self.assertEqual(result['request']['id'], 'native')
        self.assertEqual(checkpoint['outputs'][0]['key'], poster)

    def test_resume_mismatched_snapshot_preserves_known_request_without_collecting(self):
        ui = Mock()
        ui.snapshot.return_value = {'url': self.app.project_url('wrong')}
        context = Mock()
        with patch.object(self.app, 'collect') as collect:
            result = self.app.observe_generation(context, ui, {'project': 'source', 'request_id': 'native'})
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual(result['request'], {'state': 'accepted', 'id': 'native'})
        context.checkpoint.assert_not_called()
        collect.assert_not_called()

    def test_old_quota_notice_does_not_trigger_rolling_for_this_request(self):
        text = 'Not enough credits'
        ui = Mock()
        ui.snapshot.return_value = {'url': self.app.project_url('source'), 'tiles': [], 'notices': [text]}
        checkpoint = {'baseline': [], 'kind': 'image', 'count': 1, 'project': 'source', 'settings': {},
                      'notices_before': [text]}
        self.assertEqual(self.app.observe_generation(Mock(), ui, checkpoint)['status'], 'needs_inspection')

    def test_native_reference_cannot_be_silently_dropped_on_account_handoff(self):
        result = self.app.handoff(Mock(), {'params': {}, 'remaining': {
            'composer': {'ingredients': [{'id': 'account-local-id'}]}}})
        self.assertEqual(result['status'], 'needs_inspection')

    def test_bundle_metadata_matches_implemented_operations(self):
        metadata = json.loads((self.directory / 'app.json').read_text())
        self.assertEqual(set(metadata['operations']),
                         {'inspect', 'create_project', 'configure', 'generate_image', 'generate_video',
                          'upload', 'bind_reference', 'create_voice', 'create_character'})

    def test_unknown_parameter_is_reported_before_site_actions(self):
        with patch.object(self.app, 'ensure') as ensure:
            value = self.app.run(Mock(), 'generate_video', {'prompt': 'scene', 'unsupported_setting': 10})
        self.assertEqual(value['status'], 'failed')
        self.assertEqual(value['request']['state'], 'rejected')
        ensure.assert_not_called()

    def test_native_helper_is_from_loaded_module_and_has_unambiguous_control_diagnostics(self):
        context = Mock()
        context.browser_exec.return_value = {'success': True, 'output': 'FLOW_VALUE=true\n'}
        self.app.UI(context).execute('pass')
        code = context.browser_exec.call_args.args[0]
        self.assertNotIn('runpy', code)
        scope = {'js': Mock(return_value=[10, 20]), 'click_at_xy': Mock()}
        exec(code, scope)
        scope['flow_click']('button', 'label')
        scope['click_at_xy'].assert_called_once_with(10, 20)

    def test_interrupted_upload_recovery_does_not_attach_a_reference(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            source = directory / 'source.jpg'
            source.write_bytes(b'local reference')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            references = directory / 'references'
            references.mkdir()
            key = hashlib.sha256(('Default/project/id' + digest).encode()).hexdigest()
            (references / (key + '.json')).write_text(json.dumps({
                'version': 2, 'complete': False, 'assignment_intent': True}))
            ui = Mock()
            ui.context.profile = 'Default'
            ui.read.return_value = '/project/id'
            finder = Mock()
            with patch.dict(self.app.upload.__globals__, {'upload_picker': Mock(), 'find_asset': finder}):
                result = self.app.upload(ui, directory, str(source))
            self.assertEqual(result['sha256'], digest)
            finder.assert_called_once_with(ui, digest + '.jpg')
            ui.click.assert_not_called()

    def test_typed_voice_reference_cannot_be_dropped_on_handoff(self):
        result = self.app.handoff(Mock(), {'params': {}, 'remaining': {
            'composer': {'ingredients': [], 'references': [{'kind': 'voice'}]}}})
        self.assertEqual(result['status'], 'needs_inspection')

    def test_entities_are_scoped_to_profile_and_project(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Default')
            entities = self.app.entities
            value = {'kind': 'voice', 'id': 'saved', 'name': 'Selected voice', 'project': 'project'}
            entities.remember(context, value)
            self.assertEqual(entities.reference(context, 'voice', 'Selected voice', 'project')['id'], 'saved')
            self.assertIsNone(entities.reference(context, 'voice', 'Selected voice', 'another-project'))
            context.profile = 'Profile 2'
            self.assertIsNone(entities.reference(context, 'voice', 'Selected voice', 'project'))
            self.assertIsNone(entities.reference(context, 'image', 'Selected voice', 'project'))

    def test_character_capture_requires_owned_job_and_page_marker(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), job_id='own')
            path = context.directory / 'checkpoint.json'
            checkpoint = {'job': 'own', 'operation': 'create_character', 'project': 'https://flow.google.com/project/p'}
            path.write_text(json.dumps(checkpoint))
            ui = Mock()
            ui.read.side_effect = [checkpoint['project'] + '/character/native', 'own']
            self.app.entities.capture_character(context, ui)
            self.assertEqual(context.checkpoint.call_args.args[0]['native_id'], 'native')
            context.checkpoint.reset_mock()
            checkpoint['job'] = 'peer'
            path.write_text(json.dumps(checkpoint))
            self.app.entities.capture_character(context, ui)
            context.checkpoint.assert_not_called()

    def test_unresolved_character_draft_stays_on_its_original_page(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), job_id='own')
            checkpoint = {'job': 'own', 'operation': 'create_character', 'project': 'https://flow.google.com/project/p'}
            (context.directory / 'checkpoint.json').write_text(json.dumps(checkpoint))
            ui = Mock()
            ui.read.return_value = checkpoint['project'] + '/character'
            with self.assertRaisesRegex(RuntimeError, 'original character draft'):
                self.app.entities.capture_character(context, ui)
            ui.execute.assert_not_called()

    def test_resume_character_finishes_existing_native_entity(self):
        context = Mock(job_id='own')
        checkpoint = {'job': 'own', 'operation': 'create_character', 'native_id': 'saved'}
        with patch.object(self.app.entities, 'finish_character', return_value={'status': 'ok'}) as finish, \
                patch.object(self.app.entities, 'create_character') as create, patch.object(self.app, 'ensure') as ensure:
            self.app.resume(context, {'checkpoint': checkpoint})
            self.assertEqual(finish.call_args.args[2]['native_id'], 'saved')
            create.assert_not_called()
            ensure.assert_not_called()

    def test_resume_voice_observes_original_save(self):
        context = Mock(job_id='own')
        checkpoint = {'job': 'own', 'operation': 'create_voice', 'stage': 'save_intent', 'project': 'source'}
        with patch.object(self.app.entities, 'save_voice', return_value={'status': 'running'}) as save, \
                patch.object(self.app.entities, 'create_voice') as create, patch.object(self.app, 'ensure'):
            self.app.resume(context, {'checkpoint': checkpoint})
            save.assert_called_once()
            create.assert_not_called()

    def test_lost_voice_draft_returns_existing_preview_without_another_save(self):
        entities = self.app.entities
        ui = Mock()
        checkpoint = {'params': {}, 'stage': 'preview_ready', 'preview': {'path': 'existing.wav'}}
        with patch.object(entities, 'voice_state', return_value=None):
            value = entities.save_voice(Mock(), ui, checkpoint)
        self.assertEqual(value['status'], 'needs_inspection')
        self.assertEqual(value['data']['preview']['path'], 'existing.wav')
        ui.click.assert_not_called()

    def test_saved_voice_download_preserves_native_id_without_preview_or_save(self):
        entities = self.app.entities
        params = {'base': 'Base', 'name': 'Custom', 'dialogue': 'Test words', 'performance': 'Conversational'}
        checkpoint = {'params': params, 'stage': 'saved', 'native_id': 'native', 'project': 'project', 'preview': {}}
        ui = Mock()
        state = {**params, 'src': 'https://flow-content.google/audio/native?temporary=token'}
        with patch.object(entities, 'voice_state', return_value=state), \
                patch.object(entities, 'audio', return_value={'path': 'saved.wav'}) as audio, \
                patch.object(entities, 'remember'):
            value = entities.save_voice(Mock(), ui, checkpoint)
        self.assertEqual(value['request'], {'state': 'completed', 'id': 'native'})
        audio.assert_called_once()
        ui.click.assert_not_called()

    def test_voice_binding_checks_actual_audio_id(self):
        references = sys.modules[self.app.bind.__module__]
        ui = Mock()
        ui.snapshot.return_value = {'references': [{'kind': 'voice', 'name': '', 'ready': True, 'disabled': False}]}
        with patch.object(references, 'voice_binding', return_value={'source': 'https://flow-content.google/audio/other?token=temp', 'text': ''}):
            with self.assertRaisesRegex(RuntimeError, 'audio ID'):
                references.verify_binding(ui, {'kind': 'voice'}, {'id': 'wanted'})

    def test_character_binding_matches_portrait_across_display_sizes(self):
        references = sys.modules[self.app.bind.__module__]
        ui = Mock()
        ui.snapshot.return_value = {'references': [{'kind': 'character', 'src': 'https://flow.google.com/asb/portrait=s128-rw',
                                                   'ready': True, 'disabled': False}]}
        value = references.verify_binding(ui, {'kind': 'character'}, {
            'id': 'character', 'portrait': 'https://flow.google.com/asb/portrait=s512-rw'})
        self.assertEqual(value['character_id'], 'character')

    def test_rebinding_character_preserves_existing_chip_without_clicking(self):
        with tempfile.TemporaryDirectory() as root:
            ui = Mock()
            ui.context.directory = Path(root)
            ui.context.profile = 'Default'
            portrait = 'https://flow.google.com/asb/portrait=s512-rw'
            state = {'url': 'project', 'references': [{'kind': 'character', 'src': portrait, 'ready': True, 'disabled': False}]}
            ui.snapshot.return_value = state
            folder = Path(root) / 'references'
            folder.mkdir()
            key = hashlib.sha256(json.dumps(['Default','project','Character','character',None]).encode()).hexdigest()
            (folder / ('binding-' + key + '.json')).write_text(json.dumps({
                'kind': 'character', 'reference': {'src': portrait}, 'character_id': 'saved'}))
            value = self.app.bind(ui, 'Character', 'character')
            self.assertTrue(value['already_bound'])
            self.assertEqual(value['character_id'], 'saved')
            ui.click.assert_not_called()

    def test_character_fields_use_bulk_input_and_blur_before_waiting_for_save(self):
        ui = Mock()
        self.app.entities.character_field(ui, 'input', 'Character name')
        code = ui.execute.call_args.args[0]
        scope = {'cdp': Mock(), 'drain_events': Mock(), 'js': Mock(return_value=True),
                 'type_text': Mock(), 'wait_for_network_idle': Mock(return_value=True)}
        exec(code, scope)
        scope['type_text'].assert_called_once_with('Character name')
        scope['js'].assert_called_with('document.activeElement.blur()')
        scope['wait_for_network_idle'].assert_called_once_with(timeout=30, idle_ms=1000)

    def test_upload_activates_focused_menu_only_when_chooser_has_not_opened(self):
        for pointer_opens_chooser in (True, False):
            with self.subTest(pointer_opens_chooser=pointer_opens_chooser), tempfile.TemporaryDirectory() as root:
                directory = Path(root)
                source = directory / 'portrait.jpg'
                source.write_bytes(b'portrait')
                ui = Mock()
                ui.context.profile = 'Default'
                ui.read.side_effect = ['/project/p', False, True]
                opened = []
                keys = []
                assignments = []

                def click(selector, text=None):
                    if text == 'Upload' and pointer_opens_chooser:
                        opened.append(True)

                def key(value):
                    keys.append(value)
                    if value == 'Enter':
                        opened.append(True)

                def events():
                    if opened:
                        opened.clear()
                        return [{'method': 'Page.fileChooserOpened', 'params': {'backendNodeId': 7}}]
                    return []

                def cdp(method, **params):
                    if method == 'DOM.setFileInputFiles':
                        receipts = list((directory / 'references').glob('*.json'))
                        self.assertTrue(json.loads(receipts[0].read_text())['assignment_intent'])
                        assignments.append(params)

                def execute(code):
                    exec(code, {'flow_click': click, 'press_key': key, 'drain_events': events,
                                'cdp': cdp, 'js': lambda expression: True, 'wait': lambda seconds: None})

                ui.execute.side_effect = execute
                with patch.dict(self.app.upload.__globals__, {'upload_picker': Mock()}):
                    self.app.upload(ui, directory, str(source))
                self.assertEqual(keys.count('Enter'), int(not pointer_opens_chooser))
                self.assertEqual(len(assignments), 1)
                self.assertEqual(assignments[0]['backendNodeId'], 7)

    def test_upload_names_are_distinct_for_agents_sharing_a_project(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'portrait.jpg'
            source.write_bytes(b'same portrait')
            results = []
            for owner in ('agent-one', 'agent-two'):
                directory = Path(root) / owner
                directory.mkdir()
                ui = Mock()
                ui.context.profile = 'Default'
                ui.read.side_effect = ['/project/shared', False, True]
                with patch.dict(self.app.upload.__globals__, {'upload_picker': Mock()}):
                    results.append(self.app.upload(ui, directory, str(source)))
            self.assertEqual(results[0]['sha256'], results[1]['sha256'])
            self.assertNotEqual(results[0]['title'], results[1]['title'])

    def test_completed_historical_upload_retains_its_original_title(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            source = directory / 'portrait.jpg'
            source.write_bytes(b'portrait')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            files = directory / 'references'
            files.mkdir()
            key = hashlib.sha256(('Default/project/p' + digest).encode()).hexdigest()
            (files / (key + '.json')).write_text(json.dumps({'complete': True, 'title': digest + '.jpg'}))
            ui = Mock()
            ui.context.profile = 'Default'
            ui.read.return_value = '/project/p'
            result = self.app.upload(ui, directory, str(source))
            self.assertEqual(result['title'], digest + '.jpg')
            ui.execute.assert_not_called()

    def test_character_recovery_waits_for_voice_data_without_reassigning_it(self):
        entities = self.app.entities
        context = Mock()
        ui = Mock()
        url = 'https://flow.google.com/project/p/character/saved'
        ui.read.return_value = url
        params = {'name': 'Character', 'description': 'Adult character', 'voice': 'Saved voice'}
        source = 'https://flow-content.google/audio/voice-id'
        checkpoint = {'native_id': 'saved', 'stage': 'verifying', 'params': params,
                      'project': 'project', 'character_url': url, 'reference': {},
                      'voice': {'source': source}}
        state = {'id': 'saved', 'name': params['name'], 'description': params['description'],
                 'portrait': 'https://flow.google.com/asb/portrait=s512-rw', 'voice_text': ''}

        def wait(expression, timeout=20):
            if 'Saved voice' in expression:
                state['voice_text'] = 'voice_selection\nSaved voice\nplay_arrow'
                state['voice_audio'] = source

        ui.wait.side_effect = wait
        with patch.object(entities, 'character_state', side_effect=lambda ui: dict(state)), \
                patch.object(entities, 'character_field') as field, patch.object(entities, 'remember'):
            value = entities.finish_character(context, ui, checkpoint)
        self.assertEqual(value['status'], 'ok')
        field.assert_not_called()
        ui.click.assert_called_once_with('button.back-button')
        self.assertTrue(any(source in call.args[0] for call in ui.wait.call_args_list))

    def test_agent_reacquires_editor_replaced_by_reference_binding(self):
        ui = Mock()
        marker = {'active': False, 'reads': 0, 'prompt': ''}

        def read(expression):
            if 'setAttribute(\'data-hermes-flow-editor\'' in expression:
                marker.update(active=True, reads=marker['reads'] + 1)
                return '[data-hermes-flow-editor=active]'
            if expression == 'location.href':
                return 'https://flow.google.com/project/p'
            if '.innerText' in expression:
                self.assertTrue(marker['active'], 'Reference binding replaced the old editor')
                return marker['prompt']

        def bind(*args):
            marker['active'] = False
            return {'kind': 'character', 'character_id': 'character'}

        def observe(context, ui, checkpoint):
            checkpoint['request_id'] = 'native'
            return {'status': 'running'}

        ui.read.side_effect = read
        ui.fill.side_effect = lambda selector, prompt: marker.update(prompt=prompt)
        ui.snapshot.return_value = {'url': 'https://flow.google.com/project/p', 'ingredients': [],
                                    'references': [], 'frames': [], 'notices': [], 'tiles': []}
        group = lambda value: {'options': [{'value': value, 'selected': True}]}
        settings = {'mode': 'agent', 'groups': [group('9:16'), group('x1'), group('9:16'), group('x1')],
                    'models': [{'value': 'Model', 'selector': 'video'}], 'duration': None, 'approval': '2'}
        with patch.object(self.app, 'configure', return_value=settings), \
                patch.object(self.app, 'account', return_value={'credits': 99}), \
                patch.object(self.app, 'bind', side_effect=bind), \
                patch.object(self.app.entities, 'reference', return_value=None), \
                patch.object(self.app, 'observe_generation', side_effect=observe), \
                patch.object(self.app.shutil, 'which', return_value='/tool'):
            context = Mock(directory=Path(self.enterContext(tempfile.TemporaryDirectory())), profile='Default')
            value = self.app.generate(context, ui, 'generate_video', {
                'prompt': 'A quiet conversation', 'references': [{'kind': 'character', 'title': 'Character'}]})
        self.assertEqual(value['status'], 'running')
        self.assertEqual(marker['reads'], 2)
        ui.fill.assert_called_once()
        ui.click.assert_called_once_with('flow-generate-icon-button button', project='https://flow.google.com/project/p')

    def test_rebinding_saved_voice_checks_id_without_removing_the_chip(self):
        references = sys.modules[self.app.bind.__module__]
        with tempfile.TemporaryDirectory() as root:
            ui = Mock()
            ui.context.directory = Path(root)
            ui.context.profile = 'Default'
            chip = {'kind': 'voice', 'name': '', 'ready': True, 'disabled': False}
            ui.snapshot.return_value = {'url': 'project', 'references': [chip]}
            folder = Path(root) / 'references'
            folder.mkdir()
            key = hashlib.sha256(json.dumps(['Default','project','Voice','voice',None]).encode()).hexdigest()
            (folder / ('binding-' + key + '.json')).write_text(json.dumps({
                'kind': 'voice', 'media_id': 'saved', 'reference': chip}))
            with patch.object(references, 'voice_binding', return_value={'source': 'https://flow-content.google/audio/saved', 'text': 'Voice'}):
                value = self.app.bind(ui, 'Voice', 'voice')
            self.assertTrue(value['already_bound'])
            ui.click.assert_not_called()

    def test_handoff_uses_portable_references_remaining_count_and_one_destination(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Profile 2', job_id='job')
            context.checkpoint.side_effect = lambda value: (Path(root) / 'checkpoint.json').write_text(json.dumps(value))
            ui = Mock()
            ui.read.side_effect = ['https://flow.google.com/', True]
            reference = {'path': '/local/portrait.jpg', 'kind': 'image', 'slot': 'first'}
            packet = {'params': {'project': 'source', 'prompt': 'Original scene', 'count': 3},
                      'remaining': {'references': [reference], 'remaining_count': 1}}
            with patch.object(self.app, 'ensure', return_value=ui), \
                    patch.object(self.app, 'create_project', return_value={'url': 'https://flow.google.com/project/target'}) as create:
                first = self.app.handoff(context, packet)
                second = self.app.handoff(context, packet)
            create.assert_called_once()
            self.assertEqual(first['params'], second['params'])
            self.assertEqual(first['params']['references'], [reference])
            self.assertEqual(first['params']['count'], 1)
            self.assertEqual(first['params']['prompt'], 'Original scene')
            self.assertEqual(first['params']['project'], 'https://flow.google.com/project/target')
            self.assertEqual(packet['params']['project'], 'source')
            self.assertEqual(first['request']['state'], 'not_submitted')

    def test_handoff_preflight_preserves_original_local_references(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Profile 2', job_id='job')
            ui = Mock()
            ui.read.return_value = 'https://flow.google.com/'
            reference = {'path': '/local/portrait.jpg', 'kind': 'image'}
            with patch.object(self.app, 'ensure', return_value=ui), \
                    patch.object(self.app, 'create_project', return_value={'url': 'https://flow.google.com/project/target'}):
                result = self.app.handoff(context, {'params': {'references': [reference]}})
            self.assertEqual(result['params']['references'], [reference])

    def test_handoff_resume_uses_destination_preparation_without_source_observation(self):
        with patch.object(self.app, 'handoff', return_value={'status': 'ok'}) as handoff, \
                patch.object(self.app, 'observe_generation') as observe:
            packet = {'params': {'prompt': 'scene'}}
            self.app.resume(Mock(), {'phase': 'handoff', 'handoff': packet})
            handoff.assert_called_once()
            self.assertEqual(handoff.call_args.args[1], packet)
            observe.assert_not_called()

    def test_interrupted_destination_creation_captures_owned_native_url(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Profile 2', job_id='job')
            path = Path(root) / 'checkpoint.json'
            path.write_text(json.dumps({'job': 'job', 'operation': 'handoff', 'stage': 'create_intent',
                                       'profile': 'Profile 2', 'before': 'https://flow.google.com/', 'params': {}}))
            ui = Mock()
            ui.read.side_effect = ['https://flow.google.com/project/created', 'job']
            self.app.capture_destination(context, ui)
            saved = context.checkpoint.call_args.args[0]
            self.assertEqual(saved['stage'], 'prepared')
            self.assertEqual(saved['params']['project'], 'https://flow.google.com/project/created')
            self.assertEqual(self.app.local_state(context)['projects']['Profile 2'], 'https://flow.google.com/project/created')
            ui.click.assert_not_called()

    def test_unknown_destination_creation_is_preserved_without_navigation_or_recreation(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Profile 2', job_id='job')
            (Path(root) / 'checkpoint.json').write_text(json.dumps({
                'job': 'job', 'operation': 'handoff', 'stage': 'create_intent',
                'profile': 'Profile 2', 'before': 'https://flow.google.com/', 'params': {}}))
            ui = Mock()
            ui.read.side_effect = ['https://flow.google.com/project/other', 'another-job']
            with self.assertRaisesRegex(RuntimeError, 'original destination'):
                self.app.capture_destination(context, ui)
            ui.execute.assert_not_called()
            ui.click.assert_not_called()

    def test_created_destination_identity_is_checkpointed_before_title_edit(self):
        context = Mock()
        ui = Mock()
        ui.read.side_effect = ['/', 'https://flow.google.com/project/created']
        ui.fill.side_effect = RuntimeError('title editor changed')
        checkpoint = {'params': {}, 'stage': 'create_intent'}
        with patch.object(self.app, 'local_state', return_value={}), patch.object(self.app, 'save_state'):
            with self.assertRaisesRegex(RuntimeError, 'title editor'):
                self.app.create_project(context, ui, 'Continued project', checkpoint)
        self.assertEqual(checkpoint['stage'], 'prepared')
        self.assertEqual(checkpoint['params']['project'], 'https://flow.google.com/project/created')
        context.checkpoint.assert_called_once()

    def test_attached_voice_is_reconciled_without_a_binding_receipt(self):
        references = sys.modules[self.app.bind.__module__]
        with tempfile.TemporaryDirectory() as root:
            ui = Mock()
            ui.context.directory = Path(root)
            ui.context.profile = 'Default'
            ui.snapshot.return_value = {'url': 'project', 'references': [
                {'kind': 'voice', 'name': '', 'ready': True, 'disabled': False}]}
            with patch.object(references, 'voice_binding', return_value={
                    'source': 'https://flow-content.google/audio/existing', 'text': 'voice_selection\nWanted voice'}):
                result = self.app.bind(ui, 'Wanted voice', 'voice')
            self.assertEqual(result['media_id'], 'existing')
            self.assertTrue(result['already_bound'])
            self.assertEqual(len(list((Path(root) / 'references').glob('binding-*.json'))), 1)
            ui.click.assert_not_called()

    def test_selecting_another_voice_replaces_the_previous_voice(self):
        references = sys.modules[self.app.bind.__module__]
        with tempfile.TemporaryDirectory() as root:
            ui = Mock()
            ui.context.directory = Path(root)
            ui.context.profile = 'Default'
            state = {'url': 'project', 'ingredients': [], 'frames': [], 'references': [
                {'kind': 'voice', 'name': '', 'ready': True, 'disabled': False}]}
            ui.snapshot.return_value = state
            ui.read.side_effect = [['before'], None, False, ['after']]
            with patch.object(references, 'voice_binding', side_effect=[
                    {'source': 'https://flow-content.google/audio/old', 'text': 'Old voice'},
                    {'source': 'https://flow-content.google/audio/new', 'text': 'New voice'}]), \
                    patch.object(references, 'select_asset') as select:
                result = self.app.bind(ui, 'New voice', 'voice', expected={'id': 'new'})
            self.assertEqual(result['media_id'], 'new')
            select.assert_called_once_with(ui, 'New voice', 'voice')

    def test_quota_preflight_uses_native_price_and_allows_free_generation(self):
        for balance, quote, operation, refused in (
                (0, 'Pembuatan akan menggunakan 9 kredit', 'generate_video', True),
                (8, 'Pembuatan akan menggunakan 9 kredit', 'generate_video', True),
                (9, 'Pembuatan akan menggunakan 9 kredit', 'generate_video', False),
                (0, 'Pembuatan akan menggunakan 0 kredit', 'generate_image', False),
                (1000, 'Generation will use 1,050 credits', 'generate_video', True)):
            with self.subTest(balance=balance, quote=quote):
                ui = Mock()
                project = self.app.project_url('p')
                ui.read.side_effect = [project, 'editor', 'editor', 'scene']
                ui.snapshot.return_value = {'url': project, 'ingredients': [], 'references': [],
                                            'frames': [], 'tiles': [], 'notices': []}
                settings = {'mode': 'classic', 'groups': [], 'models': [],
                            'duration': None, 'approval': None, 'quote': quote}
                context = Mock(job_id='job', profile='Default',
                               directory=Path(self.enterContext(tempfile.TemporaryDirectory())))

                def observe(context, ui, checkpoint):
                    checkpoint['request_id'] = 'native'
                    return {'status': 'running'}

                with patch.object(self.app, 'configure', return_value=settings), \
                        patch.object(self.app, 'account', return_value={'credits': balance}), \
                        patch.object(self.app, 'observe_generation', side_effect=observe), \
                        patch.object(self.app.shutil, 'which', return_value='/tool'):
                    result = self.app.generate(context, ui, operation, {'prompt': 'scene'})
                if refused:
                    self.assertEqual(result['status'], 'quota_exhausted')
                    self.assertFalse(context.checkpoint.call_args.args[0]['submit_intent'])
                    ui.click.assert_not_called()
                else:
                    self.assertEqual(result['status'], 'running')
                    ui.click.assert_called_once_with('flow-generate-icon-button button', project=project)

    def test_source_retry_restores_project_model_and_only_prices_remaining_outputs(self):
        for balance, quote, visible, status in (
                (9, '9 credits', True, 'running'),
                (8, '9 credits', True, 'quota_exhausted'),
                (9, None, True, 'needs_inspection'),
                (9, '9 credits or 18 credits', True, 'needs_inspection'),
                (None, '9 credits', True, 'needs_inspection'),
                (9, '9 credits', False, 'needs_inspection')):
            with self.subTest(balance=balance, quote=quote, visible=visible):
                project = self.app.project_url('resumable-source')
                original_file = {'path': '/fixture/earlier.mp4'}
                ctx = Mock(directory=Path(self.enterContext(tempfile.TemporaryDirectory())),
                           job_id='job', profile='Profile 2')
                path = ctx.directory / 'checkpoint.json'
                ctx.checkpoint.side_effect = lambda value: path.write_text(json.dumps(value))
                original_settings = {'mode': 'classic', 'models': [{'selector': 'model', 'value': 'Original model'}],
                                     'selected': {'Aspect ratio': '9:16', 'Video resolution': '720p'},
                                     'duration': {'text': '5 seconds'}}
                output = {'id': 'already-collected', 'kind': 'video'}
                packet = {'operation': 'generate_video', 'params': {'project': 'earlier-account', 'prompt': 'scene'},
                          'source': {'profile': 'Profile 2', 'account': {'id': 'source-account'}},
                          'checkpoint': {'job': 'job', 'operation': 'generate_video', 'count': 2, 'project': project,
                                         'quota_evidence': 'Not enough credits', 'settings': original_settings,
                                         'files': [original_file], 'outputs': [output]},
                          'remaining': {'remaining_count': 1, 'completed': [original_file]}}
                prepared = self.app.prepare_source_retry(ctx, packet)
                self.assertEqual(prepared['status'], 'ok', prepared)
                self.assertEqual(prepared['params'], {'project': project, 'prompt': 'scene', 'count': 1,
                    'mode': 'classic', 'model': 'Original model', 'aspect': '9:16', 'resolution': '720p',
                    'duration': 5, 'references': []})
                self.assertEqual(packet['params']['project'], 'earlier-account')
                ui = Mock()
                ui.read.side_effect = [project, 'editor', 'editor', 'scene']
                ui.snapshot.return_value = {'url': project, 'ingredients': [], 'references': [],
                    'frames': [], 'tiles': [output] if visible else [], 'notices': [], 'quote': quote}
                native = {'mode': 'classic', 'groups': [], 'models': original_settings['models'],
                          'duration': None, 'approval': None, 'quote': 'stale price: 12 credits'}

                def observe(context, ui, checkpoint):
                    self.assertEqual(checkpoint['baseline'], ['already-collected'])
                    self.assertEqual(checkpoint['continued_files'], [original_file])
                    self.assertEqual(checkpoint['count'], 1)
                    checkpoint['request_id'] = 'new-native-id'
                    return {'status': 'running'}

                with patch.object(self.app, 'configure', return_value=native), \
                        patch.object(self.app, 'account', return_value={'id': 'source-account', 'credits': balance}), \
                        patch.object(self.app, 'observe_generation', side_effect=observe), \
                        patch.object(self.app.shutil, 'which', return_value='/tool'):
                    result = self.app.generate(ctx, ui, 'generate_video', prepared['params'])
                self.assertEqual(result['status'], status, result)
                if status == 'running':
                    ui.click.assert_called_once_with('flow-generate-icon-button button', project=project)
                else:
                    ui.click.assert_not_called()
                if status == 'needs_inspection':
                    blocked = json.loads(path.read_text())
                    self.assertEqual(result['request']['state'], 'not_submitted')
                    self.assertEqual(self.app.resume(ctx, {'checkpoint': blocked}), result)
                if status == 'quota_exhausted':
                    self.assertEqual(result['handoff']['remaining_count'], 1)
                    self.assertEqual(result['handoff']['completed'], [original_file])
                    self.assertEqual(json.loads(path.read_text())['prior_source_outputs'], [output])

    def test_source_retry_does_not_accept_an_old_output_when_its_tile_gains_an_id(self):
        project = self.app.project_url('source')
        ctx, ui = Mock(), Mock()
        ui.snapshot.return_value = {'url': project, 'notices': [],
            'tiles': [{'id': 'old-result', 'kind': 'video', 'src': 'new-source', 'ready': True}]}
        checkpoint = {'project': project, 'kind': 'video', 'count': 1, 'settings': {},
                      'baseline': ['old-poster'],
                      'prior_source_outputs': [{'id': 'old-result', 'key': 'old-poster'}]}
        result = self.app.observe_generation(ctx, ui, checkpoint)
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual(result['data']['outputs'], [])
        ctx.accepted.assert_not_called()

    def test_partial_quota_refusal_collects_completed_outputs_before_handoff(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root))
            ui = Mock()
            project = self.app.project_url('source')
            ui.snapshot.return_value = {'url': project, 'tiles': [{'kind': 'image', 'id': 'native', 'ready': True}],
                                        'notices': ['Not enough credits']}
            ui.read.side_effect = [['Ukuran asli'], '/project/source']
            checkpoint = {'operation': 'generate_image', 'project': 'source', 'prompt': 'scene',
                          'kind': 'image', 'count': 3, 'baseline': [], 'notices_before': [],
                          'settings': {'mode': 'classic'}, 'portable_references': [{'path': '/source/reference.png'}]}
            file = {'path': '/source/completed.png'}
            with patch.object(self.app, 'open_output', return_value=project + '/edit/native'), \
                    patch.object(self.app, 'collect', return_value=file), \
                    patch.object(self.app, 'verify', return_value=file):
                result = self.app.observe_generation(context, ui, checkpoint)
            self.assertEqual(result['status'], 'quota_exhausted')
            self.assertEqual(result['request']['id'], 'native')
            self.assertTrue(result['request']['terminal'])
            self.assertEqual(result['handoff']['remaining_count'], 2)
            self.assertEqual(result['handoff']['completed'], [file])
            self.assertIn('/source/completed.png', result['handoff']['files'])

    def test_quota_notice_preserves_pending_source_outputs(self):
        context = Mock()
        ui = Mock()
        ui.snapshot.return_value = {'url': self.app.project_url('source'),
                                    'tiles': [{'kind': 'image', 'id': 'native', 'ready': False}],
                                    'notices': ['Not enough credits']}
        checkpoint = {'operation': 'generate_image', 'project': 'source', 'kind': 'image', 'count': 2,
                      'baseline': [], 'notices_before': [], 'settings': {}}
        result = self.app.observe_generation(context, ui, checkpoint)
        self.assertEqual(result['status'], 'running')
        self.assertEqual(result['request']['id'], 'native')
        self.assertNotIn('handoff', result)

    def test_pending_download_preserves_the_request_and_collects_without_another_click(self):
        with tempfile.TemporaryDirectory() as root:
            context, ui = Mock(directory=Path(root)), Mock()
            project = self.app.project_url('source')
            ui.snapshot.return_value = {'url': project, 'tiles': [
                {'kind': 'image', 'id': 'native', 'ready': True}], 'notices': []}
            ui.read.side_effect = [['Original size'], '/project/source']
            checkpoint = {'operation': 'generate_image', 'project': 'source', 'prompt': 'fixture',
                          'kind': 'image', 'count': 1, 'baseline': [], 'notices_before': [],
                          'settings': {'mode': 'classic'}, 'request_id': 'accepted', 'credits_before': 10}
            receipt = Path(root) / 'downloads' / 'native.json'
            file = {'path': '/fixture/native.png'}
            with patch.object(self.app, 'open_output', return_value=project + '/edit/native') as open_output, \
                    patch.object(self.app, 'collect', side_effect=[{'pending': True}, file]) as collect, \
                    patch.object(self.app, 'verify', return_value=file), \
                    patch.object(self.app, 'account', return_value={'credits': 5}):
                pending = self.app.observe_generation(context, ui, checkpoint)
                receipt.parent.mkdir()
                receipt.write_text(json.dumps({'guid': 'fixture-guid'}))
                done = self.app.observe_generation(context, ui, checkpoint)
            self.assertEqual(pending['status'], 'running')
            self.assertEqual(pending['request'], {'state': 'accepted', 'id': 'accepted'})
            self.assertEqual(done['request'], {'state': 'completed', 'id': 'accepted'})
            self.assertEqual(done['data']['files'], [file])
            open_output.assert_called_once()
            self.assertTrue(collect.call_args_list[0].args[3])
            self.assertEqual(collect.call_args_list[1].args[3], '')

    def test_quota_notice_cannot_end_an_accepted_job_with_missing_results(self):
        for show_completed in (False, True):
            with self.subTest(show_completed=show_completed):
                context, ui = Mock(), Mock()
                completed = {'kind': 'image', 'id': 'done', 'ready': True}
                pending = {'kind': 'image', 'id': 'pending', 'ready': False}
                checkpoint = {'project': 'source', 'kind': 'image', 'count': 3, 'baseline': [],
                              'outputs': [completed, pending], 'request_id': 'native'}
                ui.snapshot.return_value = {'url': self.app.project_url('source'),
                                            'tiles': [completed.copy()] if show_completed else [],
                                            'notices': ['Not enough credits']}
                with patch.object(self.app, 'collect') as collect:
                    result = self.app.observe_generation(context, ui, checkpoint)
                self.assertEqual(result['status'], 'needs_inspection')
                self.assertEqual(result['request'], {'state': 'accepted', 'id': 'native'})
                self.assertEqual([tile['id'] for tile in checkpoint['outputs']], ['done', 'pending'])
                self.assertNotIn('quota_evidence', checkpoint)
                self.assertNotIn('handoff', result)
                context.checkpoint.assert_called_once()
                collect.assert_not_called()

    def test_accepted_receipt_without_saved_tiles_is_not_terminal_on_generic_quota(self):
        ui = Mock()
        ui.snapshot.return_value = {'url': self.app.project_url('source'), 'tiles': [],
                                    'notices': ['Not enough credits']}
        checkpoint = {'project': 'source', 'kind': 'image', 'count': 1, 'baseline': [],
                      'request_id': 'native'}
        result = self.app.observe_generation(Mock(), ui, checkpoint)
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual(result['request'], {'state': 'accepted', 'id': 'native'})
        self.assertNotIn('handoff', result)

    def test_missing_source_tile_does_not_lose_other_newly_observed_outputs(self):
        ui, context = Mock(), Mock()
        first = {'kind': 'image', 'id': 'first', 'ready': False}
        second = {'kind': 'image', 'id': 'second', 'ready': False}
        state = {'url': self.app.project_url('source'), 'notices': []}
        ui.snapshot.side_effect = [{**state, 'tiles': [second.copy()]},
                                   {**state, 'tiles': [first.copy(), second.copy()]}]
        checkpoint = {'project': 'source', 'kind': 'image', 'count': 3, 'baseline': [],
                      'outputs': [first], 'request_id': 'first', 'settings': {}}

        pending = self.app.observe_generation(context, ui, checkpoint)
        self.assertEqual(pending['status'], 'needs_inspection')
        self.assertEqual([tile['id'] for tile in checkpoint['outputs']], ['first', 'second'])
        resumed = self.app.observe_generation(context, ui, checkpoint)
        self.assertEqual(resumed['status'], 'running')
        self.assertEqual(resumed['request']['id'], 'first')

    def test_video_upload_recovery_uses_native_stem_without_reuploading(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            source = directory / 'clip.mp4'
            source.write_bytes(b'video')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            files = directory / 'references'
            files.mkdir()
            local = files / (digest + '-owner.mp4')
            local.write_bytes(source.read_bytes())
            key = hashlib.sha256(('Default/project/p' + digest).encode()).hexdigest()
            (files / (key + '.json')).write_text(json.dumps({
                'version': 2, 'complete': False, 'assignment_intent': True,
                'path': str(local), 'title': local.name}))
            ui = Mock()
            ui.context.profile = 'Default'
            ui.read.return_value = '/project/p'
            finder = Mock()
            with patch.dict(self.app.upload.__globals__, {'upload_picker': Mock(), 'find_asset': finder}):
                result = self.app.upload(ui, directory, str(source))
            self.assertEqual(result['title'], local.stem)
            self.assertEqual(result['filename'], local.name)
            self.assertEqual(result['path'], str(local))
            finder.assert_called_once_with(ui, local.stem)
            ui.click.assert_not_called()

    def test_complete_video_receipt_preserves_the_local_file_extension(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            source = directory / 'clip.mp4'
            source.write_bytes(b'video')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            files = directory / 'references'
            files.mkdir()
            key = hashlib.sha256(('Default/project/p' + digest).encode()).hexdigest()
            (files / (key + '.json')).write_text(json.dumps({
                'complete': True, 'title': digest, 'filename': digest + '.mp4'}))
            ui = Mock()
            ui.context.profile = 'Default'
            ui.read.return_value = '/project/p'
            result = self.app.upload(ui, directory, str(source))
            self.assertTrue(result['path'].endswith('.mp4'))
            self.assertEqual(result['title'], digest)
            ui.execute.assert_not_called()

    def test_media_binding_waits_for_image_inside_the_new_chip(self):
        references = sys.modules[self.app.bind.__module__]
        ui = Mock()
        references.wait_for_media(ui, 'image')
        expression = ui.wait.call_args.args[0]
        self.assertIn('chips.length>0', expression)
        self.assertIn("e.querySelector('img')", expression)
        self.assertIn('i?.complete&&i.naturalWidth>0', expression)


    def test_switch_to_classic_closes_agent_panel_before_toggling(self):
        ui = self.app.UI(Mock())
        ui.snapshot = Mock(return_value={'mode': 'agent'})
        ui.read = Mock(return_value=True)
        ui.click = Mock()
        ui.wait = Mock()
        ui.mode('classic')
        self.assertIn('flow-agent-panel', ui.click.call_args_list[0].args[0])
        self.assertEqual(ui.click.call_args_list[1].args,
                         ('button.agent-mode-chip, flow-agent-mode-switch button',))
        self.assertIn('flow-agent-panel', ui.wait.call_args_list[0].args[0])

    def test_empty_error_retains_exception_type(self):
        with patch.object(self.app, 'ensure', side_effect=StopIteration):
            value = self.app.run(Mock(), 'inspect', {})
        self.assertEqual(value['message'], 'StopIteration')
        self.assertEqual(value['error']['type'], 'StopIteration')

    def test_voice_metadata_survives_character_voice_link_readback(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Default')
            voice = {'kind': 'voice', 'id': 'native', 'project': 'project', 'name': 'Voice',
                     'base': 'Achird', 'dialogue': 'Sample', 'performance': 'Calm'}
            self.app.entities.remember(context, voice)
            self.app.entities.remember(context, {key: voice[key] for key in ('kind', 'id', 'project', 'name')})
            value = self.app.entities.reference(context, 'voice', 'Voice', 'project')
            self.assertEqual(self.app.entities.definition(context, value)['base'], 'Achird')

    def test_handoff_requires_creation_definition_for_native_voice(self):
        result = self.app.handoff(Mock(), {'params': {'references': [{'kind': 'voice', 'title': 'Voice'}]}})
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertIn('creation definition', result['message'])

    def test_child_entity_receipt_never_accepts_parent_video_request(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Mock(directory=Path(root), profile='Profile 2', job_id='parent')
            position = {'active_entity': 'voice-0'}
            child = self.app.preparation.EntityContext(parent, position, 'voice-0')
            child.checkpoint({'native_id': 'voice-id'})
            child.accepted('voice-id')
            parent.accepted.assert_not_called()
            self.assertEqual(json.loads((child.directory / 'checkpoint.json').read_text())['native_id'], 'voice-id')
            self.assertEqual(parent.checkpoint.call_args.args[0], position)

    def test_prepared_entity_recovery_clears_stale_active_child_without_creation(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Mock(directory=Path(root), profile='Profile 2', job_id='parent')
            position = {'active_entity': 'voice-0'}
            child = self.app.preparation.EntityContext(parent, position, 'voice-0')
            data = {'kind': 'voice', 'id': 'saved', 'name': 'Voice', 'project': 'target'}
            (child.directory / 'result.json').write_text(json.dumps(data))
            with patch.object(self.app.entities, 'create_voice') as create:
                value = self.app.preparation.prepare(parent, position, 'voice-0', 'voice', {})
            self.assertEqual(value['id'], 'saved')
            self.assertNotIn('active_entity', position)
            self.assertEqual(self.app.entities.reference(parent, 'voice', 'Voice', 'target')['id'], 'saved')
            create.assert_not_called()

    def test_separate_generation_jobs_never_share_prepared_entity_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Mock(directory=Path(root), profile='Profile 2', job_id='first')
            first = self.app.preparation.EntityContext(parent, {}, 'voice-0')
            parent.job_id = 'second'
            second = self.app.preparation.EntityContext(parent, {}, 'voice-0')
            self.assertNotEqual(first.directory, second.directory)
            self.assertNotEqual(first.job_id, second.job_id)

    def test_partial_outputs_from_prior_accounts_are_kept_in_next_handoff(self):
        context = Mock()
        checkpoint = {'operation': 'generate_video', 'count': 2,
                      'continued_files': [{'path': '/first.mp4'}], 'files': [{'path': '/second.mp4'}]}
        value = self.app.quota_rejection(context, checkpoint, 'Native credit refusal')
        self.assertEqual(value['handoff']['remaining_count'], 1)
        self.assertEqual(value['handoff']['files'], ['/first.mp4', '/second.mp4'])

    def test_extra_unattributed_outputs_never_trigger_terminal_quota_handoff(self):
        ui = Mock()
        ui.snapshot.return_value = {'url': self.app.project_url('source'), 'tiles': [
            {'kind': 'image', 'id': 'one'}, {'kind': 'image', 'id': 'two'}], 'notices': ['Not enough credits']}
        value = self.app.observe_generation(Mock(), ui, {'project': 'source', 'kind': 'image',
                                                         'baseline': [], 'count': 1})
        self.assertEqual(value['status'], 'needs_inspection')
        self.assertNotIn('handoff', value)

    def test_upload_picker_handles_rights_dialog_that_appears_after_first_probe(self):
        module = sys.modules[self.app.upload.__module__]
        ui = Mock()
        ui.read.return_value = []
        with patch.object(module, 'acknowledge_upload', side_effect=[False, True]) as acknowledge, \
                patch.object(module, 'picker', side_effect=[RuntimeError('Modal covers picker'), None]) as picker:
            module.upload_picker(ui)
        self.assertEqual(acknowledge.call_count, 2)
        self.assertEqual(picker.call_count, 2)
        ui.execute.assert_not_called()

    def test_upload_picker_does_not_hide_an_unrelated_failure(self):
        module = sys.modules[self.app.upload.__module__]
        with patch.object(module, 'acknowledge_upload', return_value=False), \
                patch.object(module, 'picker', side_effect=RuntimeError('Unrelated failure')) as picker:
            with self.assertRaisesRegex(RuntimeError, 'Unrelated failure'):
                module.upload_picker(Mock())
        picker.assert_called_once()

    def test_zero_credit_agent_uses_live_model_price_then_restores_agent(self):
        ui = Mock()
        group = lambda value: {'options': [{'value': value, 'selected': True}]}
        agent = {'mode': 'agent', 'groups': [group('9:16'), group('x1'), group('9:16'), group('x1')],
                 'models': [{'selector': 'video', 'value': 'Native model'}], 'duration': None, 'approval': '2'}
        project = self.app.project_url('p')
        ui.snapshot.return_value = {'url': project, 'ingredients': [], 'references': [],
                                    'frames': [], 'tiles': [], 'notices': []}
        prompt = 'Create exactly 1 video output(s) now using Native model. The output aspect ratio must be 9:16. scene'
        ui.read.side_effect = [project, 'editor', 'editor', prompt]
        context = Mock(directory=Path(self.enterContext(tempfile.TemporaryDirectory())), profile='Default', job_id='job')
        params = {'mode': 'agent', 'prompt': 'scene'}
        with patch.object(self.app, 'configure', side_effect=[agent, {'quote': 'Uses 9 credits'}, agent]) as configure, \
                patch.object(self.app, 'account', return_value={'credits': 0}), \
                patch.object(self.app.shutil, 'which', return_value='/tool'):
            value = self.app.generate(context, ui, 'generate_video', params)
        self.assertEqual(value['status'], 'quota_exhausted')
        self.assertIn('native classic composer', value['quota']['evidence'])
        self.assertEqual(configure.call_args.args[1], params)
        ui.click.assert_not_called()

    def test_portable_character_definition_includes_original_voice_recipe(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), profile='Default')
            self.app.entities.remember(context, {'kind': 'voice', 'id': 'audio', 'project': 'p',
                'name': 'Voice', 'base': 'Achird', 'dialogue': 'Sample', 'performance': 'Calm'})
            value = self.app.entities.definition(context, {'kind': 'character', 'name': 'Actor',
                'reference': {'path': '/portrait.jpg'}, 'voice': {'name': 'Voice', 'id': 'audio'}})
            self.assertEqual(value['path'], '/portrait.jpg')
            self.assertEqual(value['voice_definition']['base'], 'Achird')

    def test_cached_source_quota_still_recovers_saved_source_voice_definition(self):
        with tempfile.TemporaryDirectory() as root:
            context = Mock(directory=Path(root), job_id='job', profile='Default')
            source = 'https://flow.google.com/project/source'
            self.app.entities.remember(context, {'kind': 'voice', 'id': 'audio', 'project': source,
                'name': 'Voice', 'base': 'Achird', 'dialogue': 'Sample', 'performance': 'Calm'})
            context.profile = 'Profile 2'
            ui = Mock()
            ui.read.return_value = 'https://flow.google.com/'
            packet = {'source': {'profile': 'Default'}, 'params': {
                'project': source, 'references': [{'kind': 'voice', 'title': 'Voice'}]}}
            with patch.object(self.app, 'ensure', return_value=ui), patch.object(self.app, 'configure'), \
                    patch.object(self.app, 'create_project', return_value={'url': 'https://flow.google.com/project/target'}), \
                    patch.object(self.app.preparation, 'references', return_value=[]):
                value = self.app.handoff(context, packet)
            self.assertEqual(value['params']['references'][0]['definition']['base'], 'Achird')

    def test_classic_uses_updated_native_quote_after_reference_binding(self):
        context = Mock(directory=Path(self.enterContext(tempfile.TemporaryDirectory())), profile='Default', job_id='job')
        ui = Mock()
        project = self.app.project_url('p')
        ui.read.side_effect = [project, 'editor', project, 'editor', 'scene']
        ui.snapshot.return_value = {'url': project, 'ingredients': [], 'references': [],
                                    'frames': [], 'tiles': [], 'notices': [], 'quote': 'Uses 9 credits'}
        settings = {'mode': 'classic', 'groups': [], 'models': [], 'duration': None,
                    'approval': None, 'quote': 'Uses 15 credits'}

        def observe(context, ui, checkpoint):
            checkpoint['request_id'] = 'native'
            return {'status': 'running'}

        with patch.object(self.app, 'configure', return_value=settings), \
                patch.object(self.app, 'account', return_value={'credits': 9}), \
                patch.object(self.app, 'bind', return_value={'kind': 'image'}), \
                patch.object(self.app, 'observe_generation', side_effect=observe), \
                patch.object(self.app.shutil, 'which', return_value='/tool'):
            value = self.app.generate(context, ui, 'generate_video', {
                'prompt': 'scene', 'references': [{'kind': 'image', 'title': 'Portrait'}]})
        self.assertEqual(value['status'], 'running')
        self.assertEqual(context.checkpoint.call_args.args[0]['quota_quote'], 'Uses 9 credits')
        ui.click.assert_called_once_with('flow-generate-icon-button button', project=project)


if __name__ == '__main__':
    unittest.main()
