# microduck-replica 借鉴参考（HD-1910 实机复刻）

日期 2026-11-05。对象：[`fanhao375/microduck-replica`](https://github.com/fanhao375/microduck-replica)
（1581 star，默认分支 `master`，已下载到 `microduck-software/.upstream/replica/`）。

**一句话**：这是目前网上唯一把 **飞特 HD-1910 整机跑到实机行走 + 前滚翻起身** 的开源复刻项目
（2026-10-24 实测录像），和我们同舵机、同训练框架（mjlab/BAM）、同 61 维观测/14 维动作接口。
不是简单"参考"，是**我们这条路上走得最远的先例**，值得逐条对照吸收。

## 0. 与我们的关键差异（先看这个）

| | 我们 | replica |
|---|---|---|
| 主控 | 已定 **香橙派 Zero 3W（A733）** | **Radxa Zero 3W（RK3566）+ Armbian** |
| 舵机参数 | **飞特官方 m6**（`ftservo/ftservo-bam`，`apply_to_live.py --plant hd1910_ftservo_m6`） | **LuwuDynamics 公开 1910 M6**（`xgoduck_rl` 提交 `326d77a`） |
| 训练配方 | kp_fw=8（部署档）/ kp5（备选） | kp_fw=5，vin 7.4–8.0，延迟 3–6 步 |
| IMU | 总线 ID 200（feetech.rs 排最后，500k） | FT6 固件 + DXL2 兼容自动识别（20261023c）；部分机器用 I2C BNO085 |
| 进度 | 台架单颗验证（poses 11/15） | 整机站立/行走/翻滚起身全跑通 |

**参数来源上我们领先一步**：replica 在 `HD-1910-M6参数来源.md` 里明确写「把飞特官方参数接进
训练工程的方案审过一轮，**还没做**」，而我们已经用官方 m6 建了 plant。他们那份文档里的
**陆吾 M6 vs 飞特 m6 对比表**（下 §3）对我们核对自己的参数仍是重要参照。

---

## 1. HD-1910 实机已验证的配置（可直接抄作业）

来自 `踩坑记录.md` 汇总（都是 10-11～10-15 真机实测）：

| 项 | 已验证值 | 出处 |
|---|---|---|
| 舵机 ID 分配 | 左腿 20–24 / 颈头嘴 30–34 / 右腿 10–14 / IMU 200 | `硬件规格速查.md` |
| 行走用增益 | **P5 / D0 / 转矩 1000**（kissqy V167 默认）；后调 **P3 / D0 / 转矩 700** | 踩坑记录「舵机的 D 跟走路发颤」 |
| 行走不摔配置 | 动作缩放 0.9、头滤波 0.5、腿滤波 0.7（**不在 robotd.toml**，在模型包 `deployment-execution.json`） | 踩坑记录「联合模型的缩放和滤波」 |
| 整机重量 | 806 g（训练模型 820 g）vs XL330 版 737 g | 10-15 记录 §2.1 |
| 电池 | **NP-F550**（2S，6.6–8.2 V 带载），**不是 NP-F970** | 踩坑记录「买东西」 |
| 满电电压 | 8.4 V = HD-1910 电压上限，**零余量**；上机建议 8.0 V 留余量 | 踩坑记录 |
| 供电 | 15 舵机峰值电流大：**10 A 电源或 2S 电池**，16–18 AWG 线，XT30/XT60，输入并 1000–2200 µF | 踩坑记录「整机掉电是供电」 |

## 2. HD-1910 特性坑（台架/上机都会遇到）

来自 `docs/HD-1910训练前数据清单.md` + 踩坑记录：

- **位置计数方向与 XL330 相反**：15 颗全反 → `directions` 全取 −1（replica 用
  `microduck-software/tools/servo-web/directions.json`，robotd 里 `[bus.feetech] directions`）。我们
  `feetech.rs` 的 joint_signs 就是干这件事的。
- **不认「扭矩写 128」中位校准**：固件 3.46（HLS ≥3.43）不支持，回「成功」但偏移不变 →
  必须走 **0x0B 位置校准指令**，校完回读确认（飞特很多不支持的操作照样回成功）。
- **校准时别关扭矩等**：关扭矩后关节被重力压下（颈部 7°），等得越久掉越多。
- **FD 调试软件**：先装 URT-2 驱动 → 波特率选 **1 Mbps**（出厂默认）→ 型号显示 unknown
  是正常的（寄存器读写正常）。
- **URT-2 上电顺序**：先插 USB、后给舵机上电；反了总线 S–G 被压到 2.1 V，全不应答。
- **P/D/转矩写在 RAM**：断电回出厂值（HD-1910 出厂 EEPROM **P32 / D40 / I0**、转矩 1000）；
  上力时写、卸力恢复。上力状态下重启 robotd 会把残留测试值当原值记下。
- **HD-1910 规格书核心值**（A/0）：4–8.4 V、4096 counts、320:1、回差 ≤0.5°、
  空载 113 RPM @7.4V、堵转 1.47 N·m @7.4V、模式 4（纯位置 PD）默认。
- **脚线序**：1=Signal 2=Vcc 3=GND（与 Dynamixel 相反）；AMP2.0-3P 间距 2.0 mm。

## 3. M6 参数对比（replica 整理的陆吾 vs 飞特官方）

`docs/HD-1910-M6参数来源.md` 的表格（前五行按 BAM 公式推算，后面是 JSON 原值）：

| | 陆吾 1910 M6 | 飞特 HD-1910 m6 |
|---|---|---|
| 控制模型 | 借 STS3215（0.166×1.32） | 专门 HD1910（0.163） |
| 每 rad 误差每单位 P 的占空比 | 0.219 | 0.163 |
| P=5 时饱和误差 | 0.88 rad | 1.19 rad |
| 7.4 V 堵转力矩 | 0.91 N·m | 1.37 N·m |
| 静刚度（P=5） | 1.03 N·m/rad | 1.15 N·m/rad |
| 电机电阻 R | 4.91 Ω | 2.97 Ω |
| 指令延迟 | 6.0 ms | 1.0 ms |

飞特官方接入注意（他们审过但没做的三条，我们做官方 m6 时要核对）：
1. `actuator` 键大小写（`"hd1910"` vs 注册表 `"HD1910"`）KeyError；
2. 换算系数 0.163（飞特）vs 0.166（STS3215），借 sts3215 模型时要 `error_gain_ratio≈0.98193`；
3. `record.py` 只写 P（地址 50），出厂 D=40 的阻尼可能被拟合进摩擦参数（推测）——
   **我们部署档用 kp_fw=8、D 保持默认 200/8 的寄存器组合，这条对我们有参考价值**。

## 4. IMU 相关（与我们审查直接相关）

- **20261023c 起支持总线 IMU 自动识别**：`[bus] imu_protocol = "auto"/"feetech"/"dxl2"`，
  FT6/兼容 IMU-to-DXL Fieetech 固件走 56/15 块，DXL2 走 124/12 SFLP 块；只读共同 12 字节，
  对方 @136 的 8 字节诊断没接。身份字节 `d8 27 01`（model 10200、fw 1）。
  → 印证我们 `IMU_BLOCK_LEN=12` 只消费前 12 字节的设计，以及 666wsp 板 status/sequence
  被忽略的现状（他们也一样不读）。
- **BNO085 芯片自身姿态乱跳**（走路时 20ms 跳 20–60°，陀螺说只转 1–2°）是「走两三步就摔」
  的根因；修法是 robotd 里用陀螺自积分 + 芯片姿态慢跟（`[trunk_imu] bno08x_fusion="gyro"`）。
  → 我们总线 IMU 是 LSM6DSV16X SFLP，芯片侧姿态是硬件融合，是否也有类似落脚冲击乱跳
  **尚未实测**，这是上台架后第一个要查的量（自洽检查：陀螺外推 vs 芯片姿态差 >5° 即撒谎）。
- **IMU 装歪 8.5°** 会让模型接管后猛冲：校准方法是站 HOME 后把真机关节角放进仿真算
  真实倾角，与 IMU 读数相减补进安装四元数（`microduck-software/tools/radxa/onboard-analysis/`）。

## 5. 硬件/系统层坑（部分与我们选型相关）

- **Radxa Zero 3W V1.12（AIC8800）引导坑**：Armbian 自带引导起不来，要换瑞莎 U-Boot +
  从 B1 镜像拿 DTB；overlay 写 `extlinux.conf` 的 `fdtoverlays`（armbianEnv.txt 不生效）。
  → **这些是 RK3566-specific，A733 不适用**，但我们走 Armbian/香橙派时会有同类坑，
  关注他们做卡脚本（`microduck-software/tools/radxa/build-armbian-card.sh`）的思路。
- **UART2 被 agetty 占**：`systemctl mask serial-getty@ttyS2`（Armbian 默认在舵机串口上跑登录台）。
- **主板散热**：机身内无风道，RK3566 85°C 降频到 408 MHz → 控制周期从 20ms 变 25ms；
  没接摄像头时 mediad/tofd 崩溃循环烧 CPU。→ A733 主频更高但同样要注意。
- **供电压降**：走路/站起时整机掉电重启的案例多次出现，最终结论是供电不是软件；
  可调电源的线要短要粗（8V 输出到舵机端掉 1V）。
- **转向弱**（肉转只有指令的 1/4，关节只跟到一半）——截至 10-15 未解决，他们列为待办。
- **脚底摩擦**：TPU 95A 偏硬；训练摩擦下限 0.7（35° 斜板）；太滑会变碎步（仿真结论）。

## 6. 工具链值得看的文件（replica 仓库内）

| 路径 | 内容 |
|---|---|
| `microduck-software/tools/servo-web/` | 舵机网页调试（DXL2/feetech 双协议、的方向核对、读寄存器），有 selftest 和 poses |
| `microduck-software/tools/radxa/onboard-analysis/` | 上机分析：`duck_rec.py`（每秒 fsync 录像）、`judge_block.py`、`ab_blocks.py`、`imu_fault_ctx.py`、`imu_tilt_check.py` |
| `microduck-software/tools/gait-analysis/` | `foot_clear.py`（离地间隙）、`home_roll.py`（站姿不共面分析）、`stance_pitch.py` |
| `software/training/src/mjlab_microduck/tasks/microduck_hd1910_env_cfg.py` | HD1910 训练环境（Luwu 参数版），与我们 env_cfg 结构同源 |
| `software/image/tests/fixtures/etc/robot/feetech-ft5/robotd.toml` | 飞特版 robotd 配置样例（`feetech-ft5` 段） |
| `hardware/imu_to_dxl/` | IMU 板工程（STM32G031 + LSM6DSV16X，DXL2 从机），含 VALIDATION.md |
| `docs/HD-1910训练前数据清单.md` | 几何/质量/惯量/关节表全填版（含出处标注）——**我们写同类清单可直接对照** |
| `docs/硬件方案逆向.md` | 从 Rust 源码逆向的完整电控方案推导 |

## 7. 我们不该照抄的部分

1. **Radxa/RK3566 专属**：设备树 overlay、armbianEnv、瑞莎引导——A733 全不同。
2. **kissqy 镜像/机器人身份**：他们的镜像预装样机标定（零位 1372–2176），上来要先换自己的。
3. **他们的 robotd 只认总线 IMU 小板**（control.40/43 ），用 IMU 模块的会卡「Feetech ID 200 无应答」——
   我们 DuckBuddy 系 robotd 的 IMU 读取方式与他们不同，别混用配置。
4. **BAM 版本**：他们锁 `62bd8ce`，飞特 `q_target_smooth` 初始化 bug 他们修过
   （`actuator/feetech_bam.py`）——我们若遇到同类 AttributeError 直接看他们的修法。

## 8. 对我们的行动建议（按优先级）

1. **台架第一项**：用 `hd1910_ident.py` 的自洽检查（陀螺外推 vs 芯片姿态差）查我们总线 IMU
   在冲击下是否乱跳——replica 证明这是「走两三步就摔」类问题的头号根因，且纯软件可修。
2. **核对官方 m6 接入三条**（键名大小写、0.163 系数、D 是否被拟合进摩擦）。
3. **上机清单**对照 `HD-1910训练前数据清单.md`：我们已有 poses 实测，可补他们「动态数据」
   部分（阶跃响应、回差 ±1°、足底摩擦斜板法——这些现在就能做，零成本）。
4. **供电设计**按他们验证过的：电池或 10A 源、16–18AWG、XT60、并电容；HAT 侧别忘保险丝。
5. **别重训的理由再确认一次**：他们用 Luwu M6 训出来的模型上机只差 IMU，说明参数差异
   不是成败关键——与我们「heading 奖励 A/B 判 no decision」的结论方向一致。

---

**数据来源**：replica 仓库 `README.md`、`docs/HD-1910-M6参数来源.md`、
`docs/HD-1910训练前数据清单.md`、`docs/硬件规格速查.md`、`docs/执行器选型.md`、
`docs/HD1910-20261015-IMU乱跳根因与陀螺融合上机.md`、`docs/HD1910-20261023-总线IMU自动识别.md`、
`踩坑记录.md`、`software/training/docs/hd1910-baseline.md`（2026-11-05 本地全文阅读）。
