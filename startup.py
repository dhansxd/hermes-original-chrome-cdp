"""Start the original Chrome profile and verify its CDP endpoint; never copy a profile."""
import ctypes
import json
import os
import re
import subprocess
import time
from pathlib import Path

CHROME = Path('/Applications/Google Chrome.app')
PERSONAL = Path.home() / 'Library/Application Support/Google/Chrome'


class ChromeLaunchNotDispatched(RuntimeError):
    """Chrome rejected before any window request was sent."""


def process_alive(identity):
    import psutil
    try:
        return psutil.Process(identity['pid']).create_time() == identity['started']
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, PermissionError):
        return True  # Unreadable does not mean the owned windows are gone.


def endpoint_identity(data):
    """Only accept the endpoint published by this live Chrome process."""
    import psutil
    data = Path(data).resolve()
    port_file = data / 'DevToolsActivePort'
    lines = port_file.read_text().splitlines()
    port, path = int(lines[0]), lines[1]
    if not 0 < port < 65536 or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9_-]+', path):
        raise ValueError('invalid Chrome endpoint')
    owners = []
    for process in psutil.process_iter():
        try:
            info = _chrome_process_info(process)
            if info is None:
                continue
            root = Path(next((a.split('=', 1)[1] for a in info['cmdline']
                              if a.startswith('--user-data-dir=')), str(PERSONAL))).resolve()
            if root != data or not chrome_executable(info['exe']):
                continue
            if port_file.stat().st_mtime < info['create_time']:
                continue
            if any(c.status == 'LISTEN' and c.laddr.port == port and
                   c.laddr.ip in {'127.0.0.1', '::1'} for c in process.net_connections(kind='tcp')):
                if process.create_time() == info['create_time']:
                    owners.append((process.pid, info['create_time']))
        except psutil.NoSuchProcess:
            continue
    if len(owners) != 1 or port_file.read_text().splitlines() != lines:
        raise ValueError('Chrome endpoint owner unavailable')
    return {'pid': owners[0][0], 'started': owners[0][1],
            'endpoint': f'ws://127.0.0.1:{port}{path}'}


def launch(data, profile, seed_url):
    """One GUI launch works for stopped, windowless and already-open Chrome."""
    data = Path(data).resolve()
    if data == PERSONAL.resolve():
        if not accessibility_trusted():
            raise RuntimeError('Grant Accessibility to the process running Hermes.')
        settings = json.loads((data / 'Local State').read_text())
        if settings.get('devtools', {}).get('remote_debugging', {}).get('user-enabled') is not True:
            raise RuntimeError('Enable remote debugging in chrome://inspect/#remote-debugging.')
        if profile not in settings.get('profile', {}).get('info_cache', {}):
            raise RuntimeError('The selected original Chrome profile does not exist.')
    gui_launch(data, seed_url, profile_directory=profile)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            identity = endpoint_identity(data)
            if seed_window_ready(identity['pid'], seed_url) and endpoint_identity(data) == identity:
                return identity['endpoint']
        except (OSError, ValueError, IndexError):
            pass
        time.sleep(.1)
    raise RuntimeError('Chrome did not expose the requested window and CDP endpoint; launch was not repeated.')

def _chrome_process_info(process,*,with_started=True,strict_named=False):
    """Read command arguments only for a readable, positively named Chrome PID."""
    import math,psutil
    named=False
    def unreadable():
        if strict_named and named:raise RuntimeError('chrome_process_identity_unavailable')
        return None
    try:
        if process.name()!='Google Chrome':return None
        named=True
        attrs=['name','exe','cmdline']+(['create_time'] if with_started else [])
        info=process.as_dict(attrs=attrs)
        # as_dict can suppress AccessDenied into None. Unreadable arguments
        # never mean an empty/default-root Chrome command line.
        if (info.get('name')!='Google Chrome' or not isinstance(info.get('exe'),str)
            or not info['exe'] or not isinstance(info.get('cmdline'),list)
            or any(not isinstance(arg,str) for arg in info['cmdline'])):return unreadable()
        if with_started:
            started=info.get('create_time')
            if type(started) not in (int,float) or not math.isfinite(started) or started<=0:return unreadable()
        return info
    except psutil.NoSuchProcess:return None
    except (psutil.AccessDenied,PermissionError):return unreadable()
    except SystemError as error:
        # macOS psutil may wrap a denied sysctl command-line read in a
        # SystemError. Suppress only that permission chain, never other bugs.
        cause=error.__cause__ or error.__context__
        for _ in range(8):
            if isinstance(cause,(PermissionError,psutil.AccessDenied)):return unreadable()
            if cause is None:break
            cause=cause.__cause__ or cause.__context__
        raise

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


def notify_running_chrome(data, identity, arguments):
    """Forward startup arguments to the verified Chrome singleton on macOS."""
    import errno
    import socket
    import tempfile
    address = (data / 'SingletonSocket').resolve(strict=True)
    nonce = (data / 'SingletonCookie').readlink()
    if (address.parent / 'SingletonCookie').readlink() != nonce:
        raise RuntimeError('Chrome startup socket identity is unavailable.')
    message = b'\0'.join(os.fsencode(part) for part in ['START', str(data), *arguments])
    # A short, private alias also supports Chrome's socket paths exceeding
    # Python's sockaddr_un path limit. It contains no browser/profile data.
    with tempfile.TemporaryDirectory(prefix='hermes-chrome-ipc-', dir='/tmp') as directory:
        alias = Path(directory) / 'socket'
        alias.symlink_to(address)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
            channel.settimeout(15)
            channel.connect(str(alias))
            # Darwin SOL_LOCAL / LOCAL_PEERPID identifies the connected process.
            if (channel.getsockopt(0, 0x002) != identity[0]
                    or not process_alive({'pid': identity[0], 'started': identity[1]})
                    or (data / 'SingletonCookie').readlink() != nonce
                    or (address.parent / 'SingletonCookie').readlink() != nonce):
                raise RuntimeError('Chrome startup socket identity changed.')
            channel.sendall(message)
            try:
                channel.shutdown(socket.SHUT_WR)
            except OSError as error:
                # Chrome can acknowledge and close before this half-close.
                # Its buffered ACK still determines whether startup succeeded.
                if error.errno != errno.ENOTCONN:
                    raise
            reply = b''
            while len(reply) < 8:
                part = channel.recv(8 - len(reply))
                if not part:
                    break
                reply += part
            if reply != b'ACK':
                raise RuntimeError('Chrome startup was not acknowledged; request was not replayed.')


