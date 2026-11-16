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

    def test_no_submit_after_invalid_prompt(self):
        ui = Mock()
        with self.assertRaises(ValueError):
            self.app.generate(Mock(), ui, 'generate_video', {'prompt': ''})
        ui.click.assert_not_called()

    def test_resume_observes_source_without_generation(self):
        context = Mock(job_id='job')
        record = {'params': {}, 'attempts': [{'request_id': 'native'}], 'checkpoint': {
            'job': 'job', 'submit_intent': True, 'request_id': 'native', 'project': 'source'}}
        with patch.object(self.app, 'ensure') as ensure, \
                patch.object(self.app, 'observe_generation', return_value={'status': 'running'}) as observe, \
                patch.object(self.app, 'generate') as generate:
            self.assertEqual(self.app.resume(context, record)['status'], 'running')
            ensure.assert_called_once_with(context, {'project': 'source'})
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
        ui.model('agent', 'video')
        self.assertEqual(ui.click.call_args.args, ('[role=menuitem]', 'Native model'))
        ui.execute.assert_not_called()

    def test_result_open_uses_direct_container_when_nested_prompt_has_container(self):
        ui = Mock()
        ui.read.side_effect = [['exact prompt'], 'https://flow.google.com/project/id/edit/native']
        self.app.open_output(ui, {'kind': 'image', 'id': 'media'}, 'exact prompt', 'classic')
        ui.click.assert_called_once_with('flow-image-tile:has([data-media-id="media"]) > .container')

    def test_pending_tile_refreshes_readiness_without_overwriting_it_from_checkpoint(self):
        ui = Mock()
        ui.snapshot.return_value = {'tiles': [{'kind': 'image', 'id': 'native', 'ready': True}], 'notices': []}
        context = Mock()
        checkpoint = {'baseline': [], 'kind': 'image', 'request_id': 'native', 'count': 2,
                      'outputs': [{'kind': 'image', 'id': 'native', 'ready': False}],
                      'project': 'source', 'settings': {'mode': 'classic'}}
        self.assertEqual(self.app.observe_generation(context, ui, checkpoint)['status'], 'running')
        self.assertTrue(checkpoint['outputs'][0]['ready'])

    def test_old_quota_notice_does_not_trigger_rolling_for_this_request(self):
        text = 'Not enough credits'
        ui = Mock()
        ui.snapshot.return_value = {'tiles': [], 'notices': [text]}
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
            with patch.dict(self.app.upload.__globals__, {'picker': Mock(), 'find_asset': finder}):
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
        with patch.object(references, 'voice_binding', return_value='https://flow-content.google/audio/other?token=temp'):
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
                with patch.dict(self.app.upload.__globals__, {'picker': Mock()}):
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
                with patch.dict(self.app.upload.__globals__, {'picker': Mock()}):
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
            value = self.app.generate(Mock(), ui, 'generate_video', {
                'prompt': 'A quiet conversation', 'references': [{'kind': 'character', 'title': 'Character'}]})
        self.assertEqual(value['status'], 'running')
        self.assertEqual(marker['reads'], 2)
        ui.fill.assert_called_once()
        ui.click.assert_called_once_with('flow-generate-icon-button button')

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
            with patch.object(references, 'voice_binding', return_value='https://flow-content.google/audio/saved'):
                value = self.app.bind(ui, 'Voice', 'voice')
            self.assertTrue(value['already_bound'])
            ui.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
