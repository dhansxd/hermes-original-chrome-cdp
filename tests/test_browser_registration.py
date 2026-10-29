"""Unique browser tool and routed context, without native browser dispatch."""
import builtins,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plugin

class BrowserRegistrationTests(unittest.TestCase):
    def register(self):
        self.ctx=Mock()
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.ctx.state.data_dir=Path(temporary.name)
        original_import=builtins.__import__
        def checked_import(name,*args,**kwargs):
            if name in ('tools.browser_use_cli','tools.approval_context','tools.registry'):
                raise AssertionError('native browser integration import')
            return original_import(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=checked_import),patch('plugin.ChromeProvider') as provider,patch('plugin.BrowserLifecycle') as lifecycle:
            plugin.register(self.ctx)
        self.provider=provider.return_value
        self.provider.execute.return_value='{"success":true,"stdout":"fixture"}'
        self.lifecycle=lifecycle.return_value;self.lifecycle.status.return_value=[]
        self.registration=next(c.kwargs for c in self.ctx.register_tool.call_args_list if c.kwargs['name']=='browser_original_chrome_exec')
        policy=patch('plugin.native_browser_tools_disabled',return_value=True)
        policy.start();self.addCleanup(policy.stop)
        return self.registration['handler']

    def selected(self):
        return patch('plugin.browser_config',return_value={'cloud_provider':plugin.NAME,'backend':'browser-use'})

    def test_unselected_provider_refuses_without_native_dispatch(self):
        handler=self.register()
        with patch('plugin.browser_config',return_value={'cloud_provider':'other'}):
            result=json.loads(handler({'code':'print(1)'},task_id='task',session_id='session'))
        self.assertFalse(result['success']);self.assertFalse(result['fallback_used'])
        self.assertFalse(result['action_replayed'])
        self.provider.execute.assert_not_called();self.ctx.dispatch_tool.assert_not_called()

    def test_unique_tool_uses_local_schema_and_needs_no_override(self):
        handler=self.register()
        self.ctx.has_capability.assert_not_called();self.ctx.register_browser_provider.assert_called_once()
        self.assertFalse(self.registration.get('override',False))
        self.assertEqual(self.registration['toolset'],'original_chrome')
        self.assertIn('code',self.registration['schema']['parameters']['properties'])
        with self.selected(),patch('gateway.session_context.get_session_env',return_value='route'):
            result=json.loads(handler({'code':'print(1)'},task_id='task',session_id='session'))
        self.assertTrue(result['success']);self.provider.execute.assert_called_once()

    def test_context_is_read_at_call_time_and_explicit_route_has_priority(self):
        handler=self.register()
        with self.selected(),patch('gateway.session_context.get_session_env',return_value='routed-key') as get:
            handler({'code':'print(1)'},task_id='task-a',session_id='session-a')
            get.assert_called_once_with('HERMES_SESSION_KEY','')
            self.assertEqual(self.lifecycle.bind.call_args.kwargs['session_key'],'routed-key')
            get.reset_mock()
            handler({'code':'print(1)'},task_id='task-b',session_id='session-b',session_key='explicit-key')
            get.assert_not_called()
            self.assertEqual(self.lifecycle.bind.call_args.kwargs['session_key'],'explicit-key')

    def test_missing_routed_context_refuses_before_provider_or_binding(self):
        handler=self.register()
        with self.selected(),patch('gateway.session_context.get_session_env',side_effect=RuntimeError('context unavailable')):
            result=json.loads(handler({'code':'print(1)'},task_id='task',session_id='session'))
        self.assertFalse(result['success'])
        self.provider.execute.assert_not_called();self.lifecycle.bind.assert_not_called()
        self.ctx.dispatch_tool.assert_not_called()

if __name__=='__main__':unittest.main()
