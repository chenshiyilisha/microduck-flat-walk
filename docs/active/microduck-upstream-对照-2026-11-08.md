# MicroDuck 上游对照纪要（2026-11-08）

> 范围：把我们这条 **HD-1910 复刻线**（`microduck-software/`，Radxa/FT-SCS 原生协议，物理总线 ID **1–15**）
> 与上游三个相关源码树逐一对照：
> - `JoyandAI/microduck` —— `pollen-robotics/microduck` 的 fork，是「鸭子脑子」Rust 守护进程（robotd / duck-control）的**正源**，与 HD-1910 同平台；本仓库已把它快照到 `.upstream/` 下（`hd1910m` / `ft1910` / `DuckBuddy-main` 等）。
> - `hd1910m`（Radxa / FT-SCS 原生协议，物理 ID 1–15）
> - `ft1910`（较新，官方 Dynamixel ID 10–14/20–24/30–34，左腿优先 `JOINT_NAMES`）
> - `DuckBuddy-main`（社区项目 `Animan-AI/microduck-life`：HL-2915 / Orange Pi / **mode-0**）
>
> 凡写「查到」均有 `文件:行号` 出处；凡「推的」均明标。

---

## 0. 一句话结论

1. **两套关节 ID 体系绝对不能混抄**（见 §1）——这是 H11 清单那条「照抄别的项目 installation.json ⇒ 15 颗全错位」的根。
2. **reg33 线错已根治**（见 §2）——上游 HD-1910 线校验 `row[33]==4`（mode-4），DuckBuddy 线校验 `mode!=0`（reg33=0）；我们之前套了 DuckBuddy 的期望，已改回。
3. **真机可视化通道确实存在**（见 §4）——`robotctl monitor --json`（服务端降采样）吐出 `RobotState`，`joints`/`targets` 是裸角度数组，可直接喂 3D 查看器。已据此起草骨架（见 C 任务）。
4. **CWD 依赖已根治**（见 §6）——根因是工具默认锚 `cwd`；改为锚 `microduck-software/`（与 `record_provenance` 的 `ROOT` 一致）。**没有**改 toml 的 `../logs/...`，因为那会破坏 robotd 生产加载与 bundle/provenance 绑定。

---

## 1. 两套关节 ID 体系（最高优先级，不能混）

HD-1910 家族里「关节名 ↔ 总线 ID ↔ 数组下标」存在**两套互不相容**的约定。复制粘贴 `installation.json` / `joint_ids` / `JOINT_NAMES` 跨线 ⇒ 15 颗电机全部错位、总线电气全过但动作全错。

### 1.1 体系 A —— 我们的复刻线 / `hd1910m`（物理 ID 1–15）

- 出处：`.upstream/hd1910m/robot_description/servo_ids.json`
  ```json
  {"id":1,"name":"right_ankle"}, … {"id":15,"name":"mouth"}
  ```
  顺序（数组下标 0..14）：`right_ankle(1) right_knee(2) right_hip_pitch(3) right_hip_roll(4) right_hip_yaw(5) left_ankle(6) left_knee(7) left_hip_pitch(8) left_hip_roll(9) left_hip_yaw(10) head_pitch(11) neck_pitch(12) head_roll(13) head_yaw(14) mouth(15)`。
- **这是我们的物理总线 ID**：总线上的舵机就是 1–15。
- 我们的 `out/robotd_hd1910_mode0.toml` 的 `joint_ids` 也用 1–15，但**数组顺序采用了 ft1910 的左腿优先顺序**（见 1.2），所以 toml 里写的是 `[10,9,8,7,6,12,11,14,13,15,5,4,3,2,1]`——本质是把 1–15 按左腿优先名序排列。

### 1.2 体系 B —— 官方 / `ft1910`（真实 Dynamixel ID，左腿优先名序）

- 出处：`ft1910/duck-ipc-proto/src/lib.rs:536`（JOINT_NAMES）与 `:560`（JOINT_IDS）
  - `JOINT_NAMES`（数组下标 0..14，注意是**左腿优先**）：
    `left_hip_yaw left_hip_roll left_hip_pitch left_knee left_ankle neck_pitch head_pitch head_yaw head_roll mouth right_hip_yaw right_hip_roll right_hip_pitch right_knee right_ankle`
  - `JOINT_IDS`（与 JOINT_NAMES 同序）：`20,21,22,23,24（左腿） 30,31,32,33,34（颈/头/嘴） 10,11,12,13,14（右腿）`
- 即官方物理 ID：左腿 20–24、颈/头/嘴 30–34、右腿 10–14。

### 1.3 对照表（核心）

