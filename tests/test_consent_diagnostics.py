"""Offline consent boundary/deadline tests: no sockets, Chrome, or native AX."""
import sys
import threading
import unittest
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import consent
from consent_fakes import exact_sheet


@contextmanager
def fake_clock():
    now=[10.0]
    def advance(seconds):now[0]+=seconds
    with patch('consent.time.monotonic',side_effect=lambda:now[0]),\
         patch('consent.time.sleep',side_effect=advance):
        yield now


class ConsentGuardTests(unittest.TestCase):
    def test_nested_same_thread_scope_keeps_other_thread_excluded_until_outer_exit(self):
        trying=threading.Event();entered=threading.Event();errors=[]
        with tempfile.TemporaryDirectory() as home,patch('consent.Path.home',return_value=Path(home)):
            root=Path(home)/'profile'
            def contender():
                trying.set()
                try:
                    with consent.consent_guard(root,timeout=2):entered.set()
                except Exception as exc:errors.append(exc)
            thread=threading.Thread(target=contender)
            with consent.consent_guard(root):
                with self.assertRaisesRegex(RuntimeError,'nested fixture'):
                    with consent.consent_guard(root/'unused'/'..',timeout=.2):
                        raise RuntimeError('nested fixture')
                thread.start()
                self.assertTrue(trying.wait(1))
                self.assertFalse(entered.wait(.1),'nested exit must not unlock the outer scope')
            self.assertTrue(entered.wait(1));thread.join(1)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])

    def test_nested_expired_budget_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as home,patch('consent.Path.home',return_value=Path(home)):
            root=Path(home)/'profile'
            with consent.consent_guard(root):
                with self.assertRaisesRegex(consent.ConsentError,'phase=queue'):
                    with consent.consent_guard(root,deadline=consent.time.monotonic()-1):
                        self.fail('expired nested scope entered')

    def test_inherited_thread_local_record_cannot_reuse_a_different_pid_lock(self):
        pid=os.getpid()
        with tempfile.TemporaryDirectory() as home,patch('consent.Path.home',return_value=Path(home)):
            root=Path(home)/'profile'
            with consent.consent_guard(root):
                with patch('consent.os.getpid',return_value=pid+1):
                    with self.assertRaisesRegex(consent.ConsentError,'phase=queue'):
                        with consent.consent_guard(root,timeout=.02):
                            self.fail('another PID inherited the reentrancy exemption')


