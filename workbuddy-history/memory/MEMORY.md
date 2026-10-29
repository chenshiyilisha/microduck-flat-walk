# 项目长期记忆（MicroDuck / flat-walk）

_2026-10-29 压缩重写。只留仍有效结论；翻案过程见 `2026-10-25/26.md`，
数字与证据见 `.upstream/dew_repo/docs/05-flat-walk.md`。_

## 0. 总纲

**遇事先查资料，再改代码 / 下结论。** 卡住、选型、判负结果、定下一步时，先搜上游
`AGENTS.md` / `docs/*_policy.md`、社区复刻仓、BAM/规格书与既有 `microduck-*.md`；
没有一手出处就不动。⚠️ **查到"通用文档"时必须回源码核对**：mjlab 默认
`rel_heading_envs=0.3`，microduck 任务实际是 `0.0`（差点照抄通用默认值下结论）。

**工作区入口**：根 `README.md`；文档在 `docs/`（`active`/`hardware`/`sideline`/`archive`/`reference`）。
现行方案 `docs/active/microduck-HD1910软件方案.md`。

**读数与算术上下界矛盾 ⇒ 错的一定是读数**（曾读出 0.174 < 下界 0.233，追出 25% env 被课程偷改）。
找不到两个互相矛盾的来源就判不了真假；验证问「这个量动没动、量级对不对」，不问「结果对不对」。

**正式训练用 GPU（`cuda:0`）**；Windows 上 `MUJOCO_GL=glfw`（勿设 `egl`）；CPU 只做探针/导出。
`--gpu-ids '[0]'` 决定设备；空 `CUDA_VISIBLE_DEVICES=` 会逼 CPU。

## 1. 仓库与权限（实测）

- **主线仓 = `chenshiyilisha/microduck-flat-walk`（private）**；`origin`=主线、
  `upstream`=emwstudio/DuckEMW（只读）、`fork`=chenshiyilisha/DuckEMW（只维护 PR #2，
  **可选出口不阻塞主线**：合并权在对方）。`main` 跟踪 `origin/main` ⇒ push 默认进自己的仓。
- **训练任务包 = 官方 `microduck_rl@develop` 快照，velocity 代码零自加补丁**
  （逐 blob sha 核对：254 文件中 249 个与官方 `b02fdea` 逐字节相同）；mdp.py 头部 NaN 防护
  Patch 1-2/4/5 是**官方自带**（曾误归为自加）。复现链 `tools/upstream_patches/replay_all.py`
  已闭环，唯二残差 = 丢失的 `patch_joy_foot_peak.py`（只影响 joy，README 已声明）。
- **submodule 已修**：指向 public Apache-2.0 的 `microduck_rl@b02fdea` + `microduck-playground@f010ef1`。
- `microduck-software/repo` 是第三方 `tailong-wu/microduck-mjbatch` 克隆（无 LICENSE、
  已标 `NON-OFFICIAL.md`），纯 CPU 脚手架，**正式训练从不用，不可推进本仓**。
- 工具坑：浅克隆推不了新仓（先 `--unshallow`）；`git push` 不能接 `| tail`（吞 rc）。
  **推送兜底**：`github.com:443` 常被本地代理 502（但 `api.github.com` 正常 ⇒ 单域名被挡）
  ⇒ 改走 ssh（origin 本就是 `git@github.com`）+ 免沙箱，一次成功；别原地重试 https。

## 2. 评估协议铁律

- 改上游文件只做**纯新增**不 patch。迭代分档：探索 1024×2000 / 定稿 4096×4000 / 评估 64–512
  （平地步态 32 env 是已标注例外）。**判决以部署侧数字为准**。本地 4070 优先，云只用 4090D。
- **配置冻结必须可测量**。冻结字段前先问**还有谁写它**；两处写者就必须 `cfg.curriculum.pop`
  + 记录实际值 + 闸门。清 `rel_*` 必须用反射不能逐个点名（曾漏 `rel_forward_envs`，
  `velocity_command.py:95-99` 把 vx 钳 ≥0.3，毁掉 <0.3 扫描）。三次发作：
  `standing_envs`、`rel_forward_envs`、**plant 常量**（见 §13）。
- **`error_vel_xy` 单位依赖窗口长度**（`velocity_command.py:61-69`，从不清零）；8 s 读数像
  m/s 纯属巧合。评估脚本对齐 `resampling_time_range=(duration,duration)`。
