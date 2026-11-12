# MicroDuck 主板到货 · 上板执行单（照着做）

_2026-11-12。用户已下单 Radxa Zero 3W 1GB（SSOT 订正⑫）+ 整机物料在路上。本文把散在 `Radxa上电验收清单`、`board_acceptance_contract.json`(25 条)、`board_capture.py`(B7)、`stage0_software_prep.md`、B2/B8 契约里的判据，串成一份**按时间顺序、带安全前置、带证据落位**的执行单。到货当天从上往下划，不跳步。_

> **口径（先读，别跳过）**
> - 这是**人照着做的操作单**，不是自动脚本。所有采集器（`board_acceptance.py` / `board_capture.py` / `check_image_pairing.py` / `reproducible_card.py`）**不执行任何命令、不开串口、不碰网络**；命令栏是给人看的，不是 shell 输入。
> - **`COLLECTED != PASS`**：`--record` 只存观察值 + 证据文件 sha256，永不自动判 PASS。是否闭合由 `closure_contract.json` 的 `signoff` **人工签署**。全单跑完，`ship_verdict` 仍是 `NOT_SHIPPABLE`，直到 7 条 `INCONCLUSIVE_*` 全闭 + 人工签字。
> - **主板 ≠ 整机**：里程碑 ① ② 做完，A2 悬案闭合数 **仍是 0**。只有里程碑 ③（15 舵机 + 电池 + 装配）才可能动悬案。
> - 2026-11-12 已对本单所有采集器做 Dry-run：B1 `--check` PASS(25 条)/`--selftest` 30/30/`--ship-gate` rc=1、B2 `--verify-sources` PASS、B7 `--check` PASS、B8 flag 审计符合预期、`--record` 真写 COLLECTED 且 ship 不假绿。**工具到货即用，无需临时补代码。**

---

## 0. 三个先导静默阻塞（到货前就能解除，别等插上电才发现）

这三项当前是"结构已备、实体未到手"，会卡住对应步骤。按优先级在**到货前**处理：

| # | 阻塞 | 卡住哪步 | 现状 | 解除动作 | owner |
|---|---|---|---|---|---|
| **P0-1** | ~~kissqy R1 镜像 `.img.xz` 未本地下载~~ **已下载+本机实算（2026-11-12）** | ① 做卡 | ✅ 本机有 R1 实体（`.upstream/downloads/`，gitignored），sha256 与 GitHub 官方 digest / fanhao 脚本 / contract 三源对账；详见 `microduck-底座产物下载与本机实算sha-P0预处理-2026-11-12.md` §3。contract `pin_kind` 按 distributable 语义仍 `UPSTREAM_PUBLISHED`（不冒充 clone 方有文件） | 到货当天 `local_evidence.py --verify` 复核一次即可做卡 | 已完成 |
| **P0-2** | ~~V167 中控 ZIP 未下载、control.43 `UNOBTAINABLE`~~ **已下载+固件包实算（2026-11-12）** | ② control.43 升级 (`BA-X-1`)、③ 策略加载 (`BA-7-2`) | ✅ V167 ZIP 本机实算 `7e2d70ba…`（git blob SHA-1 双算互证）；control.43 固件包从 ZIP 内抽出实算 `bcfd5c18…` 与三源一致；R1 预装 control.40，**升级判据仍按 `BA-X-1` 上板回读**。见本报告 §4（证据升级但不改 contract pin_kind、未上真机） | 到货当天 `local_evidence.py --verify` 复核 + 执行单 2.5 升级后版本回读 | 已完成（实算）/ 待上板（`BA-X-1`） |
| **P0-3** | **人人 HUB 取电板 / NP-F550 几何未量** | ③ 装配前 (`BA-2-5` / `DIMENSION` 悬案) | 只有商品名与价，无几何一手；`power_support` / `banana_pcb_locker` 需按实物重打，不能套 fanhao STEP | 到手卡尺量板框/孔径/孔距/双铜柱间距，与 NP-F550 实物凹孔试插，再重打打印件 | 到货当天（卡尺） |

