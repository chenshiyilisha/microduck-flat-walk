#!/usr/bin/env python
"""Audit a robotd.toml against the gain scale the policy was trained on.

Why this exists
---------------
`robotd --fake` / `--sim` cannot answer the question that matters. Both build a
`FakeIo` / `RemoteIo` (robotd/src/main.rs:1342-1363) and never touch a serial port,
and `DynamixelIo` only exists under `#[cfg(target_os = "linux")]`
(main.rs:1457-1461). So on a Windows dev box there is no way to watch a gain land in
reg 50. Worse, robotd does not compile on Windows at all: `use tokio::net::{UnixListener,
UnixStream}` (main.rs:51) and `std::os::unix::fs::{FileTypeExt, PermissionsExt}`
(main.rs:4279) are unconditional, and the whole IPC surface is a unix socket.

What *can* be checked off-hardware is the arithmetic that turns a gain into a
register value, and that arithmetic is the whole story here (see the next section).

The trap in one line
--------------------
**`policy.gain` is not reg 50.** On the Feetech path every gain goes through

    reg50 = clamp(round(gain * position_kp / 200), 1, 254)      (feetech.rs:236)

so `[policy] gain = 8` with the default `position_kp = 8` writes
`round(8*8/200) = 0.32 -> 1`: every servo at its softest possible Kp. The robot
goes limp, and the symptom reads as "the policy does not walk".

This file used to make exactly that mistake: it compared the raw `gain` number
against the trained register Kp and demanded `gain = 8`, which is the destructive
value. Correct is `policy.gain = 200` (the XL330 reference the policies run at)
with `[bus] position_kp = 8` -- which is what the built-in defaults already give.

Because running/standing/limp/pose all pass through the same round(), the
*ratios* survive any uniform rescale; what does not survive is rounding at a
small `position_kp` (50*2/200 = 0.5 -> 1, so limp collapses onto running). That
is checked here in register units, where it is visible.

Defaults audited here (robotd-params/src/lib.rs, checked 2026-11-03):
  PolicyParams  gain 200 (:2460) | standing_gain_ratio 0.8 (:2457) | action_scale 0.9
                head_lowpass 0.5 | legs_lowpass 0.7 | standing_action_scale 1.0
  SafetyParams  gain_limp 50 (:2480) | limp_fall_pose_gain 160 (:2500)
                fall_gravity_z -0.5 | fall_debounce_ms 200 | deadman_ms 500
                limp_fall_tilt_z -0.90 | limp_fall_predict_z -0.5
                limp_fall_lookahead_ms 300 | limp_fall_debounce_ms 60 | limp_fall_arm_ms 200
  Bus           fast_sync_read true | port (required)

Usage
-----
  python tools/hd1910/audit_robotd_toml.py                       # audit deploy/robotd.toml
  python tools/hd1910/audit_robotd_toml.py --toml /etc/robot/robotd.toml --expect-kp 8
  python tools/hd1910/audit_robotd_toml.py --selftest            # negative controls

Exit codes: 0 all pass, 1 at least one FAIL, 3 selftest failed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:  # py3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

# ---------------------------------------------------------------------------
# defaults transcribed from robotd-params/src/lib.rs (line refs in the docstring)
# ---------------------------------------------------------------------------

# JOINT_NAMES length (duck-control/src/model.rs): 15 servos on the bus, IMU board at ID 200.
NUM_JOINTS = 15

DEFAULTS: dict[str, dict[str, object]] = {
    "policy": {
        "gain": 200,
        "standing_gain_ratio": 0.8,
        "action_scale": 0.9,
        "standing_action_scale": 1.0,
        "head_lowpass": 0.5,
        "legs_lowpass": 0.7,
        "enabled": True,
        "mode": "walk",
    },
    "safety": {
        "gain_limp": 50,
        "limp_fall_pose_gain": 160,
        "fall_gravity_z": -0.5,
        "fall_debounce_ms": 200,
        "deadman_ms": 500,
        "limp_fall": True,
        "limp_fall_tilt_z": -0.90,
        "limp_fall_predict_z": -0.5,
        "limp_fall_lookahead_ms": 300,
        "limp_fall_debounce_ms": 60,
        "limp_fall_arm_ms": 200,
        "battery_empty_shutdown": True,
    },
    "bus": {"servo": "feetech_hls",
            "position_kp": 8, "position_kp_head": 16, "position_kd": 8},
    "control": {"hz": 50},
    "update_gate": {"min_achieved_hz": 45.0, "stall_periods": 25,
                     "max_consecutive_errors": 10},
}

# ---------------------------------------------------------------------------
# The schema, transcribed from the Rust structs. Load-bearing because BOTH `Params`
# and `Bus` are `#[serde(deny_unknown_fields)]` (robotd-params/src/lib.rs:32,934):
# one unknown key anywhere and robotd refuses the ENTIRE file -- it does not start,
# it does not warn about the one key, and the failure reads as "the daemon is broken".
# That is exactly how a `bus.protocol = ` line copied from kissqy's config bricks it.
#
# Sections: Params' twelve fields (lib.rs:34-47). There is NO `[board]` section --
# `board.version` was a phantom in this audit until 2026-11-04 **for this generation**.
# Careful: there are TWO robotd generations in this workspace and their schemas do not mix.
#   A) out/upstream_ref/  (Radxa Zero 3W + XL330): Params HAS `board`, `pickup`, `head_imu`,
#      `idle`, `duck_detector`; BUS HAS `fast_sync_read`; there is a board.rs. No `joint_ids`,
#      no feetech, no `[battery]`/`[thermal]`.
#   B) .upstream/DuckBuddy-main/ (Orange Pi + HL-2915): `joint_ids`, `servo`, `[battery]`,
#      `[thermal]`; NO `board`, NO `fast_sync_read`, no board.rs, 500 kbps hardcoded.
# HD-1910 is a Feetech HLS servo -> only B can drive it -> the whitelist below is B's.
# A key that is real in A and absent in B is still a load failure in B, which is the whole
# point: `deny_unknown_fields` does not care that the key exists somewhere else.
KNOWN_SECTIONS = {
    "bus", "control", "update_gate", "policy", "safety", "audio", "theremin",
    "chorale", "media", "detect", "thermal", "battery",
}
# Only the sections this audit drives are enumerated key-by-key; an unknown key in
# `[audio]`/`[media]`/... is not judged here rather than guessed at.
SECTION_KEYS: dict[str, set[str]] = {
    # lib.rs:941-1000 (Bus). No `baud`, no `protocol`, no `joint_names`.
    "bus": {"port", "servo", "joint_ids", "joint_signs", "joint_offsets", "imu",
            "imu_axes", "imu_pitch_trim_deg", "imu_roll_trim_deg", "imu_median",
            "position_kp", "position_kp_head", "position_kd", "current_limit_ma",
            "mouth_torque", "mouth_wake"},
    "battery": {"cells", "max_volts"},
    "thermal": {"warn_c", "walk_max_c", "sit_c", "hysteresis_c", "rest_c", "resume_c",
                "rest_min_s", "rest_head_c", "deep_sit"},
}

# The HD-1910's own overheat latch: reg13 = 80 degC, read from ID 10 on 2026-11-02.
SERVO_OVERHEAT_C = 80.0
# HD-1910 rated supply (robotd-params/src/lib.rs:52: "4-8.4 V, burn on 3S").
HD1910_MAX_V = 8.4
# duck-control/src/model.rs:15 -- the reference map, for judging a filled-in joint_ids.
REFERENCE_JOINT_IDS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14]

# feetech.rs:115 -- the XL330 gain the policies run at. Every requested gain is scaled
# by position_kp / this before it reaches reg 50.
KP_REFERENCE = 200.0


def register_kp(gain: float, position_kp: float) -> int:
    """`policy.gain` -> the value actually written to reg 50 (feetech.rs:236).

    `(running * kp / KP_REFERENCE).round().clamp(1, 254)`. Upstream's own unit tests pin
    the reference points: kp_for_gain(200, 8) = 8, (50, 8) = 2, (160, 8) = 6, (0, 8) = 1.
    """
    return int(min(254.0, max(1.0, round(gain * position_kp / KP_REFERENCE))))


def effective(cfg: dict, section: str, key: str):
    """Value the daemon will actually use, plus whether the file said so."""
    table = cfg.get(section, {}) or {}
    if key in table:
        return table[key], True
    return DEFAULTS.get(section, {}).get(key), False


# ---------------------------------------------------------------------------
# The whitelist above is only worth what its provenance is. It was wrong once: this audit
# used to report `bus.fast_sync_read` and `board.version` as real knobs, and neither exists
# in the DuckBuddy tree -- as unknown keys they abort the whole config load instead of doing
# what the audit said they did. So the lists are re-derived from the Rust source whenever it
# is present, and a mismatch is a FAIL rather than a footnote.
# ---------------------------------------------------------------------------

DEFAULT_SCHEMA_RS = (Path(__file__).resolve().parents[2]
                     / ".upstream/DuckBuddy-main/robotd-params/src/lib.rs")

STRUCT_OF_SECTION = {"Params": None, "Bus": "bus", "BatteryParams": "battery",
                     "Thermal": "thermal"}


def parse_struct_fields(src: str, struct_name: str) -> set[str] | None:
    """`pub name:` inside `pub struct <struct_name> { ... }`, or None if not found."""
    import re
    m = re.search(rf"^pub struct {struct_name} \{{", src, re.M)
    if not m:
        return None
    body = src[m.end():]
    end = re.search(r"^\}$", body, re.M)
    if end:
        body = body[:end.start()]
    return set(re.findall(r"^\s*pub ([a-z_][a-z0-9_]*):", body, re.M))


def verify_schema(rust_path: Path) -> list[str]:
    """Cross-check the hardcoded schema against the Rust structs. Returns problems."""
    if not rust_path.exists():
        return []
    src = rust_path.read_text(encoding="utf-8", errors="replace")
    problems: list[str] = []
    for struct, section in STRUCT_OF_SECTION.items():
        got = parse_struct_fields(src, struct)
        want = KNOWN_SECTIONS if section is None else SECTION_KEYS[section]
        if got is None:
            problems.append(f"{struct}: not found in {rust_path.name} -- the struct was renamed")
            continue
        extra = sorted(want - got)
        missing = sorted(got - want)
        if extra:
            problems.append(f"{struct}: this audit allows {extra}, which the struct does not "
                            f"have -- those keys abort the load (deny_unknown_fields)")
        if missing:
            problems.append(f"{struct}: this audit does not know {missing}, which the struct "
                            f"DOES have -- a real key would be reported as unknown")
    return problems


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []  # level, key, value, note
        self.fails = 0

    def add(self, level: str, key: str, value, note: str) -> None:
        if level == "FAIL":
            self.fails += 1
        self.rows.append((level, key, str(value), note))

    def render(self) -> None:
        w = max(len(r[1]) for r in self.rows) if self.rows else 10
        for level, key, value, note in self.rows:
            print(f"  {level:4}  {key:<{w}}  {value:<10}  {note}")


def audit(cfg: dict, expect_kp: int) -> Report:
    rep = Report()
    gain, gain_set = effective(cfg, "policy", "gain")
    pkp, pkp_set = effective(cfg, "bus", "position_kp")
    pkp_head, head_set = effective(cfg, "bus", "position_kp_head")
    p_legs = register_kp(gain, pkp)
    p_head = register_kp(gain, pkp_head)

    # R1: what the legs' reg 50 will actually be. The failure this catches is not "gain
    # is not the trained number" -- it is "the mapping eats the number".
    where = (f"reg50 = round(policy.gain {gain} x position_kp {pkp} / {KP_REFERENCE:.0f})"
             f" = {p_legs}")
    if p_legs != expect_kp:
        want = round(expect_kp * KP_REFERENCE / gain) if gain else expect_kp
        rep.add("FAIL", "bus.position_kp", f"{pkp} (-> reg50 {p_legs})",
                f"{where}, but the plant was trained at Kp {expect_kp}. "
                f"position_kp = {want} would give it. "
                + (f"policy.gain = {gain} is an XL330-scale number, NOT reg 50 -- "
                   f"setting it to {expect_kp} with the default position_kp=8 writes "
                   f"round({expect_kp}*8/200) = {register_kp(expect_kp, 8)}"
                   if gain != KP_REFERENCE else ""))
    else:
        rep.add("ok", "bus.position_kp", f"{pkp} (-> reg50 {p_legs})",
                f"{where} -- matches the trained plant"
                + ("" if pkp_set else " (from default)"))

    if gain != KP_REFERENCE:
        rep.add("WARN", "policy.gain", gain,
                f"set in the file; the reference is {KP_REFERENCE:.0f} (feetech.rs:115). "
                f"Every ratio still survives (they all take the same round()), but this "
                f"number no longer means what the docs say it means -- and the register "
                f"value it produces is {p_legs}")
    else:
        rep.add("ok", "policy.gain", gain, "the XL330 reference the policies run at"
                + ("" if gain_set else " (from default)"))

    # The head group is a different register value on purpose (main.rs:1169 applies it to
    # joints 5..=9 = neck/head pitch/yaw/roll/mouth). Reported, not judged.
    rep.add("ok", "bus.position_kp_head", f"{pkp_head} (-> reg50 {p_head})",
            "joints 5..=9 only; the leg value does not reach them"
            + ("" if head_set else " (from default)")
            + ("  ⚠️ equal to the legs' -- upstream keeps it stiffer because at 6 the neck "
               "sagged 15 deg off the home pose" if p_head == p_legs else ""))

    # R2: limp must be a LOWER reg 50 than running, or a fall stiffens the robot.
    limp, limp_set = effective(cfg, "safety", "gain_limp")
    p_limp = register_kp(limp, pkp)
    if p_limp >= p_legs:
        rep.add("FAIL", "safety.gain_limp", f"{limp} (-> reg50 {p_limp})",
                f"not below the running {p_legs}: limp_fall would STIFFEN the robot. "
                f"Upstream's 50 lands at 2 because of the same round(); pick a smaller "
                f"gain_limp, or raise position_kp so the rounding stops collapsing")
    else:
        rep.add("ok", "safety.gain_limp", f"{limp} (-> reg50 {p_limp})",
                f"{p_limp / p_legs:.2f}x the running Kp"
                + ("" if limp_set else " (from default)"))

    # R3: standing back up after a fall runs at its own gain.
    pose, pose_set = effective(cfg, "safety", "limp_fall_pose_gain")
    p_pose = register_kp(pose, pkp)
    if p_pose > p_legs:
        rep.add("FAIL", "safety.limp_fall_pose_gain", f"{pose} (-> reg50 {p_pose})",
                f"stiffer than the running {p_legs}: the 0.6 s stand-back-up would slam. "
                f"Upstream's 160 lands at 6")
    elif p_pose == p_legs:
        rep.add("WARN", "safety.limp_fall_pose_gain", f"{pose} (-> reg50 {p_pose})",
                f"rounds onto the running Kp exactly -- no softening left"
                + ("" if pose_set else " (from default)"))
    else:
        rep.add("ok", "safety.limp_fall_pose_gain", f"{pose} (-> reg50 {p_pose})",
                f"{p_pose / p_legs:.2f}x running Kp" + ("" if pose_set else " (from default)"))

    # R4: standing runs at gain * ratio, and then through the same rounding.
    sgr, sgr_set = effective(cfg, "policy", "standing_gain_ratio")
    p_stand = p_legs                      # only reassigned when the ratio is a number
    if isinstance(sgr, (int, float)):
        p_stand = register_kp(gain * sgr, pkp)
        level = "ok" if 0.5 * p_legs <= p_stand <= 1.2 * p_legs else "WARN"
        rep.add(level, "policy.standing_gain_ratio", f"{sgr} (-> reg50 {p_stand})",
                f"standing Kp {p_stand} vs running {p_legs}"
                + ("" if sgr_set else f" (default {DEFAULTS['policy']['standing_gain_ratio']})"))

    # R4b: rounding is the only place the requested ratios can be lost. When two requests
    # differ by a real amount but land on the same register value, the safety layer stops
    # having the distinction it thinks it has -- and nothing in any log says so.
    collapse = []
    for name, req, got in (("gain_limp", limp, p_limp),
                           ("limp_fall_pose_gain", pose, p_pose),
                           ("standing", gain * sgr if isinstance(sgr, (int, float)) else gain,
                            p_stand)):
        if got == p_legs and gain and abs(req - gain) >= 0.10 * gain:
            collapse.append(f"{name} {req:.0f}->{got}")
    if collapse:
        rep.add("WARN", "bus.position_kp (rounding)", f"{pkp}",
                f"{', '.join(collapse)} all round onto the running reg50 {p_legs}: those "
                f"requests ask for a different stiffness and do not get one. Raise "
                f"position_kp to give the rounding room")

    # R5: action scale. Training used 1.0; robotd's default is the prototype's 0.9,
    # which would shrink every action by 10% before it reaches the PD loop.
    scale, scale_set = effective(cfg, "policy", "action_scale")
    if not scale_set:
        rep.add("FAIL", "policy.action_scale", f"{scale} (default)",
                "training used 1.0 (docs/05-flat-walk.md); the 0.9 default belongs to the "
                "alpha/velstand policies and shrinks every action 10%")
    elif scale != 1.0:
        rep.add("WARN", "policy.action_scale", scale,
                "training used 1.0 -- confirm this policy really was trained at this scale")
    else:
        rep.add("ok", "policy.action_scale", scale, "matches training")

    # R6: low-pass filters. The deploy default is 0.5 head / 0.7 legs, described in
    # robotd.toml as "the values the alpha policies are TRAINED with". That is NOT true of
    # this training pipeline: `grep -r low_pass` over microduck_rl + mjlab 1.3.0 + bam finds
    # nothing, and the action term is a plain `target = current + action*scale`
    # (mjlab/envs/mdp/actions/actions.py:231). So pass-through 1.0 is the value that matches;
    # anything else is a first-order filter the policy never saw (0.7 at 50 Hz = tau ~17 ms,
    # -2% at 2 Hz and -7% at 4 Hz, plus 6-11 deg of phase).
    for key in ("head_lowpass", "legs_lowpass"):
        val, was_set = effective(cfg, "policy", key)
        if val == 1.0:
            rep.add("ok", f"policy.{key}", val, "pass-through -- matches training (no filter)")
        else:
            rep.add("WARN", f"policy.{key}", val,
                    "training has NO low-pass (grep: zero hits in microduck_rl/mjlab/bam); "
                    "1.0 is the matching value. This one filters targets the policy never saw"
                    + ("" if was_set else " (from default)"))

    bus_tbl = cfg.get("bus") or {}
    # R7: bus identity
    port = (cfg.get("bus") or {}).get("port")
    rep.add("ok" if port else "WARN", "bus.port", port or "(unset)",
            "must be the tty the URT-2/bridge enumerates as, e.g. /dev/ttyS2 or /dev/ttyUSB0"
            if not port else "")
    # `fast_sync_read` used to be audited here as a real knob. It is not one in this
    # codebase: it appears ZERO times in the whole DuckBuddy tree, and the Feetech driver
    # only ever calls rustypot's sync_read_raw_data (feetech.rs:412,474,556), i.e. 0x82.
    # The key belongs to the other fork (params_lib.rs), so in a file for THIS robotd it
    # is an unknown key -> the whole config is refused. The unknown-key check above says
    # the mechanics; this row exists only so the message names the mistake.
    if "fast_sync_read" in bus_tbl:
        rep.add("FAIL", "bus.fast_sync_read", bus_tbl["fast_sync_read"],
                "no such field here (0 hits in the DuckBuddy tree). The 0x8A/0x82 choice is "
                "inside rustypot, not a config key -- and the bench answer is already in: "
                "0x8A returned 0 bytes on ID 10 while 0x82 sync read matched single reads "
                "(servo_probe/probe_sync_read.py). DELETE the line, do not set it false")
    # R7c: keys that do not exist. One of them aborts the whole load, so this is the
    # cheapest failure to catch off-hardware and the most expensive to debug on it.
    stray_sections = sorted(set(cfg) - KNOWN_SECTIONS)
    if stray_sections:
        rep.add("FAIL", "unknown section", ", ".join(stray_sections),
                "Params is #[serde(deny_unknown_fields)] (lib.rs:32): robotd refuses the "
                "whole file. Known sections: " + ", ".join(sorted(KNOWN_SECTIONS))
                + ("  -- `board` exists in the OLD generation (out/upstream_ref, Radxa+XL330, "
                   "which has a board.rs) but NOT in the Feetech one this audit targets: here "
                   "it is a load failure, not a setting" if "board" in stray_sections else ""))
    for sec, allowed in SECTION_KEYS.items():
        table = cfg.get(sec) or {}
        # `fast_sync_read` and `bus.protocol` get their own rows below, with the specific
        # "where this came from" story; listing them twice only pads the FAIL count.
        extra = sorted(k for k in table
                       if k not in allowed and k not in ("fast_sync_read", "protocol"))
        if extra:
            hint = ""
            if sec == "bus" and "baud" in extra:
                hint = ("  `baud` is compiled in (feetech.rs:35 BAUD_RATE = 500_000) and "
                        "lives in the servo as reg6 = 1, NOT here. Move it with "
                        "servo_probe/hd1910_ident.py baud")
            if sec == "bus" and "protocol" in extra:
                hint = ('  the key is bus.servo = "feetech_hls"; kissqy\'s protocol= targets '
                        "an older schema")
            rep.add("FAIL", f"{sec}.<unknown>", ", ".join(extra),
                    f"not a field of the {sec} struct; deny_unknown_fields aborts the load"
                    + hint)

    # R7b: which servo family. The key is `bus.servo` (robotd-params ServoKind), NOT
    # `bus.protocol` -- and Bus carries #[serde(deny_unknown_fields)], so a stray protocol=
    # line makes robotd refuse the whole file at startup. ServoKind's default IS FeetechHls,
    # so "servo absent" is correct here and must not be warned about.
    if "protocol" in bus_tbl:
        rep.add("FAIL", "bus.protocol", bus_tbl["protocol"],
                "upstream Bus is #[serde(deny_unknown_fields)] (robotd-params/src/lib.rs:934): "
                "an unknown key aborts the whole config load. The key is bus.servo = "
                "\"feetech_hls\". kissqy's robotd-selftrained.toml uses protocol= because it "
                "targets an older schema -- copying that line here bricks the daemon")
    servo, servo_set = effective(cfg, "bus", "servo")
    if servo == "feetech_hls":
        rep.add("ok", "bus.servo", servo,
                "Feetech branch: feetech.rs:95 RAD_PER_SEC_PER_COUNT = 0.732 rpm/count. "
                "BENCH 2026-11-04 (ID 10, 4.6 V): reg46 10/20 -> 49.4/49.3 counts/s per "
                "count (STS theory 49.97; the XL330 0.229 would give 15.63)"
                + ("" if servo_set else " (from default -- ServoKind::FeetechHls is #[default])"))
    elif servo == "dynamixel_xl330":
        rep.add("FAIL", "bus.servo", servo,
                "HD1910 is Feetech. bus.rs:31 would scale every joint velocity by 0.229/0.732 "
                "= 3.15x small and decode sign-magnitude as two's complement: 15 of 61 obs "
                "dims silently wrong, no error anywhere")
    else:
        rep.add("FAIL", "bus.servo", servo,
                "not a ServoKind variant (feetech_hls / dynamixel_xl330); serde refuses it")

    jids = bus_tbl.get("joint_ids") or []
    if not jids:
        rep.add("FAIL", "bus.joint_ids", "(empty)",
                "the Feetech bus refuses to open without the joint->ID map rather than guess "
                "which servo is which joint (robotd/src/main.rs:5495). Fill 15 entries in "
                "JOINT_NAMES order")
    elif len(jids) != NUM_JOINTS or len(set(jids)) != len(jids):
        rep.add("FAIL", "bus.joint_ids", f"{len(jids)} ids",
                f"need exactly {NUM_JOINTS} distinct IDs in JOINT_NAMES order")
    elif sorted(jids) != sorted(REFERENCE_JOINT_IDS):
        rep.add("WARN", "bus.joint_ids", f"{len(jids)} ids",
                "distinct, but not the reference set "
                f"{REFERENCE_JOINT_IDS} (model.rs:15). Could be real -- this airframe is not "
                "the XL330 duck -- or a mis-pairing, which drives one joint with another's "
                "targets. Re-check with servo_probe/identify_joints.py")
    else:
        rep.add("ok", "bus.joint_ids", f"{len(jids)} ids",
                "the reference set, in JOINT_NAMES order -- matches model.rs:15. Still not "
                "measured on THIS robot: one deflection per joint settles it")

    # R9: the pack. The default is cells = [2, 3], and with both accepted a 3S pack reads as
    # a perfectly valid 3S (11.1 V / 3 = 3.7 V a cell) and robotd drives the servos at it.
    # HD-1910s are 4-8.4 V and burn on 3S (lib.rs:52). Nothing about this fails loudly.
    cells, cells_set = effective(cfg, "battery", "cells")
    cells = list(cells or [])
    if 3 in cells:
        rep.add("FAIL", "battery.cells", cells,
                "a 3S pack would be accepted and driven: HD-1910s are rated 4-8.4 V and burn "
                "on 3S (lib.rs:52). Use [2]"
                + ("" if cells_set else " (this is the [2, 3] default -- nothing in the file "
                                        "said otherwise)"))
    elif 2 not in cells:
        rep.add("FAIL", "battery.cells", cells,
                "2S not allowed -- this robot runs a 2S pack, and identify_pack would refuse it")
    else:
        rep.add("ok", "battery.cells", cells, "2S only" + ("" if cells_set else " (default)"))
    mv, mv_set = effective(cfg, "battery", "max_volts")
    if not mv_set or not isinstance(mv, (int, float)):
        rep.add("WARN", "battery.max_volts", mv,
                "0 = only the cell count is checked. A full 2S LiHV is 8.7 V, over the "
                f"HD-1910's {HD1910_MAX_V} rating; set {HD1910_MAX_V}")
    elif mv > HD1910_MAX_V:
        rep.add("WARN", "battery.max_volts", mv,
                f"above the servo rating {HD1910_MAX_V} V -- a pack that reads over the "
                f"rating is refused, so this lets it through")
    else:
        rep.add("ok", "battery.max_volts", mv, f"refuses a pack over the {HD1910_MAX_V} V rating")

    # R10: the thermal guard. The servo latches its own shutdown at reg13 = 80 degC and cuts
    # torque, which drops a walking robot; walk_max_c must stop short of it.
    wm, wm_set = effective(cfg, "thermal", "walk_max_c")
    if not isinstance(wm, (int, float)) or wm <= 0:
        rep.add("WARN", "thermal.walk_max_c", wm,
                "0 = no guard. The servo's own latch is reg13 = 80 degC and it drops the "
                "robot; set 70 (10 degC of margin, the HL-2915 robot's choice after a "
                "walking trial took its hottest servo to 61)")
    elif wm >= SERVO_OVERHEAT_C:
        rep.add("FAIL", "thermal.walk_max_c", wm,
                f"at or above the servo's own latch ({SERVO_OVERHEAT_C:.0f} degC): the guard "
                f"never acts before the servo cuts torque")
    else:
        rep.add("ok", "thermal.walk_max_c", wm,
                f"{SERVO_OVERHEAT_C - wm:.0f} degC below the servo's reg13 latch"
                + ("" if wm_set else " (from default)"))
    warn_c, _ = effective(cfg, "thermal", "warn_c")
    if isinstance(wm, (int, float)) and isinstance(warn_c, (int, float)) and warn_c >= wm:
        rep.add("WARN", "thermal.warn_c", warn_c,
                f"not below walk_max_c {wm}: the warning never precedes the refusal")

    # R10b: [thermal] section internal consistency (2026-11-04)
    # The guard has four actions in order: warn → rest → sit → walk-blocked.
    # Each threshold must fire before the one that acts more strongly, and the
    # hysteresis must be positive so a reading hovering on a threshold does not flap.
    sr, _ = effective(cfg, "thermal", "rest_c")
    rc, _ = effective(cfg, "thermal", "resume_c")
    rsm, _ = effective(cfg, "thermal", "rest_min_s")
    hy, _ = effective(cfg, "thermal", "hysteresis_c")
    sc, _ = effective(cfg, "thermal", "sit_c")
    if isinstance(sr, (int, float)) and isinstance(wm, (int, float)) and sr > 0 and sr >= wm:
        rep.add("WARN", "thermal.rest_c", sr,
                f"at or above walk_max_c {wm}: rest (legs go limp) fires at the same "
                f"temperature as walk-blocked, so the legs drop instead of refusing")
    if isinstance(sr, (int, float)) and isinstance(rc, (int, float)) and sr > 0 and rc >= sr:
        rep.add("WARN", "thermal.resume_c", rc,
                f"not below rest_c {sr}: a rest can never end -- the servo cools below "
                f"resume_c only after it has already cooled below rest_c")
    if isinstance(hy, (int, float)) and hy <= 0:
        rep.add("WARN", "thermal.hysteresis_c", hy,
                "must be > 0: with 0, a reading hovering on a threshold flaps the guard")
    if isinstance(rsm, (int, float)) and rsm < 0:
        rep.add("WARN", "thermal.rest_min_s", rsm, "negative: a rest lasts negative time")
    if isinstance(sc, (int, float)) and isinstance(sr, (int, float)) and sc > 0 and sc <= sr:
        rep.add("WARN", "thermal.sit_c", sc,
                f"at or below rest_c {sr}: sit (keeps torque) fires before rest (drops it), "
                f"so the robot sits down and then immediately goes limp on top of it")

    # R10c: rest_head_c consistency (2026-11-04)
    # `rest_head_c > 0` makes a hot head limp along with the legs in a deep rest. It must
    # fire before walk_max_c (a servo that hot would already have walk-blocked the robot)
    # and after warn_c (a head limping at a temperature that hasn't even warned is too eager).
    rhc, _ = effective(cfg, "thermal", "rest_head_c")
    if isinstance(rhc, (int, float)) and rhc > 0 and isinstance(wm, (int, float)) and rhc >= wm:
        rep.add("WARN", "thermal.rest_head_c", rhc,
                f"at or above walk_max_c {wm}: by the time the head is this hot the robot "
                f"is already walk-blocked, so a deep rest for the head never fires")
    if isinstance(rhc, (int, float)) and rhc > 0 and isinstance(warn_c, (int, float)) and rhc <= warn_c:
        rep.add("WARN", "thermal.rest_head_c", rhc,
                f"at or below warn_c {warn_c}: the head limps in a deep rest before it has "
                f"even warned, so the deep-rest trigger fires too eagerly")
    if isinstance(rhc, (int, float)) and rhc == 0:
        rep.add("ok", "thermal.rest_head_c", rhc, "0 = off (the head never limps in a rest)")

    # R10d: deep_sit without a lie policy (2026-11-04)
    # `deep_sit = false` means a deep rest lies down (the lie policy). Without one the
    # deep rest is silently skipped (main.rs:3623) -- the legs go limp but the body
    # cannot get down. This is not a config error per se, but worth flagging.
    ds, ds_set = effective(cfg, "thermal", "deep_sit")
    if ds_set and ds is False:
        rep.add("WARN", "thermal.deep_sit", ds,
                "false means a deep rest lies down (the lie policy). Without a lie policy "
                "the deep rest is silently skipped -- the legs go limp but the body cannot "
                "get down (main.rs:3623). Set true to sit instead, or provide a lie policy")

    # R8: safety verdicts that are reported, not enforced
    fz, _ = effective(cfg, "safety", "fall_gravity_z")
    rep.add("ok", "safety.fall_gravity_z", fz,
            "60 deg: a REPORT only; limp_fall is what acts (docs/05-flat-walk.md 22.9)")
    dm, _ = effective(cfg, "safety", "deadman_ms")
    rep.add("ok", "safety.deadman_ms", dm, "zeroes twist only; torque stays on")

    # R9: limp_fall (FallPredictor) internal consistency (2026-11-04)
    # The predictor has three conditions: already tilted past tilt_z, extrapolating past
    # predict_z in lookahead, held together for debounce. Each must be consistent with the
    # SafetyConfig fall verdict, or the limp either never fires or fires on a standing robot.
    #
    # gravity_z goes from -1.0 (upright) to 0 (flat). "Tilted" = already past tilt_z
    # (more negative than tilt_z). "Predicted fallen" = extrapolation reaches predict_z.
    # tilt_z MUST be more negative than predict_z (already-tilted is a prerequisite for
    # prediction; if tilt_z >= predict_z, the "already tilted" gate blocks every prediction).
    # debounce MUST be shorter than fall_debounce: the predictor fires before the actual
    # fall verdict, so it can't wait longer than the thing it predicts.
    lf_tilt, _ = effective(cfg, "safety", "limp_fall_tilt_z")
    lf_pred, _ = effective(cfg, "safety", "limp_fall_predict_z")
    lf_deb, _ = effective(cfg, "safety", "limp_fall_debounce_ms")
    fd_ms, _ = effective(cfg, "safety", "fall_debounce_ms")
    if (isinstance(lf_tilt, (int, float)) and isinstance(lf_pred, (int, float))
            and lf_tilt > lf_pred):
        rep.add("WARN", "safety.limp_fall_tilt_z", lf_tilt,
                f"more negative than predict_z {lf_pred}: the 'already tilted' gate blocks "
                f"every prediction, so the limp never fires while the robot is falling")
    if (isinstance(lf_pred, (int, float)) and isinstance(fz, (int, float))
            and abs(lf_pred - fz) > 0.01 and not isinstance(fz, bool)):
        rep.add("ok", "safety.limp_fall_predict_z", lf_pred,
                f"differs from fall_gravity_z {fz} -- deliberate? (default is the same number)")
    if (isinstance(lf_deb, (int, float)) and isinstance(fd_ms, (int, float))
            and lf_deb >= fd_ms):
        rep.add("WARN", "safety.limp_fall_debounce_ms", lf_deb,
                f"at or above fall_debounce_ms {fd_ms}: the predictor waits longer than the "
                f"fall verdict it predicts, so the limp fires after the robot has already "
                f"landed (fall.rs:38-46, safety.rs:180-210)")

    # R11: [update_gate] must match the control rate (2026-11-04)
    # The defaults are calibrated against 50 Hz: min_achieved_hz = 45 (90%),
    # stall_periods = 25 (500 ms at 50 Hz). If [control] hz is changed without
    # retuning these, the consequences are silent:
    #   hz dropped (say 20) but min_achieved_hz still 45 -> the loop can NEVER
    #   reach 45 Hz so robotd reports unhealthy forever -> silent auto-rollback.
    #   hz raised (say 100) but stall_periods still 25 -> 250 ms window, ordinary
    #   scheduler jitter trips the dead-loop detector on a healthy robot.
    ct, _ct_set = effective(cfg, "control", "hz")
    ua, _ua_set = effective(cfg, "update_gate", "min_achieved_hz")
    sp, _sp_set = effective(cfg, "update_gate", "stall_periods")
    me, _me_set = effective(cfg, "update_gate", "max_consecutive_errors")
    if (isinstance(ct, (int, float)) and ct > 0
            and isinstance(ua, (int, float))):
        rep.add("ok", "update_gate.min_achieved_hz", ua,
                f"{ua:.0f} Hz vs control.hz {ct:.0f} ({ua/ct:.0%} of the target rate)")
        if ua >= ct:
            rep.add("WARN", "update_gate.min_achieved_hz", ua,
                    f"at or above control.hz {ct}: the loop can never reach this rate. "
                    f"robotd reports unhealthy forever and silently auto-rolls back")
    if (isinstance(ct, (int, float)) and ct > 0
            and isinstance(sp, (int, float))):
        stall_ms = sp / ct * 1000.0
        rep.add("ok", "update_gate.stall_periods", f"{sp} ({stall_ms:.0f} ms)",
                f"at control.hz {ct:.0f}, 500 ms is the default window")
        if stall_ms < 300.0:
            rep.add("WARN", "update_gate.stall_periods", sp,
                    f"{stall_ms:.0f} ms at {ct:.0f} Hz -- ordinary scheduler jitter on a "
                    f"loaded board is 80 ms, so the dead-loop detector trips on a healthy "
                    f"robot and rolls back a good release")
        if stall_ms > 2000.0:
            rep.add("WARN", "update_gate.stall_periods", sp,
                    f"{stall_ms:.0f} ms at {ct:.0f} Hz -- a genuinely wedged loop takes this "
                    f"long to detect; the dead-loop detector fires too late")
    if isinstance(me, (int, float)) and me == 0:
        rep.add("WARN", "update_gate.max_consecutive_errors", me,
                "0 tolerates NO bus error: a single dropped transaction (ordinary on a "
                "bus) is enough to report unhealthy and trigger auto-rollback")

    # R13: [control] heading_hold_gain -- the policy was never trained with it (2026-11-05)
    # The default is 0.0 (off). Turning it on adds a heading PD loop around the policy's
    # own heading command; the robot veers or drifts, and the symptom reads as "unbalanced
    # motors" or "the policy doesn't walk straight", not as a config error.
    hh, _hh_set = effective(cfg, "control", "heading_hold_gain")
    if isinstance(hh, (int, float)) and hh > 0:
        rep.add("WARN", "control.heading_hold_gain", hh,
                "nonzero: an extra heading PD the policy was never trained with. "
                "Symptom is a robot that veers or drifts, not an error")
    else:
        rep.add("ok", "control.heading_hold_gain", hh, "off (matches training)")

    return rep


def selftest() -> int:
    fails: list[str] = []

    def check(name: str, cond: bool) -> None:
        print(f"  {'ok  ' if cond else 'FAIL'} {name}")
        if not cond:
            fails.append(name)

    # The mapping itself, pinned against upstream's own unit tests
    # (feetech.rs:875 gain_scales_from_the_reference). If these drift, every verdict below
    # is arithmetic on the wrong number.
    check("kp_for_gain(200, 8) = 8", register_kp(200, 8) == 8)
    check("kp_for_gain(50, 8) = 2", register_kp(50, 8) == 2)
    check("kp_for_gain(160, 8) = 6", register_kp(160, 8) == 6)
    check("kp_for_gain(0, 8) = 1 (never zero)", register_kp(0, 8) == 1)
    check("kp_for_gain(200, 16) = 16", register_kp(200, 16) == 16)

    base_bus = {"port": "/dev/ttyS2", "servo": "feetech_hls",
                "joint_ids": list(range(1, 16))}
    good = {
        "policy": {"action_scale": 1.0, "standing_gain_ratio": 0.8,
                   "head_lowpass": 1.0, "legs_lowpass": 1.0},
        "bus": dict(base_bus),
        "battery": {"cells": [2], "max_volts": 8.4},
        "thermal": {"walk_max_c": 70.0},
        "safety": {},
    }
    r2 = audit(good, 8)
    check("a default file (gain 200, position_kp 8) passes", r2.fails == 0)
    check("...and reports reg50 = 8",
          any(k == "bus.position_kp" and "reg50 8" in v for _, k, v, _ in r2.rows))

    # 🔴 THE regression: gain=8 was demanded by an earlier version of this file. With the
    # default position_kp it writes 0.32 -> 1, i.e. every servo at its softest Kp.
    hazard = dict(good, policy=dict(good["policy"], gain=8))
    r_h = audit(hazard, 8)
    check("policy.gain = 8 (with default position_kp) is a FAIL",
          any(k == "bus.position_kp" and lv == "FAIL" for lv, k, _, _ in r_h.rows))
    check("...and the message says it lands on reg50 1",
          any("reg50 1" in v or "round(8*8/200) = 1" in n
              for _, _, v, n in r_h.rows))

    # The plant-equivalent deployment for mode 0 is position_kp = 16, not gain = 16.
    dev16 = dict(good, bus=dict(base_bus, position_kp=16))
    check("position_kp=16 is a FAIL when the plant is Kp8", audit(dev16, 8).fails > 0)
    check("...and passes when the plant is Kp16", audit(dev16, 16).fails == 0)

    # gain=400 / position_kp=8 is the same register value as 200/16 -- the mapping is what
    # binds, so a rescaled file must audit identically.
    alt = dict(good, policy=dict(good["policy"], gain=400))
    check("gain=400 x position_kp=8 == position_kp=16 (reg50 16)",
          audit(alt, 16).fails == 0)

    # Rounding collapse: at position_kp=2 a requested 160 lands on the running 2, so the
    # stand-back-up stops being softer than walking without any single check turning red.
    squash = dict(good, bus=dict(base_bus, position_kp=2))
    r_s = audit(squash, 2)
    check("position_kp=2 makes the requested ratios vanish -> WARN",
          any("rounding" in k and lv == "WARN" for lv, k, _, _ in r_s.rows))
    check("...and it does NOT fire at the default position_kp=8",
          not any("rounding" in k for _, k, _, _ in r2.rows))

    # limp stiffer than running, in register units
    stifflimp = dict(good, safety={"gain_limp": 300})
    check("gain_limp above the running gain is a FAIL",
          any(k == "safety.gain_limp" and lv == "FAIL"
              for lv, k, _, _ in audit(stifflimp, 8).rows))

    check("missing action_scale is a FAIL",
          any(k == "policy.action_scale" and lv == "FAIL"
              for lv, k, _, _ in audit({"policy": {}, "bus": dict(base_bus)}, 8).rows))

    # negative controls for the two deploy defaults that look harmless and are not
    only_defaults = dict(good, policy=dict(good["policy"]))
    only_defaults["policy"].pop("legs_lowpass")          # falls back to 0.7
    r4 = audit(only_defaults, 8)
    check("default legs_lowpass 0.7 raises a WARN",
          any(k == "policy.legs_lowpass" and lv == "WARN" for lv, k, _, _ in r4.rows))

    # `fast_sync_read` is NOT a knob in this codebase (0 hits in the DuckBuddy tree). It used
    # to be reported here as a WARN-or-ok, which taught the reader to keep a line that makes
    # robotd refuse the whole file.
    fs = dict(good, bus=dict(base_bus, fast_sync_read=False))
    r5 = audit(fs, 8)
    check("fast_sync_read raises a FAIL, not a WARN",
          any(k == "bus.fast_sync_read" and lv == "FAIL" for lv, k, _, _ in r5.rows))

    # which servo family: bus.servo is the real key; bus.protocol does not exist and, because
    # Bus is deny_unknown_fields, would abort the daemon's config load outright.
    dx = dict(good, bus=dict(base_bus, servo="dynamixel_xl330"))
    r6 = audit(dx, 8)
    check("servo=dynamixel_xl330 is a FAIL",
          any(k == "bus.servo" and lv == "FAIL" for lv, k, _, _ in r6.rows))

    nk = dict(good, bus=dict(base_bus))          # servo absent -> ServoKind default
    r7 = audit(nk, 8)
    check("absent servo is NOT a warning (default is feetech_hls)",
          any(k == "bus.servo" and lv == "ok" for lv, k, _, _ in r7.rows)
          and r7.fails == 0)

    pk = dict(good, bus=dict(base_bus, protocol="feetech"))
    r8 = audit(pk, 8)
    check("a stray bus.protocol line is a FAIL (deny_unknown_fields)",
          any(k == "bus.protocol" and lv == "FAIL" for lv, k, _, _ in r8.rows))

    noids = dict(good, bus={"port": "/dev/ttyS2", "servo": "feetech_hls"})
    r9 = audit(noids, 8)
    check("empty joint_ids is a FAIL (bus refuses to open)",
          any(k == "bus.joint_ids" and lv == "FAIL" for lv, k, _, _ in r9.rows))

    dupids = dict(good, bus=dict(base_bus, joint_ids=[1] * 15))
    r10 = audit(dupids, 8)
    check("duplicate joint_ids is a FAIL",
          any(k == "bus.joint_ids" and lv == "FAIL" for lv, k, _, _ in r10.rows))

    # the plain ratio arithmetic, independent of the audit logic
    check("50/8 is 6.25x", abs(50 / 8 - 6.25) < 1e-12)
    check("50/200 is 0.25x", abs(50 / 200 - 0.25) < 1e-12)

    # ---- keys that do not exist (deny_unknown_fields kills the whole file) ----
    bd = dict(good, board={"version": "zero3"})
    check("[board] is a FAIL (no such section; it used to be a phantom row here)",
          any(k == "unknown section" and lv == "FAIL" for lv, k, _, _ in audit(bd, 8).rows))
    baw = dict(good, bus=dict(base_bus, baud=500_000))
    r_baw = audit(baw, 8)
    check("bus.baud is a FAIL", any(k == "bus.<unknown>" and lv == "FAIL"
                                    for lv, k, _, _ in r_baw.rows))
    check("...and says the rate is reg6 / compiled in",
          any("reg6" in n for _, _, _, n in r_baw.rows))
    jn = dict(good, bus=dict(base_bus, joint_names=["a"]))
    check("bus.joint_names is a FAIL", any(k == "bus.<unknown>"
                                           for lv, k, _, _ in audit(jn, 8).rows))

    # ---- the pack: the [2, 3] default accepts a 3S and burns the servos ----
    nobat = dict(good)
    nobat.pop("battery")
    r_bat = audit(nobat, 8)
    check("absent [battery] falls back to [2, 3] -> FAIL",
          any(k == "battery.cells" and lv == "FAIL" for lv, k, _, _ in r_bat.rows))
    three_s = dict(good, battery={"cells": [2, 3], "max_volts": 8.4})
    check("cells = [2, 3] is a FAIL (3S burns an HD-1910)",
          any(k == "battery.cells" and lv == "FAIL"
              for lv, k, _, _ in audit(three_s, 8).rows))
    nov = dict(good, battery={"cells": [2]})
    check("max_volts absent -> WARN", any(k == "battery.max_volts" and lv == "WARN"
                                          for lv, k, _, _ in audit(nov, 8).rows))
    check("cells = [2] + 8.4 V passes", audit(good, 8).fails == 0)

    # ---- the thermal guard must stop before the servo's own latch ----
    hot = dict(good, thermal={"walk_max_c": 80.0})
    check("walk_max_c at the servo's 80 degC latch is a FAIL",
          any(k == "thermal.walk_max_c" and lv == "FAIL"
              for lv, k, _, _ in audit(hot, 8).rows))
    off = dict(good, thermal={"walk_max_c": 0.0})
    check("walk_max_c = 0 (guard off) is a WARN",
          any(k == "thermal.walk_max_c" and lv == "WARN"
              for lv, k, _, _ in audit(off, 8).rows))
    check("walk_max_c 70 is ok", any(k == "thermal.walk_max_c" and lv == "ok"
                                     for lv, k, _, _ in audit(good, 8).rows))

    # ---- [thermal] section internal consistency: negative controls ----
    # rest_c at or above walk_max_c: rest fires at the same temp as walk-blocked
    r_rest_hot = dict(good, thermal={"walk_max_c": 70.0, "rest_c": 70.0})
    check("rest_c == walk_max_c is a WARN",
          any(k == "thermal.rest_c" and lv == "WARN"
              for lv, k, _, _ in audit(r_rest_hot, 8).rows))
    # resume_c >= rest_c: a rest can never end
    r_never_end = dict(good, thermal={"rest_c": 60.0, "resume_c": 60.0})
    check("resume_c == rest_c is a WARN",
          any(k == "thermal.resume_c" and lv == "WARN"
              for lv, k, _, _ in audit(r_never_end, 8).rows))
    # hysteresis <= 0: flaps on a hovering reading
    r_no_hyst = dict(good, thermal={"hysteresis_c": 0.0})
    check("hysteresis_c = 0 is a WARN",
          any(k == "thermal.hysteresis_c" and lv == "WARN"
              for lv, k, _, _ in audit(r_no_hyst, 8).rows))
    # sit_c <= rest_c: sit fires before rest, robot sits then immediately goes limp
    r_sit_first = dict(good, thermal={"rest_c": 60.0, "sit_c": 55.0})
    check("sit_c < rest_c is a WARN",
          any(k == "thermal.sit_c" and lv == "WARN"
              for lv, k, _, _ in audit(r_sit_first, 8).rows))
    # rest_min_s negative
    r_neg_min = dict(good, thermal={"rest_min_s": -5.0})
    check("rest_min_s negative is a WARN",
          any(k == "thermal.rest_min_s" and lv == "WARN"
              for lv, k, _, _ in audit(r_neg_min, 8).rows))
    # rest_head_c >= walk_max_c: by the time the head is this hot, walk is already blocked
    r_head_late = dict(good, thermal={"walk_max_c": 70.0, "rest_head_c": 70.0})
    check("rest_head_c == walk_max_c is a WARN",
          any(k == "thermal.rest_head_c" and lv == "WARN"
              for lv, k, _, _ in audit(r_head_late, 8).rows))
    # rest_head_c <= warn_c: head limps before it even warns
    r_head_early = dict(good, thermal={"walk_max_c": 70.0, "warn_c": 55.0, "rest_head_c": 55.0})
    check("rest_head_c == warn_c is a WARN",
          any(k == "thermal.rest_head_c" and lv == "WARN"
              for lv, k, _, _ in audit(r_head_early, 8).rows))
    # rest_head_c = 0 (off) is ok
    r_head_off = dict(good, thermal={"walk_max_c": 70.0, "rest_head_c": 0.0})
    check("rest_head_c = 0 is ok (off)",
          any(k == "thermal.rest_head_c" and lv == "ok"
              for lv, k, _, _ in audit(r_head_off, 8).rows))
    # deep_sit = false (no lie policy) is a WARN
    r_no_lie = dict(good, thermal={"deep_sit": False})
    check("deep_sit = false is a WARN",
          any(k == "thermal.deep_sit" and lv == "WARN"
              for lv, k, _, _ in audit(r_no_lie, 8).rows))

    # ---- limp_fall (FallPredictor) consistency: negative controls ----
    # tilt_z > predict_z (i.e. not more negative): the "already tilted" gate blocks predictions
    r_lf_tilt = dict(good, safety=dict(good["safety"],
                                       limp_fall_tilt_z=-0.40, limp_fall_predict_z=-0.50))
    check("limp_fall_tilt_z > predict_z is a WARN",
          any(k == "safety.limp_fall_tilt_z" and lv == "WARN"
              for lv, k, _, _ in audit(r_lf_tilt, 8).rows))
    # limp_fall_debounce_ms >= fall_debounce_ms: predictor waits longer than the fall verdict
    r_lf_deb = dict(good, safety=dict(good["safety"],
                                      limp_fall_debounce_ms=250, fall_debounce_ms=200))
    check("limp_fall_debounce_ms >= fall_debounce_ms is a WARN",
          any(k == "safety.limp_fall_debounce_ms" and lv == "WARN"
              for lv, k, _, _ in audit(r_lf_deb, 8).rows))
    # default limp_fall values pass
    r_lf_ok = dict(good)
    check("default limp_fall values are ok",
          not any(k.startswith("safety.limp_fall_tilt_z") and lv == "WARN"
                  for lv, k, _, _ in audit(r_lf_ok, 8).rows))

    # ---- heading_hold_gain (R13): nonzero is a silent veer ----
    r_heading = dict(good, control={"hz": 50, "heading_hold_gain": 0.5})
    check("heading_hold_gain > 0 is a WARN",
          any(k == "control.heading_hold_gain" and lv == "WARN"
              for lv, k, _, _ in audit(r_heading, 8).rows))
    r_heading_off = dict(good, control={"hz": 50, "heading_hold_gain": 0.0})
    check("heading_hold_gain = 0 is ok (off)",
          any(k == "control.heading_hold_gain" and lv == "ok"
              for lv, k, _, _ in audit(r_heading_off, 8).rows))

    # ---- [update_gate] must match [control] hz: negative controls ----
    # min_achieved_hz >= control.hz: loop can never reach it -> permanent unhealthy
    r_gate_impossible = dict(good, control={"hz": 20.0},
                             update_gate={"min_achieved_hz": 45.0})
    check("min_achieved_hz >= control.hz is a WARN",
          any(k == "update_gate.min_achieved_hz" and lv == "WARN"
              for lv, k, _, _ in audit(r_gate_impossible, 8).rows))
    # stall_periods at a high hz: 25 periods at 200 Hz = 125 ms < 300 ms
    r_gate_jitter = dict(good, control={"hz": 200.0},
                         update_gate={"stall_periods": 25})
    check("stall_periods too tight at 200 Hz is a WARN",
          any(k == "update_gate.stall_periods" and lv == "WARN"
              for lv, k, _, _ in audit(r_gate_jitter, 8).rows))
    # stall_periods at a low hz: 25 periods at 2 Hz = 12.5 s > 2 s
    r_gate_late = dict(good, control={"hz": 2.0},
                       update_gate={"stall_periods": 25})
    check("stall_periods too loose at 2 Hz is a WARN",
          any(k == "update_gate.stall_periods" and lv == "WARN"
              for lv, k, _, _ in audit(r_gate_late, 8).rows))
    # max_consecutive_errors = 0: one dropped transaction trips it
    r_gate_no_err = dict(good, update_gate={"max_consecutive_errors": 0})
    check("max_consecutive_errors = 0 is a WARN",
          any(k == "update_gate.max_consecutive_errors" and lv == "WARN"
              for lv, k, _, _ in audit(r_gate_no_err, 8).rows))
    # default hz (50) + default gate -> ok
    r_gate_ok = dict(good)
    check("default 50 Hz + default gate passes",
          any(k == "update_gate.min_achieved_hz" and lv == "ok"
              for lv, k, _, _ in audit(r_gate_ok, 8).rows))

    # ---- joint_ids: a distinct-but-different map is a WARN, not a pass ----
    ref = dict(good, bus=dict(base_bus, joint_ids=list(REFERENCE_JOINT_IDS)))
    check("the reference set is ok", any(k == "bus.joint_ids" and lv == "ok"
                                         for lv, k, _, _ in audit(ref, 8).rows))
    check("a map outside the reference set is a WARN",
          any(k == "bus.joint_ids" and lv == "WARN"
              for lv, k, _, _ in audit(good, 8).rows))

    # ---- the whitelist must be derivable from the Rust source, not remembered ----
    snippet = (
        'pub struct Bus {\n'
        '    /// doc line with a brace { in it\n'
        '    pub port: String,\n'
        '    pub joint_ids: Vec<u8>,\n'
        '}\n'
    )
    check("parser finds the two fields, ignores doc lines",
          parse_struct_fields(snippet, "Bus") == {"port", "joint_ids"})
    check("parser returns None for a struct that is not there",
          parse_struct_fields(snippet, "Nope") is None)

    if DEFAULT_SCHEMA_RS.exists():
        check("whitelist matches robotd-params/src/lib.rs",
              verify_schema(DEFAULT_SCHEMA_RS) == [])
        # negative control: one invented key must be caught
        SECTION_KEYS["bus"].add("fast_sync_read")
        try:
            caught = verify_schema(DEFAULT_SCHEMA_RS)
        finally:
            SECTION_KEYS["bus"].discard("fast_sync_read")
        check("...and an invented key is caught",
              any("fast_sync_read" in p for p in caught))
    else:
        print("  skip  whitelist cross-check (no .upstream copy) -- run with --schema-rs")

    print()
    if fails:
        print(f"SELFTEST FAILED ({len(fails)}): {', '.join(fails)}")
        return 3
    print("selftest passed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit robotd.toml against the trained gain scale.")
    ap.add_argument("--toml", default="deploy/robotd.toml")
    ap.add_argument("--expect-kp", type=int, default=8,
                    help="the reg-50 Kp the plant was trained at (not policy.gain)")
    ap.add_argument("--schema-rs", default=None,
                    help="robotd-params/src/lib.rs to re-derive the key whitelist from "
                         "(default: the .upstream copy if present)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    path = Path(args.toml)
    if not path.exists():
        print(f"no such file: {path}")
        print("pass --toml explicitly; inside this repo the upstream file is deploy/robotd.toml")
        return 2
    with path.open("rb") as fh:
        cfg = tomllib.load(fh)

    print(f"== {path} (expecting reg50 = {args.expect_kp}) ==")
    schema_rs = Path(args.schema_rs) if args.schema_rs else DEFAULT_SCHEMA_RS
    problems = verify_schema(schema_rs)
    if problems:
        print(f"  FAIL  schema  {'':<10}  the key whitelist does not match {schema_rs}:")
        for p in problems:
            print(f"        - {p}")
    elif schema_rs.exists():
        print(f"  ok    schema  {'':<10}  key whitelist re-derived from {schema_rs.name} "
              f"(Params + Bus + BatteryParams + Thermal)")
    rep = audit(cfg, args.expect_kp)
    rep.render()
    print()
    fails = rep.fails + len(problems)
    print(f"{fails} FAIL" if fails else "all pass")
    print("\nnot checked: whether robotd is running, what it wrote to reg 50, or whether the "
          "bridge answers -- for reg 50 read it back on the robot after robotd starts.")
    print("Also not in this file: reg6 (baud) and reg33 (mode). robotd CHECKS those and "
          "refuses to open the bus on a mismatch (feetech.rs:386); the rate is compiled in "
          "(500 kbps) and the servo ships at 1 Mbps, so they must be moved on the servo.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
