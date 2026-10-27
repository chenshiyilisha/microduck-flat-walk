# SPDX-License-Identifier: Apache-2.0
"""Parity check for an exported ONNX against its own checkpoint.

    python tools/check_onnx_parity.py --checkpoint model_1250.pt --onnx walk.onnx

Why a second implementation instead of rsl_rl's forward
-------------------------------------------------------
`mjlab_microduck.export` is a thin wrapper over `runner.export_policy_to_onnx`, which trusts that
`ActorCritic.as_onnx` folds the observation normalizer into the graph. That trust is the documented
deployment failure mode ("behaves in the viewer, not on hardware"). Comparing the ONNX against
`policy.act_inference()` would NOT catch it: the normalizer lives on the same module, so a bug in
the export path and a bug in the forward path cancel out.

So the reference here is rebuilt from raw tensors with numpy + explicit ELU, independent of both
code paths. It reads only `actor_state_dict`.

Two facts are taken from the library source, not guessed:
  * `EmpiricalNormalization.forward` is `(x - _mean) / (_std + eps)` -- it divides by the STORED
    std buffer, not by `sqrt(_var)`, and **eps defaults to 1e-2** (rsl_rl/modules/normalization.py).
    Using 1e-5 here (as some older exporters do) shifts every output and would look like a real
    mismatch.
  * the MLP is Linear/ELU(alpha=1.0) repeated, mean action only (no sampling head).

Sensitivity is asserted, not assumed
------------------------------------
`--control` runs the same reference with normalization REMOVED and requires the mismatch to be
large. A check that cannot detect the normalizer being missing is worthless: it would pass on a
graph that a robot would fail on. If the control does not diverge, the run exits non-zero.

Exit code is 0 only if (parity passes) AND (control diverges).
"""

import argparse
import json
import pathlib
import sys

import numpy as np
import onnx
import onnxruntime as ort
import torch

# From rsl_rl/modules/normalization.py: EmpiricalNormalization.__init__(eps: float = 1e-2).
DEFAULT_NORM_EPS = 1e-2
ELU_ALPHA = 1.0


def elu(x: np.ndarray, alpha: float = ELU_ALPHA) -> np.ndarray:
    return np.where(x > 0.0, x, alpha * (np.exp(np.minimum(x, 0.0)) - 1.0))


def load_actor(ckpt_path: pathlib.Path) -> dict[str, np.ndarray]:
    ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    if "actor_state_dict" not in ck:
        raise SystemExit(f"{ckpt_path} has no 'actor_state_dict'; keys={list(ck.keys())}")
    sd = {k: v.detach().cpu().numpy().astype(np.float64) for k, v in ck["actor_state_dict"].items()}
    return sd


