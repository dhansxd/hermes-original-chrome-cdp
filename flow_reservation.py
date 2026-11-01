"""Cooperative Flow account reservation, independent of transient GUI focus.

One participating Flow job per original profile. Other-site browser work is not
reserved. A dirty or potentially billed job survives process death as metadata;
only recovery of that same job may retire it. This is not network interception
or isolation from manual actions/nonparticipating clients.
"""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time
from urllib.parse import unquote, urlsplit
import uuid

VERSION = 1
_PHASES = {'opening', 'preparing', 'submitted', 'rendering', 'recovering', 'completed'}


class FlowResourceBusy(RuntimeError):
    code = 'flow_resource_busy'
    retryable = True
    def __init__(self):
        super().__init__('flow_resource_busy: Flow is in use; other websites remain available')


class FlowRecoveryRequired(FlowResourceBusy):
    code = 'flow_recovery_required'
    retryable = False
    def __init__(self):
        RuntimeError.__init__(self, 'flow_recovery_required: recover the existing Flow job; do not generate again')


def protected_url(url):
    """Explicit Flow/Google identity URLs only; redirects/scripts are not intercepted."""
    try:
        value = urlsplit(url)
        host = (value.hostname or '').lower().rstrip('.')
        if value.scheme.lower() not in {'http', 'https'}:
            return False
        if host in {'flow.google.com', 'labs.google', 'accounts.google.com',
                    'myaccount.google.com', 'signin.google.com', 'accounts.youtube.com'}:
            return True
        if host == 'google.com' or host.endswith('.google.com'):
            parts = unquote(value.path).lower().split('/')
            return any(p in {'accounts', 'logout', 'signout', 'signoutoptions', 'signin'} for p in parts)
        return False
    except (ValueError, TypeError, AttributeError):
        return False


def _folder():
    folder = Path.home()/'.cache/original-chrome-default/flow-reservations-v1'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('flow_reservation_directory_not_private')
    return folder


def _key(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('flow_reservation_path_not_absolute')
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()


def _paths(profile):
    key = _key(profile)
    folder = _folder()
    return folder/(key+'.lock'), folder/(key+'.json')


def _validate(record):
    if (type(record) is not dict or set(record) != {'version', 'job', 'nonce', 'dirty',
            'spent', 'resolved', 'phase', 'project_id', 'media_id'}
        or type(record['version']) is not int or record['version'] != VERSION
        or not isinstance(record['job'], str) or not re.fullmatch('[0-9a-f]{64}', record['job'])
        or not isinstance(record['nonce'], str) or not re.fullmatch('[0-9a-f]{32}', record['nonce'])
        or any(type(record[k]) is not bool for k in ('dirty', 'spent', 'resolved'))
        or not isinstance(record['phase'], str) or record['phase'] not in _PHASES):
        raise FlowRecoveryRequired()
    if record['phase'] in {'submitted','rendering'} and not record['spent']:
        raise FlowRecoveryRequired()
    for key in ('project_id', 'media_id'):
        value = record[key]
        if value is not None:
            try:
                if not isinstance(value, str) or str(uuid.UUID(value)) != value:
                    raise ValueError
            except (ValueError, AttributeError):
                raise FlowRecoveryRequired() from None
    return record


def _read(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 8192):
            raise FlowRecoveryRequired()
        raw = os.read(fd, 8193)
        if len(raw) > 8192:
            raise FlowRecoveryRequired()
        try:
            return _validate(json.loads(raw))
        except (ValueError, UnicodeError):
            raise FlowRecoveryRequired() from None
    finally:
        os.close(fd)


def _sync(folder):
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(path, record):
    _validate(record)
    temporary = path.with_name(path.stem+'.'+secrets.token_hex(12)+'.pending')
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(record, output, separators=(',', ':'))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _sync(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class Reservation:
    def __init__(self, fd, path, record):
        self.fd, self.path, self.record = fd, path, record
        self.owner = (os.getpid(), threading.get_ident())
        self.closed = False
        self.pending = record is not None

    def _owned(self):
        if self.closed or self.owner != (os.getpid(), threading.get_ident()):
            raise RuntimeError('flow_reservation_wrong_owner')
        current = _read(self.path)
        if current is None or current['nonce'] != self.record['nonce'] or current['job'] != self.record['job']:
            raise RuntimeError('flow_reservation_owner_lost')
        return current

    def update(self, **fields):
        current = self._owned()
        if not set(fields) <= {'dirty', 'spent', 'resolved', 'phase', 'project_id', 'media_id'}:
            raise ValueError('flow_reservation_update_invalid')
        if current['spent'] and fields.get('spent') is False:
            raise ValueError('flow_reservation_cannot_forget_submit')
        for key in ('project_id', 'media_id'):
            if current[key] is not None and key in fields and fields[key] != current[key]:
                raise ValueError('flow_reservation_handle_changed')
        updated = dict(current, **fields)
        _write(self.path, updated)
        self.record = updated

    def close(self):
        if self.closed:
            return
        if self.owner != (os.getpid(), threading.get_ident()):
            raise RuntimeError('flow_reservation_wrong_owner')
        try:
            if self.record is not None:
                current = self._owned()
                self.pending = current['dirty'] or (current['spent'] and not current['resolved'])
                if not self.pending:
                    self.path.unlink()
                    _sync(self.path.parent)
        finally:
            self.closed = True
            os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _acquire(profile, workspace, resume, timeout, require_unsubmitted=False):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
        raise ValueError('flow_reservation_timeout_invalid')
    lock, path = _paths(profile)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError('flow_reservation_lock_not_private')
        deadline = time.monotonic()+min(timeout, 30)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise FlowResourceBusy() from None
                time.sleep(min(remaining, .05))
        current = _read(path)
        job = _key(workspace) if workspace is not None else None
        if require_unsubmitted and (not resume or current is None
                or job != current['job'] or current['spent'] is not False):
            raise FlowRecoveryRequired()
        if current is not None:
            # Kernel ownership is gone, but a server job/dirty settings are not.
            if resume and job == current['job']:
                pass
            elif not current['dirty'] and not current['spent']:
                path.unlink(); _sync(path.parent)
                current = None
            else:
                raise FlowRecoveryRequired()
        if job is None:
            return Reservation(fd, path, None)
        if current is None:
            current = dict(version=VERSION, job=job, nonce=secrets.token_hex(16), dirty=False,
                           spent=bool(resume), resolved=False,
                           phase='recovering' if resume else 'opening', project_id=None, media_id=None)
            _write(path, current)
        return Reservation(fd, path, current)
    except BaseException:
        os.close(fd)
        raise


def acquire_browser(profile, timeout=15):
    return _acquire(profile, None, False, timeout)


def acquire_job(profile, workspace, *, resume=False, timeout=15, require_unsubmitted=False):
    return _acquire(profile, workspace, resume, timeout, require_unsubmitted)


def deny_if_reserved(profile):
    """Parent-side defense only; helpers also hold the actual exclusion lock."""
    _, path = _paths(profile)
    if _read(path) is not None:
        raise FlowResourceBusy()


def reservation_for_job(profile, workspace):
    _, path = _paths(profile)
    record = _read(path)
    return record if record is not None and record['job'] == _key(workspace) else None
