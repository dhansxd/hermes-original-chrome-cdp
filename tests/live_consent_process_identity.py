"""Opt-in exact-PID consent regression with two empty same-name Chrome roots.

Runs the production selector read-only before any handshake, then the unchanged
consent flow once per root. No personal browser actions or permission changes.
Run with the managed Hermes interpreter; receipts stay outside Git.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path.home() / '.hermes/hermes-agent')]
import hermes_bootstrap
import psutil
import plugin
import consent
from websockets.sync.client import connect


def main():
    output = Path(tempfile.mkdtemp(prefix='consent-exact-pid-', dir=Path.home() / '.hermes/cache/scratch'))
    report = {'level': 'source; two disposable approval-mode roots; not native chat',
              'checks': {}, 'click_receipts': [], 'handshakes': {}, 'presses': {}}
    run = subprocess.run
    roots = [output / name for name in ('first', 'second')]
    sockets = []

    def check(name, value):
        report['checks'][name] = bool(value)
        assert value, name

    def processes(root):
        found = []
        for process in psutil.process_iter():
            try:
                info = process.as_dict(attrs=['exe', 'cmdline'])
                if Path(info['exe'] or '').name == 'Google Chrome' and '--user-data-dir=' + str(root) in (info['cmdline'] or []):
                    found.append(process)
            except psutil.Error:
                continue
        return found

    def wait_for(fn, description):
        deadline = time.monotonic() + 10
        while True:
            try:
                value = fn()
            except consent.ConsentError as exc:
                if str(exc) not in {'consent_ax_read:-25202', 'consent_ax_read:-25204'}:
                    raise
                value = None
            if value:
                return value
            if time.monotonic() >= deadline:
                raise TimeoutError(description)
            time.sleep(.05)

    def recording_run(argv, **kwargs):
        if argv and argv[0] == '/usr/bin/open':
            assert any('--user-data-dir=' + str(root) in argv for root in roots)
            assert argv.count('--remote-debugging-port=0') == 1
            argv = [arg for arg in argv if arg != '--remote-debugging-port=0']
            assert not any(arg.startswith('--remote-debugging-') for arg in argv)
        result = run(argv, **kwargs)
        if argv[:2] == ['osascript', '-e'] and argv[2] == consent.PRESS_SCRIPT:
            report['click_receipts'].append({'pid': int(argv[-2]), 'returncode': result.returncode,
                                             'stdout': result.stdout, 'stderr': result.stderr})
        return result

    def endpoint(root):
        try:
            portfile = root / 'DevToolsActivePort'
            lines = portfile.read_text().splitlines()
            if len(lines) != 2 or not lines[1].startswith('/devtools/browser/'):
                return None
            port = int(lines[0])
            listeners = [p for p in processes(root) if portfile.stat().st_mtime >= p.create_time()
                         and any(c.status == 'LISTEN' and c.laddr.port == port
                                 and c.laddr.ip in {'127.0.0.1', '::1'} for c in p.net_connections(kind='tcp'))]
            if len(listeners) == 1 and portfile.read_text().splitlines() == lines:
                return listeners[0], lines
        except (OSError, ValueError, psutil.Error):
            return None

    def window_ready(pid, seed, close=False):
        ax = consent.AX()
        try:
            app = ax.ax.AXUIElementCreateApplication(pid)
            ax.refs.append(app)
            ax.ax.AXUIElementSetMessagingTimeout(app, .25)
            values = ax.attr(app, 'AXWindows')
            windows = [ax.cf.CFArrayGetValueAtIndex(values, i)
                       for i in range(ax.cf.CFArrayGetCount(values))] if values else []
            owned = [node for node in windows if ax.text(node, 'AXDocument') == seed.as_uri()]
            if close:
                assert len(owned) == 1
                button = ax.attr(owned[0], 'AXCloseButton')
                assert button and ax.ax.AXUIElementPerformAction(button, ax.string('AXPress')) == 0
            return bool(owned)
        finally:
            ax.clear()

    class RecordingConsent(consent.MacConsent):
        def press(self, sheet, *, pending):
            report['presses'][str(self.root)] = report['presses'].get(str(self.root), 0) + 1
            return super().press(sheet, pending=pending)

    try:
        ax = consent.AX()
        try:
            check('accessibility_available_without_prompt', ax.trusted())
        finally:
            ax.clear()
        ready = []
        with patch.object(plugin.subprocess, 'run', side_effect=recording_run):
            for root in roots:
                (root / 'Default').mkdir(parents=True)
                (root / 'Local State').write_text(json.dumps({'devtools': {'remote_debugging': {'user-enabled': True}},
                                                              'profile': {'last_used': 'Default'}}))
                seed = root / 'seed.html'
                seed.write_text('<!doctype html><title>Exact PID disposable consent</title>')
                plugin.gui_launch(root, seed.as_uri())
                process, lines = wait_for(lambda: endpoint(root), 'exact-root listener')
                wait_for(lambda: window_ready(process.pid, seed), 'exact seed window')
                ready.append((root, seed, process, lines))
            check('two_distinct_listener_pids', len({p.pid for _, _, p, _ in ready}) == 2)
            # Run the real main selector and both identity guards, returning before
            # enumerating windows or taking any native action.
            marker = '   repeat with w in windows of p'
            assert consent.PRESS_SCRIPT.count(marker) == 1
            identity_script = consent.PRESS_SCRIPT.replace(marker, '   return "pid:" & (unix id of p as text)\n' + marker)
            report['identity_receipts'] = []
            for root, seed, process, lines in ready:
                got = run(['osascript', '-e', identity_script, str(process.pid), 'com.google.Chrome'],
                          capture_output=True, text=True, timeout=3)
                report['identity_receipts'].append({'expected_pid': process.pid, 'returncode': got.returncode,
                                                    'stdout': got.stdout, 'stderr': got.stderr})
                check(root.name + '_exact_pid_not_name_alias', got.returncode == 0 and got.stdout.strip() == 'pid:' + str(process.pid))
                wrong = run(['osascript', '-e', identity_script, str(process.pid), 'fixture.wrong.bundle'],
                            capture_output=True, text=True, timeout=3)
                check(root.name + '_wrong_bundle_still_rejected', wrong.returncode == 0 and wrong.stdout.strip() == 'stale-host')
            for root, seed, process, lines in ready:
                if root == roots[1]:
                    window_ready(process.pid, seed, close=True)
                    wait_for(lambda: not window_ready(process.pid, seed), 'seed closed')
                    plugin.gui_launch(root, seed.as_uri())
                    wait_for(lambda: window_ready(process.pid, seed), 'reopened seed')
                    same, same_lines = wait_for(lambda: endpoint(root), 'reopened endpoint')
                    check('reopen_preserves_listener_generation', same.pid == process.pid and same.create_time() == process.create_time() and same_lines == lines)
                def dial(url, **kwargs):
                    report['handshakes'][str(root)] = report['handshakes'].get(str(root), 0) + 1
                    return connect(url, **kwargs)
                backend = RecordingConsent(root, int(lines[0]), lines[1])
                try:
                    ws = consent.connect_with_consent('ws://127.0.0.1:' + lines[0] + lines[1], root, dial, backend=backend, timeout=10)
                    sockets.append(ws)
                    ws.send(json.dumps({'id': 1, 'method': 'Browser.getVersion'}))
                    response = json.loads(ws.recv(timeout=5))
                    check(root.name + '_accepted_and_cdp_usable', response.get('id') == 1 and response.get('result', {}).get('product', '').startswith('Chrome/'))
                    check(root.name + '_one_handshake_one_press', report['handshakes'][str(root)] == report['presses'][str(root)] == 1)
                    check(root.name + '_native_question_disappeared', not any(consent.button_for_dialog(s['name'], s['headings']) for s in backend.scan() if s['pid'] == process.pid))
                finally:
                    if backend.ax:
                        backend.ax.clear()
        report['success'] = True
    except Exception as exc:
        report.update(success=False, error_type=type(exc).__name__, error=str(exc))
    finally:
        for ws in sockets:
            try:
                ws.send(json.dumps({'id': 2, 'method': 'Browser.close'}))
            except Exception:
                pass
            ws.close()
        for root in roots:
            _, left = psutil.wait_procs(processes(root), timeout=3)
            for process in left:
                try:
                    if '--user-data-dir=' + str(root) in process.cmdline():
                        process.terminate()
                except psutil.Error:
                    pass
            psutil.wait_procs(left, timeout=3)
        report['process_residue'] = {root.name: [p.pid for p in processes(root)] for root in roots}
        if any(report['process_residue'].values()):
            report['success'] = False
        (output / 'result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps({'success': report.get('success'), 'error': report.get('error'),
                          'checks': report['checks'], 'evidence': str(output / 'result.json')}, indent=2))
    return 0 if report.get('success') else 1


if __name__ == '__main__':
    sys.exit(main())
