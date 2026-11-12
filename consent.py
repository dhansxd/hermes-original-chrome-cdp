"""Exact consent matching; automatic approval is scoped to a pending attach."""

class ConsentError(RuntimeError):
    def __init__(self,message,*,diagnostics=None):
        super().__init__(message)
        # Operator diagnostics never become part of the model-facing message.
        self.diagnostics=dict(diagnostics or {})


def select_sheet(sheets, baseline, hosts):
    unique={}
    for sheet in sheets:
        if button_for_dialog(sheet['name'],sheet['headings']):
            key=sheet['key']
            if key in unique and any(sheet[k]!=unique[key][k] for k in ('pid','name','headings','buttons')):
                raise ConsentError('consent_ambiguous: inconsistent sheet observation')
            if key in unique and sheet.get('owner') is not None and not sheet['owner'].same_sheet(sheet,unique[key]):
                raise ConsentError('consent_ambiguous: distinct sheets share an observation key')
            unique[key]=sheet
    candidates=list(unique.values())
    if not candidates:return None
    if len(candidates)!=1:raise ConsentError('consent_ambiguous: multiple debugging sheets')
    sheet=candidates[0]
    if sheet['key'] in baseline:raise ConsentError('consent_preexisting: will not approve an older request')
    if sheet['pid'] not in hosts:raise ConsentError('consent_host_uncorrelated')
    button=button_for_dialog(sheet['name'],sheet['headings'])
    if sheet['buttons'].count(button)!=1:raise ConsentError('consent_ambiguous_button')
    return sheet


def socket_matches(server, client, port):
    inbound=[pair for pair in server if pair[0][1]==port]
    return len(inbound)==1 and len(client)==1 and inbound[0]==tuple(reversed(client[0]))

import threading, time, json, plistlib, subprocess, os, math, logging
from pathlib import Path
from urllib.parse import urlsplit
from contextlib import contextmanager
from contextvars import ContextVar

_manual_consent = ContextVar('original_chrome_manual_consent', default=False)
_guard_state = threading.local()


@contextmanager
def manual_consent():
    """Operator diagnostic only: wait up to 60s, never press consent buttons."""
    token = _manual_consent.set(True)
    try:
        yield
    finally:
        _manual_consent.reset(token)

if __package__:
    from .cdp_peers import accepted_peers, register_accepted, socket_identity
else:
    from cdp_peers import accepted_peers, register_accepted, socket_identity


class ConsentTrace:
    """Counts and fixed outcome labels only: no endpoints, titles, IDs or text."""
    def __init__(self):
        self.started=time.monotonic()
        self.values={'phase':'queue','scan_calls':0,'scan_ms':0,'sheets_seen':0,
                     'debugging_sheets_seen':0,'hosts_bound_max':0,'host_candidates_seen':0,
                     'identity_checks':0,'identity_ms':0,'ax_windows_seen':0,
                     'ax_roots_without_sheet':0,'ax_depth_cutoffs':0,'scan_errors':0,'transient_ax_reads':0,
                     'press_attempted':False,'press_dispatched':False,'press_outcome':'not_attempted',
                     'geometry_resets':0,'drag_waits':0,
                     'first_sheet_ms':None,'press_ms':None,
                     'transport_phase':'not_started','http_status':None,'http_rejection':None,
                     'cleanup_outcome':'not_attempted','failure_code':None}
    def add(self,key,value=1):self.values[key]+=value
    def call(self,key,fn,*args,**kwargs):
        started=time.monotonic()
        try:return fn(*args,**kwargs)
        finally:self.values[key]+=max(0,round((time.monotonic()-started)*1000))
    def observe(self,sheets,hosts=()):
        self.add('sheets_seen',len(sheets))
        self.add('debugging_sheets_seen',sum(bool(button_for_dialog(s['name'],s['headings'])) for s in sheets))
        self.values['hosts_bound_max']=max(self.values['hosts_bound_max'],len(hosts))
        return sheets
    def elapsed_ms(self):return max(0,round((time.monotonic()-self.started)*1000))
    def snapshot(self):
        return dict(self.values,elapsed_ms=self.elapsed_ms())
    def failure(self,exc):
        if not exc.diagnostics:
            self.values['failure_code']=failure_code(exc)
            exc.diagnostics=self.snapshot()
            logging.getLogger(__name__).warning('Chrome consent diagnostics: %s',json.dumps(exc.diagnostics,sort_keys=True))
        return exc