> P0-1/P0-2 已于 2026-11-12 提前解除（本机实算闭环，工具 `local_evidence.py`，报告见 `microduck-底座产物下载与本机实算sha-P0预处理-2026-11-12.md`）；**但实算 ≠ 上板**：contract `pin_kind` 与 `ship_verdict` 不变、`BA-X-1` 上板判据仍等整机。P0-3 必须等实物。三者都**不改采购域权威文件、不碰用户手改 xlsx**。

---

## 1. 里程碑 ① · 主板裸板（Radxa + TF + USB-C，不接 HAT/舵机/电池）

**目标**：板子活、卡能复现、串口能进。到此 `live_hardware_accessed` 翻 `true`，但 `ship_verdict` 不变。

| 步 | 动作 | 命令 / 工具 | PASS 判据 | 证据落位 | FAIL 回退 |
|---|---|---|---|---|---|
| 1.1 | 做卡（PC 侧，不执行 dd） | `reproducible_card.py --check --verify-sources .upstream --flags "--overlay i2c4-m0"` | rc=0；`--no-camera`/`--no-tof` 必被拒(rc=1) | 成品卡 sha 记入 §7 | 先核 R1 sha(P0-1)；做坏只重刷 TF，无 A/B 回滚 |
| 1.2 | 烧 R1 + 首次上电 | 串口看 U-Boot→内核→login | 无 panic，进 login | dmesg 快照 → 证据文件 | 见 stage0 §6「搜不到按顺序查」 |
| 1.3 | 串口 / SSH 进板 | `cat /proc/cmdline`；`systemctl status serial-getty@ttyS2` | 无 `console=ttyS2`；robotd 能 open(`BA-3-4`) | cmdline 快照 → `--record BA-3-4` | 做卡时 mask getty 未生效→重做卡 |
| 1.4 | 四元组版本实算 | `check_image_pairing.py --check --verify-sources .upstream` | R1/IMU-HEX 两个 slot 升 `LOCAL_COMPUTED`；`control43` 仍 UNOBTAINABLE 如实 | 报告 → §7 | P0-1/P0-2 未解除则 slot 不闭环，不假绿 |

**里程碑 ① 结束**：`board_acceptance.py --record BA-3-4 --value "..." --evidence <cmdline快照> --evidence-dir out/board_acceptance/`。看一眼 `ship verdict` 仍 `NOT_SHIPPABLE` 即为正确。

---

## 2. 里程碑 ② · + HAT + 供电（最小系统，仍未装 15 舵机）

**目标**：总线节点与 IMU 路径就绪、控制配置对线。**仍无一颗舵机转。**

| 步 | 动作 | 命令 / 工具 | PASS 判据 | 证据落位 | FAIL 回退 |
|---|---|---|---|---|---|
| 2.1 | HAT 物理贴合 / 无短接 | 目视 + 万用表量供电端 `< 1Ω` 报警 | 40-pin 无顶针错位；供电端不短(`BA-2-4`) | 万用表读数 → `--record BA-2-4` | 断电再插；P0-3 未量前装夹座先验无短接 |
| 2.2 | 舵机总线节点 | `dmesg \| grep tty; ls -l /dev/ttyS2` | 出现 `/dev/ttyS2`(UART2_M0)、有 rw 权限(`BA-3-2`) | dmesg/ls → `--record BA-3-2` | 节点名不符先 `dmesg` 定位真名，不臆改引脚 |
| 2.3 | I2C 设备扫（**辅助姿态，非策略 IMU**） | `i2cdetect -y 3` | 板载 IMU 出现在 0x68/0x69 | i2cdetect 输出 → 存档 | ⚠️ `BA-5-1` 标 `LINE_MISMATCH`：扫到头 IMU **不代表**策略用的总线 ID200 就绪 |
| 2.4 | robotd 起进程 / 读配置 | robotd 启动日志 | 无 `unverified HD1910M mode-4 firmware/registers`、无 BUILD FAILED 退出(`BA-6-1`) | 启动日志 → `--record BA-6-1` | 固件/标定不匹配→不要按 DuckBuddy 表写 EEPROM |
| 2.5 | control.40→.43 升级 | V167 中控「系统维护」装随包固件 + 版本回读 | 回读 control.43/API40，与 BUILD 记录配对(`BA-X-1`) | 版本回读 → `--record BA-X-1` | **P0-2 未解除则无法升级**，如实记缺口 |

