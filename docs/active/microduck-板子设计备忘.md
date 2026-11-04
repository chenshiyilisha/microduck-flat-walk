# 板子设计备忘（私人定做 · 后置）

记录日：2026-10-29。施工主线仍以 [采购清单 §7](../hardware/microduck-采购清单.md) 为准；**本页只钉「以后真要改板时怎么干」，现在不启动。**

相关：[2026-10-27 纪要 §1.2 IMU](microduck-2026-10-27裁决与场景纪要.md) · [软件方案](microduck-HD1910软件方案.md)

---

## 1. 现在不设计板

| 项 | 现行口径 | 出处 |
|---|---|---|
| 阶段 2 默认板 | **买 kissqy HAT+IMU 成品**（AMP2.0），不自打 | 采购清单 §7.4 |
| 官方 HAT 开源资料 | `pollen-robotics/elec_RPI_Robot_HAT` rev D1，`production/` 可交嘉立创（路线 A / 对照） | 采购清单 §4 |
| `imu_to_dxl` | **延后**；要对齐官方双 IMU / 镜像只认总线 ID 200 时再做 | 采购清单 §5；纪要 §1.2 |
| 社区可抄板 | `avanx/microduck_imu_to_ttl`、`jyg9/microduck-community-kit`、fanhao 手册 | `docs/reference/microduck-生态全景.md` |

阶段 0 台架过闸前，**不买打样、不开私人 PCB 项目**。

---

## 2. 以后私人定做时：可借鉴工具

