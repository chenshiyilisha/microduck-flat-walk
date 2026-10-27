# DuckEMW 二次扫描：四处上次漏掉的东西

> 2026-10-24 08:0x。用户又把 `https://github.com/emwstudio/DuckEMW` 贴了一次。
> 第一次挖的是「奖励配方」（`microduck-走起来的配方.md`）。这次不重复那条线，
> 只找**上次没读到、但会影响我们现在做法**的部分。
> 全部来自 GitHub API + `raw.githubusercontent.com`（`default_branch=main`，
> 本地缓存 `.upstream/duckemw/DuckEMW-main/`，87 个文件，未截断）。

---

## 0. 一句话

**这个仓库里最重要的不是配方，是它 `docs/04` 里那条「CPU 彩排不可信、一律以 mjlab 环境内数据为准」——
它直接判了我们 `tools/probe_joy_policy.py` 的死刑（当验收用的话）。**

---

## 1. ⚠️ CPU MuJoCo 彩排不是同一套物理（推翻我们的验收方式）

`docs/04-stilts-repro.md:56-65` 原文：

> **不可信路径（勿用）**：CPU MuJoCo 彩排（`scripts/infer_policy.py` 风格的
> `PolicyInference`，即使补上 BAM M6 执行器）渲染高跷策略会在 **~2.4s 摔倒**，
> 而同一 checkpoint 在真实环境里 **32 envs × 10s survival = 1.0**。
> 高跷策略的验证一律以 mjlab 环境内数据为准。

同一份权重，CPU 上说「2.4 秒就摔」，warp 环境里说「10 秒全活」。这不是精度问题，
是**两套接触求解**：

| | CPU MuJoCo | mjlab（mujoco-warp） |
|---|---|---|
| 碰撞 | 原生、`margin=0.2 mm` | Warp MULTICCD，**margin 必须 0** |
| 约束 | 原生 CG/Newton | warp 自己的 constraint buffer |
| 来源 | `microduck_joy_env_cfg.py:72` 注释明写：「Warp MULTICCD requires zero margin; CPU rehearsal retains .2 mm margin」 ||

我们的 `tools/probe_joy_policy.py` 正是 CPU 回放。它在**同一台机器上比较两个策略**
时仍然有效（同一物理、同一误差），但**不能当验收门**。

### 落地：`tools/eval_joy_in_sim.py`

对应他们训练日志 `:93` 的自建工具 `scripts/eval_sprint_speed.py`
（「warp 原生环境内测 checkpoint 真实速度，绕开一切 harness 差异」）。
我们的版本：

```
.venv-mjlab/Scripts/python.exe tools/eval_joy_in_sim.py \
    --checkpoint logs/.../model_599.pt --num-envs 512 --device cuda:0
```

- 用**训练时同一个 env cfg** 建环境（`load_env_cfg(task, play=...)`），把 checkpoint
  塞进 `MicroduckOnPolicyRunner` 拿推理策略，直接 step。
- 9 条 gate 全部从 `mdp.joy_*` 与 entity 状态现算，**不重实现观测契约**。
- 除了 gate，还报 `joy_foot_rhythm / joy_balance / joy_drift / joy_head` 四项
  训练奖励的实测值——这样「训练日志里的数」和「评估里的数」可以互相校验。

**已发现的第一个真 bug（本脚本自证）**：`max_target_step_rad` 一开始测出 **0.222 rad**，
超过 `joy_max_step=0.08` 的硬钳位，看着像策略在猛抖。追下去是**采样时机**：
`BaseAction.__init__` 把 `_processed_actions` 初始化成 `zeros`，第一次 `process_actions`
之前读到的是**全零缓冲**，于是「第一帧→第一帧之后」的差就是整个默认站姿（≈0.21 rad）。
另外 reset 那一步目标会被 `initialize_joy_servo_targets` snap 回实测姿态，也是假跳。
两处都已在脚本里剔掉。→ **凡是被硬约束钳住的量一旦超限，先怀疑测量，不要先怀疑策略。**
（第一次修的时候我猜的是 reset，只剔 reset 还是 0.21；把 `tgt[0]` 也剔掉才归零——
假说的正确性必须用「修完数字对不对」验证，不能凭解释力强的故事收工。）

---

## 2. `artifacts/simple_stairs/` 是失败样本，不是参考实现

