"""Exact consent matching; automatic approval is scoped to a pending attach."""

class ConsentError(RuntimeError):pass


def select_sheet(sheets, baseline, hosts):
    unique={}
    for sheet in sheets:
        if button_for_dialog(sheet['name'],sheet['headings']):
            key=sheet['key']
            if key in unique and any(sheet[k]!=unique[key][k] for k in ('pid','name','headings','buttons')):
                raise ConsentError('consent_ambiguous: inconsistent sheet observation')
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

import threading, time, json, plistlib, subprocess, os
from pathlib import Path
from urllib.parse import urlsplit
from contextlib import contextmanager
if __package__:
    from .cdp_peers import accepted_peers, register_accepted, socket_identity
else:
    from cdp_peers import accepted_peers, register_accepted, socket_identity


@contextmanager
def consent_guard(data_root,timeout=20):
    # Chrome can put another client's debugging sheet on our owned window.
    # Serialize only handshake/cancellation and target close, never page work.
    import fcntl,hashlib
    folder=Path.home()/'.cache/original-chrome-default';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    name=hashlib.sha256(str(Path(data_root).resolve()).encode()).hexdigest()[:20]+'.attach.lock'
    with open(folder/name,'a')as lock:
        os.chmod(folder/name,0o600);deadline=time.monotonic()+timeout
        while True:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise ConsentError('consent_attach_busy: no connection opened')
                time.sleep(.05)
        yield


def connect_with_consent(endpoint, data_root, connect, *, backend=None, timeout=15):
    if backend is not None and not isinstance(backend,MacConsent):
        return _connect_with_consent(endpoint,data_root,connect,backend=backend,timeout=timeout)
    with consent_guard(data_root,timeout):
        return _connect_with_consent(endpoint,data_root,connect,backend=backend,timeout=timeout)

def _connect_with_consent(endpoint, data_root, connect, *, backend=None, timeout=15):
    url=urlsplit(endpoint)
    if url.scheme!='ws' or url.hostname not in {'127.0.0.1','localhost','::1'} or not url.port or url.username or not url.path.startswith('/devtools/browser/'):
        raise ConsentError('consent_endpoint: expected local browser WebSocket')
    backend=backend or MacConsent(data_root,url.port,url.path)
    baseline=set();issue=None
    # Establish a readable baseline before initiating another consent request.
    baseline_deadline=time.monotonic()+min(2,timeout)
    while True:
        try:
            prepare=getattr(backend,'prepare',None)
            sheets=prepare()if prepare else backend.scan()
            if any(button_for_dialog(s['name'],s['headings'])for s in sheets):raise ConsentError('consent_preexisting: unresolved debugging prompt; no new connection opened')
            baseline={s['key'] for s in sheets}
            break
        except Exception as exc:
            if str(exc) in {'consent_ax_read:-25202','consent_ax_read:-25204'} and time.monotonic()<baseline_deadline:
                time.sleep(.05);continue
            raise ConsentError('consent_preflight_failed: '+str(exc)) from None
    done=threading.Event();abandoned=threading.Event();result={};raw_socket=None;success=False
    def attach():
        nonlocal raw_socket
        try:
            kwargs:dict={'open_timeout':timeout}
            if isinstance(backend,MacConsent):
                import socket
                raw_socket=socket.create_connection((url.hostname,url.port),timeout=min(3,timeout))
                if abandoned.is_set():raw_socket.close();return
                backend.pending_port=raw_socket.getsockname()[1]
                # Dial timeout is not a receive deadline for the retained observer.
                raw_socket.settimeout(None)
                kwargs.update(sock=raw_socket,proxy=None)
            ws=connect(endpoint,**kwargs)
            if abandoned.is_set():ws.close()
            else:result['ws']=ws
        except Exception as exc:result['error']=str(exc)
        finally:done.set()
    thread=threading.Thread(target=attach,daemon=True);thread.start()
    deadline=time.monotonic()+timeout;pressed=False
    try:
        while not done.wait(.05) and time.monotonic()<deadline:
            if pressed or (issue and not issue.startswith('consent_attach_uncorrelated:')):continue
            try:
                sheet=select_sheet(backend.scan(),baseline,backend.hosts())
                if sheet:
                    if not backend.correlate():
                        issue='consent_attach_uncorrelated: cannot prove sole local connection'
                        continue
                    issue=None
                    if not done.is_set():backend.press(sheet,pending=lambda:not done.is_set() and time.monotonic()<deadline);pressed=True
            except Exception as exc:
                # Discard invalid/busy AX snapshots; scan rebuilds host/window refs.
                # Retry observation only within this same pending handshake.
                if str(exc) in {'consent_ax_read:-25202','consent_ax_read:-25204'}:continue
                issue=str(exc)
        if 'ws' in result:
            ws=result['ws']
            if isinstance(backend,MacConsent):
                try:ws=register_accepted(ws,data_root,url.port,url.path)
                except BaseException:
                    # Raw TCP close doesn't unblock a full library receive queue.
                    try:ws.close()
                    except Exception:pass  # Preserve the registration failure.
                    raise
            success=True;return ws
        raise ConsentError('consent_attach_failed: '+(issue or result.get('error','deadline; approve exact debugging prompt manually if appropriate')))
    finally:
        abandoned.set()
        if not success and raw_socket is not None:
            import socket
            try:raw_socket.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            raw_socket.close()
        thread.join(timeout=3 if not success else .1)
        if not success and isinstance(backend,MacConsent):
            try:backend.cleanup_abandoned(baseline)
            except Exception:pass  # Preserve original attach error; next preflight still gates.



