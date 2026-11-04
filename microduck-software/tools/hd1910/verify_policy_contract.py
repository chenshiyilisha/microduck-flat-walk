#!/usr/bin/env python
"""Does the trained policy's contract match the daemon that will run it?

Two independent sources are read and compared. Neither is allowed to be the
other's reference:

  * **robotd** (Rust): `duck-control/src/obs.rs` documents the 61-float layout,
    `duck-control/src/model.rs` holds `MOUTH_INDEX` / `DEFAULT_POSITION`,
    `duck-ipc-proto/src/lib.rs` holds `JOINT_NAMES`.
  * **the training env** (Python): the resolved `Mjlab-Velocity-Flat-MicroDuck`
    cfg gives the actor observation terms *in order*, and the compiled MuJoCo
    model gives the joint/actuator order and the home pose.

Plus the exported ONNX, which must agree with both on widths and must produce a
bounded action for the observation a standing robot actually generates.

Why this exists
---------------
`obs.rs`'s own header calls itself "the highest-risk code in the crate": a wrong
offset does not fail loudly, it produces a plausible robot that falls over, and
the symptom looks like tuning. The same is true of the joint order — upstream
writes "a guess drives one joint with another's targets". Both are checked here
from two sources, with negative controls, because a check that has only ever
been green is not evidence.

What this cannot check
----------------------
* **Frames.** `gyro` and `projected gravity` must be in the trunk frame;
  whether robotd's `imu_mount` is right is a bench question (B4).
* **Signs and offsets.** They are per-joint calibration, not schema.
* Anything about the servos at all. This is a file-and-graph check.

Usage
-----
    python tools/hd1910/verify_policy_contract.py \
        --onnx out/p8head_2999.onnx --toml out/robotd_hd1910_mode0.toml

    python tools/hd1910/verify_policy_contract.py --selftest
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / ".upstream" / "DuckBuddy-main"
OBS_RS = UPSTREAM / "duck-control" / "src" / "obs.rs"
PARAMS_RS = UPSTREAM / "robotd-params" / "src" / "lib.rs"
MODEL_RS = UPSTREAM / "duck-control" / "src" / "model.rs"
PROTO_RS = UPSTREAM / "duck-ipc-proto" / "src" / "lib.rs"

N_CHECKS = [0]


# ── the two sides ────────────────────────────────────────────────────────────


class NotChecked(Exception):
    """This side of the comparison is unavailable; the check is SKIP, not FAIL."""


def _read(path: pathlib.Path) -> str:
    if not path.exists():
        raise NotChecked(f"{path.relative_to(ROOT)} not found")
    return path.read_text(encoding="utf-8", errors="replace")


def _const(text: str, name: str, cast=int):
    m = re.search(rf"pub const {name}: \w+ = ([0-9_\.]+);", text)
    if not m:
        raise NotChecked(f"`{name}` not found")
    return cast(m.group(1).replace("_", ""))


class Robotd:
    """What the daemon thinks the layout is, read out of its own source."""

    def __init__(self) -> None:
        obs = _read(OBS_RS)
        self.obs_len = _const(obs, "OBS_LEN")
        self.command_len = _const(obs, "COMMAND_LEN")

        # The `//!  index  width  contents` tables at the top of obs.rs. There are
        # two: the six top-level blocks, then a breakdown of the command block.
        # Split them by containment rather than by counting lines.
        rows = []
        for lo, hi, width, label in re.findall(
            r"//!\s+(\d+)(?:\.\.(\d+))?\s+(\d+)\s+(.+)", obs
        ):
            start = int(lo)
            end = int(hi) if hi else start + int(width)
            rows.append((start, end, label.strip()))
        if not rows:
            raise NotChecked("obs.rs layout table not found")

        def inside(inner, outer):
            return (
                inner is not outer
                and inner[0] >= outer[0]
                and inner[1] <= outer[1]
                and (inner[0], inner[1]) != (outer[0], outer[1])
            )

        self.blocks = [r for r in rows if not any(inside(r, o) for o in rows)]
        self.command_blocks = [
            r for r in rows if inside(r, self.blocks[-1])
        ] if self.blocks else []

        model = _read(MODEL_RS)
        self.mouth_index = _const(model, "MOUTH_INDEX")
        self.home_all = self._home(model)
        self.joint_names = self._names(_read(PROTO_RS))

        if len(self.home_all) != len(self.joint_names):
            raise NotChecked(
                f"DEFAULT_POSITION has {len(self.home_all)} entries but "
                f"JOINT_NAMES has {len(self.joint_names)}"
            )

    @staticmethod
    def _home(model: str) -> list[float]:
        m = re.search(
            r"pub const DEFAULT_POSITION: \[f64; NUM_JOINTS\] = \[(.*?)\n\];",
            model,
            re.S,
        )
        if not m:
            raise NotChecked("DEFAULT_POSITION not found")
        body = re.sub(r"//[^\n]*", "", m.group(1))  # strip trailing comments
        return [float(x) for x in re.findall(r"-?[0-9]+\.[0-9]+|-?[0-9]+", body)]

    @staticmethod
    def _names(proto: str) -> list[str]:
        m = re.search(r"pub const JOINT_NAMES: \[&str; \d+\] = \[(.*?)\n\];", proto, re.S)
        if not m:
            raise NotChecked("JOINT_NAMES not found")
        return re.findall(r'"([^"]+)"', m.group(1))

    @property
    def policy_joints(self) -> list[str]:
        return [n for i, n in enumerate(self.joint_names) if i != self.mouth_index]

    @property
    def policy_home(self) -> list[float]:
        return [h for i, h in enumerate(self.home_all) if i != self.mouth_index]


class Training:
    """What the env the policy was trained in actually asks for."""

    TERM_FIXED = {
        "base_ang_vel": 3,
        "projected_gravity": 3,
        "raw_accelerometer": 3,
    }
    TERM_PER_JOINT = {"joint_pos", "joint_vel", "actions"}

    def __init__(self) -> None:
        try:
            import mjlab_microduck  # noqa: F401  (registers the tasks)
            from mjlab_microduck.robot.microduck_constants import (
                HOME_FRAME,
                MICRODUCK_WALK_ROBOT_CFG,
            )
            from mjlab_microduck.tasks.microduck_velocity_env_cfg import (
                make_microduck_velocity_env_cfg,
            )
        except Exception as exc:  # noqa: BLE001
            raise NotChecked(f"mjlab_microduck unavailable: {exc}") from exc

        cfg = make_microduck_velocity_env_cfg()

        model = MICRODUCK_WALK_ROBOT_CFG.spec_fn().compile()
        # The actuator order *is* the action order, and the joint it drives is the
        # name robotd will be mapping to a servo id.
        self.actuators = [model.actuator(i).name for i in range(model.nu)]

        # HOME_FRAME.joint_pos is a dict of regex -> value, not joint -> value.
        self.home = []
        for joint in self.actuators:
            value = 0.0
            for pattern, v in HOME_FRAME.joint_pos.items():
                if re.search(pattern, joint):
                    value = float(v)
            self.home.append(value)

        self.terms: list[tuple[str, int]] = []
        for name, term in cfg.observations["actor"].terms.items():
            width = self._width(name, term, cfg, len(self.actuators))
            self.terms.append((name, width))

        action = cfg.actions["joint_pos"]
        self.action_scale = float(action.scale)
        self.use_default_offset = bool(action.use_default_offset)
        self.action_offset = float(action.offset)
        self.ctrl_dt = float(cfg.decimation) * float(cfg.sim.mujoco.timestep)

    def _width(self, name: str, term, cfg, n_joints: int) -> int:
        if name in self.TERM_FIXED:
            return self.TERM_FIXED[name]
        if name in self.TERM_PER_JOINT:
            return n_joints
        params = getattr(term, "params", None) or {}
        cmd = params.get("command_name")
        if cmd is not None:
            if cmd not in cfg.commands:
                raise NotChecked(f"obs term {name} names unknown command {cmd!r}")
            ranges = cfg.commands[cmd].ranges
            if cmd == "twist":
                # The three velocity fields; `heading` rides in the ranges but is
                # not part of the command the policy sees.
                return sum(
                    1 for f in ("lin_vel_x", "lin_vel_y", "ang_vel_z") if hasattr(ranges, f)
                )
            return len(ranges)
        # A term nobody has taught us the width of. Refuse rather than guess:
        # a guessed width can still sum to 61 and hide a shifted block.
        raise NotChecked(
            f"obs term {name!r} ({getattr(term.func, '__name__', term.func)}) has no "
            "known width -- add it to TERM_FIXED / TERM_PER_JOINT / command handling"
        )


# ── the checks ───────────────────────────────────────────────────────────────


def check_obs_width(rd: Robotd, tr: Training, onnx_in: int | None):
    total = sum(w for _, w in tr.terms)
    parts = [f"robotd {rd.obs_len}", f"training {total}"]
    ok = rd.obs_len == total
    if onnx_in is not None:
        parts.append(f"onnx {onnx_in}")
        ok = ok and onnx_in == total
    detail = ", ".join(parts)
    if not ok:
        detail += "  <- widths disagree; every block after the first one that differs is shifted"
    return ok, "obs width", detail


# robotd block label -> the training term that must occupy it, in order
BLOCK_FOR_TERM = {
    "base_ang_vel": "gyro",
    "raw_accelerometer": "gravity",
    "projected_gravity": "gravity",
    "joint_pos": "joint position",
    "joint_vel": "joint velocity",
    "actions": "previous action",
    "command": "vx, vy",
    "head_command": "neck_pitch",
    "body_command": "body",
}


def check_block_order(rd: Robotd, tr: Training):
    """The training terms, in order, must land exactly on robotd's blocks.

    robotd's top-level table is coarser than the training cfg in exactly one
    place: the last 13 floats are one block there and three terms here (twist,
    head, body). So the first n-1 blocks must match term for term, and the last
    block must cover the rest exactly. `check_command_block` then pins the split
    inside it, which is what catches a head/body swap.
    """
    terms = list(tr.terms)
    blocks = list(rd.blocks)
    if len(blocks) < 2 or len(blocks) > len(terms):
        return False, "block order", (
            f"robotd has {len(blocks)} blocks, training has {len(terms)} terms"
        )
    pairs = list(zip(blocks[:-1], terms))
    tail_block, tail_terms = blocks[-1], terms[len(blocks) - 1:]

    problems = []
    offset = 0
    for (lo, hi, label), (term, width) in pairs:
        want = BLOCK_FOR_TERM.get(term)
        if want is None:
            problems.append(f"{term}: no mapping to a robotd block")
        elif want not in label:
            problems.append(f"[{lo}:{hi}] is {label!r}, training puts {term} there")
        if lo != offset or hi - lo != width:
            problems.append(f"[{lo}:{hi}] width {hi - lo}, training says {width} at {offset}")
        offset = hi

    lo, hi, label = tail_block
    tail_width = sum(w for _, w in tail_terms)
    if "command" not in label:
        problems.append(f"[{lo}:{hi}] is {label!r}, expected the command block")
    if lo != offset or hi - lo != tail_width:
        problems.append(
            f"[{lo}:{hi}] width {hi - lo}, training's "
            f"{[t for t, _ in tail_terms]} sum to {tail_width}"
        )
    if problems:
        return False, "block order", "; ".join(problems[:3])
    return True, "block order", " / ".join(t for t, _ in terms)


def check_joint_order(rd: Robotd, tr: Training):
    a, b = rd.policy_joints, tr.actuators
    if a == b:
        return True, "joint order", f"{len(a)} joints, identical"
    if len(a) != len(b):
        return False, "joint order", f"robotd {len(a)} vs training {len(b)}"
    diffs = [f"{i}: {x} vs {y}" for i, (x, y) in enumerate(zip(a, b)) if x != y]
    return False, "joint order", "; ".join(diffs[:4])


def check_home_pose(rd: Robotd, tr: Training, tol: float = 1e-6):
    a, b = rd.policy_home, tr.home
    if len(a) != len(b):
        return False, "home pose", f"robotd {len(a)} vs training {len(b)}"
    worst = max(abs(x - y) for x, y in zip(a, b))
    if worst > tol:
        bad = [
            f"{n}: {x:+.4f} vs {y:+.4f}"
            for n, x, y in zip(tr.actuators, a, b)
            if abs(x - y) > tol
        ]
        return False, "home pose", f"max |diff| {worst:.4f} rad -- " + "; ".join(bad[:3])
    return True, "home pose", f"max |diff| {worst:.2e} rad"


def check_action(tr: Training, toml: dict | None):
    notes = [f"training scale {tr.action_scale:g}, default offset {tr.use_default_offset}"]
    ok = tr.action_scale == 1.0 and tr.use_default_offset
    if toml is not None:
        scale = (toml.get("policy") or {}).get("action_scale")
        if scale is None:
            notes.append("toml has no [policy] action_scale (default 1.0)")
            ok = ok and True
        else:
            notes.append(f"toml action_scale {scale:g}")
            ok = ok and float(scale) == tr.action_scale
    if not ok:
        notes.append("<- target = home + a*scale; a mismatch bends every joint")
    return ok, "action mapping", ", ".join(notes)


def check_rate(tr: Training, toml: dict | None, default_hz: float | None = None):
    hz = 1.0 / tr.ctrl_dt if tr.ctrl_dt else 0.0
    notes = [f"decimation x timestep -> {hz:.1f} Hz"]
    ok = abs(hz - 50.0) < 0.5
    if toml is not None:
        got = (toml.get("control") or {}).get("hz")
        if got is None:
            # Absent means the daemon's own default, not "unset" -- read it out of
            # the source rather than assuming it agrees with the training env.
            notes.append(f"toml omits [control] hz -> robotd default {default_hz}")
            ok = ok and default_hz is not None and abs(default_hz - hz) < 0.5
        else:
            notes.append(f"toml hz {got}")
            ok = ok and abs(float(got) - hz) < 0.5
    return ok, "control rate", ", ".join(notes)


def check_command_block(rd: Robotd, tr: Training):
    """The 13-wide command block, broken out: twist(3), head(4), body(6).

    obs.rs's second table splits this one up, so a head/body swap is visible here
    even though it would leave the 61-wide total unchanged.
    """
    if not rd.command_blocks:
        return True, "command block", "obs.rs has no breakdown table"
    widths = [hi - lo for lo, hi, _ in rd.command_blocks]
    want = [
        w for term, w in tr.terms if term in ("command", "head_command", "body_command")
    ]
    total = sum(widths)
    ok = (
        len(want) == 3
        and total == rd.command_len
        and len(widths) >= 2
        and widths[0] == want[0]
        and widths[1] == want[1]
        and sum(widths[2:]) == want[2]
    )
    detail = f"robotd {widths} (sum {total}={rd.command_len}) vs training {want}"
    if not ok:
        detail += "  <- twist/head/body do not line up"
    return ok, "command block", detail


def check_onnx(path: pathlib.Path, expected_in: int, expected_out: int, stand_obs):
    import numpy as np
    import onnxruntime as ort

    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    inp, out = sess.get_inputs()[0], sess.get_outputs()[0]
    got_in = inp.shape[1] if len(inp.shape) == 2 else None
    got_out = out.shape[1] if len(out.shape) == 2 else None
    if (got_in, got_out) != (expected_in, expected_out):
        return False, "onnx shape", (
            f"{inp.name}{inp.shape} -> {out.name}{out.shape}, "
            f"expected [1,{expected_in}] -> [1,{expected_out}]"
        )

    action = sess.run(None, {inp.name: np.asarray(stand_obs, np.float32)[None]})[0][0]
    finite = bool(np.all(np.isfinite(action)))
    peak = float(np.abs(action).max())
    # The observation is a robot standing still at home: a sane policy commands a
    # small correction. A metre-scale action means the obs is being read wrong.
    ok = finite and peak < 1.0
    detail = f"{inp.name}{inp.shape} -> {out.name}{out.shape}, stand |a|max {peak:.3f} rad"
    if not finite:
        detail += "  <- non-finite action"
    elif not ok:
        detail += "  <- >1 rad at a standstill; check the obs blocks and home pose"
    return ok, "onnx graph", detail


# ── driver ───────────────────────────────────────────────────────────────────


def stand_observation(rd: Robotd):
    """The observation a standing robot produces, laid out by robotd's table."""
    import numpy as np

    obs = np.zeros(rd.obs_len, np.float32)
    for lo, hi, label in rd.blocks:
        if "gravity" in label:
            obs[lo:hi] = [0.0, 0.0, -1.0]
        elif "gyro" in label:
            obs[lo:hi] = 0.0
    return obs


