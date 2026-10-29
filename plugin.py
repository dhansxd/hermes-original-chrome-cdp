"""Original headed Chrome provider and plugin-owned browser tools. No core mutation."""
import ast, copy, ctypes, json, os, re, signal, subprocess, sys, threading, time
from contextlib import contextmanager
from pathlib import Path
from agent.browser_provider import BrowserProvider

NAME='original-chrome-default'
EXEC_TOOL='browser_original_chrome_exec'
VAULT_TOOL='browser_original_chrome_vault'
TOOLSET='original_chrome'
ROOT=Path(__file__).resolve().parent
CHROME=Path('/Applications/Google Chrome.app')
PERSONAL=Path.home()/'Library/Application Support/Google/Chrome'
APPROVED_ACCOUNT='developer@example.invalid'


def expected_account(get_setting=None):
    # Production receives PluginContext.get_config; direct callers have no
    # ambient settings fallback and must supply their own explicit dependency.
    return get_setting('expected_account') if callable(get_setting) else None


def browser_config():
    # Browser selection is a core setting, separate from plugin-owned settings.
    from hermes_cli.config import load_config_readonly
    try:config=load_config_readonly()
    except Exception:
        raise RuntimeError('browser_configuration_unavailable: no browser action sent') from None
    value=config.get('browser',{}) if isinstance(config,dict) else None
    if not isinstance(value,dict):raise RuntimeError('browser_configuration_unavailable: no browser action sent')
    return value


def selected_browser(config):
    return config.get('cloud_provider')==NAME


def native_browser_tools_disabled():
    """Read persistent host policy; never silently change operator configuration.

    These exclusions outlive the plugin, so removing it cannot re-enable native
    browser tools. Require both names explicitly rather than depending on a
    particular Hermes version's aliases or composite toolsets.
    """
    from hermes_cli.config import load_config_readonly
    try:
        config=load_config_readonly()
        disabled=config.get('agent',{}).get('disabled_toolsets',[])
        if isinstance(disabled,str):
            try:disabled=json.loads(disabled)
            except ValueError:disabled=ast.literal_eval(disabled)
        if not isinstance(disabled,list) or not all(isinstance(v,str) for v in disabled):return False
        return {'browser','browser-use'} <= set(disabled)
    except Exception:return False


def require_browser_route(config,native_browser_disabled):
    if not selected_browser(config):
        raise RuntimeError('browser_provider_not_selected: no browser action sent')
    if not native_browser_disabled:
        raise RuntimeError('browser_native_tools_enabled: disable browser and browser-use in agent.disabled_toolsets; no browser action sent')
    # Current Hermes has one core browser tool and its picker no longer writes
    # backend. Retain compatibility with the older explicit browser-use value.
    if config.get('backend') not in (None,'browser-use'):
        raise RuntimeError('browser_backend_unsupported: selected legacy backend is unsupported; no browser action sent')


def require_call_identity(value,name):
    if not isinstance(value,str) or not value.strip():
        raise RuntimeError('browser_identity_required: '+name+' must identify the calling agent; no browser action sent')


def _execution_policy():
    if __package__:
        from . import execution_policy
    else:
        import execution_policy
    return execution_policy


def _consent_guard(data):
    if __package__:
        from .consent import consent_guard
    else:
        from consent import consent_guard
    return consent_guard(data)


def _emit_diagnostic(sink,result):
    """Optional operator-only callback; never part of a tool schema/result."""
    if not callable(sink) or not isinstance(result,dict) or result.get('success') is True:return
    diagnostic={}
    if isinstance(result.get('error'),str):diagnostic['error']=result['error'][:800]
    if isinstance(result.get('error_type'),str):diagnostic['error_type']=result['error_type'][:80]
    if isinstance(result.get('uncertain'),bool):diagnostic['uncertain']=result['uncertain']
    try:sink(diagnostic)
    except Exception:pass # Diagnostics never change execution, outcome, or retry behavior.


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


def accessibility_trusted():
    # Read-only TCC probe. Never use AXIsProcessTrustedWithOptions (which can prompt).
    ax=ctypes.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
    ax.AXIsProcessTrusted.restype=ctypes.c_bool
    ax.AXIsProcessTrusted.argtypes=[]
    return bool(ax.AXIsProcessTrusted())


def chrome_gui_snapshot():
    if __package__:
        from .gui_status import chrome_gui_snapshot as snapshot
    else:
        from gui_status import chrome_gui_snapshot as snapshot
    return snapshot(PERSONAL,chrome_executable)


