"""Setup, unload and migration tests with Home Assistant's own services mocked."""

import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch


def _module(test: unittest.TestCase):
    try:
        return importlib.import_module("custom_components.edifier_ble")
    except ModuleNotFoundError as exc:
        if exc.name == "homeassistant":
            test.skipTest("Home Assistant is not installed")
        raise


def _entry(module, model: str = "M90", unique_id: str = "AA:BB:CC:22:33:55"):
    return SimpleNamespace(
        data={module.CONF_ADDRESS: unique_id, module.CONF_MODEL: model},
        unique_id=unique_id,
        entry_id="entry-1",
        title=f"Edifier {model}",
        async_on_unload=Mock(),
        async_create_background_task=Mock(),
        runtime_data=None,
    )


def _coordinator(device):
    return SimpleNamespace(
        device=device,
        async_refresh=Mock(),  # only handed to the mocked background task
        _async_bluetooth_callback=Mock(),
        _async_unavailable=Mock(),
    )


class SetupEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_creates_entities_without_waiting_for_the_speaker(self):
        module = _module(self)
        entry = _entry(module)
        device = SimpleNamespace(model=None, close=AsyncMock())
        coordinator = _coordinator(device)
        hass = SimpleNamespace(config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()))
        with (
            patch.object(module.bluetooth, "async_scanner_count", return_value=1),
            patch.object(module, "async_clear_stale_connections", AsyncMock()) as clear,
            patch.object(module, "make_device", return_value=device),
            patch.object(module, "EdifierCoordinator", return_value=coordinator),
            patch.object(module, "_migrate_entities") as migrate,
            patch.object(module.bluetooth, "async_register_callback", Mock(return_value=Mock())),
            patch.object(module.bluetooth, "async_track_unavailable", Mock(return_value=Mock())),
        ):
            self.assertTrue(await module.async_setup_entry(hass, entry))
        clear.assert_awaited_once_with(entry.data[module.CONF_ADDRESS])
        self.assertIs(entry.runtime_data, coordinator)
        self.assertEqual(device.model, "M90")  # the confirmed model is applied before any read
        migrate.assert_called_once_with(hass, entry)
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()
        self.assertEqual(entry.async_on_unload.call_count, 2)  # advertisement callback + availability
        entry.async_create_background_task.assert_called_once()  # the first read starts after setup

    async def test_setup_refuses_to_load_without_a_connectable_scanner(self):
        module = _module(self)
        with patch.object(module.bluetooth, "async_scanner_count", return_value=0):
            with self.assertRaises(module.ConfigEntryNotReady):
                await module.async_setup_entry(SimpleNamespace(), _entry(module))

    async def test_setup_closes_the_device_when_platforms_fail(self):
        module = _module(self)
        entry = _entry(module)
        device = SimpleNamespace(model=None, close=AsyncMock())
        coordinator = _coordinator(device)
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock(side_effect=RuntimeError("boom")))
        )
        with (
            patch.object(module.bluetooth, "async_scanner_count", return_value=1),
            patch.object(module, "async_clear_stale_connections", AsyncMock()),
            patch.object(module, "make_device", return_value=device),
            patch.object(module, "EdifierCoordinator", return_value=coordinator),
            patch.object(module, "_migrate_entities"),
            patch.object(module.bluetooth, "async_register_callback", Mock(return_value=Mock())),
            patch.object(module.bluetooth, "async_track_unavailable", Mock(return_value=Mock())),
            self.assertRaises(RuntimeError),
        ):
            await module.async_setup_entry(hass, entry)
        device.close.assert_awaited_once()
        entry.async_create_background_task.assert_not_called()

    async def test_unload_releases_the_device_only_when_platforms_unloaded(self):
        module = _module(self)
        device = SimpleNamespace(close=AsyncMock())
        entry = SimpleNamespace(runtime_data=SimpleNamespace(device=device))
        hass = SimpleNamespace(config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True)))
        self.assertTrue(await module.async_unload_entry(hass, entry))
        device.close.assert_awaited_once()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
        self.assertFalse(await module.async_unload_entry(hass, entry))


class MigrationTests(unittest.TestCase):
    def test_migration_removes_old_entities_and_reveals_disabled_ones(self):
        module = _module(self)
        registry = MagicMock()
        registry.async_get_entity_id.side_effect = lambda platform, domain, unique_id: f"{platform}.{unique_id}"
        registry.async_get.return_value = SimpleNamespace(
            config_entry_id="entry-1", disabled_by=module.er.RegistryEntryDisabler.INTEGRATION
        )
        entry = SimpleNamespace(
            entry_id="entry-1",
            unique_id="AA:BB",
            runtime_data=SimpleNamespace(device=SimpleNamespace(model="M90")),
        )
        with patch.object(module.er, "async_get", return_value=registry):
            module._migrate_entities(SimpleNamespace(), entry)
        # The codec sensor of an older release and the removed media player go away.
        registry.async_remove.assert_any_call("sensor.AA:BB_codec_preference")
        registry.async_remove.assert_any_call("media_player.AA:BB_speaker")
        self.assertEqual(registry.async_remove.call_count, 2)
        # Settings that used to be integration-disabled are revealed again.
        for platform, key in (("sensor", "audio_status"), ("text", "device_name"), ("select", "codec_preference")):
            registry.async_update_entity.assert_any_call(f"{platform}.AA:BB_{key}", disabled_by=None)
        self.assertEqual(registry.async_update_entity.call_count, 3)

    def test_migration_leaves_another_entrys_entities_alone(self):
        module = _module(self)
        registry = MagicMock()
        registry.async_get_entity_id.side_effect = lambda platform, domain, unique_id: f"{platform}.{unique_id}"
        registry.async_get.return_value = SimpleNamespace(
            config_entry_id="someone-else", disabled_by=module.er.RegistryEntryDisabler.INTEGRATION
        )
        entry = SimpleNamespace(
            entry_id="entry-1",
            unique_id="AA:BB",
            runtime_data=SimpleNamespace(device=SimpleNamespace(model="M60")),
        )
        with patch.object(module.er, "async_get", return_value=registry):
            module._migrate_entities(SimpleNamespace(), entry)
        registry.async_remove.assert_not_called()
        registry.async_update_entity.assert_not_called()


if __name__ == "__main__":
    unittest.main()
