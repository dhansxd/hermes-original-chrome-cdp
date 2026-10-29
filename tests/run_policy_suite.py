"""Run the phase-one fake-transport regression suite with the Hermes interpreter.

Usage: <Hermes environment python> tests/run_policy_suite.py
No dependency bootstrap, real GUI launch, live profile or network is required.
Live acceptance scripts are deliberately not discovered by this runner.
"""
import os
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULES = [
    'test_resource_watch', 'test_runtime_snapshot', 'test_provider_removal',
    'test_execution_policy', 'test_browser_actions', 'test_worker_policy',
    'test_worker', 'test_cdp_policy', 'test_binding', 'test_observer',
    'test_browser_finish', 'test_provider_policy', 'test_profile',
    'test_registration_capability', 'test_manifest', 'test_plugin_installation', 'test_lifecycle',
    'test_resilience', 'test_adapter', 'test_cdp_response_deadline',
    'test_cleanup_confirmation', 'test_cleanup_final_ownership',
    'test_repair', 'test_session_concurrency', 'test_event_overflow',
    'test_close_lifecycle', 'test_native_dialog',
    'test_status', 'test_selftest', 'test_vault_policy', 'test_browser_redaction', 'test_public_result',
    'test_operator_diagnostics', 'test_recovery', 'test_worker_progress', 'test_provider_recovery',
    'test_ownership_journal', 'test_observer_checkpoint', 'test_journal_provider', 'test_checkpoint_merge', 'test_gui_status',
    'test_browser_registration',
    'test_consent', 'test_consent_diagnostics', 'test_chrome_identity',
    'test_process_snapshots',
    'test_endpoint_readiness', 'test_pending_dialog', 'test_resume_setup',
    'test_idle_observer', 'test_cdp_peers', 'test_coexistence',
]


def main():
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT / 'tests'), str(ROOT), str(ROOT.parents[1] / 'hermes-agent')]
    # Some old tests import bootstrap just to set Python paths. It can perform
    # dependency installs, so never execute it in this isolated regression run.
    sys.modules['hermes_bootstrap'] = types.ModuleType('hermes_bootstrap')
    with tempfile.TemporaryDirectory(prefix='chrome-policy-tests-') as home:
        with patch.dict(os.environ, HERMES_HOME=home, HERMES_DISABLE_LAZY_INSTALLS='1',
                        PYTHONDONTWRITEBYTECODE='1'):
            with patch.object(socket.socket, 'connect', side_effect=AssertionError('offline suite refuses network')):
                with patch('plugin.gui_launch', side_effect=AssertionError('offline suite refuses real Chrome launch')):
                    discovered = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
                    def cases(suite):
                        for item in suite:
                            if isinstance(item, unittest.TestSuite):
                                yield from cases(item)
                            elif not item.id().endswith((
                                '.test_registration_failure_closes_completed_websocket_with_full_receiver_queue',
                                '.test_gui_launch_uses_its_own_snapshot_not_a_peer_info_dict',
                                '.test_idle_event_burst_does_not_starve_keepalive',
                                '.test_retained_connection_survives_tcp_dial_budget',
                                '.test_live_socket_is_epoch_scoped_and_removed_on_close',
                                '.test_receipt_pins_socket_descriptor_until_retired',
                                '.test_revoked_receipt_is_not_returned_after_socket_scan',
                            )):
                                # Separate tests exercise a loopback socket and
                                # the launcher (with its own subprocess stub).
                                # Neither can run under these global vetoes.
                                yield item
                    suite = unittest.TestSuite(cases(discovered))
                    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
