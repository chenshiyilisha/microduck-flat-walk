"""Widen `joy_foot_rhythm`'s height tolerance from 9 mm to 18 mm.

Why this patch exists -- after three rejected attempts
-----------------------------------------------------
Four runs stall at the same place (feet_peak 5.3-5.7 mm against a 24 mm target)
and the plant, sigma, entropy and action_rate have each been ruled out by
experiment. This tool is the fifth attempt, and the first three are recorded
here because two of them *made things worse* and the reason matters:

1. **Peak-graded criterion** (run `joy_smooth_2048x600_peak`): grade the running
   peak of each swing instead of the instantaneous height. Result: `joy_feet`
   was exactly **0.0000** from iteration ~30 to 200 and the run was stopped.
   Cause is arithmetic, not tuning: it kept the *product over two feet* of a
   Gaussian centred 18 mm away from where the policy is, so the term is ~0
   unless a foot is already near target, and there is no gradient to get there.

2. **Isaac Lab's official additive trio** (run `joy_smooth_2048x600_trio`:
   `feet_air_time` +3.0 / `feet_clearance` -2.0 / `foot_swing_height` -0.36):
   `joy_air_time` was **0.0000 at iteration 57** and the landing peak was
   0.1 mm -- the robot simply stood. Official's design relies on a *velocity
   command* to force stepping; the joy task zeroes the command (it is stepping
   in place), so nothing paid for moving. `joy_foot_rhythm` is not just a
   height metric here, it is the only thing that makes the robot step at all.
   Removing it is not a reward-shape change, it deletes the task.

3. This one: keep `joy_foot_rhythm` exactly as the task's forcing function and
   change only its **tolerance**, because the tolerance is what decides whether
   a policy that is 18 mm away can feel a gradient.

The numbers behind it (`exp(-((h-24)/sigma)^2)`):

        h (mm)      sigma=9      sigma=12     sigma=18
           0        0.0008       0.0183       0.1690
           3        0.0043       0.0468       0.2564
           6        0.0183       0.1054       0.3679
          12        0.1690       0.3679       0.6412
          18        0.6412       0.7788       0.8948
          24        1.0000       1.0000       1.0000

        gradient d/dh at the measured h = 5.7 mm:
          sigma=9   ->  value 0.0160,  gradient 0.00723 /mm
          sigma=12  ->  value 0.0977,  gradient 0.02484 /mm
          sigma=18  ->  value 0.3557,  gradient 0.04018 /mm

At sigma=9 the policy sits at value 0.016 with a gradient of 0.007/mm -- it is
in the flat tail of the Gaussian, 18 mm from the peak, where a 1 mm improvement
changes the reward by 0.7%. That is why changing the exploration sigma (0.4 vs
0.12) and the action_rate weight did nothing: those change *where the policy
samples*, not whether there is a gradient there. At sigma=18 the same point has
5.6x the gradient and the value is 0.36 instead of 0.016.

The trade-off is real and is accepted deliberately: a wider tolerance also
shrinks the *contrast* between standing (0.356) and perfect (1.000) from 62x to
2.8x. So this run tests a specific claim -- that the blocker is gradient
availability near 6 mm, not the height of the target -- and if feet_peak moves,
a second run can narrow sigma again with the policy no longer in the tail.

Why sigma=18 and not 12: 18 mm is where the *command itself* already fails. The
commanded knee excursion for a 24 mm lift is 1.238 rad, which at 1.15 Hz needs
~8.9 rad/s, but the deployment conditioner `joy_max_step=0.08 rad @ 50 Hz` caps
every joint at 4.0 rad/s. A knee-only lift is therefore capped near 0.87 rad of
travel, i.e. ~8.8 mm of height. A tolerance of 18 mm keeps a usable gradient
across that whole reachable band instead of only at its top edge.

Idempotent: re-running prints "already applied" and exits 0.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / ".upstream/microduck_rl-develop/src/mjlab_microduck/tasks"
SITE = ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks"
MDP_FILES = [SRC / "mdp.py", SITE / "mdp.py"]
CFG_FILES = [SRC / "microduck_joy_env_cfg.py", SITE / "microduck_joy_env_cfg.py"]

# --- mdp.py: make the tolerance a parameter instead of a hardcoded .009 ----
MDP_OLD = """def joy_foot_rhythm(env, asset_cfg=SceneEntityCfg('robot',site_names=['left_foot','right_foot'])):
    asset=env.scene[asset_cfg.name];p=joy_phase(env);e=torch.clamp(env.episode_length_buf*env.step_dt/.8,0.,1.)
    target=.0005+.024*torch.stack((torch.relu(torch.sin(p))**2,torch.relu(-torch.sin(p))**2),dim=-1)*e[:,None]
    actual=asset.data.site_pos_w[:,asset_cfg.site_ids,2]-env.scene.terrain.env_origins[:,None,2]
    return torch.exp(-((actual-target)/.009)**2).prod(-1)"""

MDP_NEW = """def joy_foot_rhythm(env, asset_cfg=SceneEntityCfg('robot',site_names=['left_foot','right_foot']), sigma=.009):
    # `sigma` is the height tolerance in metres. Default .009 keeps every existing
    # caller (including tools/eval_joy_in_sim.py's comparable metric) unchanged;
    # training passes sigma=.018 -- see tools/patch_joy_foot_sigma.py.
    asset=env.scene[asset_cfg.name];p=joy_phase(env);e=torch.clamp(env.episode_length_buf*env.step_dt/.8,0.,1.)
    target=.0005+.024*torch.stack((torch.relu(torch.sin(p))**2,torch.relu(-torch.sin(p))**2),dim=-1)*e[:,None]
    actual=asset.data.site_pos_w[:,asset_cfg.site_ids,2]-env.scene.terrain.env_origins[:,None,2]
    return torch.exp(-((actual-target)/sigma)**2).prod(-1)"""

# --- joy cfg: restore joy_feet (rhythm) with the wide tolerance -----------
CFG_NEW = """    # Forcing function + height metric in one term -- see tools/patch_joy_foot_sigma.py.
    # sigma .009 -> .018: at the measured h=5.7mm the old tolerance put the policy in
    # the flat tail (value .016, gradient .007/mm). .018 gives 5.6x the gradient.
    cfg.rewards['joy_feet']=RewardTermCfg(func=mdp.joy_foot_rhythm,weight=12.,params={"asset_cfg":SceneEntityCfg("robot",site_names=["left_foot","right_foot"]),"sigma":.018})
