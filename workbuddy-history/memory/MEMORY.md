# 项目长期记忆（MicroDuck / flat-walk）

_2026-10-26 压缩。只留仍有效的结论；翻案过程见 `2026-10-25.md`/`2026-10-26.md`，
数字与证据见 `.upstream/dew_repo/docs/05-flat-walk.md`（§号均指该文档）。_

## 0. 总纲

**遇事先查资料，再改代码 / 下结论。** 卡住、选型、判负结果、定下一步时，先搜上游
`AGENTS.md` / `docs/*_policy.md`、社区复刻仓、BAM/规格书与既有 `microduck-*.md`；
没有一手出处就不动。用户反复强调；违反这条比写错代码更糟。
⚠️ **查到的是"通用文档"时必须回源码核对**：mjlab 默认 `rel_heading_envs=0.3`，
microduck 任务是 `0.0`（10-28 差一点照抄通用默认值下结论）。

**工作区入口**：仓库根目录 `README.md`；文档在 `docs/`（`active` / `hardware` / `sideline` / `archive` / `reference`）。
现行方案：`docs/active/microduck-HD1910软件方案.md`。

**正式训练用 GPU（`cuda:0`）**；Windows 上 `MUJOCO_GL=glfw`（勿设 `egl`）。
CPU 只做探针/导出/无卡对照。mjlab 设备由 `--gpu-ids '[0]'` 决定；空 `CUDA_VISIBLE_DEVICES=` 会逼 CPU。

**读数与算术上下界矛盾 ⇒ 错的一定是读数**（曾读出 0.174 < 下界 0.233，追出 25% env 被课程偷改）。
找不到两个互相矛盾的来源就判不了真假；验证问「这个量动没动、量级对不对」，不问「结果对不对」。

## 1. 仓库与权限（实测）

- **主线仓库 = `chenshiyilisha/microduck-flat-walk`（private，2026-10-25 建）**。本地 remote：
  `origin`=主线、`upstream`=emwstudio/DuckEMW（只读）、`fork`=chenshiyilisha/DuckEMW（只维护 PR #2）；
  `main` 跟踪 `origin/main` ⇒ `git push` 默认进自己的仓。
- **`emwstudio/DuckEMW` 是上游原仓**（fork:false、138★、作者是个 User 账号非组织）。
  chenshiyilisha 对它 push=false，`gh pr merge` 被 GraphQL 403 拒 ⇒ **PR #2 是可选出口不阻塞主线**，
  合并权只在 emwstudio；main 无分支保护、PR 无 CI（有权限者点 Merge 零拦截）。
- **训练任务包 = 官方 `pollen-robotics/microduck_rl@develop` 快照，velocity 代码零自加补丁**
  （2026-10-26 逐 blob sha 核对，§7.0）：254 文件中 249 个与官方 `b02fdea` 逐字节相同
  （含 velocity cfg）；5 个纯追加文件 + 2 个新增文件**全部 joy 专用**；mdp.py 头部 NaN 防护
  Patch 1-2/4/5 是**官方自带**（`mdp.py:25` 起，曾误归为自加——干净基线重放才暴露）。
  **复现链闭环**：`tools/upstream_patches/replay_all.py` 从干净 b02fdea 重放出 254/256 文件
  逐字节等于快照；唯二残差 = 已丢失的 `patch_joy_foot_peak.py`（只影响 joy，README 已声明）。
- **submodule 已修**：原指 emwstudio 私有仓（404），现指 `microduck_rl@b02fdea` +
  `Vottivott/microduck-playground@f010ef1`（均 public Apache-2.0）⇒ 公开读者 clone 后可复现
  （附补丁重放说明）。
- `microduck-software/repo` 是第三方 `tailong-wu/microduck-mjbatch` 克隆（2★、无 LICENSE 文件、
  已标 `NON-OFFICIAL.md`）——纯 CPU 脚手架，**正式训练从不用它，绝不可推到我们的仓库**。
- 工具坑：浅克隆推不了新仓（先 `git fetch --unshallow`）；ssh 被沙箱挡（用
  `credential.helper='!gh auth git-credential'` 不落盘）；`git push` 不能接 `| tail`（吞 rc）；
  502 重试 1-3 次。

## 2. 评估协议铁律

- 改上游文件只做**纯新增**不 patch。迭代分档：探索 1024×2000 / 定稿 4096×4000 / 评估 64–512
  （平地步态 32 env 是已标注例外）。**判决以部署侧数字为准**。成本：本地 4070 优先，
  云只用 4090D ¥1.88/h。
