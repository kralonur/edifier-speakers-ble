"""Verified prompt tone and M90 switches."""

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EdifierConfigEntry
from .entity import EdifierEntity

# One speaker, one BLE link: Home Assistant must not start two entity writes at once.
PARALLEL_UPDATES = 1


async def async_setup_entry(hass: HomeAssistant, entry: EdifierConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    fields = {"prompt_tone": "Bluetooth connection prompt tone"}
    if entry.runtime_data.device.model == "M90":
        fields.update({
            "multipoint": "Multipoint",
            "power_save": "Power save",
            "shutdown_timer": "15-minute shutdown timer",
        })
    async_add_entities(EdifierSwitch(entry, field, name) for field, name in fields.items())


class EdifierSwitch(EdifierEntity, SwitchEntity):
    """Switch with confirmed read-back."""

    def __init__(self, entry: EdifierConfigEntry, field: str, name: str) -> None:
        super().__init__(entry, field)
        self._field = field
        self._attr_name = name

    @property
    def is_on(self) -> bool | None:
        value = self.state_field(self._field)
        return bool(value) if value is not None else None

    @property
    def available(self) -> bool:
        return super().available and self.state_field(self._field) is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_change(self._field, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_change(self._field, False)
