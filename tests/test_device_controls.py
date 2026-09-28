"""Per-setting write tests and error paths, without HA or Bluetooth hardware.

The fake client and the private-package loader come from test_protocol.py, which
is discovered next to this file. Every fake answer echoes the request's app byte,
because the device only accepts a reply whose app matches the request.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

try:  # discovered as a top-level module
    from test_protocol import AnswerAll, FakeClient, protocol
except ModuleNotFoundError:  # imported as part of a package
    from .test_protocol import AnswerAll, FakeClient, protocol


def records_for(model: str) -> bytes:
    """A valid custom-EQ payload for one model, exactly as the speaker reports it."""
    header = bytes((3 if model == "M60" else 0x10, len(protocol.EQ_FREQUENCIES[model])))
    body = b""
    for index, frequency in enumerate(protocol.EQ_FREQUENCIES[model]):
        if model == "M60":
            body += bytes((index, 0)) + frequency.to_bytes(2, "big") + bytes((6, 7))
        else:
            body += bytes((index,)) + frequency.to_bytes(2, "big") + bytes((6,))
    return header + body + (b"\x00" * 4 if model == "M90" else b"")


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def connect(self, model, answers):
        client = FakeClient(model, answers)

        async def connector(device, disconnected):
            client.is_connected = True
            return client

        device = protocol.EdifierDevice(lambda: object(), connector)
        await device.identify()
        self.addAsyncCleanup(device.close)
        return device, client

    async def test_invalid_values_are_rejected_before_any_write(self):
        cases = {
            "M60": [
                ("volume", 17), ("volume", 5.5), ("source", "HDMI"), ("eq", "Custom"),
                ("prompt_tone", "yes"), ("light_timeout", "bogus"), ("light_sensitivity", "bogus"),
                ("sub_out", "Low"), ("shutdown_timer", True), ("multipoint", True),
                ("device_name", ""), ("eq_profile_name", ""), ("eq_band_0", 0.25),
                ("eq_band_0", True), ("eq_band_9", 0.5), ("eq_band_x", 0.5),
                ("codec_preference", "bogus"), ("nonsense", 1),
            ],
            "M90": [
                ("volume", 51), ("multipoint", "yes"), ("power_save", "yes"),
                ("shutdown_timer", "yes"), ("light_timeout", "5 seconds"), ("eq_band_0", True),
                ("sub_out", "Nope"),
            ],
        }
        for model, values in cases.items():
            device, client = await self.connect(model, {})
            for field, value in values:
                with self.subTest(model=model, field=field, value=value), self.assertRaises(ValueError):
                    await device.change(field, value)
            self.assertEqual(client.writes, [], f"{model}: nothing may be written for an invalid value")

    async def test_unexpected_responses_are_reported(self):
        def answer(payload):
            return lambda data: (0xBB, data[1], data[2], payload)

        cases = [
            ("M90", "_volume", b"\x1d\x63"),        # above the reported maximum
            ("M90", "_volume", b"\x1d"),            # wrong length
            ("M90", "_source", b"\x1d"),            # wrong length
            ("M90", "_source", b"\x0f\x01"),        # wrong group for this model
            ("M90", "_source", b"\x1d\x63"),        # unknown source code
            ("M90", "_eq", b"\x63"),                # unknown preset code
            ("M90", "_eq", b"\x00\x00"),            # wrong length
            ("M90", "_tone", b"\x09\x09"),
            ("M60", "_light", b"\x01\x01\x01"),
            ("M90", "_sub_out", b"\x09\x09"),
            ("M90", "_codec_preference", b"\x00"),
            ("M60", "_codec_preference", b""),
            ("M90", "_a2dp_status", b"\x01\x02"),
            ("M90", "_audio_status", b"\x01\x02"),
            ("M90", "_shutdown_timer", b"\x01"),
            ("M90", "_classic_address", b"\x01"),
            ("M90", "_firmware", b"\x01"),
            ("M60", "_eq_records", b"\x03\x05" + b"\x00" * 40),
            ("M90", "_eq_records", b"\x10\x09" + b"\x00" * 40),
            ("M60", "_eq_records", b"\x03\x06" + bytes((9,)) + b"\x00" * 35),
            ("M60", "_eq_profile_name", b"\x03\x05"),
            ("M60", "_eq_profile_name", b"\x03\x06" + b"\x00" * 37),          # date missing
            ("M60", "_eq_profile_name", b"\x03\x06" + b"\x00" * 36 + b"\x00" * 4 + b"\xff\xfe"),
            ("M60", "_device_name", b"\xff\xfe"),
        ]
        for model, method, payload in cases:
            device, _client = await self.connect(model, AnswerAll(answer(payload)))
            with self.subTest(model=model, method=method, payload=payload), self.assertRaises(protocol.ProtocolError):
                await getattr(device, method)()

    async def test_boolean_reader_checks_indexed_plain_and_range(self):
        for payload, kwargs in ((b"\x01\x01", {"indexed": True}), (b"\x01\x02", {}), (b"\x02", {})):
            device, _client = await self.connect(
                "M90", AnswerAll(lambda data, p=payload: (0xBB, data[1], data[2], p)))
            with self.subTest(payload=payload, kwargs=kwargs), self.assertRaises(protocol.ProtocolError):
                await device._boolean(0x7F, **kwargs)

    async def test_requests_outside_the_frame_format_are_rejected(self):
        for opcode, payload, app in ((-1, b"", 0xEC), (256, b"", 0xEC), (1, b"", 0xEE), (1, b"x" * 65536, 0xEC)):
            with self.subTest(opcode=opcode, app=app, size=len(payload)):
                with self.assertRaises(ValueError):
                    protocol.build_frame(opcode, payload, app)

    async def test_disruptive_commands_are_refused_on_the_wrong_model(self):
        device, _client = await self.connect("M60", {})
        with self.assertRaises(ValueError):
            await device.power_off()
        device, _client = await self.connect("M90", {})
        with self.assertRaises(ValueError):
            await device.disconnect_audio()

    async def test_codec_write_that_loses_its_ack_is_still_verified(self):
        preference = next(iter(protocol.CODEC_PREFS))
        code = protocol.CODEC_PREFS[preference]

        def answer(data):
            if data[2] == 0x92:
                raise OSError("link dropped before the ACK")
            if data[2] == 0x91:
                return (0xBB, data[1], 0x91, bytes((0x0E, code)))
            return (0xBB, data[1], data[2], b"")

        device, _client = await self.connect("M90", AnswerAll(answer))
        with patch.object(protocol.asyncio, "sleep", AsyncMock()):
            changed = await device.change("codec_preference", preference)
        self.assertEqual(protocol.CODEC_PREFS[changed["codec_preference"]], code)

    async def test_command_rejection_is_reported(self):
        device, _client = await self.connect("M90", AnswerAll(lambda data: (0xCC, data[1], data[2], b"\x00\x01")))
        with self.assertRaises(protocol.ProtocolError):
            await device._set(0x13, b"", app=0xED)

    async def test_pending_request_fails_when_the_link_drops(self):
        client = FakeClient("M90", {})

        async def connector(device, disconnected):
            client.is_connected = True
            return client

        device = protocol.EdifierDevice(lambda: object(), connector)
        await device.identify()
        self.addAsyncCleanup(device.close)
        task = asyncio.create_task(device.read_name())
        await asyncio.sleep(0.05)
        device._disconnected(client)
        with self.assertRaises(protocol.ProtocolError):
            await task

    async def test_stale_disconnect_callback_and_garbage_frames_are_ignored(self):
        device, _client = await self.connect("M90", {})
        await device.connect_now()
        device._disconnected(object())  # a callback from an older client is not ours
        self.assertIsNotNone(device._client)
        device._notification(None, b"\x00")  # not an Edifier frame
        self.assertIsNone(device.event_callback)

    async def test_closed_and_unreachable_devices_raise(self):
        unreachable = protocol.EdifierDevice(lambda: None, AsyncMock())
        with self.assertRaises(protocol.ProtocolError):
            await unreachable.read_name()
        with self.assertRaises(protocol.ProtocolError):
            _ = unreachable.model_name
        await unreachable.close()
        with self.assertRaises(protocol.ProtocolError):
            await unreachable.read_name()

    async def test_model_change_is_rejected_on_reconnect(self):
        device, client = await self.connect("M60", {})
        client.services.model = "M90"
        with self.assertRaises(protocol.ProtocolError):
            await device.read_name()

    async def test_idle_disconnect_leaves_a_pinned_link_alone(self):
        device, client = await self.connect("M90", {})
        await device.connect_now()
        disconnects = client.disconnects
        await device._idle_disconnect(0)
        self.assertEqual(client.disconnects, disconnects)  # the pinned link stays open
        self.assertTrue(device._pinned)

    async def test_optional_reads_tolerate_a_failing_speaker(self):
        # Everything read_state() does not guard with _optional must answer.
        required = {
            0x66: b"\x32\x05",           # volume
            0x61: b"\x1d\x01",           # source
            0xD5: b"\x00",                # EQ preset
            0x86: b"\x02\x01",           # prompt tone
            0x13: b"\x00\x01",           # Sub Out (app 0xED)
            0x7C: b"\x00\x01",           # multipoint
            0xB1: b"\x01",                # power save
        }

        def answer(data):
            # The reads that matter answer; every optional one is malformed.
            return (0xBB, data[1], data[2], required.get(data[2], b"\x01"))

        device, _client = await self.connect("M90", AnswerAll(answer))
        state = await device.read_state()
        self.assertEqual(state.volume, 5)
        self.assertIsNone(state.firmware)  # unreadable optional fields stay unknown
        self.assertIsNone(state.classic_address)

    async def test_classic_address_and_firmware_readers(self):
        answers = {0xC8: lambda data: (0xBB, 0xEC, 0xC8, bytes.fromhex("AA BB CC 22 33 44")),
                   0xC6: lambda data: (0xBB, 0xEC, 0xC6, b"\x02\x05\x01")}
        device, _client = await self.connect("M90", answers)
        self.assertEqual(await device.read_classic_address(), "AA:BB:CC:22:33:44")
        self.assertEqual(await device.read_firmware(), "2.5.1")

    async def test_prompt_tone_write_is_verified(self):
        state = {0x86: b"\x02\x00"}

        def answer(data):
            if data[2] == 0x87:
                state[0x86] = bytes((2, data[7]))
                return (0xBB, data[1], 0x87, bytes((2, 1, data[7])))
            return (0xBB, data[1], data[2], state[0x86])

        device, _client = await self.connect("M60", AnswerAll(answer))
        self.assertEqual(await device.change("prompt_tone", True), {"prompt_tone": True})
        self.assertEqual(await device.change("prompt_tone", False), {"prompt_tone": False})

    async def test_smart_light_write_preserves_the_other_field(self):
        state = {"timer": 1, "sensitivity": 0}

        def answer(data):
            if data[2] == 0x85:
                state["timer"], state["sensitivity"] = data[6], data[7]
            return (0xBB, data[1], data[2], bytes((3, state["timer"], state["sensitivity"])))

        device, _client = await self.connect("M60", AnswerAll(answer))
        self.assertEqual(await device.change("light_sensitivity", "Low"),
                         {"light_timeout": "10 seconds", "light_sensitivity": "Low"})
        self.assertEqual(await device.change("light_timeout", "Always on"),
                         {"light_timeout": "Always on", "light_sensitivity": "Low"})

    async def test_smart_light_mismatch_is_not_reported_as_applied(self):
        stale = lambda data: (0xBB, data[1], data[2], bytes((3, 1, 0)))
        device, _client = await self.connect("M60", AnswerAll(stale))
        with self.assertRaises(protocol.CommandNotApplied):
            await device.change("light_timeout", "Always on")

    async def test_switch_and_timer_writes_are_verified(self):
        state = {"multipoint": 0, "power_save": 0, "timer": 15}

        def answer(data):
            opcode = data[2]
            if opcode == 0x7D:
                state["multipoint"] = data[6]
            elif opcode == 0xB2:
                state["power_save"] = data[5]
            elif opcode == 0xD1:
                state["timer"] = 15
            elif opcode == 0xD2:
                state["timer"] = 0
            payload = {
                0x7C: bytes((0, state["multipoint"])),
                0xB1: bytes((state["power_save"],)),
                0xD3: state["timer"].to_bytes(2, "big"),
            }.get(opcode, b"")
            return (0xBB, data[1], opcode, payload)

        device, _client = await self.connect("M90", AnswerAll(answer))
        self.assertEqual(await device.change("multipoint", True), {"multipoint": True})
        self.assertEqual(await device.change("power_save", True), {"power_save": True})
        self.assertEqual(await device.change("shutdown_timer", True), {"shutdown_timer": 15})
        self.assertEqual(await device.change("shutdown_timer", False), {"shutdown_timer": 0})

    async def test_shutdown_timer_mismatch_is_not_reported_as_applied(self):
        def answer(data):
            payload = b"\x00\x0f" if data[2] == 0xD3 else b""
            return (0xBB, data[1], data[2], payload)

        device, _client = await self.connect("M90", AnswerAll(answer))
        with self.assertRaises(protocol.CommandNotApplied):
            await device.change("shutdown_timer", False)

    async def test_device_name_write_reports_an_invalid_read_back(self):
        device, _client = await self.connect("M60", AnswerAll(lambda data: (0xBB, data[1], data[2], b"Renamed")))
        self.assertEqual(await device.change("device_name", "Renamed"), {"device_name": "Renamed"})
        broken, _client = await self.connect("M60", AnswerAll(lambda data: (0xBB, data[1], data[2], b"\xff\xfe")))
        with self.assertRaises(protocol.ProtocolError):
            await broken.change("device_name", "Renamed")

    async def test_eq_profile_name_survives_a_lost_ack(self):
        def answer(data):
            if data[2] == 0x47:
                raise OSError("link dropped before the ACK")
            return (0xBB, data[1], 0x43, records_for("M60") + b"\x00" * 4 + b"Studio")

        device, _client = await self.connect("M60", AnswerAll(answer))
        self.assertEqual(await device.change("eq_profile_name", "Studio"), {"eq_profile_name": "Studio"})

    async def test_eq_profile_name_without_a_name_is_empty_on_m60(self):
        device, _client = await self.connect("M60", AnswerAll(lambda data: (0xBB, data[1], 0x43, records_for("M60"))))
        self.assertEqual(await device.read_eq_profile_name(), "")

    async def test_eq_band_write_is_verified_on_both_models(self):
        for model, preset in (("M60", "Customized"), ("M90", "Custom")):
            state = {"records": records_for(model)}

            def answer(data, model=model, preset=preset, state=state):
                opcode = data[2]
                if opcode == 0xD5:
                    return (0xBB, data[1], opcode, bytes((list(protocol.PRESETS[model]).index(preset),)))
                if opcode == 0x44:
                    offset = 4 if model == "M60" else 3
                    records = bytearray(state["records"])
                    records[2 + offset] = data[5 + offset]
                    state["records"] = bytes(records)
                return (0xBB, data[1], opcode, state["records"])

            device, _client = await self.connect(model, AnswerAll(answer))
            changed = await device.change("eq_band_0", 0.5)
            self.assertEqual(changed["eq_gains"][0], 0.5, model)

            # A speaker that keeps reporting the old gain must not be called successful.
            stale_state = {"records": records_for(model)}

            def stale_answer(data, model=model, preset=preset, state=stale_state):
                if data[2] == 0xD5:
                    return (0xBB, data[1], 0xD5, bytes((list(protocol.PRESETS[model]).index(preset),)))
                return (0xBB, data[1], data[2], state["records"])

            stale, _stale_client = await self.connect(model, AnswerAll(stale_answer))
            with self.assertRaises(protocol.CommandNotApplied):
                await stale.change("eq_band_0", 0.5)

    async def test_eq_band_requires_the_custom_preset(self):
        device, _client = await self.connect("M90", AnswerAll(lambda data: (0xBB, data[1], data[2], b"\x00")))
        with self.assertRaises(protocol.ProtocolError):
            await device.change("eq_band_0", 0.5)

    async def test_source_write_retries_until_the_speaker_reports_it(self):
        reads = {"count": 0}

        def answer(data):
            if data[2] == 0x61:
                reads["count"] += 1
                code = 2 if reads["count"] == 1 else 1  # USB first, then the requested Bluetooth
                return (0xBB, data[1], 0x61, bytes((0x1D, code)))
            return (0xBB, data[1], data[2], b"")

        device, _client = await self.connect("M90", AnswerAll(answer))
        with patch.object(protocol.asyncio, "sleep", AsyncMock()):
            self.assertEqual(await device.change("source", "Bluetooth"), {"source": "Bluetooth"})
        self.assertEqual(reads["count"], 2)

    async def test_codec_preference_write_is_verified_on_both_models(self):
        state = {"code": 0}

        def answer(data):
            opcode = data[2]
            if opcode == 0x49:
                state["code"] = data[5]
            elif opcode == 0x92:
                state["code"] = data[6]
            if opcode == 0x48:
                return (0xBB, data[1], opcode, bytes((state["code"],)))
            if opcode == 0x91:
                return (0xBB, data[1], opcode, bytes((0x0E, state["code"])))
            if opcode == 0x84:
                return (0xBB, data[1], opcode, bytes((3, 1, 0)))
            return (0xBB, data[1], opcode, b"")

        preference = next(iter(protocol.CODEC_PREFS))
        for model in ("M60", "M90"):
            device, _client = await self.connect(model, AnswerAll(answer))
            with patch.object(protocol.asyncio, "sleep", AsyncMock()):
                changed = await device.change("codec_preference", preference)
            self.assertEqual(protocol.CODEC_PREFS[changed["codec_preference"]],
                             protocol.CODEC_PREFS[preference], model)
            if model == "M60":
                # The LDAC write can reset the smart light, so it is read back too.
                self.assertEqual(changed["light_timeout"], "10 seconds")

    async def test_codec_change_that_cannot_be_verified_is_reported(self):
        def answer(data):
            if data[2] in (0x48, 0x91):
                raise OSError("still reconnecting")
            return (0xBB, data[1], data[2], b"")

        device, _client = await self.connect("M90", AnswerAll(answer))
        with patch.object(protocol.asyncio, "sleep", AsyncMock()), self.assertRaises(protocol.ProtocolError):
            await device.change("codec_preference", next(iter(protocol.CODEC_PREFS)))

    async def test_codec_readback_is_retried_after_a_failed_attempt(self):
        preference = next(iter(protocol.CODEC_PREFS))
        code = protocol.CODEC_PREFS[preference]
        attempts = {"count": 0}

        def answer(data):
            if data[2] == 0x91:
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise OSError("reconnecting")
                return (0xBB, data[1], 0x91, bytes((0x0E, code)))
            return (0xBB, data[1], data[2], b"")

        device, _client = await self.connect("M90", AnswerAll(answer))
        with patch.object(protocol.asyncio, "sleep", AsyncMock()):
            changed = await device.change("codec_preference", preference)
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(protocol.CODEC_PREFS[changed["codec_preference"]], code)


if __name__ == "__main__":
    unittest.main()
