#!/usr/bin/env python3
"""Does an ONNX policy survive `duck-control/src/policy.rs::open` (official workspace)?

Source priority (project rule, 2026-11-06)
------------------------------------------
**The official upstream leads; community forks are supporting material only.** Every number
used to judge a file here is parsed from `pollen-robotics/microduck` first-party Rust source.
DuckBuddy / kissqy / 666wsp / fanhao375 and the B-generation robotd appear only as (a) a
negative control showing what a weaker reader would miss, and (b) hardware-side context.
They never supply a threshold, a joint order, or a pass/fail decision. If the official source
cannot be read, this tool says so and refuses to call the result verified.

Why this tool exists
--------------------
`verify_policy_bundle.py` audits the *B-generation* (DuckBuddy / HL-2915) reader, whose
`check_width` looks at nothing but the last dimension of the first outlet. The official
`pollen-robotics/microduck` workspace is a different reader with a stricter, different
contract. In particular a graph shaped `[1, 1, 61] -> [1, 1, 14]` passes every last-dimension
check and is refused by the official loader because `check_matrix` requires rank 2.

That matters here: the "software we write ourselves" branch derives from the official
Apache-2.0 workspace and intends to hot-load this repo's `p8head_2999.onnx`. A green result
from the B-generation auditor is not evidence that the official daemon accepts the file.

The judgement chain, all first-party source (`pollen-robotics/microduck`, branch `main`):

  robotctl/src/main.rs        `policy load <slot> <repo>` -> IPC to robotd
  updater/src/policy.rs       reads manifest.json, but "Absence is not evidence"; its own
                              test says "the shape gate at load was always going to be the
                              real check". A missing/omitted manifest field is never a refusal.
  duck-control/src/policy.rs  `pub fn validate(path)` -> `open(path)` -> the real gate:
                                outlet(path, inputs, "obs")        named input required
                                check_matrix(obs, OBS_LEN)         dtype/rank/batch/width
                                (inputs.len(), outputs.len())      exactly (1,1) or (3,3)
                                check_matrix(action, ACTION_LEN)   dtype/rank/batch/width
                                LSTM (3,3): named "actions" plus h_in/c_in/h_out/c_out
                                Sha256::digest                     recorded, never compared
  `Policy::load` additionally runs `open_warm` (one inference on Observation::zeroed());
  `validate()` deliberately does not. A static check cannot cover that -- use R1 in
  verify_policy_bundle.py for it.

Every threshold below is parsed out of those Rust files. If a required one cannot be parsed,
the tool refuses to judge instead of silently falling back to a remembered number.

    python tools/hd1910/verify_official_loader.py --selftest
    python tools/hd1910/verify_official_loader.py policy.onnx \
        --policy-rs out/evidence-official/official/duck-control_src_policy.rs \
        --obs-rs out/evidence-official/official-main/duck-control/src/obs.rs
    python tools/hd1910/verify_official_loader.py policy.onnx --upstream <workspace root>

The ONNX half is static (needs `onnx`, not `onnxruntime`), so it also runs on a machine that
has no ORT shared library -- the exact situation `open()` reports as PolicyError::Runtime.
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

PASS, FAIL, WARN, INFO, SKIP = "PASS", "FAIL", "WARN", "INFO", "SKIP"
FLOAT32 = 1  # onnx.TensorProto.FLOAT


# ---------------------------------------------------------------------------------------------
# The contract, read from source.

@dataclass
class LoaderContract:
    obs_len: int = 0
    action_len: int = 0
    rank: int = 0                       # check_matrix: shape.len() != N
    batch_ok: set[int] = field(default_factory=set)   # shape[0] != 1 && shape[0] != -1
    io_counts: set[tuple[int, int]] = field(default_factory=set)
    input_name: str = ""
    dtype: str = ""                    # TensorElementType::Float32
    recurrent_output_name: str = ""    # only checked for (3,3)
    state_cap: int = 0                 # <= 1_048_576 elements per LSTM state
    has_warmup: bool = False
    records_digest: bool = False
    verified: bool = False             # all *required* fields came from source
    problems: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)


def _read(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _int(s: str) -> int:
    return int(s.replace("_", ""))


def parse_contract(policy_rs: Path | None = None, obs_rs: Path | None = None,
                   upstream: Path | None = None) -> LoaderContract:
    """Pull the loader's thresholds out of Rust source; never hardcode a judgement value."""
    c = LoaderContract()
    p = policy_rs or (upstream / "duck-control/src/policy.rs" if upstream else None)
    o = obs_rs or (upstream / "duck-control/src/obs.rs" if upstream else None)
    # Some local mirrors store the files flattened (duck-control_src_policy.rs).
    if p is None or not _read(p):
        cand = upstream / "duck-control_src_policy.rs" if upstream else None
        if cand and _read(cand):
            p = cand
    if o is None or not _read(o):
        cand = upstream / "duck-control_src_obs.rs" if upstream else None
        if cand and _read(cand):
            o = cand

    pol, obs = _read(p), _read(o)
    c.sources = {"policy.rs": str(p) if p else "(none)", "obs.rs": str(o) if o else "(none)"}
    if not pol:
        c.problems.append(f"policy.rs unreadable: {p}")
    if not obs:
        c.problems.append(f"obs.rs unreadable: {o}")

    def need(pattern: str, text: str, label: str, cast=str):
        m = re.search(pattern, text, re.S)
        if not m:
            c.problems.append(f"cannot parse {label}")
            return None
        return cast(m.group(1))

    c.obs_len = need(r"pub const OBS_LEN: usize = (\d+);", obs, "OBS_LEN", int) or 0
    c.action_len = need(r"pub const ACTION_LEN: usize = (\d+);", obs, "ACTION_LEN", int) or 0
    c.rank = need(r"shape\.len\(\) != (\d+)", pol, "check_matrix rank", int) or 0

    m = re.search(r"shape\[0\] != (-?\d+) && shape\[0\] != (-?\d+)", pol)
    if m:
        c.batch_ok = {int(m.group(1)), int(m.group(2))}
    else:
        c.problems.append("cannot parse check_matrix batch rule")

    counts = re.findall(r"\((\d+),\s*(\d+)\)\s*=>\s*(?:false|true)", pol)
    if counts:
        c.io_counts = {(int(a), int(b)) for a, b in counts}
    else:
        c.problems.append("cannot parse input/output count match")

    c.input_name = need(r'outlet\(path,\s*inputs,\s*"([^"]+)"\)', pol, "named input") or ""
    c.dtype = need(r"TensorElementType::([A-Za-z0-9]+)", pol, "tensor dtype") or ""
    # Optional fields: their absence is a fact about the source, not a broken parse.
    rout = re.search(r'outlet\(path,\s*outputs,\s*"([^"]+)"\)', pol)
    c.recurrent_output_name = rout.group(1) if rout else ""
    cap = re.search(r"n <= ([\d_]+)", pol)
    c.state_cap = _int(cap.group(1)) if cap else 0
    c.has_warmup = "open_warm" in pol
    c.records_digest = "Sha256::digest" in pol

    required = [c.obs_len, c.action_len, c.rank, c.batch_ok, c.io_counts,
                c.input_name, c.dtype]
    c.verified = bool(pol and obs and all(required) and not c.problems)
    return c


