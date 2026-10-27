"""Consent fixtures do not press real UI or open Chrome."""
import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import consent

class MatchingTests(unittest.TestCase):
    def test_exact_localized_question_and_button(self):
        self.assertEqual(consent.button_for_dialog('', ['Izinkan proses debug jarak jauh?']), 'Izinkan')
        self.assertEqual(consent.button_for_dialog('Allow remote debugging?', []), 'Allow')
        self.assertIsNone(consent.button_for_dialog('Allow?', []))
        self.assertIsNone(consent.button_for_dialog('Allow remote debugging?', ['Izinkan proses debug jarak jauh?']))

class CorrelationTests(unittest.TestCase):
    def test_accepted_ipv4_peer_does_not_exempt_unknown_ipv6_peer_with_same_ports(self):
        import tempfile,os,json
        from types import SimpleNamespace as NS
        from unittest.mock import patch,Mock
        import cdp_peers as peers
        def conn(local,remote=None,ip='127.0.0.1',status='ESTABLISHED',fd=10):
            return NS(laddr=NS(ip=ip,port=local),raddr=NS(ip=ip,port=remote)if remote else (),status=status,fd=fd)
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory)/'root';endpoint='/devtools/browser/family-test'
            accepted=Mock();accepted.uids.return_value=NS(real=os.getuid());accepted.create_time.return_value=1
            accepted.net_connections.return_value=[conn(4000,5000)]
            marker=Path(directory)/(peers._prefix(root,5000,endpoint)+'-peer-fixture.json')
            marker.write_text(json.dumps({'epoch':peers._prefix(root,5000,endpoint),'pid':99,'started':1,'local_port':4000,'fd':10}));marker.chmod(0o600)
            server=Mock();server.create_time.return_value=1;server.exe.return_value='/chrome'
            server.net_connections.return_value=[conn(5000,status='LISTEN'),conn(5000,4000)]
            client=Mock();client.net_connections.return_value=[conn(4001,5000)]
            backend=consent.MacConsent(root,5000,endpoint);backend.endpoint_matches=Mock(return_value=True)
            backend.pending_port=4001;backend.processes={42:{'bound':True,'kind':'main','started':1,'exe':'/chrome'}}
            def process(pid):return {42:server,99:accepted,os.getpid():client}[pid]
            with patch.object(peers,'_folder',return_value=Path(directory)),patch('psutil.Process',side_effect=process):
                self.assertTrue(backend.no_peers(),'the exact accepted socket alone is settled')
                server.net_connections.return_value.append(conn(5000,4001))
                self.assertTrue(backend.correlate(),'the sole exact pending socket still qualifies')
                server.net_connections.return_value.append(conn(5000,4000,ip='::1'))
                self.assertFalse(backend.correlate(),'unknown IPv6 socket cannot inherit accepted IPv4 consent')
                server.net_connections.return_value.pop(-2)
                self.assertFalse(backend.no_peers(),'unknown IPv6 peer must block orphan cancellation')

    def test_requires_one_new_sheet_on_bound_host(self):
        sheet={'key':(42,1),'pid':42,'name':'','headings':['Izinkan proses debug jarak jauh?'],'buttons':['Izinkan']}
        self.assertEqual(consent.select_sheet([sheet],set(),{42}),sheet)
        for sheets,baseline,hosts in [([sheet],{(42,1)},{42}),([sheet,dict(sheet,key=(42,2))],set(),{42}),([sheet],set(),{99})]:
            with self.assertRaisesRegex(consent.ConsentError,'consent_'):
                consent.select_sheet(sheets,baseline,hosts)
        self.assertIsNone(consent.select_sheet([],set(),{42}))

    def test_socket_correlation_requires_only_our_pending_connection(self):
        server=[(('127.0.0.1',5000),('127.0.0.1',4000))]
        client=[(('127.0.0.1',4000),('127.0.0.1',5000))]
        self.assertTrue(consent.socket_matches(server,client,5000))
        self.assertFalse(consent.socket_matches(server+[(('::1',5000),('::1',4000))],client,5000))
        self.assertFalse(consent.socket_matches(server,[(('::1',4000),('::1',5000))],5000))

