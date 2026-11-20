# DuckBuddy HD1910 模型 + bringup 工作台只读比对

日期：2026-11-18
来源：`Animan-AI/DuckBuddy`（GitHub API 核 94★ / Apache-2.0 / 11-15 push / 社区项目、非 pollen 官方）
定性：**社区第三方一手源码**，按来源约定记作「Animan-AI/DuckBuddy 平台文档」，禁止写成「官方」。
本轮性质：**只读比对，未改任何现有源码 / 契约 / 采购表 / xlsx，未对板子写操作，未下任何凭据。**

## 0. 为什么做这件事

用户问「这两个仓库有没有值得借鉴的」，裁决后执行最优一步：把与 B 代 HD1910 线直接相关的
DuckBuddy `hardware/rev-a/mjcf-hd1910/` 模型与 `tools/bringup` 工作台，与本地已落地的设定逐项比对，
只取「本地没有 / 本地更弱」的，避免把已知当新发现。

## 1. 同源判定（不是新项目，是本地副本的上游更新）

- 远端 `UPSTREAM-CHANGES.md` 与本地 `.upstream/DuckBuddy-main` **逐字相同**：都从 pollen 官方
  `590b986`（2026-08-27）起步，改 37 文件 / 新增 724 文件。
- 文件树对比：远端 556 blob，本地 477 文件；远端多 82 个，本地仅多 3 个
  （`duck-control/src/sim.rs`、`tests/sim_e2e.rs`、`hardware/print/microduck2.3mf`）。
- 远端多出的 82 个中，大头是 ~50 个 STL + 3 份 3mf 打印工程；真正有价值的是 §2、§3 两块。
- 结论：**这是同一条线的上游新版**，不是需要新引入的第二权威；比对的是「增量」。

## 2. 可借鉴增量 A：HD1910(2S) MuJoCo 模型 + 基线策略

| 项 | 远端一手 | 与本地关系 | 裁决 |
|---|---|---|---|
| 模型 | `mjcf-hd1910/`：总质量 806 g（2S 实测）、每台 HD-1910 含舵盘 22.8 g；复用 `../mjcf/assets/` STL | 本地 `.upstream/DuckBuddy-main` **没有** `mjcf-hd1910/` 目录 | ✅ 可直接取（Apache-2.0） |
| 接口 | `robot_walk.xml` 的 `<actuator>` **14 个 position 关节**：左腿 5（hip_yaw/roll/pitch、knee、ankle）→ 头 4（neck_pitch、head_pitch/yaw/roll）→ 右腿 5 同序 | 与本地部署契约 **obs 61 / act 14 / 50 Hz / 关节序** 逐名同序（SSOT §384、§617） | ✅ 接口兼容，非第二套关节体系 |
| 执行器参数 | `joints_properties.xml`：`chosen_actuator` kp=0.55 / forcerange ±0.96 / damping 0.053 / frictionloss 0.0048 / armature 0.0018；另有 old/new/antoine 三组对照 | 本地 `joints_properties.xml`（XL330 线）参数不同 | ⚠️ 参考量级，**不可直接套**——本地 500k/ID1-15 的 kp 口径另有一手 |
| 基线策略 | `training/policies/hd1910_walk_kp16_6500.onnx`（Kp16 / ckpt 6500），自述为 `-r3` 镜像 HD-1910(2S) 基线 | 本地已有 `p8head_2999.onnx`（obs61/act14，站姿幅值上限 0.193 rad） | ⚠️ 属**另一训练配方**，仅作对照；换策略=重训链，不在本轮范围 |
| IMU 模型 | `sensors.xml`：framequat/gyro/velocimeter/accelerometer on site `imu` + subtreeangmom | 本地 ID200 总线 IMU、SflpDecoder 另有一手 | ✅ 命名兼容，无冲突 |

数值独立核对：15 × 22.8 g = 342 g（舵机），806 − 342 = 464 g（结构 + 电池 + 板）；14 关节由
`re.findall('<position ... joint=...>')` 从 actuator 段提取，与上面逐名列表一致（非按 body 名猜）。

## 3. 可借鉴增量 B：bringup 工作台的整机体检判据

`tools/bringup/README.md`（8375 B）。带网页图文向导：舵机批量配置 / 关节映射 / 零位标定 /
IMU 固件 / 整机测试，四个页签。逐项与本地比对后的**真正增量**（负对照已做：搜索模式先在远端
正对照命中、再在本地跑，避免假「本地没有」）：

