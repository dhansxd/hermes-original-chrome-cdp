"""Early native dialog interrupts the existing transport, never replays it."""
import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from worker import Wire


class NativeDialogShapeTests(unittest.TestCase):
    def button(self,title,key):return {'role':'AXButton','title':title,'key':key}

    def test_duplicate_buttons_with_same_title_are_ambiguous(self):
        from native_dialog import dialog_controls
        for title in ('OK','Oke','Cancel','Batal'):
            buttons=[self.button('OK',1)] if title not in ('OK','Oke') else []
            buttons.extend([self.button(title,2),self.button(title,3)])
            with self.subTest(title=title):self.assertIsNone(dialog_controls(buttons))

    def test_unknown_button_or_reused_identity_is_not_a_supported_dialog(self):
        from native_dialog import dialog_controls
        for buttons in ([self.button('OK',1),self.button('Allow',2)],
                        [self.button('OK',1),self.button('Cancel',1)]):
            self.assertIsNone(dialog_controls(buttons))

    def test_exact_alert_confirm_and_prompt_shapes(self):
        from native_dialog import dialog_controls
        ok=self.button('Oke',1);cancel=self.button('Batal',2)
        field={'role':'AXTextField','title':'message','value':'default','key':3}
        self.assertEqual(dialog_controls([ok])['type'],'alert')
        self.assertEqual(dialog_controls([ok,cancel])['type'],'confirm')
        self.assertEqual(dialog_controls([ok,cancel,field])['type'],'prompt')
        self.assertIsNone(dialog_controls([ok,field]))


class NativeDialogTransportTests(unittest.TestCase):
    def test_native_dialog_yields_pending_command_before_response_deadline(self):
        class Socket:
            def __init__(self):self.sent=[]
            def send(self,text):self.sent.append(json.loads(text))
            def recv(self,timeout):raise TimeoutError()
        wire=Wire.__new__(Wire);wire.ws=Socket();wire.counter=0
        wire.native_dialog_probe=lambda: {'type':'prompt','message':'early'}
        try:wire('Runtime.evaluate',{'expression':'window.open()'},'owned')
        except Exception as exc:self.assertIn('dialog_pending',str(exc))
        else:self.fail('native dialog must yield, not claim action success')
        self.assertEqual(len(wire.ws.sent),1)
        self.assertEqual(wire.pending_responses,{1:'Runtime.evaluate'})


