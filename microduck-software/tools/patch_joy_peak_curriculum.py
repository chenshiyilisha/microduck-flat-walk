"""Curriculum on `joy_foot_peak`'s target height: 7 mm -> 20 mm over 320 iterations.

Why a curriculum, when five reward shapes already failed
-------------------------------------------------------
`tools/probe_policy_bias_lift.py` measured what the trained policy does when its
left-knee command is nudged (closed loop, so the policy keeps trying to balance):

    knee bias   foot peak   upright min   fell
     0.00        5.94 mm      0.996        no
     0.10        6.11 mm      0.994        no
     0.20       38.85 mm      0.350       YES   <- 38.85 is the tumble, not a lift

Two facts come out of that table, and together they explain every failed run:

1. A 0.10 rad knee bias moves the foot **0.17 mm**, not the ~2.4 mm the FK sweep
   predicts. The policy is *actively cancelling* the lift -- it has learned that
   the foot must stay low and it corrects any perturbation back.
2. A 0.20 rad bias tips the trunk to 69 deg and terminates the episode. The
   balance margin is essentially zero at the current stance.

So the blocker is neither the plant nor the reward *shape*: it is a local optimum.
"Stand still" is the only zero-risk policy reachable by exploration, because a
24 mm lift needs a coordinated multi-joint excursion (the FK sweep says 0.28 rad
on the best joint set) that random action noise of `init_std = 0.12` cannot
sample, and any partial attempt unbalances the trunk before it pays.

Five reward shapes were tried at a fixed 20-24 mm target: pointwise Gaussian at
9 mm, at 18 mm, running-peak Gaussian at 24 mm, the official trio, and
running-peak linear at 20 mm. All five converged to 5.3-5.7 mm, because all five
asked for the same unreachable step. Changing the *shape* of an unreachable
target does not make it reachable.

What this patch changes
-----------------------
Only the target height, and only as a function of training progress:

    iteration    0    80    160   240   320+
    target      7mm  9.5mm  12.5mm 16mm  20mm

7 mm is deliberately just above the 5.94 mm the policy already reaches, so the
first stage is *almost* satisfied by standing -- the gradient exists from step
zero and it points at a modest, balanceable excursion. Each later stage is a
~27% increase on a policy that has already learned to balance the previous one.
20 mm is the upstream `target_height = 0.02` (and the audit's PASS values are
18.46 / 20.03 mm), so the endpoint matches the real acceptance criterion.

The linear payoff is kept: `clamp(peak / target, 0, 1)` with a constant
1/target gradient. With a *moving* target the gradient is 1/7mm = 0.143 /mm early
on, which is 2.9x the sigma=18 Gaussian's 0.0402 /mm, and it never decays.

Implementation notes
--------------------
- `common_step_counter` is env steps, and `num_steps_per_env = 24` (the same
  convention as the existing `action_rate_weight` schedule: `150*24` = iteration
  150). Stages are written as `80*24` etc. for that reason.
- `target_height=None` now means "use the curriculum". `eval_joy_in_sim.py`
  passes `target_height=0.020` explicitly so the acceptance number stays
  comparable across runs instead of silently reporting against stage 0.
- The active target is logged as `Metrics/joy_peak_target_m` so a run can be read
  against the stage it was actually in.

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/patch_joy_peak_curriculum.py
    .venv-mjlab/Scripts/python.exe tools/patch_joy_peak_curriculum.py --revert
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MDP = ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/mdp.py"
EVAL = ROOT / "tools/eval_joy_in_sim.py"

STAGES_NOTE = '''# --- joy_foot_peak target curriculum -----------------------------------------
# Grows the graded lift from 7 mm to the upstream 20 mm. 24 = num_steps_per_env,
# so 80*24 is iteration 80. See tools/patch_joy_peak_curriculum.py for why a
# fixed 20 mm target cannot be learned by exploration from a standing start.
JOY_PEAK_TARGET_STAGES = (
    (0, 0.007),
    (80 * 24, 0.0095),
    (160 * 24, 0.0125),
    (240 * 24, 0.016),
    (320 * 24, 0.020),
)


def joy_peak_target_height(env, stages=JOY_PEAK_TARGET_STAGES):
    """Latest stage whose step threshold has elapsed."""
    target = stages[0][1]
    for step, value in stages:
        if env.common_step_counter > step:
            target = value
    return target


class joy_foot_peak:'''

OLD_SIG = ('def __call__(self, env, asset_cfg, target_height=.020, sigma=.009,\n'
           '                 frequency=1.15, stance_height=.0005, ramp_s=.8):\n'
           '        asset = env.scene[asset_cfg.name]')
NEW_SIG = ('def __call__(self, env, asset_cfg, target_height=None, sigma=.009,\n'
           '                 frequency=1.15, stance_height=.0005, ramp_s=.8):\n'
           '        # None = follow the curriculum. An explicit value pins the target,\n'
           '        # which is what the acceptance harness does (20 mm, always).\n'
           '        if target_height is None:\n'
           '            target_height = joy_peak_target_height(env)\n'
           '        asset = env.scene[asset_cfg.name]')

OLD_LOG = ('            env.extras["log"]["Metrics/joy_peak_height_max"] = self.peak.max()\n')
NEW_LOG = ('            env.extras["log"]["Metrics/joy_peak_height_max"] = self.peak.max()\n'
           '            env.extras["log"]["Metrics/joy_peak_target_m"] = torch.as_tensor(\n'
           '                target_height, device=self.peak.device, dtype=self.peak.dtype)\n')

# eval must pin the target, or it reports against whatever stage 0 happens to be
OLD_EVAL = '                joy_peak_hist.append(peak_term(u, foot_cfg).clone())'
NEW_EVAL = ('                # Pin at 20 mm: the gate is a fixed contract, so the\n'
            '                # reported number must not drift with the curriculum stage.\n'
            '                joy_peak_hist.append(\n'
            '                    peak_term(u, foot_cfg, target_height=0.020).clone()\n'
            '                )')


def swap(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            print(f"  [skip] {label}: already patched")
            return text
        raise SystemExit(f"anchor missing in {label}")
    if text.count(old) != 1:
        raise SystemExit(f"anchor not unique in {label} ({text.count(old)}x)")
    print(f"  [ok]   {label}")
    return text.replace(old, new)


def main() -> int:
    revert = "--revert" in sys.argv
    mdp_txt = MDP.read_text(encoding="utf-8")
    ev_txt = EVAL.read_text(encoding="utf-8")

    # 1. insert the stage table + helper right above `class joy_foot_peak:`
    if revert:
        if "JOY_PEAK_TARGET_STAGES" in mdp_txt:
            start = mdp_txt.index("# --- joy_foot_peak target curriculum")
            end = mdp_txt.index("class joy_foot_peak:")
            mdp_txt = mdp_txt[:start] + mdp_txt[end:]
            print("  [ok]   removed stage table")
        body_a, body_b = NEW_SIG, OLD_SIG
        log_a, log_b = NEW_LOG, OLD_LOG
        ev_a, ev_b = NEW_EVAL, OLD_EVAL
        mdp_txt = swap(mdp_txt, body_a, body_b, "joy_foot_peak signature")
        mdp_txt = swap(mdp_txt, log_a, log_b, "target logging")
        ev_txt = swap(ev_txt, ev_a, ev_b, "eval pinned target")
    else:
        if "class joy_foot_peak:" not in mdp_txt:
            raise SystemExit("joy_foot_peak not found -- apply patch_joy_peak_linear.py first")
        if "JOY_PEAK_TARGET_STAGES" in mdp_txt:
            print("  [skip] stage table: already present")
        else:
            # only touch the FIRST occurrence, which is the def line
            mdp_txt = mdp_txt.replace("class joy_foot_peak:", STAGES_NOTE, 1)
            print("  [ok]   inserted stage table + helper")
        mdp_txt = swap(mdp_txt, OLD_SIG, NEW_SIG, "joy_foot_peak signature")
        mdp_txt = swap(mdp_txt, OLD_LOG, NEW_LOG, "target logging")
        ev_txt = swap(ev_txt, OLD_EVAL, NEW_EVAL, "eval pinned target")

    MDP.write_text(mdp_txt, encoding="utf-8")
    EVAL.write_text(ev_txt, encoding="utf-8")

    import py_compile
    for p in (MDP, EVAL):
        py_compile.compile(str(p), doraise=True)
        print(f"  [ok]   compiles: {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