| 判据 | 远端一手 | 本地状态（负对照核实） | 裁决 |
|---|---|---|---|
| IMU 型号握手 | 读 ID200，`0x16D6`（十进制 **5846**）、标志=3、融合输出 **90–150 Hz**、\|q\|≈1、静止陀螺噪声 <1 dps、零偏 <5 dps、无接收错误；俯仰/横滚按 `imu_axes` 换到躯干系 | 本地有 BIT15/reg31/reg19/ID200/750k 等一堆更深的记录，但 **`0x16D6` 0 命中、`90–150 Hz` 判据 0 命中** | ✅ 新增，可直接补进整机体检清单 |
| 舵机总线 | `joint_ids` 逐个 PING + N 轮 SYNC_READ（addr 56 起 15 B，IMU 排最后）；**错误率 ≤0.5%**、状态位全 0、无多圈读数 | 本地有 SYNC_READ 336B/16 设备一手，但错误率阈值未见 | ✅ 阈值可直接借 |
| reg31 当零位工具 | **写 EEPROM 31（位置校正、BIT15 符号位）把当前位置记成 2048**；0/4095 跳变点与目标一起平移 ⇒ 舵盘装偏 / 零位靠跳变点时不用拆舵盘。HL-2915 fw3.45 台架实测（断电保存、跨跳变点连续、回中摆动到位），**HD-1910 未测** | 本地把 reg31 当**只读方向位/位置偏移**解释（8 处），**没有「写它设中位」这个用法** | ⚠️ 新用法，但 HD-1910 未测 ⇒ 只登记为**待验证选项**，不可当 PASS 写进 SOP |
| reg46 必须重写 | **写目标时 42..47 一起写（目标位置 + 44 + 46）；HD-1910 不重写 46 会零电流卡住** | 本地 `重写 46` / `42..47` **0 命中** | ✅ 新增硬约束，进注意事项 |
| 关节 ID 无冲突改号 | 按选定顺序批量改 ID 时**先全挪到临时号 160 + 新 ID 再落位**，互换也行；或不动 ID、把 `joint_ids` 写进配置 | 本地 `identify_joints.py` 是**只读**解 ID，**无写号流程** | ⚠️ 参考流程；本地 stance 是「只读优先」，写号需用户明确授权后才考虑 |
| 卸载条件值 | HD-1910 写 **5**、HL-2915 写 **13** | 本地有 reg19 是卸载条件（BIT0 电压保护）、本机实测读作 4，但**没有 5/13 这套目标值** | ⚠️ 新增目标值，需一手验证后再采纳 |
| 安全规则 | robotd 在跑时拒绝总线/IMU 操作（**停 robotd 不卸力**）；会动舵机的操作先网页确认「托好了」；读数超 0..4095 拒上扭矩；摆动 ±幅度 + 400mA 限流、>1.5A 或偏 15° 立刻切扭矩；写 EEPROM 先解锁 55=0 再上锁；IMU 200 不能占 | 本地有 EEPROM 时序 + 断电回读双验（更深） | ✅ 互补：本地强在写时序，远端强在**动作前安全联锁** |
| 波特率 1M/750k | A733 UART7 设 1M 实际 750k，改 ID/波特率要 CH343 USB 调试板 | 本地**三源交叉**已证（INTERFACE-CN.md:97 / set_baud.py:4 / feetech.rs:34-35），且算出 24MHz/16/3 | ❌ 本地更深，不借 |

## 4. 明确不借 / 不动的

- **RP1 全系 GPL-3.0**：`roboparty_joystick` 的两阶段 ACK（ACK1 500ms / ACK2 5000ms / 3 重试 /
  退避 1.5× / 同刻一个动作）、SPKI pin、WSS 通道——**思路可看、代码禁抄**（传染 Apache 主线）。
  且用户已明确不做 A8 演示入口，App 现状够用。
- **HD1910 策略 ONNX**：换策略=整条重训链，当前核心缺口是「无整机」，不是「没策略」。
- **3mf 打印工程 / STL**：采购与打印位已定（SSOT + 两张 xlsx 禁重跑），不动。
- **本地副本不更新**：`.upstream/DuckBuddy-main` 保持现状，避免污染主线与手工改动；需要时按
  单文件拉取对照即可。

## 5. 边界（UNVERIFIED 不翻）

- 远端 README 自述「整机日常运行」= **Orange Pi Zero 3W + 15 HL-2915 + 3S**，不是 HD1910；
  HD1910 那套明写「板子在焊、驱动和策略待做」⇒ 它的 HD1910 模型/策略是 **sim-only**，
  不能当真机验收证据。
- 本轮只比对文档与模型 XML，**未跑 MuJoCo / 未上板 / 未验证 reg31、reg46、0x16D6 在本地板子上成立**。
  全部保持 `UNVERIFIED`；`ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不变。
- 唯一官方仍是 `pollen-robotics/microduck`；DuckBuddy 是社区项目，来源标注按
  `docs/active/microduck-来源术语约定-2026-11-13.md`。

## 6. 建议落地顺序（供用户定，未执行）

1. 把 §3 表格里标 ✅ 的三条（IMU 型号/融合频率判据、SYNC_READ 错误率 ≤0.5%、reg46 必重写）
   补进 `deploy_import_checklist.md` 的 B/H 关卡——纯文档增量，低风险。
2. reg31 设中位、临时号 160 改号、卸载条件 5/13 标为「待真机验证」，不写进 SOP 通过项。
3. 若将来取得整机，再按 §2 拉模型做 sim 彩排对照；真机前一律不下发写命令。
