# 第三分支：软件也自己写时，「完整功能 + 压价」的解（2026-11-06）

> 目标函数：**保留原版 zero3 完整功能 + 15×HD-1910 + 软件自己写 + 价格最低**。
> 本文只回答这一支。前两份文档的目标函数不同，均不被推翻（见 §6）。

## 0. 一句话判决

**软件自己写不改变硬件 BOM，也不改变总价（¥2,432.71，落地 ¥2,540–2,730），但它把「用一键镜像换功能」升级为「同价拿回全部自由度」**：

> `Radxa ZERO 3W 2GB 带排针` + **官方 Apache-2.0 workspace 派生的自有 fork**（改动集中在 `duck-control` 三个文件）+ `robotctl policy load` 直接挂自己的 `p8head_2999` + 成品 HAT/IMU + HUB 走 community-kit Gerber。**不重训，不碰 kissqy 的个人非商业许可。**

**主控仍是 Radxa，不回 A733。** 约束不是软件能力，而是 40-pin 复用与官方 `[board] version="zero3"` / `[bus] port="/dev/ttyS2"` / MIPI-I2S-I2C 设备树；软件自己写改不了引脚（见 `最优方案.md` §2.6 的同 SoC 不同复用判据）。

## 1. 为什么「软件自己写」省不了钱

软件本来就是 ¥0：官方 0.15.1 源码（Apache-2.0）、kissqy R1 镜像、R17 中控、10 个动作模型全免费。硬件 BOM 与软件作者无关——HAT 的音频 codec / 配电 / 半双工收发、IMU 板、相机、ToF、喇叭、电池、TF 卡、15 颗舵机，少一样就砍一项功能。

所以上一轮的四笔节省**原样成立**：团购 ¥99/颗 −¥300、PS5 DualSense 已有 −¥89.91、URT-2 已有 −¥45、HUB 改 Gerber −¥69 ⇒ **−¥503.91（−17.2%）→ ¥2,432.71**；必加打印件 ¥60–199 与电池接入/运费 ¥50–100 ⇒ **落地 ¥2,540–2,730**。

### 1.1 新增可压的几笔（都在一手清单里，但都有代价）

| 项 | 可省 | 前提 / 代价 | 判决 |
|---|---|---|---|
| 山泽读卡器 | ¥22.90 | kissqy 清单原文「已有可复用」 | ✅ 有就别买 |
| HAT+IMU 改手焊 | ¥83.78–123.78（成品 ¥218 → 首批材料 ¥94.22–134.22） | 要焊 HAT-V5 **84 器件** + IMU **25 器件**（含 LGA-14）；新购焊接/烧录工具 ¥800–1000 | ⚠️ **只有已有工具才划算** |
| 官方开源 HAT 自绘 | 看似省 ¥119 | `elec_RPI_Robot_HAT` Apache-2.0 确含 KiCad+Gerber+BOM+贴片坐标，但 **4 层板 / 123 颗件 / VQFN-32 + LGA-14 必须 SMT**，打样几百元起且有起订量 | ❌ 比成品贵 |
| Radxa 1GB 版 | 约 ¥100–170（官价口径混乱） | 官方验证基线是 **2GB / 无 eMMC / 带排针 ¥309**；7 守护进程 + WebRTC 相机 + ONNX 在 1GB 上无实机证据 | ❌ 不入定案 |

⇒ 极限档（已有工具 + 已有读卡器 + 愿手焊）≈ **¥2,286–2,326**，但**不推荐**：把软件省下的工时又换成了焊接风险。地板仍由 15×¥99=¥1,485 决定，占约 57%。

## 2. 自己写消掉的四项代价，与新增的一项收益

对照 `完整功能压价方案.md` §4.2：

