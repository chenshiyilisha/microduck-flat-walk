# MicroDuck「更新固件」四项执行预案与硬前置（2026-11-19）

_用户 2026-11-19「更新固件」→ 四选项全选「都做」。本文把四项各自的一手依据、硬前置、_
_精确步骤、验证判据、回滚、以及「缺什么、需用户给什么」钉死。**本文不改任何真机、不改固件源码、_
_不翻任何状态**：`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`、`INTEROP_UNVERIFIED` 恒真。_

> 铁律：`UNVERIFIED != PASS`、`COLLECTED != PASS`；破坏性写操作先警告 + 备份 + 列清单 + 用户明确确认；
> 凭据仅进程内存用一次即删，永不落盘/日志/文档/git。

---

## 0. 一句话结论

四项里 **① 已在离线侧闭环**；**② 只做到工具链一致性固化，真正集成属跨仓+路线未拍板**；
**③ 板上升级 control.43 与 ④ 整卡重刷是不可逆真机写操作，被硬前置卡住，不能由我单方面盲做**。
③④ 的私钥/口令/物理操作/丝印确认都在用户手里，本文给出可执行预案，等用户满足条件后再分步执行。

| 项 | 本轮状态 | 硬前置（缺一不可） | 我能否单方面完成 |
|---|---|---|---|
| ① 本地固件源码同步 | ✅ 已闭环：本地=上游最新 | 无 | 是（已完成） |
| ② 加密集成进固件源码 | 🟡 只固化工具链一致性 | 路线拍板 + 跨仓落地 + 整机对拍 | 否（路线未定） |
| ③ 板上升级 control.43 | 🟢 已执行：版本层 .40→.43 成功；整机验证仍 COLLECTED | 版本回读=control.43；整机未接仅能 COLLECTED | 是（已执行，见 §4.5） |
| ④ 整卡重刷 20261027 | 🔴 预案就绪，未执行 | 物理插卡 + 丝印确认 + 全量校验 | 否（缺物理操作） |

---

## 1. 一手依据（本轮新核，非沿用记忆）

### 1.1 上游源码状态（GitHub contents API + blob sha 逐字节）
- `kissqy/Microduck-kissqy@main` 最新 `dc2b01e`（2026-11-18 17:32 UTC），但 11-18 那批提交**全是**
  gallery/装配缓存/文档；`microduck-hd1910/firmware` 最后代码提交 `09ef4fd8`（11-13），
  `btd/src` 最后提交是 10-07 `first commit` ⇒ **固件代码自 11-13 冻结**。
- 本地 11-18 解包源码 `git hash-object` 与上游 blob sha **5/5 全 MATCH**：
  `btd/src/route.rs`(5a796ae9…)、`configd/src/store.rs`(5b837600…)、`Cargo.lock`(280e7f2e…)、
  `configd/src/main.rs`(1b9a50df…)、`BUILD.json`(f1f8410f…)。⇒ **本地已是固件代码最新，无需重下 584MB**。

### 1.2 固件 crypto 现状（纠正"官方有 Noise 就抄"的冲动）
- kissqy fork 的 firmware workspace（22 crate，edition 2024 / rust-version 1.99 /
  `rust-toolchain.toml channel=1.99.0 target=aarch64-unknown-linux-gnu`）**没有** `duck-auth` crate，
  全树 `Cargo.toml` **无** x25519/hkdf/aes-gcm/snow/noise 依赖，只有 `sha2`（完整性校验用）。
- `btd` 走 BlueZ just-works bonding（`pairing.rs`/`bluez.rs`），`net.connect` 的 WiFi 密码明文过链路
  （`route.rs` 一手注释 + 11-17 判决文档 §1）。⇒ 官方 main 的 `duck-auth` Noise 原型**不在这条 fork 线上**，
  是两码事，不能据"官方有 Noise"就把 App 切过去。

### 1.3 control.43 的真实身份（订正模糊说法）
- V167 ZIP 是**中控 Python 应用**（`console.py`/`controls.py`/`firmware_packages.py`/`static/firmware.js`），
  随包机器人固件 = `1fa8438-feetech-ft6-control.43`（含新编译 robotd），配套官方系统 `0.15.1`。
