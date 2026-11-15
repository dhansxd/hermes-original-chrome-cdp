"""Synthetic provider used only by rolling acceptance tests."""
import json
import os
from pathlib import Path
from urllib.parse import urlencode


def settings():
    return json.loads(Path(__file__).with_name('scenario.json').read_text())


def event(context, kind, **data):
    with Path(__file__).with_name('events.jsonl').open('a') as stream:
        stream.write(json.dumps({'kind': kind, 'profile': context.profile,
                                'job': context.job_id, **data}) + '\n')


def browser(context, action=None):
    config = settings()
    url = config['native_url'] + '/?' + urlencode({'profile': context.profile})
    code = f'if js("location.href") != {url!r}: goto_url({url!r})\n'
    code += 'wait_for_element("#ready", timeout=10)\n'
    if action:
        expression = "document.querySelector('#" + action + "').dataset.job=" + json.dumps(context.job_id)
        code += f'js({expression!r})\n'
        selector = '#' + action
        expression = "(()=>{const r=document.querySelector(" + json.dumps(selector) + ").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()"
        code += f'r=js({expression!r})\nclick_at_xy(r["x"],r["y"])\n'
        code += 'print(js("window.fixtureResponse.then(x=>JSON.stringify(x))"))'
    else:
        code += 'print(js("JSON.stringify({account:document.body.dataset.account,origin:performance.timeOrigin,marker:window.fixtureMarker})"))'
    result = context.browser_exec(code)
    if not result.get('success'):
        raise RuntimeError(result)
    value = json.loads(result['output'].strip())
    event(context, 'browser', action=action, value=value, session=result['session'])
    return value


def identify(context, operation, params):
    config = settings()
    item = config['profiles'][context.profile]
    event(context, 'identify')
    account = item.get('account', context.profile)
    if config.get('native_url'):
        account = browser(context)['account']
    if item.get('unavailable'):
        return {'available': False, 'evidence': 'Fixture sign-in is absent.'}
    quota = {'scope': item.get('scope', 'video')}
    if 'available' in item:
        quota.update(available=item['available'], evidence='Fixture quota readback.')
    return {'account': {'id': account, 'evidence': 'Fixture account readback.'},
            'quota': quota}


def handoff(context, packet):
    event(context, 'handoff', packet=packet)
    if settings().get('handoff_timeout'):
        raise TimeoutError('Fixture destination preparation was interrupted.')
    params = {**packet['params'], 'project': 'destination-' + context.profile}
    if 'remaining_count' in packet['remaining']:
        params['count'] = packet['remaining']['remaining_count']
    return {'status': 'ok', 'params': params}


def completed(context, identifier):
    path = context.directory / (identifier + '.txt')
    path.write_text('fixture output')
    context.checkpoint({'phase': 'downloaded', 'files': [str(path)]})
    return {'status': 'ok', 'request': {'state': 'completed', 'id': identifier},
            'data': {'files': [str(path)]}}


def run(context, operation, params):
    item = settings()['profiles'][context.profile]
    event(context, 'run', params=params)
    mode = item.get('mode', 'complete')
    if settings().get('native_url'):
        observed = browser(context, 'submit')
        assert observed['job'] == context.job_id and observed['profile'] == context.profile
        assert observed['state'] == ('rejected' if mode in {'quota', 'partial'} else 'accepted')
    if mode in {'quota', 'partial', 'invalid_quota'}:
        remaining = {}
        if mode == 'partial':
            path = context.directory / 'already-finished.txt'
            path.write_text('preserve completed fixture')
            remaining = {'files': [str(path)], 'remaining_count': max(0, params.get('count', 2) - 1),
                         'completed': [str(path)]}
        context.checkpoint({'phase': 'quota', 'project': params.get('project')})
        return {'status': 'quota_exhausted', 'request': {'state': 'rejected'},
                'quota': {'scope': item.get('scope', 'video'), 'exhausted': True,
                          'reset_at': item.get('reset_at'),
                          'evidence': '' if mode == 'invalid_quota' else 'Fixture provider rejected this request for quota.'},
                'handoff': remaining}
    if mode == 'timeout':
        raise TimeoutError('Fixture submit outcome was not observed.')
    if mode == 'selector':
        raise LookupError('Fixture selector is absent.')
    if mode == 'rejected':
        return {'status': 'failed', 'request': {'state': 'rejected', 'evidence': 'Fixture definitive non-quota refusal.'}}
    identifier = 'request-' + context.profile.replace(' ', '-') + '-' + context.job_id
    context.accepted(identifier, {'project': params.get('project')})
    if mode == 'crash':
        os._exit(23)
    if mode == 'accepted':
        return {'status': 'running', 'request': {'state': 'accepted', 'id': identifier}}
    return completed(context, identifier)


def resume(context, record):
    item = settings()['profiles'][context.profile]
    event(context, 'resume', record=record)
    mode = item.get('resume', 'complete')
    if settings().get('native_url'):
        observed = browser(context, 'observe')
        assert observed['job'] == record['id'] and observed['state'] == 'completed'
        assert observed['id'] == record['attempts'][-1]['request_id']
    if mode == 'not_submitted':
        return {'status': 'ok', 'request': {'state': 'not_submitted', 'evidence': 'Fixture confirms absence.'},
                'params': {**record['params'], 'project': 'destination-' + context.profile}}
    identifier = record['attempts'][-1].get('request_id')
    if not identifier:
        identifier = 'reconciled-' + record['id']
    if mode == 'wrong_id':
        identifier = 'wrong-request'
    if mode == 'quota':
        return {'status': 'quota_exhausted', 'request': {'state': 'rejected'},
                'quota': {'scope': 'video', 'exhausted': True, 'evidence': 'Fixture quota message.'}}
    if mode == 'running':
        return {'status': 'running', 'request': {'state': 'accepted', 'id': identifier}}
    return completed(context, identifier)
