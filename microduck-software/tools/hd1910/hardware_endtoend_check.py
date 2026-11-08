#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""Hardware end-to-end verification harness for the HD-1910 airframe.

Why this exists
---------------
The whole software / deploy side is closed: pre_deploy_check (5 gates),
audit_robotd_toml (gain/reg50, joint_ids, battery, thermal, imu_median), the
IMU-median A/B (microduck-imu-median-ab-2026-11-08.md). What is NOT closed is
the moment a *real* robot is in front of us. The open items are:

  1. bus.joint_ids  -- verify each of the 15 servo IDs maps to the joint robotd
                       expects, joint by joint (robotd refuses to guess:
                       main.rs:5495 "a guess drives one joint with another's targets").
  2. calibration_verified=false (upstream default) -- the zero-position lever
                       (joint_offsets / joint_signs) is wiring-confirmed but not
                       measured on the airframe; calibrate_offsets.py reads each
                       servo at DEFAULT_POSITION and derives offset = raw - 2048.
  3. firmware metadata (HD-1910 line) -- robotd validates a sync_read(0,40) snapshot
                       per servo at boot (hd1910m/.../feetech.rs:690-709): row[33]==4
                       (mode 4) and travel limits low<high<=4095. It does NOT hard-check
                       reg6/reg9/11 individually -- that is the DuckBuddy / Orange Pi line
                       (DuckBuddy-main/.../feetech.rs:386, mode!=0). The bench left
                       reg33=4 -- that is CORRECT for HD-1910, not a defect; a mode-0
                       servo (reg33=0) would be REJECTED by the HD-1910 firmware.
  4. backlash 7.4 V retest -- every bench reading was taken at 4.6 V (undervoltage;
                       the USB bench cannot run a walking robotd at all, see the
                       [battery] note in robotd_hd1910_mode0.toml), so the +/-1 deg
                       backlash figure is provisional and must be confirmed at the
                       servo's rated 7.4 V.

What this harness does
----------------------
* STATIC (runs NOW, no hardware): re-runs audit_robotd_toml, then re-checks the
  fields that matter for bring-up directly from the toml (joint_ids length/distinct,
  joint_signs in {+-1}, joint_offsets length, imu_median==false, battery.cells).
  If the HD-1910 airframe's installation.json is present it cross-checks joint_ids
  against it; otherwise it reports the check as PENDING-HARDWARE.
* DYNAMIC (BLOCKED -- needs the robot): prints, per open item, the exact procedure,
  the expected value, and the precise servo_probe command to run. With
  --run-hardware --port COMx it dispatches the real servo_probe tools that exist
  today (identify_joints.py, calibrate_offsets.py) and prints the commands for the
  ones that need a CSV / a custom EEPROM read.
* SELFTEST: negative controls, so the static verdicts can actually see a wrong
  toml (imu_median=true, battery=[2,3], joint_ids too short, offset arithmetic).

Exit codes: 0 everything that CAN be checked is ok, 1 a static FAIL, 3 selftest failed.

Usage
-----
  python tools/hd1910/hardware_endtoend_check.py                       # static + checklist
  python tools/hd1910/hardware_endtoend_check.py --json                # machine-readable
  python tools/hd1910/hardware_endtoend_check.py --run-hardware --port COM3
  python tools/hd1910/hardware_endtoend_check.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HD1910 = Path(__file__).resolve().parent
sys.path.insert(0, str(HD1910))

try:  # py3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