| 上一轮（用 kissqy R1 镜像） | 本分支（自己写） |
|---|---|
| 🔴 部署链变了，`p8head_2999` 不能假定可加载 | 官方 `robotctl policy load <slot> <file>` 标准槽位，宽度 `obs[1,61]→actions[1,14]` 加载时硬校验；**官方与 B 代 `obs.rs` 布局表逐字节相同** ⇒ 可直接挂（§3.2） |
| 🔴 kp8 与 V164/V167 的 P5/D0 两个写者冲突 | 自己是唯一写者，保持台架实测已持久化的 `reg21/reg50=8` |
| 🔴 kissqy 原创部分「个人非商业」+ 模型个人非商业 | 官方 workspace Apache-2.0 + 自有 fork + 自己训的模型 ⇒ **可商用**（按文件核许可，§3.3） |
| 🔴 出厂 control.40 须升 43 / R17 V167 中控绑定 | 用官方 `robotctl` / `configd` / `btd`，版本自己定 |

**新增收益：回到 Radxa 让 1 Mbps 出厂可用。** 官方 `model.rs` 是 `BAUD_RATE=1_000_000`，HD-1910 出厂 `reg6=0` 正好 1M ⇒ **15 颗 reg6 一颗都不用写**（B13 的「免写」结论在 A733 分支被判作废，在 Radxa 分支重新成立）；IMU 成品预烧 FT6 免重刷、免反转 PA1 DE 有效电平。

## 3. 自己写到底要写多少：一手源码定位

架构前提：七个守护进程经 Unix socket 用同一份 JSON-RPC 契约通信，**只有 `robotd` 独占总线**；相机/ToF 不进 50 Hz 控制回路（纯发布者模式、数据面与控制面分离）。⇒ `configd / btd / padd / mediad / tofd / updaterd` **原样编译**，改动面集中在 `duck-control`：

| 文件 | 官方现状（一手原文） | 换 HD-1910 要改成 |
|---|---|---|
| `duck-control/src/model.rs` | `BAUD_RATE=1_000_000`；`EXPECTED_REGISTERS` = `return_delay_time 0` / `baud_rate 3`（**DXL 编码 3=1M**）/ `pwm_slope 255` / `shutdown 52`；`RAD_PER_SEC_PER_COUNT` 0.229 rpm/count；膝盖 `homing_offset` −45°（0.088°/count） | 换成 Feetech 开机硬校验（本仓 B 代口径 reg6 / reg33 / reg9 / reg11，`checked, not corrected`）；速度标度 0.732 rpm/count；零位只靠 `joint_offsets`；**`JOINT_IDS` 不用改** |
| `duck-control/src/bus.rs` | `rustypot::...::Xl330Controller`、`READ_ADDR=124 / READ_LEN=12`、`0x8A` fast sync read（16 设备拼一个状态包）、DXL sync_write | `0x82` SYNC_READ、`addr 56 / 15 B`、**缺席也占槽**；Feetech 帧实现本仓 `hd1910_readonly.py` 已有；关 `fast_sync_read` |
| `duck-control/src/imu.rs` | 12 B：gyro `i16` ±500 dps + SFLP half-float 四元数，`w = +√(1−n²)` | 15 B Feetech 人格（`sync_read(56, 0x0F)` 的 15 B 是净荷，21 B 是整帧 `LEN+4`，两者不矛盾）；`w` 正号有 ST 背书可保留 |
| `robotd-params` / 配置 | 官方 `[bus] fast_sync_read`、`[policy] action_scale=0.9`（walk 默认） | 回填本仓口径：`action_scale=1.0`、两个 lowpass=1.0、`imu_median=false`、`gain=200`、`cells=[2]+max_volts=8.4`；⚠️ `deny_unknown_fields`，写一个不存在的键 = 整份配置加载失败 |

### 3.2 `JOINT_IDS` 与 obs 不用动（本轮最硬的发现）

三份一手证据互相咬合：

1. 官方 `duck-ipc-proto/src/lib.rs:652`：`JOINT_IDS = [20..24, 30..34, 10..14]`，`IMU_DXL_ID=200` —— **正是本仓 B 代口径**，不是复刻线的 `1..15`（照抄会 15 颗全错位且电气全过）。
2. 官方 `deploy/robotd.toml` `[policy]` 原文：*All must be 61-input, 14-output: every alpha policy is obs[1,61] -> actions[1,14], and robotd checks that at load*；`robotctl policy load <slot> <file>` 可热换网络。
3. 官方 `duck-control/src/obs.rs` 布局表与 `.upstream/DuckBuddy-main/duck-control/src/obs.rs` **逐行 diff 为空**（`OBS_LEN=61` / `ACTION_LEN=14` / `COMMAND_LEN=13`，`gyro 3 → gravity 3 → joint_pos 14 → joint_vel 14 → last_action 14 → command 13`，body 块顺序 `z, roll, pitch`）。

