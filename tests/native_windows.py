"""Read original Chrome's native windows without activating the application."""
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import startup
from consent import AX, ConsentError


def window_keys():
    import psutil
    result = set()
    ax = AX()
    try:
        if not ax.trusted():
            raise RuntimeError('Native window verification requires existing Accessibility access')
        for process in psutil.process_iter():
            info = startup._chrome_process_info(process, strict_named=True)
            if info is None:
                continue
            root = next((arg.split('=', 1)[1] for arg in info['cmdline']
                         if arg.startswith('--user-data-dir=')), str(startup.PERSONAL))
            if Path(root).resolve() != startup.PERSONAL.resolve():
                continue
            if not startup.chrome_executable(info['exe']):
                raise RuntimeError('Native Chrome window owner could not be verified')
            app = ax.ax.AXUIElementCreateApplication(process.pid)
            ax.refs.append(app)
            values = ax.attr(app, 'AXWindows')
            for index in range(ax.cf.CFArrayGetCount(values) if values else 0):
                window = ax.cf.CFArrayGetValueAtIndex(values, index)
                if ax.text(window, 'AXSubrole') == 'AXStandardWindow':
                    result.add((process.pid, int(ax.cf.CFHash(window))))
        return result
    finally:
        ax.clear()


def native_fixture_call(provider, task_id, session_id, turn_id, args):
    """Arrange or inspect a local fixture outside the public model tool."""
    from tools.registry import registry

    route = provider.prepare_call('browser_exec', args, task_id, session_id=session_id, turn_id=turn_id)
    if not route or route.get('action') != 'modify':
        return {'success': False, 'error': (route or {}).get('message')}
    return registry.snapshot_registration('browser_exec').handler(
        route['args'], task_id=task_id, session_id=session_id)


def verify_cleanup(before, timeout=3):
    deadline = time.monotonic() + timeout
    while True:
        try:
            after = window_keys()
        except ConsentError as error:
            if (str(error) not in {'consent_ax_read:-25202', 'consent_ax_read:-25204'}
                    or time.monotonic() >= deadline):
                raise
            time.sleep(.05)
            continue
        if after == before:
            print('NATIVE_WINDOW_CLEANUP_PASS', len(after), flush=True)
            return
        if time.monotonic() >= deadline:
            raise AssertionError({'native_windows_added': sorted(after - before),
                                  'native_windows_missing': sorted(before - after)})
        time.sleep(.05)


def verify_no_chrome_about_events(started):
    result = subprocess.run([
        '/usr/bin/log', 'show', '--style', 'compact', '--info', '--debug',
        '--start', datetime.fromtimestamp(started).strftime('%Y-%m-%d %H:%M:%S'),
        '--predicate', 'process == "loginwindow" AND eventMessage CONTAINS "aevt,abtm" '
                       'AND eventMessage CONTAINS "target=Google Chrome"',
    ], capture_output=True, text=True, check=True, timeout=30)
    events = [line for line in result.stdout.splitlines() if 'aevt,abtm' in line]
    assert not events, {'unexpected_chrome_about_this_mac_events': events}
    print('CHROME_ABOUT_THIS_MAC_EVENT_CHECK_PASS', flush=True)