class NativeDialogObserverTests(unittest.TestCase):
    def test_native_probe_attaches_exact_child_before_peer_can_hide_its_prompt(self):
        from unittest.mock import Mock,patch
        from observer import ScopedObserver
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_gaps={};wire.detached_sessions=set()
        wire.return_value={'sessionId':'held-child'}
        state={'context':'ctx','current':'root','owned':{'root':10},'verified':True}
        pending={'child':{'dialog':{'type':'prompt','message':'identical'},'window_id':10}}
        with patch('observer.Wire',return_value=wire):
            obs=ScopedObserver('fixture','/fixture/Default');obs.state=state
            obs.native.scan=Mock(return_value=pending)
            self.assertTrue(obs._probe_native())
            self.assertEqual(obs.sessions.get('child'),'held-child',
                             'an un-debugged native prompt is cancelled when a peer changes the active tab')
            self.assertEqual(state['owned'],{'root':10,'child':10})
            self.assertEqual(wire.call_args_list[0].args,
                             ('Target.attachToTarget',{'targetId':'child','flatten':True}))
            self.assertEqual(wire.dialog_yield_sessions,{'held-child'})
            self.assertTrue(obs._probe_native())
            wire.assert_called_once() # no Page.enable, action replay or duplicate attach
            obs.close()

    def test_child_with_native_prompt_is_not_page_enabled_until_answer(self):
        from unittest.mock import Mock,patch
        from observer import ScopedObserver
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_gaps={};wire.detached_sessions=set()
        wire.return_value={'windowId':10}
        state={'context':'ctx','current':'root','owned':{'root':10,'child':10},'verified':True}
        with patch('observer.Wire',return_value=wire):
            obs=ScopedObserver('fixture','/fixture/Default');obs.state=state
            obs.native_pending={'child':{'dialog':{'type':'prompt','message':'early'}}}
            obs._attached({'sessionId':'held','targetInfo':{'targetId':'child','type':'page','browserContextId':'ctx','openerId':'root'},'waitingForDebugger':False})
            self.assertEqual(obs.sessions['child'],'held')
            self.assertEqual([call.args[0] for call in wire.call_args_list],['Browser.getWindowForTarget'])
            obs.close()


    def test_dialog_appearing_during_page_enable_defers_setup_not_real_attach(self):
        from unittest.mock import Mock,patch
        from observer import ScopedObserver
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_gaps={};wire.detached_sessions=set()
        state={'context':'ctx','current':'root','owned':{'root':10,'child':10},'verified':True}
        with patch('observer.Wire',return_value=wire):
            obs=ScopedObserver('fixture','/fixture/Default');obs.state=state
            def respond(method,params=None,session=None):
                if method=='Browser.getWindowForTarget':return {'windowId':10}
                if method=='Page.enable':
                    obs.native_pending={'child':{'dialog':{'type':'prompt','message':'early'}}}
                    raise RuntimeError('dialog_pending: Page.enable sent once')
                return {}
            wire.side_effect=respond
            failure=None
            try:obs._attached({'sessionId':'held','targetInfo':{'targetId':'child','type':'page','browserContextId':'ctx','openerId':'root'},'waitingForDebugger':False})
            except RuntimeError as exc:failure=str(exc)
            self.assertIsNone(failure,'an exact pending native dialog must defer setup, not fail attachment')
            self.assertEqual(obs.sessions['child'],'held')
            self.assertEqual([call.args[0] for call in wire.call_args_list],['Browser.getWindowForTarget','Page.enable'])
            obs.close()

    def test_native_dialog_defers_related_setup_without_marking_it_complete(self):
        from unittest.mock import Mock,patch
        from observer import ScopedObserver
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_gaps={};wire.detached_sessions=set()
        state={'context':'ctx','current':'root','owned':{'root':10,'child':10},'verified':True}
        infos=[{'targetId':'root'},{'targetId':'child'}]
        with patch('observer.Wire',return_value=wire):
            obs=ScopedObserver('fixture','/fixture/Default');obs.watched={'root'}
            def respond(method,params=None,session=None):
                if method=='Target.autoAttachRelated':
                    obs.sessions['child']='held'
                    obs.native_pending={'child':{'dialog':{'type':'prompt','message':'early','defaultPrompt':'initial'}}}
                    raise RuntimeError('dialog_pending: Target.autoAttachRelated sent once')
                return {'targetInfos':infos}
            wire.side_effect=respond
            failure=None;result={}
            try:result=obs.request({'method':'Target.getTargets'},state)
            except RuntimeError as exc:failure=str(exc)
            self.assertIsNone(failure,'pending setup must not block independent browser metadata')
            self.assertEqual(result['value'],{'targetInfos':infos})
            self.assertEqual(result['dialogs']['held']['message'],'early')
            self.assertNotIn('child',obs.watched,'unacknowledged setup is not complete')
            obs.request({'method':'Target.getTargets'},state)
            self.assertEqual(sum(call.args[0]=='Target.autoAttachRelated' for call in wire.call_args_list),1)
            obs.close()

    def test_setup_still_raises_without_exact_native_dialog_provenance(self):
        from unittest.mock import Mock,patch
        from observer import ScopedObserver
        for pending,error in (({},'dialog_pending: Page.enable'),
                              ({'foreign':{}},'dialog_pending: Page.enable'),
                              ({'child':{}},'setup_rejected')):
            with self.subTest(pending=pending,error=error):
                wire=Mock();wire.events=[];wire.event_gaps={};wire.detached_sessions=set()
                state={'context':'ctx','current':'root','owned':{'root':10,'child':10},'verified':True}
                with patch('observer.Wire',return_value=wire):
                    obs=ScopedObserver('fixture','/fixture/Default');obs.state=state
                    def respond(method,params=None,session=None):
                        if method=='Browser.getWindowForTarget':return {'windowId':10}
                        obs.native_pending=pending
                        raise RuntimeError(error)
                    wire.side_effect=respond
                    try:
                        with self.assertRaisesRegex(RuntimeError,error):
                            obs._attached({'sessionId':'held','targetInfo':{'targetId':'child','type':'page','browserContextId':'ctx','openerId':'root'}})
                    finally:obs.close()

    def test_pending_child_is_not_watched_before_explicit_native_answer(self):
        from unittest.mock import Mock,patch
        from observer import ScopedObserver
        wire=Mock();wire.events=[];wire.dialogs={};wire.event_gaps={};wire.detached_sessions=set()
        wire.return_value={'targetInfos':[{'targetId':'root'},{'targetId':'child'}]}
        state={'context':'ctx','current':'root','owned':{'root':10,'child':10},'verified':True}
        with patch('observer.Wire',return_value=wire):
            obs=ScopedObserver('fixture','/fixture/Default');obs.state=state;obs.watched={'root'}
            obs.native_pending={'child':{'dialog':{'type':'prompt','message':'early'}}}
            obs.request({'method':'Target.getTargets'},state)
            self.assertNotIn('Target.autoAttachRelated',[call.args[0] for call in wire.call_args_list])
            obs.close()


