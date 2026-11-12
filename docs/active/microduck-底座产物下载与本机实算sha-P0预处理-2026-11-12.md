# MicroDuck 底座产物下载 · 本机实算 sha（P0-1/P0-2 预处理）

_2026-11-12。承接 `microduck-主板到货上板执行单-2026-11-12.md` §0 的 P0-1/P0-2。用户"全套底座+固件包、本机实算；control.43 先核验再按机制改判"授权。本文记录**下载 stacks、"用谁的方案"的事实裁定、四槽本机实算对照、control.43 的证据升级与其边界**。

> **口径（先读）**
> - 下载的是 **kissqy 主仓发布的底座原件**（R1 / V167 / control.43 固件包）。**不是** fanhao 另发的一套——fanhao 是叠在 kissqy 之上的 fork，不发布镜像/固件二进制（见 §1 一手裁定）。
> - 全部落 **gitignored** 的 `.upstream/downloads/`，**不入库、不碰采购域 xlsx、不碰 contract 的 pin_kind**。
> - **本机实算 sha 只回答"这些字节与发布方公布值是否一致"，不回答"能不能开机/刷入/真机跑"**。签名/启动链/rootfs 内容/硬件验证一概不在本文范围。
> - `ship_verdict` 恒 `NOT_SHIPPABLE`、`live_hardware_accessed=false`、A2 七悬案闭合数仍 0。

---

## 1. "不是用 fanhao 的方案吗" —— 一手事实裁定

这是本轮必须先答的问题。结论：**"方案"和"底座产物"是两个层次，不矛盾**。

| 层次 | 谁发布 | 本项目怎么用 | 一手依据 |
|---|---|---|---|
| **底座**：R1 系统镜像 / R17 V167 中控 / control.43 已编译固件 | **kissqy 主仓** | 下原件、本机实算 sha、做卡时改引导 | `kissqy/README.md`（本地 `.upstream/kissqy/`）行 9/17-20/22/26/28 |
| **叠加**：IMU 直连 I²C + gyro_fusion / 舵机调参 / UDP 手柄 / BLE | fanhao fork `hd1910-v167-trunk-imu-i2c` | 只借源码思路与做卡脚本；**"每个改动不打开就跟 V167 原版逐字节一致"** | `microduck-kissqy-HD1910-robotd-IMU与调参-参考价值-2026-11-09.md:27` |
| 做卡配方 | fanhao `kissqy-r1-v112.sh` | 已在本地，B8 脚本化（10 pin + 5 前置） | `microduck-B2B8B1…:76`「**底座不动（R1 + fanhao 叠层）**」 |

→ **fanhao 从不单独发布镜像或固件二进制**；它的价值是叠加代码与做卡脚本。所以下 kissqy 底座原件 = 走 fanhao 方案的底座，方向正确。

### 1.1 🔴 本轮新查到的两个事实（要落账，不掩盖）

1. **fanhao fork 远端已 404**：GitHub API 实测 `repos/fanhao375/Microduck-kissqy` 返回 404；该账号 26 个 repo 里已无 `Microduck-kissqy`（只有 `microduck-replica` / `microduck` / `microduck_rl` 等）。
2. **fanhao fork 源码的本地一手快照不完整**：本机 `.upstream/` 下并存多套 robotd 快照但**没有一套是 fanhao 的 API40 fork**——

   | 本地目录 | `API_VERSION` | 归属 |
   |---|---|---|
   | `.upstream/hd1910m/microduck` | **23** | MicroDuck HD1910M 另一套（README 自称 BNO08x/发 APK），**非 fanhao fork** |
   | `.upstream/DuckBuddy-main` | 16 | B 代 Orange Pi 线 |
   | `.upstream/ft1910` | 39 | 另一套 |
   | `.upstream/imu-displace` | 44 | 另一套 |

   `gyro_fusion.rs` / `[trunk_imu]` 配置键本机**找不到**。11-09 调研文档引用的 fanhao `API_VERSION=40`（`duck-ipc-proto/src/lib.rs:437`）是当时联网读的一手，fork 404 后本地未完整留存。

→ **影响**：① 安卓 App 线（已落地代码）基于当时核实过的 wire 契约（API40/BLE/路由表），不受底座下载影响；② 但"重新从一手源码复验 fanhao 叠加"这条路现在断了，若要恢复须另找归档或联系作者。**本文不把任何本地 23/39/44 快照冒充 fanhao API40**。

---

## 2. 下载通道实测（本机代理状态 2026-11-12）

记忆 11-06 记过"直连 release 被代理 502、gh-proxy + API asset 通"。本轮实测**通道能力又变了**，逐项记录，别再凭旧记忆选路：

