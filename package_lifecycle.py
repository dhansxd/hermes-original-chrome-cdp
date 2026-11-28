"""Migrate historical package copies and perform an explicitly requested full uninstall."""
import errno
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path


def _shipped_files(directory, digests):
    if directory.is_symlink() or not directory.is_dir():
        return {}
    files = {}
    for path in directory.iterdir():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            return {}
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return files if digest in digests else {}


def retire_legacy_packages(root, get_setting=None, set_setting=None):
    lock = root / '.install.lock'
    if root.is_symlink() or not lock.is_file() or lock.is_symlink():
        return
    import fcntl
    # Older hosts used this same lock when seeding the external directory.
    digests = json.loads(Path(__file__).with_name('legacy-package-digests.json').read_text())
    try:
        descriptor = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
    except FileNotFoundError:
        return
    with os.fdopen(descriptor, 'r+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if not lock.exists() or not os.path.samestat(lock.stat(), os.fstat(stream.fileno())):
            return
        retired = False
        if get_setting is not None and set_setting is not None:
            for name in digests:
                key = 'apps_disabled.' + name
                if get_setting(key) is True and not os.path.lexists(root / name):
                    set_setting(key, 'removed')
                    retired = True
        for name, versions in digests.items():
            directory = root / name
            files = _shipped_files(directory, versions)
            if files:
                # Only unlink verified source files. Keep any independently added entries.
                for filename in files:
                    (directory / filename).unlink()
                directory.rmdir()
                retired = True
        if retired and lock.stat().st_size == 0:
            lock.unlink()
            try:
                root.rmdir()
            except OSError as error:
                if error.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                    raise


PLUGIN_ID = 'original-chrome-default'
# Native Hermes PluginState directory for this manifest ID. Never match plugin data by a wildcard.
STATE_DIRECTORY = 'agent-plugin-original-chrome-default-31c84a78'


def remove_data_directory(path):
    import shutil
    if path.parent.is_symlink():
        raise ValueError(f'Refusing to purge through a linked parent: {path.parent}')
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        raise ValueError(f'Expected a plugin data directory: {path}')


def remove_installation(hermes, home, external, *, last_installation=False):
    # The host-wide lock and peer cache is shared by all profiles, including disabled installs.
    installed = home / 'plugins' / PLUGIN_ID
    if installed.parent.is_symlink() or installed.is_symlink():
        raise ValueError('Clean uninstall requires an ordinary Git-installed plugin.')
    if last_installation:
        default = Path.home() / '.hermes'
        profiles = {default, home}
        for base in (default, home):
            profiles.update((base / 'profiles').glob('*'))
        if home.parent.name == 'profiles':
            profiles.add(home.parent.parent)
            profiles.update(home.parent.glob('*'))
        if any(candidate.resolve() != home.resolve() and os.path.lexists(candidate / 'plugins' / PLUGIN_ID)
               for candidate in profiles):
            raise ValueError('A second Hermes profile still has Original Chrome installed.')
    if not external.resolve().is_relative_to(installed.resolve()):
        retire_legacy_packages(external)
    if installed.exists():
        subprocess.run([*hermes, 'plugins', 'remove', PLUGIN_ID], check=True)
        if os.path.lexists(installed):
            raise RuntimeError('Hermes still has an installed plugin directory.')
    remove_data_directory(home / 'plugin-data' / STATE_DIRECTORY)
    if last_installation:
        remove_data_directory(Path.home() / '.cache' / PLUGIN_ID)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Remove Original Chrome and its data from one Hermes profile.')
    parser.add_argument('action', choices=['uninstall'])
    parser.add_argument('--profile', help='Hermes profile, as accepted by the official CLI')
    parser.add_argument('--last-installation', action='store_true',
                        help='Also remove shared Mac coordination files after all profiles have stopped using this plugin.')
    args = parser.parse_args()
    hermes = ['hermes', '--profile', args.profile] if args.profile else ['hermes']
    config = Path(subprocess.check_output([*hermes, 'config', 'path'], text=True).strip())
    if not config.is_absolute() or config.name != 'config.yaml':
        raise ValueError('Could not identify the selected Hermes profile.')
    home = config.parent

    def setting(key):
        result = subprocess.run([*hermes, 'config', 'get', key, '--json'], text=True, capture_output=True)
        if result.returncode and ('Config key not set: ' + key) in (result.stdout + result.stderr):
            return None
        result.check_returncode()
        return json.loads(result.stdout)

    if setting('browser.cloud_provider') == PLUGIN_ID:
        parser.error('Restore the previous browser in Hermes before uninstalling.')
    external = setting(f'plugins.entries.{PLUGIN_ID}.settings.apps_directory')
    remove_installation(hermes, home, Path(external).expanduser() if external else home / 'browser-apps',
                        last_installation=args.last_installation)
    print(f'Removed {PLUGIN_ID} and its profile data from {home}.')


if __name__ == '__main__':
    main()