class ExactPressTests(unittest.TestCase):
    def test_manual_diagnostic_observes_but_never_presses(self):
        connected=threading.Event();approved=threading.Event()
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?',
               'headings':[],'buttons':['Allow']}
        class Backend:
            scans=0
            press=Mock(side_effect=AssertionError('manual mode must not press'))
            def scan(self):
                if not connected.is_set():return []
                self.scans+=1
                if self.scans>=2:approved.set()
                return [sheet]
            def hosts(self):return {42}
            def correlate(self):return True
        backend=Backend();receipt=object()
        def attach(*args,**kwargs):
            connected.set()
            if not approved.wait(1):raise AssertionError('manual approval not observed')
            return receipt
        with consent.manual_consent():
            result=consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id',
                '/fixture',attach,backend=backend)
        self.assertIs(result,receipt);backend.press.assert_not_called()

    def test_manual_timeout_extension_is_scoped_to_operator_context(self):
        backend=object()
        with patch('consent._connect_with_consent',return_value='ready') as connect:
            with consent.manual_consent():
                consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id',
                    '/fixture',Mock(),backend=backend)
            self.assertEqual(connect.call_args.kwargs['timeout'],60)
            consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id',
                '/fixture',Mock(),backend=backend)
            self.assertEqual(connect.call_args.kwargs['timeout'],15)

    def test_only_retained_exact_button_pressed_with_own_timeout(self):
        ax,sheet,data=exact_sheet()
        with ax.pin(sheet):self.assertTrue(ax.press(sheet))
        ax.ax.AXUIElementPerformAction.assert_called_once_with(4,'AXPress')
        self.assertEqual(ax.ax.AXUIElementSetMessagingTimeout.call_args.args,(4,1))
        self.assertEqual(ax.cf.CFRetain.call_count,3)
        self.assertEqual(ax.cf.CFRelease.call_count,3)

    def test_replacement_sheet_or_button_is_not_inherited_via_hash(self):
        ax,sheet,data=exact_sheet()
        for change in ({'sheet':20},{'window':10},{'elements':{'Allow':40}},
                       {'host':dict(sheet['host'],started=99)}):
            self.assertFalse(ax.same_sheet(sheet,dict(sheet,**change)))
        with self.assertRaisesRegex(consent.ConsentError,'distinct sheets'):
            consent.select_sheet([sheet,dict(sheet,sheet=20)],set(),{42})

    def test_same_object_with_changed_question_is_not_approved(self):
        ax,sheet,data=exact_sheet()
        data[2]['AXTitle']='Allow download?';data[3]['AXValue']='Allow download?'
        with self.assertRaisesRegex(consent.ConsentError,'changed_before_press'):ax.press(sheet)
        ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_changed_parent_pid_or_pending_state_blocks_action(self):
        for kind in ('parent','pid','pending'):
            ax,sheet,data=exact_sheet()
            if kind=='parent':ax.attr=lambda node,key:None
            if kind=='pid':ax.ax.AXUIElementGetPid.side_effect=lambda node,pid:0
            with self.subTest(kind=kind):
                if kind=='pending':self.assertFalse(ax.press(sheet,pending=lambda:False))
                else:
                    with self.assertRaisesRegex(consent.ConsentError,'changed_before_press'):ax.press(sheet)
            ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_action_error_is_single_attempt_and_outcome_unknown(self):
        for status in (-25204,-25202,-25200):
            ax,sheet,data=exact_sheet();ax.ax.AXUIElementPerformAction.return_value=status
            with self.assertRaisesRegex(consent.ConsentError,'press outcome unknown; no retry'):ax.press(sheet)
            ax.ax.AXUIElementPerformAction.assert_called_once()

    def test_timeout_setup_failure_or_expiry_never_presses(self):
        ax,sheet,data=exact_sheet();ax.ax.AXUIElementSetMessagingTimeout.return_value=-25202
        with self.assertRaisesRegex(consent.ConsentError,'timeout_setup'):ax.press(sheet)
        ax.ax.AXUIElementPerformAction.assert_not_called()
        ax.ax.AXUIElementSetMessagingTimeout.return_value=0;ax.deadline=1
        with patch('consent.time.monotonic',return_value=2):
            with self.assertRaisesRegex(consent.ConsentError,'consent_deadline'):ax.press(sheet)
        ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_mac_revalidates_same_refs_and_socket_immediately_before_action(self):
        ax,sheet,data=exact_sheet();backend=consent.MacConsent('/fixture',5000)
        backend.ax=ax;backend.scan=Mock(return_value=[sheet]);backend.hosts=Mock(return_value={42})
        backend.correlate=Mock(side_effect=[True,False])
        with fake_clock():backend.press(sheet,pending=lambda:True)
        self.assertEqual(backend.correlate.call_count,2)
        ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_mac_waits_before_single_exact_action_and_records_dispatch_time(self):
        ax,sheet,data=exact_sheet();backend=consent.MacConsent('/fixture',5000)
        backend.ax=ax;backend.scan=Mock(return_value=[sheet]);backend.hosts=Mock(return_value={42})
        backend.correlate=Mock(return_value=True)
        with fake_clock() as now:
            backend.trace=ax.trace=consent.ConsentTrace()
            dispatched=[]
            ax.ax.AXUIElementPerformAction.side_effect=lambda *args:dispatched.append(now[0]) or 0
            backend.press(sheet,pending=lambda:True)
        self.assertEqual(len(dispatched),1)
        self.assertGreaterEqual(dispatched[0]-10,1)
        self.assertEqual(ax.ax.AXUIElementPerformAction.call_args.args,(4,'AXPress'))
        self.assertGreaterEqual(ax.trace.values['press_ms'],1000)
        self.assertEqual(ax.cf.CFRetain.call_count,3)
        self.assertEqual(ax.cf.CFRelease.call_count,3)

    def test_socket_finishing_during_settle_prevents_action(self):
        ax,sheet,data=exact_sheet();backend=consent.MacConsent('/fixture',5000)
        backend.ax=ax;backend.scan=Mock()
        with fake_clock() as now:
            backend.trace=ax.trace=consent.ConsentTrace()
            backend.press(sheet,pending=lambda:now[0]<10.2)
        backend.scan.assert_not_called();ax.ax.AXUIElementPerformAction.assert_not_called()
        self.assertEqual(ax.trace.values['press_outcome'],'pending_ended')
        self.assertIsNone(ax.trace.values['press_ms'])
        self.assertEqual(ax.cf.CFRelease.call_count,3)

    def test_deadline_during_settle_prevents_action_without_extending_budget(self):
        ax,sheet,data=exact_sheet();backend=consent.MacConsent('/fixture',5000)
        backend.ax=ax;backend.scan=Mock();backend.deadline=10.2
        with fake_clock() as now:
            with self.assertRaisesRegex(consent.ConsentError,'phase=settling'):
                backend.press(sheet,pending=lambda:True)
            self.assertAlmostEqual(now[0],10.2)
        backend.scan.assert_not_called();ax.ax.AXUIElementPerformAction.assert_not_called()
        self.assertEqual(backend.deadline,10.2)
        self.assertEqual(ax.cf.CFRelease.call_count,3)

    def test_replaced_sheet_or_changed_socket_after_settle_prevents_action(self):
        for change in ('sheet','socket'):
            with self.subTest(change=change),fake_clock() as now:
                ax,sheet,data=exact_sheet();backend=consent.MacConsent('/fixture',5000)
                backend.ax=ax;backend.hosts=Mock(return_value={42})
                def rescan():
                    self.assertGreaterEqual(now[0],11)
                    return [dict(sheet,sheet=20) if change=='sheet' else sheet]
                backend.scan=Mock(side_effect=rescan)
                backend.correlate=Mock(return_value=change!='socket')
                with self.assertRaisesRegex(consent.ConsentError,'changed_before_press'):
                    backend.press(sheet,pending=lambda:True)
                ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_unknown_action_result_after_settle_is_one_attempt(self):
        ax,sheet,data=exact_sheet();backend=consent.MacConsent('/fixture',5000)
        backend.ax=ax;backend.scan=Mock(return_value=[sheet]);backend.hosts=Mock(return_value={42})
        backend.correlate=Mock(return_value=True);ax.ax.AXUIElementPerformAction.return_value=-25204
        with fake_clock():
            with self.assertRaisesRegex(consent.ConsentError,'outcome unknown; no retry'):
                backend.press(sheet,pending=lambda:True)
        ax.ax.AXUIElementPerformAction.assert_called_once_with(4,'AXPress')

    def test_only_claimed_exact_sheet_can_be_cancelled(self):
        ax,sheet,data=exact_sheet();backend=consent.MacConsent('/fixture',5000)
        backend.ax=ax;backend.scan=Mock(side_effect=[[sheet],[]]);backend.hosts=Mock(return_value={42})
        backend.no_peers=Mock(return_value=True)
        backend.claim(sheet)
        try:backend.cleanup_abandoned(set())
        finally:backend.release_claim()
        ax.ax.AXUIElementPerformAction.assert_called_once_with(5,'AXPress')

    def test_exhausted_action_budget_has_one_second_for_claimed_cancel_only(self):
        ax,sheet,data=exact_sheet();backend=consent.MacConsent('/fixture',5000)
        backend.ax=ax;backend.deadline=1;ax.deadline=1
        backend.scan=Mock(side_effect=[[sheet],[]]);backend.hosts=Mock(return_value={42})
        backend.no_peers=Mock(return_value=True)
        backend.claim(sheet)
        try:
            with patch('consent.time.monotonic',return_value=2):backend.cleanup_abandoned(set())
        finally:backend.release_claim()
        ax.ax.AXUIElementPerformAction.assert_called_once_with(5,'AXPress')
        self.assertEqual((backend.deadline,ax.deadline),(1,1))
        self.assertEqual(ax.ax.AXUIElementSetMessagingTimeout.call_args.args,(5,1))

    def test_exhausted_action_budget_never_cleans_unclaimed_prompt(self):
        backend=consent.MacConsent('/fixture',5000);backend.deadline=1
        backend.scan=Mock();backend.ax=Mock()
        with patch('consent.time.monotonic',return_value=2):backend.cleanup_abandoned(set())
        backend.scan.assert_not_called();backend.ax.press.assert_not_called()

    def test_unknown_peer_or_replacement_blocks_claimed_cancellation(self):
        for replacement in (False,True):
            ax,sheet,data=exact_sheet();backend=consent.MacConsent('/fixture',5000)
            backend.ax=ax;backend.scan=Mock(return_value=[dict(sheet,sheet=20) if replacement else sheet])
            backend.hosts=Mock(return_value={42});backend.no_peers=Mock(return_value=False)
            backend.claim(sheet)
            try:
                with self.assertRaises(consent.ConsentError):backend.cleanup_abandoned(set())
            finally:backend.release_claim()
            ax.ax.AXUIElementPerformAction.assert_not_called()


