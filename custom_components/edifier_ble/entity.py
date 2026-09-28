"""Common HA device metadata and action handling."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EdifierConfigEntry
from .const import DOMAIN
from .coordinator import EdifierCoordinator


class EdifierEntity(CoordinatorEntity[EdifierCoordinator]):
    """An entity attached to one physical speaker."""

    _attr_has_entity_name = True

    def __init__(self, entry: EdifierConfigEntry, key: str) -> None:
        super().__init__(entry.runtime_data)
        self._entry_unique_id = entry.unique_id
        self._attr_unique_id = f"{entry.unique_id}_{key}"

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

    def state_field(self, name: str, default=None):
        """Read one field from coordinator state, tolerating 'no data yet'."""
        data = self.coordinator.data
        return getattr(data, name, default) if data is not None else default