- **判决双轴**：`err<0.97×` 且 `vx≥0.97×` 才算 improved。**跨版本评估脚本数字不可混用**。
- tyro 已暴露 230 条 `--env.rewards.*` ⇒ 调核宽不改 site-packages；cfg sha 对 CLI 覆盖一无所知
  ⇒ 必须回读生效值。改 curriculum 用 `train_velocity_variant.py`；`--defer-by` 必须连带推后
  更晚 stage 否则静默跳级；`except BaseException` 才能抓 SystemExit 留证据。
- ⚠️ **任何训练都要显式 `--agent.logger tensorboard`**：本机 venv 默认 logger 是坏的
  （`rsl_rl/utils/wandb_utils.py:46` 的 `wandb.Settings(start_method="thread")` 被已装 wandb
  判 `extra_forbidden`）。它炸的位置在 `device=cuda:0` 与 `[BamActuator]` 横幅**之后**，
  极易误判成 plant/设备问题。`tools/train_velocity.sh:243` 也是为此显式传的。

## 3. 读数方差（同 ckpt ×3）

CV：`error_vel_xy` 0.54%、`vx_median` 1.82%、`aacc` 1.67%、`dx_body` 5.5%、
**`abs_dy_body_median` 31.4%** ⇒ 位移类不可复现，`|dy|` 闸门作废。**闸门只能用低 CV 量**。

## 4-6. 策略真实状态（XL330 线，交付基础）

- 核宽比较必须用 **`std/cmd_max`**（官方 0.50 vs 本项目 0.79：绝对值紧、相对松）。
- Baseline（std²=0.10）：**vx = 0.659·cmd − 0.018**；cmd=0 时 err 仍 0.105（49%）⇒ 一半误差是
  速度无关底噪。**策略精确优化了给定奖励，最优点就在 66% —— 任务定义与奖励不一致，非训练不足**；
  6000 轮峰值在 1250 ⇒ 「训练更久」已关闭。
- **单变量 std 0.3162→0.2**：vx 0.2493→**0.3093**、ratio 0.623→**0.773**、err→**0.1620**；
  主改善是截距归零。交付点 **`walk_std004_1250`**（ratio 0.78–0.81）。
  **代价：cmd≤0.12 双稳态死区 ⇒ 部署下限 0.15 m/s**。
- **低速死区机制**：抬脚唯一正激励是 `air_time`（阶跃窗口 0.125–0.3 s）；其余全负权重且乘脚速
  ⇒ 低速「搓地/乱蹬」就是最优解。**别调低 threshold_min 治低速**，是固有盲区；真低速要新任务。
  判「静止」别用 `|vx|<0.01`，看 `aacc`+`landings`+滞空分布。

## 7. 归因方法论

**有现成判据就先跑判据，时间重合是最弱证据。** 「课程跳档致退化」被证伪（上游判据不触发；
干预后变体反而摔更多）⇒ **课程是鲁棒性来源，课程线已关闭**。
**checkpoint 抖动是上游常态**（「always run the walk sweep before picking」）；
`rsl_rl` 无 best-by-eval ⇒ 选点必须外层 sweep。

## 8. 参照系

上游 `alpha_walking` + 真机 v8 在 0.4 指令只做到 0.17 m/s（Rough+Backlash）；我们 0.249/0.309
是 Flat 无背隙 ⇒ **不能宣称更好**。判「未达标」要写明参照指令值还是平台可达水平。

## 9. 部署链与契约（上游 `pollen-robotics/microduck`）

四步：① `export.py`→ONNX ② **`infer_policy.py --walking` = CPU MuJoCo 部署彩排（BAM M6）**
③ `uv run publish`→HF Hub ④ `robotctl policy load`。契约 obs 61/act 14/control_hz 50 与我们吻合；
cfg 与上游 md5 相同（`33a44a7…`）是热插拔铁证。
上游真部署物是 **VelStand**（`0045i2si@2749`），纯 velocity 是 walk teacher；`--switch-threshold`
0.05 运行时 walk/stand 热切换 ⇒ 低速死区真机上先靠运行时（需 stand 策略，我们没有）。
⚠️ 沙箱 huggingface.co 不可达 ⇒ 官方策略集 manifest 未核对。

## 10. parity 闸门

上游导出**零自检**。参考实现必须独立（不能拿 `act_inference()` —— normalizer 同模块 bug
互相抵消）；负对照（拆归一化）必须严重偏离（实测 53000× 容差）。
工具 `tools/flat_walk/check_onnx_parity.py`，max|Δ|=2.65e-06。

## 11. 彩排 ≠ 评估：两个仪器

- `tools/flat_walk/rehearse_deploy.py`（执行副本 md5 须一致）：stub + `spec_from_file_location`
  加载上游 infer_policy，只换外层循环。**不要重写执行器**（重写 = 两个实现互相抵消）。
