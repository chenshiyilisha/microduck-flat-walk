# DuckEMW

> **这是什么仓库 / 谁的代码**
>
> `chenshiyilisha/microduck-flat-walk` —— [emwstudio/DuckEMW](https://github.com/emwstudio/DuckEMW)
> （138★）的**衍生工作仓**，内容以「平地速度跟踪（flat-walk）」这一支为主：上游任务的复现、
> 评估协议的两个纠错、一个单变量实验（奖励核宽）、一个被证伪的负结果、以及 ONNX 交付与
> 部署彩排两道闸门。全部细节与证据见 `docs/05-flat-walk.md`。
>
> **不是我的部分**（本仓库没有改动它们任何一行）：
> - 训练任务包（环境 / 奖励 / 课程 / 机器人 XML / BAM 执行器）来自
>   [`tailong-wu/microduck-mjbatch`](https://github.com/tailong-wu/microduck-mjbatch)，
>   此处以 `third_party/microduck_rl`（**private** submodule）引用 —— 所以「clone 即复现」
>   是夸大的说法，真实前提写在 `docs/05-flat-walk.md` §7.0。
> - 部署栈与 `infer_policy.py` 来自
>   [`pollen-robotics/microduck_rl`](https://github.com/pollen-robotics/microduck_rl)；
>   机器人本体与 runtime 来自
>   [`pollen-robotics/microduck`](https://github.com/pollen-robotics/microduck)。
> - 框架：mjlab / IsaacLab / rsl_rl / MuJoCo / onnxruntime。
>
> **是我（chenshiyilisha）的部分**：`tools/flat_walk/` 的七个工具、`docs/05-flat-walk.md`
> 的分析与结论、`artifacts/flat_walk/` 里的证据与产物。
> 给上游的 PR 是 [emwstudio/DuckEMW#2](https://github.com/emwstudio/DuckEMW/pull/2) ——
> 那是**可选出口**，不是这个仓库的前提；合并权在上游账号手里。
>
> 仓库保持 **private**：内容含第三方任务包的实验产物与未发布的 checkpoint。

教 MicroDuck（约 800 g、25 cm 双足机器人，14 个 XL330 舵机）挑战五件事：**平地极速冲刺**、**跟着音乐跳 DJ**、**踩篮球杂耍平衡**、**踩高跷（10cm→2m 课程复现）**、**360° 荡秋千（刚性杆全圈）**——RL 训练的运动策略 + 评估/出片管线。

基于 [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck)（机器人本体/runtime）与 [pollen-robotics/microduck_rl](https://github.com/pollen-robotics/microduck_rl)（mjlab/MuJoCo Warp + PPO 训练框架，本仓库以 fork + submodule 方式扩展）。

## 极速项目（2026-09-05，running 策略）

出厂行走基线 **0.4 m/s** → 峰值冲刺 **2.06 m/s**（HUD 实测读数；直立门控瞬时峰值 **2.196 m/s**）。

| 口径 | 本仓库 | 对照 |
|---|---|---|
| 直立瞬时峰值 | **2.196 m/s**（model_13250，512 env 电池取 max，倾斜 <45° 门控） | Max Sumrall 视频遥测峰值 1.88（X 平台公开） |
| 百米均速（10s 窗） | 1.659 m/s | Hannes von Essen 发布版 1.651 / 前沿 1.683 |
| 素材片 | `final_4k_v2.mp4`（4K@50fps，HUD 实时读数冲到 2.06，贴地跟拍） | 参考视频在 `artifacts/references/` |

- **方法**：PPO（rsl_rl）+ mjlab（MuJoCo Warp GPU 并行仿真），512 envs 并行，从零 13,500 轮大训（Hannes 配方 TARGET 2.5 / CAP 2.6）；奖励骨架 = forward_progress 主导 + 腾空相 + 航向保持 + anti-violence 正则（action_rate / 冲击 / 滑移）。
- **关键教训**（详见 `docs/03-training-log.md`）：纪录是「早就破了才发现」——只盯均值/p90 会看不见瞬时峰值，**评估指标决定你能看见什么**；激进续训（weight 8/cap 3.0）反而把均值打回 1.48；同 seed 渲染存在 2.06–2.20 的混沌漂移（warp GPU 非比特确定），属正常。
- 冲刺任务 `Mjlab-Sprint-Flat-MicroDuck`（徒脚极速）、评估 `eval_sprint_speed.py`、出片 `sprint_show.py` 均在 submodule `develop` 分支；纪录大训复现自 [Vottivott/microduck-playground](https://github.com/Vottivott/microduck-playground)（Hannes 的 running 配方）。

## 舞蹈项目（2026-08-31，v10s 策略）

| 指标 | 数值 |
|---|---|
| 高潮深蹲振幅 | 45.0 mm（参考 78%） |
| 高潮摆胯振幅 | 27.5°（峰峰） |
| 甩头/点头锤 | ±32° / ±34°（headbang 每正拍砸中） |
| 踩点精度 | 中位偏差 26 ms，91% 在 100 ms 内 |
| 稳定性 | 全曲 + 12 鸭方阵均**零摔倒** |
| 终版视频 | `stage_v10s_army12_cinematic_4k.mp4`（12 鸭阅兵方阵 + 电影运镜，4K 16:9） |

极限探索结论：单通道极限为深蹲 53 mm / 摆胯 ±22°，但 128 BPM 下不可兼得（XL330 舵机扭矩/转速与重心几何的真实约束，已由 BAM 执行器模型在仿真中验证）。

## 篮球平衡项目（2026-09-08，basketball 策略）

鸭子站上**自由滚动的 7 号篮球**，靠本体感觉保持平衡并跟踪速度命令——**盲 LSTM 策略**：actor 看不到球的任何状态，靠循环记忆从历史本体感觉推断球的动力学。

| 指标（3 seeds × 1024 envs × 60s 推搡电池） | 本仓库（model_7375） | Hannes b11 发布值 |
|---|---|---|
| 60s 存活率 | **98.34%**（3021/3072） | 97.01%（2980/3072） |
| 首次摔倒 | **51 次** | 92 次 |
| ONNX parity（40 步含 reset） | 2.15e-6 | 1.43e-6（同量级） |
| 展示片 | `bb_7375_close_10s_4k.mp4`（4K，踩球特写，底部留字幕位） | — |

- **方法**：续训 [HannesVonEssen/microduck-basketball](https://huggingface.co/HannesVonEssen/microduck-basketball) 发布的 b11@6999 checkpoint（官方续训配方：4096 envs × 500 轮、LR 2e-5、action-rate −0.2、1.5–3s 推搡扰动），然后对 3 个存档点逐个跑匹配评估电池再选定——**最终档 7498 反而回退到 95.74%，冠军是中间档 7375**（第三次验证本项目铁律：最终档 ≠ 最佳档）。
- **部署注意**：LSTM 策略的 ONNX 带 h/c 双隐状态（[1,1,256]），真机需要 runtime 的 recurrent 支持（`model_api: 2`，[runtime PR #231](https://github.com/pollen-robotics/microduck/pull/231)）。
- 训练源码 [Vottivott/microduck-playground](https://github.com/Vottivott/microduck-playground) @ `aa5bd790`（与 microduck_rl 依赖全同，PYTHONPATH 复用零安装）。

## 踩高跷项目（2026-09-10，stilts 课程复现）

复现 Hannes 的 [microduck-stilts](https://huggingface.co/HannesVonEssen/microduck-stilts) 完整课程（`Mjlab-Stilt-Flat-MicroDuck`，37 级：先在 2cm 上把跷底 blend 0→0.25→0.50（平板→圆杆），再逐级加高到 2m，每级从上阶段 checkpoint 续训；AutoDL 4090D 约 4.5h ≈ ¥8.5）。8 个里程碑门禁（1024 envs × 10s，cmd 0.15 m/s，seed 123）全部通过：

| 高度 | 10cm | 15cm | 20cm | 25cm | 50cm | 1.0m | 1.4m | 2.0m |
|---|---|---|---|---|---|---|---|---|
| survival | 99.8% | 99.9% | 100% | 100% | 100% | 100% | 98.9% | 99.9% |
| 均速 (m/s) | 0.167 | 0.163 | 0.179 | 0.177 | 0.176 | 0.204 | 0.178 | 0.153 |
| 倾斜中位 | 3.55° | 3.38° | 3.32° | 3.17° | 3.29° | 3.69° | 3.71° | 3.15° |

- **出片**：8 档 × 6s 4K@50fps 合集 `stilts_all_heights_4k.mp4`，mjlab 训练环境内无头录制（`third_party/microduck-playground/scripts/record_stilt_play.py`，纯新增脚本）。
- **验证纪律教训**：CPU MuJoCo 彩排（infer_policy 式，即使补上 BAM M6）会让 10cm 策略 ~2.4s 摔倒，而同一 checkpoint 在真实 mjlab 环境 32 envs × 10s survival 100%——高跷策略一律在训练环境内验证/出片。
- 50cm 以上为纯仿真研究，不作为打印硬件依据（原作者同此声明）；暂无实体机器人，未上真机。
- 课程脚本 `autodl/run_stilt_curriculum.sh`（37 级、断点续跑）；全程记录 `docs/04-stilts-repro.md`；门禁数据 `artifacts/stilts_repro/eval/repro_*.json`（已入库）。

## 360° 秋千项目（2026-09-12，swing360 策略）

复现 Hannes 的 [microduck-swing](https://huggingface.co/HannesVonEssen/microduck-swing)（柔性吊绳自泵秋千，实测摆幅峰值 **173.2°**——绳子一过水平就松，物理上到不了整圈），改造为**刚性摆杆**全圈任务 `Mjlab-Swing360-MicroDuck`：刚性杆 + 世界固定 y 轴被动铰链（weld 到躯干），过水平后仍能传力，PPO 自己发现泵荡过顶并维持整圈旋转。

| 指标（60s × 16 env 无头电池） | 数值 |
|---|---|
| 过顶 | **12/16** |
| 完整整圈 | **11/16** |
| 连续整圈 | **7 圈** |
| 成片峰值 | **2717.8°**（≈7.5 圈，`swing360_4k_7turns.mp4`，4K@25fps 60s，角度 overlay 破纪录变绿） |

- **方法**：同一 61D 部署观测契约，底部静止出生、无相位时钟、无脚本脉冲；pivot 精确运动学仅对 critic/奖励可见。v3 配方从零 4000 轮（4096 envs，AutoDL 4090D 约 2h ≈ ¥4）。
- **出片管线**（submodule `swing360` 分支）：`render_swing360_play.py`（play 契约渲染，支持 `--width/--height/--seed/--duration/--fps` 与 `--lookat/--distance/--elevation/--azimuth` 机位覆盖）+ `add_swing360_angle_overlay.py`（烧录「最大角度 + 圈数」）。评估用 `evaluate_swing360_checkpoint.py`（过顶/整圈电池，部署侧口径，不看训练指标）。
- 纯仿真结果，暂无实体机器人，未上真机。

## 拔河项目（2026-09-21，tugchain 策略）

两只鸭子戴自研 3D 打印抱箍（开口环+螺丝收紧，前后双 D 环系绳），背对背拔一根真张力麻绳——绳中心挂红色布条标记，拖过胜负线即赢。**v16 微调策略镜像局：红队 12.3 秒胜，全程零摔倒、近乎不转**。

| 指标（终版 1v1 镜像局实测） | 数值 |
|---|---|
| 回合时长 | **12.3 s**（红线过线判胜） |
| 摔倒 | **0%** |
| 朝向漂移 | **<20°**（v7 基线 ±150°+，yaw 通道微调+部署 PD 回正） |
| 绳绷紧占比 | **76%**（其余 24% 为踉跄瞬间的短暂松弛——真绳特性） |
| 成片 | `match_1v1_final.mp4` + `match_1v1_final_4k.mp4`（4K@50fps） |

- **方法**：PPO（rsl_rl）+ mjlab，4096 envs。训练环境家族在 playground `tug-of-war` 分支（滑车→1v1 鸭链→3v3 冻结→3v3 全员自对弈→面对面，共 5 个注册任务）；终版策略 `policies/tugchain_steady_v16_2250.onnx`（v7 满级 checkpoint + 500 轮 yaw 通道微调，权重已入库）。比赛/出片管线 `scripts/tug_of_war.py`：真绳（张力死区绳、环间距 taut）、疲劳打滑决胜、红布条中心标记、跟拍消旋镜头、绳型随弦长选型（绷紧/下垂真实切换）。
- **迭代 16 版配方的关键教训**：奖励黑客会摆拍假拉（差分式奖励根治）；前倾在 38% 头重鸭子身上是物理死穴（+8°/+15° 全摔，后仰挂绳才是正解）；物理锁转（阻尼/双绳）会连「输家转身滑走」一起锁死成全平局——直线必须训进策略里（v16 微调），不能靠外力。
- 训练管线：`autodl/run_tug.sh` + `watch_tug_*.sh`（AutoDL 4090D 冒烟→快试→正式，自动导出拉回）。
- 纯仿真结果，抱箍未上真机。

## 平地速度跟踪（2026-10-25，flat-walk 基线）

上游默认任务 `Mjlab-Velocity-Flat-MicroDuck` 原样复现——**奖励与环境零改动**（cfg / mdp 的字节哈希与上游一致，写在 runmeta 里），4096 envs 从零训练，**iter 1250** 即得 11 项闸门全过的行走策略。这一节的主要用途是**标定参照系**：后面所有「走得好不好」的判断都拿它当尺子。

| 指标（32 envs × 8 s，cmd vx 0.4） | 数值 |
|---|---|
| vx 中位 | **0.252 m/s**（指令的 63%）——出厂 `alpha_walking` 同指令只有 0.164 |
| 官方 `error_vel_xy` | **0.212**（同任务公开的 5000–6000 轮水平是 0.42–0.43） |
| 沿自身朝向净位移 | **+1.821 m**（期望 3.2，ratio 0.59） |
| 脚峰 / 落地 | **15.9 / 17.2 mm**（目标 20）/ **1.88 Hz** 每脚，同时落地 4.0% |
| 终止率 / upright | **0.00%** / 0.998 |
| 成本 | 本地 4070 8 GB，3.2 s/iter × 10.6 h，**¥0** |

- **三条标定结论**：① cmd 0.4 下 0.15–0.25 m/s 是正常范围（出厂策略也够不到 0.4，0.4 不是及格线）；② `error_vel_xy ≈ 0.42` 不是任务固有天花板，是配方问题；③ 平地脚峰参照是 **14–20 mm**（上游 target 20 mm，而原地抬腿的关节限位天花板只有 25.3 mm），`simple_stairs` 里的 **66.6 mm 是爬楼梯策略的值，不能当平地参照**。
- **1250 是峰值，不是半路**：同 run 的 9 档 checkpoint 全部同协议评测（`docs/05-flat-walk.md` §2b），1500 之后**没有一档回到 1250**，6000 还跌出一个 `no_fall` 闸门失败。于是在 6000 停训（原计划 12000，省 5.3 h），ckpt 全留、续训脚本在，决定可逆。
- **一个贵的评测坑**：`standing_envs` 课程项会每步重写 `rel_standing_envs`，把「冻结指令」的评测变成「75% 走 + 25% 站着」——旧读数里 4000 比 1250「好 10%」，修掉后是「差 10%」，**符号反了**。现在协议自检本身就是一项闸门（`command_frozen_ok`），拿掉修复跑负对照会立刻 FAIL（`docs/05-flat-walk.md` §5 坑 3）。
- **单变量实验：奖励核宽 std² 0.10 → 0.04**（`std/cmd_max` 0.791 → 0.500，回到 mjlab 官方口径；cfg 其余逐字节不动）。iter1250 同协议三次重复：vx 0.249 → **0.309**、ratio 0.623 → **0.773**、`error_vel_xy` 0.216 → **0.162**。**主改善是截距归零**（`0.7136·cmd−0.0363` → `0.7679·cmd+0.0025`），斜率只涨 7.6%——所以这不是「走得快了」，是「零速时不再乱蹬」。代价是 `cmd≤0.12` 出现双稳态死区，机制见 §11（滞空 0.04 s 掉出 `air_time` 的 0.125 s 阶跃窗口，而 `air_time` 是抬脚的唯一正激励）。详见 `docs/05-flat-walk.md` §10 / §11。
- **负结果留档**：求解器 10/20 → 100/50 **不改善抬脚**（脚峰 2.11/3.25 → 1.82/3.05 mm，冒烟尺度噪声），只作抗 NaN 保险；别重复试。
- **另一个负结果**：把 iter 1500 之后的课程整表推后 1000 档，判据（1999 轮 ratio 守在 0.77）**未达成**（实测 0.684），且退化换了性质（变体是 7.3% 的 env 摔倒，对照是变慢但稳）。顺带按上游 `AGENTS.md` 的判据复核——训练侧指标在跳档点**没有 step down**，原假设本来就不该成立。课程线关闭，详见 §12。
- **issue #46 三处改法**已写成可回滚补丁（`tools/flat_walk/patch_issue46.py`）但**刻意保持未应用**：1250 轮已过闸，在好策略上动奖励风险大于收益。
- **验收是分层的，闸门全过 ≠ 达到预期**：工程闭环（从零 / ¥0 / 可复现）与「会走」（速度、抬脚、交替、不摔）达标；**「跟得准」未达标**（63%）；**「走直线」上游任务根本没要求**——`rel_heading_envs = 0.0`，所以那段晃不是策略违约，而是任务定义的空白。详见 `docs/05-flat-walk.md` §9。
- 产物 `artifacts/flat_walk/`（checkpoint + 评估 JSON + runmeta + 9 档曲线 + 两条 8 s 录像 + 部署图）、方法 `docs/05-flat-walk.md`、工具 `tools/flat_walk/`（11 闸门评估器 / 训练与续训包装 / 里程碑判停 / 无头录像 / **ONNX parity 闸门** / **部署彩排**）。
- **交付链与两道闸门**：`model_1250.pt` → `walk_std004_1250.onnx`（obs 61 → act 14、opset 18、静态 batch 1）→ **parity**（numpy 独立重建前向，`max|Δ|` **2.65e−06**；负对照拆掉归一化偏离 **53000×** 容差）→ **部署彩排**（上游 `infer_policy.py` 的 BAM M6 + XL330 电压模型栈：`nominal`/`high_batt` 站得住且前进，`low_batt` 2.64 s 摔）。⚠️ **彩排数字不可与 32-env 评估并排**——单机/无延迟/CPU 求解器/固定摩擦 vs 32 台/3–6 lag/warp/摩擦 DR，是两个仪器。§13 / §14。
- 纯仿真结果，未上真机。缺口最小的一步是上游 `scripts/testbench_sim2real.py`：同一 ONNX 在 sim(BAM) 与真机 XL330 上跑同一角度序列做对比，**一个电机 + 一个 USB 口**即可。

## 仓库结构

```
├── third_party/microduck_rl   # fork（emwstudio/microduck_rl，develop 分支）
│   └── 新增 Mjlab-Sprint-Flat-MicroDuck / Mjlab-Dance-Flat-MicroDuck 任务、
│       eval_sprint_speed.py（速度电池+直立峰值口径）、sprint_show.py、stage_show.py
├── third_party/microduck-playground  # fork（emwstudio/microduck-playground）
│   └── 新增 record_stilt_play.py（mjlab 环境内无头 4K 录制）、render_stilt_video.py（CPU 彩排反例）、
│       Mjlab-Swing360-MicroDuck 刚性杆秋千任务 + evaluate/render/overlay 三件套（swing360 分支）
├── dance/
│   ├── beats.py               # librosa 节拍/BPM 提取 → beats.json
│   ├── timeline.py            # 节拍 → 编舞时间线（支持 --map 显式编舞）
│   └── songs/                 # beats/timeline（音频因版权不入库）
├── autodl/                    # setup.sh（一键环境）+ run_stilt_curriculum.sh（高跷 37 级课程）
├── tools/flat_walk/           # 平地速度跟踪：11 闸门评估器（含协议自检）、训练/续训包装、里程碑判停、无头录像、ONNX parity 闸门、部署彩排、issue#46 可回滚补丁
├── artifacts/                 # 产物（默认不入库；simple_stairs / flat_walk 的 ckpt 与评估 JSON 例外入库）
├── docs/                      # playbook 提炼、设计笔记、训练日志（舞蹈 v1-v11 + 极速 + 喙砸 + 篮球 + 高跷 + 平地）
└── AGENTS.md                  # 项目铁律（上游同步/修改必重训/成本纪律/验证纪律）
```

## 任务设计要点

- **观测契约**：与官方完全一致（61 维 = 48 本体感觉 + 13 命令块），全策略家族热插拔。舞蹈任务把 body_pose 槽语义重载为 `[sin(φ/2), cos(φ/2), tempo, 3-bit 舞步 id]`（2 拍周期相位编码——每拍回绕会让 2 拍周期的摇摆不可观测，这是 v3 踩坑后的关键修复）
- **冲刺**：速度命令课程（command-speed curriculum）+ 50% 初速出生 + 短回合爆发；直立门控瞬时峰值口径防止「摔倒前扑」刷假纪录
- **舞蹈**：参考跟踪（高斯**乘积**复合，塌掉静止妥协盆地）+ 节拍同步（potential-based shaping）+ 官方正则；幅度课程 35%→100% 爬坡；舞步库 0 squat_bounce / 1 weight_shift / 2 head_bob / 3 climax / 4 call_out

## 快速开始

```bash
# 1. 克隆（含 submodule）
git clone --recurse-submodules https://github.com/emwstudio/DuckEMW
cd DuckEMW/third_party/microduck_rl && uv sync
uv run --with pytest pytest tests/ -q          # CPU 测试全绿

# 2. 冲刺训练（AutoDL 4090D，一键环境见 autodl/setup.sh）
uv run train Mjlab-Sprint-Flat-MicroDuck --env.scene.num-envs 64 --agent.max_iterations 5   # 冒烟
uv run train Mjlab-Sprint-Flat-MicroDuck --env.scene.num-envs 4096 --agent.max_iterations 2000

# 3. 速度评估（512 env 电池：均值/p90/直立瞬时峰值）
uv run scripts/eval_sprint_speed.py --checkpoint <model.pt> --vx 2.2 --num-envs 512

# 4. 舞蹈训练与验证（节拍条件化策略 + 歌曲编舞 + 本地 CPU MuJoCo 彩排）
uv run train Mjlab-Dance-Flat-MicroDuck --env.scene.num-envs 4096 --agent.max_iterations 1000
uv run dance/beats.py dance/songs/<歌>.wav
uv run scripts/export.py Mjlab-Dance-Flat-MicroDuck --checkpoint-file <model.pt>
uv run python scripts/dance_to_timeline.py --policy dance.onnx \
    --timeline ../../dance/songs/<歌>.timeline.json --record out.mp4 --save-csv out.csv

# 5. 高跷课程复现（AutoDL；含门禁评估，断点续跑）
bash autodl/run_stilt_curriculum.sh
# 高跷 4K 出片（本地 CPU，mjlab 环境内无头录制）
cd third_party/microduck-playground
MICRODUCK_STILT_HEIGHT_CM=10 MICRODUCK_STILT_BLEND=0.5 PYTHONPATH=src \
uv run --no-sync python scripts/record_stilt_play.py \
    --checkpoint-file <model.pt> --duration-s 6 --width 3840 --height 2160 --out out.mp4
cd ../microduck_rl

# 6. 秋千 360（AutoDL 4090D；third_party/microduck-playground）
cd third_party/microduck-playground && uv sync
uv run train Mjlab-Swing360-MicroDuck --env.scene.num-envs 64 --agent.max_iterations 5   # 冒烟
uv run train Mjlab-Swing360-MicroDuck --env.scene.num-envs 4096 --agent.max_iterations 4000
uv run scripts/evaluate_swing360_checkpoint.py <model.pt> --output eval.json --duration 60 --num-envs 16
MUJOCO_GL=egl uv run --with imageio python scripts/render_swing360_play.py <model.pt> \
    --out s4k.mp4 --metrics s4k.json --device cuda:0 --duration 60 --seed 101 --fps 25 --width 3840 --height 2160
uv run --with imageio --with pillow python scripts/add_swing360_angle_overlay.py \
    --input s4k.mp4 --metrics s4k.json --output swing360_4k.mp4 --font-size 140
cd ../..

# 7. 出片（冲刺跟拍 / 舞台 N 鸭齐舞）
uv run python scripts/sprint_show.py --policy sprint.onnx   # 成片输出到 artifacts/sprint_show/
uv run python scripts/stage_show.py --policy dance.onnx \
    --timeline ../../dance/songs/<歌>.timeline.json \
    --ducks 12 --formation army --camera cinematic --record show.mp4 --width 1920 --height 1080

# 8. 平地速度跟踪（上游默认任务；判读用 11 项闸门，不看训练指标）
uv run train Mjlab-Velocity-Flat-MicroDuck --env.scene.num-envs 4096 \
    --env.sim.mujoco.iterations 100 --env.sim.mujoco.ls-iterations 50 \
    --agent.max-iterations 12000 --agent.save-interval 250
uv run python tools/flat_walk/eval_velocity_in_sim.py \
    --checkpoint artifacts/flat_walk/checkpoints/model_1250.pt \
    --num-envs 32 --seconds 8 --cmd-vx 0.4 --solver-iters 100 --solver-ls 50 --out out/eval.json
```

## 成本实录（AutoDL 4090D ¥1.88/h）

- 极速项目：基线测量 + 4 轮配方迭代 + 13.5k 轮大训 + 评估/出片，约 **¥70**
- 舞蹈项目：11 轮训练 + 环境配置，约 **¥35**；单轮快训（1000 步）约 ¥1、正式（4000 步）约 ¥4
- 篮球项目：HF 快照下载 + 冒烟 + 500 轮续训 + 3 档 × 3 seed 验收电池 + 5 次渲染，约 **¥5**
- 高跷项目：37 级课程 4.5h + 8 里程碑门禁评估，约 **¥8.5**（4K 出片为本地 CPU，零租金）
- 秋千 360 项目：v1–v3 配方迭代（2000 轮快试）+ 4000 轮正式 + 逐 seed 4K 扫描/出片，约 **¥12**
- 平地速度跟踪：**本地 4070 8 GB，没有云租金**，4096 envs × 12000 迭代约 10.6 h，**¥0**（只烧电）

详见 `docs/03-training-log.md`（两项目全程逐轮记录）。`artifacts/` 默认不入库（`.gitignore` 排除 checkpoint / ONNX / 成片），
只对 `simple_stairs`、`stilts_repro`、`swing360_v3`、`flat_walk` 做**逐项例外**——入库的都是「复现判决必需的小体积证据」。

## 致谢

- [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck) 与 [microduck_rl](https://github.com/pollen-robotics/microduck_rl)——机器人、训练框架与 sim2real 配方（其 AGENTS.md 是本项目的奖励设计圣经）
- [Vottivott/microduck-playground](https://github.com/Vottivott/microduck-playground)（Hannes von Essen）——running 极速配方与评估电池口径、[microduck-basketball](https://huggingface.co/HannesVonEssen/microduck-basketball) 盲 LSTM 平衡配方与发布 checkpoint、[microduck-stilts](https://huggingface.co/HannesVonEssen/microduck-stilts) 踩高跷课程 lineage 与 TRAINING.md、[microduck-swing](https://huggingface.co/HannesVonEssen/microduck-swing) 柔性吊绳秋千任务（360° 项目的改造起点）
- [mjlab](https://github.com/mujocolab/mjlab)、[BAM](https://github.com/Rhoban/bam)

License: 代码 Apache 2.0（遵循上游）；3D 模型文件 CC BY-SA-NC（上游资产）。
