"""Operator diagnostic uses fixed scripts and only its own synthetic session IDs."""
import json
from contextvars import ContextVar
from pathlib import Path
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import selftest


class SelftestTests(unittest.TestCase):
    def test_manual_command_only_changes_its_consent_context(self):
        import consent
        ctx=Mock()
        selftest.register(ctx)
        command=ctx.register_command.call_args.kwargs['handler']
        def run(*args):
            self.assertTrue(consent._manual_consent.get())
            return {'success':True}
        with patch('selftest.run',side_effect=run):
            result=json.loads(command('manual'))
        self.assertEqual(result['consent_mode'],'manual')
        self.assertFalse(consent._manual_consent.get())

    def fixture(self,fail_start=False,shared_target=False):
        provider=SimpleNamespace(lock=threading.RLock(),states={('unrelated','keep'):{'manual':True}})
        calls=[];active=0;max_active=0
        def handler(args,**ids):
            nonlocal active,max_active
            key=(ids['task_id'],args['session'])
            with provider.lock:
                calls.append((dict(args),dict(ids)))
                active+=1;max_active=max(max_active,active)
            try:
                time.sleep(.01)
                if args['code']==selftest.FINISH_SOURCE:
                    with provider.lock:provider.states.pop(key,None)
                    return json.dumps({'success':True,'fallback_used':False})
                if args['code']==selftest.START_SOURCE:
                    target='shared' if shared_target else 'target-'+ids['task_id']
                    with provider.lock:
                        provider.states[key]={'state':{'verified':True,'current':target,'owned':{target:target+'-window'}}}
                    if fail_start and ids['task_id'].endswith('-1'):
                        return json.dumps({'success':False,'fallback_used':False,'error':'synthetic-private-details'})
                return json.dumps({'success':True,'fallback_used':False,
                    'stdout':'Example Domain\nSELFTEST_WAIT_COMPLETE'})
            finally:
                with provider.lock:active-=1
        return provider,handler,calls,lambda:max_active

    def test_three_sessions_run_concurrently_reuse_owned_targets_and_cleanup_only_their_ids(self):
        provider,handler,calls,peak=self.fixture();finalize=Mock()
        report=selftest.run(provider,handler,lambda:{'ready':True},finalize)
        self.assertTrue(report['success'],report)
        self.assertEqual(report['level'],'registered_tool_in_gateway_not_llm_agent')
        self.assertEqual(len(report['sessions']),3)
        self.assertGreaterEqual(peak(),3)
        self.assertEqual(len(calls),9)
        self.assertEqual({call[0]['code'] for call in calls},
            {selftest.START_SOURCE,selftest.PARALLEL_SOURCE,selftest.FINISH_SOURCE})
        self.assertTrue(all(call[0]['timeout_s']==20 for call in calls))
        self.assertEqual(provider.states,{('unrelated','keep'):{'manual':True}})
        self.assertEqual(finalize.call_count,3)

    def test_startup_failure_does_not_replay_page_work_and_still_cleans_own_sessions(self):
        provider,handler,calls,_=self.fixture(fail_start=True)
        report=selftest.run(provider,handler,lambda:{'ready':True})
        self.assertFalse(report['success'])
        self.assertTrue(report['checks']['all_test_sessions_cleaned'])
        self.assertEqual(report['startup_calls'],2)
        self.assertEqual(sum(args['code']==selftest.START_SOURCE for args,ids in calls),2)
        self.assertNotIn(selftest.PARALLEL_SOURCE,[args['code'] for args,ids in calls])
        self.assertNotIn('synthetic-private-details',json.dumps(report))
        self.assertEqual(provider.states,{('unrelated','keep'):{'manual':True}})

    def test_startup_operator_diagnostic_uses_private_sink_and_excludes_page_payloads(self):
        provider,handler,calls,_=self.fixture();private_sinks=[]
        def failed(args,**ids):
            private_sinks.append((args['code'],callable(ids.get('_diagnostic_sink'))))
            result=handler(args,**ids)
            if args['code']==selftest.START_SOURCE:
                ids['_diagnostic_sink']({'error':'specific-worker-failure:'+'x'*1000,
                    'error_type':'RuntimeError','uncertain':False,'stdout':'private-page-output',
                    'state':{'private-target':7}})
                return {'success':False,'fallback_used':False,'error_code':'browser_action_failed',
                    'error':'The browser action failed.'}
            return result
        report=selftest.run(provider,failed,lambda:{'ready':True})
        self.assertFalse(report['success'])
        self.assertEqual(report['startup_calls'],1)
        error=next(e for e in report['errors'] if e['phase']=='startup')
        self.assertEqual(set(error['diagnostic']),{'error','error_type','uncertain'})
        self.assertEqual(len(error['diagnostic']['error']),800)
        self.assertIn('specific-worker-failure',error['diagnostic']['error'])
        self.assertNotIn('private-page-output',json.dumps(report))
        self.assertNotIn('private-target',json.dumps(report))
        self.assertTrue(all(enabled==(source==selftest.START_SOURCE) for source,enabled in private_sinks))
        self.assertTrue(report['checks']['all_test_sessions_cleaned'])

    def test_shared_target_is_not_accepted_as_session_isolation(self):
        provider,handler,calls,_=self.fixture(shared_target=True)
        report=selftest.run(provider,handler,lambda:{'ready':True})
        self.assertFalse(report['success'])
        self.assertFalse(report['checks']['distinct_owned_targets'])
        self.assertTrue(report['checks']['all_test_sessions_cleaned'])

    def test_cleanup_failure_is_visible_and_cleanup_is_not_replayed(self):
        provider,handler,calls,_=self.fixture()
        cleanup_calls=[]
        def failed_cleanup(args,**ids):
            if args['code']==selftest.FINISH_SOURCE:
                cleanup_calls.append(ids['task_id'])
                return {'success':False,'fallback_used':False}
            return handler(args,**ids)
        report=selftest.run(provider,failed_cleanup,lambda:{'ready':True})
        self.assertFalse(report['success'])
        self.assertFalse(report['checks']['all_test_sessions_cleaned'])
        self.assertEqual(len(cleanup_calls),3)
        self.assertEqual(len(set(cleanup_calls)),3)
        self.assertEqual(sum(e['code']=='selftest_cleanup_incomplete' for e in report['errors']),3)

    def test_readiness_refusal_never_calls_browser_handler(self):
        handler=Mock()
        report=selftest.run(object(),handler,lambda:{'ready':False})
        self.assertFalse(report['browser_actions_started'])
        handler.assert_not_called()

    def test_parallel_calls_and_cleanup_keep_host_profile_context(self):
        profile=ContextVar('selftest_profile',default='wrong-profile')
        token=profile.set('calling-profile')
        provider,handler,calls,_=self.fixture();seen=[]
        def scoped(args,**ids):
            seen.append(profile.get())
            return handler(args,**ids)
        try:report=selftest.run(provider,scoped,lambda:{'ready':True})
        finally:profile.reset(token)
        self.assertTrue(report['success'],report)
        self.assertEqual(seen,['calling-profile']*9)

    def test_operator_command_rejects_arguments_and_has_no_tool_registration(self):
        ctx=Mock();handler=Mock()
        selftest.register(ctx,object(),handler,lambda:{'ready':True})
        command=ctx.register_command.call_args.kwargs['handler']
        result=json.loads(command('https://unapproved.example'))
        self.assertEqual(result['errors'][0]['code'],'selftest_arguments_not_supported')
        handler.assert_not_called();ctx.register_tool.assert_not_called()

    def test_missing_native_suppression_command_is_inert(self):
        ctx=Mock();selftest.register(ctx)
        result=json.loads(ctx.register_command.call_args.kwargs['handler'](''))
        self.assertEqual(result['errors'][0]['code'],'browser_native_tools_enabled')
        self.assertFalse(result['browser_actions_started'])


if __name__=='__main__':unittest.main()
