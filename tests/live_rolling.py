"""Rolling through native Hermes tools and CDP UI on a local provider fixture."""
import json
import shutil
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_windows import window_keys, verify_cleanup

import hermes_bootstrap

sys._hermes_pin_default_home = False
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.browser_registry import get_provider
from gateway.session_context import clear_session_vars, set_session_vars
from hermes_constants import set_hermes_home_override
from hermes_cli.plugins import get_plugin_manager, invoke_hook
from hermes_cli.plugins_manifest import parse_manifest_file
from native_windows import native_fixture_call
from tools.browser_session_lifecycle import cleanup_profile_browsers
from model_tools import handle_function_call
import tools.browser_use_cli


class Fixture(BaseHTTPRequestHandler):
    scenario = None
    requests = {}
    counts = {}

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        profile = query.get('profile', [''])[0]
        item = self.scenario['profiles'].get(profile, {})
        if parsed.path in {'/submit', '/observe'}:
            job = query['job'][0]
            if parsed.path == '/submit':
                self.counts[job] = self.counts.get(job, 0) + 1
                value = {'job': job, 'profile': profile,
                         'state': 'rejected' if item.get('mode') in {'quota', 'partial'} else 'accepted',
                         'id': 'request-' + profile.replace(' ', '-') + '-' + job}
                self.requests[job] = value
            else:
                value = {**self.requests[job], 'state': 'completed'}
            body = json.dumps(value)
            content_type = 'application/json'
        else:
            account = json.dumps(item.get('account', profile))
            body = '''<!doctype html><title>Native rolling fixture</title>
<button id="submit">Submit fixture</button><button id="observe">Observe result</button>
<script>
document.body.dataset.account=ACCOUNT;
window.fixtureMarker=crypto.randomUUID();
for(const action of ['submit','observe']){
 document.getElementById(action).onclick=event=>{
  const query=new URLSearchParams(location.search);
  query.set('job',event.currentTarget.dataset.job);
  window.fixtureResponse=fetch('/'+action+'?'+query).then(response=>response.json());
 };
}
document.body.insertAdjacentHTML('beforeend','<div id="ready"></div>');
</script>'''.replace('ACCOUNT', account)
            content_type = 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


