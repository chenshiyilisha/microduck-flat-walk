"""Train `Mjlab-Velocity-Flat-MicroDuck` with a declared, recorded cfg variant.

Why this exists
---------------
`tools/train_velocity.sh` can already override reward terms through the CLI,
because tyro exposes the reward dict (`--env.rewards.<term>.params.std`). But it
CANNOT override curriculum *stage tables*: their `params` hold `list[dict]`,
which tyro does not surface as flags at all (the `params` help block for
`env.curriculum.standing-envs` is empty). So "stretch the curriculum stages"
-- the fix upstream prescribes for a metric that steps down exactly at a stage
boundary -- is unreachable from the command line.

The alternative, editing `site-packages/mjlab_microduck/tasks/*.py`, is worse:
`tools/check_velocity_ready.py` has two blocking checks over those exact files
(`velocity_cfg_pristine` wants a byte-identical cfg; `mdp_patch_contained`
allows only joy/NaN/warm-start additions to mdp.py). Editing them forces
`--no-check`, i.e. trading the guard rails for experiment capability.

So this script does what the CLI cannot: parse the *real* `TrainConfig` exactly
like `mjlab.scripts.train`, mutate the live cfg object in-process, record what
changed, and hand it to `mjlab.scripts.train.launch_training`. Neither file
under `site-packages` is touched, and the pristine check stays meaningful.

Why stage tables and not something else
---------------------------------------
Upstream's own AGENTS.md (:200-204):

    Phase-align every stage with what the policy has actually learned: don't
    harden spawn mixes before the current slice consolidates; don't introduce
    taxes before the skill exists. When a wandb metric steps DOWN exactly at
    curriculum stage boundaries, the pacing is wrong -- stretch stages or move
    the introduction later, never earlier.

Measured on this task, both stage tables step at iteration 1500:

    standing_envs     0.15 -> 0.20            (`rel_standing_envs`)
    head_pose_range   +-0.39 -> +-0.72 rad    (+85% in one step)

and the delivered checkpoint peaks at 1250 while iter 1999 falls back to the
baseline's ratio (docs/05-flat-walk.md §10.4). The timing is exact; this script
tests whether it is also causal.

Usage
-----
    # control: reproduce the unmodified schedule (sanity check)
    .venv-mjlab/Scripts/python.exe tools/train_velocity_variant.py \
        --env.scene.num-envs 4096 --agent.max-iterations 2000 \
        --agent.run-name vel_defer_ctrl

    # variant: push every stage at/after iter 1500 out by 1000 iterations
    .venv-mjlab/Scripts/python.exe tools/train_velocity_variant.py \
        --defer-from 1500 --defer-by 1000 \
        --env.scene.num-envs 4096 --agent.max-iterations 2000 \
        --agent.run-name vel_defer1500x1000

`--defer-from/--defer-by` are the only knobs this script adds; everything else
is mjlab's own `TrainConfig` and is passed through verbatim.

What gets recorded
------------------
`out/variant_meta_<run>.json` holds the resolved schedule before AND after the
mutation, plus the sha256 of the untouched cfg files. A declared change is not
evidence that it took effect -- the "after" table is read back off the same cfg
object that training receives.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import mjlab
import mjlab.tasks  # noqa: F401  (populates the task registry)
import tyro

DEFAULT_TASK = "Mjlab-Velocity-Flat-MicroDuck"

# Curriculum terms whose params hold a stage table, and the key the table lives
# under. Kept explicit rather than auto-discovered: "every list-of-dict param" is
# not the same set as "every timeline", and silently shifting an unrelated table
# would corrupt the experiment.
STAGE_TABLES: dict[str, str] = {
    "standing_envs": "standing_stages",
    "head_pose_range": "range_stages",
    "body_pose_range": "range_stages",
}


def _sha16(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError as e:  # noqa: BLE001
        return f"<unreadable: {type(e).__name__}>"


def _snapshot(cfg) -> dict:
    """Read the working stage tables off the live cfg (not from the source file)."""
    out: dict[str, list] = {}
    for term_name, key in STAGE_TABLES.items():
        term = cfg.curriculum.get(term_name)
        if term is None:
            out[term_name] = []
            continue
        stages = term.params.get(key)
        if stages is None:
            out[term_name] = []
            continue
        # Copy so the "before" snapshot cannot be mutated along with the cfg.
        out[term_name] = [dict(s) for s in stages]
    return out


def _rewards(cfg) -> dict:
    """Read back the effective tracking kernels off the live cfg.

    Same reasoning as `train_velocity.sh`: this script receives its overrides as
    argv, and a printed/declared flag is not evidence that tyro resolved it. The
    numbers here are read from the object training will actually use.
    """
    try:
        cmd_max = max(abs(v) for v in cfg.commands["twist"].ranges.lin_vel_x)
    except Exception:  # noqa: BLE001
        cmd_max = None
    out: dict[str, dict] = {}
    for name in ("track_linear_velocity", "track_angular_velocity", "action_rate_l2"):
        term = cfg.rewards.get(name)
        if term is None:
            continue
        row: dict = {"weight": term.weight}
        sigma = term.params.get("std") if isinstance(term.params, dict) else None
        if sigma is not None:
            row["std"] = sigma
            row["std_sq"] = sigma * sigma
            row["std_over_cmd_max"] = (sigma / cmd_max) if cmd_max else None
        out[name] = row
    return out


def _defer(cfg, defer_from_iter: int, defer_by_iter: int, steps_per_iter: int) -> dict:
    """Shift every stage whose step is at/after `defer_from_iter` by `defer_by_iter`.

    Shifting *all* later stages (not just the boundary one) keeps the table
    monotonic -- moving 1500 to 2500 while leaving 2000 in place would put the
    steps out of order and the curriculum's "last stage at or below current" walk
    would silently skip a level.
    """
    from_step = defer_from_iter * steps_per_iter
    delta = defer_by_iter * steps_per_iter
    changed: dict[str, list] = {}
    for term_name, key in STAGE_TABLES.items():
        term = cfg.curriculum.get(term_name)
        if term is None or key not in term.params:
            continue
        before = [dict(s) for s in term.params[key]]
        after = []
        for stage in before:
            stage = dict(stage)
            if stage.get("step", 0) >= from_step:
                stage["step"] = stage["step"] + delta
            after.append(stage)
        term.params[key] = after
        changed[term_name] = [
            {"was": b.get("step"), "now": a.get("step")} for b, a in zip(before, after)
        ]
    return changed


def main() -> int:
    import argparse

    # Two custom flags are peeled off before tyro sees argv: tyro is configured
    # for mjlab's TrainConfig and would reject them as unknown.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--defer-from", type=int, default=None)
    pre.add_argument("--defer-by", type=int, default=0)
    pre.add_argument("--task", default=DEFAULT_TASK)
    pre.add_argument("--dry-run", action="store_true")
    known, passthrough = pre.parse_known_args()

    from mjlab.scripts.train import TrainConfig, launch_training

    if "--help" in passthrough or "-h" in passthrough:
        # Delegate: tyro prints the full TrainConfig help, which is the contract
        # this script forwards. Custom flags are documented in the module docstring.
        import sys

        tyro.cli(
            TrainConfig,
            args=["--help"],
            default=TrainConfig.from_task(known.task),
            config=mjlab.TYRO_FLAGS,
        )
        return 0

    args = tyro.cli(
        TrainConfig,
        args=passthrough,
        default=TrainConfig.from_task(known.task),
        config=mjlab.TYRO_FLAGS,
    )

    steps_per_iter = int(args.agent.num_steps_per_env)
    before = _snapshot(args.env)
    changed: dict[str, list] = {}
    if known.defer_from is not None and known.defer_by != 0:
        changed = _defer(args.env, known.defer_from, known.defer_by, steps_per_iter)
    after = _snapshot(args.env)

    live = Path(__file__).resolve().parents[1] / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks"
    meta = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "run": args.agent.run_name,
        "task": known.task,
        "variant": {
            "defer_from_iter": known.defer_from,
            "defer_by_iter": known.defer_by,
            "steps_per_iter": steps_per_iter,
            "shift_steps": (known.defer_by * steps_per_iter) if known.defer_from is not None else 0,
        },
        "curriculum_before": before,
        "curriculum_after": after,
        "curriculum_changed": changed,
        "envs": int(args.env.scene.num_envs),
        "iters": int(args.agent.max_iterations),
        # These files are NOT modified by this script; the hashes are recorded so a
        # future reader can tell an unmodified install from a patched one.
        "cfg_sha256_16": _sha16(live / "microduck_velocity_env_cfg.py"),
        "mdp_sha256_16": _sha16(live / "mdp.py"),
        "passthrough_args": passthrough,
        "rewards_effective": _rewards(args.env),
    }

    out_dir = Path("out")
    out_dir.mkdir(exist_ok=True)
    name = args.agent.run_name or datetime.now().strftime("%m%d_%H%M%S")
    meta_path = out_dir / f"variant_meta_{name}.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"variant meta -> {meta_path}")
    if not changed:
        print("curriculum: UNCHANGED (control run)")
    else:
        for term, rows in changed.items():
            moved = [r for r in rows if r["was"] != r["now"]]
            if moved:
                print(f"curriculum {term}: " + ", ".join(f"{r['was']}->{r['now']}" for r in moved))

    if known.dry_run:
        print("--dry-run: resolved and recorded, not launching training")
        return 0

    launch_training(task_id=known.task, args=args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