def status_snapshot(ctx):
    checks={name:False for name in ('settings_readable','account_configured','account_approved',
        'browser_config_readable','provider_selected','browser_backend_supported','native_browser_tools_disabled',
        'profile_identity_verified','gui_identity_ready','accessibility_trusted')}
    failures=[]
    try:
        account=expected_account(ctx.get_config)
        checks['settings_readable']=True
        checks['account_configured']=isinstance(account,str) and bool(account.strip())
        checks['account_approved']=checks['account_configured'] and account.strip().casefold()==APPROVED_ACCOUNT
        if not checks['account_configured']:failures.append('account_binding_unconfigured')
        elif not checks['account_approved']:failures.append('account_binding_not_approved')
    except Exception:
        failures.append('plugin_settings_unavailable')
    try:
        config=browser_config()
        checks['browser_config_readable']=True
        checks['provider_selected']=selected_browser(config)
        checks['browser_backend_supported']=config.get('backend') in (None,'browser-use')
        if not checks['provider_selected']:failures.append('browser_provider_not_selected')
        if not checks['browser_backend_supported']:failures.append('browser_backend_unsupported')
    except Exception:
        failures.append('browser_configuration_unavailable')
    try:checks['native_browser_tools_disabled']=native_browser_tools_disabled()
    except Exception:pass
    if not checks['native_browser_tools_disabled']:failures.append('browser_native_tools_enabled')
    if checks['account_approved']:
        try:
            verify_account(PERSONAL,account)
            checks['profile_identity_verified']=True
        except Exception:failures.append('account_binding_mismatch')
    try:
        gui_identity()
        checks['gui_identity_ready']=True
    except Exception:failures.append('safe_GUI_launch_unavailable')
    try:checks['accessibility_trusted']=accessibility_trusted()
    except Exception:pass
    if not checks['accessibility_trusted']:failures.append('consent_accessibility')
    return {'plugin':NAME,'status_version':3,'loaded_policy':'bounded-browser-script-v1',
        'ready':all(checks.values()),'checks':checks,'failures':failures,
        'chrome_gui':chrome_gui_snapshot(),
        'process':{'pid':os.getpid(),'executable':sys.executable},
        'accessibility_scope':'current process only; other processes and launch contexts are not verified',
        'browser_connection':'not_probed','terminal_tool_required':False,'secret_output_filter':False}


