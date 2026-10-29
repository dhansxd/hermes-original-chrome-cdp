"""Provider recovery retains findings without replaying uncertain browser actions."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from plugin import ChromeProvider
from public_result import model_result


class Observer:
    def __init__(self):self.closed=False;self.close_count=0
    def close(self):self.closed=True;self.close_count+=1


class ProviderRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.provider=ChromeProvider(data=self.temporary.name,workspace=self.temporary.name+'/work')
        self.key=('researcher','research')
        self.entry=self.owned('current')
        self.provider.states[self.key]=self.entry
        self.provider.endpoint=Mock(side_effect=self.endpoint)
        self.provider._prepare_observer=Mock(side_effect=self.prepare)

    @staticmethod
    def owned(target):
        return {'endpoint':'ws://synthetic-unused','observer':Observer(),
                'state':{'context':'ctx','current':target,'owned':{target:7},'verified':True}}

    def endpoint(self,*,entry):
        entry['state']=self.owned('fresh')['state']
        return 'ws://synthetic-unused'

    @staticmethod
    def prepare(entry,**kwargs):
        entry.setdefault('observer',Observer())
        return entry['observer']

    def execute(self,source,**kwargs):
        return json.loads(self.provider.execute({'session':self.key[1],'code':source,
                                                'timeout_s':30,**kwargs},task_id=self.key[0]))

    def test_timeout_keeps_output_cleans_once_leaves_peer_and_continues_lazily(self):
        peer=self.owned('peer');peer_state=copy.deepcopy(peer['state'])
        self.provider.states[('other-agent','research')]=peer
        calls=[];observer=self.entry['observer']
        source="click_element('#submit')\nprint(read_page())"
        def worker(request,timeout,*,entry):
            calls.append((request.get('code'),bool(request.get('cleanup')),entry))
            if request.get('cleanup'):
                entry['state']['owned']={}
                return {'success':True}
            if request['code']==source:
                entry['partial_stdout']='Completed earlier research finding\n'
                raise subprocess.TimeoutExpired('synthetic-worker',timeout)
            return {'success':True,'stdout':'continued research\n'}
        self.provider._worker=worker
        result=self.execute(source)
        self.assertFalse(result['success']);self.assertTrue(result['uncertain'])
        self.assertEqual(result['stdout'],'Completed earlier research finding\n')
        self.assertEqual(result['recovery']['status'],'fresh_session_ready')
        self.assertTrue(result['recovery']['cleanup_complete'])
        self.assertFalse(result['action_replayed'])
        self.assertEqual(sum(cleanup for _,cleanup,_ in calls),1)
        self.assertEqual(sum(code==source for code,_,_ in calls),1)
        self.assertNotIn(self.key,self.provider.states)
        self.provider.endpoint.assert_not_called()
        self.assertEqual(observer.close_count,1)
        self.assertEqual(peer['state'],peer_state);self.assertFalse(peer['observer'].closed)
        continued=self.execute('print(read_page())')
        self.assertTrue(continued['success'])
        self.provider.endpoint.assert_called_once()
        self.assertEqual(self.provider.states[self.key]['state']['current'],'fresh')
        self.assertIsNot(self.provider.states[self.key],self.entry)
        self.assertIs(self.provider.states[('other-agent','research')],peer)
        self.assertEqual(sum(code==source for code,_,_ in calls),1)

    def test_read_retry_is_once_on_the_same_verified_entry_and_held_observer(self):
        calls=[];observer=self.entry['observer']
        def worker(request,timeout,*,entry):
            self.assertIs(entry,self.entry);self.assertIs(entry['observer'],observer)
            self.assertFalse(request.get('cleanup'));calls.append(timeout)
            if len(calls)==1:
                return {'success':False,'error':'CDP_response_timeout: Runtime.evaluate',
                        'uncertain':True,'stdout':'first completed finding\n'}
            return {'success':True,'stdout':'recovered page\n'}
        self.provider._worker=worker
        result=self.execute('print(read_page())')
        self.assertTrue(result['success']);self.assertEqual(len(calls),2)
        self.assertLessEqual(calls[1],10)
        self.assertEqual(result['recovery']['status'],'read_retry_succeeded')
        self.assertEqual(result['recovery']['read_retry_count'],1)
        self.assertIn('first completed finding',result['stdout'])
        self.assertIn('recovered page',result['stdout'])
        self.assertFalse(model_result(result)['action_replayed']);self.assertFalse(observer.closed)
        self.provider.endpoint.assert_not_called();self.provider._prepare_observer.assert_not_called()

    def test_failed_read_retry_is_bounded_and_only_then_cleans_once(self):
        reads=[];cleanup=[]
        def worker(request,timeout,*,entry):
            if request.get('cleanup'):
                cleanup.append(entry);entry['state']['owned']={}
                return {'success':True}
            reads.append(timeout)
            return {'success':False,'error':'CDP_response_timeout: Runtime.evaluate',
                    'uncertain':True,'stdout':'partial '+str(len(reads))}
        self.provider._worker=worker
        result=self.execute('print(read_page())')
        self.assertEqual(len(reads),2);self.assertEqual(cleanup,[self.entry])
        self.assertFalse(result['success']);self.assertTrue(result['uncertain'])
        self.assertEqual(result['recovery']['status'],'fresh_session_ready')
        self.assertEqual(result['recovery']['read_retry_count'],1)
        self.assertIn('partial 1',result['stdout']);self.assertIn('partial 2',result['stdout'])
        self.provider.endpoint.assert_not_called()

    def test_deterministic_long_wait_and_navigation_batches_never_retry(self):
        for source in ("wait(30)\nprint(read_page())", "goto_url('https://example.test')\nprint(read_page())"):
            with self.subTest(source=source):
                self.provider.states[self.key]=self.owned('current');calls=[]
                def worker(request,timeout,*,entry):
                    calls.append(bool(request.get('cleanup')))
                    if request.get('cleanup'):return {'success':True}
                    return {'success':False,'error':'browser_exec_timeout','uncertain':True}
                self.provider._worker=worker
                result=self.execute(source)
                self.assertEqual(calls,[False,True]);self.assertEqual(result['recovery']['read_retry_count'],0)

    def test_unknown_observer_loss_and_incomplete_cleanup_never_claim_ready(self):
        calls=[]
        def worker(request,timeout,*,entry):
            calls.append(bool(request.get('cleanup')))
            if request.get('cleanup'):return {'success':False,'error':'target_close_unconfirmed'}
            entry['observer'].closed=True
            return {'success':False,'error':'observer_lost: synthetic','uncertain':True,'stdout':'findings'}
        self.provider._worker=worker
        result=self.execute('print(read_page())')
        self.assertEqual(calls,[False,True]);self.assertFalse(result['success'])
        self.assertEqual(result['recovery']['status'],'fresh_session_required')
        self.assertFalse(result['recovery']['cleanup_complete'])
        self.assertIs(self.provider.states[self.key],self.entry)
        self.assertTrue(self.entry['uncertain'])
        self.provider.endpoint.assert_not_called()

    def test_no_read_retry_when_the_whole_request_budget_is_already_spent(self):
        calls=[]
        def worker(request,timeout,*,entry):
            calls.append(bool(request.get('cleanup')))
            return ({'success':True} if request.get('cleanup') else
                    {'success':False,'error':'browser_exec_timeout','uncertain':True})
        self.provider._worker=worker
        with patch('plugin.time.monotonic',side_effect=[0,30]):
            result=self.execute('print(read_page())')
        self.assertEqual(calls,[False,True]);self.assertEqual(result['recovery']['read_retry_count'],0)

    def test_parent_retains_real_pipe_progress_when_its_worker_times_out(self):
        root=Path(self.temporary.name)
        (root/'worker.py').write_text('import json,sys,time\n'
            'json.loads(sys.stdin.readline())\n'
            'print(json.dumps({"progress":{"stdout":"Completed research before timeout\\n"}}),flush=True)\n'
            'time.sleep(30)\n')
        with self.assertRaises(subprocess.TimeoutExpired):
            self.provider._run_worker({'endpoint':self.entry['endpoint']},.3,entry=self.entry,worker_path=root/'worker.py')
        self.assertEqual(self.entry['partial_stdout'],'Completed research before timeout\n')
        self.assertFalse(self.entry['observer'].closed)


if __name__=='__main__':unittest.main()
