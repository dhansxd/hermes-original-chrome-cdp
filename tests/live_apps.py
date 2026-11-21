"""Native site-package acceptance using local fixtures and original Chrome."""
import concurrent.futures
import json
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import hermes_bootstrap

sys._hermes_pin_default_home = False
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.browser_registry import get_provider
from gateway.session_context import clear_session_vars, set_session_vars
from hermes_constants import set_hermes_home_override
from hermes_cli.plugins import get_plugin_manager, invoke_hook
from hermes_cli.plugins_manifest import parse_manifest_file
from tools.browser_session_lifecycle import cleanup_profile_browsers
from tools.registry import registry
from model_tools import handle_function_call
import tools.browser_use_cli


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<!doctype html><title>Extension fixture</title><input id=field>')

    def log_message(self, *args):
        pass


APP_SOURCE = r'''import json

def run(context, operation, params):
    code = ""
    if params.get('url'):
        code += f"goto_url({params['url']!r})\n"
        expression = 'window.fixtureMarker=' + json.dumps(params['marker'])
        code += f"js({expression!r})\n"
    code += 'print(js("JSON.stringify({marker:window.fixtureMarker,origin:performance.timeOrigin})"))'
    native = context.browser_exec(code)
    context.checkpoint({'marker': params.get('marker'), 'phase': params.get('status', 'ok')})
    return {'status': params.get('status', 'ok') if native['success'] else 'failed', 'data': {
        'task': context.task_id, 'chat': context.session_id, 'turn': context.turn_id,
        'revision': 1, 'directory': str(context.directory), 'native': native}}
'''


def package(root, identifier):
    directory = root / identifier
    directory.mkdir(parents=True)
    (directory / 'app.json').write_text(json.dumps({
        'api_version': 1, 'id': identifier, 'name': identifier,
        'operations': {'inspect': {'parameters': {'type': 'object'}}},
    }))
    (directory / 'app.py').write_text(APP_SOURCE)
    return directory


