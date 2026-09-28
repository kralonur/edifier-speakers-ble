"""One serialized BLE connection and model-specific controls."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    # Typing only: the protocol layer is tested without bleak installed.
    from bleak import BleakClient
    from bleak.backends.device import BLEDevice

from .frames import CommandNotApplied, Frame, ProtocolError, UnsupportedDevice, build_frame, parse_frame

NOTIFY_UUID = "48090001-1a48-11e9-ab14-d663bd873d93"
WRITE_UUID = "48090002-1a48-11e9-ab14-d663bd873d93"
RESPONSE_TIMEOUT = 5
# A user command keeps the GATT link open this long; each new command renews it.
# Shorter than the led_ble library's 120 s; HA core gardena_bluetooth uses 5 s.
SESSION_IDLE_SECONDS = 60
SERVICES = {
    "M60": "4809f601-1a48-11e9-ab14-d663bd873d93",
    "M90": "48094503-1a48-11e9-ab14-d663bd873d93",
}
SOURCES = {
    "M60": {"Bluetooth": 1, "USB": 2, "AUX": 3},
    "M90": {"Bluetooth": 1, "USB": 2, "HDMI": 3, "Optical": 4, "AUX": 5},
}
PRESETS = {
    "M60": {"Music": 0, "Monitor": 1, "Game": 2, "Movie": 3, "Customized": 4},
    "M90": {"Classic": 0, "Monitor": 1, "Dynamic": 2, "Custom": 3},
}
TIMERS = {"5 seconds": 0, "10 seconds": 1, "20 seconds": 2, "Always on": 3}
SENSITIVITY = {"High": 0, "General": 1, "Low": 2}
SUB_OUT = {"Low": 0, "Medium": 1, "High": 2}
CODEC_PREFS = {"Default (LDAC disabled)": 0, "44.1/48 kHz preference": 1, "96 kHz preference": 2}
EQ_FREQUENCIES = {
    "M60": (62, 250, 1000, 4000, 8000, 16000),
    "M90": (62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000),
}
_LOGGER = logging.getLogger(__name__)
PLAYBACK_ACTIONS = {"play": 0x00, "pause": 0x01, "next": 0x04, "previous": 0x05}


@dataclass(frozen=True, slots=True)
class SpeakerState:
    volume: int
    source: str
    eq: str
    prompt_tone: bool
    light_timeout: str | None = None
    light_sensitivity: str | None = None
    sub_out: str | None = None
    multipoint: bool | None = None
    power_save: bool | None = None
    device_name: str | None = None
    codec_preference: str | None = None
    audio_status: int | None = None
    eq_gains: tuple[float, ...] | None = None
    shutdown_timer: int | None = None
    eq_profile_name: str | None = None
    a2dp_status: int | None = None
    firmware: str | None = None
    classic_address: str | None = None


def _decode(mapping: dict[str, int], value: int) -> str:
    try:
        return next(key for key, code in mapping.items() if code == value)
    except StopIteration as exc:
        raise ProtocolError(f"Unknown speaker setting: {value}") from exc


class EdifierDevice:
    """Connection ownership, notification matching and model-specific operations.

    The connector is supplied by HA (or a mock) and receives a BLEDevice and a
    disconnected callback; the BLEDevice supplier is called again on reconnect.
    """

    def __init__(
        self,
        ble_device: Callable[[], BLEDevice | None],
        connector: Callable[[BLEDevice, Callable[[object], None]], Awaitable[BleakClient]],
    ) -> None:
        self._ble_device = ble_device
        self._connector = connector
        self._client: BleakClient | None = None
        self._pending: tuple[int, int, set[int], asyncio.Future[Frame]] | None = None
        self._lock = asyncio.Lock()
        self._idle_task: asyncio.Task[None] | None = None
        self._pinned = False
        # Set by the coordinator: the speaker announced something changed.
        self.event_callback: Callable[[], None] | None = None
        # Set by the coordinator: the BLE control link opened or closed.
        self.link_callback: Callable[[], None] | None = None
        self._link_reported = False
        self.model: str | None = None
        self.firmware: str | None = None
        self.device_name: str | None = None
        self.eq_profile_name: str | None = None
        self.classic_address: str | None = None
        # Handed over by Home Assistant from an advertisement; a device that only
        # advertises briefly must be connected to with this exact object.
        self._advertisement_device: BLEDevice | None = None
        self._closed = False

    def set_ble_device(self, device: BLEDevice | None) -> None:
        """Remember the BLEDevice object Home Assistant just delivered."""
        self._advertisement_device = device

    @asynccontextmanager
    async def _session(self, *, hold: bool = False) -> AsyncIterator[None]:
        """Run one operation; `hold` marks a user command that keeps the link open."""
        async with self._lock:
            opened_here = self._client is None
            if hold:
                self._cancel_idle()
            try:
                await self._connect()
                yield
            finally:
                if hold:
                    self._schedule_idle()
                elif opened_here and not self._pinned:
                    # Background read: do not leave a link the user did not ask for.
                    await self._disconnect()

    def _cancel_idle(self) -> None:
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

    def _schedule_idle(self) -> None:
        """Close the link after the idle window, unless a force-connect pins it."""
        self._cancel_idle()
        if self._pinned or self._client is None:
            return
        self._idle_task = asyncio.create_task(self._idle_disconnect(SESSION_IDLE_SECONDS))
        self._notify_link()

    async def _idle_disconnect(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        async with self._lock:
            self._idle_task = None
            if self._pinned or self._closed:
                return
            await self._disconnect()

    async def connect_now(self) -> None:
        """Force-connect and pin the link until `disconnect_now`."""
        async with self._lock:
            self._cancel_idle()
            await self._connect()
            self._pinned = True
            self._notify_link()

    async def disconnect_now(self) -> None:
        """Release the link immediately, including a force-connected one."""
        async with self._lock:
            self._cancel_idle()
            self._pinned = False
            await self._disconnect()

    async def identify(self) -> str:
        async with self._session():
            assert self.model is not None
            return self.model

    @property
    def model_name(self) -> str:
        """The GATT-confirmed model; every frame layout and option map depends on it."""
        if self.model is None:
            raise ProtocolError("Speaker model is not known yet")
        return self.model

    @property
    def is_connected(self) -> bool:
        """True while a live GATT link is held, so commands will not pay a connect."""
        return self._client is not None and bool(self._client.is_connected)

    @property
    def is_link_held(self) -> bool:
        """True while Home Assistant deliberately holds the link.

        Transient reads during a poll open and close the link within seconds;
        only a pinned link or the command window counts as held, so the indicator
        does not flap on every poll.
        """
        return self.is_connected and (self._pinned or self._idle_task is not None)

    def _notify_link(self) -> None:
        held = self.is_link_held
        if held == self._link_reported:
            return
        self._link_reported = held
        if self.link_callback is not None:
            self.link_callback()

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None and client.is_connected:
            await client.disconnect()
        self._notify_link()

    async def _connect(self) -> BleakClient:
        if self._closed:
            raise ProtocolError("Speaker client is closed")
        if self._client is not None and self._client.is_connected:
            return self._client
        device = self._advertisement_device or self._ble_device()
        if device is None:
            raise ProtocolError("Speaker is not reachable by a connectable Bluetooth adapter")
        client = await self._connector(device, self._disconnected)
        try:
            models = [model for model, uuid in SERVICES.items() if client.services.get_service(uuid)]
            if len(models) != 1 or not client.services.get_characteristic(NOTIFY_UUID) or not client.services.get_characteristic(WRITE_UUID):
                raise UnsupportedDevice("Unsupported Edifier GATT profile")
            if self.model is not None and self.model != models[0]:
                raise ProtocolError("Speaker model changed at this Bluetooth address")
            self.model = models[0]
            await client.start_notify(NOTIFY_UUID, self._notification)
        except BaseException:
            await client.disconnect()
            raise
        self._client = client
        self._notify_link()
        return client

    def _disconnected(self, _client: object) -> None:
        if _client is not self._client:
            return
        self._client = None
        self._notify_link()
        if self._pending is not None:
            future = self._pending[3]
            if not future.done():
                future.set_exception(ProtocolError("Speaker disconnected"))
                # The request itself can fail first (a write error while the link goes
                # down), leaving this future awaited by nobody. Retrieve the exception
                # now: the waiter still raises it, and the event loop stops reporting
                # "Future exception was never retrieved" when it is collected.
                future.exception()

    def _notification(self, _sender: object, data: bytearray) -> None:
        try:
            frame = parse_frame(bytes(data))
        except ProtocolError:
            return
        if self._pending is not None:
            app, opcode, kinds, future = self._pending
            if frame.app == app and frame.opcode == opcode and frame.kind in kinds and not future.done():
                future.set_result(frame)
                return
        # Unsolicited frame: the speaker changed something itself, for example
        # because the 2.4 GHz RF remote was used. Payloads of these pushes are
        # not documented, so re-read authoritative state instead of guessing.
        if self.event_callback is not None:
            self.event_callback()

    async def _request(self, opcode: int, payload: bytes = b"", *, app: int = 0xEC, ack: bool = False) -> bytes:
        client = await self._connect()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Frame] = loop.create_future()
        self._pending = (app, opcode, {0xBB, 0xCC} if ack else {0xBB}, future)
        try:
            await client.write_gatt_char(WRITE_UUID, build_frame(opcode, payload, app))
            frame = await asyncio.wait_for(future, RESPONSE_TIMEOUT)
            if ack and frame.payload and frame.payload[0] == 0 and frame.kind == 0xCC:
                raise ProtocolError("Speaker rejected command")
            return frame.payload
        finally:
            self._pending = None

    async def _query(self, opcode: int, *, app: int = 0xEC) -> bytes:
        return await self._request(opcode, app=app)

    async def _set(self, opcode: int, payload: bytes, *, app: int = 0xEC) -> None:
        await self._request(opcode, payload, app=app, ack=True)

    async def _volume(self) -> int:
        data = await self._query(0x66)
        expected = 16 if self.model == "M60" else 50
        if len(data) != 2 or data[0] != expected or data[1] > expected:
            raise ProtocolError("Unexpected volume response")
        return data[1]

    async def _source(self) -> str:
        data = await self._query(0x61)
        group = 0x0F if self.model == "M60" else 0x1D
        if len(data) != 2 or data[0] != group:
            raise ProtocolError("Unexpected source response")
        return _decode(SOURCES[self.model_name], data[1])

    async def _eq(self) -> str:
        data = await self._query(0xD5)
        if len(data) != 1:
            raise ProtocolError("Unexpected EQ response")
        return _decode(PRESETS[self.model_name], data[0])

    async def _tone(self) -> bool:
        data = await self._query(0x86)
        if len(data) != 2 or data[0] != 2 or data[1] not in (0, 1):
            raise ProtocolError("Unexpected prompt tone response")
        return bool(data[1])

    async def _light(self) -> tuple[str, str]:
        data = await self._query(0x84)
        if len(data) != 3 or data[0] != 3:
            raise ProtocolError("Unexpected smart light response")
        return _decode(TIMERS, data[1]), _decode(SENSITIVITY, data[2])

    async def _sub_out(self) -> str:
        data = await self._query(0x13, app=0xED)
        if len(data) != 2 or data[0] != 0:
            raise ProtocolError("Unexpected Sub Out response")
        return _decode(SUB_OUT, data[1])

    async def _boolean(self, opcode: int, *, indexed: bool = False) -> bool:
        data = await self._query(opcode)
        if indexed:
            if len(data) != 2 or data[0] != 0:
                raise ProtocolError("Unexpected indexed setting response")
            value = data[1]
        else:
            if len(data) != 1:
                raise ProtocolError("Unexpected setting response")
            value = data[0]
        if value not in (0, 1):
            raise ProtocolError("Unexpected boolean setting")
        return bool(value)

    async def _codec_preference(self) -> str:
        data = await self._query(0x48 if self.model == "M60" else 0x91)
        if self.model == "M90":
            if len(data) != 2 or data[0] != 0x0E:
                raise ProtocolError("Unexpected M90 codec preference response")
            code = data[1]
        else:
            if len(data) != 1:
                raise ProtocolError("Unexpected M60 LDAC preference response")
            code = data[0]
        return _decode(CODEC_PREFS, code)

    async def _a2dp_status(self) -> int:
        data = await self._query(0xC3)
        if len(data) != 1:
            raise ProtocolError("Unexpected Bluetooth transport response")
        return data[0]

    async def _audio_status(self) -> int:
        data = await self._query(0x68)
        if len(data) != 1:
            raise ProtocolError("Unexpected audio status response")
        return data[0]

    async def _eq_records(self) -> tuple[bytes, ...]:
        data = await self._query(0x43)
        frequencies = EQ_FREQUENCIES[self.model_name]
        size = 6 if self.model == "M60" else 4
        fmt = 3 if self.model == "M60" else 0x10
        minimum = 2 + len(frequencies) * size + (4 if self.model == "M90" else 0)
        if len(data) < minimum or data[:2] != bytes((fmt, len(frequencies))):
            raise ProtocolError("Unexpected custom EQ response")
        records = tuple(data[2 + index * size:2 + (index + 1) * size] for index in range(len(frequencies)))
        for index, (record, frequency) in enumerate(zip(records, frequencies)):
            offset = 2 if self.model == "M60" else 1
            if record[0] != index or int.from_bytes(record[offset:offset + 2], "big") != frequency:
                raise ProtocolError("Unexpected custom EQ band record")
        return records

    async def _eq_gains(self) -> tuple[float, ...]:
        records = await self._eq_records()
        offset = 4 if self.model == "M60" else 3
        return tuple((record[offset] - 6) * 0.5 for record in records)

    async def _shutdown_timer(self) -> int:
        data = await self._query(0xD3)
        if len(data) != 2:
            raise ProtocolError("Unexpected shutdown timer response")
        return int.from_bytes(data, "big")

    _T = TypeVar("_T")

    async def _optional(self, reader: Callable[[], Awaitable[_T]], label: str) -> _T | None:
        try:
            return await reader()
        except Exception as exc:
            _LOGGER.debug("Unable to read optional %s: %s", label, exc)
            return None

    async def read_state(self) -> SpeakerState:
        async with self._session():
            volume = await self._volume()
            source = await self._source()
            eq = await self._eq()
            tone = await self._tone()
            if self.firmware is None:
                self.firmware = await self._optional(self._firmware, "speaker firmware")
            if self.device_name is None:
                self.device_name = await self._optional(self._device_name, "speaker name")
            if self.eq_profile_name is None:
                self.eq_profile_name = await self._optional(self._eq_profile_name, "custom EQ profile name")
            if self.classic_address is None:
                self.classic_address = await self._optional(self._classic_address, "classic Bluetooth address")
            codec = await self._optional(self._codec_preference, "codec preference")
            audio = await self._optional(self._audio_status, "audio status")
            transport = await self._optional(self._a2dp_status, "Bluetooth transport status")
            gains = await self._optional(self._eq_gains, "custom EQ")
            if self.model == "M60":
                timer, sensitivity = await self._light()
                return SpeakerState(
                    volume, source, eq, tone, timer, sensitivity,
                    device_name=self.device_name, codec_preference=codec,
                    audio_status=audio, eq_gains=gains,
                    eq_profile_name=self.eq_profile_name, a2dp_status=transport,
                    firmware=self.firmware, classic_address=self.classic_address,
                )
            sub_out = await self._sub_out()
            multipoint = await self._boolean(0x7C, indexed=True)
            power_save = await self._boolean(0xB1)
            shutdown = await self._optional(self._shutdown_timer, "shutdown timer")
            return SpeakerState(
                volume, source, eq, tone, sub_out=sub_out,
                multipoint=multipoint, power_save=power_save,
                device_name=self.device_name, codec_preference=codec,
                audio_status=audio, eq_gains=gains, shutdown_timer=shutdown,
                eq_profile_name=self.eq_profile_name, a2dp_status=transport,
                firmware=self.firmware, classic_address=self.classic_address,
            )

    async def playback_command(self, action: str) -> None:
        """Forward AVRCP control; the device provides no ACK or playback state."""
        if action not in PLAYBACK_ACTIONS:
            raise ValueError("Unsupported playback action")
        async with self._session(hold=True):
            client = await self._connect()
            await client.write_gatt_char(
                WRITE_UUID, build_frame(0xC2, bytes((PLAYBACK_ACTIONS[action],)))
            )

    async def _device_name(self) -> str:
        data = await self._query(0xC9)
        try:
            name = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("Invalid speaker name encoding") from exc
        self.device_name = name
        return name

    async def read_name(self) -> str:
        """Read the speaker firmware name, not HA's Device Registry name."""
        async with self._session():
            return await self._device_name()

    async def _eq_profile_name(self) -> str:
        data = await self._query(0x43)
        count = len(EQ_FREQUENCIES[self.model_name])
        size = 6 if self.model == "M60" else 4
        end = 2 + count * size
        if len(data) < end or data[:2] != bytes((3 if self.model == "M60" else 0x10, count)):
            raise ProtocolError("Unexpected custom EQ profile response")
        if len(data) == end and self.model == "M60":
            return ""
        if len(data) < end + 4:
            raise ProtocolError("Missing custom EQ profile date")
        try:
            return data[end + 4:].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("Invalid custom EQ profile name encoding") from exc

    async def read_eq_profile_name(self) -> str:
        async with self._session():
            self.eq_profile_name = await self._eq_profile_name()
            return self.eq_profile_name

    async def power_off(self) -> None:
        """Explicit M90 shutdown: no ACK; the link may drop immediately."""
        if self.model != "M90":
            raise ValueError("M60 shutdown command is not documented")
        async with self._session(hold=True):
            client = await self._connect()
            await client.write_gatt_char(WRITE_UUID, build_frame(0xCE))

    async def disconnect_audio(self) -> None:
        """Explicit M60 disconnect; may drop both BLE and Classic links."""
        if self.model != "M60":
            raise ValueError("M90 disconnect command is not documented")
        async with self._session(hold=True):
            client = await self._connect()
            await client.write_gatt_char(WRITE_UUID, build_frame(0xCD))

    async def _classic_address(self) -> str:
        data = await self._query(0xC8)
        if len(data) != 6:
            raise ProtocolError("Unexpected classic address response")
        self.classic_address = ":".join(f"{b:02X}" for b in data)
        return self.classic_address

    async def read_classic_address(self) -> str:
        async with self._session():
            return await self._classic_address()

    async def _firmware(self) -> str:
        data = await self._query(0xC6)
        if len(data) != 3:
            raise ProtocolError("Unexpected firmware response")
        self.firmware = ".".join(str(part) for part in data)
        return self.firmware

    async def read_firmware(self) -> str:
        async with self._session():
            return await self._firmware()

    async def change(self, field: str, value: object) -> dict[str, Any]:
        """Write and read back just the affected setting; return authoritative fields."""
        async with self._session(hold=True):
            if field == "volume":
                maximum = 16 if self.model == "M60" else 50
                if type(value) is not int or not 0 <= value <= maximum:
                    raise ValueError("Volume out of range")
                await self._set(0x67, bytes((value,)))
                actual: object = await self._volume()
            elif field == "source":
                options = SOURCES[self.model_name]
                if value not in options:
                    raise ValueError("Unsupported source")
                group = 0x0F if self.model == "M60" else 0x1D
                await self._set(0x62, bytes((group, options[value])))
                actual = await self._source()
                for delay in (0.5, 0.75, 1, 1):
                    if actual == value:
                        break
                    await asyncio.sleep(delay)
                    actual = await self._source()
            elif field == "eq":
                options = PRESETS[self.model_name]
                if value not in options:
                    raise ValueError("Unsupported EQ preset")
                await self._set(0xC4, bytes((options[value],)))
                actual = await self._eq()
            elif field == "prompt_tone":
                if type(value) is not bool:
                    raise ValueError("Invalid prompt tone state")
                await self._set(0x87, bytes((2, 1, int(value))))
                actual = await self._tone()
            elif field in ("light_timeout", "light_sensitivity") and self.model == "M60":
                options = TIMERS if field == "light_timeout" else SENSITIVITY
                if value not in options:
                    raise ValueError("Unsupported smart light setting")
                timer, sensitivity = await self._light()
                if field == "light_timeout":
                    timer = value
                else:
                    sensitivity = value
                await self._set(0x85, bytes((3, TIMERS[timer], SENSITIVITY[sensitivity])))
                actual_timer, actual_sensitivity = await self._light()
                actual = actual_timer if field == "light_timeout" else actual_sensitivity
                if actual != value:
                    raise CommandNotApplied(f"{field}: requested {value}, speaker reports {actual}")
                return {"light_timeout": actual_timer, "light_sensitivity": actual_sensitivity}
            elif field == "sub_out" and self.model == "M90":
                if value not in SUB_OUT:
                    raise ValueError("Unsupported Sub Out level")
                await self._set(0x14, bytes((0, SUB_OUT[value])), app=0xED)
                actual = await self._sub_out()
            elif field in ("multipoint", "power_save") and self.model == "M90":
                if type(value) is not bool:
                    raise ValueError("Invalid switch state")
                if field == "multipoint":
                    await self._set(0x7D, bytes((0, int(value))))
                    actual = await self._boolean(0x7C, indexed=True)
                else:
                    await self._set(0xB2, bytes((int(value),)))
                    actual = await self._boolean(0xB1)
            elif field == "shutdown_timer" and self.model == "M90":
                if type(value) is not bool:
                    raise ValueError("Invalid shutdown timer state")
                if value:
                    await self._set(0xD1, b"\x00\x0F")
                else:
                    await self._set(0xD2, b"")
                minutes = await self._shutdown_timer()
                if (minutes > 0) != value:
                    raise CommandNotApplied(f"Shutdown timer: speaker reports {minutes} minutes")
                return {"shutdown_timer": minutes}
            elif field == "device_name":
                if type(value) is not str or not value or len(value.encode("utf-8")) > 35:
                    raise ValueError("Speaker name must be 1–35 UTF-8 bytes")
                await self._set(0xCA, value.encode("utf-8"))
                data = await self._query(0xC9)
                try:
                    name = data.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ProtocolError("Invalid speaker name encoding") from exc
                self.device_name = name
                actual = name
            elif field == "eq_profile_name":
                if type(value) is not str or not value or len(value.encode("utf-8")) > 35:
                    raise ValueError("EQ profile name must be 1–35 UTF-8 bytes")
                payload = int(time.time()).to_bytes(4, "little") + value.encode("utf-8")
                try:
                    await self._set(0x47, payload)
                except Exception as exc:
                    _LOGGER.debug("EQ name write lost ACK; checking read-back: %s", exc)
                name = await self._eq_profile_name()
                self.eq_profile_name = name
                actual = name
            elif field.startswith("eq_band_"):
                try:
                    index = int(field.removeprefix("eq_band_"))
                except ValueError as exc:
                    raise ValueError("Invalid EQ band") from exc
                if not 0 <= index < len(EQ_FREQUENCIES[self.model_name]):
                    raise ValueError("Unsupported EQ band")
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)  # bools are ints; the speaker does not take them
                    or not -3.0 <= value <= 3.0
                    or value * 2 != int(value * 2)
                ):
                    raise ValueError("Unsupported EQ gain")
                if await self._eq() != ("Customized" if self.model == "M60" else "Custom"):
                    raise ProtocolError("Select Custom EQ preset before editing bands")
                records = await self._eq_records()
                record = bytearray(records[index])
                record[4 if self.model == "M60" else 3] = int(value * 2 + 6)
                await self._set(0x44, bytes(record))
                gains = await self._eq_gains()
                if gains[index] != value:
                    raise CommandNotApplied(f"EQ band {index}: requested {value}, speaker reports {gains[index]}")
                return {"eq_gains": gains}
            elif field == "codec_preference":
                if value not in CODEC_PREFS:
                    raise ValueError("Unsupported codec preference")
                if self.model == "M60":
                    opcode, payload = 0x49, bytes((CODEC_PREFS[value],))
                else:
                    # M90 0x92 mode changes were not independently tested.
                    opcode, payload = 0x92, bytes((0x0E, CODEC_PREFS[value], 0xFF))
                try:
                    await self._set(opcode, payload)
                except Exception as exc:
                    # Codec writes may change the preference while dropping the link.
                    _LOGGER.debug("Codec write lost connection or ACK; checking read-back: %s", exc)
                actual = None
                for delay in (0.5, 1, 2, 3):
                    await asyncio.sleep(delay)
                    try:
                        actual = await self._codec_preference()
                    except Exception as exc:
                        _LOGGER.debug("Waiting to verify codec after reconnect: %s", exc)
                        continue
                    if actual == value:
                        break
                if actual is None:
                    raise ProtocolError("Cannot verify codec preference; it may have changed. Reconnect and refresh")
                if actual != value:
                    raise CommandNotApplied(f"Codec: requested {value}, speaker reports {actual}")
                updates = {"codec_preference": actual}
                if self.model == "M60":
                    light = await self._optional(self._light, "smart light after LDAC")
                    if light is not None:
                        updates["light_timeout"], updates["light_sensitivity"] = light
                return updates
            else:
                raise ValueError("Unsupported speaker control")
            if actual != value:
                raise CommandNotApplied(f"{field}: requested {value}, speaker reports {actual}")
            return {field: actual}

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            self._cancel_idle()
            self._pinned = False
            await self._disconnect()
