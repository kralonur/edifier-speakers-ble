"""Stateless playback actions for speakers without playback-state reporting."""

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EdifierConfigEntry
from .entity import EdifierEntity

# One speaker, one BLE link: Home Assistant must not start two entity writes at once.
PARALLEL_UPDATES = 1


async def async_setup_entry(hass: HomeAssistant, entry: EdifierConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    buttons = [
        EdifierPlaybackButton(entry, "play"),
        EdifierPlaybackButton(entry, "pause"),
        EdifierPlaybackButton(entry, "next"),
        EdifierPlaybackButton(entry, "previous"),
    ]
    buttons.append(EdifierDisruptiveButton(entry))
    buttons.append(EdifierLinkButton(entry, "connect"))
    buttons.append(EdifierLinkButton(entry, "disconnect"))
    async_add_entities(buttons)


class EdifierPlaybackButton(EdifierEntity, ButtonEntity):
    """Send a playback command without guessing what the source did."""

    def __init__(self, entry: EdifierConfigEntry, action: str) -> None:
        super().__init__(entry, action)
        self._action = action
        name_map = {
            "play": "Play",
            "pause": "Pause",
            "next": "Next track",
            "previous": "Previous track",
        }
        icon_map = {
            "play": "mdi:play",
            "pause": "mdi:pause",
            "next": "mdi:skip-next",
            "previous": "mdi:skip-previous",
        }
        self._attr_name = name_map.get(action, action.title())
        self._attr_icon = icon_map.get(action, f"mdi:{action}")

    async def async_press(self) -> None:
        await self.coordinator.async_playback_command(self._action)


class EdifierLinkButton(EdifierEntity, ButtonEntity):
    """Force-connect or force-disconnect the HA control link.

    Commands already hold the link for five minutes, so these exist to hold it
    indefinitely or to hand the speaker back to the Edifier app immediately.
    """

    def __init__(self, entry: EdifierConfigEntry, action: str) -> None:
        super().__init__(entry, f"link_{action}")
        self._action = action
        self._attr_name = "Force connect" if action == "connect" else "Force disconnect"
        self._attr_icon = "mdi:bluetooth-connect" if action == "connect" else "mdi:bluetooth-off"

    @property
    def available(self) -> bool:
        """Pressable even while the speaker is unreachable, unlike state entities."""
        return True

    async def async_press(self) -> None:
        await self.coordinator.async_link_command(self._action)


class EdifierDisruptiveButton(EdifierEntity, ButtonEntity):
    """Explicit user action which can sever a Bluetooth connection."""

    def __init__(self, entry: EdifierConfigEntry) -> None:
        model = entry.runtime_data.device.model
        super().__init__(entry, "power_off" if model == "M90" else "disconnect_audio")
        self._action = "power_off" if model == "M90" else "disconnect_audio"
        self._attr_name = "Power off speaker" if model == "M90" else "Disconnect Bluetooth audio"
        self._attr_icon = "mdi:power" if model == "M90" else "mdi:bluetooth-off"

    async def async_press(self) -> None:
        await self.coordinator.async_disruptive_command(self._action)
