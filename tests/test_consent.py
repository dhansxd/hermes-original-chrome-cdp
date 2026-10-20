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
    def test_requires_one_new_sheet_on_bound_host(self):
        sheet={'key':(42,1),'pid':42,'name':'','headings':['Izinkan proses debug jarak jauh?'],'buttons':['Izinkan']}
        self.assertEqual(consent.select_sheet([sheet],set(),{42}),sheet)
        for sheets,baseline,hosts in [([sheet],{(42,1)},{42}),([sheet,dict(sheet,key=(42,2))],set(),{42}),([sheet],set(),{99})]:
            with self.assertRaisesRegex(consent.ConsentError,'consent_'):
                consent.select_sheet(sheets,baseline,hosts)
        self.assertIsNone(consent.select_sheet([],set(),{42}))

    def test_socket_correlation_requires_only_our_pending_connection(self):
        self.assertTrue(consent.socket_matches([(4000,5000)],[(5000,4000)],5000))
        self.assertFalse(consent.socket_matches([(4000,5000),(4001,5000)],[(5000,4000)],5000))
        self.assertFalse(consent.socket_matches([(4000,5000)],[(5000,9999)],5000))

class HandshakeTests(unittest.TestCase):
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
        b=Mock(spec=['scan','press']);b.scan.side_effect=consent.ConsentError('consent_ax_read:-25202')
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


class StalePreflightTests(unittest.TestCase):
    def test_preexisting_prompt_blocks_before_new_handshake(self):
        from unittest.mock import Mock
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow','Cancel']}
        backend=Mock(spec=['scan']);backend.scan.return_value=[sheet];attach=Mock()
        with self.assertRaisesRegex(consent.ConsentError,'preexisting'):
            consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',attach,backend=backend,timeout=.2)
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
        sock=Mock();sock.shutdown.side_effect=lambda *a:order.append('shutdown');sock.close.side_effect=lambda:order.append('close')
        def fail(*a,**kw):
            self.assertIs(kw['sock'],sock);raise TimeoutError('fixture timeout')
        with patch('socket.create_connection',return_value=sock):
            with self.assertRaisesRegex(consent.ConsentError,'fixture timeout'):
                consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',fail,backend=Backend('/fixture',5000),timeout=1)
        self.assertLess(order.index('close'),order.index('cleanup'))

if __name__=='__main__':unittest.main()
