# HD-1910 复刻线 · 把 feetech_hls robotd 烤到泰山派(LCKFB-TSPI)立创镜像

_起草日期：2026-11-09 · 状态：**步骤草案（待板验证）**，非已验证流程。_

_定位：这是「换板不换协议」的部署草案——保持我们复刻线 `feetech_hls` + 500k + 关节 ID 1–15 全部工具链，只把 robotd 从 Radxa Zero 3W 迁到泰山派 RK3566，复用立创官方镜像的内核/设备树/系统层，改 `port=ttyS3` + 对齐 IMU 朝向即可。_

_证据等级标注：`✅已核实`= 之前会话已从源码/官方文档核对；`⚠️推的/待查`= 本次未实测、需上板或读源码确认。_

---

## 0. 为什么这是"低难度迁移"而不是"从零移植"

- ✅ **同 SoC**：泰山派 = Rockchip **RK3566**，与 Radxa Zero 3W 同款（4×A55, aarch64）。robotd 二进制无需为 CPU 重编（`.cargo/config.toml:3` 即 `aarch64-unknown-linux-gnu`）。
- ✅ **robotd 不钉板子厂商**：身份识别只从通用 `/proc/device-tree/serial-number` 读序列号（`configd/src/identity.rs:35`），无 Radxa/Orange Pi 专属分支。
- ✅ **现成系统层**：立创官方 Microduck 泰山派案例镜像（kernel 6.1.141，**已含 UART3 半双工支持**），舵机 `/dev/ttyS3`、IMU `/dev/i2c-2` @0x6B——系统/内核/部署层不用自搞。
- ✅ **现成内核补丁**：`docs/active/microduck-taishanpi-uart3-halfduplex-20261021.patch`（源于 `jlckfb/easyduck`）已 vendored，直接可用（见 §4）。

> 真正的决策变量是「**换不换舵机协议分支**」：本草案选 **保持 `feetech_hls`**（推荐，因训练/EEPROM/标定/HLS 工具链全在这条线），**不**切 EasyDuck 的 `scs`（1MHz + 官方 ID 体系）。保持 HLS 时，迁移本质是"换板不换协议"。

---

## 1. 决策：保留 feetech_hls 分支（不要切 SCS）

| 维度 | 我们复刻线（本草案采用） | EasyDuck `scs`（不采用） |
|---|---|---|
| 协议实现 | `feetech.rs` / `feetech_hls` | `scs.rs` / 标准 SCS |
| 波特率 | **500_000**（`feetech.rs:35` 硬编码） | **1_000_000** |
| 关节 ID 体系 | **1–15**（左腿优先，来自 `hd1910m/installation.json`） | 20–24/30–34/10–14（官方） |
| 与现有工具链 | ✅ `hls_probe`/EEPROM 校验/标定/零位全兼容 | ❌ 全不兼容 |

⚠️ 若误把 EasyDuck 的 `scs` 驱动或官方 ID 体系塞进我们的 toml：`Bus` 带 `deny_unknown_fields`，且 `joint_ids` 体系错位会让 15 颗全错位、电气全过、症状只是往错方向倒（见 `deploy_import_checklist.md` H11）。**本草案全程保持 `servo="feetech_hls"` + `joint_ids` 1–15 体系。**

---

## 2. 目标镜像与已验证的现成资源

- ✅ 立创官方 Microduck 泰山派案例镜像：`wiki.lckfb.com/zh-hans/tspi-rk3566/project-case/microduck/image.html`
  - 定制 Debian 12，内核 **6.1.141 "包含 UART3 半双工控制支持"**，预装 ONNX Runtime 1.28、整套 robotd。
  - 舵机 `/dev/ttyS3`、IMU `/dev/i2c-2` @0x6B（BNO085/LSM6DSV16X 自动探测）。
- ✅ 内核半双工补丁：`docs/active/microduck-taishanpi-uart3-halfduplex-20261021.patch`（已 vendored，源自 `jlckfb/easyduck`）。

> ⚠️ **待查**：立创镜像是否已把 `485_ctrl_gpio` 绑到具体物理 DE/RE 引脚、以及该引脚在哪个 40-pin 脚位。若镜像内核已含支持但设备树未绑具体 GPIO，仍需在板设备树补一行（见 §3）。**先 `cat /proc/device-tree/.../485_ctrl_gpio` 或读镜像 DTS 确认**，再决定走 §4 的"用现成镜像"还是"自编译内核"。

