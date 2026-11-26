"""Shared, authoritative speaker state."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .protocol.device import EdifierDevice, SpeakerState
from .protocol.frames import CommandNotApplied

_LOGGER = logging.getLogger(__name__)

# A speaker that has been silent for this long is worth a repair card: it is off,
# out of range, or advertising a different address after a re-pair.
UNREACHABLE_REPAIR_AFTER = timedelta(hours=24)
# Polls only connect while the speaker advertises. Failed connects to an
# advertising speaker back off by doubling, up to the maximum.
POLL_INTERVAL = timedelta(minutes=2)
MAX_POLL_INTERVAL = timedelta(minutes=30)


class EdifierCoordinator(DataUpdateCoordinator[SpeakerState]):
    """One periodic state read and one serialized client per speaker."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: EdifierDevice) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name="Edifier BLE", update_interval=POLL_INTERVAL)
        self.device = device
        self._address: str = entry.data[CONF_ADDRESS]
        self._failed_connects = 0
        # Set when a read was skipped or the speaker went away: the next
        # advertisement then triggers one read instead of waiting for the timer.
        self._read_on_advertisement = False
        self._entry_title = entry.title
        self._unreachable_since: datetime | None = None
        self._repair_issue_id = f"unreachable_{entry.entry_id}"
        self._event_task: asyncio.Task[None] | None = None
        device.event_callback = self._handle_device_event
        device.link_callback = self.async_update_listeners

    def _handle_device_event(self) -> None:
        """Re-read state right away instead of waiting for the next poll.

        Called from the BLE notification callback, so it only schedules work.
        """
        if self._event_task is not None and not self._event_task.done():
            return
        self._event_task = self.hass.async_create_task(self._async_refresh_from_event())

    @callback
    def _async_bluetooth_callback(self, service_info: object, _change: object) -> None:
        """Cache the freshest BLEDevice object from an advertisement.

        A speaker that comes back is read once right away. Later advertisements
        never trigger a read: an unreachable speaker that keeps advertising
        would otherwise cause a connect attempt per advertisement.
        """
        self.device.set_ble_device(getattr(service_info, "device", None))
        if not self._read_on_advertisement:
            return
        if self.config_entry is not None and self.config_entry.pref_disable_polling:
            return
        self._read_on_advertisement = False
        self._handle_device_event()

    @callback
    def _async_unavailable(self, _service_info: object) -> None:
        """Home Assistant stopped seeing the speaker, so report it offline."""
        # A connected speaker normally stops advertising; the GATT link is
        # stronger evidence of reachability than the advertisement timer.
        if self.device.is_connected:
            return
        # The cached BLEDevice is stale now; connecting with it would only time out.
        self.device.set_ble_device(None)
        self._read_on_advertisement = True
        if self.last_update_success:
            self.async_set_update_error(UpdateFailed("Speaker is no longer advertising"))

    async def _async_refresh_from_event(self) -> None:
        try:
            await self.async_refresh()
        except Exception as exc:  # a failed refresh must not kill the callback
            _LOGGER.debug("Refresh after a speaker-initiated change failed: %s", exc)

    async def _async_update_data(self) -> SpeakerState:
        # A held link answers even though a connected speaker stops advertising.
        if not self.device.is_connected and not bluetooth.async_address_present(
            self.hass, self._address, connectable=True
        ):
            # Not advertising means off or out of range: skip the connect entirely.
            self._read_on_advertisement = True
            self._async_note_unreachable()
            raise UpdateFailed("Speaker is not advertising")
        try:
            state = await self.device.read_state()
        except Exception as exc:
            self._failed_connects += 1
            self.update_interval = min(POLL_INTERVAL * 2**self._failed_connects, MAX_POLL_INTERVAL)
            self._async_note_unreachable()
            raise UpdateFailed(f"Unable to read Edifier speaker: {exc}") from exc
        self._failed_connects = 0
        self.update_interval = POLL_INTERVAL
        self._async_clear_unreachable()
        return state

    @callback
    def _async_note_unreachable(self) -> None:
        """Raise a repair card once the speaker has been silent for a day.

        Driven by polls on purpose: someone who turned polling off asked Home
        Assistant not to watch the speaker.
        """
        now = dt_util.utcnow()
        if self._unreachable_since is None:
            self._unreachable_since = now
        if now - self._unreachable_since < UNREACHABLE_REPAIR_AFTER:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._repair_issue_id,
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.WARNING,
            translation_key="speaker_unreachable",
            translation_placeholders={"name": self._entry_title},
        )

    @callback
    def _async_clear_unreachable(self) -> None:
        """The speaker answered: forget the outage and withdraw the repair card."""
        self._unreachable_since = None
        ir.async_delete_issue(self.hass, DOMAIN, self._repair_issue_id)

    async def async_link_command(self, action: str) -> None:
        """Force the BLE control link open (pinned, with a fresh read) or release it now."""
        try:
            if action == "connect":
                await self.device.connect_now()
            elif action == "disconnect":
                await self.device.disconnect_now()
                return
            else:
                raise ValueError("Unsupported link action")
        except Exception as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="link_command_failed",
                translation_placeholders={"action": action, "error": str(exc)},
            ) from exc
        # Pinning the link is most useful when polling is disabled, so read once.
        await self.async_refresh()

    async def async_disruptive_command(self, action: str) -> None:
        """Send an explicit disconnect/shutdown without assuming an ACK."""
        try:
            if action == "power_off":
                await self.device.power_off()
            elif action == "disconnect_audio":
                await self.device.disconnect_audio()
            else:
                raise ValueError("Unsupported speaker action")
        except Exception as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="disruptive_command_failed",
                translation_placeholders={"action": action, "error": str(exc)},
            ) from exc
        await self.async_request_refresh()

    async def async_playback_command(self, action: str) -> None:
        """Report BLE write failures, without claiming the source acted on them."""
        try:
            await self.device.playback_command(action)
        except Exception as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="playback_command_failed",
                translation_placeholders={"action": action, "error": str(exc)},
            ) from exc

    async def async_change(self, field: str, value: object) -> None:
        try:
            changes = await self.device.change(field, value)
        except CommandNotApplied as exc:
            # A mismatch is still an authoritative observation: refresh the state.
            await self.async_request_refresh()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="change_not_applied",
                translation_placeholders={"error": str(exc)},
            ) from exc
        except Exception as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="change_failed",
                translation_placeholders={"field": field, "error": str(exc)},
            ) from exc
        if not self.last_update_success:
            await self.async_request_refresh()
        else:
            self.async_set_updated_data(replace(self.data, **changes))