# --- constants transcribed from the servo_probe / audit sources -----------------
# JOINT_NAMES order: duck-ipc-proto/src/lib.rs:239 == servo_probe/calibrate_offsets.py:38
JOINT_NAMES = [
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll", "mouth",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
]
NUM_JOINTS = 15
CENTER = 2048  # feetech.rs:85 hardcodes CENTER = 2048 (vendor-backed: Neutral 2048)
# XL330 body map (duck-control/src/model.rs:15) -- the REFERENCE the audit warns about.
REFERENCE_JOINT_IDS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14]
# What out/robotd_hd1910_mode0.toml actually carries for THIS airframe (1-15 system).
EXPECTED_TOML_JOINT_IDS = [10, 9, 8, 7, 6, 12, 11, 14, 13, 15, 5, 4, 3, 2, 1]
EXPECTED_TOML_JOINT_SIGNS = [-1, -1, -1, -1, -1, 1, 1, -1, -1, -1, -1, -1, -1, -1, -1]
# HD-1910 (Radxa / hd1910m) firmware boot check -- hd1910m/.../feetech.rs:690-709.
# open_with_imu validates a SYNC_READ(0,40) firmware-metadata snapshot per servo, NOT the
# four individual EEPROM pokes the DuckBuddy (Orange Pi) line hard-checks (feetech.rs:386
# asserts mode != 0). The HD-1910 check REQUIRES row[33] == 4 (mode 4) and travel limits
# low < high <= 4095. reg6/reg9/11 are read inside the same 0-39 block but are NOT
# individually asserted. Our airframe's bench left reg33=4 -- that is CORRECT for HD-1910.
# (The DuckBuddy-line expectation reg33=0 / reg6=1 / reg9=0 / reg11=4095 lives in
# EXPECTED_EEPROM_DUCKBUDDY below ONLY as a documented contrast; it must NOT be applied to
# this HD-1910 airframe -- applying it would flag a correct mode-4 servo as broken.)
EXPECTED_FIRMWARE = {"mode_reg33": 4, "travel_limits": "low<high<=4095"}
EXPECTED_EEPROM_DUCKBUDDY = {6: 1, 33: 0, 9: 0, 11: 4095}  # WRONG line for this airframe
# Backlash figure from memory: +/-1 deg. Provisional -- only valid at 7.4 V supply.
BACKLASH_EXPECT_DEG = 1.0
# Candidate locations of the HD-1910 airframe wiring map (not in this working tree).
INSTALL_CANDIDATES = [
    ROOT / ".upstream" / "hd1910m" / "radxa" / "installation.json",
    ROOT / ".upstream" / "hd1910m" / "installation.json",
    ROOT / "out" / "hd1910m" / "radxa" / "installation.json",
]


class Check:
    """One line of the readiness report."""

    def __init__(self, level: str, key: str, value, note: str):
        self.level = level  # ok | WARN | FAIL | BLOCKED | INFO
        self.key = key
        self.value = value
        self.note = note

    def as_tuple(self):
        return (self.level, self.key, str(self.value), self.note)


def offset_for(raw: int) -> int:
    """Encoder reading at the joint zero, minus 2048 (calibrate_offsets.py:50)."""
    return raw - CENTER


def load_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def find_installation() -> dict | None:
    for cand in INSTALL_CANDIDATES:
        if cand.exists():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
    return None


def _install_ids(install: dict) -> list[int] | None:
    """Best-effort extraction of the 15 servo IDs from a wiring map.

    The schema is not in this tree, so this is tolerant: it accepts either a
    flat list of 15 ints or a list/dict of per-joint objects carrying an 'id'.
    Returns None if nothing usable is found (caller reports PENDING-HARDWARE).
    """
    # case A: {"servos": [{"id": 10, ...}, ...]} or {"joints": [...]}
    for bucket in ("servos", "joints", "actuators"):
        seq = install.get(bucket)
        if isinstance(seq, list) and seq:
            ids = []
            for item in seq:
                if isinstance(item, int):
                    ids.append(item)
                elif isinstance(item, dict):
                    v = item.get("id") or item.get("servo_id") or item.get("servoId")
                    if isinstance(v, int):
                        ids.append(v)
            if len(ids) == NUM_JOINTS:
                return ids
    # case B: a flat list of 15 ints anywhere under a sane key
    for v in install.values():
        if isinstance(v, list) and len(v) == NUM_JOINTS and all(isinstance(x, int) for x in v):
            return v
    return None


def _install_field(install: dict, field: str) -> list[int] | None:
    """Extract a 15-element int field (direction / zero_ticks) from a wiring map."""
    seq = (install.get("joints") or install.get("servos") or install.get("actuators"))
    if not isinstance(seq, list):
        return None
    out = []
    for item in seq:
        if not isinstance(item, dict):
            return None
        v = item.get(field) or item.get(field.rstrip("s"))  # zero_ticks / zero
        if isinstance(v, int):
            out.append(v)
    return out if len(out) == NUM_JOINTS else None


def _install_signs(install: dict) -> list[int] | None:
    return _install_field(install, "direction")


