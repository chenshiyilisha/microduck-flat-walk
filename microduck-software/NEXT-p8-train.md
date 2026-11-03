# 明天执行：P8 植物重训（`hd1910_kp8`）

_准备于 2026-11-02 晚；2026-11-03 08:35 起训。**植物、闸门、冒烟已就绪并通过，
但开工前发现两个启动脚本根本没带 heading 奖励配方（见 §1.0），已修并重跑冒烟。**_

> **背景与动机在仓库** `docs/05-flat-walk.md` **§18**（本文件的上游）。两边不一致时以仓库为准。

---

## ✅ 判决已出（2026-11-03 11:56）——先看这里，下面的计划文字保留作记录

`p8head_030_4096x3000` 跑满 3000 轮（08:33→11:50）。**主判据 PASS，但收益有前提。**

| 格子 | n | 摔倒 | vx | abs(heading_err) |
|---|---|---|---|---|
| P5 训练 × p3(kp5) 基线 | 8 | 0 | 0.1129 | 3.73° |
| **P8 训练 × p8(kp8)** | 8 | **0** | **0.2069（+83.3%，t=71）** | 6.91° |
| P8 训练 × p3(kp5)（OOD） | 8 | **7** | — | 56.65° |
| P8 策略 × 80 ms | 8 | 8 | — | — |
| 目标 ±90° 负对照 | 4+4 | 0 | 0.207 / 0.203 | 7.46 / 7.55° |

- 主判据（vx 显著更高）**PASS**；副判据（航向不劣于 3.73°）**相对口径 FAIL**、绝对口径（≤20°）PASS。
- 🔴 **+83% 只在 kp_fw=8 上成立**：同一策略在 kp=5 上 7/8 摔倒。要拿这个数，必须把真机
  15 颗舵机 reg 50 改成 8（无社区先例，且 kp=8 的 duty 余量还没测）。
- 详细数据、判据对照与三条前提见 `docs/05-flat-walk.md` **§21**。
  复算：`python tools/hd1910/judge_summary.py out/xplant_p5head_base out/xplant_p8head_030_4096x3000:8 ...`

### ✅ 后续裁决（12:10）：**kp_fw=8 采纳，不必再找替代点**

补跑了 kp 稳健性扫描（§22）与台架 duty 线性律，两条结论改写上面的 🔴：

- **kp ∈ [7, 12] 是一个平台**（0 摔、vx 0.192–0.213、航向 ≤7°）。kp≤6 崩溃（6 一档 1/8 摔、
  航向 22.6°±15）。⇒ +83% **不是对单一植物值的过拟合**，策略对刚度有 1.7× 容差。
- 台架 **duty% ≈ 5.1 × kp**：kp5 26%、kp8 40.5%、kp12 60.7%、kp32 100%（饱和，onset≈kp20 @4.6V）。
  ⇒ kp=8 留 **2.47×** 电流余量，是最划算的一点；kp=9/10 的 vx 优势（+2.9%）不显著却多付 13–25% 电流。
- P5/P8 两条线的 ONNX **都配 `model_2999.pt`** ⇒ +83% 里没有「训练更久」的成分。

**因此阶段 0 的硬性前置（不是建议）**：增益必须**两个寄存器都写、都回读**——
`50/51`（RAM，运行时生效，断电回落）与 `21/22`（EEPROM，上电载入）；
写 EEPROM 前 `55=0`、写完 `55=1`（**出厂锁是 1，不解锁写入会"成功"但读回仍是旧值**）。
其余：**reg 41 必须是 0**（写 10 会让整定翻倍）；reg 46 保持 0（**不要照抄旧的「必须写 300」**）；
reg 48=1000、reg 33=4。任何一颗不匹配 ⇒ 该机不可用（kp=5 时 7/8 摔，无降级模式）。

工具：`tools/hd1910/set_gains_all.py`（默认只读审计；`--write --yes` 才写；`--persist` 才动 EEPROM）。
台架 ID10 已验证：RAM→`p_ram=8`；persist→`p_eeprom=8` 且锁回 1；**断电重上电后
`p_eeprom=8 / p_ram=8`**（哨兵 15 被 EEPROM 值替换）⇒ 写 EEPROM 真持久、上电真载入，
**真机不必每次启动写 RAM**。

⚠️ 但这条结论是用**修正后的时序**才拿到的：旧实现四个 EEPROM 包背靠背写，全部撞进
~10 ms 的 commit 窗口，**回读是 RAM shadow（显示 8），断电回滚 32**。现在每写一个
EEPROM 区寄存器等 50 ms、写前关扭矩写完恢复。**回读 PASS 永远不等于持久 PASS。**
判据只有一条：断电后回读。方法（哨兵法）见 `docs/05-flat-walk.md` §22.7。

⚠️ 仍未闭合一件：**启动时是否有第二个写者**（真机运行时不在本仓，只能在 Radxa 上查）。
若它写 5，台架设好的 8 会在上电时被静默覆盖，症状与「没写」一模一样。

