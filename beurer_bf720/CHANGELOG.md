# Changelog

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
