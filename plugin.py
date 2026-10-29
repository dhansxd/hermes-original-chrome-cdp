"""Original headed Chrome provider and public browser_exec override. No core mutation."""
import ast, copy, ctypes, json, os, re, secrets, signal, subprocess, sys, threading, time
from contextlib import contextmanager
from pathlib import Path
from agent.browser_provider import BrowserProvider

NAME='original-chrome-default'
ROOT=Path(__file__).resolve().parent
CHROME=Path('/Applications/Google Chrome.app')
PERSONAL=Path.home()/'Library/Application Support/Google/Chrome'


def expected_account():
    # Profile-local operator setting; never derive authority from Chrome metadata.
    from hermes_cli.config import read_raw_config
    return read_raw_config().get('plugins',{}).get('entries',{}).get(NAME,{}).get('settings',{}).get('expected_account')


def verify_account(data,expected):
    if not isinstance(expected,str) or not expected.strip():
        raise RuntimeError('account_binding_unconfigured: set the expected Default account in plugin settings; no Chrome launch')
    expected=expected.strip()
    try:
        meta=json.loads((Path(data)/'Local State').read_text())['profile']['info_cache']['Default']
        prefs=json.loads((Path(data)/'Default/Preferences').read_text())
        matches=meta.get('user_name','').casefold()==expected.casefold()
        present=any(a.get('email','').casefold()==expected.casefold() for a in prefs.get('account_info',[]))
    except (OSError,ValueError,KeyError,TypeError):matches=present=False
    if not matches or not present:
        raise RuntimeError('account_binding_mismatch: requested Default account not verified; no Chrome launch')


def chrome_executable(path):
    if __package__:
        from .consent import verify_chrome_executable
    else:
        from consent import verify_chrome_executable
    return verify_chrome_executable(path)


def gui_identity(pid=None):
    uid=os.getuid()
    domain=f'pid/{pid}' if pid else f'gui/{uid}'
    result=subprocess.run(['/bin/launchctl','print',domain],capture_output=True,text=True,timeout=2)
    contexts=re.findall(r'^\s*security context = \{([^{}]*)\}',result.stdout,re.M)
    if result.returncode or not result.stdout.startswith(domain+' = {') or len(contexts)!=1:
        raise RuntimeError('safe_GUI_launch_unavailable: GUI destination identity unavailable')
    pairs=re.findall(r'^\s*(uid|asid) = ([0-9]+)\s*$',contexts[0],re.M)
    values=dict(pairs)
    if len(pairs)!=2 or set(values)!={'uid','asid'} or int(values['uid'])!=uid:
        raise RuntimeError('safe_GUI_launch_unavailable: GUI destination identity ambiguous')
    if not pid and re.findall(r'^\s*session = (\S+)\s*$',result.stdout,re.M)!=['Aqua']:
        raise RuntimeError('safe_GUI_launch_unavailable: no Aqua destination')
    asid=int(values['asid']);actual=ctypes.c_uint32();flags=ctypes.c_uint32()
    security=ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
    status=security.SessionGetInfo(ctypes.c_uint32(asid),ctypes.byref(actual),ctypes.byref(flags))
    if status or actual.value!=asid or not flags.value & 0x10 or os.geteuid()!=uid or os.stat('/dev/console').st_uid!=uid:
        raise RuntimeError('safe_GUI_launch_unavailable: destination has no verified graphic access')
    return (uid,asid)


def gui_launch(data,seed_url=None):
    import psutil
    destination=gui_identity()
    def browsers():
        found=[]
        for p in psutil.process_iter():
            try:
                info=p.as_dict(attrs=['name','exe','cmdline','create_time'])
                if info['name']!='Google Chrome':continue
                args=info['cmdline'] or []
                root=Path(next((a.split('=',1)[1] for a in args if a.startswith('--user-data-dir=')),str(PERSONAL))).resolve()
                if root!=data.resolve():continue
                if not chrome_executable(info['exe']) or gui_identity(p.pid)!=destination:
                    raise RuntimeError('safe_GUI_launch_unavailable: Chrome destination mismatch')
                found.append((p.pid,info['create_time']))
            except psutil.NoSuchProcess:continue
        return found
    browsers()
    args=['/usr/bin/open','-n','-g','-a',str(CHROME),'--args',f'--user-data-dir={data}','--profile-directory=Default']
    if data.resolve()!=PERSONAL.resolve():args+=['--remote-debugging-port=0','--no-first-run','--no-default-browser-check']
    if seed_url:args+=['--new-window',seed_url]
    env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin','TMPDIR':str(Path.home()/'.hermes/cache/scratch')}
    subprocess.run(args,env=env,capture_output=True,text=True,timeout=15,check=True)
    deadline=time.monotonic()+8
    while not browsers():
        if time.monotonic()>=deadline:raise RuntimeError('safe_GUI_launch_unavailable: launched Chrome identity unavailable; no replay')
        time.sleep(.1)
    if gui_identity()!=destination:raise RuntimeError('safe_GUI_launch_unavailable: GUI destination changed')


