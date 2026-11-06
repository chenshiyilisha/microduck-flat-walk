# MicroDuck 开源资料全景盘点（2026-11-06）

> 目标：以 **香橙派 Zero 3W（A733）+ 15×HD-1910 + 2S** 定案为坐标，把此前三方对照
> （666wsp / kissqy / DuckBuddy）和 `fanhao375/microduck-replica` 之外的开源资料补齐。
>
> **方法**：GitHub 官方 API（`search/repositories` + `repos` 查 `default_branch`），
> codeload tarball 拉全文，不采信搜索引擎给的仓库名。先找现成语义索引
> （`joeynyc/awesome-microduck`，98 KB `readme.md` + `policies.json`），再按条目逐个核实。
> 本地副本全部在 `microduck-software/.upstream/`（已被 gitignore 覆盖，不入库）。

---

## 0. 先说结论：这轮有 5 处改判

| # | 此前结论 | 改判 | 证据强度 |
|---|---|---|---|
| 1 | 香蕉 PCB / 分线板要自己设计打样（昨晚我画了两张 SVG） | **有现成开源 Gerber + BOM，直接下单即可** | 一手仓库 `production/*.zip`，批量验证 |
| 2 | IMU「排第一 vs 排最后」是固件冲突，只能台架实测 | **根因是两套不同协议**（DXL `0x8A` / 飞特 `0x82`），且有第三条已真机验证的路 | 官方运行时设计文档 + 固件真机报告 |
| 3 | H2「15 颗方向全 −1，实机逐颗核对」 | **证据强度不均**：官方适配版只验过 3 颗，点名 `left_knee` 可疑 | 两份一手资料互相矛盾 |
| 4 | 台架推出来的 EEPROM / P/D / 速度标度结论 | 全部获得**厂商内存表 + 官方运行时源码**背书（有一处措辞要校正） | 厂商手册原文 |
| 5 | 上线关卡 H1–H7 够了 | **缺两条会真机重启的关卡**：上电顺序、volatile P/D 漂移守卫 | 官方 first-light 实测记录 |

**不变的部分**：A733 主控、4GB+eMMC、UART7(pin16/18)@500k、2S PDB、HAT+IMU 一套、
obs61/act14/50Hz、以及「总线只需 500k」的带宽结论——本轮资料**没有**推翻这些。

---

## 1. 新发现的仓库（按与我们方案的相关度排序）

### 1.1 直接改判级

| 仓库 | ★/许可/分支 | 为什么关键 |
|---|---|---|
| **`jyg9/microduck-community-kit`** | 28★ / 根 Apache-2.0，**硬件 CERN-OHL-P** / main | 复刻缺的三块板**全有现成生产文件**：`banana_pcb`、`dxl_hub`、`imu_to_dxl`。三块板各自带 `production/*.zip`（Gerber）+ BOM/位号/坐标表。README 明写「方案已经过批量验证，在原版 XL330 和飞特 HD1910 舵机上，都适配良好」。附 `docs/飞特通讯协议说明.md`（厂商 SCS.cpp/HLSCL.cpp 逐条核对，带逐字节帧示例）与 `firmware/v1/docs/bus_timing_borrow_plan.md`（真机联调报告） |
| **`jyg9/microduck_ft1910`** | 0★ / Apache-2.0 / main | **官方 `pollen-robotics/microduck` 0.16.0 的飞特适配 fork**，`docs/design/scs-bus.md` 是整条 SCS/HLS 后端的设计文档。2026-10-06 在 Radxa Zero 3W / `/dev/ttyS2` @ **1 Mbaud** 完成 first light：15 舵机 + ID200 节点一次事务全应答、50.0/50.0 Hz、0 missed / 436 ticks、8.22 V、33 °C |
| **`Juxi-Technology/imu-displace-microduck`** | 1★ / Apache-2.0 / main | 官方 `microduck@648bf22` 的 I²C IMU 替换参考（ICM-42670-P），**专为 HD-1910**。核心洞察：把 IMU 挪下总线可**分开故障域**（原来 IMU 不答会让整笔 sync_read 作废、15 颗一起丢数据）。⚠️ 状态诚实：数据链已真机验证（99.4 Hz / 0 丢帧 / 0.92 ms），**`robotd` 运行时未接线**，不能拿它直接走路 |

