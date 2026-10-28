"""History retention must not poison current metadata or another held session."""
import io, json, sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from worker import Wire, PipeWire, helper_namespace
from binding import BoundBrowser
from observer import ScopedObserver


class Socket:
    def __init__(self):self.frames=[];self.closed=False;self.sent=[]
    def send(self,text):
        m=json.loads(text);self.sent.append(m);method=m['method'];p=m['params']
        result={}
        if method=='Target.getTargets':result={'targetInfos':[{'targetId':t,'browserContextId':'ctx'} for t in ('a','b')]}
        elif method=='Browser.getWindowForTarget':result={'windowId':1}
        elif method=='Target.attachToTarget':result={'sessionId':p['targetId']+'-sid'}
        elif method=='Runtime.evaluate':
            expr=p['expression']
            value='complete' if expr=='document.readyState' else json.dumps({'title':'fixture'}) if 'JSON.stringify' in expr else 'fixture'
            result={'result':{'type':'string','value':value}}
        self.frames.append({'id':m['id'],'result':result})
    def recv(self,timeout):
        if not self.frames:raise TimeoutError()
        return json.dumps(self.frames.pop(0))
    def close(self):self.closed=True


def fixture():
    wire=Wire.__new__(Wire);wire.ws=Socket();wire.counter=0
    wire.event({})
    with patch('observer.Wire',return_value=wire):observer=ScopedObserver('fixture','/fixture/Default')
    observer.auto_attached=True
    observer.native.scan=lambda state,wire: {}
    states={t:{'current':t,'context':'ctx','owned':{t:1},'verified':True} for t in ('a','b')}
    observer.entries=[{'state':s} for s in states.values()]
    for t,s in states.items():observer.request({'method':'Target.attachToTarget','params':{'targetId':t}},s)
    return observer,states


def pipe(observer,state):
    protocol=io.StringIO()
    class Source:
        def readline(self):
            request=json.loads(protocol.getvalue().splitlines()[-1])['cdp']
            return json.dumps(observer.request(request,state))+'\n'
    return PipeWire(protocol,Source())


def burst(wire,sid='a-sid',count=4100):
    for i in range(count):wire.event({'method':'Network.dataReceived','sessionId':sid,'params':{'requestId':str(i)}})