def seed_window_ready(pid,seed_url):
    # A live listener can outlast its final window; approval needs a modal host.
    if __package__:
        from .consent import AX,ConsentError
    else:
        from consent import AX,ConsentError
    ax=AX()
    try:
        if not ax.trusted():raise ConsentError('consent_accessibility: grant Accessibility manually; no permission change attempted')
        app=ax.ax.AXUIElementCreateApplication(pid);ax.refs.append(app)
        ax.ax.AXUIElementSetMessagingTimeout(app,.25)
        values=ax.attr(app,'AXWindows')
        windows=[ax.cf.CFArrayGetValueAtIndex(values,i) for i in range(ax.cf.CFArrayGetCount(values))] if values else []
        matches=[w for w in windows if ax.text(w,'AXSubrole')=='AXStandardWindow' and ax.text(w,'AXDocument')==seed_url]
        return len(matches)==1
    except ConsentError as exc:
        if str(exc) in {'consent_ax_read:-25202','consent_ax_read:-25204'}:return False
        raise
    finally:ax.clear()


class ChromeProvider(BrowserProvider):
    name=NAME
    display_name='Original headed Chrome · Default'
    def __init__(self, data=None, workspace=None):
        self.data=Path(data or PERSONAL).resolve()
        self.workspace=Path(workspace or Path.home()/'.hermes/cache/scratch/native-chrome-work')
        self.states={};self.lock=threading.RLock();self.last_cleanup={};self.last_sessions={}
        self._session_locks={};self._task_active={};self._closing_tasks={};self._unloading=False
        self._setup_lock=threading.RLock()

    @contextmanager
    def session_guard(self,key):
        # Count waiters before acquiring: removing an entry cannot split one
        # session across an old lock and a new lock while callers are queued.
        with self.lock:
            slot=self._session_locks.setdefault(key,[threading.RLock(),0,object()]);slot[1]+=1
            generation=slot[2]
        try:
            with slot[0]:yield generation
        finally:
            with self.lock:
                slot[1]-=1
                if not slot[1]:self._session_locks.pop(key)
    def is_available(self):return sys.platform=='darwin' and CHROME.exists()
    def get_setup_schema(self):
        return {'name':self.display_name,'badge':'local GUI','tag':'Original Default, owned windows; no profile copy','env_vars':[]}
    def endpoint(self,*,entry):
        # No arbitrary endpoint override: port file is tied to the authorized data root.
        if self.data==PERSONAL.resolve():verify_account(self.data,expected_account())
        # GUI explicitly selects Default BEFORE CDP work; never scan other contexts.
        seed=self.workspace/'seeds'/('chrome-agent-'+secrets.token_hex(16)+'.html')
        seed.parent.mkdir(parents=True,exist_ok=True)
        seed.write_text('<!doctype html><title>Chrome agent setup</title>')
        seed_url=seed.resolve().as_uri()
        # Setup authority belongs to this entry before launch, never a mutable
        # provider-wide active-entry/seed selected by a concurrent caller.
        entry['state']={'pending_seed':seed_url,'owned':{},'verified':False}
        gui_launch(self.data,seed_url)
        import psutil
        deadline=time.monotonic()+20;waiting_for_seed=False
        while time.monotonic()<deadline:
            try:
                lines=(self.data/'DevToolsActivePort').read_text().splitlines()
                port=int(lines[0]);path=lines[1]
                if not 0<port<65536 or not path.startswith('/devtools/browser/'):raise ValueError('invalid port file')
                owners=[]
                for process in psutil.process_iter():
                    info=process.as_dict(attrs=['name','exe','cmdline','create_time'])
                    if info['name']!='Google Chrome':continue
                    args=info['cmdline'] or []
                    root=Path(next((a.split('=',1)[1] for a in args if a.startswith('--user-data-dir=')),str(PERSONAL))).resolve()
                    if root!=self.data or not chrome_executable(info['exe']):continue
                    started=info['create_time']
                    if (self.data/'DevToolsActivePort').stat().st_mtime < started:continue
                    if any(c.status=='LISTEN' and c.laddr.port==port and c.laddr.ip in {'127.0.0.1','::1'} for c in process.net_connections(kind='tcp')):
                        if process.create_time()==started:owners.append(process.pid)
                if len(owners)!=1 or (self.data/'DevToolsActivePort').read_text().splitlines()!=lines:
                    raise ValueError('endpoint not published by current browser generation')
                waiting_for_seed=True
                if not seed_window_ready(owners[0],seed_url):
                    time.sleep(.05);continue
                # AX readiness may take time; do not return a replaced endpoint.
                if (self.data/'DevToolsActivePort').read_text().splitlines()!=lines:
                    raise ValueError('endpoint changed during window readiness')
                return f'ws://127.0.0.1:{port}{path}'
            except (OSError,ValueError,IndexError,psutil.Error):time.sleep(.2)
        if waiting_for_seed:raise RuntimeError('Default_seed_window_unavailable: exact owned GUI seed not ready; no connection opened or launch replay')
        raise RuntimeError('Chrome_endpoint_unavailable: enable chrome://inspect/#remote-debugging; no headless fallback used')
    def _key(self,args,task_id):
        session=args.get('session') or 'default'
        if not re.fullmatch('[A-Za-z0-9_-]{1,64}',session):raise ValueError('invalid session name')
        return (str(task_id or 'default'),session)
    def _chrome_processes(self):
        import psutil
        found=[]
        for proc in psutil.process_iter():
            try:
                info=proc.as_dict(attrs=['name','exe','cmdline'])
                if info['name']!='Google Chrome':continue
                args=info['cmdline'] or []
                root=Path(next((v.split('=',1)[1] for v in args if v.startswith('--user-data-dir=')),str(PERSONAL))).resolve()
                if root==self.data and chrome_executable(info['exe']):found.append(proc)
            except psutil.NoSuchProcess:continue
        return found

    def _finish_browser(self, entry):
        # Setup cannot reuse an endpoint while its disposable browser is exiting.
        with self._setup_lock:return self._finish_browser_locked(entry)

    def _finish_browser_locked(self, entry):
        state=entry.get('state') or {}
        if state.get('owned') or state.get('unresolved_creation'):
            return {'browser_closed':False,'browser_close_deferred':'targets_remaining'}
        with self.lock:
            if any(other is not entry for other in self.states.values()):
                return {'browser_closed':False,'browser_close_deferred':'other_sessions_active'}
        if self.data==PERSONAL.resolve():
            # This root is shared with the Flow API and original user sessions.
            # Closing our known targets never grants authority to quit Chrome.
            return {'browser_closed':False,'browser_close_deferred':'shared_browser'}
        processes=self._chrome_processes()
        observer=entry['observer']
        error=None
        try:observer.request({'method':'Browser.close'},state) # Serialized with idle drain; normal shutdown.
        except Exception as exc:error=type(exc).__name__
        import psutil
        _,alive=psutil.wait_procs(processes,timeout=5)
        if alive or (error and not processes):
            return {'browser_closed':False,'browser_close_error':error or 'Chrome_process_still_running'}
        observer.close()
        return {'browser_closed':True}

    def _worker(self,request,timeout:float=300,*,entry):
        # Protocol stdout is distinct from captured user stdout. No durable journal.
        frames=[];errors=[]
        proxied=bool(request.get('endpoint'))
        if proxied:
            if __package__:
                from .observer import ScopedObserver
            else:
                from observer import ScopedObserver
            if request.get('cleanup') and entry.get('observer') and entry['observer'].closed:
                entry.pop('observer') # Fresh cleanup-only connection; never resumes dialog observation.
            if 'observer' not in entry:
                # An in-flight worker timeout may have to close this transport.
                # Never let that revoke another named session's held callbacks.
                entry['observer']=ScopedObserver(request['endpoint'],request['profile'])
            if hasattr(entry['observer'],'bind'):entry['observer'].bind(entry)
            request=dict(request,parent_transport=True)
        proc=subprocess.Popen([sys.executable,str(ROOT/'worker.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
        assert proc.stdin is not None and proc.stdout is not None
        def read():
            assert proc.stdin is not None and proc.stdout is not None
            try:
                for line in proc.stdout:
                    frame=json.loads(line)
                    if 'checkpoint' in frame:entry['state']=frame['checkpoint']
                    elif 'cdp' in frame:
                        try:
                            if frame['cdp']['method']=='__finish_browser__':
                                response={'value':self._finish_browser(entry),'events':[],'dialogs':{},'event_overflow':False}
                            else:response=entry['observer'].request(frame['cdp'],entry.get('state'))
                        except Exception as exc:response={'error':str(exc)}
                        proc.stdin.write(json.dumps(response)+'\n');proc.stdin.flush()
                    elif 'result' in frame:frames[:]=[frame['result']]
                    else:raise RuntimeError('invalid worker protocol')
            except Exception as exc:errors.append(exc)
        reader=threading.Thread(target=read,daemon=True);reader.start()
        try:
            proc.stdin.write(json.dumps(request)+'\n');proc.stdin.flush()
            if not proxied:proc.stdin.close()
            try:proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                reader.join(.1)
                if reader.is_alive() and entry.get('observer'):entry['observer'].close()
                reader.join()
                raise
            # A bounded worker does not leave user-spawned descendants holding pipes.
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            reader.join()
            if proc.returncode or errors or not frames:raise RuntimeError('browser_worker_failed: missing or invalid final result; outcome uncertain')
            return frames[0]
        finally:
            if proc.poll() is None:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            reader.join();proc.stdout.close()
            if not proc.stdin.closed:
                try:proc.stdin.close()
                except BrokenPipeError:pass # Teardown must not replace the action timeout.
    def _release_observer(self, entry):
        observer=entry.get('observer')
        if observer:
            with self.lock:
                shared=any(other is not entry and other.get('observer') is observer for other in self.states.values())
            if hasattr(observer,'entries'):
                with observer._lock:observer.entries[:]=[e for e in observer.entries if e is not entry]
            if not shared:observer.close()

    def execute(self,args,task_id=None,**kwargs):
        try:key=self._key(args,task_id)
        except Exception as exc:
            return json.dumps({'success':False,'error':str(exc),'fallback_used':False,'action_replayed':False})
        with self.session_guard(key) as generation:
            token=object()
            with self.lock:
                if self._unloading or self._closing_tasks.get(key[0]) or self._session_locks[key][2] is not generation:
                    return json.dumps({'success':False,'error':'session_cleanup_in_progress: no action sent','action_replayed':False,'fallback_used':False})
                self.last_sessions.pop(key[0],None)
                self._task_active.setdefault(key[0],set()).add(token)
            result={}
            try:
                result=self._execute_session(args,key)
                return json.dumps(result)
            finally:
                with self.lock:
                    active=self._task_active[key[0]];active.discard(token)
                    if not active:self._task_active.pop(key[0])
                    entry=self.states.get(key) or {}
                    if not active and result.get('success') and not entry.get('uncertain') and (entry.get('state') or {}).get('owned'):
                        self.last_sessions[key[0]]=key[1]
                    else:self.last_sessions.pop(key[0],None)

    def _execute_session(self,args,key):
        endpoint=None
        with self.lock:entry=self.states.get(key)
        try:
            if self.data==PERSONAL.resolve():verify_account(self.data,expected_account())
            timeout=max(5,min(1800,int(args.get('timeout_s',300))))
            if entry and entry.get('uncertain'):
                # Only the exact finish expression can cross quarantine. It is
                # parsed, never executed; the worker receives cleanup, not code.
                code=args.get('code','')
                try:
                    tree=ast.parse(code)
                    finish_only=any(ast.dump(tree,include_attributes=False)==ast.dump(ast.parse(allowed),include_attributes=False)
                                    for allowed in ('finish_browser()','print(finish_browser())'))
                except (SyntaxError,TypeError):finish_only=False
                if not finish_only:raise RuntimeError('previous_execution_outcome_uncertain: do not replay; inspect and release session')
                self.close_session(key[0],session=key[1])
                with self.lock:result=copy.deepcopy(self.last_cleanup.get(key,{'success':False,'error':'cleanup_outcome_unknown'}))
                return dict(result,fallback_used=False,action_replayed=False,cleanup_only=True)
            if not entry:
                # Only GUI launch/root setup is serialized; ordinary page I/O is
                # outside this boundary and outside the state-map lock.
                with self._setup_lock:
                    entry:dict={'endpoint':None,'state':None}
                    with self.lock:self.states[key]=entry
                    entry['endpoint']=self.endpoint(entry=entry)
            endpoint=entry['endpoint']
            workspace=self.workspace/str(abs(hash(key)))
            request={'endpoint':endpoint,'profile':str(self.data/'Default'),'workspace':str(workspace),'state':entry['state'],'code':args.get('code','')}
            result=self._worker(request,timeout,entry=entry)
            if result.get('state'):entry['state']=result.pop('state')
            if entry.get('observer') and ((entry.get('state') or {}).get('observer_released') or not (entry.get('state') or {}).get('owned')):
                self._release_observer(entry)
                if not (entry.get('state') or {}).get('owned'):
                    with self.lock:self.states.pop(key,None)
            if result.get('uncertain') or (not result.get('success') and (entry.get('state') or {}).get('verified') is False):
                entry['uncertain']=True
            result['fallback_used']=False
            result['limitations']=['No arbitrary-Python sandbox','Only owned roots and related targets are observed; no browser-wide page auto-attach; uniquely bound early popup dialogs use native AX with an explicit answer; ambiguous native bindings or unavailable Accessibility refuse; dialog_pending requires explicit answer, never action replay; observer loss fails without reconnect','Vault uses the exact selected held parent transport/session; missing or lost observer binding refuses without reconnect','Only opener-linked popups tracked; automatic cleanup on session finalization/interruption, not ordinary turn completion; use finish_browser() for explicit task finish','New tabs use separate owned windows','Consent auto-click verified on personal main Chrome and 9Router PWA; ambiguous/uncorrelated prompts report failure']
            return result
        except subprocess.TimeoutExpired:
            if entry:entry['uncertain']=True
            return {'success':False,'error':'browser_exec_timeout: action outcome uncertain; no retry performed; targets may remain','fallback_used':False,'action_replayed':False}
        except Exception as exc:
            if entry:
                entry['uncertain']=True
                self._release_observer(entry)
            return {'success':False,'error':str(exc),'error_type':type(exc).__name__,'fallback_used':False,'action_replayed':False}
    def create_session(self,task_id):
        # This provider cannot safely hand its browser-wide endpoint to legacy target selection.
        raise RuntimeError('Use browser.backend=browser-use with the approved browser_exec override; legacy browser_* attachment is not safe')
    def close_session(self,session_id,session=None):
        task=str(session_id);results=[]
        with self.lock:
            if session is None:self._closing_tasks[task]=self._closing_tasks.get(task,0)+1
            keys=[key for key in set(self.states)|set(self._session_locks)
                  if key[0]==task and (session is None or key[1]==session)]
            for key in keys:
                if key in self._session_locks:self._session_locks[key][2]=object()
        try:
            for key in sorted(keys):
                # Wait only for this session's worker, never under the map lock.
                with self.session_guard(key):
                    with self.lock:entry=self.states.get(key)
                    if entry is None:continue
                    try:
                        if not entry.get('state') or not entry.get('endpoint'):
                            result={'success':False,'error':'ownership_lost_after_timeout: no targets adopted for cleanup'}
                        else:
                            result=self._worker({'endpoint':entry['endpoint'],'state':entry['state'],'profile':str(self.data/'Default'),'workspace':str(self.workspace),'cleanup':True},30,entry=entry)
                        with self.lock:
                            self.last_cleanup[key]=result
                            if result.get('success'):
                                self.states.pop(key,None)
                                if self.last_sessions.get(task)==key[1]:self.last_sessions.pop(task,None)
                        results.append(bool(result.get('success')))
                    except Exception as exc:
                        with self.lock:self.last_cleanup[key]={'success':False,'error':str(exc)}
                        results.append(False)
                    finally:self._release_observer(entry)
            return all(results)
        finally:
            if session is None:
                with self.lock:
                    self._closing_tasks[task]-=1
                    if not self._closing_tasks[task]:self._closing_tasks.pop(task)
    def emergency_cleanup(self,session_id):self.close_session(session_id)
    def unload(self):
        with self.lock:
            self._unloading=True
            tasks={key[0] for key in self.states}|set(self._task_active)
        for task in sorted(tasks):self.close_session(task)


class BrowserLifecycle:
    """Only explicit host teardown/cancel is terminal; completed turns are not tasks."""
    def __init__(self,ctx,provider):
        self.ctx=ctx;self.provider=provider;self.bindings={};self.pending={};self.notices={}
    def bind(self,task_id=None,session_id=None,session_key=None,**kwargs):
        if not task_id or not session_id:return
        with self.provider.lock:
            self.bindings[str(task_id)]={'session_id':str(session_id),'session_key':str(session_key or '')}
    def register(self):
        for name,callback in [('on_session_finalize',self.finalize),('agent_loop_stopped',self.cancel),
                              ('on_session_end',self.turn_end),('on_human_input_request',self.waiting),
                              ('on_human_input_resolved',self.resolved),('transform_llm_output',self.output)]:
            self.ctx.register_hook(name,callback)
    def _cleanup(self,tasks,reason):
        reports=[]
        for task in tasks:
            with self.provider.lock:
                ids=copy.deepcopy(self.bindings.get(task))
            if ids is None:continue
            success=self.provider.close_session(task)
            with self.provider.lock:
                report={'task_id':task,'session_id':ids['session_id'],'reason':reason,'success':success,
                        'results':[dict(result,session=key[1]) for key,result in self.provider.last_cleanup.items() if key[0]==task]}
                previous=self.notices.get(ids['session_id'],[])
                self.notices[ids['session_id']]=[r for r in previous if r['task_id']!=task]+[report]
                if success and self.bindings.get(task)==ids:self.bindings.pop(task,None)
            reports.append(report)
            # Public event + next browser tool/output transform; observer return alone is not delivery.
            self.ctx.emit('browser_cleanup',report)
        return reports
    def finalize(self,session_id=None,**kwargs):
        with self.provider.lock:
            tasks=[task for task,ids in self.bindings.items() if session_id and ids['session_id']==str(session_id)]
            self.pending.pop(str(session_id),None)
        return self._cleanup(tasks,'session_finalized') or None
    def cancel(self,session_key=None,**kwargs):
        with self.provider.lock:
            tasks=[task for task,ids in self.bindings.items() if session_key and ids['session_key']==str(session_key)]
        return self._cleanup(tasks,'cancelled') or None
    def turn_end(self,task_id=None,session_id=None,interrupted=False,**kwargs):
        with self.provider.lock:
            ids=self.bindings.get(str(task_id))
            if not ids or ids['session_id']!=str(session_id):return
            if not interrupted:return {'cleanup_deferred':True,'reason':'pending_human_input' if self.pending.get(str(session_id)) else 'turn_is_not_task_completion'}
        return self._cleanup([str(task_id)],'interrupted')
    def waiting(self,session_id=None,session_key=None,request_id=None,**kwargs):
        with self.provider.lock:
            if session_id and request_id:self.pending.setdefault(str(session_id),set()).add(str(request_id))
            # Human-input payload can supply routing identity absent from a direct tool call.
            for ids in self.bindings.values():
                if session_id and ids['session_id']==str(session_id) and session_key:ids['session_key']=str(session_key)
    def resolved(self,session_id=None,request_id=None,**kwargs):
        with self.provider.lock:
            self.pending.get(str(session_id),set()).discard(str(request_id))
    def status(self,session_id):
        with self.provider.lock:return copy.deepcopy(self.notices.get(str(session_id),[]))
    def output(self,response_text,session_id=None,**kwargs):
        failures=[r for r in self.status(session_id) if not r['success']]
        if failures:return str(response_text)+'\n\nBrowser cleanup failed; owned targets may remain: '+json.dumps(failures)


def register(ctx):
    if not ctx.has_capability('tools.override'):
        # Doctor intentionally has no operator grants. Expose only inert,
        # non-conflicting metadata there (and on any real no-grant host).
        # Never register the provider or fall back to a different browser/vault.
        def capability_required(args,**kw):
            return json.dumps({'success':False,'error_type':'plugin_capability_required',
                'error':'tools.override is not granted; native browser/vault integration is inactive. Enable through the official plugin consent flow.',
                'fallback_used':False,'action_replayed':False})
        from tools.browser_use_cli import BROWSER_EXEC_SCHEMA
        for name,schema,toolset in (
                ('original_chrome_default_browser_exec',BROWSER_EXEC_SCHEMA,'browser-use'),
                ('original_chrome_default_browser_vault',json.loads((ROOT/'vault_schema.json').read_text()),'browser')):
            schema=copy.deepcopy(schema);schema['name']=name
            schema['description']='Inactive metadata only: tools.override consent required; no browser or credential access.'
            ctx.register_tool(name=name,toolset=toolset,schema=schema,handler=capability_required)
        return
    from tools.browser_use_cli import BROWSER_EXEC_SCHEMA, browser_exec
    from hermes_cli.config import read_raw_config
    from agent.redact import redact_sensitive_text, REDACT_WALK_MAX_DEPTH, REDACT_WALK_DEPTH_MARKER
    def scrub_result(value,depth=0):
        # Scrub decoded strings before JSON escaping, including errors and cleanup.
        # Never change held browser state or the worker's screenshot/artifact bytes.
        if depth>=REDACT_WALK_MAX_DEPTH:return REDACT_WALK_DEPTH_MARKER
        if isinstance(value,str):return redact_sensitive_text(value,force=True)
        if isinstance(value,list):return [scrub_result(v,depth+1) for v in value]
        if isinstance(value,dict):return {scrub_result(k,depth+1):scrub_result(v,depth+1) for k,v in value.items()}
        return value
    provider=ChromeProvider()
    lifecycle=BrowserLifecycle(ctx,provider);lifecycle.register()
    ctx.on_unload(provider.unload)
    def selected():return read_raw_config().get('browser',{}).get('cloud_provider')==NAME
    def handler(args,**kw):
        if selected():
            from tools.approval_context import get_current_session_key
            lifecycle.bind(**dict(kw,session_key=kw.get('session_key') or get_current_session_key(default='')))
            result=json.loads(provider.execute(args,**kw))
            result['browser_cleanup']=lifecycle.status(kw.get('session_id'))
            result['automatic_cleanup']='session finalization or explicit interruption only; completed turns preserve pending/multi-turn work'
            return json.dumps(scrub_result(result))
        return browser_exec(code=args.get('code',''),session=args.get('session',''),timeout_s=args.get('timeout_s',300),task_id=kw.get('task_id'))
    ctx.register_browser_provider(provider)
    ctx.register_tool(name='browser_exec',toolset='browser-use',schema=copy.deepcopy(BROWSER_EXEC_SCHEMA),handler=handler,override=True)
    # Native supervisor focus_page selects first same-origin browser-wide target. Never allow
    # native vault to drift into a manual tab while this scoped provider is selected.
    # Vault import/registration drift must not roll back ordinary browsing. Always
    # install a guard, including when native registration is missing; never leave
    # an unguarded native page action as a compatibility fallback.
    from tools.registry import registry
    vault=None
    try:
        from tools import browser_vault_tool as vault
        entry=registry.get_entry('browser_vault')
    except Exception:
        entry=None
    original=entry.handler if entry else None
    schema=copy.deepcopy(entry.schema) if entry else json.loads((ROOT/'vault_schema.json').read_text())
    def unavailable():
        return json.dumps({'success':False,'error_type':'vault_compatibility_unavailable',
            'error':'Native vault compatibility unavailable; no credential access, fallback or replay.'})
    def guarded(args,**kw):
        if selected() and args.get('action') not in ('list','unlock'):
            if original is None or args.get('action') not in ('fill','save_login','enter_code'):
                return unavailable()
            try:
                if __package__:
                    from .vault_adapter import invoke
                else:
                    from vault_adapter import invoke
            except Exception:
                return unavailable()
            return invoke(provider,original,args,kw)
        if original is None and vault is not None:
            # Only the two non-page native entry points are safe without the
            # registered unified handler. No credential-write fallback exists.
            if args.get('action')=='list' and callable(getattr(vault,'browser_vault_list',None)):
                return vault.browser_vault_list()
            if args.get('action')=='unlock' and callable(getattr(vault,'browser_vault_unlock',None)):
                return vault.browser_vault_unlock(str(args.get('backend') or ''))
        return original(args,**kw) if original else unavailable()
    ctx.register_tool(name='browser_vault',toolset=entry.toolset if entry else 'browser',schema=schema,handler=guarded,override=True)
