# Changelog

## 0.1.2

- Fix "Characteristic 2A9F not found" / repeated "device disconnected" on
  Home Assistant OS. The BF720's User Data service needs a bonded/encrypted link
  on BlueZ: register a BlueZ pairing agent (bleak's `pair()` needs one to exist),
  bond before subscribing, mark the device Trusted so reconnects reuse the bond,
  and re-read services on the encrypted link. Adds a `dbus-fast` dependency.

## 0.1.1

- Fix crash on startup (`TypeError: string indices must be integers`): read the
  add-on options (especially the `users` list) directly from `/data/options.json`
  instead of passing a complex list through a bashio environment variable.
- Harden user parsing: tolerate odd shapes (entries as JSON strings, string
  numbers), skip malformed entries with a clear warning, and log the loaded user
  indices at startup.

## 0.1.0

- Initial release.
- Reads a Beurer BF720 over Bluetooth (per-user consent handshake).
- Publishes weight + native body composition (fat, muscle, water, BMI, BMR,
  masses, impedance) to Home Assistant via MQTT auto-discovery.
- Multi-user: one MQTT device per configured on-scale profile.
