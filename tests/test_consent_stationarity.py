"""Dialog geometry controls the pre-action wait independently of global mouse input."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import consent
from consent_fakes import exact_sheet
from test_consent_diagnostics import fake_clock

class StationarityTests(unittest.TestCase):
    def backend(self):
        ax,sheet,_=exact_sheet();backend=consent.MacConsent('/fixture',5000)
        backend.ax=ax;backend.scan=Mock(return_value=[sheet]);backend.hosts=Mock(return_value={42})
        backend.correlate=Mock(return_value=True)
        return backend,ax,sheet

    def test_resize_near_old_deadline_waits_again_before_sole_click(self):
        backend,ax,sheet=self.backend()
        with fake_clock() as now:
            backend.trace=ax.trace=consent.ConsentTrace()
            ax.geometry_state=lambda _: (1000 if now[0]<10.8 else 1200,700)
            ax.mouse_down=lambda:False
            times=[];ax.ax.AXUIElementPerformAction.side_effect=lambda *args:times.append(now[0]) or 0
            backend.press(sheet,pending=lambda:True)
        self.assertEqual(len(times),1)
        self.assertGreaterEqual(times[0],11.8)

    def test_global_mouse_hold_does_not_exhaust_pending_handshake(self):
        backend,ax,sheet=self.backend();backend.deadline=12
        with fake_clock() as now:
            ax.geometry_state=lambda _:(1000,700)
            ax.mouse_down=Mock(return_value=True)
            times=[];ax.ax.AXUIElementPerformAction.side_effect=lambda *args:times.append(now[0]) or 0
            backend.press(sheet,pending=lambda:now[0]<backend.deadline)
        self.assertEqual(len(times),1)
        self.assertAlmostEqual(times[0],11)
        ax.mouse_down.assert_not_called()

    def test_global_mouse_change_before_action_does_not_cancel_exact_button(self):
        backend,ax,sheet=self.backend()
        held=[False]
        ax.mouse_down=Mock(side_effect=lambda:held[0])
        def rescan():
            held[0]=True
            return [sheet]
        backend.scan=Mock(side_effect=rescan)
        with fake_clock():backend.press(sheet,pending=lambda:True)
        ax.ax.AXUIElementPerformAction.assert_called_once()
        ax.mouse_down.assert_not_called()

    def test_continuous_resize_never_clicks_or_extends_handshake_budget(self):
        backend,ax,sheet=self.backend();backend.deadline=11.5
        with fake_clock() as now:
            ax.geometry_state=lambda _:(round(now[0],4),700)
            ax.mouse_down=lambda:False
            with self.assertRaisesRegex(consent.ConsentError,'phase=settling'):
                backend.press(sheet,pending=lambda:True)
            self.assertAlmostEqual(now[0],11.5)
        ax.ax.AXUIElementPerformAction.assert_not_called()

    def test_geometry_change_in_final_preaction_check_sends_no_click(self):
        backend,ax,sheet=self.backend();changed=[False]
        ax.geometry_state=lambda _:(1200 if changed[0] else 1000,700)
        ax.mouse_down=lambda:False
        def rescan():
            changed[0]=True
            return [sheet]
        backend.scan=Mock(side_effect=rescan)
        with fake_clock(),self.assertRaisesRegex(consent.ConsentError,'geometry_changed_before_press'):
            backend.press(sheet,pending=lambda:True)
        ax.ax.AXUIElementPerformAction.assert_not_called()
