#!/usr/bin/env python3
"""Fold a provenance block into an HD-1910 training run's runmeta.

The `explore_*` / `resume_*` / `train_*` shell launchers in this directory each
write `out/runmeta_<RUN>.json` (run / task / plant / params-sha / envs / iters),
but none of them records *how to reproduce the run*: git commit, uncommitted
diff, seed, or dependency versions. This script closes that gap by appending a
`provenance` key to that file (or, if it is absent, writing
`out/run_provenance_<RUN>.json`).

It is wired into resume_standup.sh / explore_standup.sh / train_roller.sh /
explore_ground_pick.sh as a single post-meta line:
    "$PY" tools/hd1910/log_run_provenance.py --run "$RUN" --via "$0"

Seed: pass `--seed` if the launcher fixes one. The standup / roller / groundpick
launchers do NOT (rsl_rl defaults), so those runs record seed=null -- which is
itself a reproducibility finding worth fixing.

No GPU, no import of mjlab: this only touches git + the local runmeta file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _provenance import capture_provenance  # noqa: E402


def _command_from_runmeta(meta: dict[str, Any], via: str | None, seed: Any) -> str:
    parts: list[str] = [via or "tools/hd1910/<launcher>.sh"]
    if meta.get("task"):
        parts.append(str(meta["task"]))
    if meta.get("envs") is not None:
        parts.append(f"envs={meta['envs']}")
    iters = meta.get("iters", meta.get("max_iterations"))
    if iters is not None:
        parts.append(f"iters={iters}")
    if meta.get("plant"):
        parts.append(f"plant={meta['plant']}")
    if meta.get("resume"):
        parts.append("resume")
    seed_s = seed if seed is not None else meta.get("seed", None)
    if seed_s is not None:
        parts.append(f"seed={seed_s}")
    return " ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="run name; matches out/runmeta_<RUN>.json")
    ap.add_argument("--seed", type=int, default=None,
                    help="training seed if the launcher fixes one (else recorded null)")
    ap.add_argument("--via", default=None,
                    help="path of the launching script, for command reconstruction")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "out",
                    help="directory holding runmeta_*.json (default: out/)")
    args = ap.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    runmeta_path = out_dir / f"runmeta_{args.run}.json"

    meta: dict[str, Any] = {}
    if runmeta_path.exists():
        try:
            meta = json.loads(runmeta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:  # noqa: BLE001
            print(f"WARN: could not parse {runmeta_path}: {e}", file=sys.stderr)

    command = _command_from_runmeta(meta, args.via, args.seed)
    prov = capture_provenance(ROOT, seed=args.seed, command=command)
    prov["_command_note"] = (
        "reconstructed from runmeta + --via; the exact rsl_rl flag set is fixed "
        "in the launching script named by --via"
    )

    if meta:
        meta["provenance"] = prov
        runmeta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        print(f"provenance -> {runmeta_path} "
              f"(git {prov['git_commit'][:10]} dirty={prov['git_dirty']} "
              f"seed={prov['seed']})")
    else:
        target = out_dir / f"run_provenance_{args.run}.json"
        target.write_text(json.dumps(
            {"run": args.run, "provenance": prov}, indent=2, ensure_ascii=False),
            encoding="utf-8")
        print(f"provenance -> {target} (no runmeta found)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