另外 §23（指令包线）给出一条部署事实：P8 线**没有低速死区**（cmd=0.10 稳定 0.059 m/s，
航向 1.12°），与 XL330 线 §4 的「部署下限 0.15 m/s」不同；但 **cmd=0 仍以 0.034 m/s 爬行**
⇒ 静止必须靠独立 stand 策略 + `--switch-threshold 0.05`，不能靠 cmd=0。

---

## 0. 一句话目标

回答一个二元问题：**把训练植物从 `kp_fw=5` 换成 `kp_fw=8`（台架甜点），
在同等轮数下能不能得到一个更好的策略**——更好的定义是「同植物彩排下 vx 更高且
航向误差不劣化」。

**不是**为了证明 P8 更快。P8 更快已经由台架证明了（gain +43%）；没证明的是
**在 P8 上训出来的策略**是否比在 P5 上训出来的更好。这两件事不是一回事。

---

## 1.0 🔴 开工当天发现的坑：两个启动脚本都没带 heading 奖励

`explore_heading.sh` / `smoke_heading.sh` 只传了 `--rel-heading-envs`，而
**heading 奖励藏在 `--heading-hold-weight` + `--heading-tracking-final-weight` +
`--ang-vel-z-clip` 后面，三者都默认 None ⇒ 不带就不加奖励**。也就是说：

- 昨夜那次 P8 冒烟、以及被中止的 4096×3000，**都只验了命令闭环，没验奖励**；
- 今天若照原命令开训，产出的策略会**没有 heading_hold / heading_tracking**，
  与 `model_2999`（hold 1.0 / tracking 课程到 3.0）完全不是同一个任务 ——
  2×2 矩阵会变成一个假对照。

已修：两个脚本都带上配方（默认对齐 `resume_heading_run.py::RECIPE`），冒烟新增
「env.yaml 里必须出现 heading_hold/heading_tracking」的闸门，并预检课程末档必须
严格落在 run 之内（负对照：`ITERS=2000` + 默认表 → 退出码 2，且在建 4096 env 之前退出）。

**今天这次 08:35 起训的 run 是修好之后跑的**，回读已确认：
`heading_hold weight=1.0`、`heading_tracking 0.0@0 → 1.5@42000 → 3.0@60000`、
`ang_vel_z (-0.5, 0.5)`、`rel_heading_envs 0.0 → 0.3`。

---

## 1. ⚠️ 开工前先确认三件事

```bash
cd /e/WorkBuddy/2026-10-23-08-26-15/microduck-software

# ① live 植物必须已经是 P8（昨晚已切换并 gate_ok=True）
.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --check
#   期望：detected hd1910_kp8 / kp_fw=8.0 / gate_ok True
#   若显示 hd1910_kp5：.venv-mjlab/Scripts/python.exe tools/hd1910/apply_to_live.py --plant p8

# ② 没有残留训练进程（昨晚 21:27 那次 3000 轮已被中止，只剩 iter 0 的垃圾目录）
.venv-mjlab/Scripts/python.exe tools/hd1910/stop_training.py --match p8head_030_4096x3000
#   期望：no trainer process ... -- nothing to stop

# ③ 彩排默认 ONNX 仍解析到 model_2999（P5 定稿），不是昨晚的 iter-0 垃圾
.venv-mjlab/Scripts/python.exe tools/hd1910/rehearse_hd1910.py -h | head -4
#   期望：--onnx 指向 ...resume2499.onnx
```

第 ③ 条是今晚新加的护栏（`MIN_TRAINED_ITER = 50`）：中止的 run 与 64×5 的冒烟都会
导出 ONNX 且 mtime 比昨夜的真 ckpt 更新，按 mtime 取最新会静默拿到一张**没训过**的图。
已做过负对照（只留 iter 0 的 ONNX 时会打印告警）。

---

## 2. 训练（一条命令，约 2 h 45 min）

```bash
PLANT=p8 ENVS=4096 ITERS=3000 REL_HEADING=0.30 \
  bash tools/hd1910/explore_heading.sh p8head_030_4096x3000
```

- 与 P5 定稿线 `model_2999` **同轮数（3000）、同课程（0,1000,1750,2500）、同
  `rel_heading_envs=0.30`、同 `ang_vel_z` 裁剪**，只有 reg 50 一个数字不同 ⇒ 可直接横比。
- 脚本自带三道闸门：CUDA 可用 + 植物回读（`hd1910_kp8`/8.0）+ heading 旋钮回读。
- 课程最后一段 mark = 2500×24 = 60000 < 3000×24 = 72000 ⇒ **权重 3.0 会真正生效**
  （这正是 P5 线第一轮踩的坑：2500 轮配 2500 mark，`>` 严格比较 ⇒ 一步没训到）。
- 中途 ckpt **不能用来判成败**（§29.1 实测非单调：2750 最差、2999 最好）。
  只看 2999。

---

## 3. 判决（训练跑完后）

