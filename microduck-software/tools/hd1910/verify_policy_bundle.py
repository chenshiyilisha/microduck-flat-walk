#!/usr/bin/env python3
"""Trace one policy bundle from the ONNX file to what `robotd` actually does with it.

Two ends, two sets of gates, and a gap between them.

**The writing end** — `uv run publish` (`microduck_rl` `publish/manifest.py`):
    check_onnx        one input, one output, last dim 61 -> 14, dims literal
    smoke_run_onnx    50 steps of random input; finite output, output not constant
    validate_manifest obs_len / action_len / model_api / robot.model / kind / encoding
It also writes a `manifest.json` (schema 2) and, when exporting from a checkpoint,
ONNX metadata: `joint_names`, `default_joint_pos`, `observation_names`,
`command_names`, `action_scale`.

**The reading end** — this workspace's `robotd` (`DuckBuddy-main`, the HL-2915 build):
    duck-control/src/policy.rs:352-388   check_width(inputs[-1] == 61)
    duck-control/src/policy.rs:352-388   check_width(outputs[-1] == 14)
    duck-control/src/policy.rs:244-249   a warm-up inference on `Observation::zeroed()`
    duck-control/src/policy.rs:400       `ort::inputs!["obs" => ...]` -- the name is hardcoded
That is the whole of it. `grep metadata robotd/ duck-control/` returns nothing, and
`robotd-params::PolicyParams` has no version, no obs_len, no manifest.

So the interesting column is neither list; it is the difference:

* `check_width` reads **only the last dimension of the first outlet**. A graph whose 61
  inputs are in another order, or whose 14 outputs mean other joints, is structurally
  indistinguishable from a correct one.
* The manifest is read by `robotctl` on the *other* robotd generation. This one never
  opens it. A field that is present and wrong here fails nothing.
* `action_scale`, `head_lowpass`, `legs_lowpass`, `gain`, the 50 Hz rate — none of them
  live in the bundle. They live in `[policy]` / `[bus]` of `robotd.toml`, and three of
  them have a non-neutral default (0.9 / 0.5 / 0.7) that will silently apply to a policy
  trained without them.
* The ONNX metadata *does* carry the layout contract — and it is the only thing in the
  bundle that could catch a re-ordered observation. Nothing reads it, so a bundle without
  it and a bundle with a wrong one look the same to the robot.

The tool reproduces both ends, names the gap, and refuses to call the gap "probably fine".

    python tools/hd1910/verify_policy_bundle.py                       # every local sample
    python tools/hd1910/verify_policy_bundle.py out/deploy61.onnx \\
        --manifest out/publish/duck-walk-56d/manifest.json \\
        --toml out/robotd_hd1910_mode0.toml
    python tools/hd1910/verify_policy_bundle.py --selftest            # incl. negative controls
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DUCK = ROOT / ".upstream" / "DuckBuddy-main"
RL = ROOT / ".upstream" / "microduck_rl-develop"

PASS, FAIL, WARN, SKIP, INFO = "PASS", "FAIL", "WARN", "SKIP", "INFO"


# ---------------------------------------------------------------------------------------------
# What the two ends say, read from source rather than copied here.

@dataclass
class Contract:
    """Every number below is parsed out of a file. A hardcoded copy would drift."""

    obs_len: int = 0
    action_len: int = 0
    command_len: int = 0
    mouth_index: int = -1
    joint_names: list[str] = field(default_factory=list)
    home_pose: list[float] = field(default_factory=list)
    # One entry per command slot: does `Observation::build` write a value the daemon can
    # vary, or a literal zero? The daemon's head/body pose commands are usually zero, so
    # a normaliser that explodes on those slots is only a latent fault -- until someone
    # tilts the body.
    command_writes: list[bool] = field(default_factory=list)
    input_name: str = ""
    publish_obs_len: int = 0
    publish_action_len: int = 0
    publish_model_api: int = 0
    publish_servos: str = ""
    lowpass_defaults: dict[str, tuple[float, float]] = field(default_factory=dict)
    action_scale_default: dict[str, float] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load_contract(duck: Path = DUCK, rl: Path = RL) -> Contract:
    c = Contract()

    obs = _read(duck / "duck-control/src/obs.rs")
    for name, attr in (("OBS_LEN", "obs_len"), ("ACTION_LEN", "action_len"),
                       ("COMMAND_LEN", "command_len")):
        m = re.search(rf"pub const {name}: usize = (\d+);", obs)
        if m:
            setattr(c, attr, int(m.group(1)))
        else:
            c.problems.append(f"obs.rs: no `pub const {name}: usize = N;`")

    model = _read(duck / "duck-control/src/model.rs")
    m = re.search(r"MOUTH_INDEX: usize = (\d+)", model)
    if m:
        c.mouth_index = int(m.group(1))
    else:
        c.problems.append("model.rs: no MOUTH_INDEX")

    # `0.0, // left_hip_yaw` -- the home the robot actually holds, and therefore the zero
    # of the 14 joint_pos observation slots.
    m = re.search(r"pub const DEFAULT_POSITION: \[f64; NUM_JOINTS\] = \[(.*?)\];", model, re.S)
    if m:
        pairs = re.findall(r"(-?[0-9.]+)\s*,\s*//\s*([a-z0-9_]+)", m.group(1))
        c.home_pose = [float(v) for v, _ in pairs]
    else:
        c.problems.append("model.rs: no DEFAULT_POSITION literal")

    proto = _read(duck / "duck-ipc-proto/src/lib.rs")
    m = re.search(r"pub const JOINT_NAMES: \[&str; (\d+)\] = \[(.*?)\];", proto, re.S)
    if m:
        declared, body = int(m.group(1)), m.group(2)
        names = re.findall(r'"([a-z0-9_]+)"', body)
        c.joint_names = names
        if declared != len(names):
            c.problems.append(f"JOINT_NAMES declares {declared}, lists {len(names)}")
    else:
        c.problems.append("duck-ipc-proto: no JOINT_NAMES array")

    policy = _read(duck / "duck-control/src/policy.rs")
    # `session.run(ort::inputs!["obs" => &input])` -- whatever is between the quotes.
    m = re.search(r'ort::inputs!\[\s*"([^"]+)"\s*=>', policy)
    if m:
        c.input_name = m.group(1)
    else:
        c.problems.append("policy.rs: cannot find the graph's input name")

    pub = _read(rl / "src/mjlab_microduck/publish/manifest.py")
    for name, attr in (("OBS_LEN", "publish_obs_len"), ("ACTION_LEN", "publish_action_len"),
                       ("MODEL_API", "publish_model_api")):
        m = re.search(rf"^{name} = (\d+)", pub, re.M)
        if m:
            setattr(c, attr, int(m.group(1)))
        else:
            c.problems.append(f"publish/manifest.py: no `{name} = N`")
    m = re.search(r'"servos":\s*"([^"]+)"', pub)
    if m:
        c.publish_servos = m.group(1)

    # `head_lowpass: Some(self.head_lowpass.unwrap_or(0.5)).filter(|a| *a < 1.0),`
    # The filter is not a clamp: anything >= the bound becomes `None`, i.e. pass-through,
    # with no error. Writing 1.5 asking for heavier smoothing silently gives you none.
    params = _read(duck / "robotd-params/src/lib.rs")
    for key in ("head_lowpass", "legs_lowpass"):
        m = re.search(
            rf"{key}: Some\(self\.{key}\.unwrap_or\(([0-9.]+)\)\)\.filter\(\|a\| \*a < ([0-9.]+)\)",
            params,
        )
        if m:
            c.lowpass_defaults[key] = (float(m.group(1)), float(m.group(2)))
        else:
            c.problems.append(f"robotd-params: no filter pattern for {key}")

    m = re.search(
        r"action_scale: self\.action_scale\.unwrap_or\(match self\.mode \{\s*"
        r"Mode::Walk => ([0-9.]+),\s*Mode::Roller => ([0-9.]+),", params)
    if m:
        c.action_scale_default = {"walk": float(m.group(1)), "roller": float(m.group(2))}
    else:
        c.problems.append("robotd-params: no per-mode action_scale default")

    # `fill(command_block, [command.twist[0], ..., 0.0, // body x -- unbound in training])`
    # Which of the 13 slots the daemon can drive, taken from the code that fills them.
    m = re.search(r"fill\(\s*command_block,\s*\[(.*?)\],\s*\);", obs, re.S)
    if m:
        entries = []
        for line in m.group(1).splitlines():
            code = line.split("//")[0].strip().rstrip(",").strip()
            if code:
                entries.append(code)
        c.command_writes = [e.startswith("command.") for e in entries]
        if len(c.command_writes) != c.command_len:
            c.problems.append(
                f"obs.rs command block lists {len(entries)} slots, COMMAND_LEN is "
                f"{c.command_len}")
    else:
        c.problems.append("obs.rs: cannot find the command_block fill")

    return c


# ---------------------------------------------------------------------------------------------
# Findings.

@dataclass
class Check:
    key: str
    group: str
    status: str
    detail: str = ""


def _fmt(c: Check) -> str:
    mark = {PASS: "ok  ", FAIL: "FAIL", WARN: "warn", SKIP: "skip", INFO: "    "}[c.status]
    return f"  [{mark}] {c.key:<28} {c.detail}"


# ---------------------------------------------------------------------------------------------
# ONNX facts, without needing onnxruntime for the static half.

@dataclass
class Graph:
    path: Path
    inputs: list[tuple[str, int, list]] = field(default_factory=list)
    outputs: list[tuple[str, int, list]] = field(default_factory=list)
    ops: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    # (producer node, target initializer names) for Sub/Div, for the normaliser check.
    arith: list[tuple[str, str, list[str]]] = field(default_factory=list)
    divisor: str = ""
    error: str = ""


def _dims(value) -> list:
    out = []
    for d in value.type.tensor_type.shape.dim:
        if d.HasField("dim_value"):
            out.append(int(d.dim_value))
        else:
            out.append(d.dim_param or "?")
    return out


def read_graph(path: Path) -> Graph:
    g = Graph(path=path)
    try:
        import onnx
    except ImportError:
        g.error = "onnx is not installed"
        return g
    try:
        model = onnx.load(str(path), load_external_data=False)
    except Exception as e:  # noqa: BLE001 - any loader failure is the same finding
        g.error = f"cannot load: {e}"
        return g

    graph = model.graph
    inits = {i.name for i in graph.initializer}
    g.inputs = [(i.name, i.type.tensor_type.elem_type, _dims(i))
                for i in graph.input if i.name not in inits]
    g.outputs = [(o.name, o.type.tensor_type.elem_type, _dims(o)) for o in graph.output]
    for n in graph.node:
        g.ops[n.op_type] = g.ops.get(n.op_type, 0) + 1
        if n.op_type in ("Sub", "Div", "Mul"):
            consts = [i for i in n.input if i in inits]
            g.arith.append((n.op_type, n.name or "?", consts))
        if n.op_type == "Div" and len(n.input) >= 2 and n.input[1] in inits:
            g.divisor = n.input[1]
    g.metadata = {p.key: p.value for p in model.metadata_props}
    return g


# DTYPE enum: 1 = FLOAT.
FLOAT = 1


def check_graph(g: Graph, c: Contract) -> list[Check]:
    """The two static gates: what `publish` refuses, and what `robotd` checks at load."""
    out: list[Check] = []
    tag = g.path.name

    if g.error:
        return [Check("graph", "A", FAIL, f"{tag}: {g.error}")]

    # -- A1: publish wants exactly one input and one output (check_onnx).
    if len(g.inputs) == 1 and len(g.outputs) == 1:
        out.append(Check("A1 single in/out", "A", PASS,
                         f"{g.inputs[0][0]} -> {g.outputs[0][0]}"))
    else:
        out.append(Check("A1 single in/out", "A", FAIL,
                         f"{len(g.inputs)} inputs {[i[0] for i in g.inputs]}, "
                         f"{len(g.outputs)} outputs {[o[0] for o in g.outputs]}"))

    # -- A2/A3: the last dimension, which is all either end looks at.
    if g.inputs:
        name, dtype, dims = g.inputs[0]
        last = dims[-1] if dims else "?"
        ok = last == c.obs_len
        out.append(Check("A2 obs width", "A", PASS if ok else FAIL,
                         f"last dim {last}, robotd check_width wants {c.obs_len}"))
        # -- A6: a symbolic last dim fails check_width (it compares against a literal).
        if not isinstance(last, int):
            out.append(Check("A6 literal last dim", "A", FAIL,
                             f"input last dim is symbolic ({last!r}); "
                             "check_width compares it to an integer and would refuse"))
        else:
            out.append(Check("A6 literal last dim", "A", PASS, str(last)))
        # -- A4: robotd feeds the graph by name.
        if name == c.input_name:
            out.append(Check("A4 input name", "A", PASS, f'"{name}"'))
        else:
            out.append(Check("A4 input name", "A", FAIL,
                             f'graph calls it "{name}", policy.rs feeds "{c.input_name}" '
                             "(startup failure: ort::inputs! names the tensor)"))
        # -- A5: robotd builds a f32 tensor; a f64 graph is refused at run time.
        if dtype == FLOAT:
            out.append(Check("A5 input dtype", "A", PASS, "float32"))
        else:
            out.append(Check("A5 input dtype", "A", FAIL,
                             f"elem_type {dtype}, robotd builds float32"))
    else:
        out.append(Check("A2 obs width", "A", FAIL, "no inputs"))

    if g.outputs:
        name, dtype, dims = g.outputs[0]
        last = dims[-1] if dims else "?"
        out.append(Check("A3 action width", "A", PASS if last == c.action_len else FAIL,
                         f"last dim {last}, robotd wants {c.action_len}"))
    else:
        out.append(Check("A3 action width", "A", FAIL, "no outputs"))

    # -- A7: the blind spot. `check_width` takes `outlets.first()`; a second input is
    # unchecked. Not a FAIL on its own -- robotd would fail at run with a missing feed --
    # but it is the kind of thing that makes "it loaded" mean less than it sounds.
    if len(g.inputs) > 1:
        rest = ", ".join(f"{n}:{d[-1] if d else '?'}" for n, _, d in g.inputs[1:])
        out.append(Check("A7 extra inputs blind", "A", WARN,
                         f"check_width only reads inputs()[0]; unchecked: {rest}"))

    return out


def check_external_data(g: Graph) -> list[Check]:
    """Are the weights in the file, or beside it?

    A split ONNX is a bundle of two files that every tool in the chain treats as one.
    `publish` copies the model alone (`shutil.copyfile(onnx_path, staged / POLICY_FILE)`)
    and `check_onnx` reads with `load_external_data=False`, so a split export uploads as a
    3 KB graph with no weights and nothing notices until the robot loads it.
    """
    try:
        import onnx
    except ImportError:
        return []
    try:
        model = onnx.load(str(g.path), load_external_data=False)
    except Exception:  # noqa: BLE001
        return []

    inits = list(model.graph.initializer)
    ext = [i for i in inits if i.data_location == onnx.TensorProto.EXTERNAL]
    if not ext:
        return [Check("A8 weights in the file", "A", PASS,
                      f"{len(inits)} initializers, all embedded")]

    base = g.path.parent
    locations: dict[str, bool] = {}
    for i in ext:
        info = {e.key: e.value for e in i.external_data}
        loc = info.get("location", "")
        if loc:
            locations[loc] = locations.get(loc, True) and (base / loc).exists()

    missing = sorted(k for k, ok in locations.items() if not ok)
    present = sorted(k for k, ok in locations.items() if ok)
    if missing:
        return [Check("A8 weights in the file", "A", FAIL,
                      f"{len(ext)}/{len(inits)} initializers point at {missing}, which is "
                      f"not beside the model; copying the .onnx alone gives a graph that "
                      f"will not load")]
    return [Check("A8 weights in the file", "A", WARN,
                  f"{len(ext)}/{len(inits)} initializers live in {present}; the bundle is "
                  "two files and `publish` would upload only one")]


def check_metadata(g: Graph, c: Contract) -> list[Check]:
    """The layout contract the bundle carries and the runtime ignores."""
    out: list[Check] = []
    md = g.metadata

    if not md:
        out.append(Check("B0 metadata present", "B", FAIL,
                         "no metadata_props: the layout contract is absent, and nothing "
                         "else in the chain can notice a re-ordered observation"))
        return out
    out.append(Check("B0 metadata present", "B", PASS, f"{len(md)} keys"))

    # -- B1: `joint_names` must be the robot's 14 policy joints, in the robot's order.
    expect = [n for i, n in enumerate(c.joint_names) if i != c.mouth_index]
    raw = md.get("joint_names")
    if raw is None:
        out.append(Check("B1 joint_names", "B", FAIL, "absent"))
    else:
        got = [s.strip() for s in raw.split(",") if s.strip()]
        if got == expect:
            out.append(Check("B1 joint_names", "B", PASS, f"{len(got)} joints, robotd order"))
        elif len(got) == len(c.joint_names) and got == c.joint_names:
            out.append(Check("B1 joint_names", "B", FAIL,
                             f"{len(got)} names including mouth; the 14-wide policy order "
                             "skips it -- anything indexing actions by these names is off "
                             f"by one past index {c.mouth_index}"))
        elif len(got) != c.action_len:
            close = [a for a in got if a.replace("passive_", "").replace("_backlash", "") in expect]
            hint = (f"; {len(close)}/{len(got)} are real joints with `passive_*_backlash` "
                    "interleaved") if close and len(got) > c.action_len else ""
            out.append(Check("B1 joint_names", "B", FAIL,
                             f"{len(got)} names for {c.action_len} actions{hint}"))
        else:
            diff = [(i, a, b) for i, (a, b) in enumerate(zip(got, expect)) if a != b]
            out.append(Check("B1 joint_names", "B", FAIL,
                             f"order differs at {len(diff)} positions, first "
                             f"{diff[0][0]}: {diff[0][1]!r} vs robotd {diff[0][2]!r}"))

    # -- B2: `default_joint_pos` -- the home the policy's joint_pos was measured from.
    # The daemon's own home is `DEFAULT_POSITION`; a bundle that names another one puts a
    # constant offset on all 14 joint_pos slots and nothing else would notice.
    raw = md.get("default_joint_pos")
    if raw is None:
        out.append(Check("B2 default_joint_pos", "B", FAIL, "absent (home pose unknown)"))
    else:
        try:
            vals = [float(v) for v in raw.split(",") if v.strip()]
        except ValueError:
            vals = []
        expect = [v for i, v in enumerate(c.home_pose) if i != c.mouth_index]
        if len(vals) != c.action_len:
            out.append(Check("B2 default_joint_pos", "B", FAIL,
                             f"{len(vals)} values for {c.action_len} actions"))
        elif not expect:
            out.append(Check("B2 default_joint_pos", "B", SKIP, "no DEFAULT_POSITION parsed"))
        else:
            diffs = [(i, abs(a - b)) for i, (a, b) in enumerate(zip(vals, expect))]
            worst = max(diffs, key=lambda t: t[1])
            # 1e-3: the exports round to three decimals (-0.087 for -0.0873), and the
            # observation subtracts this from the measured position -- 1 mrad is noise.
            ok = worst[1] <= 1e-3
            out.append(Check("B2 default_joint_pos", "B", PASS if ok else FAIL,
                             f"max|delta| vs robotd DEFAULT_POSITION: {worst[1]:.4f} rad"
                             + ("" if ok else f" at joint {worst[0]} "
                                              f"({vals[worst[0]]:.4f} vs {expect[worst[0]]:.4f})")))

    # -- B3/B4: the observation and command splits. These are the only place the 61 -> block
    # boundaries are written down inside the bundle.
    obs_parts: list[str] = []
    for key, total in (("observation_names", c.obs_len), ("command_names", c.command_len)):
        raw = md.get(key)
        if raw is None:
            out.append(Check(f"B3 {key}", "B", FAIL, "absent"))
            continue
        parts = [s.strip() for s in raw.split(",") if s.strip()]
        if key == "observation_names":
            obs_parts = parts
        out.append(Check(f"B3 {key}", "B", INFO,
                         f"{len(parts)} blocks: {', '.join(parts)} "
                         f"(widths are not in the metadata; {total} floats total)"))

    # -- B4: the two lists have to describe the same observation. `observation_names`
    # names head_command and body_command; `command_names` is the split *inside* those.
    if obs_parts and md.get("command_names"):
        cmd_parts = [s.strip() for s in md["command_names"].split(",") if s.strip()]
        names_extra = [n for n in obs_parts if n in ("head_command", "body_command")]
        if names_extra and len(cmd_parts) < 3:
            out.append(Check("B4 splits agree", "B", WARN,
                             f"observation_names carries {names_extra}, but command_names "
                             f"names only {cmd_parts}: the 13-wide block is described two "
                             "ways by the same metadata, and nothing reconciles them"))
        else:
            out.append(Check("B4 splits agree", "B", PASS,
                             f"{len(obs_parts)} observation blocks, {len(cmd_parts)} command"))

    # -- B5: `action_scale` in the metadata is the *policy's* own scale; robotd reads its
    # own from the toml. They have to agree, and nothing compares them.
    raw = md.get("action_scale")
    if raw is None:
        out.append(Check("B5 action_scale", "B", INFO, "absent from metadata"))
    else:
        try:
            out.append(Check("B5 action_scale", "B", INFO,
                             f"metadata says {raw}; robotd's own comes from "
                             "[policy] action_scale, not from here"))
        except ValueError:
            out.append(Check("B5 action_scale", "B", WARN, f"unparseable: {raw!r}"))

    return out


def check_normaliser(g: Graph, c: Contract) -> list[Check]:
    """`robotd` feeds raw observations. If the graph does not normalise, nothing will."""
    out: list[Check] = []
    subs = [a for a in g.arith if a[0] == "Sub"]
    divs = [a for a in g.arith if a[0] in ("Div", "Mul")]

    if not subs or not divs:
        out.append(Check("C1 normaliser baked", "C", FAIL,
                         f"Sub x{len(subs)} Div/Mul x{len(divs)}: the daemon feeds raw "
                         "observations, so an un-baked normaliser is a silent scaling error"))
        return out
    out.append(Check("C1 normaliser baked", "C", PASS,
                     f"Sub x{len(subs)}, Div/Mul x{len(divs)}"))

    # -- C2: a Sub between two activations is not a normaliser. Require the constant operand.
    with_const = [a for a in subs if a[2]]
    if with_const:
        out.append(Check("C2 normaliser shape", "C", PASS,
                         f"Sub over an initializer: {with_const[0][2][0]}"))
    else:
        out.append(Check("C2 normaliser shape", "C", FAIL,
                         "a Sub exists but neither operand is an initializer"))

    # -- C3: the widths must match the observation, or the bake was done for another layout.
    try:
        import onnx
        from onnx import numpy_helper
        model = onnx.load(str(g.path), load_external_data=False)
        by_name = {i.name: i for i in model.graph.initializer}
        widths = []
        for op, _, consts in with_const:
            for name in consts:
                arr = numpy_helper.to_array(by_name[name])
                if arr.ndim == 1:
                    widths.append(int(arr.shape[0]))
        if widths:
            ok = all(w == c.obs_len for w in widths)
            out.append(Check("C3 normaliser width", "C", PASS if ok else FAIL,
                             f"constant width(s) {widths}, observation {c.obs_len}"))
    except Exception as e:  # noqa: BLE001
        out.append(Check("C3 normaliser width", "C", SKIP, f"{e}"))

    return out


# -- obs.rs block boundaries, for naming a bad normaliser dimension.
LEAD_BLOCKS = [("gyro", 3), ("gravity", 3), ("joint_pos", 14), ("joint_vel", 14),
               ("last_action", 14)]
COMMAND_SLOT_NAMES = ["twist.vx", "twist.vy", "twist.vyaw",
                      "head[0]", "head[1]", "head[2]", "head[3]",
                      "body.x", "body.y", "body.z", "body.roll", "body.pitch", "body.yaw"]


def _owner(index: int, c: Contract) -> tuple[str, bool | None]:
    """Block name, and whether the daemon writes a value there (None = outside command)."""
    at = 0
    for name, width in LEAD_BLOCKS:
        if index < at + width:
            return f"{name}[{index - at}]", True
        at += width
    slot = index - at
    if 0 <= slot < len(COMMAND_SLOT_NAMES):
        writes = c.command_writes[slot] if slot < len(c.command_writes) else True
        return COMMAND_SLOT_NAMES[slot], writes
    return f"[{index}]", True


def check_normaliser_floor(g: Graph, c: Contract) -> list[Check]:
    """The divisor is the training standard deviation. A near-zero one is an amplifier.

    `VecNorm` exports floor it (`std + eps`; 0.01289 across every upstream sample). A
    graph whose normaliser has no floor divides by whatever the running variance was --
    and on a slot that was constant during training (the head pose, the body roll) that
    is ~1e-5. The daemon then feeds a real command into it: 0.05 rad becomes 4500.

    Every shape check still passes. The robot walks -- until someone turns the head.
    """
    if not g.divisor:
        return [Check("C4 normaliser floor", "C", SKIP, "no Div over an initializer")]

    try:
        import onnx
        from onnx import numpy_helper
        model = onnx.load(str(g.path), load_external_data=False)
        by_name = {i.name: i for i in model.graph.initializer}
        scale = numpy_helper.to_array(by_name[g.divisor]).astype("float64").ravel()
    except Exception as e:  # noqa: BLE001
        return [Check("C4 normaliser floor", "C", SKIP, f"{e}")]

    if scale.shape[0] != c.obs_len:
        return [Check("C4 normaliser floor", "C", FAIL,
                      f"divisor is {scale.shape[0]}-wide for a {c.obs_len}-wide observation")]

    # 1e-3 means "an input of 1 is multiplied by 1000". The healthy exports sit at
    # 1.3e-2, so anything below this is two orders of magnitude outside the family.
    floor = 1e-3
    sick = [(int(i), float(v)) for i, v in enumerate(scale) if abs(v) < floor]
    if not sick:
        return [Check("C4 normaliser floor", "C", PASS,
                      f"min {float(np_min(scale)):.4g}, everything above {floor:g}")]

    live, latent = [], []
    for i, v in sick:
        name, writes = _owner(i, c)
        amp = 1.0 / abs(v) if v else float("inf")
        (live if writes else latent).append((name, amp))

    detail = (f"{len(sick)} dims below {floor:g}: "
              + ", ".join(f"{n} x{a:.0f}" if a != float("inf") else f"{n} x inf"
                          for n, a in (live + latent)[:6]))
    if live:
        return [Check("C4 normaliser floor", "C", FAIL,
                      detail + f" -- {len(live)} of them are slots the daemon drives, so a "
                      "real command lands here magnified")]
    return [Check("C4 normaliser floor", "C", WARN,
                  detail + " -- all on slots obs.rs pins to 0.0, so harmless while that "
                  "holds, and a cliff the moment it does not")]


def np_min(a):
    return min(float(v) for v in a)


# ---------------------------------------------------------------------------------------------
# Runtime probes. These need onnxruntime, and they ask the question the static half cannot:
# "what does the graph do at the observations a robot actually produces".

GYRO = (0.0, 0.0, 0.0)
GRAVITY = (0.0, 0.0, -1.0)


def plausible_obs(obs_len: int, twist=(0.3, 0.0, 0.0)) -> list[float]:
    """One observation at robot magnitudes, in the order `obs.rs` builds it.

    3 gyro | 3 gravity | 14 joint_pos (relative to home) | 14 joint_vel |
    14 last_action | 13 command (twist 3, head 4, body z/roll/pitch/yaw)
    """
    obs = [0.0] * obs_len
    obs[0:3] = list(GYRO)
    obs[3:6] = list(GRAVITY)
    # A stance a little off home: the graph was trained with the robot moving.
    for i in range(14):
        obs[6 + i] = 0.05 * (1 if i % 2 else -1)
    for i in range(14):
        obs[20 + i] = 0.3 * (1 if i % 3 else 0)
    # last_action: the previous output, raw.
    for i in range(14):
        obs[34 + i] = 0.02 * (1 if i % 2 else 0)
    if obs_len >= 48:
        obs[48:51] = list(twist)
    return obs


def _session(g: Graph):
    """One ORT session, quiet. The control loop would hold one too; so does this."""
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.log_severity_level = 3
    so.intra_op_num_threads = 1
    return ort.InferenceSession(str(g.path), sess_options=so,
                                providers=["CPUExecutionProvider"])


def run_onnx(sess, rows: list[list[float]]):
    import numpy as np

    name = sess.get_inputs()[0].name
    return np.stack([sess.run(None, {name: np.asarray([r], dtype=np.float32)})[0]
                     for r in rows])


def check_runtime(g: Graph, c: Contract) -> list[Check]:
    out: list[Check] = []
    try:
        import numpy as np
        import onnxruntime  # noqa: F401
    except ImportError as e:
        return [Check("R0 runtime", "R", SKIP, str(e))]

    # -- R1: robotd's warm-up is one inference on an all-zero observation, and a failure
    # there makes the daemon unhealthy -- i.e. a rollback, not a robot that sits still.
    try:
        sess = _session(g)
        zero = run_onnx(sess, [[0.0] * c.obs_len])
        finite = bool(np.all(np.isfinite(zero)))
        out.append(Check("R1 zero-obs warm-up", "R", PASS if finite else FAIL,
                         "finite" if finite else "non-finite action on Observation::zeroed()"))
    except Exception as e:  # noqa: BLE001
        return [Check("R1 zero-obs warm-up", "R", FAIL, f"{type(e).__name__}: {e}")]

    # -- R2: at robot magnitudes, the action has to be a joint offset, not a number.
    try:
        peak = float(np.max(np.abs(run_onnx(sess, [plausible_obs(c.obs_len)])[0][0])))
        # 14 actions, each a fraction of a radian. A normaliser applied twice, or not at
        # all, shows up here as an order of magnitude, not as a shape error.
        status = PASS if peak <= 3.0 else FAIL
        out.append(Check("R2 action magnitude", "R", status,
                         f"max|a| {peak:.3f} at a plausible stance "
                         f"({'within a joint offset' if status == PASS else 'not a joint offset'})"))
    except Exception as e:  # noqa: BLE001
        out.append(Check("R2 action magnitude", "R", SKIP, f"{e}"))

    # -- R3: `publish`'s smoke run, reproduced: does the output respond to the input at all?
    try:
        rng = np.random.default_rng(0)
        obs = np.zeros(c.obs_len, dtype=np.float32)
        outs = []
        for _ in range(50):
            o = run_onnx(sess, [obs.tolist()])[0][0]
            outs.append(o)
            obs = rng.normal(0.0, 0.05, size=c.obs_len).astype(np.float32)
            lo = c.obs_len - c.command_len - c.action_len
            obs[lo:lo + c.action_len] = np.clip(o, -1, 1)
        spread = float(np.std(np.stack(outs)))
        out.append(Check("R3 output varies", "R", PASS if spread > 0 else FAIL,
                         f"std over 50 jittered steps: {spread:.3g}"
                         + ("" if spread > 0 else " (a constant graph is not a policy)")))
    except Exception as e:  # noqa: BLE001
        out.append(Check("R3 output varies", "R", SKIP, f"{e}"))

    return out


# ---------------------------------------------------------------------------------------------
# The pass-through parameters: not in the bundle, applied anyway, with non-neutral defaults.

def _toml_section(text: str, section: str) -> dict[str, str]:
    body, out = False, {}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            body = s == f"[{section}]"
            continue
        if body and "=" in s and not s.startswith("#"):
            k, _, v = s.partition("=")
            out[k.strip()] = v.split("#")[0].strip()
    return out


def check_sideband(c: Contract, metadata: dict[str, str], manifest: dict | None,
                   toml_path: Path | None) -> list[Check]:
    out: list[Check] = []
    if toml_path is None:
        out.append(Check("D0 sideband", "D", INFO,
                         "no --toml: action_scale / lowpass / gain unchecked"))
        return out
    text = _read(toml_path)
    if not text:
        return [Check("D0 sideband", "D", FAIL, f"{toml_path}: unreadable")]

    pol = _toml_section(text, "policy")

    def num(section: dict, key: str) -> float | None:
        if key not in section:
            return None
        try:
            return float(section[key])
        except ValueError:
            return None

    # -- D1: action_scale. The default is 0.9 walking / 0.8 roller -- ten percent off a
    # policy trained at 1.0, applied silently.
    scale = num(pol, "action_scale")
    dflt = c.action_scale_default.get("walk")
    if scale is None:
        out.append(Check("D1 action_scale", "D", WARN,
                         f"absent: robotd resolves {dflt:g} for walk mode "
                         "(a policy trained at 1.0 loses 10% of every action)"
                         if dflt is not None else "absent and no default parsed"))
    else:
        out.append(Check("D1 action_scale", "D", PASS, f"{scale:g} (walk default {dflt:g})"
                         if dflt is not None else f"{scale:g}"))
    if scale is not None and "action_scale" in metadata:
        try:
            mscale = float(metadata["action_scale"])
            if abs(mscale - scale) > 1e-9:
                out.append(Check("D2 scale agrees", "D", FAIL,
                                 f"toml {scale:g} vs onnx metadata {mscale:g}"))
            else:
                out.append(Check("D2 scale agrees", "D", PASS, f"{scale:g}"))
        except ValueError:
            pass

    # -- D3: the two low-passes. Both default to < 1, i.e. on. A policy trained without
    # one has to say 1.0, and `filter(|a| *a < 1.0)` turns that into `None` = pass-through.
    for key in ("head_lowpass", "legs_lowpass"):
        dflt, bound = c.lowpass_defaults.get(key, (float("nan"), float("nan")))
        v = num(pol, key)
        if v is None:
            out.append(Check(f"D3 {key}", "D", WARN,
                             f"absent: robotd applies {dflt:g} (filter is on)"))
        elif v >= bound:
            # Not a clamp: `Some(1.5).filter(<1.0)` is `None`, i.e. no filtering at all.
            note = "pass-through" if v == bound else "silently becomes pass-through"
            out.append(Check(f"D3 {key}", "D", WARN if v != bound else PASS,
                             f"{v:g} >= {bound:g} -> {note}"))
        elif v <= 0.0:
            out.append(Check(f"D3 {key}", "D", WARN,
                             f"{v:g}: the target is frozen at its first value"))
        else:
            out.append(Check(f"D3 {key}", "D", PASS, f"{v:g}"))

    # -- D4: what the manifest promised about the runtime, versus the toml.
    if manifest:
        dep = manifest.get("deployment") or {}
        promised = dep.get("runtime_lowpass_pass_through") or {}
        for key, label in (("head_lowpass", "head"), ("legs_lowpass", "legs")):
            if label in promised:
                want = promised[label]
                got = num(pol, key)
                actual = 1.0 if got is None or got >= c.lowpass_defaults.get(key, (0, 1))[1] else got
                if abs(actual - want) > 1e-9:
                    out.append(Check(f"D4 {label} promised", "D", FAIL,
                                     f"manifest promises pass-through {want:g}, "
                                     f"toml resolves {actual:g}"))
                else:
                    out.append(Check(f"D4 {label} promised", "D", PASS, f"{want:g}"))

    # -- D5: the rate. 50 Hz is `Control::default().hz`; the bundle has no say in it.
    bus = _toml_section(text, "bus")
    if bus:
        out.append(Check("D5 control rate", "D", INFO,
                         "50 Hz is duck-control's own constant, not a bundle field"))
    return out


# ---------------------------------------------------------------------------------------------

def check_manifest(c: Contract, manifest: dict | None, g: Graph,
                   toml_path: Path | None) -> list[Check]:
    out: list[Check] = []
    if manifest is None:
        out.append(Check("E0 manifest", "E", INFO, "none given (this robotd never reads one)"))
        return out

    m = manifest
    # -- E1/E2: the two numbers the *other* robotd would refuse on.
    obs = m.get("obs_len")
    out.append(Check("E1 manifest obs_len", "E", PASS if obs in (None, c.obs_len) else FAIL,
                     f"{obs}" + ("" if obs == c.obs_len else f" (this robotd builds {c.obs_len})")))
    act = m.get("action_len")
    out.append(Check("E2 manifest action_len", "E",
                     PASS if act in (None, c.action_len) else FAIL,
                     f"{act}" + ("" if act == c.action_len else f" (robotd wants {c.action_len})")))

    # -- E3: `publish` refuses anything that is not exactly 61 -> 14. A hand-written bundle
    # with other numbers could never have come out of it.
    if obs is not None and c.publish_obs_len and obs != c.publish_obs_len:
        out.append(Check("E3 publish-impossible", "E", WARN,
                         f"obs_len {obs}: `publish`'s check_onnx refuses anything that is "
                         f"not {c.publish_obs_len} -> {c.publish_action_len}, so this manifest "
                         "was written by hand and skipped every gate"))
    else:
        out.append(Check("E3 publish-impossible", "E", PASS, "shape is one publish could emit"))

    # -- E4: does this robotd read any of it? Count the fields it knows.
    known = {"obs_len", "action_len", "robot.model", "kind", "duration_s", "unwind_s",
             "action_scale", "slot", "command.idle", "command.encoding"}
    if toml_path is not None:
        out.append(Check("E4 read by robotd", "E", INFO,
                         "0 fields of this manifest are opened by this robotd "
                         "(grep metadata/robotctl policy -> nothing; PolicyParams has no "
                         "manifest field). The numbers above are for the other generation."))

    # -- E5: `publish` stamps servos: "xl330" for every policy it writes.
    servos = (m.get("robot") or {}).get("servos")
    if servos is not None and c.publish_servos and servos == c.publish_servos:
        hw = (m.get("robot") or {}).get("servos")
        out.append(Check("E5 robot.servos", "E", INFO,
                         f'"{hw}" is what `publish` hardcodes for every repo; a Feetech '
                         "HL-2915 build inherits the xl330 label"))

    # -- E6: the bundle's own claim about the normaliser, against the graph.
    norm = ((m.get("eval") or {}).get("normalisation")
            or (m.get("deployment") or {}).get("observation_normalizer_baked"))
    if norm is not None:
        baked = bool([a for a in g.arith if a[0] == "Sub"])
        claim = norm is True or (isinstance(norm, str) and "baked" in norm)
        out.append(Check("E6 normaliser claim", "E", PASS if claim == baked else FAIL,
                         f"manifest says {norm!r}, graph {'has' if baked else 'lacks'} "
                         "a Sub/Div pair"))

    return out


# ---------------------------------------------------------------------------------------------

def audit(path: Path, c: Contract, manifest_path: Path | None = None,
          toml_path: Path | None = None, verbose: bool = True) -> list[Check]:
    g = read_graph(path)
    manifest = None
    if manifest_path is not None:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            manifest = None
            if verbose:
                print(f"  [FAIL] manifest unreadable: {e}")

    checks: list[Check] = []
    checks += check_graph(g, c)
    checks += check_external_data(g)
    checks += check_metadata(g, c)
    checks += check_normaliser(g, c)
    checks += check_normaliser_floor(g, c)
    checks += check_runtime(g, c)
    checks += check_sideband(c, g.metadata, manifest, toml_path)
    checks += check_manifest(c, manifest, g, toml_path)

    if verbose:
        print(f"\n=== {path}")
        last = None
        for ch in checks:
            if ch.group != last:
                print(f"  -- group {ch.group}")
                last = ch.group
            print(_fmt(ch))
    return checks


def summarise(all_checks: dict[str, list[Check]]) -> int:
    print("\n" + "=" * 78)
    fails = 0
    for name, checks in all_checks.items():
        bad = [c for c in checks if c.status == FAIL]
        warn = [c for c in checks if c.status == WARN]
        fails += len(bad)
        verdict = "FAIL" if bad else ("warn" if warn else "ok")
        print(f"  {verdict:<5} {name:<58} {len(checks):2d} checks, "
              f"{len(bad)} fail, {len(warn)} warn")
        for ch in bad:
            print(f"        ! {ch.key}: {ch.detail}")
        for ch in warn:
            print(f"        ~ {ch.key}: {ch.detail}")
    print("=" * 78)
    return 1 if fails else 0


# ---------------------------------------------------------------------------------------------
# Self-test: a synthetic graph, then the same graph broken in one specific way per control.

def synth(path: Path, obs_len: int = 61, act_len: int = 14, *,
          metadata: dict[str, str] | None = None,
          input_name: str = "obs", output_name: str = "actions",
          with_sub: bool = True, sub_has_const: bool = True,
          two_inputs: bool = False, symbolic_last: bool = False,
          constant_output: bool = False,
          std_small: tuple[int, ...] = (), std_small_value: float = 1.113e-05) -> Path:
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    rng = np.random.default_rng(7)
    inits, nodes = [], []

    def init(name, arr):
        inits.append(numpy_helper.from_array(arr, name))
        return name

    x = input_name
    if with_sub:
        mean = init("obs_mean", np.zeros(obs_len, dtype=np.float32))
        scale = np.ones(obs_len, dtype=np.float32)
        for k in std_small:
            if 0 <= k < obs_len:
                scale[k] = std_small_value
        std = init("obs_std", scale)
        # `sub_has_const=False` wires the Sub to the input twice: a Sub that is not a
        # normaliser. That is the negative control for C2 -- neither operand is an
        # initializer, so there is no constant to subtract.
        nodes.append(helper.make_node(
            "Sub", [x, mean] if sub_has_const else [x, x], ["sub_out"]))
        nodes.append(helper.make_node("Div", ["sub_out", std], ["norm_out"]))
        x = "norm_out"

    zeros = constant_output

    def weight(name: str, shape: tuple[int, ...]) -> str:
        arr = (np.zeros(shape, dtype=np.float32) if zeros
               else rng.normal(0, 0.2, shape).astype(np.float32))
        return init(name, arr)

    w1 = weight("w1", (obs_len, 32))
    b1 = init("b1", np.zeros(32, dtype=np.float32))
    w2 = weight("w2", (32, 32))
    b2 = init("b2", np.zeros(32, dtype=np.float32))
    w3 = weight("w3", (32, act_len))
    b3 = init("b3", np.zeros(act_len, dtype=np.float32))
    nodes += [
        helper.make_node("Gemm", [x, w1, b1], ["g1"]),
        helper.make_node("Elu", ["g1"], ["a1"]),
        helper.make_node("Gemm", ["a1", w2, b2], ["g2"]),
        helper.make_node("Elu", ["g2"], ["a2"]),
        helper.make_node("Gemm", ["a2", w3, b3], [output_name]),
    ]

    # The last dim of the *input* is the one `check_width` reads; a symbolic one there is
    # what A6 exists for. Declaring `[1, obs_len]` for the input and a symbolic output
    # would only test A3.
    in_dims: list = ["batch", "obs_dim"] if symbolic_last else [1, obs_len]
    out_dims: list = ["batch", act_len] if symbolic_last else [1, act_len]
    inputs = [helper.make_tensor_value_info(input_name, TensorProto.FLOAT, in_dims)]
    if two_inputs:
        inputs.append(helper.make_tensor_value_info("aux", TensorProto.FLOAT, [1, 3]))
    output = helper.make_tensor_value_info(output_name, TensorProto.FLOAT, out_dims)

    graph = helper.make_graph(nodes, "synth", inputs, [output], inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 10
    if metadata:
        for k, v in metadata.items():
            p = model.metadata_props.add()
            p.key, p.value = k, v
    onnx.save(model, str(path))
    return path


def selftest() -> int:
    import tempfile

    c = load_contract()
    checks: list[tuple[str, bool, str]] = []

    def ok(name: str, cond: bool, detail: str = "") -> None:
        checks.append((name, bool(cond), detail))

    # -- the contract parse itself
    ok("contract: OBS_LEN == 61", c.obs_len == 61, str(c.obs_len))
    ok("contract: ACTION_LEN == 14", c.action_len == 14, str(c.action_len))
    ok("contract: COMMAND_LEN == 13", c.command_len == 13, str(c.command_len))
    ok("contract: 15 JOINT_NAMES, mouth at 9",
       len(c.joint_names) == 15 and c.mouth_index == 9 and c.joint_names[9] == "mouth",
       f"{len(c.joint_names)} names, index {c.mouth_index}")
    ok("contract: 15 DEFAULT_POSITION values",
       len(c.home_pose) == len(c.joint_names),
       f"{len(c.home_pose)} vs {len(c.joint_names)}")
    ok("contract: input name 'obs'", c.input_name == "obs", c.input_name)
    ok("contract: publish 61->14", (c.publish_obs_len, c.publish_action_len) == (61, 14),
       f"{c.publish_obs_len}->{c.publish_action_len}")
    ok("contract: lowpass defaults 0.5/0.7 below 1.0",
       c.lowpass_defaults.get("head_lowpass", (0, 0))[0] == 0.5
       and c.lowpass_defaults.get("legs_lowpass", (0, 0))[0] == 0.7
       and all(b == 1.0 for _, b in c.lowpass_defaults.values()),
       str(c.lowpass_defaults))
    ok("contract: action_scale default 0.9 walk", c.action_scale_default.get("walk") == 0.9,
       str(c.action_scale_default))
    ok("contract: 13 command slots, 3 of them literal zeros",
       c.command_writes == [True] * 7 + [False, False] + [True] * 3 + [False],
       str(c.command_writes))
    ok("contract: no parse problems", not c.problems, "; ".join(c.problems))

    home14 = [v for i, v in enumerate(c.home_pose) if i != c.mouth_index]
    good_meta = {
        "joint_names": ",".join(n for i, n in enumerate(c.joint_names) if i != c.mouth_index),
        "default_joint_pos": ",".join(f"{v:g}" for v in home14),
        "observation_names": "base_ang_vel,projected_gravity,joint_pos,joint_vel,actions,"
                             "command,head_command,body_command",
        "command_names": "twist,head_pose,body_pose",
        "action_scale": "1.0",
    }

    def status_of(checks_list, key):
        for ch in checks_list:
            if ch.key.startswith(key):
                return ch.status
        return "MISSING"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # -- 1: a clean bundle passes every gate that does not need a manifest.
        p = synth(tmp / "good.onnx", metadata=good_meta)
        res = audit(p, c, verbose=False)
        ok("clean: all A/B/C/R pass",
           not [ch for ch in res if ch.status == FAIL],
           "; ".join(f"{ch.key}:{ch.detail}" for ch in res if ch.status == FAIL))

        # -- 2: negative controls. Each is the same graph with one thing wrong.
        cases = [
            ("N1 obs width 60 -> A2 fails", synth(tmp / "n1.onnx", obs_len=60,
                                                 metadata=good_meta), "A2", FAIL),
            ("N2 action width 15 -> A3 fails", synth(tmp / "n2.onnx", act_len=15,
                                                    metadata=good_meta), "A3", FAIL),
            ("N3 input named observation -> A4 fails",
             synth(tmp / "n3.onnx", input_name="observation", metadata=good_meta), "A4", FAIL),
            ("N4 two inputs -> A1 fails",
             synth(tmp / "n4.onnx", two_inputs=True, metadata=good_meta), "A1", FAIL),
            ("N4b two inputs -> A7 warns",
             synth(tmp / "n4b.onnx", two_inputs=True, metadata=good_meta), "A7", WARN),
            ("N5 symbolic last dim -> A6 fails",
             synth(tmp / "n5.onnx", symbolic_last=True, metadata=good_meta), "A6", FAIL),
            ("N6 no metadata -> B0 fails", synth(tmp / "n6.onnx"), "B0", FAIL),
            ("N7 no Sub/Div -> C1 fails",
             synth(tmp / "n7.onnx", with_sub=False, metadata=good_meta), "C1", FAIL),
            ("N8 Sub without a constant -> C2 fails",
             synth(tmp / "n8.onnx", sub_has_const=False, metadata=good_meta), "C2", FAIL),
            ("N9 constant output -> R3 fails",
             synth(tmp / "n9.onnx", constant_output=True, metadata=good_meta), "R3", FAIL),
        ]
        for name, path, key, want in cases:
            res = audit(path, c, verbose=False)
            got = status_of(res, key)
            ok(name, got == want, f"got {got}")

        # -- 10: joint_names off by one -- the mouth left in.
        bad = dict(good_meta, joint_names=",".join(c.joint_names))
        res = audit(synth(tmp / "n10.onnx", metadata=bad), c, verbose=False)
        ok("N10 joint_names includes mouth -> B1 fails", status_of(res, "B1") == FAIL,
           status_of(res, "B1"))

        # -- 11: joint_names reordered (a swap at index 2/3 passes a width check).
        names = good_meta["joint_names"].split(",")
        names[2], names[3] = names[3], names[2]
        res = audit(synth(tmp / "n11.onnx", metadata=dict(good_meta,
                                                         joint_names=",".join(names))),
                    c, verbose=False)
        ok("N11 joint_names swapped -> B1 fails", status_of(res, "B1") == FAIL,
           status_of(res, "B1"))

        # -- 12: 28 names with passive joints, the shape the HL-2915 export actually has.
        wide = []
        for n in c.joint_names:
            wide += [n, f"passive_{n}_backlash"]
        res = audit(synth(tmp / "n12.onnx", metadata=dict(good_meta,
                                                         joint_names=",".join(wide))),
                    c, verbose=False)
        ok("N12 28 names for 14 actions -> B1 fails", status_of(res, "B1") == FAIL,
           status_of(res, "B1"))

        # -- 13: default_joint_pos of the wrong width.
        res = audit(synth(tmp / "n13.onnx", metadata=dict(
            good_meta, default_joint_pos=",".join(["0.0"] * 28))), c, verbose=False)
        ok("N13 28 default positions -> B2 fails", status_of(res, "B2") == FAIL,
           status_of(res, "B2"))

        # -- 14: the sideband. A toml that says 1.5 is not clamped, it is dropped.
        toml = tmp / "r.toml"
        toml.write_text("[policy]\naction_scale = 0.9\nhead_lowpass = 1.5\n"
                        "legs_lowpass = 1.0\n", encoding="utf-8")
        res = audit(synth(tmp / "n14.onnx", metadata=dict(good_meta, action_scale="1.0")),
                    c, toml_path=toml, verbose=False)
        ok("N14 lowpass 1.5 -> warns about silent pass-through",
           status_of(res, "D3 head_lowpass") == WARN, status_of(res, "D3 head_lowpass"))
        ok("N14b lowpass 1.0 -> pass-through is not a warning",
           status_of(res, "D3 legs_lowpass") == PASS, status_of(res, "D3 legs_lowpass"))
        ok("N14c toml 0.9 vs metadata 1.0 -> D2 fails",
           status_of(res, "D2") == FAIL, status_of(res, "D2"))

        # -- 15: a manifest claiming 56 dims, i.e. one publish could never have written.
        man = tmp / "m.json"
        man.write_text(json.dumps({"obs_len": 56, "action_len": 14}), encoding="utf-8")
        res = audit(synth(tmp / "n15.onnx", metadata=good_meta), c,
                    manifest_path=man, verbose=False)
        ok("N15 manifest obs_len 56 -> E1 fails", status_of(res, "E1") == FAIL,
           status_of(res, "E1"))
        ok("N15b manifest 56 -> E3 flags a hand-written bundle",
           status_of(res, "E3") == WARN, status_of(res, "E3"))

        # -- 16: the manifest claiming a baked normaliser that is not there.
        man2 = tmp / "m2.json"
        man2.write_text(json.dumps({"deployment": {"observation_normalizer_baked": True}}),
                        encoding="utf-8")
        res = audit(synth(tmp / "n16.onnx", with_sub=False, metadata=good_meta), c,
                    manifest_path=man2, verbose=False)
        ok("N16 manifest claims baked, graph has none -> E6 fails",
           status_of(res, "E6") == FAIL, status_of(res, "E6"))

        # -- 17: a split ONNX. `publish` copies one file, so the weights have to be inside.
        import onnx

        split_dir = tmp / "split"
        split_dir.mkdir()
        base = synth(tmp / "n17_src.onnx", metadata=good_meta)
        onnx.save(onnx.load(str(base)), str(split_dir / "policy.onnx"),
                  save_as_external_data=True, all_tensors_to_one_file=True,
                  location="policy.onnx.data", size_threshold=0)
        res = audit(split_dir / "policy.onnx", c, verbose=False)
        ok("N17a split onnx, .data beside it -> A8 warns", status_of(res, "A8") == WARN,
           status_of(res, "A8"))
        (split_dir / "policy.onnx.data").unlink()
        res = audit(split_dir / "policy.onnx", c, verbose=False)
        ok("N17b .data removed -> A8 fails", status_of(res, "A8") == FAIL,
           status_of(res, "A8"))

        # -- 18: metadata naming head_command/body_command while command_names says twist.
        res = audit(synth(tmp / "n18.onnx", metadata=dict(good_meta, command_names="twist")),
                    c, verbose=False)
        ok("N18 command_names contradicts observation_names -> B4 warns",
           status_of(res, "B4") == WARN, status_of(res, "B4"))

        # -- 19: a home pose 10 mrad off. That is a constant offset on 14 observation
        # slots -- invisible to every width check, and to a rollout that still walks.
        off = list(home14)
        off[2] += 0.010
        res = audit(synth(tmp / "n19.onnx",
                          metadata=dict(good_meta,
                                        default_joint_pos=",".join(f"{v:g}" for v in off))),
                    c, verbose=False)
        ok("N19 home pose off by 10 mrad -> B2 fails", status_of(res, "B2") == FAIL,
           status_of(res, "B2"))

        # -- 20: a normaliser that divides by nothing. `deploy61` has exactly this on the
        # head and body slots: 1.1e-5 against the upstream family's 1.29e-2.
        res = audit(synth(tmp / "n20.onnx", metadata=good_meta, std_small=(48,)), c,
                    verbose=False)
        ok("N20 near-zero divisor on twist.vx -> C4 fails",
           status_of(res, "C4") == FAIL, status_of(res, "C4"))
        # -- 21: the same defect only on slots obs.rs pins to 0.0: latent, not live.
        res = audit(synth(tmp / "n21.onnx", metadata=good_meta, std_small=(55, 56, 60)), c,
                    verbose=False)
        ok("N21 near-zero divisor only on pinned-zero slots -> C4 warns",
           status_of(res, "C4") == WARN, status_of(res, "C4"))
        # -- 22: a healthy floor (the upstream 1.29e-2) passes.
        res = audit(synth(tmp / "n22.onnx", metadata=good_meta, std_small=(48,),
                          std_small_value=0.01289), c, verbose=False)
        ok("N22 upstream-sized floor passes", status_of(res, "C4") == PASS,
           status_of(res, "C4"))

    print("\nSelf-test")
    bad = 0
    for name, cond, detail in checks:
        print(f"  [{'ok  ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
        bad += 0 if cond else 1
    print(f"\n  {len(checks) - bad}/{len(checks)} passed")
    return 1 if bad else 0


# ---------------------------------------------------------------------------------------------
# Stamping: write the layout contract into a graph that shipped without one, and inline the
# weights while we are there. Both defects are in the samples this repo means to deploy.

def stamp(src: Path, dst: Path, c: Contract, action_scale: float | None = None) -> int:
    """Copy `src` to `dst` with the observation contract in its metadata, as one file.

    Not a fix for the gap -- `robotd` still reads none of it. It is what makes the bundle
    self-describing: B1/B2 can then be checked against the robot instead of being absent,
    and the next reader has something to disagree with.

    `onnx.load` pulls external data into memory, so saving without `save_as_external_data`
    folds a split export back into one file -- the only shape `publish` can carry.
    """
    import onnx

    if dst.resolve() == src.resolve():
        print("refusing to stamp in place: give --stamp <new path>", file=sys.stderr)
        return 2
    try:
        model = onnx.load(str(src))
    except Exception as e:  # noqa: BLE001
        print(f"cannot load {src}: {e}", file=sys.stderr)
        return 2

    graph = model.graph
    inits = {i.name for i in graph.initializer}
    inputs = [i for i in graph.input if i.name not in inits]
    if len(inputs) != 1 or len(graph.output) != 1:
        print(f"{src}: {len(inputs)} inputs / {len(graph.output)} outputs, not a policy graph",
              file=sys.stderr)
        return 2
    dims = inputs[0].type.tensor_type.shape.dim
    if not dims or not dims[-1].HasField("dim_value") or dims[-1].dim_value != c.obs_len:
        print(f"{src}: input is not {c.obs_len}-wide; refusing to vouch for it", file=sys.stderr)
        return 2
    out_dims = graph.output[0].type.tensor_type.shape.dim
    if not out_dims or not out_dims[-1].HasField("dim_value") \
            or out_dims[-1].dim_value != c.action_len:
        print(f"{src}: output is not {c.action_len}-wide; refusing to vouch for it", file=sys.stderr)
        return 2

    keep = [i for i in range(len(c.joint_names)) if i != c.mouth_index]
    fields = {
        "joint_names": ",".join(c.joint_names[i] for i in keep),
        "joint_stiffness": ",".join(["1.000"] * c.action_len),
        "joint_damping": ",".join(["0.000"] * c.action_len),
        "default_joint_pos": ",".join(f"{c.home_pose[i]:.3f}" for i in keep),
        "command_names": "twist,head_pose,body_pose",
        "observation_names": "base_ang_vel,projected_gravity,joint_pos,joint_vel,actions,"
                             "command,head_command,body_command",
    }
    if action_scale is not None:
        fields["action_scale"] = f"{action_scale:g}"

    existing = {p.key: p for p in model.metadata_props}
    for k, v in fields.items():
        if k in existing:
            existing[k].value = v
        else:
            p = model.metadata_props.add()
            p.key, p.value = k, v
    # A stale claim is worse than an absent one: drop what we cannot vouch for.
    for k in list(existing):
        if k not in fields:
            model.metadata_props.remove(existing[k])

    dst.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(dst), save_as_external_data=False)
    print(f"[stamp] {src.name} -> {dst}")
    print(f"        {len(fields)} metadata keys, weights inlined "
          f"({dst.stat().st_size} bytes)")
    return 0


# ---------------------------------------------------------------------------------------------

LOCAL_SAMPLES = [
    ("out/deploy61.onnx", None),
    ("out/p8head_2999.onnx", None),
    ("out/hd1910_resume_4096_to6000_1027_it5999.onnx", None),
    ("out/publish/duck-walk-56d/policy.onnx", "out/publish/duck-walk-56d/manifest.json"),
    (".upstream/DuckBuddy-main/policies/alpha_walking.onnx", None),
    (".upstream/DuckBuddy-main/training/policies/hl2915_roulade_v4bl_6999.onnx", None),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("onnx", nargs="?", help="policy .onnx, or a directory holding policy.onnx")
    ap.add_argument("--manifest", type=Path, help="manifest.json beside it")
    ap.add_argument("--toml", type=Path, help="robotd.toml to read [policy] from")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--stamp", type=Path, metavar="OUT",
                    help="write a copy with the layout contract in its metadata, weights "
                         "inlined, then audit that copy")
    ap.add_argument("--action-scale", type=float,
                    help="value to record as the policy's own action_scale when stamping")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    c = load_contract()
    if c.problems:
        print("contract parse problems:")
        for p in c.problems:
            print(f"  - {p}")
        print()

    if args.stamp:
        if not args.onnx:
            print("--stamp needs a source .onnx", file=sys.stderr)
            return 2
        src = Path(args.onnx)
        if src.is_dir():
            src = src / "policy.onnx"
        rc = stamp(src, args.stamp, c, args.action_scale)
        if rc != 0:
            return rc
        return summarise({str(args.stamp): audit(args.stamp, c, args.manifest, args.toml)})

    results: dict[str, list[Check]] = {}
    if args.onnx:
        p = Path(args.onnx)
        if p.is_dir():
            p = p / "policy.onnx"
        results[str(p)] = audit(p, c, args.manifest, args.toml)
    else:
        print(f"contract: {c.obs_len}/{c.action_len} obs/act, command {c.command_len}, "
              f"{len(c.joint_names)} joints (mouth {c.mouth_index}), "
              f"input {c.input_name!r}; publish {c.publish_obs_len}->{c.publish_action_len}")
        for rel, man in LOCAL_SAMPLES:
            p = ROOT / rel
            if not p.exists():
                continue
            mp = ROOT / man if man else None
            results[rel] = audit(p, c, mp, args.toml)
    return summarise(results)


if __name__ == "__main__":
    sys.exit(main())


