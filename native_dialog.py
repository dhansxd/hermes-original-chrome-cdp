"""Early JS dialogs on positively owned targets; explicit answers, no CDP peer."""
import ctypes as c
import time
from pathlib import Path
from urllib.parse import urlsplit
if __package__:
    from .consent import AX, ConsentError
else:
    from consent import AX, ConsentError


def select_dialogs(state, infos, windows, snapshot, bindings=None):
    bindings={} if bindings is None else bindings
    pages={t['targetId']:t for t in infos if t.get('type','page')=='page' and t.get('browserContextId')==state.get('context')}
    owned=set(state.get('owned',{}))
    for _ in pages:
        added={tid for tid,t in pages.items() if tid not in state.get('baseline',[]) and t.get('openerId') in owned}
        if added<=owned:break
        owned.update(added)
    def matches_url(native,url):
        if native.get('document'):return native['document']==url
        # During a load-time dialog AXDocument can be unset; use only the exact omnibox URL.
        return bool(url and url.startswith(('http://','https://')) and native.get('address') in (url,url.split('://',1)[1]))
    result={}
    for tid in owned & pages.keys() & windows.keys():
        win=windows[tid];bounds=win['bounds']
        frame=tuple(bounds.get(k) for k in ('left','top','width','height'))
        if None in frame or bounds.get('windowState','normal')!='normal':continue
        # Pin the native root before action using a unique document/frame pair.
        # The same window can then show its new opener-linked child, including about:blank.
        if any(other not in owned and w['windowId']==win['windowId'] for other,w in windows.items()):continue
        if state.get('owned',{}).get(tid) not in (None,win['windowId']):continue
        key=bindings.get(win['windowId'])
        if key is not None:
            matches=[w for w in snapshot if w['key']==key and tuple(w.get('frame',()))==frame and matches_url(w,pages[tid].get('url'))]
        else:
            if any(w['windowId']!=win['windowId'] and pages.get(t,{}).get('url')==pages[tid].get('url') and tuple(w['bounds'].get(k) for k in ('left','top','width','height'))==frame for t,w in windows.items()):continue
            matches=[w for w in snapshot if tuple(w.get('frame',()))==frame and matches_url(w,pages[tid].get('url'))]
        if len(matches)!=1:continue
        native=matches[0]
        bindings[win['windowId']]=native['key']
        if len(native.get('dialogs',[]))!=1:continue
        if sum(w['windowId']==win['windowId'] and pages.get(t,{}).get('url')==pages[tid].get('url') for t,w in windows.items())!=1:continue
        result[tid]={'dialog':native['dialogs'][0],'window_key':native['key'],'window_id':win['windowId'],'document':pages[tid]['url'],'frame':frame}
    return result


class NativeAX(AX):
    def __init__(self,pid):
        super().__init__();self.pid=pid;self.elements={}
        self.cf.CFGetTypeID.restype=c.c_ulong;self.cf.CFGetTypeID.argtypes=[c.c_void_p]
        self.cf.CFStringGetTypeID.restype=c.c_ulong;self.cf.CFStringGetTypeID.argtypes=[]
        self.ax.AXValueGetValue.restype=c.c_bool;self.ax.AXValueGetValue.argtypes=[c.c_void_p,c.c_int,c.c_void_p]
        self.ax.AXUIElementSetAttributeValue.restype=c.c_int;self.ax.AXUIElementSetAttributeValue.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p]
    def text(self,node,name):
        try:value=self.attr(node,name)
        except ConsentError as exc:
            if str(exc)=='consent_ax_read:-25200' and name in {'AXTitle','AXDescription','AXValue','AXSubrole','AXDocument'}:return ''
            raise
        if not value or self.cf.CFGetTypeID(value)!=self.cf.CFStringGetTypeID():return ''
        buf=c.create_string_buffer(8192)
        return buf.value.decode() if self.cf.CFStringGetCString(value,buf,len(buf),0x08000100) else ''
    def scan(self):
        self.clear();self.elements={}
        if not self.trusted():raise RuntimeError('native_dialog_accessibility_unavailable')
        app=self.ax.AXUIElementCreateApplication(self.pid);self.refs.append(app)
        self.ax.AXUIElementSetMessagingTimeout(app,.2)
        values=self.attr(app,'AXWindows')
        roots=[self.cf.CFArrayGetValueAtIndex(values,i) for i in range(self.cf.CFArrayGetCount(values))] if values else []
        class Pair(c.Structure):_fields_=[('a',c.c_double),('b',c.c_double)]
        def walk(node,depth=0):
            if depth>12:raise RuntimeError('native_dialog_tree_depth')
            role=self.text(node,'AXRole');key=self.cf.CFHash(node);self.elements[key]=node
            row={'role':role,'key':key,'subrole':self.text(node,'AXSubrole'),'title':self.text(node,'AXTitle'),'value':self.text(node,'AXValue')}
            row['children']=[] if role in {'AXWebArea','AXScrollArea'} else [walk(x,depth+1) for x in self.children(node)]
            return row
        def nodes(n):
            yield n
            for child in n['children']:yield from nodes(child)
        result=[]
        for root in roots:
            if self.text(root,'AXSubrole')!='AXStandardWindow':continue
            tree=walk(root);frame=[]
            for name,kind in [('AXPosition',1),('AXSize',2)]:
                value=self.attr(root,name);pair=Pair()
                if not value or not self.ax.AXValueGetValue(value,kind,c.byref(pair)):break
                frame.extend((pair.a,pair.b))
            dialogs=[]
            for dialog in nodes(tree):
                if dialog['subrole']!='AXApplicationDialog':continue
                controls=list(nodes(dialog));fields=[n for n in controls if n['role']=='AXTextField']
                buttons={n['title']:n['key'] for n in controls if n['role']=='AXButton'}
                ok=[buttons[k] for k in ('Oke','OK') if k in buttons];cancel=[buttons[k] for k in ('Batal','Cancel') if k in buttons]
                if len(ok)!=1 or len(fields)>1 or len(cancel)>1:continue
                # A prompt's accessible field label is its message, not page instructions.
                kind='prompt' if fields else ('confirm' if cancel else 'alert')
                dialogs.append({'key':dialog['key'],'type':kind,'message':fields[0]['title'] if fields else self.text(self.elements[dialog['key']],'AXDescription'),
                                'defaultPrompt':fields[0]['value'] if fields else '', 'field':fields[0]['key'] if fields else None,
                                'ok':ok[0],'cancel':cancel[0] if cancel else None})
            addresses=[n['value'] for n in nodes(tree) if n['role']=='AXTextField' and n['title'] in ('Bilah penelusuran dan alamat','Address and search bar')]
            result.append({'key':tree['key'],'frame':tuple(frame),'document':self.text(root,'AXDocument'),'address':addresses[0] if len(addresses)==1 else '', 'dialogs':dialogs})
        return result
    def answer(self,dialog,accept,prompt):
        if dialog['type']=='prompt' and accept:
            field=self.elements[dialog['field']]
            status=self.ax.AXUIElementSetAttributeValue(field,self.string('AXValue'),self.string(prompt))
            if status or self.text(field,'AXValue')!=prompt:raise RuntimeError('native_dialog_prompt_write_unconfirmed')
        key=dialog['ok'] if accept or dialog['type']=='alert' else dialog['cancel']
        if key is None:raise RuntimeError('native_dialog_button_unavailable')
        if self.ax.AXUIElementPerformAction(self.elements[key],self.string('AXPress')):raise RuntimeError('native_dialog_press_unconfirmed')