class OverflowTests(unittest.TestCase):
    def test_helpers_and_other_session_survive_history_gap(self):
        observer,states=fixture()
        burst(observer.wire)
        self.assertTrue(observer.wire.event_overflow)
        self.assertEqual(len(observer.wire.events),4000)
        a=BoundBrowser(pipe(observer,states['a']),states['a']);ns=helper_namespace(a)
        self.assertEqual(ns['js']('document.title'),'fixture')
        self.assertTrue(ns['wait_for_load']())
        self.assertEqual(ns['page_info']()['title'],'fixture')
        with self.assertRaisesRegex(RuntimeError,'event_buffer_overflow'):ns['drain_events']()
        # A new worker on the same epoch must not silently erase the gap.
        again=helper_namespace(BoundBrowser(pipe(observer,states['a']),states['a']))
        with self.assertRaisesRegex(RuntimeError,'event_buffer_overflow'):again['wait_for_network_idle'](timeout=.1,idle_ms=0)
        b=helper_namespace(BoundBrowser(pipe(observer,states['b']),states['b']))
        self.assertEqual(b['page_info']()['title'],'fixture')
        self.assertTrue(b['wait_for_network_idle'](timeout=.1,idle_ms=0))

    def test_eviction_is_attributed_to_lost_session_not_incoming_session(self):
        observer,states=fixture()
        burst(observer.wire,'b-sid',count=1);burst(observer.wire,'a-sid',count=4000)
        self.assertEqual(observer.wire.event_gaps,{'a-sid':False,'b-sid':True})
        b=helper_namespace(BoundBrowser(pipe(observer,states['b']),states['b']))
        with self.assertRaisesRegex(RuntimeError,'event_buffer_overflow'):b['drain_events']()
        a=helper_namespace(BoundBrowser(pipe(observer,states['a']),states['a']))
        self.assertEqual(len(a['drain_events']()),4000)

    def test_other_caller_cannot_consume_history_or_mark_foreign_gap(self):
        observer,states=fixture();burst(observer.wire,count=3)
        b=observer.request({'method':'__pump__','event_gaps':['a-sid','unknown']},states['b'])
        self.assertEqual(b['events'],[])
        self.assertEqual(observer.wire.event_gaps,{'a-sid':False,'b-sid':False})
        a=observer.request({'method':'__pump__'},states['a'])
        self.assertEqual(len(a['events']),3)

    def test_dialog_snapshot_survives_open_and_close_event_eviction(self):
        observer,states=fixture()
        observer.wire.event({'method':'Page.javascriptDialogOpening','sessionId':'a-sid','params':{'type':'alert','message':'exact'}})
        burst(observer.wire)
        a=helper_namespace(BoundBrowser(pipe(observer,states['a']),states['a']))
        self.assertEqual(a['page_info'](),{'dialog':{'type':'alert','message':'exact'}})
        observer.wire.event({'method':'Page.javascriptDialogClosed','sessionId':'a-sid'})
        burst(observer.wire)
        self.assertEqual(a['page_info']()['title'],'fixture')
        with self.assertRaisesRegex(RuntimeError,'event_buffer_overflow'):a['drain_events']()

    def test_gap_state_is_bounded_by_held_sessions_and_fresh_attachment(self):
        observer,states=fixture();burst(observer.wire)
        for i in range(4100):
            observer.wire.event({'method':'Network.dataReceived','sessionId':'unknown-'+str(i)})
        self.assertEqual(len(observer.wire.events),4000)
        self.assertEqual(set(observer.wire.event_gaps),{'a-sid','b-sid'})
        # Explicit successful retirement, not silent reset of the damaged epoch.
        original=observer.wire.ws.send
        def send(text):
            original(text)
            if json.loads(text)['method']=='Target.closeTarget':observer.wire.ws.frames[-1]['result']={'success':True}
        observer.wire.ws.send=send
        observer.request({'method':'Target.closeTarget','params':{'targetId':'a'}},states['a'])
        self.assertNotIn('a-sid',observer.wire.event_gaps)
        observer.wire.event({'method':'Target.detachedFromTarget','params':{'sessionId':'a-sid'}})
        self.assertNotIn('a-sid',observer.wire.detached_sessions)
        # Distinct SID is the fresh observation epoch; historical loss stays retired.
        def new_send(text):
            original(text)
            if json.loads(text)['method']=='Target.attachToTarget':observer.wire.ws.frames[-1]['result']={'sessionId':'a-fresh'}
        observer.wire.ws.send=new_send
        response=observer.request({'method':'Target.attachToTarget','params':{'targetId':'a'}},states['a'])
        self.assertEqual(response['event_gaps']['a-fresh'],False)
        self.assertTrue(observer.wire.event_overflow) # Never silently clear diagnostic.

    def test_worker_only_eviction_survives_final_response_and_next_worker(self):
        observer,states=fixture();w=pipe(observer,states['a'])
        burst(observer.wire,count=2500);w('__pump__')
        burst(observer.wire,count=2500);w('__pump__')
        self.assertFalse(observer.wire.event_overflow)
        self.assertTrue(w.event_overflow)
        self.assertEqual(len(w.events),4000)
        w.close() # No subsequent user command to carry the final local gap.
        ns=helper_namespace(BoundBrowser(pipe(observer,states['a']),states['a']))
        with self.assertRaisesRegex(RuntimeError,'event_buffer_overflow'):ns['drain_events']()
        self.assertEqual(ns['page_info']()['title'],'fixture')

    def test_vault_borrow_keeps_gap_history_exact_session_and_callback(self):
        observer,states=fixture();burst(observer.wire)
        before=list(observer.wire.events);callback=getattr(observer.wire,'on_event',None)
        with observer.borrow(states['a']) as browser:
            self.assertEqual(browser.sessions,{'a':'a-sid'})
            self.assertIsNone(browser.send({'meta':'pending_dialog'})['dialog'])
        self.assertEqual(observer.wire.events,before)
        self.assertTrue(observer.wire.event_gaps['a-sid'])
        self.assertIs(getattr(observer.wire,'on_event',None),callback)

    def test_vault_validation_cannot_miss_detach_evicted_during_info(self):
        observer,states=fixture();original=observer.wire.ws.send
        def send(text):
            original(text)
            if json.loads(text)['method']=='Target.getTargets':
                observer.wire.ws.frames[:0]=[{'method':'Target.detachedFromTarget','params':{'sessionId':'a-sid'}}]+[{'method':'Network.dataReceived','sessionId':'b-sid'} for _ in range(4100)]
        observer.wire.ws.send=send
        with self.assertRaisesRegex(RuntimeError,'observer_lost'):
            with observer.borrow(states['a']):self.fail('borrowed detached session')

    def test_evicted_owned_detach_is_still_loss_before_query_or_vault(self):
        for vault in (False,True):
            observer,states=fixture()
            observer.wire.event({'method':'Target.detachedFromTarget','params':{'sessionId':'a-sid'}})
            burst(observer.wire,'b-sid')
            self.assertFalse(any(e['method']=='Target.detachedFromTarget' for e in observer.wire.events))
            sent=len(observer.wire.ws.sent)
            with self.assertRaisesRegex(RuntimeError,'observer_lost'):
                if vault:
                    with observer.borrow(states['a']):self.fail('borrowed detached session')
                else:observer.request({'method':'Runtime.evaluate','session':'b-sid','params':{'expression':'counter++'}},states['b'])
            self.assertEqual(len(observer.wire.ws.sent),sent)
            self.assertTrue(observer.closed)

if __name__=='__main__':unittest.main()
