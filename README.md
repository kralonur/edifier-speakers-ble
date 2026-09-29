# Edifier Speakers BLE

Community documentation for Edifier speakers' **BLE control protocols**. Currently documented: **M60 and M90**. The references combine observations from real hardware with model-specific mappings from the EDIFIER ConneX Android app. They cover GATT discovery, frame format, commands, responses and known limits.

## Protocol references

- [M60 BLE protocol](docs/edifier-m60-ble.md)
- [M90 BLE protocol](docs/edifier-m90-ble.md)

**Use the reference for your exact model.** The speakers share some opcodes and characteristic UUIDs, but differ in service UUID, source group and options, volume range, EQ record format, and codec-control commands. A value documented for one model is not automatically valid on the other.

Unless a section says otherwise, documented controls were exercised on a physical speaker. App-derived labels and capabilities, unanswered probes, and commands without end-to-end confirmation are identified in the relevant sections. An acknowledgement alone does not prove a setting took effect; audio quality and acoustic response are not established by BLE read-backs.

## Home Assistant custom integration (early release)

[![Add to HACS](https://img.shields.io/badge/Add%20to-HACS-41BDF5?style=for-the-badge&logo=homeassistant&logoColor=white)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kralonur&repository=edifier-speakers-ble&category=integration)

**Edifier BLE** brings [Edifier](https://www.edifier.com/) speakers — the **M60** and **M90** — into Home Assistant over Bluetooth Low Energy. It talks to the speaker directly, so no account, cloud service or vendor app is involved.

**Prerequisites:** the built-in Bluetooth integration must be working, with a connectable adapter or an ESPHome Bluetooth proxy in range of the speaker, and the speaker itself powered on. Then either add this repository to HACS as a custom repository (category **Integration**) and install **Edifier BLE** from there, or copy `custom_components/edifier_ble` into your configuration's `custom_components/` directory. Either way, restart Home Assistant and add **Edifier BLE** from Settings → Devices & services. Home Assistant suggests a speaker from a connectable advertisement named `EDIFIER *` (any case) or carrying the ConneX service UUID — the M60 often advertises with no name — and confirms the model over GATT after you confirm. It does not pair the speakers.

**What you get**

- Volume slider (0–50 M90, 0–16 M60), source select, separate Play/Pause/Next/Previous buttons, EQ preset plus writable custom bands (6 on M60, 9 on M90 — select `Customized`/`Custom` first), prompt tone.
- Model extras: M60 smart light and LDAC preference; M90 Sub Out, multipoint, power save, 15-minute shutdown timer.
- Sensors: firmware, Classic Bluetooth MAC, audio *UI/status* code (not a negotiated codec), Bluetooth transport status. Renameable speaker and custom EQ profile names.
- **Force connect** / **Force disconnect**, plus — only on purpose — M90 **Power off** and M60 **Disconnect Bluetooth audio**.

**How it behaves.** State is polled every two minutes, and a command holds the BLE link for one minute so consecutive changes do not each pay a reconnect. While the speaker is unreachable, settings keep their **last known value**: the **Online** sensor is the one entity that reports reachability, so trust it (and Home Assistant's last-updated time) rather than the values. **Setup never waits for the speaker.** The entities are created immediately and the first read runs in the background, so a sleeping speaker is reported by **Online** instead of making the integration unavailable. That is deliberate: these speakers are unreachable while they are in standby, and the usual Home Assistant alternative — refusing to set up until the speaker answers — would delete all of the entities on every restart. A speaker that stays unreachable for **24 hours** raises a repair card telling you to check that it is powered on and in range and to press **Force connect**; it withdraws itself as soon as the speaker answers. Because the card is driven by polls, it stays quiet if you turned polling off.

**Bluetooth control link** shows whether Home Assistant is deliberately holding the link — while it is, the Edifier app cannot connect. The speaker accepts only one BLE connection, so to hand it to the app entirely, turn off Settings → Devices & services → **Edifier BLE** → System options → *Enable polling for changes* (needs Advanced Mode); the same switch is available through `config_entries/update` with `"pref_disable_polling": true`. That indicator flips with every command, so it is **disabled by default**: enable it on the entity's settings page if you want to watch the link. **Online** is not disabled — it is the reachability signal.

**Observed on tested hardware (not guarantees for every host or firmware)**

- **M60 observations on a desktop Linux PC (firmware 2.4.1):** with no music, four BLE connections succeeded but exposed **0 GATT services**; with phone audio streaming, the PC read the full control state. Idle connects sometimes took about 30 seconds, and advertisements varied by input state. These observations do not establish behavior on every host or firmware. See the [M60 reference](docs/edifier-m60-ble.md).
- Playback buttons forward AVRCP without an ACK or state query: M60's effect was observed at a host player, M90's player-side effect was not documented, and play/pause state plus track metadata stay unknown.
- Audio `0x68` values are UI codes from the app; `09` was never observed on either model.
The integration does not require Classic Bluetooth pairing. M60 protocol reads have been verified on a PC,
not yet through Home Assistant; its writes (custom EQ, smart light, codec preference) have **not** been
exercised on hardware. Protocol details for each model live in [docs/](docs/).

Tell Home Assistant when a speaker has been unreachable for a while:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.edifier_m90_online   # your entity name will differ
    to: "off"
    for: "00:10:00"
actions:
  - action: persistent_notification.create
    data:
      title: "Edifier M90 offline"
      message: "Not reachable for ten minutes."
```

For a support report, use **Download diagnostics** (Settings → Devices & services → **Edifier BLE** → three-dot menu): model, link and polling state, the last update result with Home Assistant's reachability explanation, and the last state snapshot. Bluetooth addresses and user-set speaker names are redacted, including in error text; review the file before sharing it. The integration has no credentials.

**Removal.** Delete **Edifier BLE** in Settings → Devices & services, remove the `custom_components/edifier_ble` directory, then restart. Nothing on the speaker changes.

Protocol tests run without Home Assistant: `python -m unittest discover -s tests -v`. The integration is also checked with `mypy --strict` against Home Assistant's own type information, using `mypy.ini`; run it inside the Home Assistant container, where both the integration and Home Assistant are importable:

```text
PYTHONPATH=$PWD:/usr/src/homeassistant python3 -m mypy
```

BLE addresses are used as device identifiers, which assumes a stable discoverable address; protocol tests use mocked BLE.

Every push runs the same checks in CI, inside the Home Assistant container: `unittest`, `mypy --strict` and a coverage gate of 95%, plus hassfest and the HACS repository validation. The integration is MIT licensed.

Test coverage is measured the same way, in the same container:

```text
PYTHONPATH=$PWD python3 -m coverage run --branch --source=custom_components/edifier_ble -m unittest discover -s tests
python3 -m coverage report
```

## Branding

The integration icon and logo are the Edifier wordmark as published in Home Assistant's [brands repository](https://github.com/home-assistant/brands/tree/master/core_integrations/edifier_infrared), where the same artwork is used for Home Assistant's own Edifier integration, with the dark-theme variants included. The files are shipped unmodified. Edifier and the Edifier logo are trademarks of Edifier; this integration is unofficial and is not affiliated with or endorsed by Edifier.

## Scope and safety

The current references cover BLE controls, not firmware updates or the Bluetooth audio transport. Track metadata may need to come from the audio source rather than the speaker. Firmware revisions may behave differently.

Commands that rename, switch inputs, change audio settings, or disconnect a link can disrupt playback. Read and record the current value first, then check the result and restore it if testing. Do not assume the speaker reconnects automatically. Reset, OTA and pairing-management commands are outside the tested scope.
