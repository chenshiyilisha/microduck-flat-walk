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

### 4.1 2026-11-06 实测：把「8 PASS」升级成官方口径，并查清 duck-sim / WSL

#### 4.1.1 `duck-sim` 本机跑不了；WSL2 能跑，但**验不了本分支真正要改的东西**

| 项 | 结论 | 依据 |
|---|---|---|
| 本机直跑 | ❌ | 无 `cargo` / `rustc`（`~/.cargo/bin` 也不存在）；无官方 workspace 全量 checkout；`scripts/duck-sim` 是 `#!/bin/sh`，要 `setsid`、`.venv/bin/python`、`libonnxruntime.so`，Windows 侧只有 `.dll` |
| 本机 WSL 是否可用 | **未验证** | `wsl.exe` 被本机安全策略列入黑名单，命令被拒；按纪律不重试、不绕过，故**不写成定案** |
| WSL2 跑 `up` 模式 | ✅ 技术上可行 | 官方 `docs/design/simulation.md` §3：body 走 **TCP 7801** 而非 unix socket，理由就是「a container on Linux, **a Linux VM with MuJoCo**」⇒ VM/WSL 是被设计支持的 |
| 需要 GUI 吗 | 不需要 | `DUCK_SIM_VIEWER=0` 触发 `--headless`（`docs/robot/simulation.md:168`）；WSLg 的 X11/Wayland + vGPU OpenGL 只是可选项（Microsoft Learn：需 WSL2 + Win10 19044+/Win11 + vGPU 驱动） |
| `boot` 模式 | ⚠️ 另加条件 | 需要 `sudo` + `systemd-nspawn` + `mmdebstrap`；WSL2 需 `/etc/wsl.conf` 开 `systemd=true`。用 `up` 即可绕开 |
| 跑起来还缺什么 | — | 605 文件官方 workspace、Rust 工具链（`cargo build -p robotd -p robotctl -p tof -p sounds -p configd -p updater`）、`microduck_rl` 的 `uv sync` venv、首次联网取 `velstand.onnx` |

🔴 **决定性边界**：官方 `docs/design/simulation.md` §7 原文 *Absent — not exercised at all: the Dynamixel bus driver … A servo bus dropping reads. The twin would have caught **none** of them.* `duck-sim` 用 `duck_control::sim::RemoteIo` **整条替换了舵机总线**。⇒ 它验不了 §3 要自己写的三个文件（`bus.rs` 的 `0x82`/addr56/15 B、`imu.rs` 的 15 B 飞特人格、`model.rs` 的 reg6/33 校验），也验不了 Radxa 1M 下的 16 设备时序与丢包。它能验的是「官方守护进程 + `p8head_2999` 能否站起 / 走、`policy load`、IPC、50 Hz 控制环、updater」——这部分有价值，但**不是飞特适配的证据**。真要装 WSL，用 `up` + headless，并显式 `action_scale = 1.0`。

#### 4.1.2 契约脚本升级（`verify_policy_contract.py`）

原先硬编码只读 B 代 `.upstream/DuckBuddy-main`。本轮新增 `--upstream <源码根>` 与 `--rehearsal`，把四个 Rust 文件全部改为按源码根解析；`_display()` 修掉源码树在仓库外时 `relative_to(ROOT)` 抛错。**并修掉一个会漏判的盲点**：`check_action` 原把「TOML 省略 `[policy] action_scale`」当成默认 1.0 放行，而官方与 B 代源码都是 `Mode::Walk => 0.9`。现在 `default_action_scale()` 直接从 `robotd-params/src/lib.rs` 的 `unwrap_or(match self.mode {...})` 读；读不到就判 FAIL，不静默假设。

`--selftest` 从 15 条扩到 **19 条**（新增：源码默认值 ==0.9、省略键 +0.9 ⇒ 必须红、显式 1.0 ⇒ 必须绿、默认值读不到 ⇒ 必须红）。**B 代与官方两棵源码树各跑一次，均 19/19 全绿。**