class NativeDialogs:
    def __init__(self,root,endpoint):
        self.root=Path(root).resolve();self.endpoint=endpoint;self.ax=None;self.process=None;self.bindings={}
    def _host(self):
        import psutil
        if __package__:
            from .plugin import chrome_executable,PERSONAL
        else:
            from plugin import chrome_executable,PERSONAL
        parsed=urlsplit(self.endpoint)
        if (self.root/'DevToolsActivePort').read_text().splitlines()!=[str(parsed.port),parsed.path]:raise RuntimeError('native_dialog_endpoint_changed')
        if self.process is None:
            matches=[]
            for proc in psutil.process_iter(['name','cmdline']):
                if proc.info['name']!='Google Chrome':continue
                args=proc.info['cmdline'] or []
                root=Path(next((v.split('=',1)[1] for v in args if v.startswith('--user-data-dir=')),str(PERSONAL))).resolve()
                if root==self.root and chrome_executable(proc.exe()) and any(x.status=='LISTEN' and x.laddr.port==parsed.port for x in proc.net_connections(kind='tcp')):matches.append(proc)
            if len(matches)!=1:raise RuntimeError('native_dialog_host_unavailable')
            self.process=(matches[0].pid,matches[0].create_time(),matches[0].exe())
        pid,started,exe=self.process;proc=psutil.Process(pid)
        if proc.create_time()!=started or proc.exe()!=exe:raise RuntimeError('native_dialog_host_changed')
        if self.ax is None:self.ax=NativeAX(pid)
    def scan(self,state,wire):
        self._host()
        infos=wire('Target.getTargets')['targetInfos']
        windows={t['targetId']:wire('Browser.getWindowForTarget',{'targetId':t['targetId']}) for t in infos if t.get('type')=='page' and t.get('browserContextId')==state.get('context')}
        assert self.ax is not None
        found=select_dialogs(state,infos,windows,self.ax.scan(),self.bindings)
        return found
    def answer(self,target,expected,params,state,wire):
        accept=params.get('accept')
        if not isinstance(accept,bool) or not isinstance(params.get('promptText',''),str):raise ValueError('native_dialog_explicit_decision_required')
        # A freshly exposed Chrome dialog may ignore AXPress with status zero.
        # Settle before the sole press, revalidating the exact binding each time.
        ready_at=time.monotonic()+1
        while True:
            fresh=self.scan(state,wire).get(target)
            if fresh is None or fresh!=expected:raise RuntimeError('native_dialog_identity_changed: no action sent')
            remaining=ready_at-time.monotonic()
            if remaining<=0:break
            time.sleep(min(.1,remaining))
        assert self.ax is not None
        try:
            self.ax.answer(fresh['dialog'],accept,params.get('promptText',''))
            # No retry after AXPress. Verify actual disappearance, not only AX status.
            deadline=time.monotonic()+1
            while True:
                remaining=[d for w in self.ax.scan() for d in w['dialogs'] if d['key']==fresh['dialog']['key']]
                if not remaining:return {}
                if time.monotonic()>=deadline:raise TimeoutError()
                time.sleep(.05)
        except Exception as exc:
            # After native action begins, readback errors cannot authorize another press.
            raise TimeoutError('native_dialog_answer_outcome_uncertain: do not replay') from exc
    def close(self):
        if self.ax:self.ax.clear();self.ax=None
