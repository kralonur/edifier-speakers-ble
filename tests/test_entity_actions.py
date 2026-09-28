"""Entity-level behaviour: state mapping, identity and the write paths."""

import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock


def _modules(test: unittest.TestCase):
    try:
        return {
            name: importlib.import_module(f"custom_components.edifier_ble.{name}")
            for name in ("sensor", "number", "select", "switch", "text", "protocol.device")
        }
    except ModuleNotFoundError as exc:
        if exc.name == "homeassistant":
            test.skipTest("Home Assistant is not installed")
        raise


def _entry(coordinator, unique_id: str | None = "AA:BB:CC:22:33:55"):
    return SimpleNamespace(runtime_data=coordinator, unique_id=unique_id, entry_id="entry-1")


def _coordinator(modules, data=None, model="M60"):
    return SimpleNamespace(
        device=SimpleNamespace(model=model, model_name=model, firmware="2.5.1"),
        data=data,
        last_update_success=True,
        async_change=AsyncMock(),
    )


class StatusSensorTests(unittest.TestCase):
    def test_speaker_codes_are_shown_as_words(self):
        modules = _modules(self)
        state = modules["protocol.device"].SpeakerState
        cases = [
            ("firmware", {"firmware": "2.5.1"}, "2.5.1"),
            ("classic_address", {"classic_address": "AA:BB:CC:22:33:44"}, "AA:BB:CC:22:33:44"),
            ("audio_status", {"audio_status": 4}, "Wireless Hi-Res UI status"),
            ("audio_status", {"audio_status": 0}, "Standard/unknown"),
            ("audio_status", {"audio_status": 99}, "Unknown status (0x63)"),
            ("a2dp_status", {"a2dp_status": 3}, "Transport closed"),
            ("a2dp_status", {"a2dp_status": 13}, "Transport opened (may persist after playback stops)"),
            ("a2dp_status", {"a2dp_status": 7}, "Unknown transport status (0x07)"),
        ]
        for field, overrides, expected in cases:
            for model in ("M60", "M90"):
                if field == "a2dp_status" and overrides.get("a2dp_status") == 13 and model != "M60":
                    continue  # the long transport message is M60-specific
                data = state(volume=5, source="Bluetooth", eq="Music", prompt_tone=True, **overrides)
                sensor = modules["sensor"].EdifierStatusSensor(
                    _entry(_coordinator(modules, data, model)), field, field)
                self.assertEqual(sensor.native_value, expected, f"{model} {field} {overrides}")

    def test_sensor_is_unavailable_until_the_first_read(self):
        modules = _modules(self)
        empty = _entry(_coordinator(modules, None))
        sensor = modules["sensor"].EdifierStatusSensor(empty, "classic_address", "Classic Bluetooth address")
        self.assertFalse(sensor.available)
        self.assertIsNone(sensor.native_value)
        # Firmware is the exception: it falls back to the model read when the entry was added.
        firmware = modules["sensor"].EdifierStatusSensor(empty, "firmware", "Firmware")
        self.assertEqual(firmware.native_value, "2.5.1")
        data = modules["protocol.device"].SpeakerState(volume=5, source="Bluetooth", eq="Music", prompt_tone=True,
                                                      classic_address="AA:BB:CC:22:33:44")
        sensor = modules["sensor"].EdifierStatusSensor(_entry(_coordinator(modules, data)), "classic_address", "Address")
        self.assertTrue(sensor.available)
        self.assertEqual(sensor.native_value, "AA:BB:CC:22:33:44")

    def test_entity_identity_and_device_info(self):
        modules = _modules(self)
        data = modules["protocol.device"].SpeakerState(volume=5, source="Bluetooth", eq="Music", prompt_tone=True)
        entry = _entry(_coordinator(modules, data, model="M90"), unique_id=None)  # hand-made entry
        sensor = modules["sensor"].EdifierStatusSensor(entry, "firmware", "Firmware")
        self.assertEqual(sensor._attr_unique_id, "entry-1_firmware")
        info = sensor.device_info
        self.assertEqual(info["identifiers"], {("edifier_ble", "entry-1")})
        self.assertEqual(info["model"], "M90")
        self.assertEqual(info["sw_version"], "2.5.1")
        self.assertEqual(info["name"], "Edifier M90")


class WritableEntityTests(unittest.IsolatedAsyncioTestCase):
    async def test_number_writes_are_forwarded(self):
        modules = _modules(self)
        coordinator = _coordinator(modules)
        entry = _entry(coordinator)
        await modules["number"].EdifierVolumeNumber(entry).async_set_native_value(12.7)
        coordinator.async_change.assert_awaited_with("volume", 12)
        await modules["number"].EdifierEqBand(entry, 3).async_set_native_value(1.5)
        coordinator.async_change.assert_awaited_with("eq_band_3", 1.5)

    async def test_select_switch_and_text_writes_are_forwarded(self):
        modules = _modules(self)
        coordinator = _coordinator(modules)
        entry = _entry(coordinator)
        select = modules["select"].EdifierSelect(entry, "source", "Source", ["Bluetooth", "USB"])
        await select.async_select_option("USB")
        coordinator.async_change.assert_awaited_with("source", "USB")
        switch = modules["switch"].EdifierSwitch(entry, "power_save", "Power save")
        await switch.async_turn_on()
        coordinator.async_change.assert_awaited_with("power_save", True)
        await switch.async_turn_off()
        coordinator.async_change.assert_awaited_with("power_save", False)
        await modules["text"].EdifierText(entry, "device_name", "Speaker name").async_set_value("Studio")
        coordinator.async_change.assert_awaited_with("device_name", "Studio")


if __name__ == "__main__":
    unittest.main()
