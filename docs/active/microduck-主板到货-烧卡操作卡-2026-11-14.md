# 主板到货 · 烧卡操作卡（2026-11-14 现场）

_2026-11-14。回应「可以了，F 盘」——读卡器就位后的**最优执行路径**。本卡只做「把可启动系统写进空白 microSD」，不改任何判据、contract、SSOT 或 xlsx。_

## 0. 一句话结论

**镜像已在本机做好并验证完毕，只差把 `V112.img` 写进 F 盘这一步（不可逆写盘，留给你在工具里目视确认目标盘后点 START）。**

---

## 1. 现场只读检测（本机实测，非推断）

| 项 | 实测值 |
|---|---|
| F 盘 | `FAT32` / 卷标空 / `62,304,288,768` B（≈58 GiB）/ `DriveType=2 Removable` / Health Healthy |
| 对应物理盘 | **Disk 2**，`Mass Storage Device`，`BusType=USB`，`62,325,260,288` B，`MBR`，`IsBoot=False`，`IsSystem=False` |
| 盘内内容 | 仅 `System Volume Information`（Windows 自动生成），**无任何用户数据** |
| 系统盘 | Disk 0 = Samsung 990 PRO 1TB (NVMe)，Disk 1 = KIOXIA 1TB (NVMe) ⇒ **目标 Disk 2 与系统盘可明确区分** |
| 本机烧卡工具 | ❌ 无 Etcher / Rufus / Win32DiskImager（全盘扫描无命中）⇒ 本轮新取便携版 |
| WSL2 | `MicroDuckUbuntu` WSL2，root，`/dev/loop-control` + `/dev/loop0` 可用，`dd/xz/sha256sum/losetup/dpkg-deb/mount/python3` 齐全，虚拟盘 950 GB 可用 |
| 空间 | E: 剩 836 GB，足够放 3.0 GB 产出镜像 |
| gitignore | `.upstream/` 已忽略；实查 `git ls-files` 确认既有 R1 镜像未入库 ⇒ **本轮所有二进制都不会进库** |

---

## 2. 路线决策（本轮改了两次，都是被新事实推着改，留档）

### 2.1 ① 本仓既定 kissqy R1 —— 一度被 404 卡死，已修复

- `kissqy-r1-v112.sh` 与 `build-armbian-card.sh` 依赖同一个瑞莎 deb：`radxa-repo.github.io/bookworm/.../u-boot-rk2410_2017.09-64-39cd993_arm64.deb`。2026-11-14 实测该 URL **与仓库目录根都返回 404**，本地原本也无缓存。
- 检索到**南阳理工学院开源镜像站** `mirror4.nyist.edu.cn/radxa-deb/bookworm/pool/main/u/u-boot-rk2410/` 有同名同版本 deb（17.6 MiB）。已下载到脚本目录（脚本 `DEB="$HERE/$(basename ...)"` 会跳过 curl 直接用本地文件），本机实算 sha256 = `fb319203ab7d568aac77505504c05698385aea8a0e8f895c226c6bc557a1bce7`，**与脚本内 pin 逐字一致**。
- ⇒ ① 复活，且全程零联网依赖。

### 2.2 ② 上游最新 20261027 —— 资源核实无误，但下载不划算

- GitHub REST API 实测资产 `microduck-replica-20261027.img.xz` = `741,604,104` B；`.sha256` = `91ab5550e0f409d634722718a638d6e9615412b779b5d26c0af5c777056d0194`，与 `superpowers/verification/2026-10-27-web-updates-publication.md` 记录**逐字一致**；Etcher 便携版资产 `284,199,765` B 也在。
- 但实际下载速度从 ~200 KB/s 衰减到 ~120 KB/s，707 MB 预计 **>1 小时**；Etcher 便携版 284 MB 同样慢。已停止后台任务并**删除 31,289,344 B 未完成残片**（保留 1,159 B README 与 100 B sha256 作留档）。
- ⇒ ② 降级为「以后要用网页升级 / 新功能时的备选」，**本次不采用**。

### 2.3 最终选 ① 的理由

