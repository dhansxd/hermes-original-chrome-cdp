"""Session fault isolation through real bounded worker pipes; no personal Chrome."""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from plugin import ChromeProvider


class SessionIsolationTests(unittest.TestCase):
    def test_timeout_during_parent_cdp_response_preserves_peer_connection(self):
        class Wire:
            def __init__(self,*args):
                self.closed=False;self.events=[];self.dialogs={};self.event_gaps={}
                self.event_overflow=False;self.detached_sessions=set()
                self.release=threading.Event()
            def __call__(self,method,params=None,session=None):
                if method=='Fixture.block':
                    self.release.wait(2)
                    if self.closed:raise OSError('transport closed while awaiting response')
                return {'marker':'peer'}
            def pump(self):pass
            def close(self):self.closed=True;self.release.set()

        with tempfile.TemporaryDirectory() as root:
            script=Path(root)/'worker.py'
            script.write_text('import json,sys\nr=json.loads(sys.stdin.readline())\n'
                'print(json.dumps({"cdp":{"method":r["method"]}}),flush=True)\n'
                'response=json.loads(sys.stdin.readline())\n'
                'print(json.dumps({"result":{"success":"error" not in response,"response":response}}),flush=True)\n')
            provider=ChromeProvider(data=root)
            first:dict={'state':{'owned':{'a':1}}};peer:dict={'state':{'owned':{'b':2}}}
            provider.states={('a','default'):first,('b','default'):peer}
            def request(entry,method,timeout):
                return provider._worker({'endpoint':'ws://fixture','profile':root+'/Default','method':method},timeout,entry=entry)
            with patch('plugin.ROOT',Path(root)),patch('observer.Wire',Wire):
                try:
                    self.assertTrue(request(peer,'Fixture.read',2)['success'])
                    with self.assertRaises(subprocess.TimeoutExpired):request(first,'Fixture.block',.2)
                    self.assertFalse(peer['observer'].closed,'one worker timeout closed its peer observer')
                    self.assertTrue(request(peer,'Fixture.read',2)['success'])
                    self.assertIsNot(first['observer'],peer['observer'])
                finally:
                    for entry in (first,peer):
                        if entry.get('observer'):entry['observer'].close()


