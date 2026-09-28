"""Use Home Assistant's adapter selection and connection retry helper."""

from bleak_retry_connector import (
    BleakClientWithServiceCache,
    close_stale_connections_by_address,
    establish_connection,
)
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothReachabilityIntent
from homeassistant.core import HomeAssistant

from .protocol.device import EdifierDevice
from .protocol.frames import ProtocolError

# Idle M60 connections took around half a minute on a tested PC. Give slow
# connections enough time, with fewer retries to avoid overlapping attempts.
CONNECT_ATTEMPTS = 2
CONNECT_TIMEOUT_SECONDS = 40


async def async_clear_stale_connections(address: str) -> None:
    """Drop links left over by a previous run, as HA core BLE integrations do."""
    await close_stale_connections_by_address(address)


def make_device(hass: HomeAssistant, address: str) -> EdifierDevice:
    """Resolve the best connectable proxy/adapter again for each connection."""

    def resolve():
        return bluetooth.async_ble_device_from_address(hass, address, connectable=True)

    def ble_device():
        device = resolve()
        if device is None:
            # Home Assistant explains reachability itself, so surface its reason.
            reason = bluetooth.async_address_reachability_diagnostics(hass, address, BluetoothReachabilityIntent.CONNECTION)
            raise ProtocolError(f"Speaker is not reachable right now: {reason}")
        return device

    async def connect(device, disconnected):
        return await establish_connection(
            BleakClientWithServiceCache, device, address,
            disconnected_callback=disconnected,
            # Re-resolve the best adapter on each retry instead of reusing a stale path.
            ble_device_callback=resolve,
            max_attempts=CONNECT_ATTEMPTS,
            timeout=CONNECT_TIMEOUT_SECONDS,
        )

    return EdifierDevice(ble_device, connect)
