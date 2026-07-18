#!/usr/bin/env python3
"""Beurer BF720 -> Home Assistant MQTT bridge (add-on entrypoint).

Scans for the scale, performs the per-user consent handshake, decodes weight +
native body composition, and publishes to Home Assistant via MQTT auto-discovery
(one device per on-scale user). The frame decoders are the same logic unit-tested
in the companion custom_component (tests/test_parser.py).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import sys
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from bleak import BleakClient, BleakScanner

# ─── Config ─────────────────────────────────────────────────────────────────
# Read the add-on options straight from /data/options.json — a list of objects
# (users) does not round-trip cleanly through a bashio env var. Fall back to env
# vars for local (non-add-on) runs.
_OPTIONS_FILE = "/data/options.json"
try:
    with open(_OPTIONS_FILE, encoding="utf-8") as _f:
        _OPTS = json.load(_f)
except (OSError, ValueError):
    _OPTS = {}


def _opt(key: str, env: str, default):
    if key in _OPTS and _OPTS[key] not in (None, ""):
        return _OPTS[key]
    return os.environ.get(env, default)


SCALE_ADDRESS = str(_opt("scale_address", "SCALE_ADDRESS", "")).strip()
SCAN_INTERVAL = int(_opt("scan_interval", "SCAN_INTERVAL", 30))
DEBUG = str(_opt("debug", "DEBUG", "false")).lower() in ("true", "1")


def _normalize_users(raw) -> list[dict]:
    """Coerce the configured users into a clean list of {name, user_index, pin}.

    Tolerant of odd shapes (an entry arriving as a JSON string, string numbers,
    etc.) so a misconfiguration logs a clear warning instead of crashing later.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    if not isinstance(raw, list):
        return []
    users: list[dict] = []
    for entry in raw:
        if isinstance(entry, str):
            try:
                entry = json.loads(entry)
            except ValueError:
                pass
        if not isinstance(entry, dict) or "user_index" not in entry or "pin" not in entry:
            _EARLY_WARNINGS.append(f"Skipping malformed user entry: {entry!r}")
            continue
        try:
            users.append(
                {
                    "name": str(entry.get("name") or f"BF720 user {entry['user_index']}"),
                    "user_index": int(entry["user_index"]),
                    "pin": int(entry["pin"]),
                }
            )
        except (TypeError, ValueError):
            _EARLY_WARNINGS.append(f"Skipping user entry with bad index/pin: {entry!r}")
    return users


_EARLY_WARNINGS: list[str] = []
_raw_users = _OPTS["users"] if "users" in _OPTS else json.loads(os.environ.get("USERS_JSON", "[]"))
USERS = _normalize_users(_raw_users)

MQTT_HOST = os.environ.get("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")

DISCOVERY_PREFIX = "homeassistant"
BASE_TOPIC = "beurer_bf720"
AVAILABILITY_TOPIC = f"{BASE_TOPIC}/status"

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
_LOGGER = logging.getLogger("beurer_bf720")

# ─── BLE constants ──────────────────────────────────────────────────────────
BEURER_COMPANY_ID = 0x0611
CHAR_CURRENT_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"
CHAR_WEIGHT = "00002a9d-0000-1000-8000-00805f9b34fb"
CHAR_BODY_COMPOSITION = "00002a9c-0000-1000-8000-00805f9b34fb"
CHAR_USER_CONTROL_POINT = "00002a9f-0000-1000-8000-00805f9b34fb"
KJ_PER_KCAL = 4.1868
_CONSENT_SETTLE = 3.0


# ─── Frame decoders (identical to the tested custom_component parser) ────────
@dataclass
class WeightFrame:
    weight_kg: float
    timestamp: dt.datetime | None = None
    user_index: int | None = None
    bmi: float | None = None
    height_m: float | None = None


@dataclass
class BodyCompositionFrame:
    fat_pct: float
    bmr_kcal: int | None = None
    muscle_pct: float | None = None
    muscle_mass_kg: float | None = None
    soft_lean_mass_kg: float | None = None
    water_mass_kg: float | None = None
    impedance_ohm: float | None = None
    user_index: int | None = None

    @property
    def is_complete(self) -> bool:
        return bool(self.impedance_ohm)


@dataclass
class Measurement:
    weight_kg: float
    user_index: int | None = None
    timestamp: dt.datetime | None = None
    bmi: float | None = None
    fat_pct: float | None = None
    muscle_pct: float | None = None
    muscle_mass_kg: float | None = None
    water_mass_kg: float | None = None
    water_pct: float | None = None
    impedance_ohm: float | None = None
    bmr_kcal: int | None = None