def failure_code(exc):
    # Only fixed code prefixes may enter operator diagnostics. Never include
    # arbitrary transport messages, endpoints, or UI text from an exception.
    allowed={'consent_ambiguous','consent_preexisting','consent_host_uncorrelated',
             'consent_ambiguous_button','consent_deadline','consent_timeout_invalid',
             'consent_endpoint','consent_ax_timeout_setup','consent_ax_read',
             'consent_ax_tree_depth','consent_sheet_unbound','consent_changed_before_press',
             'consent_press_not_confirmed','consent_accessibility','consent_cancel_not_owned',
             'consent_cancel_identity_changed','consent_cancel_not_dismissed',
             'consent_press_already_attempted','consent_attach_uncorrelated',
             'consent_geometry_unavailable','consent_geometry_changed_before_press'}
    message=str(exc)
    for prefix in ('consent_attach_failed: ','consent_preflight_failed: '):
        if message.startswith(prefix):message=message[len(prefix):]
    code=message.partition(':')[0]
    return code if code in allowed else 'unknown'


def observed(backend,fn,trace):
    if isinstance(backend,MacConsent):return fn()
    trace.add('scan_calls')
    return trace.observe(trace.call('scan_ms',fn))


def remaining(deadline,phase,cap=None):
    value=deadline-time.monotonic()
    if value<=0:raise ConsentError('consent_deadline: phase='+phase+'; no action replay')
    return min(value,cap) if cap is not None else value


@contextmanager
def consent_guard(data_root,timeout=20,*,deadline=None):
    # Chrome can put another client's debugging sheet on our owned window.
    # Serialize only handshake/cancellation and target close, never page work.
    import fcntl,hashlib
    root=str(Path(data_root).resolve());pid=os.getpid()
    if getattr(_guard_state,'pid',None)!=pid:
        _guard_state.pid=pid;_guard_state.held={}
    held=_guard_state.held
    deadline=time.monotonic()+timeout if deadline is None else deadline
    remaining(deadline,'queue')
    if root in held:
        # The outer scope owns the flock until it exits. Only this OS thread
        # and PID can reuse it; another thread/process still takes the lock.
        yield
        return
    folder=Path.home()/'.cache/original-chrome-default';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    name=hashlib.sha256(root.encode()).hexdigest()[:20]+'.attach.lock'
    with open(folder/name,'a')as lock:
        os.chmod(folder/name,0o600)
        while True:
            remaining(deadline,'queue')
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                time.sleep(remaining(deadline,'queue',.05))
        held[root]=lock
        try:yield
        finally:held.pop(root,None)


def connect_with_consent(endpoint, data_root, connect, *, backend=None, timeout=15):
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
        raise ConsentError('consent_timeout_invalid')
    if _manual_consent.get():timeout=max(timeout,60)
    deadline=time.monotonic()+timeout;trace=ConsentTrace()
    trace.values['consent_mode']='manual' if _manual_consent.get() else 'automatic'
    try:
        if backend is not None and not isinstance(backend,MacConsent):
            return _connect_with_consent(endpoint,data_root,connect,backend=backend,timeout=timeout,deadline=deadline,trace=trace)
        with consent_guard(data_root,timeout,deadline=deadline):
            return _connect_with_consent(endpoint,data_root,connect,backend=backend,timeout=timeout,deadline=deadline,trace=trace)
    except ConsentError as exc:raise trace.failure(exc)

def _connect_with_consent(endpoint, data_root, connect, *, backend=None, timeout=15,deadline=None,trace=None):
    trace=trace or ConsentTrace()
    try:return _connect_attempt(endpoint,data_root,connect,backend=backend,timeout=timeout,deadline=deadline,trace=trace)
    except ConsentError as exc:raise trace.failure(exc)


