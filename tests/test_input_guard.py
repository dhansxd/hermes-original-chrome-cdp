import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from input_guard import install, prepare_code


class InputGuardTests(unittest.TestCase):
    def namespace(self, focused=True):
        return {'fill_input': Mock(return_value='native-result'),
                'js': Mock(return_value=focused), 'wait_for_element': Mock(return_value=True)}

    def test_failed_focus_never_calls_native_typing(self):
        for result in (False, None, 'true'):
            ns = self.namespace(result)
            native = ns['fill_input']
            install(ns)
            with self.assertRaisesRegex(RuntimeError, 'not focused'):
                ns['fill_input']('#hidden', 'fixture')
            native.assert_not_called()

    def test_success_uses_original_helper_once_and_preserves_options(self):
        ns = self.namespace()
        native = ns['fill_input']
        install(ns)
        self.assertEqual(ns['fill_input']('#visible', 'fixture', clear_first=False, timeout=2), 'native-result')
        ns['wait_for_element'].assert_called_once_with('#visible', timeout=2)
        native.assert_called_once_with('#visible', 'fixture', clear_first=False, timeout=0.0)

    def test_wait_failure_never_calls_native_typing(self):
        ns = self.namespace()
        native = ns['fill_input']
        ns['wait_for_element'].return_value = False
        install(ns)
        with self.assertRaisesRegex(RuntimeError, 'not found'):
            ns['fill_input']('#late', 'fixture', timeout=2)
        native.assert_not_called()
        ns['js'].assert_not_called()

    def test_repeated_hook_does_not_stack_guards(self):
        ns = self.namespace()
        native = ns['fill_input']
        code = prepare_code(prepare_code("fill_input('#visible', 'fixture')"))
        exec(code, ns)
        ns['js'].assert_called_once()
        native.assert_called_once()

    def test_python_docstrings_and_future_imports_keep_their_semantics(self):
        for prefix in ('', '# comment\n', '"""keterangan é"""\n',
                       'from __future__ import annotations\n',
                       '"é"; from __future__ import annotations; ',
                       '"é"\nfrom __future__ import (\n annotations,\n) # comment\n'):
            ns = self.namespace(False)
            native = ns['fill_input']
            code = prefix + "fill_input('#hidden', 'fixture')"
            with self.assertRaisesRegex(RuntimeError, 'not focused'):
                exec(prepare_code(code), ns)
            native.assert_not_called()
            if prefix.startswith('"'):
                self.assertIsInstance(ns['__doc__'], str)

    def test_invalid_and_empty_code_still_belong_to_native_runner(self):
        for code in ('', None, 'if :'):
            self.assertEqual(prepare_code(code), code)


if __name__ == '__main__':
    unittest.main()