| 关节名 | 体系 A 物理 ID（我们/hd1910m） | 体系 B 物理 ID（官方/ft1910） | 数组下标（体系 A 名序） | 数组下标（体系 B 名序） |
|---|---|---|---|---|
| right_ankle | 1 | 14 | 0 | 14 |
| right_knee | 2 | 13 | 1 | 13 |
| right_hip_pitch | 3 | 12 | 2 | 12 |
| right_hip_roll | 4 | 11 | 3 | 11 |
| right_hip_yaw | 5 | 10 | 4 | 10 |
| left_ankle | 6 | 24 | 5 | 4 |
| left_knee | 7 | 23 | 6 | 3 |
| left_hip_pitch | 8 | 22 | 7 | 2 |
| left_hip_roll | 9 | 21 | 8 | 1 |
| left_hip_yaw | 10 | 20 | 9 | 0 |
| head_pitch | 11 | 32 | 10 | 6 |
| neck_pitch | 12 | 31 | 11 | 5 |
| head_roll | 13 | 33 | 12 | 8 |
| head_yaw | 14 | 34 | 13 | 7 |
| mouth | 15 | 30 | 14 | 9 |

> ⚠️ **结论**：我们这条线**永远用体系 A 的 1–15 物理 ID**；数组下标按我们 toml 采用的「左腿优先」名序（= 体系 B 名序）。
> 任何从官方/ft1910 仓库抄来的 `installation.json` 或 `JOINT_IDS` 都是体系 B（10–14/20–24/30–34），直接填进我们的机器人 ⇒ 整列错位。
> `audit_robotd_toml.py` 的 `bus.joint_ids` 审计（行 529–546）按 `JOINT_NAMES` 顺序校验 15 个互异 ID；我们给的参考集是 1–15 顺序（行 1188 `list(range(1,16))`），**不要**改成官方 ID。

---

## 2. reg33 线错（A 任务已修）

- **HD-1910 线（我们 / `hd1910m`）启动校验**：`hd1910m/duck-control/src/feetech.rs:690-709` 的 `open_with_imu` 读固件元数据快照 `sync_read(0,40)`，要求 **`row[33]==4`（mode-4）** 且行程限位 `low<high<=4095`；**不**逐个硬校验 reg6/reg9/11。台架实测 `reg33=4` 是**正确**的。
- **DuckBuddy 线（Orange Pi / HL-2915）校验**：`DuckBuddy-main/duck-control/src/feetech.rs:386` 校验 `mode != 0`（即 reg33=0）。
- 我们之前的 harness 常量 `EXPECTED_EEPROM = {6:1,33:0,9:0,11:4095}` 是 **DuckBuddy 线的期望（reg33=0）**，错套到 HD-1910 线。
- **已修**（`hardware_endtoend_check.py`）：
  - 删掉误用的 `EXPECTED_EEPROM`，改为 `EXPECTED_FIRMWARE = {"mode_reg33":4, "travel_limits":"low<high<=4095"}`；
  - 保留 `EXPECTED_EEPROM_DUCKBUDDY` **仅作对照并标注「不得用于本机体」**；
  - 静态检查改 `firmware.mode4/limits`；动态步骤 3 改 `3-firmware-check`，引用上游 `docs/robot/robotd_with_crc_error*.log` 作负对照；
  - selftest 加两条守卫：`EXPECTED_FIRMWARE.mode_reg33==4` 与 `DuckBuddy-line 期望未施加（reg33==0）`。
  - 验证：**selftest 9/9 PASS**（含 `EXPECTED_FIRMWARE mode_reg33==4` 与 `DuckBuddy-line NOT applied`），`py_compile` 通过。从 `/tmp` 任意 CWD 运行均通过（CWD 无关，见 §6）。

---

## 3. 单位换算（均查到，非推）

- **位置**：`ft1910/duck-control/src/bus.rs:543`（FT-SCS/feetech，4096 counts/rev）
  `position_rad = 2π · position / 4096 − π`
  反算 `raw = round(4096·(π + rad)/(2π))`（同文件 :690-691）。
- **计数/圈**：`ft1910/duck-control/src/scs/wire.rs:514` `POSITION_COUNTS_PER_REV = 4096.0`。
- **速度**：`ft1910/duck-control/src/bus.rs:40`
  `RAD_PER_SEC_PER_COUNT = 0.229 · (2π/60)`（即总线层 ≈0.229 RPM/count）。
  > 注：记忆里「速度标度 0.732 RPM/LSB」是我们 HD-1910 某次台架实测值（与官方 0.229 不一致，可能是不同舵机型号/标度），属「推的/待复核」，不要当作官方常量。
- **中位 / 电压 / 电流**：HD-1910-C001 中位 2048、4096/圈、电压窗 4.0–8.4V（2S 7.4V）、电流 6.5 mA/LSB（bias 73 暂扣）——这些来自机械/电气规格，属「推的/待复核」，仅作台架读数判读参考。

---