def unverified_contract() -> LoaderContract:
    """No source given. Return the remembered official values, explicitly flagged as unverified."""
    return LoaderContract(
        obs_len=61, action_len=14, rank=2, batch_ok={1, -1},
        io_counts={(1, 1), (3, 3)}, input_name="obs", dtype="Float32",
        recurrent_output_name="actions", state_cap=1_048_576,
        has_warmup=True, records_digest=True, verified=False,
        problems=["no --upstream/--policy-rs/--obs-rs: thresholds are remembered, not "
                  "read back from source"],
        sources={"policy.rs": "(none)", "obs.rs": "(none)"},
    )


# ---------------------------------------------------------------------------------------------
# ONNX facts, statically.

@dataclass
class Tensor:
    name: str
    dtype: int
    dims: list  # int or str (dim_param); ORT turns a dim_param into -1


@dataclass
class Graph:
    path: Path
    inputs: list[Tensor] = field(default_factory=list)
    outputs: list[Tensor] = field(default_factory=list)
    external: list[str] = field(default_factory=list)
    metadata: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class Check:
    key: str
    status: str
    detail: str = ""


def _fmt(ch: Check) -> str:
    mark = {PASS: "ok  ", FAIL: "FAIL", WARN: "warn", INFO: "    ", SKIP: "skip"}[ch.status]
    return f"  [{mark}] {ch.key:<32} {ch.detail}"


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
    except Exception as e:  # noqa: BLE001
        g.error = f"cannot load: {e}"
        return g
    graph = model.graph
    inits = {i.name for i in graph.initializer}
    # ORT's session.inputs() omits tensors that are also initializers. Match it.
    g.inputs = [Tensor(i.name, i.type.tensor_type.elem_type, _dims(i))
                for i in graph.input if i.name not in inits]
    g.outputs = [Tensor(o.name, o.type.tensor_type.elem_type, _dims(o))
                 for o in graph.output]
    for i in graph.initializer:
        if i.data_location == onnx.TensorProto.EXTERNAL:
            info = {e.key: e.value for e in i.external_data}
            loc = info.get("location", "(unspecified)")
            g.external.append(loc)
    g.metadata = [p.key for p in model.metadata_props]
    return g