- ⚠️ 同 ckpt 同 cmd：彩排 vx 0.463 vs 32env 0.312（**+49%**）⇒ **仪器差不是 bug，只能同仪器内纵比**。
- ⚠️ 训练有 delay lag 3-6，彩排延迟路径与训练不是同一件事 ⇒ **延迟维只记缺口不作结论**。
- 判据可判定性：摔倒口径照抄训练 **70°**（`limit_angle=1.2217…rad`）；**摔倒即截断且 vx 记 n/a**；
  触发步单独记 `tilt_at_fall_deg`；**负对照用量纲**（BAM 写力矩 vs legacy 写目标角：0.407 vs 0.000）；
  单机低速只一个样本不可结论；cmd<0.2 时 `moves_forward` 记 not_applicable；cmd=0 是 stand 语义。
- 已验勿重做：`nu=14` 顺序==DEFAULT_POSE；obs 指纹 `[48:51]=[0.4,0,0]`；`USE_PROJECTED_GRAVITY=True`；
  action scale=1.0；episode_length_s=20。

## 12. 上游经验在哪

`microduck_rl` 默认分支 **develop**；真东西在 `AGENTS.md`（17.7KB）与 `docs/*_policy.md`。
raw 404 ≠ 文件不存在（走 contents API base64）。AGENTS.md:161-167 核宽
（「tight std taxed walking so hard the policy stood still」= 死区预言）；`:183-188` 冷门命令要
显式 bucket；`velstand_policy.md:68-69` 发车前先做 reward check。

## 13. plant 是一等坐标（2026-10-28 破案）

- **每一次读数必须带 plant 指纹。** cfg/mdp sha 盖不到传递闭包：velocity cfg 从
  `microduck_constants.MICRODUCK_WALK_ROBOT_CFG` 拿 `actuators`，由 `_BAM_ACTUATOR_KWARGS`
  构造 ⇒ 改 plant 时两个 sha 照样「一切正常」。这是 §2 第三次发作。
- **A/B（同 ckpt，cmd 0.4/32env/8s）**：xl330(kp 200) vx **0.318 / 摔 0%** ↔
  hd1910(kp 32) vx **0.109 / 摔 100%** ⇒ **换 plant = 换任务，必须重训**。
- 工具 `plant_id.py`（两份 eval 已接入）。**clone / 新机器第一件事 =
  `apply_to_live.py --plant hd1910` + `--check`**（官方默认装的是 XL330）。已写进根 README、
  `tools/hd1910/README.md`、stage0 SOP §1.5。⚠️ 期望值里的 `kp_fw=32.0` **已被推翻，见 §16**。
- ⚠️ 坑：`--plant xl330` 恢复会被 Windows 回收站钩子挡（`SHFileOperationW 0x78`）⇒ 手工
  `cp *.xl330.bak` + 删 pyc；**live 把绝对路径烤进 site-packages** ⇒ 换机/挪目录须在新位置重跑。
- **`walk_std004_1250` 及全部数字/ONNX 属 XL330，对 HD1910 无效**（勿再引其 0.78–0.81 ratio）。
  HD1910 有自己的线：`model_5999.pt`（4096×2000→续训 6000）cmd 0.4 ratio **0.747**、不摔、
  **`error_vel_yaw` 1.164（XL330 的 3.4×）**、`|dy|` 0.899 m、`not_sideways` ❌
  ⇒ **缺口是偏航/横移不是前进速度**（治法见 §18）。⚠️ 这些数在 kp=32 下测，见 §16。

## 14. 这台仿真不可逐位复现

**同 seed 只保证初始条件一致，不保证轨迹一致**（实测 seed=1 两次 yaw0 逐位相同，推 **20 步空动作**
就在第 4 位漂了）⇒ **"再跑一遍验证"不算验证**；独立性只能靠 **N 次重复 + sem**。
依据非推测：`mjlab/docs/faq.md`「MuJoCo Warp does not yet guarantee determinism… mujoco_warp#562」，
出路是 `wp.set_device("cpu")`。
⛔ argparse 的 `help` 字符串里**不能写 `%`**（被当格式化符 → ValueError）。

## 15. 偏航缺口（P2，三次重复）

- **symmetry 已证伪**：三次符号翻转（+2.52 / −1.99 / −1.08 deg/s），同号率 0.51 ≈ 抛硬币
  ⇒ 非左右结构性不对称，**不必启用 symmetry 重训**。排除靠**符号**不靠大小。
