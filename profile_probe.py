"""Explicit original-profile probe provider, never registered as a Hermes tool.

The registered ChromeProvider remains fixed to approved Default. This separate
provider supplies only owned endpoint plumbing to the gflow read-only probe.
Visible Flow account verification remains the caller's required acceptance gate.
"""
import json
import os
import re
import stat

if __package__:
    from . import plugin as base
else:
    import plugin as base


def _signature(info):
    return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns


def _trusted(info,directory=False):
    return ((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid==os.getuid() and not info.st_mode & 0o022)


def _directory_identity(info):
    return info.st_dev,info.st_ino,getattr(info,'st_birthtime_ns',getattr(info,'st_birthtime',None))


def _read(directory,name):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    try:
        before=os.fstat(fd)
        maximum=8*1024*1024
        if not _trusted(before) or before.st_size>maximum:raise ValueError('unsafe metadata')
        blocks=[];size=0
        while block:=os.read(fd,min(65536,maximum+1-size)):
            blocks.append(block);size+=len(block)
            if size>maximum:raise ValueError('oversized metadata')
        if (_signature(before)!=_signature(os.fstat(fd))
            or _signature(before)!=_signature(os.stat(name,dir_fd=directory,follow_symlinks=False))):
            raise ValueError('metadata changed')
        value=json.loads(b''.join(blocks))
        if not isinstance(value,dict):raise ValueError('invalid metadata')
        return value
    finally:os.close(fd)


class ProfileProbeProvider(base.ChromeProvider):
    """Separate explicit provider; no execute/schema/profile selector is registered."""
    display_name='Explicit original Chrome profile probe'

    def __init__(self,profile_id,expected_account,workspace,*,read_browser_config,native_browser_disabled):
        if (not isinstance(profile_id,str) or not 0<len(profile_id)<=128
            or not profile_id.isprintable() or profile_id in {'.','..','Guest Profile','System Profile'}
            or '/' in profile_id or '\\' in profile_id):raise ValueError('profile_probe_invalid_id')
        if (not isinstance(expected_account,str) or len(expected_account)>320
            or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',expected_account)
            or not expected_account.isprintable()):raise ValueError('profile_probe_invalid_account')
        self.profile_id=profile_id
        self.expected_account=expected_account
        self._probe_binding=None
        super().__init__(workspace=workspace,read_browser_config=read_browser_config,
                         native_browser_disabled=native_browser_disabled)

    @property
    def profile_path(self):return self.data/self.profile_id

    def _launch_seed(self,seed_url):
        # Snapshot/journal preparation can take time. Never launch a replacement
        # directory using the identity captured before that preparation.
        self.require_ready()
        base.gui_launch(self.data,seed_url,profile_directory=self.profile_id)

    def require_ready(self):
        if self.data!=base.PERSONAL.resolve():raise RuntimeError('profile_probe_original_root_required')
        base.require_browser_route(self._read_browser_config(),self._native_browser_disabled())
        descriptors=[]
        try:
            root=os.open(self.data,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);descriptors.append(root)
            child=os.open(self.profile_id,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root);descriptors.append(child)
            if not _trusted(os.fstat(root),True) or not _trusted(os.fstat(child),True):
                raise ValueError('unsafe directory')
            state=_read(root,'Local State')
            meta=state['profile']['info_cache'][self.profile_id]
            prefs=_read(child,'Preferences')
            expected=self.expected_account.casefold()
            if (not isinstance(meta,dict) or meta.get('is_ephemeral',False) is not False
                or meta.get('force_signin_profile_locked',False) is not False
                or meta.get('user_name','').casefold()!=expected
                or not any(isinstance(a,dict) and a.get('email','').casefold()==expected
                           for a in prefs.get('account_info',[]))):raise ValueError('account mismatch')
            actual=os.stat(self.profile_id,dir_fd=root,follow_symlinks=False);opened=os.fstat(child)
            if not _trusted(actual,True) or _directory_identity(actual)!=_directory_identity(opened):
                raise ValueError('directory changed')
            current_root=os.stat(self.data,follow_symlinks=False)
            if not _trusted(current_root,True) or _directory_identity(current_root)!=_directory_identity(os.fstat(root)):
                raise ValueError('root changed')
            binding=(_directory_identity(os.fstat(root)),_directory_identity(opened),meta.get('metrics_bucket_index'))
            if self._probe_binding is not None and self._probe_binding!=binding:
                raise ValueError('profile identity changed')
            self._probe_binding=binding
        except (OSError,ValueError,KeyError,TypeError,AttributeError):
            raise RuntimeError('profile_probe_binding_unavailable: verify the selected original Chrome profile/account in GUI; no fallback or login change') from None
        finally:
            for fd in reversed(descriptors):os.close(fd)

    def execute(self,*args,**kwargs):
        raise RuntimeError('profile_probe_only: not a registered execution provider')
