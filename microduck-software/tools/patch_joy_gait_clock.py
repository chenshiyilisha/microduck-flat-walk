"""Put the 1.15 Hz stepping clock into the observation, as an explicit pair.

What the evidence says
----------------------
`tools/probe_phase_profile.py` on `joy_curric_2048x600/model_400` (the seventh
reward version, height curriculum 7->20 mm) gave, binned by gait phase:

    phase   left     right
     0.02  20.09 mm   0.45 mm     left foot is up at the start of its own window
     0.52   4.53 mm   4.05 mm     ... and down at the start of the right's
     0.98  18.47 mm   0.56 mm

    left  mean 9.48 mm  sd 6.54 mm  r(sin) = +0.301
    right mean 2.26 mm  sd 1.84 mm  r(sin) = -0.220

So the left leg tracks the clock (a clean half-sine, and the gate confirms
`feet_peak_left_m = 24.5 mm`) while the right leg sits at 0.45-4 mm *inside its
own swing window* and its correlation with the clock is **negative**. That is
not "both feet too low" -- it is a one-leg stance: left foot cycling in the air,
right foot pinned to the ground carrying the body.

That reframes every earlier failure. Five reward shapes and a height curriculum
all landed at 5.3-5.8 mm on the *min* of the two feet because the binding
constraint was never the payoff for height; it was that lifting the second foot
requires handing support over to the first one, which is a coordination problem,
not a magnitude problem.

What the clock has to do with it
--------------------------------
The phase is currently only *implicit*, and only inside tracking commands:

    joy_head_command  -> (..., .24*sin(p), .12*sin(p))
    joy_body_command  -> (..., .006*(1-cos(2p)), .07*sin(p), ...)

There is `sin(p)` but no usable `cos(p)` (`1-cos(2p)` has period p/2, so p and
p+pi are indistinguishable through it), and the sin terms ride on head/body
pose targets that the policy must first learn to track. So the policy cannot
tell "rising toward the left swing" from "falling away from it", which is
exactly the half-cycle distinction the two legs divide between them.

Both reference implementations hand the clock over directly:

  * Booster Gym (arXiv 2506.15132), Table I: "Gait Cycle 2" ticks for actor and
    critic, `(cos 2*pi*f*t, sin 2*pi*f*t)`; the paper notes the standing gait
    sets the cycle to zero so standing and walking share one policy.
  * unitree_rl_mjlab / walka_rl_mjlab: a gait-clock phase observation feeds
    `feet_gait` and `stand_still`, ported from the velocity-task fork.
  * mjlab itself ships no gait-phase observation term -- hence this patch
    rather than a config change.

The fix, and why it is only this
--------------------------------
Add two dimensions: `sin(p), cos(p)`, from the *same* `joy_phase(env)` the
reward uses, so the observation and the graded window cannot drift apart.

Reward, target height and curriculum are left untouched on purpose. The sixth
version (window peak + linear 20 mm) already proved the payoff can move the
first foot to 24.5 mm; changing it again in the same run would confound the one
variable that matters here. If the clock is what was missing, the right foot
starts tracking without any reward change; if it is not, that is a clean
negative and the next suspect is the support hand-over itself.

Cost, stated plainly
--------------------
The actor input grows by 2, so this requires training from scratch (which
`AGENTS.md` already demands for any reward/observation change). Deployment must
carry the same two dimensions -- the ONNX policy input width changes.

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/patch_joy_gait_clock.py [--revert]
"""

from __future__ import annotations

import py_compile
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MDP = ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/mdp.py"
CFG = ROOT / ".upstream/microduck_rl-develop/src/mjlab_microduck/tasks/microduck_joy_env_cfg.py"
INSTALLED = (ROOT / ".venv-mjlab/Lib/site-packages/mjlab_microduck/tasks/"
             "microduck_joy_env_cfg.py")

# --- mdp.py: the observation term -------------------------------------------
ANCHOR_FN = "def joy_head_command(env):"

NEW_FN = '''def joy_gait_clock(env):
    """Explicit (sin p, cos p) for the 1.15 Hz stepping clock.

    The phase is otherwise only implied by head_command (.24 sin p) and
    body_command (.07 sin p, .006(1-cos 2p)) -- and with no cos p the policy
    cannot tell the rising half-cycle from the falling one, which is exactly how
    the two legs divide the work. probe_phase_profile.py on model_400 measured
    the consequence: left foot 24.5 mm and phase-locked, right foot pinned at
    0.45-4 mm inside its own window with r(sin) = -0.22.

    Same clock as joy_foot_peak grades (`joy_phase`), so observation and reward
    cannot drift. Booster Gym (arXiv 2506.15132, Table I) feeds the identical
    pair to actor and critic; unitree_rl_mjlab does the same via a gait-clock
    observation. See tools/patch_joy_gait_clock.py.
    """
    p = joy_phase(env)
    return torch.stack((torch.sin(p), torch.cos(p)), dim=-1)


'''

# --- env cfg: register it on actor and critic -------------------------------
OLD_CFG = """        cfg.observations[group].terms['body_command']=ObservationTermCfg(func=mdp.joy_body_command)"""
NEW_CFG = """        cfg.observations[group].terms['body_command']=ObservationTermCfg(func=mdp.joy_body_command)
        # Explicit stepping clock (+2 dims). See tools/patch_joy_gait_clock.py.
        cfg.observations[group].terms['gait_clock']=ObservationTermCfg(func=mdp.joy_gait_clock)"""


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

    txt = MDP.read_text(encoding="utf-8")
    if revert:
        if "def joy_gait_clock(env):" in txt:
            head, _, tail = txt.partition("def joy_gait_clock(env):")
            # drop the function up to the next top-level def
            rest = tail.split("\ndef ", 1)
            txt = head + "\ndef " + rest[1] if len(rest) == 2 else head
            print("  [ok]   mdp.py joy_gait_clock removed")
        else:
            print("  [skip] mdp.py joy_gait_clock: absent")
    else:
        txt = swap(txt, ANCHOR_FN, NEW_FN + ANCHOR_FN, "mdp.py joy_gait_clock")
    MDP.write_text(txt, encoding="utf-8")

    txt = CFG.read_text(encoding="utf-8")
    if revert:
        txt = swap(txt, NEW_CFG, OLD_CFG, "joy_env_cfg gait_clock term")
    else:
        txt = swap(txt, OLD_CFG, NEW_CFG, "joy_env_cfg gait_clock term")
    CFG.write_text(txt, encoding="utf-8")
    # train.exe imports the site-packages copy, not the .upstream source.
    INSTALLED.write_text(txt, encoding="utf-8")
    print(f"  [ok]   synced -> {INSTALLED.relative_to(ROOT)}")

    for p in (MDP, CFG):
        py_compile.compile(str(p), doraise=True)
        print(f"  [ok]   compiles: {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
