"""Original headed Chrome provider and public browser_exec override. No core mutation."""
import copy, ctypes, json, os, re, secrets, subprocess, sys, threading, time
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


def gui_launch(data,seed_url=None):
    manager=subprocess.run(['/bin/launchctl','managername'],capture_output=True,text=True,timeout=5)
    security=ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
    sid=ctypes.c_uint32();attrs=ctypes.c_uint32()
    status=security.SessionGetInfo(ctypes.c_uint32(0xffffffff),ctypes.byref(sid),ctypes.byref(attrs))
    if manager.stdout.strip()!='Aqua' or status or not attrs.value & 0x10 or os.stat('/dev/console').st_uid!=os.getuid():
        raise RuntimeError('safe_GUI_launch_unavailable: run Hermes in the unlocked logged-in Aqua session; Chrome not launched')
    args=['/usr/bin/open','-n','-a',str(CHROME),'--args',f'--user-data-dir={data}','--profile-directory=Default']
    if data.resolve()!=PERSONAL.resolve():args+=['--remote-debugging-port=0','--no-first-run','--no-default-browser-check']
    if seed_url:args+=['--new-window',seed_url]
    subprocess.run(args,capture_output=True,text=True,timeout=15,check=True)


class ChromeProvider(BrowserProvider):
    name=NAME
    display_name='Original headed Chrome · Default'
    def __init__(self, data=None, workspace=None):
        self.data=Path(data or PERSONAL).resolve()
        self.workspace=Path(workspace or Path.home()/'.hermes/cache/scratch/native-chrome-work')
        self.states={};self.lock=threading.RLock();self.last_cleanup={};self.last_sessions={}
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
        gui_launch(self.data,self.seed_url)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            try:
                lines=(self.data/'DevToolsActivePort').read_text().splitlines()
                port=int(lines[0]);path=lines[1]
                if not 0<port<65536 or not path.startswith('/devtools/browser/'):raise ValueError('invalid port file')
                return f'ws://127.0.0.1:{port}{path}'
            except (OSError,ValueError,IndexError):time.sleep(.2)
        raise RuntimeError('Chrome_endpoint_unavailable: enable chrome://inspect/#remote-debugging; no headless fallback used')
    def _key(self,args,task_id):
        session=args.get('session') or 'default'
        if not re.fullmatch('[A-Za-z0-9_-]{1,64}',session):raise ValueError('invalid session name')
        return (str(task_id or 'default'),session)
    def _worker(self,request,timeout=300):
        proc=subprocess.run([sys.executable,str(ROOT/'worker.py')],input=json.dumps(request),capture_output=True,text=True,timeout=timeout)
        if proc.returncode:raise RuntimeError('browser_worker_failed: '+proc.stderr[-500:])
        return json.loads(proc.stdout)
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
                endpoint=entry['endpoint'] if entry else self.endpoint()
                workspace=self.workspace/str(abs(hash(key)))
                request={'endpoint':endpoint,'profile':str(self.data/'Default'),'workspace':str(workspace),'state':entry['state'] if entry else None,'seed_url':getattr(self,'seed_url',None) if not entry else None,'code':args.get('code','')}
                result=self._worker(request,timeout)
                if result.get('state'):self.states[key]={'endpoint':endpoint,'state':result.pop('state')}
                if result.get('success') and self.states.get(key,{}).get('state',{}).get('owned'):
                    self.last_sessions[key[0]]=key[1]
                result['fallback_used']=False
                result['limitations']=['No arbitrary-Python sandbox','Vault uses version-pinned exact-target adapter; native chat and real prompt acceptance pending','Only opener-linked popups tracked; automatic cleanup on session finalization/interruption, not ordinary turn completion; use finish_browser() for explicit task finish','New tabs use separate owned windows','Consent auto-click verified on personal main Chrome and 9Router PWA; ambiguous/uncorrelated prompts report failure']
                return json.dumps(result)
            except subprocess.TimeoutExpired:
                if key is not None:
                    self.states.setdefault(key,{'endpoint':endpoint,'state':None})['uncertain']=True
                return json.dumps({'success':False,'error':'browser_exec_timeout: action outcome uncertain; no retry performed; targets may remain','fallback_used':False,'action_replayed':False})
            except Exception as exc:
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
                    if not entry.get('state'):
                        self.last_cleanup[key]={'success':False,'error':'ownership_lost_after_timeout: no targets adopted for cleanup'}
                        results.append(False);continue
                    result=self._worker({'endpoint':entry['endpoint'],'state':entry['state'],'profile':str(self.data/'Default'),'workspace':str(self.workspace),'cleanup':True},30)
                    self.last_cleanup[key]=result
                    results.append(result.get('success',False))
                    if result.get('success'):
                        self.states.pop(key)
                        if self.last_sessions.get(key[0])==key[1]:self.last_sessions.pop(key[0],None)
                except Exception as exc:
                    self.last_cleanup[key]={'success':False,'error':str(exc)};results.append(False)
            return all(results)
    def emergency_cleanup(self,session_id):self.close_session(session_id)


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
