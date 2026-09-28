# Edifier M60 BLE protocol reference

**Scope:** M60 BLE controls observed on a real unit (firmware 2.4.1) using a desktop Linux PC. Protocol reads were verified on that PC; M60 state reads through Home Assistant have **not** been verified. Names and option labels come from EDIFIER ConneX 1.0.30; untested commands or meanings are marked where they appear. This controls the speaker, not the Bluetooth audio stream. An ACK alone does not prove a setting changed.

## Device profile

| Property | M60 |
|---|---|
| BLE advertisement name | `EDIFIER BLE`; sometimes no name is advertised while idle (addresses vary by unit; omitted here) |
| Device name (`0xC9`) | `EDIFIER M60` on the tested unit; user-changeable |
| ConneX search UUID (app profile) | `0000f600-0000-1000-8000-00805f9b34fb` |
| GATT service | `4809f601-1a48-11e9-ab14-d663bd873d93` |
| Read/notify characteristic | `48090001-1a48-11e9-ab14-d663bd873d93` |
| Write characteristic | `48090002-1a48-11e9-ab14-d663bd873d93` |

M60 and M90 share characteristic UUIDs, **not** service UUIDs or every payload mapping. `0xC8` returns a unit-specific Classic audio address; do not use another owner's value.

## Observed BLE availability

On the tested PC, BLE advertisements were intermittent with no music (including a 90-second scan with none), but appeared while Bluetooth audio streamed. Four idle `bluetoothctl connect` attempts succeeded; GATT exposed **0 services** then. With music streaming from a phone, the PC connected over BLE and read the control service and full state. An idle PC connection took around 30 seconds in those tests. USB-input observations also found periods with no BLE advertisements or Classic inquiry responses. These observations are from one unit and PC; other firmware and setups have not been tested.

## Frame format

```text
AA EC opcode length_hi length_lo payload... checksum   host request
BB EC opcode length_hi length_lo payload... checksum   speaker reply
```

Length is the payload size (16-bit big-endian); checksum is the low byte of the sum of all preceding bytes. Some setter ACKs use `CC EC` (notably rename). An ACK is distinct from a query response.

## D8 capability response

Query: `AA EC D8 00 00 6E`. The 22-byte capability payload was:

```text
00 00 01 04 01 01 01 00 00 00 01 01 0A 13 01 00 00 20 04 03 04 30
```

| Offset(s) | Raw | App interpretation |
|---|---|---|
| `b1` | `00` | No battery display. |
| `b2`–`b5` | `01 04 01 01` | Name read/write, Classic address read, firmware read; app limits rename to 35 UTF-8 bytes. |
| `b6` | `01` | A2DP disconnect advertised; A2DP-only behavior **unproven**. |
| `b8`–`b10` | `00 00 01` | No timed/no-audio shutdown; device-off advertised. |
| `b12` | `0A` | BLE OTA flags; not tested. |
| `b13` | `13` | EQ profile 19, **not** current preset. |
| `b17` | `20` | Reset advertised; not tested. |
| `b18` | `04` | LDAC control; no LHDC advertised. |
| `b19`–`b21` | `03 04 30` | Source/volume, Hi-Res status, smart-light/prompt-tone controls. |

Capability flags are not proof that a setter works.

## Command reference

### Device metadata

| Function | Request / response | Evidence |
|---|---|---|
| Name | `0xC9` query `AA EC C9 00 00 5F`; example response `BB EC C9 00 0B 45 44 49 46 49 45 52 20 4D 36 30 46` | UTF-8 `EDIFIER M60`. `0xCA` writes UTF-8 name; rename/read-back/restore verified, ACK `CC EC CA 00 01 01 84`. Device stored 36-byte names but truncated longer tests; ConneX limits input to 35 bytes. |
| Firmware | `AA EC C6 00 00 5C` → `BB EC C6 00 03 02 04 01 77` | Firmware `2.4.1` on this unit; other units may differ. |
| Classic address | `AA EC C8 00 00 5E` → 6-byte address payload | Response matched advertisement manufacturer data. Actual address/frame omitted for privacy. |

### Input source

`0x61` queries `<group> <source>`; `0x62` sets it. **M60 group is `0F`**, not M90's `1D`. All three selections were set and read back; setter ACK: `BB EC 62 00 01 01 0B`.

