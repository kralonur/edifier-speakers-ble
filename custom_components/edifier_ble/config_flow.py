"""Bluetooth discovery and UI configuration for Edifier speakers."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS

from .bluetooth_device import make_device
from .const import CONF_MODEL, DOMAIN
from .protocol.frames import UnsupportedDevice

_LOGGER = logging.getLogger(__name__)


# ConneX service UUIDs, from the app profiles for each model.
EDIFIER_SERVICE_UUIDS = {
    "0000f600-0000-1000-8000-00805f9b34fb",  # M60
    "00004503-0000-1000-8000-00805f9b34fb",  # M90
}


def _is_edifier(info: BluetoothServiceInfoBleak) -> bool:
    """Match by name or by service UUID: the M60 often advertises without a name."""
    name = info.name or ""
    if name.upper().startswith("EDIFIER"):
        return True
    return bool(EDIFIER_SERVICE_UUIDS.intersection(service.lower() for service in (info.service_uuids or [])))


class EdifierConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Only GATT-confirmed M60/M90 devices can create entries."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._model: str | None = None

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        self._address = discovery_info.address
        await self.async_set_unique_id(self._address.upper())
        self._abort_if_unique_id_configured()
        return self.async_show_form(step_id="bluetooth_confirm")

    async def async_step_bluetooth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="bluetooth_confirm")
        assert self._address is not None  # set by async_step_bluetooth before this step
        device = make_device(self.hass, self._address)
        try:
            self._model = await device.identify()
        except UnsupportedDevice as exc:
            _LOGGER.debug("Edifier candidate did not identify: %s", exc)
            return self.async_abort(reason="not_supported")
        except Exception as exc:
            _LOGGER.debug("Could not connect to Edifier candidate: %s", exc)
            return self.async_show_form(step_id="bluetooth_confirm", errors={"base": "cannot_connect"})
        finally:
            await device.close()
        return self.async_create_entry(
            title=f"Edifier {self._model}",
            data={CONF_ADDRESS: self._address, CONF_MODEL: self._model},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Offer only Edifier-named advertisements; the model is still confirmed over GATT."""
        candidates = {
            info.address: info
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True)
            if _is_edifier(info)
        }
        if not candidates:
            return self.async_abort(reason="no_devices_found")
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address not in candidates:
                return self.async_abort(reason="no_devices_found")
            return await self.async_step_bluetooth(candidates[address])
        options = {
            address: f"{info.name or 'EDIFIER BLE'} ({address})"
            for address, info in sorted(candidates.items(), key=lambda item: (item[1].name or "", item[0]))
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(options)}),
        )
