"""Device on/off indicator and the BLE control-link indicator."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EdifierConfigEntry
from .entity import EdifierEntity

# The coordinator centralises updates, so reads never run in parallel.
PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: EdifierConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([EdifierOnlineSensor(entry), EdifierLinkSensor(entry)])


class EdifierOnlineSensor(EdifierEntity, BinarySensorEntity):
    """The single on/off signal for the speaker being reachable.

    Every other entity keeps its last known value while this is off, so one
    failed poll no longer rewrites the whole device at once.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: EdifierConfigEntry) -> None:
        super().__init__(entry, "online")
        self._attr_name = "Online"

    @property
    def available(self) -> bool:
        """Report off instead of disappearing, which is the point of the entity."""
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class EdifierLinkSensor(EdifierEntity, BinarySensorEntity):
    """On while Home Assistant deliberately holds the GATT link.

    Transient reads during a poll open and close the link within seconds and do
    not count, so this does not flap every poll interval.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: EdifierConfigEntry) -> None:
        super().__init__(entry, "link_connected")
        self._attr_name = "Bluetooth control link"

    @property
    def available(self) -> bool:
        """Always report the link state, even while the speaker is unreachable."""
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.device.is_link_held
