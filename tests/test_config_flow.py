"""HA config-flow regression tests; require Home Assistant to be installed."""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


def _config_flow_module(test: unittest.TestCase):
    try:
        return importlib.import_module("custom_components.edifier_ble.config_flow")
    except ModuleNotFoundError as exc:
        if exc.name == "homeassistant":
            test.skipTest("Home Assistant is not installed")
        raise


def _matchers() -> list[dict]:
    manifest = json.loads((Path(__file__).parent.parent / "custom_components/edifier_ble/manifest.json").read_text())
    return manifest["bluetooth"]


def _service_info(name: str | None, address: str = "AA:BB:CC:11:22:33", service_uuids: list[str] | None = None):
    return SimpleNamespace(
        address=address, name=name, connectable=True, service_uuids=service_uuids or [], service_data={}, manufacturer_data={},
        advertisement=SimpleNamespace(local_name=name),
    )


class ManifestDiscoveryTests(unittest.TestCase):
    """The M60 advertises its model name, not `EDIFIER BLE`."""

    def test_manifest_declares_bluetooth_adapters_dependency(self):
        """HA docs: integrations using an adapter must depend on bluetooth_adapters."""
        manifest = json.loads((Path(__file__).parent.parent / "custom_components/edifier_ble/manifest.json").read_text())
        self.assertIn("bluetooth_adapters", manifest["dependencies"])

    def test_manifest_matchers_cover_observed_edifier_names(self):
        _config_flow_module(self)  # loads the package only when Home Assistant is present
        from homeassistant.components.bluetooth.match import ble_device_matches
        for name in ("EDIFIER BLE", "EDIFIER M60", "EDIFIER M90", "Edifier M60"):
            matched = any(ble_device_matches(matcher, _service_info(name)) for matcher in _matchers())
            self.assertTrue(matched, f"manifest matchers must accept {name!r}")
        for name in ("Xiaomi Tag", "Oclean Se", ""):
            matched = any(ble_device_matches(matcher, _service_info(name)) for matcher in _matchers())
            self.assertFalse(matched, f"manifest matchers must reject {name!r}")

    def test_manifest_matchers_accept_edifier_service_uuids(self):
        """The M60 advertises without a name, so discovery must match its ConneX UUID."""
        _config_flow_module(self)
        from homeassistant.components.bluetooth.match import ble_device_matches
        for uuid in ("0000f600-0000-1000-8000-00805f9b34fb", "00004503-0000-1000-8000-00805f9b34fb"):
            info = _service_info("", address="AA:BB:CC:11:22:44", service_uuids=[uuid])
            self.assertTrue(any(ble_device_matches(matcher, info) for matcher in _matchers()),
                            f"manifest matchers must accept {uuid}")


class ConfigFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_does_not_connect_until_confirmation(self):
        try:
            module = importlib.import_module("custom_components.edifier_ble.config_flow")
        except ModuleNotFoundError as exc:
            if exc.name == "homeassistant":
                self.skipTest("Home Assistant is not installed")
            raise
        flow = module.EdifierConfigFlow()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = Mock()
        flow.async_show_form = Mock(return_value={"type": "form", "step_id": "bluetooth_confirm"})
        flow.async_create_entry = Mock(return_value={"type": "create_entry"})
        with patch.object(module, "make_device", side_effect=AssertionError("Discovery must not connect")):
            result = await flow.async_step_bluetooth(SimpleNamespace(address="TEST-ADDRESS", name="EDIFIER BLE"))
        self.assertEqual(result["step_id"], "bluetooth_confirm")
        flow.async_set_unique_id.assert_awaited_once_with("TEST-ADDRESS")

        offline = SimpleNamespace(identify=AsyncMock(side_effect=OSError("offline")), close=AsyncMock())
        with patch.object(module, "make_device", return_value=offline):
            await flow.async_step_bluetooth_confirm({})
        flow.async_show_form.assert_called_with(step_id="bluetooth_confirm", errors={"base": "cannot_connect"})
        offline.close.assert_awaited_once()

        online = SimpleNamespace(identify=AsyncMock(return_value="M90"), close=AsyncMock())
        with patch.object(module, "make_device", return_value=online):
            await flow.async_step_bluetooth_confirm({})
        flow.async_create_entry.assert_called_once_with(title="Edifier M90", data={"address": "TEST-ADDRESS", "model": "M90"})
        online.close.assert_awaited_once()

    async def test_user_step_lists_only_edifier_devices(self):
        module = _config_flow_module(self)
        flow = module.EdifierConfigFlow()
        flow.hass = SimpleNamespace()
        flow.async_step_bluetooth = AsyncMock(return_value={"type": "form", "step_id": "bluetooth_confirm"})
        speaker = _service_info("EDIFIER M60")
        other = _service_info("Xiaomi Tag", address="AA:BB:CC:33:44:55")
        unnamed = _service_info("", address="AA:BB:CC:33:44:66")
        with patch.object(module.bluetooth, "async_discovered_service_info", return_value=[other, unnamed, speaker]):
            result = await flow.async_step_user(None)
            self.assertEqual(result["step_id"], "user")
            options = next(iter(result["data_schema"].schema.values())).container
            self.assertEqual(list(options), ["AA:BB:CC:11:22:33"])
            self.assertEqual(options["AA:BB:CC:11:22:33"], "EDIFIER M60 (AA:BB:CC:11:22:33)")
            await flow.async_step_user({"address": "AA:BB:CC:11:22:33"})
        flow.async_step_bluetooth.assert_awaited_once_with(speaker)

    async def test_user_step_aborts_when_nothing_is_discovered(self):
        module = _config_flow_module(self)
        flow = module.EdifierConfigFlow()
        flow.hass = SimpleNamespace()
        with patch.object(module.bluetooth, "async_discovered_service_info", return_value=[]):
            result = await flow.async_step_user(None)
        self.assertEqual(result["reason"], "no_devices_found")

    async def test_user_step_lists_nameless_speaker_by_service_uuid(self):
        """The M60 often advertises name-less; it must still appear in the add list."""
        module = _config_flow_module(self)
        flow = module.EdifierConfigFlow()
        flow.hass = SimpleNamespace()
        flow.async_step_bluetooth = AsyncMock(return_value={"type": "form", "step_id": "bluetooth_confirm"})
        nameless = _service_info("", address="AA:BB:CC:11:22:44", service_uuids=["0000f600-0000-1000-8000-00805f9b34fb"])
        with patch.object(module.bluetooth, "async_discovered_service_info", return_value=[nameless]):
            result = await flow.async_step_user(None)
            options = next(iter(result["data_schema"].schema.values())).container
            self.assertEqual(list(options), ["AA:BB:CC:11:22:44"])
            self.assertEqual(options["AA:BB:CC:11:22:44"], "EDIFIER BLE (AA:BB:CC:11:22:44)")

    async def test_user_step_aborts_when_only_other_devices_are_nearby(self):
        module = _config_flow_module(self)
        flow = module.EdifierConfigFlow()
        flow.hass = SimpleNamespace()
        others = [_service_info("Xiaomi Tag", address="AA:BB:CC:33:44:55"), _service_info(None, address="AA:BB:CC:33:44:66")]
        with patch.object(module.bluetooth, "async_discovered_service_info", return_value=others):
            result = await flow.async_step_user(None)
        self.assertEqual(result["reason"], "no_devices_found")


class SetupTests(unittest.TestCase):
    """Setup must not wait for the speaker: HA creates the entities first."""

    def test_setup_starts_the_first_read_in_the_background(self):
        source = (Path(__file__).parent.parent / "custom_components/edifier_ble/__init__.py").read_text()
        setup = source[source.index("async def async_setup_entry"):source.index("async def async_unload_entry")]
        self.assertNotIn("await coordinator.async_refresh()", setup,
                         "the first read must not block Home Assistant's start-up")
        self.assertIn("async_create_background_task", setup, "the first read must still happen")
        self.assertLess(setup.index("entry.runtime_data = coordinator"),
                        setup.index("async_forward_entry_setups"),
                        "platforms need runtime_data before they are set up")


if __name__ == "__main__":
    unittest.main()