def _u16(data: bytes, off: int) -> int:
    return int.from_bytes(data[off : off + 2], "little")


def decode_weight(data: bytes) -> WeightFrame:
    flags = data[0]
    off = 1
    raw = _u16(data, off)
    off += 2
    kg = raw * 0.005 if not (flags & 0x01) else raw * 0.01 * 0.45359237
    frame = WeightFrame(weight_kg=round(kg, 2))
    if flags & 0x02:
        year = _u16(data, off)
        try:
            frame.timestamp = dt.datetime(
                year, data[off + 2], data[off + 3], data[off + 4], data[off + 5], data[off + 6]
            )
        except ValueError:
            frame.timestamp = None
        off += 7
    if flags & 0x04:
        frame.user_index = data[off]
        off += 1
    if flags & 0x08:
        frame.bmi = round(_u16(data, off) * 0.1, 1)
        off += 2
        frame.height_m = round(_u16(data, off) * 0.001, 2)
        off += 2
    return frame


def decode_body_composition(data: bytes) -> BodyCompositionFrame:
    flags = _u16(data, 0)
    mm = 0.005 if not (flags & 0x01) else 0.01
    off = 2

    def u16() -> int:
        nonlocal off
        val = _u16(data, off)
        off += 2
        return val

    frame = BodyCompositionFrame(fat_pct=round(u16() * 0.1, 1))
    if flags & 0x0002:
        off += 7
    if flags & 0x0004:
        frame.user_index = data[off]
        off += 1
    if flags & 0x0008:
        frame.bmr_kcal = round(u16() / KJ_PER_KCAL)
    if flags & 0x0010:
        frame.muscle_pct = round(u16() * 0.1, 1)
    if flags & 0x0020:
        frame.muscle_mass_kg = round(u16() * mm, 2)
    if flags & 0x0040:
        u16()  # fat free mass (unused)
    if flags & 0x0080:
        frame.soft_lean_mass_kg = round(u16() * mm, 2)
    if flags & 0x0100:
        frame.water_mass_kg = round(u16() * mm, 2)
    if flags & 0x0200:
        frame.impedance_ohm = round(u16() * 0.1, 1)
    return frame


def merge(weight: WeightFrame, body: BodyCompositionFrame) -> Measurement:
    m = Measurement(
        weight_kg=weight.weight_kg,
        user_index=weight.user_index if weight.user_index is not None else body.user_index,
        timestamp=weight.timestamp,
        bmi=weight.bmi,
        fat_pct=body.fat_pct,
        muscle_pct=body.muscle_pct,
        muscle_mass_kg=body.muscle_mass_kg,
        water_mass_kg=body.water_mass_kg,
        impedance_ohm=body.impedance_ohm,
        bmr_kcal=body.bmr_kcal,
    )
    if body.water_mass_kg and weight.weight_kg:
        m.water_pct = round(body.water_mass_kg / weight.weight_kg * 100, 1)
    return m


def build_current_time(now: dt.datetime) -> bytes:
    return bytes([now.year & 0xFF, (now.year >> 8) & 0xFF, now.month, now.day,
                  now.hour, now.minute, now.second, now.isoweekday(), 0, 0])


def build_consent(user_index: int, pin: int) -> bytes:
    return bytes([0x02, user_index & 0xFF, pin & 0xFF, (pin >> 8) & 0xFF])


def _newer(a: dt.datetime | None, b: dt.datetime | None) -> bool:
    if a is None:
        return False
    if b is None:
        return True
    return a > b


# ─── BlueZ pairing / bonding ────────────────────────────────────────────────
# The BF720's User Data service (0x181C, incl. the UCP consent characteristic
# 0x2A9F) requires an ENCRYPTED link on BlueZ — the characteristics are not even
# discoverable until the device is bonded. bleak's pair() needs a BlueZ agent to
# exist; a bare add-on container has none, so we register our own (auto-accepts
# Just Works, supplies the PIN for Passkey Entry). Mirrors ble-scale-sync #168.
_AGENT_PATH = "/beurer/agent"
_AGENT_BUS = None  # kept alive for the process lifetime

