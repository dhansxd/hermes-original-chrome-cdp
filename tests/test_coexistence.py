"""Dual-client boundaries; loopback-only tests, no personal browser."""
import sys,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import consent
from websockets.sync.client import connect
from websockets.sync.server import serve
from websockets.exceptions import ConnectionClosed


class CoexistenceTests(unittest.TestCase):
    def test_retained_connection_survives_tcp_dial_budget(self):
        release=threading.Event();ws=None
        def peer(socket):
            if release.wait(8):
                try:socket.send('still-live')
                except ConnectionClosed:pass
        server=serve(peer,'127.0.0.1',0,ping_interval=None,close_timeout=.5)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        port=server.socket.getsockname()[1]
        backend=consent.MacConsent('/fixture',port)
        backend.prepare=Mock(return_value=[]);backend.scan=Mock(return_value=[])
        backend.cleanup_abandoned=Mock()
        try:
            ws=consent._connect_with_consent('ws://127.0.0.1:'+str(port)+'/devtools/browser/fixture','/fixture',connect,backend=backend,timeout=8)
            threading.Event().wait(3.3);release.set()
            try:result=ws.recv(timeout=2)
            except ConnectionClosed as exc:result=type(exc).__name__
            self.assertEqual(result,'still-live')
        finally:
            release.set()
            if ws is not None:ws.close()
            server.shutdown();thread.join(2)
        self.assertFalse(thread.is_alive())


class SharedFinishTests(unittest.TestCase):
    def test_personal_browser_finish_does_not_quit_other_clients(self):
        from plugin import ChromeProvider,PERSONAL
        provider=ChromeProvider(data=PERSONAL)
        observer=Mock();entry={'observer':observer,'state':{'owned':{},'verified':True}}
        provider.states={('task','default'):entry}
        with patch.object(provider,'_chrome_processes',return_value=[]),patch('psutil.wait_procs',return_value=([],[])):
            result=provider._finish_browser(entry)
        self.assertEqual(result.get('browser_close_deferred'),'shared_browser')
        self.assertFalse(result['browser_closed'])
        observer.request.assert_not_called()
        observer.close_disposable_browser.assert_not_called()


class ScopedAttachTests(unittest.TestCase):
    def test_observer_watches_only_owned_root_not_browser_wide_pages(self):
        from observer import ScopedObserver
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_overflow=False;wire.event_gaps={};wire.detached_sessions=set()
        def response(method,params=None,session=None):
            if method=='Target.getTargets':return {'targetInfos':[{'targetId':'owned','browserContextId':'ctx','type':'page'}]}
            if method=='Browser.getWindowForTarget':return {'windowId':1}
            return {}
        wire.side_effect=response
        state={'current':'owned','context':'ctx','owned':{'owned':1},'baseline':['api'],'verified':True}
        with patch('observer.Wire',return_value=wire):
            obs=ScopedObserver('fixture','/fixture/Default')
        try:
            obs.request({'method':'Browser.getVersion'},state)
            calls=[(c.args[0],c.args[1] if len(c.args)>1 else {}) for c in wire.call_args_list]
            self.assertNotIn('Target.setAutoAttach',[c[0] for c in calls])
            self.assertIn(('Target.autoAttachRelated',{'targetId':'owned','waitForDebuggerOnStart':True,'filter':[{'type':'page'},{'exclude':True}]}),calls)
            wire.reset_mock()
            obs._attached({'sessionId':'foreign','waitingForDebugger':True,'targetInfo':{'targetId':'api','type':'page','browserContextId':'ctx'}})
            self.assertEqual([c.args[0] for c in wire.call_args_list],['Target.detachFromTarget'])
        finally:obs.close()


class SharedConsentTests(unittest.TestCase):
    def test_accepted_peer_does_not_make_exact_pending_socket_ambiguous(self):
        from types import SimpleNamespace as NS
        def conn(local,remote=None,status='ESTABLISHED'):
            return NS(laddr=NS(port=local,ip='127.0.0.1'),raddr=NS(port=remote,ip='127.0.0.1') if remote else None,status=status)
        server=Mock();server.create_time.return_value=1;server.exe.return_value='/chrome'
        server.net_connections.return_value=[conn(5000,None,'LISTEN'),conn(5000,4000),conn(5000,4001)]
        client=Mock();client.net_connections.return_value=[conn(4001,5000)]
        backend=consent.MacConsent('/fixture',5000,'/devtools/browser/fixture')
        backend.pending_port=4001;backend.endpoint_matches=Mock(return_value=True)
        backend.processes={123:{'bound':True,'kind':'main','started':1,'exe':'/chrome'}}
        with patch('psutil.Process',side_effect=lambda pid:server if pid==123 else client),patch.object(consent,'accepted_peers',return_value={(('127.0.0.1',4000),('127.0.0.1',5000))},create=True):
            self.assertTrue(backend.correlate(),'accepted settled socket blocked exact new handshake')
            server.net_connections.return_value.append(conn(5000,4002))
            self.assertFalse(backend.correlate(),'unknown concurrent peer must still block approval')


class ConsentCloseRaceTests(unittest.TestCase):
    def test_target_close_waits_for_peer_handshake_without_blocking_reads(self):
        import tempfile,time
        from observer import ScopedObserver
        root=Path(tempfile.mkdtemp(dir=Path.home()/'.hermes/cache/scratch',prefix='coexist-lock-'))
        entered=threading.Event();release=threading.Event();closed=threading.Event();errors=[]
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_overflow=False;wire.event_gaps={};wire.detached_sessions=set()
        def response(method,params=None,session=None):
            if method=='Target.getTargets':return {'targetInfos':[{'targetId':'owned','type':'page','browserContextId':'ctx'}]}
            if method=='Browser.getWindowForTarget':return {'windowId':1}
            if method=='Target.closeTarget':closed.set();return {'success':True}
            return {}
        wire.side_effect=response
        def pending(*args,**kwargs):entered.set();release.wait(4);return 'accepted'
        def handshake():
            try:consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/fixture',root,Mock())
            except Exception as exc:errors.append(str(exc))
        state={'current':'owned','context':'ctx','owned':{'owned':1}}
        def close_owned():
            try:obs.request({'method':'Target.closeTarget','params':{'targetId':'owned'}},state)
            except Exception as exc:errors.append(str(exc))
        with patch('observer.Wire',return_value=wire),patch.object(consent,'_connect_with_consent',side_effect=pending):
            obs=ScopedObserver('fixture',str(root/'Default'))
            attaching=threading.Thread(target=handshake);closing=threading.Thread(target=close_owned)
            attaching.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(obs.request({'method':'Browser.getVersion'},state)['value'],{})
                closing.start()
                self.assertFalse(closed.wait(.2),'target close destroyed the other client consent host')
            finally:
                release.set();attaching.join(3)
                if closing.ident:closing.join(3)
                obs.close()
        self.assertEqual(errors,[]);self.assertTrue(closed.is_set())
        self.assertFalse(attaching.is_alive());self.assertFalse(closing.is_alive())
        import shutil;shutil.rmtree(root)


if __name__=='__main__':unittest.main()
