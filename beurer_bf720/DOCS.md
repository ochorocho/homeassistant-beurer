# Beurer BF720 Scale add-on

Reads a **Beurer BF720** body-composition scale over Bluetooth and publishes
per-user measurements to Home Assistant through **MQTT auto-discovery**. Each
on-scale profile becomes its own device with sensors for weight, body fat,
muscle, water, BMI, basal metabolism, and more.

## Requirements

- Home Assistant OS or Supervised (add-ons don't run on Container/Core).
- The **Mosquitto broker** add-on installed and the **MQTT integration** set up
  (this add-on pulls the broker credentials from the Supervisor automatically).
- A Bluetooth adapter reachable by the host (built-in, USB, or the scale in range).
- The **consent PIN** for each user profile you want to read (see below).

> **Bluetooth note:** this add-on talks to the host's BlueZ over D-Bus. If Home
> Assistant's own *Bluetooth* integration is actively using the same adapter,
> the two can contend for it. Prefer a dedicated adapter for the scale, or the
> native `beurer_ble` custom component instead of this add-on if you want to
> share one adapter with other Bluetooth devices.

## Getting the consent PIN

The scale stores a separate 4-digit **consent PIN** per user profile:

1. Wake the scale and select the profile you want.
2. Enter that profile's Bluetooth/pairing mode — the scale shows its PIN.
3. Note the PIN and the profile **index** (slot number, usually 1, 2, 3 …).

Each profile has its own PIN. The scale computes body-fat/muscle from the
profile's height/age/gender, so map each configured user to the right profile.

## Installation

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add
   `https://github.com/ochorocho/ha_beurer`.
2. Install **Beurer BF720 Scale**.
3. Open **Configuration** and add your users (see options below).
4. **Start** the add-on and watch the **Log** tab.

## Options

```yaml
scale_address: ""        # optional: pin to one scale's MAC/UUID (blank = auto-detect)
scan_interval: 30        # seconds between scan/read cycles
debug: false
users:
  - name: "Jochen"
    user_index: 3        # on-scale profile slot
    pin: 1234            # that profile's consent PIN
```

| Option | Description |
| --- | --- |
| `scale_address` | Optional MAC/UUID to target a specific scale. Leave blank to auto-detect a `BF720`. |
| `scan_interval` | Seconds between BLE scan/read cycles (10–3600). |
| `debug` | Verbose logging. |
| `users` | One entry per on-scale profile: `name`, `user_index`, and `pin`. |

## What you get

For each configured user, an MQTT device **BF720 <name>** appears in Home
Assistant with sensors: Weight, Body fat, Muscle, Body water, BMI, Basal
metabolism, Muscle mass, Water mass, Impedance.

Do a weigh-in; on the next scan cycle the sensors update. Measurements the scale
recorded while the add-on was disconnected are replayed on the next connection.
