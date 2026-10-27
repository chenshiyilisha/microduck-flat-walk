# SPDX-License-Identifier: Apache-2.0
"""Stop the PD variant from overriding the joy action-rate schedule.

Why this file exists
--------------------
The run `joy_smooth_2048x600_1024_0757` learned the *rhythm* of stepping but only
~15 % of the commanded amplitude (foot lifts 6 mm of 24 mm, contact breaks 14x/8 s
against 18 expected). The question was which term was taking the missing reward.

`Episode_Reward/action_rate_l2` was the largest single penalty on the reward panel
(-1.55/step, against `joy_feet` +5.64). Regressing it on the policy's own action
noise over iters 210-599 gives

    action_rate_l2 = -25.0 * sigma^2        R^2 = 0.98

and the closed form for the squared difference of two i.i.d. N(0, sigma^2)
samples over 14 action dims is 2 * 14 * sigma^2 = 28 sigma^2. So the term is 89 %
of the *exploration-noise floor*: it carries essentially no information about
whether the learned motion is smooth, and its only gradient is "make sigma
smaller". sigma did fall 0.45 -> 0.25 over the run, i.e. exactly that.

Upstream has two joy schedules and they disagree:

    BAM  (make_microduck_joy_env_cfg)        -0.05 -> -0.15 @150 -> -0.30 @300
    PD   (pd_actuators=True override)        -0.10 -> -0.50 @100 -> -1.00 @200

The PD override is 3.3x tighter at the end and carries no comment saying why. It
was the only reward weight where the deployable plant was made *strictly harder*
than the plant upstream actually trained joy with. This patch deletes it, so PD
inherits the joy values.

This is deliberately a **single-variable** change: same task, same plant, same
600-iteration budget, same seed, only the action-rate schedule differs. If
`feet_peak` rises, the schedule was the blocker; if it does not, the amplitude is
limited by something else and the next change should be to the gait reward.

The fix must survive `tools/apply_joy_patch.py`, which re-copies the joy cfg from
the upstream tree into site-packages. So both copies are patched and the function
is idempotent.

Usage
-----
  .venv-mjlab/Scripts/python.exe tools/patch_joy_action_rate.py
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TREE = ROOT / ".upstream" / "microduck_rl-develop" / "src" / "mjlab_microduck" / "tasks"
SITE = ROOT / ".venv-mjlab" / "Lib" / "site-packages" / "mjlab_microduck" / "tasks"
NAME = "microduck_joy_env_cfg.py"

# The two lines that make the PD plant stricter than upstream's joy recipe.
OLD = '''        cfg.rewards["action_rate_l2"].weight=-.1
        cfg.curriculum["action_rate_weight"].params["weight_stages"]=[{"step":0,"weight":-.1},{"step":100*24,"weight":-.5},{"step":200*24,"weight":-1.}]'''

NEW = '''        # No action_rate override on purpose (tools/patch_joy_action_rate.py).
        # The inherited joy schedule is -0.05 -> -0.15 @150 -> -0.30 @300. The old
        # PD-only -0.1/-0.5@100/-1.0@200 was 3.3x tighter at the end and had no
        # comment justifying it. Measured on run joy_smooth_2048x600_1024_0757,
        # action_rate_l2 at weight -1.0 equals -25*sigma^2 with R^2=0.98 -- i.e.
        # 89% of the pure exploration-noise floor (2*14*sigma^2) -- so it rewarded
        # shrinking sigma rather than smoothing the gait, and sigma fell 0.45->0.25
        # while the foot amplitude stalled at 15% of command.'''

MARKER = "No action_rate override on purpose"


def patch_file(path: pathlib.Path) -> str:
    if not path.is_file():
        return f"skip (missing): {path}"
    src = path.read_text(encoding="utf-8")
    if MARKER in src:
        return f"already patched: {path}"
    if OLD not in src:
        raise SystemExit(
            f"anchor not found in {path}\n"
            "Expected the PD action_rate override verbatim. Refusing to guess --\n"
            "read the file and update OLD in this script if upstream changed it."
        )
    path.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
    return f"patched: {path}"


def main() -> None:
    targets = [TREE / NAME, SITE / NAME]
    for t in targets:
        print("  " + patch_file(t))
    if not any(p.is_file() for p in targets):
        sys.exit("no joy cfg found -- run tools/apply_joy_patch.py first")


if __name__ == "__main__":
    main()
