"""Model-facing browser results; operator diagnostics stay outside this boundary."""
import copy
import json
import re


_RECOVERY_GUIDANCE={
    'read_retry_succeeded':'A bounded read-only retry succeeded. Continue using this result and the preserved findings.',
    'read_retry_exhausted':'The bounded read retry reached its limit. Keep the partial findings and continue in a fresh named browser session; do not repeat uncertain actions.',
    'fresh_session_ready':'Cleanup completed. Continue research with the same session name; its next call opens a fresh session. Choose the next intended page step and do not repeat uncertain actions.',
    'fresh_session_required':'Keep the partial findings and continue research in a new named browser session. Leave the unfinished session for cleanup and do not repeat its uncertain actions.',
    'operator_attention':'Browser access needs operator attention. Keep the partial findings and continue any research that does not require this browser.',
    'continue_current_session':'Inspect the current page and continue with the next intended step; do not replay the failed script.',
    'correct_script':'Use the documented browser helpers and continue from the existing findings without repeating earlier actions.',
}


def _recovery(value,success):
    if not isinstance(value,dict) or value.get('status') not in _RECOVERY_GUIDANCE:return None
    status=value['status']
    if status=='fresh_session_ready' and value.get('cleanup_complete') is not True:status='fresh_session_required'
    if status=='read_retry_succeeded' and not success:status='read_retry_exhausted'
    result={'status':status,'next_action':_RECOVERY_GUIDANCE[status]}
    for name in ('cleanup_complete','partial_output_preserved'):
        if type(value.get(name)) is bool:result[name]=value[name]
    count=value.get('read_retry_count')
    if type(count) is int and 0<=count<=1:result['read_retry_count']=count
    session=value.get('session')
    if isinstance(session,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',session):result['session']=session
    return result


def _error(result):
    raw=result.get('error')
    code=raw.partition(':')[0] if isinstance(raw,str) else ''
    if code.startswith(('consent_','native_dialog_accessibility','safe_GUI_',
                        'accessibility_','Default_','Chrome_endpoint_',
                        'account_binding_','browser_configuration_',
                        'browser_provider_','browser_backend_','plugin_capability_')):
        return 'browser_unavailable','The browser is unavailable. Its configuration or permissions need operator attention.'
    if result.get('uncertain') is True:
        return 'browser_outcome_unknown','The preceding browser action could not be confirmed. Do not repeat its uncertain actions; preserve partial findings and follow the recovery guidance to continue research.'
    if code=='dialog_pending':
        return code,'A browser dialog needs an answer. Inspect page_info(), then use answer_dialog(); do not repeat the preceding action.'
    if code.startswith('browser_script_') or result.get('error_type')=='PolicyError':
        return 'invalid_browser_script','The browser script uses an unsupported operation or exceeds its limits. Use the documented browser helpers.'
    if code in {'invalid session name','browser_identity_required'}:
        return 'browser_session_unavailable','The browser session could not be selected.'
    if code in {'session_cleanup_in_progress','target_close_pending'}:
        return 'browser_session_busy','The browser session is finishing. Do not repeat its preceding action.'
    if code in {'target_not_owned','session_not_owned','window_binding_changed','binding_unavailable'}:
        return 'browser_tab_unavailable','The requested browser tab is unavailable to this session. Do not select another user tab as a substitute.'
    if code.startswith(('browser_url_','cdp_navigation_')):
        return 'browser_url_not_allowed','Use an HTTP(S) URL or about:blank.'
    if code in {'target_close_rejected','target_close_unconfirmed','cleanup_outcome_unknown','ownership_lost_after_timeout'}:
        return 'browser_cleanup_incomplete','The browser tabs could not be confirmed closed. Do not repeat the preceding action.'
    if code.startswith(('browser_selector_','browser_argument_','browser_dialog_answer_')):
        return 'invalid_browser_arguments','Check the arguments against the browser helper description.'
    if isinstance(raw,str) and any(marker in raw for marker in (
        'page_selector_not_unique','click_selector_not_unique','element_disabled',
        'element_not_visible','element_obscured','fill_input: element not found')):
        return 'browser_element_unavailable','The selected page element is missing, ambiguous, disabled, or obscured. Read the page again before choosing a target.'
    # Preserve a useful category without forwarding page-controlled exception
    # text, transport messages, filesystem paths, or executable helper snippets.
    return 'browser_action_failed','The browser action failed. Inspect the current page before continuing.'


def model_result(result,cleanup_reports=(),scrub=lambda value:value):
    """Allowlist result data. Never alter the provider's private state/report."""
    if not isinstance(result,dict):
        result={'success':False,'error':'invalid_browser_result','uncertain':True}
    public={'success':result.get('success') is True,
            'fallback_used':result.get('fallback_used') is True,
            'action_replayed':result.get('action_replayed') is True}
    if isinstance(result.get('stdout'),str):public['stdout']=scrub(result['stdout'])
    if isinstance(result.get('uncertain'),bool):public['uncertain']=result['uncertain']
    recovery=_recovery(result.get('recovery'),public['success'])
    if recovery is not None:public['recovery']=recovery
    if not public['success']:
        public['error_code'],public['error']=_error(result)
    cleanup_failed=any(isinstance(report,dict) and report.get('success') is not True for report in cleanup_reports)
    if cleanup_failed:
        public['cleanup_complete']=False
        public['notice']='Some browser tabs could not be confirmed closed.'
    if result.get('cleanup_only'):
        public['cleanup_complete']=public['success'] and not cleanup_failed
    # A screenshot is an artifact of the browser operation, not a diagnostic.
    # Do not rewrite binary/data-URL image blocks with a text-secret regex.
    blocks=result.get('content') if isinstance(result.get('content'),list) else []
    images=[copy.deepcopy(block) for block in blocks if
            isinstance(block,dict) and block.get('type') in {'image','image_url','input_image'}]
    if images:
        summary=json.dumps(public,ensure_ascii=False)
        return dict(public,_multimodal=True,text_summary=summary,
                    content=[{'type':'text','text':summary}]+images)
    # Preserve a standalone screenshot artifact until a caller supplies the
    # native image envelope. No filesystem reads/path discovery happen here.
    if isinstance(result.get('screenshot_path'),str):public['screenshot_path']=scrub(result['screenshot_path'])
    return public
