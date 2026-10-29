"""Cleanup must observe disappearance, not equate a CDP ack with completion."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from binding import BoundBrowser


class CleanupConfirmationTests(unittest.TestCase):
    def browser(self, close):
        live={'owned':{'targetId':'owned','type':'page','browserContextId':'ctx'},
              'manual':{'targetId':'manual','type':'page','browserContextId':'ctx'}}
        calls=[]
        def wire(method,params=None,session=None):
            calls.append((method,params))
            if method=='Target.getTargets':return {'targetInfos':list(live.values())}
            if method=='Browser.getWindowForTarget':return {'windowId':7}
            if method=='Target.closeTarget':return close(live)
            raise AssertionError(method)
        state={'current':'owned','context':'ctx','owned':{'owned':7},'baseline':['manual']}
        return BoundBrowser(wire,state),live,calls

    def test_acknowledged_but_live_target_is_retained_without_replaying_close(self):
        browser,live,calls=self.browser(lambda live:{'success':True})
        with patch('time.sleep'),patch('time.monotonic',side_effect=range(100)):
            result=browser.cleanup()
        self.assertFalse(result['success'],result)
        self.assertEqual(result['remaining_owned_targets'],['owned'])
        self.assertEqual(browser.state['owned'],{'owned':7})
        self.assertEqual(result['cleanup_errors']['owned']['code'],'close_not_observed')
        self.assertEqual([params['targetId'] for method,params in calls if method=='Target.closeTarget'],['owned'])
        self.assertIn('manual',live)

    def test_per_target_failure_has_bounded_diagnostic_without_exception_payload(self):
        def close(live):raise RuntimeError('private page content must not escape')
        browser,live,calls=self.browser(close)
        result=browser.cleanup()
        self.assertFalse(result['success'])
        self.assertEqual(result['cleanup_errors']['owned'],{'code':'close_failed','error_type':'RuntimeError'})
        self.assertNotIn('private',str(result))
        self.assertEqual(browser.state['owned'],{'owned':7})
        self.assertIn('manual',live)

    def test_confirmed_disappearance_retires_only_exact_owned_target(self):
        def close(live):live.pop('owned');return {'success':True}
        browser,live,calls=self.browser(close)
        self.assertEqual(browser.cleanup(),{'remaining_owned_targets':[],'unresolved_creation':False,'success':True})
        self.assertEqual(browser.state['owned'],{})
        self.assertEqual(set(live),{'manual'})

    def test_inventory_loss_after_ack_keeps_outcome_unknown_and_ownership(self):
        browser,live,calls=self.browser(lambda live:{'success':True})
        original=browser.wire
        acknowledged=False
        def wire(method,params=None,session=None):
            nonlocal acknowledged
            if method=='Target.getTargets' and acknowledged:raise OSError('private transport details')
            result=original(method,params,session)
            if method=='Target.closeTarget':acknowledged=True
            return result
        browser.wire=wire
        result=browser.cleanup()
        self.assertFalse(result['success'])
        self.assertEqual(result['cleanup_errors']['owned'],{'code':'close_observation_failed','error_type':'OSError'})
        self.assertEqual(browser.state['owned'],{'owned':7})
        self.assertEqual(sum(m=='Target.closeTarget' for m,p in calls),1)

    def test_delayed_destruction_is_observed_on_same_wire_without_close_replay(self):
        browser,live,calls=self.browser(lambda live:{'success':True})
        original=browser.wire;observations=0;acknowledged=False
        def wire(method,params=None,session=None):
            nonlocal observations,acknowledged
            if method=='Target.getTargets' and acknowledged:
                observations+=1
                if observations==3:live.pop('owned')
            result=original(method,params,session)
            if method=='Target.closeTarget':acknowledged=True
            return result
        browser.wire=wire;checkpoints=[]
        browser.checkpoint=lambda:checkpoints.append(dict(browser.state['owned']))
        with patch('time.sleep') as sleep,patch('time.monotonic',return_value=0):
            result=browser.cleanup()
        self.assertTrue(result['success'],result)
        self.assertEqual(observations,3)
        self.assertEqual(sleep.call_count,2)
        self.assertEqual(checkpoints[-1],{})
        self.assertTrue(all(snapshot=={'owned':7} for snapshot in checkpoints[:-1]))
        self.assertEqual(sum(m=='Target.closeTarget' for m,p in calls),1)
        self.assertEqual(set(live),{'manual'})

    def test_multiple_targets_share_one_polling_budget_not_one_per_target(self):
        browser,live,calls=self.browser(lambda live:{'success':True})
        live['other']={'targetId':'other','type':'page','browserContextId':'ctx'}
        browser.state['owned']['other']=7
        ticks=[0,0,.99,1]
        with patch('time.sleep') as sleep,patch('time.monotonic',side_effect=ticks) as clock:
            result=browser.cleanup()
        self.assertFalse(result['success'],result)
        self.assertEqual(set(result['remaining_owned_targets']),{'owned','other'})
        self.assertEqual(set(browser.state['owned']),{'owned','other'})
        self.assertEqual({row['code'] for row in result['cleanup_errors'].values()},{'close_not_observed'})
        self.assertEqual(clock.call_count,4)
        self.assertEqual(sleep.call_count,2)
        self.assertEqual([p['targetId'] for m,p in calls if m=='Target.closeTarget'],['owned','other'])
        self.assertIn('manual',live)

    def test_explicit_close_rejection_keeps_exact_ownership_and_diagnostic(self):
        browser,live,calls=self.browser(lambda live:{'success':False})
        result=browser.cleanup()
        self.assertFalse(result['success'])
        self.assertEqual(result['cleanup_errors'],{'owned':{'code':'close_rejected'}})
        self.assertEqual(browser.state['owned'],{'owned':7})
        self.assertEqual(sum(m=='Target.closeTarget' for m,p in calls),1)
        self.assertIn('manual',live)

    def test_retained_target_and_unresolved_creation_never_become_cleanup_success(self):
        browser,live,calls=self.browser(lambda live:{'success':True})
        browser.state['unresolved_creation']=True
        result=browser.cleanup(retain=['owned'])
        self.assertEqual(result,{'remaining_owned_targets':['owned'],'unresolved_creation':True,'success':False})
        self.assertEqual(browser.state['owned'],{'owned':7})
        self.assertFalse(any(m=='Target.closeTarget' for m,p in calls))

    def test_worker_preserves_diagnostic_and_checkpointed_ownership(self):
        import worker
        browser,live,calls=self.browser(lambda live:{'success':True})
        wire=browser.wire;checkpoints=[]
        class Transport:
            def __call__(self,*args,**kwargs):return wire(*args,**kwargs)
            def close(self):pass
        request={'state':browser.state,'cleanup':True}
        with patch('time.sleep'),patch('time.monotonic',side_effect=range(100)):
            result=worker.run(request,publish=lambda state:checkpoints.append(dict(state['owned'])),transport=Transport())
        self.assertFalse(result['success'],result)
        self.assertEqual(result['state']['owned'],{'owned':7})
        self.assertEqual(result['cleanup_errors']['owned']['code'],'close_not_observed')
        self.assertTrue(checkpoints)
        self.assertTrue(all(snapshot=={'owned':7} for snapshot in checkpoints))
        self.assertEqual(sum(m=='Target.closeTarget' for m,p in calls),1)


if __name__=='__main__':unittest.main()
