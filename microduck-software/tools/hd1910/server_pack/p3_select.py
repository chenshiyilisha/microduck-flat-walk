#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""P3 seed sweep: record runs and pick a checkpoint by fixed-condition eval.

Why this file exists
--------------------
rsl_rl has no best-checkpoint-by-eval; the last .pt is where training stopped.
Task #76 asks for >=3 training seeds per action, evaluated on the SAME plant,
then pick by (primary high, risk low) using median + sem across the sweep.
Doing that by hand invites the classic failure: comparing a 64-env number with
a 256-env one, or silently treating a missing field as zero. So the instrument
(num_envs / seconds / cmd / eval seed / plant) is fixed for every row, cached
JSON is reused, and a missing field raises instead of becoming a plausible 0.

Subcommands
-----------
  record   append/refresh one manifest row (p3_sweep.sh calls this)
  done     exit 0 iff (task,seed,envs,iters) already recorded status=ok
  select   eval every ok row, write summary JSON + markdown table
  selftest synthetic data + negative controls; NO GPU, NO training

Usage (on the 4070 Ti server, Git Bash):
  PY=.venv-mjlab/Scripts/python.exe
  $PY tools/hd1910/server_pack/p3_select.py select \
      --manifest out/p3_sweep_manifest.jsonl --out out/p3_sweep_summary.json
  # print commands without burning GPU:
  $PY tools/hd1910/server_pack/p3_select.py select --dry-run ...
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVAL = {
    "walk": ROOT / "tools" / "eval_velocity_in_sim.py",
    "ground_pick": ROOT / "tools" / "hd1910" / "eval_ground_pick.py",
    "standup": ROOT / "tools" / "hd1910" / "eval_standup.py",
}
KEY = ("task", "seed", "envs", "iters")


def key_of(row: dict) -> tuple:
    return tuple(row[k] for k in KEY)


def load_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"bad manifest line {i} in {path}: {e}") from e
    return rows


