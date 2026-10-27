#!/usr/bin/env python
"""Pre-flight check for the leg-walking route (`Mjlab-Velocity-Flat-MicroDuck`).

Why this exists
---------------
Every previous failure in this project was found *after* spending GPU hours, and
several of them were contract mismatches that a 40-second static check would have
caught (obs dimension, curriculum counter, wrong robot model, patch leaking into
an unrelated task). This script spends no training time and answers, before a
single iteration runs:

  A. the task exists and both cfgs (train / play) build;
  B. actor observation is exactly the 61-D deployment contract, same 8 terms in
     the same order (so a policy trained here is deployable without touching the
     MCU side);
  C. action is 14-D;
  D. network / PPO hyper-parameters are the values we think they are;
  E. the live cfg is byte-identical to the upstream snapshot (no silent local
     edits);
  F. the joy-only patch layers do not touch the velocity task;
  G. the walking robot model is `robot_walk.xml`, not the stand-up model;
  H. `MICRODUCK_WARM_START` is off (it restarts curricula after a checkpoint
     load -- harmless from scratch, but it must not be on by accident);
  I. the compute budget, in env-steps, with a wall-clock estimate;
  J. GPU is free and the disk can hold the checkpoints.

Exit code is 0 when every BLOCKING check passes, 1 otherwise.

Usage:
    python tools/check_velocity_ready.py
    python tools/check_velocity_ready.py --envs 4096 --iters 12000
    python tools/check_velocity_ready.py --json out/velocity_ready.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = "Mjlab-Velocity-Flat-MicroDuck"

# The deployment contract. A policy is only useful if these match, in this order.
EXPECTED_ACTOR_TERMS = [
    "base_ang_vel",        # 3
    "projected_gravity",   # 3
    "joint_pos",           # 14
    "joint_vel",           # 14
    "actions",             # 14
    "command",             # 3   (twist)
    "head_command",        # 4
    "body_command",        # 6
]
EXPECTED_ACTOR_DIM = 61
EXPECTED_ACTION_DIM = 14

# Measured on this machine (RTX 4070 Laptop 8 GB), see microduck-走起来的配方.md §6.
SEC_PER_ITER = {2048: 1.55, 4096: 3.08, 8192: 14.13}

results: list[dict] = []


def record(key: str, ok: bool | None, detail: str, blocking: bool = True) -> None:
    results.append({"check": key, "ok": ok, "detail": detail, "blocking": blocking})
    mark = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
    print(f"  [{mark}] {key}: {detail}")


def head(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--envs", type=int, default=4096)
    ap.add_argument("--iters", type=int, default=12000)
    ap.add_argument("--json", default=None)
    ap.add_argument("--skip-env", action="store_true",
                    help="skip building the env (fast path, contract check becomes advisory)")
    a = ap.parse_args()

    info: dict = {"task": TASK, "envs": a.envs, "iters": a.iters}

    # ---------------------------------------------------------------- A. import
    head("A. task registration and cfg load")
    try:
        import mjlab_microduck.tasks  # noqa: F401  (side effect: registers tasks)
        from mjlab.tasks.registry import load_env_cfg
        # Use the official `list-envs` implementation instead of hand-filtering
        # `list_tasks()`: counting by hand is how "官方 35 个任务" survived three
        # documents when the real number was 33 (see microduck-RL_duck教学仓对照.md).
        # This prints the same table the CLI prints and returns the row count, so
        # the number here always agrees with `list-envs.exe --keyword`.
        import io
        import re
        from contextlib import redirect_stdout

        from mjlab.scripts.list_envs import list_environments

        buf = io.StringIO()
        with redirect_stdout(buf):
            n_duck = list_environments(keyword="MicroDuck")
        # prettytable rows look like `| 12 | Mjlab-Velocity-Flat-MicroDuck |`
        ids = re.findall(r"^\|\s*\d+\s*\|\s*(\S+)\s*\|", buf.getvalue(), flags=re.M)
        info["microduck_task_count"] = n_duck
        info["microduck_task_ids"] = ids
        have = TASK in ids
        record("task_registered", have,
               f"{TASK} listed among {len(ids)} MicroDuck tasks (official list-envs)"
               if have else f"{TASK} NOT in official list-envs table")
        if not have:
            return finish(a, info)
        cfg = load_env_cfg(TASK, play=False)
        cfg_play = load_env_cfg(TASK, play=True)
        record("cfg_train_builds", True, f"num_envs default {cfg.scene.num_envs}")
        record("cfg_play_builds", True, f"num_envs default {cfg_play.scene.num_envs}")
    except Exception as e:  # noqa: BLE001
        record("cfg_load", False, f"{type(e).__name__}: {e}")
        return finish(a, info)

    # ------------------------------------------------------------- B/C. contract
    head("B/C. observation and action contract")
    if a.skip_env:
        record("actor_obs_dim", None, "skipped (--skip-env)")
        record("action_dim", None, "skipped (--skip-env)")
    else:
        try:
            from mjlab.envs import ManagerBasedRlEnv
            probe = load_env_cfg(TASK, play=False)
            probe.scene.num_envs = 2
            env = ManagerBasedRlEnv(probe, device="cpu")
            try:
                dims = env.observation_manager.group_obs_dim
                actor_dim = int(dims["actor"][0])
                terms = list(env.observation_manager.active_terms["actor"])
                act_dim = int(env.action_manager.total_action_dim)
            finally:
                close = getattr(env, "close", None)
                if callable(close):
                    close()
            info["actor_obs_dim"] = actor_dim
            info["actor_terms"] = terms
            info["critic_obs_dim"] = int(dims["critic"][0])
            info["action_dim"] = act_dim

            record("actor_obs_dim", actor_dim == EXPECTED_ACTOR_DIM,
                   f"{actor_dim} (expected {EXPECTED_ACTOR_DIM})")
            same_order = terms == EXPECTED_ACTOR_TERMS
            record("actor_term_order", same_order,
                   "identical to deployment contract" if same_order
                   else f"got {terms}")
            record("action_dim", act_dim == EXPECTED_ACTION_DIM,
                   f"{act_dim} (expected {EXPECTED_ACTION_DIM})")
        except Exception as e:  # noqa: BLE001
            record("env_build", False, f"{type(e).__name__}: {str(e)[:200]}")

    # --------------------------------------------------------------- D. RL cfg
    head("D. network and PPO hyper-parameters")
    try:
        from mjlab_microduck.tasks.microduck_velocity_env_cfg import (
            MicroduckRlCfg as R,
            NUM_STEPS_PER_ENV,
            ENABLE_SYMMETRY,
        )
        rl = {
            "actor_hidden_dims": list(R.actor.hidden_dims),
            "critic_hidden_dims": list(R.critic.hidden_dims),
            "activation": R.actor.activation,
            "obs_normalization": bool(R.actor.obs_normalization),
            "init_std": R.actor.distribution_cfg.get("init_std"),
            "std_type": R.actor.distribution_cfg.get("std_type"),
            "learning_rate": R.algorithm.learning_rate,
            "schedule": R.algorithm.schedule,
            "entropy_coef": R.algorithm.entropy_coef,
            "clip_param": R.algorithm.clip_param,
            "gamma": R.algorithm.gamma,
            "lam": R.algorithm.lam,
            "desired_kl": R.algorithm.desired_kl,
            "num_learning_epochs": R.algorithm.num_learning_epochs,
            "num_mini_batches": R.algorithm.num_mini_batches,
            "max_grad_norm": R.algorithm.max_grad_norm,
            "num_steps_per_env": R.num_steps_per_env,
            "max_iterations": R.max_iterations,
            "save_interval": R.save_interval,
            "symmetry": bool(ENABLE_SYMMETRY),
        }
        info["rl_cfg"] = rl
        record("actor_hidden_dims", list(R.actor.hidden_dims) == [512, 256, 128],
               str(rl["actor_hidden_dims"]))
        record("num_steps_per_env", R.num_steps_per_env == NUM_STEPS_PER_ENV,
               f"{R.num_steps_per_env} (module const {NUM_STEPS_PER_ENV})")
        record("lr_schedule", R.algorithm.schedule == "adaptive",
               f"lr={R.algorithm.learning_rate} schedule={R.algorithm.schedule}",
               blocking=False)
        record("max_iterations_default", R.max_iterations >= 10000,
               f"{R.max_iterations}", blocking=False)
    except Exception as e:  # noqa: BLE001
        record("rl_cfg", False, f"{type(e).__name__}: {e}")

    # --------------------------------------------------- E. upstream byte-diff
    head("E. live cfg vs upstream snapshot")
    rel = "src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py"
    up = ROOT / ".upstream" / "microduck_rl-develop" / rel
    live = ROOT / ".venv-mjlab" / "Lib" / "site-packages" / "mjlab_microduck" / "tasks" / Path(rel).name
    try:
        same = up.read_bytes() == live.read_bytes()
        record("velocity_cfg_pristine", same,
               "byte-identical to upstream" if same
               else f"DIFFERS from {up.name} -- run tools/verify_vs_official.py --sync")
    except Exception as e:  # noqa: BLE001
        record("velocity_cfg_pristine", None, f"cannot compare: {e}", blocking=False)

    # ------------------------------------------------ F. joy patch containment
    head("F. joy-only patches do not leak into velocity")
    try:
        txt = live.read_text(encoding="utf-8")
        leaks = [t for t in ("joy_", "pair_min", "gait_clock", "peak_target") if t in txt]
        record("no_joy_terms_in_velocity_cfg", not leaks,
               "clean" if not leaks else f"found {leaks}")
        mdp_live = live.parent / "mdp.py"
        mdp_up = up.parent / "mdp.py"
        n = 0
        if mdp_up.exists() and mdp_live.exists():
            import difflib
            up_l = mdp_up.read_text(encoding="utf-8", errors="replace").splitlines()
            li_l = mdp_live.read_text(encoding="utf-8", errors="replace").splitlines()
            dif = [l for l in difflib.unified_diff(up_l, li_l, n=0, lineterm="")
                   if l[:1] in "+-" and l[:3] not in ("+++", "---")]
            n = len(dif)
            # Every added line should be inside a joy_* function or a guard block.
            suspicious = [l for l in dif if l.startswith("+") and "joy" not in l.lower()
                          and "MICRODUCK_WARM_START" not in l and "nan" not in l.lower()]
            info["mdp_added_lines"] = n
            record("mdp_patch_contained", len(suspicious) == 0,
                   f"{n} changed lines, {len(suspicious)} not obviously joy/NaN/warm-start",
                   blocking=False)
    except Exception as e:  # noqa: BLE001
        record("joy_patch_containment", None, f"cannot audit: {e}", blocking=False)

    # ---------------------------------------------------- G. walking robot model
    head("G. robot model for the walking task")
    try:
        import mjlab_microduck.robot.microduck_constants as C
        walk_xml = next((getattr(C, k) for k in dir(C) if "WALK_XML" in k), None)
        info["walk_xml"] = None if walk_xml is None else str(walk_xml)
        ok = walk_xml is not None and "robot_walk" in str(walk_xml)
        record("robot_walk_model", ok, str(info["walk_xml"]))
        exists = Path(str(walk_xml)).exists() if walk_xml is not None else False
        record("walk_xml_exists", exists if walk_xml is not None else None,
               str(walk_xml), blocking=False)
    except Exception as e:  # noqa: BLE001
        record("robot_walk_model", None, f"cannot read constants: {e}", blocking=False)

    # ------------------------------------------------------ H. env-var switches
    head("H. behaviour switches")
    switches = {
        "MICRODUCK_WARM_START": os.environ.get("MICRODUCK_WARM_START", "0"),
        "MICRODUCK_JOY_PAIR_MIN": os.environ.get("MICRODUCK_JOY_PAIR_MIN", "0"),
        "MICRODUCK_JOY_PHASE_RSI": os.environ.get("MICRODUCK_JOY_PHASE_RSI", "0"),
        "MICRODUCK_JOY_SYMMETRY": os.environ.get("MICRODUCK_JOY_SYMMETRY", "0"),
    }
    info["switches"] = switches
    ws = str(switches["MICRODUCK_WARM_START"]).strip() not in ("", "0")
    record("warm_start_off", not ws,
           "off (from-scratch run)" if not ws else f"ON={switches['MICRODUCK_WARM_START']} -- will restart curricula")

    # --------------------------------------------------------- I. compute budget
    head("I. compute budget")
    steps = None
    try:
        nsp = info.get("rl_cfg", {}).get("num_steps_per_env", 24)
        steps = a.envs * a.iters * nsp
        info["env_steps"] = steps
        spi = SEC_PER_ITER.get(a.envs)
        hours = (spi * a.iters / 3600) if spi else None
        info["est_hours"] = hours
        ref = {"Duckverse joy (fine-tune)": 15e6, "our joy runs": 29.5e6,
               "upstream gait playbook (low)": 393e6, "RL_duck velocity (walked)": 590e6}
        detail = f"{steps/1e6:.1f} M env-steps"
        if hours:
            detail += f", ~{hours:.1f} h at {spi}s/iter"
        record("budget", spi is not None,
               detail + ("" if spi else " (no measured s/iter for this env count)"),
               blocking=False)
        info["reference_steps"] = {k: v for k, v in ref.items()}
        if spi is None:
            record("envs_tuned", False,
                   f"{a.envs} not measured; 4096 is the 8 GB sweet spot", blocking=True)
        else:
            record("envs_tuned", True, f"{a.envs} envs has a measured s/iter")
    except Exception as e:  # noqa: BLE001
        record("budget", None, f"cannot estimate: {e}", blocking=False)

    # ------------------------------------------------------------ J. resources
    head("J. machine resources")
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15)
        gpu = out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else None
        info["gpu"] = gpu
        if gpu:
            parts = [p.strip() for p in gpu.split(",")]
            used = int(parts[2].split()[0])
            total = int(parts[1].split()[0])
            free = total - used
            record("gpu_free", free > 3000, f"{gpu} (free {free} MiB)")
        else:
            record("gpu_free", None, "nvidia-smi gave no output", blocking=False)
    except FileNotFoundError:
        record("gpu_free", None, "nvidia-smi not found", blocking=False)
    except Exception as e:  # noqa: BLE001
        record("gpu_free", None, f"{type(e).__name__}: {e}", blocking=False)

    du = shutil.disk_usage(ROOT)
    free_gb = du.free / 2**30
    info["disk_free_gb"] = round(free_gb, 1)
    record("disk_free", free_gb > 5, f"{free_gb:.1f} GB free on the project drive")

    return finish(a, info)


def finish(a, info: dict) -> int:
    blocking = [r for r in results if r["blocking"] and r["ok"] is False]
    print("\n" + "=" * 68)
    if blocking:
        print(f"NOT READY -- {len(blocking)} blocking check(s) failed")
        for r in blocking:
            print(f"  - {r['check']}: {r['detail']}")
    else:
        print("READY -- all blocking checks passed")
    print("=" * 68)

    info["results"] = results
    info["ready"] = not blocking
    if a.json:
        p = Path(a.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {p}")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
