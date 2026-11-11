# MicroDuck B2 / B8 / B1：镜像固件版本配对、可复现做卡、上板验收脚本化

_2026-11-11，承接 `microduck-四源软件工程对照与取长补短-2026-11-11.md`（A1/A2/A3，commit `3536e9e`）。本轮把「自己写镜像/固件、取长补短」的目标落成三件**离线可建、带负对照、不碰采购域权威文件**的护栏。_

> 口径：官方 / kissqy / fanhao / luwu 四源为主，其他开源为辅；先查一手源码与文档，再下结论；查不到明标 `UNOBTAINABLE`，不外推。**离线 / 源码 / 仿真 / 第三方公布值 ≠ 实机验收**；`UNVERIFIED != PASS`。

---

## 0. 结论

| | 交付 | 一句话 |
|---|---|---|
| **B2** | `image_pairing_contract.json` + `check_image_pairing.py` | 把「R1 镜像 ↔ control.43 ↔ V167 中控 ↔ IMU 节点 HEX」四元组绑成单一主人；**第三方公布的 sha 不算本地实算**，`--ship-gate` 必红 |
| **B8** | `card_build_contract.json` + `reproducible_card.py` | 把 fanhao 两个做卡脚本的 sha / 扇区 / overlay / 禁用 flag 抽成配方并互证；**回滚是借用目标，不是路① 现状**；绝不执行 dd |
| **B1** | `board_acceptance_contract.json` + `board_acceptance.py` | 把 2026-11-06 上电验收清单变成 23 条带 `authority` 的 CLI 判据；`--record` 只写 `COLLECTED`，**永不自动判 PASS** |

三件套都遵循同一条边界：**稀缺的不是代码所有权，是上板验收证据**。当前 `ship_verdict = NOT_SHIPPABLE` 是如实状态，不是待修的红灯。

---

## 1. 本轮查全的一手来源

| 来源 | 取到的事实 |
|---|---|
| `.upstream/kissqy/README.md` 行 9/17–20/22/38–39 | control.43 随 V167 中控提供、R1 仍预装 control.40；官方 0.15.1 / API40；R17 V167(1.0.167)；训练中控 R1.5.27；Public Image R1；`firmware/BUILD.json` 与 V167 随包固件 BUILD 记录一致、两个中控源码与各自 ZIP 同步；`docs/BUILD.md` / `BASELINE.md` / `PUBLICATION-MANIFEST.json` 指向 |
| `.upstream/kissqy/README.md` 行 11 | kissqy 的 IMU 板是另一套「STM32 FT6 单独刷」，control.43 装到 ZERO **不会**烧录外置 IMU |
| `.upstream/replica/tools/radxa/build-armbian-card.sh` 全文 | `UBOOT_DEB_SHA=fb319203…`、扇区 64/16384、extlinux 挂 `uart2-m0` + `dwc3-peripheral`、`console=tty1`、`g_serial` + `serial-getty@ttyGS0`、mask `serial-getty@ttyS2`/`ttyFIQ0`、machine-id 空 + sshd-keygen 校验、删除预生成 SSH host key |
| `.upstream/replica/tools/radxa/kissqy-r1-v112.sh` 全文 | `R1_SHA=75da978b…`（注释自述「kissqy 发布页公布的校验值」）、同一 U-Boot sha、根分区 ≥ 32768 检查、只换引导其余原样保留、`--overlay` / `--no-camera` / `--no-tof`、写入 `/etc/microduck-v112-image.txt`、结尾输出成品卡 sha |
| `.upstream/replica/hardware/imu_to_dxl/firmware/VALIDATION.md` | 0.2.0 解码镜像 SHA-256 `66bc7c53…`、Flash 10,724 字节；**「真总线、舵机、T_resp 实测、DE 释放时序都还没测」** |
| `.upstream/replica/hardware/imu_to_dxl/firmware/Build/imu_to_dxl.hex` | 本机实算：文件 sha `10ef4813…`；独立 Intel HEX 解码 671 条 type00 记录、`0x08000000..0x080029E3`、10,724 字节、镜像 sha `66bc7c53…` —— 与上游文档逐字吻合 |
| 官方 `pollen-robotics/microduck_yocto` 仓库页（联网一手） | kas + Yocto 6.0 wrynose、`microduck-zero3` stand-in machine、A/B RAUC 签名更新 + 健康检查自动回滚、dev/shipping 双镜像、QEMU 无板验 systemd 顺序、Apache-2.0 |
| `.upstream/ft1910/docs/design/scs-bus.md` §What is verified and what is not | 33 个无板测试 + 2026-10-06 zero3 first light（`/dev/ttyS2` 1M、15 舵机 + ID200 全应答、50.0/50.0 Hz、0 missed/436 ticks）；明写「numbers are still firmware 3.46's」「zeros are borrowed」「direction inherited for eleven joints」「Nothing has been commanded to move」 |
| `docs/hardware/microduck-Radxa上电验收清单-2026-11-06.md` 全文 195 行 | §0–§9 全部 PASS/FAIL 判据；§6.2 自述沿用 DuckBuddy 键名；§8.5 自述台架 4.6V 是欠压值 |
| SSOT 订正⑬/㉑/㉔/㉕ | 路① = 1GB/无 eMMC、R17→V167 非 publish、人人 C1 + IMU + HUB + 金属件、相机与 ToF 必需不可砍、上机前必闭合四项 |