| Source | Input | Set request | Selected-state reply |
|---|---|---|---|
| `01` | Bluetooth | `AA EC 62 00 02 0F 01 0A` | `BB EC 61 00 02 0F 01 1A` |
| `02` | USB | `AA EC 62 00 02 0F 02 0B` | `BB EC 61 00 02 0F 02 1B` |
| `03` | AUX | `AA EC 62 00 02 0F 03 0C` | `BB EC 61 00 02 0F 03 1C` |

Allow ~2–3 s for source read-back to settle. USB playback was heard: UAC 1 stereo PCM (`S16_LE`/`S24_3LE`, 48/96 kHz). AUX was selected and read back, **not** acoustically checked.

### Volume

`0x66` query `AA EC 66 00 00 FC` replies `<maximum> <current>`; maximum is `10` (16 decimal). Set with `0x67` and one volume byte `00`–`10`: `AA EC 67 00 01 <V> <(FE+V) mod 256>`. `01 → 00 → 01` set/ACK/read-back; `00` silenced audio by ear. Example `00` request `AA EC 67 00 01 00 FE` → ACK `BB EC 67 00 02 10 00 20` → query `BB EC 66 00 02 10 00 1F`. dB per step is **unknown**; do not reuse M90's 0–50 range.

### Media playback

`0xC2` sends one AVRCP action byte, with no BLE ACK/query. These requests were observed to control a registered host player:

| Action | Meaning | Request |
|---|---|---|
| `00` | Play | `AA EC C2 00 01 00 59` |
| `01` | Pause | `AA EC C2 00 01 01 5A` |
| `04` | Next | `AA EC C2 00 01 04 5D` |
| `05` | Previous | `AA EC C2 00 01 05 5E` |

`02`, `03`, `06`–`0F` made no player call in this test; do not assign meanings to them. Metadata probes (`0x01`, `0x02`, `0x50`–`0x52`) produced no title/artist over BLE while idle or playing; **not proof that every metadata path is absent**. Read titles from the audio-source player for now.

### Preset EQ

Query `AA EC D5 00 00 6B` returns one preset byte; set `0xC4` with one byte. All five values were set and read back. Labels are from the M60 app profile 19, not M90.

| Value | Label | Set request | Selected-state reply |
|---|---|---|---|
| `00` | Music | `AA EC C4 00 01 00 5B` | `BB EC D5 00 01 00 7D` |
| `01` | Monitor | `AA EC C4 00 01 01 5C` | `BB EC D5 00 01 01 7E` |
| `02` | Game | `AA EC C4 00 01 02 5D` | `BB EC D5 00 01 02 7F` |
| `03` | Movie | `AA EC C4 00 01 03 5E` | `BB EC D5 00 01 03 80` |
| `04` | Customized | `AA EC C4 00 01 04 5F` | `BB EC D5 00 01 04 81` |

### Custom EQ

Query `AA EC 43 00 00 D9`. M60 layout: `<format=03> <band_count=06> <six 6-byte records> [<4-byte date> [<UTF-8 name>]]`; each record is `<index> <filter/raw> <freq_hi> <freq_lo> <gain> <Q>`. ConneX band centers: 62, 250, 1k, 4k, 8k, 16k Hz. The device can add the date/name suffix after a write.

`0x44` sets one 6-byte record. With Customized selected, band 0 `06 → 07 → 06` used `AA EC 44 00 06 00 00 00 3E 07 07 2C` and restore `AA EC 44 00 06 00 00 00 3E 06 07 2B`; both ACKed `BB EC 44 00 01 01 ED` and only the intended band changed in read-back. All six bands were tested and restored separately. `0D`/`0E` requests read back clamped to `0C`.

App gain scale, not an acoustic measurement: `(code − 6) × 0.5 dB`; `06` = 0 dB, `0C` = +3 dB. `0x47` writes `<4-byte little-endian Unix date><name UTF-8>`; temporary date/name writes were read back and restored. A date-only write can be used; do not treat the suffix as a fixed length. **M90 uses 9 bands of 4 bytes instead.**

### Codec status/preferences

`0x48` queries LDAC preference; `0x49` sets one option byte:

| Value | App option | Set request | Query reply |
|---|---|---|---|
| `00` | Default codec / LDAC disabled | `AA EC 49 00 01 00 E0` | `BB EC 48 00 01 00 F0` |
| `01` | 44.1/48 kHz preference | `AA EC 49 00 01 01 E1` | `BB EC 48 00 01 01 F1` |
| `02` | 96 kHz preference | `AA EC 49 00 01 02 E2` | `BB EC 48 00 01 02 F2` |

