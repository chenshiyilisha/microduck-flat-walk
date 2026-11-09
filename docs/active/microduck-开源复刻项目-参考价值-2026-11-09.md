# Microduck / HD-1910 开源复刻 · 参考价值调查（2026-11-09）

> 目的：在项目已 vendored / 研究过的 `AI-FanGe/Microduck-build-tutorial`、`jlckfb/easyduck`、`pollen-robotics/rustypot` 之外，扩查 `fanhao375/microduck-replica`、`LuwuDynamics/xgoduck_*`、`chenkui164/microduck-replica` 及周边仓库，**提取对我们有借鉴价值的内容**。
> 方法：GitHub codeload tarball 拉源码 + API tree，读 README / 协议手册 / 固件 / 标定 / 控制代码。
> 结论前置：**所有飞特系复刻与我们的 `feetech_hls` 同协议家族（Feetech STS3215 级 SCS），寄存器/编码器三者同根，差异只在波特率、ID 方案、增益语义缩放——均属"改配置+验证"级，非协议冲突。**

---

## 0. 协议分支总判定（最关键）

| 维度 | 我们 `feetech_hls` | 社区复刻（xgoduck / chenkui / fanhao） | 结论 |
|---|---|---|---|
| 协议 | Feetech 串行总线（STS3215 级，HD-1910） | 飞特 **SCS 协议**：`0xFF 0xFF` 帧头、指令 `0x01/0x02/0x03/0x82/0x83`、校验和取反（chenkui `docs/飞特资料/SCS通信协议-v1.0-2026-06-09.md`；xgoduck `sketch/scs_bus.h`；chenkui `hardware/imu_to_dxl/firmware/Core/Src/protocol.c` 注释"Feetech SCS communication protocol"） | **同分支** |
| 寄存器映射 | STS3215 级 | `0x05`ID / `0x2A`目标位 / `0x38`当前位 / `0x3E`电压 / `0x15/0x16` EEPROM KP/KD / `0x37`解锁 / 4096 编码器（xgoduck `sketch/duck_config.h`；fanhao `servo_tool.py` 寄存器表） | **完全对齐** |
| 波特率 | **500k** | **1 Mbps**（HD-1910 出厂默认，范围 38.4k–1M，见 chenkui 数据清单 §4） | **需改造**（支持范围内，改波特即可） |
| 舵机 ID | **1–15** | 社区约定：左腿 20–24 / 右腿 10–14 / 颈头 30–33 / 嘴 34（xgoduck `duck_config.h`；chenkui 数据清单关节表） | **需重映射** |
| 增益语义 | HLS（P/D 缩放可能不同） | SCS/STS，写 `0x15/0x16` EEPROM + `50/51` RAM，mode 4 位置 PD | **需对齐**（见 `microduck-HD1910-增益语义对齐-HLSvsSCS-2026-11-09.md`，已闭环） |

→ 一句话：**协议/寄存器/编码器同根，直接可对标；差异只在波特率、ID 方案、增益语义缩放**，属"改配置+验证"级，不是协议冲突。

---

## 1. `fanhao375/microduck-replica`（HD-1910 实机验证派，最贴近我们硬件）

- **定位**：2026-10-24 完成飞特 HD-1910 替代 XL330 的实机验证（站立/行走/前滚翻起身）。仓库极全（1551 文件）：装配图、BOM、21 页说明书、烧录镜像、**IMU 桥固件 + Python 工具 + 单元测试**、大量调试日志（`docs/HD1910-*`）。含真实代码（631 文件），非纯文档仓。
- **SBC/协议**：沿用官方架构（Radxa/树莓派类）；舵机走飞特 SCS 总线；IMU 两条路（板载 I²C BNO085/LSM6DSV16X **和** 总线 IMU 从机 ID200）。同分支。

