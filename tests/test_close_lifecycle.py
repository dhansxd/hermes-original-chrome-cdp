"""A close is sent once and remains owned until disappearance is observed."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from binding import BoundBrowser
from observer import ScopedObserver


class CloseWire:
    def __init__(self):
        self.live={t:{'targetId':t,'type':'page','browserContextId':'ctx'} for t in ('owned','peer')}
        self.calls=[];self.close_error=None;self.remove_after=None;self.polls=0;self.sent=False
        self.events=[];self.dialogs={};self.event_gaps={};self.detached_sessions=set();self.event_overflow=False
    def __call__(self,method,params=None,session=None):
        self.calls.append((method,params,session))
        if method=='Target.getTargets':
            if self.sent:
                self.polls+=1
                if self.remove_after is not None and self.polls>=self.remove_after:self.live.pop('owned',None)
            return {'targetInfos':list(self.live.values())}
        if method=='Browser.getWindowForTarget':return {'windowId':7}
        if method=='Target.closeTarget':
            self.sent=True
            if self.close_error:raise self.close_error
            return {'success':True}
        return {}
    def close(self):pass


def state():
    return {'context':'ctx','current':'owned','owned':{'owned':7},'baseline':['peer']}


class CloseLifecycleTests(unittest.TestCase):
    def test_ack_only_keeps_ownership_and_cleanup_does_not_send_again(self):
        wire=CloseWire();owned=state();browser=BoundBrowser(wire,owned)
        with patch('binding.time.sleep'),patch('binding.time.monotonic',side_effect=range(100)):
            with self.assertRaisesRegex(TimeoutError,'target_close_unconfirmed'):
                browser.cdp('Target.closeTarget',targetId='owned')
            result=browser.cleanup()
        self.assertFalse(result['success'])
        self.assertEqual(owned['owned'],{'owned':7})
        self.assertEqual(owned['pending_closes'],{'owned':'acknowledged'})
        self.assertEqual(sum(m=='Target.closeTarget' for m,_,_ in wire.calls),1)
        self.assertIn('peer',wire.live)

    def test_intent_is_checkpointed_before_send_and_disappearance_is_required(self):
        wire=CloseWire();wire.remove_after=3;owned=state();saved=[]
        browser=BoundBrowser(wire,owned,lambda:saved.append(copy.deepcopy(owned)))
        original=wire.__call__
        def observed(method,params=None,session=None):
            if method=='Target.closeTarget':
                self.assertEqual(saved[-1]['pending_closes'],{'owned':'sent'})
                self.assertEqual(saved[-1]['owned'],{'owned':7})
            return original(method,params,session)
        browser.wire=observed
        with patch('binding.time.sleep'),patch('binding.time.monotonic',return_value=0):
            self.assertEqual(browser.cdp('Target.closeTarget',targetId='owned'),{'success':True})
        self.assertEqual(owned['owned'],{})
        self.assertNotIn('pending_closes',owned)
        self.assertEqual(set(wire.live),{'peer'})
        self.assertEqual(wire.polls,3)

    def test_unknown_send_survives_new_binding_without_replay(self):
        wire=CloseWire();wire.close_error=TimeoutError('injected lost acknowledgement');owned=state()
        with self.assertRaises(TimeoutError):BoundBrowser(wire,owned).cdp('Target.closeTarget',targetId='owned')
        self.assertEqual(owned['pending_closes'],{'owned':'sent'})
        wire.close_error=None;wire.live.pop('owned')
        self.assertTrue(BoundBrowser(wire,copy.deepcopy(owned)).cleanup()['success'])
        self.assertEqual(sum(m=='Target.closeTarget' for m,_,_ in wire.calls),1)
        self.assertEqual(set(wire.live),{'peer'})

    def test_pending_target_cannot_be_driven_or_reattached(self):
        wire=CloseWire();owned=state();owned['pending_closes']={'owned':'sent'}
        browser=BoundBrowser(wire,owned)
        for method,params in [('Page.navigate',{'url':'https://example.test'}),
                              ('Target.attachToTarget',{'targetId':'owned'}),
                              ('Target.activateTarget',{'targetId':'owned'})]:
            with self.subTest(method=method),self.assertRaisesRegex(RuntimeError,'target_close_pending'):
                browser.cdp(method,**params)
        self.assertEqual(wire.calls,[])

    def test_observer_keeps_mapping_until_disappearance_and_never_repeats_close(self):
        wire=CloseWire();owned=state()
        with patch('observer.Wire',return_value=wire):observer=ScopedObserver('fixture','/fixture/Default')
        self.addCleanup(observer.close)
        observer.sessions={'owned':'owned-sid','peer':'peer-sid'}
        observer.request({'method':'Target.closeTarget','params':{'targetId':'owned'}},owned)
        self.assertEqual(observer.sessions,{'owned':'owned-sid','peer':'peer-sid'})
        wire.detached_sessions.add('owned-sid')
        observer.request({'method':'Target.getTargets'},owned)
        self.assertFalse(observer.closed)
        with self.assertRaisesRegex(RuntimeError,'target_close_pending'):
            observer.request({'method':'Target.closeTarget','params':{'targetId':'owned'}},owned)
        self.assertEqual(sum(m=='Target.closeTarget' for m,_,_ in wire.calls),1)
        wire.live.pop('owned')
        observer.request({'method':'Target.getTargets'},owned)
        self.assertEqual(observer.sessions,{'peer':'peer-sid'})
        self.assertNotIn('owned-sid',wire.detached_sessions)
        self.assertFalse(observer.closed)


if __name__=='__main__':unittest.main()
