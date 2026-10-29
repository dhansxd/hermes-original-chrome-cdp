"""Observe removal of loaded plugin source while browser resources are active.

Construction is inert. The provider explicitly starts one watcher before its
first resource and stops it after the last resource. This module only checks
fixed marker metadata and invokes one supplied cleanup callback; it installs no
hook, registry entry, configuration change, or surviving uninstall process.
"""
import math
from pathlib import Path
import stat
import threading
import time


class SourceRemovalWatch:
    """One-use, bounded-poll daemon; missing source must persist across samples."""
    def __init__(self,markers,on_removed,*,poll_interval=.5,grace_s=1.0):
        self.markers=tuple(Path(marker).absolute() for marker in markers)
        if not 1<=len(self.markers)<=4 or not callable(on_removed):
            raise ValueError('source_watch_arguments_invalid')
        for value in (poll_interval,grace_s):
            if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
                raise ValueError('source_watch_interval_invalid')
        self.poll_interval=float(poll_interval)
        self.grace_s=float(grace_s)
        self._on_removed=on_removed
        self._stop=threading.Event();self._stopped=threading.Event();self._stopped.set()
        self._detected=threading.Event();self._callback_failed=threading.Event()
        self._lock=threading.Lock();self._thread=None

    @property
    def stopped(self):return self._stopped.is_set()

    @property
    def removal_detected(self):return self._detected.is_set()

    @property
    def callback_failed(self):return self._callback_failed.is_set()

    @property
    def is_running(self):
        with self._lock:thread=self._thread
        return thread is not None and thread.is_alive()

    def start(self):
        """Start once. Repeated starts or starting after stop are inert."""
        with self._lock:
            if self._thread is not None or self._stop.is_set():return False
            self._stopped.clear()
            self._thread=threading.Thread(target=self._run,name='chrome-source-removal-watch',daemon=True)
            try:self._thread.start()
            except Exception:
                self._stop.set();self._stopped.set()
                raise
            return True

    def stop(self,join_timeout=1.0):
        """Cancel observation; never run cleanup here or wait on this own thread."""
        if type(join_timeout) not in (int,float) or not math.isfinite(join_timeout) or not 0<=join_timeout<=5:
            raise ValueError('source_watch_join_invalid')
        self._stop.set()
        with self._lock:thread=self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(join_timeout)
        return self.stopped

    def _present(self):
        # lstat never follows the final marker. A symlink or directory cannot
        # substitute for one of the loaded source files after removal.
        for marker in self.markers:
            try:info=marker.lstat()
            except OSError:return False
            if not stat.S_ISREG(info.st_mode):return False
        return True

    def _run(self):
        missing_since=None;missing_samples=0
        try:
            while not self._stop.is_set():
                if self._present():
                    missing_since=None;missing_samples=0
                else:
                    now=time.monotonic()
                    if missing_since is None:missing_since=now
                    missing_samples+=1
                    if missing_samples>=3 and now-missing_since>=self.grace_s:
                        # Cleanup is exclusively on this daemon, never inline
                        # in start(), and can safely call stop() on itself.
                        if self._stop.is_set():return
                        self._detected.set()
                        try:self._on_removed()
                        except Exception:self._callback_failed.set()
                        return
                if self._stop.wait(self.poll_interval):return
        finally:self._stopped.set()
