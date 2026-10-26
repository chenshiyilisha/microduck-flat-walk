"""Grade BOTH feet (`min` of each foot's last-window peak) + unify the reward clock.

Why the reward had no term requiring both legs, and why `min` is the right shape
--------------------------------------------------------------------------------
`joy_foot_peak` graded only the foot that was *currently* inside its swing
window:

    w       = in_swing                 # exactly one foot True on any step
    denom   = w.sum(-1).clamp(min=1)   # == 1, always
    per_foot= clamp(peak / target, 0, 1)
    out     = (per_foot * w).sum(-1) / denom

A one-leg march therefore scored, on every step, wherever the swinging foot got
to; the stance foot's 0 never entered the numerator. Measured on the ninth run
(`joy_sym_2048x600`, model_599):

    joy_foot_peak_mean = 0.529   ~= (1.0 + 0.05) / 2

i.e. one foot at the 20 mm target, the other pinned at 0.5-5 mm, which is
*exactly* the observed gait:

    phase     left    right
     0.02     2.89     0.42     left window: neither foot lifts
     0.35     0.90     1.35
     0.44     0.10     5.18     right window: right foot starts to rise
     0.65    -0.35    21.90     right foot at target, left foot on the ground
     0.98     2.30     0.79

An alternating gait would score ~1.0, so the old reward already said
"alternating is worth 2x" -- and the policy still converged to the march,
because 0.529 was reachable while both-feet-lifting was not, and nothing was
lost by never lifting one foot. The gap is *not* in the weighting.

This patch changes the graded quantity to

    score = min(last_peak_left, last_peak_right) / target

where `last_peak_f` is the peak latched at the end of foot f's most recent swing
window. Consequences, all three checked in tools/probe_pair_min.py:

    gait                       old score      pair_min
    standing still              0.145          0.145
    one-leg march               0.529          ~0.145
    alternating, both at 20mm   1.000          1.000

The gradient now points from the march (0.145) toward alternating (1.0) instead
of being flat from 0.529 upward. `min` is also immune to the failure that made
the earlier pointwise `prod(-1)` unusable: that multiplied the swinging foot's
score by the stance foot's 0.285 *on the same step*, compressing the
perfect-vs-stance contrast. A latched end-of-window peak is immune to that
because stance steps no longer contribute to the graded foot at all.

Literature
----------
Siekmann et al., "Sim-to-Real Learning of All Common Bipedal Gaits via Periodic
Reward Composition" (arXiv 2011.01387) is the framework this fits into: each leg
is graded by a phase indicator times a phase-specific quantity. Their gait
parameterisation makes the failure explicit -- |theta_left - theta_right| ~ 0 is
"hopping", ~0.5 is "walking". A march is a leg whose swing indicator never fires,
which no phase offset can fix; only a term that requires *both* legs can.

Teach Biped (arXiv 1910.10194) uses a double-support duration penalty for the
same symptom (-2.0 and episode termination once t_ds exceeds 100 steps). That is
deliberately NOT implemented here: (a) it is redundant with `pair_min` --
"both feet planted" is the march, and `pair_min` already grades it at 0.145
versus 1.0; (b) a hard threshold plus termination is a much blunter instrument
than a continuous score and would make the early curriculum stages unstable.

What IS implemented as the complement is `joy_foot_stance`: a cost on the
*support* foot leaving the ground while the other foot is in its swing window.
`pair_min` punishes "neither foot lifts"; `joy_foot_stance` punishes "both feet
lift" (a hop). Together they bracket the alternating gait from both sides. It is
registered only when MICRODUCK_JOY_DS_WEIGHT > 0 (default 0) so the tenth run
stays a two-variable change (pair_min + RSI) rather than three.

Second, unrelated but blocking fix: the reward built its own phase
---------------------------------------------------------------
`joy_foot_peak.__call__` computed

    p = 2 * math.pi * frequency * t          # t = episode_length_buf * step_dt

while `joy_phase(env)` -- which `joy_gait_clock`, `joy_head_command` and
`joy_body_command` all call -- returns the same thing **plus** the per-episode
RSI offset once `MICRODUCK_JOY_PHASE_RSI=1`. With RSI off there is no offset
attribute and the two are bit-identical, which is why the ninth run never
exposed it. With RSI on, the observation clock and the reward clock would be
phase-shifted against each other by up to pi, and the policy would be graded on
the wrong windows with no error message anywhere.

Switching to `joy_phase(env, frequency=frequency)` is bit-identical when RSI is
off and correct when it is on. This is a precondition for the tenth run, not an
optional cleanup.

Switches
--------
    MICRODUCK_JOY_PAIR_MIN=1     grade min(last_peak_left, last_peak_right)
                                 (default off -> old per-swing-window grading)
    MICRODUCK_JOY_DS_WEIGHT=W    add `joy_ds` at weight W (default off)

The `-1 step_dt` window edge and the curricula are untouched, so a pair_min run
differs from `joy_sym_2048x600` in exactly these two things.

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/patch_joy_pair_min.py [--revert]

WARNING: `tools/apply_joy_patch.py` re-syncs `.upstream/.../mdp.py` (the
*unpatched* original) into site-packages. Re-running it reverts this and every
other mdp.py patch; re-run the patch chain afterwards. This script refuses to
run if it sees the unpatched anchor, rather than silently doing nothing.
"""

