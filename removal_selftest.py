"""Operator-only removal acceptance using a disposable copy of plugin code."""
import json
from pathlib import Path
import shutil
import tempfile
import time

if __package__:
    from .runtime_snapshot import DEPENDENCIES,OPTIONAL_DEPENDENCIES
else:
    from runtime_snapshot import DEPENDENCIES,OPTIONAL_DEPENDENCIES


def run(provider,readiness):
    report={'success':False,'level':'operator_source_removal_fixture_not_package_manager',
            'installed_plugin_removed':False,'checks':{},'errors':[]}
    if provider is None or not callable(readiness) or not readiness().get('ready'):
        report['errors'].append('removal_test_not_ready');return report
    parent=provider.workspace/'removal-tests';parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    folder=Path(tempfile.mkdtemp(prefix='fixture-',dir=parent))
    source=folder/'source';source.mkdir(mode=0o700);(source/'vendor').mkdir(mode=0o700)
    candidate=None;watch=None
    try:
        for relative in (*DEPENDENCIES,*OPTIONAL_DEPENDENCIES,'plugin.yaml'):
            origin=provider.source_root/relative
            if relative in OPTIONAL_DEPENDENCIES and not origin.exists():continue
            destination=source/relative
            destination.write_bytes(origin.read_bytes());destination.chmod(0o600)
        candidate=type(provider)(data=provider.data,workspace=folder/'work',source_root=source,
            get_setting=provider._get_setting,read_browser_config=provider._read_browser_config,
            native_browser_disabled=provider._native_browser_disabled)
        result=json.loads(candidate.execute({'session':'removal','timeout_s':20,
            'code':"goto_url('https://example.com')\nwait_for_load(timeout=10)\nprint(read_page(limit=500))"},
            task_id='operator-removal-fixture'))
        report['checks']['page_read']=result.get('success') is True and 'Example Domain' in result.get('stdout','')
        if not report['checks']['page_read']:
            report['errors'].append('removal_test_startup_failed');return report
        watch=candidate._resource_watch
        report['checks']['watcher_active']=watch is not None and watch.is_running
        if not report['checks']['watcher_active']:
            report['errors'].append('removal_test_watch_missing');return report
        # Delete only this generated fixture. The installed repository and its
        # manifest, grants and configuration are never removed or modified.
        shutil.rmtree(source)
        deadline=time.monotonic()+45
        while not watch.stopped and time.monotonic()<deadline:time.sleep(.1)
        report['checks'].update(source_removed=not source.exists(),
            removal_detected=watch.removal_detected,watcher_stopped=watch.stopped,
            cleanup_callback_succeeded=not watch.callback_failed,
            all_owned_sessions_cleaned=not candidate.states,
            journal_empty=not candidate._journal().records(),
            worker_snapshot_removed=candidate._runtime_snapshot.active_workers==0
                and not any((candidate.workspace/'runtime').glob('worker-*')))
        report['success']=all(report['checks'].values())
        if not report['success']:report['errors'].append('removal_test_cleanup_incomplete')
        return report
    except Exception as exc:
        report['errors'].append('removal_test_failed:'+type(exc).__name__)
        return report
    finally:
        if candidate is not None:
            try:candidate.unload()
            except Exception:report['errors'].append('removal_test_finalize_failed');report['success']=False
        if candidate is None or (not candidate.states and (watch is None or watch.stopped)):
            shutil.rmtree(folder)
        else:
            # Failed ownership proof must survive the test, not be erased by
            # TemporaryDirectory cleanup. This path is operator-only metadata.
            report['diagnostic_workspace']=str(folder)