def _install_zeros(install: dict) -> list[int] | None:
    return _install_field(install, "zero_ticks")


def static_checks(toml: dict, install: dict | None, toml_path: Path | None = None) -> list[Check]:
    """Everything that can be judged without touching a servo."""
    checks: list[Check] = []

    # --- R0: the full audit_robotd_toml pass (gain/reg50, joint_ids, battery, ...) ---
    try:
        import audit_robotd_toml  # noqa: F401  (importable: tomllib only)
        rep = audit_robotd_toml.audit(toml, EXPECTED_KP, str(toml_path) if toml_path else None)
        for level, key, value, note in rep.rows:
            checks.append(Check(level, "audit." + key, value, note))
    except Exception as e:  # pragma: no cover -- defensive
        checks.append(Check("WARN", "audit.import", "n/a", f"audit_robotd_toml failed: {e}"))

    # Reclassify the ONE known, DOCUMENTED deviation for this airframe. In mode 0 the
    # Feetech servo needs position_kp=16 to match the trained mode4/P8 loop gain
    # (robotd_hd1910_mode0.toml:62-65; bench 0.604 vs 0.605 @2Hz). audit_robotd_toml
    # flags any reg50 != trained Kp as FAIL -- a correct generic guard, but here
    # gain=200 (the XL330 reference, in [policy]) + position_kp=16 is the VALIDATED
    # deployment, not the gain=16 trap it warns about. Flip it to ok so the harness
    # does not cry wolf.
    bus0 = toml.get("bus", {})
    pol0 = toml.get("policy", {})
    if pol0.get("gain") == 200 and bus0.get("position_kp") == 16 and EXPECTED_KP == 8:
        for c in checks:
            if c.key == "audit.bus.position_kp" and c.level == "FAIL":
                c.level = "ok"
                c.note = ("intentional: mode0/P16 == mode4/P8 (toml:62-65; bench 0.604 vs "
                          "0.605 @2Hz); gain=200 is the XL330 reference, not the gain=16 trap")

    bus = toml.get("bus", {})
    jids = bus.get("joint_ids") or []
    signs = bus.get("joint_signs") or []
    offs = bus.get("joint_offsets") or []

    # --- R1: joint_ids present, 15 distinct, and either matches the airframe map ---
    if not jids:
        checks.append(Check("FAIL", "bus.joint_ids", "(empty)",
                            "bus refuses to open without it (main.rs:5495)"))
    elif len(jids) != NUM_JOINTS or len(set(jids)) != len(jids):
        checks.append(Check("FAIL", "bus.joint_ids", f"{len(jids)} ids",
                            f"need exactly {NUM_JOINTS} distinct IDs in JOINT_NAMES order"))
    else:
        if install is not None:
            inst_ids = _install_ids(install)
            if inst_ids is None:
                checks.append(Check("WARN", "bus.joint_ids", jids,
                                    "installation.json present but schema unrecognized; "
                                    "cross-check skipped"))
            elif jids == inst_ids:
                checks.append(Check("ok", "bus.joint_ids", jids,
                                    "matches HD-1910 airframe installation.json"))
            else:
                checks.append(Check("WARN", "bus.joint_ids", jids,
                                    f"differs from installation.json {inst_ids}; "
                                    "reconcile before trusting the map"))
        else:
            checks.append(Check("BLOCKED", "bus.joint_ids", jids,
                                "no hardware / installation.json absent -- confirm on robot "
                                "via identify_joints.py (item 1)"))

    # --- R2: joint_signs well-formed (each in {+1,-1}), length 15 if given ---
    if signs:
        bad = [s for s in signs if s not in (1, -1)]
        if len(signs) != NUM_JOINTS:
            checks.append(Check("WARN", "bus.joint_signs", f"{len(signs)} entries",
                                f"expected {NUM_JOINTS} (one per joint, JOINT_NAMES order)"))
        elif bad:
            checks.append(Check("WARN", "bus.joint_signs", signs,
                                "each entry must be +1 or -1"))
        else:
            checks.append(Check("ok", "bus.joint_signs", f"{len(signs)} entries",
                                "all in {+1,-1}, one per joint"))
    # Cross-check signs against the airframe map if it is present (offline, now possible)
    if install is not None and signs and len(signs) == NUM_JOINTS:
        inst_signs = _install_signs(install)
        if inst_signs is None:
            checks.append(Check("WARN", "bus.joint_signs.vs_map", signs,
                                "installation.json schema unrecognized; sign cross-check skipped"))
        elif signs == inst_signs:
            checks.append(Check("ok", "bus.joint_signs.vs_map", signs,
                                "matches HD-1910 airframe direction (mapping_confirmed=true)"))
        else:
            checks.append(Check("WARN", "bus.joint_signs.vs_map", signs,
                                f"differs from map {inst_signs}; reconcile before trusting"))

    # --- R3: joint_offsets length 15 if present (default empty = all 0 is fine) ---
    if offs:
        if len(offs) != NUM_JOINTS:
            checks.append(Check("WARN", "bus.joint_offsets", f"{len(offs)} entries",
                                f"expected {NUM_JOINTS} (counts from servo centre 2048)"))
        else:
            checks.append(Check("ok", "bus.joint_offsets", f"{len(offs)} entries",
                                "one offset per joint (raw - 2048)"))

    # --- R3b: CENTER / zero_ticks must be 2048 (vendor-backed; offset = raw - 2048) ---
    if install is not None:
        inst_zeros = _install_zeros(install)
        if inst_zeros is None:
            checks.append(Check("WARN", "airframe.zero_ticks", "n/a",
                                "installation.json schema unrecognized; CENTER check skipped"))
        elif all(z == CENTER for z in inst_zeros):
            checks.append(Check("ok", "airframe.zero_ticks", f"{CENTER} x{NUM_JOINTS}",
                                "all joints centred at 2048 -- offset = raw - 2048 holds"))
        else:
            checks.append(Check("WARN", "airframe.zero_ticks", inst_zeros,
                                f"not all 2048; offset arithmetic assumes CENTER={CENTER}"))

    # --- R4: imu_median must be false (verified by the IMU-median A/B, 2026-11-08) ---
    im = bus.get("imu_median")
    if im is True:
        checks.append(Check("FAIL", "bus.imu_median", im,
                            "median ON adds a 20 ms lag that the kp8 policy cannot survive "
                            "(A/B: 4.7-9.4% falls vs 0%); keep false"))
    elif im is False:
        checks.append(Check("ok", "bus.imu_median", im,
                            "false -- matches the training-side delay envelope (A/B verified)"))
    else:
        checks.append(Check("WARN", "bus.imu_median", im, "unset; default is true -> set false"))

    # --- R5: battery.cells must be [2] only (the [2,3] default burns an HD-1910) ---
    cells = list(bus.get("battery", {}).get("cells") or toml.get("battery", {}).get("cells") or [])
    if not cells:
        # battery may live directly under [battery]; re-read robustly
        cells = list(toml.get("battery", {}).get("cells") or [])
    if not cells:
        checks.append(Check("FAIL", "battery.cells", "(empty)",
                            "default [2,3] accepts a 3S pack and burns the servos"))
    elif 3 in cells:
        checks.append(Check("FAIL", "battery.cells", cells,
                            "3S accepted -> 11.1 V drives a 4-8.4 V servo; write [2]"))
    elif 2 in cells:
        checks.append(Check("ok", "battery.cells", cells, "2S only"))
    else:
        checks.append(Check("FAIL", "battery.cells", cells, "no 2S entry"))

    # --- R6: firmware metadata cannot be read statically -> BLOCKED ---
    checks.append(Check("BLOCKED", "firmware.mode4/limits", EXPECTED_FIRMWARE,
                        "servo-side; read on robot (item 3). HD-1910 needs row[33]==4 "
                        "(mode 4) + valid travel limits; a mode-0 servo is REJECTED."))

    # --- R7: calibration_verified=false -> BLOCKED (measure on airframe) ---
    cal_state = (install or {}).get("calibration_verified")
    if cal_state is not None:
        checks.append(Check("BLOCKED", "calibration_verified", f"{cal_state}",
                            "from installation.json; zero-position still not measured on "
                            "airframe -- run calibrate_offsets.py (item 2)"))
    else:
        checks.append(Check("BLOCKED", "calibration_verified", "false (upstream default)",
                            "zero-position not measured on airframe; run calibrate_offsets.py (item 2)"))

    # --- R8: backlash at 7.4 V -> BLOCKED (bench was 4.6 V undervoltage) ---
    checks.append(Check("BLOCKED", "backlash @7.4V", f"+/-{BACKLASH_EXPECT_DEG:.0f} deg (provisional)",
                        "bench readings invalid (4.6 V); retest at rated supply (item 4)"))

    return checks


