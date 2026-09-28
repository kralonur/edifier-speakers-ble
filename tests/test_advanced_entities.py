"""HA entity-shape tests; run on a Home Assistant installation."""

import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


class AdvancedEntityTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_specific_advanced_entities(self):
        try:
            modules = {
                platform: importlib.import_module(f"custom_components.edifier_ble.{platform}")
                for platform in ("binary_sensor", "number", "select", "sensor", "switch", "text")
            }
            state_type = importlib.import_module("custom_components.edifier_ble.protocol.device").SpeakerState
        except ModuleNotFoundError as exc:
            if exc.name == "homeassistant":
                self.skipTest("Home Assistant is not installed")
            raise
        for model in ("M60", "M90"):
            data = state_type(
                volume=5, source="Bluetooth", eq="Music" if model == "M60" else "Custom",
                prompt_tone=True, device_name=f"EDIFIER {model}", eq_gains=(0.0,) * (6 if model == "M60" else 9),
                codec_preference="44.1/48 kHz preference", shutdown_timer=15 if model == "M90" else None,
                eq_profile_name="Custom", a2dp_status=3, multipoint=True, power_save=False,
                sub_out="Low", audio_status=0, light_timeout="10 seconds", light_sensitivity="Low",
                firmware="2.5.1", classic_address="AA:BB:CC:22:33:44",
            )
            coordinator = SimpleNamespace(
                device=SimpleNamespace(model=model, model_name=model, firmware="2.5.1", is_connected=False, is_link_held=False),
                data=data, last_update_success=True, async_change=AsyncMock(),
            )
            entry = SimpleNamespace(runtime_data=coordinator, unique_id="test-speaker", entry_id="test-entry")
            entities = {}
            for platform, module in modules.items():
                created = []
                if platform == "number" and model == "M90":
                    registry = SimpleNamespace(
                        async_get_entity_id=Mock(side_effect=lambda domain, platform, uid: f"sensor.{uid}"),
                        async_get=Mock(return_value=SimpleNamespace(config_entry_id="test-entry")),
                        async_remove=Mock(),
                    )
                    with patch.object(module.er, "async_get", return_value=registry):
                        await module.async_setup_entry(None, entry, created.extend)
                    self.assertEqual(registry.async_remove.call_count, 8)
                else:
                    await module.async_setup_entry(None, entry, created.extend)
                entities[platform] = created
            self.assertEqual(len(entities["number"]), 7 if model == "M60" else 10)
            self.assertEqual(len(entities["select"]), 5 if model == "M60" else 4)
            self.assertEqual(len(entities["sensor"]), 4)
            self.assertEqual(len(entities["switch"]), 1 if model == "M60" else 4)
            self.assertEqual(entities["number"][0].name, "Volume")
            self.assertEqual(entities["number"][0].native_value, 5.0)
            self.assertEqual(entities["select"][0].name, "Source")
            self.assertEqual(entities["select"][0].current_option, "Bluetooth")
            self.assertEqual(entities["sensor"][1].name, "Classic Bluetooth address")
            self.assertEqual(entities["sensor"][1].native_value, "AA:BB:CC:22:33:44")
            self.assertEqual(entities["text"][0].native_value, f"EDIFIER {model}")
            self.assertEqual(entities["text"][1].native_value, "Custom")
            self.assertEqual([entity.name for entity in entities["binary_sensor"]], ["Online", "Bluetooth control link"])
            online, link = entities["binary_sensor"]
            self.assertEqual(online.unique_id, "test-speaker_online")
            self.assertTrue(online.is_on)
            self.assertFalse(link.is_on)
            coordinator.device.is_link_held = True
            self.assertTrue(link.is_on)
            coordinator.last_update_success = False
            self.assertFalse(online.is_on)
            self.assertTrue(online.available, "Online must report off, not disappear")
            self.assertTrue(link.available, "the link indicator must work while the speaker is unreachable")
            # The churn fix: settings keep their values instead of all going unavailable.
            for platform in ("number", "select", "switch", "text"):
                for entity in entities[platform]:
                    self.assertTrue(entity.available, f"{type(entity).__name__} ({entity.name}) must not flap on a failed poll")
            coordinator.data = None
            self.assertFalse(entities["select"][0].available, "unavailable only before the first successful read")
            coordinator.data = data
            coordinator.last_update_success = True
            coordinator.device.is_link_held = False
            self.assertEqual(entities["number"][1].native_value, 0.0)
            if model == "M90":
                self.assertEqual(entities["number"][-1].native_value, 0.0)
                self.assertEqual(entities["number"][-1].name, "Custom EQ 16000 Hz (app gain)")
                self.assertTrue(entities["switch"][-1].is_on)
                await entities["switch"][-1].async_turn_off()
                coordinator.async_change.assert_awaited_with("shutdown_timer", False)
            else:
                self.assertEqual(entities["select"][-1].current_option, "44.1/48 kHz preference")

    async def test_platforms_load_before_the_first_successful_read(self):
        """Entities must be addable while the speaker is unreachable (data is None)."""
        try:
            modules = {
                platform: importlib.import_module(f"custom_components.edifier_ble.{platform}")
                for platform in ("binary_sensor", "number", "select", "sensor", "switch", "text")
            }
        except ModuleNotFoundError as exc:
            if exc.name == "homeassistant":
                self.skipTest("Home Assistant is not installed")
            raise
        coordinator = SimpleNamespace(
            device=SimpleNamespace(model="M90", model_name="M90", firmware=None, is_connected=False, is_link_held=False),
            data=None, last_update_success=False, async_change=AsyncMock(),
        )
        entry = SimpleNamespace(runtime_data=coordinator, unique_id="test-speaker", entry_id="test-entry")
        for platform, module in modules.items():
            created = []
            if platform == "number":
                registry = SimpleNamespace(async_get_entity_id=Mock(return_value=None), async_get=Mock(return_value=None), async_remove=Mock())
                with patch.object(module.er, "async_get", return_value=registry):
                    await module.async_setup_entry(None, entry, created.extend)
            else:
                await module.async_setup_entry(None, entry, created.extend)
            for entity in created:
                # Reading state must not raise, and must not claim to be available.
                if platform not in ("binary_sensor",):
                    self.assertFalse(entity.available, f"{type(entity).__name__} must be unavailable with no data")
                entity.name, entity.unique_id
                getattr(entity, "native_value", None), getattr(entity, "is_on", None), getattr(entity, "current_option", None)


if __name__ == "__main__":
    unittest.main()
