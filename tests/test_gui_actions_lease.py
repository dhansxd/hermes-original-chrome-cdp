import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from browser_actions import public_helpers


class SharedGuiActions(unittest.TestCase):
    def helpers(self, url, leases):
        browser = Mock()
        browser.info.return_value = {'url': url}
        browser.cdp.return_value = {}
        trusted = {name: Mock() for name in (
            'page_info', 'type_text', 'press_key', 'scroll', 'list_tabs', 'current_tab',
            'activate_tab', 'close_tab', 'ensure_real_tab', 'js')}
        return browser, public_helpers(browser, trusted, Path(tempfile.gettempdir()),
            profile=Path(tempfile.gettempdir())/'synthetic-profile', lease_stack=leases)

    def test_same_batch_holds_one_flow_lease_until_exit(self):
        lease = Mock()
        lease.__enter__ = Mock(return_value=lease)
        lease.__exit__ = Mock()
        with patch('browser_actions.gui_lease.acquire', return_value=lease) as acquire:
            with contextlib.ExitStack() as stack:
                browser, helpers = self.helpers('https://flow.google.com/project/x', stack)
                helpers['goto_url']('https://flow.google.com/project/y')
                helpers['page_info']()
                acquire.assert_called_once()
                lease.__exit__.assert_not_called()
            lease.__exit__.assert_called_once()

    def test_unrelated_search_does_not_wait_for_flow(self):
        with patch('browser_actions.gui_lease.acquire') as acquire, contextlib.ExitStack() as stack:
            browser, helpers = self.helpers('https://example.com', stack)
            helpers['goto_url']('https://example.com/search')
            helpers['page_info']()
            acquire.assert_not_called()

    def test_busy_flow_sends_no_navigation(self):
        from gui_lease import GuiResourceBusy
        with patch('browser_actions.gui_lease.acquire', side_effect=GuiResourceBusy()), contextlib.ExitStack() as stack:
            browser, helpers = self.helpers('https://example.com', stack)
            with self.assertRaises(GuiResourceBusy):
                helpers['goto_url']('https://flow.google.com/project/x')
            browser.cdp.assert_not_called()