**里程碑 ② 结束**：总线节点与配置就位。A2 悬案闭合数 **仍 0**；`ship_verdict` 仍 `NOT_SHIPPABLE`。

---

## 3. 里程碑 ③ · 整机落地（15 舵机 + 2S 电池 + 装配）→ 才动 A2

**安全前置（H1/H8，先读 stage0 §0 五条铁律）**：
- **先插 USB 后给舵机上电**（反了总线压到 2.1V，一颗不应答）；
- **`set_torque(true)` 前先写当前姿态到 goal → 回读 → 再上扭矩**（同一次调用内），否则 15 颗 inrush 触发欠压重启；
- **电池 7.4V 档（非 3S）**，配置显式 `[battery] cells=[2]` / `max_volts=8.4`，误接 3S 有烧毁风险；
- **写 EEPROM 只能在「上电默认 reg40=0、robotd 起来之前」窗口**，窗口 ≥0.35s，**绝不切 mode**（会从 EEPROM 重载冲掉）；回读 PASS ≠ 持久 PASS，须断电回读。

| 步 | 动作 | 命令 / 工具 | PASS 判据 | 证据落位 | 关联悬案 |
|---|---|---|---|---|---|
| 3.1 | 电池实测 | 万用表量满电 ≤8.4V；核对 cells=[2] | `BA-1-5` | `--record BA-1-5` | CURRENT |
| 3.2 | 排线极性 | J13/J14(3P TTL)接 15 颗；J3/J11(4P RS485)空置；认脚号不认颜色 | `BA-2-2` | 接线照片 | — |
| 3.3 | 人人 HUB 几何 + 重打件 | 卡尺量 + NP-F550 试插 + 按实物重打 | `BA-2-5` | 卡尺记录/试插照片/STL | `DIMENSION` |
| 3.4 | **15 颗 1M 扫 ID + identify** | `identify_joints.py --port <COM> --baud 1000000`（该工具 `--baud` 默认已是 1000000；其 help 里"robotd 部署档是 500000"是 **B 代遗留注释，路① 不适用**，别照它填 500000） | 15/15 应答、无丢包；逐颗回读 ID/direction/zero_ticks(`BA-4-1`) | 逐颗日志/ID 表/方向表 → `--record BA-4-1` | `LIVE_IDENTIFY`+`LR_LABEL` |
| 3.5 | 总线 IMU 认板 | 接人人 ¥80 IMU(imu_to_dxl)，读 ID200 + FT6 身份字节 `06 00 00 00 F2`；**断开再跑一次须变红** | `BA-5-2` | 回读日志 + 负对照输出 → `--record BA-5-2` | `LIVE_IDENTIFY` |
| 3.6 | EEPROM 免写 | 回读 reg6 保持 0；确认未发写指令 | `BA-4-2` | reg6 回读 | `RATE_MISMATCH` |
| 3.7 | p8head_2999 加载 | R17 V167 中控加载 + 字段回读 | 加载成功无 mismatch；不成功改镜像配套模型(`BA-7-2`) | 中控加载日志 → `--record BA-7-2` | —（上机前必闭合②） |
| 3.8 | 安全层 | 核 fall=-0.5/debounce200ms/FallPredictor/deadman；首次站立限位低速 | `BA-8-1`；0.6s 回站触发 | 配置回读 + 回站日志 → `--record BA-8-1` | — |
| 3.9 | 相机 + ToF 上线 | mediad/tofd 服务状态 + 读数 | IMX219 出图、VL53L5CX V2 读数、无崩溃(`BA-X-3`) | 服务状态/图像/测距 | —（订正㉑必需不可砍） |
| 3.10 | 手柄 mapping | 遥操作实测 + 5GHz Wi-Fi | `BA-X-2` | 映射表/实测 | — |
| 3.11 | 轮滑策略（两版都做） | 中控读策略清单→加载/切换→回读 action_scale→换装位移跨度；**未加载时判据须失败** | `BA-9-1` | 清单/字段/配置/位移记录 → `--record BA-9-1` | `ROLLER_POLICY` |
| 3.12 | 真机时变命令跟踪 | 50Hz 下发 vx 0.30±0.10 / wz 0±0.6 的 sine/step，回读本体速度，按 E3 口径算 nRMSE/lag/meas-cmd；负对照 period-0 + 策略未加载 | `BA-X-4`：nRMSE ≤0.40 才算跟住；注入检查不过读数无效 | 原始序列/逐周期表/负对照 → `--record BA-X-4` | `LIVE_TRACKING` |