def default_ctrl_hz() -> float | None:
    """`control.hz` as the daemon defaults it, read from the source not guessed."""
    try:
        text = _read(PARAMS_RS)
    except NotChecked:
        return None
    block = re.search(r"impl Default for Control\b[^{]*\{(.*?)\n\}", text, re.S)
    if not block:
        return None
    m = re.search(r"hz: ([0-9_.]+),", block.group(1))
    return float(m.group(1).replace("_", "")) if m else None


def parse_toml(path: pathlib.Path | None):
    if path is None:
        return None
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib
    return tomllib.loads(path.read_text(encoding="utf-8"))


def report(rows):
    width = max(len(k) for _, k, _ in rows)
    bad = 0
    for ok, key, detail in rows:
        mark = "PASS" if ok else "FAIL"
        bad += not ok
        print(f"  [{mark}] {key:<{width}}  {detail}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--onnx", type=pathlib.Path, default=ROOT / "out" / "p8head_2999.onnx")
    ap.add_argument("--toml", type=pathlib.Path, default=ROOT / "out" / "robotd_hd1910_mode0.toml")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    rows = []
    try:
        rd = Robotd()
    except NotChecked as exc:
        print(f"robotd side unavailable: {exc}")
        return 2
    try:
        tr = Training()
    except NotChecked as exc:
        print(f"training side unavailable: {exc}")
        return 2

    import numpy as np  # noqa: F401

    onnx_in = None
    if args.onnx.exists():
        import onnxruntime as ort

        sess = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])
        onnx_in = sess.get_inputs()[0].shape[1]

    rows.append(check_obs_width(rd, tr, onnx_in))
    rows.append(check_block_order(rd, tr))
    rows.append(check_joint_order(rd, tr))
    rows.append(check_home_pose(rd, tr))

    toml = parse_toml(args.toml if args.toml and args.toml.exists() else None)
    rows.append(check_command_block(rd, tr))
    rows.append(check_action(tr, toml))
    rows.append(check_rate(tr, toml, default_ctrl_hz()))

    if args.onnx.exists():
        rows.append(
            check_onnx(args.onnx, rd.obs_len, len(tr.actuators), stand_observation(rd))
        )
    else:
        rows.append((False, "onnx graph", f"{args.onnx} missing"))

    print(f"policy <-> robotd contract  ({args.onnx.name}, {args.toml.name if toml else 'no toml'})")
    bad = report(rows)
    print()
    if bad:
        print(f"{bad} FAIL")
    else:
        print("all pass -- layout, order, home pose and action mapping agree on both sides")
    print("\nnot checked: trunk-frame conventions, sign/offset calibration, and anything "
          "about the servos. Those are bench items (B3, B4).")
    return 1 if bad else 0


