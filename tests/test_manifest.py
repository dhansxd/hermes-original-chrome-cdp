import unittest
from pathlib import Path

from packaging.requirements import Requirement
from utils import fast_safe_load


class ManifestTests(unittest.TestCase):
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