本仓 `verify_policy_contract.py` 已对 `p8head_2999.onnx` + 成品 TOML 跑过 **8 项全 PASS**（含 obs 61、block order、14 关节顺序、HOME 逐位差 0、action mapping scale 1、50 Hz、ONNX 宽度、站姿动作幅值上限 0.193 rad）。⇒ **不需要自己移植发布链，也不需要重训。**

### 3.3 许可要按文件核，不能按仓库核

- 官方主仓 `pollen-robotics/microduck` 与 `pollen-robotics/elec_RPI_Robot_HAT`：GitHub API `license.spdx_id = Apache-2.0`（实测）。
- fanhao375 `software/image/README.md` 一手表格：官方运行时 0.15.1、他们 fork 的 `robotd/padd/mediad`、Microduck Studio、updater、ONNX Runtime = **Apache-2.0 / MIT**；**只有 10 个走路和动作模型是「个人非商业」**。
- `fanhao375/Microduck-kissqy` 是 `kissqy/Microduck-kissqy` 的 fork，API `license = None`、父仓 `NOASSERTION`，但有 7 个 `hd1910-*` 分支（`hd1910-v167-imu-dxl2`、`hd1910-v167-imu-autodetect` 等）可作起点 —— **其中 Rust 运行时代码仍继承官方 Apache-2.0**。
- ⇒ 可安全复用 **Rust 运行时源码**；不要连带复制镜像、模型、签名包、板卡设计。这与「`contents/LICENSE` 查不到 ≠ 项目没有许可」是同一类坑：**父仓的 `NOASSERTION` 不能反推 fork 里每个文件的许可**。

## 4. 零成本验证链（官方工具链本就是为自写设计的）

1. **`scripts/duck-sim`** —— PC 上跑真实守护进程 + MuJoCo 身体，**完全不需要硬件**；先在这里验 obs 组装与策略加载，不必等主板到货。
2. `cargo zigbuild --locked --release --target aarch64-unknown-linux-gnu.2.31 -p robotd --bin robotd`（官方 `.cargo/config.toml` 把 GLIBC 下限钉在 2.31；fanhao375 一手 README 给的是同一条命令）。
3. `docs/robot/install-dev.md`：Armbian 26.2.1 Minimal（Radxa Zero 3）→ `scripts/provision-board.sh` → `scripts/dev-push.sh` 一分钟推分支；注意 dev-push **走完整签名 / health gate / 回滚**，不是裸拷二进制。
4. `robotctl policy load walk p8head_2999.onnx` 热挂自己的模型。
5. 真机 G0–G5 沿用本仓 `sts_bench.py` / `probe_bus_budget.py` / `verify_policy_contract.py` / `policy_numeric_gate.py`（均已有 selftest 负对照）。

## 5. 必须先解决的口径差（别只报好消息）