# ---------------------------------------------------------------------------------------------
# The gate itself.

def _find(tensors: list[Tensor], name: str) -> Tensor | None:
    for t in tensors:
        if t.name == name:
            return t
    return None


def _matrix(t: Tensor, width: int, c: LoaderContract, label: str) -> list[Check]:
    """Reproduce `tensor_shape` + `check_matrix` for one outlet."""
    out: list[Check] = []
    ok_dtype = t.dtype == FLOAT32 and c.dtype.lower() == "float32"
    out.append(Check(f"F4 {label} dtype", PASS if ok_dtype else FAIL,
                     f"elem_type {t.dtype}, open() requires {c.dtype} (float32)"
                     if not ok_dtype else "float32"))

    dims = t.dims
    rank_ok = len(dims) == c.rank
    out.append(Check(f"F5 {label} rank", PASS if rank_ok else FAIL,
                     f"shape {dims}: rank {len(dims)}, check_matrix requires {c.rank}"))

    batch = dims[0] if len(dims) >= c.rank and c.rank >= 1 else None
    symbolic = isinstance(batch, str)
    batch_ok = symbolic or batch in c.batch_ok
    note = " (dim_param -> ORT reports -1, allowed)" if symbolic else ""
    out.append(Check(f"F6 {label} batch", PASS if batch_ok else FAIL,
                     f"shape[0]={batch!r}{note}, allowed {sorted(c.batch_ok)}"))

    # check_matrix reads shape[1], i.e. the *second* dim, not dims[-1]. With rank 2 they
    # coincide; with any other rank they do not, which is the whole point of this tool.
    width_dim = dims[1] if len(dims) >= 2 else None
    width_ok = width_dim == width
    out.append(Check(f"F7 {label} width", PASS if width_ok else FAIL,
                     f"shape[1]={width_dim!r}, open() requires {width}"))
    return out


