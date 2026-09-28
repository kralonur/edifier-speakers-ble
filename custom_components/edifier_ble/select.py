"""Verified EQ, lighting and output selections."""

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import EntityCategory

from . import EdifierConfigEntry
from .entity import EdifierEntity
from .protocol.device import CODEC_PREFS, PRESETS, SENSITIVITY, SOURCES, SUB_OUT, TIMERS

# One speaker, one BLE link: Home Assistant must not start two entity writes at once.
PARALLEL_UPDATES = 1


async def async_setup_entry(hass: HomeAssistant, entry: EdifierConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    model = entry.runtime_data.device.model_name
    fields = {
        "source": SOURCES[model],
        "eq": PRESETS[model],
    }
    if model == "M60":
        fields.update({
            "light_timeout": TIMERS,
            "light_sensitivity": SENSITIVITY,
            "codec_preference": CODEC_PREFS,
        })
    else:
        fields["sub_out"] = SUB_OUT
        fields["codec_preference"] = CODEC_PREFS
    async_add_entities(EdifierSelect(entry, field, list(options)) for field, options in fields.items())


class EdifierSelect(EdifierEntity, SelectEntity):
    """Read current selection from the shared speaker snapshot."""

    def __init__(self, entry: EdifierConfigEntry, field: str, options: list[str]) -> None:
        # The codec select carries a different name per model, so it needs its own
        # translated name while the unique-id suffix stays the same for both.
        model = entry.runtime_data.device.model
        translation_key = None
        if field == "codec_preference":
            translation_key = "codec_preference_ldac" if model == "M60" else "codec_preference_hd"
        super().__init__(entry, field, translation_key=translation_key)
        self._field = field
        self._attr_options = options
        if field == "codec_preference":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def current_option(self) -> str | None:
        value = self.state_field(self._field)
        return value if isinstance(value, str) else None

    @property
    def available(self) -> bool:
        return super().available and self.current_option is not None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_change(self._field, option)