- **配置冻结必须可测量**：`standing_envs` 课程项每步重写 `rel_standing_envs`（末级 0.25）⇒
  曾致 25% env 被命令站立、误差被稀释、差值符号都反。冻结字段前先问**还有谁写它**；
  两处写者就必须 `cfg.curriculum.pop` + 记录实际值 + 闸门。清 `rel_*` 必须用反射不能逐个点名
  （曾漏 `rel_forward_envs`，`velocity_command.py:95-99` 把它 vx 钳 ≥0.3，毁掉 <0.3 扫描）。
- **`error_vel_xy` 单位依赖窗口长度**（`velocity_command.py:61-69`，`+=‖cmd−v‖/max_command_step`
  从不清零）；8 s 读数像 m/s 纯属巧合。评估脚本对齐 `resampling_time_range=(duration,duration)`。
- **判决双轴**：`err<0.97×` 且 `vx≥0.97×` 才算 improved。**跨版本评估脚本数字不可混用**
  （同 ckpt 差 4.8% > CV）。
- tyro 已暴露 230 条 `--env.rewards.*` ⇒ 调核宽不改 site-packages；cfg sha 对 CLI 覆盖一无所知
  ⇒ 必须回读生效值（`rewards_effective`）。改 curriculum 表用 `train_velocity_variant.py` 包装；
  `--defer-by` 必须连带推后更晚 stage 否则静默跳级；`except BaseException` 才能抓 SystemExit 留证据。

## 3. 读数方差（同 ckpt ×3）

CV：`error_vel_xy` 0.54%、`vx_median` 1.82%、`aacc` 1.67%、`dx_body` 5.5%、
**`abs_dy_body_median` 31.4%** ⇒ 位移类不可复现，`|dy|` 闸门作废。**闸门只能用低 CV 量**。
训练日志与单点评估打架时先怀疑单点评估。

## 4-5. 策略真实状态（交付基础）

- 核宽比较必须用 **`std/cmd_max`**（官方 0.50 vs 本项目 0.79：绝对值紧、相对松）。
- Baseline（std²=0.10）：**vx = 0.659·cmd − 0.018**；cmd=0 时 err 仍 0.105（49%）⇒ 一半误差是
  速度无关底噪。**策略精确优化了给定奖励，最优点就在 66%——任务定义与奖励不一致，非训练不足**；
  6000 轮峰值在 1250 ⇒ 「训练更久」已关闭。
- **单变量 std 0.3162→0.2**：vx 0.2493→**0.3093**(+24%)、ratio 0.623→**0.773**、err→**0.1620**；
  主改善是截距归零。峰值仍 iter1250；iter1999 掉点是 checkpoint 抖动非退化。交付点
  **`walk_std004_1250`**（ratio 0.78–0.81）。**代价：cmd≤0.12 双稳态死区 ⇒ 部署下限 0.15 m/s**。

## 6. 低速死区机制

抬脚唯一正激励是 `air_time`（+3.0，`sum(1{0.125<t<0.3})` 阶跃窗口）；`foot_clearance` 等全是负权重
且 cost 乘脚速 ⇒ 低速「搓地/乱蹬」就是最优解（实测 cmd 0.12 滞空 0.040 s 掉出窗口，aacc 与 0.4 一样大）。
**别调低 threshold_min 治低速**——小步慢走在两套主流口径下都不算迈步，是固有盲区；真低速必须新任务。
判「静止」别用 `|vx|<0.01` 比例，看 `aacc`+`landings`+滞空分布。

## 7. 归因方法论

**有现成判据就先跑判据，时间重合是最弱证据。** 「课程跳档致退化」被证伪：上游判据
（AGENTS.md:200-204 metric step DOWN at stage boundary）实测不触发；干预（defer1500×1000）
判据 0.77 实测 0.684，且变体 7.3% env 摔——**课程是鲁棒性来源，课程线已关闭**。
`--defer-by` 是多变量干预（standing_envs 与 head_pose_range 反向）。
**checkpoint 抖动是上游常态**（velstand_policy.md：「always run the walk sweep before picking」）；
`rsl_rl` 无 best-by-eval ⇒ 选点必须外层 sweep。

## 8. 参照系

上游 `alpha_walking` + 真机 v8 在 0.4 指令只做到 0.17 m/s（Rough+Backlash）；我们 0.249/0.309 是
Flat 无背隙 ⇒ **不能宣称更好**。判「未达标」要写明参照指令值还是平台可达水平。

## 9. 部署链与契约（上游 `pollen-robotics/microduck`）

