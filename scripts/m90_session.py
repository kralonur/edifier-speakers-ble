#!/usr/bin/env python3
"""M90 BLE session runner: waits for one M90 BLE, connects, subscribes to
notifications, and provides an interactive or programmatic interface for commands.

Pass the address as the first argument or in EDIFIER_ADDRESS, for example:
    ./m90_session.py AA:BB:CC:22:33:55
"""

import os
import sys
import time

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib


def speaker_address() -> str:
    """Address to connect to, from argv or EDIFIER_ADDRESS.

    Nothing is hardcoded: every speaker has its own address, and a repository
    should not ship someone's device identifier.
    """
    address = (sys.argv[1] if len(sys.argv) > 1 else "") or os.environ.get("EDIFIER_ADDRESS", "")
    address = address.strip().upper()
    if not address:
        raise SystemExit(f"usage: {os.path.basename(sys.argv[0])} <BLE-ADDRESS>   (or set EDIFIER_ADDRESS)")
    return address


BLUEZ = "org.bluez"
ADAPTER_PATH = "/org/bluez/hci0"
DEVICE_IFACE = "org.bluez.Device1"
CHAR_IFACE = "org.bluez.GattCharacteristic1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

TARGET_ADDR = speaker_address()
TARGET_PATH = f"{ADAPTER_PATH}/dev_{TARGET_ADDR.replace(':', '_')}"

SERVICE_UUID = "48094503-1a48-11e9-ab14-d663bd873d93"
NOTIFY_UUID = "48090001-1a48-11e9-ab14-d663bd873d93"
WRITE_UUID = "48090002-1a48-11e9-ab14-d663bd873d93"