### 1.2 强补充级

| 仓库 | 许可 | 补我们哪个缺口 |
|---|---|---|
| `joeynyc/awesome-microduck` | CC0-1.0 | 98 KB 语义索引 + `policies.json`（策略清单）。本轮所有新线索出自它 §394–442 |
| `avanx/microduck_imu_to_ttl` | Apache-2.0 / **master** | **第四家 `imu_to_dxl` 板**，立创 OSHWHub 可直接打样。给出了我们一直没查到的**硬件方向控制实现**：`SN74LVC2G241` 半双工收发 + TVS/PTC 保护；供电 HT7533(3V3) + SGM2036-1.8(IMU 1V8)；MCU↔LSM6DSV16X 走 **SPI+INT**；带躯干 IMU 安装朝向推理 |
| `MHDuck/microduck` | Apache-2.0 / master | HD-1910 + **I²C BNO085** + Radxa Zero 3W 的完整 runtime fork（含 build/deploy/gamepad 文档 + 配套训练仓），比 imu-displace 更完整 |
| `Ley-WL/microduck-rl` | Apache-2.0 / main | HD-1910 的 mjlab 适配 + 已发表 1910 M6 执行器参数，可与我们 `hd1910_ftservo_m6` plant 对照。2026-11-05 仍在更新 |
| `lumimoon-robotics/microduck-lumi` | 本地 LICENSE = Apache-2.0（API 显示 NOASSERTION） | **Radxa Zero 3W + 双供电路线**：调试期 7.5V/3A 桌面适配器、整机期 2S 18650（3400 mAh + 5A 保险）。⚠️ 硬约束：主控 5V 必须独立 DC-DC，**不能与舵机 7.5V 共正极**；舵机大电流禁止走 URT-2 的 5A 通路 |
| `Shiyao-Huang/ChinaMicroDuck` | 许可未标 | 四条制造路线成本对比 + **官方资产复用许可审计**（我们一直含糊的许可问题） |

### 1.3 现成工具（对应我们 checklist H 段）

| 仓库 | 许可 | 对应 |
|---|---|---|
| `janauto/microduck-calibration-guide` | MIT | **只读**关节方向检查（搬动关节、看编码器变化，从不给舵机发命令）→ 正是 H2 缺的工具 |
| `Ley-WL/microduck-observer` | Apache-2.0 | 只读 Web 仪表盘：BNO085 姿态 + 15 颗 HD-1910 + **shadow ONNX 推理**，从不发运动命令 → 适合 H6 台架观测 |
| `JieJie-H/microduck-servo-numbering` | 代码 MIT / 3D 模型 NC | 逐颗扫描、写、回读舵机 ID |
| `lxm/microduck-maker`、`jackwuwei/microduck-tools` | MIT / Apache-2.0 | 逐关节零位标定、备份恢复、校准托盘 |
| `7757/fanduck` | 许可逐项标注 | 成品复刻 + BOM/板件/打印件 maker pack |

### 1.4 警示类（不抄，但要记住）

- `CMU MicroDuck`：Radxa Cubie A7Z，官方策略 0.25 m/s，但**过热把控制环拖到 ~40 Hz 后步态发散** → A733 八核上板必须测散热与 50 Hz 稳态。
- `Dukki`：作者称有「head-IMU 温度 bug」也影响 Pollen 官方机器人 → 又一条 IMU 温度坑，我们目前只观测温度不判。
- `RDK X5 MicroDuck`：HD1910M 实机短走，但**回放录制舵机目标**而非完整策略，不算 sim2real 验证。

---

## 2. 改判 1：供电板不用自己画了（推翻我昨晚的结论）

我昨晚画了 `microduck-供电接线图.svg` + `microduck-分线板设计图.svg`，并写「整机只剩分线板这一块躲不掉打样」。
**这个判断被 `community-kit` 直接推翻**：人家三块板的 KiCad 9 工程 + Gerber 都在，而且批量验证过。

