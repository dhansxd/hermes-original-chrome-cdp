"""Public registry and routed context integration with inert browser handlers."""
import builtins
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plugin


class BrowserRegistrationTests(unittest.TestCase):
    def register(self, *, available=True, is_async=False, granted=True):
        self.ctx=Mock()
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.ctx.state.data_dir=Path(temporary.name)
        self.ctx.has_capability.return_value=granted
        self.native=Mock(return_value='{"success":true,"native":true}')
        self.schema=json.loads((plugin.ROOT/'browser_schema.json').read_text())
        self.schema['parameters']['properties']['fixture_option']={'type':'boolean'}
        entry=SimpleNamespace(handler=self.native,schema=self.schema,is_async=is_async,
            toolset='browser-use') if available else None
        original_import=builtins.__import__
        def checked_import(name,*args,**kwargs):
            if name in ('tools.browser_use_cli','tools.approval_context'):
                raise AssertionError('private browser integration import')
            return original_import(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=checked_import), \
             patch('tools.registry.registry.get_entry',side_effect=lambda name:entry if name=='browser_exec' else None) as lookup, \
             patch('plugin.ChromeProvider') as provider,patch('plugin.BrowserLifecycle') as lifecycle:
            plugin.register(self.ctx)
        self.provider=provider.return_value
        self.provider.execute.return_value='{"success":true,"stdout":"fixture"}'
        self.lifecycle=lifecycle.return_value
        self.lifecycle.status.return_value=[]
        self.lookup=lookup
        name='browser_exec' if granted else 'original_chrome_default_browser_exec'
        self.registration=next(c.kwargs for c in self.ctx.register_tool.call_args_list
            if c.kwargs['name']==name)
        return self.registration['handler']

    def selected(self):
        return patch('plugin.browser_config',return_value={
            'cloud_provider':plugin.NAME,'backend':'browser-use'})

    def test_captured_native_handler_and_schema_do_not_follow_later_registry_changes(self):
        handler=self.register()
        schema_before=copy.deepcopy(self.schema)
        args={'code':'print(1)','session':'named','fixture_option':True}
        with patch('plugin.browser_config',return_value={'cloud_provider':'other'}), \
             patch('tools.registry.registry.get_entry',side_effect=AssertionError('recursive lookup')):
            result=json.loads(handler(args,task_id='task',session_id='session'))
        self.assertTrue(result['native'])
        self.native.assert_called_once_with(args,task_id='task',session_id='session')
        self.provider.execute.assert_not_called()
        parameters=copy.deepcopy(self.registration['schema']['parameters'])
        parameters['properties']['code']=self.schema['parameters']['properties']['code']
        self.assertEqual(parameters,self.schema['parameters'])
        self.assertEqual(self.schema,schema_before)
        self.assertIsNot(self.registration['schema'],self.schema)

    def test_missing_or_async_native_does_not_prevent_selected_provider(self):
        for available,is_async in ((False,False),(True,True)):
            handler=self.register(available=available,is_async=is_async)
            with self.selected(),patch('gateway.session_context.get_session_env',return_value='route'):
                result=json.loads(handler({'code':'print(1)'},task_id='task',session_id='session'))
            self.assertTrue(result['success'])
            self.provider.execute.assert_called_once()
            self.native.assert_not_called()
            with patch('plugin.browser_config',return_value={'cloud_provider':'other'}):
                refused=json.loads(handler({'code':'print(1)'}))
            self.assertFalse(refused['success'])
            self.assertFalse(refused['fallback_used'])
            self.assertFalse(refused['action_replayed'])
            self.assertIn('code',self.registration['schema']['parameters']['properties'])

    def test_no_grant_uses_only_local_schema_and_no_registry_lookup(self):
        handler=self.register(granted=False)
        self.lookup.assert_not_called()
        self.ctx.register_browser_provider.assert_not_called()
        self.assertFalse(self.registration.get('override',False))
        self.assertNotIn('fixture_option',self.registration['schema']['parameters']['properties'])
        self.assertEqual(json.loads(handler({}))['error_type'],'plugin_capability_required')

    def test_native_exception_is_uncertain_without_private_text_or_retry(self):
        handler=self.register()
        self.native.side_effect=RuntimeError('SYNTHETIC-PRIVATE-TEXT')
        with patch('plugin.browser_config',return_value={'cloud_provider':'other'}):
            raw=handler({'code':'print(1)'})
        result=json.loads(raw)
        self.assertFalse(result['success'])
        self.assertTrue(result['uncertain'])
        self.assertFalse(result['action_replayed'])
        self.assertNotIn('SYNTHETIC-PRIVATE-TEXT',raw)
        self.native.assert_called_once()

    def test_context_is_read_at_call_time_and_explicit_route_has_priority(self):
        handler=self.register(available=False)
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
        with self.selected(),patch('gateway.session_context.get_session_env',side_effect=RuntimeError('private-context')):
            raw=handler({'code':'print(1)'},task_id='task',session_id='session')
        self.assertFalse(json.loads(raw)['success'])
        self.assertNotIn('private-context',raw)
        self.provider.execute.assert_not_called()
        self.lifecycle.bind.assert_not_called()
        self.native.assert_not_called()


if __name__=='__main__':
    unittest.main()
