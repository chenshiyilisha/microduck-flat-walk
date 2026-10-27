#!/usr/bin/env python
"""零成本探针：站桩是不是当前奖励表的 argmax？

做法抄自 DuckEMW `docs/03-training-log.md` 的 v13 一条：
「**探针确诊**（零成本）：站桩报酬是前进报酬 38 倍（v12 日志 stance 0.87 vs
progress 0.023 实锤）」。他们先量，再改奖励；我们之前是直接看总 reward 曲线
猜。这个脚本把「量」这一步补上：

  1. 用固定命令跑若干**固定行为**（零动作站桩 / 若干 checkpoint），不训练；
  2. 把 `env.step()` 返回的每一项 term 记下来（未加权）；
  3. 在同一批 term 上套**两套权重**各算一次总分：
       - OURS   = 我们 `--upstream-rewards` 那套（就是跑站桩的那套）
       - HANNES = Vottivott/microduck-playground 的 `Mjlab-Running-Flat-MicroDuck`
                  （唯一有公开数据证明走起来的配方：13.5k 轮 1.659 m/s）
  4. 顺带给出每一项的 min/p50/max —— 只看均值会漏掉「恒定值」这种静默失效。

如果 HANNES 那列的分差（走路 - 站桩）明显大于 OURS 那列，就说明站桩不是
「训练不够」而是「配方把站桩设成了最优解」。反之则说明要动的是别的东西。

    python tools/probe_argmax.py --policy out/robust61_u6.pt --command 0.4,0,0
"""

import argparse
import json
import pathlib
import sys

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repo"))
import train_ppo as T  # noqa: E402
import train_robust as R  # noqa: E402  —— 61 维 deployable env，u6/a 都是它训出来的

# 我们 `--upstream-rewards` 实际用的表（照 train_u6.log 首行抄，不凭记忆）
OURS = dict(
  track=2.0, air_time=3.0, clearance=-2.0, slip=-0.1, swing=-0.25,
  head=2.0, head_bias=0.0, angvel=-0.05, yaw_drift=0.0, head_band=0.0,
  turn=2.0, gait=0.0, pose=1.0, upright=2.0, height=0.0, slab=0.0,
  rate=-0.1, torque=0.0, limits=-1.0,
)

# Vottivott/microduck-playground @ main
#   src/mjlab_microduck/tasks/microduck_running_env_cfg.py:262-305
# `clearance`/`swing` 上游只改 target_height=0.015 而没动权重，这里沿用我们的权重
# 并在表里标 * —— 它们是「反站桩」的项（命令非零时脚不抬就罚），保留只会更利于走路。
HANNES = dict(
  forward_progress=5.0,   # cfg:265  running_forward_progress, speed_cap=RUNNING_SPEED_CAP
  track=2.0,              # cfg:270  std=sqrt(0.15)
  turn=0.5,               # cfg:272  std=sqrt(0.5)
  planar_drift=-0.05,     # cfg:274  lateral_weight=4.0
  heading_hold=1.5,       # cfg:282  std=0.4
  pose=0.15,              # cfg:290
  upright=0.75,           # cfg:291  std=sqrt(0.15)
  angvel=-0.01,           # cfg:293
  rate=-0.02,             # cfg:295  课程末档 -0.10
  slip=-0.05,             # cfg:296
  air_time=0.0,           # cfg:297  跑起来时整项关掉
  clearance=-2.0,         # *
  swing=-0.25,            # *
  head=0.0, head_bias=0.0, gait=0.0, height=0.0, slab=0.0, torque=0.0,
  limits=-1.0, yaw_drift=0.0, head_band=0.0,
)

HANNES_TRACK_STD2 = 0.15
HANNES_TURN_STD2 = 0.5
HANNES_UPRIGHT_STD2 = 0.15
HANNES_HEADING_STD = 0.4
HANNES_LATERAL_W = 4.0