本机 R1 原包（732 MB，`75da978b…a7bce5`，已与 contract pin 比对）+ 已验 deb + 现成 WSL2 ⇒ **零下载、版本链与 `card_build_contract.json` 一致、不引入新版本变量**。这也是上一轮给出的原始建议，本轮补齐了缺失依赖并做完了最难的一步。

> ⚠️ **最大未验证点：板子丝印版本仍未确认**。换引导是 **V1.12（AIC8800）专属**（脚本头注、R1 分析 §4/§7）。本次按「到货板为 V1.12」执行；若背面丝印是 V1.12J 或其他，请告知——R1 原包（未换引导）仍在本机，可随时重烧，或走 ② 镜像。标 `UNVERIFIED_hardware`。

---

## 3. 已完成的构建与独立验证

**构建**（WSL2 前台执行，7/7 步全过，未联网、未碰 F 盘）：

```
bash kissqy-r1-v112.sh microduck-zero3w-0.15.1-R1.img.xz --overlay i2c4-m0
→ microduck-zero3w-0.15.1-R1-V112.img
```

| 产出 | 值 |
|---|---|
| 路径 | `microduck-software/.upstream/downloads/microduck-zero3w-0.15.1-R1-V112.img` |
| 大小 | `3,157,262,336` B（3.0 GB，**未压缩 raw img，直接烧，不要再解压 xz**） |
| sha256 | `d8207edea3a3abf8234cb16cf18c859c94292ca492e5f2eff3a981e2fbd24f41` |
| 双工具复核 | WSL `sha256sum` 与 Windows `Get-FileHash` 结果逐字一致 |

**独立验证**（`verify_v112.sh`，判据取自 deb 与 R1 原包，**不取自脚本自身输出**）：

- ✅ 镜像扇区 64 md5 `fa3fd676…` = deb 内 `idbloader.img` 首扇区 md5
- ✅ 镜像扇区 16384 md5 `77b5b117…` = deb 内 `u-boot.itb` 首扇区 md5
- ✅ **负对照**：R1 原包同两处扇区分别为 `eec9148e…` / `846a40f2…`，**与换引导后完全不同** ⇒ 改动确实发生，不是假绿
- ✅ 只读 loop 挂载 rootfs：`/boot/extlinux/extlinux.conf` 含 `rk3568-i2c4-m0.dtbo`、`vmlinuz-6.1.115-vendor-rk35xx`、`rk3566-radxa-zero3.dtb`、`root=UUID=34d3c17e…`；`/etc/microduck-v112-image.txt` 标记 `no-camera=0 no-tof=0`（遵守订正㉑，未勾 `--no-camera`/`--no-tof`）

---

## 4. 写盘（2026-11-14 已执行完成）

> ✅ **实测结论（优先于下文 GUI 预案）**：用户授权「你来操作」后，本轮**没有用 Rufus GUI**，改用自写、可审查的 `write_v112_to_disk2.ps1` 做裸扇区写；写后发现并修复了 Windows 对 GPT 头的自动改写。**最终卡的前 3.0 GB 全量 SHA-256 = 镜像 `d8207ede…24f41`，逐字节一致，Quick 9/9 + Full 10/10 PASS**。详见 §4.6。下文三步保留为「人工 GUI 备选 / 复现路线」。

**⚠️ 这是整盘覆盖写操作：F 盘（62.3 GB）现有内容会被全部清空。**本轮执行前已机械确认是空白新卡、无用户数据，16 项 guard 全过（含排除两块 NVMe 系统盘）才写第一字节；写盘由用户在 14:45 明确授权，非擅自执行。

工具：`microduck-software/.upstream/downloads/rufus-4.15p.exe`（1,989,992 B，Rufus 4.15 便携版，来自 `pbatard/rufus` Release，无需安装；双击运行，若弹 UAC 允许）。

1. **设备**：在 `Device` 下拉里选 **`F: / Mass Storage Device / ~62.3 GB / USB`**。🔴 绝不能选 Disk 0 / Disk 1 两块 NVMe 系统盘。
2. **镜像**：点 `SELECT` → **把文件类型过滤器从默认 ISO 切到 `DD Image`（或「所有文件」）** → 选 `microduck-zero3w-0.15.1-R1-V112.img`（3.0 GB raw img）。
3. **写**：点 `START` → 弹出模式选择时**必须选 `DD Image mode`**（逐字节写入；若误选 ISO 模式，卡不能启动）→ 确认清空警告 → 等进度走完。
4. 写完 Windows 若弹「需要格式化」一律点**取消**（`烧录和第一次使用.md` §2 第 4 条，烧完的 ext4 分区 Windows 读不了是正常的）。安全弹出 → 卡插回主板 → 按执行单 1.0b 完整断电重启。

