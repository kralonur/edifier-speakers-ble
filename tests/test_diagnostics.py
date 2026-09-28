"""Diagnostics tests; require Home Assistant."""

import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


def _modules(test):
    try:
        diagnostics = importlib.import_module("custom_components.edifier_ble.diagnostics")
        device = importlib.import_module("custom_components.edifier_ble.protocol.device")
    except ModuleNotFoundError as exc:
        if exc.name == "homeassistant":
            test.skipTest("Home Assistant is not installed")
        raise
    return diagnostics, device


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_describes_link_identity_and_snapshot(self):
        diagnostics, device = _modules(self)
        state = device.SpeakerState(volume=12, source="Bluetooth", eq="Custom", prompt_tone=True)
        speaker = SimpleNamespace(
            model="M90",
            firmware="1.2.3",
            device_name=None,
            eq_profile_name="My EQ",
            classic_address="AA:BB:CC:22:33:44",
            is_connected=True,
            is_link_held=False,
        )
        coordinator = SimpleNamespace(
            device=speaker, last_update_success=False, last_exception=RuntimeError("boom"), data=state
        )
        entry = SimpleNamespace(
            title="Edifier M90",
            data={"address": "AA:BB:CC:22:33:55", "model": "M90"},
            options={},
            pref_disable_polling=True,
            runtime_data=coordinator,
        )
        with patch.object(diagnostics.bluetooth, "async_address_reachability_diagnostics", return_value="seen 3 s ago"):
            report = await diagnostics.async_get_config_entry_diagnostics(MagicMock(), entry)
        self.assertEqual(report["identity"]["classic_address"], "AA:BB:CC:22:33:44")
        self.assertEqual(report["link"], {"gatt_connected": True, "held_by_policy": False})
        self.assertFalse(report["update"]["last_update_success"])
        self.assertIn("boom", report["update"]["last_exception"])
        self.assertTrue(report["update"]["polling_disabled"])
        self.assertEqual(report["update"]["reachability"], "seen 3 s ago")
        self.assertEqual(report["snapshot"]["volume"], 12)

    async def test_report_survives_a_speaker_never_read(self):
        diagnostics, _device = _modules(self)
        speaker = SimpleNamespace(
            model="M60", firmware=None, device_name=None, eq_profile_name=None, classic_address=None,
            is_connected=False, is_link_held=False,
        )
        coordinator = SimpleNamespace(device=speaker, last_update_success=False, last_exception=None, data=None)
        entry = SimpleNamespace(
            title="Edifier M60", data={"address": "AA:BB:CC:11:22:44", "model": "M60"}, options={},
            pref_disable_polling=False, runtime_data=coordinator,
        )
        with patch.object(diagnostics.bluetooth, "async_address_reachability_diagnostics", return_value="unknown"):
            report = await diagnostics.async_get_config_entry_diagnostics(MagicMock(), entry)
        self.assertIsNone(report["snapshot"])
        self.assertIsNone(report["update"]["last_exception"])
        self.assertEqual(report["identity"]["firmware"], None)


if __name__ == "__main__":
    unittest.main()