| 板 | 现成文件路径 | 关键规格（一手 README） |
|---|---|---|
| `banana_pcb` | `hardware/banana_pcb/production/banana_pcb.zip`（Gerber）；`.kicad_pcb/.kicad_sch` | 2.5 mm 香蕉头 PCB 连接器 **13 mm、尾部 1.5 mm，参考型号 U6068**；引出导线**正常运行电流 3–5 A** |
| `dxl_hub` | `hardware/dxl_hub/production/dxl_hub_v0.3_gerber_1p.zip` | 「电力与数据分发板」；**飞特 1910 用 `AMP175778/8283/A2007WV-3P` 立式**，XL330 用 `B3B-EH-A(LF)(SN)`，二选一焊接；3 个焊背面（两腿+IMU）、1 个正面（脖子） |
| `imu_to_dxl` | `hardware/imu_to_dxl/production/imu_to_dxl_v1.0.0_10p_gerber.zip` + `bom.csv` + `positions.csv` + `netlist.ipc` | GD32F303CC，LSM6DSV16X，固件可在线升级（A/B slot） |

**许可**：三块板各自 `LICENCE.txt` = **CERN-OHL-P（宽松）**，可制造/修改/商用，只需保留 Notice；仓库软件 Apache-2.0。
比 kissqy 的「原创部分个人非商业」宽松得多。

**拓扑差异（⚠️ 这一条是按 README 推的，未解析 `.kicad_pcb` 原理图）**：
`dxl_hub` 是 **4 个分支**（两腿 + IMU + 脖子），每支内部再串接舵机，不是我昨晚画的「16 路 AMP2.0 全并联」；
banana→hub 那段只按 3–5 A 设计，而我按 10 A 母线 / 30 A 堵转画。**两者都能供电，但现成方案是有实机背书的折中拓扑**，
我那两张图应降级为「自绘备用参考」，下单优先走现成 Gerber。

> 顺带修正此前说法：「kissqy 有香蕉插头母座焊盘」只是买焊盘；`community-kit` 给的是**整块板**。
> 用户提供的那条信息（未独立核实）现在不再是必需项。

---

## 3. 改判 2：IMU 同步读顺序冲突的根因 = 两套协议

此前三方对照把「666wsp/kissqy 要求 IMU 排第一」vs「DuckBuddy 硬编码排最后」当成固件口味冲突。
**`ft1910/docs/design/scs-bus.md` + `community-kit` 固件报告说明，这是两条不同的协议路径**：

| | **Dynamixel 路线** | **飞特 SCS/HLS 路线** |
|---|---|---|
| 同步读指令 | `0x8A` **Fast Sync Read**（聚合帧，CRC-16 累积） | `0x82` SYNC_READ（每设备各回一帧） |
| 读取地址/长度 | addr **124** / **12 B** | addr **56** / **15 B**（文档化块 56..70） |
| IMU 位次 | **第 0 位**（官方运行时 tick 读 `[200] + 15 关节`） | 也是**第一位**，因为「协议让每个设备按列表位置对应的槽应答」 |
| 让位规则 | 按**前面 k 段的字节数**让位（`8 + k×(X+4)`） | 按**槽**让位，实测 **≈295 µs/槽**，且**前导设备缺席也照样占一槽** |
| 波特率 | 1 Mbaud（ft1910 first light，RK3566 `/dev/ttyS2`） | 1 Mbaud（community-kit 实测，reg6=0） |
| 我们的 A733 | — | DuckBuddy 走 **500k**（reg6=1），因 UART7 上不了真 1M |

**所以我们之前那个「死结」其实是三件事被混成一件事**：
1. **协议不同**：`0x8A` 与 `0x82` 的让位算法根本不一样（D10 明确：按槽让位在 `0x8A` 下必撞包）。
2. **波特率不同**：官方/社区飞特版是 1M，DuckBuddy 因 A733 限制降到 500k。
3. **固件实现不同**：`community-kit` 的 GD32F303CC 固件 **D2 + D10 两套都实现**，真机验证过三种位次
   （§7.8：第 0 位 / 第 1 位 / 未被点名静默，19 项全过），所以**它的板能放在任意位次**。

→ 这给了第四条路，比「改 robotd 排队位」或「刷 DuckBuddy 固件」都省事：**用 community-kit 的 `imu_to_dxl` 板**，
它的固件已经把两套协议的位次仲裁都做完了。代价是它跑 1M，A733 上要把总线整体降到 500k 并确认固件支持
（**未核实**：`community-kit` 固件是否支持 500k 档；其协议文档 reg6 编码表列了 1=500k，但固件波特率是否可配未在本次读到）。

