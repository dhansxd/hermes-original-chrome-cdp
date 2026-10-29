"""Final cleanup accounting includes ownership acquired during confirmation."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from binding import BoundBrowser
import plugin
import worker


class ConfirmationTransport:
    def __init__(self,late_child):
        self.live={'root':{'targetId':'root','type':'page','browserContextId':'ctx'},
                   'peer':{'targetId':'peer','type':'page','browserContextId':'ctx'}}
        self.late_child=late_child;self.ack=False;self.calls=[]
    def pump(self):pass
    def close(self):pass
    def __call__(self,method,params=None,session=None):
        self.calls.append((method,params))
        if method=='Target.getTargets':
            if self.ack and self.late_child:
                self.late_child=False
                child={'targetId':'child','type':'page','browserContextId':'ctx','openerId':'root'}
                self.live['child']=child
                # Delivery precedes retirement of the positively owned opener.
                self.on_event({'method':'Target.targetCreated','params':{'targetInfo':child},'session_id':None})
            return {'targetInfos':list(self.live.values())}
        if method=='Browser.getWindowForTarget':return {'windowId':7}
        if method=='Target.closeTarget':
            self.ack=True;self.live.pop(params['targetId'])
            return {'success':True}
        raise AssertionError('unexpected offline command: '+method)


def owned_state():
    return {'current':'root','context':'ctx','owned':{'root':7},'baseline':['peer'],'verified':True}


class FinalOwnershipTests(unittest.TestCase):
    def assert_only_root_closed(self,wire):
        self.assertEqual([params['targetId'] for method,params in wire.calls if method=='Target.closeTarget'],['root'])
        self.assertIn('peer',wire.live)

    def test_confirmation_child_is_checkpointed_and_reported_remaining(self):
        wire=ConfirmationTransport(True);state=owned_state();checkpoints=[]
        result=BoundBrowser(wire,state,lambda:checkpoints.append(copy.deepcopy(state))).cleanup()
        self.assertIn({'root':7,'child':None},[s['owned'] for s in checkpoints])
        self.assertEqual(checkpoints[-1]['owned'],{'child':None})
        self.assertEqual(state['owned'],{'child':None})
        self.assertEqual(result['remaining_owned_targets'],['child'])
        self.assertFalse(result['success'],result)
        self.assertFalse(result['unresolved_creation'])
        self.assertEqual(set(wire.live),{'peer','child'})
        self.assert_only_root_closed(wire)

    def test_worker_cleanup_reports_the_same_final_child_ownership(self):
        wire=ConfirmationTransport(True);state=owned_state();checkpoints=[]
        with patch.object(worker,'Wire',side_effect=AssertionError('no connector allowed')):
            result=worker.run({'state':state,'cleanup':True},publish=lambda state:checkpoints.append(copy.deepcopy(state)),transport=wire)
        self.assertEqual(result['state']['owned'],{'child':None})
        self.assertEqual(result['remaining_owned_targets'],['child'])
        self.assertFalse(result['success'],result)
        self.assertEqual(checkpoints[-1]['owned'],{'child':None})
        self.assert_only_root_closed(wire)

    def provider_case(self,late_child,unresolved=False):
        wire=ConfirmationTransport(late_child);state=owned_state()
        if unresolved:state['unresolved_creation']=True
        provider=plugin.ChromeProvider(data='/fixture',workspace='/fixture-work')
        key=('cleanup-task','default');entry={'endpoint':'offline://fixture','state':state}
        peer={'endpoint':'offline://peer','state':{'owned':{'peer':7}},'observer':Mock()}
        provider.states[key]=entry;provider.states[('peer-task','default')]=peer
        def offline_worker(request,timeout,*,entry):
            return worker.run(request,publish=lambda state:entry.update(state=state),transport=wire)
        with patch.object(provider,'_worker',side_effect=offline_worker) as called,patch.object(worker,'Wire',side_effect=AssertionError('no connector allowed')):
            closed=provider.close_session(key[0])
        called.assert_called_once()
        self.assertIs(provider.states[('peer-task','default')],peer)
        peer['observer'].close.assert_not_called()
        self.assertEqual(peer['state']['owned'],{'peer':7})
        self.assert_only_root_closed(wire)
        return provider,key,entry,closed

    def test_provider_retains_entry_with_actual_worker_late_child_result(self):
        provider,key,entry,closed=self.provider_case(True)
        self.assertFalse(closed)
        self.assertIs(provider.states.get(key),entry)
        self.assertEqual(entry['state']['owned'],{'child':None})
        result=provider.last_cleanup[key]
        self.assertFalse(result['success'])
        self.assertEqual(result['remaining_owned_targets'],['child'])

    def test_no_child_success_releases_only_the_finished_provider_entry(self):
        provider,key,entry,closed=self.provider_case(False)
        self.assertTrue(closed)
        self.assertNotIn(key,provider.states)
        self.assertEqual(entry['state']['owned'],{})
        self.assertEqual(provider.last_cleanup[key]['remaining_owned_targets'],[])
        self.assertTrue(provider.last_cleanup[key]['success'])

    def test_unresolved_creation_retains_provider_even_without_remaining_ids(self):
        provider,key,entry,closed=self.provider_case(False,unresolved=True)
        self.assertFalse(closed)
        self.assertIs(provider.states.get(key),entry)
        self.assertEqual(entry['state']['owned'],{})
        self.assertEqual(provider.last_cleanup[key]['remaining_owned_targets'],[])
        self.assertTrue(provider.last_cleanup[key]['unresolved_creation'])
        self.assertFalse(provider.last_cleanup[key]['success'])


if __name__=='__main__':unittest.main()