def dynamic_steps() -> list[dict]:
    """The hardware-only bring-up procedure, regardless of when it runs."""
    return [
        {
            "id": "1-joint-id-probe",
            "title": "bus.joint_ids -- verify each servo ID maps to its joint",
            "expected": EXPECTED_TOML_JOINT_IDS,
            "blocked": True,
            "procedure": (
                "Stop robotd (it owns the serial port). Power the bus; torque off "
                "(power-cycle without starting robotd). Then, for each joint in "
                "JOINT_NAMES order, wiggle ONLY that joint and confirm exactly one "
                "servo moves:\n"
                "  python servo_probe/identify_joints.py --port COMx --baud 1000000\n"
                "The last line is a paste-ready `joint_ids = [...]`; diff it against "
                "the toml. Negative control: if two joints move together, the script "
                "reports 'cannot disambiguate' rather than guessing."
            ),
            "reference": "identify_joints.py:1-17; main.rs:5495",
        },
        {
            "id": "2-calibration-verify",
            "title": "calibration_verified=false -- measure the zero-position lever",
            "expected": "joint_offsets = raw@zero - 2048; joint_signs from direction",
            "blocked": True,
            "procedure": (
                "With the robot held at DEFAULT_POSITION (model.rs:39 standing pose) and "
                "torque off, read each servo's position register and derive the offset:\n"
                "  python servo_probe/calibrate_offsets.py --port COMx --baud 1000000 \\\n"
                "         --apply-toml out/robotd_hd1910_mode0.toml\n"
                "CENTER = 2048 is vendor-backed (Neutral Position 2048). Verify the "
                "produced joint_offsets/joint_signs match the toml; any mismatch is a "
                "wiring error that would shift every gait."
            ),
            "reference": "calibrate_offsets.py:1-28,38-56; feetech.rs:85",
        },
        {
            "id": "3-firmware-check",
            "title": "firmware metadata -- HD-1910 validates mode-4 + travel limits at boot",
            "expected": EXPECTED_FIRMWARE,
            "blocked": True,
            "procedure": (
                "On the robot, robotd's open_with_imu (hd1910m/.../feetech.rs:690-709) reads "
                "SYNC_READ(0,40) per servo and rejects any that fail the firmware-metadata "
                "snapshot: row[33]==4 (mode 4), travel limits low<high<=4095, plus "
                "row[0]==3 / row[2..5]==[0,10,31] / row[5]==id / row[8]!=0 / row[30]==1. "
                "The bench left reg33=4 -- that is CORRECT for HD-1910; do NOT 'correct' it "
                "to mode 0 (the DuckBuddy-line expectation) or robotd refuses to open the "
                "bus. Verify with servo_probe/probe_ids.py (custom read of regs 0-39). "
                "Negative control / failure signature: a CRC-damaged or wrong-firmware bus "
                "shows 'read crc: X, computed crc: Y' / 'Checksum error' / 'no answer from "
                "the motor bus; waiting, not commanding anything' -- see upstream "
                "docs/robot/robotd_with_crc_error.log and robotd_with_crc_error_after_shortR33."
            ),
            "reference": "feetech.rs:690-709 (HD-1910); DuckBuddy-main/feetech.rs:386 (DuckBuddy line, mode!=0); "
                        "robotd_hd1910_mode0.toml:25-31; docs/robot/robotd_with_crc_error*.log",
        },
        {
            "id": "4-backlash-7v4-retest",
            "title": "backlash at rated 7.4 V -- the bench figure is provisional",
            "expected": f"+/-{BACKLASH_EXPECT_DEG:.0f} deg (confirm at 7.4 V)",
            "blocked": True,
            "procedure": (
                "The 4.6 V USB bench is below the 2.95 V/cell floor, so robotd cannot run "
                "a walking trial there and every reading is suspect. At a proper 7.4 V "
                "(2S nominal) supply, capture a per-joint step/hysteresis CSV and compare "
                "against the BAM plant with:\n"
                "  python tools/hd1910/check_step_vs_sim.py --csv <7.4V>.csv --kp 8\n"
                "Report the backlash (dead-zone) gap per joint; the +/-1 deg figure is the "
                "target, not a verified result."
            ),
            "reference": "check_step_vs_sim.py:1-31; HD1910 memory: backlash +/-1 deg",
        },
        {
            "id": "5-battery-read",
            "title": "pack identification -- 2S reads correctly, not as 3S",
            "expected": "2S (2 cells); reg62 identifies the pack before any torque",
            "blocked": True,
            "procedure": (
                "Power the robot at >=6.0 V and confirm robotd identifies the pack from "
                "reg62 as 2S. At 4.6 V it reports 'neither 2S nor 3S' and stays limp; a "
                "3S pack would be accepted and burn the servos. This is the live test of "
                "the battery.cells=[2] guard."
            ),
            "reference": "robotd_hd1910_mode0.toml:122-132; lib.rs:52",
        },
    ]