from __future__ import annotations

import pathlib
import py_compile
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
MDP = ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/mdp.py"
CFG = ROOT / "third_party/microduck_rl/src/mjlab_microduck/tasks/microduck_joy_env_cfg.py"
INSTALLED = (
    ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/microduck_joy_env_cfg.py"
)

# --- mdp.py: (1) one clock --------------------------------------------------

OLD_CLOCK = """        t = env.episode_length_buf.to(torch.float32) * self.step_dt
        p = 2 * math.pi * frequency * t
        s = torch.sin(p)"""

NEW_CLOCK = """        t = env.episode_length_buf.to(torch.float32) * self.step_dt
        # ONE clock. joy_gait_clock / joy_head_command / joy_body_command all
        # read joy_phase(), so the reward must read the same function. This is
        # bit-identical to `2*pi*frequency*t` while RSI is off (no offset
        # attribute exists), and carries the per-episode offset once
        # MICRODUCK_JOY_PHASE_RSI=1. Building the phase locally -- as this term
        # did until now -- silently grades against an un-shifted clock as soon
        # as RSI is enabled. See tools/patch_joy_pair_min.py.
        p = joy_phase(env, frequency=frequency)
        s = torch.sin(p)"""

# --- mdp.py: (2) latched end-of-window peak --------------------------------

OLD_INIT = """            (env.num_envs, self.num_feet), -1, dtype=torch.long, device=env.device
        )
        self.step_dt = env.step_dt"""

NEW_INIT = """            (env.num_envs, self.num_feet), -1, dtype=torch.long, device=env.device
        )
        self.step_dt = env.step_dt
        # Peak latched at the END of each foot's most recent swing window.
        # `self.peak` is the running peak of the window still in progress;
        # `end_peak` is what `pair_min=True` grades, so a stance step can never
        # contribute to the other foot's score.
        self.end_peak = torch.zeros(env.num_envs, self.num_feet, device=env.device)
        self.prev_swing = torch.zeros(
            env.num_envs, self.num_feet, dtype=torch.bool, device=env.device
        )"""

OLD_SIG = """    def __call__(self, env, asset_cfg, target_height=None, sigma=.009,
                 frequency=1.15, stance_height=.0005, ramp_s=.8):"""

NEW_SIG = """    def __call__(self, env, asset_cfg, target_height=None, sigma=.009,
                 frequency=1.15, stance_height=.0005, ramp_s=.8, pair_min=False):"""

OLD_LATCH = """        self.peak = torch.where(in_swing, peak, self.peak)
        self.window = window"""

NEW_LATCH = """        self.peak = torch.where(in_swing, peak, self.peak)
        # Latch the finished window's peak on the True -> False edge. `self.peak`
        # is already frozen outside the swing window, so it still holds the value
        # the window ended on.
        ended = self.prev_swing & ~in_swing
        self.end_peak = torch.where(ended, self.peak, self.end_peak)
        # A new episode must not inherit either buffer. Without this the last
        # lift of the previous episode keeps paying for up to one full cycle
        # (1/1.15 s ~ 0.87 s per window, 1.7 s worst case), and `self.peak`
        # starts the first window from a stale value instead of the current foot
        # height. `episode_length_buf` is 0 on the reset step.
        fresh_episode = env.episode_length_buf <= 0
        if bool(fresh_episode.any()):
            self.peak[fresh_episode] = h[fresh_episode]
            self.end_peak[fresh_episode] = 0.
        self.prev_swing = in_swing
        self.window = window"""

