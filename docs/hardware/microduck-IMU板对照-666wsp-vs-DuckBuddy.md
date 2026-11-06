# IMU 板对照：666wsp IMU_TO_DXL v1.2 vs DuckBuddy 上游驱动

_2026-11-05。目的：判断 666wsp 这块 IMU 板（CH32V203 + LSM6DSV16X，ID 200）能不能直接接到
DuckBuddy 上游的 robotd/duck-control 驱动上。结论先行：**字节级兼容，固件级有 2 个冲突 + 1 个附带损失，下单前需台架验证。**_

## 0. 来源

| 侧 | 来源 | 本地路径 |
|----|------|----------|
| IMU 板 | `666wsp/microduck-hd1910`（IMU_TO_DXL v1.2 资料库） | `microduck-software/.upstream/666wsp-microduck-hd1910/` |
| 驱动 | DuckBuddy 上游 `duck-control`（XL330 总线 + Feetech 总线两条路径） | `microduck-software/.upstream/DuckBuddy-main/` |

关键文件：666wsp 侧 `README.md`、`imu_dev_guide.md`；DuckBuddy 侧 `duck-control/src/imu.rs`、
`duck-control/src/bus.rs`（XL330 路径）、`duck-control/src/feetech.rs`（HD-1910 用的这条）、
`docs/hardware/INTERFACE-CN.md`。

## 1. 字节级完全对齐（好消息）

| 项目 | 666wsp IMU 板 | DuckBuddy 驱动 | 结论 |
|------|--------------|----------------|------|
| 传感器 | LSM6DSV16X + SFLP 硬件融合 | LSM6DSV16X + SFLP | ✅ 同一颗 |
| 从站 ID | 200（0xC8，可改） | `IMU_DXL_ID = 200`（model.rs:164） | ✅ |
| FT 协议起始地址 | 56（0x38） | Feetech 路径 `PRESENT_POSITION = 56`（feetech.rs:62） | ✅ |
| 数据块前 12 字节 | gyro x/y/z（int16）+ quat x/y/z（half） | `IMU_BLOCK_LEN = 12`，消费同样 12 字节（imu.rs:22） | ✅ 逐字节吻合 |
| 四元数 W | 只发 x/y/z，主机补 W | `w = √(1 − x² − y² − z²)`（imu.rs:136） | ✅ 同算法 |
| 陀螺仪刻度 | ±500 dps，17.5 mdps/LSB | `GYRO_RAD_PER_LSB = 0.0175`（imu.rs:48） | ✅ |
| 输出频率 | 120 Hz，最坏姿态延迟 8.3 ms | 120 Hz | ✅ |
| 物理层 | 单线半双工 UART，TTL 3.3V | 同 | ✅ |

DuckBuddy Feetech 路径每次 tick 从地址 56 读 **15 字节**、但只消费前 12 字节
（feetech.rs:69 `READ_LEN = 15`，imu.rs 只解码前 12）。这 15 字节布局恰好就是 666wsp 的
FT 紧凑块，前 12 字节 = gyro + quat x/y/z，完全对上。

## 2. 两个真实冲突（下单/上板前必须解决）

### 冲突 1：波特率 1 Mbps vs 500 kbps

- **666wsp**：出厂要求**精确 1 Mbps**，误差 < ±2%（用 12 MHz 晶振或 PLL，禁用内部 RC）。
  Python 示例 `BAUD = 1000000`（README.md:175、imu_dev_guide.md:180）。
- **DuckBuddy**：Feetech 总线 `BAUD_RATE = 500_000`（feetech.rs:35）。原因见
  INTERFACE-CN.md：**A733 的 UART7 设 1 Mbps 实际只有约 750 kbps**，所以整机统一用 500k。
- **处置**：用 666wsp 自带的 **FD.exe**（`01_Tool/FD1985-250729/FD.exe`）把这块板子的
  波特率改成 500k，否则它在 DuckBuddy 总线上不应答。666wsp 提供了工具和 `ft_setup_bat/`
  恢复脚本。**能改，不是死结。**

### 冲突 2：同步读顺序「IMU 排第一位」 vs 「IMU 排最后」 ⚠️ 风险最大的一条

- **666wsp**：手册明文（imu_dev_guide.md:148-152）：
  1. **ID 200 必须排在同步读 ID 列表的第一位**（协议按 ID 顺序分配时隙，它排第一=主机发完立刻回）；
  2. 不要让其他设备插在 200 前面。