### 值得借鉴
- **C5 标定工具（A2 直接可用）** — `hardware/imu_to_dxl/firmware-1.0.0/Tools/servo_tool.py`：纯 Python/pyserial 飞特舵机工具（scan/read/test/write + 寄存器表 `REG_GOAL_POS=42`、`REG_POS=56`、`REG_VOLT=62`、`REG_ID=5`），明确"与 IMU 板（ID200）共用单线总线，扫舵机时板子静默"。可作为我们 500k/ID1-15 标定套件起点，只需改默认波特与 ID 范围。
- **C2 IMU 融合教训（高价值避坑）** — `docs/HD1910-20261015-IMU乱跳根因与陀螺融合上机.md`：**根因是 BNO085 内置融合姿态在落脚时 20ms 内跳 20–60°，陀螺本身正常**；解决是 robotd 里**改用陀螺自积分 + 加速度缓慢校正**（`[trunk_imu] bno08x_fusion="gyro"`），直立时间 62s→634s。**与 xgoduck 的 `ImuFilter` 殊途同归——别信传感器内置融合，自己做互补滤波**。直接指导我们的 IMU 朝向处理。
- **C1 总线 IMU 自动识别** — `docs/HD1910-20261023-总线IMU自动识别.md`：运行时同时支持 飞特 SCS 总线 IMU（ID200，56/15 块）与 ScrapMeta DXL2 总线 IMU（ID200，124/12 SFLP 块，model 10200，陀螺小端 i16 17.5mdps/LSB，四元数 binary16），`imu_protocol="auto"/"feetech"/"dxl2"`。"总线 IMU 从机 ID200"是社区活跃方案。
- **C6 半双工总线调试** — `Tools/bus_monitor.py`、`imu_probe.py`、`protocol_test.py`、`Tests/*_test.c`。

### 借不了
- 调试日志是**他们那台机器**的叙事（BNO085 胶粘、NP-F550 8.4V 顶格掉电重启等），只能当避坑清单读，不能直接套。
- 默认站立角、PID 默认值（P=5,D=0）是他们调的，不是我们的。
- 运行时在它的 fork `fanhao375/Microduck-kissqy` 里（见 §5）。

**总评**：最贴近我们硬件的"踩坑+工具"宝库，`servo_tool.py` 与 IMU 融合教训可立即借用。

---

## 2. `LuwuDynamics/xgoduck_hardware` + `xgoduck_runtime_arduino`（厂商级，资料最完整）

> 注：单仓 `LuwuDynamics/xgoduck` **不存在**；实际拆成两个仓：`xgoduck_hardware`（结构件 STL/TPU、Altium PCB、BOM、装配手册）与 `xgoduck_runtime_arduino`（固件+控制+模型）。**无 LICENSE**（保留所有权利，商用需授权）。

- **定位**：陆吾智能基于 Microduck 改 Arduino Uno Q 双芯片（QRB2210 Linux + STM32U585 Zephyr），15 颗飞特 1910，QMI8658 IMU，8 个预训练 ONNX 模型。资料完整度最高。
- **SBC/协议**：Arduino Uno Q（非树莓派/泰山派）；舵机 **飞特 SCS @ 1Mbps**（`sketch/duck_config.h:SERVO_BAUD=1000000`）；IMU **QMI8658 直连 STM32 I²C（非总线从机）**。同协议家族，波特/ID 不同。

