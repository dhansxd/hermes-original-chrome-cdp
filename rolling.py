"""Quota-driven profile rolling with durable provider-request ownership."""
import copy
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager

if __package__:
    from .profiles import get_profile, list_profiles, profile_directory
else:
    from profiles import get_profile, list_profiles, profile_directory


HANDOFF_MODES = ('manual', 'automatic')
RECONCILE_PHASES = {'submitting', 'pending', 'handoff'}
ACTIVE_PHASES = RECONCILE_PHASES | {'awaiting_profile'}


class JobStore:
    def __init__(self, root, write_json):
        self.root, self.write_json = root, write_json

    @contextmanager
    def lease(self, owner, alias):
        import fcntl
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = hashlib.sha256(json.dumps([owner, alias]).encode()).hexdigest()
        descriptor = os.open(self.root / (name + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
            else:
                try:
                    yield True
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def read(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise ValueError('Choose a job ID returned by browser_app run or describe.')
        record = json.loads((self.root / (identifier + '.json')).read_text())
        if (record.get('version') != 1 or record.get('id') != identifier
                or not re.fullmatch(r'[a-f0-9]{64}', record.get('directory_key', ''))):
            raise ValueError('The saved job record needs inspection.')
        return record

    def save(self, record):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.write_json(self.root / (record['id'] + '.json'), record)

    def pending(self, owner, alias=None):
        paths = sorted(self.root.glob('*.json')) if self.root.exists() else []
        records = [self.read(path.stem) for path in paths]
        return [record for record in records if record['owner'] == owner and record['phase'] != 'done'
                and (alias is None or record['alias'] == alias)]

    def summaries(self, owner):
        return [{'job': record['id'], 'operation': record['operation'], 'session_alias': record['alias'],
                 'phase': record['phase'],
                 'profile': (record['handoff']['source']['profile'] if record['phase'] == 'awaiting_profile'
                             else record['attempts'][-1]['profile'] if record['attempts'] else None)}
                for record in self.pending(owner)]

    def quota(self, account, scope, value=None):
        key = hashlib.sha256(json.dumps([account, scope]).encode()).hexdigest()
        path = self.root.parent / 'quota' / (key + '.json')
        if value is not None:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.write_json(path, {'account': account, 'scope': scope, **value})
        return json.loads(path.read_text()) if path.exists() else {}

    def cursor(self, owner, alias, value=None):
        key = hashlib.sha256(json.dumps([owner, alias]).encode()).hexdigest()
        path = self.root.parent / 'cursors' / (key + '.json')
        if value is not None:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.write_json(path, value)
        return json.loads(path.read_text()) if path.exists() else {}


class RollingJob:
    def __init__(self, host, context, module, *, mode=None):
        self.host, self.context, self.module = host, context, module
        self.store = host.jobs(context.app)
        self.mode = mode
        self.record = None

    @property
    def attempt(self):
        return self.record['attempts'][-1]

    def save(self):
        self.record['updated_at'] = time.time()
        self.store.save(self.record)

    def checkpoint(self, value):
        self.record['checkpoint'] = copy.deepcopy(value)
        self.save()

    def policy_key(self, choice):
        rule, source = self.host.provider.rules.resolve(choice.app_id, choice.owner, choice.alias,
            choice.platform, self.host.provider.parents.get(choice.owner[1]))
        default = self.host.get_setting('profile_directory') if rule['mode'] == 'default' else None
        return hashlib.sha256(json.dumps([rule, source, default], sort_keys=True).encode()).hexdigest()

    def accepted(self, request_id, data=None):
        if not isinstance(request_id, str) or not request_id:
            raise ValueError('accepted needs the provider request ID.')
        if self.attempt.get('request_id') not in {None, request_id}:
            raise ValueError('This job already owns a different provider request.')
        self.attempt.update(request_id=request_id, accepted_data=data)
        self.record['phase'] = 'pending'
        self.save()
        with self.host.provider.lock:
            self.context._choice().pending = True

    def finish(self, value, phase):
        result = {**value, 'success': value['status'] in {'ok', 'running'}, 'job': self.record['id'],
                  'app': self.context.app, 'operation': self.record['operation'],
                  'session': self.context.session,
                  'profiles_tried': list(dict.fromkeys(attempt['profile'] for attempt in self.record['attempts'])),
                  'profile': self.attempt['profile'] if self.record['attempts'] else None}
        self.record.update(phase=phase, result=result)
        if phase == 'quota_exhausted':
            self.record['next_profile'] = self.record['start_profile']
            self.store.cursor(self.record['owner'], self.record['alias'], {
                'profile': self.record['start_profile'], 'identity': None,
                'start_profile': self.record['start_profile'], 'policy': self.record['policy']})
        self.save()
        with self.host.provider.lock:
            try:
                choice = self.context._choice()
            except RuntimeError:
                pass
            else:
                choice.pending = phase in RECONCILE_PHASES
        workspace = self.store.root.parent / self.record['directory_key']
        self.store.write_json(workspace / 'result.json', result)
        return result

    def inspect(self, message, **details):
        return self.finish({'status': 'needs_inspection', 'error': {'message': message}, **details},
                           self.record['phase'])

    def wait_for_profile(self, message=None):
        packet = self.record['handoff']
        source = packet['source']
        quota = source.get('quota') or source.get('result', {}).get('quota', {})
        attempt_result = self.attempt.get('result', {})
        if message is None and self.blocked_destination(attempt_result):
            message = attempt_result.get('message')
        return self.finish({'status': 'quota_exhausted', 'awaiting_profile': True,
                            'source_profile': source['profile'], 'quota': quota,
                            'handoff': packet['remaining'],
                            'message': message or 'Pass this job with an explicit target_profile to continue.'},
                           'awaiting_profile')

    def bind(self, profile, identity=None):
        current = get_profile(profile, self.host.provider.data)
        if identity is not None and list(current.identity) != list(identity):
            raise RuntimeError('The job source Chrome profile was replaced.')
        self.context.select_profile(profile)
        self.context._choice().directory_key = self.record['directory_key']
        return current

    def candidates(self, target_profile):
        profiles = list_profiles(self.host.provider.data)
        by_id = {profile.id: profile for profile in profiles}
        start = self.record['next_profile']
        if target_profile is not None:
            return [by_id[target_profile]] if target_profile in by_id else []
        if self.mode == 'manual' or (self.mode == 'automatic' and not self.record.get('handoff')):
            return [by_id[start]] if start in by_id else []
        preferred = self.host.get_setting('rolling_profiles.' + self.context.app) or []
        if not isinstance(preferred, list) or any(not isinstance(item, str) for item in preferred):
            raise ValueError('rolling_profiles must contain a list of Chrome directory IDs.')
        if self.mode == 'automatic':
            source = self.record['handoff']['source']['profile']
            return [by_id[identifier] for identifier in dict.fromkeys(preferred)
                    if identifier in by_id and identifier != source]
        order = list(dict.fromkeys([*preferred, *by_id]))
        order = [identifier for identifier in order if identifier in by_id]
        if start in order:
            index = order.index(start)
            order = order[index:] + order[:index]
        return [by_id[identifier] for identifier in order]

    def execute(self, operation, params, identifier=None, *, target_profile=None):
        for name in ('identify', 'handoff', 'resume'):
            if not callable(getattr(self.module, name, None)):
                raise ValueError('rotate_on_limit packages must define identify, handoff and resume callbacks.')
        choice = self.context._choice()
        owner, alias = self.context.session_id, choice.alias
        if not owner:
            raise ValueError('Rolling jobs require the calling Hermes conversation identity.')
        if target_profile is not None:
            if not self.mode or not identifier or not target_profile:
                raise ValueError('Choose a target_profile with an explicit manual handoff job ID.')
            target_profile = profile_directory(target_profile)
        with self.store.lease(owner, alias) as acquired:
            if not acquired:
                return {'success': True, 'status': 'running', 'app': self.context.app,
                        'message': 'This app session already has an operation in progress.'}
            if identifier:
                record = self.store.read(identifier)
                if record['owner'] != owner or record['alias'] != alias or record['operation'] != operation:
                    raise ValueError('Resume this job from its owning conversation, operation and session alias.')
            else:
                pending = self.store.pending(owner, alias)
                record = next((item for item in pending if item['operation'] == operation
                               and item['params'] == params), None)
                active = next((item for item in pending if item['phase'] in ACTIVE_PHASES), None)
                if active is not None and record is not active:
                    return {'success': False, 'status': 'needs_inspection', 'job': active['id'],
                            'message': 'This alias owns an unresolved provider request. Resume its job or use another alias.'}
                if record is None:
                    policy = self.policy_key(choice)
                    try:
                        initial = choice.profile or self.host.provider.choose_profile(choice)
                        start = initial.id
                    except (OSError, ValueError, RuntimeError, KeyError):
                        rule, _ = self.host.provider.rules.resolve(choice.app_id, choice.owner, choice.alias,
                            choice.platform, self.host.provider.parents.get(choice.owner[1]))
                        start = rule.get('profile') or self.host.get_setting('profile_directory') or 'Default'
                    start = profile_directory(start)
                    next_profile = start
                    cursor = self.store.cursor(owner, alias)
                    if cursor.get('policy') == policy:
                        try:
                            current = get_profile(cursor['profile'], self.host.provider.data)
                            valid = cursor.get('identity') is None or list(current.identity) == cursor['identity']
                        except (OSError, ValueError, RuntimeError, KeyError):
                            valid = False
                        if valid and (choice.profile is None or choice.profile.id == cursor['profile']):
                            next_profile, start = cursor['profile'], cursor['start_profile']
                    self.context.directory
                    checkpoint = self.context.directory / 'checkpoint.json'
                    record = {'version': 1, 'id': uuid.uuid4().hex, 'owner': owner, 'alias': alias,
                              'operation': operation, 'params': copy.deepcopy(params), 'current_params': copy.deepcopy(params),
                              'directory_key': choice.directory_key, 'start_profile': start,
                              'next_profile': next_profile, 'policy': policy,
                              'phase': 'probing', 'attempts': [],
                              'checkpoint': json.loads(checkpoint.read_text()) if checkpoint.exists() else None}
                    if self.mode is not None:
                        record['handoff_mode'] = self.mode
                    self.store.save(record)
            self.record = record
            self.mode = record.get('handoff_mode')
            if target_profile is not None and (self.mode != 'manual' or record['phase'] != 'awaiting_profile'):
                return {'success': False, 'status': 'needs_inspection', 'job': record['id'],
                        'message': 'A target_profile requires an awaiting manual handoff. Check the job without target_profile first.'}
            if record['phase'] == 'done':
                return {**record['result'], 'cached': True}
            if identifier and self.mode is not None:
                active = next((item for item in self.store.pending(owner, alias)
                               if item['id'] != identifier and item['phase'] in ACTIVE_PHASES), None)
                if active is not None:
                    return {'success': False, 'status': 'needs_inspection', 'job': active['id'],
                            'message': 'This alias has an active job. Resume that job or use another alias.'}
            self.context._choice().directory_key = record['directory_key']
            self.context.directory
            self.context._rolling = self
            try:
                if record['phase'] in RECONCILE_PHASES:
                    phase = record['phase']
                    if phase == 'handoff':
                        self.check_handoff_files(record['handoff'])
                    self.bind(self.attempt['profile'], self.attempt['identity'])
                    probe = self.module.identify(self.context, operation, copy.deepcopy(record['params']))
                    account = probe.get('account', {})
                    if not account.get('evidence') or account.get('id') != self.attempt['account']['id']:
                        return self.inspect('The source service account changed or is unavailable.')
                    observed = self.module.resume(self.context, copy.deepcopy(record))
                    if (self.not_submitted(observed) and not self.attempt.get('request_id')
                            and not self.blocked_destination(observed) and not self.blocked_source_retry(observed)):
                        if phase == 'handoff' and not isinstance(observed.get('params'), dict):
                            return self.inspect('Source reconciliation must return prepared destination params.')
                        self.record['current_params'] = observed.get('params', self.record['current_params'])
                        if not isinstance(self.record['current_params'], dict):
                            return self.inspect('Reconciled params must be an object.')
                        observed = self.submit()
                    if not self.outcome(observed):
                        return self.record['result']
                    if self.blocked_destination(observed):
                        return self.roll(target_profile, skip_attempt=self.attempt)
                if identifier:
                    retried = self.retry_saved_source(target_profile)
                    if retried is not None:
                        return retried
                return self.roll(target_profile)
            except Exception as error:
                return self.inspect(str(error), error={'type': type(error).__name__, 'message': str(error)})
            finally:
                self.context._rolling = None

    @staticmethod
    def not_submitted(value):
        request = value.get('request', {}) if isinstance(value, dict) else {}
        return request.get('state') == 'not_submitted' and bool(request.get('evidence'))

    def blocked_destination(self, value):
        packet = self.record.get('handoff')
        return (self.mode is not None and bool(packet)
                and self.attempt['profile'] != packet['source']['profile']
                and not self.attempt.get('request_id') and value.get('status') == 'failed'
                and self.not_submitted(value) and not value['request'].get('id'))

    def blocked_source_retry(self, value):
        return (self.attempt.get('retry_pause') and value.get('status') == 'needs_inspection'
                and self.not_submitted(value) and not value['request'].get('id'))

    def retry_saved_source(self, target_profile):
        packet = self.record.get('handoff')
        prepare = getattr(self.module, 'prepare_source_retry', None)
        if not packet or not callable(prepare):
            return None
        source = packet['source']
        phase = self.record['phase']
        manual = phase == 'awaiting_profile' and target_profile == source['profile']
        automatic = phase == 'quota_exhausted' and self.mode == 'automatic' and target_profile is None
        if not (manual or automatic) or source.get('result', {}).get('status') != 'quota_exhausted':
            return None
        try:
            profile = self.bind(source['profile'], source['identity'])
        except (OSError, ValueError, RuntimeError):
            if automatic:
                return None
            raise
        probe = self.module.identify(self.context, self.record['operation'], copy.deepcopy(self.record['params']))
        account, quota = probe.get('account', {}), probe.get('quota', {})
        if (not account.get('evidence') or account.get('id') != source['account']['id']
                or quota.get('scope') != source['scope']):
            if automatic:
                return None
            return self.inspect('The original service account or quota scope could not be verified.')
        self.check_handoff_files(packet)
        prepared = prepare(self.context, copy.deepcopy(packet))
        if prepared.get('status') != 'ok' or not isinstance(prepared.get('params'), dict):
            return self.inspect('The source project is not ready to resume.', provider_result=prepared)
        self.record['attempts'].append({'profile': profile.id, 'identity': list(profile.identity),
                                        'account': account, 'scope': source['scope'], 'retry_pause': phase})
        self.record['current_params'] = prepared['params']
        if not self.outcome(self.submit()):
            return self.record['result']
        if manual:
            return self.wait_for_profile()
        return self.roll(None, skip_attempt=self.attempt)

    def ready_for_handoff(self):
        with self.host.provider.lock:
            self.context._choice().pending = False
        self.record['phase'] = 'awaiting_profile' if self.mode == 'manual' else 'probing'

    def submit(self):
        if self.attempt.get('request_id'):
            return {'status': 'needs_inspection',
                    'request': {'state': 'accepted', 'id': self.attempt['request_id']},
                    'message': 'This attempt already recorded a provider request.'}
        self.record['phase'] = 'submitting'
        self.save()  # A crash after this point must reconcile the source before another submit.
        self.store.cursor(self.record['owner'], self.record['alias'], {
            'profile': self.attempt['profile'], 'identity': self.attempt['identity'],
            'start_profile': self.record['start_profile'], 'policy': self.record['policy']})
        return self.module.run(self.context, self.record['operation'], copy.deepcopy(self.record['current_params']))

    def save_handoff(self, value, source=None):
        self.record['handoff'] = {
            'job': self.record['id'], 'operation': self.record['operation'],
            'params': copy.deepcopy(self.record['params']),
            'source': copy.deepcopy(source if source is not None else self.attempt),
            'checkpoint': copy.deepcopy(self.record['checkpoint']),
            'remaining': copy.deepcopy(value.get('handoff', {})),
            'directory': str(self.context.directory)}
        self.save()

    @staticmethod
    def check_handoff_files(packet):
        files = packet['remaining'].get('files', [])
        if not isinstance(files, list) or any(not isinstance(path, str) or not os.path.isfile(path) for path in files):
            raise ValueError('Handoff local files are unavailable.')

    def outcome(self, value):
        if not isinstance(value, dict):
            self.inspect('The package must return a structured provider-request outcome.')
            return False
        request = value.get('request', {})
        state, identifier = request.get('state'), request.get('id')
        known = self.attempt.get('request_id')
        if known and identifier != known:
            self.inspect('The result does not match the accepted source request.', provider_result=value)
            return False
        self.attempt['result'] = copy.deepcopy(value)
        quota = value.get('quota', {})
        if (value.get('status') == 'quota_exhausted' and state == 'rejected'
                and quota.get('exhausted') is True and quota.get('evidence')
                and quota.get('scope') == self.attempt['scope']
                and (not known or request.get('terminal') is True)):
            self.store.quota(self.attempt['account']['id'], quota['scope'],
                             {**quota, 'observed_at': time.time()})
            self.ready_for_handoff()
            self.save_handoff(value)
            return True
        if self.blocked_destination(value):
            self.ready_for_handoff()
            self.save()
            return True
        if self.blocked_source_retry(value):
            phase = self.attempt['retry_pause']
            if phase == 'awaiting_profile':
                value = {**value, 'awaiting_profile': True, 'source_profile': self.attempt['profile']}
            self.finish(value, phase)
            return False
        if state in {'accepted', 'completed'} and isinstance(identifier, str) and identifier:
            self.accepted(identifier, request.get('data'))
            if state == 'completed' and value.get('status') == 'ok':
                self.finish(value, 'done')
            else:
                status = 'running' if value.get('status') == 'running' else 'needs_inspection'
                self.finish({**value, 'status': status}, 'pending')
        elif value.get('status') == 'ok' and self.not_submitted(value) and not known:
            self.finish(value, 'done')
        elif state == 'rejected' and request.get('evidence') and not known and value.get('status') == 'failed':
            self.finish(value, 'done')
        else:
            self.record['phase'] = 'pending'
            self.inspect('The provider outcome requires source reconciliation.', provider_result=value)
        return False

    def roll(self, target_profile, *, skip_attempt=None):
        if self.record['phase'] == 'awaiting_profile':
            if target_profile is None:
                return self.wait_for_profile()
            if target_profile == self.record['handoff']['source']['profile']:
                return self.wait_for_profile('Choose a different Chrome profile for the handoff.')
        visited, accounts = set(), set()
        if skip_attempt is not None:
            visited.add((skip_attempt['profile'], tuple(skip_attempt['identity'])))
        round_start = len(self.record['attempts'])
        source_refusal = bool(self.record['phase'] == 'probing' and self.record['attempts']
                              and self.attempt.get('result', {}).get('status') == 'quota_exhausted')
        while True:
            candidates = [profile for profile in self.candidates(target_profile)
                          if (profile.id, profile.identity) not in visited]
            if not candidates:
                if target_profile is not None:
                    return self.wait_for_profile('The requested profile is unavailable or has insufficient quota. Choose another target_profile.')
                packet = self.record.get('handoff') if self.mode == 'automatic' else None
                exhausted = bool(packet) or source_refusal or any(attempt.get('quota', {}).get('exhausted')
                                or attempt.get('result', {}).get('status') == 'quota_exhausted'
                                for attempt in self.record['attempts'][round_start:])
                status = 'quota_exhausted' if exhausted else 'needs_inspection'
                quotas = {}
                for attempt in self.record['attempts']:
                    if 'account' in attempt:
                        key = (attempt['account']['id'], attempt['scope'])
                        known = self.store.quota(*key)
                        if known.get('exhausted'):
                            quotas[key] = known
                result = {'status': status, 'exhausted': list(quotas.values()),
                          'message': 'All current candidates are exhausted or unavailable. Resume this job after availability changes.'}
                if packet:
                    result.update(source_profile=packet['source']['profile'], handoff=packet['remaining'])
                return self.finish(result, 'quota_exhausted' if exhausted else 'probing')
            profile = candidates[0]
            visited.add((profile.id, profile.identity))
            if not self.record['attempts'] and profile.id != self.record['next_profile']:
                self.save_handoff({}, {'profile': self.record['next_profile'], 'unavailable': True})
            try:
                self.bind(profile.id, profile.identity)
            except (OSError, ValueError, RuntimeError):
                current = list_profiles(self.host.provider.data)
                if not any(item.id == profile.id and item.identity == profile.identity for item in current):
                    continue
                raise
            self.record['attempts'].append({'profile': profile.id, 'identity': list(profile.identity)})
            if target_profile is None:
                self.record['phase'] = 'probing'
            self.save()
            probe = self.module.identify(self.context, self.record['operation'], copy.deepcopy(self.record['params']))
            if probe.get('available') is False and probe.get('evidence'):
                self.attempt['unavailable'] = copy.deepcopy(probe)
                if self.mode is None and not self.record.get('handoff'):
                    self.save_handoff(probe)
                self.save()
                continue
            account, quota = probe.get('account', {}), probe.get('quota', {})
            if (not isinstance(account.get('id'), str) or not account['id'] or not account.get('evidence')
                    or not isinstance(quota.get('scope'), str) or not quota['scope']):
                raise ValueError('identify must provide service account evidence and the operation quota scope.')
            self.attempt.update(account=copy.deepcopy(account), scope=quota['scope'])
            key = (account['id'], quota['scope'])
            source = self.record.get('handoff', {}).get('source', {})
            same_account = self.mode is not None and account['id'] == source.get('account', {}).get('id')
            if key in accounts or same_account:
                self.attempt['duplicate_account'] = True
                self.save()
                if target_profile is not None and same_account:
                    return self.wait_for_profile('The requested profile uses the same service account. Choose a different account.')
                continue
            accounts.add(key)
            cached = self.store.quota(*key)
            if quota.get('available') is False and quota.get('evidence'):
                self.attempt['quota'] = {**quota, 'exhausted': True, 'observed_at': time.time()}
                self.store.quota(*key, self.attempt['quota'])
            elif quota.get('available') is True and quota.get('evidence'):
                self.store.quota(*key, {**quota, 'exhausted': False, 'observed_at': time.time()})
            elif cached.get('exhausted') and not quota.get('requires_fresh_evidence'):
                self.attempt['quota'] = cached
            if 'quota' in self.attempt:
                if not self.record.get('handoff'):
                    if self.mode == 'manual':
                        self.record['phase'] = 'awaiting_profile'
                    self.save_handoff(probe)
                    if self.mode == 'manual':
                        return self.wait_for_profile()
                self.save()
                continue
            if self.record.get('handoff'):
                packet = copy.deepcopy(self.record['handoff'])
                self.check_handoff_files(packet)
                self.record['phase'] = 'handoff'
                self.save()
                packet['target'] = {'profile': profile.id, 'account': copy.deepcopy(account)}
                prepared = self.module.handoff(self.context, packet)
                if prepared.get('request', {}).get('state') in {'accepted', 'completed'}:
                    self.outcome(prepared)
                    return self.record['result']
                if prepared.get('status') != 'ok' or not isinstance(prepared.get('params'), dict):
                    return self.inspect('The destination handoff requires inspection.', provider_result=prepared)
                self.record['current_params'] = copy.deepcopy(prepared['params'])
                self.save()
            if not self.outcome(self.submit()):
                return self.record['result']
            if self.mode == 'manual':
                return self.wait_for_profile()
