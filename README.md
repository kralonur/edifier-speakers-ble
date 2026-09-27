# Edifier Speakers BLE

Community documentation for Edifier speakers' **BLE control protocols**. Currently documented: **M60 and M90**. The references combine observations from real hardware with model-specific mappings from the EDIFIER ConneX Android app. They cover GATT discovery, frame format, commands, responses and known limits.

## Protocol references

- [M60 BLE protocol](docs/edifier-m60-ble.md)
- [M90 BLE protocol](docs/edifier-m90-ble.md)

**Use the reference for your exact model.** The speakers share some opcodes and characteristic UUIDs, but differ in service UUID, source group and options, volume range, EQ record format, and codec-control commands. A value documented for one model is not automatically valid on the other.

Unless a section says otherwise, documented controls were exercised on a physical speaker. App-derived labels and capabilities, unanswered probes, and commands without end-to-end confirmation are identified in the relevant sections. An acknowledgement alone does not prove a setting took effect; audio quality and acoustic response are not established by BLE read-backs.

## Scope and safety

The current references cover BLE controls, not firmware updates or the Bluetooth audio transport. Track metadata may need to come from the audio source rather than the speaker. Firmware revisions may behave differently.

Commands that rename, switch inputs, change audio settings, or disconnect a link can disrupt playback. Read and record the current value first, then check the result and restore it if testing. Do not assume the speaker reconnects automatically. Reset, OTA and pairing-management commands are outside the tested scope.