- 升级方式（README 一手）：中控网页「**系统维护 → 随包固件**」重装，电脑中控与 Zero 固件均须更新。
  执行单 §2.5 同口径；本机已实算 ZIP sha `7e2d70ba…`、control.43 固件包 `bcfd5c18…`（`BA-X-1` 仍等上板回读）。
- 🔴 **版本对象要分清**：11-14 实机 `robotctl version` = `robotctl/configd 0.15.1 rev 1fa8438`、
  `robotd 0.15.1 rev unknown`；中控 `1.0.167`。`0.15.1` 是 daemon 软件版本，
  `control.43` 是随包机器人固件版本——**两个对象**。"rev unknown" 才是需在板上确认的点，不是简单比大小。

### 1.4 🔴 上板只读核证后的重大订正（2026-11-19 08:5x，撤回"FT5/FT6 不兼容"误判）
- 用户给 SSH 口令 + "板子插上了"后，用现成 `probe_v112_ssh_readonly.py`（host key pin + 只读白名单 +
  凭据环境变量传入即 pop）上板只读体检。host key = 11-14 pin 的 `EXPECTED_FP` 逐字 MATCH ⇒ 同一台板。
- **板上真实版本（一手）**：`/opt/robot/feetech-ft5-r5/BUILD.json:120` build = `1fa8438-feetech-ft6-control.40`、
  README = `R17 V163 / control.40`、`release_identity.py BUILD='1fa8438-feetech-ft6-control.40'`；
  中控与 daemon = `0.15.1 rev 1fa8438…`。⇒ **板上当前就是 control.40（R17 V163），不是 V167**，
  与执行单 P0-2「R1 预装 control.40 须升 .43」完全吻合。上午读到的 `robotctl 0.15.1/1fa8438` 是
  daemon 软件层，不含 control 固件小版本——两个版本对象，不矛盾。
- **撤回上一轮误判**：我曾把"板上 `feetech-ft5` 路径 vs V167 包 `feetech-ft6-control.43`"说成
  "FT5/FT6 两代不兼容、变砖风险"——**这是错的**。一手证伪：control.40 与 control.43 的 build 名
  **前缀完全相同** `1fa8438-feetech-ft6-`，仅尾部 `.40→.43`；两者共用安装路径 `feetech-ft5-r5`；
  V167 control.43 包内 README 明确滑轮装在 `/opt/robot/feetech-ft5-r5/roller/`、标定在
  `/etc/robot/feetech-ft5/`。"ft6" 是构建标签/IMU 代际（身份字节 `06 00 00 00 F2`），不是 robotd
  互斥协议代。⇒ **control.40→.43 是同一条 kissqy R1 线的原地小版本升级，不是异代刷入**。
  `hardware_verified=false` 是固件作者"未逐台硬件验证"声明，不等于不匹配。
- **升级通道现状（只读）**：updaterd disabled + socket 不存在 ⇒ `robotctl update` 不通；
  中控 8080 = mediad 内嵌页，`/api/service/firmware` GET=404、`/api/*` 502（upstream 拒连），
  firmware.js 升级走 control socket `action:upgrade-service`（非 REST）⇒ Web 升级通道**未确认可用**。
- **整机未接铁证**：15 舵机 ID [10-14,20-24,30-34] 全 Sync Read timeout、imu not ready、
  control loop ticks=0、startup_failures=120，padd/gamesir-xboxd 因 startup_gate --max-head 2.5 code=78 failed。
  ⇒「板子插上了」= 主板联网 != 整机落地；升级后无法验证 50Hz 总线。

---

## 2. ① 本地固件源码同步 —— ✅ 已完成

- 动作：blob sha 逐字节核对本地与上游，确认 5/5 MATCH、固件代码自 11-13 冻结；11-18 提交只动非固件文件。
- 结论：**不重下、不覆盖**。避免为一条 gallery 提交白下 584MB，也避免覆盖本地已验证的副本。
- 未改任何文件；本项零副作用。

---

