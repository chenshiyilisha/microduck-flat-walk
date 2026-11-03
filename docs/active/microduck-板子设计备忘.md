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

