"""Coordinator tests for speaker-initiated changes; require Home Assistant."""

import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock


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
        _module, _device, _created, _task, coordinator = _coordinator(self)
        coordinator.async_set_update_error = Mock()
        coordinator.last_update_success = False
        coordinator._async_unavailable(None)
        coordinator.async_set_update_error.assert_not_called()
        coordinator.last_update_success = True
        coordinator._async_unavailable(None)
        coordinator.async_set_update_error.assert_called_once()

    async def test_event_reread_swallows_failures(self):
        _module, _device, _created, _task, coordinator = _coordinator(self)
        coordinator.async_refresh = AsyncMock(side_effect=RuntimeError("speaker offline"))
        await coordinator._async_refresh_from_event()  # Must not raise into the BLE callback.


if __name__ == "__main__":
    unittest.main()
