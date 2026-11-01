"""Durable cleanup provenance, without browser control or page/account data.

The trusted parent supplies a verified Chrome process generation. Records grant
no authority over a different generation or arbitrary matching page URLs. An
unbound seed is only a recovery candidate until its exact, unique marker is
claimed and persisted against the current verified generation.
"""
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import threading
import time
from urllib.parse import urlsplit


class JournalError(RuntimeError):
    pass


_ID=re.compile(r'[0-9a-f]{32}\Z')
_TARGET=re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_DIGEST=re.compile(r'[0-9a-f]{64}\Z')


def _target(value):
    if not isinstance(value,str) or not _TARGET.fullmatch(value):
        raise JournalError('ownership_journal_invalid_target')
    return value


def _window(value):
    if value is not None and (type(value) is not int or value<0):
        raise JournalError('ownership_journal_invalid_window')
    return value


def browser_generation(value):
    """Normalize parent-verified PID/birth/endpoint proof, storing no endpoint."""
    if not isinstance(value,dict) or type(value.get('pid')) is not int or value['pid']<=0:
        raise JournalError('ownership_journal_invalid_generation')
    started=value.get('started')
    if type(started) not in (int,float) or not math.isfinite(started) or started<=0:
        raise JournalError('ownership_journal_invalid_generation')
    digest=value.get('endpoint_sha256')
    if digest is None:
        endpoint=value.get('endpoint')
        if not isinstance(endpoint,str):raise JournalError('ownership_journal_invalid_generation')
        try:
            url=urlsplit(endpoint)
            valid=(url.scheme=='ws' and url.hostname in {'127.0.0.1','localhost','::1'}
                   and url.port and not url.username and not url.password
                   and url.path.startswith('/devtools/browser/') and not url.query and not url.fragment)
        except ValueError:valid=False
        if not valid:raise JournalError('ownership_journal_invalid_generation')
        digest=hashlib.sha256(endpoint.encode()).hexdigest()
    if not isinstance(digest,str) or not _DIGEST.fullmatch(digest):
        raise JournalError('ownership_journal_invalid_generation')
    return {'pid':value['pid'],'started':float(started),'endpoint_sha256':digest}


def _state(value):
    """Copy only provenance. Never persist dialogs, stdout, URLs, or page data."""
    if not isinstance(value,dict) or not isinstance(value.get('owned',{}),dict):
        raise JournalError('ownership_journal_invalid_state')
    owned=value.get('owned',{})
    if len(owned)>512:raise JournalError('ownership_journal_too_many_targets')
    owned={_target(target):_window(window) for target,window in owned.items()}
    context=value.get('context')
    if owned or context is not None:context=_target(context)
    verified=value.get('verified',False)
    unresolved=value.get('unresolved_creation',False)
    if type(verified) is not bool or type(unresolved) is not bool:
        raise JournalError('ownership_journal_invalid_state')
    pending=value.get('pending_closes',{})
    if not isinstance(pending,dict) or any(t not in owned or v not in {'sent','acknowledged'} for t,v in pending.items()):
        raise JournalError('ownership_journal_invalid_close_state')
    result={'owned':owned,'verified':verified,'unresolved_creation':unresolved}
    if context is not None:result['context']=context
    if pending:result['pending_closes']=dict(pending)
    current=value.get('current')
    if current in owned:result['current']=current
    return result


