# Beurer BF720 for Home Assistant

Read a **Beurer BF720** Bluetooth body-composition scale (and the protocol-compatible
**BF105**) into Home Assistant — weight and native body composition (body fat, muscle,
water, BMI, basal metabolism, impedance) with full **multi-user** support.

A native `custom_component` that uses Home Assistant's own Bluetooth stack: entities directly,
no MQTT broker, works with a host adapter or an ESP32 BLE proxy, on any HA install (OS,
Supervised, Container, Core). The BLE frame decoding lives in one place
(`custom_components/beurer_ble/parser.py`) and is unit-tested (`tests/test_parser.py`).

## Install

Install via [HACS](https://hacs.xyz/) as a custom repository, or copy
`custom_components/beurer_ble/` into your HA `config/custom_components/`. Restart Home Assistant,
let the scale auto-discover, and add each user (name, index, PIN) in the config flow.

## Getting the consent PIN

The scale stores a separate 4-digit **consent PIN per user profile**. Wake the scale, select the
profile, enter its Bluetooth/pairing mode — the scale shows its PIN. Note the PIN and the profile
**index** (slot 1, 2, 3 …). The scale computes body composition from the profile's
height/age/gender, so map each configured user to the correct profile.

## Bonding on Home Assistant OS (BlueZ)

The scale's body-composition data lives behind an *encrypted* User Data characteristic. On most
setups this just works — CoreBluetooth and ESP32 BLE proxies bond transparently, and the
integration also makes a best-effort `pair()` on connect. If, on a HAOS host adapter, you only
get weight but no body composition, bond the scale once at the OS level and the persistent bond
fixes it:

```sh
bluetoothctl
# in the prompt:
pair  AA:BB:CC:DD:EE:FF     # the scale's address
trust AA:BB:CC:DD:EE:FF
```

## Credits & licence

Protocol knowledge derives from [openScale](https://github.com/oliexdev/openScale) and
[ble-scale-sync](https://github.com/KristianP26/ble-scale-sync), both GPL-3.0. Licensed under
**GPL-3.0** — see [LICENSE](LICENSE).
