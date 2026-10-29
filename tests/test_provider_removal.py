"""Source removal cleans an actual provider through cached inert worker pipes."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plugin
from resource_watch import SourceRemovalWatch
from runtime_snapshot import DEPENDENCIES,SnapshotError


WORKER='''import json,sys,time
from pathlib import Path
request=json.loads(sys.stdin.readline())
state={'context':'fixture-context','current':'owned','owned':{'owned':7},'verified':True}
if request.get('cleanup') or request.get('code')=='finish_browser()':
    state['owned']={}
    state['observer_released']=True
print(json.dumps({'checkpoint':state}),flush=True)
if request.get('code')=='wait(30)':
    print(json.dumps({'progress':{'stdout':'finding before removal\\n'}}),flush=True)
    time.sleep(30)
print(json.dumps({'result':{'success':True,'state':state,'stdout':str(Path(__file__))}}),flush=True)
'''


class InertObserver:
    def __init__(self):self.closed=False;self.close_count=0
    def close(self):self.closed=True;self.close_count+=1


class ProviderRemovalTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.enterContext(patch('resource_watch.SourceRemovalWatch',side_effect=lambda markers,callback:
            SourceRemovalWatch(markers,callback,poll_interval=.01,grace_s=.03)))
        self.enterContext(patch('plugin.seed_window_ready',return_value=True))
        self.launches=[]
        self.enterContext(patch('plugin.gui_launch',side_effect=lambda *args:self.launches.append(args)))

    def provider(self,name):
        import psutil
        source=self.root/name/'source';source.mkdir(parents=True)
        for relative in DEPENDENCIES:
            destination=source/relative;destination.parent.mkdir(exist_ok=True)
            shutil.copyfile(plugin.ROOT/relative,destination)
        (source/'worker.py').write_text(WORKER)
        (source/'plugin.yaml').write_text('name: inert-removal-fixture\n')
        provider=plugin.ChromeProvider(data=self.root/name/'chrome',
            workspace=self.root/name/'work',source_root=source)
        generation={'pid':os.getpid(),'started':psutil.Process(os.getpid()).create_time(),
                    'endpoint':'ws://127.0.0.1:5000/devtools/browser/fixture'}
        self.enterContext(patch.object(provider,'_endpoint_identity',return_value=generation))
        def prepare(entry,cleanup=False):
            if entry.get('observer') is None or cleanup and entry['observer'].closed:
                entry['observer']=InertObserver()
            return entry['observer']
        self.enterContext(patch.object(provider,'_prepare_observer',side_effect=prepare))
        done=threading.Event();unload=provider.unload
        def unload_and_signal():
            try:return unload()
            finally:done.set()
        provider.unload=Mock(side_effect=unload_and_signal)
        calls=[];run_worker=provider._run_worker
        def run(request,timeout,*,entry,worker_path):
            calls.append({'cleanup':bool(request.get('cleanup')),'code':request.get('code'),
                          'worker_path':worker_path,'source_present':source.exists(),
                          'cache_present':worker_path.is_file(),
                          'active_workers':provider._runtime_snapshot.active_workers})
            return run_worker(request,timeout,entry=entry,worker_path=worker_path)
        provider._run_worker=run
        self.addCleanup(provider.unload)
        return provider,source,done,calls

    def execute(self,provider,code='print(1)'):
        return json.loads(provider.execute({'code':code,'session':'research','timeout_s':60},task_id='fixture-agent'))

    def test_removed_source_cleans_once_through_existing_cache_and_leaves_other_provider(self):
        provider,source,done,calls=self.provider('removed')
        other,other_source,other_done,other_calls=self.provider('peer')
        self.assertTrue(self.execute(provider)['success']);self.assertTrue(self.execute(other)['success'])
        watch=provider._resource_watch;peer_watch=other._resource_watch
        cache=provider._runtime_snapshot.worker_path;peer_cache=other._runtime_snapshot.worker_path
        peer_entry=other.states[('fixture-agent','research')]
        shutil.rmtree(source)
        self.assertTrue(done.wait(2),'source removal did not finish scoped cleanup')
        self.assertTrue(watch.stop());self.assertTrue(watch.removal_detected)
        self.assertFalse(watch.callback_failed);provider.unload.assert_called_once()
        self.assertEqual(sum(call['cleanup'] for call in calls),1)
        cleanup=next(call for call in calls if call['cleanup'])
        self.assertEqual(cleanup['worker_path'],cache)
        self.assertFalse(cleanup['source_present']);self.assertTrue(cleanup['cache_present'])
        self.assertEqual(cleanup['active_workers'],1)
        self.assertFalse(provider.states);self.assertEqual(provider._journal().records(),[])
        self.assertFalse(cache.exists())
        with self.assertRaises(SnapshotError):provider._runtime_snapshot.worker_path
        self.assertFalse(other_done.is_set());other.unload.assert_not_called()
        self.assertTrue(other_source.is_dir());self.assertTrue(peer_cache.is_file())
        self.assertFalse(peer_watch.removal_detected);self.assertIs(other.states[('fixture-agent','research')],peer_entry)
        self.assertFalse(peer_entry['observer'].closed)
        self.assertTrue(self.execute(other,'print(2)')['success'])
        self.assertEqual(sum(call['cleanup'] for call in other_calls),0)
        provider.unload()
        self.assertEqual(sum(call['cleanup'] for call in calls),1,'repeat unload replayed cleanup')

    def test_active_worker_is_cancelled_before_snapshot_removal_and_cleanup_uses_cache(self):
        provider,source,done,calls=self.provider('busy')
        self.assertTrue(self.execute(provider)['success'])
        cache=provider._runtime_snapshot.worker_path;close_checks=[]
        close=provider._runtime_snapshot.close
        def checked_close():
            close_checks.append(provider._runtime_snapshot.active_workers)
            self.assertEqual(provider._runtime_snapshot.active_workers,0)
            return close()
        provider._runtime_snapshot.close=checked_close
        results=[];thread=threading.Thread(target=lambda:results.append(self.execute(provider,'wait(30)')))
        thread.start();self.addCleanup(lambda:thread.join(2))
        entry=provider.states[('fixture-agent','research')]
        deadline=time.monotonic()+2
        while entry.get('partial_stdout')!='finding before removal\n' and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertEqual(entry.get('partial_stdout'),'finding before removal\n')
        proc=entry['_worker_proc'];self.assertIsNone(proc.poll())
        shutil.rmtree(source)
        self.assertTrue(done.wait(3),'removal did not cancel the running worker and finish cleanup')
        thread.join(2);self.assertFalse(thread.is_alive())
        self.assertIsNotNone(proc.poll());self.assertFalse(cache.exists())
        self.assertEqual(close_checks,[0])
        self.assertEqual(sum(call['code']=='wait(30)' for call in calls),1)
        self.assertEqual(sum(call['cleanup'] for call in calls),1)
        self.assertTrue(next(call for call in calls if call['cleanup'])['cache_present'])
        self.assertFalse(results[0]['success']);self.assertIn('finding before removal',results[0]['stdout'])
        self.assertFalse(provider.states)

    def test_explicit_finish_stops_watch_when_no_owned_resources_remain(self):
        provider,source,done,calls=self.provider('finished')
        self.assertTrue(self.execute(provider)['success']);watch=provider._resource_watch
        self.assertTrue(watch.is_running)
        self.assertTrue(self.execute(provider,'finish_browser()')['success'])
        self.assertFalse(provider.states);self.assertIsNone(provider._resource_watch)
        self.assertTrue(watch.stopped);self.assertFalse(watch.removal_detected)
        shutil.rmtree(source)
        time.sleep(.06);provider.unload.assert_not_called()

    def test_watch_and_cached_worker_are_ready_before_any_seed_launch(self):
        provider,source,done,calls=self.provider('ordering')
        seen=[]
        def launch(*args):
            seen.append((provider._resource_watch.is_running,provider._runtime_snapshot.worker_path.is_file()))
        with patch('plugin.gui_launch',side_effect=launch):
            self.assertTrue(self.execute(provider)['success'])
        self.assertEqual(seen,[(True,True)])


if __name__=='__main__':unittest.main()