| 目标 | 通道 | 实测 | 采用 |
|---|---|---|---|
| GitHub API（元数据/digest/contents size） | `api.github.com` | HTTP 200，R1 `assets[0].digest=sha256:75da…`、V167 `contents` size=39865662 | ✅ 拿公布值/交叉互证 |
| R1 `.img.xz` | release 直连 HEAD | 302→200，Content-Length=767412924 | 仅探测 |
| R1 `.img.xz` | **API asset** `Accept: application/octet-stream` | **支持 Range(206)**，但实测仅 **64 KB/s**（732MB 要 >3h） | ❌ 太慢，弃 |
| R1 `.img.xz` | gh-proxy 全量 | **~1.1–2.3 MB/s**，但**忽略 Range**（`-r 0-1023` 返回 200+整段，不能续传） | ✅ 采用，靠 sha256 兜完整性 |
| V167 ZIP / 小 json·sha256 | gh-proxy + raw | 2.26 MB/s，小文件偶发 `HTTP=000`（连接重置），`--retry 3` 可解 | ✅ 采用 |

**结论**：完整性由 sha256 对账兜底，是否断点续传不重要；API asset 的"支持 Range"优势被 64KB/s 抵销。R1 全量下载中途文件小于发布 size 是**正常在途态**，本机证据工具判 `INCOMPLETE_DOWNLOAD`（不误报"损坏"）。

---

## 3. 四槽本机实算对照

单一权威：`tools/hd1910/local_evidence_manifest.json`（公布值 pins + witnesses）+ `tools/hd1910/local_evidence.py`（本机字节实算 + 多源对账）。`--verify` 只读、离线、不碰硬件；`--local-selftest` 9/9（含篡改/半成品/缺文件/git blob 假红四类负对照）。

| artifact | 本地文件 | 本机实算 sha256 | 对照公布值 | 判据 |
|---|---|---|---|---|
| `system_image_r1` | `microduck-zero3w-0.15.1-R1.img.xz` | `75da978b...5bce5`（三实现互证：工具 `read_bytes` / Python 流式哈希 / 系统 `sha256sum`） | `75da978b…`（GitHub digest + fanhao 脚本 + contract 三源） | 四源 + size=767412924；gh-proxy 全量下载 9m24s/1.36MB/s、rc=0、BYTES 精确相等 |
| `robot_console_v167` | `Microduck-Console-R17-V167.zip` | `7e2d70ba…` | 本地实算 + **git blob SHA-1** `b8ed246c…` 与 GitHub API contents 逐字复现 | 双算互证 + ZIP testzip 完整 + size=39865662 |
| `robot_firmware_control43_pkg` | `Microduck-Robotd-FT6-R17.tar.gz`（**从 V167 ZIP 内 `updates/` 抽出**） | `bcfd5c18…` | `firmware-control43.json` + ZIP 内 `BUILD_MANIFEST.json` 的 `service_package_sha256` + `Microduck-Robotd-FT6-R17.sha256` 三源 | 三源 + size=34138802 + embedded 复算 |
| `imu_ft6_bin`（旁证，非 contract slot） | `imu_to_feetech_ReVA_FT6_SYNC15_UART_IRQ_v1.bin` | `d7bd2f37…` | `imu-ft6.sha256` + ZIP 内 `updates/` 实算 | 双源 |
| `imu_node_firmware_020` | `.upstream/replica/…/imu_to_dxl.hex` | 双 sha（文件 + 解码镜像） | 走 `check_image_pairing.py --verify-sources`（既有 `LOCAL_COMPUTED`） | 不重复列 manifest |

> ⚠️ `imu_ft6_bin` 是 kissqy 的 **FT6 外置 IMU 板**固件，与 contract 的 `imu_node_firmware_020`（fanhao 复刻 STM32G031 / LSM6DSV16X 总线板 HEX）**是不同对象**，不得混、不映射 slot。

---

## 4. control.43 的证据升级与边界（用户"先核验再按机制改判"）

**核验结果**：control.43 固件包已从 V167 ZIP 抽出，本机实算 `bcfd5c18…` 与三处一手公布值逐字一致；元数据 `build=1fa8438-feetech-ft6-control.43` / `official_version=0.15.1` / `api_version=40` / `console_version=1.0.167`，ZIP 内 `BUILD_MANIFEST.json` 的 `service_build` / `official_baseline=1fa84386…` / `service_package_sha256` 与之同批次。**这把 control.43 从"连固件包都取不到"升级为"有本地实体 + 三源实算一致"。**

**按机制改判的落地方式（不改 contract `pin_kind`，理由如下）**：