## 4. 真机可视化契约（`robot.state` / `RobotState`）—— C 任务依据

- **数据来源**：`robotctl monitor --json`（默认 **服务端降采样 10 Hz**，见 `ft1910/robotctl/src/main.rs:317-326` 的 `Monitor` 子命令与 `--fps`）。整帧是 `RobotState` 的 JSON 序列化。
- **结构体**：`ft1910/duck-ipc-proto/src/lib.rs:3781`（`RobotState`），关键字段（**索引均按 `JOINT_NAMES`**）：
  - `t: f64` —— 守护进程启动以来的秒数（单调，只用于关联采样，不是墙上时钟）。
  - `move: MoveState`、`head: [f64;4]`、`policy: String`（"walk"/"stand"/"held"）、`safety: SafetyState`、`loop: LoopState`。
  - **`joints: Vec<f64>` —— 实测关节角，弧度，按 `JOINT_NAMES` 索引（15 个）**。
  - **`targets: Vec<f64>` —— 指令角，弧度，同序**。查看器可据此画「跟踪误差」而非猜。
  - `velocities: Vec<f64>` —— 实测角速度，rad/s（**v36 新增；默认为空**：守护进程 <v36、或 `--fake`、或 `robotd.toml` 关 `publish_velocity_and_load` 时为空；**空 ≠ 静止，禁止渲染成 0**）。
  - `currents_ma: Vec<f64>` —— 每关节电流幅值，mA（同上默认空规则；是机器人唯一的外力测度）。
  - `odom: OdomState` —— 接触里程计位姿。
- **中继到浏览器/手机/LLM**：`mediad` 经 **WebRTC** 把帧 relay 出去（`DuckBuddy-main/mediad/src/...`、`*.webclient/index.html`）。即：真机可视化通道**存在且官方支持**，之前「没有可视化通道」的结论要推翻。
- **JOINT_NAMES 的确切顺序**（我们的机器人按此吐 `joints`/`targets`，左腿优先）：
  `left_hip_yaw(0) left_hip_roll(1) left_hip_pitch(2) left_knee(3) left_ankle(4) neck_pitch(5) head_pitch(6) head_yaw(7) head_roll(8) mouth(9) right_hip_yaw(10) right_hip_roll(11) right_hip_pitch(12) right_knee(13) right_ankle(14)`
  （与 `ft1910/duck-ipc-proto/src/lib.rs:536` 一致；我们的 `robotd_hd1910_mode0.toml` 注释也写明「left leg 0-4, neck/head/mouth 5-9, right leg 10-14」。）

---

## 5. fact-check 纪律（照搬的教训）

- `XL330` / `Radxa Zero 3W` / `IMX219` / `LSM6DSV16X` 均属**第三方逆向**，不是官方 BOM。
- 开源范围仅覆盖 **SDK / 仿真 / RL 训练**；机械与电气**不开源**。
- 任何「HD-1910 用了 X 零件/总线」的断言，先看它是不是逆向拼出来的，再决定是否进我们的规格文档。

---

## 6. CWD 依赖根治（D 任务）

### 6.1 根因
证据链的锚点不一致：
- `bundle_bindings.py` 的 `--root` 默认 `Path.cwd()`；而 bundle 内所有 `rel_path`（`logs/rsl_rl/...` onnx、`out/...` toml、3 份 `deploy_check_*.json`）都**相对 `microduck-software/`**。所以之前必须从 `microduck-software/` 启动，否则 `root / rel_path` 找错目录。
- `record_provenance.py` 用 `ROOT = HERE.parent.parent`（已锚到 `microduck-software/`）；CI 的 CWD 也是 `microduck-software/`。
- harness 之前靠 `os.chdir(ROOT)`（行 546）把自己修好。

### 6.2 为什么**不**采纳「把 toml 三路径改成 `../logs/rsl_rl/...`」
- 用户的原始提议是把 toml 的 `[policy]` onnx 路径改成 `../logs/...`（相对 toml 的父目录 `out/`）。查证后这会**更糟**：
  1. **破坏 robotd 生产加载**：`audit_robotd_toml.py:284-291` 明确——robotd 在运行时把相对路径**按它自己的 CWD** 解析（`duck-control/src/policy.rs`），不是按 toml 父目录。系统服务通常以 `/` 或自身目录为 CWD，`../logs/...` 会指向完全错误的位置 ⇒ 加载失败或静默回退到官方 alpha 步态。生产正确做法是**绝对板载路径**，不是 `../` 前缀。
  2. **破坏 bundle / provenance 绑定**：bundle 的 `provenance.per_artifact` 键与 `artifacts.*.rel_path` 都用 `logs/...`（相对 `microduck-software/`）。toml 改成 `../logs/...` 会让「audit 看到的路径」与「bundle 绑定路径」脱节 ⇒ SLSA subject mismatch FAIL。
  3. **只是换了一个启动约束**：从「必须在 microduck-software 启动」变成「必须在 git 根启动」，没根治。