def register_status_command(ctx):
    def setup(parser):
        parser.add_argument('action',nargs='?',choices=['status'],default='status')
        parser.add_argument('--json',action='store_true',dest='json_output',help='Print structured readiness checks')
    def handler(args):
        status=status_snapshot(ctx)
        if args.json_output:print(json.dumps(status,sort_keys=True))
        else:
            print('Original Chrome: '+('ready for browser connection' if status['ready'] else 'not ready'))
            for name,value in status['checks'].items():print('  '+name+': '+('yes' if value else 'no'))
            if status['failures']:print('Reasons: '+', '.join(status['failures']))
            print('Accessibility applies to this process only. Browser connection was not tested.')
        return 0 if status['ready'] else 1
    ctx.register_cli_command(name='original-chrome',help='Inspect original Chrome plugin readiness without connecting',
        description='Read-only profile, browser route, GUI identity and Accessibility status.',setup_fn=setup,handler_fn=handler)
    def slash_handler(raw_args=''):
        return json.dumps(status_snapshot(ctx),sort_keys=True)
    ctx.register_command(name='original-chrome-status',handler=slash_handler,
        description='Read-only original Chrome readiness and Accessibility in this Hermes process')


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
    def __init__(self, data=None, workspace=None, *, get_setting=None,
                 read_browser_config=None, native_browser_disabled=None, source_root=None):
        self.data=Path(data or PERSONAL).resolve()
        self._get_setting=get_setting
        self._read_browser_config=read_browser_config
        self._native_browser_disabled=native_browser_disabled
        self._workspace_source=workspace if workspace is not None else Path(os.environ.get('HERMES_HOME') or Path.home()/'.hermes')/'cache/scratch/native-chrome-work'
        # Source injection is for fixed operator/offline removal fixtures only;
        # registered production never takes it from configuration or agent input.
        self.source_root=Path(source_root or ROOT)
        self.states={};self.lock=threading.RLock();self.last_cleanup={};self.last_sessions={}
        self._session_locks={};self._task_active={};self._closing_tasks={};self._unloading=False
        self._setup_lock=threading.RLock()
        self._ownership_journal=None
        self._runtime_snapshot=None;self._resource_watch=None;self._observer_type=None

    @property
    def workspace(self):
        # Resolving the public durable-state directory belongs to actual work,
        # not discovery. A registration-only host need not create/read state.
        with self.lock:
            if callable(self._workspace_source):
                self._workspace_source=Path(self._workspace_source())
            return Path(self._workspace_source)

    @workspace.setter
    def workspace(self,value):
        self._workspace_source=value

    def _runtime(self):
        with self.lock:
            if self._runtime_snapshot is None:
                if __package__:
                    from .runtime_snapshot import RuntimeSnapshot
                    from .observer import ScopedObserver
                else:
                    from runtime_snapshot import RuntimeSnapshot
                    from observer import ScopedObserver
                self._runtime_snapshot=RuntimeSnapshot(self.source_root,self.workspace/'runtime')
                # Import trusted parent cleanup dependencies before source can
                # disappear; importing creates no connection or GUI object.
                self._observer_type=ScopedObserver
            return self._runtime_snapshot

    def _start_resource_watch(self):
        if __package__:
            from .resource_watch import SourceRemovalWatch
        else:
            from resource_watch import SourceRemovalWatch
        with self.lock:
            if self._unloading:raise RuntimeError('session_cleanup_in_progress: no launch sent')
            if not self.states:return
            if self._resource_watch is None:
                self._resource_watch=SourceRemovalWatch((self.source_root/'plugin.yaml',self.source_root/'worker.py'),self.unload)
                self._resource_watch.start()

    def _stop_idle_watch(self):
        with self.lock:
            if self.states:return
            watch=self._resource_watch;self._resource_watch=None
        if watch is not None:watch.stop()

    def _journal(self):
        with self.lock:
            if self._ownership_journal is None:
                if __package__:
                    from .ownership_journal import OwnershipJournal
                else:
                    from ownership_journal import OwnershipJournal
                self._ownership_journal=OwnershipJournal(self.workspace/'ownership',self.data)
            return self._ownership_journal

    def _checkpoint(self,entry,state):
        # Write provenance before acknowledging the worker's next CDP command.
        # A failed durable write fails closed rather than forgetting ownership.
        from contextlib import nullcontext
        observer=entry.get('observer')
        tracked=isinstance(getattr(observer,'confirmed_absent',None),set)
        with observer._lock if tracked else nullcontext():
            try:
                previous=entry.get('state') or {}
                if tracked:
                    if not isinstance(state,dict) or not isinstance(state.get('owned',{}),dict):
                        raise RuntimeError('ownership_checkpoint_invalid')
                    old_owned=previous.get('owned',{})
                    context=previous.get('context')
                    if old_owned and context is not None and state.get('context') not in (None,context):
                        raise RuntimeError('ownership_context_changed')
                    absent=observer.confirmed_absent
                    owned={target:window for target,window in state.get('owned',{}).items() if target not in absent}
                    for target,window in old_owned.items():
                        if target in absent:continue
                        current=owned.get(target)
                        if current is not None and window is not None and current!=window:
                            raise RuntimeError('window_binding_changed')
                        if target not in owned or window is not None:owned[target]=window
                    pending={target:phase for target,phase in state.get('pending_closes',{}).items() if target in owned}
                    for target,phase in previous.get('pending_closes',{}).items():
                        if target in owned and target not in observer.rejected_closes:
                            if phase=='acknowledged' or target not in pending:pending[target]=phase
                    # Keep the exact object used by a callback; _attached may
                    # continue updating its owned mapping after this returns.
                    if state is previous:
                        state.setdefault('owned',{}).clear();state['owned'].update(owned)
                    else:
                        state=copy.deepcopy(state);state['owned']=owned
                    if context is not None and owned:state['context']=context
                    if pending:state['pending_closes']=pending
                    else:state.pop('pending_closes',None)
                    if state.get('current') in absent:state.pop('current',None)
                    # A worker snapshot cannot erase the original manual-tab
                    # baseline while parent observation has advanced.
                    if previous.get('baseline'):
                        state['baseline']=sorted(set(previous['baseline'])|set(state.get('baseline',[])))
                    if observer.state is previous:observer.state=state
                entry['state']=state
                if entry.get('journal_id'):
                    # The journal exists before observer callbacks are installed.
                    # Never take provider.lock while holding the observer lock.
                    self._ownership_journal.checkpoint(entry['journal_id'],state)
            except Exception:
                if observer is not None:
                    try:observer.close()
                    except Exception:pass
                raise

    def _complete_record(self,entry):
        if entry.get('journal_id'):
            self._journal().checkpoint(entry['journal_id'],entry.get('state') or {})
            self._journal().complete(entry['journal_id'])
            entry.pop('journal_id',None)

    def _endpoint_identity(self):
        """Read-only proof for the original root and current Chrome generation."""
        import psutil
        port_file=self.data/'DevToolsActivePort'
        lines=port_file.read_text().splitlines()
        port=int(lines[0]);path=lines[1]
        if not 0<port<65536 or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9_-]+',path):
            raise ValueError('invalid port file')
        owners=[]
        for process in psutil.process_iter():
            try:
                info=process.as_dict(attrs=['name','exe','cmdline','create_time'])
                if info['name']!='Google Chrome':continue
                args=info['cmdline'] or []
                root=Path(next((a.split('=',1)[1] for a in args if a.startswith('--user-data-dir=')),str(PERSONAL))).resolve()
                if root!=self.data or not chrome_executable(info['exe']):continue
                started=info['create_time']
                if port_file.stat().st_mtime<started:continue
                if any(c.status=='LISTEN' and c.laddr.port==port and c.laddr.ip in {'127.0.0.1','::1'} for c in process.net_connections(kind='tcp')):
                    if process.create_time()==started:owners.append((process.pid,started))
            except psutil.NoSuchProcess:continue
        if len(owners)!=1 or port_file.read_text().splitlines()!=lines:
            raise ValueError('endpoint not published by current browser generation')
        return {'pid':owners[0][0],'started':owners[0][1],
                'endpoint':f'ws://127.0.0.1:{port}{path}'}

    def require_ready(self):
        # Explicit non-personal roots are disposable fixture injection points.
        # Registration never accepts a root override from configuration or code.
        if self.data!=PERSONAL.resolve():return
        account=expected_account(self._get_setting)
        if not isinstance(account,str) or not account.strip():
            raise RuntimeError('account_binding_unconfigured: configure the approved Default account; no Chrome launch')
        if account.strip().casefold()!=APPROVED_ACCOUNT:
            raise RuntimeError('account_binding_not_approved: configured account is outside this plugin scope; no Chrome launch')
        if not callable(self._read_browser_config) or not callable(self._native_browser_disabled):
            raise RuntimeError('browser_policy_unconfigured: production provider requires explicit host policy; no Chrome launch')
        require_browser_route(self._read_browser_config(),self._native_browser_disabled())
        verify_account(self.data,account)

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
        self.require_ready()
        if self.data==PERSONAL.resolve() and not accessibility_trusted():
            raise RuntimeError('accessibility_permission_required: Hermes runtime cannot inspect Chrome windows; no browser launched')
        if self.data==PERSONAL.resolve():
            try:
                enabled=json.loads((self.data/'Local State').read_text()).get('devtools',{}).get('remote_debugging',{}).get('user-enabled') is True
            except (OSError,ValueError,TypeError,AttributeError):enabled=False
            if not enabled:
                raise RuntimeError('Chrome_endpoint_disabled: enable remote debugging in Chrome settings; no window launched')
        # GUI explicitly selects Default BEFORE CDP work; never scan other contexts.
        # Prepare cleanup code before any window can exist. Official uninstall
        # may remove the source tree before runtime unload is dispatched.
        self._runtime().ensure()
        self._start_resource_watch()
        record=self._journal().begin_seed()
        entry['journal_id']=record['id']
        seed_url=record['seed_url']
        entry['_checkpoint']=lambda state:self._checkpoint(entry,state)
        # Setup authority belongs to this entry before launch, never a mutable
        # provider-wide active-entry/seed selected by a concurrent caller.
        entry['state']={'pending_seed':seed_url,'owned':{},'verified':False}
        with self.lock:
            if self._unloading:
                # No GUI request has been issued, so this exact unused marker
                # can be retired without inferring absence from a screenshot.
                self._ownership_journal.retire(entry['journal_id'],seed_absent=True)
                entry.pop('journal_id',None);entry['state']=None
                raise RuntimeError('session_cleanup_in_progress: no GUI launch sent')
        gui_launch(self.data,seed_url)
        import psutil
        deadline=time.monotonic()+20;waiting_for_seed=False
        while time.monotonic()<deadline:
            try:
                identity=self._endpoint_identity()
                entry['generation']=identity
                entry['endpoint']=identity['endpoint']
                self._journal().bind_generation(record['id'],identity)
                waiting_for_seed=True
                if not seed_window_ready(identity['pid'],seed_url):
                    time.sleep(.05);continue
                # AX readiness may take time; do not return a replaced endpoint.
                if self._endpoint_identity()!=identity:
                    raise ValueError('endpoint changed during window readiness')
                return identity['endpoint']
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
        try:observer.close_disposable_browser(state) # Parent-only disposable-root shutdown.
        except Exception as exc:error=type(exc).__name__
        import psutil
        _,alive=psutil.wait_procs(processes,timeout=5)
        if alive or (error and not processes):
            return {'browser_closed':False,'browser_close_error':error or 'Chrome_process_still_running'}
        observer.close()
        return {'browser_closed':True}

    def _prepare_observer(self,entry,cleanup=False):
        """Serialize new connections with GUI setup; held page work stays parallel."""
        observer=entry.get('observer')
        if observer is not None and not (cleanup and observer.closed):return observer
        with self._setup_lock,_consent_guard(self.data):
            observer=entry.get('observer')
            if observer is not None and not (cleanup and observer.closed):return observer
            if observer is not None:
                entry.pop('observer') # Cleanup may reconnect; ordinary work never does.
            if not entry.get('endpoint'):raise RuntimeError('browser_endpoint_unavailable')
            self._runtime()
            observer=self._observer_type(entry['endpoint'],str(self.data/'Default'))
            entry['observer']=observer
            if hasattr(observer,'bind'):observer.bind(entry)
            return observer

    def _worker(self,request,timeout:float=300,*,entry):
        with self._runtime().worker() as worker_path:
            return self._run_worker(request,timeout,entry=entry,worker_path=worker_path)

    def _run_worker(self,request,timeout,*,entry,worker_path):
        # Preserve completed observations even if the worker dies before its
        # final result. Protocol frames are never exposed as browser content.
        frames=[];errors=[]
        entry['partial_stdout']=''
        proxied=bool(request.get('endpoint'))
        if proxied:
            if entry.get('endpoint') not in (None,request['endpoint']):
                raise RuntimeError('browser_endpoint_changed: no connection opened')
            entry.setdefault('endpoint',request['endpoint'])
            if entry.get('endpoint') is None:entry['endpoint']=request['endpoint']
            self._prepare_observer(entry,cleanup=bool(request.get('cleanup')))
            request=dict(request,parent_transport=True)
        with self.lock:
            if self._unloading and not request.get('cleanup'):
                raise RuntimeError('session_cleanup_in_progress: no browser worker started')
            proc=subprocess.Popen([sys.executable,'-B',str(worker_path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
            entry['_worker_proc']=proc;entry['_worker_cleanup']=bool(request.get('cleanup'))
        assert proc.stdin is not None and proc.stdout is not None
        def read():
            assert proc.stdin is not None and proc.stdout is not None
            try:
                for line in proc.stdout:
                    frame=json.loads(line)
                    if 'checkpoint' in frame:self._checkpoint(entry,frame['checkpoint'])
                    elif 'progress' in frame:
                        progress=frame['progress']
                        if not isinstance(progress,dict) or not isinstance(progress.get('stdout'),str):
                            raise RuntimeError('invalid worker progress')
                        entry['partial_stdout']=progress['stdout'][-20000:]
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
            if entry.get('_worker_proc') is proc:
                entry.pop('_worker_proc',None);entry.pop('_worker_cleanup',None)
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
        sink=kwargs.get('_diagnostic_sink')
        def finish(result):
            _emit_diagnostic(sink,result)
            return json.dumps(result)
        try:
            if self.data==PERSONAL.resolve():require_call_identity(task_id,'task_id')
            self.require_ready()
            _execution_policy().validate_source(args.get('code',''))
            key=self._key(args,task_id)
        except Exception as exc:
            return finish({'success':False,'error':str(exc),'error_type':type(exc).__name__,'fallback_used':False,'action_replayed':False})
        with self.session_guard(key) as generation:
            token=object()
            with self.lock:
                if self._unloading or self._closing_tasks.get(key[0]) or self._session_locks[key][2] is not generation:
                    return finish({'success':False,'error':'session_cleanup_in_progress: no action sent','action_replayed':False,'fallback_used':False})
                self.last_sessions.pop(key[0],None)
                self._task_active.setdefault(key[0],set()).add(token)
            result={}
            try:
                result=self._execute_session(args,key)
                return finish(result)
            finally:
                with self.lock:
                    active=self._task_active[key[0]];active.discard(token)
                    if not active:self._task_active.pop(key[0])
                    entry=self.states.get(key) or {}
                    if not active and result.get('success') and not entry.get('uncertain') and (entry.get('state') or {}).get('owned'):
                        self.last_sessions[key[0]]=key[1]
                    else:self.last_sessions.pop(key[0],None)
                self._stop_idle_watch()

    def _execute_session(self,args,key):
        if __package__:
            from .recovery import recovery_plan
        else:
            from recovery import recovery_plan
        started=time.monotonic()
        try:budget=max(5,min(1800,int(args.get('timeout_s',300))))
        except (TypeError,ValueError):budget=300
        result=self._execute_attempt(args,key)
        retries=0
        with self.lock:entry=self.states.get(key)
        observer=(entry or {}).get('observer')
        state=(entry or {}).get('state') or {}
        plan=recovery_plan(args.get('code',''),result,remaining_s=budget-(time.monotonic()-started),
            session_verified=state.get('verified') is True and bool(state.get('owned')),
            transport_usable=observer is not None and not observer.closed)
        if plan['action']=='retry_read':
            # This is the same positively bound session and held observer. No
            # navigation, inputs, reconnect, or setup is authorized by this retry.
            previous=result.get('stdout','')
            entry['uncertain']=False
            retry_args=dict(args,timeout_s=int(plan['retry_timeout_s']))
            result=self._execute_attempt(retry_args,key);retries=1
            if previous:result['stdout']=(previous+'\n'+result.get('stdout',''))[-20000:]
            plan=recovery_plan(args.get('code',''),result,attempts=1)
            if result.get('success'):
                result['recovery']={'status':'read_retry_succeeded','read_retry_count':1,
                    'partial_output_preserved':bool(result.get('stdout')),'session':key[1]}
                return result
        if plan['action']=='none':return result
        if plan['action'] in {'fresh_session','operator_attention'}:
            # Reclaim only this session, once. Do not open a replacement window
            # until the agent actually chooses its next research step.
            cleanup_complete=self.close_session(key[0],session=key[1])
            status=('operator_attention' if plan['action']=='operator_attention' else
                    'fresh_session_ready' if cleanup_complete else 'fresh_session_required')
            result['recovery']={'status':status,'cleanup_complete':cleanup_complete,
                'read_retry_count':retries,'partial_output_preserved':bool(result.get('stdout')),'session':key[1]}
        else:
            result['recovery']={'status':plan['action'],'read_retry_count':retries,
                'partial_output_preserved':bool(result.get('stdout')),'session':key[1]}
        return result

    def _execute_attempt(self,args,key):
        endpoint=None
        with self.lock:entry=self.states.get(key)
        try:
            self.require_ready()
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
                # A new GUI seed must not steal focus while another connection
                # is waiting on its debug dialog. Keep launch and attach in one
                # shared critical section; release it before worker page I/O.
                with self._setup_lock:
                    self._recover_orphans()
                with self._setup_lock,_consent_guard(self.data):
                    entry:dict={'endpoint':None,'state':None}
                    with self.lock:self.states[key]=entry
                    entry['endpoint']=self.endpoint(entry=entry)
                    self._prepare_observer(entry)
            endpoint=entry['endpoint']
            workspace=self.workspace/str(abs(hash(key)))
            request={'endpoint':endpoint,'profile':str(self.data/'Default'),'workspace':str(workspace),'state':entry['state'],'code':args.get('code','')}
            result=self._worker(request,timeout,entry=entry)
            if result.get('state'):self._checkpoint(entry,result.pop('state'))
            current=entry.get('state') or {}
            empty=(not current.get('owned') and not current.get('pending_seed')
                   and not current.get('unresolved_creation') and not current.get('pending_closes'))
            if entry.get('observer') and (current.get('observer_released') or empty):
                self._release_observer(entry)
                if empty:
                    self._complete_record(entry)
                    with self.lock:self.states.pop(key,None)
                    self._stop_idle_watch()
                elif current.get('observer_released') and result.get('success'):
                    # A popup may have been recorded by the parent after the
                    # worker's final cleanup snapshot. Its success cannot erase
                    # that ownership or claim all windows have disappeared.
                    result.update(success=False,error='cleanup_outcome_unknown: additional owned targets remain',uncertain=True)
                    result['stdout']=result.get('stdout','')+'\nCleanup confirmation changed; see recovery.cleanup_complete.\n'
            if result.get('uncertain') or (not result.get('success') and (entry.get('state') or {}).get('verified') is False):
                entry['uncertain']=True
            result['fallback_used']=False
            result['limitations']=['Browser scripts use a bounded data interpreter and named helpers; this does not confine other Hermes tools or installed host code','Only owned roots and related targets are observed; no browser-wide page auto-attach; uniquely bound early popup dialogs use native AX with an explicit answer; ambiguous native bindings or unavailable Accessibility refuse; dialog_pending requires explicit answer, never action replay; observer loss fails without reconnect','Vault page actions are unavailable; list and unlock use only the captured registered native handler','Only opener-linked popups tracked; automatic cleanup on completed or failed turns, finalization and interruption; pending host human-input waits are preserved','New tabs use separate owned windows','Ambiguous or uncorrelated consent prompts report failure']
            return result
        except subprocess.TimeoutExpired:
            if entry:entry['uncertain']=True
            return {'success':False,'error':'browser_exec_timeout: action outcome uncertain; no actions replayed',
                'stdout':(entry or {}).get('partial_stdout',''),'uncertain':True,'fallback_used':False,'action_replayed':False}
        except Exception as exc:
            if entry:
                entry['uncertain']=True
                self._release_observer(entry)
            return {'success':False,'error':str(exc),'error_type':type(exc).__name__,
                'stdout':(entry or {}).get('partial_stdout',''),'uncertain':bool(entry and entry.get('uncertain')),'fallback_used':False,'action_replayed':False}
    def create_session(self,task_id):
        # This provider cannot safely hand its browser-wide endpoint to legacy target selection.
        raise RuntimeError('Use browser_original_chrome_exec; native browser_* attachment is not safe')

    def _recover_orphans(self):
        # Registration/import never connects to Chrome. The next real browser
        # call may recover abandoned leases in this profile's private journal.
        if not (self.workspace/'ownership').is_dir():return
        journal=self._journal()
        for record in journal.eligible_records()[:4]:
            record=journal.claim(record['id'])
            state=copy.deepcopy(record['state'])
            if record['phase']=='seed':state['pending_seed']=record['seed_url']
            key=('recovered-'+record['id'],'default')
            entry={'state':state,'endpoint':None,'journal_id':record['id'],
                   'generation':record['generation'],'uncertain':True}
            entry['_checkpoint']=lambda value,entry=entry:self._checkpoint(entry,value)
            with self.lock:self.states[key]=entry
            self.close_session(key[0],session=key[1])

    def _cleanup_entry(self,entry):
        generation=entry.get('generation')
        if generation:
            # Chrome may have been quit by its user. A PID reuse is a different
            # generation; never reconnect or send old target IDs to it.
            import psutil
            try:gone=psutil.Process(generation['pid']).create_time()!=generation['started']
            except psutil.NoSuchProcess:gone=True
            if gone:
                if entry.get('journal_id'):
                    self._journal().retire(entry['journal_id'],generation_gone=True)
                    entry.pop('journal_id',None)
                entry['state']={'owned':{},'verified':False}
                return {'success':True,'cleanup_complete':True,'browser_generation_ended':True}
        state=entry.get('state') or {}
        if entry.get('journal_id'):
            if not generation and not self._chrome_processes():
                # A timed-out GUI launch may publish its process/window later.
                # This snapshot cannot prove that no launch was ever attempted.
                return {'success':False,'cleanup_complete':False,
                        'error':'seed_launch_outcome_unconfirmed: ownership retained; no cleanup command sent'}
            current=self._endpoint_identity()
            if __package__:
                from .ownership_journal import browser_generation
            else:
                from ownership_journal import browser_generation
            if generation and browser_generation(generation)!=browser_generation(current):
                return {'success':False,'error':'ownership_generation_changed: no cleanup command sent'}
            entry['generation']=current;entry['endpoint']=current['endpoint']
            self._journal().bind_generation(entry['journal_id'],current)
        if not state or not entry.get('endpoint'):
            if not state and not entry.get('journal_id') and not entry.get('endpoint'):
                return {'success':True,'cleanup_complete':True,'no_window_launched':True}
            return {'success':False,'error':'ownership_lost_after_timeout: no targets adopted for cleanup'}
        result=self._worker({'endpoint':entry['endpoint'],'state':state,'profile':str(self.data/'Default'),
            'workspace':str(self.workspace),'cleanup':True},30,entry=entry)
        if result.get('seed_absent'):
            # Compatibility defense for an older worker: absence of a marker
            # once is not evidence that a delayed/navigated owned seed is gone.
            return {'success':False,'cleanup_complete':False,
                    'error':'seed_ownership_unresolved: marker absence is not cleanup confirmation'}
        if isinstance(result.get('state'),dict):self._checkpoint(entry,result.pop('state'))
        if result.get('success'):
            self._complete_record(entry)
        return result

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
                        result=self._cleanup_entry(entry)
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
            self._stop_idle_watch()
    def emergency_cleanup(self,session_id):self.close_session(session_id)
    def unload(self):
        with self.lock:
            if self._unloading:return
            self._unloading=True
            tasks={key[0] for key in self.states}|set(self._task_active)
            entries=list(self.states.values());watch=self._resource_watch
        if watch is not None:watch.stop()
        # Stop only our bounded script processes, never Chrome or another agent.
        # Their latest checkpoints remain the sole cleanup authority.
        for entry in entries:
            proc=entry.get('_worker_proc')
            if proc is not None and not entry.get('_worker_cleanup'):
                entry['uncertain']=True
                try:proc.kill()
                except ProcessLookupError:pass
        try:
            for task in sorted(tasks):self.close_session(task)
        finally:
            # Failed cleanup remains durable. A later activation can claim only
            # these explicitly released records, never another live provider.
            if self._ownership_journal is not None:self._ownership_journal.release_all()
            if self._runtime_snapshot is not None:self._runtime_snapshot.close()


class BrowserLifecycle:
    """Release owned windows at a finished agent turn; preserve host human waits.

    A completed turn is not proof that a larger project is over. The explicit
    policy is short-lived browser windows: a later turn gets a fresh session,
    while the original Chrome profile and its login remain shared and intact.
    """
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
        reports=self._cleanup(tasks,'session_finalized')
        if any(not report['success'] for report in reports):
            return {'message':'Some browser tabs could not be confirmed closed.'}
    def cancel(self,session_key=None,**kwargs):
        with self.provider.lock:
            tasks=[task for task,ids in self.bindings.items() if session_key and ids['session_key']==str(session_key)]
        return self._cleanup(tasks,'cancelled') or None
    def turn_end(self,task_id=None,session_id=None,interrupted=False,completed=False,failed=False,**kwargs):
        with self.provider.lock:
            ids=self.bindings.get(str(task_id))
            if not ids or ids['session_id']!=str(session_id):return
            if not interrupted and self.pending.get(str(session_id)):
                return {'cleanup_deferred':True,'reason':'pending_human_input'}
            if not (interrupted or completed or failed):
                return {'cleanup_deferred':True,'reason':'turn_still_active'}
        return self._cleanup([str(task_id)],'interrupted' if interrupted else 'turn_failed' if failed else 'turn_completed')
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
        if failures:return str(response_text)+'\n\nSome browser tabs could not be confirmed closed.'


def register(ctx):
    register_status_command(ctx)
    if __package__:
        from . import selftest
        from .public_result import model_result
    else:
        import selftest
        from public_result import model_result

    def route_guard(tool_name,args=None,**kwargs):
        if not isinstance(tool_name,str) or not tool_name.startswith('browser_') or tool_name in {EXEC_TOOL,VAULT_TOOL}:return
        try:
            if not selected_browser(browser_config()):return
        except Exception:
            return {'action':'block','message':'Browser configuration unavailable; no browser action sent.'}
        return {'action':'block','message':'Use browser_original_chrome_exec for browser actions; native browser tools are disabled.'}

    # The official host exclusions remain the guard when this plugin is absent.
    # While loaded, refuse native routes even if a session held an older schema.
    ctx.register_hook('pre_tool_call',route_guard)
    browser_schema=json.loads((ROOT/'browser_schema.json').read_text())
    browser_schema['name']=EXEC_TOOL
    provider=ChromeProvider(workspace=lambda:ctx.state.data_dir/'browser-work',
        get_setting=ctx.get_config,read_browser_config=browser_config,
        native_browser_disabled=native_browser_tools_disabled)
    lifecycle=BrowserLifecycle(ctx,provider);lifecycle.register()
    ctx.on_unload(provider.unload)

    def publish_result(result,cleanup_reports=()):
        # Operator explicitly chose unfiltered page text. Keep the model-result
        # allowlist and error minimization, without importing a private redactor.
        public=model_result(result,cleanup_reports)
        return public if public.get('_multimodal') else json.dumps(public)

    def handler(args,**kw):
        diagnostic_sink=kw.pop('_diagnostic_sink',None)
        def refused(result):
            _emit_diagnostic(diagnostic_sink,result)
            return publish_result(result)
        try:
            require_browser_route(browser_config(),native_browser_tools_disabled())
            require_call_identity(kw.get('task_id'),'task_id')
            require_call_identity(kw.get('session_id'),'session_id')
        except Exception as exc:
            return refused({'success':False,'error':str(exc),'error_type':type(exc).__name__,
                'fallback_used':False,'action_replayed':False})
        try:
            from gateway.session_context import get_session_env
            session_key=kw.get('session_key') or get_session_env('HERMES_SESSION_KEY','')
        except Exception:
            return refused({'success':False,'error':'browser_configuration_unavailable: session context unavailable',
                'fallback_used':False,'action_replayed':False})
        lifecycle.bind(**dict(kw,session_key=session_key))
        result=json.loads(provider.execute(args,**kw,_diagnostic_sink=diagnostic_sink))
        return publish_result(result,lifecycle.status(kw.get('session_id')))

    ctx.register_browser_provider(provider)
    ctx.register_tool(name=EXEC_TOOL,toolset=TOOLSET,
        schema=_execution_policy().apply_browser_schema(browser_schema),handler=handler)
    selftest.register(ctx,provider,handler,lambda:status_snapshot(ctx),
        lambda session_id:lifecycle.finalize(session_id=session_id))

    # Public dispatch preserves the host vault's own approvals and credentials.
    # No native handler capture and no page action can attach to a foreign tab.
    schema=json.loads((ROOT/'vault_schema.json').read_text())
    schema['name']=VAULT_TOOL
    def unavailable(kind='vault_handler_unavailable'):
        return json.dumps({'success':False,'error_type':kind,
            'error':'Vault operation unavailable for this browser; no fallback or replay.',
            'fallback_used':False,'action_replayed':False})
    def guarded(args,**kw):
        try:
            require_browser_route(browser_config(),native_browser_tools_disabled())
            if args.get('action') not in ('list','unlock'):
                return unavailable('vault_page_actions_unavailable')
            raw=ctx.dispatch_tool('browser_vault',args,**kw)
            if args.get('action')=='list':
                result=json.loads(raw)
                if isinstance(result,dict) and result.get('success') is True:
                    # Native help refers to tools/page actions unavailable here.
                    # Adapt only those control fields; item metadata stays intact.
                    if 'hint' in result:
                        result['hint']='No saved vault items are available. Saving or filling credentials is unavailable in this browser tool.'
                    locked=result.get('locked')
                    if isinstance(locked,list):
                        for item in locked:
                            if isinstance(item,dict) and item.get('unlock')=='browser_vault action=unlock':
                                item['unlock']=VAULT_TOOL+' action=unlock'
                    result['page_actions_available']=False
                    return json.dumps(result)
            return raw
        except Exception:
            # Handler errors may contain credential arguments; do not expose
            # exception text or attempt another entry point.
            return unavailable()
    ctx.register_tool(name=VAULT_TOOL,toolset=TOOLSET,schema=schema,handler=guarded)