三份 eval（512 envs × 20 s，5 个难度档）全在那儿摆着，读出来的数：

| ckpt | `climb` 摔倒率 | 到顶率 | `hold`（站着不动）摔倒率 |
|---|---|---|---|
| ck1000 | 0.86–1.00 | 0 | 0.27–0.30 |
| ck1500 | 0.99–1.00 | 0 | 0.28–0.36 |
| ck1999 | 0.88–1.00 | 0 | 0.28–0.33 |

- 爬楼：**基本全摔**，`final_rise_m_p50` 在 −0.07 到 +0.11 之间（也就是原地）。
- 连「站着不动」在 15 mm 级高的台阶上都摔 **三成**。
- `JOURNEY.md` 自己写清了路线：v1 硬上 30 mm 失败 → v2 被 `min_riser_m=29mm` 钳制 →
  v2r 续训 2200 轮**零进步**（判决性证据，证明「加步数」无效）→ v3 换侧目标更差 →
  根因锁定「29–30 mm 超出迈步步态 ~25 mm 的可靠包络」。

**结论：这些 `.pt` 不要当「会走的策略」下载。**（我本来打算拉下来在我们仿真里跑，
看完 eval 就不用了 —— 它们连站都不稳。）

顺带一条可用的数据（`JOURNEY.md` 背景测量）：
官方交替梯策略抬脚**净空 median 66.6 mm / p90 72.4 / max 78.8**；运动学极限 ~170 mm。
→ 我们 joy 现在定的「峰值 >8 mm」只是**能看出在踏步**的下限，不是步态质量。

---

## 3. 三个 dt 在飞，必须钉死一个写进验收

`docs/02-design-notes.md`「50Hz 控制对齐」一节：

> 训练物理：`timestep=0.005 + decimation=4`（50Hz）。上游 `scripts/infer_policy.py`
> 沿用场景 XML 默认 `0.002`（实际 125Hz 控制），是**既有偏差、未动**。

我们自己现在是：

| 路径 | 物理步长 | 控制 | 备注 |
|---|---|---|---|
| 训练 `Mjlab-JoyPD`（我们 cfg） | 0.001 | 50 Hz（decim 20） | ✔ |
| 训练 `Mjlab-Joy`（BAM） | 0.002 | 50 Hz（decim 10） | ✔ |
| `probe_joy_policy.py`（CPU） | **0.0002** | 50 Hz（decim 100） | 按 Duckverse `joy.py` 的 5 kHz |
| Duckverse `joy.py:report()` gate | 0.0002 | 50 Hz | 抬脚 16.36 mm |
| 官方 upstream `infer_policy.py` | 0.002 | **125 Hz** | DuckEMW 标注为「既有偏差」 |

**好消息：控制率全是 50 Hz**，没人在跑 125 Hz。**坏消息：物理步长差 10 倍**
（0.2 ms vs 2 ms），这正是当初「抬脚 14.8 mm → 16.36 mm」那 10% 差异的来源。

→ 写进验收：**gate 一律在训练 cfg（0.001/50 Hz，PD 植物）下测**；
CPU 的 5 kHz 数只用于和 Duckverse ONNX 对表（口径必须一致才可比）。

---

## 4. `AGENTS.md` 的训练纪律（有几条我们违反过）

- **配方探索 1024 envs × 2000 iter；定稿才 4096 × 4000；评估 64–512。**
  不一律 4096（那是官方为步态/爬梯调的主训默认值）。→ 我们 2048×600 属于探索档，合理。
- **「任何代码/奖励/编舞修改 → 从零重训；只有同配方加步数才能 `--agent.load-checkpoint` 续训」。**
  → **我们接下来加 `forward_progress` + 砍四项静止白拿，必须从零重训，不能 resume 这条 600 iter 的。**
- **冒烟 64 envs × 5 iters 能抓 ~95% 配置错误。**（我们已照做）
- **验证纪律**：训练指标不作数，以部署侧实测为准。→ 就是上面 §1 那个脚本的意义。
- 一个坑值得记：`ModuleNotFoundError: mjlab_microduck` 在 macOS 上是 `.venv` 被打了 `hidden`
  标记导致 `.pth` 被跳过，`chflags -R nohidden .venv` 解决。（Windows 无关，但同症状别再往代码里找。）

---

