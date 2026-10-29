"""Data-only browser script interpreter; never executes agent Python bytecode.

The trusted worker supplies named browser operations. Agent values can only be
bounded plain data, never Python modules, functions, classes or transport objects.
This confines browser_exec, not other Hermes tools or code installed on the host.
"""
import ast
import copy
import math
import operator


class PolicyError(RuntimeError):
    pass


HELPERS = frozenset({
    'goto_url', 'page_info', 'read_page', 'click_element', 'click_at_xy',
    'type_text', 'fill_input', 'press_key', 'scroll', 'capture_screenshot',
    'list_tabs', 'current_tab', 'activate_tab', 'switch_tab', 'new_tab',
    'close_tab', 'ensure_real_tab', 'wait', 'wait_for_load',
    'wait_for_element', 'wait_for_network_idle', 'drain_events',
    'answer_dialog', 'finish_browser',
})
BUILTINS = frozenset({'print', 'len', 'str', 'int', 'float', 'bool', 'range',
                      'enumerate', 'zip', 'min', 'max', 'abs', 'round',
                      'sorted', 'list', 'dict'})
METHODS = frozenset({'get', 'keys', 'values', 'items', 'append', 'strip',
                     'lower', 'upper', 'startswith', 'endswith', 'split', 'join'})
MAX_SOURCE = 32768
MAX_DATA = 65536
MAX_ITEMS = 4096
MAX_STEPS = 20000
TOOL_DESCRIPTION = """Use the user's original Chrome GUI through named browser helpers.
The code parameter is a bounded Python-like browser script: assignments, if,
for/while, break/continue, lists/dicts, indexing, arithmetic, f-strings and print.
No imports, function definitions, filesystem/process/network access, raw JS or CDP.
Helpers: goto_url(url), page_info(), read_page(selector='body', limit=12000),
click_element(selector), click_at_xy(x,y), type_text(text), fill_input(selector,text),
press_key(key), scroll(x,y,dy=-300,dx=0), capture_screenshot(full=False),
list_tabs(), current_tab(), new_tab(url='about:blank'), switch_tab(target),
activate_tab(target), close_tab(target=None), ensure_real_tab(), wait(seconds=1),
wait_for_load(timeout=15), wait_for_element(selector,timeout=10,visible=False),
wait_for_network_idle(timeout=10,idle_ms=500), drain_events(),
answer_dialog(accept,prompt_text=None), finish_browser(retain=[]).
Only owned tabs are available. URLs must be HTTP(S) or about:blank.
read_page returns visible text and visible controls with selectors; passwords
and hidden field values are excluded. Screenshot filenames are generated locally.
Use print(...) to return results. Data methods: get/keys/values/items, append,
strip/lower/upper/startswith/endswith/split/join. Data builtins: len/str/int/float/
bool/range/enumerate/zip/min/max/abs/round/sorted/list/dict.
Example: goto_url('https://example.com'); print(read_page())
If a browser action fails with an unknown outcome, do not repeat its clicks,
inputs, navigation, or dialog answers. Preserve the returned partial findings.
The result may report a bounded retry of a read-only batch, or a fresh session
ready for your next call after cleanup. Continue the research from those findings
using the same session name; choose new page work explicitly rather than replaying
the failed script. If cleanup is incomplete, follow the result's recovery guidance.
"""


def apply_browser_schema(schema):
    schema = copy.deepcopy(schema)
    schema['description'] = TOOL_DESCRIPTION
    if 'code' in schema.get('parameters', {}).get('properties', {}):
        schema['parameters']['properties']['code']['description'] = (
            'Bounded browser script using the helpers described above; no arbitrary Python.')
    return schema


_NODES = (ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.If, ast.For,
          ast.While, ast.Break, ast.Continue, ast.Pass, ast.Name, ast.Constant,
          ast.List, ast.Tuple, ast.Dict, ast.Subscript, ast.Slice, ast.Call,
          ast.Attribute, ast.keyword, ast.BinOp, ast.UnaryOp, ast.BoolOp,
          ast.Compare, ast.IfExp, ast.JoinedStr, ast.FormattedValue,
          ast.Load, ast.Store, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
          ast.Mod, ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
          ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
          ast.In, ast.NotIn, ast.Is, ast.IsNot)


def _plain_name(name):
    if name.startswith('_') or name in {'True', 'False', 'None'}:
        raise PolicyError('browser_script_name_not_allowed')


def _assignment(target):
    if isinstance(target, ast.Name):
        _plain_name(target.id)
        if target.id in HELPERS | BUILTINS:
            raise PolicyError('browser_script_reserved_name')
    elif isinstance(target, (ast.List, ast.Tuple)):
        for item in target.elts:
            _assignment(item)
    else:
        raise PolicyError('browser_script_assignment_not_allowed')