**顺带一个同源观察（这是推的，未找到直接引用）**：666wsp 的 15 字节布局
（byte12=sequence / 13=status / 14=reserved）与 community-kit 的 15 字节「契约块」
（byte12=采样计数 / 13=状态位 / 14=0）**结构一致、状态位 bit 定义不同**；而
`community-kit` 的 `bus_timing_borrow_plan.md` 明写外部依据来自 `fanhao375/microduck-replica` 的
`总线协议.md`。三方很可能同源于 replica 那条线，不是独立设计。

**还有一个真机 bug 值得记进 H6**：`community-kit` §7.8 抓到「USART 接收中断里按位 CRC-16 耗时 11–20 µs，
超过 1M 下一个字节的 10 µs，紧跟的字节被覆盖」→ **任何「紧跟指令帧发言」的设备都会被吃掉首字节**。
这类时序 bug 在 500k 下字节时间翻倍到 20 µs，风险更小，但仍是台架要留意的形状。

---

## 4. 改判 3：H2「15 颗全 −1」的证据强度要降级

两份一手资料对不上：

| 来源 | 说法 |
|---|---|
| `fanhao375/microduck-replica` `tools/servo-web/directions.json` | 15 颗**全部 −1**（我们 H2 写成「实机逐颗核对」） |
| `jyg9/microduck_ft1910` `docs/design/scs-bus.md` §Commissioning | `direction` 是**单一 `-1`**，但只把 3 个关节
（`left_hip_pitch` / `left_ankle` / `right_ankle`）用手转过 + 两个脚踝过了镜像检查；**「Eleven joints were never watched」**，
并**点名 `left_knee` 最可疑**（模型轴 −Y，而 hip/ankle 是 +Y）。文档原话：`direction is the one field it cannot measure — a sign is not visible in a position` |

→ 结论：**「全 −1」是社区共识值，不是逐颗实测值**。它大概率对（两家都能走），但
「从没看过的 11 颗」正是那种「所有电气检查都通过、症状只是往错方向倒」的静默 bug 形状
（对照 `imu-displace` 的 mount 警告：装歪 90° 时所有电气检查都通过）。

**H2 应改成**：上板用**只读**方向检查逐颗验 —— 现成工具
`janauto/microduck-calibration-guide`（MIT，HD-1910 专用，搬动关节看编码器变化，从不给舵机发命令），
重点先查 `left_knee`。这比「照抄 15 个 −1」稳。

---

## 5. 改判 4：台架推断获得厂商手册 / 官方源码背书

`community-kit/docs/飞特通讯协议说明.md` §5 是**飞特官网《磁编码 HLS 舵机-内存表解析》**逐条抄录，
`ft1910/docs/design/scs-bus.md` 是官方运行时设计文档。我们此前靠台架实测推出的结论逐项对上：

| 我们记忆/checklist 里的结论 | 现在的一手依据 | 判定 |
|---|---|---|
| 速度标度 **0.732 rpm/count** | reg46 运行速度，单位 **0.732 RPM** | ✅ 厂商手册背书 |
| EEPROM 21/22 → RAM 50/51（P/D 环） | reg21/22/23 明写「**上电赋值给 50/51/52**」；ft1910 实测写 50/51=99/88 → `0x08` reboot 回 32/40 | ✅ 且补上了 reboot 触发 |
| **reg50 = clamp(gain × position_kp / 200)** 是第二写者 | ft1910：策略 `gain`（200 nominal / 50 limp）是 **XL330 数值，必须缩放到飞特 profile**，直接要 P=200 等于出厂值 20 倍 | ✅ 机制说明补齐 |
| EEPROM 时序：解锁 55=0 → 写 → 上锁 55=1 → 断电回读 | reg55 明写「**写 0 = 关闭写入锁，写 EPROM 的值掉电保存；写 1 = 打开写入锁，写 EPROM 的值掉电不保存**」，出厂默认 1；ft1910：「**锁着的舵机接受写入到 RAM 且静默不持久化，没回读的调用会报成功**」 | ✅ **「回读 PASS ≠ 持久 PASS」的机制找到了** |
| 校零须走 `0x0B`（写 128 不生效） | 指令表 `0x0B = CAL 中位校准（写入 OFS）` | ✅ |
| 行程 reg9/11 = 0/4095 物理无效 | ft1910 first light：15 颗 travel window 全是 `0..4095`，「钳位从不生效，因为没人设过 MIN/MAX」 | ✅ |
| CENTER=2048 / 方向位 | reg31 位置偏移 **BIT15 为方向位**；ft1910 `scs_commission` 双路径交叉验证 `zero_ticks=2048` + `direction=-1` | ✅ |
| reg6=1 是 500k | 波特率编码表 **0=1M, 1=500k, 2=250k …** | ✅ 也解释了三方分歧（官方飞特版 reg6=0） |
| 台架 4.6 V 欠压读数要重测 | reg15 最低输入电压 **40 = 4.0 V**；community-kit 实测母线 4.4 V 是「USB 供电能力不足，已知且临时，后续提高到 7 V 以上」 | ✅ 欠压判断成立 |