---

## 3. 设备树 485_ctrl_gpio 接线

半双工舵机总线需要一个 **DE/RE 方向脚** 来翻转收发器方向。补丁从设备树属性 `485_ctrl_gpio` 读取这个 GPIO，由内核在每次 TX 时自动翻转。

### 3.1 已 vendored 的接线（来自补丁 DTS hunk）
补丁给 `tspi-rk3566-user-v10-linux.dts` 的 `uart3` 节点加了：
```dts
&uart3 {
    status = "okay";
    pinctrl-names = "default";
    pinctrl-0 = <&uart3m1_xfer>;
    485_ctrl_gpio = <&gpio3 RK_PC4 GPIO_ACTIVE_HIGH>;   // DE/RE 方向脚
};
```
- ✅ `ttyS3` ↔ RK3566 的 **uart3**（pinctrl `uart3m1_xfer` 决定 TX/RX 引脚组）。
- ✅ DE/RE 方向脚 = **GPIO3_C4**，极性 `ACTIVE_HIGH`（DE 输出高 = 发送态）。

### 3.2 硬件接线（🔴 硬前提：robotd 自己不翻方向，方向全靠这里）
- ✅ 逻辑：舵机半双工总线 → RS485/单线收发器 → 收发器的 **DE 与 /RE 并联** 接到 GPIO3_C4；TX/RX 接到 uart3 的 TX/RX 引脚组。
- 🔴 **为何是硬前提（R1 结论派生）**：robotd 的 `FeetechIo::open` 只 `serialport::new().open()`，**用户态完全不翻方向脚**（§9 R1 已查实）。所以半双工方向**必须**由本节的收发器 + 内核 DE gpio 提供。收发器 DE/RE 没接到 GPIO3_C4（或没打 §4 补丁）→ robotd 静默读不到总线，症状像"舵机坏了"。
- ✅ **最稳路径**：直接用**立创泰山派 Microduck 载板**（其伺服接口已把收发器 DE/RE 接 GPIO3_C4 且内核支持——EasyDuck 能在上面跑即证据），跳过自接线。
- ⚠️ **自接线才待查**：若不用立创载板，GPIO3_C4 在 40-pin 排针上的具体脚位（查 RK3566 数据手册 / 立创载板丝印）+ uart3m1_xfer 的 TX/RX 脚位必须拿到板 + 原理图钉死，**不要照抄 Radxa 排针定义**。
- ⚠️ 极性：补丁 `GPIOF_OUT_INIT_*` 使 DE 上电为**接收态**（半双工总线空闲约定）。若实际收发器是低有效 DE，把 `GPIO_ACTIVE_HIGH` 改成 `GPIO_ACTIVE_LOW`（补丁已支持，极性取自 GPIO flags cell）。

---

## 4. 内核打补丁与重编译流程

> 仅当 §2 确认立创镜像**未**含 DE 绑定、或你要自编译内核时才走此节。若镜像已含，跳到 §5。

补丁本身**与波特率无关**（波特率只是 termios `B500000`），可直接复用，省掉自踩 em485 卡死 + TX DMA 串扰的坑。代价：基于内核 **6.1.141**，需重编译内核（不是 dt-overlay 即插即用）。

1. **取源码**：立创官方 6.1.141 内核源码（与镜像同版本，否则模块签名/ABI 对不上）。
2. **打补丁**：
   ```bash
   cd linux-tspi-6.1.141
   git apply --check ../docs/active/microduck-taishanpi-uart3-halfduplex-20261021.patch
   git apply            ../docs/active/microduck-taishanpi-uart3-halfduplex-20261021.patch
   ```
3. **确认三处改动落地**（负对照：patch 未应用则下面三处都缺）：
   - `drivers/tty/serial/8250/8250_dw.c`：`of_get_named_gpio_flags(..., "485_ctrl_gpio", ...)` 存在、`de_gpio=-1` 初始化、`de_gpio < 0` 才挂 DMA。
   - `drivers/tty/serial/8250/8250_port.c`：`serial8250_de_assert/release` 两个函数、且 `serial8250_tx_chars` 里在 FIFO 批次前后调用它们。
   - `include/linux/serial_8250.h`：`struct uart_8250_port` 新增 `int de_gpio; bool de_active_low;`。
4. **设备树**：确认 §3.1 的 `485_ctrl_gpio` 行已进 `tspi-rk3566-user-v10-linux.dts`（补丁已含）。
5. **编译**：
   ```bash
   make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- defconfig   # 或官方 config
   make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) Image dtbs modules
   ```