OLD_SCORE = """        per_foot = torch.clamp(self.peak / target_height, 0., 1.)
        w = in_swing.to(per_foot.dtype)
        denom = w.sum(-1).double().clamp(min=1.).to(per_foot.dtype)
        out = (per_foot * w).sum(-1) / denom * e"""

NEW_SCORE = """        if pair_min:
            # BOTH feet must reach the target inside *their own* window:
            #   standing      2.9/20, 2.9/20  -> min 0.145
            #   one-leg march 20.0/20, 2.9/20 -> min 0.145
            #   alternating   20.0/20, 20/20  -> min 1.000
            # Under the old per-swing-window rule the march scored 0.529 and the
            # stance half-cycle cost nothing. See the module docstring.
            per_foot = torch.clamp(self.end_peak / target_height, 0., 1.)
            out = per_foot.min(-1).values * e
        else:
            per_foot = torch.clamp(self.peak / target_height, 0., 1.)
            w = in_swing.to(per_foot.dtype)
            denom = w.sum(-1).double().clamp(min=1.).to(per_foot.dtype)
            out = (per_foot * w).sum(-1) / denom * e"""

OLD_LOG = """            if sw.numel() > 1:
                env.extras["log"]["Metrics/joy_peak_swing_p50"] = sw.median()
                env.extras["log"]["Metrics/joy_peak_swing_min"] = sw.min()"""

NEW_LOG = """            if sw.numel() > 1:
                env.extras["log"]["Metrics/joy_peak_swing_p50"] = sw.median()
                env.extras["log"]["Metrics/joy_peak_swing_min"] = sw.min()
            # Per-foot latched peaks: the acceptance question is whether the
            # *right* one starts moving, and the gate is min() of the two, so
            # they must be readable separately rather than inferred.
            if self.num_feet >= 2:
                env.extras["log"]["Metrics/joy_end_peak_left_m"] = (
                    self.end_peak[:, 0].mean())
                env.extras["log"]["Metrics/joy_end_peak_right_m"] = (
                    self.end_peak[:, 1].mean())
                env.extras["log"]["Metrics/joy_end_peak_min_m"] = (
                    self.end_peak.min(-1).values.mean())"""

# --- mdp.py: (3) support-foot cost (anti-hop complement) -------------------

STANCE_FN = '''def joy_foot_stance(env, asset_cfg=SceneEntityCfg('robot',site_names=['left_foot','right_foot']),
                    stance_m=.006, stance_height=.0005, frequency=1.15, ramp_s=.8):
    """Cost: a foot must stay planted while the OTHER foot is in its swing window.

    The complement of `joy_foot_peak(pair_min=True)`. That one asks "did both feet
    reach the target in their own window"; this one asks "was the non-swinging
    foot actually carrying the body". Together they bracket the alternating gait:

        gait              pair_min   joy_foot_stance
        one-leg march     0.145      ~0 (the support foot is planted)
        hop / both lift   1.000      large (the support foot leaves the ground)
        alternating       1.000      0

    Without it, `pair_min` alone would rate a hop as perfect -- both feet do reach
    20 mm, just at the same time. A hop is only prevented physically (the body
    falls), not by the reward, and that leaves the policy free to trade a short
    unsupported phase for score. See the module docstring for why the Teach Biped
    double-support-duration penalty (arXiv 1910.10194) is not used instead.

    Magnitude, measured in tools/probe_pair_min.py: a full hop puts the support
    foot 14 mm over `stance_m`, so the cost is 0.014 m per step. `joy_feet` pays
    up to 12 per step, so a weight near 850 would be needed for this term to
    outweigh a hop on its own -- far too stiff to train stably. Treat it as a
    continuous hint (weight order 50-200) layered on top of the fact that an
    unsupported phase physically falls; not as a hard constraint.

    Returns a NEGATIVE cost (same convention as `joy_drift_cost`), so the config
    weight is positive. Linear in the excess over `stance_m`, so a support foot
    that is merely on its way down is not punished; only one that is off the
    ground by more than `stance_m` is.

    Not registered by default: `MICRODUCK_JOY_DS_WEIGHT=W` adds it at weight W.
    """
    asset = env.scene[asset_cfg.name]
    p = joy_phase(env, frequency=frequency)
    s = torch.sin(p)
    in_swing = torch.stack((s > 0, s < 0), dim=-1)
    must_stance = ~in_swing
    h = (asset.data.site_pos_w[:, asset_cfg.site_ids, 2]
         - env.scene.terrain.env_origins[:, None, 2] - stance_height)
    over = torch.relu(h - stance_m)
    w = must_stance.to(over.dtype)
    denom = w.sum(-1).double().clamp(min=1.).to(over.dtype)
    e = torch.clamp(env.episode_length_buf.to(torch.float32) * env.step_dt / ramp_s, 0., 1.)
    return -(over * w).sum(-1) / denom * e


def joy_head_tracking(env):'''