def check_loader(g: Graph, c: LoaderContract) -> list[Check]:
    out: list[Check] = []
    if g.error:
        return [Check("F1 ONNX loadable", FAIL, f"{g.path.name}: {g.error}")]
    out.append(Check("F1 ONNX loadable", PASS, f"{g.path.name}"))

    counts = (len(g.inputs), len(g.outputs))
    counts_ok = counts in c.io_counts
    out.append(Check("F2 io count", PASS if counts_ok else FAIL,
                     f"{counts[0]} in / {counts[1]} out; open() accepts "
                     f"{sorted(c.io_counts)} (the (3,3) form is LSTM)"))

    obs = _find(g.inputs, c.input_name)
    if obs is None:
        out.append(Check("F3 named input", FAIL,
                         f'no input named "{c.input_name}"; have '
                         f"{[t.name for t in g.inputs]}. outlet() looks it up by name, "
                         "and run() feeds ort::inputs![\"obs\"]"))
        return out
    out.append(Check("F3 named input", PASS, f'"{c.input_name}" found'))

    recurrent = counts == (3, 3)
    if recurrent:
        action = _find(g.outputs, c.recurrent_output_name)
        if action is None:
            out.append(Check("F12 LSTM actions", FAIL,
                             f'recurrent form needs an output named '
                             f'"{c.recurrent_output_name}"; have '
                             f"{[t.name for t in g.outputs]}"))
            return out
        out.append(Check("F12 LSTM actions", PASS, f'"{c.recurrent_output_name}" found'))
    else:
        # Non-recurrent: `let action = &outputs[0]` -- the name is free.
        action = g.outputs[0] if g.outputs else None
        if action is None:
            out.append(Check("F8 action outlet", FAIL, "no outputs"))
            return out
        out.append(Check("F8 action outlet", INFO,
                         f'outputs[0] is "{action.name}" (name unconstrained in the '
                         "(1,1) form)"))

    out += _matrix(obs, c.obs_len, c, "obs")
    out += _matrix(action, c.action_len, c, "action")

    if recurrent:
        state_names = ("h_in", "c_in", "h_out", "c_out")
        shapes = []
        for name in state_names:
            pool = g.inputs if name.endswith("_in") else g.outputs
            t = _find(pool, name)
            if t is None:
                shapes.append(None)
                continue
            d = t.dims
            valid = (len(d) == 3 and isinstance(d[0], int) and d[0] > 0
                     and (d[1] == 1 or d[1] == -1 or isinstance(d[1], str))
                     and isinstance(d[2], int) and d[2] > 0)
            shapes.append(d if valid else None)
        good = all(s is not None for s in shapes) and len({tuple(s) for s in shapes}) == 1
        out.append(Check("F12 LSTM state shapes", PASS if good else FAIL,
                         f"{dict(zip(state_names, shapes))}"))
        if good and c.state_cap:
            n = shapes[0][0] * shapes[0][2]
            out.append(Check("F12 LSTM state size", PASS if n <= c.state_cap else FAIL,
                             f"{n} elements vs cap {c.state_cap}"))

    # -- things `open()` does NOT gate on, recorded so a PASS is not over-read.
    if g.external:
        missing = [loc for loc in set(g.external)
                   if loc != "(unspecified)" and not (g.path.parent / loc).exists()]
        status = FAIL if missing else WARN
        out.append(Check("F14 external weights", status,
                         f"{len(g.external)} initializer(s) point at {sorted(set(g.external))}"
                         + (f"; missing beside the model: {missing}" if missing else
                            "; commit_from_file needs the .data file beside the .onnx")))
    else:
        out.append(Check("F14 weights embedded", PASS, "no EXTERNAL initializers"))

    out.append(Check("F15 metadata_props", INFO,
                     f"{len(g.metadata)} key(s): open() never reads metadata_props. "
                     "B0 in verify_policy_bundle.py is about self-description, NOT about "
                     "whether this daemon will load the file."))
    notes = ["Sha256 is recorded, not compared" if c.records_digest
             else "no digest recorded"]
    if c.has_warmup:
        notes.append("Policy::load also runs one zero-observation inference (open_warm); "
                     "validate() does not. Static half cannot cover it -- see R1.")
    out.append(Check("F16 digest / warm-up", INFO, " ".join(notes)))
    return out


def audit(path: Path, c: LoaderContract, verbose: bool = True) -> list[Check]:
    g = read_graph(path)
    checks: list[Check] = []
    if c.verified:
        checks.append(Check("F0 thresholds from source", PASS,
                            f"{c.obs_len}/{c.action_len}, rank {c.rank}, batch "
                            f"{sorted(c.batch_ok)}, io {sorted(c.io_counts)}, "
                            f'input "{c.input_name}", dtype {c.dtype}'))
    else:
        checks.append(Check("F0 thresholds from source", WARN,
                            "NOT verified against source -- judgement uses remembered "
                            "official values (this is a guess, not evidence). "
                            + "; ".join(c.problems)))
    checks += check_loader(g, c)
    if verbose:
        print(f"\n=== {path}")
        for ch in checks:
            print(_fmt(ch))
    return checks