def _connect_attempt(endpoint, data_root, connect, *, backend=None, timeout=15,deadline=None,trace):
    deadline=time.monotonic()+timeout if deadline is None else deadline
    trace.values['phase']='preflight'
    url=urlsplit(endpoint)
    if url.scheme!='ws' or url.hostname not in {'127.0.0.1','localhost','::1'} or not url.port or url.username or not url.path.startswith('/devtools/browser/'):
        raise ConsentError('consent_endpoint: expected local browser WebSocket')
    backend=backend or MacConsent(data_root,url.port,url.path)
    if isinstance(backend,MacConsent):backend.deadline=deadline;backend.trace=trace
    baseline=set();issue=None
    # Establish a readable baseline before initiating another consent request.
    baseline_deadline=min(deadline,time.monotonic()+2)
    while True:
        try:
            remaining(deadline,'preflight')
            prepare=getattr(backend,'prepare',None)
            sheets=observed(backend,prepare or backend.scan,trace)
            if any(button_for_dialog(s['name'],s['headings'])for s in sheets):raise ConsentError('consent_preexisting: unresolved debugging prompt; no new connection opened')
            baseline={s['key'] for s in sheets}
            break
        except Exception as exc:
            if str(exc) in {'consent_ax_read:-25202','consent_ax_read:-25204'} and time.monotonic()<baseline_deadline:
                time.sleep(remaining(baseline_deadline,'preflight',.05));continue
            raise ConsentError('consent_preflight_failed: '+str(exc)) from None
    done=threading.Event();abandoned=threading.Event();result={};raw_socket=None;success=False;ws_closed=False
    def attach():
        nonlocal raw_socket
        try:
            kwargs:dict={'open_timeout':remaining(deadline,'handshake')}
            if isinstance(backend,MacConsent):
                import socket
                trace.values['transport_phase']='socket'
                raw_socket=socket.create_connection((url.hostname,url.port),timeout=remaining(deadline,'socket',3))
                if abandoned.is_set():raw_socket.close();return
                backend.pending_port=raw_socket.getsockname()[1]
                # Dial timeout is not a receive deadline for the retained observer.
                raw_socket.settimeout(None)
                kwargs.update(sock=raw_socket,proxy=None,open_timeout=remaining(deadline,'handshake'),close_timeout=1)
            trace.values['transport_phase']='handshake'
            ws=connect(endpoint,**kwargs)
            trace.values['transport_phase']='complete'
            if abandoned.is_set():ws.close()
            else:result['ws']=ws
        except Exception as exc:
            trace.values['transport_phase']='failed'
            response=getattr(exc,'response',None)
            status=getattr(response,'status_code',None)
            if type(status) is int:
                trace.values['http_status']=status
                body=getattr(response,'body',b'')
                # Classify only fixed Chrome responses; never retain arbitrary response text.
                trace.values['http_rejection']=('chrome_connection_rejected' if body==b'Connection rejected'
                    else 'origin_rejected' if isinstance(body,(bytes,bytearray)) and body.startswith(b'Rejected an incoming WebSocket connection from the ')
                    else 'other')
            result['error']=str(exc)
        finally:done.set()
    thread=threading.Thread(target=attach,daemon=True);thread.start()
    pressed=False;trace.values['phase']='handshake';issue_phase=None
    try:
        while not done.wait(.05) and time.monotonic()<deadline:
            if pressed or (issue and not issue.startswith('consent_attach_uncorrelated:')):continue
            try:
                trace.values['phase']='observation'
                sheets=observed(backend,backend.scan,trace)
                hosts=backend.hosts()
                trace.values['hosts_bound_max']=max(trace.values['hosts_bound_max'],len(hosts))
                sheet=select_sheet(sheets,baseline,hosts)
                if sheet:
                    if trace.values['first_sheet_ms'] is None:
                        trace.values['first_sheet_ms']=trace.elapsed_ms()
                    trace.values['phase']='correlation'
                    if not backend.correlate():
                        issue='consent_attach_uncorrelated: cannot prove sole local connection'
                        issue_phase='correlation'
                        continue
                    issue=None;issue_phase=None
                    if _manual_consent.get():
                        # Observe the same pending attach, but never claim or
                        # press its sheet. No automatic Cancel in cleanup either.
                        trace.values['phase']='awaiting_user'
                        continue
                    if not done.is_set():
                        # Native AX records dispatch before the action. Unknown
                        # backends remain terminal once press has been entered.
                        pressed=True
                        trace.values.update(phase='press',press_attempted=True,press_outcome='validating')
                        if isinstance(backend,MacConsent):backend.claim(sheet)
                        backend.press(sheet,pending=lambda:not done.is_set() and time.monotonic()<deadline)
                        if trace.values['press_outcome']=='validating':trace.values['press_outcome']='returned_without_receipt'
                trace.values['phase']='handshake'
            except Exception as exc:
                # Discard invalid/busy AX snapshots; scan rebuilds host/window refs.
                # Retry observation only within this same pending handshake.
                if (str(exc) in {'consent_ax_read:-25202','consent_ax_read:-25204','consent_geometry_changed_before_press'}
                    and (not pressed or (isinstance(backend,MacConsent)
                                         and trace.values.get('press_dispatched') is False))):
                    # Native pre-action reads can become stale while a dialog
                    # settles. Drop the old claim, then observe this same pending
                    # connection again. A dispatched/unknown action is terminal.
                    if pressed:
                        backend.release_claim();pressed=False
                        trace.values['press_outcome']='reobserving'
                    issue=None;issue_phase=None
                    trace.add('transient_ax_reads');continue
                issue=str(exc);issue_phase=trace.values['phase']
                if pressed and trace.values['press_outcome']=='validating':trace.values['press_outcome']='rejected_before_dispatch'
        if 'ws' in result:
            ws=result['ws']
            trace.values['phase']='registration'
            remaining(deadline,'registration')
            if isinstance(backend,MacConsent):
                try:ws=register_accepted(ws,data_root,url.port,url.path)
                except BaseException:
                    # Raw TCP close doesn't unblock a full library receive queue.
                    try:ws.close();ws_closed=True
                    except Exception:pass  # Preserve the registration failure.
                    raise
            success=True;return ws
        trace.values['phase']=issue_phase or 'handshake'
        raise ConsentError('consent_attach_failed: '+(issue or result.get('error','consent_deadline: phase=handshake; no action replay')))
    finally:
        abandoned.set()
        if not success and raw_socket is not None:
            import socket
            try:raw_socket.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            raw_socket.close()
        if not success and 'ws' in result and not ws_closed:
            try:result['ws'].close()
            except Exception:pass
        thread.join(timeout=max(0,min(.1,deadline-time.monotonic())))
        if not success and isinstance(backend,MacConsent):
            try:backend.cleanup_abandoned(baseline)
            except Exception:pass  # Preserve original attach error; next preflight still gates.
        if isinstance(backend,MacConsent):backend.release_claim()



