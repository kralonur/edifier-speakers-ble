"""Coordinator tests for speaker-initiated changes; require Home Assistant."""

import importlib
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch


def _coordinator(test):
    try:
        module = importlib.import_module("custom_components.edifier_ble.coordinator")
    except ModuleNotFoundError as exc:
        if exc.name == "homeassistant":
            test.skipTest("Home Assistant is not installed")
        raise
    created = []
    task = Mock()
    task.done.return_value = False

    def async_create_task(coro):
        coro.close()
        created.append(coro)
        return task

    hass = MagicMock()
    hass.async_create_task = async_create_task
    device = MagicMock()
    return module, device, created, task, module.EdifierCoordinator(hass, MagicMock(), device)


class DeviceEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_speaker_initiated_change_schedules_one_reread(self):
        _module, device, created, task, coordinator = _coordinator(self)
        self.assertEqual(device.event_callback, coordinator._handle_device_event)
        coordinator.async_refresh = AsyncMock()
        coordinator._handle_device_event()
        self.assertEqual(len(created), 1)
        coordinator._handle_device_event()  # A read is already pending: no second one.
        self.assertEqual(len(created), 1)
        task.done.return_value = True
        coordinator._handle_device_event()
        self.assertEqual(len(created), 2)

    async def test_bluetooth_advertisement_only_refreshes_the_device_object(self):
        """Advertising must not trigger a connect attempt per advertisement."""
        _module, device, created, _task, coordinator = _coordinator(self)
        coordinator.data = None
        coordinator.last_update_success = False
        service_info = SimpleNamespace(device="fresh-device")
        coordinator._async_bluetooth_callback(service_info, None)
        device.set_ble_device.assert_called_once_with("fresh-device")
        self.assertEqual(created, [], "an advertisement must not schedule a state read")

    async def test_unavailable_callback_marks_offline_only_when_online(self):
        _module, device, _created, _task, coordinator = _coordinator(self)
        coordinator.async_set_update_error = Mock()
        device.is_connected = False
        coordinator.last_update_success = False
        coordinator._async_unavailable(None)
        coordinator.async_set_update_error.assert_not_called()
        coordinator.last_update_success = True
        device.is_connected = True
        coordinator._async_unavailable(None)  # connected devices stop advertising
        coordinator.async_set_update_error.assert_not_called()
        device.is_connected = False
        coordinator._async_unavailable(None)
        coordinator.async_set_update_error.assert_called_once()

    async def test_event_reread_swallows_failures(self):
        _module, _device, _created, _task, coordinator = _coordinator(self)
        coordinator.async_refresh = AsyncMock(side_effect=RuntimeError("speaker offline"))
        await coordinator._async_refresh_from_event()  # Must not raise into the BLE callback.