class AX:
    """Small direct AX reader: never requests/changes OS permissions or focus."""
    def __init__(self):
        import ctypes as c
        self.c=c;self.refs=[]
        self.cf=c.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.ax=c.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
        def sig(lib,name,restype,args):
            fn=getattr(lib,name);fn.restype=restype;fn.argtypes=args;return fn
        p=c.c_void_p;i=c.c_long
        sig(self.ax,'AXIsProcessTrusted',c.c_bool,[])
        sig(self.ax,'AXUIElementCreateApplication',p,[c.c_int])
        sig(self.ax,'AXUIElementCopyAttributeValue',c.c_int,[p,p,c.POINTER(p)])
        sig(self.ax,'AXUIElementPerformAction',c.c_int,[p,p])
        sig(self.ax,'AXUIElementSetMessagingTimeout',c.c_int,[p,c.c_float])
        sig(self.cf,'CFStringCreateWithCString',p,[p,c.c_char_p,c.c_uint])
        sig(self.cf,'CFStringGetCString',c.c_bool,[p,c.c_char_p,i,c.c_uint])
        sig(self.cf,'CFArrayGetCount',i,[p]);sig(self.cf,'CFArrayGetValueAtIndex',p,[p,i])
        sig(self.cf,'CFRelease',None,[p]);sig(self.cf,'CFHash',c.c_ulong,[p])
    def trusted(self):return self.ax.AXIsProcessTrusted()
    def string(self,s):
        value=self.cf.CFStringCreateWithCString(None,s.encode(),0x08000100);self.refs.append(value);return value
    def attr(self,node,name):
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
    def nodes(self,node,depth=0):
        if depth>20:raise ConsentError('consent_ax_tree_depth')
        yield node
        for child in self.children(node):yield from self.nodes(child,depth+1)
    def clear(self):
        for value in reversed(self.refs):self.cf.CFRelease(value)
        self.refs=[]
    def sheets(self,pid):
        app=self.ax.AXUIElementCreateApplication(pid);self.refs.append(app)
        self.ax.AXUIElementSetMessagingTimeout(app,.25)
        result=[]
        # Only walk window descendants; do not recursively enumerate webpage DOMs.
        windows=self.attr(app,'AXWindows')
        roots=[self.cf.CFArrayGetValueAtIndex(windows,i) for i in range(self.cf.CFArrayGetCount(windows))] if windows else []
        def find(node,depth=0):
            if depth>5:return
            role=self.text(node,'AXRole')
            if role=='AXSheet':yield node;return
            if role in {'AXWebArea','AXScrollArea'}:return
            for child in self.children(node):yield from find(child,depth+1)
        for root in roots:
            for sheet in find(root):
                headings=[];buttons=[];elements={}
                for node in self.nodes(sheet):
                    role=self.text(node,'AXRole')
                    label=self.text(node,'AXTitle') or self.text(node,'AXDescription')
                    if role=='AXHeading':headings.append(label or self.text(node,'AXValue'))
                    if role=='AXButton':buttons.append(label);elements[label]=node
                result.append({'key':(pid,self.cf.CFHash(sheet)),'pid':pid,'name':self.text(sheet,'AXTitle'), 'headings':headings,'buttons':buttons,'elements':elements})
        return result
    def press(self,sheet):
        completed=subprocess.run(['osascript','-e',PRESS_SCRIPT,str(sheet['pid']),sheet['bundle']],
                                 capture_output=True,text=True,timeout=3)
        if completed.returncode or completed.stdout.strip()!='clicked':
            raise ConsentError('consent_press_not_confirmed')