class AX:
    """Small direct AX reader: never requests/changes OS permissions or focus."""
    def __init__(self):
        import ctypes as c
        self.c=c;self.refs=[];self.deadline=None;self.trace=None
        self.cf=c.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.ax=c.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
        def sig(lib,name,restype,args):
            fn=getattr(lib,name);fn.restype=restype;fn.argtypes=args;return fn
        p=c.c_void_p;i=c.c_long
        sig(self.ax,'AXIsProcessTrusted',c.c_bool,[])
        sig(self.ax,'AXUIElementCreateApplication',p,[c.c_int])
        sig(self.ax,'AXUIElementCopyAttributeValue',c.c_int,[p,p,c.POINTER(p)])
        sig(self.ax,'AXUIElementPerformAction',c.c_int,[p,p])
        sig(self.ax,'AXUIElementGetPid',c.c_int,[p,c.POINTER(c.c_int)])
        sig(self.ax,'AXUIElementSetMessagingTimeout',c.c_int,[p,c.c_float])
        sig(self.ax,'AXValueGetValue',c.c_bool,[p,c.c_int,p])
        class Pair(c.Structure):
            _fields_=[('first',c.c_double),('second',c.c_double)]
        self._pair_type=Pair
        sig(self.cf,'CFStringCreateWithCString',p,[p,c.c_char_p,c.c_uint])
        sig(self.cf,'CFStringGetCString',c.c_bool,[p,c.c_char_p,i,c.c_uint])
        sig(self.cf,'CFArrayGetCount',i,[p]);sig(self.cf,'CFArrayGetValueAtIndex',p,[p,i])
        sig(self.cf,'CFRelease',None,[p]);sig(self.cf,'CFHash',c.c_ulong,[p])
        sig(self.cf,'CFRetain',p,[p]);sig(self.cf,'CFEqual',c.c_bool,[p,p])
    def limit(self,node,cap=.25):
        timeout=cap if getattr(self,'deadline',None) is None else remaining(self.deadline,'accessibility',cap)
        status=self.ax.AXUIElementSetMessagingTimeout(node,timeout)
        if status:raise ConsentError('consent_ax_timeout_setup:'+str(status))
    def trusted(self):return self.ax.AXIsProcessTrusted()
    def string(self,s):
        value=self.cf.CFStringCreateWithCString(None,s.encode(),0x08000100);self.refs.append(value);return value
    def attr(self,node,name):
        self.limit(node)
        value=self.c.c_void_p()
        err=self.ax.AXUIElementCopyAttributeValue(node,self.string(name),self.c.byref(value))
        if err in (-25205,-25212):return None
        if err:raise ConsentError('consent_ax_read:'+str(err))
        if value.value:self.refs.append(value.value)
        return value.value
    def text(self,node,name):
        try:value=self.attr(node,name)
        except ConsentError as exc:
            if str(exc)=='consent_ax_read:-25200' and name in {'AXTitle','AXDescription','AXValue'}:return ''
            raise
        if not value:return ''
        buf=self.c.create_string_buffer(8192)
        return buf.value.decode() if self.cf.CFStringGetCString(value,buf,len(buf),0x08000100) else ''
    def children(self,node):
        value=self.attr(node,'AXChildren')
        return [self.cf.CFArrayGetValueAtIndex(value,i) for i in range(self.cf.CFArrayGetCount(value))] if value else []
    def geometry(self,node):
        result=[]
        for name,kind in (('AXPosition',1),('AXSize',2)):
            value=self.attr(node,name);pair=self._pair_type()
            if not value or not self.ax.AXValueGetValue(value,kind,self.c.byref(pair)):
                raise ConsentError('consent_geometry_unavailable')
            result.extend((pair.first,pair.second))
        if not all(math.isfinite(v) for v in result) or result[2]<=0 or result[3]<=0:
            raise ConsentError('consent_geometry_unavailable')
        return tuple(result)
    def geometry_state(self,sheet):
        # Chromium resets input protection on window bounds changes. Include
        # other windows of the same host process, not just the retained sheet.
        start=len(self.refs)
        try:
            app=self.ax.AXUIElementCreateApplication(sheet['pid']);self.refs.append(app)
            values=self.attr(app,'AXWindows')
            windows=[self.cf.CFArrayGetValueAtIndex(values,i) for i in range(self.cf.CFArrayGetCount(values))] if values else []
            frames=tuple(sorted((int(self.cf.CFHash(w)),self.geometry(w)) for w in windows
                                if self.text(w,'AXSubrole')=='AXStandardWindow'))
            return frames,self.geometry(sheet['window']),self.geometry(sheet['sheet'])
        finally:
            for ref in reversed(self.refs[start:]):self.cf.CFRelease(ref)
            del self.refs[start:]
    def nodes(self,node,depth=0):
        if depth>20:raise ConsentError('consent_ax_tree_depth')
        yield node
        for child in self.children(node):yield from self.nodes(child,depth+1)
    def clear(self):
        for value in reversed(self.refs):self.cf.CFRelease(value)
        self.refs=[]
    def sheets(self,pid):
        app=self.ax.AXUIElementCreateApplication(pid);self.refs.append(app)
        result=[]
        # Only walk window descendants; do not recursively enumerate webpage DOMs.
        windows=self.attr(app,'AXWindows')
        roots=[self.cf.CFArrayGetValueAtIndex(windows,i) for i in range(self.cf.CFArrayGetCount(windows))] if windows else []
        trace=getattr(self,'trace',None)
        if isinstance(trace,ConsentTrace):trace.add('ax_windows_seen',len(roots))
        def find(node,depth=0):
            if depth>5:
                if isinstance(trace,ConsentTrace):trace.add('ax_depth_cutoffs')
                return
            role=self.text(node,'AXRole')
            if role=='AXSheet':yield node;return
            if role in {'AXWebArea','AXScrollArea'}:return
            for child in self.children(node):yield from find(child,depth+1)
        for root in roots:
            found=list(find(root))
            if not found and isinstance(trace,ConsentTrace):trace.add('ax_roots_without_sheet')
            for sheet in found:
                result.append(self.describe_sheet(sheet,pid,root))
        return result
    def describe_sheet(self,sheet,pid,window):
        headings=[];buttons=[];elements={}
        for node in self.nodes(sheet):
            role=self.text(node,'AXRole')
            label=self.text(node,'AXTitle') or self.text(node,'AXDescription')
            if role=='AXHeading':headings.append(label or self.text(node,'AXValue'))
            if role=='AXButton':buttons.append(label);elements[label]=node
        return {'key':(pid,self.cf.CFHash(sheet)),'pid':pid,'name':self.text(sheet,'AXTitle'),
                'headings':headings,'buttons':buttons,'elements':elements,
                'sheet':sheet,'window':window,'owner':self}
    @contextmanager
    def pin(self,sheet):
        # CFHash is only an index, never proof of object identity. Keep the
        # selected objects alive across scan.clear(), then compare with CFEqual.
        if sheet.get('owner') is not self:raise ConsentError('consent_sheet_unbound')
        label=button_for_dialog(sheet['name'],sheet['headings'])
        if not label or sheet['buttons'].count(label)!=1:raise ConsentError('consent_ambiguous_button')
        nodes=[sheet['window'],sheet['sheet'],sheet['elements'][label]]
        for node in nodes:self.cf.CFRetain(node)
        try:yield sheet
        finally:
            for node in reversed(nodes):self.cf.CFRelease(node)

    def same_sheet(self,left,right):
        label=button_for_dialog(left['name'],left['headings'])
        return (left.get('owner') is self and right.get('owner') is self
                and left['pid']==right['pid'] and left.get('host')==right.get('host')
                and label==button_for_dialog(right['name'],right['headings'])
                and right['buttons'].count(label)==1
                and all(self.cf.CFEqual(left[key],right[key]) for key in ('window','sheet'))
                and self.cf.CFEqual(left['elements'][label],right['elements'][label]))

    def within(self,node,ancestor):
        for _ in range(20):
            if self.cf.CFEqual(node,ancestor):return True
            node=self.attr(node,'AXParent')
            if not node:return False
        return False

    def press(self,sheet,*,pending=lambda:True,label=None):
        # The action uses the exact retained AX button, never a new window/title
        # search in another process. Apple's timeout is per object, so set it on
        # every object read and on this exact button before the single AXPress.
        wanted=button_for_dialog(sheet['name'],sheet['headings'])
        label=label or wanted
        trace=getattr(self,'trace',None)
        outcome='press_outcome' if label==wanted else 'cleanup_outcome'
        if isinstance(trace,ConsentTrace):trace.values[outcome]='validating'
        if (sheet.get('owner') is not self or not wanted or sheet['buttons'].count(label)!=1
            or label not in {wanted,'Cancel' if wanted=='Allow' else 'Batal'}):
            raise ConsentError('consent_sheet_unbound')
        button=sheet['elements'][label]
        fresh=self.describe_sheet(sheet['sheet'],sheet['pid'],sheet['window'])
        if (button_for_dialog(fresh['name'],fresh['headings'])!=wanted
            or fresh['buttons'].count(label)!=1 or not self.cf.CFEqual(button,fresh['elements'][label])):
            raise ConsentError('consent_changed_before_press')
        for node,role in ((sheet['window'],'AXWindow'),(sheet['sheet'],'AXSheet'),(button,'AXButton')):
            if self.text(node,'AXRole')!=role:raise ConsentError('consent_changed_before_press')
            self.limit(node)
            pid=self.c.c_int()
            if self.ax.AXUIElementGetPid(node,self.c.byref(pid)) or pid.value!=sheet['pid']:
                raise ConsentError('consent_changed_before_press')
        actual=self.text(button,'AXTitle') or self.text(button,'AXDescription')
        if actual!=label or not self.within(button,sheet['sheet']) or not self.within(sheet['sheet'],sheet['window']):
            raise ConsentError('consent_changed_before_press')
        if not pending():
            if isinstance(trace,ConsentTrace):trace.values[outcome]='pending_ended'
            return False
        self.limit(button,1)
        if isinstance(trace,ConsentTrace):
            trace.values[outcome]='requested'
            if label==wanted:
                trace.values['press_dispatched']=True
                trace.values['press_ms']=trace.elapsed_ms()
        status=self.ax.AXUIElementPerformAction(button,self.string('AXPress'))
        if isinstance(trace,ConsentTrace):
            trace.values[outcome]='acknowledged' if not status else 'unconfirmed'
            trace.values['press_ax_status' if label==wanted else 'cleanup_ax_status']=int(status)
        if status:
            raise ConsentError('consent_press_not_confirmed: ax_status='+str(status)+'; press outcome unknown; no retry')
        return True


