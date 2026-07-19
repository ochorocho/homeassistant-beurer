"""Constants for the Beurer BLE (BF720) integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "beurer_ble"

# Advertisement identifiers.
BEURER_COMPANY_ID: Final = 0x0611  # Beurer GmbH, SIG-assigned
LOCAL_NAME_PREFIX: Final = "BF"  # BF720 / BF105 / BF500

# Standard SIG GATT characteristics (full 128-bit form).
CHAR_CURRENT_TIME: Final = "00002a2b-0000-1000-8000-00805f9b34fb"
CHAR_WEIGHT: Final = "00002a9d-0000-1000-8000-00805f9b34fb"
CHAR_BODY_COMPOSITION: Final = "00002a9c-0000-1000-8000-00805f9b34fb"
CHAR_USER_CONTROL_POINT: Final = "00002a9f-0000-1000-8000-00805f9b34fb"

# User Control Point opcodes.
UCP_CONSENT: Final = 0x02
UCP_RESPONSE: Final = 0x20
UCP_RESULT_SUCCESS: Final = 0x01

# Config / options keys.
CONF_ADDRESS: Final = "address"
CONF_USERS: Final = "users"
CONF_USER_INDEX: Final = "user_index"
CONF_PIN: Final = "pin"
CONF_NAME: Final = "name"

# How long to keep the scale connection open waiting for a live weigh-in.
CONNECT_CAPTURE_SECONDS: Final = 40

# Don't reconnect to the scale more often than this (it wakes on each weigh-in).
POLL_MIN_INTERVAL_SECONDS: Final = 30