### 3.1 2×2 交叉矩阵——唯一能分离「训得好」与「植物好」的设计

| 训练植物 \ 彩排植物 | P5 | P8 |
|---|---|---|
| **P5**（`model_2999`，已有） | 0.1129 / 3.7° | **0.0981 / 1.9°** |
| **P8**（明天产出） | ? | ? |

每格 n=8（起始 yaw 0,45,…,315），`--seconds 8 --cmd-vx 0.4 --heading-target-deg 0`。
P5×P5 与 P5×P8 两格昨晚已测完，只需补 P8 那一行。

**用 `xplant_matrix.sh`，别手敲**（一条命令跑完 8 个 yaw、校验 ONNX 代数、写 manifest、出汇总）：

```bash
# P8 那一行（今天产出的 ckpt）
TRAIN_PLANT=p8 ONNX=logs/rsl_rl/microduck_velocity_hd1910/<run>/<run>.onnx \
  bash tools/hd1910/xplant_matrix.sh

# 想重测 P5 那一行做同代码路径对照
TRAIN_PLANT=p5 ONNX=<model_2999.onnx> bash tools/hd1910/xplant_matrix.sh
```

默认 `PLANTS="p3 p8"`、`YAWS="0 45 … 315"`、`DUR=8`；`COND=delay4` 可切条件档，
`FORCE=1` 重跑已有格子，`PLANTS="" YAWS=""` 只写 manifest（干跑用）。

⚠️ 三个已踩过的坑：① 变量名是 **`DUR` 不是 `SECONDS`**（`SECONDS` 是 bash 内建变量，
开局为 0 ⇒ 所有彩排跑 0 秒）；② 空串要用 `${VAR-default}` 才不会被默认值覆盖；
③ `--plant p8` 与 `--plant p3 --kp-fw 8` 等价（P8 = 同 JSON + 同控制律 + 只改 reg 50）。

### 3.2 判据（先写好，跑完再对，不许事后挑）

- **主判据**：P8×P8 的 `vx_mean_steady` 相对 P5×P5（0.1129）**显著更高**
  （Welch |t| > 3，n=8 对 8）。
- **副判据**：`|heading_error_final_deg|` **不劣于** P5×P5 的 3.7°（目标 ≤20°）。
- **🚫 禁止用** `yaw_delta_deg`（末−初）。8 个起点里从 180° 起步「成功」本来就要转
  ~180°，大 Δyaw 是成绩不是失败——这个错量曾把「已解决」误判成「未解决」。
- **🚫 禁止用** `error_vel_yaw`（训练标量，含 70% 非 heading env 的随机角速度指令）。
- `moves_forward` 闸门的 FAIL 是**预期**的：闭环转向后净位移 `dx_body` 可以为负，
  它问的是「沿初始朝向的净位移」，不是「有没有往前走」。看 `vx_mean_steady`。

### 3.3 出结果后必做的两件事

1. **换目标负对照**（排除「只是有个固定吸引子」）：`--heading-target-deg -90` 与 `+90`，
   末态航向必须跟着走。
2. **延迟档**（唯一的硬边界风险，§29.4）：`--delay 1/2/4` = 20/40/80 ms。
   P5 定稿是 20/40 ms 不摔、**80 ms 必摔（1.20 s）**；P8 线必须至少不比这更差。

---

## 4. 今晚已完成（不必重做）

| 项 | 状态 |
|---|---|
| `plant_spec.HD1910_OFFICIAL_M6_KP8`（同 JSON + 同控制律，只改 reg 50） | 已加 |
| `apply_to_live.py --plant p8` + 回读按 kp 区分 P5/P8（共用一份 JSON，光看文件名分不出） | 已加，gate_ok True |
| `rehearse_hd1910.py --plant p8` | 已加 |
| `explore_heading.sh` / `smoke_heading.sh` 的 `PLANT=p3\|p8` 闸门泛化 | 已改，语法已检 |
| P8 冒烟（64 env × 5 iter，GPU） | **PASS** |
| live 已切到 `hd1910_kp8` | `30768e18ffebf763` |
| 彩排默认 ONNX 护栏 `MIN_TRAINED_ITER`（防中止 run / 冒烟的图被当成最新策略） | 已加 + 负对照已验 |
| `summarize_rehearsal_grid.py`（固定口径：vx + `\|heading_error_final_deg\|`，Welch t） | 已加 |

---

## 5. 收尾

- 判决写进 `docs/05-flat-walk.md` §18，证据 JSON 入库（`out/kpsweep_p8train/`）。
- **无论结论如何都要把 live 植物切回 `p3`**（`apply_to_live.py --plant p3`），
  除非 P8 明确胜出并决定切换——否则下一次谁跑彩排都会在 P8 植物上，而 P5 线的
  全部数字都不适用。
- 舵机已恢复出厂（mode=4/reg44=500/reg46=300/reg41=10/reg48=1000/P32/D40），
  台架未再动过。
