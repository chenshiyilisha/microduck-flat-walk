# HD1910 · kissqy 上板导入清单（有板再勾）

对应 `docs/active/microduck-HD1910阶段C软件清单.md` §4。  
**不自写 robotd。** 主链：kissqy 镜像 + 本仓 ONNX（obs 61 / act 14 / 50 Hz）。

出处：清单 §1–4；`stage0_software_prep.md`；`docs/reference/microduck-mjlab-GPU与三个新仓库.md`（0.9/0.5/0.7）；fanhao 飞特方向说明。

---

## A. 镜像与版本（先记再动）

| # | 项 | 期望 / 备注 | □ |
|---|---|---|---|
| A1 | 系统镜像 | kissqy R1（`microduck-zero3w-0.15.1-R1.img.xz`） | |
| A2 | 机器人中控 | **V167**（修鸭身抖动；配套 control.43） | |
| A3 | 记下确切版本 | 镜像 tag / 中控 Vxxx / 固件 control.4x | |
| A4 | 许可 | 作者原创部分**个人非商业** | |

下载入口：`stage0_software_prep.md`。

---

## B. 总线与方向（上策略前）

| # | 项 | 期望 | □ |
|---|---|---|---|
| B1 | 舵机家族 | `[bus] servo = "feetech_hls"`。**`ServoKind` 的 `#[default]` 就是它**，所以不写也对；写成 `dynamixel_xl330` 会让 15 维 `joint_vel` 小 3.15×。⚠️ **没有 `protocol` 这个键** —— `Bus` 带 `#[serde(deny_unknown_fields)]`，抄 kissqy 那份的 `protocol = "feetech"` 会让 robotd **整个配置文件加载失败**（不是静默忽略）。🔴 **更要紧的是「两代 schema 不通用」**：`out/upstream_ref/` 是**A 代**（Radxa+XL330，有 `[board]`、`bus.fast_sync_read`、无 `joint_ids`、1 Mbps），`.upstream/DuckBuddy-main/` 是**B 代**（OPi+HL-2915，有 `servo`/`joint_ids`/`[battery]`/`[thermal]`、无 `board`/`fast_sync_read`、500 kbps 写死）。HD-1910 是 Feetech ⇒ **只能用 B 代**；而某个键在 A 代是真的、在 B 代照样是加载失败。我们那份 toml 混着两代写过（`servo`/`joint_ids` 来自 B、`fast_sync_read` 来自 A）⇒ **两代都起不来** | |
| B2 | `robotctl health` | bus 绿；loop **50 Hz 0 missed** | |
| B3 | 方向表 | HD1910 读数方向常与 XL330 **相反** → 多数关节 **−1**（以本机标定为准，逐颗核对） | |
| B4 | 零位 / 限位 / IMU | 关节工作台过一遍；IMU 俯仰偏差必须运行时校掉。⚠️ **别指望舵机自己的行程当限位**：EEPROM `reg9/reg11 = 0/4095` 在物理上不起作用，实测推超程时堵在 1213/2816（相隔 1603 counts ≈ 141°），而 reg19 的过载位 32 是刻意关的 ⇒ 撞住不卸力，只有过流 3.25 A 兜底 | |
| B5 | **reg50 的真值由 robotd 算出来，不是 toml 里那个 `gain`** | `reg50 = clamp(round(policy.gain × position_kp / 200), 1, 254)`（`feetech.rs:236`，`KP_REFERENCE=200`）。上游单测钉死：`kp_for_gain(200,8)=8`、`(50,8)=2`、`(160,8)=6`、`(0,8)=1`。**要 kp8 就写 `policy.gain=200` + `position_kp=8`（都是默认值）；要 mode 0 下与 plant 等价就 `position_kp=16`**。`set_gains_all.py --persist` 手写 EEPROM（RAM 50 / EEPROM 21）只覆盖 "robotd 起来之前" 那段窗口——robotd 每次启动/切增益都会重写 reg50（§22.7/§22.8） | |
| B6 | D / 转矩 | 部署的 **D 是 `[bus] position_kd`（默认 8），在 bring-up 写进 reg51**（`feetech.rs:399`），**不是 0** —— `set_gain` 只钉 P；`bus.rs` 里那句"I=0、D=0"是 **Dynamixel 路径**，Feetech 不走它。台架补测（mode 0 / 4.6 V，见 §8.2）：D=8 花掉约 5% 增益、但把 2 Hz 滞后从 73.9° 降到 68.0° ⇒ 是净收益，别去关它。转矩上限 1000 | |
| B7 | **`[policy] gain` 不要改成 8** | 它是 **XL330 口径**的参考值（`feetech.rs:115 KP_REFERENCE=200`），**不是寄存器 P**。`gain=8` + 默认 `position_kp=8` 会写出 `round(0.32)=0 → clamp 到 1`：每颗舵机 P=1，机器人瘫软，而症状看起来是"策略不会走路"。⚠️ 本项目 2026-11-04 之前的清单和 `audit_robotd_toml.py` 都写过 `gain = 8`，已一并改掉 | |
| B8 | 跑起来后回读 reg 50 | 腿应读到 **`round(gain × position_kp / 200)`**（部署档 = 16）。读到 1 ⇒ B7 被人按旧清单改成了 `gain=8`；读到 8 ⇒ `position_kp` 还是默认 8；读到 4 ⇒ 刚跌倒过，`gain_limp` 还在 RAM | |
| B9 | **增益标度家族（比例会自动保住，不要手调）** | 因为 running/standing/limp/pose 全都过同一个 `kp_for_gain()`，任何统一缩放之后**比例天然不变**：`gain_limp=50 → 2`（0.25×）、`limp_fall_pose_gain=160 → 6`（0.80×）、`standing_gain_ratio=0.8 → 6`。⚠️ 旧清单写的 `gain_limp=3` / `limp_fall_pose_gain=8` 是把 gain 当寄存器值算出来的，实际会落到 1，**不要用**。真正的坑是 `position_kp` 太小：`position_kp=2` 时 160 也落到 2，"瘫软"和"回站姿"变成一个值 —— `audit_robotd_toml.py` 现在按寄存器单位判这一项（24 项自检）。`[policy] action_scale = 1.0`（默认 0.9 是 alpha 策略的，会让每个动作小 10%；匹配训练时才是 1.0，§8.5.6） | |
| B10 | **两个「中立」默认值其实不中立** | ① `[policy] head_lowpass / legs_lowpass` 默认 **0.5 / 0.7**——robotd 注释说这是 alpha 策略的训练值，但**本训练管线里零低通**（`grep low_pass` 在 microduck_rl + mjlab 1.3.0 + bam 全无命中，动作是 `target = current + action*scale`）⇒ 必须写 **1.0**，否则等于给策略从未见过的目标加了个 τ≈17 ms 的一阶滤波（2 Hz 处 −2%、4 Hz 处 −7%、相移 6–11°）。② ~~`[bus] fast_sync_read` 默认 true~~ —— **这一项不存在**（2026-11-04 逐字核过）。`fast_sync_read` 在整棵 DuckBuddy 树里出现 **0 次**：0x8A 还是 0x82 由 rustypot 的 `sync_read_raw_data` 决定（`feetech.rs:412/474/556`），**没有配置键**。它属于**另一个 fork**（那些笔记里引的 `params_lib.rs`），写进这份配置就是未知键 ⇒ `deny_unknown_fields` **拒绝整份文件**（与 B1 的 `protocol=` 同一个坑）。⇒ **结论不变但动作相反：不是写 `false`，而是把这行删掉**。台架那次 0x8A/0x82 的对照仍然有效（0x8A 返 0 字节、0x82 同步读与单读一致），它证明的正是「走 Feetech 路径是对的」。**优先级**：① 是硬故障（训练时零低通），②是"写了就起不来" | |
| B11 | **保护开关 reg19 = 13**（EEPROM，逐颗写） | 出厂只有 **4（仅过热）**，过压/过流/过载/磁编全关。写 **13 = 电压+过热+过流**，`set_protection.py --ids 1,...,15 --apply`。**时序不能改**：必须在**断电重上电后、robotd 起来之前**跑（那时 reg40 默认 0 = 扭矩关，是官方要求的写入前置条件），解锁 0.25 s → 写 0.50 s → 上锁 0.50 s；**绝不切 mode**（会从 EEPROM 重载、把刚写的值冲掉）。写完**必须再断电一次**跑 `--verify`：回读 PASS 只证明 RAM 影子改了，前 3 次就是这么假成功的（§8.5 台账）。⚠️ **过载位 32 绝不能开**，且别拿「恢复出厂」当安全动作（出厂 52 含 32） | |
| B12 | **`[bus] joint_ids`（15 条，Feetech 必需）** | 空或重复 ⇒ **总线拒绝打开**，优先报 `"the key to set"` 而不是猜哪颗是哪个关节（`robotd/src/main.rs:5495` 有对应测试）。顺序**固定按 `JOINT_NAMES`**：0-4 左腿(hip_yaw/hip_roll/hip_pitch/knee/ankle)、5-9 颈/头(neck_pitch/head_pitch/head_yaw/head_roll/mouth)、10-14 右腿(同左)。建议 ID 沿用上游 `JOINT_IDS`（右腿 **10-14**、左腿 **20-24**、头 **30-34**），IMU 板 **200 不在这个表里**。台架那颗已是 **ID 10 = right_hip_yaw**，与上游一致。**不要照抄参考表**：`model.rs:15` 那份是 XL330 机身的映射，robotd 的注释明写「a guess drives one joint with another's targets」。真机解这张表的工具（只读、不写任何寄存器）：`python servo_probe/identify_joints.py --port COM3` —— 逐条关节提示"扳哪个、怎么扳"，每个 ID 采 3 s 峰峰值，**两个一起动就判"分不清"**（阈值 8 步 ≈0.7°，要求第二名 < 第一名的一半），最后直接打印可粘贴的 `joint_ids = [...]` | |
| B13 | **robotd 打开总线时的三项 EEPROM 硬校验** | `feetech.rs:386` 逐颗比对，**不满足就 `IoError::Bus` 拒绝启动**，注释明写「EEPROM is checked, not corrected」——它不会替你改。对照台架现状：① `baud` 由 `feetech.rs:35 BAUD_RATE` 决定：B 代写 **500 kbps**（reg6 = 1），我们是 **0（1 Mbps，出厂值）**。**但这一项建议改板子那边、不要改舵机** —— `feetech.rs:34` 给的理由只有一句 *Exactly representable on the A733's UART7 (24 MHz/16/3). 1 Mbit/s is not.*，A733 是 **B 代那块板**（Orange Pi），不是我们要用的 Radxa Zero 3W（RK3566：官方 debug UART 默认 1.5 Mbps、datasheet 写 UART up to 4 Mbps、上游主仓自己在 Zero 3W 上跑 1 Mbps）。⇒ 改 `BAUD_RATE = 1_000_000` + `BAUD_REGISTER_VALUE = 0`，**15 颗的 reg6 一颗都不用写**。⚠️ 编码陷阱：`model.rs:177` 的 `("baud_rate", 3), // 3 = 1 Mbps` 是 **Dynamixel** 编码（XL330 路径），套到 Feetech 上 3 = 128 kbps ⇒ 上电即失联；Feetech 是 **0 = 1M / 1 = 500k**。⚠️ 前提：适配板/桥要能吃 1 Mbps（台架 CH343 已证明可以，RS485 板未验，见 §11.5）。每 tick 总线预算见 §11（500 kbps 下 10.9 ms / 20 ms）；② `mode` 要 **0**，我们是 **4**（出厂默认）✗；③ `limits` 要 **0/4095** ✓。**mode 的改法**（用验证过的 EEPROM 时序：解锁 0.25 → 写 0.50 → 上锁 0.50 → 断电回读）：`python servo_probe/hd1910_ident.py mode --port COM3 --id N`。**不能在 robotd 跑着的时候做**，每颗做完必须**断电重上电再回读**。mode 0 与 4 的差异见 B14 | |
| B14 | **mode 0 vs mode 4 已在台架复核：差一倍**（2026-11-04） | 10–90% 阶跃上升时间 mode4 182/207/230 ms vs mode0 363/413/436 ms（4.4°/8.8°/17.6° 三档），**比值恒 1.9–2.0**；超调≈0、稳态误差 1 步。限速(reg46 250→1000)、加速度规划(reg41 0/100/254)、goal time(reg44 500→50) 全部排除。⇒ **部署在 mode 0 上的 plant 比 kp8 平台慢一倍，属 plant 口径不一致**。三条路：①**改 fork 允许 mode 4**（代价最小，但要先确认 mode 4 下 reg40 关不掉扭矩 robotd 能否接受）②在 mode 0 上重训 ③先测正弦带宽。**③ 已于 2026-11-04 跑完，缺口补上且结论不变**：0.5–4 Hz 五档 mode 0 在每个频点都比 mode 4 差 12–45%、多滞后 6–21°；2 Hz（=步频）gain **0.35 vs 0.60**、lag **+90° vs +74°** ⇒ 「阶跃太苛刻」解释不掉。⚠️ 顺带查实 `reg46` 的 0 是**停转**（不是无限速），250 与 1000 结果逐位相同 ⇒ 慢不是限速造成的。**2026-11-04 二次复核：把"模式差异"改判为"增益差异"。** 钉住 2 Hz / 13.2° 扫 P（`probe_pgain_speed.py`）：mode 0 的 P=8/12/16/24 给 gain **0.350 / 0.489 / 0.604 / 0.744**，而 **mode 0 在 P=16 与 mode 4 在 P=8 完全等价**（0.604 / +73.9° vs 0.604 / +73.8°，等效拐点 fc 1.21 vs 1.23 Hz）。⇒ 同一 P 下 mode 4 的环路增益约为 mode 0 的两倍；**"部署比 plant 慢一倍"的根因是 kp=8 而不是 mode 本身**（仿真 @4.6 V / kp8 的 fc = 1.24 Hz，与两者都吻合）。⇒ 新增第 ④ 条路：**不动 mode、只把寄存器 P 从 8 提到 16**，不改 fork 也不重训。**落地点不是 `[policy] gain`**（它是 XL330 口径，写 8 会变成 reg50=1，见 B7）：正确改法是 `[bus] position_kp = 16`（腿）+ 保持 `policy.gain = 200`。**全频段复核**：0.5/1/2/3/4 Hz 五点 mode0/P16 与 mode4/P8 的 gain 差 ≤0.003、lag 差 ≤0.4°。**并且补测了 D**（部署会写 `position_kd=8`，台架基线是 D=0）：mode0 P16/D8 给 2 Hz gain 0.574 / fc 1.17 Hz，已是 plant@4.6V（0.621 / 1.28）的 92%；而现有 P8/D8 只有 0.337 / 0.69 = 54%。⚠️ ④ 与 ① 的未决项相同，都是电流/发热，而这颗的**负载/电流回读是坏的**（`reg60` 恒 0、`reg62` 按 u16 读会把温度拼进来得 7469、`reg69` 正弦中读到 16000 量级）⇒ 台架判不了。**验收改看温度**：robotd 的 `SlowSensors` 只报电压与**每关节温度**（`io.rs:81`，读 reg144–146），没有电流；所以提 P 的代价只能靠在真机上跑一段看 per-joint temp 有没有逼近过热 latch。**订正（2026-11-04）：latch 在 `reg13 = 80 °C`（EEPROM 阈值，实测值），由 `reg19` bit0 使能；`reg70` 是 69-70 电流的高字节，不是温度阈值** —— 之前写的「reg70 latch」是错的。 | |
| B15 | **reg44 语义与 HLS 不同，但实测无害** | `feetech.rs:57` 自己注明 GOAL_CURRENT=44 是 **HLS 专有**（HLS 上＝电流上限 6.5 mA/count；**STS 映射上是 goal time**），而 HD1910 是 STS。robotd 默认写 `2925 mA / 6.5 = 450`，HD1910 会当成 goal time＝450。**台架实测（2026-11-04）无害**：出厂 reg44＝500，改成 50 后 mode 0 的 rise 仍是 441 ms（vs 436），且实际动作 436 ms 远短于 goal time，说明它只是**最长时限**、不构成限速。⇒ 不用改这一项；但若哪天症状是「动作像被拖慢」，先看 reg44 | |
| B16 | **电压/温度遥测走的是 feetech 路径（reg62/63），不是 `bus.rs` 的 144–146** | 容易误判：`bus.rs:41 SLOW_READ_ADDR = 144` 是 **XL330 的 Dynamixel 实现**；我们 `[bus] servo = "feetech_hls"` 走的是 `feetech.rs`，其中 `PRESENT_VOLTAGE = 62`、`slow_sensors` 读 (62, len 2) = 电压 u8×0.1 + 温度 u8（`feetech.rs:63/677`）。台架实测：**reg144/145/146 在这颗上完全无应答（None）**，而 reg62 = 46（4.6 V）、reg63 = 29 °C 正常。⇒ 电学保护（电池 6.6 V 关断）与每关节温度**都可用**，不必改；但读代码时别照着 `bus.rs` 去改地址。 | |