6. **刷写**：把新 `Image` + `tspi-rk3566-*.dtb` 拷到 boot 分区（保留原镜像的 `/lib/modules` 版本一致），重启。
7. **验证内核生效**（上板）：
   ```bash
   dmesg | grep -i "RS485 direction on gpio"     # 应看到 DE gpio 绑定日志
   ```
   看不到该日志 = 设备树没绑到 GPIO（回到 §3.2 核脚位）。

---

## 5. robotd 二进制交叉编译与部署

1. **交叉编译**（在 x86 开发机，已装 `aarch64-linux-gnu-` 工具链 + Rust target）：
   ```bash
   rustup target add aarch64-unknown-linux-gnu
   cd <robotd 仓库>            # DuckBuddy-main（B 代，唯一说 feetech 的一代）
   cargo build --release --target aarch64-unknown-linux-gnu
   ```
   ✅ `.cargo/config.toml:3` 已是 `aarch64-unknown-linux-gnu`，无需改。
2. **部署到板**：拷 `target/aarch64-unknown-linux-gnu/release/robotd`（+ `robotctl` 等）到泰山派 `/opt/robot/daemon/current/`。
   ⚠️ robotd 解析**相对路径针对它自己的 CWD**（`duck-control/src/policy.rs`）——策略 onnx 必须写成**板上绝对路径**（见 §6），dev 相对路径在机器人上不解析。
3. **策略 onnx**：把 `out/p8head_2999.onnx`（及 standup/ground_pick）烤到板，改写 `[policy]` 三个绝对路径。

---

## 6. 部署 toml 改造（基于 `out/robotd_hd1910_mode0.toml`）

| 项 | Radxa（现状） | 泰山派（改后） | 说明 |
|---|---|---|---|
| `[bus] port` | `/dev/ttyS2` | **`/dev/ttyS3`** | ✅ 立创镜像舵机设备名；改这一行即可（波特率 500k 仍硬编码在 feetech.rs，toml 无 `baud` 键——写了反而 `deny_unknown_fields` 拒加载） |
| `[bus] servo` | `feetech_hls` | `feetech_hls` | ✅ 保持不变（HLS 分支） |
| `[bus] joint_ids` | `1–15` 体系 | `1–15` 体系 | ✅ 保持不变（H11：别照抄官方 ID 体系） |
| `[bus] joint_signs/offsets` | 现有 | 现有 | ✅ 逐颗在机器人上用 `identify_joints.py` 核对 |
| `[imu]` i2c 总线 | Radxa i2c | **`/dev/i2c-2`** | ⚠️ 改到泰山派 IMU 总线号；`imu_mount_quat` 见 §7 |
| `[battery] cells` | `[2]` | `[2]` | ✅ 必须保持 `[2]+max_volts=8.4`（默认 `[2,3]` 会让 3S 被当合法、烧舵机） |
| `[bus] imu_median` | `false` | `false` | ✅ 故意偏离上游（中值=纯 20ms 延迟，超训练包络） |

### EEPROM 开机硬校验（✅ 每个机器人上电必过，robotd 不替你改）
`feetech.rs:386` 逐颗比对，不满足就 `IoError::Bus` 拒绝启动（"checked, not corrected"）：
- `reg6 = 1`（500 kbps）——出厂 0（1Mbps），**必改**。
- `reg33 = 0`（mode 0）——出厂 4，**必改**。
- `reg9/11 = 0/4095`（行程）——出厂已 0/4095，一般不用动。

写入时序（断电→解锁 55=0 等 0.25s→写值等 0.50s→上锁 55=1 等 0.50s→再断电回读，⚠️ 绝不切 mode）：
```bash
python tools/hd1910/servo_probe/hd1910_ident.py baud --port /dev/ttyS3 --id <ID>
python tools/hd1910/servo_probe/hd1910_ident.py mode --port /dev/ttyS3 --id <ID>
```

---

## 7. imu_mount_quat 朝向对齐