def unit(rows):
  """min / p50 / max 三行文本 —— 单项恒定时要一眼看得出来。"""
  a = np.asarray(rows, np.float64)
  return f"{a.min():8.3f} {np.median(a):8.3f} {a.max():8.3f}"


def run(policy, env, command, steps):
  """跑固定行为，返回逐项 term 与物理量的原始序列。"""
  trace = {k: [] for k in list(env.rewards) + [
    "vx", "vy", "wz", "lin_err2", "up_err", "yaw_rel", "fell",
  ]}
  yaw0 = None
  obs = env.obs()
  for _ in range(steps):
    # 课程/重采样会把命令换掉，探针要的是「同一条命令下不同行为」的对照。
    env.command[:] = command
    env.until[:] = 1e9
    act = policy(obs)
    _rew, _done, fell, terms = env.step(act)
    vb = np.einsum("nji,nj->ni", env.rot, env.qvel[:, :3])
    up = -env.rot[:, 2]
    yaw = np.arctan2(env.rot[:, 1, 0], env.rot[:, 0, 0])
    if yaw0 is None:
      yaw0 = yaw.copy()
    dyaw = np.arctan2(np.sin(yaw - yaw0), np.cos(yaw - yaw0))
    for k in env.rewards:
      trace[k].append(float(np.mean(terms[k])))
    trace["vx"].append(float(np.mean(vb[:, 0])))
    trace["vy"].append(float(np.mean(vb[:, 1])))
    trace["wz"].append(float(np.mean(env.qvel[:, 5])))
    trace["lin_err2"].append(
      float(np.mean(np.sum((vb[:, :2] - command[None, :2]) ** 2, 1) + vb[:, 2] ** 2))
    )
    trace["up_err"].append(float(np.mean(up[:, 0] ** 2 + up[:, 1] ** 2)))
    trace["yaw_rel"].append(float(np.mean(np.abs(dyaw))))
    trace["fell"].append(float(np.mean(fell)))
    obs = env.obs()
  return {k: np.asarray(v, np.float64) for k, v in trace.items()}


