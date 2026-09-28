"""Verified EQ, lighting and output selections."""

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory

from . import EdifierConfigEntry
from .entity import EdifierEntity
from .protocol.device import CODEC_PREFS, PRESETS, SENSITIVITY, SOURCES, SUB_OUT, TIMERS


async def async_setup_entry(hass: HomeAssistant, entry: EdifierConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    model = entry.runtime_data.device.model
    fields = {
        "source": ("Source", SOURCES[model]),
        "eq": ("EQ", PRESETS[model]),
    }
    if model == "M60":
        fields.update({
            "light_timeout": ("Smart light timeout", TIMERS),
            "light_sensitivity": ("Smart light sensitivity", SENSITIVITY),
            "codec_preference": ("LDAC preference", CODEC_PREFS),
        })
    else:
        fields["sub_out"] = ("Sub Out", SUB_OUT)
        fields["codec_preference"] = ("HD codec preference (experimental)", CODEC_PREFS)
    async_add_entities(EdifierSelect(entry, field, label, list(options)) for field, (label, options) in fields.items())


class EdifierSelect(EdifierEntity, SelectEntity):
    """Read current selection from the shared speaker snapshot."""

    def __init__(self, entry: EdifierConfigEntry, field: str, name: str, options: list[str]) -> None:
        super().__init__(entry, field)
        self._field = field
        self._attr_name = name
        self._attr_options = options
        if field == "codec_preference":
            self._attr_entity_category = EntityCategory.CONFIG
        elif field == "source":
            self._attr_icon = "mdi:audio-input-rca"

    @property
    def current_option(self) -> str | None:
        return self.state_field(self._field)

    @property
    def available(self) -> bool:
        return super().available and self.current_option is not None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_change(self._field, option)
