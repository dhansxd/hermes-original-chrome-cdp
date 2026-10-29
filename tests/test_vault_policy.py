"""Vault metadata bridge uses only public dispatch; page actions stay unavailable."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plugin

class VaultPolicyTests(unittest.TestCase):
    def register(self):
        self.ctx=Mock()
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.ctx.state.data_dir=Path(temporary.name)
        self.ctx.dispatch_tool.return_value='{"success":true,"synthetic":true}'
        with patch('plugin.ChromeProvider') as provider:plugin.register(self.ctx)
        self.provider=provider.return_value
        call=next(c.kwargs for c in self.ctx.register_tool.call_args_list if c.kwargs['name']=='browser_original_chrome_vault')
        self.assertFalse(call.get('override',False))
        self.assertEqual(call['schema']['name'],'browser_original_chrome_vault')
        policy=patch('plugin.native_browser_tools_disabled',return_value=True)
        policy.start();self.addCleanup(policy.stop)
        return call['handler']

    def invoke(self,handler,args,**kwargs):
        with patch('plugin.browser_config',return_value={'backend':'browser-use','cloud_provider':plugin.NAME}):
            return json.loads(handler(args,**kwargs))

    def test_page_actions_refuse_without_native_or_provider_access(self):
        handler=self.register()
        for action in ('fill','save_login','enter_code','unknown',None):
            with self.subTest(action=action):
                result=self.invoke(handler,{'action':action,'handle':'SYNTHETIC'})
                self.assertFalse(result['success'])
                self.assertEqual(result['error_type'],'vault_page_actions_unavailable')
                self.assertFalse(result['fallback_used']);self.assertFalse(result['action_replayed'])
        self.ctx.dispatch_tool.assert_not_called()
        self.provider.execute.assert_not_called();self.provider.endpoint.assert_not_called()

    def test_nonpage_actions_use_public_dispatch_exactly_once(self):
        handler=self.register()
        for action in ('list','unlock'):
            self.ctx.dispatch_tool.reset_mock()
            args={'action':action,'backend':'synthetic'}
            result=self.invoke(handler,args,task_id='fixture')
            self.assertTrue(result['synthetic'])
            self.ctx.dispatch_tool.assert_called_once_with('browser_vault',args,task_id='fixture')

    def test_list_help_points_to_available_tool_and_keeps_item_metadata(self):
        handler=self.register()
        items=[{'title':'browser_vault action=unlock','username':'fixture@example.invalid'}]
        native={'success':True,'items':items,
            'hint':'Use browser_vault action=save_login or action=fill.',
            'locked':[{'backend':'fixture','unlock':'browser_vault action=unlock'}]}
        self.ctx.dispatch_tool.return_value=json.dumps(native)
        result=self.invoke(handler,{'action':'list'})
        self.assertEqual(result['items'],items)
        self.assertEqual(result['locked'][0]['unlock'],'browser_original_chrome_vault action=unlock')
        self.assertNotIn('browser_vault',result['hint'])
        self.assertNotIn('action=fill',result['hint'])
        self.assertFalse(result['page_actions_available'])
        self.ctx.dispatch_tool.assert_called_once()
        self.provider.execute.assert_not_called()

    def test_list_errors_and_unlock_results_preserve_native_response(self):
        handler=self.register()
        for action,native in (('list',{'success':False,'error':'fixture locked'}),
                              ('unlock',{'success':True,'hint':'fixture unlocked'})):
            with self.subTest(action=action):
                self.ctx.dispatch_tool.reset_mock()
                self.ctx.dispatch_tool.return_value=json.dumps(native)
                self.assertEqual(self.invoke(handler,{'action':action}),native)
                self.ctx.dispatch_tool.assert_called_once()

    def test_invalid_list_response_refuses_without_replay(self):
        handler=self.register();self.ctx.dispatch_tool.return_value='invalid JSON'
        result=self.invoke(handler,{'action':'list'})
        self.assertFalse(result['success']);self.assertFalse(result['action_replayed'])
        self.ctx.dispatch_tool.assert_called_once()

    def test_direct_dispatch_rechecks_native_suppression_and_route(self):
        handler=self.register()
        with patch('plugin.native_browser_tools_disabled',return_value=False):
            self.assertFalse(self.invoke(handler,{'action':'list'})['success'])
        with patch('plugin.browser_config',return_value={'cloud_provider':plugin.NAME,'backend':'off'}):
            self.assertFalse(json.loads(handler({'action':'list'}))['success'])
        self.ctx.dispatch_tool.assert_not_called()

    def test_dispatch_exception_is_not_replayed(self):
        handler=self.register();self.ctx.dispatch_tool.side_effect=RuntimeError('vault unavailable')
        result=self.invoke(handler,{'action':'unlock'})
        self.assertFalse(result['success']);self.assertFalse(result['action_replayed'])
        self.ctx.dispatch_tool.assert_called_once()

    def test_unselected_provider_refuses_without_native_dispatch(self):
        handler=self.register()
        with patch('plugin.browser_config',return_value={'cloud_provider':'other'}):
            result=json.loads(handler({'action':'fill'},task_id='fixture'))
        self.assertFalse(result['success']);self.assertFalse(result['fallback_used'])
        self.ctx.dispatch_tool.assert_not_called()

if __name__=='__main__':unittest.main()