**取不到、明标不外推**：kissqy `docs/BUILD.md`、`docs/BASELINE.md`、`firmware/BUILD.json`、`PUBLICATION-MANIFEST.json` 正文联网均 404（与上一轮 `BASELINE.md` 同型）；本地 `.upstream/kissqy/` 只有 6 个文件、无 `firmware/` 目录 ⇒ **control.43 既无源码也无 sha，`UNOBTAINABLE`**。官方 Yocto 只有仓库页说明，本地无完整 clone；luwu 未抓源码文件树。

---

## 2. B2：四元组版本配对契约

### 2.1 为什么需要

README 行 22 的「BUILD.json 与 V167 随包固件一致」是**作者声明**，不是本机校验。而 SSOT 判路① 部署链是 R17→V167 中控、R1 预装 control.40 须升级 control.43。四元组一旦混批，离线看全都「合理」，只有上板才炸。

### 2.2 四个 slot 的真实 pin 状态

| slot | 期望值 | `pin_kind` | 证据性质 |
|---|---|---|---|
| `system_image_r1` | `75da978b…` | `UPSTREAM_PUBLISHED` | fanhao 脚本引用的「发布页公布值」；本机无 R1 `.img.xz` 实体 |
| `robot_firmware_control43` | control.43 / API40 | `UNOBTAINABLE` | 编译链与 BUILD.json 正文均取不到；只有 README 叙述 |
| `robot_console_v167` | R17 V167 ZIP | `UNPINNED` | 直链可读但未下载、无 sha、未与源码比对 |
| `imu_node_firmware_020` | 文件 `10ef4813…` / 解码镜像 `66bc7c53…` | `LOCAL_COMPUTED` | 本机实算 + 独立 HEX 解码 + 上游 VALIDATION.md 互证 |

`pin_kind` 只有 `LOCAL_COMPUTED` 算闭环；`UPSTREAM_PUBLISHED` 只证明「别人公布过这个值」。

### 2.3 🔴 HEX 双 sha 是不同量（本轮抓到的读数矛盾）

第一眼看到本地实算 `.hex` 文件 sha `10ef4813…` 与 `VALIDATION.md` 写的 `66bc7c53…` 不一致，按项目铁律「读数 vs 算术矛盾先查，不直接下结论」用**独立 Intel HEX 解码算法**互算：671 条 type00 记录、逐条校验和验过、地址连续 `0x08000000..0x080029E3`、10,724 字节，解码镜像 sha **正好等于 `66bc7c53…`**。⇒ 前者是 HEX **文本文件**、后者是它编码的 **Flash 二进制镜像**，契约里两个都 pin 且语义分开。`--verify-sources` 会同时实算两者并核对，篡改 1 字节必翻红。

### 2.4 跨槽规则与禁止动作

- R1 预装 **control.40** ⇒ 必须升级 control.43（SSOT 上机前必闭合③）。
- V167 随包 control.43、`BUILD.json` 与随包 BUILD 记录一致、两个中控源码与 ZIP 同步。
- 路① 部署链是 **R17→V167，不是 `uv run publish`**（publish 与这代 robotd 非一条链，`deploy61` 分母差 1157 倍）。
- IMU 节点 HEX 与 control.43 是**不同对象**；且该 HEX 属 fanhao 复刻仓硬件，不保证与人人 ¥80 板同硬件 ⇒ 认板前不刷（`INCONCLUSIVE_LIVE_IDENTIFY`）。

