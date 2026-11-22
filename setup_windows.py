"""Install the matching Windows Chrome companion through an existing OpenSSH host."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from windows_chrome import WindowsChrome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ssh_host', help='the trusted OpenSSH Host alias of the Windows desktop')
    parser.add_argument('--ssh-config', help='an alternate local OpenSSH configuration file')
    parser.add_argument('--device', default='windows', help='device ID in the active Hermes profile')
    parser.add_argument('--profile', help='pin a Windows Chrome directory ID from the setup output')
    parser.add_argument('--make-default', action='store_true', help='select this Windows device as the only browser device')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', args.device) or args.device == 'local':
        parser.error('--device must be a name such as windows or laptop, distinct from local')
    if not shutil.which('hermes'):
        parser.error('install Hermes on this Mac before pairing a Windows Chrome device')
    settings = {'ssh_host': args.ssh_host}
    if args.ssh_config:
        settings['ssh_config'] = str(Path(args.ssh_config).expanduser().resolve())
    if args.profile:
        settings['profile_directory'] = args.profile
    prefix = 'plugins.entries.original-chrome-default.settings.'
    try:
        desktop = WindowsChrome(args.device, settings)
        profiles = desktop.install_companion()
        if args.profile and args.profile not in {profile.id for profile in profiles}:
            raise ValueError('The requested Windows Chrome profile is unavailable.')
        subprocess.run(['hermes', 'config', 'set', prefix + 'windows_devices.' + args.device,
                        json.dumps(settings)], check=True)
        if args.make_default:
            subprocess.run(['hermes', 'config', 'set', prefix + 'default_device', args.device], check=True)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'Windows Chrome setup failed. {error}\n')
    except subprocess.SubprocessError:
        parser.exit(1, 'Windows Chrome setup failed while running SSH or Hermes configuration.\n')
    print(f'Windows Chrome companion installed and device {args.device!r} configured.')
    for profile in profiles:
        print(f'  {profile.id}  {profile.name}')


if __name__ == '__main__':
    main()