> **3.4 / 3.5 / 3.12 是消 A2 的三个主战场**。左右文字定义 (`LR_LABEL`) 只认 ID 数字，装配/标定不认左/右文字，记录里写明视角定义后再用文字。
> **R3 (`RATE_MISMATCH`) 单独闭环**：路① Radxa 原生 1M，这批物料验不了 500k；需示波器量位宽 + 另一适配器解耦(`BA-4-3`)，不是走路前置。

---

## 4. 每步证据怎么落（统一动作）

```bash
cd microduck-software
PY=.venv-mjlab/Scripts/python.exe
EV=out/board_acceptance/            # 已 gitignore，不入库

# 采一条观察值（ba_id 换成对应 id，evidence 换成真实快照文件）
$PY tools/hd1910/board_acceptance.py --record BA-3-2 \
    --value "ttyS2 present, rw ok" \
    --evidence <你存的dmesg或日志路径> --evidence-dir $EV

# 看当前采集进度（structure PASS + ship 仍 NOT_SHIPPABLE 才对）
$PY tools/hd1910/board_acceptance.py --check --evidence-dir $EV
$PY tools/hd1910/board_capture.py --verify --evidence-dir $EV   # 读已采记录

# 生成/核对采集表与欠项
$PY tools/hd1910/board_capture.py --plan
```

- 证据文件自己存（dmesg/日志/照片/CSV），`--record` 只记它的 **sha256 + 字节数 + UTC 时间戳**，不存内容。
- **`--record` 的 id 必须在 25 条清单内**，未知 id rc=1（负对照已验证）。
- 台架 4.6V 读数（`BA-4-4`/`BA-6-3`）标 `BENCH_ONLY`，真机 7.4V 必须重测，**不作整机签收**。

---

## 5. 到货当天不要踩的线（明确别做）

- ❌ 拿清单原文 `BA-0-1`(2GB)、`BA-0-2`(kissqy HAT)、`BA-5-1`(板载 I2C)、`BA-6-2`(B代键名)、`BA-7-1`(publish 链) 当现行判据——这 7 条已标 `SUPERSEDED`/`LINE_MISMATCH`/`BENCH_ONLY`，照抄会制造假绿。
- ❌ 用 `uv run publish` / `robotctl policy load`（路① 是 **R17→V167 中控**，非 publish 链）。
- ❌ 做卡勾 `--no-camera` / `--no-tof`（订正㉑：IMX219 + VL53L5CX V2 必需不可砍，B8 会拒 rc=1）。
- ❌ 一次给 15 颗逐颗写 reg6=1（路① 原生 1M，EEPROM 免写；写了反而重复 R3 零应答）。
- ❌ 满电 8.4V 做堵转 / 用 U2D2 / 腿没伸直就用 FD「中位校准」。
- ❌ 把 `--record` 采到证据、`selftest` 全绿、或仿真侧 E3 `PATH_3` 当成"真机已验收/已能跟随"——`UNVERIFIED != PASS`。