- **机理 = 航向随机游走**：能走（path_dx 2.3–2.5 m），航向无反馈扩散（|drift| 中位
  13–17 deg/s），净沿初始航向位移只剩 **13–21%**。`sin(dψ)/dψ` 预测 vs 实测 corr +0.55。
- 参照：ANYmal yaw rate error **0.174 rad/s**，我们 1.2 ⇒ 差 7 倍（只当量级）。
- **根子与修法见 §18**（含工具、代价、须 sweep 的取值）。

## 16. ✅ `kp_fw=32` = 出厂默认值（不是运行值）+ P3 裁决

**出处**：BAM 官方 `STS3215Actuator` 构造默认（`vin=7.4, kp=32, error_gain=0.166, max_pwm=0.97`），
本仓 `HD1910Actuator` 当初照抄了这个 32。四条交叉证实「32=出厂未干预值」：BAM 默认、
**15/15 颗只读体检 EEPROM/SRAM 均 P32/D40/I0**、kissqy「结束恢复原值 32/40」、社区同说。

**运行时实际生效的另一组（差 6.4~10 倍）**：kissqy `config-diff` 12 task 全写 `kp_fw=5.0` +
`hd1910_m6.json`；部署 V164/V167 写 **P5/D0/转矩 1000**；社区实机「P 越大越晃」，现用
**P3/D0/转矩 700**。`duty=0.3` 需 **P=32→3.3°**、**P=5→21.1°** ⇒ P=5 是软腿。
⇒ **32 与 5 是两种物理特性的机器**，现有全部 HD1910 数字都在 P=32 下测。
反向（保持 32、部署时 SRAM 写 32）**无社区路线走过**且实机 P 大会颤 ⇒ 已否决。

**另两个同等级差异（并入 P3）**：① 官方控制律有内部限速 `3400·2π/4096 = 5.22 rad/s`
+ `max_pwm=0.97`，本仓自写类**完全无限速** ⇒ 仿真舵机能「瞬移」，独立 sim2real 缺口；
② kissqy 用 m6 我们用 m5（⚠️ 既往「陆吾 m6 因 `actuator` 误标 sts3215 而禁用」**是误判**，
BAM 表 Feetech 唯一合法键就是 `sts3215`）；③ ⚠️ **10-26 那次 m5 vs m6 A/B 无效** ——
kp=32 下**两者都** `terminated_frac=1.0`（全摔），当时记的「差不多」实为「两个都废」。

### ★ P3 裁决：目标植物 `hd1910_kp5`（用户授权）
= 飞特官方 HD1910 ID @7.4V/m6 + **官方 STS3215 控制律** + `kp_fw=5`。
一条命令：`apply_to_live.py --plant hd1910_kp5`（别名 `p3`），`--check` 判
`detected=hd1910_kp5 / kp_fw=5.0 / gate_ok=True`。**现有 HD1910 数字随之作废。**

🔑 **关键机制**（`bam/model.py:229-239`）：**json 同名键会覆盖 `initialize()` 设的值**
⇒ 控制律由 json 的 `"actuator"` 键决定，**读 json 文本看不出来，必须加载后读对象**。
陷阱双向：要官方控制律就得 `"actuator":"sts3215"` 且不写 `max_velocity`/`error_gain_ratio`；
陆吾那份写了 `max_velocity:100`（≈5730°/s）⇒ **官方限速被悄悄拆掉**。
⇒ `probe_plant_law.py`（四份 json 对照）+ `selftest_plant_switch.py`（负对照：改坏 kp 闸门变红、
换 json_path 换 detect，收尾还原并验 sha 一致）。

**顺序（别提前烧 GPU）**：阶段 0 台架实测 → kt/R/死区/齿隙回填 → **一次**重训；
治偏航（`rel_heading_envs>0`）合并进同一次（见 §18）。
⚠️ live **刻意留在 `hd1910`(m5/kp32)** 与归档一致，避免「当前植物≠最近档案」重演 §13；
开训第一步才是 `--plant hd1910_kp5`。

**实机参照**：kissqy 模型放 fanhao 机器 13 次试跑**也没走出连续步态**（卡在运行器/供电/过热，
非模型）⇒ 真机行走社区仍未解决，措辞留余地。可用数：① 15 颗走动电流相加 **≈26 A**
（印证双电池并联 + 15 A 慢断）；② 7.4 V 走起来舵机端跌到 6.5 V 触发保护，抬到 ~8.0 V 才稳
（粗短线+大电容）；③ 主板 84–87℃ 降频 → **25 ms（≈40 Hz）** ⇒ 部署前先散热；
④ **手托机身测行走必然失败**（模型无节拍输入）⇒ 必须落地虚护。