1. 🔴 **`action_scale`**：官方 walk 默认 **0.9**，本仓训练/评估与成品 TOML 是 **1.0**。加载后必须显式写 `[policy] action_scale = 1.0`，否则输出被缩放 10%，症状像「步态偏软」而不是报错。这是配置对齐，不是换 plant。
2. 🔴 `robotctl policy load` **只查宽度、不查 obs 语义**。61/14 相同只是必要条件；8 PASS 是静态契约，真机稳态仍要验。
3. ⚠️ **总线三条线的速率与指令别混**：官方主仓（XL330）1M + `0x8A`；kissqy R1（HD-1910）1M + `0x82`；B 代 A733（HD-1910）500k + `0x82`。本分支走 **Radxa 1M + `0x82`**，整机 16 设备 @1M 的预算要**重测**（本仓 `probe_bus_budget.py` 的 10.28–17.41 ms 是 1M 单颗实测再外推到 500k，不能直接套）。
4. ⚠️ `fast_sync_read` 官方默认开，HD-1910 不实现 `0x8A`。官方注释明写 *a device that does not implement 0x8A does not answer, so every read fails* ⇒ 必须关。本仓 `probe_sync_read.py` 已在 ID 10 上验过「0x8A 沉默 / 0x82 应答」。
5. ⚠️ `EXPECTED_REGISTERS` 的 DXL `baud_rate=3` 是 **Dynamixel 编码**，套到 Feetech 会写成 128 kbps 直接失联；开机硬校验要整个换成 B 代口径。
6. ⚠️ 与软件谁写无关的两个老坑：4.5 V 台架欠压读数不可外推 7.4 V；`HOME` 是模型站姿不是编码器零位。
7. **未闭合**：DualSense 键位（`Bus/Vendor/Product/Version` 决定 SDL/gilrs mapping GUID）、¥45/颗 舵机报价真伪（淘宝）、banana 板站起压降、HAT 10 µF 电容耐压（3S 前）、官方 3D 模型 CC BY-NC-SA 非商用限制。

## 6. 与既有文档的关系：三条分支并存，不互相推翻

| 目标函数 | 主控 | 软件 | 功能 | 落地价 | 运动模型 |
|---|---|---|---|---|---|
| 最低价换最强主控、只求走路（`最优方案.md`） | A733 4GB+eMMC | 自己 `cargo build` B 代 robotd | 运动最小集 | ¥2,574–2,653 | 自己的 kp8 `p8head_2999` |
| 完整功能 + 最少工时（`完整功能压价方案.md`） | Radxa 2GB | kissqy R1 一键镜像 | 官方全栈 | ¥2,540–2,730 | 镜像配套 kp5 |
| **完整功能 + 软件自由（本文）** | **Radxa 2GB** | **官方 Apache 源码派生自有 fork** | **官方全栈** | **¥2,540–2,730** | **自己的 kp8 `p8head_2999`，不重训** |

三个解总价几乎相同，差别在「用什么换什么」：第一条用功能换主控，第二条用自由度换工时，第三条用工时换自由度。

**不重训**仍是默认结论（`最优方案.md` §3.6）：换主控载板、换软件实现都不进 MDP / obs / plant；只有改 plant 参数、改训练侧奖励/obs/低通，或真机行为排除配置后仍与 sim 不符才触发。

## 7. 来源（均为一手，2026-11-06 核）

| 内容 | 出处 |
|---|---|
| 许可、默认分支、文件树 605 项 | GitHub API `repos/pollen-robotics/microduck`（`main` / Apache-2.0）、`git/trees/main?recursive=1`；`repos/pollen-robotics/elec_RPI_Robot_HAT`（Apache-2.0） |
| 守护进程架构、模拟器、开发链 | 官方 `README.md`、`docs/design/architecture.md`、`docs/robot/install-dev.md`、`docs/robot/simulation.md` |
| 总线 / IMU / 模型 / obs 常量 | 官方 `duck-control/src/{bus,imu,model,obs}.rs`、`duck-ipc-proto/src/lib.rs:652`、`deploy/robotd.toml`（713 行） |
| 交叉编译与 dev-push | 官方 `.cargo/config.toml`、`scripts/dev-push.sh`；deepwiki `9.3 Developer Workflow` |
| 许可分项、fork 分支、镜像组成 | fanhao375 `software/image/README.md`；GitHub API `repos/fanhao375/Microduck-kissqy` + `branches` |
| 价格与手焊/成品对照 | kissqy `DUCK-SHOPPING-LIST.md`（本地 `out/kissqy/`）、`docs/releases/public-image-r1.md`、`docs/MICRODUCK-BUILD-GUIDE.md` |
| HAT 打样成本与开源状态 | `chenkui164/microduck-replica/PROGRESS.md`、GitCode 硬件入门与 BOM 拆解两篇（社区重画，标注为二手） |
| 本仓口径与台架证据 | `.upstream/DuckBuddy-main/duck-control/src/obs.rs`、`microduck-software/tools/hd1910/` 四个校验脚本、`out/g0_60s.json`、`out/bus_budget_live_2026-11-06.txt` |
