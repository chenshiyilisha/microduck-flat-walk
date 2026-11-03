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

What *can* be checked off-hardware is the thing that actually went wrong before:
the daemon's defaults are calibrated for **gain = 200**, and our deployment runs
**gain = 8**. Every parameter that is expressed *relative* to gain then silently
means something 25x different. This tool reads a toml and says which ones are wrong.

The trap in one line
--------------------
`[safety] gain_limp = 50` is documented as "low enough to give way rather than fight
the floor" (params_lib.rs:2392). That is true at gain=200 (0.25x). At gain=8 it is
**6.25x**, so a fall would stiffen the robot instead of softening it. Arithmetically
certain, and invisible in every log until the robot is on the floor.

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
    "bus": {"fast_sync_read": True},
    "board": {"version": "zero3"},
}


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

    # R1: the deployment gain itself. Absent = 200 = 6.25x too stiff for a kp8 policy.
    if not gain_set:
        rep.add("FAIL", "policy.gain",
                f"{gain} (default)",
                f"not set in the file, so the daemon uses {DEFAULTS['policy']['gain']}; "
                f"expected {expect_kp}. HD1910 ships at 32, so this is "
                f"{DEFAULTS['policy']['gain'] / 32:.1f}x factory, not "
                f"{expect_kp / 32:.2f}x")
    elif gain != expect_kp:
        rep.add("FAIL", "policy.gain", gain, f"expected {expect_kp} (the plant the policy was trained on)")
    else:
        rep.add("ok", "policy.gain", gain, "matches the trained plant")

    gain_num = gain if isinstance(gain, (int, float)) and gain else 1

    # R2: limp gain must be *below* the running gain, or a fall stiffens the robot.
    limp, limp_set = effective(cfg, "safety", "gain_limp")
    if isinstance(limp, (int, float)):
        ratio = limp / gain_num
        if limp >= gain_num:
            rep.add("FAIL", "safety.gain_limp", limp,
                    f"{ratio:.2f}x the running gain -- limp_fall would STIFFEN the robot. "
                    f"Default {DEFAULTS['safety']['gain_limp']} was chosen for gain=200 "
                    f"(0.25x). Set it to about {max(1, round(gain_num * 0.4))}")
        else:
            rep.add("ok", "safety.gain_limp", limp, f"{ratio:.2f}x running gain"
                    + ("" if limp_set else " (from default; re-derive for this gain)"))

    # R3: posing back up after a fall runs at its own gain, also calibrated for 200.
    pose, pose_set = effective(cfg, "safety", "limp_fall_pose_gain")
    if isinstance(pose, (int, float)):
        ratio = pose / gain_num
        if ratio > 1.5:
            rep.add("FAIL", "safety.limp_fall_pose_gain", pose,
                    f"{ratio:.1f}x the running gain -- the 0.6 s stand-back-up would slam "
                    f"at {pose} instead of {gain_num}. Set it to about {gain_num}")
        else:
            rep.add("ok", "safety.limp_fall_pose_gain", pose, f"{ratio:.2f}x running gain"
                    + ("" if pose_set else " (from default)"))

    # R4: standing runs at gain * ratio. A ratio tuned against 200 may overshoot here.
    sgr, sgr_set = effective(cfg, "policy", "standing_gain_ratio")
    if isinstance(sgr, (int, float)):
        standing = gain_num * sgr
        level = "ok" if 0.5 * gain_num <= standing <= 1.2 * gain_num else "WARN"
        rep.add(level, "policy.standing_gain_ratio", sgr,
                f"standing gain = {standing:.1f}"
                + ("" if sgr_set else f" (default {DEFAULTS['policy']['standing_gain_ratio']}, "
                                      "copied from the prototype's --standing-kp-ratio)"))

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

    # R6: low-pass filters. Trained with them, or not? Must match or transfer degrades.
    for key, trained in (("head_lowpass", None), ("legs_lowpass", None)):
        val, was_set = effective(cfg, "policy", key)
        rep.add("WARN" if not was_set else "ok", f"policy.{key}", val,
                "from default -- confirm the training config used this value"
                if not was_set else "explicit")

    # R7: bus / board identity
    port = (cfg.get("bus") or {}).get("port")
    rep.add("ok" if port else "WARN", "bus.port", port or "(unset)",
            "must be the tty the URT-2/bridge enumerates as, e.g. /dev/ttyS2 or /dev/ttyUSB0"
            if not port else "")
    fast, fast_set = effective(cfg, "bus", "fast_sync_read")
    rep.add("ok", "bus.fast_sync_read", fast,
            "0x8A fast sync read; the bridge must implement it (bus.rs:477)"
            + ("" if fast_set else " (from default)"))
    board, _ = effective(cfg, "board", "version")
    rep.add("ok", "board.version", board,
            "declared, not detected (board.rs:1) -- only gates camera/hw_rev")

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

    bad = {"policy": {"gain": 8}, "safety": {"gain_limp": 50, "limp_fall_pose_gain": 160}}
    r = audit(bad, 8)
    msgs = {(lvl, key) for lvl, key, _, _ in r.rows}
    check("kp8 + default gain_limp is a FAIL", ("FAIL", "safety.gain_limp") in msgs)
    check("kp8 + default pose gain is a FAIL", ("FAIL", "safety.limp_fall_pose_gain") in msgs)
    check("missing action_scale is a FAIL", ("FAIL", "policy.action_scale") in msgs)

    good = {
        "policy": {"gain": 8, "action_scale": 1.0, "standing_gain_ratio": 1.0,
                   "head_lowpass": 0.5, "legs_lowpass": 0.7},
        "safety": {"gain_limp": 3, "limp_fall_pose_gain": 8},
        "bus": {"port": "/dev/ttyS2"},
    }
    r2 = audit(good, 8)
    check("a corrected file passes", r2.fails == 0)

    # negative control: the gain key absent must not be silently accepted
    r3 = audit({"policy": {}, "safety": {"gain_limp": 3, "limp_fall_pose_gain": 8},
                "policy2": {}}, 8)
    check("absent gain is a FAIL", any(k == "policy.gain" and lv == "FAIL"
                                       for lv, k, _, _ in r3.rows))

    # the ratio arithmetic itself, independent of the audit logic
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
    ap.add_argument("--expect-kp", type=int, default=8, help="policy gain the plant was trained at")
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

    print(f"== {path} (expecting policy.gain = {args.expect_kp}) ==")
    rep = audit(cfg, args.expect_kp)
    rep.render()
    print()
    print(f"{rep.fails} FAIL" if rep.fails else "all pass")
    print("\nnot checked: whether robotd is running, what it wrote to reg 50, or whether the "
          "bridge answers -- for reg 50 read it back on the robot after robotd starts.")
    return 1 if rep.fails else 0


if __name__ == "__main__":
    sys.exit(main())