`--check --verify-sources .upstream` 本机实跑 6/6：`IMU HEX file sha256` / `decoded Flash image sha256` / `size 10724` / `VALIDATION.md 记录一致` / `R1 sha 与脚本一致` / `source root present`；`control43_build_json_present = False` 如实。

---

## 3. B8：可复现做卡 + 可回滚的诚实边界

### 3.1 取长补短的正确姿势

**底座不动**（R1 + fanhao 叠层），只借机制：

- 借 fanhao 两个脚本做**可复现做卡配方**：10 个 pin（U-Boot deb sha / URL、R1 原包 sha、扇区 64/16384、根分区 ≥32768、两个 overlay、`console=tty1`、mask getty、USB 串口）+ 5 条前置条件（machine-id 空、sshd-keygen、删 host key、先核 R1 sha、换引导后改 extlinux 而非 armbianEnv）。
- 两个脚本写同一个 U-Boot sha 属**独立见证互证**；`--verify-sources` 实时重读两脚本，任一方改 sha 必红。
- 借官方 Yocto 的 **A/B RAUC 签名 + 健康检查自动回滚**作为回滚契约 —— 但 `status = NOT_IMPLEMENTED`。

### 3.2 🔴 回滚不能「借来说成有」

kissqy R1 / fanhao 改卡是**单分区 extlinux 卡**，没有 A/B 分区、没有 RAUC、没有自动回滚；做坏只能重刷 TF 卡。fanhao 脚本靠「先核 R1 sha + 只改引导 + 记录改动 + 输出成品 sha」降低风险，这是**可复现，不是可回滚**。契约里 `current_reality` 与 `must_not_claim` 把这条钉死，`rollback_contract.status` 改成 `IMPLEMENTED` 而不给证据 ⇒ `validate` 必红。

### 3.3 禁用 flag（与本项目硬判决冲突）

fanhao 脚本的 `--no-camera` / `--no-tof` 只用于「没接摄像头/ToF 时避免 mediad / tofd 反复崩溃占满一核」的临时调试；本项目 SSOT 订正㉑ + 用户 2026-11-10 拍板 **IMX219 与 VL53L5CX V2 必需不可砍**，所以 B8 把两个 flag 列进 `forbidden_flags`，`--flags` 审计到就 rc=1。`--overlay i2c4-m0` 仍放行，且不做裸 `--no-` 前缀匹配（`-`-相近词不误杀）。

---

## 4. B1：上板验收脚本化（含过时判据治理）

### 4.1 🔴 清单是 2026-11-06 起草，多处已被后续订正覆盖

把清单直接变可执行会**制造假绿**。23 条判据每条带 `authority`：

| authority | 条数 | 例子 |
|---|---|---|
| `CURRENT` | 16 | J13/J14 TTL、`/dev/ttyS2`、reg6=0 免写、固件元数据快照 row[33]=4、安全层、上机四项必闭合、相机+ToF |
| `SUPERSEDED` | 2 | §0/§1.1 写 **2GB**（SSOT 锁 1GB/无 eMMC）；§0/§1.2 写 **kissqy HAT**（订正㉕ 改人人 C1） |
| `LINE_MISMATCH` | 3 | §5 板载 I2C 头 IMU（路① 策略角速度来自总线 ID200）；§6.2 DuckBuddy `feetech_hls` 键名（hd191m 线键名完全不同）；§7 `uv run publish`（路① 是 R17→V167） |
| `BENCH_ONLY` | 2 | §4.3 速度标度 0.732、§6.4 P/D 台架 P8→24 —— 都是 **4.6V 欠压值**，清单 §8.5 自己写明真机 7.4V 要重测 |

被覆盖条目**原文保留作史料**，但 `validate` 强制要求 `authority_note` + `superseded_by`，且 `CURRENT` 不得同时声明 `superseded_by`。

### 4.2 跨契约集合断言

`closure_contract.json` 里 5 个 `UNVERIFIED` 悬案必须各被至少一条 check 的 `closure_refs` 引用；引用不存在的 id、或漏掉任一悬案，`--check` 变红。另加 `required_check_ids` 显式登记 23 个 id（借 `check_book.py` 的 expected == actual）：**删任意一条或新增未登记条目都必红**。A2 仍是悬案状态与签署的唯一主人，B1 不复制它的状态。

### 4.3 `--record` 永不判 PASS

