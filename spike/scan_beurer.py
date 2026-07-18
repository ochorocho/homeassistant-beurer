#!/usr/bin/env python3
"""Identify the Beurer BF720 among nearby BLE devices.

The BF720 advertises with no local name — just manufacturer data (Beurer
company id 0x0611) and/or the SIG Weight Scale / Body Composition services.
This scan prints those details for every device and flags the likely scale.

Run it while stepping on / tapping the scale so it stays awake and advertising:

    /Users/jochen/Development/ha_beurer/.venv/bin/python \
        /Users/jochen/Development/ha_beurer/spike/scan_beurer.py
"""

import asyncio

from bleak import BleakScanner

BEURER_COMPANY_ID = 0x0611  # Beurer GmbH, SIG-assigned

# SIG services the BF720 exposes (16-bit, normalised to full 128-bit lowercase).
SIG_HINT_UUIDS = {
    "0000181d-0000-1000-8000-00805f9b34fb": "Weight Scale (0x181D)",
    "0000181b-0000-1000-8000-00805f9b34fb": "Body Composition (0x181B)",
    "0000181c-0000-1000-8000-00805f9b34fb": "User Data (0x181C)",
    "0000ffff-0000-1000-8000-00805f9b34fb": "Beurer vendor (0xFFFF)",
}

SCAN_SECONDS = 25


def score(adv) -> int:
    """Higher = more likely to be the BF720."""
    s = 0
    if BEURER_COMPANY_ID in (adv.manufacturer_data or {}):
        s += 100
    for u in adv.service_uuids or []:
        if u.lower() in SIG_HINT_UUIDS:
            s += 50
    if (adv.local_name or "").upper().startswith("BF"):
        s += 200
    return s


async def main() -> None:
    print(f"Scanning {SCAN_SECONDS}s — step on / tap the scale now to keep it awake...\n")
    found = await BleakScanner.discover(timeout=SCAN_SECONDS, return_adv=True)

    rows = sorted(found.values(), key=lambda da: score(da[1]), reverse=True)

    for device, adv in rows:
        mfg = adv.manufacturer_data or {}
        mfg_str = ", ".join(f"0x{cid:04X}:{data.hex()}" for cid, data in mfg.items()) or "-"
        svcs = adv.service_uuids or []
        hints = [SIG_HINT_UUIDS[u.lower()] for u in svcs if u.lower() in SIG_HINT_UUIDS]
        flag = "  <<< LIKELY BF720" if score(adv) >= 100 else ""

        print(f"{device.address}  rssi={adv.rssi:>4}  name={adv.local_name or '(unknown)'}{flag}")
        print(f"    manufacturer_data: {mfg_str}")
        print(f"    service_uuids: {', '.join(svcs) if svcs else '-'}")
        if hints:
            print(f"    -> SIG hints: {', '.join(hints)}")
        if BEURER_COMPANY_ID in mfg:
            print(f"    -> BEURER company id 0x0611 present!")
        print()

    print(f"Done. {len(rows)} device(s). Look for the '<<< LIKELY BF720' flag or the "
          "Beurer 0x0611 company id.")
    print("If nothing is flagged, the scale may have slept — re-run and keep tapping it.")


if __name__ == "__main__":
    asyncio.run(main())
