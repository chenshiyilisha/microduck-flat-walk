"""Convert checkpoints saved with `std_type="scalar"` so the current code can load them.

Why this is needed
------------------
tools/patch_joy_exploration.py switched the joy task's action noise from
`std_type="scalar"` to `"log"`. That is the right parameterisation (sigma =
exp(log_std) is positive by construction, and rsl_rl's scalar mode is an
unclamped raw nn.Parameter that can cross zero), but it renames the parameter:

    GaussianDistribution(std_type="scalar") -> self.std_param      (value = sigma)
    GaussianDistribution(std_type="log")    -> self.log_std_param  (value = ln sigma)

So every checkpoint trained before the switch fails to load with

    Missing key(s):    distribution.log_std_param
    Unexpected key(s): distribution.std_param

The two pre-switch runs (0757 and ar03) are the baselines the whole diagnosis is
built on, so they must stay loadable -- we convert rather than discard.

The conversion is exact, not approximate: scalar sigma -> ln(sigma).

Optimizer state is copied untouched. torch's `Optimizer.load_state_dict` matches
by parameter index/shape within each group, not by name, and the std parameter has
the same index and the same shape (14 scalars) in both parameterisations, so the
Adam moments carry over.

Originals are never modified: output is `<name>_logstd.pt` next to the input.
Idempotent: an already-converted file prints "already log" and is skipped.

Usage:
    python tools/convert_ckpt_stdtype.py logs/.../model_400.pt
    python tools/convert_ckpt_stdtype.py --all      # every pre-switch run
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Runs trained before the std_type switch. Only these need converting.
LEGACY_RUNS = ["*0757*", "*ar03*"]


def convert(path: pathlib.Path) -> str:
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(ckpt, dict) or "actor_state_dict" not in ckpt:
        return f"  ! {path.name}: not an rsl_rl checkpoint (no actor_state_dict)"

    actor = ckpt["actor_state_dict"]
    if "distribution.log_std_param" in actor:
        return f"  = {path.parent.name}/{path.name}: already log, skipped"
    if "distribution.std_param" not in actor:
        return f"  ! {path.name}: neither std_param nor log_std_param present"

    std = actor.pop("distribution.std_param")
    # sigma must be > 0 for the log to exist. rsl_rl never clamps scalar std, so a
    # checkpoint could in principle hold a value at/near zero; floor it rather than
    # emit -inf, and say so, because that would be a real (and reportable) anomaly.
    floor = 1e-4
    n_bad = int((std <= floor).sum())
    if n_bad:
        print(f"    WARNING {path.name}: {n_bad}/{std.numel()} sigma <= {floor}, floored")
    actor["distribution.log_std_param"] = torch.log(torch.clamp(std, min=floor))

    ckpt["actor_state_dict"] = actor
    out = path.with_name(path.stem + "_logstd.pt")
    torch.save(ckpt, out)

    sig = std.detach().cpu()
    back = torch.exp(actor["distribution.log_std_param"]).detach().cpu()
    err = float((sig - back).abs().max())
    return (
        f"  + {path.parent.name}/{path.name}\n"
        f"      sigma min/mean/max = {sig.min():.5f}/{sig.mean():.5f}/{sig.max():.5f}"
        f"  -> round-trip max|err| = {err:.2e}  (must be ~1e-8)\n"
        f"      wrote {out.name}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ckpt", nargs="*", help="checkpoint path(s)")
    ap.add_argument("--all", action="store_true", help="convert every model_*.pt in the legacy runs")
    ap.add_argument("--last", type=int, default=0, help="with --all, only the last N per run")
    args = ap.parse_args()

    paths: list[pathlib.Path] = [pathlib.Path(p) for p in args.ckpt]

    if args.all:
        for pat in LEGACY_RUNS:
            for d in sorted((ROOT / "logs" / "rsl_rl").glob(f"**/{pat}")):
                found = sorted(d.glob("model_*.pt"), key=lambda p: p.stat().st_mtime)
                found = [p for p in found if not p.stem.endswith("_logstd")]
                if args.last:
                    found = found[-args.last :]
                paths.extend(found)

    if not paths:
        ap.error("nothing to do: pass checkpoint paths or --all")

    bad = 0
    for p in paths:
        if not p.exists():
            print(f"  ! {p}: not found")
            bad += 1
            continue
        msg = convert(p)
        print(msg)
        if msg.lstrip().startswith("!"):
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
