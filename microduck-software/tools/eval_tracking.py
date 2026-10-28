#!/usr/bin/env python
"""Does the *same* walking policy survive a command that **changes**?

This is the missing experiment behind "autonomous following" (see
``docs/active/microduck-阶段3-自动跟随.md`` §4). Everything we have measured so far
was taken with a frozen command: ``eval_velocity_in_sim.freeze_command()`` sets

    cmd.resampling_time_range = (duration, duration)

so the command is drawn once and held. Upstream *trains* with
``resampling_time_range = (3.0, 8.0) s`` and all five parameters above are upstream's
real values (``docs/reference/microduck-上游真实配置对照.md:99-112``), which means our
entire evidence base lives in one corner of the command distribution: the corner
where the command **never moves**. Following needs the command to move at ~50 Hz,
which is 150-400x faster than anything the policy was selected on.

This script drives the command itself instead of letting the manager resample it,
and grades the response the way a servo loop is graded:

  * RMSE between commanded and achieved ``v_x`` (and ``w_z``),
  * normalised by the command's own RMS so a constant and a time-varying command
    are comparable,
  * at every lag in ``[0, --max-lag]`` steps, because the step taken at time t
    used the observation made at t-1 (see LAG NOTE below),
  * plus the **additional cost**: action smoothness against a period-0 baseline,
    so "it follows, but it flails" cannot pass.

Design decisions that matter for reading the numbers:

1. **Every env gets the identical command.** The only difference between envs is
   initial conditions, so the per-env spread is exactly the seed sensitivity we
   already measured (CV 1.8% on ``vx_median``). Any larger spread here is real.
2. **Defaults keep ``cmd vx`` inside [0.20, 0.40] m/s** on purpose. Below ~0.15
   the policy is bistable and sometimes stands still (see §6 of the follow-mode
   note / the low-speed dead zone study); a sweep that dips into that region would
   measure the dead zone, not tracking. ``cmd_vx_above_deadzone`` is a gate, not a
   comment.
3. **Survivors only.** An env that terminated mid-window is excluded from every
   tracking number and counted separately: a reset teleports the robot, which is
   a discontinuity no RMSE can be asked to average honestly.
4. **Normalisation uses ``sqrt(mean(cmd^2))``, not the centred RMS.** With
   ``period 0`` the command is constant, a centred RMS is zero, and the baseline
   would divide by ~0. Using the uncentred one lets period 0 (relative steady
   state error) sit on the same axis as period 0.5 (tracking error).
5. The official ``error_vel_xy`` is recorded but is **not the criterion**: its unit
   depends on ``resampling_time_range[1]`` (mjlab
   ``velocity_command.py:61-69``). We pin that divisor to the window so the
   recorded value is at least a true window mean, but our own RMSE is the answer.

LAG NOTE (why the lag search is not cosmetic):
``ManagerBasedRlEnv.step`` applies the action, steps the sim, and only *then* calls
``command_manager.compute(dt)`` followed by ``observation_manager.compute()``
(``manager_based_rl_env.py:449-457``). So observation k carries the command written
at step k, the policy reacts with action_{k+1}, and the velocity measured after
step k+1 already carries roughly 1-2 steps of transport delay. At 50 Hz that is
20-40 ms -- 7-14 deg of phase at ``period 1 s``, but 25-50% of a ``period 0.5 s``
cycle. Searching the lag separates "cannot track" from "tracks, one step late".

Usage:
  # the question itself: does it still follow when the command moves?
  python microduck-software/tools/eval_tracking.py \
      --checkpoint artifacts/flat_walk/checkpoints/model_1250_std004.pt \
      --periods 0 0.5 1 2 5 --waveform sine

  # step inputs instead of sine
  python microduck-software/tools/eval_tracking.py \
      --checkpoint ... --waveform step --periods 1 2 5

Exit code 0 when every requested period grades ``usable``, 1 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Works both from the authoring dir (tools/flat_walk) and from the execution copy
# (microduck-software/tools), which is where `eval_joy_in_sim` actually lives.
for _cand in (
    ROOT / "tools",
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[2] / "microduck-software" / "tools",
):
    if _cand.is_dir():
        sys.path.insert(0, str(_cand))

import torch  # noqa: E402

from eval_joy_in_sim import PLANT_CHOICES, swap_plant  # noqa: E402

try:
    from plant_id import fingerprint as _plant_fingerprint, one_line as _plant_one_line
except Exception as _e:  # never let the stamp take the measurement down
    def _plant_fingerprint():
        return {"name": "unknown", "error": f"plant_id unavailable: {_e!r}"}

    def _plant_one_line():
        return "plant=UNKNOWN (plant_id import failed)"

TASK_DEFAULT = "Mjlab-Velocity-Flat-MicroDuck"
CONTACT_SENSOR = "feet_ground_contact"

WAVEFORMS = ("sine", "step")

# Judgement thresholds, stated here rather than buried in the print block.
# `usable` is deliberately the same bar we would accept for a controller that has
# to keep a target in frame: a third-RMS error still leaves the target visible.
NRMSE_USABLE = 0.40
NRMSE_MARGINAL = 0.70
MAX_TERMINATED_FRAC = 0.05
DEADZONE_VX = 0.15  # below this the walk policy is bistable (see module docstring)


# --------------------------------------------------------------------------- cfg


def neutralize_command(cfg, base_vx: float, base_vy: float, base_wz: float) -> dict:
    """Strip every *training diversity* knob, but do NOT touch the resample window.

    Same reasoning as ``eval_velocity_in_sim.freeze_command``, minus the line that
    pins ``resampling_time_range`` -- here that knob is meaningless because the
    waveform driver replaces ``term.compute()`` entirely. What survives is only
    what could still corrupt the reading *behind* the driver's back:

      * ``rel_*`` / ``init_velocity_prob``: a standing env secretly graded on
        "stand still" would inflate every RMSE, and ``rel_forward_envs`` clamps its
        vx to at least 0.3, which silently rewrites the waveform.
      * the ``standing_envs`` curriculum term, which *rewrites* ``rel_standing_envs``
        on every single step from ``common_step_counter`` -- the one failure mode we
        have already hit once, and the reason this must be a `pop`, not a `set`.
      * the ranges are collapsed onto the waveform's base so that even a stray
        ``_resample_command`` (an env can reset mid-window) writes the base value
        instead of something drawn from the training distribution.
    """
    cmd = cfg.commands["twist"]
    cmd.ranges.lin_vel_x = (base_vx, base_vx)
    cmd.ranges.lin_vel_y = (base_vy, base_vy)
    cmd.ranges.ang_vel_z = (base_wz, base_wz)
    swept = {}
    for knob in [k for k in dir(cmd) if k.startswith("rel_") or k == "init_velocity_prob"]:
        val = getattr(cmd, knob)
        if isinstance(val, (int, float)):
            swept[knob] = float(val)
            setattr(cmd, knob, 0.0)
    still_on = {k: v for k, v in swept.items() if (getattr(cmd, k) or 0.0) != 0.0} or None
    if still_on:
        raise RuntimeError(f"command-diversity knob could not be zeroed: {still_on}")
    # The command class refuses to build unless heading matches heading_command.
    cmd.heading_command = True
    cmd.ranges.heading = (0.0, 0.0)
    cfg.curriculum.pop("standing_envs", None)
    return swept


def override_solver(cfg, iters=None, ls_iters=None) -> dict:
    """Contact solver budget. **The training run used 100/50**, not the task default.

    Evidence: `artifacts/flat_walk/runmeta/variant_meta_vel_defer1500x1000_1025.json`
    lists the training passthrough args and they contain

        --env.sim.mujoco.iterations 100 --env.sim.mujoco.ls-iterations 50

    while `velocity_env_cfg.py:443-448` ships `iterations=10, ls_iterations=20`.
    Isaac Lab's own MicroDuck port raises them for the same reason given in
    `eval_velocity_in_sim.override_solver`: the low budget stops some contact
    solves short. Evaluating a policy at a different solver fidelity than it was
    optimised against is a train/eval mismatch, so this defaults to 100/50 rather
    than to whatever the cfg happens to say.
    """
    before = {
        "iterations": int(cfg.sim.mujoco.iterations),
        "ls_iterations": int(cfg.sim.mujoco.ls_iterations),
    }
    if iters is not None:
        cfg.sim.mujoco.iterations = int(iters)
    if ls_iters is not None:
        cfg.sim.mujoco.ls_iterations = int(ls_iters)
    return {
        "before": before,
        "after": {
            "iterations": int(cfg.sim.mujoco.iterations),
            "ls_iterations": int(cfg.sim.mujoco.ls_iterations),
        },
    }


def drop_pushes(cfg) -> list[str]:
    """Remove the push event -- it trains robustness, it is not asked about here."""
    dropped = [k for k in list(cfg.events.keys()) if "push" in k.lower()]
    for k in dropped:
        cfg.events.pop(k)
    return dropped


def pin_curriculum(env) -> int:
    u = env.unwrapped
    before = int(getattr(u, "common_step_counter", 0))
    u.common_step_counter = 10**9
    return before


# ---------------------------------------------------------------------- waveform


def make_wave(kind: str, base: float, amp: float, period: float, dt: float):
    """Return ``f(step_index) -> command value`` for one axis.

    ``period <= 0`` means "hold the base" -- that is the baseline every other
    period is compared against, and it is what all our previous measurements were.
    """
    if period <= 0 or amp == 0.0:
        return lambda _i: base
    steps = max(int(round(period / dt)), 2)

    if kind == "sine":
        def f(i: int) -> float:
            return base + amp * math.sin(2.0 * math.pi * i / steps)
        return f

    if kind == "step":
        half = steps // 2

        def f(i: int) -> float:
            # Square wave, alternating every half period: the input a following
            # controller actually produces when the target re-appears on the other
            # side of the frame.
            return base + amp * (1.0 if (i % steps) < half else -1.0)
        return f

    raise ValueError(f"unknown waveform {kind!r}; choose from {WAVEFORMS}")


class WaveDriver:
    """Replace ``UniformVelocityCommand.compute`` with a deterministic waveform.

    Why replace rather than configure: there is no configuration that produces a
    1-second-period command. ``resampling_time_range`` draws a *uniform random*
    command every window and holds it, which is a step function of random
    amplitude; there is nothing to set that makes it a sine.

    The instance attribute shadows the bound method (instance dict beats a
    non-data descriptor), so ``CommandManager.compute`` calls this instead. Nothing
    else in the manager touches ``vel_command_b``: ``_update_command`` -- which
    applies standing/heading/world overrides -- is never reached, and the knobs
    that would have made those matter are already zeroed (double protection, see
    neutralize_command).

    ``_update_metrics()`` is still called so the official ``error_vel_xy`` keeps
    accumulating. Its divisor is ``resampling_time_range[1] / step_dt``, which the
    caller pinned to the window length, so the accumulated value is a true window
    mean rather than an arbitrary unit.
    """

    def __init__(self, term, waves, dt: float):
        self.term = term
        self.waves = waves
        self.dt = dt
        self.n = 0

    def __call__(self, dt: float) -> None:
        if dt and dt > 0:
            buf = self.term.vel_command_b
            vals = [w(self.n) for w in self.waves]
            with torch.no_grad():
                for axis, v in enumerate(vals):
                    buf[:, axis] = float(v)
            self.n += 1
        self.term._update_metrics()


# ----------------------------------------------------------------------- analyse


def _axis_report(cmd: torch.Tensor, meas: torch.Tensor, dt: float, max_lag: int,
                 period: float) -> dict:
    """Tracking quality for one axis, one env.

    ``cmd``/``meas`` are 1-D float64 series. The gain is fitted rather than fixed
    at 1.0 because the policy already under-shoots a constant command by ~22%
    (vx = 0.659*cmd - 0.018 at std^2=0.10; ratio 0.78 at std 0.2). Folding that
    known static gain into the error would measure tracking *and* calibration at
    once, and only the first one is the question here.
    """
    t = int(cmd.numel())
    out: dict = {"n": t}
    if t < 4:
        return out

    def _fit(a: torch.Tensor, b: torch.Tensor) -> tuple[float, float, float]:
        den = float((a * a).mean())
        gain = float((a * b).mean() / den) if den > 1e-12 else 0.0
        resid = b - gain * a
        return gain, float(resid.mean()), float(torch.sqrt((resid * resid).mean()))

    best = None
    for lag in range(0, min(max_lag, t // 2) + 1):
        a = cmd[: t - lag]
        b = meas[lag:]
        gain, bias, rmse = _fit(a, b)
        if best is None or rmse < best[2]:
            best = (lag, gain, rmse, bias)
    if best is None:
        return out

    lag, gain, rmse, bias = best
    g0, b0, r0 = _fit(cmd, meas)
    rms_cmd = float(torch.sqrt((cmd * cmd).mean()))
    norm = rms_cmd if rms_cmd > 1e-9 else 1.0
    out.update(
        lag_steps_best=lag,
        lag_s_best=lag * dt,
        phase_lag_deg=(360.0 * lag * dt / period) if period > 0 else None,
        nrmse_best=rmse / norm,
        gain_best=gain,
        bias_best=bias,
        nrmse_lag0=r0 / norm,
        gain_lag0=g0,
        bias_lag0=b0,
        # How much of the error is a *delay* rather than a magnitude failure:
        # 1 means "perfect if you allow the lag", 0 means "never gets there".
        lag_explains=(1.0 - (rmse / r0) if r0 > 1e-9 else None),
        rms_cmd=rms_cmd,
        cmd_min=float(cmd.min()),
        cmd_max=float(cmd.max()),
        meas_mean=float(meas.mean()),
        cmd_mean=float(cmd.mean()),
    )
    return out


def _spread(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    x = torch.tensor(vals, dtype=torch.float64)
    n = int(x.numel())
    sd = float(x.std(unbiased=True)) if n > 1 else None
    q = torch.quantile(x, torch.tensor([0.1, 0.5, 0.9], dtype=torch.float64)).tolist()
    return {
        "n": n,
        "p10": q[0], "p50": q[1], "p90": q[2],
        "mean": float(x.mean()),
        "std": sd,
        "sem": (sd / math.sqrt(n)) if sd is not None else None,
    }


# --------------------------------------------------------------------------- run


def run_one(task_id, checkpoint, num_envs, seconds, warmup_s, device, plant,
            waveform, period, vx_base, vx_amp, vy_base, vy_amp, wz_base, wz_amp,
            max_lag, seed, solver_iters, solver_ls):
    from dataclasses import asdict

    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.utils.torch import configure_torch_backends

    configure_torch_backends()
    if seed is not None:
        torch.manual_seed(seed)

    env_cfg = load_env_cfg(task_id, play=False)
    agent_cfg = load_rl_cfg(task_id)
    env_cfg.scene.num_envs = num_envs

    swept = neutralize_command(env_cfg, vx_base, vy_base, wz_base)
    dropped = drop_pushes(env_cfg)
    solver = override_solver(env_cfg, solver_iters, solver_ls)

    plant_info = None
    if plant != "default":
        plant_info = swap_plant(env_cfg, plant)

    # Keep the episode longer than the window: a timeout reset would otherwise
    # cut the run in half and the waveform restart would be counted as error.
    ep_before = getattr(env_cfg, "episode_length_s", None)
    try:
        env_cfg.episode_length_s = float(seconds) + 2.0
    except Exception:  # noqa: BLE001
        pass
    ep_after = getattr(env_cfg, "episode_length_s", None)

    env = ManagerBasedRlEnv(cfg=env_cfg, device=device)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    runner_cls = load_runner_cls(task_id) or MjlabOnPolicyRunner
    runner = runner_cls(env, asdict(agent_cfg), device=device)
    runner.load(checkpoint, load_cfg={"actor": True}, strict=True, map_location=device)
    policy = runner.get_inference_policy(device=device)

    step_dt = float(env.unwrapped.step_dt)

    u = env.unwrapped
    term = u.command_manager.get_term("twist")
    # Make the official accumulator a true window mean (it divides by
    # resampling_time_range[1] / step_dt and never resets except on env reset).
    term.cfg.resampling_time_range = (float(seconds), float(seconds))
    waves = [
        make_wave(waveform, vx_base, vx_amp, period, step_dt),
        make_wave(waveform, vy_base, vy_amp, period, step_dt),
        make_wave(waveform, wz_base, wz_amp, period, step_dt),
    ]
    driver = WaveDriver(term, waves, step_dt)
    term.compute = driver

    obs, _ = env.reset()
    counter_before = pin_curriculum(env)

    robot = u.scene["robot"]
    contact = u.scene[CONTACT_SENSOR]
    dev = u.device
    n_steps = int(round(seconds / step_dt))
    n_warm = int(round(warmup_s / step_dt))

    cmd_h, vx_h, vy_h, wz_h, up_h = [], [], [], [], []
    found_h = []
    metric_h: dict[str, list[float]] = {}
    fell = torch.zeros(num_envs, dtype=torch.bool, device=dev)

    def _read_metrics() -> dict[str, float]:
        out: dict[str, float] = {}
        try:
            mm = u.metrics_manager
            if not mm.active_terms:
                return out
            for name, values in mm.get_active_iterable_terms(0):
                if values:
                    out[name] = float(values[0])
        except Exception:  # noqa: BLE001
            pass
        return out

    with torch.no_grad():
        for _k in range(n_steps):
            obs, _rew, dones, extras = env.step(policy(obs))
            # Re-pin every step: the curriculum manager advances the counter, and a
            # reset must not drag a term back to an earlier stage.
            u.common_step_counter = 10**9

            d = robot.data
            cmd_h.append(term.vel_command_b[:, :3].clone())
            vx_h.append(d.root_link_lin_vel_b[:, 0].clone())
            vy_h.append(d.root_link_lin_vel_b[:, 1].clone())
            wz_h.append(d.root_link_ang_vel_b[:, 2].clone())
            up_h.append((-d.projected_gravity_b[:, 2]).clone())
            found_h.append((contact.data.found > 0).float().clone())

            timeouts = extras.get("time_outs")
            terminated = dones.bool() & (~timeouts.bool() if timeouts is not None else False)
            fell |= terminated

            for name, value in _read_metrics().items():
                metric_h.setdefault(name, []).append(value)

    cmd_t = torch.stack(cmd_h).double()   # [T, N, 3]
    vx_t = torch.stack(vx_h).double()
    vy_t = torch.stack(vy_h).double()
    wz_t = torch.stack(wz_h).double()
    up_t = torch.stack(up_h).double()
    found_t = torch.stack(found_h).double()  # [T, N, 2]

    expected_last = torch.tensor(
        [w(n_steps - 1) for w in waves], dtype=cmd_t.dtype, device=cmd_t.device
    )
    last_step_cmd = cmd_t[-1, 0, :]
    uniqq = sorted({round(float(x), 6) for x in torch.unique(cmd_t[..., 0])})

    # ---- survivors only (see module docstring, point 3)
    alive = ~fell
    idx = alive.nonzero(as_tuple=False).flatten().tolist()
    terminated_frac = float(fell.float().mean())

    vx_rep, wz_rep = [], []
    for e in idx:
        vx_rep.append(_axis_report(cmd_t[n_warm:, e, 0], vx_t[n_warm:, e],
                                   step_dt, max_lag, period))
        if wz_amp != 0.0:
            wz_rep.append(_axis_report(cmd_t[n_warm:, e, 2], wz_t[n_warm:, e],
                                       step_dt, max_lag, period))

    def _agg(reports: list[dict], key: str) -> dict:
        return _spread([r[key] for r in reports if key in r])

    vx_agg = {k: _agg(vx_rep, k) for k in
              ("nrmse_best", "nrmse_lag0", "lag_s_best", "phase_lag_deg",
               "gain_best", "gain_lag0", "bias_best", "lag_explains", "meas_mean")}
    wz_agg = ({k: _agg(wz_rep, k) for k in
               ("nrmse_best", "nrmse_lag0", "lag_s_best", "gain_best", "lag_explains")}
              if wz_amp != 0.0 else None)

    # Duty cycle: fraction of time a foot is in contact, over both feet. A policy
    # that has given up lifting its feet reads nearly 1.0 -- the same signature the
    # low-speed dead zone study found at cmd 0.12 (air time 0.040 s, out of the
    # air_time reward window).
    duty = found_t[n_warm:][:, idx, :].mean(dim=(0, 2)) if idx else None

    metrics = {k: float(sum(v) / len(v)) for k, v in metric_h.items() if v}

    def _pk(k: str, dflt=None):
        return vx_agg.get(k, {}).get("p50", dflt)

    nrmse = _pk("nrmse_best")
    nrmse0 = _pk("nrmse_lag0")
    cmd_vx_min = None if not idx else float(cmd_t[n_warm:, idx, 0].min())
    gates = {
        # Measurement integrity first -- if the command was not ours, nothing below means anything.
        "waveform_injected_ok": bool(abs(float(last_step_cmd[0]) - float(expected_last[0])) <= 1e-6
                                     and abs(float(last_step_cmd[2]) - float(expected_last[2])) <= 1e-6),
        # Keep the experiment inside the region where the policy is monostable.
        "cmd_vx_above_deadzone": (bool(cmd_vx_min >= DEADZONE_VX)
                                  if (cmd_vx_min is not None and vx_base != 0) else None),
        "survivors_enough": bool(len(idx) >= max(4, 0.5 * num_envs)),
        "no_fall": bool(terminated_frac < MAX_TERMINATED_FRAC),
        "stays_upright": (bool(float(up_t[:, idx].mean()) > 0.90) if idx else None),
        "tracks_period": (bool(nrmse <= NRMSE_USABLE) if nrmse is not None else None),
        # A policy that follows only after 0.4 s of lag is not following: the lag
        # must be a transport delay, not the whole response.
        "lag_is_transport_delay": (bool(_pk("lag_s_best", 1.0) <= 0.2)
                                   if period > 0 else None),
    }
    verdict = None
    if nrmse is not None:
        if nrmse <= NRMSE_USABLE and terminated_frac < MAX_TERMINATED_FRAC:
            verdict = "usable"
        elif nrmse <= NRMSE_MARGINAL:
            verdict = "marginal"
        else:
            verdict = "fail"
    if not gates["waveform_injected_ok"]:
        verdict = "invalid"

    env.close()

    return {
        "task": task_id,
        "checkpoint": str(checkpoint),
        "num_envs": num_envs,
        "seconds": seconds,
        "warmup_s": warmup_s,
        "step_dt": step_dt,
        "device": device,
        "plant": plant,
        "plant_info": plant_info,
        # Which physical plant produced this reading. cfg/mdp hashes do NOT cover
        # it: the actuator lives one import deeper, in microduck_constants._BAM_ACTUATOR_KWARGS.
        # Swapping xl330(kp_fw 200) -> hd1910(kp_fw 32) moved cmd-0.4 vx 0.316 -> 0.109
        # and falls 0% -> 100% with every other recorded fingerprint unchanged.
        "plant_fingerprint": _plant_fingerprint(),
        "solver": solver,
        "device_name": torch.cuda.get_device_name(device) if str(device).startswith("cuda") else str(device),
        "seed": seed,
        "swept_command_knobs": swept,
        "dropped_events": dropped,
        "curriculum_counter_before_pin": counter_before,
        "episode_length_s": {"before": ep_before, "after": ep_after},
        "waveform": waveform,
        "period_s": period,
        "amp": {"vx": vx_amp, "vy": vy_amp, "wz": wz_amp},
        "base": {"vx": vx_base, "vy": vy_base, "wz": wz_base},
        "max_lag_steps": max_lag,
        "command_check": {
            "uniq_cmd_vx": uniqq[:12],
            "n_uniq_cmd_vx": len(uniqq),
            "last_cmd_env0": [round(float(x), 6) for x in last_step_cmd],
            "expected_last": [round(float(x), 6) for x in expected_last],
        },
        "survivors": len(idx),
        "terminated_frac": terminated_frac,
        "upright_mean": float(up_t[:, idx].mean()) if idx else None,
        "vx_tracking": vx_agg,
        "wz_tracking": wz_agg,
        "contact_duty_median": float(duty.median()) if (duty is not None and duty.numel()) else None,
        "metrics_env0": metrics,
        "headline": {
            "nrmse_vx_best": nrmse,
            "nrmse_vx_lag0": nrmse0,
            "lag_s": _pk("lag_s_best"),
            "phase_lag_deg": _pk("phase_lag_deg"),
            "gain": _pk("gain_best"),
        },
        "gates": gates,
        "verdict": verdict,
        "passed": [k for k, v in gates.items() if v],
        "failed": [k for k, v in gates.items() if v is False],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Time-varying command tracking test for a walking policy.")
    ap.add_argument("--task", default=TASK_DEFAULT)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--num-envs", type=int, default=32,
                    help="32 is the annotated exception for flat gait sweeps")
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--warmup", type=float, default=2.0,
                    help="discard this much at the start (reset transient)")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--waveform", default="sine", choices=list(WAVEFORMS))
    ap.add_argument("--periods", type=float, nargs="+", default=[0.0, 0.5, 1.0, 2.0, 5.0],
                    help="command period in seconds; 0 = frozen baseline")
    ap.add_argument("--vx-base", type=float, default=0.30)
    ap.add_argument("--vx-amp", type=float, default=0.10)
    ap.add_argument("--vy-base", type=float, default=0.0)
    ap.add_argument("--vy-amp", type=float, default=0.0)
    ap.add_argument("--wz-base", type=float, default=0.0)
    ap.add_argument("--wz-amp", type=float, default=0.6)
    ap.add_argument("--max-lag", type=int, default=20,
                    help="max transport delay to search, in steps (20 = 0.4 s @50 Hz)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--plant", default="default", choices=list(PLANT_CHOICES))
    ap.add_argument("--solver-iters", type=int, default=100,
                    help="training used 100; the flat cfg ships 10")
    ap.add_argument("--solver-ls", type=int, default=50,
                    help="training used 50; the flat cfg ships 20")
    ap.add_argument("--require-baseline", action="store_true",
                    help="exit non-zero if the period-0 baseline itself is not healthy "
                         "(falls / does not reach the command)")
    ap.add_argument("--out", default=None, help="write the full JSON here")
    ap.add_argument("--csv", default=None, help="write one row per period here")
    ap.add_argument("--json-only", action="store_true")
    a = ap.parse_args()

    results = []
    for period in a.periods:
        r = run_one(a.task, a.checkpoint, a.num_envs, a.seconds, a.warmup, a.device,
                    a.plant, a.waveform, period, a.vx_base, a.vx_amp,
                    a.vy_base, a.vy_amp, a.wz_base, a.wz_amp, a.max_lag, a.seed,
                    a.solver_iters, a.solver_ls)
        results.append(r)

    baseline = next((r for r in results if r["period_s"] == 0.0), None)
    if baseline:
        b = baseline["metrics_env0"]
        for r in results:
            if r is baseline:
                r["cost_vs_baseline"] = {"is_baseline": True}
                continue
            m = r["metrics_env0"]
            r["cost_vs_baseline"] = {
                k: (None if k not in b or not b[k] else m.get(k, 0.0) / b[k])
                for k in ("mean_action_rate", "mean_action_acc", "mean_dof_acc")
                if k in m or k in b
            }

    if a.out:
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {p}")
    if a.csv:
        p = Path(a.csv)
        p.parent.mkdir(parents=True, exist_ok=True)
        cols = ["period_s", "verdict", "nrmse_vx_best", "nrmse_vx_lag0", "lag_s",
                "phase_lag_deg", "gain", "terminated_frac", "survivors",
                "contact_duty_median", "n_uniq_cmd_vx"]
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for r in results:
                h = r["headline"]
                w.writerow([r["period_s"], r["verdict"],
                            h["nrmse_vx_best"], h["nrmse_vx_lag0"], h["lag_s"],
                            h["phase_lag_deg"], h["gain"], r["terminated_frac"],
                            r["survivors"], r["contact_duty_median"],
                            r["command_check"]["n_uniq_cmd_vx"]])
        print(f"wrote {p}")

    if a.json_only:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0 if all(r["verdict"] == "usable" for r in results) else 1

    print()
    print("=" * 96)
    print(f"checkpoint  {Path(a.checkpoint).name}   plant={a.plant}   "
          f"{a.num_envs} envs x {a.seconds:.0f}s (warmup {a.warmup:.0f}s)   seed={a.seed}")
    print(f"plant       {_plant_one_line()}")
    print(f"waveform    {a.waveform}  vx {a.vx_base:+.2f}±{a.vx_amp:.2f}  "
          f"vy {a.vy_base:+.2f}±{a.vy_amp:.2f}  wz {a.wz_base:+.2f}±{a.wz_amp:.2f} m/s")
    print(f"step_dt     {results[0]['step_dt']:.4f}s  max lag {a.max_lag} steps")
    sv = results[0]["solver"]
    print(f"solver      iters {sv['before']['iterations']} -> {sv['after']['iterations']}   "
          f"ls {sv['before']['ls_iterations']} -> {sv['after']['ls_iterations']}   "
          f"device {results[0]['device_name']}")
    print(f"knobs zeroed {sorted(results[0]['swept_command_knobs'])}")
    print(f"dropped     {results[0]['dropped_events'] or 'none'}")
    print("-" * 96)
    hdr = (f"{'period':>7} {'nRMSE_best':>11} {'nRMSE_lag0':>11} {'lag':>7} {'phase':>8} "
           f"{'gain':>6} {'dead':>6} {'surv':>5} {'duty':>6} {'VERDICT':>9}")
    print(hdr)
    print("-" * 96)
    for r in results:
        h = r["headline"]
        pd = "base" if r["period_s"] == 0 else f"{r['period_s']:.2f}s"
        nb = "n/a" if h["nrmse_vx_best"] is None else f"{h['nrmse_vx_best']:.3f}"
        n0 = "n/a" if h["nrmse_vx_lag0"] is None else f"{h['nrmse_vx_lag0']:.3f}"
        lg = "n/a" if h["lag_s"] is None else f"{h['lag_s']*1000:.0f}ms"
        ph = "n/a" if h["phase_lag_deg"] is None else f"{h['phase_lag_deg']:.0f}deg"
        gn = "n/a" if h["gain"] is None else f"{h['gain']:.2f}"
        print(f"{pd:>7} {nb:>11} {n0:>11} {lg:>7} {ph:>8} {gn:>6} "
              f"{r['terminated_frac']*100:>5.1f}% {r['survivors']:>5} "
              f"{(r['contact_duty_median'] if r['contact_duty_median'] is not None else float('nan')):>6.2f} "
              f"{str(r['verdict']):>9}")
    print("-" * 96)
    for r in results:
        tag = "BASE" if r["period_s"] == 0 else f"T={r['period_s']:.2f}s"
        cost = r.get("cost_vs_baseline") or {}
        ratio = {k: v for k, v in cost.items() if isinstance(v, float)}
        extra = ""
        if ratio:
            extra = "  cost vs base: " + "  ".join(f"{k} x{v:.2f}" for k, v in ratio.items())
        print(f"  [{tag:>7}] inj_ok={r['gates']['waveform_injected_ok']}  "
              f"n_uniq_cmd_vx={r['command_check']['n_uniq_cmd_vx']}"
              f"{extra}")
    print("=" * 96)
    # The baseline is the health check for the whole sweep. If the policy cannot hold a
    # CONSTANT command here, every tracking number below measures falling, not tracking --
    # and the honest answer is "this instrument is broken", not "the policy cannot follow".
    healthy = None
    if baseline is not None:
        b = baseline
        healthy = bool(b["terminated_frac"] < MAX_TERMINATED_FRAC
                       and (b["headline"]["nrmse_vx_best"] or 9.9) <= NRMSE_USABLE)
        print(f"baseline    terminated {b['terminated_frac']*100:.1f}%  "
              f"survivors {b['survivors']}/{a.num_envs}  "
              f"nRMSE {b['headline']['nrmse_vx_best']}  -> "
              f"{'HEALTHY' if healthy else 'NOT HEALTHY'}")
    if healthy is False:
        print()
        print("  **********************************************************************")
        print("  * The period-0 baseline does not hold even a CONSTANT command here.   *")
        print("  * Every number above describes falling, not tracking. Fix the baseline *")
        print("  * (wrong rollout fidelity / machine) before believing any period.      *")
        print("  **********************************************************************")

    bad = [r for r in results if r["period_s"] != 0 and r["verdict"] != "usable"]
    unusable_instrument = (healthy is False and a.require_baseline)
    if healthy is not False:
        if baseline is not None and len(results) > 1:
            fast = [r for r in results if 0 < r["period_s"] <= 2.0]
        if all(r["verdict"] == "usable" for r in fast) and fast:
            print("=> path ①: nothing to change; the current checkpoint already runs following.")
        elif any(r["verdict"] == "usable" for r in results):
            print("=> path ② candidate: it survives slow commands only -> consider "
                  "resampling_time_range ~ [0.1, 0.5] and RETRAIN FROM SCRATCH.")
        else:
            print("=> path ③: no period tracks -> a high-rate follower needs a new low-level policy.")
    if unusable_instrument:
        print("=> INSTRUMENT NOT HEALTHY: baseline failed; nothing above is usable.")
        return 2
    if bad:
        print(f"   {len(bad)} period(s) not usable: "
              + ", ".join(("base" if r["period_s"] == 0 else f"{r['period_s']}s") for r in bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