def summarise(all_checks: dict[str, list[Check]]) -> int:
    print("\n" + "=" * 78)
    fails = warns = 0
    for name, checks in all_checks.items():
        bad = [c for c in checks if c.status == FAIL]
        warn = [c for c in checks if c.status == WARN]
        fails += len(bad)
        warns += len(warn)
        verdict = "FAIL" if bad else ("warn" if warn else "ok")
        print(f"  {verdict:<5} {name:<56} {len(checks):2d} checks, "
              f"{len(bad)} fail, {len(warn)} warn")
        for ch in bad + warn:
            print(f"        {'!' if ch.status == FAIL else '~'} {ch.key}: {ch.detail}")
    print("=" * 78)
    return 1 if fails else 0


# ---------------------------------------------------------------------------------------------
# Self-test. Every judgement value is parsed from a Rust fixture, and every gate has a
# negative control that must turn red.

OBS_FIXTURE = """
pub const OBS_LEN: usize = 61;
pub const ACTION_LEN: usize = 14;
pub const COMMAND_LEN: usize = 13;
"""

POLICY_FIXTURE = """
use sha2::{Digest, Sha256};
let digest: [u8; 32] = Sha256::digest(&bytes).into();
match outlet.dtype() {
    ValueType::Tensor { ty: TensorElementType::Float32, shape, .. } => Ok(shape.to_vec()),
}
fn check_matrix(path: &Path, outlet: &Outlet, width: usize) -> Result<(), PolicyError> {
    let shape = tensor_shape(path, outlet)?;
    if shape.len() != 2 || (shape[0] != 1 && shape[0] != -1) || shape[1] != width as i64 {
        return Err(shape_error(path, "tensor shape", "", ""));
    }
    Ok(())
}
fn open(path: &Path) -> Result<Network, PolicyError> {
    let inputs = session.inputs();
    let outputs = session.outputs();
    check_matrix(path, outlet(path, inputs, "obs")?, OBS_LEN)?;
    let recurrent = match (inputs.len(), outputs.len()) {
        (1, 1) => false,
        (3, 3) => true,
        counts => return Err(shape_error(path, "", "", "")),
    };
    let action = if recurrent { outlet(path, outputs, "actions")? } else { &outputs[0] };
    check_matrix(path, action, ACTION_LEN)?;
    let count = ... .filter(|&n| n <= 1_048_576) ...;
}
fn open_warm(path: &Path, zero: &Observation) -> Result<Network, PolicyError> { ... }
"""


def synth(path: Path, *, in_dims=(1, 61), out_dims=(1, 14), dtype=FLOAT32,
          input_name="obs", output_name="actions", extra_inputs=(),
          extra_outputs=(), state=False) -> Path:
    """A tiny static graph. selftest never runs ORT, so topology only needs to be writable."""
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    def tvi(name, dims):
        return helper.make_tensor_value_info(
            name, dtype, [d if isinstance(d, int) else d for d in dims])

    inputs = [tvi(input_name, in_dims)]
    inputs += [tvi(n, d) for n, d in extra_inputs]
    outputs = [tvi(output_name, out_dims)]
    outputs += [tvi(n, d) for n, d in extra_outputs]

    w = numpy_helper.from_array(
        np.zeros((in_dims[-1], out_dims[-1]), dtype=np.float32 if dtype == FLOAT32 else np.float64),
        "w")
    nodes = [helper.make_node("MatMul", [input_name, "w"], [output_name])]
    if state:
        for src, dst in (("h_in", "h_out"), ("c_in", "c_out")):
            nodes.append(helper.make_node("Identity", [src], [dst]))

    graph = helper.make_graph(nodes, "selftest", inputs, outputs, [w])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 10
    onnx.save(model, str(path))
    return path


