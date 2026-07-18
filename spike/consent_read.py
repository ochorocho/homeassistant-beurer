#!/usr/bin/env python3
"""Consent to the Beurer BF720 and capture a live measurement.

Flow (SIG standard, from openScale / ble-scale-sync BF720 driver):
  1. scan-find + connect
  2. write Current Time (2A2B)
  3. subscribe to indications: Weight (2A9D), Body Composition (2A9C),
     User Control Point (2A9F); notify DB Change Increment (2A99)
  4. write UCP Consent  [0x02, userIndex, code_lo, code_hi]  -> 2A9F
  5. wait; step on the scale -> capture Weight + Body Composition frames

Usage:
    consent_read.py <pin> [user_index]        # pin 0-9999, index default 1
    BEURER_PIN=1234 consent_read.py            # or via env var
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
DBINCR = "00002a99-0000-1000-8000-00805f9b34fb"
CURRENT_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"

# --- args ---
pin = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("BEURER_PIN", "-1"))
user_index = int(sys.argv[2]) if len(sys.argv) > 2 else 1
if not (0 <= pin <= 9999):
    print("Provide the consent PIN (0-9999) as arg1 or BEURER_PIN env var.")
    sys.exit(1)


def is_bf720(device, adv) -> bool:
    return (
        (adv.local_name or "").upper().startswith("BF720")
        or BEURER_COMPANY_ID in (adv.manufacturer_data or {})
        or device.address.upper() == ADDRESS.upper()
    )


def current_time_bytes() -> bytes:
    now = dt.datetime.now()
    return bytes(
        [
            now.year & 0xFF,
            (now.year >> 8) & 0xFF,
            now.month,
            now.day,
            now.hour,
            now.minute,
            now.second,
            now.isoweekday(),  # 1=Mon .. 7=Sun
            0,  # fractions256
            0,  # adjust reason
        ]
    )


def parse_weight(data: bytes) -> str:
    if len(data) < 3:
        return "(short)"
    flags = data[0]
    raw = int.from_bytes(data[1:3], "little")
    kg = raw * 0.005 if not (flags & 0x01) else raw * 0.01 * 0.45359237
    unit = "kg" if not (flags & 0x01) else "lb->kg"
    return f"flags=0x{flags:02x} weight={kg:.2f} kg (raw={raw}, {unit})"


def parse_bodycomp(data: bytes) -> str:
    if len(data) < 4:
        return "(short)"
    flags = int.from_bytes(data[0:2], "little")
    mass_mult = 0.005 if not (flags & 0x01) else 0.01
    off = 2
    out = [f"flags=0x{flags:04x}"]

    def u16():
        nonlocal off
        v = int.from_bytes(data[off : off + 2], "little")
        off += 2
        return v

    # Body Fat % is the mandatory first field after flags.
    out.append(f"fat={u16() * 0.1:.1f}%")
    if flags & 0x0002:  # timestamp (7 bytes)
        off += 7
        out.append("ts")
    if flags & 0x0004:  # user id
        out.append(f"user={data[off]}")
        off += 1
    if flags & 0x0008:  # BMR (kJ)
        out.append(f"bmr={u16()} kJ")
    if flags & 0x0010:  # muscle %
        out.append(f"muscle={u16() * 0.1:.1f}%")
    if flags & 0x0020:  # muscle mass
        out.append(f"muscle_mass={u16() * mass_mult:.2f} kg")
    if flags & 0x0040:  # fat free mass
        out.append(f"ffm={u16() * mass_mult:.2f} kg")
    if flags & 0x0080:  # soft lean mass
        out.append(f"slm={u16() * mass_mult:.2f} kg")
    if flags & 0x0100:  # body water mass
        out.append(f"water_mass={u16() * mass_mult:.2f} kg")
    if flags & 0x0200:  # impedance
        out.append(f"impedance={u16() * 0.1:.1f} ohm")
    if flags & 0x0400:  # weight
        out.append(f"weight={u16() * mass_mult:.2f} kg")
    if flags & 0x0800:  # height
        out.append(f"height={u16()}")
    return " ".join(out)


def parse_ucp(data: bytes) -> str:
    if len(data) >= 3 and data[0] == 0x20:
        req = data[1]
        res = data[2]
        meaning = {0x01: "SUCCESS", 0x02: "OP_NOT_SUPPORTED", 0x04: "OP_FAILED",
                   0x05: "USER_NOT_AUTHORIZED"}.get(res, f"0x{res:02x}")
        return f"UCP response to op 0x{req:02x} -> {meaning}"
    return "UCP: " + data.hex()


def make_cb(name, parser):
    def cb(_char, data: bytes):
        print(f"  <- {name}: {data.hex()}")
        try:
            print(f"       {parser(data)}")
        except Exception as exc:  # noqa: BLE001
            print(f"       (parse error: {exc})")
    return cb


async def main() -> None:
    print(f"Scanning up to {FIND_SECONDS}s — keep the scale awake...")
    device = await BleakScanner.find_device_by_filter(is_bf720, timeout=FIND_SECONDS)
    if device is None:
        print("BF720 not found. Keep it awake and re-run.")
        return
    print(f"Found {device.address} ({device.name}). Connecting...")

    disconnected = asyncio.Event()
    client = BleakClient(device, timeout=20.0, disconnected_callback=lambda _: disconnected.set())
    await client.connect()
    print("CONNECTED\n")

    try:
        # 2. Current Time
        try:
            await client.write_gatt_char(CURRENT_TIME, current_time_bytes(), response=True)
            print("Wrote Current Time.")
        except Exception as exc:  # noqa: BLE001
            print(f"Current Time write failed (continuing): {exc}")

        # 3. Subscribe (start_notify handles indicate too)
        await client.start_notify(UCP, make_cb("UCP     ", parse_ucp))
        await client.start_notify(WEIGHT, make_cb("WEIGHT  ", parse_weight))
        await client.start_notify(BODYCOMP, make_cb("BODYCOMP", parse_bodycomp))
        try:
            await client.start_notify(DBINCR, make_cb("DBINCR  ", lambda d: d.hex()))
        except Exception:  # noqa: BLE001
            pass
        print("Subscribed to UCP / Weight / BodyComp indications.\n")

        # 4. Consent
        consent = bytes([0x02, user_index & 0xFF, pin & 0xFF, (pin >> 8) & 0xFF])
        print(f"Writing CONSENT (user={user_index}, pin={pin}): {consent.hex()}")
        await client.write_gatt_char(UCP, consent, response=True)

        # 5. Capture
        print(f"\n>>> STEP ON THE SCALE NOW. Capturing for {CAPTURE_SECONDS}s...\n")
        try:
            await asyncio.wait_for(disconnected.wait(), timeout=CAPTURE_SECONDS)
            print("\n(peer disconnected)")
        except asyncio.TimeoutError:
            print("\n(capture window ended)")
    finally:
        if client.is_connected:
            await client.disconnect()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