> 📚 **工具依据分级（2026-11-14 复核后收窄）**
> - ✅ **二进制出处与完整性已双证核实**：本机 `rufus-4.15p.exe` 为 1,989,992 B、版本 4.15.2396；sha256 `84c8a437f8af89257524478489e5c85f1edf25f761d299e2bcde46ac0afbe106` 与 GitHub REST API `pbatard/rufus` tag `v4.15` 中同名资产的 `digest` **逐字一致**；`Get-AuthenticodeSignature` = `Valid`、签发者 `Akeo Consulting`（与 Rufus 项目站点 `rufus.ie` 声明的签名主体一致）。⇒ 不是来路不明的第三方二进制。
> - ✅ **`DD Image mode` 是 Rufus 既有功能**：Rufus 项目 FAQ 目录含专条 `Why doesn't Rufus recommend DD mode over ISO mode for ISOHybrid images?`；`rufus.ie` 列明该版本便携版；IBM Storage Defender 文档、ArchWiki、MiniOS wiki 等多源一致描述为「block-for-block / byte-for-byte 逐扇区写入」。⚠️ 但本机 `github.com/pbatard/rufus/wiki/FAQ.md` 实抓超时/502、`raw.githubusercontent.com` wiki 路径 404、exe 内也搜不到明文 UI 字符串（资源被压缩）⇒ **没有拿到页内逐字原文**，这条按「多源一致 + 项目一手目录」记，不冒充页面实访。
> - ⚠️ **仍 `UNVERIFIED_hardware` 的只剩一件事**：本镜像 / 本卡 / 本板**用 Rufus DD 模式写入后能否启动**，从未实机验证。上游 `烧录和第一次使用.md` §2 指定的一手工具仍是 **balenaEtcher / Raspberry Pi Imager**（支持 `.img.xz` 直烧），本次因 Etcher 便携版 284 MB 下载限速而改用 Rufus，属**替代方案**，如实保留。若后续 Etcher 下载完成，可优先按上游原文重烧。
> - 🔴 写盘后的内容正确性由 §4.5 的独立校验承担；**校验通过也不能替代上板启动判据**（§5 / 执行单 1.2）。

---

## 4.5 写盘后立即做：独立校验（本轮新增，替代「只看工具说完成」）

**为什么**：准则 12 —— 工具打印「完成」不是证据；判据必须是**产物 + 独立比对 + 负对照**。

工具：`microduck-software/.upstream/downloads/verify_burned_card.ps1`（纯 ASCII、全程 `FileAccess.Read`，**绝不写盘**；本机实测只读打开物理盘不需要管理员）。

```powershell
cd "E:\WorkBuddyData\WorkBuddy\2026-10-23-08-26-15\microduck-software\.upstream\downloads"
powershell -ExecutionPolicy Bypass -File .\verify_burned_card.ps1              # Quick，秒级
powershell -ExecutionPolicy Bypass -File .\verify_burned_card.ps1 -Mode Full  # 追加 3.0 GB 全量 SHA-256
```

判据：
- 9 个采样点逐点 md5 比对：`MBR/sector 0`、`sector 64 (idbloader)`、`sector 16384 (u-boot.itb)`、64/256/512 MiB、1/2 GiB、尾 -1 MiB；
- 目标盘自动发现强制 `BusType=USB` + 55–70 GB + `IsBoot/IsSystem=False`，拒绝命中两块 NVMe 系统盘（**负对照**）；不依赖烧卡后可能消失的 `F:` 盘符；
- 诊断区分「空卡全零」「仍是出厂 MBR/FAT32」「内容不符」，任何一项都不会被误报成绿。

**交付前已做的正负对照（2026-11-14 实跑）**：

