"""Fresh inventory of the original Chrome's persistent profile directories."""
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChromeProfile:
    id: str
    name: str
    identity: tuple


def profile_directory(value):
    value = value or 'Default'
    if (not isinstance(value, str) or not value.isprintable() or len(value) > 128
            or value in {'.', '..', 'Guest Profile', 'System Profile'} or '/' in value or '\\' in value):
        raise ValueError('Choose an existing Chrome profile directory, e.g. Default or Profile 2.')
    return value


def list_profiles(data):
    """Read current metadata and directory identities without opening Chrome."""
    root = os.open(Path(data), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(root).st_uid != os.getuid():
            raise RuntimeError('Chrome directory ownership is unavailable.')
        descriptor = os.open('Local State', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        with os.fdopen(descriptor) as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid():
                raise RuntimeError('Chrome metadata ownership is unavailable.')
            rows = json.load(stream)['profile']['info_cache']
            after = os.fstat(stream.fileno())
            current = os.stat('Local State', dir_fd=root, follow_symlinks=False)
            signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
            if signature(before) != signature(after) or signature(after) != signature(current):
                raise RuntimeError('Chrome metadata changed. Refresh the profile inventory.')
        if not isinstance(rows, dict):
            raise ValueError('Chrome profile metadata is unavailable.')
        profiles = []
        for identifier, row in rows.items():
            try:
                if profile_directory(identifier) != identifier:
                    continue
            except ValueError:
                continue
            if not isinstance(row, dict) or row.get('is_ephemeral') or row.get('force_signin_profile_locked'):
                continue
            try:
                info = os.stat(identifier, dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                continue
            name = row.get('name')
            profiles.append(ChromeProfile(
                identifier, name if isinstance(name, str) and name else identifier,
                (info.st_dev, info.st_ino, getattr(info, 'st_birthtime', None))))
        def order(profile):
            match = re.fullmatch(r'Profile (\d+)', profile.id)
            if profile.id == 'Default':
                return (0, 0)
            if match:
                return (1, int(match[1]))
            return (2, profile.id)
        return sorted(profiles, key=order)
    finally:
        os.close(root)


def get_profile(identifier, data):
    identifier = profile_directory(identifier)
    profile = next((item for item in list_profiles(data) if item.id == identifier), None)
    if profile is None:
        raise ValueError('The selected Chrome profile is unavailable. Refresh chrome_profiles.')
    return profile


def verify_profile(profile, data):
    current = get_profile(profile.id, data)
    if current.identity != profile.identity:
        raise RuntimeError('The selected Chrome profile was replaced. Select it again from chrome_profiles.')
    return current
