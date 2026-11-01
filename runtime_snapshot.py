"""Private immutable-by-contract worker code surviving plugin source removal.

Only the explicit reviewed dependencies below are copied. Launch workers with
Python -B (or PYTHONDONTWRITEBYTECODE=1); unlisted cache/code files are refused.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import stat
import tempfile
import threading


DEPENDENCIES=('worker.py','binding.py','consent.py','execution_policy.py',
              'browser_actions.py','cdp_policy.py','cdp_peers.py','gui_lease.py',
              'flow_reservation.py','vendor/helpers.py')
OPTIONAL_DEPENDENCIES=('vendor/LICENSE.browser-harness',)


class SnapshotError(RuntimeError):
    pass


class RuntimeSnapshot:
    def __init__(self,source_root,runtime_root):
        self.source_root=Path(source_root).absolute()
        self.runtime_root=Path(runtime_root).absolute()
        self._lock=threading.RLock();self._directory=None;self._identity=None
        self._hashes={};self._active=0;self._closed=False

    @staticmethod
    def _private_directory(path):
        path.mkdir(parents=True,exist_ok=True,mode=0o700)
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
            raise SnapshotError('runtime_snapshot_directory_not_private')

    @staticmethod
    def _read(root,relative):
        """Open every relative component without following symlinks."""
        descriptors=[]
        try:
            directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);descriptors.append(directory)
            parts=Path(relative).parts
            for part in parts[:-1]:
                directory=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                descriptors.append(directory)
            fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory);descriptors.append(fd)
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size>4*1024*1024:
                raise SnapshotError('runtime_snapshot_source_invalid')
            chunks=[];size=0
            while True:
                chunk=os.read(fd,65536)
                if not chunk:break
                size+=len(chunk)
                if size>4*1024*1024:raise SnapshotError('runtime_snapshot_source_invalid')
                chunks.append(chunk)
            after=os.fstat(fd)
            identity=lambda info:(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
            if identity(before)!=identity(after):raise SnapshotError('runtime_snapshot_source_changed')
            return b''.join(chunks)
        finally:
            for fd in reversed(descriptors):os.close(fd)

    @staticmethod
    def _sync(path):
        fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)

    def _verify(self):
        directory=self._directory
        info=directory.lstat()
        if ((info.st_dev,info.st_ino)!=self._identity or not stat.S_ISDIR(info.st_mode)
            or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700):
            raise SnapshotError('runtime_snapshot_identity_changed')
        files=set()
        for path in directory.rglob('*'):
            entry=path.lstat();relative=path.relative_to(directory).as_posix()
            if stat.S_ISDIR(entry.st_mode):
                if relative!='vendor' or stat.S_IMODE(entry.st_mode)!=0o700 or entry.st_uid!=os.getuid():
                    raise SnapshotError('runtime_snapshot_contents_changed')
            elif stat.S_ISREG(entry.st_mode):
                if stat.S_IMODE(entry.st_mode)!=0o600 or entry.st_uid!=os.getuid():
                    raise SnapshotError('runtime_snapshot_contents_changed')
                files.add(relative)
            else:raise SnapshotError('runtime_snapshot_contents_changed')
        if files!=set(self._hashes):raise SnapshotError('runtime_snapshot_contents_changed')
        for relative,digest in self._hashes.items():
            if hashlib.sha256(self._read(directory,relative)).hexdigest()!=digest:
                raise SnapshotError('runtime_snapshot_contents_changed')

    def ensure(self):
        """Publish once before GUI launch; later calls never consult source."""
        with self._lock:
            if self._closed:raise SnapshotError('runtime_snapshot_closed')
            if self._directory is not None:
                self._verify();return self._directory/'worker.py'
            source_info=self.source_root.lstat()
            if not stat.S_ISDIR(source_info.st_mode):raise SnapshotError('runtime_snapshot_source_invalid')
            self._private_directory(self.runtime_root)
            payloads={relative:self._read(self.source_root,relative) for relative in DEPENDENCIES}
            for relative in OPTIONAL_DEPENDENCIES:
                try:payloads[relative]=self._read(self.source_root,relative)
                except FileNotFoundError:pass
            staging=Path(tempfile.mkdtemp(prefix='.building-',dir=self.runtime_root))
            published=None
            try:
                (staging/'vendor').mkdir(mode=0o700)
                for relative,payload in payloads.items():
                    fd=os.open(staging/relative,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                    with os.fdopen(fd,'wb') as stream:
                        stream.write(payload);stream.flush();os.fsync(stream.fileno())
                # Refuse a source edit/removal during this preparation window.
                for relative,payload in payloads.items():
                    if self._read(self.source_root,relative)!=payload:
                        raise SnapshotError('runtime_snapshot_source_changed')
                self._sync(staging/'vendor');self._sync(staging)
                destination=self.runtime_root/('worker-'+secrets.token_hex(16))
                if os.path.lexists(destination):raise SnapshotError('runtime_snapshot_destination_exists')
                os.rename(staging,destination);published=destination
                self._sync(self.runtime_root)
                info=destination.lstat()
                self._directory=destination;self._identity=(info.st_dev,info.st_ino)
                self._hashes={relative:hashlib.sha256(payload).hexdigest() for relative,payload in payloads.items()}
                self._verify()
                return destination/'worker.py'
            except BaseException:
                # Neither path has ever been returned or used by a worker.
                if published is not None:shutil.rmtree(published)
                elif staging.exists():shutil.rmtree(staging)
                self._directory=None;self._identity=None;self._hashes={}
                raise

    @property
    def worker_path(self):return self.ensure()

    @property
    def active_workers(self):
        with self._lock:return self._active

    @contextmanager
    def worker(self):
        """Hold through Popen, wait/termination, and pipe/thread cleanup."""
        with self._lock:
            path=self.ensure();self._active+=1
        try:yield path
        finally:
            with self._lock:self._active-=1

    def close(self):
        with self._lock:
            if self._active:raise SnapshotError('runtime_snapshot_workers_active')
            if self._closed:return
            if self._directory is not None:
                self._verify()
                shutil.rmtree(self._directory)
                self._sync(self.runtime_root)
                self._directory=None
            self._closed=True