| 模式 | 结果 | 退出码 |
|---|---|---|
| `-SelfTest`（镜像对自身，不开物理盘） | 9/9 OK、**PASS** | 0 |
| 当前空白卡 | 9/9 DIFF、**FAIL**，诊断 `CARD STILL HAS FACTORY MBR/FAT32 layout` | 2 |

> ⚠️ 边界：该脚本只证明「卡内容 == V112.img」，**不能证明能启动**；启动仍按 §5 / 执行单 1.2 判。第一版脚本曾把「前 1 MiB 全零」当空卡负对照，对已格式化的 FAT32 卡误报绿 —— 已按实读的 MBR 特征修正，详见 SOP 坑 17–20。

---

## 4.6 实测：裸写 → 抓到 GPT 头被改写 → 修复 → 全量通过

**写入脚本** `.upstream/downloads/write_v112_to_disk2.ps1`（必须显式传 `-IUnderstandThisErasesDisk2`，防误跑；不带开关的 dry-run 实测 `exit 3` 拒绝）。管理员权限下：16 项 guard → `FSCTL_LOCK_VOLUME` + `FSCTL_DISMOUNT_VOLUME` → 4 MiB 扇区对齐流式写 → `Flush(true)` + `FlushFileBuffers` → 解锁。实测 **3,157,262,336 B / 191.8 s / 15.7 MiB/s**，`exit 0`。

> 📚 依据（写前查资料，多源一致）：Windows 裸写物理盘须先让卷层退出，否则报 `Access denied`；块须扇区对齐；**`FlushFileBuffers` 不能省**（写缓存会掩盖真实落盘错误）；写入过程中不要调 `Get-Disk`。本机实测 `Set-Disk -IsOffline` 对可移动介质报 **"Removable media cannot be set to offline"** ⇒ 只能走 LOCK/DISMOUNT 路线。

**🔴 写入成功 ≠ 写对**：首次 `verify_burned_card.ps1` Quick 报 **8/9**，前 1 MiB 不一致，`Get-Disk` 分区样式从 MBR 变 GPT。按铁律没有跳过、没有迁就判据，而是逐层定位：

1. 前 1 MiB 逐扇区比对 ⇒ **只有 LBA1 的 12 字节不同**（偏移 16–19 / 33–35 / 49–51 / 72–73）；MBR、LBA2–2047（分区项）、扇区 64 idbloader、16384 u-boot.itb 全部一致。
2. **独立第二算法**（`diff_full.py`，纯 Python 只读物理盘，不依赖 PowerShell 校验脚本）全量扫 753 块 / 3,157,262,336 B ⇒ **仅 1 个差异块、总计 12 字节**，镜像 sha `d8207ede…24f41`、卡 `b9982a83…`。
3. 解析 GPT 头：`AlternateLBA` 6,166,527→121,729,023、`LastUsableLBA` 6,166,494→121,728,990、**`PartitionEntryLBA` 2→2016**、`HeaderCRC32` 重算；而 LBA2016 读出全 `FF`（无有效分区项），真正的分区项仍在 LBA2 ⇒ 头与数据不一致，不能带着上板。
4. **一手规范**：UEFI 2.11 §5.3.2（`uefi.org` 实访）GPT Header 字段表逐字段对上上述偏移，并明写「卷容量变化时主/备 GPT 头必须更新」「主 GPT 无效时用备份 GPT 恢复」；微软《Windows and GPT FAQ》确认 Windows 用 CRC32 维护主/备表。社区资料把该现象命名为 **"Disk size mismatch … Common when restoring images"**。
5. **同项目同板的实战记录**：DAMO 开发者矩阵《Microduck 零基础部署调试实战》§0.2「Windows 烧录工具导致分区表被清空」明写 Armbian imager / Etcher / Rufus 写后会被 Windows 分区管理干扰、自动重生成 GPT；修法含「WSL 里的 dd 绕过 Windows 分区管理」「烧完立刻弹出 TF 卡，不点格式化/修复/扫描弹窗」。⚠️ 属**社区实战记录、非厂商一手**。

**修复**：`fix_lba1.ps1` 把镜像 LBA1（512 B）写回卡，立即回读 + 4 秒后回读均 MATCH，Windows 未再改。随后：

