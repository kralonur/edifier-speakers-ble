"""Writable custom EQ bands with per-band read-back verification."""

from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EdifierConfigEntry
from .const import DOMAIN
from .entity import EdifierEntity
from .protocol.device import EQ_FREQUENCIES


async def async_setup_entry(hass: HomeAssistant, entry: EdifierConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    model = entry.runtime_data.device.model
    if model == "M90":
        # Replace the eight read-only sensors created by older releases.
        registry = er.async_get(hass)
        for index in range(1, 9):
            old_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.unique_id}_eq_band_{index}")
            if old_id and (old_entry := registry.async_get(old_id)) and old_entry.config_entry_id == entry.entry_id:
                registry.async_remove(old_id)
    entities: list[NumberEntity] = [EdifierVolumeNumber(entry)]
    entities.extend(EdifierEqBand(entry, index) for index in range(len(EQ_FREQUENCIES[model])))
    async_add_entities(entities)


class EdifierEqBand(EdifierEntity, NumberEntity):
    """App EQ gain scale; not an acoustic measurement."""

    _attr_native_unit_of_measurement = "dB"
    _attr_native_step = 0.5
    _attr_icon = "mdi:equalizer"

    def __init__(self, entry: EdifierConfigEntry, index: int) -> None:
        super().__init__(entry, f"eq_band_{index}")
        self._index = index
        model = self.coordinator.device.model
        frequency = EQ_FREQUENCIES[model][index]
        self._attr_name = f"Custom EQ {frequency} Hz (app gain)"
        self._attr_native_min_value = -3.0
        self._attr_native_max_value = 3.0

    @property
    def available(self) -> bool:
        gains = self.state_field("eq_gains")
        return super().available and gains is not None

    @property
    def native_value(self) -> float | None:
        gains = self.state_field("eq_gains")
        return gains[self._index] if gains is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_change(f"eq_band_{self._index}", value)


class EdifierVolumeNumber(EdifierEntity, NumberEntity):
    """Direct discrete volume slider (0–50 for M90, 0–16 for M60)."""

    _attr_native_step = 1.0
    _attr_icon = "mdi:volume-high"

    def __init__(self, entry: EdifierConfigEntry) -> None:
        super().__init__(entry, "volume")
        model = self.coordinator.device.model
        self._attr_name = "Volume"
        self._attr_native_min_value = 0.0
        self._attr_native_max_value = 50.0 if model == "M90" else 16.0

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        val = self.state_field("volume")
        return float(val) if val is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_change("volume", int(value))
