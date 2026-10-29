"""Plugin status is a read-only diagnostic for its calling process, never a browser probe."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plugin


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.gui=patch('plugin.chrome_gui_snapshot',return_value={'status':'running_no_windows','window_count':0})
        self.gui.start();self.addCleanup(self.gui.stop)
        policy=patch('plugin.native_browser_tools_disabled',return_value=True)
        policy.start();self.addCleanup(policy.stop)

    def context(self):
        ctx=Mock()
        import tempfile
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        ctx.state.data_dir=Path(temporary.name)
        ctx.get_config.return_value=plugin.APPROVED_ACCOUNT
        ctx.has_capability.return_value=True
        return ctx

    def test_ready_snapshot_reports_process_scope_without_browser_access(self):
        ctx=self.context()
        with patch('plugin.browser_config',return_value={'cloud_provider':plugin.NAME,'backend':'browser-use'}), \
                patch('plugin.verify_account') as verify,patch('plugin.gui_identity'), \
                patch('plugin.accessibility_trusted',return_value=True), \
                patch('plugin.gui_launch') as launch,patch('plugin.ChromeProvider') as provider:
            status=plugin.status_snapshot(ctx)
        self.assertTrue(status['ready'])
        self.assertTrue(status['checks']['native_browser_tools_disabled'])
        self.assertFalse(status['terminal_tool_required'])
        self.assertFalse(status['secret_output_filter'])
        self.assertEqual(status['browser_connection'],'not_probed')
        self.assertEqual(status['chrome_gui'],{'status':'running_no_windows','window_count':0})
        self.assertIn('current process only',status['accessibility_scope'])
        self.assertNotIn(plugin.APPROVED_ACCOUNT,json.dumps(status))
        verify.assert_called_once_with(plugin.PERSONAL,plugin.APPROVED_ACCOUNT)
        launch.assert_not_called();provider.assert_not_called()

    def test_native_browser_enabled_makes_status_unready_without_launch(self):
        ctx=self.context()
        with patch('plugin.browser_config',return_value={'cloud_provider':plugin.NAME}), \
                patch('plugin.native_browser_tools_disabled',return_value=False), \
                patch('plugin.verify_account'),patch('plugin.gui_identity'), \
                patch('plugin.accessibility_trusted',return_value=True),patch('plugin.gui_launch') as launch:
            status=plugin.status_snapshot(ctx)
        self.assertFalse(status['ready'])
        self.assertIn('browser_native_tools_enabled',status['failures'])
        self.assertFalse(status['checks']['native_browser_tools_disabled'])
        launch.assert_not_called()

    def test_failures_are_fixed_and_never_expose_config_or_profile_error_text(self):
        ctx=self.context()
        ctx.get_config.side_effect=RuntimeError('synthetic-private-setting')
        ctx.has_capability.side_effect=RuntimeError('synthetic-private-grant')
        with patch('plugin.browser_config',side_effect=RuntimeError('synthetic-private-config')), \
                patch('plugin.verify_account') as verify, \
                patch('plugin.gui_identity',side_effect=RuntimeError('synthetic-private-gui')), \
                patch('plugin.accessibility_trusted',return_value=False):
            status=plugin.status_snapshot(ctx)
        self.assertFalse(status['ready'])
        self.assertNotIn('synthetic-private',json.dumps(status))
        self.assertIn('browser_configuration_unavailable',status['failures'])
        self.assertIn('consent_accessibility',status['failures'])
        verify.assert_not_called()

    def test_unapproved_account_does_not_read_chrome_profile(self):
        ctx=self.context();ctx.get_config.return_value='different@example.test'
        with patch('plugin.browser_config',return_value={'cloud_provider':plugin.NAME,'backend':'browser-use'}), \
                patch('plugin.verify_account') as verify,patch('plugin.gui_identity'), \
                patch('plugin.accessibility_trusted',return_value=True):
            status=plugin.status_snapshot(ctx)
        self.assertIn('account_binding_not_approved',status['failures'])
        self.assertFalse(status['checks']['profile_identity_verified'])
        verify.assert_not_called()

    def test_status_command_exists_without_capability_grants(self):
        ctx=self.context();ctx.has_capability.return_value=False
        with patch('plugin.ChromeProvider') as provider:
            plugin.register(ctx)
        self.assertEqual(ctx.register_cli_command.call_args.kwargs['name'],'original-chrome')
        self.assertIn('original-chrome-status',{c.kwargs['name'] for c in ctx.register_command.call_args_list})
        provider.assert_called_once()
        ctx.has_capability.assert_not_called()

    def test_slash_status_runs_same_snapshot_in_calling_process_without_tool_registration(self):
        ctx=self.context();plugin.register_status_command(ctx)
        handler=ctx.register_command.call_args.kwargs['handler']
        expected={'ready':True,'process':{'pid':123},'checks':{'accessibility_trusted':True}}
        with patch('plugin.status_snapshot',return_value=expected) as snapshot:
            actual=json.loads(handler(''))
        self.assertEqual(actual,expected)
        snapshot.assert_called_once_with(ctx)
        ctx.register_tool.assert_not_called()

    def test_json_cli_returns_nonzero_when_readiness_is_blocked(self):
        ctx=self.context();plugin.register_status_command(ctx)
        registration=ctx.register_cli_command.call_args.kwargs
        parser=argparse.ArgumentParser()
        registration['setup_fn'](parser)
        args=parser.parse_args(['status','--json'])
        output=io.StringIO()
        with patch('plugin.status_snapshot',return_value={'ready':False,'checks':{},'failures':['consent_accessibility']}), \
                contextlib.redirect_stdout(output):
            code=registration['handler_fn'](args)
        self.assertEqual(code,1)
        self.assertEqual(json.loads(output.getvalue())['failures'],['consent_accessibility'])


if __name__=='__main__':unittest.main()