---

## 6. 完成判据（什么时候才谈得上 SHIPPABLE）

全单跑完且：① 25 条里所有 `CURRENT` 判据逐条有证据；② `SUPERSEDED`/`LINE_MISMATCH` 条目按现行 SSOT 改写后重跑；③ `closure_contract.json` 的 **7 条 `INCONCLUSIVE_*` 全闭合**（`LIVE_IDENTIFY`/`DIMENSION`/`CURRENT`/`RATE_MISMATCH`/`LR_LABEL`/`ROLLER_POLICY`/`LIVE_TRACKING`）；④ **人工签署** `signoff`。缺任一，`ship_verdict` 恒 `NOT_SHIPPABLE`。

- **里程碑 ③ 的 3.4/3.5/3.12 闭合后**，才触发 D1 `DECISION_LOWLEVEL_RETRAIN_DEFERRED` 的重开条件（整机落地 + 真机 BA-X-4 仍 PATH_3 且 ≥3 组日志复现）→ 转 A2 重拍板是否重训低层。**主板到货本身不重开任何决议。**

---

## 7. 本单引用的一手来源（不复制第三份清单）

| 主题 | 唯一主人 / 依据 |
|---|---|
| 25 条判据 + 证据落位 | `microduck-software/tools/hd1910/board_acceptance_contract.json` + `board_acceptance.py` |
| 上机采集表 / 欠项 | `tools/hd1910/board_capture.py`(B7，派生自上两者，无第三份) |
| 四元组版本配对 | `tools/hd1910/image_pairing_contract.json`(B2) |
| 做卡配方 / 禁用 flag | `tools/hd1910/card_build_contract.json`(B8) |
| 悬案状态与签署 | `tools/hd1910/closure_contract.json`(A2) |
| 上电/装配/安全 | `docs/hardware/microduck-Radxa上电验收清单-2026-11-06.md` + `tools/hd1910/stage0_software_prep.md` |
| 单颗舵机工具 | `tools/hd1910/servo_probe/`（identify_joints / hd1910_ident / calibrate_offsets / hd1910_snapshot 等） |
| 现行线别 / 部署链 | SSOT `docs/hardware/microduck-最优方案-价格硬件软件-2026-11-06.md` 订正⑫⑬㉑㉔㉕ |

---

## 8. 上板当天的门禁判读：本机红灯 ≠ 交付缺陷（2026-11-12 补）

> ⚠️ **先读这节再跑门禁**。在本机（开发者工作树）跑 `run_all_gates` / `pytest` 会看到 **48/50门禁、2 条 pytest failed、`check_closure.py --check` rc=1**；**这是已知的本地假红，不是回归，也不是交付缺陷**。到货当天在干净 checkout（CI 环境）上这些全绿（A2 selftest 31/31、8 条 A2 测试全过、`--check` 8=8 rc=0）。别为本机红灯做任何"修复"。

**根因（一句话）**：A2 的文档标记扫描 `scan_doc_marks()` 走**文件系统**遍历白名单根（`docs/` 等），于是本机一份**尚未入库（untracked）的安卓 App 线 C2 草稿文档**里那条"`robot.state` 通知流/重订阅未验"的标记被扫了进来，使本机 docs 标记数 9 > 契约 id 数 8；CI 干净树不含未跟踪文件，只扫到 8，与契约相等 → 绿。该安卓标记属**另一条软件产品线的 C2 悬案**，未登记进本仓库 A2 契约，也不该现在登记（见下「三条禁路」）。