| B17 | **`[battery] cells` 必须写死 `[2]`，不能留默认** | 默认是 **`[2, 3]`**（`lib.rs:68`），意思是"这份文件没说"。而 `identify_pack` 是按电压**逐串**判的（`model.rs:308`）：一块 3S LiPo 11.1 V → 3.7 V/cell ⇒ 判成合法 3S ⇒ robotd **照常驱动**。HD-1910 额定 **4–8.4 V，接 3S 会烧**（`lib.rs:52` 原话 "burn on 3S"），而这一步**不会报任何错**。⇒ 写 `cells = [2]` + `max_volts = 8.4`（满电 2S LiHV 8.7 V 已超额定，靠 max_volts 拦住）。⚠️ 顺带一个台架后果：**4.6 V 台架跑不了会走路的 robotd** —— 4.6/2 = 2.3 V/cell 低于 2.95 V 下限，`identify_pack` 直接报"既不是 2S 也不是 3S"、机器人保持瘫软。robotd 上电至少要 ~6.0 V | |
| B18 | **`[thermal] walk_max_c = 70`**（默认 65，也能用） | 舵机自己的过热 latch 是 **reg13 = 80 °C**（2026-11-02 从 ID 10 的 EEPROM 备份读出，出厂值；STS 手册写"初始 70"，可能是固件版本差异）。robotd 的 `thermal` 到 `walk_max_c` 就**拒走**（zero twist），到 80 就是舵机自己切扭矩 = 走路中直接趴下。上游在 HL-2915 上从 65 调到 70，理由是"给一次走路试跑留够"（13 °C/分钟 的升温速度）。⇒ 70 留 10 °C 余量；`warn_c` 保持默认 55。⚠️ **`audit_robotd_toml.py` 现在检查 `[thermal]` 段内部一致性**（2026-11-04 加）：`rest_c < walk_max_c`（否则腿在拒绝走的温度就先瘫了）、`resume_c < rest_c`（否则休息永远不会结束）、`hysteresis_c > 0`（否则阈值上跳动开关）、`sit_c > rest_c`（否则坐着又瘫）、`rest_min_s >= 0`。5 条负对照在 selftest 里 | |
| B19 | **导策略前先过「契约」这一关**（不需要板子） | `obs.rs` 自己的头注释写着 *this is the highest-risk code in the crate*：61 个 float 里错一个偏移，**不会报错**，只会得到一个「看起来在走、然后摔倒」的机器人，症状像调参。同一类错误还有关节序（robotd 原话 *a guess drives one joint with another's targets*）。⇒ 跑 `python tools/hd1910/verify_policy_contract.py --onnx <图> --toml <配置>`，它拿**两个独立来源**对质：Rust 侧解析 `obs.rs` 的布局表 + `model.rs` 的 `MOUTH_INDEX`/`DEFAULT_POSITION` + `duck-ipc-proto` 的 `JOINT_NAMES`；训练侧解析**真跑那个 task 的 cfg**（actor obs 项顺序与宽度）与编译后的 MuJoCo 模型（执行器顺序）。2026-11-04 实测结论（P8 图 + mode0 配置，8 项全绿）：布局 = `gyro 3 | gravity 3 | joint_pos 14 | joint_vel 14 | last_action 14 | twist 3 | head 4 | body 6`；13 宽命令块内部拆成 `3 / 4 / 6`；14 个策略关节序与模型的执行器序**逐位相同**（均跳过 mouth，`MOUTH_INDEX = 9`）；home 位姿与 `HOME_FRAME` **逐位相同**（max|Δ|=0）；动作 = `home + a × 1.0`（`scale=1.0` 且 `use_default_offset=True`，与 `[policy] action_scale = 1.0` 一致）；`decimation 4 × timestep 0.005` = 50 Hz = `[control] hz` 默认值。⚠️ 它**查不到**三件事：躯干坐标系的朝向（靠 B4 的 IMU 标定）、每关节符号/零点（靠 B3）、以及任何舵机侧的东西 | |
| B20 | **`[bus] imu_median = false`**（上游默认 true，这里是**故意偏离**） | 台架/源码量出来的：中值滤波是**纯一拍延迟**，50 Hz 下正好 **20 ms，每一拍都有**（`verify_imu_chain.py`，阶梯/斜坡都验过）。而训练侧 IMU 的延迟包络就是 **0–1 个控制拍 = 0–20 ms**，一半的 env 是 0（`microduck_velocity_env_cfg.py:564-569`，注释写着 *"was 3 (=60 ms worst case); real dxl IMU path is fast"*）⇒ 开着中值，每一拍都顶在包络上沿，再叠上芯片自己的采样滞后（0 到一个 SFLP 周期）就是 20–30 ms，比策略见过的任何情况都晚 0–10 ms。**`imu.rs` 自己就写着**：*walking policies fail past ~20 ms of IMU lag (BAM simulation, 2026-10-10): with it, the HL-2915 robot's trunk rocked and the policy flailed the neck as on the robot*。它换来的抗尖峰并不承重：包有校验和（rustypot `read_status_packet`），"SFLP 没起来"的全零块另有专门分支 | ⚠️ 台架若真看到单块尖峰，改回 true 并记录原因 |
| B21 | **IMU 上电姿态 = 参考姿态**（robotd 会等你，但不会提醒你歪着开机） | SFLP 的参考系是**上电那一刻的姿态**，之后靠加速度计收敛；`ready()` 要 **25 个样本 = 50 Hz 下 0.5 s**，`main.rs:2539` 在这之前**不允许策略驱动**（日志 `IMU converging (keep the robot still)`）。⇒ 开机必须让机器人**正常站立且静止**。躺倒/侧躺开机时，收敛出来的"水平"是偏的，而这一步不会报错。⚠️ 另两个已知边界：① 芯片只发 `qx,qy,qz`，`w` 靠 `+sqrt(1-n²)` 重建 —— ST 明确"*the SFLP output quaternion is chosen to have qw >= 0 always*"，所以这个假设是有背书的、不是碰巧；② 同一个答复也承认 `n≈1` 附近精度下降，**折算到本项目就是躯干俯仰 ≈90°（趴在地上）时水平线有 2° 级误差**，对 26° 闸门和 60° 跌倒判据无影响。③ 传感器坐标与世界坐标重合的姿态（本项目 = **抬头 90°**）会让整块读出 `0,0,0`，正好撞上"SFLP 未启动"的哨兵 —— 窗口只有 6e-8，实际姿态进不去 | |
| B22 | **舵机零位：`bus.joint_offsets` 是唯一杠杆，链上没有 0x0B 校准指令** | `feetech.rs:85` 硬编码 `CENTER = 2048`，注释说 *伺服器装中立位时已对中到 2048* —— **有厂商背书**（HL-2915 官方参数表：`Neutral Position 2048`、`Resolution 0.088° (360°/4096)`）。`counts_to_rad = sign_magnitude(raw) - CENTER - offset`；`joint_signs`/`joint_offsets` 是 `[bus]` 键、**默认空 = 全 +1 / 全 0**（`main.rs:1153-1154`），toml 没写 ⇒ 每根关节都按 2048 对零。**台架行程 `[1213, 2816]` 关于 2014.5 对称、关于 2048 不对称** —— 但那是**行程中点不是中立位**，不能直接相减。⚠️ **HLS 舵机固件 ≥3.43 不支持 `reg40` 写 128 校准中位**（飞特文档明写），须改用指令帧 `FF FF ID 02 0B F1`（当前位→2048）或 `FF FF ID 04 0B <lo> <hi> EB`（任意值）。而本链 `reg40` 只写 0/1、**零处** 0x0B ⇒ 重新标零位只能改 `joint_offsets`。`servo_probe/calibrate_offsets.py --scan`（只读）量 raw 算 offset，`--apply-toml` 写入 | |
| B23 | **`audit_robotd_toml.py` 的 R9–R26 审计轴（2026-11-04/05 加，纯软件）** | 除 B18 的 thermal 一致性外，audit 还检查：**R9** `[safety] limp_fall_*` 阈值关系（`limp_fall_tilt_z` 必须比 `limp_fall_predict_z` 更负——"已倾 26°"是前置、"预测 60°"是触发；`limp_fall_debounce_ms` 必须比 `fall_debounce_ms` 短——预测先触发、实际摔倒后触发）；**R11** `[update_gate]` 与 `[control] hz` 联动（`min_achieved_hz >= hz` ⇒ 永久 unhealthy 静默回滚；`stall_periods` 换算后 <300ms ⇒ 普通调度抖动触发死循环检测）；**R13** `[control] heading_hold_gain > 0`（策略没训练过这个 PD，症状是走弯路/漂移，像电机不平衡）；**R14** `[bus] imu_median = true`（中值=20ms 纯延迟，训练包络一半是 0；详见 B20）；**R15** `[policy] standing_action_scale` 与 `action_scale` 不一致（站立/行走缩放不同）；**R16** `[bus] imu_axes` 格式（三项互异带符号轴、符号可选、重复/缺项/非轴判 WARN——写错则姿态全乱而站不直像零位问题）；**R18** `[bus] joint_signs`/`joint_offsets` 长度（≠15 则静默截断，尾部关节回落到 sign=+1/offset=0=舵机中位，症状是"站不直/一条腿恒定偏置"，不报错）；**R19** `[bus] mouth_torque=false + mouth_wake=false`（嘴起始 limp 且 `mouth_wakes` 恒 false ⇒ 永远不醒来，症状是"嘴不动"像接线/ID 问题，不报错）；**R20** `[bus] imu_pitch_trim_deg`/`imu_roll_trim_deg`（f64 无 Rust 值域校验，写错 10 倍则站不直像零位问题；±90 是重力感知翻转的启发式界限——这是作者的推理不是源码读出的）；**R21** `[theremin] near_m >= far_m`（区间反转或非正 ⇒ 玩具永远收不到手，症状像传感器/接线问题）；**R22** `[detect] threshold > 1.4`（INT8 饱和值，来自 lib.rs:351-356 注释；超过则检测器永不触发，症状像模型/NPU 问题）；**R23** `[detect] enabled + hz`（`mediad` 与控制环**同板**抢 CPU，lib.rs:339 说每帧 ~50ms、lib.rs:347-349 称 2Hz 是"热数字"、跑满 95°C 降频到 408MHz「走得难看」；enabled 下视频帧率烧满一核 ⇒ 症状像电机/环路问题；**仅 enabled 时判**，默认 off 则 hz 惰性不报）；**R24** `[theremin] min_zones/statuses/hold_ms`（`min_zones > 32`（> 64 格网格的一半，tof.rs:28-30）不可达 ⇒ 玩具永不发声；`statuses` 只剩 `{5,9}` 正是 hand.rs:22-27 记录的"30cm 死掉"的已知配置；`hold_ms=0` 关抗抖、过大留残音）。**R25** `[audio] pet_enter_threshold`/`pet_exit_threshold`（lib.rs:508-510 默认 0.95/0.85 是滞回：enter 必须 > exit，否则滞回带空/反转，分类概率落在带内则抚摸状态每 tick 翻转，机器人反复 coo，症状像麦克风噪声/环境吵而非两数字配置笔误；两者都是概率须在 (0,1)）；**R26** `[policy] voltage_adapt + nominal_voltage`（lib.rs:671-676 scale = nominal/measured；`nominal<=0` 则 scale=0 全动作归零机器人定住，症状像电机死了；`nominal` 与 `[battery] cells` 错配则 scale 差 ~1.3x，症状像环路增益/电机问题；**仅 voltage_adapt=true 时判**，默认 off 则 nominal 惰性不报）。**⚠️ R17 误读教训**：`head_lowpass`/`legs_lowpass` 一度被我基于 lib.rs:630 注释（"the value the alpha policies are trained with"）加了一条判 `>=1.0` 为 WARN 的检查——但同文件 R7 已基于 `grep -r low_pass` 零命中给出相反的正确结论（训练侧根本没有低通，1.0=pass-through 才是匹配值）。注释描述的是上游 alpha 策略，不是本训练链。**矛盾暴露即错误暴露**，已删除 R17、留注释防止二次误读。**108 项自检含 50 条负对照**。跑法：`python tools/hd1910/audit_robotd_toml.py --toml <配置> --expect-kp 8` | |
阶段 0 单颗闸门（URT-2/URT-1）未过 0.2 前不要买齐 15 颗：`sts_bench.py` / FD。
---

