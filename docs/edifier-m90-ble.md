# Edifier M90 BLE protocol reference

**Scope:** M90 BLE controls, tested on a real unit unless explicitly noted otherwise. Names and option labels come from EDIFIER ConneX; untested commands or meanings are marked where they appear. This controls the speaker, not the Bluetooth audio stream. An ACK alone does not prove a setting changed.

## Device profile

| Property | M90 |
|---|---|
| BLE advertisement name | `EDIFIER BLE` (addresses vary by unit; omitted here) |
| Device name (`0xC9`) | `EDIFIER M90` on the tested unit; user-changeable |
| ConneX search UUID (app profile) | `00004503-0000-1000-8000-00805f9b34fb` |
| GATT service | `48094503-1a48-11e9-ab14-d663bd873d93` |
| Read/notify characteristic | `48090001-1a48-11e9-ab14-d663bd873d93` |
| Write characteristic | `48090002-1a48-11e9-ab14-d663bd873d93` |

M60 and M90 share characteristic UUIDs, **not** service UUIDs or every payload mapping. `0xC8` returns a unit-specific Classic audio address; do not use another owner's value. The M90 ConneX profile does not list an SPP UUID.

## Frame format

```text
AA EC opcode length_hi length_lo payload... checksum   host request
BB EC opcode length_hi length_lo payload... checksum   speaker reply
```

Length is the payload size (16-bit big-endian); checksum is the low byte of the sum of all preceding bytes. Sub Out uses application code `ED` (`AA ED` / `BB ED`); rename and timed-off setter ACKs use `CC EC`. An ACK is distinct from a query response.

## D8 capability response

Query: `AA EC D8 00 00 6E`. The 29-byte capability payload was:

```text
00 00 01 04 01 01 00 00 00 02 01 01 0A 48 00
00 00 20 00 03 84 20 41 91 00 00 20 00 10
```

| Offset(s) | Raw | App interpretation |
|---|---|---|
| `b0`–`b1` | `00 00` | No ANC/TWS or battery-display flags. |
| `b2`–`b5` | `01 04 01 01` | Name read/write, Classic address read, firmware read; app limits rename to 35 UTF-8 bytes. |
| `b6`–`b8` | `00 00 00` | No A2DP-disconnect, repair or no-audio auto-shutdown flags. |
| `b9`–`b11` | `02 01 01` | Timed power-off, device-off, manual/help flags. |
| `b12` | `0A` | BLE OTA flags; not tested. |
| `b13` | `48` | M90 EQ profile, **not** current preset. |
| `b17` | `20` | Reset advertised; not tested. |
| `b19`–`b21` | `03 84 20` | Source/volume, Hi-Res status/multipoint, prompt tone. |
| `b22`–`b23` | `41 91` | HD-codec UI, pairing-log, power-save, line Hi-Res, stereo/setup flags. |
| `b26`, `b28` | `20`, `10` | Power-on-volume memory, Sub Out. |

Capability flags are not proof that a setter works.

## Command reference

### Device metadata

| Function | Request / response | Evidence |
|---|---|---|
| Name | `0xC9` query `AA EC C9 00 00 5F`; example response `BB EC C9 00 0B 45 44 49 46 49 45 52 20 4D 39 30 49` | UTF-8 `EDIFIER M90`. `0xCA` writes UTF-8 name; rename/read-back/restore verified, ACK `CC EC CA 00 01 01 84`. |
| Firmware | `AA EC C6 00 00 5C` → `BB EC C6 00 03 02 05 01 78` | Firmware `2.5.1` on this unit; other units may differ. |
| Classic address | `AA EC C8 00 00 5E` → 6-byte address payload | Response matched advertisement manufacturer data. Actual address/frame omitted for privacy. |

### Input source

`0x61` queries `<group> <source>`; `0x62` sets it. **M90 group is `1D`**, not M60's `0F`. All five selections were set and read back; setter ACK: `BB EC 62 00 01 01 0B`.

| Source | Input | Set request | Selected-state reply |
|---|---|---|---|
| `01` | Bluetooth | `AA EC 62 00 02 1D 01 18` | `BB EC 61 00 02 1D 01 28` |
| `02` | USB | `AA EC 62 00 02 1D 02 19` | `BB EC 61 00 02 1D 02 29` |
| `03` | HDMI | `AA EC 62 00 02 1D 03 1A` | `BB EC 61 00 02 1D 03 2A` |
| `04` | Optical | `AA EC 62 00 02 1D 04 1B` | `BB EC 61 00 02 1D 04 2B` |
| `05` | AUX | `AA EC 62 00 02 1D 05 1C` | `BB EC 61 00 02 1D 05 2C` |