**自助判读（到货当天照跑，只读、不改任何东西）**：
```bash
cd microduck-software
.venv-mjlab/Scripts/python.exe tools/hd1910/check_closure.py --explain
# 本机有草稿时:  classification = LOCAL_ONLY_DRAFT_RED
#                local structure = FAIL  /  committed structure = PASS  /  rc=0
# 干净 checkout:  classification = ALIGNED  双绿  /  rc=0
```
`--explain` 会逐条列出多出的标记来自哪个文件、该文件是否 tracked，并给出**提交态（git 索引视角）**的结构判定。它**只是诊断、永远 rc=0、不是门禁**，`--check` 的判定与 rc 一个字没改。`--explain --json` 供脚本消费。判据：只要 `committed structure = PASS` 且 `ci_unregistered_markers` 为空，本机红灯就是假红，可安全继续 §1–§3 上板动作；若 `committed structure = FAIL`，那是**真回归**（有人把未登记标记写进了 tracked 文档），必须先修再上板。

**三条禁路（做了会把 CI 干净树反向弄红，或掩盖缺口）**：
- ❌ **只把那条标记加进 `closure_contract.json`**：CI 干净树没有那份草稿文档 → 契约多一条、docs 少一条 → `extra` 反向红。
- ❌ **放宽/改成只扫 tracked 文档**：会削弱 C1「文档出现未登记标记必红」的承诺——一旦有人把带标记的文档 `git add`，本机就再也发现不了。
- ❌ **移走/删除用户的安卓草稿文档来消红**：掩盖缺口，且那条 C2 悬案仍需闭合。

**唯一正确闭合时机**：安卓 App 线正式入库时，**该草稿文档转 tracked** 与**把那条标记登记为 A2 第 9 条契约**必须**原子地同时做**，使本机与干净树的 id 集合一起变 9=9；在此之前本机 9/8 保持假红、CI 8/8 保持绿，两者都如实、都不动契约判定。⚠️ 任何 tracked 文档（含本单）都**不得写出那条标记的字面全名**——扫描正则是 `INCONCLUSIVE_` + 大写串，写出即被当成第 9 个文档标记反噬 CI，故本单只用中文描述、不落字面。

**到货前消费端 Dry-run 证据（2026-11-12 本机实跑，全部 rc=0）**：P0 已下载的 4 个实体（R1 / V167 / control.43 固件包 / IMU bin）被下游三个入口正确消费，证明「到货当天照抄命令不会因工具/路径/实体缺失当场炸」——但这**只是工具链就绪**，非上板验收：

| §0 表入口 | 命令（cwd=`microduck-software`） | 实跑结果 | 边界 |
|---|---|---|---|
| P0-1/P0-2 复核 | `local_evidence.py --verify` | `verdict=ALL_LOCAL_COMPUTED`，4/4 实体本地 sha 与发布 pin 一致；`ship=NOT_SHIPPABLE` | 只证字节同一，不证能刷入/过 `BA-X-1` |
| §1.4 四元组配对 | `check_image_pairing.py --check --verify-sources .upstream` | `structure=PASS`，`source_files_verified=true`，`ship=NOT_SHIPPABLE` | control.43 版本仍等上板回读 |
| §1.1 做卡配方 | `reproducible_card.py --check --verify-sources .upstream --flags "--overlay i2c4-m0"` | `structure=PASS`，`audited flags` 无 refused，`source_files_verified=true` | 不执行 dd；相机/ToF flag 仍强制 |

> 三入口全 rc=0 仅说明**软件准备到位**；里程碑 ① 的 `live_hardware_accessed` 翻 true、A2 悬案闭合、人工签字仍全部等整机上板。`COLLECTED != PASS`、`工具就绪 != 悬案闭合` 不变。

---

_本文纯新增，未改任何既有工具/契约数字，未碰采购域 SSOT、生成源、用户手改 xlsx 与 `.ref/`。所有 Dry-run 在 `live_hardware_accessed=false` 下完成，`ship_verdict=NOT_SHIPPABLE` 不变。第 8 节为纯文档补充 + 只读诊断工具 `--explain`（`check_closure.py` 内新增，判定语义与 `--check` rc 不变）；新增 7 条注入式 selftest 负对照 + 3 条 CLI 回归测试，本机/CI 干净树双向已验。_
