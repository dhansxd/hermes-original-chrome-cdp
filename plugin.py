"""Original headed Chrome provider and public browser_exec override. No core mutation."""
import copy, ctypes, json, os, re, secrets, signal, subprocess, sys, threading, time
from pathlib import Path
from agent.browser_provider import BrowserProvider

NAME='original-chrome-default'
ROOT=Path(__file__).resolve().parent
CHROME=Path('/Applications/Google Chrome.app')
PERSONAL=Path.home()/'Library/Application Support/Google/Chrome'


EXPECTED_ACCOUNT='developer@example.invalid'


def verify_account(data,expected):
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
        for p in psutil.process_iter(['name','exe','cmdline','create_time']):
            if p.info['name']!='Google Chrome':continue
            try:
                args=p.info['cmdline'] or []
                root=Path(next((a.split('=',1)[1] for a in args if a.startswith('--user-data-dir=')),str(PERSONAL))).resolve()
                if root!=data.resolve():continue
                if not chrome_executable(p.info['exe']) or gui_identity(p.pid)!=destination:
                    raise RuntimeError('safe_GUI_launch_unavailable: Chrome destination mismatch')
                found.append((p.pid,p.info['create_time']))
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


class ChromeProvider(BrowserProvider):
    name=NAME
    display_name='Original headed Chrome · Default'
    def __init__(self, data=None, workspace=None):
        self.data=Path(data or PERSONAL).resolve()
        self.workspace=Path(workspace or Path.home()/'.hermes/cache/scratch/native-chrome-work')
        self.states={};self.lock=threading.RLock();self.last_cleanup={};self.last_sessions={}
        self._active_entry: dict={}
        self._observer=None
    def is_available(self):return sys.platform=='darwin' and CHROME.exists()
    def get_setup_schema(self):
        return {'name':self.display_name,'badge':'local GUI','tag':'Original Default, owned windows; no profile copy','env_vars':[]}
    def endpoint(self):
        # No arbitrary endpoint override: port file is tied to the authorized data root.
        if self.data==PERSONAL.resolve():verify_account(self.data,EXPECTED_ACCOUNT)
        # GUI explicitly selects Default BEFORE CDP work; never scan other contexts.
        seed=self.workspace/'seeds'/('chrome-agent-'+secrets.token_hex(16)+'.html')
        seed.parent.mkdir(parents=True,exist_ok=True)
        seed.write_text('<!doctype html><title>Chrome agent setup</title>')
        self.seed_url=seed.resolve().as_uri()
        # Setup authority is recorded before launch, not yet a verified profile binding.
        self._active_entry['state']={'pending_seed':self.seed_url,'owned':{},'verified':False}
        gui_launch(self.data,self.seed_url)
        import psutil
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            try:
                lines=(self.data/'DevToolsActivePort').read_text().splitlines()
                port=int(lines[0]);path=lines[1]
                if not 0<port<65536 or not path.startswith('/devtools/browser/'):raise ValueError('invalid port file')
                owners=[]
                for process in psutil.process_iter(['name','exe','cmdline','create_time']):
                    if process.info['name']!='Google Chrome':continue
                    args=process.info['cmdline'] or []
                    root=Path(next((a.split('=',1)[1] for a in args if a.startswith('--user-data-dir=')),str(PERSONAL))).resolve()
                    if root!=self.data or not chrome_executable(process.info['exe']):continue
                    started=process.info['create_time']
                    if (self.data/'DevToolsActivePort').stat().st_mtime < started:continue
                    if any(c.status=='LISTEN' and c.laddr.port==port and c.laddr.ip in {'127.0.0.1','::1'} for c in process.net_connections(kind='tcp')):
                        if process.create_time()==started:owners.append(process.pid)
                if len(owners)!=1 or (self.data/'DevToolsActivePort').read_text().splitlines()!=lines:
                    raise ValueError('endpoint not published by current browser generation')
                return f'ws://127.0.0.1:{port}{path}'
            except (OSError,ValueError,IndexError,psutil.Error):time.sleep(.2)
        raise RuntimeError('Chrome_endpoint_unavailable: enable chrome://inspect/#remote-debugging; no headless fallback used')
    def _key(self,args,task_id):
        session=args.get('session') or 'default'
        if not re.fullmatch('[A-Za-z0-9_-]{1,64}',session):raise ValueError('invalid session name')
        return (str(task_id or 'default'),session)
    def _worker(self,request,timeout=300):
        # Protocol stdout is distinct from captured user stdout. No durable journal.
        entry=self._active_entry
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
                if self._observer is None or self._observer.closed:
                    self._observer=ScopedObserver(request['endpoint'],request['profile'])
                entry['observer']=self._observer
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
                        try:response=entry['observer'].request(frame['cdp'],entry.get('state'))
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
            if hasattr(observer,'entries'):observer.entries[:]=[e for e in observer.entries if e is not entry]
            if not any(other is not entry and other.get('observer') is observer for other in self.states.values()):observer.close()

    def execute(self,args,task_id=None,**kwargs):
        with self.lock:
            key=None;endpoint=None
            try:
                key=self._key(args,task_id)
                self.last_sessions.pop(key[0],None)
                if self.data==PERSONAL.resolve():verify_account(self.data,EXPECTED_ACCOUNT)
                timeout=max(5,min(1800,int(args.get('timeout_s',300))))
                entry=self.states.get(key)
                if entry and entry.get('uncertain'):raise RuntimeError('previous_execution_outcome_uncertain: do not replay; inspect and release session')
                if not entry:
                    entry={'endpoint':None,'state':None}
                    self.states[key]=entry
                self._active_entry=entry
                endpoint=entry['endpoint'] or self.endpoint()
                entry['endpoint']=endpoint
                workspace=self.workspace/str(abs(hash(key)))
                request={'endpoint':endpoint,'profile':str(self.data/'Default'),'workspace':str(workspace),'state':entry['state'],'seed_url':getattr(self,'seed_url',None),'code':args.get('code','')}
                result=self._worker(request,timeout)
                if result.get('state'):entry['state']=result.pop('state')
                if entry.get('observer') and ((entry.get('state') or {}).get('observer_released') or not (entry.get('state') or {}).get('owned')):
                    self._release_observer(entry)
                    if not (entry.get('state') or {}).get('owned'):self.states.pop(key,None)
                if result.get('uncertain') or (not result.get('success') and (self.states.get(key,{}).get('state') or {}).get('verified') is False):
                    self.states[key]['uncertain']=True
                if result.get('success') and self.states.get(key,{}).get('state',{}).get('owned'):
                    self.last_sessions[key[0]]=key[1]
                result['fallback_used']=False
                result['limitations']=['No arbitrary-Python sandbox','Browser-wide page auto-attach pauses new pages; owned opener-linked popups are armed before resume; dialog_pending requires explicit answer, never action replay; observer loss fails without reconnect','Vault uses the exact selected held parent transport/session; missing or lost observer binding refuses without reconnect','Only opener-linked popups tracked; automatic cleanup on session finalization/interruption, not ordinary turn completion; use finish_browser() for explicit task finish','New tabs use separate owned windows','Consent auto-click verified on personal main Chrome and 9Router PWA; ambiguous/uncorrelated prompts report failure']
                return json.dumps(result)
            except subprocess.TimeoutExpired:
                if key is not None:
                    self.states.setdefault(key,{'endpoint':endpoint,'state':None})['uncertain']=True
                return json.dumps({'success':False,'error':'browser_exec_timeout: action outcome uncertain; no retry performed; targets may remain','fallback_used':False,'action_replayed':False})
            except Exception as exc:
                if key in self.states:
                    self.states[key]['uncertain']=True
                    self._release_observer(self.states[key])
                return json.dumps({'success':False,'error':str(exc),'error_type':type(exc).__name__,'fallback_used':False,'action_replayed':False})
    def create_session(self,task_id):
        # This provider cannot safely hand its browser-wide endpoint to legacy target selection.
        raise RuntimeError('Use browser.backend=browser-use with the approved browser_exec override; legacy browser_* attachment is not safe')
    def close_session(self,session_id):
        with self.lock:
            results=[]
            for key,entry in list(self.states.items()):
                if key[0]!=str(session_id):continue
                try:
                    if not entry.get('state') or not entry.get('endpoint'):
                        self.last_cleanup[key]={'success':False,'error':'ownership_lost_after_timeout: no targets adopted for cleanup'}
                        results.append(False);continue
                    self._active_entry=entry
                    result=self._worker({'endpoint':entry['endpoint'],'state':entry['state'],'profile':str(self.data/'Default'),'workspace':str(self.workspace),'cleanup':True},30)
                    self.last_cleanup[key]=result
                    results.append(result.get('success',False))
                    if result.get('success'):
                        self.states.pop(key)
                        if self.last_sessions.get(key[0])==key[1]:self.last_sessions.pop(key[0],None)
                except Exception as exc:
                    self.last_cleanup[key]={'success':False,'error':str(exc)};results.append(False)
                finally:
                    self._release_observer(entry)
            return all(results)
    def emergency_cleanup(self,session_id):self.close_session(session_id)
    def unload(self):
        with self.lock:
            for task in {key[0] for key in self.states}:self.close_session(task)


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
            ids=self.bindings[task]
            success=self.provider.close_session(task)
            report={'task_id':task,'session_id':ids['session_id'],'reason':reason,'success':success,
                    'results':[dict(result,session=key[1]) for key,result in self.provider.last_cleanup.items() if key[0]==task]}
            reports.append(report)
            previous=self.notices.get(ids['session_id'],[])
            self.notices[ids['session_id']]=[r for r in previous if r['task_id']!=task]+[report]
            # Public event + next browser tool/output transform; observer return alone is not delivery.
            self.ctx.emit('browser_cleanup',report)
            if success:self.bindings.pop(task,None)
        return reports
    def finalize(self,session_id=None,**kwargs):
        with self.provider.lock:
            tasks=[task for task,ids in self.bindings.items() if session_id and ids['session_id']==str(session_id)]
            result=self._cleanup(tasks,'session_finalized')
            self.pending.pop(str(session_id),None)
            return result or None
    def cancel(self,session_key=None,**kwargs):
        with self.provider.lock:
            tasks=[task for task,ids in self.bindings.items() if session_key and ids['session_key']==str(session_key)]
            return self._cleanup(tasks,'cancelled') or None
    def turn_end(self,task_id=None,session_id=None,interrupted=False,**kwargs):
        with self.provider.lock:
            ids=self.bindings.get(str(task_id))
            if not ids or ids['session_id']!=str(session_id):return
            if interrupted:return self._cleanup([str(task_id)],'interrupted')
            return {'cleanup_deferred':True,'reason':'pending_human_input' if self.pending.get(str(session_id)) else 'turn_is_not_task_completion'}
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
    from tools.browser_use_cli import BROWSER_EXEC_SCHEMA, browser_exec
    from hermes_cli.config import read_raw_config
    provider=ChromeProvider()
    lifecycle=BrowserLifecycle(ctx,provider);lifecycle.register()
    ctx.on_unload(provider.unload)
    def selected():return read_raw_config().get('browser',{}).get('cloud_provider')==NAME
    def handler(args,**kw):
        if selected():
            from tools.approval_context import get_current_session_key
            with provider.lock:
                lifecycle.bind(**dict(kw,session_key=kw.get('session_key') or get_current_session_key(default='')))
                result=json.loads(provider.execute(args,**kw))
                result['browser_cleanup']=lifecycle.status(kw.get('session_id'))
                result['automatic_cleanup']='session finalization or explicit interruption only; completed turns preserve pending/multi-turn work'
                return json.dumps(result)
        return browser_exec(code=args.get('code',''),session=args.get('session',''),timeout_s=args.get('timeout_s',300),task_id=kw.get('task_id'))
    ctx.register_browser_provider(provider)
    ctx.register_tool(name='browser_exec',toolset='browser-use',schema=copy.deepcopy(BROWSER_EXEC_SCHEMA),handler=handler,override=True)
    # Native supervisor focus_page selects first same-origin browser-wide target. Never allow
    # native vault to drift into a manual tab while this scoped provider is selected.
    from tools import browser_vault_tool as vault
    from tools.registry import registry
    for tool in ('browser_vault_fill','browser_vault_save_login','browser_vault_enter_code'):
        entry=registry.get_entry(tool)
        if entry is None:raise RuntimeError('native vault tool registration missing: '+tool)
        original=entry.handler
        def guarded(args,_original=original,**kw):
            if selected():
                if __package__:
                    from .vault_adapter import invoke
                else:
                    from vault_adapter import invoke
                return invoke(provider,_original,args,kw)
            return _original(args,**kw)
        ctx.register_tool(name=tool,toolset=entry.toolset,schema=copy.deepcopy(entry.schema),handler=guarded,override=True)
