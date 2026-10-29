"""Cooperative GUI batches for original Chrome profiles; never browser ownership.

Only participating clients honor these leases. They do not isolate login state,
govern human actions, or cover asynchronous server rendering.
"""
import fcntl
import hashlib
import math
import os
from pathlib import Path
import stat
import threading
import time
from urllib.parse import urlsplit

ORIGINS=frozenset({'https://flow.google.com','https://labs.google'})
FLOW_ORIGIN='https://flow.google.com'
_local=threading.local()


class GuiResourceBusy(RuntimeError):
    code='gui_resource_busy'
    retryable=True
    def __init__(self):super().__init__(self.code)


def origin_for_url(url):
    try:
        value=urlsplit(url)
        if value.username or value.password:return None
        if value.scheme.lower()!='https'or value.port not in (None,443):return None
        if value.hostname=='flow.google.com':return FLOW_ORIGIN
        if value.hostname=='labs.google'and (value.path in {'/flow','/fx/tools/flow'}
             or value.path.startswith(('/flow/','/fx/tools/flow/'))):return FLOW_ORIGIN
        return None
    except (TypeError,ValueError):return None


def _held():
    if getattr(_local,'pid',None)!=os.getpid():
        _local.pid=os.getpid();_local.held={}
    return _local.held


def _folder():
    folder=Path.home()/'.cache/original-chrome-default/gui-leases'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    info=folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise RuntimeError('gui_lease_directory_not_private')
    return folder


class Lease:
    def __init__(self,key,slot):
        self.key=key;self.slot=slot;self.owner=(os.getpid(),threading.get_ident());self.closed=False
    def close(self):
        if self.closed:return
        if self.owner!=(os.getpid(),threading.get_ident()):
            raise RuntimeError('gui_lease_wrong_owner')
        held=_held()
        if held.get(self.key) is not self.slot:raise RuntimeError('gui_lease_owner_lost')
        self.closed=True;self.slot[1]-=1
        if not self.slot[1]:
            del held[self.key]
            os.close(self.slot[0])
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


def acquire(profile_path,origin,timeout=30):
    """Take one profile/origin lease. Pass the operation's remaining budget.

    Reentrant only in the same PID/thread; nested close does not unlock an outer
    batch. Close in that thread at the end of GUI work, before render-only waits.
    """
    if origin not in ORIGINS:raise ValueError('gui_lease_origin_not_supported')
    # Flow's old/new hosts are one coordinated service. Holding both names in
    # opposite orders must never create a two-lock deadlock.
    origin=FLOW_ORIGIN
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<0:
        raise ValueError('gui_lease_timeout_invalid')
    profile=Path(profile_path)
    if not profile.is_absolute():raise ValueError('gui_lease_profile_not_absolute')
    key=hashlib.sha256((str(profile.resolve())+'\n'+origin).encode()).hexdigest()
    held=_held()
    if key in held:
        slot=held[key];slot[1]+=1
        return Lease(key,slot)
    file=_folder()/(key+'.lock')
    fd=os.open(file,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
            raise RuntimeError('gui_lease_file_not_private')
        deadline=time.monotonic()+min(timeout,30)
        while True:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                left=deadline-time.monotonic()
                if left<=0:raise GuiResourceBusy()
                time.sleep(min(left,.05))
        slot=[fd,1];held[key]=slot
        return Lease(key,slot)
    except BaseException:
        os.close(fd);raise
