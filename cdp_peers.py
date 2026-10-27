"""Settled same-user CDP sockets, not browser ownership or a consent grant.

Only publish AFTER the WebSocket handshake. Never whitelist a pending dial.
Both clients use this small file protocol; no cookies, page data or commands.
"""
import hashlib,json,os,stat,uuid
from pathlib import Path


def _prefix(root,port,path):
    return hashlib.sha256((str(Path(root).resolve())+'\n'+str(port)+'\n'+str(path)).encode()).hexdigest()


def _folder():
    folder=Path.home()/'.cache/original-chrome-default'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    info=folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise RuntimeError('cdp_peer_directory_not_private')
    return folder


def _matches(conn,port,local,fd=None):
    return (conn.status=='ESTABLISHED' and conn.raddr and
            conn.laddr.ip in {'127.0.0.1','::1'} and conn.raddr.ip in {'127.0.0.1','::1'} and
            conn.raddr.port==port and conn.laddr.port==local and (fd is None or conn.fd==fd))


def socket_identity(conn):
    """Exact local/remote TCP endpoints; equal ports are not equal peers."""
    return ((conn.laddr.ip,conn.laddr.port),(conn.raddr.ip,conn.raddr.port))


def accepted_peers(root,port,path):
    """Return only still-live exact registered sockets; stale files grant nothing."""
    import psutil
    prefix=_prefix(root,port,path);result=set()
    for file in _folder().glob(prefix+'-peer-*.json'):
        try:
            info=file.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>2048:continue
            row=json.loads(file.read_text())
            if not isinstance(row,dict) or row.get('epoch')!=prefix:continue
            process=psutil.Process(row['pid'])
            if process.uids().real!=os.getuid() or process.create_time()!=row['started']:continue
            live=next((c for c in process.net_connections(kind='tcp') if _matches(c,port,row['local_port'],row['fd'])),None)
            if live is not None:
                current=file.lstat()
                if (current.st_dev,current.st_ino,current.st_mtime_ns,current.st_size)==(info.st_dev,info.st_ino,info.st_mtime_ns,info.st_size):
                    result.add(socket_identity(live))
        except (OSError,ValueError,KeyError,TypeError,psutil.Error):continue
    return result


class RegisteredSocket:
    def __init__(self,ws,file,pin):
        import threading
        self._ws=ws;self._file=file;self._pin=pin;self._close_lock=threading.Lock()
    def __getattr__(self,key):return getattr(self._ws,key)
    def close(self,*args,**kwargs):
        with self._close_lock:
            try:return self._ws.close(*args,**kwargs)
            finally:
                if self._pin is not None:
                    # Remove the receipt before making its descriptor reusable.
                    self._file.unlink(missing_ok=True)
                    os.close(self._pin);self._pin=None


def register_accepted(ws,root,port,path):
    import psutil
    socket=ws.socket
    local=socket.getsockname()[1];fd=socket.fileno();process=psutil.Process(os.getpid())
    if not any(_matches(c,port,local,fd) for c in process.net_connections(kind='tcp')):
        raise RuntimeError('cdp_accepted_socket_unverified')
    prefix=_prefix(root,port,path)
    file=_folder()/(prefix+'-peer-'+uuid.uuid4().hex+'.json')
    # Pin the original socket's kernel identity even if the library closes its fd.
    pin=os.dup(fd)
    try:
        if not any(_matches(c,port,local,pin) for c in process.net_connections(kind='tcp')):
            raise RuntimeError('cdp_accepted_socket_unverified')
        row={'epoch':prefix,'pid':process.pid,'started':process.create_time(),'local_port':local,'fd':pin}
        with os.fdopen(os.open(file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'w') as handle:
            json.dump(row,handle)
        return RegisteredSocket(ws,file,pin)
    except BaseException:
        try:
            file.unlink(missing_ok=True)
            os.close(pin)
        except OSError:pass  # Keep the pin if a potentially valid receipt cannot be removed.
        raise
