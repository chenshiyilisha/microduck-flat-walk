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
  `upstream`=emwstudio/DuckEMW（只读）、`fork`=chenshiyilisha/DuckEMW（只维护 PR #2）。
  `main` 跟踪 `origin/main` ⇒ `git push` 默认进自己的仓。
- `emwstudio/DuckEMW` 是上游原仓（fork:false、138★）。对它的 PR 是**可选出口不阻塞主线**
  （合并权只在对方；main 无分支保护、PR 无 CI）。
- **训练任务包 = 官方 `pollen-robotics/microduck_rl@develop` 快照，velocity 代码零自加补丁**
  （逐 blob sha 核对：254 文件中 249 个与官方 `b02fdea` 逐字节相同）；mdp.py 头部 NaN 防护
  Patch 1-2/4/5 是**官方自带**（曾误归为自加）。复现链
  `tools/upstream_patches/replay_all.py` 已闭环，唯二残差 = 丢失的
  `patch_joy_foot_peak.py`（只影响 joy，README 已声明）。
- **submodule 已修**：指向 public Apache-2.0 的 `microduck_rl@b02fdea` +
  `microduck-playground@f010ef1` ⇒ 公开读者可复现。
- `microduck-software/repo` 是第三方 `tailong-wu/microduck-mjbatch` 克隆（无 LICENSE、
  已标 `NON-OFFICIAL.md`），纯 CPU 脚手架，**正式训练从不用，不可推进本仓**。
- 工具坑：浅克隆推不了新仓（先 `--unshallow`）；`git push` 不能接 `| tail`（吞 rc）。
  **推送兜底**：`github.com:443` 常被本地代理 502（但 `api.github.com` 正常 ⇒ 是单域名被挡）
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

- 工具 `tools/flat_walk/rehearse_deploy.py`（执行副本 md5 须一致）：
  stub + `spec_from_file_location` 加载上游 infer_policy，只换外层循环。
  **不要重写执行器**（重写 = 两个实现互相抵消）。
- ⚠️ 同 ckpt 同 cmd：彩排 vx 0.463 vs 32env 0.312（+49%）——**仪器差不是 bug，只能同仪器内纵比**。
- ⚠️ 训练有 delay lag 3-6，彩排延迟路径与训练不是同一件事 ⇒ **延迟维只记缺口不作结论**。
- 判据可判定性：摔倒口径照抄训练 **70°**（`limit_angle=1.2217…rad`）；**摔倒即截断且 vx 记 n/a**；
  触发步单独记 `tilt_at_fall_deg`；**负对照用量纲**（BAM 写力矩 vs legacy 写目标角：0.407 vs 0.000）；
  单机低速只一个样本不可结论；cmd<0.2 时 `moves_forward` 记 not_applicable；cmd=0 是 stand 语义。
- 已验勿重做：`nu=14` 顺序==DEFAULT_POSE；obs 指纹 `[48:51]=[0.4,0,0]`；
  `USE_PROJECTED_GRAVITY=True`；action scale=1.0；episode_length_s=20。

## 12. 上游经验在哪

`microduck_rl` 默认分支 **develop**；真东西在 `AGENTS.md`（17.7KB）与 `docs/*_policy.md`。
raw 404 ≠ 文件不存在（走 contents API base64）。AGENTS.md:161-167 核宽
（「tight std taxed walking so hard the policy stood still」= 死区预言）；`:183-188` 冷门命令要
显式 bucket；`velstand_policy.md:68-69` 发车前先做 reward check。

## 13. plant 是一等坐标（2026-10-28 破案）

- **每一次读数必须带 plant 指纹。** cfg sha / mdp sha 盖不到传递闭包：velocity cfg 从
  `microduck_constants.MICRODUCK_WALK_ROBOT_CFG` 拿 `actuators`，由 `_BAM_ACTUATOR_KWARGS`
  构造 ⇒ 改 plant 时两个 sha 照样「一切正常」。这是 §2 第三次发作。
- **A/B（同 ckpt，cmd 0.4/32env/8s/solver 100-50）**：xl330(kp 200) vx **0.318 / 摔 0% / 闸门全绿**
  ↔ hd1910(kp 32) vx **0.109 / 摔 100%**。**换 plant = 换任务，必须重训**。