class NativeDialogSessionTests(unittest.TestCase):
    def test_answer_refreshes_worker_mapping_after_owned_watcher_attaches(self):
        from binding import BoundBrowser
        calls=[]
        class Transport:
            def __call__(self,method,params=None,session=None):
                calls.append((method,session))
                if method=='Target.getTargets':return {'targetInfos':[{'targetId':'child','browserContextId':'ctx'}]}
                if method=='Browser.getWindowForTarget':return {'windowId':10}
                if method=='Target.attachToTarget':return {'sessionId':'held-after-answer'}
                if method in ('Page.enable','Network.enable') and session!='held-after-answer':raise RuntimeError('session_not_owned')
                return {}
        browser=BoundBrowser(Transport(),{'context':'ctx','current':'child','owned':{'child':10}})
        browser.sessions={'child':'held-before-answer'}
        browser.cdp('Page.handleJavaScriptDialog',accept=True,promptText='explicit')
        self.assertEqual(browser.sessions['child'],'held-after-answer')
        self.assertEqual(sum(m=='Page.handleJavaScriptDialog' for m,s in calls),1)


class NativeDialogScanTests(unittest.TestCase):
    def fixture(self):
        from unittest.mock import Mock
        from native_dialog import NativeDialogs
        helper=NativeDialogs('/fixture','fixture');helper._host=Mock();helper.ax=Mock()
        state={'context':'ctx','owned':{'owned':10},'verified':True}
        count=[0]
        def metadata(method,params=None):
            if method=='Target.getTargets':
                count[0]+=1
                return {'targetInfos':[{'targetId':'owned','type':'page','browserContextId':'ctx',
                                        'url':'https://example.test/'+str(count[0])}]}
            if method=='Browser.getWindowForTarget':
                return {'windowId':10,'bounds':{'left':0,'top':0,'width':900,'height':600}}
            raise AssertionError('scan attempted a browser action')
        wire=Mock(side_effect=metadata)
        return helper,state,wire

    def test_transient_scan_rebuilds_metadata_and_ax_snapshot_before_selecting(self):
        from unittest.mock import patch
        from consent import ConsentError
        for code in (-25202,-25204):
            with self.subTest(code=code):
                helper,state,wire=self.fixture()
                helper.ax.scan.side_effect=[ConsentError('consent_ax_read:'+str(code)),
                    [{'key':1,'frame':(0,0,900,600),'document':'https://example.test/2',
                      'dialogs':[{'key':100,'type':'alert','message':'fixture'}]}]]
                with patch('native_dialog.time.sleep') as sleep:found=helper.scan(state,wire)
                self.assertEqual(found['owned']['document'],'https://example.test/2')
                self.assertEqual(helper._host.call_count,2);self.assertEqual(helper.ax.scan.call_count,2)
                self.assertEqual([call.args[0] for call in wire.call_args_list],
                                 ['Target.getTargets','Browser.getWindowForTarget']*2)
                sleep.assert_called_once_with(.05);helper.ax.answer.assert_not_called()

    def test_repeated_transient_failure_stops_at_three_observations(self):
        from unittest.mock import patch
        from consent import ConsentError
        helper,state,wire=self.fixture();failure=ConsentError('consent_ax_read:-25202')
        helper.ax.scan.side_effect=failure
        with patch('native_dialog.time.sleep') as sleep:
            with self.assertRaises(ConsentError) as caught:helper.scan(state,wire)
        self.assertIs(caught.exception,failure)
        self.assertEqual(helper._host.call_count,3);self.assertEqual(helper.ax.scan.call_count,3)
        self.assertEqual(sleep.call_count,2);helper.ax.answer.assert_not_called()

    def test_other_error_or_same_text_in_non_consent_error_is_not_retried(self):
        from unittest.mock import patch
        from consent import ConsentError
        for failure in (ConsentError('consent_ax_read:-25200'),RuntimeError('consent_ax_read:-25202')):
            with self.subTest(error=type(failure).__name__):
                helper,state,wire=self.fixture();helper.ax.scan.side_effect=failure
                with patch('native_dialog.time.sleep') as sleep:
                    with self.assertRaises(type(failure)) as caught:helper.scan(state,wire)
                self.assertIs(caught.exception,failure);helper.ax.scan.assert_called_once()
                sleep.assert_not_called();helper.ax.answer.assert_not_called()


class NativeDialogAnswerTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        self.now=0
        def sleep(seconds):self.now+=seconds
        clock=SimpleNamespace(monotonic=lambda:self.now,sleep=sleep)
        timer=patch('native_dialog.time',clock);timer.start();self.addCleanup(timer.stop)

    def test_answer_waits_for_same_native_identity_before_single_press(self):
        from unittest.mock import Mock
        from native_dialog import NativeDialogs
        expected={'dialog':{'key':100,'type':'prompt'}}
        helper=NativeDialogs('/fixture','fixture');helper.ax=Mock();observed=[];pressed=[]
        def scan(state,wire):observed.append(self.now);return {'child':expected}
        helper.scan=scan;helper.ax.answer.side_effect=lambda *args:pressed.append(self.now);helper.ax.scan.return_value=[]
        helper.answer('child',expected,{'accept':True,'promptText':'answer'},{},Mock())
        self.assertGreaterEqual(pressed[0],1,'newly exposed native dialog is not ready for AXPress')
        self.assertGreaterEqual(len(observed),2,'identity must be revalidated after settling')
        helper.ax.answer.assert_called_once()

    def test_identity_change_while_settling_never_presses(self):
        from unittest.mock import Mock
        from native_dialog import NativeDialogs
        expected={'dialog':{'key':100,'type':'prompt'}}
        helper=NativeDialogs('/fixture','fixture');helper.ax=Mock()
        helper.scan=lambda state,wire:{'child':expected if self.now<.5 else {'dialog':{'key':200}}}
        with self.assertRaisesRegex(RuntimeError,'identity_changed'):
            helper.answer('child',expected,{'accept':True},{},Mock())
        helper.ax.answer.assert_not_called()

    def test_unconfirmed_native_press_quarantines_the_session(self):
        from unittest.mock import Mock,patch
        from native_dialog import NativeDialogs
        dialog={'key':100,'type':'prompt','message':'early'}
        expected={'dialog':dialog,'window_key':1}
        helper=NativeDialogs('/fixture','fixture');helper.ax=Mock()
        helper.ax.scan.return_value=[{'dialogs':[dialog]}]
        helper.scan=lambda state,wire:{'child':expected}
        with self.assertRaises(TimeoutError):
            helper.answer('child',expected,{'accept':True,'promptText':'answer'}, {},Mock())
        helper.ax.answer.assert_called_once_with(dialog,True,'answer')

    def test_native_action_or_post_press_read_error_is_uncertain(self):
        from unittest.mock import Mock
        from native_dialog import NativeDialogs
        from consent import ConsentError
        expected={'dialog':{'key':100,'type':'alert'}}
        for failed_stage in ('press','readback','transient_readback'):
            with self.subTest(stage=failed_stage):
                helper=NativeDialogs('/fixture','fixture');helper.ax=Mock()
                helper.scan=lambda state,wire:{'child':expected}
                if failed_stage=='press':helper.ax.answer.side_effect=RuntimeError('native_press_unconfirmed')
                elif failed_stage=='transient_readback':helper.ax.scan.side_effect=ConsentError('consent_ax_read:-25202')
                else:helper.ax.scan.side_effect=RuntimeError('invalid_native_snapshot')
                with self.assertRaises(TimeoutError):
                    helper.answer('child',expected,{'accept':True},{},Mock())
                helper.ax.answer.assert_called_once()
                if failed_stage!='press':helper.ax.scan.assert_called_once()

    def test_changed_native_identity_never_presses(self):
        from unittest.mock import Mock
        from native_dialog import NativeDialogs
        helper=NativeDialogs('/fixture','fixture');helper.ax=Mock()
        helper.scan=lambda state,wire:{'child':{'dialog':{'key':200}}}
        with self.assertRaisesRegex(RuntimeError,'identity_changed'):
            helper.answer('child',{'dialog':{'key':100}},{'accept':True},{},Mock())
        helper.ax.answer.assert_not_called()


