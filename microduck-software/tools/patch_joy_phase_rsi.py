"""Randomise the gait-clock start phase per episode (RSI for the stepping clock).

What the literature says, and why it applies verbatim
-----------------------------------------------------
Yu / Turk / Liu, "On Learning Symmetric Locomotion" (arXiv 1801.08093), on the
failure mode of symmetry constraints:

    "Symmetry can sometimes be harmful, especially when the character begins
     from or otherwise arrives at a neutral pose ... a symmetric policy is
     incapable of escaping from a neutral pose since the action that it takes
     would also be symmetric ... a character that starts from the T-pose will
     likely perform some kind of hopping gait ... The breaking symmetry problem
     is most severe when enforcing symmetry through network architecture ...
     A simple workaround is to always start the character from a non-neutral
     position."

LORM (PeerJ CS-927) names the same remedy for biped gait RL and calls it
random state initialisation (RSI): at the start of an episode, initialise the
environment "as one random phase of the reference gait cycle", so the agent
meets the early and late sub-tasks simultaneously instead of learning a
serial, start-phase-conditioned policy.

Our env is exactly the configuration both papers warn about:

  * reset pose is the HOME stand -- a bilaterally symmetric neutral pose;
  * `joy_phase(env) = 2*pi*1.15*episode_length_buf*step_dt`, and
    `episode_length_buf` is 0 on the reset step, so **every episode of every
    env starts at p = 0**;
  * the ninth run additionally enforces bilateral symmetry
    (`MICRODUCK_JOY_SYMMETRY=1`, data augmentation).

So all 2048 envs begin from one symmetric pose *and* one symmetric phase, and
the policy is being pushed toward symmetry-consistent actions from that point.
That is the "left foot always leads, right foot supports" bias the earlier
probes measured from the other side: `probe_policy_bias_lift.py` found the left
knee tolerates +0.10 rad while the right knee falls at +0.10 rad, and
`probe_phase_profile.py` found the right foot pinned at 0.45 mm inside its own
swing window.

What this patch changes
-----------------------
`joy_phase` gains a per-env constant offset that is **resampled on every
reset** from U[0, 2*pi). Reward terms, head/body command terms and the
`gait_clock` observation all call `joy_phase`, so they necessarily share the
same shifted clock -- no term can drift out of sync.

Off by default (`MICRODUCK_JOY_PHASE_RSI=1` to enable), and when off the reset
event is not registered at all, so `joy_phase` sees no attribute and takes
bit-identical old path. That keeps the negative control clean: the only
difference between the two runs is whether the start phase is random.

Not changed on purpose: the 0.8 s command ramp (`e = clamp(t/0.8)`) still
starts at t = 0 regardless of phase. That means the first 0.8 s has a random
phase but a ramped-down command amplitude; leaving it alone keeps this patch
to one variable.

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/patch_joy_phase_rsi.py [--revert]

Then train with `MICRODUCK_JOY_PHASE_RSI=1` in the environment.
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

# --- mdp.py: the reset event + the offset in joy_phase ----------------------

OLD_PHASE = """def joy_phase(env, frequency=1.15):
    return 2 * math.pi * frequency * env.episode_length_buf * env.step_dt"""

NEW_PHASE = '''JOY_PHASE_RSI_ENV = "MICRODUCK_JOY_PHASE_RSI"


def initialize_joy_gait_phase_offset(env, env_ids):
    """Resample each reset env's constant gait-clock offset from U[0, 2*pi).

    Registered as a mode='reset' event only when MICRODUCK_JOY_PHASE_RSI=1.
    Stored on the env instance (not a module global) so two environments in the
    same process cannot clobber each other's offsets.

    Rationale: with episode_length_buf = 0 on reset, every env starts at p = 0,
    i.e. a symmetric neutral pose *and* a symmetric phase. Yu/Turk/Liu (2018)
    show a symmetric policy cannot escape a neutral pose (hopping gait) and
    prescribe starting from a non-neutral state; LORM calls the gait-cycle
    version random state initialisation. See tools/patch_joy_phase_rsi.py.
    """
    if env_ids is None:
        env_ids = torch.arange(env.num_envs, device=env.device, dtype=torch.int64)
    n = env.num_envs
    off = getattr(env, "_joy_gait_phase_offset", None)
    if off is None or off.shape[0] != n or off.device != torch.device(env.device):
        off = torch.zeros(n, device=env.device)
        setattr(env, "_joy_gait_phase_offset", off)
    if len(env_ids):
        off[env_ids] = torch.rand(len(env_ids), device=env.device) * (2 * math.pi)


def joy_phase(env, frequency=1.15):
    p = 2 * math.pi * frequency * env.episode_length_buf * env.step_dt
    # Per-episode start-phase offset (empty / absent unless RSI is enabled).
    off = getattr(env, "_joy_gait_phase_offset", None)
    if off is not None and off.shape[0] == env.num_envs:
        p = p + off
    return p'''

# --- env cfg: register the reset event behind the switch --------------------

OLD_CFG = """    cfg.events['initialize_joy_servo_targets']=EventTermCfg(func=mdp.initialize_joy_servo_targets,mode='reset')
    return cfg"""

NEW_CFG = """    cfg.events['initialize_joy_servo_targets']=EventTermCfg(func=mdp.initialize_joy_servo_targets,mode='reset')
    # Random start phase per episode (RSI for the stepping clock). Not
    # registered at all when off, so joy_phase takes the old path exactly.
    # See tools/patch_joy_phase_rsi.py.
    if __import__('os').environ.get('MICRODUCK_JOY_PHASE_RSI','0')=='1':
        cfg.events['initialize_joy_gait_phase_offset']=EventTermCfg(
            func=mdp.initialize_joy_gait_phase_offset,mode='reset')
    return cfg"""


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

    # The two mdp.py copies are NOT identical (site-packages carries patches the
    # .upstream source does not), so each one gets the swap applied in place
    # rather than copying one over the other.
    UP_MDP = ROOT / ".upstream/microduck_rl-develop/src/mjlab_microduck/tasks/mdp.py"
    for path, label in ((MDP, "mdp.py"), (UP_MDP, "mdp.py(.upstream)")):
        if not path.exists():
            print(f"  [skip] {label}: absent")
            continue
        txt = path.read_text(encoding="utf-8")
        if revert:
            txt = swap(txt, NEW_PHASE, OLD_PHASE, f"{label} joy_phase offset")
        else:
            txt = swap(txt, OLD_PHASE, NEW_PHASE, f"{label} joy_phase offset")
        path.write_text(txt, encoding="utf-8")

    txt = CFG.read_text(encoding="utf-8")
    if revert:
        txt = swap(txt, NEW_CFG, OLD_CFG, "joy_env_cfg RSI event")
    else:
        txt = swap(txt, OLD_CFG, NEW_CFG, "joy_env_cfg RSI event")
    CFG.write_text(txt, encoding="utf-8")
    # train.exe imports the site-packages copy, not the .upstream source.
    INSTALLED.write_text(txt, encoding="utf-8")
    print(f"  [ok]   synced -> {INSTALLED.relative_to(ROOT)}")

    for p in (MDP, UP_MDP, CFG, INSTALLED):
        py_compile.compile(str(p), doraise=True)
        print(f"  [ok]   compiles: {p.name} ({p.parent.parent.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
