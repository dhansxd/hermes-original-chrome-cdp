"""Read original Chrome's native windows without activating the application."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import startup
from consent import AX


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


def verify_cleanup(before, timeout=3):
    deadline = time.monotonic() + timeout
    while True:
        after = window_keys()
        if after == before:
            print('NATIVE_WINDOW_CLEANUP_PASS', len(after), flush=True)
            return
        if time.monotonic() >= deadline:
            raise AssertionError({'native_windows_added': sorted(after - before),
                                  'native_windows_missing': sorted(before - after)})
        time.sleep(.05)
