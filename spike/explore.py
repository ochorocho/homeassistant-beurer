#!/usr/bin/env python3
"""Connect to the Beurer BF720 and dump its full GATT table.

No consent/registration yet — this just confirms the Mac can connect and
reveals the characteristic map + how bonding behaves. Reads a few safe,
unprotected characteristics (Device Info, Battery) to confirm the read path.

Keep the scale awake (step on / tap it) right before running.
"""

import asyncio
import sys

from bleak import BleakClient, BleakScanner

ADDRESS = sys.argv[1] if len(sys.argv) > 1 else "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
BEURER_COMPANY_ID = 0x0611
FIND_SECONDS = 30

# 16-bit UUID -> friendly name, for annotating the dump.
KNOWN = {
    "2a9d": "Weight Measurement",
    "2a9c": "Body Composition Measurement",
    "2a9f": "User Control Point (consent)",
    "2a99": "Database Change Increment",
    "2a2b": "Current Time",
    "2a85": "Date of Birth",
    "2a8c": "Gender",
    "2a8e": "Height",
    "2a19": "Battery Level",
    "2a29": "Manufacturer Name",
    "2a24": "Model Number",
    "181d": "Weight Scale Service",
    "181b": "Body Composition Service",
    "181c": "User Data Service",
    "1805": "Current Time Service",
    "180f": "Battery Service",
    "180a": "Device Information",
    "ffff": "Beurer vendor service",
}

SAFE_READS = {"2a29", "2a24", "2a19"}  # unprotected: manufacturer, model, battery


def short(uuid: str) -> str:
    u = uuid.lower()
    if u.startswith("0000") and u.endswith("-0000-1000-8000-00805f9b34fb"):
        return u[4:8]
    return u


def label(uuid: str) -> str:
    return KNOWN.get(short(uuid), "")


def is_bf720(device, adv) -> bool:
    if (adv.local_name or "").upper().startswith("BF720"):
        return True
    if BEURER_COMPANY_ID in (adv.manufacturer_data or {}):
        return True
    if device.address.upper() == ADDRESS.upper():
        return True
    return False


async def main() -> None:
    print(f"Scanning up to {FIND_SECONDS}s for the BF720 — keep tapping / standing on the scale...")
    device = await BleakScanner.find_device_by_filter(is_bf720, timeout=FIND_SECONDS)
    if device is None:
        print("BF720 not found while scanning — it likely slept. Keep it awake and re-run.")
        return
    print(f"Found {device.address} ({device.name}). Connecting...")

    def on_disconnect(_):
        print("!! disconnected by peer")

    client = BleakClient(device, timeout=20.0, disconnected_callback=on_disconnect)
    try:
        await client.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"CONNECT FAILED: {type(exc).__name__}: {exc}")
        print("The scale may have slept — tap it and re-run.")
        return

    print(f"CONNECTED: {client.is_connected}\n")
    try:
        for service in client.services:
            print(f"[service] {short(service.uuid)}  {label(service.uuid) or service.description}")
            for ch in service.characteristics:
                props = ",".join(ch.properties)
                note = label(ch.uuid)
                line = f"    {short(ch.uuid)}  ({props})"
                if note:
                    line += f"  <- {note}"
                print(line)
                if short(ch.uuid) in SAFE_READS and "read" in ch.properties:
                    try:
                        val = await client.read_gatt_char(ch)
                        try:
                            printable = val.decode("utf-8").strip()
                        except UnicodeDecodeError:
                            printable = val.hex()
                        print(f"        = {printable!r}")
                    except Exception as exc:  # noqa: BLE001
                        print(f"        (read failed: {type(exc).__name__}: {exc})")
            print()
    finally:
        await client.disconnect()
        print("Disconnected cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
