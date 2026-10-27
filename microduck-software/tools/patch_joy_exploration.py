"""Fix the joy task's exploration noise: smaller start, log parameterisation, no entropy push.

Why this patch exists
---------------------
Run `joy_smooth_2048x600_1024_0757` failed the stepping gates, and the measured
mechanism was: the policy's action noise sigma grew 0.40 -> 0.59 before falling
back, and at sigma ~0.52 the *expected* value of `joy_feet` above a standing-still
policy was only 0.11 of 12 points (tools/probe_noise_vs_reward.py, 512 samples).
In other words the foot-lift reward had no usable gradient left -- the policy was
sampling actions so far from the mean that a stepping mean and a standing mean
produced the same reward in expectation.

Three separate things feed that, and each needs its own fix:

1. `entropy_coef=0.01` (inherited from the velocity template) is a *constant*
   push to raise sigma that has nothing to do with the reward. rsl_rl's
   `GaussianDistribution.entropy` is `Normal.entropy().sum(-1)`, i.e.
   `14*0.5*ln(2*pi*e) + sum(ln sigma_i)`, so d(entropy)/d(ln sigma_i) == +1 per
   dimension regardless of what the robot is doing. NVIDIA's Isaac WBC-AGILE
   training notes describe exactly the resulting failure ("policy noise
   explosion"): when the task gradient is noisy the small-but-consistent entropy
   gradient wins and the policy gets noisier and noisier. Continuous-control
   practice is 0.0-0.01 (mujoco_playground quadruped uses 0.005, several IsaacLab
   configs use 0). We go to 0.002 -- small, not zero, so the policy cannot
   collapse to a deterministic mode in the first few iterations.

2. `init_std=0.4` is simply too wide for this reward's tolerance. `joy_foot_rhythm`
   is `exp(-((z - z_target)/9mm)^2)`: a 9 mm tolerance on foot height, with
   measured sensitivity ~54.5 mm of foot height per rad of joint action. So one
   sigma of action noise buys ~0.4*54.5 = 22 mm of foot-height jitter, i.e. 2.4x
   the tolerance band -- from the very first sample. 9mm/54.5mm/rad = 0.165 rad is
   the widest sigma that stays inside the band; we take 0.12 (conservative end).
   NOTE: this 0.12 is derived from our own measurement, not copied from a paper.
   Cross-check from tools/probe_noise_vs_reward.py: at sigma=0.10 the expected
   gap between a stepping and a standing policy is still 3.62/12 points, so
   exploration remains adequate.

3. `std_type="scalar"` makes sigma a raw `nn.Parameter(init_std * ones(14))` with
   **no clamp anywhere** in rsl_rl's `GaussianDistribution` -- it is fed straight
   into `Normal(mean, std)`. With entropy_coef dropped to 0.002, the only
   remaining force on sigma is the log_prob term, which pushes it *down* every
   step; nothing stops it crossing zero, and a negative std raises
   `RuntimeError: normal expects all elements of std >= 0.0`. Switching to
   `std_type="log"` (std = exp(log_std)) makes it positive by construction and is
   the standard parameterisation (SB3 / CleanRL / IsaacLab all use log_std).
   rsl_rl already implements the log branch, so this is a config change, not a
   source hack. ONNX export is unaffected: the exported graph uses
   `deterministic_output()` == the mean, which never touches sigma.

All three are applied to the *source tree* and to *site-packages*: the package is
installed as a copy, and tools/apply_joy_patch.py re-syncs source -> site-packages,
so touching only site-packages would be silently reverted on the next apply.

Idempotent: each replacement is a whole-line swap with an applied-marker; running
it again prints "already applied" and exits 0.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGETS = [
    ROOT / ".upstream/microduck_rl-develop/src/mjlab_microduck/tasks/microduck_joy_env_cfg.py",
    ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/microduck_joy_env_cfg.py",
]

OLD = "MicroduckJoyRlCfg.actor.distribution_cfg['init_std']=.4"
NEW = """# Exploration noise -- see tools/patch_joy_exploration.py for the evidence.
# sigma starts at 0.12 rad, not 0.4: joy_foot_rhythm tolerates 9 mm of foot
# height (exp(-((z-zt)/9mm)^2)) and the measured sensitivity is 54.5 mm/rad,
# so 0.4 rad of action noise = 22 mm of jitter = 2.4x the tolerance band.
# std_type 'log' keeps sigma positive by construction; rsl_rl's 'scalar' mode
# is an unclamped raw parameter and would cross zero once entropy_coef is small.
MicroduckJoyRlCfg.actor.distribution_cfg['init_std']=.12
MicroduckJoyRlCfg.actor.distribution_cfg['std_type']='log'
# entropy_coef 0.01 -> 0.002. rsl_rl's Gaussian entropy = 14*0.5*ln(2*pi*e) +
# sum(ln sigma), so its gradient on ln(sigma) is +1/dim independent of the
# reward -- a constant push to explore wider. Measured on the 0757 run: sigma
# rose 0.40 -> 0.59 and joy_feet's stepping-vs-standing gap shrank to
# 0.11/12, i.e. the task gradient vanished under the entropy gradient.
MicroduckJoyRlCfg.algorithm.entropy_coef=.002"""


def patch(path: pathlib.Path) -> str:
    if not path.exists():
        return f"  ! missing {path}"
    text = path.read_text(encoding="utf-8")
    if "init_std']=.12" in text:
        return f"  = {path.name} @ {path.parent.parent.parent.name}: already applied"
    if OLD not in text:
        return f"  !! anchor not found in {path}"
    path.write_text(text.replace(OLD, NEW), encoding="utf-8")
    return f"  + {path}: patched"


def main() -> int:
    results = [patch(p) for p in TARGETS]
    print("\n".join(results))
    if any(r.startswith("  !") or r.startswith("  !!") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
