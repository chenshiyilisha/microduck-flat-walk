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
    "bus": {"fast_sync_read": True, "servo": "feetech_hls",
            "position_kp": 8, "position_kp_head": 16, "position_kd": 8},
    "board": {"version": "zero3"},
}

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

    # R7: bus / board identity
    port = (cfg.get("bus") or {}).get("port")
    rep.add("ok" if port else "WARN", "bus.port", port or "(unset)",
            "must be the tty the URT-2/bridge enumerates as, e.g. /dev/ttyS2 or /dev/ttyUSB0"
            if not port else "")
    fast, fast_set = effective(cfg, "bus", "fast_sync_read")
    if fast:
        rep.add("WARN", "bus.fast_sync_read", fast,
                "0x8A is a DYNAMIXEL P2.0 instruction; HD-1910 is Feetech (0x82 sync read). "
                "robotd's own note: a device that does not implement 0x8A does not answer, so "
                "EVERY read times out and the journal fills with 'bus read failed' -- which "
                "reads as wiring or baud at first power-on. Set false unless the HD1910 "
                "firmware is proven to answer 0x8A (one packet at the bench)"
                + ("" if fast_set else " (from default)"))
    else:
        rep.add("ok", "bus.fast_sync_read", fast,
                "plain 0x82 sync read -- correct for Feetech; MEASURED 2026-11-04 on ID 10: "
                "0x8A returned 0 bytes while PING/0x82 single-read both answered "
                "(servo_probe/probe_sync_read.py)")
    board, _ = effective(cfg, "board", "version")
    rep.add("ok", "board.version", board,
            "declared, not detected (board.rs:1) -- only gates camera/hw_rev")

    # R7b: which servo family. The key is `bus.servo` (robotd-params ServoKind), NOT
    # `bus.protocol` -- and Bus carries #[serde(deny_unknown_fields)], so a stray protocol=
    # line makes robotd refuse the whole file at startup. ServoKind's default IS FeetechHls,
    # so "servo absent" is correct here and must not be warned about.
    bus_tbl = cfg.get("bus") or {}
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
    else:
        rep.add("ok", "bus.joint_ids", f"{len(jids)} ids", "mapped")

    # R8: safety verdicts that are reported, not enforced
    fz, _ = effective(cfg, "safety", "fall_gravity_z")
    rep.add("ok", "safety.fall_gravity_z", fz,
            "60 deg: a REPORT only; limp_fall is what acts (docs/05-flat-walk.md 22.9)")
    dm, _ = effective(cfg, "safety", "deadman_ms")
    rep.add("ok", "safety.deadman_ms", dm, "zeroes twist only; torque stays on")

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

    base_bus = {"port": "/dev/ttyS2", "fast_sync_read": False, "servo": "feetech_hls",
                "joint_ids": list(range(1, 16))}
    good = {
        "policy": {"action_scale": 1.0, "standing_gain_ratio": 0.8,
                   "head_lowpass": 1.0, "legs_lowpass": 1.0},
        "bus": dict(base_bus),
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

    fs = dict(good, bus=dict(base_bus, fast_sync_read=True))
    r5 = audit(fs, 8)
    check("fast_sync_read true raises a WARN",
          any(k == "bus.fast_sync_read" and lv == "WARN" for lv, k, _, _ in r5.rows))

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
    rep = audit(cfg, args.expect_kp)
    rep.render()
    print()
    print(f"{rep.fails} FAIL" if rep.fails else "all pass")
    print("\nnot checked: whether robotd is running, what it wrote to reg 50, or whether the "
          "bridge answers -- for reg 50 read it back on the robot after robotd starts.")
    return 1 if rep.fails else 0


if __name__ == "__main__":
    sys.exit(main())