class MacConsent:
    def __init__(self,root,port,path=None):
        self.root=Path(root).resolve();self.port=port;self.path=path;self.ax=None;self.processes={};self.pending_port: int | None=None
        self.deadline=None;self._claim=None;self._claim_context=None;self.trace=None
    def budget(self,phase,cap=2):
        return cap if self.deadline is None else remaining(self.deadline,phase,cap)
    def endpoint_matches(self):
        try:
            lines=(self.root/'DevToolsActivePort').read_text().splitlines()
            return len(lines)==2 and lines==[str(self.port),self.path]
        except OSError:return False
    def hosts(self):return {pid for pid,h in self.processes.items() if h['bound']}
    def scan(self):
        if self.trace is None:return self._scan()
        self.trace.add('scan_calls')
        try:sheets=self.trace.call('scan_ms',self._scan)
        except Exception:
            self.trace.add('scan_errors');raise
        return self.trace.observe(sheets,self.hosts())
    def identity(self,fn,*args,**kwargs):
        if self.trace is None:return fn(*args,**kwargs)
        self.trace.add('identity_checks')
        return self.trace.call('identity_ms',fn,*args,**kwargs)
    def _scan(self):
        import psutil,hashlib
        self.budget('scan')
        if self.ax is None:self.ax=AX()
        if not self.ax.trusted():raise ConsentError('consent_accessibility: grant Accessibility manually; no permission change attempted')
        self.ax.deadline=self.deadline;self.ax.trace=self.trace
        self.ax.clear();self.processes={};sheets=[]
        for process in psutil.process_iter():
            self.budget('scan')
            try:
                info=process.as_dict(attrs=['pid','exe','create_time','cmdline'])
                exe=Path(info['exe'] or '')
                if exe.name not in {'Google Chrome','app_mode_loader'}:continue
                if self.trace is not None:self.trace.add('host_candidates_seen')
                plist=plistlib.loads((exe.parents[1]/'Info.plist').read_bytes())
                kind=self.identity(host_identity,str(exe),plist,self.root,deadline=self.deadline)
                if not kind:continue
                if kind=='main':
                    check=self.identity(subprocess.run,['/usr/bin/codesign','--verify','-R','=anchor apple generic and identifier "com.google.Chrome" and certificate leaf[subject.OU] = "EQHXZ8M8AV"',str(exe.parents[2])],capture_output=True,timeout=self.budget('host_identity'))
                    if check.returncode:continue
                    args=info['cmdline'] or []
                    data=next((x.split('=',1)[1] for x in args if x.startswith('--user-data-dir=')),str(Path.home()/'Library/Application Support/Google/Chrome'))
                    bound=Path(data).resolve()==self.root
                else:
                    if not self.identity(verify_pwa_host,exe,plist,self.root,timeout=self.budget('host_identity')):continue
                    bound=True
                self.processes[process.pid]={'started':info['create_time'],'exe':str(exe),'bound':bound,'kind':kind}
                observed=self.ax.sheets(process.pid)
                for sheet in observed:sheet['host']=dict(self.processes[process.pid])
                sheets.extend(observed)
            except (psutil.Error,OSError,ValueError,subprocess.SubprocessError):continue
        return sheets
    def no_peers(self):
        import psutil
        if not self.endpoint_matches():return False
        owners=[];settled=accepted_peers(self.root,self.port,self.path)
        for pid,h in self.processes.items():
            if not h['bound']or h['kind']!='main':continue
            p=psutil.Process(pid)
            if p.create_time()!=h['started']or p.exe()!=h['exe']:return False
            conns=p.net_connections(kind='tcp')
            if any(c.status=='LISTEN'and c.laddr.port==self.port for c in conns):
                owners.append(pid)
                if any(c.raddr and c.laddr.port==self.port and c.status=='ESTABLISHED' and tuple(reversed(socket_identity(c))) not in settled for c in conns):return False
        return len(owners)==1
    def cancel_sheet(self,sheet,*,orphan=False):
        # An empty peer list cannot attribute an old sheet to us. Cancellation
        # requires the exact retained sheet claimed during this handshake.
        if self._claim is None or sheet is not self._claim:raise ConsentError('consent_cancel_not_owned')
        self.budget('cleanup')
        with self.ax.pin(sheet):
            fresh=select_sheet(self.scan(),set(),self.hosts())
            if not fresh:return
            if not self.ax.same_sheet(sheet,fresh):raise ConsentError('consent_cancel_identity_changed')
            if not self.no_peers():raise ConsentError('consent_preexisting: another connection active')
            label='Batal'if button_for_dialog(fresh['name'],fresh['headings'])=='Izinkan'else'Cancel'
            def safe():
                self.budget('cleanup')
                return self.no_peers()
            if not self.ax.press(fresh,pending=safe,label=label):raise ConsentError('consent_cancel_identity_changed')
            deadline=min(time.monotonic()+.75,self.deadline or float('inf'))
            while True:
                # A hash match alone is not enough to bind a replacement sheet.
                if not any(self.ax.same_sheet(sheet,s) for s in self.scan()):return
                if time.monotonic()>=deadline:raise ConsentError('consent_cancel_not_dismissed')
                time.sleep(remaining(deadline,'cleanup',.05))
    def claim(self,sheet):
        if self._claim is not None:raise ConsentError('consent_press_already_attempted')
        context=self.ax.pin(sheet)
        self._claim=context.__enter__()
        self._claim_context=context
    def release_claim(self):
        if self._claim_context is not None:self._claim_context.__exit__(None,None,None)
        self._claim_context=None;self._claim=None
    def cleanup_abandoned(self,baseline):
        if self._claim is None or self._claim['key'] in baseline:
            if self.trace is not None:self.trace.values['cleanup_outcome']='unclaimed'
            return
        # Main action/handshake time is exhausted independently. After the raw
        # socket is stopped, allow at most one extra second solely to cancel
        # this retained, attributed sheet. Never reopen or approve a connection.
        prior=self.deadline
        prior_ax=self.ax.deadline
        self.deadline=time.monotonic()+1
        self.ax.deadline=self.deadline
        try:self.cancel_sheet(self._claim,orphan=True)
        except Exception:
            if self.trace is not None and self.trace.values['cleanup_outcome'] in {'not_attempted','validating'}:
                self.trace.values['cleanup_outcome']='rejected_before_dispatch'
            raise
        finally:
            self.deadline=prior
            self.ax.deadline=prior_ax
    def prepare(self):
        sheets=self.scan()
        if any(button_for_dialog(s['name'],s['headings']) for s in sheets):
            raise ConsentError('consent_preexisting: unresolved debugging prompt; no new connection opened or cancellation attempted')
        return sheets
    def correlate(self):
        import psutil
        if not self.endpoint_matches():return False
        # Consent authorizes this browser connection, not a profile/window.
        # Saved profile count is unrelated; binding is checked after attach.
        # Local TCP reverse tuple must identify this worker as the sole peer.
        servers=[];owners=[]
        settled=accepted_peers(self.root,self.port,self.path)
        for pid,h in self.processes.items():
            if not h['bound'] or h['kind']!='main':continue
            p=psutil.Process(pid)
            if p.create_time()!=h['started'] or p.exe()!=h['exe']:return False
            conns=p.net_connections(kind='tcp')
            if any(c.status=='LISTEN' and c.laddr.port==self.port and c.laddr.ip in {'127.0.0.1','::1'} for c in conns):
                owners.append(pid)
                servers.extend(socket_identity(c) for c in conns if c.raddr and c.status=='ESTABLISHED' and c.laddr.port==self.port and c.raddr.ip in {'127.0.0.1','::1'})
        client=[socket_identity(c) for c in psutil.Process(os.getpid()).net_connections(kind='tcp') if c.raddr and c.status=='ESTABLISHED' and c.raddr.port==self.port and c.raddr.ip in {'127.0.0.1','::1'}]
        if self.pending_port is not None:
            client=[c for c in client if c[0][1]==self.pending_port]
            servers=[s for s in servers if tuple(reversed(s)) not in settled]
        return len(owners)==1 and socket_matches(servers,client,self.port)
    def press(self,sheet,*,pending):
        # Re-read host identity/sheets/socket at action time; no title-only click.
        if not pending():return
        with self.ax.pin(sheet):
            # Wait for stable Chrome geometry before the exact AX action.
            # Global mouse state also includes input in unrelated applications
            # and cannot establish whether this retained dialog is ready.
            geometry=self.ax.geometry_state(sheet)
            settled_at=time.monotonic()+1
            if self.trace is not None:self.trace.values['phase']='settling'
            while True:
                if not pending():
                    if self.trace is not None:self.trace.values['press_outcome']='pending_ended'
                    return
                current=self.ax.geometry_state(sheet)
                if current!=geometry:
                    if self.trace is not None:
                        self.trace.add('geometry_resets')
                    geometry=current;settled_at=time.monotonic()+1
                budget=self.budget('settling',.05)
                pause=min(budget,settled_at-time.monotonic())
                if pause<=0:break
                time.sleep(pause)
            if self.trace is not None:self.trace.values['phase']='press'
            fresh=select_sheet(self.scan(),set(),self.hosts())
            if not fresh or not self.ax.same_sheet(sheet,fresh) or not self.correlate():
                raise ConsentError('consent_changed_before_press')
            def safe():
                self.budget('press')
                if self.ax.geometry_state(fresh)!=geometry:
                    raise ConsentError('consent_geometry_changed_before_press')
                return pending() and self.correlate()
            self.ax.press(fresh,pending=safe)