### 值得借鉴
- **C3 恢复状态机（可直接抄）** — `python/recovery.py`：`FALL_DEG=55°` 持续 `0.15s` → `default_pose`(保持1s) → `getup`；`<15°` 持续 `1s` → 回到 `walk`。倾角用 `acos(-gravity[2]/norm)` 算。干净可移植。
- **C2 IMU 朝向/融合（参考模板）** — `python/rl_core.py`：`ImuFilter` 互补滤波（陀螺预测 + 加速度幅值加权校正）；轴重映射 `acc_n=[acc[2],-acc[0],-acc[1]]`、`gyro_n=[gyro[2],-gyro[0],-gyro[1]]`；`IMU_BIAS_DEG` 补偿安装偏角。**IMU 偏置标定** `python/standing_imu.py`：立正采 1.5s、≥90 样本，`offset=[0,0,-9.8]-mean(acc)`、陀螺减均值，仅 additive（无 scale/旋转），存 `.cache/imu-calibration.json`，带阈值校验（acc std<0.30、gyro std<1.125°/s）。算法可直接借鉴，轴重映射需按我们板子安装方向改。
- **C4 策略适配 / 观测布局（强参考）** — `python/rl_core.py` + `policy.py`：观测 **61 维** = `[gyro3, grav3, 关节角14, 关节速度14, prev_action14, twist3(vx,vy,wz), head4, 0×6]`；动作 **14 维**（嘴第15舵单独控）；`POLICY_IDS=[左腿10-14, 颈头30-33, 右腿20-24]`；动作 EMA 滤波（腿 α=0.35、头 α=0.45）。`policy.py` 校验 `in=[1,61], out=[1,14]`、读 ONNX `default_joint_pos` 元数据作模型特定 home。**与我们 `obs61/act14/50Hz` 完全一致，是接口契约级参考**。
- **C5 网页标定 UI（A2 参考）** — `assets/calibrate.js` + `calibrate.html` + `imu-calibration-pose.png`：逐关节"Set center & hold"手动机零位 + IMU 立正标定流程（UX 范式可抄，API 需换我们的）。
- **A3 多策略模型** — `python/xgoduck_*.onnx`：walk/getup/pick/roulade/roller/sitstand/ballkick_L/R 共 8 个。**架构（多 ONNX 技能切换 + 0.2s 预热 + 准备期取消）可借鉴，权重不可移植**（硬件/ID/几何不同，需自己重训）。
- **C6 半双工总线时序** — `sketch/scs_bus.h`：`syncWriteGoalsFromDesPos()`（Sync Write `0x83` 一次写 15 舵目标）、`readAllState()`（Sync Read `0x82` 一次读 15 舵 `0x38` 当前位+速度+负载+电压）。**Sync Read/Write 广播是性能关键，建议照搬**；`protocol.h` 定义 Linux↔STM32 的 2Mbps Bridge ABI（`CommandPacket` 80B / `StatePacket` 240B）。
- **架构范式** — `docs/architecture.md`："MCU 不等待 Linux"：STM32 100Hz 持续发 240B `duck_state` 快照，Linux 50Hz 只取最新帧、迟到跳过。双芯片解耦思路可参考。

### 借不了
- IMU 走 QMI8658 直连 STM32（双芯片架构绑定），与我们"IMU 在 SBC"或"总线 IMU ID200"路线不一致 → 只借融合算法，不借硬件接法。
- 舵机 ID 10–34、1Mbps、所有关节 `MOTOR_SIGN=-1`（硬件反向）——硬件特定，需重映射。
- **无 LICENSE**，固件/板子绑 Arduino Uno Q，商用受限；纯运动平台（无摄像头/ToF）。

**总评**：控制/融合/恢复/标定/多策略的**教科书级参考实现**，算法层（C2/C3/C4/C5）可直接借鉴，硬件绑定重、权重不可移植、无开源许可。

---

## 3. `chenkui164/microduck-replica`（已知 HD-1910 数据清单，但仓里还有硬货）

- **定位**：与 fanhao375 同源（数据清单、CAD、飞特资料一致）。**你之前只拉过 `HD-1910训练前数据清单.md`；本次确认仓内还有大量新增价值**。
- **除数据清单外还有的参考文件**：
  - `docs/飞特资料/SCS通信协议-v1.0-2026-06-09.md` —— 飞特 SCS 协议权威手册（指令码表、帧结构、校验和、读写/Sync 示例）。
  - `docs/飞特资料/磁编码STS内存表手册-v1.1-2026-08-27.md` —— STS 寄存器/EEPROM 映射（确认 `0x2A/0x38/0x05/0x37/0x15-0x16/0x3E` 与 HD-1910 对应）。
  - `hardware/imu_to_dxl/firmware/` —— **IMU 总线从机固件**（见下）。
  - `cad/` STL + `零件对照表.json`、`docs/不打HAT.md` 等接线/硬件逆向文档。

### 值得借鉴
- **C8 协议/寄存器权威文档**：SCS 协议手册 + STS 内存表，是核对我们 `feetech_hls` 寄存器是否一致的一手依据（建议与我们本地 `bam/params/feetech_sts3215_7_4V` 对照）。
- **C1 总线 IMU 从机固件（ID200）** —— `hardware/imu_to_dxl/firmware/Core/Src/`：
  - `protocol.c`：干净自包含的飞特 SCS 总线从机状态机，含半双工 **Sync-Read 轮次排队**（sec.5 队列规则）与 `T_resp` 时序、CRC 容错（一字节错重扫）、`PROTO_RESPONSE_DELAY_US`。**A1（半双工 UART）在 MCU 侧的绝佳参考**。
  - `control_table.c`：控制器每 tick Sync-Read 地址 56–70 的 15 字节块 = `gyro×3(i16) + quat_fp16×3(u16) + sample_count + status + reserved`；注释"**原始轴不经重映射，安装旋转由控制器侧完成**"。即官方 Microduck"IMU 伪装成总线从机报躯干姿态"的接口。
  - `imu.c`：LSM6DSV16X + 片上 SFLP 四元数融合 @120Hz（SPI），健壮状态机（BOOT→CONFIG 19 步→RUN→RETRY）、有界超时、不持久化偏置。
  - `main.c`：`STM32G031F8`、`Feetech ID=200 1000000 8N1`。
  - **可直接作为我们"总线 IMU 从机 ID200"方案的移植起点**（换 MCU/IMU、保留 `protocol.c` + control_table 布局）。

