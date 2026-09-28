"""Tests for HA-provided adapter selection and reachability messages."""

import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

class ReachabilityTests(unittest.IsolatedAsyncioTestCase):
    def test_unreachable_speaker_reports_ha_diagnostics(self):
        try:
            module = importlib.import_module("custom_components.edifier_ble.bluetooth_device")
            protocol_error = importlib.import_module("custom_components.edifier_ble.protocol.frames").ProtocolError
        except ModuleNotFoundError as exc:
            if exc.name in ("homeassistant", "bleak_retry_connector"):
                self.skipTest("Home Assistant is not installed")
            raise
        hass = SimpleNamespace()
        with patch.object(module.bluetooth, "async_ble_device_from_address", return_value=None), \
             patch.object(module.bluetooth, "async_address_reachability_diagnostics", return_value="no scanner currently has it") as diagnostics:
            device = module.make_device(hass, "AA:BB:CC:11:22:33".upper())
            with self.assertRaises(protocol_error) as caught:
                device._ble_device()
            self.assertIn("no scanner currently has it", str(caught.exception))
            self.assertEqual(diagnostics.call_count, 1)

    def test_reachable_speaker_uses_ha_device(self):
        try:
            module = importlib.import_module("custom_components.edifier_ble.bluetooth_device")
            protocol_error = importlib.import_module("custom_components.edifier_ble.protocol.frames").ProtocolError
        except ModuleNotFoundError as exc:
            if exc.name in ("homeassistant", "bleak_retry_connector"):
                self.skipTest("Home Assistant is not installed")
            raise
        ble = object()
        with patch.object(module.bluetooth, "async_ble_device_from_address", return_value=ble):
            device = module.make_device(SimpleNamespace(), "AA:BB:CC:11:22:33".upper())
            self.assertIs(device._ble_device(), ble)

    async def test_connection_re_resolves_the_device_on_each_retry(self):
        try:
            module = importlib.import_module("custom_components.edifier_ble.bluetooth_device")
        except ModuleNotFoundError as exc:
            if exc.name in ("homeassistant", "bleak_retry_connector"):
                self.skipTest("Home Assistant is not installed")
            raise
        calls = {}

        async def fake_establish(client_class, device, name, disconnected_callback=None, **kwargs):
            calls["kwargs"] = kwargs
            calls["device"] = device
            return SimpleNamespace()

        ble = object()
        with patch.object(module, "establish_connection", side_effect=fake_establish), \
             patch.object(module.bluetooth, "async_ble_device_from_address", return_value=ble) as resolver:
            device = module.make_device(SimpleNamespace(), "AA:BB:CC:DD:EE:FF")
            await device._connector(ble, lambda client: None)  # the connector, not full GATT setup
            self.assertIn("ble_device_callback", calls["kwargs"])
            # An M60 needs about half a minute to complete a connection, so the attempt
            # budget must be long enough that it is not cancelled on the way in.
            self.assertEqual(calls["kwargs"]["timeout"], module.CONNECT_TIMEOUT_SECONDS)
            self.assertEqual(calls["kwargs"]["max_attempts"], module.CONNECT_ATTEMPTS)
            self.assertGreaterEqual(module.CONNECT_TIMEOUT_SECONDS, 30)
            self.assertIs(calls["device"], ble)
            # The retry connector re-resolves via HA instead of reusing a stale path.
            self.assertIs(calls["kwargs"]["ble_device_callback"](), ble)
            self.assertEqual(resolver.call_count, 1)

    async def test_setup_clears_stale_connections(self):
        try:
            module = importlib.import_module("custom_components.edifier_ble.bluetooth_device")
        except ModuleNotFoundError as exc:
            if exc.name in ("homeassistant", "bleak_retry_connector"):
                self.skipTest("Home Assistant is not installed")
            raise
        with patch.object(module, "close_stale_connections_by_address", new=AsyncMock()) as closer:
            await module.async_clear_stale_connections("AA:BB:CC:DD:EE:FF")
        closer.assert_awaited_once_with("AA:BB:CC:DD:EE:FF")


if __name__ == "__main__":
    unittest.main()
