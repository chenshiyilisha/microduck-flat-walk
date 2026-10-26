"""Grade *swing-window peak* against 20 mm with a **linear** payoff, not a Gaussian.

⚠️ CORRECTION (2026-10-24, see diagnosis doc §25)
------------------------------------------------
The table below was measured with **sigma = 18 mm**, which was itself the bug
(`patch_joy_foot_sigma.py`).  At the official sigma = 9 mm the same trajectory probe
(`tools/probe_official_rhythm.py`) gives

    scorer                       alternating   march   standing    hop
    official gaussian sigma=9        0.903     0.441     0.378    0.213
    this patch, linear 20mm          0.823     0.528     0.145    0.823

so the gaussian was farmable only because sigma had been doubled, and this patch
traded a smaller "standing is worth 38%" leak for a much bigger "a hop scores full
marks" leak.  The premise below about a product over two feet multiplying a score by
0.285 applies to `clamp(peak / 20mm)`, **not** to the official form: the official
stance-foot target is 0.5 mm (it is asked to stay DOWN), so its factor is ~0.9, not
0.285.  Reverting to `joy_foot_rhythm` (sigma=9) is the recommended baseline.

The bug this fixes
------------------
`joy_foot_rhythm` is

    target(t) = 0.5mm + 24mm * relu(sin p)^2      (per foot, alternating)
    r         = prod_over_feet exp(-((actual - target)/sigma)^2)

Because `target` itself swings, the **time average of the target is 6.5 mm**
(0.5 + 24 * 1/4), and a foot parked at the measured stance height of 5.7 mm sits
almost exactly on that average. Measured cycle-mean reward with sigma=18 mm:

    policy                                    reward(/1)   x12 (weight)
    rigid stance                                  0.6155       7.39
    press the foot down to ~1 mm                  0.9133      10.96
    correct low-frequency 60% lift                0.9331      11.20
    high-frequency 5-deg / 25 Hz jitter           0.6808       8.17
    perfect tracking                              1.0000      12.00

So the *entire* payoff for lifting is 12.00 - 7.39 = **4.6 points**, and pressing
the foot down (10.96) beats standing (7.39) while costing far less balance than
lifting. That is what the policy learned: `tgt_rng` on `left_knee` came out at
27.1 deg, and the foot peak at 5.33 mm -- *below* the 5.7 mm stance height. The
run with sigma=18 scored 8.5/12 on this term and still pressed.

(The earlier "sigma=18 gives 5.6x the gradient" reasoning was not wrong about the
gradient; it missed that widening sigma also raises the *standing* baseline from
0.383 to 0.616, so net incentive for lifting fell 7.40 -> 4.61 points. Confirmed
by measuring both sigmas, not by argument.)

Why not just reuse the upstream trio
------------------------------------
`foot_clearance` and `foot_swing_height` are gated on `command_threshold = 0.01`
(the commanded velocity). The joy task zeroes `lin_vel_x/y` and `ang_vel_z`, so
those terms are identically zero here -- that is why the earlier trio run logged
`joy_air_time = 0.0000`. The *idea* transfers; the *trigger* does not. This term
replaces the velocity trigger with the phase clock the joy task already has.

The fix
-------
Grade the running peak inside each foot's own swing window, and pay it out
linearly against the upstream target height of 20 mm (`target_height = 0.02` in
`microduck_velocity_env_cfg.py`, and the audit's own PASS values are 18.46 /
20.03 mm):

    r = clamp(peak_in_window / 0.020, 0, 1)     averaged over the swinging foot

Offline cycle means with that shape (TGT = 20 mm):

    policy                                    reward(/1)   x12 (weight)
    rigid stance                                  0.2850       3.42
    press the foot down to ~1 mm                  0.0500       0.60
    high-frequency 5-deg / 25 Hz jitter           0.3818       4.58
    correct low-frequency 60% lift                0.6664       8.00
    perfect tracking                              0.7885       9.46

Press-down collapses 10.96 -> 0.60 while correct lifting stays at 8.00. Standing
baseline drops from 7.39 to 3.42, so lifting is worth 8.00 - 3.42 = **4.6 points
of pure contrast** instead of 4.6 points of which 7.4 were free. The absolute
number is unchanged; what changed is that the only way to earn it is to move the
foot up.

Two implementation details that are easy to get wrong
-----------------------------------------------------
1. **No `prod(-1)`.** The feet alternate: at any instant one is swinging and the
   other is standing at 5.7 mm = 0.285 of target. A product therefore always
   multiplies the swinging foot's score by 0.285, compressing perfect-vs-stance
   from 0.715 to 0.204. Grade only the foot that is inside its swing window.
   Since `relu(sin p)^2` and `relu(-sin p)^2` are mutually exclusive, exactly one
   foot is in-window at every step, so the denominator is 1 by construction --
   the patch asserts that instead of assuming it.
2. **Reset the peak once per window, and freeze it outside.** A stance foot must
   not accumulate a peak from body bobbing; a swing foot must not lose the peak
   it legitimately reached.

`ramp_s` is kept: the first 0.8 s of an episode is scaled linearly, which keeps
the initial reset transient out of the reward.

Residual risk, stated honestly
------------------------------
`joy_foot_peak` was tried once before and died at 0.0000 (`joy_smooth_2048x600_
peak`). That version was Gaussian at 24 mm *and* multiplied the two feet; at
h=5.7 mm it paid 0.011 x 0.011 = 1.2e-4 with a gradient of 1.7e-6 /mm, which is
indistinguishable from zero. This version pays 0.285 at the same height with a
constant 0.050 /mm gradient, which is 1.2x the sigma=18 gradient and does not
decay with height. The gradient claim is verifiable offline, which is what
`tools/probe_joy_peak_payoff.py` does.

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/patch_joy_peak_linear.py [--revert]
"""

