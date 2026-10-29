"""Readiness and public hook gates with inert providers; no Chrome or private state."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plugin


class ProductionPolicyTests(unittest.TestCase):
    def provider(self,*,account=None,config=None,granted=True):
        return plugin.ChromeProvider(data=plugin.PERSONAL,
            get_setting=lambda key:plugin.APPROVED_ACCOUNT if account is None else account,
            read_browser_config=lambda:config if config is not None else {
                'cloud_provider':plugin.NAME,'backend':'browser-use'},
            has_override=lambda:granted)

    def test_missing_production_task_identity_refuses_before_readiness_or_launch(self):
        for task_id in (None,'','   '):
            with self.subTest(task_id=task_id):
                provider=self.provider()
                with patch.object(provider,'require_ready') as ready,patch.object(provider,'endpoint') as endpoint:
                    result=json.loads(provider.execute({'code':'print(1)'},task_id=task_id))
                self.assertIn('browser_identity_required',result['error'])
                ready.assert_not_called();endpoint.assert_not_called()
                self.assertFalse(provider.states)

    def test_unapproved_account_rejected_before_profile_read_or_launch(self):
        provider=self.provider(account='different@example.test')
        with patch('plugin.verify_account') as verify,patch('plugin.gui_launch') as launch:
            result=json.loads(provider.execute({'code':'print(1)'},task_id='fixture'))
        self.assertFalse(result['success'])
        self.assertIn('account_binding_not_approved',result['error'])
        verify.assert_not_called();launch.assert_not_called()
        self.assertFalse(provider.states)

    def test_route_and_grant_rejected_before_profile_read_or_launch(self):
        cases=[({'cloud_provider':'local','backend':'browser-use'},True,'browser_provider_not_selected'),
               ({'cloud_provider':plugin.NAME,'backend':'off'},True,'browser_backend_unsupported'),
               ({'cloud_provider':plugin.NAME,'backend':'browser-use'},False,'plugin_capability_required')]
        for config,granted,error in cases:
            with self.subTest(config=config,granted=granted):
                provider=self.provider(config=config,granted=granted)
                with patch('plugin.verify_account') as verify,patch('plugin.gui_launch') as launch:
                    result=json.loads(provider.execute({'code':'print(1)'},task_id='fixture'))
                self.assertIn(error,result['error'])
                verify.assert_not_called();launch.assert_not_called()
                self.assertFalse(provider.states)

    def test_direct_original_provider_requires_explicit_policy_callbacks(self):
        provider=plugin.ChromeProvider(get_setting=lambda key:plugin.APPROVED_ACCOUNT)
        with patch('plugin.verify_account') as verify,patch('plugin.gui_launch') as launch:
            with self.assertRaisesRegex(RuntimeError,'browser_policy_unconfigured'):
                provider.endpoint(entry={})
        verify.assert_not_called();launch.assert_not_called()

    def test_current_picker_selection_without_legacy_backend_still_requires_account(self):
        provider=self.provider(config={'cloud_provider':plugin.NAME})
        with patch('plugin.verify_account') as verify,patch('plugin.gui_launch') as launch:
            provider.require_ready()
        verify.assert_called_once_with(plugin.PERSONAL.resolve(),plugin.APPROVED_ACCOUNT)
        launch.assert_not_called()

    def test_source_rejection_precedes_endpoint_and_worker(self):
        provider=plugin.ChromeProvider(data='/explicit-disposable-fixture')
        policy=Mock();policy.validate_source.side_effect=RuntimeError('restricted_source')
        with patch('plugin._execution_policy',return_value=policy),patch.object(provider,'endpoint') as endpoint,patch.object(provider,'_worker') as worker:
            result=json.loads(provider.execute({'code':'import os'},task_id='fixture'))
        self.assertIn('restricted_source',result['error'])
        endpoint.assert_not_called();worker.assert_not_called()
        self.assertFalse(provider.states)

    def test_endpoint_checks_injected_account_again_before_launch(self):
        settings=Mock(side_effect=[plugin.APPROVED_ACCOUNT,'changed@example.test'])
        provider=plugin.ChromeProvider(get_setting=settings,
            read_browser_config=lambda:{'cloud_provider':plugin.NAME,'backend':'browser-use'},
            has_override=lambda:True)
        with patch('plugin.verify_account') as verify,patch('plugin.gui_launch') as launch:
            provider.require_ready()
            with self.assertRaisesRegex(RuntimeError,'account_binding_not_approved'):
                provider.endpoint(entry={})
        verify.assert_called_once_with(plugin.PERSONAL.resolve(),plugin.APPROVED_ACCOUNT)
        launch.assert_not_called()

    def test_accessibility_refusal_precedes_seed_creation_and_launch(self):
        provider=self.provider()
        entry={}
        with patch.object(provider,'require_ready'),patch('plugin.accessibility_trusted',return_value=False), \
             patch('plugin.gui_launch') as launch,patch.object(Path,'write_text') as write:
            with self.assertRaisesRegex(RuntimeError,'accessibility_permission_required'):
                provider.endpoint(entry=entry)
        launch.assert_not_called();write.assert_not_called()
        self.assertEqual(entry,{})

    def test_remote_debugging_disabled_refuses_before_seed_or_gui_launch(self):
        provider=self.provider()
        for contents in ('{}', '{"devtools":{"remote_debugging":{"user-enabled":false}}}',
                         '{"devtools":{"remote_debugging":{"user-enabled":"true"}}}', 'invalid JSON'):
            with self.subTest(contents=contents):
                entry={}
                def read(path,*args,**kwargs):
                    self.assertEqual(path,plugin.PERSONAL/'Local State')
                    return contents
                with patch.object(provider,'require_ready'),patch('plugin.accessibility_trusted',return_value=True), \
                     patch.object(Path,'read_text',autospec=True,side_effect=read) as local_state, \
                     patch.object(provider,'_journal') as journal,patch('plugin.gui_launch') as launch, \
                     patch.object(provider,'_endpoint_identity') as identity:
                    with self.assertRaisesRegex(RuntimeError,'Chrome_endpoint_disabled'):
                        provider.endpoint(entry=entry)
                local_state.assert_called_once();journal.assert_not_called()
                launch.assert_not_called();identity.assert_not_called()
                self.assertEqual(entry,{})


class RegistrationPolicyTests(unittest.TestCase):
    def context(self,granted):
        ctx=Mock();ctx.has_capability.return_value=granted
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        ctx.state.data_dir=Path(temporary.name)
        return ctx

    def hook(self,ctx):
        return next(call.args[1] for call in ctx.register_hook.call_args_list if call.args[0]=='pre_tool_call')

    def test_loaded_without_grant_vetoes_native_browser_tools_only_when_selected(self):
        ctx=self.context(False)
        plugin.register(ctx)
        guard=self.hook(ctx)
        with patch('plugin.browser_config',return_value={'cloud_provider':plugin.NAME,'backend':'browser-use'}):
            for name in ('browser_exec','browser_vault','browser_cdp','browser_dialog','browser_navigate'):
                with self.subTest(name=name):
                    result=guard(name,{})
                    self.assertEqual(result['action'],'block')
                    self.assertIn('plugin_capability_required',result['message'])
            self.assertIsNone(guard('web_search',{}))
        with patch('plugin.browser_config',return_value={'cloud_provider':'local'}):
            self.assertIsNone(guard('browser_exec',{}))
        ctx.register_browser_provider.assert_not_called()

    def test_granted_routes_keep_raw_native_cdp_and_legacy_browsing_blocked(self):
        ctx=self.context(True)
        with patch('plugin.ChromeProvider') as constructor:
            plugin.register(ctx)
        self.assertIs(constructor.call_args.kwargs['get_setting'],ctx.get_config)
        guard=self.hook(ctx)
        with patch('plugin.browser_config',return_value={'cloud_provider':plugin.NAME,'backend':'browser-use'}):
            for name in ('browser_cdp','browser_dialog','browser_navigate','browser_click'):
                self.assertIn('browser_route_blocked',guard(name,{})['message'])
            self.assertIsNone(guard('browser_exec',{}))
            self.assertIsNone(guard('browser_vault',{}))

    def test_grant_revocation_blocks_registered_browser_handler_before_execute(self):
        ctx=self.context(True)
        with patch('plugin.ChromeProvider') as constructor:
            plugin.register(ctx)
        provider=constructor.return_value
        handler=next(c.kwargs['handler'] for c in ctx.register_tool.call_args_list if c.kwargs['name']=='browser_exec')
        ctx.has_capability.return_value=False
        with patch('plugin.browser_config',return_value={'cloud_provider':plugin.NAME,'backend':'browser-use'}):
            result=json.loads(handler({'code':'print(1)'}))
        self.assertEqual(result['error_code'],'browser_unavailable')
        self.assertNotIn('tools.override',result['error'])
        provider.execute.assert_not_called()

    def test_registered_handler_refuses_missing_agent_identity_before_binding(self):
        ctx=self.context(True)
        with patch('plugin.ChromeProvider') as constructor,patch('plugin.BrowserLifecycle') as lifecycle:
            plugin.register(ctx)
        handler=next(c.kwargs['handler'] for c in ctx.register_tool.call_args_list if c.kwargs['name']=='browser_exec')
        with patch('plugin.browser_config',return_value={'cloud_provider':plugin.NAME,'backend':'browser-use'}):
            for kwargs in ({},{'task_id':'agent-a'},{'session_id':'conversation-a'},
                           {'task_id':'agent-a','session_id':'  '}):
                with self.subTest(kwargs=kwargs):
                    result=json.loads(handler({'code':'print(1)'},**kwargs))
                    self.assertEqual(result['error_code'],'browser_session_unavailable')
        constructor.return_value.execute.assert_not_called()
        lifecycle.return_value.bind.assert_not_called()

    def test_registered_handler_refuses_config_fault_without_native_fallback(self):
        from types import SimpleNamespace
        ctx=self.context(True)
        native=Mock()
        entry=SimpleNamespace(handler=native,is_async=False,
            schema=json.loads((plugin.ROOT/'browser_schema.json').read_text()))
        with patch('plugin.ChromeProvider') as constructor,patch('tools.registry.registry.get_entry',
                side_effect=lambda name:entry if name=='browser_exec' else None):
            plugin.register(ctx)
        handler=next(c.kwargs['handler'] for c in ctx.register_tool.call_args_list if c.kwargs['name']=='browser_exec')
        with patch('plugin.browser_config',side_effect=ValueError('private-config-payload')):
            result=json.loads(handler({'code':'print(1)'},task_id='agent-a',session_id='conversation-a'))
        self.assertEqual(result['error_code'],'browser_unavailable')
        self.assertNotIn('private-config-payload',result['error'])
        constructor.return_value.execute.assert_not_called();native.assert_not_called()

    def test_unreadable_core_config_has_fixed_failure_without_native_fallback(self):
        with patch('hermes_cli.config.read_raw_config',side_effect=ValueError('private-config-payload')):
            with self.assertRaisesRegex(RuntimeError,'browser_configuration_unavailable') as caught:
                plugin.browser_config()
        self.assertNotIn('private-config-payload',str(caught.exception))


if __name__=='__main__':unittest.main()
