"""Pure recovery decisions; execution, ownership checks and cleanup stay in provider.

Navigation is deliberately an action: even a GET URL may log out or mutate a
server. A research-looking script never earns permission to replay navigation,
clicks, inputs, dialog answers, or tab mutations after an uncertain outcome.
"""
import ast
import math

if __package__:
    from .execution_policy import HELPERS, PolicyError, validate_source
else:
    from execution_policy import HELPERS, PolicyError, validate_source


READ_HELPERS=frozenset({'page_info','read_page','list_tabs','current_tab',
    'ensure_real_tab','wait','wait_for_load','wait_for_element'})
MAX_READ_RETRIES=1
MIN_RETRY_BUDGET_S=5
MAX_READ_RETRY_S=10
_SETUP_PREFIXES=('consent_','safe_GUI_','accessibility_','native_dialog_accessibility',
    'Default_','Chrome_endpoint_','account_binding_','browser_configuration_',
    'browser_provider_','browser_backend_','plugin_capability_','browser_identity_')
_READ_TIMEOUTS={'browser_exec_timeout','CDP_response_timeout','browser_read_timeout'}
_WAIT_DEFAULTS={'wait':(0,'seconds',1),'wait_for_load':(0,'timeout',15),
                'wait_for_element':(1,'timeout',10)}


def classify_script(source):
    """Conservative whole-program classification, including unexecuted branches."""
    try:tree=validate_source(source)
    except (PolicyError,TypeError,ValueError):return {'kind':'invalid','helpers':[]}
    helpers=sorted({node.func.id for node in ast.walk(tree)
                    if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
                    and node.func.id in HELPERS})
    if any(name not in READ_HELPERS for name in helpers):kind='actions'
    elif set(helpers)-{'wait'}:kind='read_only'
    else:kind='data_only'
    return {'kind':kind,'helpers':helpers}


def _waits_fit_retry(source,budget):
    """Do not retry an already-overlong wait or an unbounded wait loop."""
    tree=validate_source(source)
    waits=[node for node in ast.walk(tree) if isinstance(node,ast.Call)
           and isinstance(node.func,ast.Name) and node.func.id in _WAIT_DEFAULTS]
    if waits and any(isinstance(node,(ast.For,ast.While)) for node in ast.walk(tree)):return False
    total=0
    for node in waits:
        index,keyword,default=_WAIT_DEFAULTS[node.func.id]
        value=next((item.value for item in node.keywords if item.arg==keyword),
                   node.args[index] if len(node.args)>index else ast.Constant(default))
        if not isinstance(value,ast.Constant) or type(value.value) not in (int,float):return False
        if not math.isfinite(value.value) or value.value<0:return False
        total+=value.value
    return total<budget


def recovery_plan(source,result,*,attempts=0,remaining_s=0,
                  session_verified=False,transport_usable=False):
    """Choose at most one read retry; never perform I/O or replay actions here.

    The caller supplies positive evidence for the *same* owned session and held
    transport. Missing evidence, a lost connection, or an exhausted time budget
    cannot authorize another attempt. A fresh-session decision authorizes no
    navigation or replay: cleanup and a new blank owned session are separate
    provider operations, and the agent continues from its preserved research.
    """
    kind=classify_script(source)['kind']
    plan={'action':'none','reason':'completed','batch_kind':kind,
          'max_read_retries':MAX_READ_RETRIES,'replay_actions':False}
    if not isinstance(result,dict):
        return dict(plan,action='fresh_session',reason='outcome_unknown')
    if result.get('success') is True:return plan
    raw=result.get('error')
    code=raw.partition(':')[0] if isinstance(raw,str) else ''
    if code.startswith(_SETUP_PREFIXES):
        return dict(plan,action='operator_attention',reason='browser_unavailable')
    if code=='dialog_pending':
        return dict(plan,action='continue_current_session',reason='dialog_requires_answer')
    if kind=='invalid' or code.startswith('browser_script_') or result.get('error_type')=='PolicyError':
        return dict(plan,action='correct_script',reason='script_rejected')
    remaining=(float(remaining_s) if type(remaining_s) in (int,float) and math.isfinite(remaining_s) else 0)
    retry_count=attempts if type(attempts) is int and attempts>=0 else MAX_READ_RETRIES
    known_read_timeout=code in _READ_TIMEOUTS
    if (kind=='read_only' and known_read_timeout and retry_count<MAX_READ_RETRIES
        and remaining>=MIN_RETRY_BUDGET_S and session_verified is True and transport_usable is True
        and _waits_fit_retry(source,min(MAX_READ_RETRY_S,remaining))):
        return dict(plan,action='retry_read',reason='bounded_read_timeout',
                    retry_timeout_s=min(MAX_READ_RETRY_S,remaining))
    # No retry for navigation/network/consent errors, an unknown transport loss,
    # or a script containing even one possibly mutating operation.
    if result.get('uncertain') is True or code in _READ_TIMEOUTS or code.startswith(('observer_lost','browser_worker_failed','previous_execution_outcome_uncertain')):
        reason='read_retry_exhausted' if kind=='read_only' and retry_count>=MAX_READ_RETRIES else 'outcome_unknown'
        return dict(plan,action='fresh_session',reason=reason)
    return dict(plan,action='continue_current_session',reason='inspect_current_page')