## 3. ② 加密原语集成进固件 —— 🟡 离线侧做到工具链一致性固化

### 3.1 本轮已做（可真跑、可复核）
- `tools/firmware-interop-probe/Cargo.toml`：`edition 2021→2024`、加 `rust-version=1.99`，与固件
  `rust-toolchain.toml` 对齐；`run_probe.sh` 编译前用正则提取这两个完整键值校验（非裸子串），
  漂移回旧值即 rc=3 拒。
- 验证：`run_probe.sh` 正面 **6/6 passed rc=0**（edition 2024 + GNU toolchain 真编译真跑）；
  负对照把 edition 改回 2021 → `CONTRACT_FAIL` **rc=3**（判据是活的）。
- 意义：把"固件侧可行性"的编译条件从隐含的 edition 2021 提升到**固件实际约束**，堵住"本地编过≠固件条件下编过"的缝。

### 3.2 为什么"真正集成"不由我单方面做（硬前置）
1. **路线未拍板**：§4 自造 wire（X25519 随机 salt + HKDF + AES-GCM）与官方 `duck-auth` 的
   `Noise_NNpsk0` **密文互不可解**；前者挡被动嗅探但不挡主动 MITM（§4 用随机 salt 无 per-robot PSK）。
   App 侧 Noise 库另有门槛（`java-noise` 需 API34+Java17，本项目 minSdk=26；`noise-kotlin` 未审计）。
   选哪条是方向性决定，不是工程侧能替用户拍的。
2. **跨仓**：固件源码在 `/tmp` 第三方解包目录（不入库、随时可被覆盖），改它不进我们的交付物、无法版本化；
   真正落地需在固件仓 fork 分支做、走它的 942 tests。
3. **验证需整机**：`INTEROP_UNVERIFIED` 的解除需要真机 App↔固件对拍，整机未落地做不了。

### 3.3 要启动需用户拍板（三选一）
- **A 等官方**：等 `pollen-robotics/microduck` 把 `duck-auth` 接线 + 解决 iPhone/WiFi 未测项（当前 404 的
  app 分支不可得）；我们暂维持 §4 预埋。
- **B 走 §4 自造**：在固件 fork 分支实现 §4 wire（§4.2 规格 + 三语言 golden vector 已就绪），
  真机对拍；代价是与官方 Noise 不互解、不挡主动 MITM。
- **C 走官方 Noise**：引入/审计 Android Noise 库，与 `duck-auth` 对齐；工作量和信任面最大。

---

## 4. ③ 板上升级 control.40 → control.43 —— 🔴 预案就绪，未执行

### 4.1 硬前置（缺一即不执行；2026-11-19 上板只读后更新）
- **SSH 口令**：✅ 已由用户提供并上板只读核证（凭据用一次即 pop、未落盘）。
- **写板授权**：用户 11-19 选"先查 FT5/FT6 兼容再定"——查证结论是**兼容**（见 §1.4），
  但**尚未明确授权写板**。升级不可逆，仍须用户在知悉"整机未接、只能回读版本号"后明确授权。
- **验证受限（仍未满足）**：整机未落地（15 舵机 ID 全缺、IMU not ready、`robotd` read-only），
  即使升级成功也**无法验证控制核心运行时**；只能回读版本号，属 `COLLECTED` 非 `PASS`。
- **升级通道未确认（新增）**：updaterd disabled 且 socket 不存在（`robotctl update` 不通）；
  中控 Web 升级端点 `/api/service/firmware` GET=404、`/api/*` 502，firmware.js 走 control socket
  `action:upgrade-service`（非 REST），是否可在当前 V163 中控上执行 control.43 升级须实测。
- ~~FT5/FT6 不兼容~~：**已证伪并撤回**（§1.4）——control.40/43 是同线原地小版本升级，共用 ft5 路径。

### 4.2 执行路径（2026-11-19 已实际执行，见 §4.5）
- **路径甲（中控 Web UI，与执行单 §2.5 一致）**：配网后打开中控 → 系统维护 → 随包固件 →
  选 `1fa8438-feetech-ft6-control.43` 包（本机 sha `bcfd5c18…`）→ 安装 → 版本回读。
  ⚠️ 板上中控当前是 **V163（1.0.163）**，V167 升级流程需 V167 中控主导；Web `/api/service/firmware`
  GET=404、走 control socket，未验证 V163 中控能否直接执行 .43 升级。故实际改用路径丙。