class NativeDialogBindingTests(unittest.TestCase):
    def test_owned_child_requires_unique_native_document_and_frame(self):
        from native_dialog import select_dialogs
        state={'context':'ctx','owned':{'root':10},'baseline':['manual']}
        infos=[{'targetId':'root','browserContextId':'ctx','url':'https://example.test/root'},
               {'targetId':'child','browserContextId':'ctx','openerId':'root','url':'about:blank'},
               {'targetId':'manual','browserContextId':'ctx','url':'about:blank'}]
        windows={'root':{'windowId':10,'bounds':{'left':0,'top':0,'width':900,'height':600}},
                 'child':{'windowId':10,'bounds':{'left':0,'top':0,'width':900,'height':600}},
                 'manual':{'windowId':20,'bounds':{'left':30,'top':30,'width':900,'height':600}}}
        dialog={'key':100,'type':'prompt','message':'same-message'}
        snapshot=[{'key':1,'frame':(0,0,900,600),'document':'about:blank','dialogs':[dialog]},
                  {'key':2,'frame':(30,30,900,600),'document':'about:blank','dialogs':[dict(dialog,key=200)]}]
        found=select_dialogs(state,infos,windows,snapshot)
        self.assertEqual(set(found),{'child'})
        self.assertEqual(found['child']['dialog']['key'],100)
        # Neither duplicate geometry nor a foreign tab in the owned window grants authority.
        windows['manual']['bounds']=dict(windows['child']['bounds'])
        self.assertEqual(select_dialogs(state,infos,windows,snapshot),{})
        windows['manual']=dict(windows['child'])
        self.assertEqual(select_dialogs(state,infos,windows,snapshot),{})

    def test_root_window_binding_survives_popup_replacing_active_tab(self):
        from native_dialog import select_dialogs
        state={'context':'ctx','owned':{'root':10},'baseline':['foreign']}
        infos=[{'targetId':'root','browserContextId':'ctx','url':'https://example.test/root'},
               {'targetId':'foreign','browserContextId':'ctx','url':'about:blank'}]
        win={'windowId':10,'bounds':{'left':0,'top':0,'width':900,'height':600}}
        windows={'root':win,'foreign':dict(win,windowId=20)}
        snapshots=[{'key':1,'frame':(0,0,900,600),'document':'https://example.test/root','dialogs':[]},
                   {'key':2,'frame':(0,0,900,600),'document':'about:blank','dialogs':[]}]
        bindings={}
        select_dialogs(state,infos,windows,snapshots,bindings)
        self.assertEqual(bindings,{10:1})
        infos.append({'targetId':'child','browserContextId':'ctx','url':'about:blank','openerId':'root'})
        windows['child']=win
        snapshots[0].update(document='about:blank',dialogs=[{'key':100,'type':'prompt','message':'early'}])
        snapshots[1]['dialogs']=[{'key':200,'type':'prompt','message':'early'}]
        found=select_dialogs(state,infos,windows,snapshots,bindings)
        self.assertEqual(found['child']['dialog']['key'],100)
        self.assertNotIn('foreign',found)

    def test_bound_window_uses_exact_address_when_loading_document_is_unavailable(self):
        from native_dialog import select_dialogs
        state={'context':'ctx','owned':{'root':10},'baseline':[]}
        infos=[{'targetId':'root','browserContextId':'ctx','url':'https://example.test/root'},
               {'targetId':'child','browserContextId':'ctx','openerId':'root','url':'http://127.0.0.1:8080/early'}]
        window={'windowId':10,'bounds':{'left':0,'top':0,'width':900,'height':600}}
        snapshot=[{'key':1,'frame':(0,0,900,600),'document':'','address':'127.0.0.1:8080/early','dialogs':[{'key':100,'type':'prompt','message':'early'}]}]
        found=select_dialogs(state,infos,{'root':window,'child':window},snapshot,{10:1})
        self.assertEqual(set(found),{'child'})
        snapshot[0]['address']='127.0.0.1:8080/early-foreign'
        self.assertEqual(select_dialogs(state,infos,{'root':window,'child':window},snapshot,{10:1}),{})


if __name__=='__main__':unittest.main()
