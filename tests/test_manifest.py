import ast
import unittest
from pathlib import Path

from packaging.requirements import Requirement
from utils import fast_safe_load


class ManifestTests(unittest.TestCase):
    def test_runtime_hermes_imports_use_only_public_plugin_apis(self):
        allowed = {
            'agent.browser_provider': {'BrowserProvider'},
            'gateway.session_context': {'get_session_env'},
            'hermes_cli.config': {'load_config_readonly'},
            'hermes_constants': {'get_hermes_home'},
            'tools.browser_supervisor': {'SUPERVISOR_REGISTRY'},
        }
        core = {'agent', 'gateway', 'hermes_cli', 'hermes_constants', 'tools', 'utils', 'pm', 'browser_harness'}
        root = Path(__file__).resolve().parents[1]
        for path in root.glob('*.py'):
            name = path.name
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split('.')[0], core, (name, node.lineno, alias.name))
                if isinstance(node, ast.ImportFrom) and not node.level and node.module:
                    if node.module.split('.')[0] in core:
                        self.assertIn(node.module, allowed, (name, node.lineno, node.module))
                        for alias in node.names:
                            self.assertIn(alias.name, allowed[node.module], (name, node.lineno, alias.name))

    def test_macos_dependencies_do_not_constrain_hermes_android_resolution(self):
        manifest = fast_safe_load((Path(__file__).resolve().parents[1] / 'plugin.yaml').read_text())
        dependencies = [Requirement(value) for value in manifest['python_dependencies']]
        self.assertEqual({dependency.name for dependency in dependencies}, {'psutil', 'websockets'})
        for dependency in dependencies:
            self.assertIsNotNone(dependency.marker)
            self.assertTrue(dependency.marker.evaluate({'sys_platform': 'darwin'}))
            for platform in ('android', 'linux', 'win32'):
                self.assertFalse(dependency.marker.evaluate({'sys_platform': platform}))


if __name__ == '__main__':
    unittest.main()
