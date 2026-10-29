"""Read-only operator snapshot of Chrome processes and native window counts."""
from pathlib import Path
import time
import psutil

if __package__:
    from .consent import AX
else:
    from consent import AX


def chrome_gui_snapshot(data_root,verify_executable):
    """Count only positively inspected standard windows; never expose contents."""
    result={'running':None,'pids':[],'window_count':None,'document_window_count':None,
            'status':'unknown','reason':None}
    expected=Path(data_root).resolve()
    personal=Path.home()/'Library/Application Support/Google/Chrome'
    deadline=time.monotonic()+5
    matches=[];uncertain=False
    try:
        for process in psutil.process_iter():
            if time.monotonic()>=deadline:
                result['reason']='process_scan_timeout';return result
            try:
                if process.name()!='Google Chrome':continue
                info=process.as_dict(attrs=['exe','cmdline','create_time'])
                args=info['cmdline']
                if not isinstance(args,list):
                    uncertain=True;continue
                roots=[]
                for index,arg in enumerate(args):
                    if arg.startswith('--user-data-dir='):roots.append(arg.split('=',1)[1])
                    elif arg=='--user-data-dir':
                        if index+1>=len(args):raise ValueError('missing root')
                        roots.append(args[index+1])
                if len(roots)>1:raise ValueError('ambiguous root')
                root=Path(roots[0] if roots else personal).resolve()
                if root!=expected:continue
                if not verify_executable(info['exe']):
                    uncertain=True;continue
                matches.append((process.pid,info['create_time'],info['exe']))
            except psutil.NoSuchProcess:continue
            except Exception:uncertain=True
    except Exception:
        result['reason']='process_scan_unavailable';return result
    result['pids']=[pid for pid,_,_ in matches]
    if matches:result['running']=True
    if uncertain:
        result['reason']='process_identity_unavailable';return result
    if not matches:
        result.update(running=False,status='stopped',window_count=0,document_window_count=0)
        return result
    if len(matches)!=1:
        result['reason']='multiple_chrome_processes';return result
    pid,started,executable=matches[0]
    ax=None
    try:
        ax=AX();ax.deadline=deadline
        if not ax.trusted():
            result['reason']='accessibility_unavailable';return result
        app=ax.ax.AXUIElementCreateApplication(pid)
        if not app:
            result['reason']='accessibility_unavailable';return result
        ax.refs.append(app)
        windows=ax.attr(app,'AXWindows')
        if windows is None:
            result['reason']='window_inventory_unavailable';return result
        count=ax.cf.CFArrayGetCount(windows)
        if type(count) is not int or not 0<=count<=256:
            result['reason']='window_inventory_unavailable';return result
        standard=documents=0
        for index in range(count):
            window=ax.cf.CFArrayGetValueAtIndex(windows,index)
            if ax.text(window,'AXSubrole')=='AXStandardWindow':
                standard+=1
                if ax.text(window,'AXDocument'):documents+=1
        # Use a fresh process object; psutil caches birth times per instance.
        current=psutil.Process(pid)
        if current.create_time()!=started or current.exe()!=executable:
            result['reason']='chrome_generation_changed';return result
        result.update(window_count=standard,document_window_count=documents,
                      status='running_with_windows' if standard else 'running_no_windows')
        return result
    except Exception:
        result['reason']='window_inventory_unavailable';return result
    finally:
        if ax is not None:ax.clear()
