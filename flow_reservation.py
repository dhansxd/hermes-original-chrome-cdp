"""Cooperative Flow account reservation, independent of transient GUI focus.

One participating Flow job per verified Google account and original profile. Other-site browser work is not
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
ACCOUNT_VERSION = 2
MAX_ENTRIES = 4096
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
        raise FlowRecoveryRequired()
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


def _account(profile, account_key):
    if account_key is not None:
        if not isinstance(account_key, str) or not re.fullmatch('[0-9a-f]{64}', account_key):
            raise ValueError('flow_reservation_account_invalid')
    elif (Path(profile).parent.resolve() == (Path.home()/'Library/Application Support/Google/Chrome').resolve()
          or Path(profile).resolve().parent == (Path.home()/'Library/Application Support/Google/Chrome').resolve()):
        # Account-less operation is only a disposable fixture compatibility path.
        raise FlowRecoveryRequired()
    return account_key


def _validate(record):
    fields = {'version', 'job', 'nonce', 'dirty', 'spent', 'resolved', 'phase', 'project_id', 'media_id'}
    if type(record) is dict and record.get('version') == ACCOUNT_VERSION:
        fields |= {'account', 'profile'}
        if any(not isinstance(record.get(k), str) or not re.fullmatch('[0-9a-f]{64}', record[k]) for k in ('account', 'profile')):
            raise FlowRecoveryRequired()
    if (type(record) is not dict or set(record) != fields
        or type(record['version']) is not int or record['version'] not in (VERSION, ACCOUNT_VERSION)
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


def _read(path, *, directory=None):
    path = Path(path)
    try:
        fd = os.open(path.name if directory is not None else path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    except OSError:
        raise FlowRecoveryRequired() from None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 8192):
            raise FlowRecoveryRequired()
        raw = os.read(fd, 8193)
        if len(raw) > 8192:
            raise FlowRecoveryRequired()
        try:
            record = _validate(json.loads(raw))
            if record['version'] == ACCOUNT_VERSION and path.name != record['profile']+'.json':
                raise FlowRecoveryRequired()
            return record
        except (ValueError, UnicodeError):
            raise FlowRecoveryRequired() from None
    finally:
        os.close(fd)


def _pending(record):
    return record['dirty'] or (record['spent'] and not record['resolved'])


def _scan(account_key, own=None):
    """Read one authoritative record per profile; never follow a foreign path.

    Legacy records cannot safely acquire account provenance retroactively. Settle
    them using the matching old installation before activating account-aware work.
    """
    folder = _folder()
    try:
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise FlowRecoveryRequired() from None
    try:
        opened = os.fstat(fd)
        deadline = time.monotonic()+1
        count = 0
        with os.scandir(fd) as entries:
            for entry in entries:
                count += 1
                if count > MAX_ENTRIES or time.monotonic() > deadline:
                    raise FlowRecoveryRequired()
                if not entry.name.endswith('.json'):
                    continue
                if not re.fullmatch('[0-9a-f]{64}\\.json', entry.name):
                    raise FlowRecoveryRequired()
                record = _read(Path(entry.name), directory=fd)
                if time.monotonic() > deadline:
                    raise FlowRecoveryRequired()
                if record is None:
                    continue
                if record['version'] == VERSION:
                    raise FlowRecoveryRequired()
                if own is not None and entry.name == own.name:
                    continue
                if record['account'] == account_key and _pending(record):
                    raise FlowRecoveryRequired()
        current = folder.lstat()
        if time.monotonic() > deadline or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise FlowRecoveryRequired()
    except OSError:
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


def _check_lock(path, fd):
    try:
        current, opened = path.lstat(), os.fstat(fd)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise FlowRecoveryRequired()
    except OSError:
        raise FlowRecoveryRequired() from None


class Reservation:
    def __init__(self, fd, path, record, account_fd=None, account_key=None):
        self.fd, self.path, self.record = fd, path, record
        self.account_fd = account_fd
        self.account_key = account_key
        self.owner = (os.getpid(), threading.get_ident())
        self.closed = False
        self.pending = record is not None

    def check_binding(self):
        # Read-only pin validation may run on the same-process relay thread.
        # State mutation and close remain restricted to the original owner thread.
        if self.closed or self.owner[0] != os.getpid():
            raise RuntimeError('flow_reservation_wrong_owner')
        _check_lock(self.path.with_suffix('.lock'), self.fd)
        if self.account_fd is not None:
            _check_lock(self.path.parent/('account-'+self.account_key+'.lock'), self.account_fd)

    def _owned(self):
        if self.owner != (os.getpid(), threading.get_ident()):
            raise RuntimeError('flow_reservation_wrong_owner')
        self.check_binding()
        current = _read(self.path)
        if (current is None or current['nonce'] != self.record['nonce'] or current['job'] != self.record['job']
                or any(current.get(k) != self.record.get(k) for k in ('version', 'account', 'profile'))):
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
                self.pending = _pending(current)
                if not self.pending:
                    self.path.unlink()
                    _sync(self.path.parent)
        finally:
            self.closed = True
            os.close(self.fd)
            if self.account_fd is not None:
                os.close(self.account_fd)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _lock(lock, deadline):
    try:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise FlowRecoveryRequired() from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise FlowRecoveryRequired()
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise FlowResourceBusy() from None
                time.sleep(min(remaining, .05))
        actual = lock.lstat()
        if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
            raise FlowRecoveryRequired()
        return fd
    except BaseException:
        os.close(fd)
        raise


def _acquire(profile, workspace, resume, timeout, require_unsubmitted=False, account_key=None):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
        raise ValueError('flow_reservation_timeout_invalid')
    account_key = _account(profile, account_key)
    deadline = time.monotonic()+min(timeout, 30)
    lock, path = _paths(profile)
    account_fd = fd = None
    try:
        if account_key is not None:
            account_fd = _lock(path.parent/('account-'+account_key+'.lock'), deadline)
        fd = _lock(lock, deadline)
        _check_lock(lock, fd)
        if account_fd is not None:_check_lock(path.parent/('account-'+account_key+'.lock'), account_fd)
        current = _read(path)
        if account_key is not None:
            if current is not None and (current['version'] != ACCOUNT_VERSION or current['account'] != account_key):
                raise FlowRecoveryRequired()
            _scan(account_key, own=path)
        elif current is not None and current['version'] == ACCOUNT_VERSION:
            raise FlowRecoveryRequired()
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
            held = Reservation(fd, path, None, account_fd, account_key)
            held.check_binding()
            return held
        if current is None:
            current = dict(version=ACCOUNT_VERSION if account_key is not None else VERSION, job=job, nonce=secrets.token_hex(16), dirty=False,
                           spent=bool(resume), resolved=False,
                           phase='recovering' if resume else 'opening', project_id=None, media_id=None)
            if account_key is not None:
                current.update(account=account_key, profile=_key(profile))
            _write(path, current)
        held = Reservation(fd, path, current, account_fd, account_key)
        held.check_binding()
        return held
    except BaseException:
        if fd is not None:os.close(fd)
        if account_fd is not None:os.close(account_fd)
        raise


def acquire_browser(profile, timeout=15, *, account_key=None):
    return _acquire(profile, None, False, timeout, account_key=account_key)


def acquire_job(profile, workspace, *, resume=False, timeout=15, require_unsubmitted=False, account_key=None):
    return _acquire(profile, workspace, resume, timeout, require_unsubmitted, account_key)


def deny_if_reserved(profile, *, account_key=None):
    """Parent-side defense only; helpers also hold the actual exclusion lock."""
    account_key = _account(profile, account_key)
    _, path = _paths(profile)
    record = _read(path)
    if record is not None:
        if _pending(record) or (account_key is not None and (record['version'] != ACCOUNT_VERSION or record['account'] != account_key)):
            raise FlowRecoveryRequired()
        raise FlowResourceBusy()
    if account_key is not None:
        _scan(account_key)


def reservation_for_job(profile, workspace, *, account_key=None):
    account_key = _account(profile, account_key)
    _, path = _paths(profile)
    record = _read(path)
    if record is not None and account_key is not None and (record['version'] != ACCOUNT_VERSION or record['account'] != account_key):
        raise FlowRecoveryRequired()
    return record if record is not None and record['job'] == _key(workspace) else None
