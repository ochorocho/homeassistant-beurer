# Changelog

## 0.1.0

- Initial release.
- Reads a Beurer BF720 over Bluetooth (per-user consent handshake).
- Publishes weight + native body composition (fat, muscle, water, BMI, BMR,
  masses, impedance) to Home Assistant via MQTT auto-discovery.
- Multi-user: one MQTT device per configured on-scale profile.
