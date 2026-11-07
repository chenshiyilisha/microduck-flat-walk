# 04 - 踩高跷课程复现记录（microduck-stilts）

2026-09-09/10，AutoDL 4090D（实例 pro-78811e875f25）。复现
[Vottivott/microduck-playground](https://github.com/Vottivott/microduck-playground) @ `c5fcc50`
的 `Mjlab-Stilt-Flat-MicroDuck` 完整课程（对应 HF 模型
[HannesVonEssen/microduck-stilts](https://huggingface.co/HannesVonEssen/microduck-stilts)）。

## 结果总览

37 级阶段全部完成（21:36 开跑 → 01:49 收官，含环境约 4.5h，≈¥8.5），8 个里程碑门禁
（1024 envs × 10s，命令速度 0.15 m/s，seed 123）全部通过：

| 里程碑 | 最终 ckpt | survival | 均速 (m/s) | 中位最大倾斜 |
|---|---|---|---|---|
| 10cm  | model_2192 | 99.80% | 0.167 | 3.55° |
| 15cm  | model_2390 | 99.90% | 0.163 | 3.38° |
| 20cm  | model_2588 | 100%   | 0.179 | 3.32° |
| 25cm  | model_2786 | 100%   | 0.177 | 3.17° |
| 50cm  | model_3380 | 100%   | 0.176 | 3.29° |
| 1.0m  | model_3974 | 100%   | 0.204 | 3.69° |
| 1.4m  | model_4271 | 98.93% | 0.178 | 3.71° |
| 2.0m  | model_6465 | 99.90% | 0.153 | 3.15° |

与发布方唯一公开的 eval 数据（10cm、29g 加重审计：survival 1.0、均速 0.141、倾斜 3.28°）
相比，复现策略在同一量级（我们的是标称 22g 形态、1024 envs，条件不同，不逐点可比）。
所有 ONNX 本地加载验证通过：契约 obs[1,61] → actions[1,14]，与运行时热插拔契约一致。

产物：`artifacts/stilts_repro/<高度>/policy.onnx + checkpoint.pt`、`eval/repro_*.json`、
`completed.tsv`（37 级 run 目录/ckpt 对照）、`curriculum_status.log`、
`videos/stilt_h{10..200}cm.mp4`（8 档 × 6s @50fps，`scripts/record_stilt_play.py` 录制）。

## 复现方法

- 课程脚本：`archive/autodl-pipelines/run_stilt_curriculum.sh`（阶段表 = 原作者 TRAINING.md 的已执行
  lineage，seed 72）。每级一个训练进程，形态由 `MICRODUCK_STILT_HEIGHT_CM` /
  `MICRODUCK_STILT_BLEND` 编译期固定；blend 先在 2cm 收窄（0→0.25→0.50），再逐级加高。
- 关键机制（这版 rsl_rl）：`learn(num_learning_iterations)` 的入参是**相对起点的增量**；
  checkpoint 存的是最后一个已训练 it（阶段目标 400 → `model_399.pt`）。续训链一律用
  「上一阶段 run 目录中编号最大的 model_*.pt」，不做文件名算术；完成状态记录在
  `completed.tsv`，脚本支持断点续跑。
- 日志目录带时间戳前缀：`logs/rsl_rl/stilt_locomotion/<日期>_<时间>_stilt-h<H>cm-b<BBB>`。
- wandb 离线模式（实例无登录）；评估门：`scripts/evaluate_running_checkpoint.py`，
  survival < 0.90 即中止课程。

## 与原 lineage 的已知差异

- 1.5m 以上的「高跷桥」原文只给了累计节点（4600/6000/6500），中间每级增量是我按
  +300/+350 插值的（150→4600, 160→4950, 170→5300, 180→5650, 190→6000, 200→6500）。
- 每次续训会重训上一个已训 it（rsl_rl resume 起点语义），级间课程计数器差 1，无实际影响。

## 后续方向

- 10cm 质量随机化续训（22g→29g/32g，原作者明确未做；模拟打印件 +32% 质量误差）
- 50cm 以上为纯仿真研究结果，不作为打印硬件依据（原作者亦如此声明）

## 出片 / 彩排路径（2026-09-10 实测）

- **可信路径**：`scripts/record_stilt_play.py`（纯新增）——在 mjlab 训练环境内无头录制，
  物理/观测/DR 与课程门禁完全一致。用法见脚本 docstring（形态仍由
  `MICRODUCK_STILT_HEIGHT_CM`/`MICRODUCK_STILT_BLEND` 环境变量编译期固定）。
- **不可信路径（勿用）**：CPU MuJoCo 彩排（`scripts/infer_policy.py` 风格的
  `PolicyInference`，即使补上 BAM M6 执行器）渲染高跷策略会在 ~2.4s 摔倒，
  而同一 checkpoint 在真实环境里 32 envs × 10s survival = 1.0。
  `scripts/render_stilt_video.py` 是这次验证用的彩排渲染器，保留作反例参考。
  高跷策略的验证一律以 mjlab 环境内数据为准。
