"""Pure BF720 BLE frame decoders (no Home Assistant / bleak imports).

Kept dependency-free so it can be unit-tested against captured frames.
All multi-byte integers are little-endian. Weight resolution 0.005 kg;
percentages x0.1; impedance x0.1 ohm; BMR in kilojoules.

Byte layouts validated against a real Beurer BF720 (see
spike/fixtures/measurement-2026-07-18.md) and openScale's
StandardWeightProfileHandler / StandardBeurerSanitasHandler.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from .const import UCP_CONSENT, UCP_RESPONSE, UCP_RESULT_SUCCESS

KJ_PER_KCAL = 4.1868


@dataclass
class WeightFrame:
    """Decoded Weight Measurement (0x2A9D)."""

    weight_kg: float
    timestamp: dt.datetime | None = None
    user_index: int | None = None
    bmi: float | None = None
    height_m: float | None = None


@dataclass
class BodyCompositionFrame:
    """Decoded Body Composition Measurement (0x2A9C)."""

    fat_pct: float
    user_index: int | None = None
    bmr_kcal: int | None = None
    muscle_pct: float | None = None
    muscle_mass_kg: float | None = None
    fat_free_mass_kg: float | None = None
    soft_lean_mass_kg: float | None = None
    water_mass_kg: float | None = None
    impedance_ohm: float | None = None
    weight_kg: float | None = None

    @property
    def is_complete(self) -> bool:
        """A real BIA reading has a non-zero impedance; step-off frames are all-zero."""
        return bool(self.impedance_ohm)


@dataclass
class UserProfile:
    """A user slot from the vendor user list (0xFFFF/0x0001)."""

    index: int
    initials: str
    birth_date: str
    height_cm: int
    gender: str
    activity: int


@dataclass
class Measurement:
    """A weight frame merged with its body-composition partner."""

    weight_kg: float
    user_index: int | None = None
    timestamp: dt.datetime | None = None
    bmi: float | None = None
    height_m: float | None = None
    fat_pct: float | None = None
    muscle_pct: float | None = None
    muscle_mass_kg: float | None = None
    fat_free_mass_kg: float | None = None
    soft_lean_mass_kg: float | None = None
    water_mass_kg: float | None = None
    water_pct: float | None = None
    impedance_ohm: float | None = None
    bmr_kcal: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _u16(data: bytes, off: int) -> int:
    return int.from_bytes(data[off : off + 2], "little")


def decode_weight(data: bytes) -> WeightFrame:
    """Decode a Weight Measurement (0x2A9D) frame."""
    if len(data) < 3:
        raise ValueError("weight frame too short")
    flags = data[0]
    off = 1
    raw = _u16(data, off)
    off += 2
    weight_kg = raw * 0.005 if not (flags & 0x01) else raw * 0.01 * 0.45359237
    frame = WeightFrame(weight_kg=round(weight_kg, 2))
    if flags & 0x02:  # timestamp
        year = _u16(data, off)
        try:
            frame.timestamp = dt.datetime(
                year, data[off + 2], data[off + 3], data[off + 4], data[off + 5], data[off + 6]
            )
        except ValueError:
            frame.timestamp = None
        off += 7
    if flags & 0x04:  # user id
        frame.user_index = data[off]
        off += 1
    if flags & 0x08:  # BMI + height
        frame.bmi = round(_u16(data, off) * 0.1, 1)
        off += 2
        frame.height_m = round(_u16(data, off) * 0.001, 2)
        off += 2
    return frame


def decode_body_composition(data: bytes) -> BodyCompositionFrame:
    """Decode a Body Composition Measurement (0x2A9C) frame."""
    if len(data) < 4:
        raise ValueError("body composition frame too short")
    flags = _u16(data, 0)
    mass_mult = 0.005 if not (flags & 0x01) else 0.01
    off = 2

    def u16() -> int:
        nonlocal off
        val = _u16(data, off)
        off += 2
        return val

    frame = BodyCompositionFrame(fat_pct=round(u16() * 0.1, 1))
    if flags & 0x0002:  # timestamp
        off += 7
    if flags & 0x0004:  # user id
        frame.user_index = data[off]
        off += 1
    if flags & 0x0008:  # BMR (kJ -> kcal)
        frame.bmr_kcal = round(u16() / KJ_PER_KCAL)
    if flags & 0x0010:  # muscle %
        frame.muscle_pct = round(u16() * 0.1, 1)
    if flags & 0x0020:  # muscle mass
        frame.muscle_mass_kg = round(u16() * mass_mult, 2)
    if flags & 0x0040:  # fat free mass
        frame.fat_free_mass_kg = round(u16() * mass_mult, 2)
    if flags & 0x0080:  # soft lean mass
        frame.soft_lean_mass_kg = round(u16() * mass_mult, 2)
    if flags & 0x0100:  # body water mass
        frame.water_mass_kg = round(u16() * mass_mult, 2)
    if flags & 0x0200:  # impedance
        frame.impedance_ohm = round(u16() * 0.1, 1)
    if flags & 0x0400:  # weight
        frame.weight_kg = round(u16() * mass_mult, 2)
    return frame


def decode_user_entry(data: bytes) -> UserProfile | None:
    """Decode one row of the vendor user list (0xFFFF/0x0001).

    Row layout (12 bytes): status(0x00) index initials(3 ASCII) year(u16 LE)
    month day height_cm gender(0=male,1=female) activity.
    Returns None for the list-complete (0x01) / no-users (0x02) markers.
    """
    if not data or data[0] in (0x01, 0x02) or len(data) < 12:
        return None
    return UserProfile(
        index=data[1],
        initials=data[2:5].decode("latin1", "replace").rstrip("\x00 "),
        birth_date=f"{_u16(data, 5):04d}-{data[7]:02d}-{data[8]:02d}",
        height_cm=data[9],
        gender="female" if data[10] == 1 else "male",
        activity=data[11],
    )


def is_consent_success(data: bytes) -> bool:
    """True if a UCP indication is a successful consent response."""
    return (
        len(data) >= 3
        and data[0] == UCP_RESPONSE
        and data[1] == UCP_CONSENT
        and data[2] == UCP_RESULT_SUCCESS
    )


def merge(weight: WeightFrame, body: BodyCompositionFrame) -> Measurement:
    """Merge a weight frame with its body-composition partner into a Measurement."""
    m = Measurement(
        weight_kg=weight.weight_kg,
        user_index=weight.user_index if weight.user_index is not None else body.user_index,
        timestamp=weight.timestamp,
        bmi=weight.bmi,
        height_m=weight.height_m,
        fat_pct=body.fat_pct,
        muscle_pct=body.muscle_pct,
        muscle_mass_kg=body.muscle_mass_kg,
        fat_free_mass_kg=body.fat_free_mass_kg,
        soft_lean_mass_kg=body.soft_lean_mass_kg,
        water_mass_kg=body.water_mass_kg,
        impedance_ohm=body.impedance_ohm,
        bmr_kcal=body.bmr_kcal,
    )
    if body.water_mass_kg and weight.weight_kg:
        m.water_pct = round(body.water_mass_kg / weight.weight_kg * 100, 1)
    return m


def build_current_time(now: dt.datetime) -> bytes:
    """Build a Current Time (0x2A2B) payload."""
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


def build_consent(user_index: int, pin: int) -> bytes:
    """Build a UCP consent payload: [0x02, userIndex, code_lo, code_hi]."""
    return bytes([UCP_CONSENT, user_index & 0xFF, pin & 0xFF, (pin >> 8) & 0xFF])
