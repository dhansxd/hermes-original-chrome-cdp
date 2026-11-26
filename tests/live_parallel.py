"""Six native Hermes owners sharing one site package and original Chrome profiles."""
import concurrent.futures
import json
import sys
import tempfile
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_apps import Fixture, package
from native_windows import window_keys, verify_cleanup, verify_no_chrome_about_events
from profiles import get_profile
from relay import ChromeSession
from startup import PERSONAL

from agent.browser_registry import get_provider
from gateway.session_context import clear_session_vars, set_session_vars
from hermes_constants import set_hermes_home_override
from hermes_cli.plugins import get_plugin_manager, invoke_hook
from hermes_cli.plugins_manifest import parse_manifest_file
from native_windows import native_fixture_call
from tools.browser_session_lifecycle import cleanup_profile_browsers
from model_tools import handle_function_call


AGENTS = tuple('agent-' + str(index) for index in range(6))


def verify():
    started = time.time()
    before = window_keys()
    source = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'
    report = {}
    with tempfile.TemporaryDirectory(prefix='hermes-parallel-acceptance-') as temporary:
        home = Path(temporary).resolve()
        packages = home / 'apps'
        package(packages, 'fixture')
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
        with set_hermes_home_override(home):
            manager = get_plugin_manager()
            manager._load_plugin(parse_manifest_file(source / 'plugin.yaml', source, 'user', ''))
            provider = get_provider('original-chrome-default')
            turns = {task: uuid.uuid4().hex for task in AGENTS}
            manual = None

            def call(task, tool='browser_exec', **args):
                if tool == 'browser_exec' and 'code' not in args:
                    session = args.pop('session', 'default')
                    args = {'site_control': json.dumps(args), 'session': session}
                with set_hermes_home_override(home):
                    tokens = set_session_vars(platform='cli', session_key='parallel-' + task,
                                              session_id=task + '-chat')
                    try:
                        if tool == 'browser_exec' and 'code' in args:
                            result = native_fixture_call(provider, task, task + '-chat', turns[task], args)
                        else:
                            result = handle_function_call(tool, args, task_id=task, session_id=task + '-chat',
                                                        turn_id=turns[task], tool_call_id=uuid.uuid4().hex)
                        result = json.loads(result) if isinstance(result, str) else result
                        assert result.get('success'), result
                        return result
                    finally:
                        clear_session_vars(tokens)

            def run(task, initialize=False):
                params = {'url': url, 'marker': task} if initialize else {}
                result = call(task, action='run', app='fixture', session='same',
                              operation='inspect', params=params)
                data = result['data']
                assert (data['task'], data['chat'], data['turn']) == (task, task + '-chat', turns[task])
                assert data['revision'] == 1
                result['document'] = json.loads(data['native']['output'].strip())
                assert result['document']['marker'] == task
                return result

            def end(task, interrupted=False):
                with set_hermes_home_override(home):
                    if interrupted:
                        invoke_hook('agent_loop_stopped', session_key='parallel-' + task, platform='cli',
                                    reason='user_stop', invalidation_reason='session_interrupt')
                    else:
                        invoke_hook('on_session_end', task_id=task, session_id=task + '-chat',
                                    turn_id=turns[task], completed=True, failed=False, interrupted=False)

            try:
                inventory = call(AGENTS[0], tool='chrome_profiles', action='list', app='fixture', session='same')['profiles']
                assert len(inventory) >= 2, 'This native test needs two existing Chrome profiles.'
                first, second = inventory[0]['id'], inventory[1]['id']
                selected = get_profile(first, PERSONAL)
                manual = ChromeSession(PERSONAL, first, profile_identity=selected.identity)
                manual._start()
                manual_target = next(iter(manual.owned))
                sid = manual.wire.call('Target.attachToTarget', {
                    'targetId': manual_target, 'flatten': True})['sessionId']
                original_pages = {row['targetId'] for row in manual.wire.call('Target.getTargets')['targetInfos']
                                  if row.get('type') == 'page'} - manual.owned
                manual.wire.call('Page.navigate', {'url': url}, sid)
                deadline = time.monotonic() + 10
                while not manual.wire.call('Runtime.evaluate', {
                        'expression': "document.querySelector('#field') ? (document.querySelector('#field').value='KEEP') : null",
                        'returnByValue': True}, sid)['result'].get('value'):
                    assert time.monotonic() < deadline, 'Independent manual fixture did not mount.'
                    time.sleep(.05)
                manual_before = window_keys()

                for phase, profiles in (
                        ('shared', [first] * 6),
                        ('mixed', [first, second] * 3)):
                    for task, profile in zip(AGENTS, profiles):
                        turns[task] = uuid.uuid4().hex
                        call(task, tool='chrome_profiles', action='select', app='fixture',
                             session='same', profile=profile)
                    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                        results = list(pool.map(lambda task: run(task, initialize=True), AGENTS))
                    assert len({result['session'] for result in results}) == 6
                    assert len({result['data']['directory'] for result in results}) == 6
                    assert len(provider.sessions) == 6
                    windows, targets = [], []
                    for task, profile, result in zip(AGENTS, profiles, results):
                        session = next(item for item in provider.sessions.values()
                                       if item.cache_key.split('@', 1)[0] == 'bu-named-' + result['session'])
                        assert session.profile == profile
                        owned = {row['targetId'] for row in session._inventory() if row.get('type') == 'page'}
                        target_windows = {manual.wire.call('Browser.getWindowForTarget', {'targetId': target})['windowId']
                                          for target in owned}
                        print('PARALLEL_OWNER_WINDOWS', phase, task, len(owned), sorted(target_windows), flush=True)
                        assert len(owned) == len(target_windows) == 1, (phase, task, sorted(owned), target_windows)
                        targets.append(owned)
                        windows.append(target_windows)
                    manual_window = manual.wire.call('Browser.getWindowForTarget', {'targetId': manual_target})['windowId']
                    assert all(manual_window not in window for window in windows)
                    assert all(left.isdisjoint(right) for index, left in enumerate(windows) for right in windows[index + 1:])
                    actual_windows = window_keys()
                    assert manual_before <= actual_windows and len(actual_windows - manual_before) == 6, actual_windows

                    for iteration in range(2):
                        def write(task):
                            result = results[AGENTS.index(task)]
                            value = phase + '-' + task + '-' + str(iteration)
                            code = f"fill_input('#field', {value!r})\n"
                            code += "print(js(\"JSON.stringify({marker:window.fixtureMarker,origin:performance.timeOrigin,value:document.querySelector('#field').value})\"))"
                            native = call(task, tool='browser_exec', session=result['session'], code=code)
                            actual = json.loads(native['output'].strip())
                            assert actual == {**result['document'], 'value': value}, actual
                        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                            list(pool.map(write, AGENTS))

                    def check_new_target(task):
                        index = AGENTS.index(task)
                        code = f'''from pathlib import Path
import time
previous = current_tab()
added = new_tab()
try:
    goto_url('chrome://version/')
    deadline = time.monotonic() + 20
    actual = ''
    while not actual:
        actual = js("document.getElementById('profile_path')?.textContent || ''")
        assert actual or time.monotonic() < deadline, 'Chrome profile path is not ready.'
        if not actual:
            time.sleep(.05)
    assert Path(actual.strip()).resolve() == Path({str(PERSONAL / profiles[index])!r}).resolve(), (actual, {str(PERSONAL / profiles[index])!r})
finally:
    switch_tab(previous)
    close_tab(added)
print('OWNED_PROFILE_READBACK_PASS')
'''
                        result = call(task, tool='browser_exec', session=results[index]['session'], code=code)
                        assert 'OWNED_PROFILE_READBACK_PASS' in result['output']
                    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                        list(pool.map(check_new_target, AGENTS))
                    for expected in targets:
                        remaining = {row['targetId'] for row in manual.wire.call('Target.getTargets')['targetInfos']}
                        assert expected <= remaining

                    end(AGENTS[0], interrupted=True)
                    end(AGENTS[1])
                    assert len(provider.sessions) == 4
                    remaining = {row['targetId'] for row in manual.wire.call('Target.getTargets')['targetInfos']}
                    assert (targets[0] | targets[1]).isdisjoint(remaining)
                    for task, expected in zip(AGENTS[2:], results[2:]):
                        actual = run(task)
                        assert actual['document'] == expected['document']
                        assert actual['session'] == expected['session']
                        assert actual['data']['directory'] == expected['data']['directory']
                        native = call(task, tool='browser_exec', session=actual['session'],
                                      code='print(js("document.querySelector(\'#field\').value"))')
                        assert native['output'].strip() == phase + '-' + task + '-1'
                    assert original_pages <= remaining and manual_target in remaining
                    assert manual.wire.call('Runtime.evaluate', {
                        'expression': "document.querySelector('#field').value", 'returnByValue': True}, sid)['result']['value'] == 'KEEP'
                    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                        list(pool.map(end, AGENTS[2:]))
                    assert not provider.sessions and not provider.owners
                    assert not provider.profile_choices and not provider.profile_routes
                    verify_cleanup(manual_before)
                    report[phase] = {'agent_identities': 6, 'disjoint_window_groups': 6,
                                     'owned_windows': sum(len(window) for window in windows),
                                     'windows_per_agent': [len(window) for window in windows],
                                     'profile_groups': [profiles.count(profile) for profile in dict.fromkeys(profiles)],
                                     'parallel_input_rounds': 2, 'stop_and_completion_preserve_peers': True,
                                     'new_target_profile_readback': True,
                                     'manual_fixture_preserved': True, 'owned_resources_released': True}
                    print('PARALLEL_PHASE_PASS', phase, json.dumps(report[phase]), flush=True)
            finally:
                try:
                    assert provider.unload(), 'Provider cleanup is incomplete.'
                    cleanup_profile_browsers(str(home))
                    manager.unload('original-chrome-default')
                finally:
                    try:
                        if manual is not None:
                            assert manual.close(), 'Independent manual fixture cleanup failed.'
                    finally:
                        server.shutdown()
                        verify_cleanup(before)
    verify_no_chrome_about_events(started)
    report['no_chrome_about_this_mac_events'] = True
    report['native_windows_returned_to_baseline'] = True
    return report


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