"""

# Anchors, in order of what the file might currently contain.
CFG_BLOCK_START = "    # Foot reward: Isaac Lab's official additive trio"
CFG_PEAK_LINE = "    cfg.rewards['joy_feet']=RewardTermCfg(func=mdp.joy_foot_peak,weight=12."
CFG_RHYTHM_LINE = "    cfg.rewards['joy_feet']=RewardTermCfg(func=mdp.joy_foot_rhythm,weight=12."


def patch_mdp(path: pathlib.Path) -> str:
    if not path.exists():
        return f"  ! missing {path}"
    text = path.read_text(encoding="utf-8")
    if "sigma=.009):" in text and "patch_joy_foot_sigma" in text:
        return f"  = {path.name}: already applied"
    if MDP_OLD not in text:
        return f"  !! mdp anchor not found in {path}"
    path.write_text(text.replace(MDP_OLD, MDP_NEW, 1), encoding="utf-8")
    return f"  + {path.name}: joy_foot_rhythm gained a sigma parameter (default .009)"


def patch_cfg(path: pathlib.Path) -> str:
    if not path.exists():
        return f"  ! missing {path}"
    text = path.read_text(encoding="utf-8")
    if '"sigma":.018' in text:
        return f"  = {path.name}: already applied"

    # Drop whichever foot-reward block is currently there, then insert ours in its
    # place. All three historic shapes are handled so the tool works from a clean
    # tree as well as from either intermediate state.
    if CFG_BLOCK_START in text:
        start = text.index(CFG_BLOCK_START)
        end = text.index("\n", text.index("'target_height':.024})", start)) + 1
        text = text[:start] + CFG_NEW + text[end:]
    else:
        start = -1
        for anchor in (CFG_PEAK_LINE, CFG_RHYTHM_LINE):
            if anchor in text:
                start = text.index(anchor)
                # also swallow the two/three comment lines that introduced it
                head = text[:start]
                for prefix in (
                    "    # Peak-graded foot lift -- see tools/patch_joy_foot_peak.py.\n"
                    "    # Same weight/target/tolerance/1.15 Hz clock as before; only the graded quantity\n"
                    "    # changed, from instantaneous height to the running peak of each swing window.\n",
                    "    # Forcing function + height metric in one term -- see tools/patch_joy_foot_sigma.py.\n"
                    "    # sigma .009 -> .018: at the measured h=5.7mm the old tolerance put the policy in\n"
                    "    # the flat tail (value .016, gradient .007/mm). .018 gives 5.6x the gradient.\n",
                ):
                    if head.endswith(prefix):
                        head = head[: -len(prefix)]
                end = text.index("\n", start) + 1
                text = head + CFG_NEW + text[end:]
                break
        if start < 0:
            return f"  !! cfg anchor not found in {path}"
    path.write_text(text, encoding="utf-8")
    return f"  + {path.name}: joy_feet restored with sigma=.018"


def main() -> int:
    results = [patch_mdp(p) for p in MDP_FILES] + [patch_cfg(p) for p in CFG_FILES]
    print("\n".join(results))
    if any(r.startswith("  !") or r.startswith("  !!") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
