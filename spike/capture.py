#!/usr/bin/env python3
"""Refined BF720 capture: consent -> user list -> clean stabilized reading.

Improvements over consent_read.py:
  * full Weight frame decode (timestamp, user id, BMI, height)
  * pairs Weight + Body Composition and reports ONLY complete readings
    (non-zero impedance), ignoring step-off transitional frames
  * queries the on-scale user list via vendor char 0xFFFF/0x0001

Usage:  capture.py <pin> [user_index]     (or BEURER_PIN env var)
Keep the scale awake during the scan; do a full weigh-in when prompted.
"""

import asyncio
import datetime as dt
import os
import sys

from bleak import BleakClient, BleakScanner

ADDRESS = "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
BEURER_COMPANY_ID = 0x0611
FIND_SECONDS = 30
CAPTURE_SECONDS = 45

UCP = "00002a9f-0000-1000-8000-00805f9b34fb"
WEIGHT = "00002a9d-0000-1000-8000-00805f9b34fb"
BODYCOMP = "00002a9c-0000-1000-8000-00805f9b34fb"
CURRENT_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"
VENDOR_USERLIST = "00000001-0000-1000-8000-00805f9b34fb"

pin = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("BEURER_PIN", "-1"))
user_index = int(sys.argv[2]) if len(sys.argv) > 2 else 1
if not (0 <= pin <= 9999):
    print("Provide the consent PIN (0-9999) as arg1 or BEURER_PIN env var.")
    sys.exit(1)

readings: list[dict] = []
_last_weight: dict | None = None


def is_bf720(device, adv) -> bool:
    return (
        (adv.local_name or "").upper().startswith("BF720")
        or BEURER_COMPANY_ID in (adv.manufacturer_data or {})
        or device.address.upper() == ADDRESS.upper()
    )


def current_time_bytes() -> bytes:
    n = dt.datetime.now()
    return bytes([n.year & 0xFF, (n.year >> 8) & 0xFF, n.month, n.day,
                  n.hour, n.minute, n.second, n.isoweekday(), 0, 0])


def decode_weight(data: bytes) -> dict:
    flags = data[0]
    off = 1
    raw = int.from_bytes(data[off:off + 2], "little"); off += 2
    kg = raw * 0.005 if not (flags & 0x01) else raw * 0.01 * 0.45359237
    out = {"weight_kg": round(kg, 2), "flags": flags}
    if flags & 0x02:  # timestamp
        y = int.from_bytes(data[off:off + 2], "little")
        out["ts"] = f"{y:04d}-{data[off+2]:02d}-{data[off+3]:02d} {data[off+4]:02d}:{data[off+5]:02d}:{data[off+6]:02d}"
        off += 7
    if flags & 0x04:  # user id
        out["user"] = data[off]; off += 1
    if flags & 0x08:  # BMI + height
        out["bmi"] = round(int.from_bytes(data[off:off + 2], "little") * 0.1, 1); off += 2
        out["height_m"] = round(int.from_bytes(data[off:off + 2], "little") * 0.001, 2); off += 2
    return out


def decode_bodycomp(data: bytes) -> dict:
    flags = int.from_bytes(data[0:2], "little")
    mm = 0.005 if not (flags & 0x01) else 0.01
    off = 2
    out = {"flags": flags}

    def u16():
        nonlocal off
        v = int.from_bytes(data[off:off + 2], "little"); off += 2
        return v

    out["fat_pct"] = round(u16() * 0.1, 1)
    if flags & 0x0002: off += 7
    if flags & 0x0004: out["user"] = data[off]; off += 1
    if flags & 0x0008: out["bmr_kj"] = u16()
    if flags & 0x0010: out["muscle_pct"] = round(u16() * 0.1, 1)
    if flags & 0x0020: out["muscle_mass_kg"] = round(u16() * mm, 2)
    if flags & 0x0040: out["fat_free_mass_kg"] = round(u16() * mm, 2)
    if flags & 0x0080: out["soft_lean_mass_kg"] = round(u16() * mm, 2)
    if flags & 0x0100: out["water_mass_kg"] = round(u16() * mm, 2)
    if flags & 0x0200: out["impedance_ohm"] = round(u16() * 0.1, 1)
    if flags & 0x0400: out["weight_kg"] = round(u16() * mm, 2)
    if flags & 0x0800: out["height"] = u16()
    return out