## 17. 社区第三/四轮（2026-10-29）

公众号/盘点文**只当索引**（它可能知道有哪个仓库），仓库全部过 GitHub API 核真实性/许可/活跃度；
过滤：许可干净 + 近 30 天在动 + 有可打样/可跑的产物。新且合格的只有 jyg9 两家（Apache-2.0）：
**`microduck-community-kit`**（`hls_servo_debugger` 浏览器端飞特 HLS 调试器，可按
10-14/20-24/30-34 批量编 ID ⇒ 阶段 0 免 Windows FD exe 的跨平台备选）+ 三块板 KiCad/`production/`
与 **`microduck_ft1910`**（robotd 飞特补丁，真机那天的退路，只登记）。`7757/fanduck` 无许可⇒只读。

第四轮《单总线拆解》：**架构可抄、协议不可抄** —— IMU 伪装成总线从站 ID 200、与 15 关节锁进
**同一次 Sync Read**（消除「本周期关节+上周期姿态」错配）这条与舵机型号无关；但它整套讲
XL330 + Dynamixel P2.0（`@124 len 12`），本机飞特协议是 `@56 len 15`。
⚠️ 通律：**任何讲 XL330 控制表的资料，寄存器地址一律不可直接套。**
**最大收获**：jyg9 的 `imu_to_dxl` 双协议人格（按帧第 3 字节自动识别 Dynamixel 2.0 / 飞特 SCS/HLS），
目标拓扑就是「15 颗 HD-1910-C001 + ID 200 + 1 Mbps」⇒ **IMU 板有 Apache-2.0 现货**（待上机验证）。
清单见 `docs/reference/microduck-社区参考2026-10.md` 第三/四轮。

## 18. ✅ heading 闭环：工具已就绪，只剩「取多少」（2026-10-29，P3 附）

治 §15 的偏航。**在于不必改 model/task 源码**：`rel_heading_envs` 是把 heading env 的 `cmd[2]`
从「窗口内随机常值」**每步**重算成 `clip(0.5·wrap_to_pi(target − heading_w), ±ang_vel_z)`
的比例控制器（`velocity_command.py:81/83/118-123`）。

🔑 **必须回读对象，读源码必错**：`heading_command` 在 `microduck_velocity_env_cfg.py` 里
**一次都不出现**（基类继承 + `**vars(cmd)` 重建）。live 回读 `heading_command=True / stiffness=0.5 /
ranges.heading=(−π,π)`，**`rel_heading_envs=0.0` 是唯一被关的** ⇒ 只改这一个数字。
（§0「通用默认≠任务实际」第三次命中：mjlab 通用默认 0.3。）

**工具**：`tools/train_heading_variant.py`（`--rel-heading-envs X`，进程内改 live cfg，
**site-packages 不动**；护栏：requested vs effective 不一致即退出、反射扫 curriculum 确认写者唯一、
拒绝概率越界）+ `tools/hd1910/probe_heading_loop.py`（CPU 几秒验机制；`cmd[2]` 与闭式**逐位相符**，
负对照偏差 **1.7e6× 容差**）。

⚠️ **踩的两个坑，都不是机制问题**
1. 零动作时闭环几乎不动 ⇒ 判据 margin 只有 **8 倍（擦边绿）**；加 `--drive-yaw` 主动转动后变
   **5083×**。**判据要追求碾压 margin，不是刚过线。**
2. `corr(heading_w, cmd[2]) < −0.9` **FAIL（−0.243）**：base 转过 π 后 `wrap_to_pi` 把关系折成
   三角波，全局 corr 天然拉低 ⇒ 改**局部符号一致性**（结果 441/441）。
   **教训：先确认被测量关系的数学形式，再选统计量。**

**代价**：`rel_*` 是**独立伯努利不是互斥分类** ⇒ heading × forward 期望重叠 `X × 0.20`
（0.30×0.20 = **6%**），其 ω=0 被每步覆盖（实测 1.0 vs forward-only 0.0）；vx 的 `clamp(≥0.3)`
保留 ⇒ forward 桶防低速的作用仍在。真互斥要改 `mdp.py`（被 pristine 检查挡）⇒ **接受并记录**。
观测/动作契约（obs 61/act 14/50 Hz）与 ONNX 通用性都**不变**。

**待定**：`--rel-heading-envs` **不预设值**（上游只给「稀有的重要命令区要显式 bucket」的原则）
⇒ **P3 当天用小档 sweep 由数据决定**，并必须与 P3 **合并为同一次重训**。
完整依据见 `docs/active/microduck-HD1910软件方案.md` §8.2「P3 附」。

