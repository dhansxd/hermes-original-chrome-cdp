"""Installer-visible metadata must describe the registrations actually shipped."""
import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

class ManifestTests(unittest.TestCase):
    def test_unique_names_pass_actual_catalog_builtin_collision_check(self):
        from hermes_cli.plugin_validate import ValidationReport,_check_builtin_collisions
        manifest=yaml.safe_load((ROOT/'plugin.yaml').read_text())
        self.assertNotIn('tools.override',manifest.get('capabilities',[]))
        report=ValidationReport()
        _check_builtin_collisions(report,manifest,{'tools':['browser_original_chrome_exec','browser_original_chrome_vault']})
        self.assertTrue(report.ok,report.failures)

    def test_declared_tools_exactly_cover_actual_registration(self):
        import plugin
        manifest=yaml.safe_load((ROOT/'plugin.yaml').read_text())
        ctx=Mock();ctx.state.data_dir=Path('/synthetic-plugin-state')
        with patch('plugin.ChromeProvider'):plugin.register(ctx)
        actual={call.kwargs['name'] for call in ctx.register_tool.call_args_list}
        self.assertEqual(set(manifest.get('provides_tools',[])),actual)
        self.assertEqual(actual,{'browser_original_chrome_exec','browser_original_chrome_vault'})
        ctx.has_capability.assert_not_called()

    def test_metadata_declares_lifecycle_events_and_profile_local_account_setting(self):
        manifest=yaml.safe_load((ROOT/'plugin.yaml').read_text())
        self.assertEqual(set(manifest.get('provides_hooks',[])),{
            'pre_tool_call',
            'on_session_finalize','agent_loop_stopped','on_session_end',
            'on_human_input_request','on_human_input_resolved','transform_llm_output'})
        self.assertEqual(manifest.get('emits'),['browser_cleanup'])
        self.assertEqual(manifest.get('homepage'),'https://github.com/dhansxd/hermes-original-chrome-default-plugin')
        self.assertIn('/original-chrome-status',manifest['description'])
        self.assertIn('/original-chrome-test',manifest['description'])
        setting=manifest.get('config_schema',{}).get('expected_account',{})
        self.assertEqual(setting.get('type'),'str')
        self.assertTrue(setting.get('required'))
        self.assertNotIn('default',setting)

    def test_only_explicit_production_account_allowlist_contains_personal_identity(self):
        # Installed archives and staged snapshots need no Git executable/metadata.
        paths=list(ROOT.glob('*.py'))+list((ROOT/'tests').glob('*.py'))+list((ROOT/'vendor').glob('*.py'))
        self.assertGreater(len(paths),10)
        for path in paths:
            tree=ast.parse(path.read_text())
            allowed={id(n.value) for n in tree.body if path==ROOT/'plugin.py' and isinstance(n,ast.Assign)
                     and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='APPROVED_ACCOUNT'}
            for node in ast.walk(tree):
                if isinstance(node,ast.Constant) and isinstance(node.value,str):
                    if '@' in node.value and 'gmail.com' in node.value and id(node) not in allowed:
                        self.fail('Personal account literal in '+str(path.relative_to(ROOT)))

if __name__=='__main__':unittest.main()