def verify():
    source = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'
    report = {}
    with tempfile.TemporaryDirectory(prefix='hermes-app-acceptance-') as temporary:
        home = Path(temporary).resolve()
        packages = home / 'apps'
        directory = package(packages, 'fixture')
        (directory / 'SKILL.md').write_text('Local fixture guide')
        (home / 'config.yaml').write_text('''browser:
  cloud_provider: original-chrome-default
  auto_local_for_private_urls: false
  allow_private_urls: true
  inactivity_timeout: 600
plugins:
  enabled: [original-chrome-default]
  entries:
    original-chrome-default:
      granted_capabilities: [tools.override]
      settings:
        apps_directory: ''' + str(packages) + '\n')
        turns = {task: uuid.uuid4().hex for task in ('parent', 'child', 'channel')}
        with set_hermes_home_override(home):
            manager = get_plugin_manager()
            native_entry = registry.get_entry('browser_exec')
            manager._load_plugin(parse_manifest_file(source / 'plugin.yaml', source, 'user', ''))
            provider = get_provider('original-chrome-default')

            def call(task, tool='browser_exec', platform='cli', **args):
                if tool == 'browser_exec' and 'code' not in args:
                    session = args.pop('session', 'default')
                    args = {'site_control': json.dumps(args), 'session': session}
                with set_hermes_home_override(home):
                    tokens = set_session_vars(platform=platform, session_key='apps-fixture-' + task,
                                              session_id=task + '-chat')
                    try:
                        value = handle_function_call(tool, args, task_id=task, session_id=task + '-chat',
                                                    turn_id=turns[task], tool_call_id=uuid.uuid4().hex)
                        result = json.loads(value) if isinstance(value, str) else value
                        assert result.get('success'), result
                        return result
                    finally:
                        clear_session_vars(tokens)

            def run(task, app='fixture', initialize=False, status=None, **extra):
                params = {'url': url, 'marker': task + '-' + app} if initialize else {}
                if status:
                    params['status'] = status
                result = call(task, action='run', app=app, operation='inspect',
                              session='same' if app == 'fixture' else app, params=params, **extra)
                data = result['data']
                assert (data['task'], data['chat'], data['turn']) == (
                    task, task + '-chat', turns[task]), data
                result['document'] = json.loads(data['native']['output'].strip())
                return result

            try:
                assert registry.get_entry('browser_app', scope=manager.scope_key) is None
                assert 'Unknown tool' in registry.dispatch('browser_app', {}, scope=manager.scope_key)
                assert {entry['id'] for entry in call('parent', action='list')['apps']} == {'fixture', 'gemini', 'flow'}
                assert call('parent', action='describe', app='fixture')['guide'] == 'Local fixture guide'
                assert not provider.sessions and not provider.owners
                report['discovery_and_guide_without_browser'] = True
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    futures = [pool.submit(run, task, initialize=True,
                                           platform='telegram' if task == 'channel' else 'cli')
                               for task in turns]
                    first = [future.result() for future in futures]
                assert len({value['session'] for value in first}) == 3
                report['native_parent_child_channel_identities'] = True
                repeat = run('parent')
                assert repeat['document'] == first[0]['document']
                assert repeat['session'] == first[0]['session']
                report['same_owned_document_without_navigation'] = True

                inspected = call('parent', tool='browser_exec', session='same',
                                 code='assert js("window.fixtureMarker")=="parent-fixture"')
                assert inspected['session'] == repeat['session']
                report['targeted_native_inspection_reuses_app_session'] = True
                ordinary = call('parent', tool='browser_exec', session='independent-task',
                                code=f'goto_url({url!r}); js("window.ordinaryMarker=42")')
                assert ordinary['session'] != repeat['session']

                added = package(packages, 'new-site')
                metadata = json.loads((added / 'app.json').read_text())
                metadata['operations']['new-operation'] = {'parameters': {'type': 'object'}}
                (added / 'app.json').write_text(json.dumps(metadata))
                assert {entry['id'] for entry in call('parent', action='list')['apps']} == {'fixture', 'gemini', 'flow', 'new-site'}
                assert 'new-operation' in call('child', action='describe', app='new-site')['app']['operations']
                new_site = run('parent', app='new-site', initialize=True)
                operation = call('child', action='run', app='new-site', operation='new-operation',
                                 session='new-site', params={'url': url, 'marker': 'new-child'})
                assert operation['data']['task'] == 'child'
                report['new_site_and_operation_without_registration'] = True
                (directory / 'app.py').write_text(APP_SOURCE.replace("'revision': 1", "'revision': 2"))
                assert run('parent')['data']['revision'] == 2
                assert run('child')['data']['revision'] == 2
                report['source_updates_in_both_agents_without_reload'] = True

                sessions = list(provider.sessions.values())
                observer = next(item.wire for item in sessions if item.cache_key.split('@', 1)[0]
                                == 'bu-named-' + repeat['session'])
                owned = set().union(*(item.owned for item in sessions))
                manual_before = {row['targetId'] for row in observer.call('Target.getTargets')['targetInfos']
                                 if row.get('type') == 'page'} - owned
                windows = [{observer.call('Browser.getWindowForTarget', {'targetId': row['targetId']})['windowId']
                            for row in item._inventory() if row.get('type') == 'page'} for item in sessions]
                assert len(sessions) == 6 and all(windows), len(sessions)
                assert all(left.isdisjoint(right) for index, left in enumerate(windows)
                           for right in windows[index + 1:])
                assert len({item.profile for item in sessions}) == 1
                report['six_distinct_windows_on_shared_profile'] = True

                inventory = call('parent', tool='chrome_profiles', action='list', session='same')['profiles']
                assert len(inventory) >= 2, 'This native test needs two existing Chrome profiles.'
                destination = inventory[1]['id']
                call('parent', tool='chrome_profiles', action='set_rule', scope='subagent',
                     target='fixture-writer', app='new-site', mode='fixed', profile=destination,
                     session='new-site')
                invoke_hook('subagent_start', parent_session_id='parent-chat', child_session_id='child-chat',
                            child_role='fixture-writer', parent_turn_id=turns['parent'])
                call('child', tool='chrome_profiles', action='clear_rule', scope='session',
                     app='new-site', session='new-site')
                child_site = run('child', app='new-site', initialize=True, status='running')
                assert child_site['profile'] == destination
                assert run('parent', app='new-site')['profile'] == new_site['profile']
                assert run('parent')['document'] == first[0]['document']
                report['child_role_profile_switch_is_scoped_to_its_app'] = True
                invoke_hook('on_session_end', session_id='child-chat', task_id='child',
                            completed=True, failed=False, interrupted=False)
                turns['child'] = uuid.uuid4().hex
                resumed = run('child', app='new-site', status='running')
                assert resumed['document'] == child_site['document']
                assert resumed['session'] == child_site['session']
                assert resumed['data']['directory'] == child_site['data']['directory']
                report['pending_app_retains_document_profile_and_artifacts_across_turns'] = True

                invoke_hook('agent_loop_stopped', session_key='apps-fixture-child', platform='cli',
                            reason='user_stop', invalidation_reason='session_interrupt')
                assert run('parent')['document'] == first[0]['document']
                assert run('channel', platform='telegram')['document'] == first[2]['document']
                assert run('parent', app='new-site')['document'] == new_site['document']
                call('parent', tool='browser_exec', session=ordinary['session'],
                     code='assert js("window.ordinaryMarker")==42')
                remaining = {row['targetId'] for row in observer.call('Target.getTargets')['targetInfos']}
                assert manual_before <= remaining
                report['child_stop_preserves_peers_sites_and_manual_targets'] = True
                artifact_directory = Path(new_site['data']['directory'])
                assert (artifact_directory / 'checkpoint.json').is_file()
                disabled = call('parent', action='disable', app='new-site')
                assert not disabled['enabled'] and not disabled['cleanup_pending']
                assert run('parent')['document'] == first[0]['document']
                assert run('channel', platform='telegram')['document'] == first[2]['document']
                report['disable_releases_only_the_package_and_retains_checkpoints'] = True
                call('parent', action='enable', app='new-site')
                reopened = run('parent', app='new-site', initialize=True)
                assert reopened['session'] != new_site['session']
                assert call('parent', action='remove', app='new-site')['removed']
                assert not added.exists()
                assert (artifact_directory / 'checkpoint.json').is_file()
                assert (artifact_directory / 'result.json').is_file()
                call('parent', tool='browser_exec', session=ordinary['session'],
                     code='assert js("window.ordinaryMarker")==42')
                remaining = {row['targetId'] for row in observer.call('Target.getTargets')['targetInfos']}
                assert manual_before <= remaining
                report['reenable_uses_fresh_session_and_remove_preserves_artifacts_and_peers'] = True
                pending = run('parent', status='running')
                assert provider.unload()
                assert not provider.sessions and not provider.owners
                assert not provider.profile_choices and not provider.profile_routes
                assert Path(pending['data']['directory'], 'result.json').is_file()
                report['provider_resources_released'] = True
            finally:
                cleanup_profile_browsers(str(home))
                provider.unload()
                manager.unload('original-chrome-default')
                assert registry.get_entry('browser_app', scope=manager.scope_key) is None
                assert registry.get_entry('browser_exec', scope=manager.scope_key) is native_entry
                server.shutdown()
    return report


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
