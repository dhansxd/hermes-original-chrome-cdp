"""Characterization of same-user accepted socket receipts; localhost only."""
import json,os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cdp_peers as peers
from websockets.sync.client import connect
from websockets.sync.server import serve

class PeerReceipts(unittest.TestCase):
    def test_live_socket_is_epoch_scoped_and_removed_on_close(self):
        release=threading.Event()
        def peer(ws):release.wait(5)
        server=serve(peer,'127.0.0.1',0,ping_interval=None,close_timeout=.2)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        port=server.socket.getsockname()[1];path='/devtools/browser/fixture';ws=None;registered=None
        with tempfile.TemporaryDirectory()as d,patch.object(peers,'_folder',return_value=Path(d)):
            root=Path(d)/'root'
            try:
                self.assertEqual(peers.accepted_peers(root,port,path),set())
                ws=connect('ws://127.0.0.1:'+str(port)+path,proxy=None,close_timeout=.2)
                local=ws.socket.getsockname()[1]
                self.assertEqual(peers.accepted_peers(root,port,path),set(),'a dial alone cannot be exempted')
                registered=peers.register_accepted(ws,root,port,path)
                self.assertEqual(peers.accepted_peers(root,port,path),{(('127.0.0.1',local),('127.0.0.1',port))})
                self.assertEqual(peers.accepted_peers(root,port,path+'new'),set())
                self.assertEqual(peers.accepted_peers(root/'other',port,path),set())
                file=next(Path(d).glob('*-peer-*.json'));self.assertEqual(file.stat().st_mode&0o777,0o600)
                registered.close();registered=None;ws=None
                self.assertFalse(file.exists());self.assertEqual(peers.accepted_peers(root,port,path),set())
            finally:
                if registered is not None:registered.close()
                elif ws is not None:ws.close()
                release.set();server.shutdown();thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_receipt_pins_socket_descriptor_until_retired(self):
        release=threading.Event()
        def peer(ws):release.wait(5)
        server=serve(peer,'127.0.0.1',0,ping_interval=None,close_timeout=.2)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        port=server.socket.getsockname()[1];path='/devtools/browser/pin';ws=None;registered=None
        with tempfile.TemporaryDirectory()as d,patch.object(peers,'_folder',return_value=Path(d)):
            root=Path(d)/'root'
            try:
                ws=connect('ws://127.0.0.1:'+str(port)+path,proxy=None,close_timeout=.2)
                raw_fd=ws.socket.fileno();local=ws.socket.getsockname()[1]
                registered=peers.register_accepted(ws,root,port,path)
                file=next(Path(d).glob('*-peer-*.json'));receipt=json.loads(file.read_text())
                self.assertNotEqual(receipt['fd'],raw_fd,'receipt must pin an independent descriptor, not a reusable WebSocket fd')
                self.assertEqual(peers.accepted_peers(root,port,path),{(('127.0.0.1',local),('127.0.0.1',port))})
                ws.close()  # Library/remote close can bypass RegisteredSocket.close.
                self.assertEqual(peers.accepted_peers(root,port,path),set())
                os.fstat(receipt['fd'])  # A live pin prevents same-process descriptor ABA.
                registered.close();registered=None;ws=None
                self.assertFalse(file.exists())
                with self.assertRaises(OSError):os.fstat(receipt['fd'])
            finally:
                if registered is not None:registered.close()
                elif ws is not None:ws.close()
                release.set();server.shutdown();thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_revoked_receipt_is_not_returned_after_socket_scan(self):
        import psutil
        release=threading.Event()
        def peer(ws):release.wait(5)
        server=serve(peer,'127.0.0.1',0,ping_interval=None,close_timeout=.2)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        port=server.socket.getsockname()[1];path='/devtools/browser/revoked';ws=None;registered=None
        with tempfile.TemporaryDirectory()as d,patch.object(peers,'_folder',return_value=Path(d)):
            root=Path(d)/'root'
            try:
                ws=connect('ws://127.0.0.1:'+str(port)+path,proxy=None,close_timeout=.2)
                registered=peers.register_accepted(ws,root,port,path)
                file=next(Path(d).glob('*-peer-*.json'))
                connections=psutil.Process().net_connections(kind='tcp')
                def revoked_scan(*args,**kwargs):
                    file.unlink()
                    return connections
                with patch.object(psutil.Process,'net_connections',revoked_scan):
                    self.assertEqual(peers.accepted_peers(root,port,path),set(),
                                     'a receipt revoked during validation cannot exempt a peer')
            finally:
                if registered is not None:registered.close()
                elif ws is not None:ws.close()
                release.set();server.shutdown();thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_concurrent_close_retires_receipt_and_pin_once(self):
        first_unlink=threading.Event();second_unlink=threading.Event();release=threading.Event()
        errors=[]
        class Receipt:
            calls=0
            def unlink(self,**kwargs):
                self.calls+=1
                if self.calls==1:first_unlink.set()
                else:second_unlink.set()
                release.wait(2)
        class WebSocket:
            def close(self):pass
        fd=os.open(os.devnull,os.O_RDONLY);receipt=Receipt()
        registered=peers.RegisteredSocket(WebSocket(),receipt,fd)
        def close():
            try:registered.close()
            except Exception as exc:errors.append(type(exc).__name__)
        first=threading.Thread(target=close);second=threading.Thread(target=close)
        try:
            first.start();self.assertTrue(first_unlink.wait(2));second.start()
            second_unlink.wait(.15)
        finally:
            release.set();first.join(2);second.join(2)
        self.assertFalse(first.is_alive()or second.is_alive())
        self.assertEqual(receipt.calls,1,'simultaneous closers must retire the receipt once')
        self.assertEqual(errors,[])
        with self.assertRaises(OSError):os.fstat(fd)

    def test_dead_process_or_wrong_epoch_receipt_grants_nothing(self):
        with tempfile.TemporaryDirectory()as d,patch.object(peers,'_folder',return_value=Path(d)):
            root=Path(d)/'root';epoch=peers._prefix(root,5000,'/devtools/browser/fixture')
            file=Path(d)/(epoch+'-peer-stale.json')
            file.write_text(json.dumps({'epoch':epoch,'pid':99999999,'started':1,'local_port':4001,'fd':7}));file.chmod(0o600)
            self.assertEqual(peers.accepted_peers(root,5000,'/devtools/browser/fixture'),set())
            file.write_text('[]')
            self.assertEqual(peers.accepted_peers(root,5000,'/devtools/browser/fixture'),set())

if __name__=='__main__':unittest.main()
