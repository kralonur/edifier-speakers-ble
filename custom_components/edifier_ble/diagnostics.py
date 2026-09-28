"""Diagnostics support for the Edifier BLE integration.

Nothing is redacted: this integration holds no credentials, and the Bluetooth
addresses plus the values read back from the speaker are exactly what makes a
report useful.
"""

from dataclasses import asdict
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothReachabilityIntent
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from . import EdifierConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EdifierConfigEntry
) -> dict[str, Any]:
    """Return everything needed to explain the link state of one speaker."""
    coordinator = entry.runtime_data
    device = coordinator.device
    address = entry.data[CONF_ADDRESS]
    return {
        "entry": {"title": entry.title, "data": dict(entry.data), "options": dict(entry.options)},
        "identity": {
            "model": device.model,
            "firmware": device.firmware,
            "device_name": device.device_name,
            "eq_profile_name": device.eq_profile_name,
            "classic_address": device.classic_address,
        },
        "link": {
            "gatt_connected": device.is_connected,
            "held_by_policy": device.is_link_held,
        },
        "update": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception) if coordinator.last_exception else None,
            "polling_disabled": entry.pref_disable_polling,
            "reachability": bluetooth.async_address_reachability_diagnostics(
                hass, address, BluetoothReachabilityIntent.CONNECTION
            ),
        },
        "snapshot": asdict(coordinator.data) if coordinator.data is not None else None,
    }