def on_weight(_c, data: bytes):
    global _last_weight
    _last_weight = decode_weight(data)
    print(f"  <- WEIGHT   {data.hex()}  {_last_weight}")


def on_bodycomp(_c, data: bytes):
    bc = decode_bodycomp(data)
    print(f"  <- BODYCOMP {data.hex()}  {bc}")
    if bc.get("impedance_ohm", 0) > 0:  # complete reading, not step-off noise
        merged = {**(_last_weight or {}), **bc}
        readings.append(merged)
        print("       ^ COMPLETE READING captured")


def on_ucp(_c, data: bytes):
    if len(data) >= 3 and data[0] == 0x20:
        res = {0x01: "SUCCESS", 0x04: "OP_FAILED", 0x05: "NOT_AUTHORIZED"}.get(data[2], hex(data[2]))
        print(f"  <- UCP      {data.hex()}  -> op 0x{data[1]:02x}: {res}")
    else:
        print(f"  <- UCP      {data.hex()}")


def decode_user_entry(data: bytes) -> dict:
    """status(0x00) index initials(3) year(2 LE) month day height_cm gender activity."""
    return {
        "index": data[1],
        "initials": data[2:5].decode("latin1", "replace").rstrip(),
        "dob": f"{int.from_bytes(data[5:7], 'little'):04d}-{data[7]:02d}-{data[8]:02d}",
        "height_cm": data[9],
        "gender": "female" if data[10] == 1 else "male",
        "activity": data[11],
    }


def on_userlist(_c, data: bytes):
    if not data:
        return
    status = data[0]
    if status == 0x01:
        print("  <- USERLIST (list complete)")
    elif status == 0x02:
        print("  <- USERLIST (no users on scale)")
    elif len(data) >= 12:
        print(f"  <- USER {decode_user_entry(data)}")
    else:
        print(f"  <- USERLIST raw {data.hex()}")


async def main() -> None:
    print(f"Scanning up to {FIND_SECONDS}s — keep the scale awake...")
    device = await BleakScanner.find_device_by_filter(is_bf720, timeout=FIND_SECONDS)
    if device is None:
        print("BF720 not found. Keep it awake and re-run.")
        return
    print(f"Found {device.address}. Connecting...")

    disc = asyncio.Event()
    client = BleakClient(device, timeout=20.0, disconnected_callback=lambda _: disc.set())
    await client.connect()
    print("CONNECTED\n")
    try:
        try:
            await client.write_gatt_char(CURRENT_TIME, current_time_bytes(), response=True)
        except Exception as e:  # noqa: BLE001
            print(f"(current-time write failed: {e})")

        await client.start_notify(UCP, on_ucp)
        await client.start_notify(WEIGHT, on_weight)
        await client.start_notify(BODYCOMP, on_bodycomp)

        consent = bytes([0x02, user_index & 0xFF, pin & 0xFF, (pin >> 8) & 0xFF])
        print(f"Consent (user={user_index}, pin={pin}): {consent.hex()}")
        await client.write_gatt_char(UCP, consent, response=True)
        await asyncio.sleep(1.5)

        # Query the on-scale user list via vendor char.
        try:
            await client.start_notify(VENDOR_USERLIST, on_userlist)
            await client.write_gatt_char(VENDOR_USERLIST, bytes([0x00]), response=True)
            print("Requested on-scale user list.")
            await asyncio.sleep(1.5)
        except Exception as e:  # noqa: BLE001
            print(f"(user-list query failed: {e})")

        print(f"\n>>> DO A FULL WEIGH-IN NOW (stand still). Capturing {CAPTURE_SECONDS}s...\n")
        try:
            await asyncio.wait_for(disc.wait(), timeout=CAPTURE_SECONDS)
            print("\n(peer disconnected)")
        except asyncio.TimeoutError:
            print("\n(capture window ended)")
    finally:
        if client.is_connected:
            await client.disconnect()

    print("\n=== COMPLETE READINGS ===")
    if not readings:
        print("(none — try again with a full, still weigh-in)")
    for i, r in enumerate(readings, 1):
        print(f"[{i}] {r}")


if __name__ == "__main__":
    asyncio.run(main())