try:
    from dbus_fast import BusType, Variant
    from dbus_fast.aio import MessageBus
    from dbus_fast.service import ServiceInterface, method

    class _PairingAgent(ServiceInterface):
        """Minimal org.bluez.Agent1 that completes pairing without a UI."""

        def __init__(self, passkey: int | None) -> None:
            super().__init__("org.bluez.Agent1")
            self._passkey = passkey or 0

        @method()
        def Release(self):  # noqa: N802
            pass

        @method()
        def RequestPinCode(self, device: "o") -> "s":  # noqa: N802,F821
            return f"{self._passkey:04d}"

        @method()
        def RequestPasskey(self, device: "o") -> "u":  # noqa: N802,F821
            return int(self._passkey)

        @method()
        def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: N802,F821
            pass

        @method()
        def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: N802,F821
            pass

        @method()
        def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: N802,F821
            pass  # accept (Just Works / numeric comparison)

        @method()
        def RequestAuthorization(self, device: "o"):  # noqa: N802,F821
            pass  # accept

        @method()
        def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: N802,F821
            pass  # accept

        @method()
        def Cancel(self):  # noqa: N802
            pass

    _HAS_DBUS = True
except ImportError:
    _HAS_DBUS = False


async def register_pairing_agent(passkey: int | None) -> None:
    """Register a system BlueZ pairing agent so bleak's pair() can complete."""
    global _AGENT_BUS
    if not _HAS_DBUS:
        _LOGGER.warning("dbus-fast unavailable; cannot register a pairing agent.")
        return
    try:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        bus.export(_AGENT_PATH, _PairingAgent(passkey))
        introspection = await bus.introspect("org.bluez", "/org/bluez")
        obj = bus.get_proxy_object("org.bluez", "/org/bluez", introspection)
        manager = obj.get_interface("org.bluez.AgentManager1")
        await manager.call_register_agent(_AGENT_PATH, "KeyboardDisplay")
        try:
            await manager.call_request_default_agent(_AGENT_PATH)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("RequestDefaultAgent failed: %s", err)
        _AGENT_BUS = bus  # keep the connection alive
        _LOGGER.info("Registered BlueZ pairing agent.")
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not register BlueZ pairing agent: %s", err)


def _has_ucp(client: BleakClient) -> bool:
    target = CHAR_USER_CONTROL_POINT.lower()
    return any(
        ch.uuid.lower() == target
        for service in client.services
        for ch in service.characteristics
    )


async def _set_trusted(client: BleakClient) -> None:
    """Mark the device Trusted so future reconnects reuse the bond (best-effort)."""
    if _AGENT_BUS is None or not _HAS_DBUS:
        return
    try:
        path = client._backend._device_path  # type: ignore[attr-defined]  # noqa: SLF001
        introspection = await _AGENT_BUS.introspect("org.bluez", path)
        obj = _AGENT_BUS.get_proxy_object("org.bluez", path, introspection)
        props = obj.get_interface("org.freedesktop.DBus.Properties")
        await props.call_set("org.bluez.Device1", "Trusted", Variant("b", True))
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not set Trusted: %s", err)


async def _ensure_bonded(client: BleakClient) -> None:
    """Bond with the scale so the encrypted User Data service becomes usable."""
    try:
        await client.pair()  # no-op if already paired; needs our agent otherwise
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Pairing failed (continuing unbonded): %s", err)
    await _set_trusted(client)
    # After a fresh bond the encrypted characteristics may only appear on a new
    # connection — reconnect once if the UCP characteristic is still missing.
    if not _has_ucp(client):
        _LOGGER.info("UCP characteristic not visible yet; reconnecting on encrypted link...")
        try:
            await client.disconnect()
            await asyncio.sleep(1.0)
            await client.connect()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Reconnect after pairing failed: %s", err)


# ─── BLE read ───────────────────────────────────────────────────────────────
def _is_bf720(device, adv) -> bool:
    if SCALE_ADDRESS:
        return device.address.upper() == SCALE_ADDRESS.upper()
    return (adv.local_name or "").upper().startswith("BF720") or (
        BEURER_COMPANY_ID in (adv.manufacturer_data or {})
    )