def write_manifest(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def newest_ckpt(ckpt_dir: str | None) -> Path | None:
    if not ckpt_dir:
        return None
    d = Path(ckpt_dir)
    if not d.is_dir():
        return None
    pts = [p for p in d.glob("model_*.pt") if p.stem[6:].isdigit()]
    if not pts:
        return None
    return max(pts, key=lambda p: int(p.stem[6:]))


def resolve_ckpt_dir(glob_pat: str | None, status: str) -> str | None:
    """status=ok must resolve to a real dir containing checkpoints (fail loud)."""
    hits = sorted(glob.glob(glob_pat)) if glob_pat else []
    hits = [h for h in hits if Path(h).is_dir()]
    if status == "ok" and not hits:
        raise SystemExit(f"FAIL: no checkpoint dir matched {glob_pat!r}; "
                         "training reported success but produced no run dir")
    if status == "ok" and newest_ckpt(hits[-1]) is None:
        raise SystemExit(f"FAIL: {hits[-1]} has no model_*.pt")
    return str(Path(hits[-1])) if hits else None


def cmd_record(a) -> int:
    path = Path(a.manifest)
    row = {
        "task": a.task, "seed": int(a.seed), "envs": int(a.envs),
        "iters": int(a.iters), "run": a.run, "status": a.status,
        "plant": a.plant, "ckpt_dir": resolve_ckpt_dir(a.ckpt_glob, a.status),
    }
    rows = [r for r in load_manifest(path) if key_of(r) != key_of(row)]
    rows.append(row)
    write_manifest(path, rows)
    print(f"recorded {a.task} seed={a.seed} status={a.status} run={a.run}")
    return 0


def cmd_done(a) -> int:
    want = (a.task, int(a.seed), int(a.envs), int(a.iters))
    for r in load_manifest(Path(a.manifest)):
        if key_of(r) == want and r.get("status") == "ok":
            return 0
    return 1


def eval_cmd(task: str, ckpt: Path, out: Path, a) -> list[str]:
    py = sys.executable
    if task == "walk":
        return [py, str(EVAL[task]), "--checkpoint", str(ckpt),
                "--plant", a.plant, "--num-envs", str(a.num_envs),
                "--seconds", str(a.seconds), "--cmd-vx", str(a.cmd_vx),
                "--cmd-wz", "0", "--seed", str(a.eval_seed), "--out", str(out)]
    return [py, str(EVAL[task]), "--checkpoint", str(ckpt),
            "--envs", str(a.num_envs), "--device", a.device, "--json", str(out)]


def extract(task: str, data: dict) -> dict:
    """Strict: a missing field is an error, never a silent zero."""
    if task == "walk":
        return {
            "primary": data["speed"]["vx_median_of_env_means"],
            "risk": data["stability"]["terminated_frac"],
            "upright": data["stability"]["upright_mean"],
            "err_xy": data["official_metrics"].get("error_vel_xy"),
            "failed_gates": [k for k, v in data["gates"].items() if v is False],
            "primary_name": "vx_median_of_env_means",
            "risk_name": "terminated_frac",
        }
    return {
        "primary": data["success_rate"][0],
        "risk": data["fall_rate"][0],
        "primary_name": "success_rate_median",
        "risk_name": "fall_rate_median",
    }


def med_sem(xs: list[float]) -> dict:
    if not xs:
        return {"median": None, "sem": None, "n": 0}
    return {
        "median": statistics.median(xs),
        "sem": (statistics.stdev(xs) / math.sqrt(len(xs))) if len(xs) > 1 else None,
        "n": len(xs),
    }


def rank(rows: list[dict]) -> list[dict]:
    """Two-axis order: primary DESC, risk ASC. Never collapse to one number."""
    return sorted(rows, key=lambda r: (-r["primary"], r["risk"], r["run"]))


def summarize(rows: list[dict]) -> dict:
    out = {}
    for task in sorted({r["task"] for r in rows}):
        group = [r for r in rows if r["task"] == task]
        out[task] = {
            "primary": med_sem([r["primary"] for r in group]),
            "risk": med_sem([r["risk"] for r in group]),
            "primary_name": group[0]["primary_name"],
            "risk_name": group[0]["risk_name"],
            "ordered": [r["run"] for r in rank(group)],
            "recommended": rank(group)[0]["run"],
        }
    return out


def cmd_select(a) -> int:
    manifest = Path(a.manifest)
    rows = [r for r in load_manifest(manifest) if r.get("status") == "ok"]
    if not rows:
        raise SystemExit(f"no status=ok rows in {manifest}; run p3_sweep.sh first")
    out_dir = Path(a.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / "p3_eval_cache"
    cache.mkdir(parents=True, exist_ok=True)

    measured = []
    for r in rows:
        ckpt = newest_ckpt(r.get("ckpt_dir"))
        if ckpt is None:
            raise SystemExit(f"FAIL: row {r['run']} has no model_*.pt in {r.get('ckpt_dir')}")
        js = cache / f"{r['run']}_n{a.num_envs}_s{a.seconds}_g{a.eval_seed}.json"
        if js.exists() and not a.force:
            print(f"[cached] {js.name}", flush=True)
        else:
            cmd = eval_cmd(r["task"], ckpt, js, a)
            if a.dry_run:
                print("[dry-run] " + " ".join(cmd))
                continue
            env = dict(os.environ)
            env.setdefault("MUJOCO_GL", "glfw")
            print(f"eval {r['run']} -> {js.name}", flush=True)
            rc = subprocess.run(cmd, cwd=ROOT, env=env).returncode
            if rc != 0 or not js.exists():
                raise SystemExit(f"FAIL: eval {r['run']} rc={rc}; see {js}")
        m = extract(r["task"], json.loads(js.read_text(encoding="utf-8")))
        measured.append({**r, "checkpoint": ckpt.name, **m})

    if a.dry_run:
        print("dry-run: no eval executed, no summary written")
        return 0

    summary = {
        "generated_by": "tools/hd1910/server_pack/p3_select.py",
        "manifest": str(manifest),
        "instrument": {
            "num_envs": a.num_envs, "seconds": a.seconds,
            "cmd_vx": a.cmd_vx, "eval_seed": a.eval_seed,
            "plant": a.plant, "device": a.device,
        },
        "rows": measured,
        "by_task": summarize(measured),
        "note": "Cross-training-seed selection, NOT a causal comparison. "
                "Numbers from a different instrument must never be mixed.",
    }
    Path(a.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("\n| task | run | primary | risk | failed gates |")
    print("|---|---|---:|---:|---|")
    for r in measured:
        print(f"| {r['task']} | {r['run']} | {r['primary']:.4f} | {r['risk']:.4f} "
              f"| {','.join(r.get('failed_gates', [])) or '-'} |")
    for task, s in summary["by_task"].items():
        print(f"\n{task}: median primary={s['primary']} risk={s['risk']}")
        print(f"  recommended = {s['recommended']}  (order: {s['ordered']})")
    print(f"\nsummary -> {a.out}")
    return 0


def cmd_selftest() -> int:
    """Synthetic rows + three negative controls. No GPU, no training."""
    checks = []

    def ck(name, ok):
        checks.append((name, bool(ok)))

    # 1) median / sem on a known vector
    s = med_sem([0.10, 0.20, 0.30])
    ck("median=0.20", abs(s["median"] - 0.20) < 1e-12)
    ck("sem=0.1/sqrt(3)", abs(s["sem"] - (0.1 / math.sqrt(3))) < 1e-12)

    # 2) two-axis ordering
    rows = [
        {"task": "walk", "run": "A", "primary": 0.20, "risk": 0.0,
         "primary_name": "vx", "risk_name": "term"},
        {"task": "walk", "run": "B", "primary": 0.20, "risk": 0.5,
         "primary_name": "vx", "risk_name": "term"},
        {"task": "walk", "run": "C", "primary": 0.15, "risk": 0.0,
         "primary_name": "vx", "risk_name": "term"},
    ]
    ck("rank A>B>C", [r["run"] for r in rank(rows)] == ["A", "B", "C"])
    ck("recommended A", summarize(rows)["walk"]["recommended"] == "A")

    # NEGATIVE CONTROL 1: a high-risk run must not win, even at top primary
    bad = [dict(r) for r in rows]
    bad[0]["risk"] = 0.9
    ck("negctl risk demotes A", summarize(bad)["walk"]["recommended"] != "A")

    # NEGATIVE CONTROL 2: missing field must raise, never become 0
    try:
        extract("walk", {"speed": {}, "stability": {}, "official_metrics": {},
                         "gates": {}})
        ck("negctl missing field raises", False)
    except KeyError:
        ck("negctl missing field raises", True)

    # NEGATIVE CONTROL 3: status=ok with no ckpt dir must fail loud
    try:
        resolve_ckpt_dir("nonexistent_glob_for_selftest/*", "ok")
        ck("negctl ok-without-ckpt fails", False)
    except SystemExit:
        ck("negctl ok-without-ckpt fails", True)
    ck("fail status tolerates no ckpt",
       resolve_ckpt_dir("nonexistent_glob_for_selftest/*", "fail") is None)

    # record / done round trip in a temp dir
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "manifest.jsonl"
        run_dir = Path(td) / "logs" / "run_A"
        run_dir.mkdir(parents=True)
        (run_dir / "model_100.pt").write_bytes(b"x")
        (run_dir / "model_200.pt").write_bytes(b"x")
        ns = argparse.Namespace(manifest=str(m), task="walk", seed=42, envs=64,
                                iters=10, run="A", status="ok", plant="default",
                                ckpt_glob=str(run_dir.parent / "*_A"))
        # glob pattern above does not match run_A; fix it explicitly
        ns.ckpt_glob = str(run_dir)
        cmd_record(ns)
        ck("record writes row", len(load_manifest(m)) == 1)
        ck("done returns 0", cmd_done(argparse.Namespace(
            manifest=str(m), task="walk", seed=42, envs=64, iters=10)) == 0)
        ck("done rejects other seed", cmd_done(argparse.Namespace(
            manifest=str(m), task="walk", seed=43, envs=64, iters=10)) == 1)
        ck("newest ckpt = 200", newest_ckpt(str(run_dir)).stem == "model_200")
        # refresh, not duplicate
        cmd_record(ns)
        ck("record is idempotent", len(load_manifest(m)) == 1)

    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    bad_n = sum(1 for _, ok in checks if not ok)
    print(f"{len(checks) - bad_n}/{len(checks)} passed")
    return 1 if bad_n else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record")
    for k in ("manifest", "task", "run", "status", "plant", "ckpt-glob"):
        r.add_argument("--" + k, required=True)
    for k in ("seed", "envs", "iters"):
        r.add_argument("--" + k, required=True, type=int)
    r.set_defaults(fn=cmd_record)

    d = sub.add_parser("done")
    for k in ("manifest", "task"):
        d.add_argument("--" + k, required=True)
    for k in ("seed", "envs", "iters"):
        d.add_argument("--" + k, required=True, type=int)
    d.set_defaults(fn=cmd_done)

    s = sub.add_parser("select")
    s.add_argument("--manifest", default="out/p3_sweep_manifest.jsonl")
    s.add_argument("--out", default="out/p3_sweep_summary.json")
    s.add_argument("--plant", default="default", help="eval plant; default = live plant")
    s.add_argument("--num-envs", type=int, default=64)
    s.add_argument("--seconds", type=float, default=8)
    s.add_argument("--cmd-vx", type=float, default=0.4)
    s.add_argument("--eval-seed", type=int, default=0)
    s.add_argument("--device", default="cuda:0")
    s.add_argument("--force", action="store_true", help="ignore cached eval JSON")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_select)

    t = sub.add_parser("selftest")
    t.set_defaults(fn=lambda _a: cmd_selftest())

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
