#!/usr/bin/env python3
"""闸门：backlash 域是不是「hd1910 plant + 2° 游隙」，且 obs/action 契约没变。

为什么存在
----------
上游自带方向性齿隙实现（不需要自己造）：

  1. ``robot/add_backlash.py`` 给每个舵机关节串一个**被动铰链**
     ``passive_<joint>_backlash``，range = ±deg/2，硬限位（solref 0.01 压住冲击）。
     齿隙在死区内时电机转、负载不动；撞限位后刚性传递 —— 这是「方向相关」的来源，
     加噪声模拟不出来。
  2. ``BacklashEncoderBamActuator`` 让固件位置环读**输出侧**角度（main + backlash），
     与真舵机编码器装在齿轮游隙之后一致。
  3. ``tasks/backlash.py`` 把 joint_pos/vel obs 换成 ``*_rel_backlash``，
     并把 ``dof_pos_limits`` 奖励收窄到舵机关节（齿隙关节本就该贴着自己的限位）。

关键结论（本脚本守的就是它）：执行器参数来自 ``_BAM_ACTUATOR_KWARGS``，与主任务
**共用同一块**，而 ``apply_to_live.py --plant`` 改的正是那块 ⇒ hd1910 plant 自动
穿透到 backlash 任务，obs/action 仍是 61/14，ONNX/robotd 一行都不用改。
这条是读代码推的，所以必须机械核对，不能靠记忆。

用法
----
  python tools/hd1910/check_backlash_task.py                 # 默认查 backlash 任务
  python tools/hd1910/check_backlash_task.py --no-build-env  # 跳过建环境（快 ~80 s）
  python tools/hd1910/check_backlash_task.py --expect-deg 1.0
  python tools/hd1910/check_backlash_task.py --selftest      # 负对照

退出码：0 全过 / 2 有失败
"""

from __future__ import annotations

import argparse
import math
import sys

TASK = "Mjlab-Velocity-Flat-Backlash-MicroDuck"
BASE_TASK = "Mjlab-Velocity-Flat-MicroDuck"
OBS_DIM = 61
ACT_DIM = 14
EXPECT_JOINTS = 14  # 舵机关节数；backlash 关节应与之 1:1


def _cfg(task: str):
    import mjlab_microduck.tasks  # noqa: F401  (import side effect: registers tasks)
    from mjlab.tasks.registry import load_env_cfg

    return load_env_cfg(task)


def audit(task: str, expect_deg: float = 2.0, build_env: bool = True,
          require_backlash: bool = True) -> tuple[list[str], dict]:
    """返回 (问题列表, 摘要)。require_backlash=False 时反向断言：必须**没有**齿隙。"""
    problems: list[str] = []
    cfg = _cfg(task)
    ent = cfg.scene.entities["robot"]
    spec = ent.spec_fn()
    names = [j.name for j in spec.joints]
    bl = [j for j in spec.joints
          if j.name.startswith("passive_") and j.name.endswith("_backlash")]
    # 基座自由关节（mjtJoint.mjJNT_FREE == 0, nq 占 7）不是舵机：nq 21 = 7 + 14。
    servo = [j.name for j in spec.joints
             if not j.name.startswith("passive_") and int(j.type) != 0]

    info = {
        "task": task,
        "joints": len(names),
        "servo_joints": len(servo),
        "backlash_joints": len(bl),
        "actuator": type(_first_actuator(ent)).__name__,
        "kp_fw": getattr(_first_actuator(ent), "kp_fw", None),
        "json_path": getattr(_first_actuator(ent), "json_path", None),
    }

    if require_backlash:
        if len(bl) != EXPECT_JOINTS:
            problems.append(f"expect {EXPECT_JOINTS} backlash joints, got {len(bl)}")
        if len(servo) != EXPECT_JOINTS:
            problems.append(f"expect {EXPECT_JOINTS} servo joints, got {len(servo)}")
        want = math.radians(expect_deg) / 2.0
        for j in bl:
            lo, hi = float(j.range[0]), float(j.range[1])
            if abs(hi - want) > 1e-6 or abs(lo + want) > 1e-6:
                problems.append(
                    f"{j.name}: range [{lo:.6f},{hi:.6f}] != +/-{want:.6f} "
                    f"(= +/-{expect_deg / 2:g} deg)")
                break
            if not j.limited:
                problems.append(f"{j.name}: limited=false -> 死区不是硬限位，齿隙会漏")
                break
        # 1:1 配对：每个舵机都有自己的齿隙关节，且名字对得上
        pairs = {n for n in names if n.startswith("passive_") and n.endswith("_backlash")}
        missing = [s for s in servo if f"passive_{s}_backlash" not in pairs]
        if missing:
            problems.append(f"servo joints without backlash partner: {missing[:3]}")
        if not type(_first_actuator(ent)).__name__.startswith("BacklashEncoder"):
            problems.append(
                f"actuator {info['actuator']} is not BacklashEncoder* -> PD 会读电机侧，"
                "齿隙只影响动力学、不进入反馈，等于半个模型")
        for g in ("actor", "critic"):
            for term_name in ("joint_pos", "joint_vel"):
                term = cfg.observations[g].terms.get(term_name)
                if term is None:
                    continue
                fn = getattr(term.func, "__name__", str(term.func))
                if not fn.endswith("_backlash"):
                    problems.append(f"obs[{g}].{term_name} uses {fn}, expected *_backlash")
        dop = cfg.rewards.get("dof_pos_limits")
        if dop is None:
            problems.append("reward dof_pos_limits missing")
        else:
            ac = dop.params.get("asset_cfg")
            jn = getattr(ac, "joint_names", None)
            if not jn or not any("passive_" in p for p in jn):
                problems.append(
                    "dof_pos_limits not scoped away from passive joints -> "
                    "齿隙关节终生贴限位会喂一份永久越界惩罚")
    else:
        if bl:
            problems.append(f"expect ZERO backlash joints, got {len(bl)}")

    # plant 穿透：执行器必须还是 hd1910（json_path 含 hd1910，kp_fw 是部署档）
    jp = str(info["json_path"] or "").replace("\\", "/").lower()
    if "hd1910" not in jp and "official_m6_stslaw" not in jp:
        problems.append(f"actuator json_path does not look like hd1910 plant: {info['json_path']}")
    if info["kp_fw"] != 8.0:
        problems.append(f"kp_fw={info['kp_fw']}, deployment plant is 8.0")

    # 奖励/命令必须与基础任务逐键一致（域变、任务不变）
    base = _cfg(BASE_TASK)
    if set(cfg.rewards) != set(base.rewards):
        problems.append(f"reward keys differ from base: {set(cfg.rewards) ^ set(base.rewards)}")
    if getattr(cfg.commands["twist"].ranges, "__dict__", {}) != \
            getattr(base.commands["twist"].ranges, "__dict__", {}):
        problems.append("command ranges differ from base task")

    if build_env:
        dims = _env_dims(task)
        info.update(dims)
        if dims["obs_dim"] != OBS_DIM or dims["act_dim"] != ACT_DIM:
            problems.append(
                f"obs/act = {dims['obs_dim']}/{dims['act_dim']}, contract is "
                f"{OBS_DIM}/{ACT_DIM} -> ONNX/robotd would need changes")
    return problems, info


