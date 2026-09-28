"""Edifier M60/M90 Bluetooth integration."""

from dataclasses import replace
import logging

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .bluetooth_device import async_clear_stale_connections, make_device
from .const import CONF_MODEL, DOMAIN, PLATFORMS
from .coordinator import EdifierCoordinator

_LOGGER = logging.getLogger(__name__)


type EdifierConfigEntry = ConfigEntry[EdifierCoordinator]


def _migrate_entities(hass: HomeAssistant, entry: EdifierConfigEntry) -> None:
    """Replace old codec sensor and reveal integration-disabled settings."""
    registry = er.async_get(hass)
    unique_id = entry.unique_id
    if entry.runtime_data.device.model == "M90":
        old_id = registry.async_get_entity_id("sensor", DOMAIN, f"{unique_id}_codec_preference")
        if old_id and (old := registry.async_get(old_id)) and old.config_entry_id == entry.entry_id:
            registry.async_remove(old_id)
    old_mp = registry.async_get_entity_id("media_player", DOMAIN, f"{unique_id}_speaker")
    if old_mp and (old := registry.async_get(old_mp)) and old.config_entry_id == entry.entry_id:
        registry.async_remove(old_mp)
    for platform, key in (("sensor", "audio_status"), ("text", "device_name"), ("select", "codec_preference")):
        entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{unique_id}_{key}")
        if entity_id and (record := registry.async_get(entity_id)) and record.config_entry_id == entry.entry_id and record.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
            registry.async_update_entity(entity_id, disabled_by=None)


async def async_setup_entry(hass: HomeAssistant, entry: EdifierConfigEntry) -> bool:
    """Set up even when the speaker is unreachable, so entities always exist.

    The first read runs in the background, so a sleeping speaker delays neither
    Home Assistant's start-up nor the creation of its entities; it leaves the
    settings unavailable and the Online sensor off until the normal poll or an
    advertisement picks the speaker up.
    """
    if not bluetooth.async_scanner_count(hass, connectable=True):
        raise ConfigEntryNotReady(
            "No connectable Bluetooth adapter or proxy can reach the Edifier speaker"
        )
    address = entry.data[CONF_ADDRESS]
    await async_clear_stale_connections(address)
    device = make_device(hass, address)
    # The model was confirmed over GATT when the entry was created, so entities can
    # be built before the speaker answers; _connect() still rejects a mismatch.
    device.model = entry.data[CONF_MODEL]
    coordinator = EdifierCoordinator(hass, entry, device)
    entry.runtime_data = coordinator
    try:
        entry.async_on_unload(
            bluetooth.async_register_callback(
                hass,
                coordinator._async_bluetooth_callback,
                BluetoothCallbackMatcher({"address": address}),
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )
        entry.async_on_unload(
            bluetooth.async_track_unavailable(hass, coordinator._async_unavailable, address, connectable=True)
        )
        _migrate_entities(hass, entry)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await device.close()
        raise
    # A mismatch is still rejected by _connect() on every connection attempt.
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), "edifier_ble initial refresh"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EdifierConfigEntry) -> bool:
    """Unload platforms, then release notifications and GATT resources."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.device.close()
    return True