All options changed and read back after reconnection. On one PipeWire/BlueZ host with LDAC support, `02` exposed an active 96 kHz LDAC sink and `0x68 = 04`; `00` exposed only SBC variants. This is host-dependent, not proof of bitrate, losslessness or audibly improved quality. Bluetooth-mode `0x49` writes may drop both BLE and Classic, sometimes with ATT `0x0E` and no ACK **despite storing the value**; reconnect manually from the host UI, then query. One AUX-mode ACK did not change the preference. These writes may also reset smart-light sensitivity.

### Prompt tone

Query `AA EC 86 00 00 1C` returns `<tone-index> <state>`; the M60 returned one entry, index `02` (Bluetooth connection tone). `0x87` sets `<index=02> <type=01> <state>`:

| State | Set request | Selected-state reply |
|---|---|---|
| Off `00` | `AA EC 87 00 03 02 01 00 23` | `BB EC 86 00 02 02 00 31` |
| On `01` | `AA EC 87 00 03 02 01 01 24` | `BB EC 86 00 02 02 01 32` |

Both changes ACKed, read back and original state restored. Other ConneX tone types were not established on M60.

### Lighting and output

M60 has **smart light**, not M90 Sub Out. Query `AA EC 84 00 00 1A` returns `<index=03> <timer> <sensitivity>`; `0x85` sets the same three-byte payload.

| Field | Tested values | App meanings |
|---|---|---|
| Timer | `00`, `01`, `02`, `03` | 5 s, 10 s, 20 s, always on. |
| Sensitivity | `00`, `01`, `02` | High, General, Low. |

Set/ACK/read-back for each timer and sensitivity value; e.g. `AA EC 85 00 03 03 01 01 23` → `BB EC 85 00 03 03 01 01 34` → `BB EC 84 00 03 03 01 01 33`. Timer persisted over a power cycle; sensitivity reset to `00` after a power cycle or LDAC write but survived an `0xCD` disconnect/reconnect. Both original values were restored after testing.

### Other settings

| Function | Request / response | Interpretation / limit |
|---|---|---|
| A2DP state `0xC3` | `AA EC C3 00 00 59` → `BB EC C3 00 01 03 6E` | `03` closed; `0D` after a stream opened transport. `0D` could persist after playback stopped. |
| Audio decoding `0x68` | `AA EC 68 00 00 FE` → `BB EC 68 00 01 00 10` | `00` on USB 48 kHz / standard BT, `04` on active 96 kHz LDAC, `05` on USB 96 kHz and AUX; status may lag. The app shows `04` as wireless Hi-Res, `05` as wired Hi-Res, and `09` as 192 kHz (**not observed on M60**). These are UI/status codes, not codec identifiers. |
| A2DP disconnect `0xCD` | `AA EC CD 00 00 63`; no protocol reply | On tested host the entire BLE/Classic connection dropped along with A2DP. A2DP-*only* scope unproven. |
| Headset state `0xF2` | `AA EC F2 00 00 88`; no accepted reply | App parser expects headset battery/TWS fields. M60 advertises no battery; not a verified speaker-state query. |

## Observed state and test history

Reversible M60 controls were read back and temporary changes restored, except the chosen LDAC preference retained after testing. AVRCP was checked at the host player, USB playback by ear, and audio-decoding status against active stream conditions. No dB/step or EQ acoustic response measurement was made. These observations describe tested firmware and host conditions, **not every M60 unit or firmware**.

## Limitations and safety

- **Unverified:** A2DP-only disconnect, M60 AUX audio playback, every possible metadata path, unobserved `0x68` values and acoustic response. App capability flags alone are not execution proof.
- Allow ~3 s for source transitions. An ACK or immediate status query may be stale. LDAC writes can disconnect both links; **do not assume auto-reconnect**. BLE monitoring should not initiate pairing.
- No reset, OTA, shutdown, pairing, unpairing or clear-pairing *protocol* command was used in this reference. A Classic bond was manually re-created using a host Bluetooth UI during testing, separate from the protocol tests.

## Mapping provenance

EDIFIER ConneX 1.0.30 Android APK: `D8Bean.java`, `CommandManager.java`, `CommandParser.java`, `CmdExtKt.java`, `ResManager.java` and related device UI classes. Do not copy another Edifier model's opcode meanings without testing.
