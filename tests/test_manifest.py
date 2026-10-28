"""Installer-visible metadata must describe the registrations actually shipped."""
import ast
import sys
import unittest
from pathlib import Path

import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

class ManifestTests(unittest.TestCase):
    def test_metadata_declares_lifecycle_events_and_profile_local_account_setting(self):
        manifest=yaml.safe_load((ROOT/'plugin.yaml').read_text())
        self.assertEqual(set(manifest.get('provides_hooks',[])),{
            'on_session_finalize','agent_loop_stopped','on_session_end',
            'on_human_input_request','on_human_input_resolved','transform_llm_output'})
        self.assertEqual(manifest.get('emits'),['browser_cleanup'])
        self.assertEqual(manifest.get('homepage'),'https://github.com/dhansxd/hermes-original-chrome-default-plugin')
        setting=manifest.get('config_schema',{}).get('expected_account',{})
        self.assertEqual(setting.get('type'),'str')
        self.assertTrue(setting.get('required'))
        self.assertNotIn('default',setting)

    def test_shipped_python_uses_no_personal_account_literals(self):
        # Installed archives and staged snapshots need no Git executable/metadata.
        paths=list(ROOT.glob('*.py'))+list((ROOT/'tests').glob('*.py'))+list((ROOT/'vendor').glob('*.py'))
        self.assertGreater(len(paths),10)
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.Constant) and isinstance(node.value,str):
                    if '@' in node.value and 'gmail.com' in node.value:
                        self.fail('Personal account literal in '+str(path.relative_to(ROOT)))

if __name__=='__main__':unittest.main()