**一处措辞要校正**：我们记忆写「上锁 55=1」，手册语义是「**打开写入锁 ⇒ 写入不持久化**」；
数值操作没错（结束时回到 1），但「上锁」容易被理解成「保护已写入的值」，实际是**关掉持久化**。
另外 `community-kit` 的 IMU 节点**故意把 55 默认取 0**（手册是 1）以便主机改 ID/波特率直接存 —— 又一个
「有意偏离上游默认」的例子，和我们 `[bus] imu_median=false` 同类。

---

## 6. 改判 5：上线关卡缺两条（都会真机重启）

来自 `ft1910/docs/design/scs-bus.md` 的 first-light 实测，我们 H1–H7 没有：

**H8 · 上电顺序（最硬的一条）**
> 「给 goal 寄存器还留着旧目标的舵机上扭矩，会同时驱动所有关节；15 颗 × 最多 26° 误差的
> inrush 触发板子欠压锁定 —— **8 分钟内 4 次 SBC 重启**。」
→ `set_torque(true)` 必须 **先写机器人当前姿态到 goal → 回读验证 → 再上扭矩**，且封装在一次调用里，
不能靠调用方约定。扭矩关闭是一次广播写 + 回读，不肯释放的舵机要报错而不是静默 relax。
→ 另有一条相关坑：**`sync_write` 写 reg40 与写 reg50 行为不同**，reg40 回读立刻是 0（造成假的释放成功），
必须改成**逐台带 ACK 的 WRITE**（bring-up/relax 各 15 次往返）。这给我们台架「mode=4 下 reg40 关不掉扭矩」
提供了另一种解释：可能不只是 mode，而是 sync_write 语义。

**H9 · volatile P/D 漂移守卫**
50/51 是 RAM，`0x08` reboot 会从 21/22 重载。运行时三道防线：
① `set_torque` 上电前写 profile 并回读，不通过就拒绝使能；
② `slow_sensors` 每秒读 50..63（顺带看增益 + 包电压 + 壳温），比对 15 颗，漂移就重写并响亮报错；
③ `reboot` 清 verified flag，下次 bring-up 重写。
**EEPROM 永不自动写**（写错就是每次开机都猛冲，且中断的 EEPROM 写会让舵机不可用），只提供
`scs_commission --persist-gains` 显式四步：读锁→清锁→写 21/22→**回读**→恢复锁，且使能状态下拒绝执行。

**H10（建议）· 方向逐颗只读验证**：见 §4，工具 `janauto/microduck-calibration-guide`。

---

## 7. 软件栈多了一个正经备选

此前定案用 **DuckBuddy B 代 robotd**（因为它是 HL-2915 实机验证、我们审了它的 TOML R1–R29）。
现在多一个 **`jyg9/microduck_ft1910`：官方 0.16.0 + 飞特 SCS/HLS 后端**，与 HD-1910 更对口：

```toml
[bus]
scs = true
scs_config = "/etc/robot/scs.json"     # deny_unknown_fields；两个键不一致 Params::validate 直接拒
```
```jsonc
{ "imu_id": 200, "imu_mount": [1,0,0,0], "baud_rate": 1000000,
  "servo_pd": { "kp": 6, "kd": 20, "mouth_kp": 10 },
  "joints": [ { "zero_ticks": 2236, "direction": -1 } /* …15, wire order */ ] }
```

