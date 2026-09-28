"""Edifier BLE integration constants."""

from homeassistant.const import Platform

DOMAIN = "edifier_ble"
CONF_MODEL = "model"
PLATFORMS = (
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
)