def gui_launch(data,seed_url=None,*,profile_directory='Default'):
    if (not isinstance(profile_directory,str) or not 0<len(profile_directory)<=128
        or not profile_directory.isprintable() or profile_directory in {'.','..','Guest Profile','System Profile'}
        or '/' in profile_directory or '\\' in profile_directory):
        raise ValueError('invalid explicit Chrome profile directory')
    import psutil
    destination=gui_identity()
    def browsers(*, before_launch=False):
        found=[]
        for p in psutil.process_iter():
            try:
                info=_chrome_process_info(p,strict_named=True)
                if info is None:continue
                args=info['cmdline'] or []
                root=Path(next((a.split('=',1)[1] for a in args if a.startswith('--user-data-dir=')),str(PERSONAL))).resolve()
                if root!=data.resolve():continue
                if not chrome_executable(info['exe']) or gui_identity(p.pid)!=destination:
                    error = ChromeLaunchNotDispatched if before_launch else RuntimeError
                    raise error('safe_GUI_launch_unavailable: Chrome destination mismatch')
                found.append((p.pid,info['create_time']))
            except psutil.NoSuchProcess:continue
        return found
    running=browsers(before_launch=True)
    args=[str(CHROME/'Contents/MacOS/Google Chrome'),f'--user-data-dir={data}',f'--profile-directory={profile_directory}']
    if data.resolve()!=PERSONAL.resolve():args+=['--remote-debugging-port=0','--no-first-run','--no-default-browser-check']
    if seed_url:args+=['--new-window',seed_url]
    if running:
        if len(running)!=1:
            raise RuntimeError('safe_GUI_launch_unavailable: Chrome destination ambiguous')
        notify_running_chrome(data,running[0],args)
    else:
        env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin','TMPDIR':str(Path.home()/'.hermes/cache/scratch')}
        subprocess.run(['/usr/bin/open','-g','-a',str(CHROME),'--args',*args[1:]],
                       env=env,capture_output=True,text=True,timeout=15,check=True)
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


def close_seed_tab(data,identity,seed_url,title):
    """Close the exact startup tab when CDP attach failed before ownership discovery."""
    if not identity or not seed_url or not title:
        return False
    if __package__:
        from .consent import AX,ConsentError
    else:
        from consent import AX,ConsentError
    ax=AX()
    ax.deadline=time.monotonic()+3
    def matches():
        app=ax.ax.AXUIElementCreateApplication(identity['pid']);ax.refs.append(app)
        values=ax.attr(app,'AXWindows')
        windows=[ax.cf.CFArrayGetValueAtIndex(values,i) for i in range(ax.cf.CFArrayGetCount(values))] if values else []
        found=[];groups=[]
        def visit(node,window,depth=0):
            role=ax.text(node,'AXRole')
            if role in {'AXWebArea','AXScrollArea'}:
                return
            if role=='AXTabGroup':
                groups.append(node)
            if ax.text(node,'AXSubrole')=='AXTabButton':
                if ax.text(node,'AXTitle')==title:
                    found.append((window,node))
                return
            if depth>12:
                raise RuntimeError('Startup tab tree is incomplete.')
            for child in ax.children(node):
                visit(child,window,depth+1)
        for window in windows:
            if ax.text(window,'AXSubrole')=='AXStandardWindow':
                before=len(groups)
                visit(window,window)
                if len(groups)==before:
                    raise RuntimeError('Startup tab group is unavailable.')
        return found
    try:
        if not ax.trusted() or endpoint_identity(data)!=identity:
            return False
        found=matches()
        if len(found)!=1:
            return not found
        window,tab=found[0]
        buttons=[node for node in ax.children(tab) if ax.text(node,'AXRole')=='AXButton']
        if len(buttons)!=1 or ax.text(window,'AXDocument')!=seed_url:
            return False
        button=buttons[0]
        for node in (window,tab,button):
            pid=ax.c.c_int()
            if ax.ax.AXUIElementGetPid(node,ax.c.byref(pid)) or pid.value!=identity['pid']:
                return False
        if (endpoint_identity(data)!=identity or ax.text(tab,'AXTitle')!=title
                or not ax.within(button,tab) or not ax.within(tab,window)
                or ax.text(window,'AXDocument')!=seed_url):
            return False
        ax.limit(button,1)
        ax.ax.AXUIElementPerformAction(button,ax.string('AXPress'))
        while time.monotonic()<ax.deadline:
            if endpoint_identity(data)!=identity:
                return False
            try:
                if not matches():
                    return True
            except ConsentError as exc:
                if str(exc) not in {'consent_ax_read:-25202','consent_ax_read:-25204'}:
                    raise
            time.sleep(.05)
        return False
    except Exception:
        return False
    finally:
        ax.clear()
