"""Private worker-copy tests; deletion/rename is confined to temporary fixtures."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_snapshot import DEPENDENCIES,OPTIONAL_DEPENDENCIES,RuntimeSnapshot,SnapshotError


class RuntimeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.source=self.home/'source';self.source.mkdir(mode=0o700)
        (self.source/'vendor').mkdir(mode=0o700)
        for relative in DEPENDENCIES+OPTIONAL_DEPENDENCIES:
            shutil.copyfile(ROOT/relative,self.source/relative)
        self.runtime=self.home/'runtime';self.snapshot=RuntimeSnapshot(self.source,self.runtime)

    def test_only_explicit_code_and_license_are_copied_privately(self):
        (self.source/'Cookies').write_text('fixture secret must not be copied')
        (self.source/'config.yaml').write_text('fixture account must not be copied')
        worker=self.snapshot.ensure();directory=worker.parent
        files={path.relative_to(directory).as_posix() for path in directory.rglob('*') if path.is_file()}
        self.assertEqual(files,set(DEPENDENCIES+OPTIONAL_DEPENDENCIES))
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE((directory/'vendor').stat().st_mode),0o700)
        for relative in files:
            self.assertEqual(stat.S_IMODE((directory/relative).stat().st_mode),0o600)
            self.assertNotIn(b'fixture secret',(directory/relative).read_bytes())

    def test_real_child_rejects_invalid_source_from_snapshot_after_fixture_original_is_renamed(self):
        worker=self.snapshot.ensure()
        self.source.rename(self.home/'removed-source-fixture')
        child=('import os,sys,types,socket,runpy; '
               'os.environ["HERMES_DISABLE_LAZY_INSTALLS"]="1"; '
               'sys.modules["hermes_bootstrap"]=types.ModuleType("hermes_bootstrap"); '
               'socket.socket.connect=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError("network forbidden")); '
               'sys.path.insert(0,os.path.dirname(sys.argv[1])); '
               'runpy.run_path(sys.argv[1],run_name="__main__")')
        environment=dict(os.environ,HERMES_HOME=str(self.home/'hermes'),HERMES_DISABLE_LAZY_INSTALLS='1',
                         PYTHONDONTWRITEBYTECODE='1')
        with self.snapshot.worker() as leased:
            self.assertEqual(leased,worker)
            result=subprocess.run([sys.executable,'-B','-c',child,str(leased)],
                input=json.dumps({'code':'import os'}),capture_output=True,text=True,
                cwd=self.home,env=environment,timeout=10,check=True)
        frames=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(frames),1)
        self.assertFalse(frames[0]['result']['success'])
        self.assertEqual(frames[0]['result']['error_type'],'PolicyError')
        self.assertIn('browser_script_syntax_not_allowed',frames[0]['result']['error'])
        self.assertEqual(self.snapshot.worker_path,worker)
        self.snapshot.close();self.assertFalse(worker.parent.exists())

    def test_source_file_or_vendor_symlinks_are_rejected_without_publishing(self):
        target=self.home/'outside.py';target.write_text('outside fixture')
        source=self.source/'binding.py';source.unlink();source.symlink_to(target)
        with self.assertRaises(OSError):self.snapshot.ensure()
        self.assertEqual(list(self.runtime.iterdir()),[])
        self.assertEqual(target.read_text(),'outside fixture')
        source.unlink();shutil.copyfile(ROOT/'binding.py',source)
        (self.source/'vendor').rename(self.home/'vendor-outside')
        (self.source/'vendor').symlink_to(self.home/'vendor-outside',target_is_directory=True)
        with self.assertRaises(OSError):self.snapshot.ensure()
        self.assertEqual(list(self.runtime.iterdir()),[])

    def test_source_root_and_runtime_root_symlinks_are_rejected(self):
        source_link=self.home/'source-link';source_link.symlink_to(self.source,target_is_directory=True)
        with self.assertRaises(SnapshotError):RuntimeSnapshot(source_link,self.runtime).ensure()
        runtime_target=self.home/'unrelated';runtime_target.mkdir(mode=0o700)
        self.runtime.symlink_to(runtime_target,target_is_directory=True)
        with self.assertRaises(SnapshotError):self.snapshot.ensure()
        self.assertEqual(list(runtime_target.iterdir()),[])

    def test_missing_required_file_fails_closed_but_optional_license_may_be_absent(self):
        (self.source/'worker.py').unlink()
        with self.assertRaises(FileNotFoundError):self.snapshot.ensure()
        self.assertEqual(list(self.runtime.iterdir()),[])
        shutil.copyfile(ROOT/'worker.py',self.source/'worker.py')
        (self.source/OPTIONAL_DEPENDENCIES[0]).unlink()
        worker=self.snapshot.ensure()
        self.assertTrue(worker.is_file());self.assertFalse((worker.parent/OPTIONAL_DEPENDENCIES[0]).exists())

    def test_failed_write_does_not_leave_partial_published_snapshot(self):
        with patch('runtime_snapshot.os.fsync',side_effect=OSError('fixture disk failure')):
            with self.assertRaises(OSError):self.snapshot.ensure()
        self.assertEqual(list(self.runtime.iterdir()),[])
        self.assertTrue(self.snapshot.ensure().is_file())

    def test_published_snapshot_is_stable_despite_source_changes_and_tampering_is_rejected(self):
        worker=self.snapshot.ensure();original=worker.read_bytes()
        (self.source/'worker.py').write_text('changed source fixture')
        self.assertEqual(self.snapshot.worker_path,worker);self.assertEqual(worker.read_bytes(),original)
        worker.write_text('changed snapshot fixture')
        with self.assertRaisesRegex(SnapshotError,'contents_changed'):self.snapshot.ensure()

    def test_cleanup_waits_for_worker_lease_and_removes_only_its_snapshot(self):
        sibling=RuntimeSnapshot(self.source,self.runtime);sibling_worker=sibling.ensure()
        with self.snapshot.worker() as worker:
            self.assertEqual(self.snapshot.active_workers,1)
            with self.assertRaisesRegex(SnapshotError,'workers_active'):self.snapshot.close()
            self.assertTrue(worker.is_file())
        self.assertEqual(self.snapshot.active_workers,0)
        self.snapshot.close();self.snapshot.close()
        self.assertFalse(worker.parent.exists());self.assertTrue(sibling_worker.is_file())
        self.assertEqual(sibling.worker_path,sibling_worker)
        with self.assertRaisesRegex(SnapshotError,'closed'):self.snapshot.ensure()
        sibling.close()

    def test_replaced_snapshot_directory_is_never_deleted_as_owned(self):
        worker=self.snapshot.ensure();directory=worker.parent
        directory.rename(self.home/'moved-owned-fixture')
        directory.mkdir(mode=0o700);foreign=directory/'foreign.txt';foreign.write_text('preserve')
        with self.assertRaisesRegex(SnapshotError,'identity_changed'):self.snapshot.close()
        self.assertEqual(foreign.read_text(),'preserve')


if __name__=='__main__':unittest.main()
