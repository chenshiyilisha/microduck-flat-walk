"""Mechanically diff our joy run against the official joy training artifacts.

Why: every hand-read comparison in this project has been wrong at least once
(five separate self-negations on 2026-10-24, each one a number read out of the
wrong file or off the wrong line). This script does the reading instead, and
prints only the *differences*, so a claim like "11 of 12 reward weights match"
is reproducible rather than remembered.

Inputs
------
  .upstream/official-joy-2026-10/selected-env.yaml     official env (resolved)
  .upstream/official-joy-2026-10/selected-agent.yaml   official PPO hyperparams
  .upstream/official-joy-2026-10/run.json              stage-2 resume bookkeeping
  logs/rsl_rl/microduck_joy_smooth/<run>/params/       our run (default: latest)

Usage
-----
  .venv-mjlab/Scripts/python.exe tools/verify_vs_official.py
  .venv-mjlab/Scripts/python.exe tools/verify_vs_official.py --run <run-dir-name>
  .venv-mjlab/Scripts/python.exe tools/verify_vs_official.py --section rewards
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
OFF = ROOT / ".upstream" / "official-joy-2026-10"
RUNS = ROOT / "logs" / "rsl_rl" / "microduck_joy_smooth"


# ---------------------------------------------------------------- yaml loading
def _tuple(loader, node):
    return tuple(loader.construct_sequence(node, deep=True))


def _object(loader, node):
    return dict(loader.construct_mapping(node, deep=True))


class L(yaml.SafeLoader):
    pass


def _any(loader, suffix, node):
    """catch-all: python/name:module.func, python/object:Class, etc."""
    suffix = suffix.split(":")[-1] if ":" in suffix else suffix
    if isinstance(node, yaml.ScalarNode):
        return suffix
    try:
        return loader.construct_mapping(node, deep=True)
    except Exception:
        return suffix


L.add_constructor("tag:yaml.org,2002:python/tuple", _tuple)
L.add_multi_constructor("tag:yaml.org,2002:python/", _any)


def load(p: pathlib.Path) -> dict:
    with open(p, encoding="utf-8") as f:
        return yaml.load(f, Loader=L)


# ---------------------------------------------------------------- normalisation
def func_name(term: dict) -> str:
    """`func` is either a string, a dict with __name__, or a python/object dump."""
    f = term.get("func")
    if isinstance(f, str):
        return f.rsplit(".", 1)[-1].rstrip(")")
    if isinstance(f, dict):
        for k in ("__name__", "name", "func"):
            if k in f:
                return str(f[k])
        return "<dict:" + ",".join(sorted(f)[:4]) + ">"
    return repr(f)


def norm_params(p) -> dict:
    if p is None:
        return {}
    if not isinstance(p, dict):
        p = getattr(p, "__dict__", {}) or {}
    out = {}
    for k, v in p.items():
        # SceneEntityCfg shows up either as a dump dict or as the live object.
        if not isinstance(v, (str, int, float, bool, list, tuple, type(None))):
            v = getattr(v, "__dict__", v)
        if isinstance(v, dict):
            for kk in ("name", "site_names", "body_names", "joint_names"):
                if kk in v and v[kk] is not None:
                    out[k + "." + kk] = str(v[kk])
            continue
        if isinstance(v, slice):
            continue
        if isinstance(v, (list, tuple)):
            out[k] = str(tuple(v))
        elif isinstance(v, float):
            out[k] = round(v, 9)
        else:
            out[k] = v
    return out


def rewards_of(env: dict) -> dict[str, dict]:
    r = env.get("rewards")
    if not isinstance(r, dict):
        return {}
    out = {}
    for name, term in r.items():
        term = term if isinstance(term, dict) else {}
        out[name] = {
            "weight": round(float(term.get("weight", 0.0)), 6),
            "func": func_name(term),
            "params": norm_params(term.get("params")),
        }
    return out


def curriculum_of(env: dict) -> dict[str, object]:
    c = env.get("curriculum")
    if not isinstance(c, dict):
        return {}
    out = {}
    for name, term in c.items():
        term = term if isinstance(term, dict) else {}
        stages = None
        p = term.get("params")
        if isinstance(p, dict):
            stages = p.get("weight_stages")
        out[name] = {
            "func": func_name(term),
            "stages": json.dumps(stages) if stages is not None else "-",
        }
    return out


def obs_terms(env: dict, group: str) -> dict[str, int]:
    o = (env.get("observations") or {}).get(group) or {}
    terms = o.get("terms") if isinstance(o, dict) else None
    if not isinstance(terms, dict):
        return {}
    return {k: 1 for k in terms}


# ---------------------------------------------------------------- reporting
def diff_dict(tag: str, off: dict, ours: dict, lines: list[str]) -> None:
    only_off = [k for k in off if k not in ours]
    only_our = [k for k in ours if k not in off]
    same, diff = [], []
    for k in off:
        if k in ours:
            (same if off[k] == ours[k] else diff).append(k)
    lines.append(
        f"[{tag}] same={len(same)} diff={len(diff)} only_official={len(only_off)} "
        f"only_ours={len(only_our)}"
    )
    for k in diff:
        lines.append(f"  DIFF {k}")
        a, b = off[k], ours[k]
        if isinstance(a, dict):
            for f in a:
                if a.get(f) != b.get(f):
                    lines.append(f"        {f}: official={a.get(f)!r}  ours={b.get(f)!r}")
        else:
            lines.append(f"        official={a!r}  ours={b!r}")
    for k in only_off:
        lines.append(f"  MISSING-IN-OURS {k}  official={off[k]!r}")
    for k in only_our:
        lines.append(f"  EXTRA-IN-OURS   {k}  ours={ours[k]!r}")


AGENT_KEYS = [
    ("actor.init_std", ("actor", "distribution_cfg", "init_std")),
    ("actor.std_type", ("actor", "distribution_cfg", "std_type")),
    ("actor.hidden_dims", ("actor", "hidden_dims")),
    ("actor.activation", ("actor", "activation")),
    ("alg.entropy_coef", ("algorithm", "entropy_coef")),
    ("alg.learning_rate", ("algorithm", "learning_rate")),
    ("alg.num_learning_epochs", ("algorithm", "num_learning_epochs")),
    ("alg.num_mini_batches", ("algorithm", "num_mini_batches")),
    ("alg.gamma", ("algorithm", "gamma")),
    ("alg.lam", ("algorithm", "lam")),
    ("alg.desired_kl", ("algorithm", "desired_kl")),
    ("alg.clip_param", ("algorithm", "clip_param")),
    ("alg.max_grad_norm", ("algorithm", "max_grad_norm")),
    ("num_steps_per_env", ("num_steps_per_env",)),
    ("max_iterations", ("max_iterations",)),
    ("resume", ("resume",)),
]


def dig(d: dict, path: tuple):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return "<absent>"
        cur = cur[k]
    return cur


def actor_in_features(ckpt: pathlib.Path):
    """actor MLP input width == length of the actor observation vector."""
    try:
        import torch
    except Exception:
        return "?"
    try:
        d = torch.load(ckpt, map_location="cpu", weights_only=False)
    except Exception:
        return "?"
    sd = d.get("actor_state_dict") or {}
    for k, v in sd.items():
        if k.endswith("weight") and getattr(v, "ndim", 0) == 2:
            return int(v.shape[1])
    return "?"


def table(off_env: dict, off_ag: dict) -> str:
    """One row per run: the numbers that were previously read by hand, per run."""
    off_r = rewards_of(off_env)
    rows = []
    for run in sorted(RUNS.iterdir()):
        pe = run / "params" / "env.yaml"
        pa = run / "params" / "agent.yaml"
        if not pe.exists() or not pa.exists():
            continue
        env = load(pe)
        ag = load(pa)
        r = rewards_of(env)
        n_diff = sum(1 for k in off_r if k in r and off_r[k] != r[k])
        n_diff += sum(1 for k in off_r if k not in r) + sum(1 for k in r if k not in off_r)
        models = sorted(
            int(p.stem.split("_")[1]) for p in run.glob("model_*.pt")
            if p.stem.split("_")[1].isdigit()
        )
        last = models[-1] if models else "-"
        ck = run / f"model_{last}.pt" if models else None
        rows.append({
            "run": run.name,
            "last": last,
            "actor_in": actor_in_features(ck) if ck else "?",
            "init_std": dig(ag, ("actor", "distribution_cfg", "init_std")),
            "std_type": dig(ag, ("actor", "distribution_cfg", "std_type")),
            "entropy": dig(ag, ("algorithm", "entropy_coef")),
            "max_it": dig(ag, ("max_iterations",)),
            "joy_feet": r.get("joy_feet", {}).get("func", "-"),
            "ar_w0": r.get("action_rate_l2", {}).get("weight", "-"),
            "gait_clock": "yes" if "gait_clock" in (
                ((env.get("observations") or {}).get("actor") or {}).get("terms") or {}
            ) else "no",
            "diff_vs_off": n_diff,
        })
    cols = ["run", "last", "actor_in", "init_std", "std_type", "entropy", "max_it",
            "joy_feet", "ar_w0", "gait_clock", "diff_vs_off"]
    w = {c: max(len(c), max((len(str(x[c])) for x in rows), default=0)) for c in cols}
    out = [" ".join(c.rjust(w[c]) for c in cols), " ".join("-" * w[c] for c in cols)]
    for x in rows:
        out.append(" ".join(str(x[c]).rjust(w[c]) for c in cols))
    out.append("")
    out.append("official: actor_in=61 (run.json actor_observations) init_std="
               f"{dig(off_ag, ('actor','distribution_cfg','init_std'))} "
               f"std_type={dig(off_ag, ('actor','distribution_cfg','std_type'))} "
               f"entropy={dig(off_ag, ('algorithm','entropy_coef'))} "
               f"joy_feet={rewards_of(off_env).get('joy_feet',{}).get('func')} "
               f"ar_w0={rewards_of(off_env).get('action_rate_l2',{}).get('weight')}")
    return "\n".join(out)


STACK_MARKERS = [
    # (label, file, substring that must exist when the layer is applied)
    ("peak_linear (mdp)", "mdp.py", "Linear payoff, and grade only the foot"),
    ("peak_linear (cfg)", "cfg", "func=mdp.joy_foot_peak"),
    ("peak_curriculum (mdp)", "mdp.py", "JOY_PEAK_TARGET_STAGES"),
    ("gait_clock (mdp)", "mdp.py", "def joy_gait_clock"),
    ("gait_clock (cfg)", "cfg", "terms['gait_clock']"),
    ("phase_rsi (mdp)", "mdp.py", "_joy_gait_phase_offset"),
    ("pair_min (mdp)", "mdp.py", "self.end_peak"),
    ("pair_min gate (cfg)", "cfg", "MICRODUCK_JOY_PAIR_MIN"),
    ("stance term (mdp)", "mdp.py", "def joy_foot_stance"),
    ("stance gate (cfg)", "cfg", "MICRODUCK_JOY_DS_WEIGHT"),
    ("official rhythm still present", "mdp.py", "def joy_foot_rhythm"),
    ("sigma override (should be absent)", "cfg", "sigma=.018"),
]


TASK_DIRS = {
    "installed": "ROOT/.venv-mjlab/Lib/site-packages/mjlab_microduck/tasks",
    "upstream": "ROOT/.upstream/microduck_rl-develop/src/mjlab_microduck/tasks",
}


def task_dirs() -> dict[str, pathlib.Path]:
    return {k: ROOT / v[5:] for k, v in TASK_DIRS.items()}


def sync_installed_to_upstream() -> str:
    """Copy the *live* task files back over the upstream source tree.

    Why this direction: the cfg patches write `.upstream/.../microduck_joy_env_cfg.py`
    and then copy it into site-packages, but the mdp.py patches write ONLY into
    site-packages. So `.upstream/mdp.py` falls behind, and `.upstream` is what a
    reinstall rebuilds the package from -- i.e. a reinstall silently drops four
    reward layers while the cfg still references them. 2026-10-24 `--stack`
    showed exactly that: installed had 10/10 layers, upstream had 5/10.

    Verifies: both files compile, and after the copy every marker is PRESENT in
    both trees (the check that would have gone red before this fix).
    """
    import py_compile
    import shutil

    d = task_dirs()
    lines = []
    for name in ("mdp.py", "microduck_joy_env_cfg.py"):
        src, dst = d["installed"] / name, d["upstream"] / name
        if not src.exists():
            lines.append(f"skip {name}: no installed copy")
            continue
        if src.read_bytes() == dst.read_bytes():
            lines.append(f"ok   {name}: already identical")
            continue
        py_compile.compile(str(src), doraise=True)
        backup = dst.with_suffix(dst.suffix + ".pre-sync")
        if not backup.exists():
            shutil.copy2(dst, backup)
        shutil.copy2(src, dst)
        py_compile.compile(str(dst), doraise=True)
        lines.append(f"cp   {name}: installed -> upstream (backup {backup.name})")
    lines.append("")
    lines.append(stack())
    return "\n".join(lines)


def stack(trees=("installed", "upstream")) -> str:
    """Which patch layers are present in each copy of the joy task.

    There are two copies and they are edited by different paths: the patch
    scripts edit `.upstream/.../microduck_joy_env_cfg.py` and then copy it into
    site-packages, while `apply_joy_patch.py` writes the joy block into mdp.py.
    Nothing guarantees the two copies agree, and a run imports site-packages.
    """
    paths = {
        "installed": ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks",
        "upstream": ROOT / ".upstream/microduck_rl-develop/src/mjlab_microduck/tasks",
    }
    paths.update(task_dirs())
    out = []
    for t in trees:
        d = paths[t]
        mdp = (d / "mdp.py").read_text(encoding="utf-8", errors="replace")
        cfg = (d / "microduck_joy_env_cfg.py").read_text(encoding="utf-8", errors="replace")
        out.append(f"== {t}: {d.relative_to(ROOT)}")
        for label, which, needle in STACK_MARKERS:
            txt = mdp if which == "mdp.py" else cfg
            out.append(f"   {'PRESENT' if needle in txt else 'absent ':8s} {label}")
    # do the two copies agree?
    try:
        import filecmp
        for name in ("mdp.py", "microduck_joy_env_cfg.py"):
            same = filecmp.cmp(paths["installed"] / name, paths["upstream"] / name, shallow=False)
            out.append(f"== {name}: installed == upstream ? {same}")
    except Exception as e:  # pragma: no cover
        out.append(f"== compare failed: {e}")
    return "\n".join(out)


def live_snapshot(task: str = "smooth"):
    """The config that a training launch *right now* would use.

    Built by importing the installed package, not by reading a saved run, so it
    shows drift that has never been trained: on 2026-10-24 the *stage-1* cfg had
    already moved to lr=3e-4 (official 2e-4) while every saved run said 2e-4.

    `task` must be the task the run actually uses -- `Mjlab-JoySmoothPD` builds
    through `make_microduck_joy_smooth_pd_env_cfg`, which adds the
    `initialize_joy_servo_targets` reset event. Diffing the plain
    `make_...(pd_actuators=True)` build instead reports that event as "missing
    from ours", which is a bug in the checker, not in the code.
    """
    from mjlab_microduck.tasks.microduck_joy_env_cfg import (  # noqa: PLC0415
        MicroduckJoyPdRlCfg,
        MicroduckJoySmoothPdRlCfg,
        make_microduck_joy_pd_env_cfg,
        make_microduck_joy_smooth_pd_env_cfg,
    )

    if task == "smooth":
        c, Rl = make_microduck_joy_smooth_pd_env_cfg(), MicroduckJoySmoothPdRlCfg
    else:
        c, Rl = make_microduck_joy_pd_env_cfg(), MicroduckJoyPdRlCfg
    env = {"rewards": {}, "observations": {}, "curriculum": {}}
    for name, term in c.rewards.items():
        f = getattr(term, "func", None)
        env["rewards"][name] = {
            "weight": round(float(term.weight), 6),
            "func": getattr(f, "__name__", str(f)),
            "params": norm_params(getattr(term, "params", None)),
        }
    for g in ("actor", "critic"):
        terms = getattr(c.observations.get(g), "terms", None) or {}
        env["observations"][g] = {"terms": {n: 1 for n in terms}}
    for name, term in (c.curriculum or {}).items():
        stages = (getattr(term, "params", None) or {}).get("weight_stages")
        env["curriculum"][name] = {
            "func": getattr(getattr(term, "func", None), "__name__", "?"),
            "params": {"weight_stages": stages},
        }
    ag = {
        "num_steps_per_env": Rl.num_steps_per_env,
        "max_iterations": Rl.max_iterations,
        "resume": Rl.resume,
        "actor": {
            "hidden_dims": Rl.actor.hidden_dims,
            "activation": Rl.actor.activation,
            "distribution_cfg": dict(Rl.actor.distribution_cfg),
        },
        "algorithm": dict(Rl.algorithm.__dict__),
    }
    return env, ag


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="run dir name under logs/rsl_rl/microduck_joy_smooth")
    ap.add_argument("--section", default="all", choices=["all", "rewards", "obs", "curriculum", "agent"])
    ap.add_argument("--table", action="store_true", help="one row per run instead of a single diff")
    ap.add_argument("--live", action="store_true",
                    help="diff the installed config (what a launch now would use) instead of a saved run")
    ap.add_argument("--live-task", default="smooth", choices=["smooth", "pd"],
                    help="which registered task --live should build (default Mjlab-JoySmoothPD)")
    ap.add_argument("--stack", action="store_true",
                    help="which patch layers are present in installed vs upstream copies")
    ap.add_argument("--sync", action="store_true",
                    help="copy installed task files over .upstream so a reinstall keeps the stack")
    a = ap.parse_args()

    off_env = load(OFF / "selected-env.yaml")
    off_ag = load(OFF / "selected-agent.yaml")

    if a.sync:
        print(sync_installed_to_upstream())
        return 0

    if a.stack:
        print(stack())
        return 0

    if a.table:
        print(table(off_env, off_ag))
        return 0

    if a.live:
        our_env, our_ag = live_snapshot(a.live_task)
        label = f"LIVE installed cfg (task={a.live_task})"
    else:
        if a.run:
            run = RUNS / a.run
        else:
            cands = sorted(p for p in RUNS.iterdir() if (p / "params" / "env.yaml").exists())
            if not cands:
                print("no run with params/env.yaml under", RUNS)
                return 2
            run = cands[-1]
        our_env = load(run / "params" / "env.yaml")
        our_ag_path = run / "params" / "agent.yaml"
        our_ag = load(our_ag_path) if our_ag_path.exists() else {}
        label = f"run: {run.name}"

    meta = json.loads((OFF / "run.json").read_text(encoding="utf-8"))

    lines: list[str] = []
    lines.append(f"official env : {OFF/'selected-env.yaml'}")
    lines.append(f"ours         : {label}")
    lines.append("")

    if a.section in ("all", "rewards"):
        diff_dict("rewards", rewards_of(off_env), rewards_of(our_env), lines)
        lines.append("")

    if a.section in ("all", "curriculum"):
        diff_dict("curriculum", curriculum_of(off_env), curriculum_of(our_env), lines)
        lines.append("")

    if a.section in ("all", "obs"):
        for g in ("actor", "critic"):
            o, u = obs_terms(off_env, g), obs_terms(our_env, g)
            extra = [k for k in u if k not in o]
            missing = [k for k in o if k not in u]
            lines.append(
                f"[obs/{g}] official_terms={len(o)} ours={len(u)} "
                f"extra={extra} missing={missing} "
                f"official_actor_obs={meta.get('actor_observations')}"
            )
        lines.append("")

    if a.section in ("all", "agent"):
        lines.append("[agent] official vs ours")
        for label, path in AGENT_KEYS:
            x, y = dig(off_ag, path), dig(our_ag, path)
            flag = "   " if str(x) == str(y) else "XX "
            lines.append(f"  {flag}{label}: official={x}  ours={y}")
        lines.append(f"  -- run.json: resume_index={meta.get('resume_index')} "
                     f"selected_checkpoint_index={meta.get('selected_checkpoint_index')} "
                     f"fine_tune_updates={meta.get('matched_fine_tune_updates_through_selected')}")
        lines.append("")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
