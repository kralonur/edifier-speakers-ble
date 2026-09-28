"""Speaker firmware name and custom EQ profile name."""

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EdifierConfigEntry
from .entity import EdifierEntity


async def async_setup_entry(hass: HomeAssistant, entry: EdifierConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([
        EdifierText(entry, "device_name", "Speaker firmware name"),
        EdifierText(entry, "eq_profile_name", "Custom EQ profile name"),
    ])


class EdifierText(EdifierEntity, TextEntity):
    """Editable stored names; neither changes HA's Device Registry label."""

    _attr_native_min = 1
    _attr_native_max = 35
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: EdifierConfigEntry, field: str, name: str) -> None:
        super().__init__(entry, field)
        self._field = field
        self._attr_name = name

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> str | None:
        return self.state_field(self._field)

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.async_change(self._field, value)
