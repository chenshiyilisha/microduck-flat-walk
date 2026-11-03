"""Verify that a finished run really is the reward-free control arm.

Why this exists
---------------
The A/B "did the heading reward help?" only means something if the two arms
differ in nothing but the reward terms. Twice in this project a run's name
claimed one recipe while params/ said another:

  * 2026-11-02 21:26 `p8head_030_4096x3000`: launched with only
    --rel-heading-envs 0.30. `--ang-vel-z-clip` was read only inside the reward
    branch, so the flag did nothing and the run trained on +-1.0 while the name
    said 030. Same name as the 2026-11-03 reward arm, different plant-side
    recipe.
  * 2026-10-xx: scripts that "passed the heading knob" but never added the two
    reward terms (fixed in explore_heading.sh).

So the arm is defined by what is in `params/env.yaml`, not by the script, the
run name, or the command line. This checker reads the run directory and
refuses to accept a control arm that carries any heading reward or a turn range
that differs from the reward arm.

YAML note: mjlab writes `!!python/tuple` / `!!python/name:` /
`!!python/object/apply:` tags that SafeLoader cannot construct, and the object
graph is not needed here -- only scalars and nested keys. Stripping the tags
turns them into plain lists/dicts, which is enough to read every field below.

Usage
    python tools/hd1910/check_control_arm.py --run-dir <dir> \\
        --expect-abs-envs 4096 --expect-iters 3000 --expect-seed 42 \\
        --expect-rel-heading 0.30 --expect-ang-vel-z 0.5
    python tools/hd1910/check_control_arm.py --selftest
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

LOGS = Path("logs/rsl_rl/microduck_velocity_hd1910")
REWARD_ARM = "2026-11-03_08-33-18_p8head_030_4096x3000"
NO_REWARD_WIDE_TURN_ARM = "2026-11-02_21-26-53_p8head_030_4096x3000"
TAG_RE = re.compile(r"!!python/[A-Za-z0-9_./]+(?::[^\s]*)?")


def load_yaml(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    return yaml.safe_load(TAG_RE.sub("", raw))


def find_run(name: str) -> Path | None:
    hits = sorted(LOGS.glob(f"*_{name}")) or sorted(LOGS.glob(f"*{name}*"))
    return hits[-1] if hits else None


def as_pair(v) -> tuple[float, float]:
    lo, hi = v
    return (float(lo), float(hi))


def check(run_dir: Path, *, envs: int, iters: int, seed: int,
          rel_heading: float, clip: float) -> list[str]:
    """Return a list of failures; empty means the run is the control arm."""
    bad: list[str] = []
    env_p = run_dir / "params" / "env.yaml"
    agent_p = run_dir / "params" / "agent.yaml"
    for p in (env_p, agent_p):
        if not p.exists():
            return [f"missing {p} (run died before writing params?)"], {}
    env = load_yaml(env_p)
    agent = load_yaml(agent_p)

    rewards = env.get("rewards") or {}
    curriculum = env.get("curriculum") or {}
    extra_rewards = sorted(k for k in rewards if "heading" in k)
    extra_curriculum = sorted(k for k in curriculum if "heading" in k)
    if extra_rewards:
        bad.append(f"rewards carry heading terms {extra_rewards} -- this is not "
                   f"the reward-free arm")
    if extra_curriculum:
        bad.append(f"curriculum carries heading terms {extra_curriculum} -- this "
                   f"is not the reward-free arm")

    twist = (env.get("commands") or {}).get("twist") or {}
    got_rel = twist.get("rel_heading_envs")
    got_range = twist.get("ranges", {}).get("ang_vel_z")
    if got_rel is None or abs(float(got_rel) - rel_heading) > 1e-9:
        bad.append(f"commands.twist.rel_heading_envs = {got_rel}, expected {rel_heading}")
    want_range = (-clip, clip)
    if got_range is None or as_pair(got_range) != want_range:
        bad.append(f"commands.twist.ranges.ang_vel_z = {got_range}, expected "
                   f"{want_range} -- a control arm with a wider turn range differs "
                   f"from the reward arm in more than the reward")

    got_envs = (env.get("scene") or {}).get("num_envs")
    if int(got_envs) != envs:
        bad.append(f"scene.num_envs = {got_envs}, expected {envs}")

    got_iters = agent.get("max_iterations")
    if int(got_iters) != iters:
        bad.append(f"agent.max_iterations = {got_iters}, expected {iters}")
    got_seed = agent.get("seed")
    if int(got_seed) != seed:
        bad.append(f"agent.seed = {got_seed}, expected {seed} (same seed keeps the "
                   f"two arms' initial conditions identical)")

    # not fatal, but the reason the range matters: cmd[2] is clipped at this bound
    stiff = twist.get("heading_control_stiffness")
    return bad, {"rel_heading_envs": got_rel, "ang_vel_z": got_range,
                 "heading_stiffness": stiff, "envs": got_envs, "iters": got_iters,
                 "seed": got_seed, "heading_rewards": extra_rewards or None}


def report(run_dir: Path, bad: list[str], info: dict) -> int:
    print(f"run: {run_dir}")
    if info:
        print(f"  envs={info['envs']} iters={info['iters']} seed={info['seed']} "
              f"rel_heading={info['rel_heading_envs']} ang_vel_z={info['ang_vel_z']} "
              f"stiffness={info['heading_stiffness']}")
        print(f"  heading reward terms: {info['heading_rewards'] or 'none'}")
    for b in bad:
        print(f"  FAIL {b}")
    if bad:
        print(f"{len(bad)} check(s) failed")
        return 2
    print("  ok: reward-free control arm, turn range matches the reward arm")
    return 0


def selftest() -> int:
    fails = 0

    def one(label: str, run_dir: Path, expect_rc: int, **kw) -> None:
        nonlocal fails
        try:
            bad, info = check(run_dir, **kw)
            rc = 2 if bad else 0
        except Exception as exc:  # noqa: BLE001 - a crash is also a failure
            bad, info, rc = [f"{type(exc).__name__}: {exc}"], {}, 2
        ok = rc == expect_rc
        if not ok:
            fails += 1
        why = "" if ok else "  <<< " + "; ".join(bad[:2])
        print(f"[{'ok' if ok else 'FAIL'}] {label}{why}")

    base = dict(envs=4096, iters=3000, seed=42, rel_heading=0.30, clip=0.5)
    reward_arm = find_run(REWARD_ARM)
    wide_arm = find_run(NO_REWARD_WIDE_TURN_ARM)

    # 1) negative control: the reward arm must be rejected (heading rewards)
    if reward_arm:
        one("t1 奖励臂必须被拒（带 heading 奖励）", reward_arm, 2, **base)
        bad, _ = check(reward_arm, **base)
        if not any("heading terms" in b for b in bad):
            fails += 1
            print("[FAIL] t1 红的原因不是奖励项，而是别的检查先炸了")
        else:
            print("[ok] t1 红在奖励项上（不是撞到别处）")
    else:
        fails += 1
        print("[FAIL] t1 找不到奖励臂目录，无法做负对照")

    # 2) negative control: no rewards but +-1.0 turn range must be rejected --
    #    this is the "flag silently ignored" case, the reason the range is checked
    if wide_arm:
        one("t2 无奖励但 ±1.0 转向范围必须被拒", wide_arm, 2, **base)
        bad, _ = check(wide_arm, **base)
        if not any("ang_vel_z" in b for b in bad):
            fails += 1
            print("[FAIL] t2 红的原因不是转向范围")
        else:
            print("[ok] t2 红在转向范围上")
    else:
        fails += 1
        print("[FAIL] t2 找不到 11-02 run 目录，无法做负对照")

    # 3) positive control: same as t2 but with the range patched to +-0.5 must pass,
    #    otherwise the checker could be "red for everything" and prove nothing.
    if wide_arm:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / wide_arm.name
            (tmp / "params").mkdir(parents=True)
            for f in ("env.yaml", "agent.yaml"):
                shutil.copy(wide_arm / "params" / f, tmp / "params" / f)
            txt = (tmp / "params" / "env.yaml").read_text(encoding="utf-8")
            patched = txt.replace("ang_vel_z: !!python/tuple\n      - -1.0\n      - 1.0",
                                  "ang_vel_z: !!python/tuple\n      - -0.5\n      - 0.5", 1)
            if patched == txt:
                fails += 1
                print("[FAIL] t3 没能改写 ±1.0 -> ±0.5（格式变了？），正对照未执行")
            else:
                (tmp / "params" / "env.yaml").write_text(patched, encoding="utf-8")
                one("t3 同样的 run 把转向范围改成 ±0.5 后必须通过", tmp, 0, **base)

    # 4) seed/iters changes must be caught (the arms have to share them)
    if wide_arm:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / wide_arm.name
            (tmp / "params").mkdir(parents=True)
            for f in ("env.yaml", "agent.yaml"):
                shutil.copy(wide_arm / "params" / f, tmp / "params" / f)
            txt = (tmp / "params" / "env.yaml").read_text(encoding="utf-8")
            (tmp / "params" / "env.yaml").write_text(
                txt.replace("ang_vel_z: !!python/tuple\n      - -1.0\n      - 1.0",
                            "ang_vel_z: !!python/tuple\n      - -0.5\n      - 0.5", 1),
                encoding="utf-8")
            one("t4 其余都对但 seed 不同必须被拒", tmp, 2,
                **{**base, "seed": 7})

    print(f"\nselftest: {'all green' if fails == 0 else f'{fails} check(s) FAILED'}")
    return 0 if fails == 0 else 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir")
    ap.add_argument("--expect-abs-envs", type=int)
    ap.add_argument("--expect-iters", type=int)
    ap.add_argument("--expect-seed", type=int)
    ap.add_argument("--expect-rel-heading", type=float)
    ap.add_argument("--expect-ang-vel-z", type=float)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.run_dir:
        ap.error("--run-dir or --selftest required")
    need = ("expect_abs_envs", "expect_iters", "expect_seed",
            "expect_rel_heading", "expect_ang_vel_z")
    missing = [n for n in need if getattr(a, n) is None]
    if missing:
        ap.error(f"missing {missing}")
    bad, info = check(Path(a.run_dir), envs=a.expect_abs_envs, iters=a.expect_iters,
                      seed=a.expect_seed, rel_heading=a.expect_rel_heading,
                      clip=a.expect_ang_vel_z)
    return report(Path(a.run_dir), bad, info)


if __name__ == "__main__":
    sys.exit(main())