CHROME=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')


def verify_pwa_host(exe,plist,root,*,apps_root=None,timeout=2):
    exe=Path(exe).resolve()
    apps_root=Path(apps_root or Path.home()/'Applications/Chrome Apps.localized').resolve()
    if host_identity(str(exe),plist,root)!='pwa':return False
    try:
        exe.relative_to(apps_root)
        checked=subprocess.run(['/usr/bin/codesign','--verify','--strict',str(exe.parents[2])],capture_output=True,timeout=timeout)
        return checked.returncode==0
    except (ValueError,OSError,subprocess.SubprocessError):return False


def verify_chrome_executable(executable,*,deadline=None):
    """Accept only stable Google-signed macOS signing clones, including running pre-update versions."""
    import re,stat
    path=Path(executable)
    if path==CHROME:return True
    if not re.fullmatch(r'/private/var/folders/[^/]+/[^/]+/X/com\.google\.Chrome\.code_sign_clone/code_sign_clone\.[A-Za-z0-9_-]+/Google Chrome\.app\.bundle/Contents/MacOS/Google Chrome',str(path)):return False
    try:
        paths=(path,)
        before=[p.stat() for p in paths]
        if not all(stat.S_ISREG(s.st_mode) for s in before):return False
        requirement='anchor apple generic and identifier "com.google.Chrome" and certificate leaf[subject.OU] = "EQHXZ8M8AV"'
        for p in paths:
            timeout=2 if deadline is None else remaining(deadline,'host_identity',2)
            check=subprocess.run(['/usr/bin/codesign','--verify','--strict','-R='+requirement,str(p.parents[2])],capture_output=True,timeout=timeout)
            if check.returncode:return False
        return all((p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns)==(s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns) for p,s in zip(paths,before))
    except (OSError,subprocess.SubprocessError):return False


