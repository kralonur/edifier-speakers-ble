"""Speaker firmware name and custom EQ profile name."""

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EdifierConfigEntry
from .entity import EdifierEntity

# One speaker, one BLE link: Home Assistant must not start two entity writes at once.
PARALLEL_UPDATES = 1


async def async_setup_entry(hass: HomeAssistant, entry: EdifierConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([EdifierText(entry, "device_name"), EdifierText(entry, "eq_profile_name")])


class EdifierText(EdifierEntity, TextEntity):
    """Editable stored names; neither changes HA's Device Registry label."""

    _attr_native_min = 1
    _attr_native_max = 35
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: EdifierConfigEntry, field: str) -> None:
        super().__init__(entry, field)
        self._field = field

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> str | None:
        value = self.state_field(self._field)
        return value if isinstance(value, str) else None

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.async_change(self._field, value)