- 工具 `tools/flat_walk/plant_id.py`；`eval_velocity_in_sim.py` / `eval_tracking.py` 已接入指纹。
- **clone / 新机器第一件事 = `apply_to_live.py --plant hd1910` + `--check`**。官方装的默认是 XL330
  ⇒ 不切就训＝另一个 robot。已写进根 README、`tools/hd1910/README.md`、stage0 SOP §1.5，
  记录模板加 `sim_plant` 字段。**⚠️ 但期望值里的 `kp_fw=32.0` 本身已被推翻，见 §16。**
- ⚠️ 坑：`--plant xl330` 恢复时 `unlink` 会被 Windows 回收站钩子挡（`SHFileOperationW 0x78`）
  ⇒ 手工 `cp *.xl330.bak` + 删 `*.pyc`。**已安装的 plant 把绝对路径烤进 site-packages**
  （`E:/WorkBuddyData/...`）⇒ 换机/挪目录须在新位置重跑，否则 hard fail。
  `server_pack/bootstrap.ps1` 本就在跑 `--plant hd1910`。
- **`walk_std004_1250` 及全部数字/ONNX 属 XL330 plant，对 HD1910 无效**（勿再引用其 0.78–0.81 ratio
  当新硬件预期）。**但 HD1910 已有自己的线**：`model_5999.pt`（4096×2000→续训 6000）cmd 0.4
  ratio **0.747**、不摔、**`error_vel_yaw` 1.164（XL330 的 3.4×）**、`|dy|` 0.899 m、`not_sideways` ❌
  ⇒ **缺口是偏航/横移不是前进速度**。⚠️ 这些数在 kp=32 下测，见 §16。

## 14. 这台仿真不可逐位复现

**同 seed 只保证初始条件一致，不保证轨迹一致**（实测 seed=1 两次 yaw0 逐位相同，推 **20 步空动作**
就在第 4 位漂了）⇒ **"再跑一遍验证"不算验证**；独立性只能靠 **N 次重复 + sem**。
依据非推测：`mjlab/docs/faq.md`「MuJoCo Warp does not yet guarantee determinism… mujoco_warp#562」，
出路是 `wp.set_device("cpu")`。
⛔ argparse 的 `help` 字符串里**不能写 `%`**（被当格式化符 → ValueError）。

## 15. 偏航缺口的确切形态（P2，三次重复）

- **symmetry 假设已证伪**：三次符号翻转（+2.52 / −1.99 / −1.08 deg/s），同号率 0.51 ≈ 抛硬币
  ⇒ 不是左右结构性不对称，**不必启用 symmetry 重训**。排除靠**符号**不靠大小。
- **真机理 = 航向随机游走**：能走（path_dx 2.3–2.5 m），航向无反馈扩散（|drift| 中位 13–17 deg/s），
  净沿初始航向位移只剩 **13–21%**。`sin(dψ)/dψ` 预测 vs 实测 corr +0.55。
- **根子在任务定义**：`microduck_velocity_env_cfg.py:643` **`rel_heading_envs = 0.0`**
  ⇒ 训练中零个 env 练过航向闭环。要治就加 `rel_heading_envs > 0`（**task 改动 ⇒ 必重训**）。
- 参照：ANYmal yaw rate error **0.174 rad/s**，我们 1.2 ⇒ 差 7 倍（只当量级）。

## 16. ✅ `kp_fw=32` 出处已查明 + **P3 已裁决**（2026-10-29 结案）

**32 的确切出处 = BAM 官方 `STS3215Actuator` 的构造默认值**
（`.upstream/bam-62bd8ce.../bam/feetech/actuator.py`：`vin=7.4, kp=32, error_gain=0.166, max_pwm=0.97`）。
本仓 `tools/bam_actuators.py` 的 `HD1910Actuator` 当初照抄了这个 32。

四条来源交叉证实「32 = 出厂未干预值」：BAM 源码默认值、**15/15 颗只读体检 EEPROM 与 SRAM 都是
P32/D40/I0**、kissqy 运行器「结束恢复原值 32/40」、社区「HD-1910 出厂 EEPROM 是 P32/D40/I0」。