def host_identity(executable, plist, root,*,deadline=None):
    path=Path(executable)
    if plist.get('CFBundleIdentifier')=='com.google.Chrome' and plist.get('CFBundleExecutable')=='Google Chrome' and verify_chrome_executable(executable,deadline=deadline):return 'main'
    if path.name!='app_mode_loader' or path.parent.name!='MacOS' or path.parent.parent.name!='Contents' or path.parents[2].suffix!='.app':return None
    shortcut=plist.get('CrAppModeShortcutID')
    if not shortcut or plist.get('CFBundleExecutable')!='app_mode_loader' or plist.get('CrBundleIdentifier')!='com.google.Chrome' or plist.get('CFBundleIdentifier')!='com.google.Chrome.app.'+shortcut:return None
    # Consent host belongs to the browser data root; it need not prove the
    # work target's Default profile. Chrome also uses root/-/Web Applications.
    data=Path(plist.get('CrAppModeUserDataDir','/'))
    if data in {Path(root)/part/'Web Applications'/('_crx_'+shortcut) for part in ('Default','-')}:return 'pwa'
    return None


PAIRS={'Allow remote debugging?':'Allow','Izinkan proses debug jarak jauh?':'Izinkan'}

def button_for_dialog(name, headings):
    labels=({name} | set(headings)) & PAIRS.keys()
    return PAIRS[next(iter(labels))] if len(labels)==1 else None
