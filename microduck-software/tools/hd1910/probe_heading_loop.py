"""Prove that `rel_heading_envs > 0` really produces a per-step heading loop.

This is the instrument behind the claim that switching the knob on cures the yaw
random walk. It does NOT take that claim on faith: a "policy learns heading"
story would show up only after a full GPU training run, which is exactly when
being wrong is expensive. This runs in seconds on CPU with 8 envs and no policy.

What it measures
----------------
`mjlab/tasks/velocity/mdp/velocity_command.py::_update_command` runs EVERY step:

    heading_error = wrap_to_pi(heading_target - heading_w)
    vel_command_b[heading_ids, 2] = clip(stiffness * heading_error,
                                         ranges.ang_vel_z[0], ranges.ang_vel_z[1])

Three independent assertions, each able to fail on its own:

1. FORMULA MATCH. Recompute the closed form at every step and compare with the
   manager's live `vel_command_b[:, 2]`. With the knob on this must agree to
   float precision (~1e-7). With it off, `vel_command_b[:, 2]` is whatever was
   sampled once per 3-8 s window, so it drifts away from the recomputation as
   `heading_w` moves. Agreement here is real evidence: it can only hold if the
   manager is actually rewriting slot 2 each step.

2. STEP-TO-STEP VARIATION. Standard deviation of cmd[2] over the window must be
   ~0 for the control (constant within a resample window) and clearly non-zero
   for the variant. Catches the case "0 happens to equal clip(...)".

3. FORWARD-BUCKET OVERRIDE. `rel_*` flags are independent Bernoulli draws, so
   some envs are both heading and forward. `_resample_command` gives forward
   envs `wz = 0`; if the heading loop runs `_update_command` afterwards those
   envs must show `wz != 0` while keeping `vx >= 0.3`. This is the accepted cost
   of the variant, made countable instead of asserted.

The venv will be annoyed about a policy-less env, so rows scroll to stderr;
only the verdict table goes to stdout.

Usage
-----
    .venv-mjlab/Scripts/python.exe tools/hd1910/probe_heading_loop.py
    .venv-mjlab/Scripts/python.exe tools/hd1910/probe_heading_loop.py --steps 120 --rel-heading-envs 1.0
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import torch

DEFAULT_TASK = "Mjlab-Velocity-Flat-MicroDuck"
TOL = 1e-6


def wrap_to_pi(x: torch.Tensor) -> torch.Tensor:
    """Mirror of mjlab's `wrap_to_pi` so the recheck is independent of it.

    Deliberately not imported: importing the very function under test would let
    a bug in it cancel out here, exactly the failure mode the ONNX parity tool
    warns about (docs/05-flat-walk.md §10).
    """
    return (x + math.pi) % (2.0 * math.pi) - math.pi


def quat_mul(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """Hamilton product, (w, x, y, z) layout, world-frame rotate when left-multiplied."""
    aw, ax, ay, az = a.unbind(-1)
    bw, bx, by, bz = b.unbind(-1)
    return torch.stack(
        (
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ),
        dim=-1,
    )


def _slider_for(robot, device: str, delta: float, num_envs: int) -> torch.Tensor:
    """Quaternion that rotates a root frame by `delta` about world z."""
    half = torch.full((num_envs,), delta * 0.5, device=device)
    return torch.stack(
        (torch.cos(half), torch.zeros_like(half), torch.zeros_like(half), torch.sin(half)),
        dim=-1,
    )


def _build(rel_heading_envs: float, num_envs: int, seed: int, steps: int,
           device: str, drive_yaw: float = 0.0) -> dict:
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.tasks.registry import load_env_cfg

    env_cfg = load_env_cfg(DEFAULT_TASK, play=False)
    env_cfg.scene.num_envs = num_envs
    env_cfg.seed = seed

    cmd = env_cfg.commands["twist"]
    cmd.rel_heading_envs = rel_heading_envs
    # Pin the command window so every resample happens when we expect it and
    # the "constant within a window" assertion has a well-defined interval.
    cmd.resampling_time_range = (3.0, 3.0)
    # Drop the other diversity buckets: they zero or override slot 2 too, and
    # this probe is about heading alone.
    for knob in ("rel_standing_envs", "rel_forward_envs", "rel_turn_in_place_envs",
                 "rel_world_envs", "init_velocity_prob"):
        if hasattr(cmd, knob):
            setattr(cmd, knob, 0.0)

    env = ManagerBasedRlEnv(cfg=env_cfg, device=device)
    env.reset()
    term = env.command_manager.get_term("twist")
    robot = env.scene["robot"]

    zero = torch.zeros(num_envs, env.action_space.shape[-1], device=device)

    cmd2_hist: list[torch.Tensor] = []
    expect_hist: list[torch.Tensor] = []
    heading_hist: list[torch.Tensor] = []
    for _ in range(steps):
        # Rotate the base about world z before stepping, so `heading_w` sweeps a
        # meaningful arc and the closed loop is exercised far from equilibrium.
        # Left undriven the zero-action base barely moves (measured: 0.024 rad
        # over 90 steps), the predicted cmd[2] varies by only 8e-4, and the
        # "not constant" assertions would pass by a factor of 8 -- technically
        # green, actually fragile. Sliding the heading makes the loop sweep
        # through saturation, which also exposes any sign error.
        if drive_yaw:
            pos = robot.data.root_link_pos_w.detach().clone()
            quat = robot.data.root_link_quat_w.detach().clone()
            lin = robot.data.root_link_lin_vel_w.detach().clone()
            ang = robot.data.root_link_ang_vel_w.detach().clone()
            quat = quat_mul(_slider_for(robot, device, drive_yaw, num_envs), quat)
            root_state = torch.cat((pos, quat, lin, ang), dim=-1)
            robot.write_root_state_to_sim(root_state)
        # Step the sim (zero action) so heading_w actually evolves; the policy is
        # irrelevant here -- we are auditing the command manager, not behaviour.
        env.step(zero)
        heading_w = robot.data.heading_w.detach().clone()
        cmd2 = term.vel_command_b[:, 2].detach().clone()
        expect = torch.clip(
            term.cfg.heading_control_stiffness
            * wrap_to_pi(term.heading_target.detach() - heading_w),
            min=float(term.cfg.ranges.ang_vel_z[0]),
            max=float(term.cfg.ranges.ang_vel_z[1]),
        )
        cmd2_hist.append(cmd2)
        expect_hist.append(expect)
        heading_hist.append(heading_w)

    c = torch.stack(cmd2_hist)      # (steps, num_envs)
    e = torch.stack(expect_hist)    # (steps, num_envs)
    is_head = term.is_heading_env.detach().clone()

    n_head = int(is_head.sum().item())
    if n_head:
        fm = (c[:, is_head] - e[:, is_head]).abs().max().item()
        var = c[:, is_head].std(dim=0).mean().item()
        # Variation of the closed-form prediction, to prove the piece we compare
        # against actually moves (otherwise agreement would be trivial).
        var_exp = e[:, is_head].std(dim=0).mean().item()
    else:
        fm = var = var_exp = float("nan")

    # On non-heading envs the recomputation must NOT describe slot 2 -- that is
    # the control group living inside the same run.
    non_head = ~is_head
    fm_control = (
        (c[:, non_head] - e[:, non_head]).abs().max().item()
        if int(non_head.sum().item())
        else float("nan")
    )
    var_control = (
        c[:, non_head].std(dim=0).mean().item()
        if int(non_head.sum().item())
        else float("nan")
    )

    h = torch.stack(heading_hist)  # (steps, num_envs)

    # Feedback sign, checked LOCALLY rather than by a global correlation.
    #
    # A Pearson corr(heading_w, cmd[2]) looks like the obvious test and is WRONG:
    # once the base turns more than pi, wrap_to_pi folds the error and the pair
    # traces a triangle wave, dragging the correlation up (measured -0.24 at
    # 6.26 rad of travel even though the loop is exactly correct). Instead take
    # it step by step: while the clip is inactive, cmd[2] = k*(target - heading),
    # so d(cmd[2]) and d(heading) must have OPPOSITE signs on every step where
    # heading actually moved. Immune to folding, and it catches a sign-inverted
    # "controller" that would satisfy check 1 word for word.
    corr_heading_cmd2 = float("nan")
    sign_ok = sign_total = 0
    if n_head and steps > 2:
        hm = h[:, is_head]
        dhv = wrap_to_pi(hm[1:] - hm[:-1])
        dcv = c[1:, is_head] - c[:-1, is_head]
        bound = min(abs(float(term.cfg.ranges.ang_vel_z[0])),
                    abs(float(term.cfg.ranges.ang_vel_z[1])))
        prev_err = wrap_to_pi(term.heading_target.detach()[is_head].unsqueeze(0) - hm[:-1])
        unsaturated = (float(term.cfg.heading_control_stiffness) * prev_err).abs() < bound - 1e-6
        moved = dhv.abs() > 1e-9
        mask = unsaturated & moved
        if mask.any():
            agree = torch.sign(dcv[mask]) == -torch.sign(dhv[mask])
            sign_ok = int(agree.sum().item())
            sign_total = int(mask.sum().item())
        if hm.std(dim=0).mean().item() > 1e-9:
            cols = []
            for j in range(hm.shape[1]):
                a, b = hm[:, j], c[:, is_head][:, j]
                if a.std() <= 0 or b.std() <= 0:
                    continue
                cols.append(torch.corrcoef(torch.stack((a, b)))[0, 1].item())
            corr_heading_cmd2 = (sum(cols) / len(cols)) if cols else float("nan")

    return {
        "drive_yaw_per_step_rad": drive_yaw,
        "rel_heading_envs": rel_heading_envs,
        "steps": steps,
        "num_envs": num_envs,
        "n_heading_envs": n_head,
        "n_non_heading_envs": int(non_head.sum().item()),
        "formula_max_abs_err_heading": fm,
        "cmd2_stepstd_mean_heading": var,
        "expected_stepstd_mean_heading": var_exp,
        "formula_max_abs_err_non_heading": fm_control,
        "cmd2_stepstd_mean_non_heading": var_control,
        "corr_heading_cmd2": corr_heading_cmd2,
        "sign_agree_steps": sign_ok,
        "sign_checked_steps": sign_total,
        "sign_agree_frac": (sign_ok / sign_total) if sign_total else None,
        "heading_w_span_rad": float(
            (torch.stack(heading_hist).max(dim=0).values
             - torch.stack(heading_hist).min(dim=0).values).max().item()
        ),
        "stiffness": float(term.cfg.heading_control_stiffness),
        "ranges_ang_vel_z": [float(v) for v in term.cfg.ranges.ang_vel_z],
        "serialized_heading_targets": [
            round(float(v), 4) for v in term.heading_target.detach().cpu()[:4]
        ],
    }


def _overlap_probe(num_envs: int, seed: int, device: str, rel_heading: float) -> dict:
    """Count how vx/wz come out when an env is both heading AND forward.

    Run separately because this probe deliberately re-enables rel_forward_envs,
    whereas the main probe disables every other bucket to isolate heading.
    """
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.tasks.registry import load_env_cfg

    env_cfg = load_env_cfg(DEFAULT_TASK, play=False)
    env_cfg.scene.num_envs = num_envs
    env_cfg.seed = seed
    cmd = env_cfg.commands["twist"]
    cmd.rel_heading_envs = rel_heading
    cmd.rel_forward_envs = 0.5  # exaggerated so the overlap is countable
    cmd.resampling_time_range = (3.0, 3.0)
    for knob in ("rel_standing_envs", "rel_turn_in_place_envs", "rel_world_envs",
                 "init_velocity_prob"):
        if hasattr(cmd, knob):
            setattr(cmd, knob, 0.0)

    env = ManagerBasedRlEnv(cfg=env_cfg, device=device)
    env.reset()
    term = env.command_manager.get_term("twist")
    zero = torch.zeros(num_envs, env.action_space.shape[-1], device=device)
    for _ in range(90):
        env.step(zero)

    both = (term.is_heading_env & term.is_forward_env).detach()
    fwd_only = (term.is_forward_env & ~term.is_heading_env).detach()
    cmd = term.vel_command_b.detach()
    return {
        "rel_heading_envs": rel_heading,
        "rel_forward_envs": 0.5,
        "n_both": int(both.sum().item()),
        "n_forward_only": int(fwd_only.sum().item()),
        "both_vx_min": float(cmd[both, 0].min().item()) if int(both.sum()) else None,
        "both_abs_wz_max": float(cmd[both, 2].abs().max().item()) if int(both.sum()) else None,
        "fwd_only_abs_wz_max": (
            float(cmd[fwd_only, 2].abs().max().item()) if int(fwd_only.sum()) else None
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--num-envs", type=int, default=8)
    ap.add_argument("--steps", type=int, default=90)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--rel-heading-envs", type=float, default=1.0,
                    help="variant value; the control run always uses 0.0")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--drive-yaw", type=float, default=0.02,
                    help="rad/step to rotate the base about z (0 = leave it alone)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    control = _build(0.0, a.num_envs, a.seed, a.steps, a.device, a.drive_yaw)
    variant = _build(a.rel_heading_envs, a.num_envs, a.seed, a.steps, a.device,
                     a.drive_yaw)
    # Deliberately 0.5 regardless of --rel-heading-envs: at 1.0 every forward
    # env is also a heading env, leaving no forward-only control row.
    overlap = _overlap_probe(max(a.num_envs, 32), a.seed, a.device, 0.5)

    checks: list[tuple[str, bool, str]] = []

    def _margin(v: float, thr: float) -> str:
        return f"({v / thr:.0f}x threshold)" if thr else ""

    # 1. Formula match on heading envs must be at machine precision.
    checks.append((
        "variant: cmd[2] == clip(k*wrap(target-heading)) every step",
        variant["n_heading_envs"] > 0
        and variant["formula_max_abs_err_heading"] <= TOL,
        f"max|err| = {variant['formula_max_abs_err_heading']:.3e} "
        f"(tol {TOL:.0e}), {variant['n_heading_envs']} heading envs",
    ))
    checks.append((
        "variant: d(cmd[2]) opposes d(heading) on every unsaturated step",
        variant["sign_checked_steps"] > 0
        and variant["sign_agree_steps"] == variant["sign_checked_steps"],
        f"{variant['sign_agree_steps']}/{variant['sign_checked_steps']} steps agree "
        f"(global corr = {variant['corr_heading_cmd2']:.3f}, deliberately not used: "
        "it folds once heading turns past pi)",
    ))
    # 2. And trivially so -- the target itself must be moving relative to heading.
    checks.append((
        "variant: the closed form is not constant (test does something)",
        variant["expected_stepstd_mean_heading"] > 1e-4,
        f"std of predicted cmd[2] over the window = "
        f"{variant['expected_stepstd_mean_heading']:.3e} "
        f"{_margin(variant['expected_stepstd_mean_heading'], 1e-4)}",
    ))
    checks.append((
        "variant: cmd[2] varies step to step",
        variant["cmd2_stepstd_mean_heading"] > 1e-4,
        f"mean per-env std over {variant['steps']} steps = "
        f"{variant['cmd2_stepstd_mean_heading']:.3e} "
        f"{_margin(variant['cmd2_stepstd_mean_heading'], 1e-4)}",
    ))
    # 3. Negative control: with the knob off there are no heading envs at all and
    #    slot 2 must NOT follow the closed form.
    checks.append((
        "control: zero heading envs exist",
        control["n_heading_envs"] == 0,
        f"n_heading_envs = {control['n_heading_envs']}",
    ))
    checks.append((
        "control: cmd[2] does NOT track the heading error",
        not (control["formula_max_abs_err_non_heading"] <= TOL),
        f"max|err| = {control['formula_max_abs_err_non_heading']:.3e} "
        f"(must be > {TOL:.0e}, actual margin "
        f"{_margin(control['formula_max_abs_err_non_heading'], TOL)})",
    ))
    # 4. The cost, counted rather than asserted.
    checks.append((
        "overlap: heading envs that are also forward keep vx>=0.3",
        overlap["n_both"] == 0 or (overlap["both_vx_min"] or 0.0) >= 0.3 - 1e-6,
        f"n_both = {overlap['n_both']}, min vx = {overlap['both_vx_min']}",
    ))
    checks.append((
        "overlap: those envs LOSE the forward wz=0 (documented cost)",
        overlap["n_both"] == 0 or (overlap["both_abs_wz_max"] or 0.0) > 1e-3,
        f"max |wz| among both = {overlap['both_abs_wz_max']}, "
        f"among forward-only = {overlap['fwd_only_abs_wz_max']}",
    ))

    out = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "task": DEFAULT_TASK,
        "seed": a.seed,
        "control": control,
        "variant": variant,
        "forward_overlap": overlap,
        "checks": [{"check": c, "ok": ok, "detail": d} for c, ok, d in checks],
        "all_passed": all(ok for _, ok, _ in checks),
    }

    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"{'rel_heading_envs':<34} control={control['rel_heading_envs']:<6} "
              f"variant={variant['rel_heading_envs']}")
        print(f"{'heading envs':<34} {control['n_heading_envs']:<6} "
              f"{variant['n_heading_envs']}")
        print(f"{'max|cmd2 - clip(k*err)|':<34} "
              f"{control['formula_max_abs_err_non_heading']:<7.2e} "
              f"{variant['formula_max_abs_err_heading']:.2e}")
        print(f"{'per-env std of cmd[2]':<34} "
              f"{control['cmd2_stepstd_mean_non_heading']:<7.2e} "
              f"{variant['cmd2_stepstd_mean_heading']:.2e}")
        print(f"{'std of predicted cmd[2]':<34} {'-':<7} "
              f"{variant['expected_stepstd_mean_heading']:.2e}")
        print(f"{'heading_w moved (rad)':<34} "
              f"{control['heading_w_span_rad']:<7.3f} "
              f"{variant['heading_w_span_rad']:.3f}")
        print()
        for i, (name, ok, detail) in enumerate(checks, 1):
            print(f"  [{'PASS' if ok else 'FAIL'}] {i}. {name}")
            print(f"         {detail}")
        print()
        print(f"forward x heading overlap ({overlap['n_both']} envs): "
              f"vx min {overlap['both_vx_min']}, max|wz| {overlap['both_abs_wz_max']} "
              f"vs forward-only max|wz| {overlap['fwd_only_abs_wz_max']}")
        print(f"ALL PASSED: {out['all_passed']}")

    outdir = Path("out")
    outdir.mkdir(exist_ok=True)
    p = outdir / "probe_heading_loop.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"probe json -> {p}")
    return 0 if out["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