**运行时实际生效的另一组值（差 6.4~10 倍）**：kissqy `config-diff` 12 个 task 全写
`kp_fw=5.0` + `hd1910_m6.json`；部署 V164「合同」/V167 写 **P=5 / D=0 / 转矩 1000**；
社区实机「P 越大越晃：P5 晃 56°/s、P3 晃 30°/s」，现用 **P3 / D0 / 转矩 700**。

物理含义（`duty = err·kp·error_gain`，err 单位 rad；单位链路
`ε_f = ε·4096/2π`、`λ = Kp·Kg·ε`）：要 `duty=0.3` 需 **P=32 → 3.3°**、**P=5 → 21.1°**、
P=3 → 35.2° ⇒ P=5 的腿「很软」，策略必须在软动态里学走。

**结论**：32 与 5 不是松紧偏好，是**两种物理特性的机器**；现有全部 HD1910 数字都在 P=32 下测。
反向选项（保持 32、部署时在 SRAM 写 32）**无社区路线走过**，且已知实机 P 大会颤，已否决。

**同时查明两个同等级差异（一并入 P3）**
1. **控制律不同**：官方 STS3215 有 `q_target_smooth` 内部限速
   （`3400·2π/4096 = 5.22 rad/s ≈ 299°/s`）+ `max_pwm=0.97`；本仓 `HD1910Actuator`
   **完全无限速**、`max_pwm=1.0`、多了 `max_current` ⇒ 我们的仿真舵机能「瞬移」，独立 sim2real 缺口。
2. **模型阶数**：kissqy 用 m6，本仓用 m5。陆吾 `1910_m6.json` 已在
   `.upstream/l_1910_m6.json`（`actuator:"sts3215"`、`max_velocity:100`、`error_gain_ratio:1.3217`）。
   ⚠️ **既往「陆吾 m6 因 actuator 误标 sts3215 而禁用」是误判** —— BAM `actuators` 表里
   Feetech 唯一合法键就是 `sts3215`，反倒是本仓的 hd1910/HD1910 名是自己注册的。
3. ⚠️ **10-26 那次 m5 vs m6 A/B 无效**：两者在 kp=32 下都 `terminated_frac=1.0`（全摔），
   当时记的「差不多」实为「两个都废」。

### ★ 裁决结论：P3 目标植物 `hd1910_kp5`（用户授权「你觉得合适就好」）

= **飞特官方 HD1910 ID 参数 @7.4V/m6** + **官方 `STS3215Actuator` 控制律** + **`kp_fw=5`**。
已落成一条命令：`apply_to_live.py --plant hd1910_kp5`（别名 `p3`），`--check` 判
`detected=hd1910_kp5 / kp_fw=5.0 / gate_ok=True`。**现有全部 HD1910 数字随之作废。**

🔑 **实现的关键 = BAM 的覆盖机制**（`bam/model.py:229-239`
`load_parameters_from_dict`）：**json 里出现的同名键会覆盖类 `initialize()` 设的值**。
所以控制律是靠 json 的 `"actuator"` 键选的，而这个陷阱双向都有：
- 要拿官方控制律 ⇒ `"actuator":"sts3215"`，且 json **不能写** `max_velocity`/`error_gain_ratio`
  （写了就失去官方 5.2155 rad/s 限速）
- 陆吾 `l_1910_m6.json` 写了 `max_velocity:100`（≈5730°/s）⇒ **限速被悄悄拆掉**。
  **读 json 文本永远看不出来**，必须加载后读对象。

⇒ 新增 `tools/hd1910/probe_plant_law.py`（打印实际生效的 `law_class`/`kp`/`max_velocity`/
`max_pwm`/`error_gain`；四份 json 实测对照：只有 derived 那份保住了官方限速）。
⇒ 新增 `tools/hd1910/selftest_plant_switch.py`（含**负对照**：改坏 `kp_fw` 闸门必须变红、
换掉 json_path 必须换 detect；最后还原现场并验 sha 逐字节一致）。

