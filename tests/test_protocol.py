"""Protocol tests that run without HA or physical Bluetooth hardware."""

import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Load just the HA-independent subpackage under a private test-only name.
package = types.ModuleType("edifier_protocol_test")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components" / "edifier_ble" / "protocol")]
sys.modules[package.__name__] = package
frames = importlib.import_module("edifier_protocol_test.frames")
protocol = importlib.import_module("edifier_protocol_test.device")


def reply(kind, app, opcode, payload):
    body = bytes((kind, app, opcode)) + len(payload).to_bytes(2, "big") + payload
    return body + bytes((sum(body) & 255,))


class FakeServices:
    def __init__(self, model):
        self.model = model

    def get_service(self, uuid):
        return uuid == protocol.SERVICES.get(self.model)

    def get_characteristic(self, uuid):
        return uuid in (protocol.NOTIFY_UUID, protocol.WRITE_UUID)


class FakeClient:
    def __init__(self, model, answers):
        self.is_connected = True
        self.services = FakeServices(model)
        self.answers = answers
        self.writes = []
        self.callback = None
        self.disconnects = 0

    async def start_notify(self, uuid, callback):
        self.callback = callback

    async def write_gatt_char(self, uuid, data, response=False):
        self.writes.append(bytes(data))
        if data[2] in self.answers:
            kind, app, opcode, payload = self.answers[data[2]](data)
            self.callback(None, reply(kind, app, opcode, payload))

    async def disconnect(self):
        self.is_connected = False
        self.disconnects += 1


class AnswerAll(dict):
    """Answer every opcode, so tests need not enumerate each set/query pair."""

    def __init__(self, handler):
        super().__init__()
        self.handler = handler

    def __contains__(self, key):
        return True

    def __missing__(self, key):
        return self.handler


class FrameTests(unittest.TestCase):
    def test_documented_frames(self):
        self.assertEqual(frames.build_frame(0x67, b"\x00"), bytes.fromhex("AA EC 67 00 01 00 FE"))
        self.assertEqual(frames.build_frame(0x62, bytes.fromhex("0F 02")), bytes.fromhex("AA EC 62 00 02 0F 02 0B"))
        self.assertEqual(frames.build_frame(0x62, bytes.fromhex("1D 03")), bytes.fromhex("AA EC 62 00 02 1D 03 1A"))
        self.assertEqual(frames.build_frame(0x13, app=0xED), bytes.fromhex("AA ED 13 00 00 AA"))
        self.assertEqual(frames.parse_frame(bytes.fromhex("BB EC 66 00 02 10 00 1F")).payload, b"\x10\x00")
        self.assertEqual(frames.parse_frame(bytes.fromhex("CC EC D1 00 01 01 8B")).kind, 0xCC)
        self.assertEqual(frames.parse_frame(bytes.fromhex("BB ED 13 00 02 00 02 BF")).app, 0xED)

    def test_invalid_frames(self):
        for data in (b"", bytes.fromhex("BB EC 66 00 02 10 00 00"), bytes.fromhex("BB EC 66 00 03 10 00 1F"), bytes.fromhex("AA EC 66 00 00 FC")):
            with self.subTest(data=data), self.assertRaises(frames.ProtocolError):
                frames.parse_frame(data)


