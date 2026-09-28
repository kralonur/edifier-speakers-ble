#!/usr/bin/env python3
"""Scan for one M90 BLE address and connect without pairing.

Pass the address as the first argument or in EDIFIER_ADDRESS, for example:
    ./connect_m90_ble.py AA:BB:CC:22:33:55
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
TARGET = speaker_address()
TARGET_PATH = f"{ADAPTER_PATH}/dev_{TARGET.replace(':', '_')}"
RETRY_SECONDS = 5


class M90Watcher:
    def __init__(self):
        self.bus = dbus.SystemBus()
        self.adapter = dbus.Interface(
            self.bus.get_object(BLUEZ, ADAPTER_PATH), "org.bluez.Adapter1"
        )
        self.loop = GLib.MainLoop()
        self.discovery_started = False
        self.seen = False
        self.connecting = False
        self.connected = False
        self.last_attempt = -RETRY_SECONDS

        self.bus.add_signal_receiver(
            self.on_interfaces_added,
            signal_name="InterfacesAdded",
            dbus_interface="org.freedesktop.DBus.ObjectManager",
            bus_name=BLUEZ,
        )
        self.bus.add_signal_receiver(
            self.on_properties_changed,
            signal_name="PropertiesChanged",
            dbus_interface="org.freedesktop.DBus.Properties",
            bus_name=BLUEZ,
            path_keyword="path",
        )

    def is_connected(self):
        try:
            props = dbus.Interface(
                self.bus.get_object(BLUEZ, TARGET_PATH),
                "org.freedesktop.DBus.Properties",
            )
            return bool(props.Get(DEVICE_IFACE, "Connected"))
        except dbus.DBusException:
            return False

    def finish(self):
        if not self.connected:
            self.connected = True
            print(f"Connected to M90 BLE at {TARGET} (no pairing performed).", flush=True)
        self.loop.quit()

    def try_connect(self):
        if self.connecting or self.connected or not self.seen:
            return
        now = time.monotonic()
        if now - self.last_attempt < RETRY_SECONDS:
            return

        self.last_attempt = now
        self.connecting = True
        print(f"Found {TARGET}; connecting without pairing...", flush=True)
        try:
            device = dbus.Interface(
                self.bus.get_object(BLUEZ, TARGET_PATH), DEVICE_IFACE
            )
            device.Connect()
            if self.is_connected():
                self.finish()
            else:
                print(
                    "Connect returned, but BlueZ is not connected yet; retrying.",
                    flush=True,
                )
        except dbus.DBusException as exc:
            print(f"Connect failed ({exc}); continuing to scan.", flush=True)
        finally:
            self.connecting = False

    def on_interfaces_added(self, path, interfaces):
        if str(path) != TARGET_PATH:
            return
        props = interfaces.get(DEVICE_IFACE)
        if props and str(props.get("Address", "")).upper() == TARGET:
            self.seen = True
            if bool(props.get("Connected", False)):
                self.finish()
            else:
                self.try_connect()

    def on_properties_changed(self, interface, changed, invalidated, path=None):
        if interface != DEVICE_IFACE or str(path) != TARGET_PATH:
            return
        if bool(changed.get("Connected", False)):
            self.finish()
        elif any(key in changed for key in ("RSSI", "ManufacturerData", "ServiceData", "UUIDs")):
            self.seen = True
            self.try_connect()

    def retry(self):
        if self.connected:
            return False
        self.try_connect()
        return True

    def run(self):
        if self.is_connected():
            self.connected = True
            print(f"M90 BLE at {TARGET} is already connected.", flush=True)
            return 0

        try:
            device = dbus.Interface(
                self.bus.get_object(BLUEZ, TARGET_PATH), DEVICE_IFACE
            )
            self.seen = True
            print(f"M90 device object exists; attempting direct connect...", flush=True)
            device.Connect()
            if self.is_connected():
                self.finish()
                return 0
        except dbus.DBusException:
            pass

        print(f"Starting discovery for M90 BLE at {TARGET}...", flush=True)
        try:
            self.adapter.StartDiscovery()
            self.discovery_started = True
        except dbus.DBusException as exc:
            print(f"StartDiscovery failed ({exc}); watching signals anyway.", flush=True)

        GLib.timeout_add_seconds(RETRY_SECONDS, self.retry)
        try:
            self.loop.run()
        finally:
            if self.discovery_started:
                try:
                    self.adapter.StopDiscovery()
                except dbus.DBusException:
                    pass

        return 0 if self.connected else 1


if __name__ == "__main__":
    DBusGMainLoop(set_as_default=True)
    sys.exit(M90Watcher().run())