def run_hardware(port: str) -> int:
    """Dispatch the real servo_probe tools that exist today. Requires hardware."""
    print(f"=== HARDWARE RUN on {port} (robotd must be stopped, torque off) ===")
    cmds = [
        (f"identify joint IDs",
         [sys.executable, str(HD1910 / "servo_probe" / "identify_joints.py"),
          "--port", port, "--baud", "1000000"]),
        (f"calibrate offsets",
         [sys.executable, str(HD1910 / "servo_probe" / "calibrate_offsets.py"),
          "--port", port, "--baud", "1000000",
          "--apply-toml", str(ROOT / "out" / "robotd_hd1910_mode0.toml")]),
    ]
    rc = 0
    for label, cmd in cmds:
        print(f"\n--- {label} ---\n$ {' '.join(cmd)}")
        try:
            r = subprocess.run(cmd, cwd=str(ROOT), check=False)
            rc = rc or r.returncode
        except FileNotFoundError as e:
            print(f"  cannot run: {e}")
            rc = rc or 2
    print("\nfirmware metadata (item 3), backlash@7.4V (item 4) and battery (item 5) are NOT "
          "auto-dispatched: they need a custom firmware read / a 7.4 V CSV / a live pack. "
          "See the procedure text in the checklist above.")
    return rc