PRESS_SCRIPT = 'on headings(n, depth)\n if depth > 16 then return {}\n set labels to {}\n tell application "System Events"\n  try\n   if (role of n as text) is "AXHeading" then set end of labels to name of n as text\n  end try\n  try\n   repeat with x in UI elements of n\n    set labels to labels & my headings(x, depth + 1)\n   end repeat\n  end try\n end tell\n return labels\nend headings\non clickButton(n, wanted, depth, hostPid, expectedBundle)\n if depth > 16 then return false\n tell application "System Events"\n  try\n   if (role of n as text) is "AXButton" and (description of n as text) is wanted then\n    set p to first application process whose unix id is hostPid\n    if (unix id of p) is not hostPid then return false\n    if (bundle identifier of p as text) is not expectedBundle then return false\n    perform action "AXPress" of n\n    return true\n   end if\n  end try\n  try\n   repeat with x in UI elements of n\n    if my clickButton(x, wanted, depth + 1, hostPid, expectedBundle) then return true\n   end repeat\n  end try\n end tell\n return false\nend clickButton\non run argv\n set hostPid to item 1 of argv as integer\n set expectedBundle to item 2 of argv\n tell application "System Events"\n  try\n   set p to first application process whose unix id is hostPid\n   if (unix id of p) is not hostPid then return "stale-host"\n   if (bundle identifier of p as text) is not expectedBundle then return "stale-host"\n   repeat with w in windows of p\n    try\n     repeat with s in sheets of w\n      set labelText to ""\n      try\n       set labelText to name of s as text\n      end try\n      set seenEnglish to labelText is "Allow remote debugging?"\n      set seenIndonesian to labelText is "Izinkan proses debug jarak jauh?"\n      set hs to my headings(s, 0)\n      if hs contains "Allow remote debugging?" then set seenEnglish to true\n      if hs contains "Izinkan proses debug jarak jauh?" then set seenIndonesian to true\n      set wanted to ""\n      if seenEnglish and not seenIndonesian then set wanted to "Allow"\n      if seenIndonesian and not seenEnglish then set wanted to "Izinkan"\n      if wanted is not "" then\n       if my clickButton(s, wanted, 0, hostPid, expectedBundle) then return "clicked"\n      end if\n     end repeat\n    end try\n   end repeat\n  on error e number n\n   if n is -1719 or n is -1743 then error e number n\n  end try\n end tell\n return "not-found"\nend run\n'