- ✅ 已核对：stock `build-tutorial` 的 `constants.py` `IMU_MOUNT_QUAT=(0.7071068,0,0.7071068,0)` 与我们的 `hd1910-calibration.option-a.toml` 的 `imu_mount_quat`（wxyz）**逐位一致** → 复刻线 BNO08x 安装朝向 canonical 对齐。
- **新板做法**：在泰山派部署 toml 里把 `imu_mount_quat` 设为 `(0.7071068, 0.0, 0.0, 0.7071068)`（wxyz），物理上让 IMU 板按 canonical 朝向固定（与现有 Radxa 装法一致）。
- **装后自检**：跑 `live_viewer.py` 的 `imu_mount_sanity`——水平静止时 gravity 应≈ -Z，偏离 >20° 标 ⚠MOUNT?
- ⚠️ **上电姿态 = 参考姿态**：SFLP 参考系是上电那一刻姿态，开机必须让机器人正常站立且静止（`deploy_import_checklist.md` B21）。歪着/躺着开机不会报错但姿态全偏。

---

## 8. 上板自检清单（每条都带负对照）

> 原则：绝不在台架 PC 上断言。所有"总线通/IMU 读到/EEPROM 过"必须烤到泰山派实板跑。

| # | 检查 | 命令 / 期望 | 负对照（怎样算 FAIL 有效） |
|---|---|---|---|
| 1 | 内核 DE 绑定 | `dmesg \| grep "RS485 direction on gpio"` 看到 GPIO 号 | 无日志 = 设备树没绑 GPIO，半双工会错 |
| 2 | 舵机 500k 半双工通 | `servo_probe` 在 `/dev/ttyS3` 能 ping 到 15 颗、回读 reg6=1 | 改错 port（如 ttyS2 不存在）直接全沉默 |
| 3 | EEPROM 四项 | `hd1910_ident.py` 回读 reg6=1/reg33=0/reg9=0/reg11=4095 | 任一不符 → robotd 开机 `IoError::Bus` |
| 4 | robotd 开机校验 | 起 robotd，`robotctl health` bus 绿、loop **50 Hz 0 missed** | 总线不开 / 丢帧 → 查 §3 接线 |
| 5 | IMU 读到 | `robotctl health` 的 `robot.imu` 有数据；`imu_mount_sanity` 不报 ⚠MOUNT? | 读不到 / 朝向偏 >20° |
| 6 | 策略契约（板前可做） | `pre_deploy_check.py --selftest` 全绿（含 `--onnx/--toml` 实跑） | `--selftest` 必须含负对照用例 |
| 7 | 增益标度 | 起 robotd 后回读 reg50 = `round(gain×position_kp/200)`（部署档 = 16） | 读到 1 ⇒ gain 被改成 8；读到 8 ⇒ position_kp 还是 8 |
| 8 | 电池识别 | 至少 ~6.0 V 上电；`cells=[2]` 拦住 3S | 4.6 V 台架电压 → "既不是 2S 也不是 3S" 瘫软 |

---

## 9. 已知风险与待查项（🔴 必须在动手前消解）

### ✅ R1. 软件 RTS 方向 vs 内核 DE gpio 冲突 —— **已查清，无冲突**（2026-11-09 拉源码核实）
- **查证方法**：读 `DuckBuddy-main/duck-control/src/feetech.rs:301` 的 `FeetechIo::open` + 全仓 grep `rs485|TIOCSRS485|TIOCMSET|set_rts|half.?duplex|de_gpio|485|direction`（含 `firmware/` 子仓）+ 拉 `rustypot` 1.6.0 源码（crates.io 锁定 `duck-control/Cargo.toml:33 rustypot="1.6.0"`，实际仓库 `pollen-robotics/rustypot`）读 `src/servo/feetech/sts3215.rs` 与通信层。
- **结论**：
  - `FeetechIo::open` 只是 `serialport::new(port, BAUD_RATE).timeout(READ_TIMEOUT).open()` —— **整个 DuckBuddy-main 仓零用户态 RTS/RS485/方向翻转代码**（`direction` 命中全是视频旋转/UI/坐卧切换，无关）；`rustypot` 1.6.0 的 `Sts3215Controller`（由 `generate_servo!` 宏生成，`sts3215.rs` 只有寄存器表）也**无任何 RS485/RTS 代码**。
  - ⇒ 我们 `feetech_hls` robotd **完全不翻方向脚**，半双工方向 100% 由 **kernel/硬件层**负责。
  - ⇒ 因此 vendored 内核 `485_ctrl_gpio` DE 补丁与 robotd **不存在冲突**（原担心的"双重驱动/方向竞争"证伪）——补丁提供的正是 robotd 依赖却没自己实现的方向控制。