class ParallelExecutionTests(unittest.TestCase):
    def test_peer_progresses_while_first_worker_is_waiting(self):
        provider=ChromeProvider(data='/fixture');provider.endpoint=lambda *a,**k:'ws://inert'
        entered=threading.Event();release=threading.Event();peer_done=threading.Event()
        results={}
        def worker(request,timeout:float=300,**kwargs):
            if request.get('cleanup'):return {'success':True}
            if request['code']=='wait':entered.set();release.wait(3)
            return {'success':True,'stdout':request['code'],'state':{'owned':{'target-'+request['code']:1},'verified':True}}
        provider._worker=worker
        def dispatch(name,code):
            results[name]=json.loads(provider.execute({'code':code},task_id=name))
            if name=='b':peer_done.set()
        first=threading.Thread(target=dispatch,args=('a','wait'))
        peer=threading.Thread(target=dispatch,args=('b','read'))
        first.start()
        try:
            self.assertTrue(entered.wait(2));peer.start()
            self.assertTrue(peer_done.wait(.5),'peer serialized behind an unrelated worker')
            self.assertTrue(first.is_alive(),'first request ended before peer progress assertion')
            self.assertEqual(results['b']['stdout'],'read')
        finally:
            release.set();first.join(3)
            if peer.ident:peer.join(3)
            provider.unload()

    def test_same_session_waiters_remain_serial(self):
        provider=ChromeProvider(data='/fixture');provider.endpoint=lambda **kw:'ws://inert'
        entered=threading.Event();release=threading.Event();second_entered=threading.Event()
        calls=[]
        def worker(request,timeout:float=300,**kwargs):
            calls.append(request['code'])
            if request['code']=='finish':entered.set();release.wait(2)
            else:second_entered.set()
            return {'success':True,'state':{'owned':{'owned':1},'verified':True}}
        provider._worker=worker
        first=threading.Thread(target=lambda:provider.execute({'code':'finish'},task_id='same'))
        second=threading.Thread(target=lambda:provider.execute({'code':'read'},task_id='same'))
        first.start()
        try:
            self.assertTrue(entered.wait(2));second.start()
            self.assertFalse(second_entered.wait(.1))
        finally:release.set();first.join(3);second.join(3)
        self.assertEqual(calls,['finish','read'])
        self.assertFalse(provider._session_locks)

    def test_cancel_waits_only_for_owned_task_and_peer_keeps_progressing(self):
        from plugin import BrowserLifecycle
        from types import SimpleNamespace
        provider=ChromeProvider(data='/fixture');provider.endpoint=lambda **kw:'ws://inert'
        lifecycle=BrowserLifecycle(SimpleNamespace(emit=lambda *a:None),provider)
        lifecycle.bind(task_id='a',session_id='chat-a',session_key='route-a')
        entered=threading.Event();release=threading.Event();cancel_started=threading.Event();peer_done=threading.Event()
        calls=[]
        def worker(request,timeout:float=300,**kwargs):
            calls.append(request)
            if request.get('cleanup'):return {'success':True}
            if request['code']=='wait':entered.set();release.wait(3)
            return {'success':True,'state':{'owned':{'owned-'+request['code']:1},'verified':True}}
        provider._worker=worker
        first=threading.Thread(target=lambda:provider.execute({'code':'wait'},task_id='a'))
        def cancel():cancel_started.set();lifecycle.cancel(session_key='route-a')
        cancelling=threading.Thread(target=cancel)
        def peer():provider.execute({'code':'read'},task_id='b');peer_done.set()
        other=threading.Thread(target=peer)
        first.start()
        try:
            self.assertTrue(entered.wait(2));cancelling.start();self.assertTrue(cancel_started.wait(1));other.start()
            self.assertTrue(peer_done.wait(.5),'cancel held shared state lock while waiting for another task')
            self.assertTrue(cancelling.is_alive())
        finally:
            release.set();first.join(3)
            if cancelling.ident:cancelling.join(3)
            if other.ident:other.join(3)
        self.assertFalse(first.is_alive());self.assertFalse(cancelling.is_alive())
        self.assertNotIn(('a','default'),provider.states);self.assertIn(('b','default'),provider.states)
        self.assertEqual(len([r for r in calls if r.get('cleanup')]),1)
        self.assertFalse(provider._closing_tasks)

    def test_cancel_fences_calls_already_queued_before_cleanup(self):
        import time
        provider=ChromeProvider(data='/fixture');provider.endpoint=lambda **kw:'ws://inert'
        key=('task','default')
        provider.states[key]={'endpoint':'ws://inert','state':{'owned':{'old':1},'verified':True}}
        calls=[];result=[]
        def worker(request,timeout:float=300,**kwargs):
            calls.append(request)
            return {'success':True,'state':{'owned':{'new':1},'verified':True}}
        provider._worker=worker
        queued=threading.Thread(target=lambda:result.append(json.loads(provider.execute({'code':'must-not-run'},task_id='task'))))
        with provider.session_guard(key):
            queued.start()
            deadline=time.monotonic()+2
            while provider._session_locks[key][1]<2 and time.monotonic()<deadline:time.sleep(.001)
            self.assertEqual(provider._session_locks[key][1],2,'caller did not reach the same-session lock')
            self.assertTrue(provider.close_session('task'))
        queued.join(3)
        self.assertFalse(queued.is_alive())
        self.assertTrue(all(r.get('cleanup') for r in calls),'a pre-cancel queued action ran after cleanup')
        self.assertFalse(result[0]['success'])
        self.assertNotIn(key,provider.states)

    def test_parent_checkpoints_stay_on_explicit_entry_during_parallel_workers(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'worker.py').write_text('import json,sys,time\nr=json.loads(sys.stdin.readline())\n'
                'print(json.dumps({"checkpoint":{"owned":{r["marker"]:1},"verified":True}}),flush=True)\n'
                'time.sleep(.1)\nprint(json.dumps({"result":{"success":True,"stdout":r["marker"]}}),flush=True)\n')
            provider=ChromeProvider(data=root);entries=[{},{}];results=[]
            barrier=threading.Barrier(2)
            def run(i):
                barrier.wait(2)
                results.append(provider._worker({'marker':str(i)},2,entry=entries[i]))
            workers=[threading.Thread(target=run,args=(i,)) for i in range(2)]
            with patch('plugin.ROOT',Path(root)):
                for worker in workers:worker.start()
                for worker in workers:worker.join(3)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual([e['state']['owned'] for e in entries],[{'0':1},{'1':1}])
            self.assertEqual({r['stdout'] for r in results},{'0','1'})


class VaultConcurrencyTests(unittest.TestCase):
    def test_vault_borrows_only_selected_session_without_blocking_peer_task(self):
        import test_vault_adapter
        import vault_adapter
        fixture=test_vault_adapter.NativeSyntheticTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        provider=ChromeProvider(data='/synthetic-empty-root')
        provider.states=fixture.provider.states;provider.last_sessions=fixture.provider.last_sessions
        provider.endpoint=lambda **kw:'ws://inert'
        provider._worker=lambda *a,**kw:{'success':True,'state':{'owned':{'peer':1},'verified':True}}
        fixture.provider=provider
        entered=threading.Event();release=threading.Event();peer_done=threading.Event();results=[]
        original=vault_adapter._Transport
        class SlowTransport(original):
            def __init__(self,browser):
                entered.set();release.wait(2);super().__init__(browser)
        def fill():results.append(fixture.call())
        def read():provider.execute({'code':'read'},task_id='peer');peer_done.set()
        filling=threading.Thread(target=fill);peer=threading.Thread(target=read)
        with patch('vault_adapter._Transport',SlowTransport):
            filling.start()
            try:
                self.assertTrue(entered.wait(2));peer.start()
                self.assertTrue(peer_done.wait(.5),'vault borrow held the provider-wide state lock')
                self.assertTrue(filling.is_alive())
            finally:
                release.set();filling.join(3)
                if peer.ident:peer.join(3)
        self.assertTrue(results[0]['success'],results)
        self.assertFalse(provider._session_locks)


if __name__=='__main__':unittest.main()
