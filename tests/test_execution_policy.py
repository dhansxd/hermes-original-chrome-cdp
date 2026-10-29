"""Agent scripts never obtain Python objects, raw transports or host capabilities."""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution_policy import PolicyError, execute_source, validate_source


class ExecutionPolicyTests(unittest.TestCase):
    def run_script(self, source, helpers=None):
        output = io.StringIO()
        execute_source(source, helpers or {}, output)
        return output.getvalue()

    def test_normal_navigation_and_data_processing(self):
        navigate = Mock(return_value={'frameId': 'own-frame'})
        page = Mock(return_value={'text': 'Welcome', 'controls': [{'tag': 'button'}, {'tag': 'input'}]})
        source = """goto_url('https://example.test')
page = read_page()
tags = []
for item in page['controls']:
    tags.append(item.get('tag'))
if len(tags) == 2:
    print(page['text'], ','.join(tags))
"""
        self.assertEqual(self.run_script(source, {'goto_url': navigate, 'read_page': page}), 'Welcome button,input\n')
        navigate.assert_called_once_with('https://example.test')
        page.assert_called_once_with()

    def test_disallowed_code_is_rejected_before_earlier_browser_action(self):
        forbidden = [
            'import os', 'from pathlib import Path', 'open("Cookies")',
            '__import__("os")', 'eval("1")', 'exec("pass")',
            'http_get("https://example.test")', 'js("document.cookie")',
            'cdp("Network.getCookies")', 'upload_file("input", "Cookies")',
            'f = page_info.__globals__', 'f = (1).__class__',
            'print("{0.__class__}".format(1))', 'f = print; f(1)',
            'page_info(**{})', 'class Evil: pass', 'def f(): pass',
            'print = 1', 'a = [x for x in range(2)]',
        ]
        for code in forbidden:
            with self.subTest(code=code):
                navigation = Mock()
                with self.assertRaises(PolicyError):
                    self.run_script("goto_url('https://example.test')\n" + code, {'goto_url': navigation})
                navigation.assert_not_called()

    def test_returned_python_object_is_never_exposed(self):
        class Dangerous:
            def __str__(self):
                raise AssertionError('must not invoke object conversion')
        with self.assertRaisesRegex(PolicyError, 'non_data'):
            self.run_script('print(page_info())', {'page_info': lambda: Dangerous()})

    def test_no_implicit_retry_after_helper_timeout(self):
        click = Mock(side_effect=TimeoutError('outcome unknown'))
        with self.assertRaises(TimeoutError):
            self.run_script("click_element('button')\nclick_element('button')", {'click_element': click})
        click.assert_called_once()

    def test_resource_limits(self):
        for source in ('while True: pass', 'print(list(range(100000000)))',
                       "print('a'*100000000)", "print('%100000000s' % 'x')"):
            with self.subTest(source=source), self.assertRaises(PolicyError):
                self.run_script(source)

    def test_append_copies_data_and_cannot_form_reference_cycles(self):
        self.assertEqual(self.run_script('x = []\nx.append(x)\nprint(x)'), '[[]]\n')

    def test_loop_control_and_fstrings(self):
        self.assertEqual(self.run_script("""total = 0
for n in range(10):
    if n == 2: continue
    if n == 4: break
    total += n
print(f'total={total}')
"""), 'total=4\n')

    def test_source_validation_has_no_helper_or_browser_dependencies(self):
        self.assertIsNotNone(validate_source('print(finish_browser())'))


if __name__ == '__main__':
    unittest.main()
