"""BLE connection + consent + read flow for the Beurer BF720.

Runs entirely against a connectable BLEDevice provided by Home Assistant's
bluetooth stack. The frame decoding lives in parser.py (unit-tested); this
module only orchestrates the GATT conversation.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from . import parser
from .const import (
    CHAR_BODY_COMPOSITION,
    CHAR_CURRENT_TIME,
    CHAR_USER_CONTROL_POINT,
    CHAR_WEIGHT,
    CONNECT_CAPTURE_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

# Per-user consent + collection window.
_CONSENT_SETTLE = 3.0


@dataclass
class UserCredential:
    """A configured on-scale user we want to read."""

    user_index: int
    pin: int


async def async_read_measurements(
    ble_device: BLEDevice,
    users: list[UserCredential],
) -> dict[int, parser.Measurement]:
    """Connect, consent as each user in turn, return latest complete reading per user.

    The scale replays stored measurements (with their original timestamps) plus any
    live weigh-in; frames are tagged with a user index, so we group by that and keep
    the newest timestamped complete reading for each user.
    """
    results: dict[int, parser.Measurement] = {}
    last_weight: parser.WeightFrame | None = None

    def handle_weight(_char, data: bytearray) -> None:
        nonlocal last_weight
        try:
            last_weight = parser.decode_weight(bytes(data))
        except ValueError:
            _LOGGER.debug("Undecodable weight frame: %s", bytes(data).hex())

    def handle_bodycomp(_char, data: bytearray) -> None:
        try:
            body = parser.decode_body_composition(bytes(data))
        except ValueError:
            return
        if not body.is_complete or last_weight is None:
            return  # step-off / transitional frame
        measurement = parser.merge(last_weight, body)
        idx = measurement.user_index
        if idx is None:
            return
        prev = results.get(idx)
        if prev is None or parser.newer(measurement.timestamp, prev.timestamp):
            results[idx] = measurement

    def handle_ucp(_char, data: bytearray) -> None:
        _LOGGER.debug("UCP: %s", bytes(data).hex())

    client: BleakClient = await establish_connection(
        BleakClient, ble_device, ble_device.address
    )
    try:
        # The scale's User Data / body-composition characteristics require an
        # encrypted, bonded link on BlueZ. CoreBluetooth and ESP32 proxies bond
        # transparently; here we make a best-effort attempt and carry on if the
        # backend has no pairing agent (the OS-level bond then covers it).
        try:
            await client.pair()
        except Exception as err:  # noqa: BLE001 - not all backends/agents support pairing
            _LOGGER.debug("Pairing not available/needed: %s", err)

        try:
            await client.write_gatt_char(
                CHAR_CURRENT_TIME, parser.build_current_time(dt.datetime.now()), response=True
            )
        except Exception as err:  # noqa: BLE001 - non-fatal
            _LOGGER.debug("Current Time write failed: %s", err)

        await client.start_notify(CHAR_USER_CONTROL_POINT, handle_ucp)
        await client.start_notify(CHAR_WEIGHT, handle_weight)
        await client.start_notify(CHAR_BODY_COMPOSITION, handle_bodycomp)

        # Bound the whole consent/collect phase so a stuck consent can't hold the
        # connection open indefinitely.
        try:
            async with asyncio.timeout(CONNECT_CAPTURE_SECONDS):
                for cred in users:
                    consent = parser.build_consent(cred.user_index, cred.pin)
                    _LOGGER.debug("Consent as user %s", cred.user_index)
                    await client.write_gatt_char(
                        CHAR_USER_CONTROL_POINT, consent, response=True
                    )
                    await asyncio.sleep(_CONSENT_SETTLE)
        except TimeoutError:
            _LOGGER.debug(
                "Capture window (%ss) elapsed before all consents completed",
                CONNECT_CAPTURE_SECONDS,
            )
    finally:
        try:
            await client.disconnect()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Disconnect failed: %s", err)

    return results