- `image_pairing_contract.json` 的 `pin_kind` 描述的是**随仓库可分发的 distributable 状态**。契约自己 `known_gaps` 钉死："`.upstream/` 被 gitignore，默认不随仓库分发，其他 clone 报 `source_files_verified=false`"。
- 若把 `robot_firmware_control43` 从 `UNOBTAINABLE` 改成 `LOCAL_COMPUTED` 且 `local_file_present=true`，等于**向每个没有该文件的 clone 声称"本机有文件"**，制造新的假象，违背契约 owner 语义，也会波及 `check_image_pairing.py` selftest 里硬绑 `UNOBTAINABLE` 的两条断言 + 一条负对照。
- 因此采用契约**已有的 opt-in 模式**（同 `--verify-sources`）：contract `pin_kind` **保持不动**，本机实算证据由**正交的 `local_evidence`（B9）**承载。两个事实都真、互不覆盖：
  - *distribution 视角*：control.43 仍 `UNOBTAINABLE`（源码 `firmware/BUILD.json` 仍 404、不可自编译，且 clone 方无实体）；
  - *this-machine 视角*：B9 报 `robot_firmware_control43_pkg=LOCAL_COMPUTED`（本机固件包字节已实算配对）。

**仍不能宣称的**（元数据自述 + 项目铁律）：
- 元数据 `verification.physical_robot_operated=false`、`BUILD_MANIFEST.hardware_verified=false` ⇒ **发布方自己声明未上真机**；
- 源码 `firmware/BUILD.json` / `docs/BUILD.md` 仍 404 ⇒ **不能宣称可自编译 control.43**；
- 本机实算 sha 一致 ⇒ **只证明字节同一**，不证明能刷入、能启动、能过 `BA-X-1` 上板判据；
- **`ship_verdict` 仍 `NOT_SHIPPABLE`**，A2 / B1 悬案闭合数仍 0。

---

## 5. 到货当天可直接跑（把本文证据接回执行单）

```bash
# 0) 本机复验证据（已有下载文件时；fresh clone 会诚实报 PENDING）
.venv-mjlab/Scripts/python.exe tools/hd1910/local_evidence.py --verify --json

# 1) 四元组结构 + 随仓库可验证的 source（contract pin_kind 不动）
.venv-mjlab/Scripts/python.exe tools/hd1910/check_image_pairing.py --check --verify-sources .upstream

# 2) 做卡（不执行 dd，只校验配方 + flag 审计）
.venv-mjlab/Scripts/python.exe tools/hd1910/reproducible_card.py --check --verify-sources .upstream --flags "--overlay i2c4-m0"

# 3) 到货后按执行单 §1-§3 逐 --record；COLLECTED != PASS，闭合仍要人工签字
```

**§5 三入口 2026-11-12 本机实跑复核（全部 rc=0，工具链就绪证据）**：上述命令 0/1/2 已按字面在本机真跑一遍，确认 P0 下载的 4 个实体被三个下游消费端正确读取——`local_evidence.py --verify`=`ALL_LOCAL_COMPUTED`（4/4 实体本地 sha 与发布 pin 一致）、`check_image_pairing.py --check --verify-sources .upstream`=`structure PASS / source_files_verified=true`、`reproducible_card.py --check --verify-sources .upstream --flags "--overlay i2c4-m0"`=`structure PASS / audited flags refused=none / source_files_verified=true`。三者 `ship_verdict` 均 `NOT_SHIPPABLE`。**这只证明"到货当天照抄不会因工具/路径/实体缺失当场炸"，非上板验收**；完整判据表见执行单 §8。

> **本机 A2 门禁红灯自助判读**：本机跑门禁会看到 48/50 / 2 pytest failed / `check_closure.py --check` rc=1，这是**未入库安卓草稿文档**被文件系统扫描计入导致的已知本地假红，CI 干净树 8=8 绿。到货当天先跑 `.venv-mjlab/Scripts/python.exe tools/hd1910/check_closure.py --explain`（只读、恒 rc=0）：`committed structure=PASS` 即为假红可继续；`FAIL` 才是真回归。三条禁路与正确闭合时机见执行单 §8。任何 tracked 文档都不得写出那条第 9 标记的**字面全名**（会反噬 CI），故此处只用中文描述。

**bug 修复记录（真跑抓出、已加负对照防回归）**：`grade()` 曾有 3 个会改变判决的自身 bug——①存在文件分支漏 `results.append`（导致 selftest 越界 / 正常 artifact 消失）；② `git_blob_sha1` 匹配时误把 local sha 塞进 mismatches（V167 假红）；③ 下载中半成品被笼统判 MISMATCH（伪造"损坏"结论）。三者均已修 + selftest 覆盖。**本轮 `--explain` 又抓出 1 个 CLI-only bug**：`grade_env` 的 `committed_view_markers` 直接返回 `set`，文本模式正常但 `--explain --json` 会 `TypeError` 崩溃；已改 `sorted()` 并加 `test_explain_cli_json_is_serializable_and_not_a_gate` 守卫（只测内部函数会漏掉，必须真跑 CLI）。

---

## 6. 边界不变式

`ship_verdict=NOT_SHIPPABLE` · `live_hardware_accessed=false` · A2 七悬案闭合 0 · D1「暂缓低层重训」保持 DEFERRED（主板到货不重开）· 采购域 6/6 `BASELINE_MATCH`、手改 xlsx 零改动、untracked 不入库。