class CoordinatorCommandTests(unittest.IsolatedAsyncioTestCase):
    """Every coordinator command path, including how failures are reported."""

    def prepare(self):
        module, device, _created, _task, coordinator = _coordinator(self)
        for name in ("read_state", "connect_now", "disconnect_now", "power_off", "disconnect_audio", "playback_command", "change"):
            setattr(device, name, AsyncMock())
        coordinator.async_refresh = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()
        coordinator.async_set_updated_data = Mock()
        coordinator.data = module.SpeakerState(volume=5, source="Bluetooth", eq="Music", prompt_tone=True)
        coordinator.last_update_success = True
        return module, device, coordinator

    async def test_a_failed_read_becomes_update_failed(self):
        module, device, coordinator = self.prepare()
        device.read_state.return_value = "snapshot"
        self.assertEqual(await coordinator._async_update_data(), "snapshot")
        device.read_state.side_effect = OSError("asleep")
        with self.assertRaises(module.UpdateFailed):
            await coordinator._async_update_data()

    async def test_link_commands_pin_release_and_report_failures(self):
        module, device, coordinator = self.prepare()
        await coordinator.async_link_command("connect")
        device.connect_now.assert_awaited_once()
        coordinator.async_refresh.assert_awaited_once()  # pinning is useful with polling off
        await coordinator.async_link_command("disconnect")
        device.disconnect_now.assert_awaited_once()
        device.connect_now.side_effect = OSError("offline")
        with self.assertRaises(module.HomeAssistantError) as failure:
            await coordinator.async_link_command("connect")
        self.assertEqual(failure.exception.translation_key, "link_command_failed")
        self.assertEqual(failure.exception.translation_placeholders["action"], "connect")
        with self.assertRaises(module.HomeAssistantError):
            await coordinator.async_link_command("nonsense")

    async def test_disruptive_commands_report_failures(self):
        module, device, coordinator = self.prepare()
        await coordinator.async_disruptive_command("power_off")
        await coordinator.async_disruptive_command("disconnect_audio")
        device.power_off.assert_awaited_once()
        device.disconnect_audio.assert_awaited_once()
        self.assertEqual(coordinator.async_request_refresh.await_count, 2)
        device.power_off.side_effect = OSError("offline")
        with self.assertRaises(module.HomeAssistantError) as failure:
            await coordinator.async_disruptive_command("power_off")
        self.assertEqual(failure.exception.translation_key, "disruptive_command_failed")
        with self.assertRaises(module.HomeAssistantError):
            await coordinator.async_disruptive_command("nonsense")

    async def test_playback_failures_are_reported(self):
        module, device, coordinator = self.prepare()
        await coordinator.async_playback_command("play")
        device.playback_command.assert_awaited_once_with("play")
        device.playback_command.side_effect = OSError("offline")
        with self.assertRaises(module.HomeAssistantError) as failure:
            await coordinator.async_playback_command("play")
        self.assertEqual(failure.exception.translation_key, "playback_command_failed")

    async def test_change_publishes_verified_values_and_handles_failures(self):
        module, device, coordinator = self.prepare()
        device.change.return_value = {"volume": 7}
        await coordinator.async_change("volume", 7)
        published = coordinator.async_set_updated_data.call_args.args[0]
        self.assertEqual(published.volume, 7)
        self.assertEqual(published.source, "Bluetooth")  # untouched fields survive the update
        coordinator.async_request_refresh.assert_not_awaited()

        device.change.side_effect = module.CommandNotApplied("volume: requested 9")
        with self.assertRaises(module.HomeAssistantError) as failure:
            await coordinator.async_change("volume", 9)
        self.assertEqual(failure.exception.translation_key, "change_not_applied")
        coordinator.async_request_refresh.assert_awaited_once()  # a mismatch is re-read

        coordinator.async_request_refresh.reset_mock()
        device.change.side_effect = OSError("offline")
        with self.assertRaises(module.HomeAssistantError) as failure:
            await coordinator.async_change("volume", 9)
        self.assertEqual(failure.exception.translation_key, "change_failed")
        self.assertEqual(failure.exception.translation_placeholders["field"], "volume")
        coordinator.async_request_refresh.assert_not_awaited()

    async def test_change_refreshes_instead_of_publishing_stale_data(self):
        module, device, coordinator = self.prepare()
        coordinator.last_update_success = False
        device.change.return_value = {"volume": 11}
        await coordinator.async_change("volume", 11)
        coordinator.async_request_refresh.assert_awaited_once()
        coordinator.async_set_updated_data.assert_not_called()

    async def test_a_full_day_of_silence_raises_and_withdraws_a_repair_issue(self):
        module, device, coordinator = self.prepare()
        device.read_state.side_effect = OSError("asleep")
        with (
            patch.object(module.ir, "async_create_issue") as create,
            patch.object(module.ir, "async_delete_issue") as delete,
            patch.object(module.dt_util, "utcnow") as clock,
        ):
            clock.return_value = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
            with self.assertRaises(module.UpdateFailed):
                await coordinator._async_update_data()
            create.assert_not_called()  # one failed poll is not an outage

            clock.return_value = datetime(2026, 9, 29, 11, 0, tzinfo=UTC)
            with self.assertRaises(module.UpdateFailed):
                await coordinator._async_update_data()
            create.assert_not_called()  # still inside the first day

            clock.return_value = datetime(2026, 9, 29, 13, 0, tzinfo=UTC)
            with self.assertRaises(module.UpdateFailed):
                await coordinator._async_update_data()
            create.assert_called_once()
            self.assertEqual(create.call_args.kwargs["translation_key"], "speaker_unreachable")
            self.assertFalse(create.call_args.kwargs["is_fixable"])

            device.read_state.side_effect = None
            device.read_state.return_value = coordinator.data
            await coordinator._async_update_data()
            delete.assert_called_once()  # answering again withdraws the card
            self.assertIsNone(coordinator._unreachable_since)

    async def test_a_healthy_poll_never_raises_an_issue(self):
        module, _device, coordinator = self.prepare()
        with patch.object(module.ir, "async_create_issue") as create, \
                patch.object(module.ir, "async_delete_issue"):
            await coordinator._async_update_data()
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