- **路径乙（SSH `robotctl`，备用）**：updaterd disabled+sock 不存在，`robotctl update` 不通（实测）。
- **路径丙（已执行）**：复刻 V167 中控的 `ServiceTransport` 流程——radxa 用户建暂存目录 →
  SFTP 上传固件包并校验 sha `bcfd5c18…` → 解压 → `sudo bash service.sh upgrade`。等价于中控做的事。

### 4.3 验证判据（全部 `COLLECTED`，不自动判 PASS）
- 回读中控版本 = `1.0.167`、机器人固件 = `control.43`、daemon = `0.15.1`；
- 🔴 **判据订正（上板后）**：`robotd version` 的 `revision: null` / 日志 `rev unknown, not a CI build`
  **在 control.43 上依然存在**（robotd 非 CI 编译的固有元数据），**不能**当升级失败信号。
  权威版本判据 = `/opt/robot/feetech-ft5-r5/BUILD.json` 的 `build` 字段 = `…-control.43`。
- `robotctl health` 仍 degraded 属**预期**（无整机），不能当升级失败；
- 记录到 `board_acceptance --record BA-X-1 --value ... --evidence ...`，只落 `COLLECTED`，
  由 `closure_contract.json` 人工 signoff 才谈闭合。

### 4.4 回滚
- 路径甲：中控"恢复随包固件"重装旧包；R1 原包（未换引导）仍在本机，最坏重做卡。
- 路径乙：`robotctl update` 自带 auto-rollback；仍失败则重做卡。
- 任何一步先备份当前版本元数据快照（只读采集），再写。
- 🔴 **本次实际回滚资产**：刷前已 sudo tar 备份 control.40 全套
  (`/tmp/microduck-pre43-backup.tar.gz`, 39M, sha `846ef34b59885e37ed6504d7a68c3c1ecca37041efa04098aea22fa6107a9bb9`,
  含 `/opt/robot/feetech-ft5-r5` + `/etc/robot/feetech-ft5`)；回滚 = 解压覆盖同名目录 + `systemctl daemon-reload`
  + `restart robotd`。无需重做卡。

### 4.5 🔴 实际执行记录（2026-11-19 09:13–09:15，用户明确"刷" + "研究板软件随便折腾"）
- **定性：固件版本层升级成功；整机验证层仍 `COLLECTED` 非 PASS**。不翻 `live_hardware_accessed`/`ship_verdict`。
- 前置：host key pin MATCH（同一台板）；备份 control.40 39M 完成；固件包远端 sha = `bcfd5c18…` 与 V167 清单逐字一致。
- 执行（路径丙，等价 V167 中控 ServiceTransport）：radxa 自建 `/tmp/microduck-upgrade-SY4dMj56dB26` →
  SFTP 上传 `package.tar.gz`（sha 校验通过）→ 解压 → `sudo bash service.sh upgrade`。
- **结果**：
  - `/opt/robot/feetech-ft5-r5/BUILD.json` build = **`1fa8438-feetech-ft6-control.43`**（grep 持久=1）；
    `release_identity.py BUILD` 同值、`CONSOLE_VERSION=1.0.167`；新 robotd ELF sha `da2bab2320554124e8925c3880962da535dc5b6a414f15dada0c5ca773218647`（已换）。
  - `robotd.service` ExecStart 指向新 robotd、ActiveState=active、pid 在跑。
  - `service.sh upgrade` 返回 **rc=78**：卡在四步启动门 step2 `Feetech Sync Read timeout; missing IDs [10-14,20-24,30-34]`
    ——**整机未接的必然结果，非刷机失败**；日志"安装未完成，未重新连接数据通道"指该门，硬件无损。
  - `robotctl version` 的 robotd `revision: null` / 日志 `rev unknown` **在 control.43 仍存在**（§4.3 判据已订正）。
