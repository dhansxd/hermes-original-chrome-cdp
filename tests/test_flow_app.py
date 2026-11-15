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
                          'upload', 'bind_reference'})

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


if __name__ == '__main__':
    unittest.main()
