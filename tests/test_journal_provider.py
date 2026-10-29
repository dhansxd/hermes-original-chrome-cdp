"""Provider provenance integration with inert launch/process/browser fixtures."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plugin import ChromeProvider
from worker import run


class JournalProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)/'chrome';self.workspace=Path(self.temp.name)/'work'
        self.provider=ChromeProvider(data=self.data,workspace=self.workspace)
        self.journal=self.provider._journal()
        self.generation={'pid':424242,'started':100.5,'endpoint':'ws://127.0.0.1:5000/devtools/browser/fixture'}

    def entry(self,target='owned',*,pending=False):
        record=self.journal.begin_seed()
        state={'pending_seed':record['seed_url'],'owned':{},'verified':False}
        entry={'journal_id':record['id'],'state':state,'endpoint':None}
        if not pending:
            self.journal.bind_generation(record['id'],self.generation)
            state={'owned':{target:7},'context':'ctx','current':target,'verified':True}
            self.journal.checkpoint(record['id'],state)
            entry.update(state=state,endpoint=self.generation['endpoint'],generation=dict(self.generation))
        entry['_checkpoint']=lambda value:self.provider._checkpoint(entry,value)
        return entry

    def test_journal_marker_exists_before_launch_and_generation_binding_precedes_return(self):
        entry={}
        def launch(data,seed):
            records=self.journal.records()
            self.assertEqual(len(records),1)
            self.assertEqual(records[0]['seed_url'],seed)
            self.assertEqual(entry['state']['pending_seed'],seed)
            self.assertIsNone(records[0]['generation'])
        with patch('plugin.gui_launch',side_effect=launch) as launched,\
             patch.object(self.provider,'_endpoint_identity',return_value=self.generation),\
             patch('plugin.seed_window_ready',return_value=True):
            endpoint=self.provider.endpoint(entry=entry)
        self.assertEqual(endpoint,self.generation['endpoint']);launched.assert_called_once()
        self.assertEqual(self.journal.records()[0]['generation']['pid'],424242)
        self.assertTrue(callable(entry['_checkpoint']))

    def test_timed_out_launch_without_process_snapshot_retains_unbound_seed(self):
        entry={}
        with patch('plugin.gui_launch',side_effect=subprocess.TimeoutExpired('fixture-open',15)):
            with self.assertRaises(subprocess.TimeoutExpired):self.provider.endpoint(entry=entry)
        before=copy.deepcopy(entry['state']);record_id=entry['journal_id']
        with patch.object(self.provider,'_chrome_processes',return_value=[]),\
             patch.object(self.provider,'_worker') as worker,\
             patch.object(self.provider,'_endpoint_identity') as endpoint:
            result=self.provider._cleanup_entry(entry)
        self.assertFalse(result['success']);self.assertEqual(entry['state'],before)
        self.assertEqual(entry['journal_id'],record_id)
        self.assertEqual(self.journal.records()[0]['phase'],'seed')
        worker.assert_not_called();endpoint.assert_not_called()

    def test_legacy_worker_absent_marker_result_cannot_clear_pending_seed(self):
        entry=self.entry(pending=True);before=copy.deepcopy(entry['state'])
        with patch.object(self.provider,'_chrome_processes',return_value=[object()]),\
             patch.object(self.provider,'_endpoint_identity',return_value=self.generation),\
             patch.object(self.provider,'_worker',return_value={'success':True,'seed_absent':True,
                                                              'state':{'owned':{},'verified':False}}):
            result=self.provider._cleanup_entry(entry)
        self.assertFalse(result['success']);self.assertEqual(entry['state'],before)
        self.assertIn('journal_id',entry);self.assertEqual(self.journal.records()[0]['phase'],'seed')

    def test_ended_chrome_generation_retires_without_endpoint_or_browser_commands(self):
        import psutil
        entry=self.entry()
        with patch('psutil.Process',side_effect=psutil.NoSuchProcess(424242)),\
             patch.object(self.provider,'_worker') as worker,\
             patch.object(self.provider,'_endpoint_identity') as endpoint:
            result=self.provider._cleanup_entry(entry)
        self.assertTrue(result['success']);self.assertTrue(result['browser_generation_ended'])
        self.assertNotIn('journal_id',entry);self.assertEqual(self.journal.records(),[])
        worker.assert_not_called();endpoint.assert_not_called()

    def test_failed_durable_retire_preserves_entry_record_id_and_state(self):
        import psutil
        entry=self.entry();before=copy.deepcopy(entry['state']);record_id=entry['journal_id']
        with patch('psutil.Process',side_effect=psutil.NoSuchProcess(424242)),\
             patch.object(self.journal,'retire',side_effect=OSError('fixture durable failure')),\
             patch.object(self.provider,'_worker') as worker:
            with self.assertRaises(OSError):self.provider._cleanup_entry(entry)
        self.assertEqual(entry['journal_id'],record_id);self.assertEqual(entry['state'],before)
        self.assertEqual(len(self.journal.records()),1);worker.assert_not_called()

    def test_current_browser_endpoint_mismatch_never_receives_old_target_ids(self):
        entry=self.entry();process=Mock();process.create_time.return_value=100.5
        changed=dict(self.generation,endpoint='ws://127.0.0.1:5001/devtools/browser/new')
        with patch('psutil.Process',return_value=process),\
             patch.object(self.provider,'_endpoint_identity',return_value=changed),\
             patch.object(self.provider,'_worker') as worker:
            result=self.provider._cleanup_entry(entry)
        self.assertFalse(result['success']);worker.assert_not_called()
        self.assertEqual(entry['endpoint'],self.generation['endpoint'])
        self.assertEqual(self.journal.records()[0]['state']['owned'],{'owned':7})

    def test_same_pid_orphan_handoff_cleans_only_released_record_preserving_active_sibling(self):
        orphan=self.entry('orphan');sibling=self.entry('sibling')
        sibling_before=next(r for r in self.journal.records() if r['id']==sibling['journal_id'])
        reloaded=ChromeProvider(data=self.data,workspace=self.workspace)
        reloaded._journal() # Capture actual owner identity before any process fixtures.
        unrelated={'state':{'owned':{'current-task':9}}}
        reloaded.states[('current-task','default')]=unrelated
        cleaned=[]
        def cleanup(entry):
            cleaned.append(entry['state']['current'])
            reloaded._checkpoint(entry,{'owned':{},'verified':True})
            reloaded._complete_record(entry)
            return {'success':True}
        with patch.object(reloaded,'_cleanup_entry',side_effect=cleanup):
            reloaded._recover_orphans()
            self.assertEqual(cleaned,[],'same PID reload must not steal an active lease')
            self.journal.release(orphan['journal_id'])
            reloaded._recover_orphans()
        self.assertEqual(cleaned,['orphan'])
        self.assertEqual(self.journal.records(),[sibling_before])
        self.assertIs(reloaded.states[('current-task','default')],unrelated)
        self.assertEqual(len(reloaded.states),1)

    def test_failed_orphan_cleanup_keeps_lease_and_state_for_later_explicit_cleanup(self):
        entry=self.entry();record_id=entry['journal_id'];self.journal.release(record_id)
        reloaded=ChromeProvider(data=self.data,workspace=self.workspace)
        with patch.object(reloaded,'_cleanup_entry',return_value={'success':False,'error':'fixture pending'}) as cleanup:
            reloaded._recover_orphans();reloaded._recover_orphans()
        cleanup.assert_called_once()
        key=('recovered-'+record_id,'default')
        self.assertEqual(reloaded.states[key]['journal_id'],record_id)
        self.assertEqual(reloaded.states[key]['state']['owned'],{'owned':7})
        self.assertEqual(self.journal.records()[0]['owner']['instance'],reloaded._journal().instance_id)

    def test_successful_cleanup_retires_only_matching_session(self):
        entry=self.entry();sibling=self.entry('sibling')
        self.provider.states={('task','default'):entry,('other','default'):sibling}
        process=Mock();process.create_time.return_value=100.5
        def cleanup(request,*args,**kwargs):
            self.assertEqual(request['state']['owned'],{'owned':7})
            self.assertTrue(request['cleanup'])
            return {'success':True,'state':{'owned':{},'verified':True}}
        with patch('psutil.Process',return_value=process),\
             patch.object(self.provider,'_endpoint_identity',return_value=self.generation),\
             patch.object(self.provider,'_worker',side_effect=cleanup):
            self.assertTrue(self.provider.close_session('task',session='default'))
        self.assertEqual(list(self.provider.states),[('other','default')])
        self.assertEqual(self.journal.records()[0]['state']['owned'],{'sibling':7})


class SeedCleanupTests(unittest.TestCase):
    def request(self):
        return {'endpoint':'fixture','profile':'/fixture/Default','workspace':'/fixture',
                'cleanup':True,'state':{'pending_seed':'file:///owned-marker.html','owned':{},'verified':False}}

    def test_missing_or_navigated_marker_is_not_reported_clean_and_foreign_page_is_untouched(self):
        wire=Mock();wire.return_value={'targetInfos':[{'targetId':'user','type':'page','url':'https://example.test',
                                                     'browserContextId':'ctx'}]}
        request=self.request()
        with patch('worker.time.monotonic',side_effect=[0,6]):result=run(request,transport=wire)
        self.assertFalse(result['success']);self.assertNotIn('seed_absent',result)
        self.assertEqual(result['state'],request['state'])
        self.assertEqual([call.args[0] for call in wire.call_args_list],['Target.getTargets'])

    def test_delayed_exact_marker_is_waited_for_then_only_that_target_is_cleaned(self):
        wire=Mock();scans=0;closed=False
        info={'targetId':'seed','type':'page','url':'file:///owned-marker.html','browserContextId':'ctx'}
        def respond(method,params=None,session=None):
            nonlocal scans,closed
            if method=='Target.getTargets':
                scans+=1;return {'targetInfos':[] if scans==1 or closed else [info]}
            if method=='Browser.getWindowForTarget':return {'windowId':7}
            if method=='Target.closeTarget':
                self.assertEqual(params,{'targetId':'seed'});closed=True;return {'success':True}
            raise AssertionError('unexpected browser command: '+method)
        wire.side_effect=respond
        with patch('worker.time.sleep'):result=run(self.request(),transport=wire)
        self.assertTrue(result['success']);self.assertTrue(closed)
        self.assertEqual(result['state']['owned'],{})
        self.assertEqual(sum(call.args[0]=='Target.closeTarget' for call in wire.call_args_list),1)


if __name__=='__main__':unittest.main()
