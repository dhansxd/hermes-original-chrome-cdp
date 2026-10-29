"""Parent-observed ownership survives stale worker snapshots and durable failures."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observer import ScopedObserver
from plugin import ChromeProvider


class CheckpointMergeTests(unittest.TestCase):
    def fixture(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        provider=ChromeProvider(data=temporary.name,workspace=temporary.name+'/work')
        journal=provider._journal();record=journal.begin_seed()
        journal.bind_generation(record['id'],{'pid':123,'started':1,
            'endpoint':'ws://127.0.0.1:5000/devtools/browser/fixture'})
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_gaps={}
        wire.event_overflow=False;wire.detached_sessions=set()
        wire.return_value={'windowId':2}
        with patch('observer.Wire',return_value=wire),patch('observer.NativeDialogs'):
            observer=ScopedObserver('fixture',temporary.name+'/Default')
        self.addCleanup(observer.close)
        state={'context':'ctx','current':'root','owned':{'root':1},'baseline':['manual'],'verified':True}
        entry={'state':state,'observer':observer,'journal_id':record['id']}
        entry['_checkpoint']=lambda value:provider._checkpoint(entry,value)
        observer.entries=[entry];observer.state=state;observer.watched={'root'}
        provider._checkpoint(entry,state)
        return provider,journal,entry,observer,wire

    @staticmethod
    def attach_child(observer):
        observer._attached({'sessionId':'child-session','waitingForDebugger':True,
            'targetInfo':{'targetId':'child','type':'page','browserContextId':'ctx','openerId':'root'}})

    def test_stale_worker_snapshot_cannot_erase_parent_popup_or_pending_close(self):
        provider,journal,entry,observer,wire=self.fixture()
        old=copy.deepcopy(entry['state'])
        self.attach_child(observer)
        entry['state']['pending_closes']={'child':'acknowledged'}
        provider._checkpoint(entry,entry['state'])
        provider._checkpoint(entry,old)
        self.assertEqual(entry['state']['owned'],{'root':1,'child':2})
        self.assertEqual(entry['state']['pending_closes'],{'child':'acknowledged'})
        self.assertIs(observer.state,entry['state'])
        self.assertEqual(journal.records()[0]['state']['owned'],{'root':1,'child':2})
        self.assertEqual(journal.records()[0]['state']['pending_closes'],{'child':'acknowledged'})
        self.assertFalse(observer.closed)

    def test_inventory_confirmed_close_retires_without_stale_resurrection(self):
        provider,journal,entry,observer,wire=self.fixture()
        self.attach_child(observer)
        entry['state']['pending_closes']={'child':'acknowledged'}
        observer.closing_targets.add('child');observer.watched.add('child')
        provider._checkpoint(entry,entry['state']);stale=copy.deepcopy(entry['state'])
        wire.side_effect=lambda method,*args: {'targetInfos':[
            {'targetId':'root','type':'page','browserContextId':'ctx'}]} if method=='Target.getTargets' else {}
        observer.request({'method':'Target.getTargets'},entry['state'])
        self.assertEqual(observer.confirmed_absent,{'child'})
        retired=copy.deepcopy(stale);retired['owned'].pop('child');retired.pop('pending_closes')
        provider._checkpoint(entry,retired)
        provider._checkpoint(entry,stale)
        self.assertEqual(entry['state']['owned'],{'root':1})
        self.assertNotIn('pending_closes',entry['state'])
        self.assertEqual(journal.records()[0]['state']['owned'],{'root':1})
        self.assertNotIn('child',observer.sessions)

    def test_close_ack_without_absence_does_not_authorize_retirement(self):
        provider,journal,entry,observer,wire=self.fixture()
        self.attach_child(observer)
        entry['state']['pending_closes']={'child':'acknowledged'}
        observer.closing_targets.add('child')
        stale=copy.deepcopy(entry['state']);stale['owned'].pop('child');stale.pop('pending_closes')
        provider._checkpoint(entry,stale)
        self.assertEqual(entry['state']['owned'],{'root':1,'child':2})
        self.assertEqual(entry['state']['pending_closes'],{'child':'acknowledged'})
        with self.assertRaisesRegex(RuntimeError,'cleanup_unconfirmed'):
            provider._complete_record(entry)
        self.assertEqual(len(journal.records()),1)

    def test_child_observed_during_inventory_is_not_absent_from_older_snapshot(self):
        provider,journal,entry,observer,wire=self.fixture()
        stale=copy.deepcopy(entry['state'])
        def respond(method,*args):
            if method=='Target.getTargets':
                self.attach_child(observer)
                return {'targetInfos':[{'targetId':'root','type':'page','browserContextId':'ctx'}]}
            return {'windowId':2}
        wire.side_effect=respond
        observer.request({'method':'Target.getTargets'},entry['state'])
        self.assertNotIn('child',observer.confirmed_absent)
        provider._checkpoint(entry,stale)
        self.assertEqual(journal.records()[0]['state']['owned'],{'root':1,'child':2})

    def test_explicit_close_rejection_allows_only_its_rejected_intent_to_clear(self):
        provider,journal,entry,observer,wire=self.fixture()
        entry['state']['pending_closes']={'root':'sent'}
        provider._checkpoint(entry,entry['state'])
        def respond(method,*args):
            if method=='Target.getTargets':return {'targetInfos':[
                {'targetId':'root','type':'page','browserContextId':'ctx'}]}
            if method=='Browser.getWindowForTarget':return {'windowId':1}
            if method=='Target.closeTarget':return {'success':False}
            return {}
        wire.side_effect=respond
        observer.request({'method':'Target.closeTarget','params':{'targetId':'root'}},entry['state'])
        self.assertEqual(observer.rejected_closes,{'root'})
        next_state=copy.deepcopy(entry['state']);next_state.pop('pending_closes')
        provider._checkpoint(entry,next_state)
        self.assertEqual(entry['state']['owned'],{'root':1})
        self.assertNotIn('pending_closes',journal.records()[0]['state'])

    def test_stale_unbound_window_never_downgrades_verified_mapping(self):
        provider,journal,entry,observer,wire=self.fixture()
        stale=copy.deepcopy(entry['state']);stale['owned']['root']=None
        provider._checkpoint(entry,stale)
        self.assertEqual(journal.records()[0]['state']['owned'],{'root':1})

    def test_context_or_window_rebinding_closes_observer_without_replacing_record(self):
        for field,value in (('context','other'),('owned',{'root':9})):
            with self.subTest(field=field):
                provider,journal,entry,observer,wire=self.fixture()
                before=copy.deepcopy(entry['state']);changed=copy.deepcopy(before);changed[field]=value
                with self.assertRaisesRegex(RuntimeError,'changed'):provider._checkpoint(entry,changed)
                self.assertTrue(observer.closed);wire.close.assert_called_once()
                self.assertEqual(entry['state'],before)
                self.assertEqual(journal.records()[0]['state']['owned'],{'root':1})

    def test_failed_journal_write_closes_observer_but_retains_new_ownership_in_memory(self):
        provider,journal,entry,observer,wire=self.fixture()
        stale=copy.deepcopy(entry['state']);self.attach_child(observer)
        with patch.object(journal,'checkpoint',side_effect=OSError('synthetic disk full')):
            with self.assertRaises(OSError):provider._checkpoint(entry,stale)
        self.assertTrue(observer.closed);wire.close.assert_called_once()
        self.assertEqual(entry['state']['owned'],{'root':1,'child':2})
        self.assertEqual(journal.records()[0]['state']['owned'],{'root':1,'child':2})
        with self.assertRaisesRegex(RuntimeError,'observer_lost'):
            observer.request({'method':'Target.getTargets'},entry['state'])


if __name__=='__main__':unittest.main()
