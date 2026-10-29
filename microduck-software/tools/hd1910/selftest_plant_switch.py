# SPDX-License-Identifier: Apache-2.0
"""Round-trip + negative-control self test for the live plant switch.

Why this exists
---------------
``apply_to_live.py --check`` reporting OK once is not evidence — a gate that is
always green is worthless. This drives the switch through a real round trip and
*deliberately breaks* each discriminated field, asserting the gate goes red.

Sequence:
  1. record the current live plant (restored at the end)
  2. switch to every supported plant, assert gate_ok
  3. sabotage kp_fw -> assert gate_ok False (this is the field we most need trusted)
  4. sabotage json_path -> assert the wrong plant is *detected*
  5. switch back, assert the live file sha16 is byte-identical to step 1

Usage::

    .venv-mjlab/Scripts/python.exe tools/hd1910/selftest_plant_switch.py

Exit 0 = all assertions passed.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "hd1910"))

import apply_to_live as switch  # noqa: E402

FAILS: list[str] = []


def ok(cond: bool, label: str, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


def read_live() -> str:
    return switch.LIVE_CONSTANTS.read_text(encoding="utf-8")


def write_live(text: str) -> None:
    switch.LIVE_CONSTANTS.write_text(text, encoding="utf-8")


def main() -> int:
    print("=== 1) snapshot current live plant ===")
    before = read_live()
    before_info = switch._readback()
    print(f"  detected={before_info['detected']} kp_fw={before_info['kp_fw']} "
          f"sha16={before_info['sha16']}")

    plants = ["hd1910", "hd1910_ftservo_m6", "hd1910_kp5", "xl330"]
    try:
        for p in plants:
            print(f"=== 2) switch -> {p} ===")
            info = switch.apply(p)
            ok(info["detected"] == {"ftservo_m6": "hd1910_ftservo_m6"}.get(p, p),
               f"detect {p}", f"got {info['detected']}")
            ok(info["gate_ok"] is True, f"gate_ok {p}", f"kp_fw={info['kp_fw']}")

        print("=== 3) NEGATIVE CONTROL: kp_fw sabotage (the load-bearing field) ===")
        info = switch.apply("hd1910_kp5")
        ok(info["gate_ok"] is True, "pre-sabotage gate is green")
        clean = read_live()
        write_live(clean.replace("kp_fw=5.0", "kp_fw=32.0"))
        bad = switch._readback(HD := switch.HD1910_OFFICIAL_M6_KP5["id"])
        ok(bad["gate_ok"] is False, "kp_fw=32 makes gate RED",
           f"detected={bad['detected']} kp={bad['kp_fw']}")
        write_live(clean)

        print("=== 4) NEGATIVE CONTROL: json_path swap (detect must follow) ===")
        wrong = clean.replace("official_m6_stslaw.json", "m5.json")
        write_live(wrong)
        swapped = switch._readback(HD)
        ok(swapped["detected"] != "hd1910_kp5",
           "swapped params file is no longer detected as hd1910_kp5",
           f"detected={swapped['detected']}")
        write_live(clean)
        ok(switch._readback(HD)["gate_ok"] is True, "restored gate is green again")
    finally:
        print("=== 5) restore original plant ===")
        write_live(before)
        after_info = switch._readback()
        ok(after_info["sha16"] == before_info["sha16"],
           "live file byte-identical to snapshot",
           f"{before_info['sha16']} -> {after_info['sha16']}")
        ok(after_info["detected"] == before_info["detected"],
           "detected plant restored", f"{after_info['detected']}")

    print()
    if FAILS:
        print(f"FAILED {len(FAILS)}: {FAILS}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