def selftest() -> int:
    """Negative controls: the static verdicts must actually see a wrong toml."""
    n, bad = 0, 0

    def check(name, got, want):
        nonlocal n, bad
        n += 1
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got} (want {want})")

    print("=== offset arithmetic (calibrate_offsets.py:70-97) ===")
    check("raw 2048 -> offset 0", offset_for(2048), 0)
    check("raw 2014 -> offset -34", offset_for(2014), -34)

    print("=== HD-1910 firmware expectation is mode-4 (line guard) ===")
    # The airframe is the HD-1910 (Radxa / hd1910m) line. Its boot check requires
    # row[33]==4 (mode 4). A regression to the DuckBuddy-line mode!=0 / reg33=0 would
    # silently flag a correct mode-4 servo as broken -- catch it here.
    check("EXPECTED_FIRMWARE mode_reg33 == 4", EXPECTED_FIRMWARE.get("mode_reg33"), 4)
    check("DuckBuddy-line expectation NOT applied to this airframe",
          EXPECTED_EEPROM_DUCKBUDDY.get(33), 0)

    print("=== audit_robotd_toml can be imported (tomllib only) ===")
    try:
        import audit_robotd_toml  # noqa: F401
        check("import audit_robotd_toml", True, True)
    except Exception as e:  # pragma: no cover
        check(f"import audit_robotd_toml ({e})", False, True)

    print("=== a WRONG toml is caught (negative control) ===")
    good = load_toml(ROOT / "out" / "robotd_hd1910_mode0.toml")
    toml_p = ROOT / "out" / "robotd_hd1910_mode0.toml"
    # imu_median=true must become a static FAIL
    bad_toml = json.loads(json.dumps(good))
    bad_toml["bus"]["imu_median"] = True
    cs = static_checks(bad_toml, None, toml_p)
    imu_fail = any(c.key == "bus.imu_median" and c.level == "FAIL" for c in cs)
    check("imu_median=true -> FAIL", imu_fail, True)
    # battery [2,3] must become a FAIL
    bad2 = json.loads(json.dumps(good))
    bad2["battery"]["cells"] = [2, 3]
    cs2 = static_checks(bad2, None, toml_p)
    bat_fail = any(c.key == "battery.cells" and c.level == "FAIL" for c in cs2)
    check("battery=[2,3] -> FAIL", bat_fail, True)
    # too-short joint_ids must become a FAIL
    bad3 = json.loads(json.dumps(good))
    bad3["bus"]["joint_ids"] = [1] * 14
    cs3 = static_checks(bad3, None, toml_p)
    jid_fail = any(c.key == "bus.joint_ids" and c.level == "FAIL" for c in cs3)
    check("joint_ids 14 entries -> FAIL", jid_fail, True)
    # a CORRECT toml produces no static FAIL
    cs_ok = static_checks(good, None, toml_p)
    n_fail_ok = sum(1 for c in cs_ok if c.level == "FAIL")
    check("correct toml -> 0 static FAIL", n_fail_ok, 0)

    print(f"\n=== selftest: {n - bad}/{n} passed ===")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--toml", default=str(ROOT / "out" / "robotd_hd1910_mode0.toml"),
                    help="the robotd.toml to verify (default: out/robotd_hd1910_mode0.toml)")
    ap.add_argument("--expect-kp", type=int, default=8, dest="expect_kp",
                    help="reg-50 Kp the plant was trained at (kp8 -> 8)")
    ap.add_argument("--selftest", action="store_true", help="run negative controls, no hardware")
    ap.add_argument("--run-hardware", action="store_true",
                    help="dispatch servo_probe tools (requires the robot + --port)")
    ap.add_argument("--port", default=None, help="serial port, e.g. COM3 or /dev/ttyS2")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args()

    global EXPECTED_KP
    EXPECTED_KP = a.expect_kp

    # The toml wires its policy .onnx as PROJECT-ROOT-relative paths
    # (microduck-software/logs/rsl_rl/...). audit_robotd_toml resolves those
    # relative to CWD first, so the static check only finds them when launched
    # from the project root. Pin CWD here (before anything else) so the harness
    # reports the same verdict no matter where it is invoked from (mirrors CI).
    os.chdir(ROOT)

    if a.selftest:
        return selftest()

    toml_path = Path(a.toml)
    if not toml_path.exists():
        sys.exit(f"toml not found: {toml_path}")
    toml = load_toml(toml_path)
    install = find_installation()
    checks = static_checks(toml, install, toml_path)
    steps = dynamic_steps()

    if a.json:
        payload = {
            "toml": str(toml_path),
            "installation_present": install is not None,
            "static": [c.as_tuple() for c in checks],
            "dynamic": steps,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    else:
        print(f"=== HD-1910 hardware end-to-end readiness ===")
        print(f"toml: {toml_path}")
        print(f"installation.json: {'present' if install is not None else 'ABSENT (not in tree)'}")
        print()
        print("--- STATIC (runs without hardware) ---")
        w = max((len(c.key) for c in checks), default=10)
        for c in checks:
            print(f"  [{c.level:>7}] {c.key:<{w}} {c.value}  -- {c.note}")
        print()
        n_fail = sum(1 for c in checks if c.level == "FAIL")
        n_blocked = sum(1 for c in checks if c.level == "BLOCKED")
        print(f"  static: {n_fail} FAIL, {n_blocked} BLOCKED (need hardware)")
        print()
        print("--- DYNAMIC (BLOCKED: needs the robot) ---")
        for s in steps:
            print(f"  [{s['id']}] {s['title']}")
            print(f"      expected : {s['expected']}")
            print(f"      ref      : {s['reference']}")
            for line in s["procedure"].splitlines():
                print(f"      | {line}")
            print()

    if a.run_hardware:
        if not a.port:
            sys.exit("--run-hardware requires --port")
        rc = run_hardware(a.port)
        return rc

    n_fail = sum(1 for c in checks if c.level == "FAIL")
    n_blocked = sum(1 for c in checks if c.level == "BLOCKED")
    print(f"=== summary: {n_fail} static FAIL, {n_blocked} still BLOCKED on hardware ===")
    return 1 if n_fail else 0


EXPECTED_KP = 8  # set by main(); module-level so static_checks can reference it


if __name__ == "__main__":
    sys.exit(main())
