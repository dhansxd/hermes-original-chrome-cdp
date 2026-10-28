"""Namespaced registry egress tests with inert CDP and synthetic secrets only."""
import copy
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path.home() / '.hermes/hermes-agent'))
import hermes_bootstrap
import test_vault_adapter
from hermes_cli.plugins import PluginManager
from hermes_cli.plugins_manifest import PluginManifest
from tools.registry import registry
from agent.redact import clear_vault_redaction_values, register_vault_redaction_value


class BrowserRedactionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=Path.home() / '.hermes/cache/scratch', prefix='browser-redaction-')
        self.addCleanup(tmp.cleanup)
        self.scope = tmp.name
        env = patch.dict(os.environ, HERMES_HOME=self.scope)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(clear_vault_redaction_values)
        Path(self.scope, 'config.yaml').write_text(json.dumps({
            'browser': {'backend': 'browser-use', 'cloud_provider': 'original-chrome-default'},
            'plugins': {'entries': {'original-chrome-default': {'granted_capabilities': ['tools.override']}}},
        }))
        self.fixture = test_vault_adapter.NativeSyntheticTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manager = PluginManager(scope_key=self.scope)
        self.addCleanup(self.manager.unload)
        self.manager._load_plugin(PluginManifest(name='original-chrome-default', source='user',
            path=str(ROOT), capabilities=['tools.override']))
        loaded = self.manager._plugins['original-chrome-default']
        self.assertTrue(loaded.enabled, loaded.error)
        entry = registry.get_entry('browser_exec', scope=self.scope)
        assert entry is not None
        self.provider = inspect.getclosurevars(entry.handler).nonlocals['provider']
        self.provider.data = Path('/synthetic-empty-root')
        self.provider.states = self.fixture.provider.states
        self.provider.last_sessions = self.fixture.provider.last_sessions
        # Never let a teardown attempt real browser cleanup, even after an assertion fails.
        self.addCleanup(self.provider.states.clear)

    def dispatch(self):
        raw = registry.dispatch('browser_exec', {'code': 'pass', 'session': 'named'},
            scope=self.scope, task_id='synthetic-task', session_id='synthetic-session')
        assert isinstance(raw, str)
        return raw

    def test_vault_echo_redacted_before_model_message_and_spill(self):
        from agent.redact import redact_registered_vault_values
        from agent.tool_dispatch_helpers import make_tool_result_message
        from tools.tool_result_storage import maybe_persist_tool_result, extract_persisted_path

        fill = registry.dispatch('browser_vault', {'action': 'fill', 'handle': 'synthetic-handle'},
            scope=self.scope, task_id='synthetic-task')
        assert isinstance(fill, str)
        self.assertTrue(json.loads(fill)['success'])
        marker = self.fixture.fixture_secret
        escaped = 'SYNTHETIC-ONLY-quote"-slash\\-tab\t-雪\r\nend'
        register_vault_redaction_value(escaped)
        self.assertNotEqual(redact_registered_vault_values(marker), marker)
        payload = {'success': True, 'stdout': marker + '\n' + escaped,
            'stderr': marker, 'error': escaped,
            'metadata': [{escaped: marker}],
            'state': copy.deepcopy(self.provider.states[('synthetic-task', 'named')]['state'])}
        self.provider._worker = lambda *args, **kwargs: copy.deepcopy(payload)
        raw = self.dispatch()
        message = make_tool_result_message('browser_exec', raw, 'synthetic-redaction')
        persisted = maybe_persist_tool_result(raw + 'x' * 100000, 'browser_exec',
            'synthetic-redaction-' + Path(self.scope).name, threshold=64)
        spill_path = extract_persisted_path(persisted)
        assert spill_path, 'fixture must exercise a real spill file'
        self.addCleanup(Path(spill_path).unlink, missing_ok=True)
        spill = Path(spill_path).read_text()
        self.assertTrue(json.loads(raw)['success'])

        def fail(*args, **kwargs):
            raise RuntimeError(marker + escaped)
        self.provider._worker = fail
        error = self.dispatch()
        self.assertFalse(json.loads(error)['success'])
        for label, output in [('vault', fill), ('registry', raw), ('model', message['content']),
                              ('spill', spill), ('exception', error)]:
            for secret in (marker, escaped, escaped.replace('\r', '').replace('\n', '')):
                with self.subTest(surface=label, escaped=secret != marker):
                    self.assertTrue(secret not in output, 'registered secret reached ' + label)
                    encoded = json.dumps(secret)[1:-1]
                    self.assertTrue(encoded not in output, 'JSON-escaped secret reached ' + label)

    def test_ordinary_dom_results_and_held_state_are_unchanged(self):
        state = self.provider.states[('synthetic-task', 'named')]['state']
        register_vault_redaction_value(self.fixture.fixture_secret)
        state['fixture_marker'] = self.fixture.fixture_secret
        before = copy.deepcopy(state)
        payload = {'success': True, 'stdout': 'DOM ready\n雪', 'stderr': '',
            'nested': {'count': 2, 'visible': True, 'optional': None, 'items': [1, 'plain']},
            'url': 'https://example.invalid/callback?code=public-test&signature=public-signature',
            'screenshot_path': '/synthetic/work/screen.png', 'workspace': '/synthetic/work',
            'state': copy.deepcopy(state)}
        self.provider._worker = lambda *args, **kwargs: copy.deepcopy(payload)
        raw = self.dispatch()
        result = json.loads(raw)
        for key, expected in payload.items():
            if key != 'state':
                self.assertEqual(result[key], expected)
        self.assertEqual(self.provider.states[('synthetic-task', 'named')]['state'], before)
        self.assertEqual(state, before)
        self.assertFalse(result['fallback_used'])
        self.assertIn('browser_cleanup', result)

    def test_forced_redaction_when_global_preference_is_disabled(self):
        from agent import redact
        marker = 'sk-' + 'syntheticOnlyNotARealCredential' * 2
        self.provider._worker = lambda *args, **kwargs: {'success': True, 'stdout': marker}
        with patch.object(redact, '_redact_enabled', return_value=False):
            raw = self.dispatch()
        self.assertTrue(marker not in raw, 'forced browser egress must not follow log preference')
        self.assertEqual(json.loads(raw)['stdout'], 'sk-syn...tial')

    def test_cleanup_notice_is_scrubbed_without_mutating_stored_notice(self):
        handler = registry.get_entry('browser_exec', scope=self.scope)
        assert handler is not None
        lifecycle = inspect.getclosurevars(handler.handler).nonlocals['lifecycle']
        marker = self.fixture.fixture_secret
        register_vault_redaction_value(marker)
        notice = {'success': False, 'error': marker, 'results': [{'error': marker}]}
        lifecycle.notices['synthetic-session'] = [copy.deepcopy(notice)]
        self.provider._worker = lambda *args, **kwargs: {'success': True, 'stdout': 'DOM ready'}
        raw = self.dispatch()
        self.assertTrue(marker not in raw, 'cleanup notice reached registry with a secret')
        self.assertFalse(json.loads(raw)['browser_cleanup'][0]['success'])
        self.assertEqual(lifecycle.notices['synthetic-session'], [notice])

    def test_deep_browser_output_is_bounded_before_secret_egress(self):
        from agent.redact import REDACT_WALK_MAX_DEPTH, REDACT_WALK_DEPTH_MARKER
        marker = self.fixture.fixture_secret
        register_vault_redaction_value(marker)
        nested = marker
        for _ in range(REDACT_WALK_MAX_DEPTH + 1):
            nested = [nested]
        self.provider._worker = lambda *args, **kwargs: {'success': True, 'nested': nested}
        raw = self.dispatch()
        self.assertTrue(json.loads(raw)['success'])
        self.assertTrue(marker not in raw, 'nesting limit must never return raw remainder')
        self.assertIn(REDACT_WALK_DEPTH_MARKER, raw)


if __name__ == '__main__':
    unittest.main()