async def read_measurements(device) -> dict[int, Measurement]:
    results: dict[int, Measurement] = {}
    last_weight: WeightFrame | None = None

    def on_weight(_c, data: bytearray) -> None:
        nonlocal last_weight
        try:
            last_weight = decode_weight(bytes(data))
        except (ValueError, IndexError):
            pass

    def on_bodycomp(_c, data: bytearray) -> None:
        try:
            body = decode_body_composition(bytes(data))
        except (ValueError, IndexError):
            return
        if not body.is_complete or last_weight is None:
            return
        m = merge(last_weight, body)
        if m.user_index is None:
            return
        prev = results.get(m.user_index)
        if prev is None or _newer(m.timestamp, prev.timestamp):
            results[m.user_index] = m

    client = BleakClient(device)
    await client.connect()
    try:
        # The User Data service (2A9F) needs an encrypted link on BlueZ.
        await _ensure_bonded(client)
        try:
            await client.write_gatt_char(
                CHAR_CURRENT_TIME, build_current_time(dt.datetime.now()), response=True
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("current-time write failed: %s", err)
        await client.start_notify(CHAR_USER_CONTROL_POINT, lambda *_: None)
        await client.start_notify(CHAR_WEIGHT, on_weight)
        await client.start_notify(CHAR_BODY_COMPOSITION, on_bodycomp)
        for user in USERS:
            await client.write_gatt_char(
                CHAR_USER_CONTROL_POINT,
                build_consent(user["user_index"], user["pin"]),
                response=True,
            )
            await asyncio.sleep(_CONSENT_SETTLE)
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
    return results


# ─── MQTT ───────────────────────────────────────────────────────────────────
# (key, friendly name, unit, device_class, Measurement attribute)
SENSORS = [
    ("weight", "Weight", "kg", "weight", "weight_kg"),
    ("body_fat", "Body fat", "%", None, "fat_pct"),
    ("muscle", "Muscle", "%", None, "muscle_pct"),
    ("body_water", "Body water", "%", None, "water_pct"),
    ("bmi", "BMI", None, None, "bmi"),
    ("basal_metabolism", "Basal metabolism", "kcal", None, "bmr_kcal"),
    ("muscle_mass", "Muscle mass", "kg", "weight", "muscle_mass_kg"),
    ("water_mass", "Water mass", "kg", "weight", "water_mass_kg"),
    ("impedance", "Impedance", "Ω", None, "impedance_ohm"),
]


def make_mqtt() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=BASE_TOPIC)
    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.will_set(AVAILABILITY_TOPIC, "offline", retain=True)
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()
    return client


def publish_discovery(client: mqtt.Client) -> None:
    for user in USERS:
        index = user["user_index"]  # already an int (normalized at load)
        name = user["name"]
        device = {
            "identifiers": [f"{BASE_TOPIC}_{index}"],
            "name": name,
            "manufacturer": "Beurer",
            "model": "BF720",
        }
        state_topic = f"{BASE_TOPIC}/{index}/state"
        for key, friendly, unit, dev_class, _attr in SENSORS:
            cfg = {
                "name": friendly,
                "unique_id": f"{BASE_TOPIC}_{index}_{key}",
                "state_topic": state_topic,
                "value_template": f"{{{{ value_json.{key} }}}}",
                "availability_topic": AVAILABILITY_TOPIC,
                "state_class": "measurement",
                "device": device,
            }
            if unit:
                cfg["unit_of_measurement"] = unit
            if dev_class:
                cfg["device_class"] = dev_class
            topic = f"{DISCOVERY_PREFIX}/sensor/{BASE_TOPIC}_{index}/{key}/config"
            client.publish(topic, json.dumps(cfg), retain=True)
    client.publish(AVAILABILITY_TOPIC, "online", retain=True)
    _LOGGER.info("Published MQTT discovery for %d user(s).", len(USERS))


def publish_state(client: mqtt.Client, index: int, m: Measurement) -> None:
    payload = {key: getattr(m, attr) for key, _n, _u, _dc, attr in SENSORS}
    client.publish(f"{BASE_TOPIC}/{index}/state", json.dumps(payload), retain=True)
    _LOGGER.info("User %s: %.2f kg, %.1f%% fat", index, m.weight_kg, m.fat_pct or 0.0)


# ─── Main loop ──────────────────────────────────────────────────────────────
async def main() -> None:
    for warning in _EARLY_WARNINGS:
        _LOGGER.warning(warning)
    if not USERS:
        _LOGGER.error("No valid users configured. Add at least one user (name, index, PIN).")
        sys.exit(1)
    _LOGGER.info("Loaded %d user(s): indices %s", len(USERS), [u["user_index"] for u in USERS])

    # Register a BlueZ pairing agent up front so the encrypted User Data service
    # becomes reachable (BF720 requires a bonded link on Linux/BlueZ).
    await register_pairing_agent(USERS[0]["pin"] if USERS else None)

    client = make_mqtt()
    publish_discovery(client)
    _LOGGER.info("Watching for the scale (scan interval %ss)...", SCAN_INTERVAL)

    while True:
        try:
            device = await BleakScanner.find_device_by_filter(_is_bf720, timeout=SCAN_INTERVAL)
            if device is not None:
                _LOGGER.debug("Found %s, reading...", device.address)
                for index, measurement in (await read_measurements(device)).items():
                    publish_state(client, index, measurement)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Read cycle failed: %s", err)
        await asyncio.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