### 借不了
- 固件针对 STM32G031 + LSM6DSV16X 参考板，引脚/缓冲器不通用，主板不自动烧录小板（见 fanhao 同款说明）——需我们自己的 MCU 移植。
- 数据清单几何是 XL330 仿真值，HD-1910 装机后必须重测（清单自己标注"待实测"）。

**总评**：协议手册 + STS 寄存器表 + 总线 IMU 从机固件三位一体，是"总线 IMU ID200 / 半双工时序 / 寄存器对齐"的最硬核一手资料。

---

## 4. 与已有 A1–A4 清单的回填 + 新类别 C1–C8

### A1–A4 回填
| 原清单 | 本次回填证据 | 结论 |
|---|---|---|
| **A1 半双工 UART 内核补丁** | chenkui `protocol.c`（Sync-Read 轮次排队 + T_resp）；xgoduck `scs_bus.h`/`protocol.h` | 协议层半双工处理有现成参考；但**两仓都不直接给 Linux 内核补丁**，需我们保留 easyduck 的 A1 vendored 补丁 |
| **A2 标定套件** | fanhao `servo_tool.py`（扫/读/测/写+重寻址）；xgoduck `calibrate.js`+`standing_imu.py`（网页零位+IMU 偏置） | **强**，两个独立实现可对照；建议以 `servo_tool.py` 为骨架 + xgoduck IMU 偏置标定合流 |
| **A3 多策略模型** | xgoduck 8 个 ONNX + `policy.py` 适配器（61→14） | **架构可借，权重不可借**（硬件/ID/几何不同）；观测布局与关节顺序是"接口契约"级 |
| **A4 接线范式** | xgoduck 单线总线 + IMU 板；fanhao `docs/不打HAT.md`、总线 IMU 与舵机共线 | 单线半双工总线 + ID200 总线 IMU 是社区主流范式，可采纳 |

### 建议新增类别（优先级从高到低）
- **C2 IMU 融合/朝向**（xgoduck `ImuFilter` + fanhao BNO085 教训）——**最高优先**，两独立来源都指向"自做互补滤波、别信内置融合"。我们 `imu_mount_quat` 装后自检已部分覆盖，但融合策略要明确走"陀螺自积分+缓校"。**2026-11-09 已拉 `fanhao375/Microduck-kissqy` 源码把 C2 具体化并发现真实风险**：见 `microduck-kissqy-HD1910-robotd-IMU与调参-参考价值-2026-11-09.md` —— `gyro_fusion.rs`(6°倾斜门/0.66s/0.5s/5°·s⁻¹) 是现成算法；🔴 我们 `hd1910m/.../bno08x.rs:87-95` 对 BNO085 `0x08` **直接采信无跳变门控**，`reference_native` 只是陀螺 EMA，故该路径会原样吃进 20–60° 乱跳。
- **C1 总线 IMU 从机 ID200**（chenkui/fanhao 固件）——⚠️ **2026-11-09 精确化**：必须绑定 robotd 代次。`out/robotd_hd1910_mode0.toml` 绑的 `DuckBuddy-main` 代次 **已经在用这块板**（`imu_to_dxl v2` LSM6DSV16X，`IMU_DXL_ID=200`，`SflpDecoder`）；`hd1910m` 代次另有一条 BNO08x I2C 输入路径。⇒ C1 对部署代次是"已用/维修参考"，不是待立项的选择题。详见上述 kissqy 文档 §2.2。
- **C3 恢复状态机**（xgoduck `recovery.py`）——FALL_DEG=55°/0.15s 阈值与我们的 60°/200ms debounce 接近，可直接抄改。
- **C6 半双工 Sync-Read 时序**（chenkui `protocol.c`）——性能与可靠性关键，建议 robotd 端也走 Sync Read/Write 广播。
- **C5 标定套件骨架**（fanhao `servo_tool.py` + xgoduck `standing_imu.py`）——直接做我们 500k/ID1-15 标定工具。
- **C4 观测布局契约**（xgoduck `rl_core.py`）——obs61/act14 布局与我们一致，可作重训参考契约。
- **C7 几何/质量/惯量**（chenkui 数据清单）——URDF/MJCF 建模直接输入（注意标注"XL330 仿真值，HD-1910 需实称重测"）。
- **C8 协议/寄存器权威手册**（chenkui 飞特资料）——寄存器对齐的一手核对依据。