def verify():
    native_windows_before = window_keys()
    source = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    report = {}
    with tempfile.TemporaryDirectory(prefix='hermes-rolling-acceptance-') as temporary:
        home = Path(temporary).resolve()
        directory = home / 'apps/fixture'
        directory.mkdir(parents=True)
        shutil.copyfile(source / 'tests/fixtures/rolling_app.py', directory / 'app.py')
        (directory / 'app.json').write_text(json.dumps({
            'api_version': 1, 'id': 'fixture', 'profile_policy': 'rotate_on_limit',
            'operations': {'generate': {'parameters': {'type': 'object'}}}}))
        other = home / 'apps/other'
        other.mkdir()
        (other / 'app.json').write_text(json.dumps({'api_version': 1, 'id': 'other',
            'operations': {'inspect': {'parameters': {'type': 'object'}}}}))
        (other / 'app.py').write_text('''def run(context, operation, params):
    code='js("window.otherMarker=17")' if params.get('start') else 'assert js("window.otherMarker")==17'
    native=context.browser_exec(code)
    return {'status':'ok' if native.get('success') else 'failed','data':native}
''')
        (home / 'config.yaml').write_text('''browser:
  cloud_provider: original-chrome-default
  auto_local_for_private_urls: false
  allow_private_urls: true
plugins:
  enabled: [original-chrome-default]
  entries:
    original-chrome-default:
      granted_capabilities: [tools.override]
      settings:
        apps_directory: ''' + str(home / 'apps') + '\n')
        turns = {task: uuid.uuid4().hex for task in ('guardian', 'work', 'source', 'peer')}
        with set_hermes_home_override(home):
            manager = get_plugin_manager()
            manager._load_plugin(parse_manifest_file(source / 'plugin.yaml', source, 'user', ''))
            provider = get_provider('original-chrome-default')

            def call(task, tool='browser_exec', **args):
                if tool == 'browser_exec' and 'code' not in args:
                    session = args.pop('session', 'default')
                    args = {'site_control': json.dumps(args), 'session': session}
                with set_hermes_home_override(home):
                    tokens = set_session_vars(platform='cli', session_key='rolling-' + task, session_id=task + '-chat')
                    try:
                        if tool == 'browser_exec' and 'code' in args:
                            value = native_fixture_call(provider, task, task + '-chat', turns[task], args)
                        else:
                            value = handle_function_call(tool, args, task_id=task, session_id=task + '-chat',
                                                        turn_id=turns[task], tool_call_id=uuid.uuid4().hex)
                        result = json.loads(value) if isinstance(value, str) else value
                        assert result.get('success'), result
                        return result
                    finally:
                        clear_session_vars(tokens)

            def run(task, job=None):
                args = {'action': 'run', 'app': 'fixture', 'operation': 'generate', 'session': task,
                        'params': {'prompt': 'local fixture', 'project': 'source-project'}}
                if job:
                    args['job'] = job
                return call(task, **args)

            def save():
                (directory / 'scenario.json').write_text(json.dumps(Fixture.scenario))

            try:
                profiles = call('guardian', tool='chrome_profiles', action='list')['profiles']
                assert len(profiles) >= 3, 'This native test needs three existing Chrome profiles.'
                first, second, third = [row['id'] for row in profiles[:3]]
                Fixture.scenario = {'native_url': f'http://127.0.0.1:{server.server_port}',
                                    'profiles': {row['id']: {} for row in profiles}}
                Fixture.scenario['profiles'][first]['mode'] = 'quota'
                Fixture.scenario['profiles'][second]['mode'] = 'quota'
                save()
                guardian = call('guardian', tool='browser_exec', session='guardian',
                                code='js("window.guardianMarker=42")')
                call('guardian', action='run', app='other', operation='inspect', session='site', params={'start': True})
                observer = next(iter(provider.sessions.values())).wire
                guardian_targets = set().union(*(item.owned for item in provider.sessions.values()))
                manual = {row['targetId'] for row in observer.call('Target.getTargets')['targetInfos']
                          if row.get('type') == 'page'} - guardian_targets
                completed = run('work')
                assert completed['profile'] == third
                assert Fixture.counts[completed['job']] == 3
                events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
                assert [event['profile'] for event in events if event['kind'] == 'run'] == [first, second, third]
                report['native_cdp_ui_a_b_c_and_destination_handoff'] = True
                disabled = call('guardian', action='disable', app='fixture')
                assert not disabled['cleanup_pending']
                call('guardian', tool='browser_exec', session=guardian['session'],
                     code='assert js("window.guardianMarker")==42')
                call('guardian', action='run', app='other', operation='inspect', session='site', params={})
                call('guardian', action='enable', app='fixture')
                report['disable_after_rolling_releases_current_names_and_preserves_peers'] = True

                Fixture.scenario['profiles'][first].update(mode='accepted', available=True)
                save()
                pending = run('source')
                assert pending['status'] == 'running'
                initial_events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
                marker = next(event['value'] for event in initial_events if event['kind'] == 'browser'
                              and event['job'] == pending['job'] and event.get('action') is None)
                Fixture.scenario['profiles'][first]['mode'] = 'quota'
                save()
                peer = run('peer')
                assert peer['profile'] == third
                source_result = run('source', pending['job'])
                call('guardian', action='run', app='other', operation='inspect', session='site', params={})
                assert source_result['request']['id'] == pending['request']['id']
                assert Fixture.counts[pending['job']] == 1
                all_events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
                source_markers = [event['value'] for event in all_events if event['kind'] == 'browser'
                                  and event['job'] == pending['job'] and event.get('action') is None]
                assert all(value == marker for value in source_markers)
                report['pending_source_document_survives_peer_rolling_without_resubmit'] = True
                report['ordinary_browser_and_other_extension_preserved_during_rolling'] = True

                Fixture.scenario['profiles'][first].update(mode='accepted', available=True)
                save()
                turns['source'] = uuid.uuid4().hex
                pending = run('source')
                invoke_hook('agent_loop_stopped', session_key='rolling-source', platform='cli',
                            reason='user_stop', invalidation_reason='session_interrupt')
                call('guardian', tool='browser_exec', session=guardian['session'],
                     code='assert js("window.guardianMarker")==42')
                assert provider.unload()
                cleanup_profile_browsers(str(home))
                manager.unload('original-chrome-default')
                manager._load_plugin(parse_manifest_file(source / 'plugin.yaml', source, 'user', ''))
                provider = get_provider('original-chrome-default')
                turns['source'] = uuid.uuid4().hex
                restored = run('source', pending['job'])
                assert restored['request']['id'] == pending['request']['id']
                assert Fixture.counts[pending['job']] == 1
                report['stop_and_host_reload_recover_original_receipt_without_submit'] = True
                observer = next(iter(provider.sessions.values())).wire
                remaining = {row['targetId'] for row in observer.call('Target.getTargets')['targetInfos']}
                assert manual <= remaining
                assert provider.unload()
                assert not provider.sessions and not provider.owners
                report['manual_targets_preserved_and_owned_resources_released'] = True
            finally:
                cleanup_profile_browsers(str(home))
                provider.unload()
                manager.unload('original-chrome-default')
                server.shutdown()
    verify_cleanup(native_windows_before)
    report['native_windows_returned_to_baseline'] = True
    return report


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