### 6.3 真正的安全根治
- `bundle_bindings.py`：把 `--root` 默认值从 `Path.cwd()` 改为**锚到脚本所在仓库根** `(Path(__file__).resolve().parent).parent.parent` 即 `microduck-software/`，与 `record_provenance` 的 `ROOT` 完全一致（见文件内注释，写明「不改用 `../logs`」的理由）。
- 效果：**工具不再依赖启动 CWD**。
- 验证（均 PASS，无需特定 CWD）：
  - 从 **git 根** `E:/WorkBuddy/.../2026-10-23-08-26-15` 运行 `bundle_bindings.py`（无 `--root`）→ `VERDICT: PASS`。
  - 从 **`/tmp`** 运行（传绝对 `--bundle`）→ `VERDICT: PASS`。
  - harness `--selftest` 从 `/tmp` 运行 → `9/9 passed`（reg33 守卫在内）。
- **「连同证据链一起重生成」的落地**：证据链（bundle + 3 份 report + provenance）本身已一致且锚定 `microduck-software/`；本任务做的是**消除对 CWD 的依赖并重跑验证**，而不是重训/重新导出 onnx（那需要训练栈）。若日后要重新落盘证据链，跑 `record_provenance.py --verify` + `bundle_bindings.py --selftest` 即可，现在它们从任意目录都能跑通。

---

## 7. DuckBuddy 是什么（§2/§3 的来龙去脉）

- 社区项目 `Animan-AI/microduck-life`，基于 MicroDuck，硬件为 **Feetech HL-2915（HLS）/ Orange Pi A733 / 500k 波特率 / mode-0（reg33=0）**。
- 本仓库本地快照 `.upstream/DuckBuddy-main/`。**正是 A 任务里那条「reg33=0」错误期望的来源**——之前把它的启动校验错套到我们的 HD-1910（mode-4）线。
- 它自带一个 HLS 舵机调试器（`community-kit/software/hls_servo_debugger/`，含 webclient），可作为我们 HLS 调试的参考，但**舵机协议/模式与我们的 FT-SCS mode-4 不同，不能混用校准常量**。

---

## 8. 泰山派（RK3566）移植结论

- 立创官方定制镜像 **LCKFB-TSPI-RK3566** 已完成 MicroDuck 移植，与 Radxa 线**同 SoC**（RK3566），仅设备树不同：
  - 舵机 HD-1910 走 `/dev/ttyS3`（Radxa 线为 `/dev/ttyS2`）；
  - IMU LSM6DSV16X 走 `/dev/i2c-2`@0x6B（Radxa 线为 `/dev/i2c-4`）；
  - 预装 ONNX Runtime 1.28；robotd 50 Hz。
- SBC 选型：泰山派可作为 Radxa Zero 3W 的同级替代；**此刻最优仍是「别买板」**（台架 PC + URT-2 已能 50 Hz）。
- HAT 扩展板（屏幕/音频/RTC 类）多为通用外设，**非机器人专用**，选型时别被「HAT」字样误导。

---

## 9. 文件指针（精确出处）

| 主题 | 文件:行 |
|---|---|
| 我们线 1–15 物理 ID / 名序 | `.upstream/hd1910m/robot_description/servo_ids.json` |
| 官方 JOINT_NAMES / JOINT_IDS | `ft1910/duck-ipc-proto/src/lib.rs:536` / `:560` |
| 位置→弧度换算 | `ft1910/duck-control/src/bus.rs:543`、`:690` |
| 速度换算 | `ft1910/duck-control/src/bus.rs:40`；`scs/wire.rs:514`（4096/rev） |
| RobotState 契约 | `ft1910/duck-ipc-proto/src/lib.rs:3781` |
| monitor / 降采样 | `ft1910/robotctl/src/main.rs:317-326` |
| HD-1910 线开机校验（mode-4） | `.upstream/hd1910m/duck-control/src/feetech.rs:690-709` |
| DuckBuddy 线开机校验（mode!=0） | `DuckBuddy-main/duck-control/src/feetech.rs:386` |
| robotd 相对路径按自身 CWD 解析 | `duck-control/src/policy.rs`（见 `audit_robotd_toml.py:284-291` 注释） |
| 关节 ID 审计（我们的参考集 1–15） | `tools/hd1910/audit_robotd_toml.py:529-546`、`:1188` |
| harness reg33 修复 | `tools/hd1910/hardware_endtoend_check.py`（EXPECTED_FIRMWARE / selftest） |
| CWD 根治 | `tools/hd1910/bundle_bindings.py`（--root 默认锚 microduck-software） |
| 真机查看器骨架 | `tools/hd1910/live_viewer.py`（C 任务产出） |
