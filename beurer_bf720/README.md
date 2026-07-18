# Beurer BF720 Scale

Read a Beurer BF720 body-composition scale over Bluetooth and publish per-user
measurements to Home Assistant via MQTT auto-discovery.

Each on-scale profile becomes its own device with sensors for weight, body fat,
muscle, body water, BMI, basal metabolism, muscle/water mass, and impedance.

Requires the **Mosquitto broker** add-on + the **MQTT integration**, and a
Bluetooth adapter on the host.

See [DOCS.md](DOCS.md) for setup, options, and how to obtain each profile's
consent PIN.
