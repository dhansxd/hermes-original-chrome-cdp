"""Private operator callback diagnoses fixed selftests without model egress."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plugin


class OperatorDiagnosticTests(unittest.TestCase):
    def provider(self):
        provider=plugin.ChromeProvider(data='/synthetic-operator-diagnostic')
        provider._execute_session=Mock(return_value={'success':False,
            'error':'private-worker-detail:'+'x'*1000,'error_type':'SyntheticWorkerError',
            'uncertain':True,'stdout':'private-stdout','state':{'owned':{'private-target':1}},
            'workspace':'/private-workspace','fallback_used':False,'action_replayed':False})
        return provider

    def test_execute_calls_only_private_sink_with_bounded_allowed_fields(self):
        provider=self.provider();diagnostics=[];argument_sink=Mock()
        result=json.loads(provider.execute({'code':'pass','_diagnostic_sink':argument_sink},
            task_id='synthetic-task',_diagnostic_sink=diagnostics.append))
        self.assertEqual(set(diagnostics[0]),{'error','error_type','uncertain'})
        self.assertEqual(len(diagnostics[0]['error']),800)
        self.assertEqual(diagnostics[0]['error_type'],'SyntheticWorkerError')
        self.assertTrue(diagnostics[0]['uncertain'])
        argument_sink.assert_not_called()
        self.assertEqual(result['stdout'],'private-stdout','Operator diagnostics must not change the raw provider result')
        self.assertNotIn('_diagnostic_sink',result)
        provider._execute_session.assert_called_once()

    def test_callback_failure_cannot_change_or_repeat_execution(self):
        provider=self.provider()
        expected=copy.deepcopy(provider._execute_session.return_value)
        result=json.loads(provider.execute({'code':'pass'},task_id='synthetic-task',
            _diagnostic_sink=Mock(side_effect=RuntimeError('sink failed'))))
        self.assertEqual(result,expected)
        provider._execute_session.assert_called_once()

    def test_registered_handler_keeps_raw_diagnostic_out_of_public_result(self):
        provider=self.provider();ctx=Mock();ctx.has_capability.return_value=True
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        ctx.state.data_dir=Path(temporary.name)
        with patch('plugin.ChromeProvider',return_value=provider),patch('plugin.BrowserLifecycle') as lifecycle:
            lifecycle.return_value.status.return_value=[]
            plugin.register(ctx)
        call=next(c for c in ctx.register_tool.call_args_list if c.kwargs['name']=='browser_original_chrome_exec')
        self.assertNotIn('_diagnostic_sink',json.dumps(call.kwargs['schema']))
        sink=[]
        with patch('plugin.browser_config',return_value={'cloud_provider':plugin.NAME,'backend':'browser-use'}),patch('plugin.native_browser_tools_disabled',return_value=True):
            result=json.loads(call.kwargs['handler']({'code':'pass'},task_id='synthetic-task',
                session_id='synthetic-session',_diagnostic_sink=sink.append))
        self.assertEqual(len(sink),1)
        self.assertIn('private-worker-detail',sink[0]['error'])
        self.assertEqual(result['error_code'],'browser_outcome_unknown')
        self.assertNotIn('private-worker-detail',json.dumps(result))
        self.assertNotIn('private-target',json.dumps(result))
        lifecycle.return_value.bind.assert_called_once()
        self.assertNotIn('_diagnostic_sink',lifecycle.return_value.bind.call_args.kwargs)


if __name__=='__main__':unittest.main()