def actor_forward(sd: dict[str, np.ndarray], obs: np.ndarray, eps: float, normalize: bool) -> np.ndarray:
    """Reference forward pass, written from the tensors only."""
    x = obs.astype(np.float64)
    if normalize:
        x = (x - sd["obs_normalizer._mean"]) / (sd["obs_normalizer._std"] + eps)
    # Linear layers are named mlp.<even index>; the odd indices are ELU, which have no weights.
    idx = 0
    while f"mlp.{idx}.weight" in sd:
        x = x @ sd[f"mlp.{idx}.weight"].T + sd[f"mlp.{idx}.bias"]
        if f"mlp.{idx + 2}.weight" in sd:
            x = elu(x)
        idx += 2
    if idx == 0:
        raise SystemExit("no mlp.*.weight tensors found in actor_state_dict")
    return x


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", type=pathlib.Path, required=True)
    ap.add_argument("--onnx", type=pathlib.Path, required=True)
    ap.add_argument("--samples", type=int, default=512)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tol", type=float, default=1e-4, help="max |onnx - reference| allowed")
    ap.add_argument("--norm-eps", type=float, default=DEFAULT_NORM_EPS)
    ap.add_argument("--control-min-ratio", type=float, default=20.0,
                    help="control (no normalizer) must diverge by at least this multiple of --tol")
    ap.add_argument("--out", type=pathlib.Path, default=None)
    args = ap.parse_args()

    sd = load_actor(args.checkpoint)
    mean, std = sd["obs_normalizer._mean"], sd["obs_normalizer._std"]
    obs_dim = mean.shape[-1]

    sess = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    out_names = [o.name for o in sess.get_outputs()]

    # Realistic observations: the normalizer's own mean/std, so a graph that forgot to normalize
    # is fed exactly the inputs a robot would send. Pure N(0,1) would hide it whenever mean~0.
    rng = np.random.default_rng(args.seed)
    obs = mean + std * rng.standard_normal((args.samples, obs_dim))
    # A few far-out rows: normalization is the only thing keeping these in the net's trained range.
    n_out = max(1, args.samples // 16)
    obs[:n_out] = mean + 6.0 * std * rng.standard_normal((n_out, obs_dim))

    # The exported graph may have a STATIC batch dim (mjlab_microduck traces with a dummy input of
    # one row, which is what a deployed controller sends). Feed it in chunks of that size instead of
    # assuming a dynamic axis -- otherwise ort rejects the batch and the failure looks like a shape
    # bug in the policy rather than a property of the export.
    static_batch = inp.shape[0] if isinstance(inp.shape[0], int) else args.samples
    chunks = []
    for i in range(0, args.samples, static_batch):
        chunk = obs[i:i + static_batch]
        if chunk.shape[0] != static_batch:  # keep the static batch exact; pad by repeating row 0
            pad = np.repeat(obs[i:i + 1], static_batch - chunk.shape[0], axis=0)
            chunk = np.concatenate([chunk, pad], axis=0)
        chunks.append(np.asarray(sess.run(out_names, {inp.name: chunk.astype(np.float32)})[0],
                                  dtype=np.float64)[: args.samples - i])
    onnx_out = np.concatenate(chunks, axis=0)
    ref = actor_forward(sd, obs, eps=args.norm_eps, normalize=True)
    ctrl = actor_forward(sd, obs, eps=args.norm_eps, normalize=False)

    def diff(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
        d = np.abs(a - b)
        scale = float(np.abs(b).max()) or 1.0
        return {"max_abs": float(d.max()), "max_rel_to_ref_scale": float(d.max() / scale),
                "n_bad": int((d > args.tol).sum())}

    parity = diff(onnx_out, ref)
    control = diff(onnx_out, ctrl)
    parity_ok = parity["max_abs"] <= args.tol
    control_ok = control["max_abs"] >= args.tol * args.control_min_ratio
    shape_ok = tuple(inp.shape[1:]) == (obs_dim,)

    report = {
        "checkpoint": str(args.checkpoint),
        "onnx": str(args.onnx),
        "onnx_sha256_16": __import__("hashlib").sha256(args.onnx.read_bytes()).hexdigest()[:16],
        "opset": None,
        "inputs": [{"name": i.name, "shape": list(i.shape), "type": i.type} for i in sess.get_inputs()],
        "outputs": [{"name": o.name, "shape": list(o.shape), "type": o.type} for o in sess.get_outputs()],
        "obs_dim": obs_dim,
        "static_batch": inp.shape[0] if isinstance(inp.shape[0], int) else None,
        "act_dim": int(sd["mlp.6.weight"].shape[0]) if "mlp.6.weight" in sd else None,
        "norm_eps": args.norm_eps,
        "samples": args.samples,
        "parity": parity,
        "control_no_normalizer": control,
        "tol": args.tol,
        "control_min_ratio": args.control_min_ratio,
        "gates": {
            "single_output": len(out_names) == 1,
            "input_shape_ok": bool(shape_ok),
            "parity_ok": bool(parity_ok),
            "control_detects_missing_normalizer": bool(control_ok),
        },
    }
    try:
        report["opset"] = [(o.domain or "ai.onnx", o.version) for o in onnx.load(str(args.onnx)).opset_import]
    except Exception as exc:  # noqa: BLE001 - opset is informational only
        report["opset"] = f"unreadable: {exc}"
    report["passed"] = all(report["gates"].values())

    print(json.dumps(report, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n")
    if not report["passed"]:
        failed = [k for k, v in report["gates"].items() if not v]
        print(f"[FAIL] {failed}", file=sys.stderr)
        return 1
    print(f"[OK] max|onnx-ref|={parity['max_abs']:.3e} (tol {args.tol:g}); "
          f"control diverges {control['max_abs'] / max(args.tol, 1e-12):.0f}x tol")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
