# HD-1910 · 增益语义对齐：HLS（本线） vs SCS（EasyDuck）

_日期：2026-11-09。澄清「SCS 写 EEPROM 21/22，HLS 写 RAM 50/51，单位可能不一致」这个旧担忧。_

## 0. 结论先行（源码查证后）

- **两条 robotd 线写的是同一颗伺服的同一组 live PID 寄存器（reg50 = Kp，reg51 = Kd）**——`jlckfb/easyduck` 的 `scs.rs:20` `const GAIN: u8 = 50`，把 `[Kp, Kd]` 两字节写进 50/51；本线 `feetech.rs:51` `const KP: u8 = 50` / `:52 KD = 51`，同样写 50/51。
- 因此增益数值在**同一寄存器空间、同一颗 HL-2915/STS-1910** 上，**可直接比较、无需单位换算**。
- 差异只在**数字**：
  - 本线 HLS 默认 `position_kp = [8]`、`position_kd = 8`（`feetech.rs:154-156` 默认值）→ reg50=8、reg51=8（经 `kp_for_gain`，`feetech.rs:236`）。
  - EasyDuck SCS `reference_gain = 6`（`scs_joint_gains.json`）+ `set_position_id_gains(0, 20)`（`scs.rs:530` 测试桩）→ Kp=6、Kd=20。
- **旧担忧「单位不一致」基本消解**：两边最终都落到一个伺服的 50/51；EEPROM 21/22 只是上电时固件拷到 RAM 50/51 的源，不是两套语义。

## 1. 寄存器映射证据（三处源码逐项对）

| 寄存器 | 标准 STS（`rustypot` sts3215.rs） | 本线 HLS（`feetech.rs`） | EasyDuck SCS（`scs.rs`） | 备注 |
|---|---|---|---|---|
| 21 | `p_coefficient` (P) | （上电拷到 50） | （上电拷到 50） | EEPROM 持久 P |
| 22 | `d_coefficient` (D) | （上电拷到 50/51） | （上电拷到 50/51） | EEPROM 持久 D |
| 23 | `i_coefficient` (I) | — | — | 本线不用 I |
| **50** | （RAM live P） | **`KP`** | **`GAIN`（写 [Kp,Kd]）** | **两边同地址写 live P/D** |
| 51 | （RAM live D） | **`KD`** | （GAIN 第二字节） | 同上 |
| 33 | `mode` | `MODE`（必须=0） | `MODE` | 模式 |
| 40 | `torque_enable` | `TORQUE_ENABLE` | `TORQUE=40` | 扭矩 |
| 42 | `goal_position` | `GOAL_POSITION` | `GOAL=42` | 目标位置 |
| **44** | `goal_time` | **`GOAL_CURRENT`（6.5 mA/count，必须写）** | （默认 goal_time，未重写） | ⚠️ **协议分支 reinterpret** |
| 46 | `goal_speed` | `GOAL_SPEED`（250；0=停） | `GOAL_SPEED`（单位 50 counts/s） | 单位两边一致：50 counts/s |
| 56–70 | 读块 | `READ_ADDR=56, READ_LEN=15` | `POS=56, BLOCK_LEN=15` | **读块完全一致** |
| 62 | `present_voltage` | `0.1 V/count` | `0.1 V/count` | 一致 |
| 69/70 | `present_current` | `6.5 mA/count` | `6.5 mA/count`（`scs.rs:164`） | **一致** |
| 波特率 | — | **500 kbps**（`BAUD_RATE=500_000`） | **1 Mbps**（`BAUD=1_000_000`） | ⚠️ 仅速率不同 |

**对齐结论**：位置/速度/电流/扭矩/目标/读块 的地址与单位**两边逐字相同**；唯一协议分支级差异是 **reg44**（HLS 当 goal_current 必须写、SCS 当 goal_time 用默认）和**波特率**（500k vs 1M）。这反而证明：**同一颗伺服的不同协议分支可以 reinterpret 寄存器**——所以 PID 寄存器 50/51 的语义是否也随分支/模式变，必须上板负对照确认（见 §3）。

## 2. 我们的 HLS 增益公式（权威，来自 `feetech.rs`）

```
KP_REFERENCE = 200.0                              (feetech.rs:115)
reg50 = clamp(round(gain × position_kp / 200), 1, 254)   (kp_for_gain, :236)
```
- 默认 `gain=200` + `position_kp=8` → reg50 = round(200×8/200) = **8**（即「kp8」）。
- 部署档 `position_kp=16`（`out/robotd_hd1910_mode0.toml:65`）→ reg50 = **16**（mode0 下与训练 plant@mode4/P8 等价，台架复核 0.5–4 Hz 两点 gain/lag 差 ≤0.4°，见导入清单 B14）。
- `position_kd`（默认 8，写 reg51）= **D，不是 0**（`feetech.rs:399`，导入清单 B6）。
- ⚠️ `[policy] gain` 是 **XL330 口径参考值**，**不是寄存器 P**：写 `gain=8` → reg50=clamp(round(0.32),1,254)=1 → 每颗 P=1 → 机器人瘫软（导入清单 B7，toml 头部注释已钉死）。

## 3. 残留守查项（负对照才能消）

1. **PID 寄存器 50/51 的语义是否随协议分支/模式（reg33）变**：reg44 已被证明会随分支 reinterpret，故 50/51 不能想当然等同。→ 上板负对照：把 reg50/51 写成 SCS 的 `Kp=6/Kd=20`，观察刚度/是否振荡，与保持本线 `Kp=16/Kd=8` 对比。
2. **mode 0 vs mode 4 的环路增益差异**：台架已证同一 P 下 mode4 环路增益≈mode0 两倍，但根因是 kp 而非 mode 本身（导入清单 B14）。SCS 若跑在 mode 4 而本线锁 mode 0，则直接套 Kp=6 不等于 SCS 的等效刚度——需按本线公式换算（position_kp 调，不动 `[policy] gain`）。

## 4. 推荐动作

- **保持本线默认 / 部署档**（`position_kp=16`、`position_kd=8`），这是策略训练时的刚度，**不要盲抄 SCS 的 KP6/KD20**。
- 若想试验 SCS 的更软 P / 更强 D：通过 `[bus] position_kp` / `position_kd` 改（不是 `[policy] gain`），先在台架单舵机 + limp 安全网下试，确认不振荡再上机。
- Kd 是阻尼项、不参与位置跟踪动力学，提到 20 可能改善稳定裕度但**未测过电流/发热代价**（本线 reg60/62/69 电流回读是坏的，验收只能看 per-joint 温度），见导入清单 B14 末段。
