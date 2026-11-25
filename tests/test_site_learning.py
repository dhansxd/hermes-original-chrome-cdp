import json
import sys
import tempfile
from threading import Timer
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from site_learning import ClickCatalog, PageLearning, cached_action, page_key


class SiteLearningTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.catalog = ClickCatalog(Path(temp) / 'learned-controls.sqlite3')
        self.url = ['https://example.com', '/settings']
        self.origin, self.page = page_key(self.url)

    def record(self, element, state='aria-expanded', value='true'):
        self.catalog.record([(self.origin, self.page, ('Show details', element, state, value))])

    def test_observation_without_confirmed_effect_does_not_create_playable_control(self):
        self.record('button-a', '', '')
        self.assertEqual(self.catalog.list(self.origin, self.page), [])
        with self.catalog.open() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM controls').fetchone()[0], 1)

    def test_outdated_click_cannot_clear_newer_learning_for_same_button(self):
        self.record('button-a')
        control, = self.catalog.list(self.origin, self.page)
        old = self.catalog.get(control['id'], self.origin, self.page)
        self.record('button-b')
        self.catalog.stale(old)
        self.record('button-c', '', '')
        current = self.catalog.get(control['id'], self.origin, self.page)
        self.assertEqual(current['element_id'], 'button-b')

    def test_click_requires_current_page_and_never_replays_uncertain_result(self):
        self.record('button-a')
        control, = self.catalog.list(self.origin, self.page)
        command = {'action': 'click_learned_control', 'params': {'control': control['id']}}
        wrong_page = Mock(return_value=['https://another.example', '/settings'])
        self.assertFalse(cached_action(self.catalog, command, wrong_page)['dispatched'])
        wrong_page.assert_called_once()
        click = Mock(side_effect=[self.url, 'unconfirmed'])
        result = cached_action(self.catalog, command, click)
        self.assertTrue(result['dispatched'])
        self.assertEqual(result['status'], 'needs_inspection')
        self.assertEqual(click.call_count, 2)
        self.assertEqual(self.catalog.list(self.origin, self.page), [])

    def test_recorder_ignores_clicks_outside_native_evaluation(self):
        learner = PageLearning(self.catalog)
        wire = Mock()
        wire.call.return_value = {'identifier': 'fixture-observer'}
        learner.attach(wire, 'tab')
        payload = json.dumps({'url': self.url, 'label': 'Show details', 'element': 'button-a',
                              'state': 'aria-expanded', 'value': 'true'})
        self.assertTrue(learner.event('tab', {'name': learner.binding, 'payload': payload}))
        self.assertFalse(learner.event('tab', {'name': 'other_binding', 'payload': payload}))
        self.assertFalse(learner.observations)


    def test_pointer_learning_matches_the_actual_event_once_in_the_same_attachment(self):
        learner = PageLearning(self.catalog)
        wire = Mock()
        wire.call.return_value = {'identifier': 'fixture-observer'}
        learner.attach(wire, 'tab')
        learner.attach(wire, 'peer')
        method = 'Input.dispatchMouseEvent'
        options = {'x': 40.4, 'y': 20, 'button': 'left', 'clickCount': 1}
        pressed = dict(options, type='mousePressed')
        released = dict(options, type='mouseReleased')
        control = {'url': self.url, 'label': 'Show details', 'element': 'button-a',
                   'state': '', 'value': '', 'observation': '12-3-1'}

        def emit(sid, points):
            payload = json.dumps({**control, 'points': points})
            self.assertTrue(learner.event(sid, {'name': learner.binding, 'payload': payload,
                                                 'executionContextId': 12}))

        emit('tab', [[40, 20]])
        learner.pointer(wire, method, pressed, 'tab')

        def release(command, params, sid, **kwargs):
            if command == 'Runtime.evaluate':
                self.assertEqual(sid, 'tab')
                self.assertEqual(params['contextId'], 12)
                self.assertEqual(len(learner.observations), 1)
                return {'result': {'value': {'state': 'aria-expanded', 'value': 'true'}}}
            emit('peer', [[40, 20]])
            emit('tab', [[90, 20]])
            self.assertFalse(learner.observations)
            emit('tab', [[60, 30], [40, 20]])
            emit('tab', [[40, 20]])
            return {}

        wire.call.side_effect = release
        result = learner.pointer(wire, method, released, 'tab')
        self.assertEqual(result, {})
        self.assertEqual(len(learner.observations), 2)
        emit('tab', [[40, 20]])
        self.assertEqual(len(learner.observations), 2)
        learner.flush()
        control, = self.catalog.list(self.origin, self.page)
        self.assertEqual(control['label'], 'Show details')

    def test_pointer_learns_when_observation_arrives_after_cdp_release_reply(self):
        learner = PageLearning(self.catalog)
        wire = Mock()
        wire.call.return_value = {'identifier': 'fixture-observer'}
        learner.attach(wire, 'tab')
        method = 'Input.dispatchMouseEvent'
        options = {'x': 40, 'y': 20, 'button': 'left', 'clickCount': 1}
        learner.pointer(wire, method, dict(options, type='mousePressed'), 'tab')
        payload = json.dumps({'url': self.url, 'label': 'Show details', 'element': 'button-a',
                              'state': '', 'value': '', 'observation': '12-3-1', 'points': [[40, 20]]})
        event = {'name': learner.binding, 'payload': payload, 'executionContextId': 12}
        delayed = Timer(.03, learner.event, args=('tab', event))

        def release(command, params, sid, **kwargs):
            if command == 'Runtime.evaluate':
                return {'result': {'value': {'state': 'aria-expanded', 'value': 'true'}}}
            delayed.start()
            return {}

        wire.call.side_effect = release
        self.assertEqual(learner.pointer(wire, method, dict(options, type='mouseReleased'), 'tab'), {})
        delayed.join(1)
        learner.flush()
        self.assertEqual([item['label'] for item in self.catalog.list(self.origin, self.page)], ['Show details'])

    def test_pointer_dispatch_failure_releases_observation_state(self):
        learner = PageLearning(self.catalog)
        wire = Mock()
        wire.call.return_value = {'identifier': 'fixture-observer'}
        learner.attach(wire, 'tab')
        method = 'Input.dispatchMouseEvent'
        options = {'x': 40, 'y': 20, 'button': 'left', 'clickCount': 1}
        learner.pointer(wire, method, dict(options, type='mousePressed'), 'tab')
        wire.call.side_effect = TimeoutError('fixture timed out')
        with self.assertRaises(TimeoutError):
            learner.pointer(wire, method, dict(options, type='mouseReleased'), 'tab')
        self.assertFalse(learner.releasing)
        self.assertFalse(learner.pressed)
