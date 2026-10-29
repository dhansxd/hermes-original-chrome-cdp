import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class BindingTest(unittest.TestCase):
    def test_owned_target_only_and_lost_target_never_adopts_manual(self):
        from binding import BoundBrowser
        calls=[]
        targets=[{'targetId':'manual','type':'page','browserContextId':'ctx'}, {'targetId':'agent','type':'page','browserContextId':'ctx'}]
        def wire(method, params=None, session=None):
            calls.append((method,params,session))
            if method=='Target.getTargets': return {'targetInfos':targets}
            if method=='Browser.getWindowForTarget': return {'windowId':2}
            if method=='Target.attachToTarget': return {'sessionId':'sid'}
            return {}
        state={'current':'agent','context':'ctx','owned':{'agent':2}}
        browser=BoundBrowser(wire,state)
        browser.cdp('Page.navigate',url='https://example.com')
        self.assertEqual(calls[-1],('Page.navigate',{'url':'https://example.com'},'sid'))
        with self.assertRaisesRegex(RuntimeError,'not_owned'):
            browser.cdp('Target.closeTarget',targetId='manual')
        targets.pop()
        with self.assertRaisesRegex(RuntimeError,'binding_unavailable'):
            browser.cdp('Runtime.evaluate',expression='document.title')
        self.assertFalse(any(m=='Target.attachToTarget' and p['targetId']=='manual' for m,p,s in calls))

class CloseAcknowledgementTest(unittest.TestCase):
    def test_rejected_close_keeps_owned_target_for_cleanup(self):
        from binding import BoundBrowser
        calls=[]
        def wire(method,params=None,session=None):
            calls.append(method)
            if method=='Target.getTargets':return {'targetInfos':[{'targetId':'agent','browserContextId':'ctx'}]}
            if method=='Browser.getWindowForTarget':return {'windowId':2}
            if method=='Target.closeTarget':return {'success':False}
            raise AssertionError(method)
        state={'current':'agent','context':'ctx','owned':{'agent':2}}
        browser=BoundBrowser(wire,state)
        with self.assertRaisesRegex(RuntimeError,'target_close_rejected'):
            browser.cdp('Target.closeTarget',targetId='agent')
        self.assertEqual(state['owned'],{'agent':2})
        self.assertFalse(browser.cleanup()['success'])
        self.assertEqual(calls.count('Target.closeTarget'),2)

class UnsupportedTest(unittest.TestCase):
    def test_unimplemented_events_are_not_reported_as_empty_success(self):
        from binding import BoundBrowser
        browser=BoundBrowser(lambda *a,**k: {}, {})
        for meta in ('pending_dialog','drain_events'):
            with self.assertRaisesRegex(RuntimeError,'unsupported_helper_meta'):
                browser.send({'meta':meta})

class DiscoveredPopupTest(unittest.TestCase):
    def test_event_owned_popup_gets_window_before_observer_attachment(self):
        from binding import BoundBrowser
        targets=[{'targetId':'agent','type':'page','browserContextId':'ctx'}, {'targetId':'popup','type':'page','browserContextId':'ctx','openerId':'agent'}]
        def wire(method,params=None,session=None):
            if method=='Target.getTargets':return {'targetInfos':targets}
            if method=='Browser.getWindowForTarget':return {'windowId':22}
            raise AssertionError(method)
        state={'current':'agent','context':'ctx','owned':{'agent':1,'popup':None},'baseline':[]}
        b=BoundBrowser(wire,state);b.track_popups()
        self.assertEqual(state['owned']['popup'],22)

class PopupTest(unittest.TestCase):
    def test_new_popup_with_owned_opener_is_tracked_not_manual_same_window(self):
        from binding import BoundBrowser
        targets=[{'targetId':'agent','type':'page','browserContextId':'ctx'}, {'targetId':'popup','type':'page','browserContextId':'ctx','openerId':'agent'}, {'targetId':'manual','type':'page','browserContextId':'ctx'}]
        def wire(method,params=None,session=None):
            if method=='Target.getTargets':return {'targetInfos':targets}
            if method=='Browser.getWindowForTarget':return {'windowId':2}
            raise AssertionError(method)
        state={'current':'agent','context':'ctx','owned':{'agent':2},'baseline':['manual']}
        browser=BoundBrowser(wire,state)
        self.assertEqual(browser.track_popups(),['popup'])
        self.assertEqual(set(state['owned']),{'agent','popup'})

if __name__=='__main__':unittest.main()
