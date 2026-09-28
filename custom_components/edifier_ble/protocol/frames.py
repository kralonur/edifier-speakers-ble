"""Edifier BLE wire format (independent of Home Assistant)."""

from dataclasses import dataclass


class ProtocolError(Exception):
    """An invalid or unexpected device response."""


class UnsupportedDevice(ProtocolError):
    """The GATT profile is not an M60 or M90."""


class CommandNotApplied(ProtocolError):
    """The speaker did not report the requested state."""


@dataclass(frozen=True, slots=True)
class Frame:
    kind: int
    app: int
    opcode: int
    payload: bytes


def build_frame(opcode: int, payload: bytes = b"", app: int = 0xEC) -> bytes:
    if not (0 <= opcode <= 255 and app in (0xEC, 0xED) and len(payload) <= 65535):
        raise ValueError("Invalid Edifier request")
    body = bytes((0xAA, app, opcode)) + len(payload).to_bytes(2, "big") + payload
    return body + bytes((sum(body) & 0xFF,))


def parse_frame(data: bytes) -> Frame:
    if len(data) < 6 or data[0] not in (0xBB, 0xCC) or data[1] not in (0xEC, 0xED):
        raise ProtocolError("Invalid Edifier frame header")
    if len(data) != 6 + int.from_bytes(data[3:5], "big"):
        raise ProtocolError("Invalid Edifier frame length")
    if sum(data[:-1]) & 0xFF != data[-1]:
        raise ProtocolError("Invalid Edifier frame checksum")
    return Frame(data[0], data[1], data[2], data[5:-1])