def selftest() -> int:
    import tempfile

    checks: list[tuple[str, bool, str]] = []

    def ok(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        pol, obs = tmp / "policy.rs", tmp / "obs.rs"
        pol.write_text(POLICY_FIXTURE, encoding="utf-8")
        obs.write_text(OBS_FIXTURE, encoding="utf-8")

        c = parse_contract(pol, obs)
        ok("parse: verified", c.verified, "; ".join(c.problems))
        ok("parse: OBS_LEN 61 / ACTION_LEN 14", (c.obs_len, c.action_len) == (61, 14),
           f"{c.obs_len}/{c.action_len}")
        ok("parse: rank 2", c.rank == 2, str(c.rank))
        ok("parse: batch {1,-1}", c.batch_ok == {1, -1}, str(c.batch_ok))
        ok("parse: io {(1,1),(3,3)}", c.io_counts == {(1, 1), (3, 3)}, str(c.io_counts))
        ok("parse: input 'obs'", c.input_name == "obs", c.input_name)
        ok("parse: dtype Float32", c.dtype == "Float32", c.dtype)
        ok("parse: recurrent output 'actions'", c.recurrent_output_name == "actions",
           c.recurrent_output_name)
        ok("parse: state cap 1048576", c.state_cap == 1_048_576, str(c.state_cap))
        ok("parse: warm-up + digest present", c.has_warmup and c.records_digest)

        # -- negative controls on the parser: a changed source must change the judgement.
        pol.write_text(POLICY_FIXTURE.replace("shape.len() != 2", "shape.len() != 3"),
                       encoding="utf-8")
        ok("N1 rank rule changed in source -> parsed rank 3",
           parse_contract(pol, obs).rank == 3)
        pol.write_text(POLICY_FIXTURE.replace(
            "shape[0] != 1 && shape[0] != -1", "shape[0] != 7"), encoding="utf-8")
        ok("N2 batch rule removed -> parse problem",
           any("batch" in p for p in parse_contract(pol, obs).problems))
        obs.write_text(OBS_FIXTURE.replace("OBS_LEN: usize = 61", "OBS_LEN: usize = 56"),
                       encoding="utf-8")
        ok("N3 OBS_LEN changed -> parsed 56", parse_contract(pol, obs).obs_len == 56)
        pol.write_text(POLICY_FIXTURE, encoding="utf-8")
        obs.write_text(OBS_FIXTURE, encoding="utf-8")
        c = parse_contract(pol, obs)
        ok("N4 no source at all -> unverified", not unverified_contract().verified)
        ok("N4b empty source -> unverified",
           not parse_contract(tmp / "missing.rs", obs).verified)

        def res(p, contract=None):
            return audit(p, contract or c, verbose=False)

        def status_of(rs, key):
            for ch in rs:
                if ch.key.startswith(key):
                    return ch.status
            return "MISSING"

        def no_fail(rs):
            return not [ch for ch in rs if ch.status == FAIL]

        # -- baseline
        base = synth(tmp / "base.onnx")
        ok("baseline: 0 FAIL", no_fail(res(base)),
           "; ".join(ch.key for ch in res(base) if ch.status == FAIL))

        # -- N5: THE blind spot. Rank 3 still has 61/14 as its last dim.
        rank3 = synth(tmp / "rank3.onnx", in_dims=(1, 1, 61), out_dims=(1, 1, 14))
        r3 = res(rank3)
        ok("N5 rank-3 graph -> F5 obs rank FAIL", status_of(r3, "F5 obs rank") == FAIL,
           status_of(r3, "F5 obs rank"))
        ok("N5b rank-3 graph refused overall", not no_fail(r3))
        # Community/B-generation code is supporting material only: here it is a negative
        # control, never a source of thresholds. The existing last-dimension auditor must
        # let the rank-3 graph through -- that is precisely why the official gate is needed.
        try:
            from verify_policy_bundle import Contract as BContract, Graph as BGraph, check_graph
            mine = read_graph(rank3)
            bg = BGraph(path=rank3)
            bg.inputs = [(t.name, t.dtype, t.dims) for t in mine.inputs]
            bg.outputs = [(t.name, t.dtype, t.dims) for t in mine.outputs]
            bres = check_graph(bg, BContract(obs_len=61, action_len=14, input_name="obs"))
            legacy_fail = [ch.key for ch in bres if ch.status == "FAIL"]
            ok("N5c legacy last-dim auditor lets the rank-3 graph pass",
               not legacy_fail, f"legacy FAILs: {legacy_fail}")
        except ImportError as e:
            ok("N5c legacy auditor importable", False, str(e))

        cases = [
            ("N6 batch 2 -> F6 FAIL", dict(in_dims=(2, 61)), "F6 obs batch"),
            ("N7 float64 -> F4 FAIL", dict(dtype=11), "F4 obs dtype"),
            ("N8 2 inputs -> F2 FAIL",
             dict(extra_inputs=(("aux", (1, 3)),)), "F2 io count"),
            ("N9 input renamed -> F3 FAIL", dict(input_name="observation"), "F3 named input"),
            ("N10 obs width 60 -> F7 FAIL", dict(in_dims=(1, 60)), "F7 obs width"),
            ("N11 action width 15 -> F7 FAIL", dict(out_dims=(1, 15)), "F7 action width"),
        ]
        for i, (name, kw, key) in enumerate(cases):
            r = res(synth(tmp / f"n{i}.onnx", **kw))
            ok(name, status_of(r, key) == FAIL, f"{key} = {status_of(r, key)}")

        # -- a symbolic batch is legal: ORT reports it as -1 and check_matrix allows -1.
        sym = synth(tmp / "sym.onnx", in_dims=("batch", 61), out_dims=("batch", 14))
        ok("N12 symbolic batch passes", no_fail(res(sym)),
           "; ".join(ch.key for ch in res(sym) if ch.status == FAIL))

        # -- the (3,3) LSTM form.
        lstm = synth(tmp / "lstm.onnx", state=True,
                     extra_inputs=(("h_in", (2, 1, 32)), ("c_in", (2, 1, 32))),
                     extra_outputs=(("h_out", (2, 1, 32)), ("c_out", (2, 1, 32))))
        rl = res(lstm)
        ok("N13 LSTM (3,3) form accepted", no_fail(rl),
           "; ".join(f"{ch.key}:{ch.status}" for ch in rl if ch.status == FAIL))
        ok("N13b LSTM state shapes checked", status_of(rl, "F12 LSTM state shapes") == PASS,
           status_of(rl, "F12 LSTM state shapes"))

        # -- metadata absence is not a load failure (contrast with B0 in the bundle auditor).
        ok("N14 zero metadata_props -> no FAIL", no_fail(res(base)))
        ok("N14b F15 is INFO, not a gate", status_of(res(base), "F15") == INFO)

    print("\nSelf-test")
    bad = 0
    for name, cond, detail in checks:
        print(f"  [{'ok  ' if cond else 'FAIL'}] {name}"
              + (f"  ({detail})" if detail and not cond else ""))
        bad += 0 if cond else 1
    print(f"\n  {len(checks) - bad}/{len(checks)} passed")
    return 1 if bad else 0


# ---------------------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("onnx", nargs="?", help="policy .onnx (or a directory holding policy.onnx)")
    ap.add_argument("--upstream", type=Path,
                    help="official workspace root with duck-control/src/{policy,obs}.rs")
    ap.add_argument("--policy-rs", type=Path, help="explicit path to duck-control/src/policy.rs")
    ap.add_argument("--obs-rs", type=Path, help="explicit path to duck-control/src/obs.rs")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", type=Path, help="write all findings as JSON")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.upstream or args.policy_rs or args.obs_rs:
        c = parse_contract(args.policy_rs, args.obs_rs, args.upstream)
    else:
        c = unverified_contract()
    if c.sources.get("policy.rs") != "(none)":
        print(f"contract: {c.sources['policy.rs']} + {c.sources['obs.rs']}")
        print(f"          {c.obs_len}/{c.action_len}, rank {c.rank}, batch "
              f"{sorted(c.batch_ok)}, io {sorted(c.io_counts)}, input {c.input_name!r}, "
              f"dtype {c.dtype}, verified={c.verified}")
        for p in c.problems:
            print(f"          ! {p}")

    if not args.onnx:
        ap.error("give a policy .onnx, or --selftest")

    p = Path(args.onnx)
    if p.is_dir():
        p = p / "policy.onnx"
    results = {str(p): audit(p, c)}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {k: [{"key": ch.key, "status": ch.status, "detail": ch.detail} for ch in v]
             for k, v in results.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[json] {args.json}")
    return summarise(results)


if __name__ == "__main__":
    sys.exit(main())