def _first_actuator(ent):
    acts = ent.articulation.actuators
    a = acts[0]
    return a[0] if isinstance(a, tuple) else a


def _env_dims(task: str) -> dict:
    import torch
    from mjlab.envs import ManagerBasedRlEnv

    cfg = _cfg(task)
    cfg.scene.num_envs = 2
    env = ManagerBasedRlEnv(cfg=cfg, device="cpu")
    try:
        env.reset()
        sp = getattr(env.observation_space, "spaces", env.observation_space)
        obs_dim = int(sp["actor"].shape[-1])
        act_dim = int(env.action_space.shape[-1])
        model = env.sim._mj_model
        # 跑两步：被动关节 + 硬限位是新增的求解器负担，NaN 常在这里冒头
        a = torch.zeros(2, act_dim)
        for _ in range(2):
            obs, *_ = env.step(a)
        finite = bool(torch.isfinite(obs["actor"]).all())
        return {"obs_dim": obs_dim, "act_dim": act_dim, "finite": finite,
                "nq": int(model.nq), "nv": int(model.nv)}
    finally:
        env.close()


def _print(info: dict) -> None:
    print(f"task           : {info['task']}")
    print(f"joints         : {info['joints']} (servo {info['servo_joints']} + "
          f"backlash {info['backlash_joints']})")
    print(f"actuator       : {info['actuator']}  kp_fw={info['kp_fw']}")
    print(f"plant json     : {str(info['json_path']).replace(chr(92), '/').split('/')[-1]}")
    if "obs_dim" in info:
        print(f"obs/act        : {info['obs_dim']}/{info['act_dim']}  "
              f"nq/nv={info['nq']}/{info['nv']}  finite={info['finite']}")


def selftest() -> int:
    fails = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal fails
        print(f"{'PASS' if cond else 'FAIL'} {name}{'' if cond else '  <- ' + detail}")
        if not cond:
            fails += 1

    probs, info = audit(TASK, build_env=False)
    check("t1 backlash 任务通过闸门", not probs, "; ".join(probs[:1]))
    check("t2 认出 14 + 14 关节", info["backlash_joints"] == 14 == info["servo_joints"],
          f"{info['backlash_joints']}/{info['servo_joints']}")
    check("t3 执行器是 BacklashEncoder*", info["actuator"].startswith("BacklashEncoder"),
          info["actuator"])

    # 负对照 1：基础任务必须红（没有齿隙 → 这个闸门不能对谁都绿）
    probs_b, info_b = audit(BASE_TASK, build_env=False)
    check("t4 基础任务必须判红", bool(probs_b), "gate is green on a non-backlash task")

    # 负对照 2：反向后基础任务必须绿（证明 t4 红的是齿隙那几条，不是全盘红）
    probs_b2, _ = audit(BASE_TASK, build_env=False, require_backlash=False)
    check("t5 反向断言下基础任务绿", not probs_b2, "; ".join(probs_b2[:1]))

    # 负对照 3：齿隙量对不上必须红（真实 HD1910 若测得 3°，这个闸门要能抓住）
    probs_d, _ = audit(TASK, expect_deg=3.0, build_env=False)
    check("t6 期望 3° 时必须红", bool(probs_d), "range check did not fire")
    return 0 if fails == 0 else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=TASK)
    ap.add_argument("--expect-deg", type=float, default=2.0,
                    help="总游隙（peak-to-peak），默认 2.0 = +/-1°（上游 XL330 级默认）")
    ap.add_argument("--no-build-env", action="store_true", help="跳过建环境（快 ~80 s）")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    probs, info = audit(a.task, a.expect_deg, not a.no_build_env)
    _print(info)
    if probs:
        for p in probs:
            print(f"FAIL {p}")
        print(f"{len(probs)} check(s) failed")
        return 2
    print(f"ok: {a.expect_deg:g} deg total play (+/-{a.expect_deg / 2:g} deg), "
          f"hd1910 plant, obs/action contract intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
