#!/usr/bin/env python
"""issue #46 patch: forward-gated air_time + lateral-weighted velocity tracking.

Why
---
Upstream ``pollen-robotics/microduck_rl`` issue #46 -- "Velocity-family training
converges to standing-in-place across all reward/curriculum variants" -- is still
open, with no maintainer reply. ``Qi-hub-dot/microduck-locomotion-diagnosis``
reproduced it on the *same* RTX 4070 Laptop 8 GB + Windows hardware (4096 envs,
5000 iters, error_vel_xy 0.42 vs the reporter's 0.43) and isolated three cheap,
fixable causes:

1. ``feet_air_time`` gates on the COMMAND only
   (``mjlab/tasks/velocity/mdp/rewards.py``: ``scale = (total_command > thr).float()``).
   It never checks whether the robot actually moves. In our cfg air_time is the
   largest positive term (weight 3.0), so a robot ordered forward that tap-dances
   in place collects the full reward. That is a standing-in-place optimum.
2. Lateral drift was measured at ~2x the forward progress, while
   ``track_linear_velocity`` weights x and y equally
   (``xy_error = sum(square(cmd[:2] - actual[:2]))``) -- so "slides sideways"
   scores the same as "walks forward".
3. Tracking weight 2.0 is too weak against the regularizers.

That report measured error_vel_xy 0.35 -> 0.21 after applying all three.

What this patch changes
-----------------------
* appends two helpers to ``mjlab_microduck/tasks/mdp.py`` (append-only, does not
  touch any existing line);
* inserts ONE opt-in block into ``microduck_velocity_env_cfg.py`` immediately
  before ``return cfg``, guarded by ``MICRODUCK_ISSUE46=1``.

With the env var unset, every reward term is byte-for-byte the old behaviour, so
the baseline, its checkpoints and its runmeta stay reproducible.

Why not write it from scratch
-----------------------------
The forward gate already exists upstream: ``_forward_progress_gate`` in the same
``mdp.py`` (line ~4931), used by the roller tasks. We reuse it rather than
re-deriving it. ``air_time`` itself stays upstream's ``feet_air_time``; the
wrapper only multiplies. The single genuinely new line of logic is the lateral
weight in ``track_linear_velocity_lateral``, because upstream has no
lateral-weighted variant.

Three knobs (env vars, all optional)
------------------------------------
MICRODUCK_ISSUE46=1                  enable the patch (default 0 = off)
MICRODUCK_ISSUE46_GATE=0.15          forward speed (m/s) at which the air_time
                                     gate reaches full value. 0.15 is the speed
                                     the factory alpha_walking policy actually
                                     reaches under a 0.4 command (0.164 m/s), so
                                     it means "you are really walking".
MICRODUCK_ISSUE46_FLOOR=0.3          fraction of the air_time reward still paid
                                     at zero forward speed. Pure multiplicative
                                     gating (floor 0) removes the only gradient
                                     that gets a standing robot to lift a foot in
                                     the first place; 0.3 keeps a bootstrap path.

Usage
-----
  python tools/patch_issue46.py --check     # report only, touches nothing
  python tools/patch_issue46.py --apply     # idempotent; backs up first
  python tools/patch_issue46.py --revert    # restores the backup / strips marks
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SITE = ROOT / ".venv-mjlab" / "Lib" / "site-packages"
TASKS = SITE / "mjlab_microduck" / "tasks"
MDP = TASKS / "mdp.py"
CFG = TASKS / "microduck_velocity_env_cfg.py"
BACKUP = ROOT / "out" / "issue46_backup"

MDP_BEGIN = "# >>> ISSUE46 PATCH v1: helpers >>>"
MDP_END = "# <<< ISSUE46 PATCH v1: helpers <<<"
CFG_BEGIN = "# >>> ISSUE46 PATCH v1: opt-in block >>>"
CFG_END = "# <<< ISSUE46 PATCH v1: opt-in block <<<"


# --------------------------------------------------------------------------- #
# text helpers
# --------------------------------------------------------------------------- #
def _load(p: Path) -> tuple[str, str]:
    """Read text verbatim plus the dominant line ending (never convert)."""
    raw = p.read_bytes().decode("utf-8")
    crlf = raw.count("\r\n")
    lf = raw.count("\n") - crlf
    return raw, ("\r\n" if crlf > lf else "\n")


def _save(p: Path, text: str) -> None:
    p.write_bytes(text.encode("utf-8"))


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _strip_block(text: str, begin: str, end: str) -> tuple[str, bool]:
    """Remove a marked block including the markers. Idempotent."""
    i = text.find(begin)
    if i < 0:
        return text, False
    j = text.find(end, i)
    if j < 0:
        raise SystemExit(f"corrupt patch: found begin marker but no end marker: {begin!r}")
    j += len(end)
    # also swallow one trailing newline so reverting is byte-clean
    while j < len(text) and text[j] in "\r\n":
        j += 1
        break
    # and one leading newline if the block was appended after a blank line
    return text[:i] + text[j:], True


# --------------------------------------------------------------------------- #
# payloads
# --------------------------------------------------------------------------- #
def mdp_payload(eol: str) -> str:
    body = '''
def feet_air_time_forward_gated(
    env: ManagerBasedRlEnv,
    sensor_name: str,
    threshold_min: float = 0.05,
    threshold_max: float = 0.5,
    command_name: str | None = None,
    command_threshold: float = 0.5,
    vel_gate_ref: float = 0.15,
    gate_floor: float = 0.3,
) -> torch.Tensor:
    """Upstream ``feet_air_time``, additionally scaled by forward progress.

    Upstream gates on the *command* only: ``scale = (total_command > thr)``. A
    robot told to walk forward that tap-dances in place therefore collects the
    whole air-time reward -- upstream issue #46, the standing-in-place optimum.

    Here the reward is multiplied by
        ``gate_floor + (1 - gate_floor) * _forward_progress_gate(env, vel_gate_ref)``
    which is 1.0 at/above ``vel_gate_ref`` forward speed and ``gate_floor`` when
    the body is not moving. The floor is deliberate: pure multiplicative gating
    removes the only gradient that gets a standing robot to lift a foot at all.
    ``vel_gate_ref <= 0`` disables the gate entirely (old behaviour).

    Signature mirrors upstream so it is a drop-in for ``rewards["air_time"]``.
    """
    from mjlab.tasks.velocity.mdp.rewards import feet_air_time as _feet_air_time

    reward = _feet_air_time(
        env,
        sensor_name=sensor_name,
        threshold_min=threshold_min,
        threshold_max=threshold_max,
        command_name=command_name,
        command_threshold=command_threshold,
    )
    gate = _forward_progress_gate(env, vel_gate_ref)
    if gate is None:
        return reward
    floor = min(max(gate_floor, 0.0), 1.0)
    return reward * (floor + (1.0 - floor) * gate)


def track_linear_velocity_lateral(
    env: ManagerBasedRlEnv,
    std: float,
    command_name: str,
    lateral_scale: float = 3.0,
    asset_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
) -> torch.Tensor:
    """``track_linear_velocity`` with the lateral (y) error weighted up.

    Upstream: ``xy_error = sum(square(cmd[:2] - actual[:2]))`` -- both axes equal.
    On this robot the lateral drift was measured at ~2x the forward progress
    (``microduck-locomotion-diagnosis``), so equal weighting lets "slides
    sideways" score as well as "walks forward". ``lateral_scale=3`` matches that
    report's fix.
    """
    asset: Entity = env.scene[asset_cfg.name]
    command = env.command_manager.get_command(command_name)
    assert command is not None, f"Command '{command_name}' not found."
    actual = asset.data.root_link_lin_vel_b
    fwd_error = torch.square(command[:, 0] - actual[:, 0])
    lat_error = torch.square(command[:, 1] - actual[:, 1])
    z_error = torch.square(actual[:, 2])
    error = fwd_error + lateral_scale * lat_error + z_error
    return torch.exp(-error / std**2)
'''.replace("\n", eol)
    return f"{eol}{MDP_BEGIN}{eol}{body}{MDP_END}{eol}"


def cfg_payload(eol: str) -> str:
    body = '''
    # Upstream microduck_rl issue #46 (open, no maintainer reply):
    # "Velocity-family training converges to standing-in-place across all
    # reward/curriculum variants". Qi-hub-dot/microduck-locomotion-diagnosis
    # reproduced it on the same 4070-8GB/Windows box and isolated three causes:
    #   (1) air_time gates on the command, never on actual forward motion, so
    #       tap-dancing in place earns the largest positive term (weight 3.0);
    #   (2) lateral drift ~2x forward progress while tracking weights both axes
    #       equally, so "slides sideways" scores like "walks forward";
    #   (3) tracking weight 2.0 too weak.  That report: error 0.35 -> 0.21.
    # Off unless MICRODUCK_ISSUE46=1, so the baseline stays reproducible.
    # Local import on purpose: the module has no top-level `os` and adding one
    # would touch a line that is otherwise byte-identical to upstream.
    import os

    _issue46 = os.environ.get("MICRODUCK_ISSUE46", "0") == "1"
    if _issue46:
        cfg.rewards["air_time"].func = microduck_mdp.feet_air_time_forward_gated
        cfg.rewards["air_time"].params["vel_gate_ref"] = float(
            os.environ.get("MICRODUCK_ISSUE46_GATE", "0.15")
        )
        cfg.rewards["air_time"].params["gate_floor"] = float(
            os.environ.get("MICRODUCK_ISSUE46_FLOOR", "0.3")
        )
        cfg.rewards["track_linear_velocity"].func = (
            microduck_mdp.track_linear_velocity_lateral
        )
        cfg.rewards["track_linear_velocity"].params["lateral_scale"] = float(
            os.environ.get("MICRODUCK_ISSUE46_LATERAL", "3.0")
        )
        cfg.rewards["track_linear_velocity"].weight = float(
            os.environ.get("MICRODUCK_ISSUE46_TRACK_W", "4.0")
        )
'''.replace("\n", eol)
    return f"{eol}{CFG_BEGIN}{eol}{body}{CFG_END}{eol}"


# --------------------------------------------------------------------------- #
# actions
# --------------------------------------------------------------------------- #
def check() -> int:
    mdp_text, mdp_eol = _load(MDP)
    cfg_text, cfg_eol = _load(CFG)
    mdp_on = MDP_BEGIN in mdp_text
    cfg_on = CFG_BEGIN in cfg_text
    print(f"mdp.py   {_sha(MDP)}  eol={'CRLF' if mdp_eol == chr(13)+chr(10) else 'LF'}  patch={'ON' if mdp_on else 'off'}")
    print(f"cfg      {_sha(CFG)}  eol={'CRLF' if cfg_eol == chr(13)+chr(10) else 'LF'}  patch={'ON' if cfg_on else 'off'}")
    if mdp_on != cfg_on:
        print("WARNING: half-applied patch (one file has markers, the other does not)")
        return 2
    if mdp_on:
        print("state    APPLIED but inert (MICRODUCK_ISSUE46 unset -> behaviour identical to baseline)")
        print("         enable with MICRODUCK_ISSUE46=1")
    else:
        print("state    NOT applied")
    return 0


def apply() -> int:
    mdp_text, mdp_eol = _load(MDP)
    cfg_text, cfg_eol = _load(CFG)
    if MDP_BEGIN in mdp_text and CFG_BEGIN in cfg_text:
        print("already applied; nothing to do")
        return 0

    BACKUP.mkdir(parents=True, exist_ok=True)
    for p, tag in ((MDP, "mdp.py"), (CFG, "microduck_velocity_env_cfg.py")):
        dst = BACKUP / tag
        if not dst.exists():          # keep the pristine copy, never overwrite it
            shutil.copy2(p, dst)
            print(f"backup   {dst}")

    if MDP_BEGIN not in mdp_text:
        if not mdp_text.endswith(mdp_eol):
            mdp_text += mdp_eol
        mdp_text += mdp_payload(mdp_eol)
        _save(MDP, mdp_text)
        print(f"patched  mdp.py  (+2 helpers)")

    if CFG_BEGIN not in cfg_text:
        anchor = f"{cfg_eol}    return cfg{cfg_eol}"
        n = cfg_text.count(anchor)
        if n != 1:
            raise SystemExit(f"anchor 'return cfg' found {n} times, expected exactly 1")
        cfg_text = cfg_text.replace(anchor, cfg_payload(cfg_eol) + anchor, 1)
        _save(CFG, cfg_text)
        print(f"patched  microduck_velocity_env_cfg.py  (+1 opt-in block)")

    print()
    return check()


def revert() -> int:
    restored = 0
    for p, tag in ((MDP, "mdp.py"), (CFG, "microduck_velocity_env_cfg.py")):
        src = BACKUP / tag
        text, eol = _load(p)
        if src.exists():
            shutil.copy2(src, p)
            print(f"restored {tag} from {src}")
            restored += 1
        else:
            begin, end = (MDP_BEGIN, MDP_END) if tag == "mdp.py" else (CFG_BEGIN, CFG_END)
            text, hit = _strip_block(text, begin, end)
            if hit:
                _save(p, text)
                print(f"stripped markers from {tag}")
                restored += 1
    if not restored:
        print("nothing to revert")
    print()
    return check()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--revert", action="store_true")
    a = ap.parse_args(argv)
    for p in (MDP, CFG):
        if not p.exists():
            raise SystemExit(f"not found: {p}")
    if a.check:
        return check()
    if a.apply:
        return apply()
    return revert()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