OLD_HEAD_TRACKING = "def joy_head_tracking(env):"

# --- env cfg: both switches -------------------------------------------------

OLD_CFG = """    cfg.rewards['joy_feet']=RewardTermCfg(func=mdp.joy_foot_peak,weight=12.,params={"asset_cfg":SceneEntityCfg("robot",site_names=["left_foot","right_foot"])})"""

NEW_CFG = """    cfg.rewards['joy_feet']=RewardTermCfg(func=mdp.joy_foot_peak,weight=12.,params={"asset_cfg":SceneEntityCfg("robot",site_names=["left_foot","right_foot"])})
    # --- Phase 10: grade BOTH feet, optionally forbid a double swing ----------
    # pair_min: min(last_peak_left, last_peak_right) / target. A one-leg march
    # falls from 0.529 to 0.145 while an alternating gait stays at 1.0.
    # joy_ds:  cost on the support foot leaving the ground (anti-hop complement).
    # Both opt-in; see tools/patch_joy_pair_min.py for the measurements.
    if os.environ.get('MICRODUCK_JOY_PAIR_MIN','0')=='1':
        cfg.rewards['joy_feet'].params['pair_min']=True
    _joy_ds=float(os.environ.get('MICRODUCK_JOY_DS_WEIGHT','0') or 0.)
    if _joy_ds>0.:
        cfg.rewards['joy_ds']=RewardTermCfg(func=mdp.joy_foot_stance,weight=_joy_ds,
            params={"asset_cfg":SceneEntityCfg("robot",site_names=["left_foot","right_foot"])})"""


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
    mdp_txt = MDP.read_text(encoding="utf-8")
    cfg_txt = CFG.read_text(encoding="utf-8")

    if not revert:
        # Guard: site-packages must still carry the linear-payoff patch, else
        # apply_joy_patch.py has restored the unpatched original and every
        # anchor below is meaningless.
        if "Linear payoff, and grade only the foot" not in mdp_txt:
            print(
                "  ! site-packages mdp.py does not carry the linear payoff patch.\n"
                "    tools/apply_joy_patch.py re-synced the unpatched .upstream copy.\n"
                "    Re-run the patch chain (patch_joy_peak_linear.py, "
                "patch_joy_peak_curriculum.py, patch_joy_gait_clock.py, "
                "patch_joy_phase_rsi.py) first."
            )
            return 1

    pairs = [
        (OLD_CLOCK, NEW_CLOCK, "joy_foot_peak unifies the gait clock"),
        (OLD_INIT, NEW_INIT, "joy_foot_peak end_peak buffers"),
        (OLD_SIG, NEW_SIG, "joy_foot_peak pair_min argument"),
        (OLD_LATCH, NEW_LATCH, "joy_foot_peak window-end latch"),
        (OLD_SCORE, NEW_SCORE, "joy_foot_peak pair_min scoring"),
        (OLD_LOG, NEW_LOG, "joy_foot_peak per-foot logging"),
        (OLD_HEAD_TRACKING, STANCE_FN, "add joy_foot_stance"),
    ]
    for old, new, label in pairs:
        a, b = (new, old) if revert else (old, new)
        mdp_txt = swap(mdp_txt, a, b, label)

    a, b = (NEW_CFG, OLD_CFG) if revert else (OLD_CFG, NEW_CFG)
    cfg_txt = swap(cfg_txt, a, b, "joy_env_cfg switches")

    MDP.write_text(mdp_txt, encoding="utf-8")
    CFG.write_text(cfg_txt, encoding="utf-8")
    # train.exe imports the site-packages copy, not the .upstream source.
    INSTALLED.write_text(cfg_txt, encoding="utf-8")
    print(f"  [ok]   synced -> {INSTALLED.relative_to(ROOT)}")

    for p in (MDP, CFG, INSTALLED):
        py_compile.compile(str(p), doraise=True)
        print(f"  [ok]   compiles: {p.name} ({p.parent.parent.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
