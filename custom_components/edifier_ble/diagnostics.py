"""Diagnostics support for the Edifier BLE integration."""

from dataclasses import asdict
import re
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothReachabilityIntent
from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from . import EdifierConfigEntry

_TO_REDACT = {"address", "classic_address", "device_name", "eq_profile_name", "title"}
_MAC_ADDRESS = re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b")


def _redact_text(value: str, names: tuple[str | None, ...]) -> str:
    """Remove device addresses and user-set names from free-form error text."""
    value = _MAC_ADDRESS.sub(REDACTED, value)
    for name in names:
        if name:
            value = value.replace(name, REDACTED)
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EdifierConfigEntry
) -> dict[str, Any]:
    """Return everything needed to explain the link state of one speaker."""
    coordinator = entry.runtime_data
    device = coordinator.device
    address = entry.data[CONF_ADDRESS]
    names = (entry.title, device.device_name, device.eq_profile_name)
    report = {
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
            "last_exception": _redact_text(repr(coordinator.last_exception), names) if coordinator.last_exception else None,
            "polling_disabled": entry.pref_disable_polling,
            "reachability": _redact_text(
                bluetooth.async_address_reachability_diagnostics(
                    hass, address, BluetoothReachabilityIntent.CONNECTION
                ), names
            ),
        },
        "snapshot": asdict(coordinator.data) if coordinator.data is not None else None,
    }
    return async_redact_data(report, _TO_REDACT)