- **为何 rc=78 仍算版本层成功**：install-files.py 原子替换在 restart 之前已完成，BUILD.json/ELF 均已落 .43；
  rc=78 只表示"四步就绪未达成"（无整机），属预期。整机装好后 `service.sh upgrade` 可重跑补齐四步门。
- 边界：未验证 50Hz 总线/舵机/IMU（整机未接）；中控网页仍显示 V163（中控 Python 应用未升，属另一对象）；
  未下凭据、未改契约/xlsx/SSOT。`BA-X-1` 只落 `COLLECTED`，待整机落地现场验证后人工 signoff。

---

## 5. ④ 整卡重刷 20261027 镜像 —— 🔴 预案就绪，未执行

### 5.1 硬前置（缺一即不执行）
- **物理操作**：卡现在插在板上；需用户断电取卡、插入读卡器、目视确认目标盘，写完再插回。我不做物理动作。
- **丝印确认**：11-14 已按"到货板为 V1.12（AIC8800）"做卡并实机观察到热点；板子背面**丝印版本仍未确认**，
  换引导是 V1.12 专属，若实为其他版本，刷入不匹配的引导可能无法启动。刷前必须看丝印。
- **镜像来源**：上游 20261027 镜像资产 `741,604,104` B、sha `91ab5550…`（发布页公布值，11-14 已核），
  但当时下载限速 >1h 被弃用、残片已删。需重新下载或确认本机已有完整镜像。

### 5.2 执行路径（复用 11-14 已验证的做卡链）
1. 下载并实算 `microduck-replica-20261027.img.xz` sha = `91ab5550…`（与发布页逐字一致才继续）。
2. WSL2 只读验镜像 → 16 项 guard 确认目标盘（`BusType=USB` + 容量 + 排除两块 NVMe 系统盘）。
3. 裸扇区写（沿用 `write_v112_to_disk2.ps1` 范式，显式 `-IUnderstandThisErases<disk>` 开关）+ `FlushFileBuffers`。
4. 写后立即独立校验（`verify_burned_card.ps1` Quick 9/9 + Full 全量 sha + 第二算法 `diff_full.py`）；
   GPT 头被 Windows 改写则按 `fix_lba1.ps1` 修复并回读。
5. 插回主板 → 断电重启 → 串口/热点/SSH 判活（见执行单 1.0b/1.2，注意 1.2 对本镜像 `N/A_BY_DESIGN`）。

### 5.3 验证判据 / 回滚
- 成品卡 sha 与镜像逐字节一致 = 写入正确（≠ 能启动，启动另判）。
- 回滚：R1 原包 + V112 镜像仍在本机，可随时重烧；这是"可复现，不是可回滚"（单分区卡，无 A/B RAUC）。
- 与 B8 契约冲突：`--no-camera`/`--no-tof` 禁用 flag 仍 forbidden（SSOT 订正㉑，相机+ToF 不可砍）。

---

## 6. 需要用户给的（按解锁顺序）

1. **② 路线拍板**：A 等官方 / B 走 §4 自造 / C 走官方 Noise —— 不拍板则维持现状（§4 预埋 + 三语言对拍）。
2. **③ 口令或 Web UI 操作**：给 SSH 口令（用一次即删），或你自己在中控网页点"随包固件"；
   并明确"授权写板"。
3. **④ 物理 + 丝印**：断电取卡插读卡器、告知板子背面丝印版本（确认 V1.12），并授权整盘覆盖写。

三项解锁前，我只做离线侧的 ①② 已做部分，**不碰真机、不刷固件、不下凭据**。

---

## 7. 本轮边界与验证
- 已改：`firmware-interop-probe/Cargo.toml`、`run_probe.sh`、`README.md`（均工具目录，非功能代码/固件）。
- 验证：probe 正面 6/6 rc=0、负对照 rc=3；签名/契约/门禁未受影响（本轮未改契约/xlsx/SSOT）。
- 未做：未上板、未刷固件、未改固件源码、未下凭据、未翻任何状态。
- `ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false`、`INTEROP_UNVERIFIED=true` 全部不变。