## C. 策略导入（本仓权重）

| # | 项 | 期望 | □ |
|---|---|---|---|
| C1 | 导出 | 本仓 HD1910 ONNX，**烘焙 normalizer**；parity 过。⚠️ **`publish` 不打包外部权重**：只拷 `.onnx`，而它自己用 `load_external_data=False` 读 ⇒ 一个 split 导出会**以 3 KB 的无权重图上传成功**。拷到机器人上之前必须确认 `graph.initializer` 没有 `EXTERNAL`（`verify_policy_bundle.py` 的 A8），或用 `--stamp` 内联成单文件 | |
| C2 | 契约 | obs **61** / act **14** / **50 Hz** — 勿改布局。跑 `verify_policy_contract.py`；**再跑 `verify_policy_bundle.py`**（多一道归一化器下限 + metadata 对质） | |
| C3 | 植物指纹 | runmeta / 笔记写明：`hd1910_openmicroduck_m5`（或日后 ftservo m6）+ m5 sha | |
| C4 | 热加载 | 中控「模型管理」导入自训 walk；**不要**上 XL330 `walk_std004_*` | |
| C5 | 部署缩放 | 训练侧 1/1/1；运行端常见 **基础 0.9 / 头 0.5 / 腿 0.7**（官方 Dynamixel 运行默认，**不是训练超参**）；再乘电压补偿 `7.4/V`（以当时中控说明为准） | |
| C6 | 短站立 | 先站稳再给速度指令；再谈走路 | |
| C7 | 本仓彩排 | `rehearse_hd1910.py`（仿真，m5/kp32）作对照，**不能单独宣称真机已会走** | |
| C8 | **归一化器下限（2026-11-04 查出，会让机器人猛打限位）** | 导出的 `Div` 分母（= 训练 std）必须逐维 > `1e-3`。`deploy61.onnx` 有 **10 个维 = `1.113e-05`**（`head[0..3]`、`body.x/y/z/roll/pitch/yaw`），放大 **89866×**；其中 **7 个是 `obs.rs:196-211` 会真写非零值的槽** ⇒ 转 5.7° 头，动作从 −0.29 跳到 **−35.7 rad**。实测 `p8head_2999` / `resume_5999` 下限 `0.01289`（**差 1157 倍**）⇒ **`deploy61` 下线，换这两个之一**。⚠️ **不能靠改 onnx 修**：把 std 抬到 `1.2e-2` 等于换了一个策略（权重是在 `1.1e-5` 下学的），必须重新导出让 `VecNorm` 带 eps 地板。`publish` 自带的 `smoke_run_onnx` 抓不到它：它只断言 `std(outputs) != 0`，而 `deploy61` 在那里的 std 是 **104**（健康 0.29–0.83）—— **抖动越大越容易通过** | |

---

## D. sim2real 结论必带字段

写进日记忆 / 评测 JSON：

1. 植物指纹（m5 或 ftservo m6）+ 参数 sha  
2. 镜像版本 + 中控 V + 固件 control  
3. 实测 P / D / 转矩  
4. 方向表摘要（或「与 fanhao −1 默认一致」）  
5. 部署缩放（若改过）  
6. 短走：是否不摔、体坐标大致前向（勿只报世界系 dx）

---

## E. 明确不做

- 自写飞特 daemon  
- 陆吾 `1910_m6`（STS3215 错标）当上机模型  
- 以仿真 ratio 单独宣称真机会走  