- **DuckBuddy Feetech 路径**：`ids.extend_from_slice(&config.ids)` 先放 15 个舵机，
  `ids.push(IMU_DXL_ID)` 把 IMU 放**最后**（feetech.rs:314-316）。注释给出实测依据：
  「IMU 在前只有 990/1000 次读干净，排最后 1000/1000」。
- **关键区别**：DuckBuddy 那句「IMU 固件会数前面的应答再开口」描述的是 **DuckBuddy 自己的
  STM32G031 固件**（`firmware/imu-feetech`，INTERFACE-CN.md:89）。而 666wsp 这块是
  **CH32V203 + 另一套固件**（`IMU_TO_DXL_FT_APP`），手册却坚持必须第一位。
- **后果**：若 666wsp 固件严格要求第一位，而 DuckBuddy 驱动固定把 IMU 放最后，两者对不上。
  要么改 DuckBuddy 把 IMU 放前（赌时序成立），要么实测确认 666wsp 固件能容忍「排最后」。
- **判定**：**只能台架验证，不能纸面断定。** 注意 XL330 路径（bus.rs:114-115）是把
  IMU 放第一位的——两条路径顺序相反，选哪条路径决定了顺序要求。

## 3. 附带损失：status / sequence 字段被忽略

666wsp 的 15 字节里：

| 偏移 | 字段 | 666wsp 定义 | DuckBuddy 是否消费 |
|------|------|-------------|-------------------|
| 12 | sequence | uint8，只在有新四元数时 +1（120Hz 下每秒 +120），比时间戳可靠 | ❌ 不读（只消费前 12 字节） |
| 13 | status | bit0 NOT_READY / bit2 STALE(>30ms) / bit4 SELF_TEST / bit8 READER_SLOW(≥5 样本) | ❌ 不读 |
| 14 | reserved | 固定 0 | ❌ 不读 |

DuckBuddy 用自己的 `SflpDecoder::ready()`（25 个有效四元数样本 ≈ 0.25s）和
`StaleImuTracker` 兜底，功能上不会立刻坏，但**丢掉了这块板子自带的 STALE/READER_SLOW
告警**。若后续要在 DuckBuddy 上吃满这块板的诊断能力，需要改驱动多消费 byte12/13。

## 4. 台架验证清单（下单前跑）

1. **波特率**：FD.exe 把板子改成 500k → 在 500k 总线上能正常应答（发 README 里的同步读，
   收到 21 字节 `FF FF C8 11 00 ...`）。
2. **顺序 A**：按 666wsp 要求，ID 200 排**第一位**，15 舵机随后 → 读是否干净。
3. **顺序 B**：按 DuckBuddy 现状，15 舵机在前、ID 200 排**最后** → 读是否干净。
   - A 干净、B 不干净 → 必须改 DuckBuddy 代码把 IMU 放前（且确认台架时序成立）。
   - A、B 都干净 → 无冲突，固件能容忍两种顺序。
   - B 干净、A 反而不干净 → 与 666wsp 手册相反，以实测为准并回写文档。
4. **status 观察**：连续读几秒，看 byte13 是否出现 0x08（READER_SLOW）——若在 50Hz 控制环下
   出现，说明读太慢或总线负载过高，进 STALE/READER_SLOW 告警链。

## 5. 一句话结论

**字节级兼容（前 12 字节完全一致），固件级两个对不上：波特率（1M vs 500k，FD.exe 可改）和
同步读顺序（666wsp 要求第一位 vs DuckBuddy Feetech 放最后，需台架实测）。手头有单颗舵机台架时
可直接跑第 4 节清单；这块 IMU 板建议在批量下单前先拿 1 片验证。**

## 6. 未决事项

- kissqy 淘宝「HAT+IMU 成品」（item 1095121548583）里的 IMU **是不是就是这块 666wsp 板**——淘宝页需登录，仍未能独立核实。⚠️ 但 kissqy 官方采购清单已给出拆价 **HAT ¥119 + IMU ¥99（已烧 FT6）+ HUB ¥69**，并明写「香蕉板（暂未上架）」；我方文档里「一套 ¥150」是**过时价格**，应更正。
- ✅ **666wsp 板 BAT+ 电压范围已定（2026-11-06）**：原理图 `00_SCH/SCH_imu_todxl_v1.2_2026-10-24.pdf` 提取出 U2 = `HT7533-1`，Holtek 官方 datasheet `VIN max 30 V` / `4.3–30 V` 工作区间 ⇒ **2S 6.6–8.4 V 完全在范围内**（3S 亦在 LDO 范围内，但 10 µF 电容耐压未标，需实物确认）。
