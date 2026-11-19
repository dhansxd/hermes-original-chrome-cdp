"""Profile policy precedence stored through the public plugin configuration API."""
import hashlib
import json


SCOPES = {'session', 'agent', 'subagent', 'platform', 'default'}


def validate_rule(value):
    if (not isinstance(value, dict) or not isinstance(value.get('mode'), str)
            or value['mode'] not in {'fixed', 'default', 'random'}):
        raise ValueError('Choose profile mode fixed, default, or random.')
    if value['mode'] == 'fixed' and (not isinstance(value.get('profile'), str) or not value['profile']):
        raise ValueError('A fixed profile rule needs a Chrome directory ID.')
    identity = value.get('identity')
    if identity is not None and (not isinstance(identity, (list, tuple)) or len(identity) != 3
                                 or any(type(part) not in (int, float, type(None)) for part in identity)):
        raise ValueError('The saved Chrome profile identity is invalid. Select the profile again.')
    return value


class ProfileRules:
    def __init__(self, get_setting, set_setting):
        self.get_setting, self.set_setting = get_setting, set_setting

    @staticmethod
    def key(app, scope, target, alias=''):
        parts = json.dumps([app, scope, target, alias], ensure_ascii=False)
        return 'profile_rules.' + hashlib.sha256(parts.encode()).hexdigest()

    def read(self, app, scope, target, alias=''):
        value = self.get_setting(self.key(app, scope, target, alias))
        return validate_rule(value) if value is not None else None

    def prepare_change(self, app, scope, target, alias, rule):
        if not isinstance(scope, str) or scope not in SCOPES or not isinstance(target, str) or not target:
            raise ValueError('Choose a profile rule scope and target.')
        if self.set_setting is None:
            raise RuntimeError('The plugin configuration writer is unavailable.')
        value = None if rule is None else {
            **validate_rule(rule), 'app': app, 'scope': scope, 'target': target, 'session': alias}
        return self.key(app, scope, target, alias), value

    def apply(self, change):
        key, value = change
        self.set_setting(key, value)
        return value

    def change(self, app, scope, target, alias, rule):
        return self.apply(self.prepare_change(app, scope, target, alias, rule))

    def resolve(self, app, owner, alias, platform, parent=None, *, proposed=None):
        def read(scope, target, alias=''):
            if proposed is not None and self.key(app, scope, target, alias) == proposed[0]:
                return proposed[1]
            return self.read(app, scope, target, alias)

        task, chat, _ = owner
        candidates = [('session', chat, alias), ('agent', task, '')]
        if parent:
            candidates.extend([('subagent', parent['role'], ''), ('subagent', '*', '')])
        if platform:
            candidates.append(('platform', platform, ''))
        for scope, target, name in candidates:
            rule = read(scope, target, name)
            if rule is not None:
                return rule, scope
        if parent:
            rule = read('session', parent['session_id'], alias)
            if rule is not None:
                return rule, 'parent'
            profile = parent['profiles'].get((app, alias))
            if profile is not None:
                return {'mode': 'fixed', 'profile': profile.id, 'identity': profile.identity}, 'parent'
        return read('default', '*') or {'mode': 'default'}, 'default'