官方四步：① `export.py`→ONNX ② **`infer_policy.py --walking` = CPU MuJoCo 部署彩排（BAM M6）**
③ `uv run publish`→HF Hub（manifest schema 2）④ `robotctl policy load`。契约 `policy-manifest.md`：
obs 61/act 14/control_hz 50 与我们逐项吻合；cfg 与上游 md5 相同（`33a44a7…`）是热插拔铁证。
上游真部署物是 **VelStand**（`0045i2si@2749`），纯 velocity 是 walk teacher；`--switch-threshold`
0.05 运行时 walk/stand 热切换 ⇒ 低速死区真机上先靠运行时（需 stand 策略，我们没有）。
`testbench_sim2real.py`：单电机+单 USB 的真机最小验证。
⚠️ 沙箱 huggingface.co 不可达 ⇒ 官方策略集 manifest 未核对。

## 10. parity 闸门（§13）

上游导出**零自检**。参考实现必须独立（不能拿 `act_inference()`——normalizer 同模块 bug 互相抵消）；
`EmpiricalNormalization` 除存储 std buffer、eps=1e-2；负对照（拆归一化）必须严重偏离
（实测 53000×容差）。图是静态 batch 1。工具 `tools/flat_walk/check_onnx_parity.py`，
max|Δ|=2.65e-06。产物 `walk_std004_1250.onnx`。

## 11. 彩排 ≠ 评估：两个仪器（§14）

- 工具 `tools/flat_walk/rehearse_deploy.py`（执行副本 `microduck-software/tools/` md5 须一致）：
  stub+`spec_from_file_location` 加载上游 infer_policy，复用其 BAM/PolicyInference，只换外层循环。
  **不要重写执行器**（重写=两个实现互相抵消）。
- ⚠️ 同 ckpt 同 cmd：彩排 vx 0.463 vs 32env 0.312（+49%）——**仪器差不是 bug，只能同仪器内纵比**。
- ⚠️ 训练有 delay lag 3-6，彩排延迟路径实测与训练不是同一件事（lag 3/4/6 → 摔 1.86/1.32/0.82 s，
  训练同 lag 几乎不摔）⇒ **延迟维只记缺口不作结论**。
- 判据可判定性：摔倒口径照抄训练 **70°**（`limit_angle=1.2217…rad`）；**摔倒即截断且 vx 记 n/a**
  （训练 time_out=False；截断后存活偏差 0.5389>0.4632 的教训）；触发步单独记 `tilt_at_fall_deg`；
  **负对照用量纲**（BAM 写力矩 vs legacy 写目标角：`max|ctrl−target|` 0.407 vs 0.000，阈值 1e-3）；
  单机低速只一个样本不可结论（cmd 0.15 扫 5 yaw 全站 vs 32env ratio 0.533）；cmd<0.2 时
  `moves_forward` 记 not_applicable；cmd=0 是 stand 语义（AGENTS.md:265-269）单独解读。
- 已验勿重做：`nu=14` 顺序==DEFAULT_POSE；obs 指纹 `[48:51]=[0.4,0,0]`；scene.xml≈scene_walk.xml；
  `USE_PROJECTED_GRAVITY=True`；action scale=1.0；episode_length_s=20（8s 不 reset）。

## 12. 上游经验在哪

`pollen-robotics/microduck_rl` 默认分支 **develop**；真东西在 `AGENTS.md`（17.7KB）与
`docs/*_policy.md`。raw 404 ≠ 文件不存在（走 contents API base64）。AGENTS.md:161-167 核宽
（「tight std taxed walking so hard the policy stood still」= 死区预言）；`:183-188` 冷门命令要显式
bucket；`velstand_policy.md:68-69` 发车前先做 reward check。

## 13. plant 是一等坐标（2026-10-28 破案）

- **每一次读数必须带 plant 指纹。** 训练时记录的 cfg sha / mdp sha 只覆盖那两个文件本身，
  **盖不到它的传递闭包**：velocity cfg 从 `microduck_constants.MICRODUCK_WALK_ROBOT_CFG` 拿
  `actuators`，而它由 `_BAM_ACTUATOR_KWARGS` 构造 ⇒ 改 plant 时两个 sha 照样「一切正常」。
  这是 §2「配置冻结必须可测量」第三次发作（`standing_envs`、`rel_forward_envs` 之后）。
- **同 ckpt 同命令 cmd 0.4/32env/8s/solver 100-50 的实测 A/B**：
  xl330(kp_fw 200) vx **0.318 / 摔 0% / 12 闸门全绿** ↔ hd1910(kp_fw 32) vx **0.109 / 摔 100%**
  （ symmetries aacc 0.08→0.41，5× 挣扎）。**换 plant = 换ıcı任务，必须重训**，不是"策略变差"。