class HandshakeTests(unittest.TestCase):
    def test_registration_failure_closes_completed_websocket_with_full_receiver_queue(self):
        import threading,time
        from unittest.mock import patch,Mock
        from websockets.sync.client import connect
        from websockets.sync.server import serve
        from websockets.exceptions import ConnectionClosed
        release=threading.Event();retained=[]
        def events(remote):
            try:
                for _ in range(12):remote.send('event')
                release.wait(3)
            except ConnectionClosed:pass
        server=serve(events,'127.0.0.1',0,ping_interval=None,close_timeout=.1)
        serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
        port=server.socket.getsockname()[1]
        backend=consent.MacConsent('/fixture',port,'/devtools/browser/queue')
        backend.prepare=Mock(return_value=[]);backend.scan=Mock(return_value=[]);backend.cleanup_abandoned=Mock()
        def completed(*args,**kwargs):
            ws=connect(*args,**kwargs,max_queue=1,ping_interval=10,ping_timeout=1,close_timeout=.1)
            retained.append(ws);deadline=time.monotonic()+1
            while not ws.recv_flow_control.locked()and time.monotonic()<deadline:time.sleep(.001)
            self.assertTrue(ws.recv_flow_control.locked(),'fixture must block the library receive queue')
            time.sleep(.02);return ws
        failure=OSError('disk-full')
        try:
            with patch.object(consent,'register_accepted',side_effect=failure):
                with self.assertRaises(OSError)as caught:
                    consent._connect_with_consent('ws://127.0.0.1:'+str(port)+'/devtools/browser/queue',
                                                 '/fixture',completed,backend=backend,timeout=1)
            self.assertIs(caught.exception,failure,'cleanup must preserve the registration error')
            ws=retained[0];ws.recv_events_thread.join(.3)
            if ws.keepalive_thread is not None:ws.keepalive_thread.join(.3)
            self.assertEqual(ws.socket.fileno(),-1)
            self.assertFalse(ws.recv_events_thread.is_alive(),'completed WebSocket receiver leaked after registration failure')
            self.assertFalse(ws.keepalive_thread and ws.keepalive_thread.is_alive())
        finally:
            for ws in retained:
                ws.close_socket();ws.recv_events_thread.join(1)
                if ws.keepalive_thread is not None:ws.keepalive_thread.join(1)
            release.set();server.shutdown();serving.join(2)
        self.assertFalse(serving.is_alive())

    def test_delayed_sheet_only_pressed_during_pending_attach(self):
        import threading,time
        ready=threading.Event();calls=[]
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow']}
        class Backend:
            def scan(self):return [sheet] if calls else []
            def hosts(self):return {42}
            def correlate(self):return True
            def press(self,s,*,pending):
                if pending():calls.append('press');ready.set()
        def connect(endpoint,**kwargs):
            calls.append('connect')
            if not ready.wait(1):raise TimeoutError('fixture attach blocked')
            return 'socket'
        self.assertEqual(consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',connect,backend=Backend(),timeout=1),'socket')
        self.assertEqual(calls,['connect','press'])

    def test_transient_baseline_read_is_retried_before_connect(self):
        import threading
        ready=threading.Event();order=[]
        sheet={'key':(42,2),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow']}
        class Backend:
            count=0
            def scan(self):
                self.count+=1;order.append('scan')
                if self.count==1:raise consent.ConsentError('consent_ax_read:-25204')
                return [sheet] if 'connect' in order else []
            def hosts(self):return {42}
            def correlate(self):return True
            def press(self,s,*,pending):
                if pending():ready.set()
        def connect(*a,**k):
            order.append('connect')
            if not ready.wait(.8):raise TimeoutError('fixture no press')
            return 'socket'
        self.assertEqual(consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',connect,backend=Backend(),timeout=1),'socket')
        self.assertEqual(order[:3],['scan','scan','connect'])

    def test_transient_ax_read_during_pending_attach_can_recover(self):
        import threading
        ready=threading.Event();calls=[]
        sheet={'key':(42,2),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow']}
        class Backend:
            count=0
            def scan(self):
                self.count+=1
                if self.count==1:return []
                if self.count==2:raise consent.ConsentError('consent_ax_read:-25204')
                return [sheet]
            def hosts(self):return {42}
            def correlate(self):return True
            def press(self,s,*,pending):
                if pending():calls.append('pressed');ready.set()
        def connect(*a,**k):
            if not ready.wait(.8):raise TimeoutError('fixture no press')
            return 'socket'
        self.assertEqual(consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',connect,backend=Backend(),timeout=1),'socket')
        self.assertEqual(calls,['pressed'])

    def test_completed_attach_never_presses_and_errors_are_explicit(self):
        class Backend:
            def scan(self):return []
            def hosts(self):return set()
            def correlate(self):return False
            def press(self,s):raise AssertionError('no click allowed')
        self.assertEqual(consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',lambda *a,**k:'ready',backend=Backend(),timeout=1),'ready')
        def fail(*a,**k):raise TimeoutError('denied')
        with self.assertRaisesRegex(consent.ConsentError,'consent_attach_failed.*denied'):
            consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',fail,backend=Backend(),timeout=1)

    def test_invalid_snapshot_is_rebuilt_before_connect(self):
        from unittest.mock import patch
        class Backend:
            scans=0
            def scan(self):
                self.scans+=1
                if self.scans==1:raise consent.ConsentError('consent_ax_read:-25202')
                return []
        b=Backend();connections=[]
        def attach(*a,**k):
            self.assertEqual(b.scans,2)
            connections.append(True);return 'ready'
        with patch('consent.time.sleep'):
            self.assertEqual(consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',attach,backend=b,timeout=1),'ready')
        self.assertEqual(len(connections),1)

    def test_persistent_invalid_snapshot_stops_before_any_connect(self):
        from unittest.mock import patch,Mock
        b=Mock(spec=['scan','hosts','press','correlate']);b.scan.side_effect=consent.ConsentError('consent_ax_read:-25202')
        attach=Mock()
        with patch('consent.time.monotonic',side_effect=[0,0,2]),patch('consent.time.sleep'):
            with self.assertRaisesRegex(consent.ConsentError,'consent_preflight_failed.*-25202'):
                consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',attach,backend=b,timeout=1)
        self.assertEqual(b.scan.call_count,2);attach.assert_not_called();b.press.assert_not_called()

    def test_invalid_snapshot_during_pending_attach_does_not_restart_handshake(self):
        from unittest.mock import patch
        import threading
        done=threading.Event();calls=[]
        class Backend:
            scans=0
            def scan(self):
                self.scans+=1
                if self.scans==2:raise consent.ConsentError('consent_ax_read:-25202')
                if self.scans>=3:done.set()
                return []
            def hosts(self):return set()
        b=Backend()
        def attach(*a,**k):
            calls.append(True)
            if not done.wait(.8):raise TimeoutError('test barrier')
            return 'ready'
        self.assertEqual(consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',attach,backend=b,timeout=1),'ready')
        self.assertEqual(len(calls),1);self.assertGreaterEqual(b.scans,3)

    def test_correlation_snapshot_retry_stays_in_one_handshake(self):
        import threading
        ready=threading.Event();calls=[]
        sheet={'key':(42,8),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow']}
        class Backend:
            count=0
            def scan(self):return [sheet] if calls else []
            def hosts(self):return {42}
            def correlate(self):
                self.count+=1
                return self.count>=2
            def press(self,s,*,pending):
                self.asserted=self.count
                if pending():calls.append('press');ready.set()
        b=Backend()
        def attach(*a,**k):
            calls.append('connect')
            if not ready.wait(.7):raise TimeoutError('fixture uncorrelated')
            return 'ready'
        self.assertEqual(consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',attach,backend=b,timeout=1),'ready')
        self.assertEqual(calls,['connect','press']);self.assertGreaterEqual(b.asserted,2)

    def test_persistent_correlation_mismatch_never_presses(self):
        import threading
        calls=[]
        sheet={'key':(42,9),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow']}
        class Backend:
            def scan(self):return [sheet] if calls else []
            def hosts(self):return {42}
            def correlate(self):return False
            def press(self,*a,**k):raise AssertionError('unsafe press')
        def attach(*a,**k):
            calls.append('connect');threading.Event().wait(.3);raise TimeoutError('fixture deadline')
        with self.assertRaisesRegex(consent.ConsentError,'consent_attach_uncorrelated'):
            consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',attach,backend=Backend(),timeout=.4)
        self.assertEqual(calls,['connect'])

    def test_remote_endpoint_not_approved(self):
        with self.assertRaisesRegex(consent.ConsentError,'consent_endpoint'):
            consent.connect_with_consent('ws://example.com:5000/devtools/browser/id','/fixture',lambda *a,**k:None)

class IdentityTests(unittest.TestCase):
    def test_multi_profile_root_uses_actual_socket_not_profile_count(self):
        import tempfile
        from unittest.mock import patch, Mock
        with tempfile.TemporaryDirectory() as directory:
            backend=consent.MacConsent(directory,5000,'/devtools/browser/id')
            Path(directory,'DevToolsActivePort').write_text('5000\n/devtools/browser/id\n')
            Path(directory,'Local State').write_text('{"profile":{"info_cache":{"Default":{},"Profile 1":{}}}}')
            Path(directory,'Profile 1').mkdir()
            backend.processes={42:{'bound':True,'kind':'main','started':10,'exe':'chrome'}}
            def conn(local, remote, status):
                return Mock(laddr=Mock(ip='127.0.0.1',port=local),raddr=Mock(ip='127.0.0.1',port=remote) if remote else (),status=status)
            server=Mock();server.create_time.return_value=10;server.exe.return_value='chrome'
            server.net_connections.return_value=[conn(5000,None,'LISTEN'),conn(5000,4000,'ESTABLISHED')]
            client=Mock();client.net_connections.return_value=[conn(4000,5000,'ESTABLISHED')]
            with patch('psutil.Process',side_effect=lambda pid:server if pid==42 else client):
                self.assertTrue(backend.correlate())
                server.net_connections.return_value.append(conn(5000,4001,'ESTABLISHED'))
                self.assertFalse(backend.correlate())

    def test_adhoc_pwa_signature_is_validated_without_template_hash_equality(self):
        from unittest.mock import patch,Mock
        import tempfile,plistlib
        with tempfile.TemporaryDirectory() as root:
            app=Path(root)/'Applications/Chrome Apps.localized/Test.app'
            exe=app/'Contents/MacOS/app_mode_loader';exe.parent.mkdir(parents=True);exe.write_bytes(b'signed shim')
            data=Path(root)/'Chrome'
            plist={'CFBundleIdentifier':'com.google.Chrome.app.abc','CFBundleExecutable':'app_mode_loader','CrBundleIdentifier':'com.google.Chrome','CrAppModeShortcutID':'abc','CrAppModeUserDataDir':str(data/'- /Web Applications/_crx_abc').replace('- /','-/')}
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps(plist))
            with patch('consent.subprocess.run',return_value=Mock(returncode=0)):
                self.assertTrue(consent.verify_pwa_host(exe,plist,data,apps_root=Path(root)/'Applications/Chrome Apps.localized'))
            with patch('consent.subprocess.run',return_value=Mock(returncode=1)):
                self.assertFalse(consent.verify_pwa_host(exe,plist,data,apps_root=Path(root)/'Applications/Chrome Apps.localized'))

    def test_endpoint_must_match_data_root_port_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            backend=consent.MacConsent(directory,5000,'/devtools/browser/expected')
            self.assertFalse(backend.endpoint_matches())
            Path(directory,'DevToolsActivePort').write_text('5000\n/devtools/browser/expected\n')
            self.assertTrue(backend.endpoint_matches())
            Path(directory,'DevToolsActivePort').write_text('5000\n/devtools/browser/stale\n')
            self.assertFalse(backend.endpoint_matches())

    def test_main_and_pwa_require_exact_bundle_executable_and_root(self):
        main='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        self.assertEqual(consent.host_identity(main,{'CFBundleIdentifier':'com.google.Chrome','CFBundleExecutable':'Google Chrome'},'/data'), 'main')
        self.assertIsNone(consent.host_identity('/tmp/Google Chrome',{'CFBundleIdentifier':'com.google.Chrome'},'/data'))
        plist={'CFBundleIdentifier':'com.google.Chrome.app.abc','CFBundleExecutable':'app_mode_loader','CrBundleIdentifier':'com.google.Chrome','CrAppModeShortcutID':'abc','CrAppModeUserDataDir':'/data/Default/Web Applications/_crx_abc'}
        exe='/Users/test/Applications/Chrome Apps.localized/Test.app/Contents/MacOS/app_mode_loader'
        self.assertEqual(consent.host_identity(exe,plist,'/data'),'pwa')
        plist['CrAppModeUserDataDir']='/data/-/Web Applications/_crx_abc'
        self.assertEqual(consent.host_identity(exe,plist,'/data'),'pwa')
        plist['CrAppModeUserDataDir']='/different/-/Web Applications/_crx_abc'
        self.assertIsNone(consent.host_identity(exe,plist,'/data'))
        plist['CrAppModeUserDataDir']='/data/Default/Web Applications/_crx_abc'
        self.assertIsNone(consent.host_identity(exe,plist,'/other'))
        plist['CFBundleIdentifier']='com.attacker.app.abc'
        self.assertIsNone(consent.host_identity(exe,plist,'/data'))

class WorkerTests(unittest.TestCase):
    def test_wire_uses_profile_root_for_consent(self):
        from unittest.mock import patch
        import worker
        with patch.object(worker,'connect_with_consent',return_value=object()) as attach:
            worker.Wire('ws://127.0.0.1:5000/devtools/browser/id','/fixture')
            attach.assert_called_once_with('ws://127.0.0.1:5000/devtools/browser/id','/fixture',worker.connect)

class NativeTests(unittest.TestCase):
    def test_press_uses_pid_scoped_applescript_and_checks_clicked_receipt(self):
        from unittest.mock import patch,Mock
        sheet={'pid':42,'bundle':'com.google.Chrome','name':'','headings':['Izinkan proses debug jarak jauh?'],'buttons':['Izinkan']}
        ax=object.__new__(consent.AX)
        with patch('consent.subprocess.run',return_value=Mock(returncode=0,stdout='clicked',stderr='')) as run:
            ax.press(sheet)
            argv=run.call_args.args[0]
            self.assertEqual(argv[0:2],['osascript','-e'])
            self.assertEqual(argv[-2:],['42','com.google.Chrome'])
        with patch('consent.subprocess.run',return_value=Mock(returncode=0,stdout='not-found',stderr='')):
            with self.assertRaisesRegex(consent.ConsentError,'consent_press_not_confirmed'):
                ax.press(sheet)

    def test_pending_attach_rechecked_immediately_before_ax_press(self):
        from unittest.mock import Mock
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow']}
        backend=consent.MacConsent('/fixture',5000)
        backend.ax=Mock();backend.scan=lambda:[sheet];backend.hosts=lambda:{42};backend.correlate=lambda:True
        backend.press(sheet,pending=lambda:False)
        backend.ax.press.assert_not_called()

    def test_real_ax_extraction_reads_unnamed_localized_sheet(self):
        # Run the actual extraction traversal, replacing only C transport.
        from unittest.mock import Mock
        ax=object.__new__(consent.AX);ax.refs=[]
        data={1:{'AXRole':'AXWindow'},2:{'AXRole':'AXSheet','AXTitle':''},3:{'AXRole':'AXHeading','AXValue':'Izinkan proses debug jarak jauh?'},4:{'AXRole':'AXButton','AXTitle':'Izinkan'}}
        ax.ax=Mock();ax.ax.AXUIElementCreateApplication.return_value=99
        ax.cf=Mock();ax.cf.CFArrayGetCount.return_value=1;ax.cf.CFArrayGetValueAtIndex.return_value=1;ax.cf.CFHash.return_value=200
        ax.attr=lambda node,key:100 if key=='AXWindows' else None
        ax.text=lambda node,key:data.get(node,{}).get(key,'')
        ax.children=lambda node:{1:[2],2:[3,4]}.get(node,[])
        sheets=ax.sheets(42)
        self.assertEqual(sheets[0]['headings'],['Izinkan proses debug jarak jauh?'])
        self.assertEqual(sheets[0]['buttons'],['Izinkan'])
        self.assertEqual(sheets[0]['name'],'')

    def test_optional_title_failure_does_not_abort_sheet_traversal(self):
        ax=object.__new__(consent.AX)
        def fail(node,name):raise consent.ConsentError('consent_ax_read:-25200')
        ax.attr=fail
        self.assertEqual(ax.text(1,'AXTitle'),'')
        with self.assertRaises(consent.ConsentError):ax.text(1,'AXRole')

    def test_missing_accessibility_is_explicit_without_permission_prompt(self):
        from unittest.mock import patch
        with patch.object(consent,'AX') as ax:
            ax.return_value.trusted.return_value=False
            with self.assertRaisesRegex(consent.ConsentError,'consent_accessibility'):
                consent.MacConsent('/fixture',5000).scan()

class CancelIsolationTests(unittest.TestCase):
    def test_distinct_questions_never_cancel_either_sheet(self):
        from unittest.mock import Mock
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?','headings':[],
               'buttons':['Allow','Cancel'],'elements':{'Cancel':123}}
        backend=consent.MacConsent('/fixture',5000);backend.ax=Mock()
        backend.ax.ax.AXUIElementPerformAction.return_value=0
        backend.scan=lambda:[sheet,dict(sheet,key=(42,2))]
        backend.no_peers=lambda:True;backend.processes={42:{'kind':'main','bound':True}}
        with self.assertRaisesRegex(consent.ConsentError,'consent_cancel_ambiguous'):
            backend.cancel_sheet(sheet,orphan=True)
        backend.ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_cancel_does_not_report_success_while_exact_sheet_remains(self):
        from unittest.mock import Mock,patch
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?','headings':[],
               'buttons':['Allow','Cancel'],'elements':{'Cancel':123}}
        backend=consent.MacConsent('/fixture',5000);backend.ax=Mock()
        backend.ax.ax.AXUIElementPerformAction.return_value=0
        backend.scan=lambda:[sheet];backend.no_peers=lambda:True
        backend.processes={42:{'kind':'main','bound':True}}
        with patch('consent.time.monotonic',side_effect=[0,1]),patch('consent.time.sleep'):
            with self.assertRaisesRegex(consent.ConsentError,'consent_cancel_not_dismissed'):
                backend.cancel_sheet(sheet,orphan=True)
        backend.ax.ax.AXUIElementPerformAction.assert_called_once()

    def test_cancel_returns_only_after_exact_sheet_disappears(self):
        from unittest.mock import Mock
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?','headings':[],
               'buttons':['Allow','Cancel'],'elements':{'Cancel':123}}
        backend=consent.MacConsent('/fixture',5000);backend.ax=Mock()
        backend.ax.ax.AXUIElementPerformAction.return_value=0
        backend.scan=Mock(side_effect=[[sheet],[]]);backend.no_peers=lambda:True
        backend.processes={42:{'kind':'main','bound':True}}
        backend.cancel_sheet(sheet,orphan=True)
        backend.ax.ax.AXUIElementPerformAction.assert_called_once()
        self.assertEqual(backend.scan.call_count,2)

    def test_unknown_peer_prevents_cancellation(self):
        from unittest.mock import Mock
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?','headings':[],
               'buttons':['Allow','Cancel'],'elements':{'Cancel':123}}
        backend=consent.MacConsent('/fixture',5000);backend.ax=Mock()
        backend.scan=lambda:[sheet];backend.no_peers=lambda:False
        backend.processes={42:{'kind':'main','bound':True}}
        with self.assertRaisesRegex(consent.ConsentError,'consent_preexisting'):
            backend.cancel_sheet(sheet,orphan=True)
        backend.ax.ax.AXUIElementPerformAction.assert_not_called()

class StalePreflightTests(unittest.TestCase):
    def test_preexisting_prompt_blocks_before_new_handshake(self):
        from unittest.mock import Mock
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow','Cancel']}
        backend=Mock(spec=['scan']);backend.scan.return_value=[sheet];attach=Mock()
        with self.assertRaisesRegex(consent.ConsentError,'preexisting'):
            consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',attach,backend=backend,timeout=1)
        attach.assert_not_called()
    def test_orphan_cleanup_never_approves_and_preserves_other_dialogs(self):
        from unittest.mock import Mock
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow','Cancel']}
        unrelated=dict(sheet,key=(42,2),name='Save password?',buttons=['Save'])
        b=consent.MacConsent('/fixture',5000,'/devtools/browser/id')
        b.scan=Mock(side_effect=[[sheet,unrelated],[unrelated]]);b.no_peers=Mock(return_value=True);b.cancel_sheet=Mock()
        b.prepare()
        b.cancel_sheet.assert_called_once_with(sheet,orphan=True);self.assertEqual(b.scan.call_count,2)
    def test_existing_peer_prevents_orphan_cleanup(self):
        from unittest.mock import Mock
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow','Cancel']}
        b=consent.MacConsent('/fixture',5000,'/devtools/browser/id');b.scan=Mock(return_value=[sheet]);b.no_peers=Mock(return_value=False);b.cancel_sheet=Mock()
        with self.assertRaisesRegex(consent.ConsentError,'preexisting'):b.prepare()
        b.cancel_sheet.assert_not_called()


class AbortCleanupTests(unittest.TestCase):
    def test_failed_native_handshake_closes_socket_before_orphan_cleanup(self):
        from unittest.mock import Mock,patch
        order=[]
        class Backend(consent.MacConsent):
            def prepare(self):return []
            def scan(self):return []
            def hosts(self):return set()
            def cleanup_abandoned(self,baseline):order.append('cleanup')
        sock=Mock();sock.getsockname.return_value=('127.0.0.1',4001)
        sock.shutdown.side_effect=lambda *a:order.append('shutdown');sock.close.side_effect=lambda:order.append('close')
        # The transport must reach the handshake before its ordered abort cleanup.
        def fail(*a,**kw):
            self.assertIs(kw['sock'],sock);raise TimeoutError('fixture timeout')
        with patch('socket.create_connection',return_value=sock):
            with self.assertRaisesRegex(consent.ConsentError,'fixture timeout'):
                consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',fail,backend=Backend('/fixture',5000),timeout=1)
        self.assertLess(order.index('close'),order.index('cleanup'))

if __name__=='__main__':unittest.main()