#### 4.1.3 四组实测（`p8head_2999.onnx`，`.venv-mjlab` 的 numpy/onnxruntime）

| 组 | `--upstream` | `--toml` | 结果 |
|---|---|---|---|
| A 回归 | B 代（默认） | 本仓 `robotd_hd1910_mode0.toml` | **8/8 PASS**（原结论保持） |
| B 官方默认 | `out/official-main` | 官方 `deploy/robotd.toml` | **7 PASS + 1 FAIL** |
| C 官方 + 显式 1.0 | `out/official-main` | 官方 TOML 加 `action_scale = 1.0` | **8/8 PASS** |
| D 官方默认 + 预演 | `out/official-main` | 官方 `deploy/robotd.toml` | 1 FAIL + 预演量化 |

B 组唯一红：*`toml omits [policy] action_scale -> robotd default 0.9`*。**这正是上一轮 §5.1 那条口径差的实证**，且它不是「全绿」——按项目纪律，一个能变红的检查比全绿更有证据力。C 组把唯一的红修掉后，官方口径下 **obs 61 / 14 关节序 / HOME 逐位 / 命令块拆分 / 50 Hz / ONNX 图全绿**，⇒ §3.2「`p8head_2999` 不必移植发布链、不重训」从 B 代口径升级为**官方源码口径实证**。

#### 4.1.4 官方 vs B 代：逐项核，不只比一个文件

| 项 | 结果 |
|---|---|
| `duck-control/src/obs.rs` `//!` 布局表 | **逐行 diff 为空**（61 / 13 / 六块 + 命令块拆分 [3,4,2,1,1,1,1]） |
| `DEFAULT_POSITION` | **逐行 diff 为空**（HOME 逐位 max \|diff\| = 0） |
| `JOINT_NAMES`（14 策略关节） | **逐行 diff 为空** |
| `JOINT_IDS` | 数值相同 `20-24 / 30-34 / 10-14`，但**定义位置不同**：官方在 `duck-ipc-proto/src/lib.rs:652`，B 代在 `duck-control/src/model.rs:16` ⇒ 只 grep 一个路径会误判成「B 代没有 ID 表」 |
| `action_scale` 默认 | 两棵树都 `Walk => 0.9 / Roller => 0.8`；`deploy/robotd.toml` 里 `# action_scale = 0.9` 是**注释**，TOML 解析器根本看不到这个键 |
| `control.hz` | 官方源码 `impl Default for Control` = 50；官方 TOML 显式写 `hz = 50` |

#### 4.1.5 ONNX 站姿预演（PC 侧替代 duck-sim 的静态部分，`--rehearsal`）

| 量 | 实测 | 作用 |
|---|---|---|
| `stand \|a\|max` | **0.1930 rad**，finite | 站姿动作有界，obs 没被读错 |
| 重力块翻转 `[0,0,-1]→[0,0,+1]` 后 `\|Δa\|` | **2.6785 rad** ⇒ SENSITIVE | **负对照**：输出确实随 obs 动，不是常数图 |
| `a[0:4]` | `[-0.0952, 0.131, -0.0134, 0.044]` | 量级可复核 |
| 官方默认 0.9 的目标误差 `\|a·(1−0.9)\|` | **0.0193 rad = 1.11°**（峰值关节） | 把「步态偏软」量化成具体角度 |
| 显式 1.0 后 | 0.0000 rad | 配置对齐即闭合 |

⚠️ 这是**图 + 输入敏感性检查，不是动力学仿真**：没有 MuJoCo、没有 50 Hz 闭环、没有 BAM 执行器。`policy load` 只查宽度不查语义，真机稳态仍要上板验。

#### 4.1.6 复现