- **⚠️ 但它反过来揭示一个硬前提（升级 §3.2 为必做）**：因为 robotd 自己不提供任何方向控制，**泰山派必须**在 kernel/硬件层把方向做对——即伺服接口必须有收发器、且其 DE/RE 接到 `485_ctrl_gpio`（GPIO3_C4），并打上 §4 内核补丁。若 servo 总线接到了没被 DE 控制的引脚，robotd 会**静默读不到总线**（症状像"舵机坏了/总线打不开"而非配置错）。✅ 利好：立创泰山派 Microduck 载板已把收发器 DE/RE 接到 GPIO3_C4 且内核支持（EasyDuck 能在上面跑即证据），所以**用立创泰山派 Microduck 载板 + 打补丁**，robotd 原样可用、无需改一行方向代码。
- **🔴 顺带纠正之前 SBC 文档的一处错误**：`microduck-SBC选型-泰山派vsRadxa-2026-11-09.md` §3 与 `四板对比` §3.3 写的"半双工方向走串口自身 RTS/RS485，在 `Sts3215Controller` 内"——**被源码证伪**。方向不在 `Sts3215Controller`，在 kernel/硬件。这同时意味着迁移比原先担心的更省事（不用解 RTS 冲突），但更依赖硬件 DE 接线。四板文档里"EasyDuck 的 `scs.rs` 走 RTS"那句同理存疑（补丁源自 EasyDuck，更可能是他们也靠 kernel DE），待核对 `jlckfb/easyduck` 的 `scs.rs` 后修正。

### 🔴 R2. 机构（70×45mm / 98.6g vs Radxa 65×30mm / ~15g）
- 若只把泰山派塞进现有 Radxa 机壳，重心/配重要重评，可能需重训（见 `deploy_import_checklist.md` H12：HOME 是模型站姿不是编码器零位）。
- 若直接采用 EasyDuck 整机（板+机壳+舵机+IMU+镜像），立创已解决机构——但那走的是 scs 分支（与 §1 决策冲突）。

### 🟡 R3. 无线档次
- 泰山派多为 2.4GHz n（未标 ax），robotctl 网络 + `live_viewer --source robotctl` 的 WebRTC relay 延迟/丢包需实测。

### 🟡 R4. 供电
- 泰山派 5V/3A 或 5–18V 宽输入；确认机器人电源树余量（HD-1910 额定 4–8.4 V，robotd 上电至少 ~6.0 V）。

---

## 10. 与现有文档的关系

- `microduck-SBC选型-四板对比-2026-11-09.md` §7/§8：协议分支结论 + 可借鉴清单（A1 补丁 / A2 标定 / A4 配置）。
- `microduck-SBC选型-泰山派vsRadxa-2026-11-09.md` §3/§5：功能覆盖 + 迁移清单。
- `docs/active/microduck-taishanpi-uart3-halfduplex-20261021.patch`：§4 内核补丁源。
- `microduck-software/tools/hd1910/deploy_import_checklist.md`：B 段软件关 + H 段实机关卡（EEPROM 时序、方向、HOME、电池）全适用，本草案是其"换板"子集。
- `out/robotd_hd1910_mode0.toml`：§6 改造基线。

---

## 11. 执行顺序建议（先消 R1 再买板）

1. ✅ **R1 已查清（见 §9）**：robotd 不翻方向脚，方向 100% 在 kernel/硬件层；故**不需要改 robotd 一行方向代码**，直接走下方步骤。
2. 🔴 **确认硬件 DE 接线（§3.2，硬前提）**： servo 总线收发器的 DE/RE **必须**接到 `485_ctrl_gpio` 绑定的 GPIO3_C4（用立创泰山派 Microduck 载板即满足；自接线则查 RK3566 数据手册 + 载板丝印钉死 40-pin 脚位）。这步做错，robotd 静默读不到总线。
3. 取立创镜像，读其 DTS 确认 `485_ctrl_gpio` 已绑 GPIO3_C4（§2）；若镜像内核已含支持 → 跳到 §5；否则走 §4 自编译内核。
4. 改 toml（§6：`port=/dev/ttyS3`、servo/EEPROM/电池不动）+ 对齐 IMU 朝向（§7）。
5. 交叉编译 robotd（§5），拷板（onnx 绝对路径）。
6. 上板跑 §8 自检清单；确认内核 DE 日志 + 总线通 + EEPROM 四项 + robotd health 50Hz 0 missed 后再接真机舵机。