**仓库**：[biosshot/easyeda-copilot](https://github.com/biosshot/easyeda-copilot)（MIT，TypeScript）

**是什么**：EasyEDA Pro / 嘉立创 EDA 的 **MCP 扩展**——用自然语言在**原生工程**里生成/重组原理图、搜 LCSC、约束布局与布线、跑官方 DRC；产出可继续手改，不是静态图。演示含 ESP32-C3 / MIMXRT 控制器，以及 `pico_duck` 一类小板例子。

**怎么接**：装 EasyEDA 扩展 + MCP 客户端（Codex / Claude Code 等）→ `npx -y easyeda-copilot-mcp`（见该仓 README.zh-CN）。

**适合我们的场景**

1. 以官方 HAT（Apache-2.0）或 kissqy/社区原理图为底，**改接口 / 供电 / 舵机座 / 1000 µF 入口**再下单。
2. 自研或改版 **`imu_to_dxl` 类总线小板**（LSM6 + MCU + 半双工，落 ID 200）。
3. 小转接 / 分线板（AMP2.0、XT60 并联供电），避免舵机座菊花链扛电流。

**硬边界**

- 必须 EasyEDA Pro；不是离线 KiCad 全家桶替代品。
- AI 过 DRC ≠ 可焊交付：半双工总线、电源、ESD、热仍要人审。
- MIT 可私用 / fork；**不替代**「先成品跑通」的花钱顺序。

---

## 3. 启动闸门（未满足就别开板）

1. 阶段 0 单颗 + 温升 / 总线闸门过。
2. 阶段 2 镜像版本已定（是否强制总线 ID 200）。
3. 成品 HAT 实测暴露**明确缺口**（缺座、缺电容、缺第二 IMU、供电触点不够）——缺口写成一页需求再进 EasyEDA。

---

## 4. 待开时的最小清单（预留，未采购）

| 步骤 | 内容 |
|---|---|
| 参考导入 | 官方 D1 Gerber/BOM 或社区开源工程 → EasyEDA |
| 工具 | EasyEDA Pro + easyeda-copilot MCP |
| 打样 | 嘉立创 5 片起；LCSC 对料；舵机座 **AMP2.0 / JST 规格写死** |
| 验收 | 空载上电 → 无短路 → sync_read 见预期 ID → 再上舵机 |

*本页不写入采购金额；金额仍跟采购清单阶段表。*

---

## 5. SBC 平替评估：robotd 对板子的真实要求（2026-11-03，一手源码，未上板）

**先给判据，再谈板子。** 读 `pollen-robotics/microduck@main` 后，robotd 对主控的要求比想象的低：

| 事实 | 出处 |
|---|---|
| release 只编 **`aarch64-unknown-linux-gnu`**（带 glibc 下限） | `.github/workflows/_build-release.yml:57` |
| 总线就是**一个按路径打开的串口**，`[bus] port` 可配 | `deploy/robotd.toml` `[bus]` |
| 还有 `robotd --port <path>` 覆盖（"for a board wired differently"） | `robotd/src/main.rs:239-246` |
| 用 `serialport::new(port, baud)`，**不做 RS485/半双工 ioctl** ⇒ 方向控制全在适配板 | `duck-control/src/bus.rs:485` |
| `[board] version` 只管 `hw_rev`、camera 型号/安装角、头 IMU 由谁读（`tofd` vs `robotd`）——**不管总线** | `robotd-params/src/board.rs:33-100` |

⇒ **板子层面，一台能开串口的 aarch64 Linux 就够了**；甚至旧笔记本 + URT-2 也能当主控。

### 5.1 但真正卡住的不是板子，是 ID 200 的 IMU 桥

`docs/design/architecture.md:54` 原文：「Fifteen servos and the **IMU board** share one serial bus」。
`bus.rs` 把 IMU 和 15 颗舵机放进**同一次** `sync_read`（`IMU_DXL_ID = 200`），并有 `imu_answers()`
单独 ping 它。**没有这块板，Radxa 也跑不了整机 robotd。**

而 `imu_to_dxl` **官方没开源**（`docs/archive/microduck-研究报告.md:122`），本页 §1 已登记「延后」。
⇒ **换板省不到钱，因为缺的是桥不是板。** 先做桥（LSM6DSV16X + 小 MCU + 半双工收发器，
落 ID 200、12 字节块、SFLP fp16 四元数），再谈用哪块 SBC。

### 5.2 候选板（按改动量排）

| 板 | 价格（2026-11 实价） | 改动量 | 结论 |
|---|---|---|---|
| **Radxa Zero 3W 1G/2G 无 eMMC + 排针** | 官方 ¥136–165（可见 ¥580 = 小店/套餐溢价 4.3×） | **零** | ✅ 唯一真平替 = 同款买对渠道 |
| Radxa Zero 3E | 更低 | 小 | ❌ DT compatible 是 `radxa,zero-3e`，`Board::detect` 只认 `radxa,zero3`/`zero-3` 前缀 ⇒ 判为未知板；且**无 WiFi/蓝牙** |
| Pi Zero 2W | ¥298 | 中 | 🟡 aarch64+glibc 可跑 release；HAT 的 I²C 就在**标准 3/5 脚**（`deploy/audio/i2c3-pihat.dts` 明写），原型本来就是 Pi Zero 2W；但 UART 要走 GPIO14/15（须禁蓝牙）、仍缺 ID 200 桥、DT 不匹配 |
| Orange Pi Zero 2W / Banana Pi M4 Zero（H618） | ¥89–120 | 大 | ⚠️ 同 65×30 40 针，但电气定义与 Pi 非一一对应，microduck 社区零先例 |
| ESP32-S3 | ¥85–105 | 重写 | ❌ 跑不了 robotd（Rust + onnxruntime + unix socket） |
| 旧 PC/笔记本 + URT-2 | 0 | 0 | ✅ 台架阶段的最优解 |

### 5.2.1 比算力更早撞墙的是散热（2026-11-04，第三方同款实测）

同型号（HD-1910 ×15）、同款 Radxa、同款 URT-2 的第三方整机记录（fanhao375 调试记录）：

| 现象 | 数字 |
|---|---|
| 主板温度 | **84–92 ℃** |
| CPU 频率 | **锁在 408 MHz** —— 不是"降一点"，是掉到最低档 |
| 控制周期 | **20 ms → 25 ms**，50 Hz 守不住 |
| 关掉 `mediad` / `tofd` 后 | 仍 85–92 ℃、仍锁 408 MHz ⇒ **不只是负载，散热本身不行** |
| 停掉网页服务 | 回到 20 ms |
| 最终解 | **开孔、做风道** —— 机械改动，不是软件改动 |

⇒ **50 Hz 守不守得住取决于散热，不取决于 CPU 主频。** 也解释了为什么他们
"条件最好的一次（20 ms、1.8 GHz、最低 7.6 V）仍然只换姿势、不连续迈步"：
周期抖动本身就是策略杀手 —— 训练里有 delay 随机化，但没有这种**冷热交替**的 20↔25 ms 抖动。

对我们的三条：① **别装** `mediad` / `tofd` / 网页服务（视觉不进策略，本来就不需要）；
② 散热在**装机阶段**做，不能"跑起来再补"；③ 整机验收必须**同时**记录 CPU 温度/频率、
实际 iteration 周期、舵机 reg63 —— 只看策略表现，会把散热问题误判成"策略不行"。

### 5.3 一个被忽略的官方参数：`--fake` / `--sim`

`robotd/src/main.rs:248-259` 自带两个开发后端：
- `--fake`：**"Run against a robot made of nothing"**（无物理、无跌倒、位置完美回显）；
- `--sim`：**"Run against a robot in MuJoCo, at host:port"**——**同一个守护进程 + 仿真身体**，
  上层（循环、策略、安全、跌倒检测、里程计、IPC）**一行不改**。

⇒ 不买任何板子就能跑**真的** robotd（含 §22.9 那套 limp_fall / deadman / gain 写入），
把它接到 MuJoCo 上即可验证 `[policy] gain=8` 这类配置是否生效。
⚠️ 但 release 只有 aarch64 ⇒ **x86 PC 上要自己 `cargo build`**（`ort` 用 `load-dynamic`，
没装 libonnxruntime 也能编译，只有建 session 的测试才需要它）。

### 5.4 结论

1. **要省钱，先别买板**：台架 PC + URT-2 就是 50 Hz，且 `rehearse_hd1910.py` 是已验证仪器。
2. **要整机**：瓶颈是 §5.1 的 ID 200 桥，不是 SBC。桥没做出来之前，买 Radxa 也只是多一块吃灰的板。
3. **真要换板**：技术上成立（一条串口 + aarch64），但 DT/overlay、updater 的 `hw_rev` 匹配、
   没有 `tofd`/`padd` 这些只属于 HAT 的服务，全是没人验证过的路。等有先例再走。


---

## 6. 第三方 imu_to_dxl 桥板出现（2026-11-03，商品图核对，未上板）

用户看到一块第三方复刻的 `imu_to_dxl` 小板——即 §5 判定的"缺的那块桥"。商品声明 vs 官方契约
（`duck-control/src/imu.rs` / `bus.rs` / `model.rs`，一手）：

| 商品声明 | 官方契约 | 判 |
|---|---|---|
| IMU = LSM6DSV16XTR | `imu.rs:1` "imu_to_dxl **v2** board (LSM6DSV16X)" | ✅ 同芯片 |
| 地址 200 / 1 Mbps | `model.rs:101/103` | ✅ |
| 5–24 V 供电、TTL 3.3 V 单总线 | 半双工 TTL（DATA 勿直连 TX） | ✅ |
| 支持 Dynamixel 2.0 Fast_read | `fast_sync_read` 默认 **true**（0x8A）；`bus.rs:477` 明写 ID 200 也必须实现 | ✅ 关键项命中 |
| 自适应 Dynamixel / 飞特（按帧识别） | 官方只说 Dynamixel；飞特人格是社区需求 | 🟡 要协议文档 |
| 飞特舵机需改 robotd，提供参考代码 | 与结论一致：robotd 全总线 Dynamixel P2.0；社区 `microduck_ft1910` 已登记 | ✅ 诚实 |
| 无需重训 | obs 的 gravity/gyro 同芯片 SFLP，格式一致则成立 | 🟡 要验证 |

**官方契约（= 到手验收清单）**：组合 sync_read `@124 len 12` ⇒
`[0..6] gyro x/y/z i16 LE ±500 dps` + `[6..12] SFLP 四元数 x/y/z`（IEEE half，w=√(1−x²−y²−z²)）；
**全零块 = SFLP 未就绪**（host 持旧值，不 snap 到 identity）；诊断全块 20 B；
慢速读 `@144 len 3` 只含 JOINT_IDS、不含 IMU。

**买前三问卖家**：① 协议文档（逐字节核 @124/12B 布局）；② Feetech 人格的 payload 是否同 12 B SFLP
格式；③ 参考代码基于哪个 robotd 版本（须对上 kissqy/ft1910 线）。

**含义**：§5 的死结（"缺的是桥不是板"）有解。桥到手 + 任一 aarch64 SBC（Pi Zero 2W ¥298 或
Radxa 3W 官方价）+ 飞特 robotd 补丁 = 整条 Feetech 线可跑。风险从"自研板打样 + 自写固件"
降为"到手逐字节验收"。主控决策（买哪块 SBC、何时买）在桥到手并验收之前**维持搁置**。

---

## 7. Pi Zero 2W 到底"缺"什么：缺的是 Radxa 被换上来加的那部分（2026-11-03，一手源码）

**结论**：Pi 缺的功能真实存在，但**全部不在走路回路上**；它们正是当年把原型从 Pi 换成 Radxa 的原因
（5 GHz 无线、音频编解码、相机、更快的 CPU）。零改动的 `zero3` 生产配置里，这些**要么默认关闭、
要么根本不用**。

### 7.1 板型键是声明式的，不是探测式的

`robotd-params/src/board.rs:1-15` 原文："**Declared, not detected.**" `Board::detect` 读设备树，
但**只有 `robotctl health` 用它**——用来提示"声明与硬件不符"，**没有任何逻辑按它分支**：
"Nothing switches on what it finds, because a guess that is right on the boards we have is not a
fact about the next one."

⇒ 在 Pi 上声明 `[board] version = "zero3"`，robotd 照跑，只是 `robotctl health` 会警告不符。
板型键只门控三件事：`hw_rev`（updater 的发布门槛，zero3=1 / beta=2）、相机型号（IMX219 / GC2093）、
相机安装角（90° / 0°）。

### 7.2 生产配置只用得到一个 overlay

`scripts/setup-board.sh:112-114` 原文：原型还启用了 `i2c-gpio-pihat`、`aic3104-pihat` 和 camera
overlay，"**none apply here** — our IMU rides the Dynamixel bus rather than I²C, and **`robotd` owns
no camera or audio**." ⇒ `REQUIRED_OVERLAY=uart2-m0` 一个。

| Pi 缺的功能 | robotd 需要吗 | 依据 |
|---|---|---|
| 5 GHz 无线（AIC8800） | ❌ 不需要 | 板型键只影响相机/hw_rev；无线由上层远程访问设计自理 |
| 音频编解码 TLV320AIC3104 | ❌ 不需要 | setup-board.sh:114 "robotd owns no ... audio" |
| 相机 IMX219（含 90° 安装角） | ❌ **走路回路不需要**（但官方确有视觉功能，见 §8） | 同上；`zero3` 生产配置**不启** camera overlay |
| 头 IMU（BMI088） | ❌ **默认就是关的** | `params_lib.rs:1331-1341`：zero3 默认 `false`，因为"读它要花约 4% 的一个核"；beta 才是开 |
| ToF（i2c-gpio） | ❌ 可选 | `robotd_main.rs:2397`："tofd keeps its own counsel"；重启可容忍 |

### 7.3 真正要付的代价（都不是"功能缺失"，是胶水）

1. **UART**：必须用 PL011 走 GPIO14/15 + `dtoverlay=disable-bt`（**代价是失去蓝牙**）；Zero 2W 默认
   `ttyS0` 是 miniUART，时钟随 VPU 调频，跑不了 1 Mbps 总线。
2. **`libonnxruntime.so`**：`duck-control/Cargo.toml` 用 `ort = "=2.0.0-rc.11"` + **`load-dynamic`**
   ⇒ 运行期 dlopen，Pi OS 不自带此库，得自己放一个 aarch64 的（版本要对得上 ort rc.11 的 API）。
3. **只有 1 个数据 micro-USB**：URT-2 占掉就没有第二个 USB 口。
4. **512 MB RAM / 无 eMMC**：跑 robotd+策略够（15 MB daemon 包，P8 仅 775 KB），但加相机串流就紧；
   SD 卡要 A2，日志写放大要注意。
5. **官方 HAT 不是 Pi 形状的**：HAT 的总线走 `uart2-m0`、ToF 走 i2c-gpio、codec 走 i2s3、相机是 Radxa
   FPC；40 针**机械兼容、功能不兼容**。我们这条飞特线本来就用第三方桥手接，不受影响。
6. **provision/updater**：`setup-board.sh` 是 Armbian/RK3568 专用（`ttyS2`、`rk3568` overlay 前缀、
   停 getty），Pi 上不能跑；updater 按 `hw_rev=1` 放行 zero3 的通用 release（同 aarch64 包），
   但板级脚本要自己写一份等价物。

### 7.4 反向证据：50 Hz 本来就是在 Pi Zero 2W 上定的

`params_lib.rs:2525-2526` 原文："50 Hz is inherited from the prototype, where it was chosen on a
**Pi Zero 2W** — re-derive it on the Radxa rather than trusting it."

⇒ **控制节拍的原生平台就是 Pi Zero 2W**；Radxa 是后来为了相机/音频/无线才换的。
`fast_sync_read` 也可关（`bus.rs:477`：设备不支持 0x8A 就整条读超时，关掉即解），
所以"桥只实现普通 sync read"也有退路。

### 7.5 一句话

**Pi Zero 2W 缺的是"情感/语音/视觉"那一层，不是"走路"那一层。** 走路要的三件——UART、总线上
ID 200 的 IMU、ONNX 推理——它都有；代价是关蓝牙、自己放 libonnxruntime、一个 USB 口、SD 卡启动。

---

## 8. 相机与视觉：官方确实有，但它是"功能"，不是"走路"

**问题**：原版有 IMX219，那不就是视觉吗？——是，但视觉的去处不是策略。

### 8.1 相机被谁消费（`architecture.md:89`）

`mediad` = "the camera and audio pipeline; **nothing of the robot**"。它输出：

- WebRTC 视频/音频（手机 App、远程控制台）
- `:8080` 上的 `GET /frame`（单张 PNG 调试接口）
- `robotctl monitor` 的相机块（面板开着时 2 帧/秒，关掉就完全不取）
- `/run/mediad/media.sock` 的 `media.frame`（给本地录像或**感知进程**）

### 8.2 视觉真存在：`duck-detect`，但只做"找同类"

`duck-detect/src/lib.rs` 开头："Finding other Microducks in this Microduck's camera, **on the NPU**."
INT8 `.rknn`，320×320 入、单类、2100 候选框；crate 里三件事：letterbox、运行时、解码。
**关键**：它同时有两条运行时——`rknn.rs`（Rockchip NPU）与 **`onnx.rs`（CPU 回退）**，
后者的 Cargo 注释写明动机："the library belongs to the board, not to the build — and
`setup-board.sh` already puts it there for robotd's policies, **so a board that can walk can also see**."

⇒ **非 NPU 平台（含 Pi）走 CPU 回退，复用同一个 `libonnxruntime.so`，不需要改代码。**

### 8.3 但它不进策略：观测里没有像素

`architecture.md:321` §2.4 标题就叫 **"Data plane: features, not frames"**：

> `robotd` does not need camera frames — it needs *derived features*（"ball at (x,y)"、"person
> detected"、"loud sound"）。**Principle: put perception next to the sensor.** `mediad` owns the
> camera, runs inference, and publishes features.

走路策略的观测是 61 维本体感觉（关节位置/速度、上帧动作、重力、陀螺、速度指令），**没有图像**；
我们的 P8 ONNX 输入就是 `[1, 61]`。相机帧**从不进 robotd**（`robotd_main.rs` 里搜不到任何取帧代码）。

### 8.4 一个必须纠正的误读：`[pickup]` 不是视觉

`duck-control/models/pickup_detector.onnx`（36 KB）名字像视觉，实际是**本体感觉分类器**：
`robotd.toml:349-353` 原文——"A small classifier reads the last second of what the loop already reads
(**gyro, gravity, joints, what it commanded**)"，用来判断"有人把机器人端在手里"并暂停策略。
默认**开启**（`PickupParams::default.enabled = true`）。与相机无关。

另有一个 `pet_detect`（摸头检测）走**麦克风**，`audio.enabled` 才启动。

### 8.5 对 Pi 的实际含义

| 项 | Radxa Zero 3W | Pi Zero 2W |
|---|---|---|
| 视频流/App | ✓ IMX219 | ✓ 需换 Pi CSI 相机（HAT 的 FPC 是 Radxa 的） |
| 找同类（duck-detect） | ✓ RKNN NPU | ✓ CPU 回退，**同一份 `libonnxruntime.so`** |
| 速度 | NPU，实时 | 🟠 推算 0.2–0.5 s/帧（YOLOv5n@320 在 Zero 2W 的社区实测 200–440 ms 量级） |
| 进走路策略 | ✗ 都不进 | ✗ 同样不进 |

⇒ **视觉是"走路之外的功能"，Pi 掉的是它的速度（NPU→CPU），不是它的存在。**
反过来说：**要做视觉，Pi 不是不能，是慢到 2–5 fps**——够"看见有鸭子"，不够任何闭环控制。

### 8.6 顺带修掉 §7 的一条

§7 说"`libonnxruntime.so` 是最容易漏的一项"——`setup-board.sh:5,23-36,277-284` 显示它是一条
**脚本化步骤**：从 microsoft/onnxruntime 公共 release 下 `ONNX_VERSION=1.28.0` 的 aarch64 包到
`/usr/local/lib`，并且"ort 的版本检查是**硬失败**不是警告"（`expected >= 1.23.x`）。
Pi 上照抄这一段即可，不是手工难题。

---

## 9. 具体 SKU 核对：「4GB + 无 eMMC + 带排针」（2026-11-03，电商页，未下单）

用户看到的商品标题带「【Microduck 原版主板】」。逐项核：

| 项 | 这款 | 是否够用 | 依据 |
|---|---|---|---|
| SoC | RK3566 四核 A55 1.6 GHz | ✅ | `Board::detect` 只认 DT 前缀 `radxa,zero3` / `radxa,zero-3` |
| RAM 4GB | 官方 1/2/4/8 可选 | ✅ **超配但不错** | 第三方复刻 BOM 原文 "**2 GB RAM or more**"；robotd 包 15 MB + P8 ONNX 775 KB，512 MB 都够。4GB 只对相机/duck-detect/桌面调试有意义 |
| 无 eMMC | 走 microSD | 🟡 **可行，多一项成本与风险** | 同上 BOM："microSD card 32 GB **A1 or better** — if the Radxa has **no eMMC**"；机器人上 SD 卡受震动/掉电/日志写放大，eMMC 原文标 "**preferred**" |
| 带排针 | 已焊 40 pin | ✅ **必选** | 官方加价 $1 才给排针，HAT/接线都要它 |
| WiFi6 | AIC8800 | ✅ 无关但更好 | robotd 不用无线；`setup-board.sh` 仍会装 aic8800 驱动 |

**官方定价（Arace / 官方店，Liliputing 2023-12 更新）**：1GB/0=$15、2GB/0=$20、
**4GB/0=$30**、4GB/32GB eMMC=$45、8GB/0=$45、8GB/64GB=$65，**+$1 加排针**。
⇒ 这款的官方等值价 ≈ **$31 ≈ ¥225**。

**判断**：
1. **配置不是问题**，唯一要看的只剩价格。¥580 ⇒ 2.6× 溢价（比 1GB 版 ¥580 的 4.3× 略好，
   因为 4GB 本身就值 $30）；≤¥300 属正常含税运费区间。
2. **同价优先要 eMMC 版**（4GB/32GB eMMC = $45 ≈ ¥325）：机器人天天震动 + 掉电，eMMC 比
   SD 卡可靠，且省一张 A1 卡（¥40–85）。「无 eMMC」只在便宜 100 元以上时才划算。
3. **真正最省的 SKU 是 2GB/0 = $20（≈¥145）**：对 walking 完全够，4GB 是为视觉留的余量。
4. 「Microduck 原版主板」是**卖家话术**，官方从未指定某个 SKU 叫"原版"；任何 Zero 3W 都能过
   `Board::detect`。可据此判断卖家懂行（大概率是社区货），但不能当验收依据。
5. ⚠️ **买板仍不是当前瓶颈**（§5.1：缺的是 ID 200 桥）。若只是"顺手收一块当通用 Linux 板"，
   按上面价格阈值买不亏；若是为了跑整机，等桥板验收。

---

## 10. 想在 PC 上跑 `robotd --fake` 验配置？Windows 走不通（2026-11-03，源码级）

结论先给：**robotd 在 Windows 上编译不过，不是"缺工具链"，是源码用了 unix-only API。**

| 证据 | 位置 | 含义 |
|---|---|---|
| `use tokio::net::{UnixListener, UnixStream};` **无条件** | `robotd/src/main.rs:51` | tokio 的 `UnixListener` 只在 unix 存在，Windows 编译直接失败 |
| `use std::os::unix::fs::{FileTypeExt, PermissionsExt};` | `main.rs:4279` | 同上，`std::os::unix` 在 Windows 不存在 |
| 整个 IPC 面（`robotctl` ↔ robotd）就是 unix domain socket | `main.rs:4277-4421` | 不是可选路径，是主控制通道 |
| `type BusIo = FakeIo;` 在 `not(target_os = "linux")` | `main.rs:1457-1461` | 即使编过，非 Linux 也**没有真总线** |
| `--fake` → `FakeIo::at(DEFAULT_POSITION)`、`--sim` → `sim::RemoteIo::at(addr)` | `main.rs:1342-1363` | 两个后端**都不碰串口** |

⇒ 两个后果：

1. **别在 Windows 上折腾 Rust 工具链**（MSVC 或 mingw 都不用装）。装了也编不过；
   要跑只能在 Linux（本机 WSL 被安全策略禁用，Docker 未装）。
2. **即使跑起来，`--fake` 也验不了 `[policy] gain=8`**——fake 总线是内存模拟，
   `set_gain` 写进去没有可回读的寄存器。"配置生效"这件事在 Windows 上**无法用运行验证**。

**替代品（已入仓）**：`tools/hd1910/audit_robotd_toml.py` 把"配置是否与训练标度一致"
变成静态检查，正好对症 §22.8 那类事故（默认值覆盖没写的键）。它同时暴露了四个
按 `gain=200` 标定、在 kp8 下全部失配的参数——见 `docs/05-flat-walk.md` §22.10。

**唯一能验运行时的地方**：真板（Radxa/Pi）起 `robotd` 后回读 reg 50（清单 B8）。
不买板就没有这一步，这一点没有替代方案。
