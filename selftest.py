"""Fixed operator acceptance through the registered tool; never a model-facing tool."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from contextlib import nullcontext
import json
import secrets
import threading
import time

LEVEL='registered_tool_in_gateway_not_llm_agent'
START_SOURCE="goto_url('https://example.com')\nwait_for_load(timeout=10)\nprint(read_page(limit=1000))"
PARALLEL_SOURCE="wait(1)\nprint(read_page(limit=1000))\nprint('SELFTEST_WAIT_COMPLETE')"
FINISH_SOURCE='print(finish_browser())'
KNOWN_ERRORS=('account_binding_unconfigured','account_binding_not_approved','account_binding_mismatch',
    'plugin_capability_required','browser_provider_not_selected','browser_backend_unsupported',
    'browser_exec_timeout','browser_worker_failed','observer_lost','consent_accessibility',
    'consent_deadline','consent_attach_failed','consent_prompt_unavailable',
    'accessibility_permission_required','Default_seed_window_unavailable','Chrome_endpoint_unavailable',
    'previous_execution_outcome_uncertain','ownership_lost_after_timeout')


def _refused(code):
    return {'success':False,'level':LEVEL,'checks':{},'errors':[{'phase':'preflight','code':code}],
            'sessions':[],'browser_actions_started':False}


def run(provider,handler,readiness,finalize=None):
    """Every tool worker gets 20s; existing GUI setup has its own additional bounds.

    Join calls before cleanup. Never abandon a live thread to claim a hard global
    deadline while that thread can still create browser windows afterward.
    """
    if provider is None or handler is None:return _refused('plugin_capability_required')
    try:ready=readiness()
    except Exception:return _refused('selftest_readiness_unavailable')
    if not isinstance(ready,dict) or not ready.get('ready'):return _refused('selftest_not_ready')
    run_id=secrets.token_hex(8)
    sessions=[{'task_id':f'chrome-selftest-{run_id}-{i}',
        'session_id':f'chrome-selftest-session-{run_id}-{i}',
        'session_key':f'chrome-selftest-route-{run_id}-{i}',
        'browser_session':f'check_{i}_{run_id}'} for i in range(3)]
    report={'success':False,'level':LEVEL,'run_id':run_id,'sessions':sessions,'checks':{'readiness':True},
        'errors':[],'browser_actions_started':True,'worker_timeout_s':20,
        'setup_timeout_scope':'GUI setup has separate provider bounds; no hard total deadline claimed'}
    started=time.monotonic()

    def invoke(session,source):
        diagnostics=[]
        def collect(value):
            if not isinstance(value,dict):return
            row={}
            if isinstance(value.get('error'),str):row['error']=value['error'][:800]
            if isinstance(value.get('error_type'),str):row['error_type']=value['error_type'][:80]
            if isinstance(value.get('uncertain'),bool):row['uncertain']=value['uncertain']
            diagnostics[:]=[row]
        try:
            private={'_diagnostic_sink':collect} if source==START_SOURCE else {}
            result=handler({'code':source,'session':session['browser_session'],'timeout_s':20},
                **{key:session[key] for key in ('task_id','session_id','session_key')},**private)
            result=json.loads(result) if isinstance(result,str) else result
            result=dict(result) if isinstance(result,dict) else {'success':False,'error':'invalid_result'}
            if diagnostics:result['_operator_diagnostic']=diagnostics[0]
            return result
        except Exception:return {'success':False,'error':'handler_raised'}

    def phase(source):
        barrier=threading.Barrier(3)
        def call(session):
            barrier.wait(timeout=5)
            return invoke(session,source)
        begin=time.monotonic()
        with ThreadPoolExecutor(max_workers=3,thread_name_prefix='chrome-selftest') as pool:
            futures=[pool.submit(copy_context().run,call,session) for session in sessions]
            results=[future.result() for future in futures]
        return results,time.monotonic()-begin

    def record_failures(results,phase_name):
        for index,result in enumerate(results):
            if result.get('success') is True and result.get('fallback_used') is False:continue
            error=str(result.get('error',''))
            public_code=result.get('error_code')
            code=public_code if public_code in {'browser_unavailable','browser_outcome_unknown',
                'browser_cleanup_incomplete','dialog_pending'} else next(
                (code for code in KNOWN_ERRORS if error.startswith(code)), 'registered_tool_failed')
            failure={'phase':phase_name,'session_index':index,'code':code}
            if phase_name=='startup' and isinstance(result.get('_operator_diagnostic'),dict):
                failure['diagnostic']=result['_operator_diagnostic']
            report['errors'].append(failure)

    def ownership():
        with provider.lock:
            states=[(provider.states.get((s['task_id'],s['browser_session'])) or {}) for s in sessions]
            targets=[set((entry.get('state') or {}).get('owned') or {}) for entry in states]
            windows=[set(v for v in ((entry.get('state') or {}).get('owned') or {}).values() if v is not None)
                     for entry in states]
            valid=all(not e.get('uncertain') and (e.get('state') or {}).get('verified') is True
                      and (e.get('state') or {}).get('current') in targets[i] for i,e in enumerate(states))
        return targets,windows,valid

    try:
        # Establish one distinct session at a time. A failed consent/setup stops
        # here rather than queuing more windows behind the same failing prompt.
        results=[];begin=time.monotonic()
        for session in sessions:
            result=invoke(session,START_SOURCE);results.append(result)
            if result.get('success') is not True or result.get('fallback_used') is not False:break
            if 'Example Domain' not in str(result.get('stdout','')):
                report['errors'].append({'phase':'startup','code':'selftest_unexpected_page_content'})
                break
        report['startup_seconds']=round(time.monotonic()-begin,3)
        report['startup_calls']=len(results)
        record_failures(results,'startup')
        report['checks']['all_pages_read']=len(results)==3 and all(r.get('success') is True and r.get('fallback_used') is False
            and 'Example Domain' in str(r.get('stdout','')) for r in results)
        before,windows,valid=ownership()
        report['checks']['distinct_owned_targets']=valid and all(before) and len(set.union(*before))==sum(map(len,before))
        report['checks']['distinct_owned_windows']=all(windows) and len(set.union(*windows))==sum(map(len,windows))
        if all(report['checks'].values()):
            results,elapsed=phase(PARALLEL_SOURCE)
            report['parallel_phase_seconds']=round(elapsed,3)
            report['serial_wait_floor_seconds']=3
            record_failures(results,'parallel')
            reads=all(r.get('success') is True and r.get('fallback_used') is False
                and 'Example Domain' in str(r.get('stdout','')) and 'SELFTEST_WAIT_COMPLETE' in str(r.get('stdout',''))
                for r in results)
            after,_,valid=ownership()
            report['checks']['same_owned_targets_after_second_call']=valid and before==after
            report['checks']['parallel_page_work_observed']=reads and elapsed<3
    except Exception:
        report['errors'].append({'phase':'diagnostic','code':'selftest_observation_failed'})
    finally:
        def cleanup(session):
            key=(session['task_id'],session['browser_session'])
            with provider.lock:present=key in provider.states
            result=invoke(session,FINISH_SOURCE) if present else {'success':True,'fallback_used':False}
            with provider.lock:gone=key not in provider.states
            if gone and finalize is not None:
                try:finalize(session['session_id'])
                except Exception:return False
            return result.get('success') is True and result.get('fallback_used') is False and gone
        with ThreadPoolExecutor(max_workers=3,thread_name_prefix='chrome-selftest-cleanup') as pool:
            futures=[pool.submit(copy_context().run,cleanup,session) for session in sessions]
            clean=[future.result() for future in futures]
        report['checks']['all_test_sessions_cleaned']=all(clean)
        for index,ok in enumerate(clean):
            if not ok:report['errors'].append({'phase':'cleanup','session_index':index,'code':'selftest_cleanup_incomplete'})
    report['elapsed_seconds']=round(time.monotonic()-started,3)
    report['success']=all(report['checks'].values()) and not report['errors']
    return report


def register(ctx,provider=None,handler=None,readiness=None,finalize=None):
    lock=threading.Lock()
    def command(raw_args=''):
        mode=str(raw_args or '').strip()
        if mode not in ('','manual','removal'):return json.dumps(_refused('selftest_arguments_not_supported'))
        if not lock.acquire(blocking=False):return json.dumps(_refused('selftest_already_running'))
        try:
            if mode=='removal':
                if __package__:
                    from .removal_selftest import run as removal_test
                else:
                    from removal_selftest import run as removal_test
                return json.dumps(removal_test(provider,readiness),sort_keys=True)
            if __package__:
                from .consent import manual_consent
            else:
                from consent import manual_consent
            with manual_consent() if mode=='manual' else nullcontext():
                report=run(provider,handler,readiness,finalize)
            report['consent_mode']='manual' if mode=='manual' else 'automatic'
            return json.dumps(report,sort_keys=True)
        finally:lock.release()
    ctx.register_command(name='original-chrome-test',handler=command,
        description='Test three example.com sessions. Optional manual waits for your debug-permission click; removal tests cleanup after deleting only a temporary source fixture.')
