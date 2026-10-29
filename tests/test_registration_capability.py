"""Unique plugin tools need no builtin override capability."""
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import Mock,PropertyMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plugin

class RegistrationCapabilityTests(unittest.TestCase):
    def test_registration_and_idle_unload_never_access_durable_state(self):
        ctx=Mock()
        with patch.object(type(ctx),'state',new_callable=PropertyMock,create=True) as state:
            state.side_effect=AssertionError('registration-only contexts have no state')
            plugin.register(ctx)
            provider=ctx.register_browser_provider.call_args.args[0]
            self.assertFalse(provider.states)
            self.assertIsNone(provider._runtime_snapshot)
            self.assertIsNone(provider._resource_watch)
            ctx.on_unload.call_args.args[0]()
            state.assert_not_called()
        ctx.register_tool.assert_called()

    def test_workspace_is_resolved_once_and_keeps_first_profile_identity(self):
        with tempfile.TemporaryDirectory() as home:
            first=Path(home)/'first-profile'
            source=Mock(side_effect=[first,Path(home)/'later-profile'])
            provider=plugin.ChromeProvider(data=Path(home)/'chrome-fixture',workspace=source)
            source.assert_not_called()
            self.assertEqual(provider.workspace,first)
            self.assertEqual(provider.workspace,first)
            source.assert_called_once_with()
            self.assertFalse(first.exists())
            provider.unload()
            source.assert_called_once_with()

    def test_registration_never_requests_override_or_replaces_native_names(self):
        for granted in (False,True):
            with self.subTest(legacy_grant=granted),tempfile.TemporaryDirectory() as home:
                ctx=Mock();ctx.state.data_dir=Path(home)
                ctx.has_capability.return_value=granted
                with patch('plugin.ChromeProvider') as provider:
                    plugin.register(ctx)
                ctx.has_capability.assert_not_called()
                provider.assert_called_once();ctx.register_browser_provider.assert_called_once()
                calls=[c.kwargs for c in ctx.register_tool.call_args_list]
                self.assertEqual({c['name'] for c in calls},{'browser_original_chrome_exec','browser_original_chrome_vault'})
                for call in calls:
                    self.assertFalse(call.get('override',False))
                    self.assertEqual(call['toolset'],'original_chrome')
                    self.assertEqual(call['schema']['name'],call['name'])

if __name__=='__main__':unittest.main()
