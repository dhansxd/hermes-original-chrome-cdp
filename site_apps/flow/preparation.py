"""Prepare account-local entities while the parent generation awaits submission."""
import hashlib
import json

from . import entities
from .ui import UI


class EntityContext:
    def __init__(self, context, position, key):
        self.parent = context
        self.position = position
        profile = hashlib.sha256(context.profile.encode()).hexdigest()[:12]
        self.directory = context.directory / 'preparation' / context.job_id / profile / key
        self.directory.mkdir(parents=True, exist_ok=True)
        self.job_id = context.job_id + '-' + key

    @property
    def profile(self):
        return self.parent.profile

    def browser_exec(self, code, **kwargs):
        return self.parent.browser_exec(code, **kwargs)

    def checkpoint(self, value):
        path = self.directory / 'checkpoint.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False))
        temporary.replace(path)
        self.parent.checkpoint(self.position)
        return path

    def accepted(self, identifier, data=None):
        """The child checkpoint records this entity's preparation receipt."""


def active(context, position):
    key = position.get('active_entity')
    return EntityContext(context, position, key) if key else None


def resume_before_probe(context):
    path = context.directory / 'checkpoint.json'
    position = json.loads(path.read_text()) if path.exists() else {}
    if (position.get('job') != context.job_id or position.get('operation') != 'handoff'
            or position.get('profile') != context.profile):
        return False
    child = active(context, position)
    if not child:
        return False
    state = child.directory / 'checkpoint.json'
    if state.exists() and json.loads(state.read_text()).get('operation') == 'create_character':
        entities.capture_character(child, UI(child))
    return UI(context).read('location.href').startswith(position['params']['project'])


def prepare(context, position, key, kind, params):
    child = EntityContext(context, position, key)
    result_path = child.directory / 'result.json'
    if result_path.exists():
        data = json.loads(result_path.read_text())
        entities.remember(context, data)
        if position.get('active_entity') == key:
            position.pop('active_entity')
            context.checkpoint(position)
        return data
    position['active_entity'] = key
    context.checkpoint(position)
    ui = UI(child)
    checkpoint = child.directory / 'checkpoint.json'
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text())
        result = (entities.save_voice(child, ui, saved) if kind == 'voice'
                  else entities.finish_character(child, ui, saved))
    else:
        result = (entities.create_voice(child, ui, params) if kind == 'voice'
                  else entities.create_character(child, ui, params))
    if result.get('status') != 'ok':
        raise RuntimeError('Resume the original ' + kind + ' preparation: ' + (result.get('message') or result['status']))
    temporary = result_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result['data'], ensure_ascii=False))
    temporary.replace(result_path)
    entities.remember(context, result['data'])
    position.pop('active_entity', None)
    context.checkpoint(position)
    return result['data']


def references(context, position):
    """Create target voices before assigning them to target characters."""
    refs = position['params'].get('references', [])
    suffix = context.job_id[:8] + '-' + hashlib.sha256(context.profile.encode()).hexdigest()[:4]
    voices = {}
    prepared = []
    for index, reference in enumerate(refs):
        if reference.get('kind') != 'voice':
            continue
        definition = reference['definition']
        source_name = definition.get('name') or reference['title']
        params = {key: definition[key] for key in ('base', 'dialogue', 'performance')}
        params['name'] = source_name + ' ' + suffix
        data = prepare(context, position, 'voice-' + str(index), 'voice', params)
        voices[source_name] = data['name']
        reference['title'] = data['name']
        prepared.append({'kind': 'voice', 'source_name': source_name, 'name': data['name'], 'id': data['id'],
                         'method': 'recreated_from_definition', 'file': data['file']})
    for index, reference in enumerate(refs):
        if reference.get('kind') != 'character':
            continue
        definition = reference['definition']
        source_name = definition.get('name') or reference['title']
        params = {'name': source_name + ' ' + suffix, 'path': definition['path'],
                  'description': definition.get('description', '')}
        voice = definition.get('voice')
        voice_definition = definition.get('voice_definition')
        if voice_definition and voice not in voices:
            voice_params = {key: voice_definition[key] for key in ('base', 'dialogue', 'performance')}
            voice_params['name'] = voice + ' ' + suffix
            data = prepare(context, position, 'character-voice-' + str(index), 'voice', voice_params)
            voices[voice] = data['name']
            prepared.append({'kind': 'voice', 'source_name': voice, 'name': data['name'], 'id': data['id'],
                             'method': 'recreated_from_definition', 'file': data['file']})
        if voice:
            params['voice'] = voices.get(voice, voice)
        data = prepare(context, position, 'character-' + str(index), 'character', params)
        reference['title'] = data['name']
        prepared.append({'kind': 'character', 'source_name': source_name, 'name': data['name'], 'id': data['id'],
                         'method': 'recreated_from_definition'})
    return prepared