- 工具 `tools/flat_walk/plant_id.py`（+ 执行副本），`eval_velocity_in_sim.py` / `eval_tracking.py`
  已接入 `plant_fingerprint`；名字/meta/这个员的用法见 `tools/hd1910/apply_to_live.py --check`。
- ⚠️ `apply_to_live.py --plant xl330` 恢复时会 `unlink` 注册模块，**沙箱里被回收站钩子挡**
  （`SHFileOperationW 失败: 0x78`）⇒ 手工 `cp .xl330.bak` + 删 `*.pyc` 更可靠。
- ⚠️ 已安装的 plant 把 **绝对路径** 写进了 site-packages（`E:/WorkBuddyData/.../bam_params/hd1910/m5.json`）
  ⇒ 工作区换路径即失效，且不会报错（夏令时会 fallback？实际会 hard fail，务必留意）。
- HD1910 参数**不是实测**：`m5.json`=OpenMicroDuck 社区拟合（vin 5 V 标定），
  `ftservo_official_m6.json`=飞特官方；对照见 `tools/hd1910/bam_param_compare.md`。
  ⇒ **花得起就先让阶段 0 的实测（kt/R/死区/齿隙）回填**，再重训一次，别训两遍。
- **`walk_std004_1250` 及全部数字/ONNX 属 XL330 plant，对 HD1910 无效**（已陈述，勿再引用
  它的 0.78–0.81 ratio 当作新硬件的预期）。**但 HD1910 不是「还没训」**——它有自己的一条线，
  已跑到 `model_5999.pt`（4096×2000→续训 6000）：cmd 0.4 ratio **0.747**、不摔、
  **`error_vel_yaw` 1.164（XL330 的 3.4×）、净位移比 0.359、`|dy|` 0.899 m、`not_sideways` ❌**
  ⇒ **缺口是偏航/横移不是前进速度**。断言"必须重训"前先看 HD1910 那份文档 §0 进度表。

## 14. 这台仿真不可逐位复现（2026-10-28 实测 + 官方依据）

- **三大繁衍方式：同 seed 只保证初始条件一致，不保证轨迹一致。** 实测 seed=1 两次
  `yaw0` 逐位相同（38.8096 / −110.9149 / −12.9005），但只推 **20 步空动作** yaw 就在第 4 位漂了
  （−111.5129 vs −111.5186）。⇒ **"再跑一遍验证"不算验证**；独立性只能靠 **N 次重复 + sem**。
- 依据非推测：`mjlab/docs/faq.md`「MuJoCo Warp does not yet guarantee determinism…
  tracked in mujoco_warp#562」；MuJoCo 官方 FAQ 给的出路是 **`wp.set_device("cpu")`**。
- ⛔ 写工具小坑：argparse 的 `help` 字符串里**不能写 `%`**（被当格式化符 → ValueError）。

## 15. 偏航缺口的确切形态（2026-10-28 P2，三次重复实测）

- **symmetry 假设已证伪**：三次符号翻转（+2.52 / −1.99 / −1.08 deg/s，均值 −0.18），
  同号率 0.51 ≈ 抛硬币 ⇒ 不是左右结构性不对称，**不必为它启用 symmetry 重训**。
  排除靠**符号**不靠大小；脚本原先 `yaw_drift` 取了 `.abs()` 答不了这题。
- **真机理 = 航向随机游走**：能走（path_dx 2.3–2.5 m、体坐标 vx 0.75），航向无反馈扩散
  （|drift| 中位 13–17 deg/s，极值 ±43），净沿初始航向位移只剩 **13–21%**。
  定量支持（96 env）：`sin(dψ)/dψ` 预测 vs 实测 **corr +0.55**、量级同阶（1.04 vs 0.70）。
- **根子在任务定义**：`microduck_velocity_env_cfg.py:643` `rel_heading_envs = 0.0`
  ⇒ 训练中零个 env 练过航向闭环，wz 全程开环采样自 (−1,1)。要治就加 `rel_heading_envs > 0`
  （**task 改动 ⇒ 必重训**），建议与实测参数回填合并进同一次 P3。
- **参照尺度**：ANYmal（Science Robotics, arXiv:1901.08652）yaw rate error **0.174 rad/s**，
  我们 1.2 ⇒ 差 7 倍（跨任务粗对标，只当量级）。
- 工具已补：`eval_velocity_in_sim.py` 加 `--seed`（默认 None，不动归档口径）+ signed yaw drift
  （角度 unwrap / sem / frac_same_sign）+ signed `dy_body`；原 `.abs()` 字段保留兼容。