def score(tr, weights, cmd, cap, label):
  """在一段轨迹的 term 均值上套一套权重。返回 (总分, 逐项加权值 dict)。"""
  m = {k: float(tr[k].mean()) for k in tr}
  lin_err2 = m["lin_err2"]
  vx = m["vx"]
  derived = {
    # running_forward_progress_from_velocity: clamp(vx, 0, cap) / cap（mdp.py:1292）
    "forward_progress": float(np.clip(vx, 0.0, cap) / cap),
    # 高斯 track 在 Hannes 配方里 std²=0.15，我们 0.25/0.10 —— 同一个物理误差重算
    "track": float(np.exp(-lin_err2 / HANNES_TRACK_STD2)) if label == "HANNES" else m["track"],
    "upright": float(np.exp(-m["up_err"] / HANNES_UPRIGHT_STD2)) if label == "HANNES" else m["upright"],
    # heading_hold_reward（mdp.py:5041）: exp(-wrap(yaw-yaw_spawn)²/std²)
    "heading_hold": float(np.exp(-(m["yaw_rel"] ** 2) / HANNES_HEADING_STD ** 2)),
    # running_planar_drift_cost（mdp.py:1356）: (wz-cmd)² + 4*(vy-cmd)²
    "planar_drift": float(
      (m["wz"] - cmd[2]) ** 2 + HANNES_LATERAL_W * (m["vy"] - cmd[1]) ** 2
    ),
  }
  total, per = 0.0, {}
  for k, w in weights.items():
    v = derived.get(k, m.get(k, 0.0))
    per[k] = w * v
    total += w * v
  return total, per, m


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--policy", type=pathlib.Path, action="append", default=[])
  ap.add_argument("--command", default="0.4,0,0", help="forward m/s, lateral m/s, yaw rad/s")
  ap.add_argument("--envs", type=int, default=1024)
  ap.add_argument("--steps", type=int, default=100, help="100 steps = 2 s at 50 Hz")
  ap.add_argument("--speed-cap", type=float, default=1.2, help="Hannes RUNNING_SPEED_CAP")
  ap.add_argument("--seed", type=int, default=0)
  ap.add_argument("--json", type=pathlib.Path, default=ROOT / "out" / "probe_argmax.json")
  args = ap.parse_args()

  cmd = np.array([float(x) for x in args.command.split(",")], np.float32)
  T.UPSTREAM_REWARDS = True          # 与 robust61_u6 的启动参数一致
  T.REWARD.update(OURS)
  # train_robust.Duck 是 61 维可部署任务（延迟/噪声/推力循环），u6 与 a 都在它里面训的
  env = R.Duck(args.envs, seed=args.seed, timestep=T.TIMESTEP)

  def hold(obs):
    return np.zeros((args.envs, T.ACT_DIM), np.float32)

  behaviours = [("hold (零动作站桩)", hold)]
  for p in args.policy:
    ckpt = torch.load(p, map_location="cpu")
    net = T.ActorCritic(env.obs_dim)  # 与 train() 里的构造一致（train_ppo.py:1036）
    net.load_state_dict(ckpt["model"])
    net.eval()

    def pol(obs, net=net):
      with torch.no_grad():
        return net(torch.as_tensor(obs))[0].numpy()

    behaviours.append((p.stem, pol))

  results = {}
  for name, policy in behaviours:
    tr = run(policy, env, cmd, args.steps)
    ours_total, ours_per, m = score(tr, OURS, cmd, args.speed_cap, "OURS")
    han_total, han_per, _ = score(tr, HANNES, cmd, args.speed_cap, "HANNES")
    results[name] = dict(
      trace={k: v.tolist() for k, v in tr.items()},
      ours=dict(total=ours_total, per=ours_per),
      hannes=dict(total=han_total, per=han_per),
      physical=m,
    )

  # ---- 打印 ----
  print(f"\n命令 cmd={cmd.tolist()}  envs={args.envs}  steps={args.steps} "
        f"({args.steps * T.CTRL_DT:.1f} s)  speed_cap={args.speed_cap}")
  print("\n## 1. 物理量（这段行为的实际表现）\n")
  print(f"{'行为':<22}{'vx m/s':>9}{'|vy|':>8}{'wz':>8}{'yaw漂°':>9}{'摔%':>7}")
  for name, r in results.items():
    p = r["physical"]
    print(f"{name:<22}{p['vx']:>9.3f}{abs(p['vy']):>8.3f}{p['wz']:>8.3f}"
          f"{np.degrees(p['yaw_rel']):>9.1f}{p['fell'] * 100:>7.1f}")

  for label, tbl in (("OURS（跑站桩的那套，--upstream-rewards）", OURS),
                     ("HANNES（DuckEMW/Hannes running 配方）", HANNES)):
    print(f"\n## {label}\n")
    keys = [k for k in tbl if tbl[k] != 0.0]
    head = f"{'项':<18}{'权重':>8}" + "".join(f"{n:>20}" for n, _ in results.items())
    print(head)
    for k in keys:
      row = f"{k:<18}{tbl[k]:>8.3f}"
      for name, r in results.items():
        row += f"{r[label.split('（')[0].lower()]['per'][k]:>20.3f}"
      print(row)
    row = f"{'合计':<18}{'':>8}"
    for name, r in results.items():
      row += f"{r[label.split('（')[0].lower()]['total']:>20.3f}"
    print(row)

  print("\n## 2. 每项 term 的 min/p50/max（看它到底有没有在动）\n")
  name0 = next(iter(results))
  for k in list(T.REWARD):
    a = np.asarray(results[name0]["trace"][k])
    print(f"  {k:<18}{unit(a)}   [行为 = {name0}]")

  args.json.parent.mkdir(parents=True, exist_ok=True)
  args.json.write_text(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "trace"}
                                   for k, v in results.items()}, indent=2))
  print(f"\n原始轨迹与分数写入 {args.json}")


if __name__ == "__main__":
  main()