Allow ~2–3 s for source read-back to settle. Selection was confirmed by BLE; these tests did **not** establish audio playback on every physical input. A connected-device notification `0xAD` arrived on Bluetooth selection; its unit-specific payload is omitted.

### Volume

`0x66` query `AA EC 66 00 00 FC` replies `<maximum> <current>`; maximum is `32` (50 decimal). Set with `0x67` and one volume byte `00`–`32`: `AA EC 67 00 01 <V> <(FE+V) mod 256>`. `BB EC 66 00 02 32 08 49` shows one 8/50 reading; an earlier session reported a zero/mute test, but this reference does not include its setter/read-back frames or an acoustic check. No dB/step was measured. Do not reuse M60's 0–16 range.

### Media playback

`0xC2` sends one AVRCP action byte, with no BLE ACK/query. These four requests were exercised; external player-side verification is **not documented** for M90, so this is not proof each action reached a player:

| Action | App meaning | Request frame |
|---|---|---|
| `00` | Play | `AA EC C2 00 01 00 59` |
| `01` | Pause | `AA EC C2 00 01 01 5A` |
| `04` | Next | `AA EC C2 00 01 04 5D` |
| `05` | Previous | `AA EC C2 00 01 05 5E` |

Other values and speaker-side track-title metadata remain **unknown**. Obtain metadata from the audio-source player unless independently verified.

### Preset EQ

Query `AA EC D5 00 00 6B` returns one preset byte; set `0xC4` with one byte. All four values were set and read back (setter ACK `BB EC C4 00 01 01 6D`). Labels are from the M90 app profile 48, not M60.

| Value | Label | Set request | Selected-state reply |
|---|---|---|---|
| `00` | Classic | `AA EC C4 00 01 00 5B` | `BB EC D5 00 01 00 7D` |
| `01` | Monitor | `AA EC C4 00 01 01 5C` | `BB EC D5 00 01 01 7E` |
| `02` | Dynamic | `AA EC C4 00 01 02 5D` | `BB EC D5 00 01 02 7F` |
| `03` | Custom | `AA EC C4 00 01 03 5E` | `BB EC D5 00 01 03 80` |

### Custom EQ

Query `AA EC 43 00 00 D9`. M90 layout: `<format=10> <band_count=09> <nine 4-byte records> <4-byte date> [<UTF-8 name>]`; each record is `<index> <freq_hi> <freq_lo> <gain>`. ConneX band centers: 62, 125, 250, 500, 1k, 2k, 4k, 8k, 16k Hz. The tested unit's 9 baseline gain codes were `06` (0 dB in the app); its exact date suffix is omitted as unit-specific.

`0x44` sets one 4-byte record. Band 0 `06 → 07 → 06` used `AA EC 44 00 04 00 00 3E 07 23` and restore `AA EC 44 00 04 00 00 3E 06 22`; both ACKed `BB EC 44 00 01 01 ED`, changed band 0 in read-back, then restored the original EQ frame. Other M90 bands' writes were **not** individually verified. App gain scale, not an acoustic measurement: `(code − 6) × 0.5 dB`; `06` maps to 0 dB. Behavior above the documented range is not independently established here.

`0x47` writes `<4-byte little-endian Unix date><name UTF-8>`. A temporary name/date was read back, then the original suffix restored byte-identically; the test timestamp and name payload are omitted. **M60 uses 6 bands of 6 bytes instead.**

### Codec status/preferences

M90 advertises HD-codec control in D8 `b22 = 41` rather than M60's `b18` LDAC command family. `0x91` query `AA EC 91 00 00 27` → `BB EC 91 00 02 0E 01 49`. ConneX decodes `0E` as its feature index and `01` as LDAC preference (44.1/48 kHz option); app options: `00` default/LDAC disabled, `01` 44.1/48 kHz, `02` 96 kHz. These are **settings**, not a measurement of the active stream or bitrate.

`0x92` setter payload is `<feature_index> <ldac_mode> <lhdc_mode>`. **Only a same-value write was tested:** `AA EC 92 00 03 0E 01 FF 39` → ACK `BB EC 92 00 02 0F 01 4B` → `0x91` still read `0E 01`. **Changing the M90 mode to another value was not tested**, so do not present `00`/`02` as live-verified M90 setters or infer LHDC support from the packet layout.

### Prompt tone

Query `AA EC 86 00 00 1C` returns `<tone-index> <state>`; M90 returned index `02` (Bluetooth connection tone). `0x87` sets `<index=02> <type=01> <state>`:

| State | Set request | Selected-state reply |
|---|---|---|
| Off `00` | `AA EC 87 00 03 02 01 00 23` | `BB EC 86 00 02 02 00 31` |
| On `01` | `AA EC 87 00 03 02 01 01 24` | `BB EC 86 00 02 02 01 32` |

Both changes ACKed, read back and original state restored.

### Lighting and output

M90 has **Sub Out**, not M60 smart lighting. Commands use application code `ED`. Query `AA ED 13 00 00 AA` returns `<index=00> <level>`; `0x14` sets those two bytes:

| Level | App label | Set request | Selected-state reply |
|---|---|---|---|
| `00` | Low | `AA ED 14 00 02 00 00 AD` | `BB ED 13 00 02 00 00 BD` |
| `01` | Medium | `AA ED 14 00 02 00 01 AE` | `BB ED 13 00 02 00 01 BE` |
| `02` | High | `AA ED 14 00 02 00 02 AF` | `BB ED 13 00 02 00 02 BF` |

All three changes ACKed (`BB ED 14 ...`), read back and the original state restored. Acoustic response was not measured.

### Other settings

| Function | Request / response | Interpretation / limit |
|---|---|---|
| A2DP state `0xC3` | `AA EC C3 00 00 59` → `BB EC C3 00 01 03 6E` | `03` observed with transport closed / switched away from Bluetooth. `0D` is observed on M60 for open transport; not independently established for M90. |
| Audio decoding `0x68` | `AA EC 68 00 00 FE` → `BB EC 68 00 01 00 10` | `00` during a phone connection. The app maps `04` to wireless Hi-Res, `05` to wired Hi-Res, and `09` to 192 kHz; these values were **not observed on M90**. Do not infer the negotiated codec solely from `00`. |
| Timed power-off | `0xD3` query `AA EC D3 00 00 69` → `BB EC D3 00 02 00 00 7C` | Set 15 min using `0xD1` (`AA EC D1 00 02 00 0F 78`), ACK `CC EC D1 00 01 01 8B`, read back `00 0F`; cancel `0xD2` (`AA EC D2 00 00 68`), ACK `CC EC D2 00 01 01 8C`, read back `00 00`. |
| Multipoint | `0x7C` query `AA EC 7C 00 00 12` → `BB EC 7C 00 02 00 00 25` | `0x7D` setter `<index=00> <state>` off→on→off, ACK and read-back verified. On request `AA EC 7D 00 02 00 01 16`. |
| Power save | `0xB1` query `AA EC B1 00 00 47` → `BB EC B1 00 01 01 5A` | `0xB2` setter `<state>` on→off→on, ACK and read-back verified. Off request `AA EC B2 00 01 00 49`. |
| Device shutdown | `0xCE` (no query) | A previous session reported that `AA EC CE 00 00 64` shut the device down; no BLE reply expected. Do not use in unattended automation. |
| Connected-device notification | `0xAD` pushed on Bluetooth selection | Includes a connected device name and other unit-specific bytes; raw payload omitted for privacy. Layout of the remaining bytes is **unknown**. |

## Observed state and test history

M90 source selections, EQ presets, Sub Out, prompt tone, power save, multipoint, timed-off and rename were exercised on hardware, read back and temporary changes restored. Custom EQ band 0 and name/date were restored byte-identically. HD-codec setter was **same-value only**. Input audio, AVRCP player effects, alternate M90 `0x68` values, codec renegotiation and acoustic response were not established by these BLE captures. These observations describe tested firmware and host conditions, **not every M90 unit or firmware**.

## Limitations and safety

- **Unverified:** mode-changing HD-codec writes, player-side AVRCP behavior, every physical input's audio, additional `0x68` values on M90, metadata paths and acoustic response. App capability flags alone are not execution proof.
- Allow ~3 s for source transitions; an ACK or immediate status query may be stale. Do not assume automatic Classic reconnection after any future codec change. BLE monitoring should not initiate pairing.
- No reset, OTA, pairing, unpairing or clear-pairing protocol command was used in this reference. The 2.4 GHz RF remote is outside the BLE scope and requires suitable RF capture equipment.

## Mapping provenance

EDIFIER ConneX Android APK: `products_release.json`, `D8Bean.java`, `CommandManager.java`, `CommandParser.java`, `CmdParserExtKt.java`, `HDAudioCodeActivity.java`, `DualDeviceConnectionActivity.java` and `SubOutAc.java`. Do not copy another Edifier model's opcode meanings without testing.
