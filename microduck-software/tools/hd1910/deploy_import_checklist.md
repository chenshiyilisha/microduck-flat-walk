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
| B1 | 舵机家族 | `[bus] servo = "feetech_hls"`。**`ServoKind` 的 `#[default]` 就是它**，所以不写也对；写成 `dynamixel_xl330` 会让 15 维 `joint_vel` 小 3.15×。⚠️ **没有 `protocol` 这个键** —— `Bus` 带 `#[serde(deny_unknown_fields)]`，抄 kissqy 那份的 `protocol = "feetech"` 会让 robotd **整个配置文件加载失败**（不是静默忽略） | |
| B2 | `robotctl health` | bus 绿；loop **50 Hz 0 missed** | |
| B3 | 方向表 | HD1910 读数方向常与 XL330 **相反** → 多数关节 **−1**（以本机标定为准，逐颗核对） | |
| B4 | 零位 / 限位 / IMU | 关节工作台过一遍；IMU 俯仰偏差必须运行时校掉。⚠️ **别指望舵机自己的行程当限位**：EEPROM `reg9/reg11 = 0/4095` 在物理上不起作用，实测推超程时堵在 1213/2816（相隔 1603 counts ≈ 141°），而 reg19 的过载位 32 是刻意关的 ⇒ 撞住不卸力，只有过流 3.25 A 兜底 | |
| B5 | 固件 P（RAM 50 / EEPROM 21） | **= 8**（= 训练 `kp_fw`，§22）；`set_gains_all.py --persist` 写，**断电后回读**才算数（§22.7）。**写前先确认 15 颗全应答**：脚本会预检，缺一颗就退 2 且一个字节都不写（半套配置比原样不动更糟，§22.7 末） | |
| B6 | D / 转矩 | **D = 0**（`set_gain` 自己钉 0；出厂 D=40 会阻尼内部 PID，同 kP 下明显更软）；转矩上限 1000 | |
| B7 | **`[policy] gain`** | `/etc/robot/robotd.toml` 里 `gain = 8`。**默认 200，控制环每 tick 写 RAM，会把 EEPROM 的 8 覆盖掉**（§22.8，一手源码） | |
| B8 | 跑起来后回读 reg 50 | **= 8**。读到 200 ⇒ B7 没生效；读到 50 ⇒ 刚跌倒过，`gain_limp` 还在 RAM | |
| B9 | **增益标度家族** | 改了 `gain` 之后，另外三个按 200 标定的相对量必须同步改：`[safety] gain_limp = 3`（默认 50，在 kp8 下是 **6.25× 加力**，跌倒卸力反成硬撑）、`[safety] limp_fall_pose_gain = 8`（默认 160 = **20×**，回站姿会砸）、`[policy] action_scale = 1.0`（默认 0.9 是 alpha 策略的，会让每个动作小 10%；但这是**旋钮不是常数**——kissqy 自训版用 **0.7** 也走起来了，匹配训练时才是 1.0，§8.5.6）。用 `audit_robotd_toml.py` 一条命令查（§22.10） | |
| B10 | **两个「中立」默认值其实不中立** | ① `[policy] head_lowpass / legs_lowpass` 默认 **0.5 / 0.7**——robotd 注释说这是 alpha 策略的训练值，但**本训练管线里零低通**（`grep low_pass` 在 microduck_rl + mjlab 1.3.0 + bam 全无命中，动作是 `target = current + action*scale`）⇒ 必须写 **1.0**，否则等于给策略从未见过的目标加了个 τ≈17 ms 的一阶滤波（2 Hz 处 −2%、4 Hz 处 −7%、相移 6–11°）。② `[bus] fast_sync_read` 默认 **true** 是 **Dynamixel P2.0 的 0x8A**；HD-1910 是 Feetech（0x82）。robotd 自己的警告是「不实现 0x8A 的设备不应答，**每一次读都超时**」，症状(symptom)看起来完全像接线或波特率错 ⇒ 先写 **false**（**2026-11-04 台架已实测**：ID 10 对 0x8A 返回 0 字节，而 PING / 0x82 单读 / 0x82 同步读三个对照全通，假 id 负对照沉默 ⇒ 不是"没上电"而是"不实现"）。**优先级**：① 是硬故障（每次读超时），②③ 是"能对上最好"——kissqy 自训版 `robotd-selftrained.toml` 就把 lowpass/cmd_alpha 全留了默认并走起来了（§8.5.6） | |
| B11 | **保护开关 reg19 = 13**（EEPROM，逐颗写） | 出厂只有 **4（仅过热）**，过压/过流/过载/磁编全关。写 **13 = 电压+过热+过流**，`set_protection.py --ids 1,...,15 --apply`。**时序不能改**：必须在**断电重上电后、robotd 起来之前**跑（那时 reg40 默认 0 = 扭矩关，是官方要求的写入前置条件），解锁 0.25 s → 写 0.50 s → 上锁 0.50 s；**绝不切 mode**（会从 EEPROM 重载、把刚写的值冲掉）。写完**必须再断电一次**跑 `--verify`：回读 PASS 只证明 RAM 影子改了，前 3 次就是这么假成功的（§8.5 台账）。⚠️ **过载位 32 绝不能开**，且别拿「恢复出厂」当安全动作（出厂 52 含 32） | |
| B12 | **`[bus] joint_ids`（15 条，Feetech 必需）** | 空或重复 ⇒ **总线拒绝打开**，优先报 `"the key to set"` 而不是猜哪颗是哪个关节（`robotd/src/main.rs:5495` 有对应测试）。顺序**固定按 `JOINT_NAMES`**：0-4 左腿(hip_yaw/hip_roll/hip_pitch/knee/ankle)、5-9 颈/头(neck_pitch/head_pitch/head_yaw/head_roll/mouth)、10-14 右腿(同左)。建议 ID 沿用上游 `JOINT_IDS`（右腿 **10-14**、左腿 **20-24**、头 **30-34**），IMU 板 **200 不在这个表里**。台架那颗已是 **ID 10 = right_hip_yaw**，与上游一致 | |
| B13 | **robotd 打开总线时的三项 EEPROM 硬校验** | `feetech.rs:386` 逐颗比对，**不满足就 `IoError::Bus` 拒绝启动**，注释明写「EEPROM is checked, not corrected」——它不会替你改。对照台架现状：① `baud` 要 **1（500 kbps）**，我们是 **0（1 Mbps）** ✗（A733 的 UART7 由 24 MHz 晶振分频，取不到 1 Mbit/s，静默变 750k；16 颗读 ~7.5 ms/20 ms）；② `mode` 要 **0**，我们是 **4**（出厂默认）✗；③ `limits` 要 **0/4095** ✓。⚠️ mode 0 与 4 的行为差异还没在台架比对过（见 B14） | |
| B14 | **mode 0 vs mode 4 已在台架复核：差一倍**（2026-11-04） | 10–90% 阶跃上升时间 mode4 182/207/230 ms vs mode0 363/413/436 ms（4.4°/8.8°/17.6° 三档），**比值恒 1.9–2.0**；超调≈0、稳态误差 1 步。限速(reg46 250→1000)、加速度规划(reg41 0/100/254)、goal time(reg44 500→50) 全部排除。⇒ **部署在 mode 0 上的 plant 比 kp8 平台慢一倍，属 plant 口径不一致**。三条路：①**改 fork 允许 mode 4**（代价最小，但要先确认 mode 4 下 reg40 关不掉扭矩 robotd 能否接受）②在 mode 0 上重训 ③先测正弦带宽。**③ 已于 2026-11-04 跑完，缺口补上且结论不变**：0.5–4 Hz 五档 mode 0 在每个频点都比 mode 4 差 12–45%、多滞后 6–21°；2 Hz（=步频）gain **0.35 vs 0.60**、lag **+90° vs +74°** ⇒ 「阶跃太苛刻」解释不掉。⚠️ 顺带查实 `reg46` 的 0 是**停转**（不是无限速），250 与 1000 结果逐位相同 ⇒ 慢不是限速造成的。**2026-11-04 二次复核：把"模式差异"改判为"增益差异"。** 钉住 2 Hz / 13.2° 扫 P（`probe_pgain_speed.py`）：mode 0 的 P=8/12/16/24 给 gain **0.350 / 0.489 / 0.604 / 0.744**，而 **mode 0 在 P=16 与 mode 4 在 P=8 完全等价**（0.604 / +73.9° vs 0.604 / +73.8°，等效拐点 fc 1.21 vs 1.23 Hz）。⇒ 同一 P 下 mode 4 的环路增益约为 mode 0 的两倍；**"部署比 plant 慢一倍"的根因是 kp=8 而不是 mode 本身**（仿真 @4.6 V / kp8 的 fc = 1.24 Hz，与两者都吻合）。⇒ 新增第 ④ 条路：**不动 mode、只把 reg50 从 8 提到 16**，不改 fork 也不重训（落地点就一个数：`[policy] gain = 8` → `16`；`bus.rs:304 set_gain` 每个启动/切增益都会写 P，并**强制 I=0、D=0**，所以台架 P 扫描里 D=0 与实际部署一致）。⚠️ ④ 与 ① 的未决项相同，都是电流/发热，而这颗的**负载/电流回读是坏的**（`reg60` 恒 0、`reg62` 按 u16 读会把温度拼进来得 7469、`reg69` 正弦中读到 16000 量级）⇒ 台架判不了。**验收改看温度**：robotd 的 `SlowSensors` 只报电压与**每关节温度**（`io.rs:81`，读 reg144–146），没有电流；所以提 P 的代价只能靠在真机上跑一段看 per-joint temp 有没有逼近 reg70 latch。 | |
| B15 | **reg44 语义与 HLS 不同，但实测无害** | `feetech.rs:57` 自己注明 GOAL_CURRENT=44 是 **HLS 专有**（HLS 上＝电流上限 6.5 mA/count；**STS 映射上是 goal time**），而 HD1910 是 STS。robotd 默认写 `2925 mA / 6.5 = 450`，HD1910 会当成 goal time＝450。**台架实测（2026-11-04）无害**：出厂 reg44＝500，改成 50 后 mode 0 的 rise 仍是 441 ms（vs 436），且实际动作 436 ms 远短于 goal time，说明它只是**最长时限**、不构成限速。⇒ 不用改这一项；但若哪天症状是「动作像被拖慢」，先看 reg44 | |
| B16 | **电压/温度遥测走的是 feetech 路径（reg62/63），不是 `bus.rs` 的 144–146** | 容易误判：`bus.rs:41 SLOW_READ_ADDR = 144` 是 **XL330 的 Dynamixel 实现**；我们 `[bus] servo = "feetech_hls"` 走的是 `feetech.rs`，其中 `PRESENT_VOLTAGE = 62`、`slow_sensors` 读 (62, len 2) = 电压 u8×0.1 + 温度 u8（`feetech.rs:63/677`）。台架实测：**reg144/145/146 在这颗上完全无应答（None）**，而 reg62 = 46（4.6 V）、reg63 = 29 °C 正常。⇒ 电学保护（电池 6.6 V 关断）与每关节温度**都可用**，不必改；但读代码时别照着 `bus.rs` 去改地址。 | |

阶段 0 单颗闸门（URT-2/URT-1）未过 0.2 前不要买齐 15 颗：`sts_bench.py` / FD。

---

## C. 策略导入（本仓权重）

| # | 项 | 期望 | □ |
|---|---|---|---|
| C1 | 导出 | 本仓 HD1910 ONNX，**烘焙 normalizer**；parity 过 | |
| C2 | 契约 | obs **61** / act **14** / **50 Hz** — 勿改布局 | |
| C3 | 植物指纹 | runmeta / 笔记写明：`hd1910_openmicroduck_m5`（或日后 ftservo m6）+ m5 sha | |
| C4 | 热加载 | 中控「模型管理」导入自训 walk；**不要**上 XL330 `walk_std004_*` | |
| C5 | 部署缩放 | 训练侧 1/1/1；运行端常见 **基础 0.9 / 头 0.5 / 腿 0.7**（官方 Dynamixel 运行默认，**不是训练超参**）；再乘电压补偿 `7.4/V`（以当时中控说明为准） | |
| C6 | 短站立 | 先站稳再给速度指令；再谈走路 | |
| C7 | 本仓彩排 | `rehearse_hd1910.py`（仿真，m5/kp32）作对照，**不能单独宣称真机已会走** | |

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