class M90Session:
    def __init__(self):
        self.bus = dbus.SystemBus()
        self.adapter = dbus.Interface(
            self.bus.get_object(BLUEZ, ADAPTER_PATH), "org.bluez.Adapter1"
        )
        self.loop = GLib.MainLoop()
        self.notify_char = None
        self.write_char = None
        self.notify_path = None
        self.write_path = None
        self.connected = False
        self.discovery_active = False

        self.pending_cmd = None
        self.pending_app = 0xEC
        self.pending_reply = None
        self.reply_received = False

        self.bus.add_signal_receiver(
            self.on_ifaces_added,
            signal_name="InterfacesAdded",
            dbus_interface="org.freedesktop.DBus.ObjectManager",
            bus_name=BLUEZ,
        )
        self.bus.add_signal_receiver(
            self.on_props_changed,
            signal_name="PropertiesChanged",
            dbus_interface=PROPS_IFACE,
            bus_name=BLUEZ,
            path_keyword="path",
        )

    def on_ifaces_added(self, path, ifaces):
        p = str(path)
        if TARGET_PATH in p:
            if CHAR_IFACE in ifaces:
                uuid = str(ifaces[CHAR_IFACE].get("UUID", "")).lower()
                if uuid == NOTIFY_UUID:
                    self.notify_path = p
                    print(f"Discovered notify char: {p}", flush=True)
                elif uuid == WRITE_UUID:
                    self.write_path = p
                    print(f"Discovered write char: {p}", flush=True)
            elif DEVICE_IFACE in ifaces and not self.connected:
                props = ifaces[DEVICE_IFACE]
                if str(props.get("Address", "")).upper() == TARGET_ADDR:
                    self.try_connect()

    def on_props_changed(self, iface, changed, invalidated, path=None):
        p = str(path) if path else ""
        if iface == DEVICE_IFACE and TARGET_PATH in p:
            if "Connected" in changed:
                c = bool(changed["Connected"])
                print(f"Device Connected property changed: {c}", flush=True)
                self.connected = c
                if not c:
                    self.on_disconnected()
            elif not self.connected and any(k in changed for k in ("RSSI", "ManufacturerData")):
                self.try_connect()
            if "ServicesResolved" in changed and bool(changed["ServicesResolved"]):
                print("Services resolved!", flush=True)
                self.find_chars()
        elif iface == CHAR_IFACE and "Value" in changed:
            val = bytes(changed["Value"])
            self.handle_notification(val)

    def on_disconnected(self):
        print("Disconnected from M90 BLE.", flush=True)
        self.notify_char = None
        self.write_char = None
        self.try_connect()

    def handle_notification(self, frame):
        hex_str = frame.hex(" ").upper()
        # Check frame validity
        if len(frame) >= 6:
            prefix = frame[0]
            app_code = frame[1]
            cmd = frame[2]
            payload_len = (frame[3] << 8) | frame[4]
            if len(frame) == payload_len + 6:
                expected_cks = sum(frame[:-1]) & 0xFF
                if frame[-1] == expected_cks:
                    cks_status = "OK"
                else:
                    cks_status = f"BAD cks (got {frame[-1]:02X} exp {expected_cks:02X})"
            else:
                cks_status = "BAD len"
            print(f"<- RECV: {hex_str} [{cks_status}]", flush=True)

            # Match reply: prefix 0xBB or 0xCC, matching app_code and cmd
            if self.pending_cmd is not None and cmd == self.pending_cmd and app_code == self.pending_app:
                self.pending_reply = frame
                self.reply_received = True

    def try_connect(self):
        try:
            dev = dbus.Interface(self.bus.get_object(BLUEZ, TARGET_PATH), DEVICE_IFACE)
            print(f"Connecting to {TARGET_ADDR}...", flush=True)
            dev.Connect()
            self.connected = True
            print("Connected!", flush=True)
            # Check if services already resolved
            props = dbus.Interface(self.bus.get_object(BLUEZ, TARGET_PATH), PROPS_IFACE)
            if bool(props.Get(DEVICE_IFACE, "ServicesResolved")):
                self.find_chars()
        except dbus.DBusException as e:
            print(f"Connect attempt failed: {e}", flush=True)

    def find_chars(self):
        om = dbus.Interface(self.bus.get_object(BLUEZ, "/"), "org.freedesktop.DBus.ObjectManager")
        objs = om.GetManagedObjects()
        for p, ifaces in objs.items():
            if TARGET_PATH in p and CHAR_IFACE in ifaces:
                uuid = str(ifaces[CHAR_IFACE].get("UUID", "")).lower()
                if uuid == NOTIFY_UUID:
                    self.notify_path = p
                elif uuid == WRITE_UUID:
                    self.write_path = p

        if self.notify_path and self.write_path:
            print(f"Found both GATT characteristics:\n  Notify: {self.notify_path}\n  Write:  {self.write_path}", flush=True)
            self.setup_notify()
        else:
            print(f"Chars not yet found (notify={self.notify_path}, write={self.write_path})", flush=True)

    def setup_notify(self):
        try:
            self.notify_char = dbus.Interface(self.bus.get_object(BLUEZ, self.notify_path), CHAR_IFACE)
            self.write_char = dbus.Interface(self.bus.get_object(BLUEZ, self.write_path), CHAR_IFACE)
            self.notify_char.StartNotify()
            print("StartNotify succeeded. Session ready for commands.", flush=True)
            self.on_ready()
        except dbus.DBusException as e:
            print(f"Setup notify failed: {e}", flush=True)

    def send_frame(self, cmd, payload=b"", app_code=0xEC, timeout=3.0):
        body = bytes([0xAA, app_code, cmd, len(payload) >> 8, len(payload) & 0xFF]) + bytes(payload)
        frame = body + bytes([sum(body) & 0xFF])
        print(f"-> SEND: {frame.hex(' ').upper()}", flush=True)

        self.pending_cmd = cmd
        self.pending_app = app_code  # app_code is frame[1] (0xEC or 0xED)
        self.pending_reply = None
        self.reply_received = False

        val = dbus.Array([dbus.Byte(b) for b in frame], signature="y")
        self.write_char.WriteValue(val, dbus.Dictionary({}, signature="sv"))

        start = time.time()
        while not self.reply_received and (time.time() - start) < timeout:
            context = self.loop.get_context()
            context.iteration(True)

        reply = self.pending_reply
        self.pending_cmd = None
        return reply

    def on_ready(self):
        print("\n=== RUNNING M90 BASELINE QUERIES ===", flush=True)
        queries = [
            ("Device Name", 0xC9, b"", 0xEC),
            ("Firmware", 0xC6, b"", 0xEC),
            ("Classic MAC", 0xC8, b"", 0xEC),
            ("D8 Capabilities", 0xD8, b"", 0xEC),
            ("Input Source", 0x61, b"", 0xEC),
            ("Volume", 0x66, b"", 0xEC),
            ("Sub Out", 0x13, b"", 0xED),
            ("Timed Power-Off", 0xD3, b"", 0xEC),
            ("Multipoint", 0x7C, b"", 0xEC),
            ("Power Save", 0xB1, b"", 0xEC),
            ("Prompt Tone", 0x86, b"", 0xEC),
            ("HD Audio Codec", 0x91, b"", 0xEC),
            ("Preset EQ", 0xD5, b"", 0xEC),
            ("Custom EQ (Full 9-band capture)", 0x43, b"", 0xEC),
        ]
        for name, cmd, payload, app in queries:
            print(f"\nQuerying {name} (0x{cmd:02X}, app 0x{app:02X})...", flush=True)
            res = self.send_frame(cmd, payload=payload, app_code=app, timeout=2.5)
            if res:
                print(f"  Result: {res.hex(' ').upper()}", flush=True)
            else:
                print(f"  Result: (no reply / timeout)", flush=True)
            time.sleep(0.3)
        print("\n=== BASELINE QUERIES COMPLETE ===", flush=True)


if __name__ == "__main__":
    DBusGMainLoop(set_as_default=True)
    session = M90Session()
    # Start scanning if not connected
    try:
        session.adapter.StartDiscovery()
        session.discovery_active = True
        print(f"Scanning for M90 BLE at {TARGET_ADDR}...", flush=True)
    except Exception as e:
        print(f"StartDiscovery error: {e}", flush=True)

    def heartbeat():
        if not session.connected:
            session.try_connect()
        return True

    GLib.timeout_add_seconds(3, heartbeat)
    try:
        session.loop.run()
    finally:
        if session.discovery_active:
            try:
                session.adapter.StopDiscovery()
            except:
                pass