`--record <id> --value TEXT --evidence FILE` 只落 `COLLECTED`（观察值 + 证据文件 sha256 + 字节数 + UTC 时间戳，默认目录 `out/board_acceptance/`，已被 gitignore）。是否闭合由 `closure_contract.json` 的 `signoff` 人工签署：`overall_verdict` 要求 **signoff PASS 且至少一条证据** 才 `SHIPPABLE`，缺一即 `NOT_SHIPPABLE`。`--ship-gate` 即使已采证据仍 rc=1（真跑负对照）。

---

## 5. 本轮抓到的三个真缺陷（都是审阅/自检时暴露的）

1. **argparse rc=2 陷阱复发**：B8 `--flags "--no-camera"` 因值以 `--` 开头被 argparse 拒收（`expected one argument`），而 `run_all_gates.py` 把 rc=2 判 `GUARD INVOCATION BROKEN`。修法：`normalise_argv()` 把空格写法改写成 `--flags=...`，两种拼写都给真实拒绝 rc=1；selftest 里加 3 条 **CLI 真跑**对照，pytest 也真跑 CLI。这正是「只测内部函数不测 CLI = argparse 全绿假象」的又一次命中。
2. **清单删条目不报警**：B1 第一版 selftest 27/28，`删一条 check 必红` 没翻红 —— 删掉末尾条目后 section 覆盖与悬案引用都还成立。补 `required_check_ids` 集合相等断言后 30/30。
3. **HEX 双 sha 语义混淆**：见 §2.3，用独立解码互算才分清「文件」与「解码镜像」，避免把一个真实值误判成错误读数。

---

## 6. 落地件清单（本轮改动）

| 文件 | 性质 |
|---|---|
| `microduck-software/tools/hd1910/image_pairing_contract.json` | 新增 · B2 契约 |
| `microduck-software/tools/hd1910/check_image_pairing.py` | 新增 · B2 校验器（含 Intel HEX 解码器） |
| `microduck-software/tools/hd1910/card_build_contract.json` | 新增 · B8 契约 |
| `microduck-software/tools/hd1910/reproducible_card.py` | 新增 · B8 校验器 |
| `microduck-software/tools/hd1910/board_acceptance_contract.json` | 新增 · B1 契约（23 条判据） |
| `microduck-software/tools/hd1910/board_acceptance.py` | 新增 · B1 CLI + 证据采集 |
| `microduck-software/tests/test_image_pairing.py` | 新增 · 6 个测试 |
| `microduck-software/tests/test_reproducible_card.py` | 新增 · 6 个测试 |
| `microduck-software/tests/test_board_acceptance.py` | 新增 · 6 个测试 |
| `microduck-software/tools/hd1910/line_labels.json` | **定点追加** 3 条 `META_GUARD` 登记（19→22），既有条目/数字零改动 |
| `docs/active/microduck-B2B8B1-镜像固件版本配对与可复现做卡上板验收-2026-11-11.md` | 新增 · 本文档 |

---

## 7. 实跑验收（全部真跑，非沿用归档）

| 项目 | 结果 |
|---|---|
| B2 `--selftest` | **24/24**，rc=0（含篡改 HEX 的真负对照） |
| B2 `--check` | 结构 PASS、`ship_verdict=NOT_SHIPPABLE`、`source_files_verified=false`、rc=0 |
| B2 `--check --verify-sources .upstream` | **6/6 源实算通过**、`source_files_verified=true`、`control43_build_json_present=false` |
| B2 `--check --ship-gate` | rc=1，`SHIP GATE REFUSED: 3 slot(s) not locally computed` |
| B8 `--selftest` | **26/26**，rc=0（含 3 条 CLI 真跑） |
| B8 `--check --verify-sources .upstream` | 13 项源互证全通过、`source_files_verified=true` |
| B8 flag 审计 | `--no-camera`/`--no-tof` rc=1；`--overlay i2c4-m0` rc=0；两种拼写均非 rc=2 |
| B1 `--selftest` | **30/30**，rc=0（含 `--record` → `COLLECTED` 不假绿） |
| B1 `--check` | 23 条判据、`CURRENT 16 / SUPERSEDED 2 / LINE_MISMATCH 3 / BENCH_ONLY 2`、结构 PASS |
| B1 `--list` | 23 条，含 `BA-7-1 LINE_MISMATCH` |
| 新增 3 个测试文件 | **18 passed in 7.89 s** |
| 全量 `pytest tests/` | **133 passed in 132.76 s**（原 115 + 新增 18） |
| `run_all_gates.py --check`（venv） | **41/41 PASS**（2 meta + 39 工具），`verdict=ALL_PASS`、`ship_verdict=NOT_SHIPPABLE`、rc=0 |
| A1 `line_contract.py --check` | PASS，labelled 22，覆盖差集仍 20（如实） |
| A2 `check_closure.py --check` | docs markers 6 = contract ids 6，5 `UNVERIFIED` + 1 `CLOSED`，`NOT_SHIPPABLE` |
| 三个 `--ship-gate` | 全部 rc=1（如实红，不是 bug） |

