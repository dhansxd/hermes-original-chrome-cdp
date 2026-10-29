"""Disk-only provenance fixtures; never import Chrome/Hermes runtime or connect."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ownership_journal import JournalError,OwnershipJournal,browser_generation


class OwnershipJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/'journal'
        self.data=Path(self.temp.name)/'chrome'
        self.journal=OwnershipJournal(self.folder,self.data)
        self.generation={'pid':123,'started':100.5,'endpoint':'ws://127.0.0.1:5000/devtools/browser/fixture'}

    def claimed(self):
        record=self.journal.begin_seed()
        info={'targetId':'owned','browserContextId':'default-context','type':'page','url':record['seed_url']}
        claimed=self.journal.claim_seed(record['id'],self.generation,[info],{'owned':7})
        return claimed,info

    def test_marker_and_record_survive_reload_before_any_gui_launch(self):
        record=self.journal.begin_seed()
        reloaded=OwnershipJournal(self.folder,self.data).records()
        self.assertEqual(reloaded,[record])
        self.assertTrue((self.folder/'seeds'/(record['id']+'.html')).is_file())
        self.assertEqual(record['phase'],'seed')
        self.assertIsNone(record['generation'])
        self.assertEqual(stat.S_IMODE(self.folder.stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE((self.folder/(record['id']+'.json')).stat().st_mode),0o600)

    def test_unbound_unique_marker_is_only_candidate_until_generation_claim_persisted(self):
        record=self.journal.begin_seed()
        info={'targetId':'seed','browserContextId':'default-context','type':'page','url':record['seed_url']}
        user={'targetId':'user','browserContextId':'default-context','type':'page','url':'https://example.test/account'}
        plan=self.journal.recovery_plan(self.generation,[info,user],{'seed':7,'user':8},record_ids=[record['id']])
        self.assertEqual(plan['records'],[])
        self.assertEqual(plan['seed_candidates'],[{'id':record['id'],'target':'seed','context':'default-context','window':7}])
        self.assertEqual(self.journal.records()[0]['state']['owned'],{})
        self.journal.claim_seed(record['id'],self.generation,[info,user],{'seed':7,'user':8})
        reloaded=OwnershipJournal(self.folder,self.data)
        self.journal.handoff(record['id'],reloaded.instance_id);reloaded.claim(record['id'])
        self.assertEqual(reloaded.recovery_plan(self.generation,[info,user],{'seed':7,'user':8},record_ids=[record['id']])['records'][0]['close'],['seed'])
        self.assertFalse(reloaded.records()[0]['state']['verified'],'cleanup ownership cannot claim profile verification')

    def test_duplicate_marker_missing_context_or_window_does_not_gain_ownership(self):
        record=self.journal.begin_seed()
        info={'targetId':'seed','browserContextId':'default-context','type':'page','url':record['seed_url']}
        for infos,windows in (
            ([info,dict(info,targetId='duplicate')],{'seed':7,'duplicate':8}),
            ([dict(info,browserContextId=None)],{'seed':7}),
            ([info],{}),
            ([dict(info,url='about:blank')],{'seed':7}),
        ):
            with self.subTest(infos=infos):
                with self.assertRaises(JournalError):
                    self.journal.claim_seed(record['id'],self.generation,infos,windows)
                self.assertEqual(self.journal.records()[0]['state']['owned'],{})

    def test_checkpoint_preserves_cleanup_metadata_without_page_account_or_task_data(self):
        record,info=self.claimed()
        state={'owned':{'owned':7},'current':'owned','context':'default-context','verified':True,
               'pending_closes':{'owned':'sent'},'unresolved_creation':True,
               'baseline':['private-user-target'],'dialogs':{'owned':'private dialog'},
               'url':'https://private.example/account','cookie':'private-cookie','task_id':'private-task'}
        saved=self.journal.checkpoint(record['id'],state)
        serialized=(self.folder/(record['id']+'.json')).read_text()
        for private in ('private-user-target','private dialog','private.example','private-cookie','private-task'):
            self.assertNotIn(private,serialized)
        self.assertNotIn('/devtools/browser/',serialized)
        self.assertEqual(saved['state']['pending_closes'],{'owned':'sent'})
        self.assertTrue(saved['state']['unresolved_creation'])
        plan=self.journal.recovery_plan(self.generation,[info],{'owned':7},record_ids=[record['id']])['records'][0]
        self.assertEqual(plan['close'],[])
        self.assertEqual(plan['observe_only'],['owned'])
        self.assertEqual(plan['blocked'],{'creation':'creation_unresolved'})

    def test_other_generation_reused_target_ids_never_produce_cleanup_authority(self):
        record,info=self.claimed()
        for changed in (dict(self.generation,pid=124),dict(self.generation,started=101),
                        dict(self.generation,endpoint='ws://127.0.0.1:5000/devtools/browser/restarted')):
            with self.subTest(generation=changed):
                plan=self.journal.recovery_plan(changed,[info],{'owned':7},record_ids=[record['id']])
                self.assertEqual(plan['records'],[])
                self.assertEqual(plan['seed_candidates'],[])
                self.assertEqual(plan['stale_records'],[record['id']])
                with self.assertRaisesRegex(JournalError,'generation_changed'):
                    self.journal.bind_generation(record['id'],changed)

    def test_context_and_window_mismatches_never_close_user_targets(self):
        record,info=self.claimed()
        for current,windows,reason in (
            (dict(info,browserContextId='other-context'),{'owned':7},'context_changed'),
            (dict(info,type='service_worker'),{'owned':7},'context_changed'),
            (info,{'owned':8},'window_unconfirmed'),
            (info,{},'window_unconfirmed'),
        ):
            with self.subTest(reason=reason):
                item=self.journal.recovery_plan(self.generation,[current],windows,record_ids=[record['id']])['records'][0]
                self.assertEqual(item['close'],[])
                self.assertEqual(item['blocked'],{'owned':reason})

    def test_missing_pending_close_is_observed_without_replay_and_requires_checkpoint_to_retire(self):
        record,info=self.claimed()
        state=record['state'];state['pending_closes']={'owned':'acknowledged'}
        self.journal.checkpoint(record['id'],state)
        plan=self.journal.recovery_plan(self.generation,[],{},record_ids=[record['id']])['records'][0]
        self.assertEqual(plan['missing'],['owned'])
        self.assertEqual(plan['close'],[])
        with self.assertRaisesRegex(JournalError,'cleanup_unconfirmed'):self.journal.complete(record['id'])
        self.journal.checkpoint(record['id'],{'owned':{},'verified':True})
        self.journal.complete(record['id'])
        self.assertEqual(self.journal.records(),[])
        self.assertFalse((self.folder/'seeds'/(record['id']+'.html')).exists())

    def test_seed_or_unresolved_creation_cannot_be_retired_as_complete(self):
        record=self.journal.begin_seed()
        self.journal.checkpoint(record['id'],{'owned':{}})
        with self.assertRaisesRegex(JournalError,'cleanup_unconfirmed'):self.journal.complete(record['id'])
        claimed,info=self.claimed()
        self.journal.checkpoint(claimed['id'],{'owned':{},'unresolved_creation':True})
        with self.assertRaisesRegex(JournalError,'cleanup_unconfirmed'):self.journal.complete(claimed['id'])

    def test_failed_atomic_replace_keeps_prior_record_and_removes_temporary_file(self):
        record,info=self.claimed()
        before=self.journal.records()
        with patch('ownership_journal.os.replace',side_effect=OSError('fixture disk failure')):
            with self.assertRaises(OSError):self.journal.checkpoint(record['id'],{'owned':{}})
        self.assertEqual(self.journal.records(),before)
        self.assertEqual(list(self.folder.glob('.record-*')),[])

    def test_foreign_profile_and_symlink_record_are_rejected(self):
        record,info=self.claimed()
        with self.assertRaisesRegex(JournalError,'profile_mismatch'):
            OwnershipJournal(self.folder,self.data/'other').records()
        path=self.folder/(record['id']+'.json');original=path.read_text()
        external=Path(self.temp.name)/'external.json';external.write_text(original)
        path.unlink();path.symlink_to(external)
        with self.assertRaises(OSError):self.journal.records()
        self.assertEqual(external.read_text(),original)

    def test_parallel_journal_instances_keep_both_records(self):
        other=OwnershipJournal(self.folder,self.data);results=[];errors=[]
        def create(journal):
            try:results.append(journal.begin_seed()['id'])
            except Exception as exc:errors.append(exc)
        threads=[threading.Thread(target=create,args=(journal,)) for journal in (self.journal,other)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(2)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors,[]);self.assertEqual(len(set(results)),2)
        self.assertEqual({r['id'] for r in self.journal.records()},set(results))

    def test_generation_requires_local_browser_endpoint_and_real_birth_identity(self):
        for invalid in (dict(self.generation,pid=True),dict(self.generation,started=float('nan')),
                        dict(self.generation,endpoint='https://remote.example/browser'),
                        dict(self.generation,endpoint='ws://127.0.0.1:5000/devtools/page/id')):
            with self.subTest(generation=invalid),self.assertRaises(JournalError):browser_generation(invalid)

    def test_same_pid_reload_cannot_take_active_lease_without_explicit_release(self):
        record,info=self.claimed()
        reloaded=OwnershipJournal(self.folder,self.data)
        self.assertEqual(reloaded.eligible_records(),[])
        self.assertEqual(self.journal.eligible_records(),[])
        with self.assertRaisesRegex(JournalError,'owner_active'):reloaded.claim(record['id'])
        with self.assertRaisesRegex(JournalError,'not_owner'):
            reloaded.recovery_plan(self.generation,[info],{'owned':7},record_ids=[record['id']])
        self.journal.release(record['id'])
        self.assertEqual([r['id'] for r in reloaded.eligible_records()],[record['id']])
        reloaded.claim(record['id'])
        with self.assertRaisesRegex(JournalError,'not_owner'):
            self.journal.checkpoint(record['id'],{'owned':{}})

    def test_named_handoff_cannot_be_stolen_by_third_provider(self):
        record,info=self.claimed()
        destination=OwnershipJournal(self.folder,self.data)
        third=OwnershipJournal(self.folder,self.data,owner_alive=lambda *args:False)
        self.journal.handoff(record['id'],destination.instance_id)
        self.assertEqual(third.eligible_records(),[])
        with self.assertRaisesRegex(JournalError,'owner_active'):third.claim(record['id'])
        destination.claim(record['id'])
        self.assertEqual(destination.records()[0]['owner']['instance'],destination.instance_id)

    def test_dead_owner_may_be_claimed_but_unknown_liveness_and_other_scope_cannot(self):
        record,info=self.claimed()
        unknown=OwnershipJournal(self.folder,self.data,owner_alive=lambda *args:None)
        with self.assertRaisesRegex(JournalError,'owner_active'):unknown.claim(record['id'])
        foreign=OwnershipJournal(self.folder,self.data,scope='different-provider',owner_alive=lambda *args:False)
        self.assertEqual(foreign.eligible_records(),[])
        with self.assertRaisesRegex(JournalError,'owner_active'):foreign.claim(record['id'])
        dead=OwnershipJournal(self.folder,self.data,owner_alive=lambda *args:False)
        self.assertEqual(len(dead.eligible_records()),1)
        dead.claim(record['id'])
        self.assertEqual(dead.records()[0]['owner']['instance'],dead.instance_id)

    def test_release_all_does_not_release_another_active_instance(self):
        ours=self.journal.begin_seed();other=OwnershipJournal(self.folder,self.data)
        theirs=other.begin_seed()
        self.assertEqual(self.journal.release_all(),[ours['id']])
        records={record['id']:record for record in self.journal.records()}
        self.assertTrue(records[ours['id']]['owner']['released'])
        self.assertFalse(records[theirs['id']]['owner']['released'])

    def test_concurrent_claimants_cannot_both_acquire_released_record(self):
        record,info=self.claimed();self.journal.release(record['id'])
        claimants=[OwnershipJournal(self.folder,self.data) for _ in range(2)]
        successes=[];failures=[]
        def acquire(journal):
            try:journal.claim(record['id']);successes.append(journal.instance_id)
            except JournalError as exc:failures.append(str(exc))
        threads=[threading.Thread(target=acquire,args=(journal,)) for journal in claimants]
        for thread in threads:thread.start()
        for thread in threads:thread.join(2)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(successes),1)
        self.assertEqual(failures,['ownership_journal_owner_active'])

    def test_retirement_requires_explicit_relevant_proof_and_held_lease(self):
        record,info=self.claimed()
        for proof in ({},{'generation_gone':False},{'generation_gone':1},{'seed_absent':True}):
            with self.subTest(proof=proof),self.assertRaisesRegex(JournalError,'retirement_unconfirmed'):
                self.journal.retire(record['id'],**proof)
        other=OwnershipJournal(self.folder,self.data)
        with self.assertRaisesRegex(JournalError,'not_owner'):
            other.retire(record['id'],generation_gone=True)
        self.journal.retire(record['id'],generation_gone=True)
        self.assertEqual(self.journal.records(),[])

    def test_unclaimed_seed_requires_explicit_absence_not_missing_generation(self):
        record=self.journal.begin_seed()
        with self.assertRaisesRegex(JournalError,'retirement_unconfirmed'):
            self.journal.retire(record['id'],generation_gone=True)
        self.journal.retire(record['id'],seed_absent=True)
        self.assertEqual(self.journal.records(),[])


if __name__=='__main__':unittest.main()
