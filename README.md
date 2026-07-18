# Beurer BF720 for Home Assistant

Read a **Beurer BF720** Bluetooth body-composition scale (and the protocol-compatible
**BF105**) into Home Assistant — weight and native body composition (body fat, muscle,
water, BMI, basal metabolism, impedance) with full **multi-user** support.

This repo ships **two ways** to use it — pick one:

| | **Add-on** (`beurer_bf720/`) | **Integration** (`custom_components/beurer_ble/`) |
| --- | --- | --- |
| Runs on | HA OS / Supervised only | Any HA install (OS, Supervised, Container, Core) |
| Data path | Docker container → **MQTT** discovery | Native HA Bluetooth → entities |
| Needs MQTT broker | Yes | No |
| ESP32 Bluetooth proxy | No (host adapter) | Yes (native) |
| Install | Add-on Store (add this repo) | HACS custom repo / copy folder |

Both do the same BLE consent handshake and decode the same measurements; the code is shared
and unit-tested (`tests/test_parser.py`).

---

## Option A — Add-on (Settings → Add-ons)

A Supervisor add-on (Docker) that reads the scale and publishes to HA over MQTT auto-discovery.

**Requirements:** HA OS/Supervised, the **Mosquitto broker** add-on + **MQTT integration**, a
host Bluetooth adapter.

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add this repository's URL.
2. Install **Beurer BF720 Scale**, open **Configuration**, add your users:
   ```yaml
   users:
     - name: "Jochen"
       user_index: 3
       pin: 1234
   ```
3. **Start** the add-on. Each user appears as an MQTT device with body-composition sensors.

Full details: [`beurer_bf720/DOCS.md`](beurer_bf720/DOCS.md).

> The add-on uses the host's BlueZ. If HA's own *Bluetooth* integration is using the same
> adapter they can contend for it — prefer a dedicated adapter, or use the integration below.

---

## Option B — Integration (HACS custom component)

A native `custom_component` that uses Home Assistant's Bluetooth stack (works with ESP32 BLE
proxies, no MQTT). Install via HACS as a custom repository, or copy
`custom_components/beurer_ble/` into your HA `config/custom_components/`. Restart, let the scale
auto-discover, and add each user (name, index, PIN) in the config flow.

## Getting the consent PIN

The scale stores a separate 4-digit **consent PIN per user profile**. Wake the scale, select the
profile, enter its Bluetooth/pairing mode — the scale shows its PIN. Note the PIN and the profile
**index** (slot 1, 2, 3 …). The scale computes body composition from the profile's
height/age/gender, so map each configured user to the correct profile.

## Credits & licence

Protocol knowledge derives from [openScale](https://github.com/oliexdev/openScale) and
[ble-scale-sync](https://github.com/KristianP26/ble-scale-sync), both GPL-3.0. Licensed under
**GPL-3.0** — see [LICENSE](LICENSE).