class DeviceTests(unittest.IsolatedAsyncioTestCase):
    async def connect(self, model, answers):
        client = FakeClient(model, answers)

        async def connector(device, disconnected):
            client.is_connected = True
            return client

        device = protocol.EdifierDevice(lambda: object(), connector)
        await device.identify()
        self.addAsyncCleanup(device.close)
        return device, client

    async def test_releases_connection_after_each_operation(self):
        def answer(data):
            return (0xBB, 0xEC, data[2], b"EDIFIER M90")

        device, client = await self.connect("M90", {0xC9: answer})
        self.assertFalse(client.is_connected)  # Identification does not hold the link.
        self.assertEqual(await device.read_name(), "EDIFIER M90")
        self.assertFalse(client.is_connected)
        self.assertEqual(await device.read_name(), "EDIFIER M90")
        self.assertFalse(client.is_connected)
        self.assertEqual(client.disconnects, 3)

    def power_save_answers(self):
        """Stateful M90 fake for the link tests: 0xB2 writes, 0xB1 reads."""
        values = {0xB1: b"\x00"}

        def answer(data):
            if data[2] == 0xB2:
                values[0xB1] = bytes((data[5],))
            return (0xBB, 0xEC, data[2], values.get(data[2], b"\x00"))

        return AnswerAll(answer)

    async def test_user_commands_hold_the_link_open(self):
        device, client = await self.connect("M90", self.power_save_answers())
        await device.change("power_save", True)
        self.assertTrue(client.is_connected)  # A command keeps the link for the idle window.
        self.assertIsNotNone(device._idle_task)
        await device.read_name()  # A background read reuses it and must not close it.
        self.assertTrue(client.is_connected)
        await device.change("power_save", False)
        self.assertTrue(client.is_connected)
        await device.close()
        self.assertFalse(client.is_connected)

    async def test_idle_window_is_one_minute(self):
        self.assertEqual(protocol.SESSION_IDLE_SECONDS, 60)

    async def test_idle_window_closes_the_link_and_force_buttons_override_it(self):
        device, client = await self.connect("M90", self.power_save_answers())
        with patch.object(protocol, "SESSION_IDLE_SECONDS", 0.05):
            await device.change("power_save", True)
            self.assertTrue(client.is_connected)
            await asyncio.sleep(0.2)
            self.assertFalse(client.is_connected)
            self.assertIsNone(device._idle_task)
            await device.connect_now()  # Pinned: the idle timer must not close it.
            await device.change("power_save", False)
            await asyncio.sleep(0.2)
            self.assertTrue(client.is_connected)
            self.assertIsNone(device._idle_task)
            await device.disconnect_now()
            self.assertFalse(client.is_connected)

    async def test_identify_and_background_reads_do_not_pin_the_link(self):
        device, client = await self.connect("M90", self.power_save_answers())
        await device.identify()
        self.assertFalse(client.is_connected)
        await device.change("power_save", False)  # A command opens and holds the link.
        self.assertTrue(client.is_connected)
        await device.read_name()
        self.assertTrue(client.is_connected)
        await device.disconnect_now()
        self.assertFalse(client.is_connected)

    async def test_unsolicited_frames_trigger_a_reread_signal(self):
        def answer(data):
            return (0xBB, 0xEC, data[2], b"EDIFIER M90")

        device, client = await self.connect("M90", {0xC9: answer})
        events = []
        device.event_callback = lambda: events.append(1)
        self.assertEqual(await device.read_name(), "EDIFIER M90")
        self.assertEqual(events, [])  # Answers to our own request are not events.
        client.callback(None, reply(0xBB, 0xEC, 0xAD, b"\x01\x02"))  # Speaker push.
        self.assertEqual(events, [1])
        client.callback(None, reply(0xBB, 0xEC, 0x66, b"\x32\x08"))
        self.assertEqual(len(events), 2)

    async def test_link_held_state_ignores_transient_reads(self):
        device, client = await self.connect("M90", self.power_save_answers())
        signals = []
        device.link_callback = lambda: signals.append(device.is_link_held)
        self.assertFalse(device.is_link_held)
        await device.read_name()  # Transient read while polling.
        self.assertEqual(signals, [])  # Must not flap the indicator every poll.
        await device.change("power_save", True)  # A command holds the link.
        self.assertEqual(signals, [True])
        self.assertTrue(device.is_connected)
        await device.read_name()  # A background read inside the window keeps it.
        self.assertEqual(signals, [True])
        await device.disconnect_now()
        self.assertEqual(signals, [True, False])
        client.callback(None, reply(0xBB, 0xEC, 0xAD, b"\\x01"))  # Not a link change.
        self.assertEqual(len(signals), 2)
        await device.connect_now()  # Pinned counts as held.
        self.assertEqual(signals[-1], True)
        client.is_connected = False  # Speaker drops the link on its own.
        device._disconnected(client)
        self.assertEqual(signals[-1], False)
        self.assertFalse(device.is_link_held)

    async def test_idle_expiry_reports_the_link_as_released(self):
        device, client = await self.connect("M90", self.power_save_answers())
        signals = []
        device.link_callback = lambda: signals.append(device.is_link_held)
        with patch.object(protocol, "SESSION_IDLE_SECONDS", 0.05):
            await device.change("power_save", True)
            self.assertEqual(signals, [True])
            await asyncio.sleep(0.2)
        self.assertEqual(signals, [True, False])
        self.assertFalse(device.is_connected)

    async def test_advertised_device_is_used_instead_of_re_resolving(self):
        """A briefly-advertising speaker must be connected to with the object HA just saw."""
        advertised = object()
        resolved_calls = []

        async def connector(device, disconnected):
            resolved_calls.append(device)
            return FakeClient("M60", {})

        device = protocol.EdifierDevice(lambda: (_ for _ in ()).throw(AssertionError("must not re-resolve")), connector)
        device.set_ble_device(advertised)
        await device.identify()
        self.assertIs(resolved_calls[-1], advertised)
        self.assertEqual(device.model, "M60")
        await device.close()

    async def test_m60_state_and_volume_verification(self):
        values = {0x66: b"\x10\x01", 0x61: b"\x0F\x02", 0xD5: b"\x03", 0x86: b"\x02\x01", 0x84: b"\x03\x01\x02"}

        def answer(data):
            opcode = data[2]
            if opcode == 0x67:
                values[0x66] = bytes((16, data[5]))
                return (0xBB, 0xEC, opcode, b"\x10" + bytes((data[5],)))
            return (0xBB, 0xEC, opcode, values[opcode])

        device, client = await self.connect("M60", {key: answer for key in (*values, 0x67)})
        with patch.object(device, "_optional", new=AsyncMock(return_value=None)):
            state = await device.read_state()
        self.assertEqual((state.volume, state.source, state.eq, state.light_timeout, state.light_sensitivity), (1, "USB", "Movie", "10 seconds", "Low"))
        self.assertEqual(await device.change("volume", 0), {"volume": 0})
        self.assertEqual(client.writes[-2], bytes.fromhex("AA EC 67 00 01 00 FE"))
        self.assertEqual(client.writes[-1], bytes.fromhex("AA EC 66 00 00 FC"))
        self.assertTrue(client.is_connected)  # A volume change is a command: link is held.
        await device.close()
        self.assertFalse(client.is_connected)

    async def test_m90_model_specific_state_and_sub_out(self):
        values = {0x66: b"\x32\x08", 0x61: b"\x1D\x03", 0xD5: b"\x02", 0x86: b"\x02\x00", 0x13: b"\x00\x01", 0x7C: b"\x00\x01", 0xB1: b"\x00"}

        def answer(data):
            opcode = data[2]
            if opcode == 0x14:
                values[0x13] = b"\x00" + bytes((data[6],))
                return (0xBB, 0xED, opcode, b"\x01")
            return (0xBB, data[1], opcode, values[opcode])

        device, client = await self.connect("M90", {key: answer for key in (*values, 0x14)})
        with patch.object(device, "_optional", new=AsyncMock(return_value=None)):
            state = await device.read_state()
        self.assertEqual((state.volume, state.source, state.eq, state.sub_out, state.multipoint, state.power_save), (8, "HDMI", "Dynamic", "Medium", True, False))
        self.assertEqual(await device.change("sub_out", "High"), {"sub_out": "High"})
        self.assertEqual(client.writes[-2], bytes.fromhex("AA ED 14 00 02 00 02 AF"))

    async def test_mismatch_is_not_success(self):
        def answer(data):
            if data[2] == 0x67:
                return (0xBB, 0xEC, 0x67, b"\x10\x00")
            return (0xBB, 0xEC, 0x66, b"\x10\x00")

        device, _ = await self.connect("M60", {0x67: answer, 0x66: answer})
        with self.assertRaises(frames.CommandNotApplied):
            await device.change("volume", 10)

    async def test_smart_light_preserves_other_setting(self):
        values = {0x84: b"\x03\x01\x02"}

        def answer(data):
            opcode = data[2]
            if opcode == 0x85:
                values[0x84] = data[5:8]
            return (0xBB, 0xEC, opcode, b"\x01" if opcode == 0x85 else values[opcode])

        device, client = await self.connect("M60", {0x84: answer, 0x85: answer})
        self.assertEqual(await device.change("light_timeout", "Always on"), {"light_timeout": "Always on", "light_sensitivity": "Low"})
        self.assertEqual(client.writes[-2], bytes.fromhex("AA EC 85 00 03 03 03 02 26"))

    async def test_m90_advanced_queries_timer_rename_and_eq_band_zero(self):
        records = [bytes((index, *frequency.to_bytes(2, "big"), 6)) for index, frequency in enumerate(protocol.EQ_FREQUENCIES["M90"])]
        values = {
            0x91: b"\x0E\x01", 0x68: b"\x00", 0xD3: b"\x00\x00",
            0xC9: b"EDIFIER M90", 0xD5: b"\x03", 0xC3: b"\x03",
            "profile": b"Old",
        }

        def answer(data):
            opcode = data[2]
            if opcode == 0x43:
                payload = b"\x10\x09" + b"".join(records) + b"\x00" * 4 + values["profile"]
            elif opcode == 0x44:
                records[data[5]] = data[5:9]
                payload = b"\x01"
            elif opcode == 0xD1:
                values[0xD3] = b"\x00\x0F"
                payload = b"\x01"
            elif opcode == 0xD2:
                values[0xD3] = b"\x00\x00"
                payload = b"\x01"
            elif opcode == 0xCA:
                values[0xC9] = data[5:-1]
                payload = b"\x01"
            elif opcode == 0x47:
                values["profile"] = data[9:-1]
                payload = b"\x01"
            elif opcode == 0x92:
                values[0x91] = b"\x0E" + data[6:7]
                payload = b"\x0F" + data[6:7]
            else:
                payload = values[opcode]
            return (0xCC if opcode in (0xD1, 0xD2, 0xCA) else 0xBB, 0xEC, opcode, payload)

        device, client = await self.connect("M90", {key: answer for key in (*values, 0x43, 0x44, 0x47, 0x92, 0xD1, 0xD2, 0xCA) if isinstance(key, int)})
        self.assertEqual(await device._codec_preference(), "44.1/48 kHz preference")
        self.assertEqual(await device._audio_status(), 0)
        self.assertEqual(await device._a2dp_status(), 3)
        self.assertEqual(await device._eq_gains(), (0.0,) * 9)
        self.assertEqual(await device.read_eq_profile_name(), "Old")
        self.assertEqual(await device.change("eq_profile_name", "New"), {"eq_profile_name": "New"})
        with patch.object(protocol.asyncio, "sleep", new=AsyncMock()):
            self.assertEqual(await device.change("codec_preference", "96 kHz preference"), {"codec_preference": "96 kHz preference"})
        self.assertIn(frames.build_frame(0x92, bytes.fromhex("0E 02 FF")), client.writes)
        self.assertEqual(await device.change("shutdown_timer", True), {"shutdown_timer": 15})
        self.assertEqual(client.writes[-2], bytes.fromhex("AA EC D1 00 02 00 0F 78"))
        self.assertEqual(await device.change("shutdown_timer", False), {"shutdown_timer": 0})
        self.assertEqual(await device.read_name(), "EDIFIER M90")
        self.assertEqual(await device.change("device_name", "Desk"), {"device_name": "Desk"})
        self.assertEqual(await device.change("eq_band_0", 0.5), {"eq_gains": (0.5,) + (0.0,) * 8})
        self.assertEqual(client.writes[-2], bytes.fromhex("AA EC 44 00 04 00 00 3E 07 23"))
        for index in range(1, 9):
            before = records[index]
            result = await device.change(f"eq_band_{index}", 0.5)
            self.assertEqual(result["eq_gains"][index], 0.5)
            self.assertEqual(records[index][:3], before[:3])  # index and frequency retained
            self.assertEqual(client.writes[-2], frames.build_frame(0x44, before[:3] + b"\x07"))
        self.assertEqual(await device._eq_gains(), (0.5,) * 9)
        with self.assertRaises(ValueError):
            await device.change("eq_band_9", 0.5)
        with self.assertRaises(ValueError):
            await device.change("device_name", "é" * 18)  # 36 UTF-8 bytes

    async def test_read_state_populates_firmware_and_details(self):
        records = [bytes((index, *frequency.to_bytes(2, "big"), 6)) for index, frequency in enumerate(protocol.EQ_FREQUENCIES["M90"])]
        values = {
            0x66: b"\x32\x08", 0x61: b"\x1D\x03", 0xD5: b"\x02", 0x86: b"\x02\x00",
            0x13: b"\x00\x01", 0x7C: b"\x00\x01", 0xB1: b"\x00",
            0xC6: b"\x02\x05\x01", 0xC9: b"EDIFIER M90", 0xC8: b"\xAA\xBB\xCC\x22\x33\x44",
            0x43: b"\x10\x09" + b"".join(records) + b"\x00" * 4 + b"Custom Profile",
            0x91: b"\x0E\x01", 0x68: b"\x00", 0xC3: b"\x03", 0xD3: b"\x00\x00",
        }

        def answer(data):
            opcode = data[2]
            return (0xBB, 0xED if opcode == 0x13 else 0xEC, opcode, values[opcode])

        device, client = await self.connect("M90", {key: answer for key in values})
        state = await device.read_state()
        self.assertEqual(state.firmware, "2.5.1")
        self.assertEqual(device.firmware, "2.5.1")
        self.assertEqual(state.device_name, "EDIFIER M90")
        self.assertEqual(state.eq_profile_name, "Custom Profile")
        self.assertEqual(state.classic_address, "AA:BB:CC:22:33:44")
        self.assertEqual(device.classic_address, "AA:BB:CC:22:33:44")

    async def test_disruptive_actions_are_explicit_no_ack_writes(self):
        for model, action, frame in (("M60", "disconnect_audio", "AA EC CD 00 00 63"), ("M90", "power_off", "AA EC CE 00 00 64")):
            device, client = await self.connect(model, {})
            await getattr(device, action)()
            self.assertEqual(client.writes[-1], bytes.fromhex(frame))
            self.assertIsNone(device._pending)

    async def test_m90_codec_change_must_read_back(self):
        def answer(data):
            if data[2] == 0x92:
                return (0xBB, 0xEC, 0x92, b"\x0F\x01")
            return (0xBB, 0xEC, 0x91, b"\x0E\x01")

        device, _ = await self.connect("M90", {0x92: answer, 0x91: answer})
        with patch.object(protocol.asyncio, "sleep", new=AsyncMock()):
            with self.assertRaises(frames.CommandNotApplied):
                await device.change("codec_preference", "96 kHz preference")

    async def test_m60_custom_eq_read_and_write(self):
        records = [bytes((index, 0, *frequency.to_bytes(2, "big"), 6, 7)) for index, frequency in enumerate(protocol.EQ_FREQUENCIES["M60"])]
        def answer(data):
            opcode = data[2]
            if opcode == 0x43:
                return (0xBB, 0xEC, opcode, b"\x03\x06" + b"".join(records))
            if opcode == 0x44:
                records[data[5]] = data[5:11]
                return (0xBB, 0xEC, opcode, b"\x01")
            if opcode == 0xD5:
                return (0xBB, 0xEC, opcode, b"\x04")
            return (0xBB, 0xEC, opcode, b"\x02")

        device, client = await self.connect("M60", {key: answer for key in (0x43, 0x44, 0xD5, 0x48)})
        self.assertEqual(await device._codec_preference(), "96 kHz preference")
        self.assertEqual(await device._eq_gains(), (0.0,) * 6)
        self.assertEqual(await device.change("eq_band_0", 0.5), {"eq_gains": (0.5,) + (0.0,) * 5})
        self.assertEqual(client.writes[-2], bytes.fromhex("AA EC 44 00 06 00 00 00 3E 07 07 2C"))

    async def test_avrcp_commands_do_not_wait_for_ack_on_both_models(self):
        expected = {
            "play": "AA EC C2 00 01 00 59",
            "pause": "AA EC C2 00 01 01 5A",
            "next": "AA EC C2 00 01 04 5D",
            "previous": "AA EC C2 00 01 05 5E",
        }
        for model in ("M60", "M90"):
            device, client = await self.connect(model, {})
            for action, frame in expected.items():
                await device.playback_command(action)
                self.assertEqual(client.writes[-1], bytes.fromhex(frame))
                self.assertIsNone(device._pending)
            with self.assertRaises(ValueError):
                await device.playback_command("stop")

    async def test_avrcp_write_failure_is_not_swallowed(self):
        device, client = await self.connect("M90", {})

        async def fail_write(*args, **kwargs):
            raise OSError("BLE write failed")

        client.write_gatt_char = fail_write
        with self.assertRaises(OSError):
            await device.playback_command("play")

    async def test_request_timeout(self):
        device, client = await self.connect("M60", {})
        with patch.object(protocol, "RESPONSE_TIMEOUT", 0.01):
            with self.assertRaises(TimeoutError):
                await device.read_state()
        self.assertIsNone(device._pending)
        self.assertFalse(client.is_connected)

    async def test_source_and_eq_are_model_specific(self):
        for model, group, source, preset in (("M60", 0x0F, "AUX", "Movie"), ("M90", 0x1D, "HDMI", "Dynamic")):
            values = {0x61: bytes((group, 1)), 0xD5: b"\x00"}

            def answer(data):
                opcode = data[2]
                if opcode == 0x62:
                    values[0x61] = data[5:7]
                if opcode == 0xC4:
                    values[0xD5] = data[5:6]
                payload = b"\x01" if opcode in (0x62, 0xC4) else values[opcode]
                return (0xBB, 0xEC, opcode, payload)

            device, client = await self.connect(model, {key: answer for key in (0x61, 0x62, 0xC4, 0xD5)})
            self.assertEqual(await device.change("source", source), {"source": source})
            self.assertEqual(client.writes[0][5], group)
            self.assertEqual(await device.change("eq", preset), {"eq": preset})
            self.assertEqual(client.writes[-2][5], protocol.PRESETS[model][preset])

    async def test_unsupported_gatt_is_rejected(self):
        client = FakeClient("M60", {})
        client.services = FakeServices("unsupported")

        async def connector(device, disconnected):
            return client

        device = protocol.EdifierDevice(lambda: object(), connector)
        with self.assertRaises(frames.ProtocolError):
            await device.identify()
        self.assertFalse(client.is_connected)


if __name__ == "__main__":
    unittest.main()