**执行顺序（别提前烧 GPU）**：阶段 0 台架实测 → 真机 kt/R/死区/齿隙回填 json → **一次**重训。
若要治偏航（`rel_heading_envs>0`）合并进同一次训。

⚠️ 本机 live **刻意留在 `hd1910`（m5/kp32）**而非新植物：与已归档数字保持一致，
避免「当前植物≠最近档案」静默重演 §13。开训第一步才是 `--plant hd1910_kp5`。

**附：实机工程参照（`replica-2026-10/docs_HD1910-20261011-...`）**
kissqy 模型放 fanhao 机器上 13 次试跑**也没走出连续步态**（卡在他们的运行器/供电/过热，
不是模型）⇒ 真机行走社区仍未解决，措辞留余地。三条可直接用的数：① 15 颗一起走动自报电流
相加 **≈26 A**（印证「两 NP-F550 并联 + 15 A 慢断」）；② 7.4 V 走路时舵机端跌到 6.5 V
触发保护，抬到 ~8.0 V 才稳（粗短线+大电容）；③ 主板 84–87℃ 降频 → 周期 **25 ms（≈40 Hz）**
而非 50 Hz ⇒ 部署前先解决散热。**手法**：手托机身测行走必然失败（模型无节拍输入，靠身体
晃动+IMU 反馈）⇒ 必须落地虚护。

## 17. 社区第三/四轮（2026-10-29）

公众号文章**只当索引用**，仓库逐个过 GitHub API 验许可与活跃度。

**第三轮**新收两家 Apache-2.0：
- `jyg9/microduck-community-kit`（24★）：`imu_to_dxl`/`banana_pcb`/`dxl_hub` 三块板 KiCad +
  `production/`、GD32F303CC 固件、**`hls_servo_debugger`（Flask+pyserial 浏览器端飞特 HLS
  调试器，可批量编 ID）** ⇒ 阶段 0 免 Windows FD exe 的跨平台备选。
- `jyg9/microduck_ft1910`（0★）：官方源码 + 飞特总线补丁 ⇒ 真机那天的自编译退路（只登记）。
- `7757/fanduck`（无 LICENSE）⇒ 只读，不许抄。

**第四轮**（《MicroDuck 单总线方案拆解》）：**架构可抄，协议不可抄**。
- 可抄：IMU 伪装成总线从站 **ID 200**，与 15 关节锁进**同一 Sync Read 事务**
  ⇒ 消除「本周期关节 + 上周期姿态」错配；故障边界统一便于 watchdog/降级。ID 表 10-14/20-24/30-34
  与本机 SOP 吻合（第三方交叉验证）。
- **不可抄**：文章整套是 XL330 + Dynamixel P2.0（`@124 len 12`、goal `@116 len 4`），
  本机 HD1910 是**飞特协议**（`@56 len 15`、goal `@42 len 2`、波特率寄存器 6 且**出厂即 1M**）。
  文中「Return Delay 吃掉 40% 周期（8 ms）」也套不上：本机实测 15 颗同步读 **4.8 ms @7.2 V**，
  理论 3.2+0.5 ms，比 XL330 版还省 ⇒ 无需为 Return Delay 焦虑。
- **最大收获**：回头细查发现 jyg9 的 `imu_to_dxl` **是为我们的配置量身做的** —— 双协议人格
  （Dynamixel 2.0 `FF FF FD 00`/CRC-16 与 飞特 SCS/HLS `FF FF <ID>`/`~SUM`，**按帧第 3 字节自动识别**），
  目标拓扑明写「与 15 颗 FeeTech HD-1910-C001（10-14/20-24/30-34）并联 1 Mbps 半双工，节点 ID 200」。
  且其飞特侧 `sync_read @56 len 15` 与本仓《飞特适配架构》独立推出的数**完全一致**
  （两条互不相干来源撞出同一个数 ⇒ 两边可信度一起上升）。⇒ **IMU 板不再是"延后"，有 Apache-2.0
  现货**（仍需上机验证，作者自述未经第三方复核）。
- ⚠️ 通律：**任何讲 XL330 控制表的资料，寄存器地址一律不可直接套**。
- 清单见 `docs/reference/microduck-社区参考2026-10.md` 第三/四轮。