from __future__ import annotations

import sys

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
MDP = ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/mdp.py"
CFG = ROOT / "third_party/microduck_rl/src/mjlab_microduck/tasks/microduck_joy_env_cfg.py"
INSTALLED = (ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/"
             "microduck_joy_env_cfg.py")

# --- mdp.py: the payoff body inside joy_foot_peak ----------------------------
OLD_BODY = """        e = torch.clamp(t / ramp_s, 0., 1.)
        err = (self.peak - target_height) / sigma
        out = torch.exp(-err ** 2).prod(-1) * e
        try:
            env.extras["log"]["Metrics/joy_peak_height_max"] = self.peak.max()  # max over envs x feet
        except Exception:
            pass
        return out"""

NEW_BODY = """        e = torch.clamp(t / ramp_s, 0., 1.)
        # Linear payoff, and grade only the foot that is inside its swing window.
        # A product over both feet would multiply the swinging foot's score by the
        # standing foot's 5.7/20 = 0.285 at every step -- compressing the
        # perfect-vs-stance contrast from 0.715 to 0.204. See
        # tools/patch_joy_peak_linear.py.
        per_foot = torch.clamp(self.peak / target_height, 0., 1.)
        w = in_swing.to(per_foot.dtype)
        denom = w.sum(-1).double().clamp(min=1.).to(per_foot.dtype)
        out = (per_foot * w).sum(-1) / denom * e
        try:
            # Diagnostics: the quantity the reward grades, and the one the gate
            # reports. Log both so a "reward up, foot flat" run is visible at once.
            sw = self.peak[in_swing]
            env.extras["log"]["Metrics/joy_peak_height_max"] = self.peak.max()
            if sw.numel() > 1:
                env.extras["log"]["Metrics/joy_peak_swing_p50"] = sw.median()
                env.extras["log"]["Metrics/joy_peak_swing_min"] = sw.min()
        except Exception:
            pass
        return out"""

# target_height 0.024 -> 0.020 (upstream `target_height = 0.02`).
OLD_SIG = 'def __call__(self, env, asset_cfg, target_height=.024, sigma=.009,'
NEW_SIG = 'def __call__(self, env, asset_cfg, target_height=.020, sigma=.009,'

# --- env cfg: swap the term in ----------------------------------------------
OLD_CFG = (
    "    cfg.rewards['joy_feet']=RewardTermCfg(func=mdp.joy_foot_rhythm,weight=12.,"
    'params={"asset_cfg":SceneEntityCfg("robot",site_names=["left_foot","right_foot"]),'
    '"sigma":.018})'
)
NEW_CFG = (
    "    # Swing-window peak, linear payoff at 20 mm -- see\n"
    "    # tools/patch_joy_peak_linear.py for the measured standing/press/lift table.\n"
    "    cfg.rewards['joy_feet']=RewardTermCfg(func=mdp.joy_foot_peak,weight=12.,"
    'params={"asset_cfg":SceneEntityCfg("robot",site_names=["left_foot","right_foot"])})'
)


def swap(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            print(f"  [skip] {label}: already patched")
            return text
        raise SystemExit(f"anchor missing in {label}:\n{old!r}")
    if text.count(old) != 1:
        raise SystemExit(f"anchor not unique in {label} ({text.count(old)}x)")
    print(f"  [ok]   {label}")
    return text.replace(old, new)


def main() -> int:
    revert = "--revert" in sys.argv
    a, b, c = OLD_BODY, OLD_SIG, OLD_CFG
    d, e, f = NEW_BODY, NEW_SIG, NEW_CFG
    if revert:
        a, d = d, a
        b, e = e, b
        c, f = f, c
        print("reverting -> gaussian(24mm) x prod, joy_foot_rhythm(sigma .018)")

    txt = MDP.read_text(encoding="utf-8")
    txt = swap(txt, a, d, "mdp.py joy_foot_peak payoff")
    txt = swap(txt, b, e, "mdp.py target_height")
    MDP.write_text(txt, encoding="utf-8")

    txt = CFG.read_text(encoding="utf-8")
    txt = swap(txt, c, f, "joy_env_cfg joy_feet term")
    CFG.write_text(txt, encoding="utf-8")
    # `train.exe` imports the *copy* in site-packages, not the `.upstream` source
    # (see the header of tools/train_joy.sh). Sync it here or the run silently
    # trains the old term -- the exact failure mode that made an earlier A/B
    # look like "plant was wrong" when the config had never loaded.
    INSTALLED.write_text(txt, encoding="utf-8")
    print(f"  [ok]   synced -> {INSTALLED.relative_to(ROOT)}")

    # Compile-check both files. An earlier patch in this repo silently ate four
    # spaces of indentation and only failed 40 min into training.
    import py_compile
    for p in (MDP, CFG):
        py_compile.compile(str(p), doraise=True)
        print(f"  [ok]   compiles: {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
