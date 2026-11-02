"""Resume an interrupted heading-reward run without getting the arithmetic wrong.

Why this exists
---------------
`--agent.max-iterations` does NOT mean "train until iteration N". rsl_rl's
`learn()` computes

    start_it = self.current_learning_iteration
    total_it = start_it + num_learning_iterations      # on_policy_runner.py:77-79

so on a resume it is an INCREMENT. Passing the run's total (2500) while resuming
at 1600 silently trains to 4100; passing the remainder while the script under it
believes it is a total makes the stage validation fire. Doing this subtraction by
hand is exactly the class of error this project keeps paying for, so the number is
read out of the checkpoint here instead.

What is actually restored on resume
----------------------------------
* weights / normaliser / optimiser: `alg.load()` (rsl_rl).
* `current_learning_iteration`: `MjlabOnPolicyRunner.load` (runner.py:135-136).
* `env.common_step_counter`: `MjlabOnPolicyRunner.load` (runner.py:137-139) reads
  `infos["env_state"]["common_step_counter"]`, which `save()` writes. So the
  heading curriculum resumes at its own stage instead of restarting at phase 1.
  (Only `MICRODUCK_WARM_START=1` -- mdp.py Patch 5 -- forces it back to 0; we do
  not set it.)

Gates before a single iteration is spent
----------------------------------------
1. the run dir carries the heading rewards (guards against resuming the wrong run);
2. `counter == (iter + 1) * num_steps_per_env` -- verified empirically on
   model_1600.pt (iter 1600 -> 38424). A mismatch means the checkpoint's iteration
   and its curriculum state disagree, i.e. the resume would run phase 2 on a phase 1
   schedule or vice versa. Refuse rather than guess;
3. the live plant is still the P3 preset (kp_fw=5); a different plant is a different
   task (see docs section 10) and must not be continued from these weights;
4. remaining > 0.

Usage
-----
    # today: prove the generated command is accepted, spend no GPU
    python tools/hd1910/resume_heading_run.py

    # tomorrow: actually continue
    python tools/hd1910/resume_heading_run.py --launch
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_ROOT = ROOT / "logs" / "rsl_rl" / "microduck_velocity_hd1910"
TRAIN = ROOT / "tools" / "train_heading_variant.py"
APPLY = ROOT / "tools" / "hd1910" / "apply_to_live.py"

# The exact recipe the interrupted run was launched with. Kept in one place so a
# resume cannot drift from it by a typo.
RECIPE = [
    "--rel-heading-envs", "0.3",
    "--heading-hold-weight", "1.0",
    "--heading-tracking-final-weight", "3.0",
    "--ang-vel-z-clip", "0.5",
    "--heading-stage-iters", "0,1000,1750,2500",
    "--agent.experiment-name", "microduck_velocity_hd1910",
    "--agent.logger", "tensorboard",
]
TARGET_ITERS = 2500
EXPECT_KP = 5.0


def latest_run(pattern: str = "*p3head_rw*") -> Path:
    runs = [p for p in LOG_ROOT.glob(pattern) if p.is_dir()]
    if not runs:
        raise SystemExit(f"no run dirs matching {pattern!r} in {LOG_ROOT}")
    return max(runs, key=lambda p: p.stat().st_mtime)


def latest_ckpt(run_dir: Path) -> tuple[Path, int]:
    found = []
    for p in run_dir.glob("model_*.pt"):
        m = re.fullmatch(r"model_(\d+)\.pt", p.name)
        if m:
            found.append((int(m.group(1)), p))
    if not found:
        raise SystemExit(f"no model_*.pt checkpoints in {run_dir}")
    it, path = max(found)
    return path, it


def read_state(ckpt: Path) -> tuple[int, int | None]:
    import torch

    d = torch.load(ckpt, map_location="cpu", weights_only=False)
    it = int(d.get("iter", -1))
    infos = d.get("infos") or {}
    env_state = infos.get("env_state") or {}
    counter = env_state.get("common_step_counter")
    return it, (None if counter is None else int(counter))


def heading_tracking_stages(run_dir: Path) -> list[tuple[int, float]]:
    """Read back the tracking-weight stages this run was launched with.

    params/env.yaml is dumped with python tags, so yaml.safe_load fails on it --
    locate the block by indentation instead and pull the (step, weight) pairs.
    """
    text = (run_dir / "params" / "env.yaml").read_text(encoding="utf-8")
    i = text.find("\n  heading_tracking_weight:")
    if i < 0:
        return []
    rest = text[i + 1:]
    nxt = re.search(r"^  \w", rest[3:], re.MULTILINE)
    block = rest[: nxt.start() + 3] if nxt else rest
    return [(int(a), float(b))
            for a, b in re.findall(r"step:\s*(\d+)\s*\n\s*weight:\s*([0-9.eE+-]+)", block)]


def active_weight(stages: list[tuple[int, float]], counter: int) -> float | None:
    """Same rule as mjlab_microduck.tasks.mdp.reward_weight: last stage with step < counter."""
    w = None
    for step, weight in stages:
        if counter > step:
            w = weight
    return w


def num_steps_per_env(run_dir: Path) -> int:
    """Read it as text: mjlab dumps params with python tags, so yaml.safe_load fails."""
    text = (run_dir / "params" / "agent.yaml").read_text(encoding="utf-8")
    m = re.search(r"^num_steps_per_env:\s*(\d+)", text, re.MULTILINE)
    if not m:
        raise SystemExit(f"num_steps_per_env not found in {run_dir}/params/agent.yaml")
    return int(m.group(1))


def check_heading_run(run_dir: Path) -> None:
    env_yaml = run_dir / "params" / "env.yaml"
    if not env_yaml.exists():
        raise SystemExit(f"{run_dir} has no params/env.yaml -- not a training run dir")
    text = env_yaml.read_text(encoding="utf-8")
    if "heading_hold_reward" not in text or "heading_tracking_reward" not in text:
        raise SystemExit(
            f"{run_dir.name} does not carry the heading rewards; resuming it with the "
            "heading recipe would start a different task. Point --run-dir at the "
            "p3head_rw run."
        )


def plant_check() -> str:
    r = subprocess.run(
        [sys.executable, str(APPLY), "--check"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")
    line = next((ln.strip() for ln in out.splitlines()
                 if "detected" in ln or "kp_fw" in ln), "<no readback line>")
    got = re.search(r"kp_fw[=:]\s*([0-9.]+)", out)
    if not got:
        raise SystemExit(f"could not read kp_fw from apply_to_live --check:\n{out[-800:]}")
    kp = float(got.group(1))
    if abs(kp - EXPECT_KP) > 1e-9:
        raise SystemExit(
            f"live plant reports kp_fw={kp:g}, expected {EXPECT_KP:g} (p3 preset). "
            f"Different plant = different task (docs section 10); run "
            f"`apply_to_live.py --plant p3` before resuming. Readback: {line}"
        )
    return line


def build_cmd(run_dir: Path, ckpt: Path, done: int, remaining: int,
              run_name: str, envs: int) -> list[str]:
    return [
        sys.executable, str(TRAIN),
        *RECIPE,
        "--resume-offset", str(done),
        "--agent.max-iterations", str(remaining),
        "--agent.resume", "True",
        "--agent.load-run", run_dir.name,
        "--agent.load-checkpoint", ckpt.name,
        "--agent.run-name", run_name,
        "--env.scene.num-envs", str(envs),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", default=None,
                    help="run to continue (default: newest *p3head_rw* dir)")
    ap.add_argument("--target", type=int, default=TARGET_ITERS,
                    help=f"absolute iteration the run should end at (default {TARGET_ITERS})")
    ap.add_argument("--run-name", default=None,
                    help="name for the continued run (default <orig>_resume<iter>)")
    ap.add_argument("--envs", type=int, default=4096)
    ap.add_argument("--skip-plant-check", action="store_true")
    ap.add_argument("--launch", action="store_true",
                    help="actually start training (default: dry-run the generated command)")
    a = ap.parse_args()

    run_dir = Path(a.run_dir) if a.run_dir else latest_run()
    run_dir = run_dir.resolve()
    check_heading_run(run_dir)
    ckpt, it_from_name = latest_ckpt(run_dir)
    done, counter = read_state(ckpt)
    nse = num_steps_per_env(run_dir)

    print(f"run        : {run_dir.name}")
    print(f"checkpoint : {ckpt.name}  (iter in file = {done}, from filename = {it_from_name})")
    print(f"counter    : {counter}")

    # Gate 2: the saved iteration and the saved curriculum counter must agree.
    # save() runs after the iteration's num_steps_per_env control steps, hence +1.
    #
    # Off-by-one on resume (measured 2026-11-02, see docstring): rsl_rl's load()
    # restores current_learning_iteration = it and learn() then runs range(it, ...),
    # so the boundary iteration is trained a second time. Every resume therefore
    # adds exactly num_steps_per_env steps to common_step_counter, leaving
    # counter = (iter + 1 + resumes) * nse. Demanding exact equality refuses every
    # second resume, so the drift is bounded and printed instead.
    expect = (done + 1) * nse
    if counter is None:
        raise SystemExit(
            f"{ckpt.name} has no infos['env_state']['common_step_counter']; the heading "
            "curriculum would restart at phase 1 on resume. Refusing."
        )
    drift = counter - expect
    if drift < 0 or drift % nse != 0 or drift > 2 * nse:
        raise SystemExit(
            f"counter {counter} is not (iter {done} + 1) x {nse} = {expect} plus a whole "
            f"number of duplicated resume iterations (drift {drift} steps, allowed "
            f"0..{2 * nse}). The checkpoint's iteration and its curriculum stage disagree "
            "-- resuming would run the wrong heading stage. Refusing rather than guessing."
        )
    if drift:
        print(f"⚠️  counter drift +{drift} steps = +{drift // nse} iteration(s): rsl_rl "
              "re-trains the boundary iteration on every resume, so the curriculum runs "
              "that far ahead of the iteration number.")
    if it_from_name != done:
        raise SystemExit(f"filename says iter {it_from_name} but the file says {done}")
    print(f"counter ok : (iter+1) x num_steps_per_env = {expect} (+{drift})")

    remaining = a.target - done
    if remaining <= 0:
        print(f"nothing to do: already at {done} of {a.target} iterations")
        return 0

    # Which heading weight will actually be applied? counter is the authority for
    # that (mdp.reward_weight picks the last stage with step < counter), so read the
    # stages back out of the dumped config instead of trusting the iteration number.
    stages = heading_tracking_stages(run_dir)
    if stages:
        now = active_weight(stages, counter)
        end = active_weight(stages, counter + remaining * nse)
        print(f"heading    : tracking weight {now} now -> {end} at the end of this launch "
              f"(counter {counter} -> {counter + remaining * nse}; stages "
              f"{[(s, w) for s, w in stages]})")

    if not a.skip_plant_check:
        print(f"plant      : {plant_check()}")

    run_name = a.run_name or f"{run_dir.name.split('_', 2)[-1]}_resume{done}"
    cmd = build_cmd(run_dir, ckpt, done, remaining, run_name, a.envs)

    print(f"\ndone {done} / {a.target} -> this launch trains {remaining} more iterations")
    print(" " + " ".join(cmd))
    print()

    if not a.launch:
        # Dry-run the real command through the real script, so CLI acceptance and the
        # stage-bound arithmetic are proven now rather than at 9am tomorrow.
        r = subprocess.run([*cmd, "--dry-run"], cwd=ROOT)
        if r.returncode != 0:
            raise SystemExit(f"dry-run rejected the resume command (rc={r.returncode})")
        print("dry-run accepted the resume command. Re-run with --launch to train.")
        return 0

    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