## 5. 走路速度的真实标杆（训练日志 `:103`/`:118`）

他们用 warp 原生工具实测过两套权重：

| 来源 | 命令 2.2 m/s 下均值 | 峰值 |
|---|---|---|
| Hannes 发布的 `policy.onnx`（12195 轮） | 1.451 | 1.707（宣称 1.651） |
| Hannes 前沿 ck11748 | — | 1.683 |
| DuckEMW 自己 13,500 轮 @4096（TARGET 2.5 / CAP 2.6） | **1.659** | 2.196 |

- 1.65–1.69 是这套配方的**平台期**：续训、扩带、更激进权重（weight 8 / cap 3）
  全部回弹到 1.63。→ 别指望调 reward 破 1.7。
- 「同 seed 峰值在 2.06–2.20 漂」——**warp GPU 求解器非比特确定**。我们做前后对比时，
  差异小于这个量级的都别当回事。

---

## 6. 私有 fork 确认 404

`third_party/microduck_rl`（`emwstudio/microduck_rl`）和
`third_party/microduck-playground`（`emwstudio/microduck-playground`）
用 GitHub API 查都是 **Not Found**。所以：

- Dance 任务的 `scripts/dance_to_timeline.py` / `check_beat_align.py`、
  `forward_progress` 的具体实现，**代码拿不到，只有文档描述**。
- 我们照 `docs/01` 的「奖励红线」和 `docs/03` 的数字自己写，不要假装能抄到实现。
- 相位公式可以从 `dance/beats.py` + `docs/02` 反推：`φ = 2π(t−t0)·BPM/60`，
  BPM 用**首尾跨度法**（`60·(n−1)/(t_last−t_first)`）而不是 librosa 的 tempo 估计
  （120 BPM 上估计器报 117.45，首尾跨度法报 119.96；差 2.5 BPM 在 32 s 累积 0.6 s 漂移）。
  我们的 joy 时钟是固定 1.15 Hz 常数，不存在这个漂移源。

---

## 7. 首次 in-sim 实测（训练到 iter 100 / 600，仅作脚本自证）

`model_100.pt`，CPU、32 envs、8 s、训练 cfg：

| gate | 值 | 门槛 | 结果 |
|---|---|---|---|
| duration_s | 8.000 | ≥3.5 | PASS |
| min_upright | 0.9930 | >0.9 | PASS |
| max_drift_m | 0.0132 | <0.08 | PASS |
| **feet_peak_m** | **0.00544** | >0.008 | **FAIL** |
| end_upright | 0.9999 | >0.95 | PASS |
| target_rate_rms | 1.335 | <6 | PASS |
| max_target_step_rad | 0.222 → 修后 **0.0800** | <0.2 | PASS（且**构造上必过**：被 `joy_max_step=0.08` 钳死） |
| 8Hz 功率比 | 0.330 | <0.01 | FAIL，但 `foot_ac_rms` 只有 **0.62 mm** → 比值是噪声主导，不可解读 |

- **完全没摔**（`fell_frac 0.0`），但**抬脚只有 5.4 mm** → 现在是「站着不动」，不是踏步。
  与训练日志 `joy_feet` 5.21/12 = 0.434 一致（评估侧 0.410，两条独立路径对上了）。
- 100/600 轮下这个状态**正常**，不能判死。
- 注意 `8Hz` 这条在近静态信号上是噪声主导：0.2 mm 的求解器抖动和 20 mm 的颤振能得同一个比值。
  所以脚本现在同时报 `foot_ac_rms_m` / `knee_ac_rms_rad`，比值必须配幅值读。

---

## 8. 这次要改的东西（按优先级）

1. **joy 验收改跑 `eval_joy_in_sim.py`**（GPU，512 envs），`probe_joy_policy.py` 降级为
   「与 Duckverse ONNX 同口径对表」的工具，不再产生 PASS/FAIL。
2. 600 轮跑完后先看这条：`feet_peak_m` 有没有过 8 mm。没过就不是「精度不够」，是
   **奖励在教它站着**（`joy_drift` 权重 100 + `joy_balance` 权重 5 都在逼它不动）。
3. 过了才加 `forward_progress`，并且**从零重训**（AGENTS.md 明令）。
4. 修 `tools/probe_joy_policy.py` 的注释，写明「此脚本不是验收门」。