---

## 5. 顺带发现、值得下一轮看的仓

- **`fanhao375/Microduck-kissqy`**（上游 `kissqy/Microduck-kissqy`）：**真正跑 HD-1910 的 Rust `robotd` 运行时**——含 gyro 融合开关、总线 IMU 自动识别、标定、Studio 中控；上一节所有"上机"日志都来自它。**✅ 2026-11-09 已拉源码研究完成**（`IMU-MODULE.md` / `hardware/IMU-TIMELINE.md` / `trunk_imu.rs` / `gyro_fusion.rs` / `bno08x.rs`），成果独立落盘 `microduck-kissqy-HD1910-robotd-IMU与调参-参考价值-2026-11-09.md`——含三路线架构、C2 完整算法与真机实测、代次/输入路径分层、以及"我们 BNO08x 路径无跳变门控"的真实风险。注意它仍是 SCS 协议/1Mbps/官方 ID 体系，与我们的 `feetech_hls` 配置不同，不能直接接我们的舵机。
- **`ScrapMeta/microduck-diy`**：DXL2 协议的总线 IMU 从机固件（ID200、124/12 SFLP 块），是 C1 的"另一协议变体"参考。
- **`pollen-robotics/microduck_rl`**（已知）：官方 MuJoCo + PPO + Sim2Real 训练全链路、ONNX 导出——我们重训策略的上游。

---

## 6. 结论与我们的行动指针

1. **协议同根**：fanhao/xgoduck/chenkui 都是飞特 SCS（STS3215 级），寄存器与我们 `feetech_hls` 对齐；差异仅 波特率(1M↔500k)、ID(10-34↔1-15)、增益语义缩放——**均"改配置+验证"级，无协议冲突**。
2. **IMU 融合务必自做互补滤波**（两独立来源验证）——⚠️ **按代次分开**：`DuckBuddy-main` 部署代次是 LSM6DSV16X 总线板（板上 SFLP，host 不融合）；`hd1910m` 的 BNO08x I2C 输入路径才需要"陀螺自积分 + 缓校"，且该路径**当前无跳变门控**（见下文第 5 条）。
3. **总线 IMU 从机 ID200 是社区主流** —— 订正：我们**部署代次已在用这块板**（`imu_to_dxl v2`，`IMU_DXL_ID=200`），chenkui/fanhao 固件与 EasyEDA 工程是它的维修/重制一手参考，不是待立项的二选一。此前"当前先走直连 SBC 路线"的说法是把 `hd1910m` 输入路径误当部署线，已按 `out/robotd_hd1910_mode0.toml:69-77,105-111` 与 `DuckBuddy-main/feetech.rs:319` 纠正。
4. **标定/恢复/观测契约**可直接借鉴（C3/C5/C4/C6）；**权重/几何不可移植**（需重训/重测）。
5. ✅ **`fanhao375/Microduck-kissqy` 研究已完成**（2026-11-09 拉源码）：三路线架构 + `gyro_fusion.rs` 完整算法与真机实测 + `HostImuGate` 门控 + 舵机调参机制，落盘 `microduck-kissqy-HD1910-robotd-IMU与调参-参考价值-2026-11-09.md`。🔴 **最该带走的不是"参考"，是一条待上板验证的真实风险**：BNO085 `0x08` 走路跳 20–60°（fanhao 真机 1.9–23% 走路帧），我们 `hd1910m/.../bno08x.rs:87-95` 对 0x08 只归一化直接采信、`reference_native` 仅陀螺 EMA ⇒ 该路径会原样吃进乱跳。上板第一检查项 = 录 100Hz 原始 0x08 报告统计 >5° 单 tick 跳变。