### 负对照（改坏必红，节选）

- B2：删/重复 slot、非法 `pin_kind`、`LOCAL_COMPUTED` 无本地文件、`UNOBTAINABLE` 假称有文件、抹 rule、scope 称碰硬件、空 slots、signoff 无证据称 PASS、清 cross_slot_rules / blocked_actions、有文件却无 sha 针、篡改 HEX 1 字节、`--verify-sources` 遇篡改 HEX。
- B8：两个禁用 flag 单个/同时必拒、近似 flag 不误杀、回滚无证据称 `IMPLEMENTED`、清 forbidden_flags / pins / preconditions / blocked_actions、pin 引用不存在见证脚本、两脚本 U-Boot sha 不一致、scope 称碰硬件。
- B1：删/增未登记 check、抹 `required_check_ids`、重复 id、引用不存在悬案 id、抹掉全部悬案引用、`SUPERSEDED` 无来源/无说明、`CURRENT` 却声明被覆盖、非法 authority、空 checks、抹 rule/coverage_rule、scope 称碰硬件、`--record` 未知 id、采证据后 `--ship-gate` 仍 rc=1。

---

## 8. Scope / 已知缺口

- `live_hardware_accessed = false`；三件套都不碰串口、不开总线、不刷固件、不写 TF 卡、不下载文件、不改上游仓。
- B2 不证明 R1 可开机、control.43 可编译、V167 可加载 `p8head_2999`、人人 IMU 认板、15 关节 ID 表、R3 消解。
- B8 不证明任何卡被做出或能开机；官方 Yocto 只有仓库页一手说明，本地无完整 clone；成品卡 sha 只有做出卡之后才有。
- B1 不证明任何判据已执行；证据目录默认在 gitignore 的 `out/` 下；台架 4.6V 读数标 `BENCH_ONLY` 待 7.4V 重测。
- `.upstream/` 被 gitignore，默认不随仓库分发；`--verify-sources` 是本机可选真证据复核，其他 clone 会如实报 `source_files_verified=false`。
- 5 个 `INCONCLUSIVE_*` 悬案仍 `UNVERIFIED`；R3 未消；仿真鸭不能消 R3。
- `line_labels.json` 覆盖差集仍有 20 个 `REPORT_ONLY` 工具，未假装全覆盖（B4 待办）。

---

## 9. 采购域零改动声明

本轮**未碰** SSOT `docs/hardware/microduck-最优方案-价格硬件软件-2026-11-06.md`、生成源 `build.py`、两份用户手改 xlsx、`.ref/` 生成源、任何既有工具的数字或代码：阶段0 ¥99、手删 3 行不恢复、预算 `≈¥2,500–2,579`、人人四样边界一律不变。除 `line_labels.json` 追加 3 条登记外，**既有文件零改动**；新文档与新工具全部纯新增。

### 与 A1/A2/A3 的关系

A1 管线别、A2 管悬案、A3 管门禁编排；B2 管版本配对、B8 管做卡配方与回滚边界、B1 管上板采集。三件套都通过 `run_all_gates.py` 的 `discover()` 自动纳入统一门禁（38 → 41），**没有改 A3 的代码**，只追加了 3 条 `META_GUARD` 标签。

### 下一步可选项

1. **B5** 🔴 路① 中控链 `R17→V167` / `robotctl policy load` 工具几乎零覆盖（现有部署工具都在 `uv run publish` 链），是最大线别错配风险。
2. **B3** 把 A1/A2/A3 与 B2/B8/B1 接入 `.github/workflows/deploy-gate.yml`（当前该文件自述 POST-PUSH ADVISORY、非 merge gate）。
3. **B4** 补 20 个 `REPORT_ONLY` 工具的线别标签；**B6** 过时口径守卫（`VL53L8CX` 残留里仍有未盖 L5CX 指针的文件）。
4. 实物到手后：B1 逐条采集 → B2 四槽本地实算 → A2 `signoff` 人工签署 → 才谈得上 `SHIPPABLE`。
