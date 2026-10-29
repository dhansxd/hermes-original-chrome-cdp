"""Exercise the real worker with a fake CDP transport and disposable workspace."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker import run, helper_namespace


class FakeWire:
    def __init__(self):
        self.calls = []
        self.url = 'https://example.test'
        self.closed = False

    def __call__(self, method, params=None, session=None):
        params = params or {}
        self.calls.append((method, copy.deepcopy(params), session))
        if method == 'Target.getTargets':
            return {'targetInfos': [
                {'targetId': 'own', 'browserContextId': 'ctx', 'type': 'page', 'url': self.url},
                {'targetId': 'manual', 'browserContextId': 'ctx', 'type': 'page', 'url': 'https://manual.test'}]}
        if method == 'Browser.getWindowForTarget':
            assert params['targetId'] == 'own'
            return {'windowId': 5}
        if method == 'Target.attachToTarget':
            assert params['targetId'] == 'own'
            return {'sessionId': 'own-session'}
        if method == 'Target.setDiscoverTargets':
            return {}
        if method == 'Page.navigate':
            self.url = params['url']
            return {'frameId': 'own-frame'}
        if method == 'Runtime.evaluate':
            assert session == 'own-session'
            return {'result': {'value': {'text': 'Visible fixture text', 'controls': []}}}
        raise AssertionError('unexpected CDP command: ' + method)

    def close(self):
        self.closed = True


class WorkerPolicyTests(unittest.TestCase):
    def request(self, folder, code):
        return {'workspace': folder, 'profile': '/synthetic/Default', 'code': code,
                'state': {'current': 'own', 'context': 'ctx', 'owned': {'own': 5},
                          'verified': True, 'baseline': ['manual']}}

    def test_worker_uses_owned_page_without_loading_workspace_python(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'agent_helpers.py').write_text("raise AssertionError('untrusted local Python ran')")
            wire = FakeWire()
            result = run(self.request(folder, "goto_url('https://next.test'); print(read_page())"), transport=wire)
            self.assertTrue(result['success'], result)
            self.assertIn('Visible fixture text', result['stdout'])
            self.assertTrue(wire.closed)
            targets = [p['targetId'] for _, p, _ in wire.calls if 'targetId' in p]
            self.assertTrue(targets)
            self.assertEqual(set(targets), {'own'})

    def test_invalid_source_never_constructs_wire_or_reads_workspace(self):
        with patch('worker.Wire', side_effect=AssertionError('must not connect')) as wire:
            result = run({'code': "goto_url('https://example.test'); import os"})
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'PolicyError')
        self.assertFalse(result['action_replayed'])
        wire.assert_not_called()

    def test_missing_verification_never_executes_agent_actions(self):
        with tempfile.TemporaryDirectory() as folder:
            request = self.request(folder, "goto_url('https://next.test')")
            del request['state']['verified']
            wire = FakeWire()
            result = run(request, transport=wire)
            self.assertFalse(result['success'])
            self.assertIn('profile_binding_unverified', result['error'])
            self.assertEqual(wire.calls, [])

    def test_page_controlled_error_cannot_trigger_vendor_js_retry(self):
        class Browser:
            def __init__(self):
                self.calls = []
            def cdp(self, method, **params):
                self.calls.append(method)
                return {'result': {}, 'exceptionDetails': {'text': 'Illegal return statement'}}
            def send(self, *args, **kwargs):
                return {}
            def create(self, *args, **kwargs):
                raise AssertionError('must not create')
        browser = Browser()
        ns = helper_namespace(browser)
        with self.assertRaisesRegex(RuntimeError, 'Illegal return statement'):
            ns['js']('document.title')
        self.assertEqual(browser.calls, ['Runtime.evaluate'])


if __name__ == '__main__':
    unittest.main()