class HandshakeDiagnosticTests(unittest.TestCase):
    def test_failure_codes_are_allowlisted_without_arbitrary_error_text(self):
        for message,expected in (
            ('consent_attach_failed: consent_ax_read:-25204','consent_ax_read'),
            ('consent_preflight_failed: consent_deadline: private details','consent_deadline'),
            ('consent_attach_failed: wss://private/account','unknown'),
            ('consent_ax_read_private_account: bad','unknown'),
        ):
            with self.subTest(message=message),patch('consent.logging.getLogger'):
                error=consent.ConsentTrace().failure(consent.ConsentError(message))
                self.assertEqual(error.diagnostics['failure_code'],expected)
                self.assertNotIn('private',json.dumps(error.diagnostics))

    def test_native_transient_pre_action_read_reobserves_same_handshake_before_one_dispatch(self):
        for code in (-25202,-25204):
            with self.subTest(code=code):
                connected=threading.Event();approved=threading.Event();attempts=[]
                ax,sheet,data=exact_sheet();backend=consent.MacConsent('/fixture',5000)
                backend.ax=ax;backend.prepare=Mock(return_value=[]);backend.hosts=Mock(return_value={42})
                backend.correlate=Mock(return_value=True);backend.cleanup_abandoned=Mock()
                def scan():
                    if len(attempts)==1:
                        self.assertIsNone(backend._claim,'stale claimed sheet was not released')
                    return [sheet] if connected.is_set() else []
                backend.scan=Mock(side_effect=scan)
                def press(selected,*,pending):
                    attempts.append('entered')
                    if len(attempts)==1:
                        ax.ax.AXUIElementPerformAction.assert_not_called()
                        raise consent.ConsentError('consent_ax_read:'+str(code))
                    ax.trace=backend.trace;ax.deadline=backend.deadline
                    ax.press(selected,pending=pending)
                backend.press=Mock(side_effect=press)
                ax.ax.AXUIElementPerformAction.side_effect=lambda *args:approved.set() or 0
                receipt=Mock();sock=Mock();sock.getsockname.return_value=('127.0.0.1',4001)
                def attach(*args,**kwargs):
                    connected.set()
                    if not approved.wait(1):raise TimeoutError('fixture approval missing')
                    return receipt
                attach=Mock(side_effect=attach)
                with patch('socket.create_connection',return_value=sock),\
                     patch('consent.register_accepted',return_value=receipt):
                    result=consent._connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id',
                        '/fixture',attach,backend=backend,timeout=2)
                self.assertIs(result,receipt);attach.assert_called_once()
                self.assertEqual(len(attempts),2)
                self.assertEqual(backend.trace.values['transient_ax_reads'],1)
                ax.ax.AXUIElementPerformAction.assert_called_once_with(4,'AXPress')
                self.assertIsNone(backend._claim)

    def test_native_dispatched_action_never_retries_even_for_transient_looking_error(self):
        connected=threading.Event();dispatched=threading.Event()
        ax,sheet,data=exact_sheet();backend=consent.MacConsent('/fixture',5000)
        backend.ax=ax;backend.prepare=Mock(return_value=[]);backend.hosts=Mock(return_value={42})
        backend.correlate=Mock(return_value=True);backend.cleanup_abandoned=Mock()
        backend.scan=Mock(side_effect=lambda:[sheet] if connected.is_set() else [])
        def press(selected,*,pending):
            ax.trace=backend.trace;ax.press(selected,pending=pending)
            raise consent.ConsentError('consent_ax_read:-25204')
        backend.press=Mock(side_effect=press)
        ax.ax.AXUIElementPerformAction.side_effect=lambda *args:dispatched.set() or 0
        sock=Mock();sock.getsockname.return_value=('127.0.0.1',4001)
        def attach(*args,**kwargs):
            connected.set();dispatched.wait(1);threading.Event().wait(.15)
            raise TimeoutError('fixture handshake unknown')
        with patch('socket.create_connection',return_value=sock),patch('consent.logging.getLogger'):
            with self.assertRaisesRegex(consent.ConsentError,'consent_ax_read:-25204') as caught:
                consent._connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id',
                    '/fixture',attach,backend=backend,timeout=2)
        backend.press.assert_called_once();ax.ax.AXUIElementPerformAction.assert_called_once()
        self.assertTrue(caught.exception.diagnostics['press_dispatched'])
        self.assertEqual(caught.exception.diagnostics['transient_ax_reads'],0)
        self.assertEqual(caught.exception.diagnostics['failure_code'],'consent_ax_read')

    def test_failure_logs_sanitized_diagnostics_once_without_changing_error_text(self):
        connected=threading.Event()
        private_sheet={'key':(42,1),'pid':42,'name':'private account dialog','headings':['private title'],
                       'buttons':['private label']}
        class Backend:
            def scan(self):return [private_sheet] if connected.is_set() else []
            def hosts(self):return {42}
        def attach(*args,**kwargs):
            connected.set();threading.Event().wait(.12)
            raise TimeoutError('fixture deadline')
        with patch('consent.logging.getLogger') as logger:
            with self.assertRaises(consent.ConsentError) as caught:
                consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/private-endpoint',
                                             '/private-profile',attach,backend=Backend(),timeout=1)
        self.assertEqual(str(caught.exception),'consent_attach_failed: fixture deadline')
        diagnostics=caught.exception.diagnostics
        self.assertGreater(diagnostics['scan_calls'],1)
        self.assertGreater(diagnostics['sheets_seen'],0)
        self.assertEqual(diagnostics['debugging_sheets_seen'],0)
        self.assertFalse(diagnostics['press_attempted'])
        self.assertEqual(diagnostics['press_outcome'],'not_attempted')
        self.assertIsNone(diagnostics['first_sheet_ms'])
        self.assertIsNone(diagnostics['press_ms'])
        logger.return_value.warning.assert_called_once()
        serialized=logger.return_value.warning.call_args.args[1]
        self.assertEqual(json.loads(serialized),diagnostics)
        self.assertNotIn('private',serialized)
        self.assertNotIn('pid',diagnostics)

    def test_native_press_diagnostics_distinguish_dispatch_from_acknowledgement(self):
        for status in (0,-25204):
            ax,sheet,data=exact_sheet();ax.trace=consent.ConsentTrace()
            ax.ax.AXUIElementPerformAction.return_value=status
            if status:
                with self.assertRaises(consent.ConsentError):ax.press(sheet)
            else:ax.press(sheet)
            diagnostic=ax.trace.snapshot()
            self.assertTrue(diagnostic['press_dispatched'])
            self.assertEqual(diagnostic['press_outcome'],'unconfirmed' if status else 'acknowledged')
            self.assertEqual(diagnostic['press_ax_status'],status)

    def test_transient_looking_press_error_is_never_replayed(self):
        connected=threading.Event();release=threading.Event();order=[]
        sheet={'key':(42,1),'pid':42,'name':'Allow remote debugging?','headings':[],'buttons':['Allow']}
        class Backend:
            def scan(self):return [sheet] if connected.is_set() else []
            def hosts(self):return {42}
            def correlate(self):return True
            def press(self,sheet,*,pending):
                order.append('press');release.set()
                raise consent.ConsentError('consent_ax_read:-25204')
        def attach(*args,**kwargs):
            order.append('connect');connected.set();release.wait(.5)
            threading.Event().wait(.15)
            raise TimeoutError('fixture denied')
        with self.assertRaisesRegex(consent.ConsentError,'consent_ax_read:-25204') as caught:
            consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',attach,backend=Backend(),timeout=1)
        self.assertEqual(order,['connect','press'])
        self.assertIsInstance(caught.exception.diagnostics['first_sheet_ms'],int)
        self.assertIsNone(caught.exception.diagnostics['press_ms'])

    def test_queue_time_is_deducted_from_preflight_and_handshake_budget(self):
        clock=[10.0]
        @contextmanager
        def guard(*args,**kwargs):
            self.assertEqual(kwargs['deadline'],15)
            clock[0]=14
            yield
        backend=consent.MacConsent('/fixture',5000)
        backend.prepare=Mock(return_value=[]);backend.scan=Mock(return_value=[])
        sock=Mock();sock.getsockname.return_value=('127.0.0.1',4001)
        ws=Mock()
        with patch('consent.time.monotonic',side_effect=lambda:clock[0]),patch('consent.consent_guard',guard),\
             patch('socket.create_connection',return_value=sock) as dial,patch('consent.register_accepted',return_value=ws):
            attach=Mock(return_value=ws)
            self.assertIs(consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',attach,backend=backend,timeout=5),ws)
        self.assertEqual(dial.call_args.kwargs['timeout'],1)
        self.assertEqual(attach.call_args.kwargs['open_timeout'],1)

    def test_expired_queue_prevents_scan_and_connection(self):
        @contextmanager
        def guard(*args,**kwargs):
            raise consent.ConsentError('consent_deadline: phase=queue; no action replay')
            yield
        backend=consent.MacConsent('/fixture',5000);backend.prepare=Mock();attach=Mock()
        with patch('consent.consent_guard',guard):
            with self.assertRaisesRegex(consent.ConsentError,'phase=queue'):
                consent.connect_with_consent('ws://127.0.0.1:5000/devtools/browser/id','/fixture',attach,backend=backend,timeout=1)
        attach.assert_not_called();backend.prepare.assert_not_called()


if __name__=='__main__':unittest.main()