class MacConsent:
    def __init__(self,root,port,path=None):
        self.root=Path(root).resolve();self.port=port;self.path=path;self.ax=None;self.processes={};self.pending_port: int | None=None
    def endpoint_matches(self):
        try:
            lines=(self.root/'DevToolsActivePort').read_text().splitlines()
            return len(lines)==2 and lines==[str(self.port),self.path]
        except OSError:return False
    def hosts(self):return {pid for pid,h in self.processes.items() if h['bound']}
    def scan(self):
        import psutil,hashlib
        if self.ax is None:self.ax=AX()
        if not self.ax.trusted():raise ConsentError('consent_accessibility: grant Accessibility manually; no permission change attempted')
        self.ax.clear();self.processes={};sheets=[]
        for process in psutil.process_iter(['pid','exe','create_time','cmdline']):
            try:
                exe=Path(process.info['exe'] or '')
                if exe.name not in {'Google Chrome','app_mode_loader'}:continue
                plist=plistlib.loads((exe.parents[1]/'Info.plist').read_bytes())
                kind=host_identity(str(exe),plist,self.root)
                if not kind:continue
                if kind=='main':
                    check=subprocess.run(['/usr/bin/codesign','--verify','-R','=anchor apple generic and identifier "com.google.Chrome" and certificate leaf[subject.OU] = "EQHXZ8M8AV"',str(exe.parents[2])],capture_output=True,timeout=2)
                    if check.returncode:continue
                    args=process.info['cmdline'] or []
                    data=next((x.split('=',1)[1] for x in args if x.startswith('--user-data-dir=')),str(Path.home()/'Library/Application Support/Google/Chrome'))
                    bound=Path(data).resolve()==self.root
                else:
                    if not verify_pwa_host(exe,plist,self.root):continue
                    bound=True
                self.processes[process.pid]={'started':process.info['create_time'],'exe':str(exe),'bound':bound,'kind':kind}
                sheets.extend(self.ax.sheets(process.pid))
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
        key=sheet['key'];sheets=self.scan();fresh=next((s for s in sheets if s['key']==key),None)
        if not fresh:return
        questions={s['key']for s in sheets if button_for_dialog(s['name'],s['headings'])}
        if len(questions)!=1:raise ConsentError('consent_cancel_ambiguous')
        if fresh['pid']not in self.hosts()or not button_for_dialog(fresh['name'],fresh['headings']):raise ConsentError('consent_cancel_identity_changed')
        if orphan and not self.no_peers():raise ConsentError('consent_preexisting: another connection active')
        label='Batal'if button_for_dialog(fresh['name'],fresh['headings'])=='Izinkan'else'Cancel'
        if fresh['buttons'].count(label)!=1:raise ConsentError('consent_cancel_ambiguous')
        if self.ax is None:raise ConsentError('consent_cancel_ax_unavailable')
        err=self.ax.ax.AXUIElementPerformAction(fresh['elements'][label],self.ax.string('AXPress'))
        if err:raise ConsentError('consent_cancel_failed:'+str(err))
        deadline=time.monotonic()+.75
        while True:
            if not any(s['key']==key for s in self.scan()):return
            if time.monotonic()>=deadline:raise ConsentError('consent_cancel_not_dismissed')
            time.sleep(.05)
    def cleanup_abandoned(self,baseline):
        # The transport is already closed. Only newly-created orphan questions qualify.
        for _ in range(4):
            sheets=self.scan()
            owned=[s for s in sheets if s['key']not in baseline and s['pid']in self.hosts()and button_for_dialog(s['name'],s['headings'])]
            if not owned or not self.no_peers():return
            self.cancel_sheet(owned[0],orphan=True);time.sleep(.1)
    def prepare(self):
        for _ in range(6):
            sheets=self.scan();stale=[s for s in sheets if button_for_dialog(s['name'],s['headings'])]
            if not stale:return sheets
            if not self.no_peers():raise ConsentError('consent_preexisting: active peer; no new connection opened')
            self.cancel_sheet(stale[0],orphan=True);time.sleep(.1)
        raise ConsentError('consent_preexisting: cleanup incomplete; no new connection opened')
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
        key=sheet['key'];fresh=select_sheet(self.scan(),set(),self.hosts())
        if not fresh or fresh['key']!=key or not self.correlate():raise ConsentError('consent_changed_before_press')
        if not pending():return
        host=self.processes.get(fresh['pid'])
        fresh['bundle']='com.google.Chrome' if host and host['kind']=='main' else self._host_bundle(fresh['pid'])
        if pending():self.ax.press(fresh)
    def _host_bundle(self,pid):
        exe=Path(self.processes[pid]['exe'])
        return plistlib.loads((exe.parents[1]/'Info.plist').read_bytes())['CFBundleIdentifier']


CHROME=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')


def verify_pwa_host(exe,plist,root,*,apps_root=None):
    exe=Path(exe).resolve()
    apps_root=Path(apps_root or Path.home()/'Applications/Chrome Apps.localized').resolve()
    if host_identity(str(exe),plist,root)!='pwa':return False
    try:
        exe.relative_to(apps_root)
        checked=subprocess.run(['/usr/bin/codesign','--verify','--strict',str(exe.parents[2])],capture_output=True,timeout=2)
        return checked.returncode==0
    except (ValueError,OSError,subprocess.SubprocessError):return False


def verify_chrome_executable(executable):
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
            check=subprocess.run(['/usr/bin/codesign','--verify','--strict','-R='+requirement,str(p.parents[2])],capture_output=True,timeout=2)
            if check.returncode:return False
        return all((p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns)==(s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns) for p,s in zip(paths,before))
    except (OSError,subprocess.SubprocessError):return False


def host_identity(executable, plist, root):
    path=Path(executable)
    if plist.get('CFBundleIdentifier')=='com.google.Chrome' and plist.get('CFBundleExecutable')=='Google Chrome' and verify_chrome_executable(executable):return 'main'
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