| 校验 | 结果 |
|---|---|
| Quick | 9/9 OK、**PASS**、`exit 0` |
| Full | 10/10 OK；`image sha256 = card sha256 = d8207ede…24f41`、**MATCH**、`exit 0` |

> 🔴 **下一步立刻安全弹出 / 拔出 TF 卡**，别在 Windows 上点任何「格式化 / 修复驱动器 / 扫描」弹窗 —— 这是上述 DAMO 文档与 UEFI 规范共同指向的风险点。拔卡后 Windows 不再触碰介质，GPT 头保持镜像原值。

---

## 5. 烧完后的判活顺序（摘要，详见执行单 1.0b / 1.0c）

1. 绿灯常亮 = 供电正常（瑞莎 FAQ Q2），**不等于启动成功**。
2. 路线 B 首启热点：`Microduck-kissqy` / **`12345678`** / `http://10.42.0.1:8088`（密码以 `.upstream/replica/docs/HD1910-20261012-kissqy镜像R1分析.md` §2 第 27 行 + §7 第 106 行一手原文为准）。✅ **2026-11-14 已在本板实机观察到该热点**，撤销「从未实机复现」的 `UNVERIFIED_hardware` 标记，详见 §5.1。
3. 裸板未接摄像头 / ToF 时 `mediad`/`tofd` 会反复崩溃重启（脚本头注），属已知预期；项目一手排障文档明写「**热点不依赖 `robotd`、舵机 ID 或总线 IMU**」，别因此关服务。
4. 正式 `1.2` PASS 判据仍是**串口 1500000n8 看 U-Boot → 内核 → login**；热点只是「已到用户态」的观察值，`COLLECTED != PASS`，不自动判绿。

### 5.1 现场结果：卡回插主板后热点已出现（2026-11-14）

| 项 | 实读值 |
|---|---|
| 前置机械核对 | `Get-Disk` 只剩 Disk 0 / Disk 1 两块 NVMe，**`Disk 2 / USB / 62.3 GB` 已消失** ⇒ 卡已拔离 PC、插回主板；卡内容此前已验 = `V112.img`（Quick 9/9 + 全量 SHA-256 `d8207ede…24f41`） |
| 🔴 假象 | 普通 `netsh wlan show networks` **只显示上一次扫描的缓存**、不发起新扫描（2026-11-14 查证 StackOverflow 46428202 / 30786358、`access_points` #11、roamr ADR-0004）：首次扫到 4 个 SSID 含 `Microduck-kissqy`，随后 5 次只剩 1 个，**差点误判成「热点消失/板子掉了」** |
| ✅ 正确判据 | `wlan_scan_realtime.py` 用 `ctypes` 调 `wlanapi!WlanScan` 强制刷新（只读、不改连接/配置），等 4 s 再读 ⇒ **连续 3/3 轮稳定命中 `Microduck-kissqy`** |
| 观察值 | BSSID `cc:c8:37:e3:f2:1a`、信号 **93%**、2.4 GHz / 信道 11、WPA2-个人 / CCMP、802.11ac |
| 未闭合 | 断电负对照未做（不能 100% 排除同名 AP）；`10.42.0.1:8088` 配网页未访问；串口 1500000n8 未接；板子背面丝印版本未确认 |

> 📌 **状态不翻**：`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`、`COLLECTED != PASS`。热点只证明「已到用户态」，不是里程碑 ① 的 1.2 PASS。
> **下一步**：手机关移动数据连 `Microduck-kissqy` / `12345678` → 开 `http://10.42.0.1:8088`；断电 5 s 前后各做一次主动扫描做负对照；再接串口走正式判据。

---

## 6. 边界与铁律

- `live_hardware_accessed` **仍为 `false`**、`ship_verdict` **仍为 `NOT_SHIPPABLE`**、A2 悬案闭合数仍 0 —— 做出镜像 ≠ 上板验收，未擅自翻状态。
- 几何/采购 SSOT、contract、任何 xlsx **零改动**；本文件与执行单为纯新增/精修文档。
- 所有二进制（R1 xz、V112 img、deb、Rufus exe、验证脚本）都在已 gitignore 的 `.upstream/` 下，未入库。
- 镜像许可：作者**个人非商业**许可，不得随套件预装/分发、**不得卖烧好的卡**。
