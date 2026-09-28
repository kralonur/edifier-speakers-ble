"""Common HA device metadata and action handling."""

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EdifierConfigEntry
from .const import DOMAIN
from .coordinator import EdifierCoordinator


class EdifierEntity(CoordinatorEntity[EdifierCoordinator]):
    """An entity attached to one physical speaker."""

    _attr_has_entity_name = True

    def __init__(self, entry: EdifierConfigEntry, key: str, translation_key: str | None = None) -> None:
        super().__init__(entry.runtime_data)
        unique_id = entry.unique_id
        if unique_id is None:
            # The config flow always sets one; a hand-made entry still gets an identity.
            unique_id = entry.entry_id
        self._entry_unique_id = unique_id
        self._attr_unique_id = f"{unique_id}_{key}"
        # Names, and the icons in icons.json, come from strings.json rather than from
        # _attr_name. The key matches the unique-id suffix except where one platform
        # reuses a name across models.
        self._attr_translation_key = translation_key or key

    @property
    def device_info(self) -> DeviceInfo:
        device = self.coordinator.device
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_unique_id)},
            name=f"Edifier {device.model}",
            manufacturer="Edifier",
            model=device.model,
            sw_version=device.firmware,
        )

    @property
    def available(self) -> bool:
        """Keep the last known values instead of flapping on every failed poll.

        The device-level `online` binary sensor carries the on/off signal, so an
        unreachable speaker no longer rewrites every setting at once.
        """
        return self.coordinator.data is not None

    def state_field(self, name: str, default: Any = None) -> Any:
        """Read one field from coordinator state, tolerating 'no data yet'."""
        data = self.coordinator.data
        return getattr(data, name, default) if data is not None else default
