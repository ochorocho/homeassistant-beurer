# BF720 sample capture (synthetic)

Documents the BF720 frame layouts using **fabricated** values (no personal data).
The byte layouts match what a real Beurer BF720 emits; these samples are used by
`tests/test_parser.py`. All multi-byte integers little-endian. Weight resolution
0.005 kg; body-comp percentages x0.1; impedance x0.1 Ohm; BMR in kJ.

## UCP consent
- Write to `2A9F`: `02 02 d2 04`  (opcode 0x02 CONSENT, userIndex 2, code 0x04d2 = 1234 LE)
- Indication back: `20 02 01`  -> response to op 0x02 = SUCCESS

## Primary reading (user index 2)
Weight `2A9D`: `0e803ed007060f081e0002f7000807`
- flags 0x0e = timestamp + userId + BMI/height present, unit kg
- weight = 0x3e80 (16000) x 0.005 = 80.00 kg
- timestamp = 2000-06-15 08:30:00 ; userId = 2
- BMI = 0x00f7 (247) x 0.1 = 24.7 ; height = 0x0708 (1800) x 0.001 = 1.80 m
- cross-check: 80.00 / 1.80^2 = 24.7

Body Composition `2A9C`: `9803fa0070177c01f82ad0208813`
- flags 0x0398 = fat + BMR + muscle% + soft-lean-mass + water-mass + impedance, unit kg
- fat = 25.0 % ; BMR = 6000 kJ (= 1433 kcal) ; muscle% = 38.0 %
- soft lean mass = 55.00 kg ; water mass = 42.00 kg ; impedance = 500.0 Ohm
- derived water% = 42.00 / 80.00 x 100 = 52.5 %

## Second profile (user index 1) — demographics change the body comp
Weight `2A9D`: `0e7030d007060f09000001e4007206` -> 62.00 kg, user 1, BMI 22.8, height 1.65 m
Body Comp `2A9C`: `98032c0188134a016022c8197c15` -> fat 30.0 %, muscle 33.0 %, impedance 550.0 Ohm

## Transitional frames (step-off noise — MUST be ignored)
Body comp `9803000000000000000000000000` (all-zero) — impedance 0 => not a real reading.
Rule: a real reading pairs a weight frame with a body-comp frame whose impedance is non-zero.

## On-scale user list (vendor char 0xFFFF/0x0001, write 0x00 to request)
12-byte rows:
  status(u8): 0x00=entry, 0x01=list-complete, 0x02=no-users
  entry: index(u8) initials(3 ASCII) birth_year(u16 LE) month(u8) day(u8)
         height_cm(u8) gender(u8: 0=male,1=female) activity(u8)

| raw                          | index | initials | dob        | height | gender | act |
|------------------------------|-------|----------|------------|--------|--------|-----|
| `0001414141d0070101a50102`   | 1     | AAA      | 2000-01-01 | 165 cm | female | 2   |
| `0002424242d007060fb40003`   | 2     | BBB      | 2000-06-15 | 180 cm | male   | 3   |
| `0003434343d0070c1faa0102`   | 3     | CCC      | 2000-12-31 | 170 cm | female | 2   |
| `01`                         | list complete                                     |

## Key findings for the integration
- macOS/bleak connects with NO pairing dialog and NO encrypted bond required.
- A single UCP consent write unlocks weight + body-composition indications.
- The completed measurement is delivered right after consent; transient frames follow.
- A valid reading = weight frame + body-comp frame with non-zero impedance.
- The scale supports multiple users; measurements carry a user-index byte.
- Stored/offline measurements replay on connect with their ORIGINAL timestamps; treat
  old-timestamped frames as historical and only freshly-stamped ones as live.
