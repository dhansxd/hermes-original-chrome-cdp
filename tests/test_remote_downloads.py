"""Windows Chrome download receipts when a site omits page download events."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remote_downloads import collect


class WindowsDownloadHistoryTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.record = Path(scratch.name) / 'downloads' / 'result.json'
        self.page = 'https://gemini.google.com/app/example'
        self.row = {'name': 'video.mp4', 'bytes': 24, 'modified': 4}
        self.desktop = Mock()
        self.desktop.download_files.side_effect = [[], [self.row]]
        self.desktop.download_receipts.side_effect = [
            [{'id': 3}],
            [{'id': 4, 'guid': '1f29a42e-c721-43ed-ab79-f785e4248739',
              'path': 'C:/Downloads/video.mp4', 'bytes': 24, 'state': 1}],
        ]
        self.desktop.fetch_download.return_value = {'bytes': 24, 'sha256': 'check'}
        self.browser = Mock()
        self.browser.unique_download_page.return_value = self.page
        host = SimpleNamespace(provider=Mock())
        host.provider.desktop.return_value = self.desktop
        self.context = SimpleNamespace(host=host, device='windows', profile='Profile 1', directory=Path(scratch.name),
                                       _remote_browser=lambda: self.browser, _choice=Mock())
        self.clicked = 0
        self.events = [[]]

    def execute(self, script, timeout):
        def click():
            self.clicked += 1

        exec(script, {'cdp': lambda method: {'frameTree': {'frame': {'id': 'task'}}},
                      'drain_events': lambda: self.events.pop(0) if self.events else [],
                      'click': click, 'wait': lambda seconds: None})

    def save(self, record, state):
        record.write_text(json.dumps(state))

    def collect(self):
        return collect(self.context, self.record, 'click()', self.execute, self.save, 0)

    def test_recovers_file_from_same_page_history_without_replaying_the_click(self):
        before, completed = list(self.desktop.download_receipts.side_effect)
        self.desktop.download_receipts.side_effect = [before, [], completed]
        self.assertTrue(self.collect()['pending'])
        result = self.collect()
        self.assertEqual(result.get('guid'), '1f29a42e-c721-43ed-ab79-f785e4248739')
        self.assertEqual(result['bytes'], 24)
        self.assertEqual(self.collect(), result)
        self.assertEqual(self.clicked, 1)
        self.desktop.fetch_download.assert_called_once()

    def test_history_is_unused_when_another_tab_opens_the_same_page(self):
        self.browser.unique_download_page.side_effect = [self.page, None]
        self.assertTrue(self.collect()['pending'])
        self.assertEqual(self.clicked, 1)
        self.desktop.download_receipts.assert_called_once()
        self.desktop.fetch_download.assert_not_called()

    def test_multiple_matching_history_receipts_are_rejected(self):
        self.desktop.download_receipts.side_effect = [[{'id': 3}], [{'id': 4}, {'id': 5}]]
        with self.assertRaisesRegex(RuntimeError, 'ambiguous'):
            self.collect()
        self.desktop.fetch_download.assert_not_called()

    def test_normal_page_events_take_priority_over_history(self):
        self.events.append([
            {'method': 'Page.downloadWillBegin',
             'params': {'frameId': 'task', 'guid': 'native', 'suggestedFilename': 'video.mp4'}},
            {'method': 'Page.downloadProgress',
             'params': {'guid': 'native', 'state': 'completed', 'receivedBytes': 24}},
        ])
        execute = Mock(side_effect=self.execute)
        result = collect(self.context, self.record, 'click()', execute, self.save, 20)
        self.assertEqual(result['guid'], 'native')
        self.assertEqual(execute.call_args.args[1], 35)
        self.desktop.download_receipts.assert_called_once_with('Profile 1', self.page)
        self.assertEqual(self.clicked, 1)


if __name__ == '__main__':
    unittest.main()
