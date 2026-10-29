"""Official CLI lifecycle, local Git source, real loader; PM publication is a fixture.

No dependency resolution, bootstrap, external network, gateway or Chrome is run.
This verifies CLI/source/config/registry lifecycle, not PM's environment transaction.
"""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]


class PluginInstallationTests(unittest.TestCase):
    def test_host_routes_missing_selected_provider_to_local_after_plugin_unload(self):
        # Compatibility evidence for the absent-plugin boundary. Load the host's
        # actual routing code without replacing its registry entry or invoking
        # plugin discovery, profile reads, a browser transport or bootstrap.
        from tools import browser_session_cloud as cloud
        from tools.registry import registry
        spec=importlib.util.spec_from_file_location('host_browser_routing_fixture',
            Path(cloud.__file__).with_name('browser_use_cli.py'))
        host=importlib.util.module_from_spec(spec)
        with patch.object(registry,'register'):
            spec.loader.exec_module(host)
        session=types.ModuleType('tools.browser_session')
        session.get_session_info=Mock(side_effect=AssertionError('no browser session may start'))
        cdp=types.ModuleType('tools.browser_session_cdp')
        cdp.get_cdp_override=Mock(return_value='')
        with patch.dict(sys.modules,{'tools.browser_session':session,'tools.browser_session_cdp':cdp}), \
             patch.object(cloud,'browser_section',return_value={'cloud_provider':'original-chrome-default'}), \
             patch.object(cloud,'_ensure_browser_plugins_loaded'), \
             patch.object(cloud,'hermes_home_key',return_value='missing-provider-fixture'), \
             patch.object(cloud,'_registry_generation',return_value=(0,0)), \
             patch.dict(cloud._cached_providers,{},clear=True), \
             patch('agent.browser_registry.get_provider',return_value=None), \
             patch.object(host,'_resolve_local_cdp',return_value='fixture local route') as local:
            with self.assertRaisesRegex(ValueError,'no registered browser plugin'):
                cloud.get_cloud_provider()
            env={}
            self.assertEqual(host._resolve_backend_cdp(env,'fixture-task','fixture-session'),
                'fixture local route')
            local.assert_called_once_with(env,'fixture-task','fixture-session')
            session.get_session_info.assert_not_called()

    def test_official_install_enable_disable_reenable_uninstall(self):
        import yaml
        from rich.console import Console
        from hermes_constants import set_hermes_home_override,reset_hermes_home_override
        from hermes_cli import plugins_cmd as commands
        from hermes_cli.plugins import PluginManager
        from tools.registry import registry
        from pm.plugin_inputs import Selection,StagedUpdate

        with tempfile.TemporaryDirectory(prefix='chrome-install-fixture-') as directory:
            sandbox=Path(directory).resolve();home=sandbox/'home';home.mkdir()
            source=sandbox/'source';source.mkdir()
            # Reviewable source only. Never publish the working repository's Git
            # metadata, ignored reports, screenshots, profile data or old notes.
            for path in ROOT.iterdir():
                if path.is_file() and (path.suffix=='.py' or path.name in {
                        'browser_schema.json','vault_schema.json','plugin.yaml','README.md'}):
                    shutil.copy2(path,source/path.name)
            for folder in ('vendor','tests'):
                target=source/folder;target.mkdir()
                for path in (ROOT/folder).iterdir():
                    if path.is_file() and (path.suffix=='.py' or path.name.startswith('LICENSE')):
                        shutil.copy2(path,target/path.name)
            env=dict(os.environ,HERMES_HOME=str(home),HERMES_DISABLE_LAZY_INSTALLS='1',
                PYTHONDONTWRITEBYTECODE='1',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',
                GIT_ALLOW_PROTOCOL='file')
            def git(*args):
                return subprocess.run(['git','-C',str(source),'-c','core.hooksPath=/dev/null',
                    '-c','commit.gpgsign=false',*args],env=env,check=True,capture_output=True,text=True).stdout.strip()
            git('init','-q')
            git('add','--','.')
            git('-c','user.name=Installation Fixture','-c','user.email=fixture@example.invalid',
                'commit','-qm','Synthetic release snapshot')
            revision=git('rev-parse','HEAD')
            config_path=home/'config.yaml'
            config_path.write_text(yaml.safe_dump({'browser':{
                'cloud_provider':'original-chrome-default'},'plugins':{'enabled':[],'disabled':[],
                'entries':{'original-chrome-default':{'settings':{'expected_account':'fixture@example.invalid'}}}}}))
            output=io.StringIO();console=Console(file=output,force_terminal=False)
            publications=[]
            def publish_fixture(*,explicit=False,plugins=None,**kwargs):
                from pm.publication import validate_manifest
                self.assertTrue(explicit)
                row=dict(plugins.data);publications.append(type(plugins).__name__)
                if isinstance(plugins,StagedUpdate):
                    # Run PM's real declaration admission; only its environment
                    # solve and atomic publication are replaced by this fixture.
                    self.assertEqual(validate_manifest(Path(row['staged']))['name'],name)
                    target=Path(row['target']).resolve()
                    self.assertTrue(target.is_relative_to(home/'plugins'))
                    self.assertFalse(target.exists())
                    shutil.copytree(row['staged'],target)
                    commands._write_install_metadata(row['new_metadata'])
                elif isinstance(plugins,Selection):
                    self.assertEqual(Path(row['home']).resolve(),home)
                    for enabled in row['enabled']:
                        self.assertEqual(validate_manifest(home/'plugins'/enabled)['name'],enabled)
                    config=yaml.safe_load(config_path.read_text())
                    config.setdefault('plugins',{}).update(enabled=row['enabled'],disabled=row['disabled'])
                    config_path.write_text(yaml.safe_dump(config))
                else:
                    self.fail('Unexpected PM request '+type(plugins).__name__)
            def command(action,**kwargs):
                try:
                    commands.plugins_command(argparse.Namespace(plugins_action=action,**kwargs))
                except SystemExit as exc:
                    self.fail('Official '+action+' refused: '+str(exc)+'\n'+output.getvalue())
            def config():return yaml.safe_load(config_path.read_text())
            name='original-chrome-default';target=home/'plugins'/name
            token=set_hermes_home_override(home)
            manager=PluginManager(scope_key=str(home))
            try:
                with patch.dict(os.environ,env), \
                     patch.dict(sys.modules,hermes_bootstrap=types.ModuleType('hermes_bootstrap')), \
                     patch.object(socket.socket,'connect',side_effect=AssertionError('fixture refuses network')), \
                     patch('pm.client.sync_venv',side_effect=publish_fixture), \
                     patch('pm.workspace.enabled_plugin_dirs',return_value=[]), \
                     patch('hermes_cli.plugin_catalog.fetch_live_catalog',return_value=None), \
                     patch('hermes_cli.plugin_catalog.live_removed_list',return_value=[]), \
                     patch('hermes_cli.plugins_activation.reload_running_gateway',return_value=None), \
                     patch('hermes_cli.plugins_activation.report_activation'), \
                     patch('hermes_cli.plugins.get_plugin_manager',return_value=manager), \
                     patch.object(commands,'_console',return_value=console), \
                     patch.object(commands,'_is_tty',return_value=True), \
                     patch.object(commands,'_ask_yes',return_value=True):
                    command('install',identifier=source.as_uri(),ref=revision,no_deps=True,force=True)
                    self.assertTrue((target/'browser_schema.json').is_file())
                    self.assertFalse((target/'vault_adapter.py').exists())
                    record=commands._read_install_metadata()[name]
                    self.assertEqual(record['revision'],revision)
                    self.assertTrue(record['pinned'])
                    self.assertIn(source.as_uri(),record['source'])
                    self.assertNotIn(name,config()['plugins']['enabled'])
                    command('doctor',target=str(target),ci=True)
                    self.assertIn('OK: runtime discovery, manifest parsing, import, and registration passed',
                        output.getvalue())

                    baseline=lambda args,**kwargs:'{"success":true,"fixture_native":true}'
                    native_schema=json.loads((ROOT/'browser_schema.json').read_text())
                    registry.register('browser_exec','browser-use',native_schema,baseline,override=True,scope=str(home))
                    command('enable',name=name)
                    self.assertIn(name,config()['plugins']['enabled'])
                    self.assertIn('tools.override',config()['plugins']['entries'][name]['granted_capabilities'])
                    manager.discover_and_load(force=True)
                    loaded=manager._plugins[name]
                    self.assertTrue(loaded.enabled,loaded.error)
                    installed_handler=registry.get_entry('browser_exec',scope=str(home)).handler
                    self.assertIsNot(installed_handler,baseline)
                    self.assertTrue(installed_handler.__module__.startswith('hermes_plugins.'))

                    command('disable',name=name)
                    self.assertIn(name,config()['plugins']['disabled'])
                    self.assertEqual(config()['browser']['cloud_provider'],name)
                    manager.discover_and_load(force=True)
                    self.assertIs(registry.get_entry('browser_exec',scope=str(home)).handler,baseline)
                    self.assertTrue(target.exists())
                    self.assertIn(name,commands._read_install_metadata())

                    command('enable',name=name)
                    manager.discover_and_load(force=True)
                    self.assertIsNot(registry.get_entry('browser_exec',scope=str(home)).handler,baseline)
                    # Removal tests actual cleanup of grants/settings as well as
                    # the tracked tree and its installer-owned provenance record.
                    command('uninstall',name=name)
                    manager.discover_and_load(force=True)
                    self.assertFalse(target.exists())
                    self.assertNotIn(name,commands._read_install_metadata())
                    for key in ('enabled','disabled'):
                        self.assertNotIn(name,config()['plugins'].get(key,[]))
                    self.assertNotIn(name,config()['plugins'].get('entries',{}))
                    self.assertEqual(config()['browser']['cloud_provider'],name)
                    self.assertIs(registry.get_entry('browser_exec',scope=str(home)).handler,baseline)
                    self.assertEqual(publications,['StagedUpdate','Selection','Selection','Selection'])
            finally:
                with patch.dict(os.environ,env):manager.unload()
                reset_hermes_home_override(token)


if __name__=='__main__':
    unittest.main()