class OwnershipJournal:
    """Small private per-provider journal; all browser actions stay in parent."""
    def __init__(self,folder,data_root,*,owner=None,scope='',owner_alive=None,profile_path=None):
        self.folder=Path(folder).resolve()
        self.data_root=Path(data_root).resolve()
        selected=Path(profile_path) if profile_path is not None else self.data_root/'Default'
        if (not selected.is_absolute() or selected.is_symlink()
            or selected.resolve().parent!=self.data_root or selected.name in {'.','..','Guest Profile','System Profile'}):
            raise JournalError('ownership_journal_profile_mismatch')
        self.profile=str(selected.resolve())
        self.scope=hashlib.sha256((str(self.folder)+'\0'+self.profile+'\0'+scope).encode()).hexdigest()
        if owner is None:
            import psutil
            owner={'pid':os.getpid(),'started':psutil.Process(os.getpid()).create_time(),
                   'instance':secrets.token_hex(16)}
        self.instance_id=owner.get('instance')
        self.owner={'pid':owner.get('pid'),'started':owner.get('started'),'instance':self.instance_id,
                    'scope':self.scope,'released':False,'handoff_to':None}
        self._validate_owner(self.owner)
        self._owner_alive=owner_alive or self._process_alive
        self._lock=threading.RLock()
        self._directory(self.folder)
        self._directory(self.folder/'seeds')

    @staticmethod
    def _validate_owner(owner):
        if (not isinstance(owner,dict)
            or set(owner)!={'pid','started','instance','scope','released','handoff_to'}
            or type(owner['pid']) is not int or owner['pid']<=0
            or type(owner['started']) not in (int,float) or not math.isfinite(owner['started']) or owner['started']<=0
            or not isinstance(owner['instance'],str) or not _ID.fullmatch(owner['instance'])
            or not isinstance(owner['scope'],str) or not _DIGEST.fullmatch(owner['scope'])
            or type(owner['released']) is not bool
            or (owner['handoff_to'] is not None and
                (not owner['released'] or not isinstance(owner['handoff_to'],str) or not _ID.fullmatch(owner['handoff_to'])))):
            raise JournalError('ownership_journal_invalid_owner')

    @staticmethod
    def _process_alive(pid,started):
        try:
            import psutil
            return psutil.Process(pid).create_time()==started
        except psutil.NoSuchProcess:return False
        except Exception:return True # Unavailable proof must never steal a lease.

    def _owns(self,record):
        return record['owner']==self.owner

    def _require_owner(self,record):
        if not self._owns(record):raise JournalError('ownership_journal_not_owner')

    def _eligible(self,record):
        owner=record['owner']
        if owner['scope']!=self.scope:return False
        if owner['handoff_to'] not in (None,self.instance_id):return False
        if owner['released']:return True
        try:return self._owner_alive(owner['pid'],owner['started']) is False
        except Exception:return False

    @staticmethod
    def _directory(path):
        path.mkdir(parents=True,exist_ok=True,mode=0o700)
        info=path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077:
            raise JournalError('ownership_journal_directory_not_private')

    @contextmanager
    def _guard(self):
        deadline=time.monotonic()+2
        if not self._lock.acquire(timeout=2):raise JournalError('ownership_journal_busy')
        try:
            fd=os.open(self.folder/'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            try:
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077:
                    raise JournalError('ownership_journal_lock_not_private')
                while True:
                    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                    except BlockingIOError:
                        remaining=deadline-time.monotonic()
                        if remaining<=0:raise JournalError('ownership_journal_busy')
                        time.sleep(min(.01,remaining))
                yield
            finally:os.close(fd)
        finally:self._lock.release()

    def _path(self,record_id):
        if not isinstance(record_id,str) or not _ID.fullmatch(record_id):
            raise JournalError('ownership_journal_invalid_id')
        return self.folder/(record_id+'.json')

    def _validate(self,record):
        fields={'schema','id','data_root','profile','seed_url','created_at','generation','phase','state','owner'}
        if not isinstance(record,dict) or set(record)!=fields or record['schema']!=1:
            raise JournalError('ownership_journal_invalid_record')
        self._path(record['id'])
        self._validate_owner(record['owner'])
        if record['data_root']!=str(self.data_root) or record['profile']!=self.profile:
            raise JournalError('ownership_journal_profile_mismatch')
        if record['seed_url']!=(self.folder/'seeds'/(record['id']+'.html')).as_uri():
            raise JournalError('ownership_journal_invalid_seed')
        if type(record['created_at']) not in (int,float) or not math.isfinite(record['created_at']):
            raise JournalError('ownership_journal_invalid_record')
        if record['phase'] not in {'seed','owned','clean'}:
            raise JournalError('ownership_journal_invalid_record')
        if record['generation'] is not None:
            if record['generation']!=browser_generation(record['generation']):
                raise JournalError('ownership_journal_invalid_generation')
        if record['state']!=_state(record['state']):
            raise JournalError('ownership_journal_invalid_state')
        if record['state']['owned'] and record['generation'] is None:
            raise JournalError('ownership_journal_generation_missing')
        if record['phase']=='clean' and (record['state']['owned'] or record['state']['unresolved_creation']):
            raise JournalError('ownership_journal_cleanup_unconfirmed')
        return record

    def _read(self,record_id):
        fd=os.open(self._path(record_id),os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
                or info.st_mode & 0o077 or info.st_size>262144):
                raise JournalError('ownership_journal_record_not_private')
            with os.fdopen(fd,'r',encoding='utf-8',closefd=False) as stream:
                record=json.load(stream)
            record=self._validate(record)
            if record['id']!=record_id:raise JournalError('ownership_journal_invalid_id')
            return record
        finally:os.close(fd)

    def _sync_directory(self,folder=None):
        fd=os.open(folder or self.folder,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def _write(self,record):
        self._validate(record)
        fd,name=tempfile.mkstemp(prefix='.record-',dir=self.folder)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump(record,stream,sort_keys=True,separators=(',',':'))
                stream.flush();os.fsync(stream.fileno())
            os.replace(name,self._path(record['id']))
            self._sync_directory()
        finally:
            if os.path.exists(name):os.unlink(name)

    def begin_seed(self):
        """Persist an inert unique marker BEFORE invoking the GUI launcher."""
        with self._guard():
            record_id=secrets.token_hex(16)
            seed=self.folder/'seeds'/(record_id+'.html')
            fd=os.open(seed,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                stream.write('<!doctype html><title>Chrome agent setup</title>')
                stream.flush();os.fsync(stream.fileno())
            self._sync_directory(self.folder/'seeds')
            record={'schema':1,'id':record_id,'data_root':str(self.data_root),'profile':self.profile,
                    'seed_url':seed.as_uri(),'created_at':time.time(),'generation':None,'phase':'seed',
                    'state':_state({}),'owner':dict(self.owner)}
            self._write(record)
            return copy.deepcopy(record)

    def bind_generation(self,record_id,generation):
        generation=browser_generation(generation)
        with self._guard():
            record=self._read(record_id)
            self._require_owner(record)
            if record['generation'] not in (None,generation):
                raise JournalError('ownership_journal_generation_changed')
            record['generation']=generation;self._write(record)
            return copy.deepcopy(record)

    def checkpoint(self,record_id,state):
        state=_state(state)
        with self._guard():
            record=self._read(record_id)
            self._require_owner(record)
            if state['owned'] and record['generation'] is None:
                raise JournalError('ownership_journal_generation_missing')
            record['state']=state
            if state['owned']:record['phase']='owned'
            elif record['phase']!='seed' and not state['unresolved_creation']:record['phase']='clean'
            self._write(record)
            return copy.deepcopy(record)

    def records(self):
        with self._guard():
            ids=sorted(p.stem for p in self.folder.glob('*.json') if _ID.fullmatch(p.stem))
            if len(ids)>512:raise JournalError('ownership_journal_too_many_records')
            return [self._read(record_id) for record_id in ids]

    def eligible_records(self):
        """Read-only orphan candidates; current active records are not included."""
        return [record for record in self.records() if not self._owns(record) and self._eligible(record)]

    def claim(self,record_id):
        """Atomically acquire an orphan lease BEFORE observing/closing its tabs."""
        with self._guard():
            record=self._read(record_id)
            if self._owns(record):return copy.deepcopy(record)
            if not self._eligible(record):raise JournalError('ownership_journal_owner_active')
            record['owner']=dict(self.owner);self._write(record)
            return copy.deepcopy(record)

    def release(self,record_id):
        return self._release(record_id,None)

    def handoff(self,record_id,destination_instance_id):
        if not isinstance(destination_instance_id,str) or not _ID.fullmatch(destination_instance_id):
            raise JournalError('ownership_journal_invalid_owner')
        return self._release(record_id,destination_instance_id)

    def _release(self,record_id,destination):
        with self._guard():
            record=self._read(record_id);self._require_owner(record)
            record['owner']['released']=True;record['owner']['handoff_to']=destination
            self._write(record)
            return copy.deepcopy(record)

    def release_all(self):
        released=[]
        for record in self.records():
            if self._owns(record):
                self.release(record['id']);released.append(record['id'])
        return released

    @staticmethod
    def _seed_match(record,target_infos,windows):
        matches=[t for t in target_infos if t.get('type')=='page' and t.get('url')==record['seed_url']]
        if len(matches)!=1:return None
        info=matches[0];target=_target(info.get('targetId'));context=_target(info.get('browserContextId'))
        window=windows.get(target)
        if window is None:return None
        return {'target':target,'context':context,'window':_window(window)}

    def claim_seed(self,record_id,generation,target_infos,windows):
        """Bind only one exact generated marker, before navigation or cleanup."""
        generation=browser_generation(generation)
        with self._guard():
            record=self._read(record_id)
            self._require_owner(record)
            if record['phase']!='seed':raise JournalError('ownership_journal_seed_already_claimed')
            if record['generation'] not in (None,generation):
                raise JournalError('ownership_journal_generation_changed')
            match=self._seed_match(record,target_infos,windows)
            if match is None:raise JournalError('ownership_journal_seed_unconfirmed')
            target=match['target']
            record['generation']=generation;record['phase']='owned'
            record['state']=_state({'owned':{target:match['window']},'context':match['context'],
                                    'current':target,'verified':False})
            self._write(record)
            return copy.deepcopy(record)

    def recovery_plan(self,generation,target_infos,windows,*,record_ids):
        """Plan explicitly selected, held leases only. Never replay pending closes.

        Orphan recovery must first use eligible_records(), then claim(id). An
        active task uses its own known record ID; there is no all-sessions sweep.
        """
        generation=browser_generation(generation)
        targets={}
        for info in target_infos:
            target=_target(info.get('targetId'))
            if target in targets:raise JournalError('ownership_journal_ambiguous_inventory')
            targets[target]=info
        plan={'records':[],'seed_candidates':[],'stale_records':[]}
        with self._guard():
            records=[self._read(record_id) for record_id in dict.fromkeys(record_ids)]
            for record in records:self._require_owner(record)
        for record in records:
            if record['generation'] not in (None,generation):
                plan['stale_records'].append(record['id']);continue
            if record['phase']=='seed':
                match=self._seed_match(record,target_infos,windows)
                if match is not None:plan['seed_candidates'].append(dict(match,id=record['id']))
                else:plan['records'].append({'id':record['id'],'blocked':{'seed':'seed_unconfirmed'},
                                             'close':[],'observe_only':[],'missing':[]})
                continue
            state=record['state'];item={'id':record['id'],'close':[],'observe_only':[],'missing':[],'blocked':{}}
            if state['unresolved_creation']:item['blocked']['creation']='creation_unresolved'
            for target,window in state['owned'].items():
                info=targets.get(target)
                if info is None:item['missing'].append(target);continue
                if info.get('type')!='page' or info.get('browserContextId')!=state.get('context'):
                    item['blocked'][target]='context_changed';continue
                if window is None or windows.get(target)!=window:
                    item['blocked'][target]='window_unconfirmed';continue
                destination='observe_only' if target in state.get('pending_closes',{}) else 'close'
                item[destination].append(target)
            plan['records'].append(item)
        return plan

    def complete(self,record_id):
        """Remove only after confirmed cleanup has checkpointed an empty state."""
        with self._guard():
            record=self._read(record_id)
            self._require_owner(record)
            if record['phase']!='clean' or record['state']['owned'] or record['state']['unresolved_creation']:
                raise JournalError('ownership_journal_cleanup_unconfirmed')
            self._remove(record_id)

    def retire(self,record_id,*,generation_gone=False,seed_absent=False):
        """Retire on explicit parent proof, without touching the live browser.

        generation_gone means the recorded PID/birth was independently proved
        absent. seed_absent requires a settled authoritative inventory proving
        the exact unclaimed marker absent, never a timeout or failed inventory.
        """
        with self._guard():
            record=self._read(record_id);self._require_owner(record)
            if generation_gone is True and record['generation'] is not None:
                self._remove(record_id);return
            if (seed_absent is True and record['phase']=='seed' and not record['state']['owned']
                and not record['state']['unresolved_creation']):
                self._remove(record_id);return
            raise JournalError('ownership_journal_retirement_unconfirmed')

    def _remove(self,record_id):
        self._path(record_id).unlink();self._sync_directory()
        seed=self.folder/'seeds'/(record_id+'.html')
        try:seed.unlink()
        except FileNotFoundError:pass