```bash
V=microduck-software/.venv-mjlab/Scripts/python.exe
S=microduck-software/tools/hd1910/verify_policy_contract.py
ONNX=artifacts/flat_walk/checkpoints/p8head_2999.onnx
$V $S --selftest --upstream out/official-main              # 19/19
$V $S --upstream out/official-main --onnx $ONNX \
      --toml out/off_robotd.toml --rehearsal              # 7 PASS + 1 FAIL
$V $S --upstream out/official-main --onnx $ONNX \
      --toml out/official_robotd_scale1.toml --rehearsal  # 8/8 PASS
```

`out/official-main/` 是按官方目录结构摆的 4 个 Rust 文件镜像树（GitHub `main` 分支 raw 拉取），`out/official_robotd_scale1.toml` 是官方 TOML 只改一处加 `action_scale = 1.0`；两者都在被 gitignore 的 `out/`。原始输出见 `out/contract_official_default.txt`、`out/contract_official_scale1.txt`、`out/contract_official_09_rehearsal.txt`。

## 5. 必须先解决的口径差（别只报好消息）

1. 🔴 **`action_scale`**：官方 walk 默认 **0.9**，本仓训练/评估与成品 TOML 是 **1.0**。加载后必须显式写 `[policy] action_scale = 1.0`，否则输出被缩放 10%，症状像「步态偏软」而不是报错。这是配置对齐，不是换 plant。**§4.1 已实证**：官方源码 + 官方 TOML 实测 7 PASS / 1 FAIL，唯一的红正是这一条；显式写 1.0 后 8/8 PASS。默认 0.9 让峰值关节目标偏 **0.0193 rad = 1.11°**。⚠️ 官方 `deploy/robotd.toml` 里那行是**注释**（`# action_scale = 0.9`），TOML 解析器看不到键，别以为「文件里写了 0.9」就等于已配置。
2. 🔴 `robotctl policy load` **只查宽度、不查 obs 语义**。61/14 相同只是必要条件；§4.1 的 8 PASS 已是**官方源码口径**的静态契约，真机稳态仍要验。
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
| 守护进程架构、模拟器、开发链 | 官方 `README.md`、`docs/design/architecture.md`、`docs/robot/install-dev.md`、`docs/robot/simulation.md`、`docs/design/simulation.md` §3 / §7、`scripts/duck-sim`（`out/official/`） |
| WSL2 GUI / systemd 平台能力 | Microsoft Learn《Run Linux GUI apps on WSL》（WSL2 + WSLg X11/Wayland + vGPU OpenGL，需 Win10 19044+ / Win11）；本机 `wsl.exe` 被安全策略拒绝 ⇒ **本机是否装 WSL 未验证** |
| 总线 / IMU / 模型 / obs 常量 | 官方 `duck-control/src/{bus,imu,model,obs}.rs`、`duck-ipc-proto/src/lib.rs:652`、`deploy/robotd.toml`（713 行） |
| 交叉编译与 dev-push | 官方 `.cargo/config.toml`、`scripts/dev-push.sh`；deepwiki `9.3 Developer Workflow` |
| 许可分项、fork 分支、镜像组成 | fanhao375 `software/image/README.md`；GitHub API `repos/fanhao375/Microduck-kissqy` + `branches` |
| 价格与手焊/成品对照 | kissqy `DUCK-SHOPPING-LIST.md`（本地 `out/kissqy/`）、`docs/releases/public-image-r1.md`、`docs/MICRODUCK-BUILD-GUIDE.md` |
| HAT 打样成本与开源状态 | `chenkui164/microduck-replica/PROGRESS.md`、GitCode 硬件入门与 BOM 拆解两篇（社区重画，标注为二手） |
| 本仓口径与台架证据 | `.upstream/DuckBuddy-main/duck-control/src/obs.rs`、`microduck-software/tools/hd1910/` 四个校验脚本、`out/g0_60s.json`、`out/bus_budget_live_2026-11-06.txt` |