def validate_source(source):
    """Validate the entire program before any browser side effect."""
    if not isinstance(source, str) or len(source) > MAX_SOURCE:
        raise PolicyError('browser_script_size_limit')
    try:
        tree = ast.parse(source, mode='exec')
    except (SyntaxError, ValueError, RecursionError):
        raise PolicyError('browser_script_invalid_syntax') from None
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_ITEMS:
        raise PolicyError('browser_script_size_limit')
    parents = {child: node for node in nodes for child in ast.iter_child_nodes(node)}
    for node in nodes:
        if not isinstance(node, _NODES):
            raise PolicyError('browser_script_syntax_not_allowed: ' + type(node).__name__)
        if isinstance(node, ast.Name):
            _plain_name(node.id)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in HELPERS | BUILTINS:
                    raise PolicyError('browser_script_operation_not_allowed: ' + node.func.id)
            elif not isinstance(node.func, ast.Attribute):
                raise PolicyError('browser_script_indirect_call_not_allowed')
            if any(k.arg is None or k.arg.startswith('_') for k in node.keywords):
                raise PolicyError('browser_script_keyword_not_allowed')
        if isinstance(node, ast.Attribute):
            parent = parents.get(node)
            if node.attr not in METHODS or not isinstance(parent, ast.Call) or parent.func is not node:
                raise PolicyError('browser_script_attribute_not_allowed')
        if isinstance(node, ast.Assign):
            for target in node.targets:
                _assignment(target)
        if isinstance(node, (ast.AugAssign, ast.For)):
            _assignment(node.target)
        if isinstance(node, ast.Dict) and any(k is None for k in node.keys):
            raise PolicyError('browser_script_unpack_not_allowed')
        if isinstance(node, ast.FormattedValue) and (node.format_spec or node.conversion not in (-1, 115, 114)):
            raise PolicyError('browser_script_format_not_allowed')
    return tree


