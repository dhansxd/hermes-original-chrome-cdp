"""Inert browser transport + real PluginContext hook dispatch; never opens Chrome."""
import json, os, sys, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path.home()/'.hermes/hermes-agent'))
import hermes_bootstrap
from hermes_cli.plugins import PluginContext, PluginManager
from hermes_cli.plugins_manifest import PluginManifest
from plugin import ChromeProvider


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path.home()/'.hermes/cache/scratch',prefix='chrome-lifecycle-')
        self.addCleanup(self.tmp.cleanup)
        home=Path(self.tmp.name)
        (home/'config.yaml').write_text('plugins:\n  entries:\n    original-chrome-default:\n      granted_capabilities: [tools.override]\n')
        self.env=patch.dict(os.environ,{'HERMES_HOME':str(home)})
        self.env.start();self.addCleanup(self.env.stop)
        self.manager=PluginManager(scope_key=str(home))
        self.ctx=PluginContext(PluginManifest(name='original-chrome-default',source='user',capabilities=['tools.override']),self.manager)
        self.provider=ChromeProvider()
        self.calls=[]
        self.provider.endpoint=lambda **kw:'ws://inert'
        def worker(request,timeout,**kwargs):
            self.calls.append(request)
            return {'success':True,'state':{'owned':['agent-only']}}
        self.provider._worker=worker

    def install(self):
        from plugin import BrowserLifecycle
        self.lifecycle=BrowserLifecycle(self.ctx,self.provider)
        self.lifecycle.register()

    def execute(self,task='task-a',sid='session-a',route='route-a'):
        self.lifecycle.bind(task_id=task,session_id=sid,session_key=route)
        return json.loads(self.provider.execute({'code':'print(1)'},task_id=task))

    def fire(self,name,**kwargs):
        return self.manager.invoke_hook(name,**kwargs)

    def test_finalize_cleans_owned_state_only_for_matching_session(self):
        self.install();self.execute();self.execute('task-b','session-b','route-b')
        self.fire('on_session_finalize',session_id='session-a',reason='exit')
        self.assertNotIn(('task-a','default'),self.provider.states)
        self.assertIn(('task-b','default'),self.provider.states)
        cleanups=[r for r in self.calls if r.get('cleanup')]
        self.assertEqual(len(cleanups),1)
        self.assertEqual(cleanups[0]['state']['owned'],['agent-only'])
        self.fire('on_session_finalize',session_id='session-a',reason='exit')
        self.assertEqual(len([r for r in self.calls if r.get('cleanup')]),1)

    def test_cancel_uses_route_mapping_and_interruption_uses_task_identity(self):
        self.install();self.execute();self.execute('task-b','session-b','route-b')
        self.fire('agent_loop_stopped',session_key='unrelated',reason='stop')
        self.assertEqual(len(self.provider.states),2)
        self.fire('agent_loop_stopped',session_key='route-a',reason='stop')
        self.assertNotIn(('task-a','default'),self.provider.states)
        self.assertIn(('task-b','default'),self.provider.states)
        self.fire('on_session_end',task_id='task-b',session_id='session-b',interrupted=True)
        self.assertFalse(self.provider.states)

    def test_completed_turn_preserves_manual_wait_and_unknown_task_completion(self):
        self.install();self.execute()
        self.fire('on_human_input_request',session_id='session-a',request_id='wait-1',kind='clarify')
        result=self.fire('on_session_end',session_id='session-a',task_id='task-a',completed=True)
        self.assertIn(('task-a','default'),self.provider.states)
        self.assertEqual(result[0]['reason'],'pending_human_input')
        self.fire('on_human_input_resolved',session_id='session-a',request_id='wait-1',outcome='answered')
        result=self.fire('on_session_end',session_id='session-a',task_id='task-a',completed=True)
        self.assertEqual(result[0]['reason'],'turn_is_not_task_completion')
        self.assertIn(('task-a','default'),self.provider.states)

    def test_failed_cleanup_is_visible_in_event_next_tool_and_output_transform(self):
        self.install();self.execute()
        events=[];delivered=threading.Event()
        def receive(**payload):events.append(payload);delivered.set()
        self.ctx.subscribe('original-chrome-default:browser_cleanup',receive)
        self.provider._worker=lambda *a,**k:{'success':False,'error':'owned target missing'}
        self.fire('on_session_finalize',session_id='session-a',reason='exit')
        self.assertIn(('task-a','default'),self.provider.states)
        self.assertFalse(self.lifecycle.status('session-a')[0]['success'])
        self.assertTrue(delivered.wait(3));self.assertFalse(events[0]['success'])
        response=self.fire('transform_llm_output',session_id='session-a',response_text='Done')
        self.assertIn('Browser cleanup failed',response[0])
        self.assertIn('owned target missing',response[0])
        self.assertTrue(self.lifecycle.status('session-a'))

    def test_successful_retry_clears_failure_warning(self):
        self.install();self.execute()
        self.provider._worker=lambda *a,**k:{'success':False,'error':'cleanup denied'}
        self.fire('on_session_finalize',session_id='session-a')
        self.provider._worker=lambda *a,**k:{'success':True}
        self.fire('on_session_finalize',session_id='session-a')
        self.assertFalse(self.fire('transform_llm_output',session_id='session-a',response_text='Done'))

    def test_timeout_without_ownership_never_adopts_targets_for_cleanup(self):
        import subprocess
        self.install();self.lifecycle.bind(task_id='task-a',session_id='session-a',session_key='route-a')
        def timeout(*a,**k):raise subprocess.TimeoutExpired('inert',5)
        self.provider._worker=timeout
        self.provider.execute({'code':'print(1)'},task_id='task-a')
        result=self.fire('agent_loop_stopped',session_key='route-a')
        self.assertIn('ownership_lost_after_timeout',json.dumps(result))
        self.assertIn(('task-a','default'),self.provider.states)

    def test_registered_handler_binds_actual_caller_and_returns_cleanup_notice(self):
        from plugin import register
        from tools.registry import registry
        from tools.approval_context import set_current_session_key,reset_current_session_key
        token=set_current_session_key('actual-route')
        self.addCleanup(reset_current_session_key,token)
        with patch('plugin.ChromeProvider',return_value=self.provider),patch('hermes_cli.config.read_raw_config',return_value={'browser':{'cloud_provider':'original-chrome-default'}}):
            register(self.ctx)
            result=json.loads(registry.dispatch('browser_exec',{'code':'print(1)'},scope=str(Path(self.tmp.name)),task_id='actual-task',session_id='actual-session'))
            self.assertTrue(result['success'])
            self.provider._worker=lambda *a,**k:{'success':False,'error':'cleanup denied'}
            self.fire('agent_loop_stopped',session_key='actual-route',reason='stop')
            result=json.loads(registry.dispatch('browser_exec',{'code':'print(2)'},scope=str(Path(self.tmp.name)),task_id='actual-task',session_id='actual-session'))
            self.assertFalse(result['browser_cleanup'][0]['success'])
            self.assertIn('cleanup denied',json.dumps(result['browser_cleanup']))

    def test_cancel_waits_for_running_worker_then_closes_once(self):
        self.install();self.lifecycle.bind(task_id='task-a',session_id='session-a',session_key='route-a')
        entered=threading.Event();release=threading.Event()
        def worker(request,timeout,**kwargs):
            self.calls.append(request)
            if not request.get('cleanup'):
                entered.set();self.assertTrue(release.wait(3))
            return {'success':True,'state':{'owned':['agent-only']}}
        self.provider._worker=worker
        executing=threading.Thread(target=lambda:self.provider.execute({'code':'print(1)'},task_id='task-a'))
        cancelling=threading.Thread(target=lambda:self.fire('agent_loop_stopped',session_key='route-a',reason='stop'))
        executing.start()
        try:
            self.assertTrue(entered.wait(3));cancelling.start()
            self.assertFalse(any(r.get('cleanup') for r in self.calls))
        finally:
            release.set();executing.join(3)
            if cancelling.ident:cancelling.join(3)
        self.assertFalse(executing.is_alive());self.assertFalse(cancelling.is_alive())
        self.assertFalse(self.provider.states)
        self.assertEqual(len([r for r in self.calls if r.get('cleanup')]),1)


if __name__=='__main__':unittest.main()