**优点**：同一 `RobotIo` trait，上层控制环/观测/策略/安全完全不变；`scs.json` 独立存放 15 个**实测**
编码器零位（避免 `robotctl configure` 逐键编辑改坏）；有 `scs_commission` 只读台架程序；33 项字节级单测；
first light 已跑通 50 Hz。**风险**：first light 明确写「**还没有驱动过任何动作**」（只做了 bring-up、
保持、增益守卫），且**11 个关节方向未验证**；`servo_pd` 6/20 是「两个独立 fork 都走通」的经验值，
文档自己说「是证据不是证明，未在本机器人上测量」。

⚠️ **`servo_pd` 与仿真 `kp_fw` 必须成对改** —— 这句和我们「plant 是一等坐标、换 plant 必须重训」
是同一条纪律，但方向相反：它说的是**部署侧硬件增益与训练侧 plant 参数要一致**。我们的 `kp_fw=8`
是训练侧 plant，不能直接和 6/20 比；跨链数字不可混用。

**我的判断**：**暂不切换主栈**。理由：① 我们 R1–R29 全部审计针对 B 代 TOML，切栈等于审计作废；
② ft1910 还没跑过策略；③ 但 `scs-bus.md` 里的**上电顺序 / volatile P/D / 方向证据强度**这些
硬件事实与本轮手册背书，与用哪个栈无关，应立刻吸收进 checklist。
若后续 15 颗到货后在 B 代栈上反复撞供电/增益问题，ft1910 是第一顺位的对照实现。

---

## 8. 未核实 / 待办

| 项 | 状态 |
|---|---|
| `community-kit` 的 Gerber 是否适配 **2S 8.4 V** 与 A733 HAT 物理尺寸 | 未核实（README 只说 XL330/HD1910 批量验证，未提电压档与主控型号）；下单前需看 `.kicad_sch` 电源部分 |
| `community-kit` IMU 固件是否支持 **500k**（A733 上限） | 未核实；协议文档给了 reg6 编码表，但固件波特率可配性没读到 |
| `dxl_hub` 实际拓扑（4 分支 vs 全并联）、铜箔载流 | **按 README 推的**，未解析 `.kicad_pcb`；若直接用现成 Gerber 则不必自己校核 |
| 666wsp 与 community-kit 15 字节布局同源 | **推的**，只找到 community-kit 引用 replica 的间接证据 |
| `ft1910` first light 文档里「21-byte block at 56」与正文「每设备答 15 字节」不一致 | 内部矛盾，先记录不下结论（§1.2 实测 12/15/20/21 字节读都 OK） |
| kissqy 淘宝商品页、香蕉母座焊盘 | 仍需登录，未能独立核实（现已非必需） |
| `MHDuck/microduck`、`Ley-WL/microduck-observer`（115/195 MB） | 只核了元信息，未下载全文 |

---

## 9. 下单与执行建议（按优先级）

1. **供电板改走现成 Gerber**：`community-kit/hardware/{banana_pcb,dxl_hub,imu_to_dxl}/production/*.zip`
   发嘉立创；`dxl_hub` 焊接时选 **飞特 1910 用的 `AMP175778/8283/A2007WV-3P` 立式**；
   banana 用 **U6068 2.5mm 香蕉头 PCB 连接器**。CERN-OHL-P 可制造。
   我们那两张 SVG 降级为自绘备用参考。
2. **checklist 补 H8/H9/H10**，H2 改为「共识值 + 只读逐颗验证」。
3. **H6 判据脚本补一条**：除 SFLP 姿态跳变外，也检查 `status` 位与 `sequence` 是否推进
   （community-kit / 666wsp 的 byte12/13 都带这两个字段，我们目前在 DuckBuddy 链上完全没读）。
4. **IMU 板多一个更优候选**：`community-kit imu_to_dxl`（固件已把 `0x82`/`0x8A` 两套位次仲裁做完、
   可在线升级、CERN-OHL-P）或 `avanx/microduck_imu_to_ttl`（Apache-2.0、立创直接打样）。
   两者都比「666wsp 改 FD.exe + 改 robotd」省事；kissqy 成品仍是「到手即用」选项。
5. **散热**：A733 上板必测 50 Hz 稳态（CMU 项目 40 Hz 步态发散是先例）。
