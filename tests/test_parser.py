"""Verify the BF720 parser against synthetic frames.

The byte layouts match those captured from real hardware, but the values here
are fabricated (no personal data). Each frame is a valid encode->decode of the
documented layout, so these still exercise the real parser end-to-end.

Runnable standalone (no HA, no pytest needed):
    .venv/bin/python tests/test_parser.py
Also works under pytest.
"""

import datetime as dt
import pathlib
import sys
import types

# Bootstrap the component's parser/const as a package WITHOUT running __init__.py
# (which imports Home Assistant, not installed in this venv).
_BEURER_DIR = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "beurer_ble"
_pkg = types.ModuleType("beurer_ble")
_pkg.__path__ = [str(_BEURER_DIR)]
sys.modules.setdefault("beurer_ble", _pkg)

from beurer_ble import parser  # noqa: E402

# --- Synthetic frames (fabricated values, real byte layout) ------------------
# Primary reading: 80.00 kg, user index 2, BMI 24.7, height 1.80 m, 2000-06-15.
W_PRIMARY = "0e803ed007060f081e0002f7000807"
BC_PRIMARY = "9803fa0070177c01f82ad0208813"
# A second profile (user index 1) to show demographics change the body-comp.
W_OTHER = "0e7030d007060f09000001e4007206"
BC_OTHER = "98032c0188134a016022c8197c15"
# Step-off / transitional frame (all-zero body comp).
BC_STEPOFF = "9803000000000000000000000000"
# User list rows.
USER_1 = "0001414141d0070101a50102"
USER_2 = "0002424242d007060fb40003"
USER_3 = "0003434343d0070c1faa0102"


def test_weight_primary():
    w = parser.decode_weight(bytes.fromhex(W_PRIMARY))
    assert w.weight_kg == 80.0
    assert w.user_index == 2
    assert w.bmi == 24.7
    assert w.height_m == 1.8
    assert w.timestamp == dt.datetime(2000, 6, 15, 8, 30, 0)


def test_bodycomp_primary():
    b = parser.decode_body_composition(bytes.fromhex(BC_PRIMARY))
    assert b.fat_pct == 25.0
    assert b.muscle_pct == 38.0
    assert b.soft_lean_mass_kg == 55.0
    assert b.water_mass_kg == 42.0
    assert b.impedance_ohm == 500.0
    assert b.bmr_kcal == 1433  # 6000 kJ / 4.1868
    assert b.is_complete


def test_weight_other():
    w = parser.decode_weight(bytes.fromhex(W_OTHER))
    assert w.weight_kg == 62.0
    assert w.user_index == 1
    assert w.bmi == 22.8
    assert w.height_m == 1.65
    # cross-check: weight / height^2 ~= BMI (within rounding of the scale's own value)
    assert abs(w.weight_kg / w.height_m**2 - w.bmi) <= 0.1


def test_bodycomp_other_differs():
    b = parser.decode_body_composition(bytes.fromhex(BC_OTHER))
    assert b.fat_pct == 30.0  # different profile -> different body composition
    assert b.muscle_pct == 33.0
    assert b.impedance_ohm == 550.0


def test_stepoff_frame_incomplete():
    b = parser.decode_body_composition(bytes.fromhex(BC_STEPOFF))
    assert b.fat_pct == 0.0
    assert not b.is_complete  # impedance 0 -> not a real reading


def test_merge_computes_water_pct():
    w = parser.decode_weight(bytes.fromhex(W_PRIMARY))
    b = parser.decode_body_composition(bytes.fromhex(BC_PRIMARY))
    m = parser.merge(w, b)
    assert m.user_index == 2
    assert m.weight_kg == 80.0
    assert m.fat_pct == 25.0
    assert m.water_pct == round(42.0 / 80.0 * 100, 1)  # 52.5%


def test_user_list_rows():
    u1 = parser.decode_user_entry(bytes.fromhex(USER_1))
    assert (u1.index, u1.height_cm, u1.gender, u1.birth_date) == (1, 165, "female", "2000-01-01")
    u2 = parser.decode_user_entry(bytes.fromhex(USER_2))
    assert (u2.index, u2.initials, u2.height_cm, u2.gender) == (2, "BBB", 180, "male")
    assert parser.decode_user_entry(bytes.fromhex("01")) is None  # list complete


def test_consent_response():
    assert parser.is_consent_success(bytes.fromhex("200201"))
    assert not parser.is_consent_success(bytes.fromhex("200205"))  # not authorized


def test_build_helpers():
    assert parser.build_consent(2, 1234) == bytes.fromhex("0202d204")
    ct = parser.build_current_time(dt.datetime(2000, 6, 15, 8, 30, 0))
    assert ct[:2] == bytes([2000 & 0xFF, 2000 >> 8]) and ct[2] == 6 and ct[3] == 15


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} parser tests passed against synthetic frames.")
