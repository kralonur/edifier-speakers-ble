"""Readable metadata and advanced speaker status."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EdifierConfigEntry
from .entity import EdifierEntity

# The coordinator centralises updates, so reads never run in parallel.
PARALLEL_UPDATES = 0

_AUDIO_STATUS = {0: "Standard/unknown", 4: "Wireless Hi-Res UI status", 5: "Wired Hi-Res UI status", 9: "192 kHz UI status"}


async def async_setup_entry(hass: HomeAssistant, entry: EdifierConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    sensors = [
        EdifierStatusSensor(entry, "firmware", "Firmware"),
        EdifierStatusSensor(entry, "classic_address", "Classic Bluetooth address"),
        EdifierStatusSensor(entry, "audio_status", "Audio status"),
        EdifierStatusSensor(entry, "a2dp_status", "Bluetooth transport status"),
    ]
    async_add_entities(sensors)


class EdifierStatusSensor(EdifierEntity, SensorEntity):
    """Human-readable settings; audio codes are not negotiated codec metadata."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: EdifierConfigEntry, field: str, name: str) -> None:
        super().__init__(entry, field)
        self._field = field
        self._attr_name = name
        if self._field == "classic_address":
            self._attr_icon = "mdi:bluetooth"

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> str | None:
        if self._field == "firmware":
            return self.state_field("firmware") or self.coordinator.device.firmware
        value = self.state_field(self._field)
        if self._field == "audio_status" and value is not None:
            return _AUDIO_STATUS.get(value, f"Unknown status (0x{value:02X})")
        if self._field == "a2dp_status" and value is not None:
            if value == 3:
                return "Transport closed"
            if value == 13 and self.coordinator.device.model == "M60":
                return "Transport opened (may persist after playback stops)"
            return f"Unknown transport status (0x{value:02X})"
        return value