def plain(value, depth=0, budget=None):
    """Copy into bounded inert data; do not invoke arbitrary conversion methods."""
    budget = [MAX_DATA] if budget is None else budget
    budget[0] -= 1
    if depth > 20 or budget[0] < 0:
        raise PolicyError('browser_script_data_limit')
    if type(value) is str:
        budget[0] -= len(value)
    elif type(value) is int:
        if value.bit_length() > 63:
            raise PolicyError('browser_script_number_limit')
    elif type(value) is float:
        if not math.isfinite(value):
            raise PolicyError('browser_script_number_limit')
    elif value is None or type(value) is bool:
        pass
    elif type(value) in (list, tuple):
        if len(value) > MAX_ITEMS:
            raise PolicyError('browser_script_data_limit')
        value = [plain(v, depth + 1, budget) for v in value]
    elif type(value) is dict:
        if len(value) > MAX_ITEMS or any(type(k) not in (str, int, bool) for k in value):
            raise PolicyError('browser_script_data_limit')
        value = {plain(k, depth + 1, budget): plain(v, depth + 1, budget) for k, v in value.items()}
    else:
        raise PolicyError('browser_script_non_data_value')
    if budget[0] < 0:
        raise PolicyError('browser_script_data_limit')
    return value


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class Interpreter:
    def __init__(self, helpers, output):
        self.helpers = {k: v for k, v in helpers.items() if k in HELPERS}
        self.output = output
        self.env = {}
        self.steps = MAX_STEPS

    def tick(self):
        self.steps -= 1
        if self.steps < 0:
            raise PolicyError('browser_script_step_limit')

    def assign(self, target, value):
        if isinstance(target, ast.Name):
            self.env[target.id] = plain(value)
            plain(self.env)  # Bound all live variables, not just each expression.
        else:
            if type(value) not in (list, tuple) or len(target.elts) != len(value):
                raise PolicyError('browser_script_unpack_mismatch')
            for child, item in zip(target.elts, value):
                self.assign(child, item)

    def block(self, nodes):
        for node in nodes:
            self.tick()
            if isinstance(node, ast.Expr):
                self.expr(node.value)
            elif isinstance(node, ast.Assign):
                value = self.expr(node.value)
                for target in node.targets:
                    self.assign(target, value)
            elif isinstance(node, ast.AugAssign):
                self.assign(node.target, self.binary(node.op, self.expr(node.target), self.expr(node.value)))
            elif isinstance(node, ast.If):
                self.block(node.body if self.expr(node.test) else node.orelse)
            elif isinstance(node, (ast.For, ast.While)):
                iterable = iter(self.expr(node.iter)) if isinstance(node, ast.For) else None
                while True:
                    self.tick()
                    if iterable is not None:
                        try:
                            self.assign(node.target, next(iterable))
                        except StopIteration:
                            self.block(node.orelse)
                            break
                    elif not self.expr(node.test):
                        self.block(node.orelse)
                        break
                    try:
                        self.block(node.body)
                    except _Continue:
                        continue
                    except _Break:
                        break
            elif isinstance(node, ast.Break):
                raise _Break()
            elif isinstance(node, ast.Continue):
                raise _Continue()
            elif not isinstance(node, ast.Pass):
                raise PolicyError('browser_script_statement_not_allowed')

    def binary(self, op, left, right):
        if isinstance(op, ast.Mod) and type(left) is str:
            raise PolicyError('browser_script_format_not_allowed')
        if isinstance(op, ast.Mult):
            seq, count = (left, right) if type(left) in (str, list) else (right, left)
            if type(seq) in (str, list) and type(count) is int and len(seq) * max(0, count) > MAX_ITEMS:
                raise PolicyError('browser_script_data_limit')
        fn = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}[type(op)]
        return plain(fn(left, right))

    def expr(self, node):
        self.tick()
        if isinstance(node, ast.Constant):
            return plain(node.value)
        if isinstance(node, ast.Name):
            if node.id not in self.env:
                raise PolicyError('browser_script_unknown_variable: ' + node.id)
            return self.env[node.id]
        if isinstance(node, (ast.List, ast.Tuple)):
            return plain([self.expr(v) for v in node.elts])
        if isinstance(node, ast.Dict):
            return plain({self.expr(k): self.expr(v) for k, v in zip(node.keys, node.values)})
        if isinstance(node, ast.BinOp):
            return self.binary(node.op, self.expr(node.left), self.expr(node.right))
        if isinstance(node, ast.UnaryOp):
            return plain({ast.Not: operator.not_, ast.USub: operator.neg, ast.UAdd: operator.pos}[type(node.op)](self.expr(node.operand)))
        if isinstance(node, ast.BoolOp):
            value = self.expr(node.values[0])
            for item in node.values[1:]:
                if (isinstance(node.op, ast.And) and not value) or (isinstance(node.op, ast.Or) and value):
                    break
                value = self.expr(item)
            return value
        if isinstance(node, ast.Compare):
            left = self.expr(node.left)
            ops = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
                   ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
                   ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
                   ast.Is: operator.is_, ast.IsNot: operator.is_not}
            for op, item in zip(node.ops, node.comparators):
                right = self.expr(item)
                if not ops[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return self.expr(node.body if self.expr(node.test) else node.orelse)
        if isinstance(node, ast.Subscript):
            key = node.slice
            key = slice(*(self.expr(v) if v else None for v in (key.lower, key.upper, key.step))) if isinstance(key, ast.Slice) else self.expr(key)
            return plain(self.expr(node.value)[key])
        if isinstance(node, ast.JoinedStr):
            parts = []
            size = 0
            for item in node.values:
                part = str(self.expr(item.value)) if isinstance(item, ast.FormattedValue) else item.value
                size += len(part)
                if size > MAX_DATA:
                    raise PolicyError('browser_script_data_limit')
                parts.append(part)
            return ''.join(parts)
        if isinstance(node, ast.Call):
            args = [self.expr(v) for v in node.args]
            kwargs = {v.arg: self.expr(v.value) for v in node.keywords}
            plain([args, kwargs])
            if isinstance(node.func, ast.Attribute):
                obj = self.expr(node.func.value)
                name = node.func.attr
                allowed = {dict: {'get', 'keys', 'values', 'items'}, list: {'append'},
                           str: {'strip', 'lower', 'upper', 'startswith', 'endswith', 'split', 'join'}}
                if name not in allowed.get(type(obj), set()):
                    raise PolicyError('browser_script_method_not_allowed')
                if name == 'append':
                    if len(args) != 1 or kwargs:
                        raise PolicyError('browser_script_invalid_arguments')
                    value = plain(args[0])
                    plain(obj + [value])
                    obj.append(value)
                    plain(self.env)
                    return None
                if name == 'join' and (len(args) != 1 or not isinstance(args[0], list) or sum(len(v) for v in args[0]) + len(obj) * len(args[0]) > MAX_DATA):
                    raise PolicyError('browser_script_data_limit')
                value = getattr(obj, name)(*args, **kwargs)
                if name in {'keys', 'values', 'items'}:
                    value = list(value)
            elif node.func.id in self.helpers:
                value = self.helpers[node.func.id](*args, **kwargs)
            else:
                value = self.builtin(node.func.id, args, kwargs)
            return plain(value)
        raise PolicyError('browser_script_expression_not_allowed')

    def builtin(self, name, args, kwargs):
        if name == 'print':
            if set(kwargs) - {'sep', 'end'} or any(type(v) is not str for v in kwargs.values()):
                raise PolicyError('browser_script_print_arguments')
            text = kwargs.get('sep', ' ').join(str(v) for v in args) + kwargs.get('end', '\n')
            if self.output.tell() + len(text) > 20000:
                raise PolicyError('browser_script_output_limit')
            self.output.write(text)
            return None
        if name == 'range':
            result = range(*args, **kwargs)
            if len(result) > MAX_ITEMS:
                raise PolicyError('browser_script_data_limit')
            return list(result)
        if name in {'enumerate', 'zip'}:
            return list({'enumerate': enumerate, 'zip': zip}[name](*args, **kwargs))
        funcs = {'len': len, 'str': str, 'int': int, 'float': float, 'bool': bool,
                 'min': min, 'max': max, 'abs': abs, 'round': round,
                 'sorted': sorted, 'list': list, 'dict': dict}
        if name not in funcs:
            raise PolicyError('browser_script_operation_unavailable')
        return funcs[name](*args, **kwargs)


def execute_source(source, helpers, output):
    interpreter = Interpreter(helpers, output)
    try:
        interpreter.block(validate_source(source).body)
    except (_Break, _Continue):
        raise PolicyError('browser_script_loop_control_outside_loop') from None