# ── negative controls ────────────────────────────────────────────────────────


def selftest() -> int:
    """Every check must go red when the thing it guards is broken."""
    try:
        rd = Robotd()
        tr = Training()
    except NotChecked as exc:
        print(f"selftest needs both sides: {exc}")
        return 2

    def expect(label, got_ok, want_ok):
        N_CHECKS[0] += 1
        mark = "ok" if got_ok == want_ok else "MISMATCH"
        print(f"  {mark:<9} {label} -> {'PASS' if got_ok else 'FAIL'}"
              f" (wanted {'PASS' if want_ok else 'FAIL'})")
        return got_ok == want_ok

    good = True
    good &= expect("clean width", check_obs_width(rd, tr, 61)[0], True)
    good &= expect("clean blocks", check_block_order(rd, tr)[0], True)
    good &= expect("clean joints", check_joint_order(rd, tr)[0], True)
    good &= expect("clean home", check_home_pose(rd, tr)[0], True)
    good &= expect("clean action", check_action(tr, None)[0], True)
    good &= expect("clean command block", check_command_block(rd, tr)[0], True)
    good &= expect("clean rate", check_rate(tr, None)[0], True)

    class Mut:
        """Shallow stand-in that lets one field be wrong without rebuilding."""

        def __init__(self, base, **over):
            self.__dict__.update(base.__dict__)
            self.__dict__.update(over)

    # 1. one joint pair swapped: the exact failure upstream warns about
    swapped = list(rd.policy_joints)
    swapped[2], swapped[3] = swapped[3], swapped[2]
    good &= expect(
        "two joints swapped",
        check_joint_order(Mut(rd, policy_joints=swapped), tr)[0],
        False,
    )

    # 2. home pose off by 1 degree on one joint
    home = list(rd.policy_home)
    home[5] += 0.0175
    good &= expect("home +1 deg", check_home_pose(Mut(rd, policy_home=home), tr)[0], False)

    # 3. width one short (a dropped element, which is how zip fails silently)
    short = Mut(rd, obs_len=rd.obs_len - 1)
    good &= expect("width 60", check_obs_width(short, tr, 61)[0], False)
    good &= expect("width 60, onnx 60", check_obs_width(short, tr, 60)[0], False)

    # 4. two blocks exchanged: widths still sum to 61, so only the order check sees it
    blocks = list(rd.blocks)
    blocks[0], blocks[1] = blocks[1], blocks[0]
    good &= expect("blocks 0<->1 swapped", check_block_order(Mut(rd, blocks=blocks), tr)[0], False)

    # 5. action scale that is not 1: every joint is bent by the ratio
    good &= expect(
        "action_scale 0.5", check_action(Mut(tr, action_scale=0.5), None)[0], False
    )

    # 6. head and body sub-blocks exchanged: 61 wide either way, only this sees it
    cmd = list(rd.command_blocks)
    cmd[1], cmd[2] = cmd[2], cmd[1]
    good &= expect(
        "head<->body swapped",
        check_command_block(Mut(rd, command_blocks=cmd), tr)[0],
        False,
    )

    # 7. wrong control rate
    good &= expect("rate 100 Hz", check_rate(Mut(tr, ctrl_dt=0.01), None)[0], False)

    print()
    print(f"{N_CHECKS[0]} checks, {'all behave' if good else 'SOME NEGATIVE CONTROLS DID NOT FIRE'}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
