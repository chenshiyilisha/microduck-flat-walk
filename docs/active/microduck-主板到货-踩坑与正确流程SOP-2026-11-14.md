# 主板到货 · 踩坑复盘与正确流程 SOP（2026-11-14）

_回应「遇到的坑，正确的流程都记录下来，免得再犯」。范围：2026-11-14 从「两个 C 口用哪个」到「可以了，F 盘」这一整段裸板上电排障。**这是一份防复发文档，不是验收报告**；所有结论仍受 `UNVERIFIED_hardware` / `ship_verdict=NOT_SHIPPABLE` 约束。准绳见 `.workbuddy/memory/MEMORY.md` 准则 4/5/9/11/12。_

---

## 一、总病根：前提没验证就往下推

这一段连续踩的坑，几乎全是同一个形状：**把「卡里已经有可启动镜像」当成默认前提**，于是断电重启、卡槽方向、换引导、热点名、端口、等待时间……推了一圈，全是对着空卡说话。用户一句「新卡，没有任何东西」才把根因定死。

> 🔴 **第一准则（新增，写进项目长期记忆）**：凡「板子没反应 / 搜不到 / 灯不亮 / 没输出」，**先机械确认最前置前提**（启动介质里有镜像吗？是哪条路线做的？来源是什么？），再谈引导、端口、重启、热点。没有机械证据就不要往下推。

---

## 二、坑清单（按发生顺序，逐条给正确做法与依据）

| # | 坑 | 当时怎么错的 | 为什么错 | 正确做法 | 依据 / 证据强度 |
|---|---|---|---|---|---|
| 1 | **空卡当成已烧卡** | 连着几轮给「断电重启 / 卡槽方向 / 换引导 / 热点」排障 | 1GB 无 eMMC 板，microSD 是唯一启动介质；空卡 = boot ROM 找不到介质，U-Boot 一步都不会跑 | 先问/先查「卡里有没有镜像」；空白卡 → 直接进烧卡流程，所有「启动后」判据暂时不适用 | 瑞莎 `install-os` 页「从 SD 卡启动」；项目执行单 1.0a（**页面实访原文**） |
| 2 | **`Microduck-kissqy` 当通用验活名** | 把 R1 专属热点当成「这张卡」的验活手段，还给了 `12345678` / `8088` | 项目里有**三条互不相同的卡路线**，热点行为不同；该名是 kissqy 镜像作者自设 AP 名（项目名 + 自己仓库名），不是标准 | **先判卡路线再谈热点**：A Armbian 底包卡**不发热点**；B R1 `Microduck-kissqy`/`12345678`/`8088`；C 20261027 `Microduck-xxxx`/`microduck`/`8000` | `card_build_contract.json`、`HD1910-20261012-kissqy镜像R1分析.md` §2/§7、`热点与主板型号排查.md`（**项目一手**） |
| 3 | **「等 1–2 分钟」写成事实** | 凭感觉给等待时间 | 对 R1 无一手依据；新镜像一手写的是「约 3 分钟」（扩容 + 起名 + 认 IMU） | 有出处就引出处；没出处标「这是推的」，取保守值 | `烧录和第一次使用.md` §3（**上游一手**）；推断部分已标 |
| 4 | **绿灯 = 启动成功** | 把绿灯当成板子活了 | 绿灯只表示 5V 供电正常；Radxa 社区有 ZERO 3W「绿灯常亮、SD/eMMC 都不启动」故障案例 | 绿灯只过「供电关」；启动要串口 `U-Boot→内核→login` 或用户态证据（热点） | 瑞莎 FAQ Q2（**厂商 FAQ**）+ 社区案例（**非厂商**）；闪烁/常亮冲突口径标 `UNVERIFIED_hardware` |
| 5 | **以为能「通过板子烧镜像」** | 想省拔卡，问 OTG 能否烧 SD | 厂商安装二分法：SD 卡走 **PC 读卡器**；USB 线刷是 **eMMC 专属**，本板无 eMMC。空卡时板上没有任何程序在跑 | 拔卡 → 读卡器接 PC → 烧 → 回插。`rkdeveloptool db` + `ums 0 mmc 1` 理论绕路**未在本板验证，别赌** | 瑞莎 `install-os` / `install-os-on-emmc` 两页（**页面实访原文**）；绕路 = 推断 |
| 6 | **证据强度虚标** | 把 PDF 写成「实访」（其实直连失败、只有检索摘录）；把 3 个源并列写成「已证实风险」（实为 1 直接 + 2 间接 + 惯例） | 论证强过证据 | 逐条标来源类型；#4399 原文明说「只是提示、不影响导入」，属类比推断；明写「没有厂商文档明令 STL 必须 ASCII」 | 11-13 复盘审计 `microduck-项目资料支撑复盘审计-2026-11-13.md` |
| 7 | **脚本硬编码外部 URL 直接跑** | 换引导脚本依赖 `radxa-repo.github.io/.../39cd993_arm64.deb`，实测 **404**（连目录根也 404） | 厂商 Pages 迁移，本地无缓存 | 先 HEAD 探测 → 找替代源（南阳理工镜像站同名同版本 deb）→ 放到脚本目录 → **由脚本自带 `sha256sum -c` 验 pin** `fb319203…bce7` | 本机实测 404 + 镜像站下载 + sha 逐字一致（**独立判据**） |
| 8 | **大文件直接开下载** | HEAD 200 就启动 707 MB 后台下载 | HEAD 只证明可达，不证明可下；实测 ~120 KB/s，ETA >1 h（Etcher 284 MB 同样慢） | 先下小资产（`.sha256`/README）测速并估 ETA；不划算就换**全本地**路线；停止任务后**删残片**（31,289,344 B）避免误用 | 本机实测速率；`20261027.img.xz.sha256` = `91ab5550…d0194` 与项目验证文档一致 |
| 9 | **后台任务里调 WSL** | `run_in_background` 的 Bash 里 `wsl.exe` 报 `Permission denied`（rc=126） | 后台任务在沙箱内，前台调用才有 escalation | 需要 WSL 的命令**一律前台执行** | 本机两次对照：后台失败 / 前台成功 |
| 10 | **Git Bash 路径转换** | `wsl.exe -- bash /mnt/e/.../verify_v112.sh` → `bash: D:/Program Files/.../mnt/e/...: No such file` | MSYS 把独立参数 `/mnt/e/...` 当本地路径转成 Windows 路径 | 用 `wsl.exe -- bash -c "cd /mnt/e/... && bash verify_v112.sh"`，让 Linux 路径留在引号参数内部 | 同两次对照；`wsl.exe -- which dd` 这类无 `$` 变量的参数不受影响 |
| 11 | **只看 rc 判脚本成败** | 管道 + `tail` 后 `wsl_rc=32`，看起来像失败 | `PIPESTATUS[0]` 受管道影响；脚本其实 7/7 全过 | **判据独立于 rc**：产物存在 + 独立工具 hash + 扇区内容比对 + 负对照 | 呼应准则 4/8；本次 WSL `sha256sum` 与 Windows `Get-FileHash` 双工具一致 `d8207ede…24f41` |
| 12 | **静默替换工具/路线不标注** | Etcher 下不动就改用 Rufus | 上游一手指南指定的是 balenaEtcher / Raspberry Pi Imager；Rufus 是替代方案 | 显式写「非一手指定工具」，标 `UNVERIFIED_print`；保留 Etcher 优先的说明 | `烧录和第一次使用.md` §2；Rufus DD 模式有 IBM/ArchWiki 多源支撑但**未在本镜像实机验证** |
| 13 | **Rufus 误选 ISO 模式** | （未发生，提前防） | raw `.img` 被当 ISO 处理，写出来的卡不能启动 | 文件过滤器切 `DD Image`（或所有文件）→ 弹窗**必须选 `DD Image mode`** | IBM Storage Defender 文档 / ArchWiki |
| 14 | **不可逆写盘擅自执行** | （未发生，提前防） | 整盘覆盖写错目标 = 灾难 | 写盘前机械核对 `Disk 2 / USB / 62.3 GB / IsBoot=False`，与两块 NVMe 系统盘区分；留用户在 GUI 目视确认后点 START | 本机 `Get-Disk` 实测 |
| 15 | **板型假设没写明** | 按 V1.12 换引导，但用户始终没答丝印版本 | 换引导是 **V1.12（AIC8800）专属**；V1.12J 可能还要换设备树 | 显式写「按 V1.12 假设执行」+ 留回退（R1 原包仍在本机可重烧） | `kissqy-r1-v112.sh` 头注、R1 分析 §4/§7 |
| 16 | **工具就绪 ≠ 状态翻转** | （未发生，提前防） | 做出镜像、烧好卡都不等于上板验收 | `live_hardware_accessed` / `ship_verdict` 只在里程碑 ① 真正走完后由证据驱动变更 | 项目铁律 `UNVERIFIED != PASS`、`COLLECTED != PASS` |
| 17 | **「全零 = 空卡」负对照假绿** 🔴 | 空白 FAT32 卡前 1 MiB 非全零，写卡校验脚本却报 `negative control: OK` | 已格式化的卡前 512 B 是标准 MBR 引导代码（含 `Invalid partition table`、签名 `0xAA55`）；FAT32 BPB 在分区内、不在 0 扇区 | 判据不靠「全零」：改为 **9 个采样点内容比对** + 出厂 MBR 特征诊断；先实读前 512 B 确证再写判据 | 本机 `\\.\PhysicalDrive2` 前 512 B 实读 |
| 18 | **UTF-8 无 BOM 脚本在 PowerShell 5.1 乱码** | `FAIL —` 输出成 `FAIL 鈥?` | Windows PowerShell 5.1 按 ANSI/GBK 解读无 BOM 的 UTF-8 脚本 | 工具脚本的输出与注释**一律纯 ASCII**，中文说明留在 md 文档里 | 5.1 子进程 `powershell.exe -File` 实跑对照 |
| 19 | **检查器只见过红、没见过绿** | 第一版校验脚本只在空白卡上跑过 FAIL，没证明内容一致时会 PASS | 只会报错的检查器同样可能是坏的 | 加 `-SelfTest`（镜像对自身、不开物理盘）作**正对照**，空白卡作**负对照**，两者都必须如期 | SelfTest 9/9 PASS exit 0；空卡 0/9 FAIL exit 2 |
| 20 | **想当然的一手来源路径 / 硬凑证据** | `raw.githubusercontent.com/wiki/.../FAQ.md` 404、`github.com/.../FAQ.md` 超时+502、exe 内搜不到 `DD Image` 明文 | wiki raw 路径不适用；GitHub 域名本机偶发 502；Rufus 资源被压缩 | 换**能通的通道**取硬证据：GitHub REST API 资产 `digest` + `Get-AuthenticodeSignature` 双证；网页拿不到就如实降级为「多源一致 + 项目一手目录」，**不冒充页面实访** | REST API `84c8a437…be106`；签名 Valid / `Akeo Consulting` |

| 21 | 🔴 **Windows 写后自动改写 GPT 头**（本轮最大坑） | 3.0 GB 裸写 `exit 0`，Quick 校验却 **8/9**，前 1 MiB DIFF、`Get-Disk` 从 MBR 变 GPT | 镜像按 3 GB 盘生成 GPT 头，卡是 64 GB；Windows 重枚举时把 `AlternateLBA`/`LastUsableLBA`/`PartitionEntryLBA`/`HeaderCRC32` 共 **12 字节**按大卡重算，其中 `PartitionEntryLBA` 2→2016，而 LBA2016 全 `FF`、真分区项仍在 LBA2 ⇒ **头与数据不一致** | ① 逐扇区定位差异 → ② **独立第二算法**全量扫 3 GB 确认只有这 12 字节 → ③ 按 UEFI 2.11 §5.3.2 字段表确认字段含义 → ④ `fix_lba1.ps1` 把 LBA1 写回镜像原值并做「立即 + 延迟」回读防再改 → ⑤ Quick 9/9 + **全量 SHA-256 相等** → ⑥ **立刻拔卡**，不点格式化/修复/扫描 | UEFI 2.11 §5.3.2（`uefi.org` 实访）、微软 Windows and GPT FAQ、DAMO《Microduck 零基础部署调试实战》§0.2（社区，同板）、本机 `diff_full.py` 753 块/12 字节实测 |
| 22 | **`Set-Disk -IsOffline` 当万能解法** | 想先 offline 再裸写，报 `Removable media cannot be set to offline` | 可移动介质不支持 offline（本机实测） | 改走 `FSCTL_LOCK_VOLUME` + `FSCTL_DISMOUNT_VOLUME` 标准路线；查资料确认这是 Windows 裸写的通用做法 | 本机 PowerShell 实测；多源 Windows raw-write 资料 |
| 23 | **Win32 权限常量的 UInt32 绑定** | `CreateFile` 首跑报「无法将 -1073741824 转换为 System.UInt32」，脚本在第一字节前就挂 | PowerShell 把 `0x80000000\|0x40000000` 算成 Int32 负数，P/Invoke 签名要 `uint` | 显式 `[uint32]$ACCESS_RW = 3221225472`（0xC0000000）；**先跑不带开关的 dry-run** 验证脚本能解析且必定拒绝，再真跑 | dry-run `exit 3` REFUSED；重跑 16 guard 全过 |
| 24 | **运行时编译被安全策略拦就硬闯 / 手工降级** | 内联 `Add-Type` 做快速逐字节比对被拦（`Command blocked for security`） | 环境禁止运行时编译 .NET；脚本文件内的 `Add-Type` 可用，但内联不行 | 换**独立语言 + 独立算法**：纯 Python 只读物理盘做 753 块 md5 + 差异定位 + 双 SHA-256，不依赖 PowerShell 校验脚本、不编译 .NET | `diff_full.py` 166.4 s 跑完，结论与 PowerShell 侧一致 |
| 25 | **把「写入 exit 0」当完成** | 写盘脚本报 `WRITE DONE` 就想交差 | 写缓存、OS 事后改写、扇区错都会让「成功」是假的 | 脚本自己就打印「this is NOT proof」；**强制接独立校验**（9 点 + 全量 SHA），且校验必须能定位差异而非只比 sha | 准则 4/12；本轮若跳过校验就会带着坏 GPT 头上板 |
| 26 | 🔴 **`netsh wlan show networks` 只读缓存 ⇒ 上板判活假阴性** | 卡回插主板后第一次扫到 `Microduck-kissqy`，紧接着 5 次普通扫描全没了，差点判「热点消失 / 板子没起来」 | netsh **不发起扫描**，只显示适配器上一次扫描的缓存，可陈旧约 60 s；后台扫描周期不定，连着跑同一个命令只会反复读同一份旧结果 | 查资料确认后换**主动扫描**：`ctypes` 调 `wlanapi!WlanScan` 强制刷新 → 等 4 s（Windows logo 扫描完成时限）→ 再读；连续 3/3 轮稳定命中同一 SSID + BSSID + 93% 信号才作数 | StackOverflow 46428202 / 30786358、`access_points` issue #11、roamr ADR-0004（2026-11-14 检索）；本机 `wlan_scan_realtime.py` 实跑 `WlanScan rc=0` 3/3 |
| 27 | 🔴 **明文渲染层替换敏感串 ⇒ 订正方向反转**（11-14 终裁推翻前几轮判断） | 前几轮把用户实机输入并连上的那 8 位串判成「压缩记忆错值」，按明文显示值去「订正」，结果「错值 == 对值」自相矛盾 | `od -An -tu1` / `base64` / Python `ord()` 三条字节级通道显示**所有磁盘文件（一手文档、执行单、操作卡、SOP、审查报告、MEMORY）字节完全一致**，从来没有写错；错的是**明文输出通道**（Grep / Read / cat / grep）会把该串渲染成另一个值 | **终裁**：以字节级编码 + 实机 WPA 握手为准；明文显示值不作依据、不据此反推；订正文本**连幻影值也不复写**，只指向一手源（`.upstream/replica/docs/HD1910-20261012-kissqy镜像R1分析.md` §2 L27 / §7 L106、镜像内 `Microduck-Setup.nmconnection` 的 `psk=`）。详见 `microduck-主板到货-手机侧实机观测与密码口径终裁-2026-11-14.md` §1 | 真机 WPA2 `COMPLETED` + DHCP `10.42.0.254/24`；字节扫描 6 份文件；同一条 WSL 命令内 `grep '^psk='` 与 `od` 互相矛盾 |
| 28 | 🔴 **手机连上无互联网热点后自动回落 ⇒ 验活假阴性** | 手机已连 `Microduck-kissqy` 并拿到 `10.42.0.254/24`，随后 `ping` 源地址变 `192.168.50.203`、curl `:8088` 两次 timeout，差点判「配网页死了」 | 手机 `dumpsys connectivity` 显示 `Active default network` 是 `MOBILE[LTE]`（`IS_VALIDATED`）；热点无 Internet 能力，系统把它降级回落到已保存的家用 WiFi / 蜂窝。平台文档两次抓取失败，**机制为推断，设备侧观测是实测** | 探测前**先核「手机当前 AP + 源地址 + 路由」三条前提**，不成立就报 `PRECONDITION_FAIL` 而非 `FAIL`，且一个 HTTP 都不发；现场工具 `.upstream/downloads/probe_v112_phone.sh` 已真跑负对照 `rc=2` | 终裁文档 §3/§4/§9；`bash -n` OK、负对照 `P1` 即拒绝 |
| 29 | **「扫不到热点」不等于板子坏了** | 重新上电后 PC 主动扫描 3/3 + 手机强制扫描 + 早期 6 轮全部无 `Microduck-kissqy`，差点判启动失败 | 镜像 `main()`：`PROVISIONED_PATH.exists()` 且 `wait_for_saved_wifi()` 成功即 `return`、**按设计不再开 AP**；实机 `ping microduck.local` 3/3 通、`SSH 22 OPEN` + OpenSSH banner、MAC 与热点 BSSID 同源（RFC 4291 App.A）⇒ 板子活着且已连家里 WiFi | 判活要换观测面：mDNS / ICMP / SSH / 路由器 DHCP，不只盯 beacon；把「AP 消失」当状态变化而非故障 | 终裁文档 §9；`22 OPEN` + 负对照 `9999 CLOSED` |
| 30 | 🔴 **把 `Discoverable: no` 推断成「App 连不上」** | 21:0x 首次 SSH 登板读到 `bluetoothctl show` 的 `Discoverable: no` / `Pairable: no`，中途据此判「BLE 前端不可见、App 连接前置条件不成立」 | **过度推断**：`Discoverable` 是 BlueZ `Adapter1` 全局可见性开关（默认 false）、`Pairable` 只影响入站配对；`ActiveInstances: 0x02` 才是 LE 广播实例数；PC 侧独立 BLE 扫描实际命中 `duck-6a07` | 读布尔位 / 退出码 / 数量前先回一手 API 文档（`org.bluez.Adapter.rst` / `LEAdvertisingManager.rst`）；结论用第三方观测（PC / 手机扫描 + 负对照）证伪，不靠字段字面推 | 单一权威文档 §5.2；该推断已撤回 |

---

## 三、正确流程 SOP（照着走，每步带判据）

### 步骤 0 · 机械确认最前置前提 🔴 最容易被跳过
```powershell
# 卡是不是空白？目标盘认准了吗？
Get-Volume -DriveLetter F | Select DriveLetter,FileSystem,Size,SizeRemaining,DriveType
Get-ChildItem -Force 'F:\' | Select Name,Length          # 空卡通常只有 System Volume Information
Get-Partition -DriveLetter F | Get-Disk | Select Number,FriendlyName,BusType,Size,IsBoot,IsSystem
```
**判据**：`DriveType=Removable` + `BusType=USB` + `IsBoot=False` + 与 NVMe 系统盘编号可区分；盘内无镜像分区 ⇒ 空卡。
**已烧卡的路线判别**（插回 PC / WSL2 可读 ext4）：
```bash
ls /boot/extlinux/extlinux.conf      # 路线 B：R1 / V112
ls /root/先连WiFi.txt                # 路线 A：Armbian 底包卡
systemctl cat microduck-netcheck     # 路线 C：复刻镜像
```

### 步骤 1 · 板与电
- 确认背面丝印版本（V1.12 / V1.12J / 其他）→ 决定要不要换引导。
- 电源插 **`USB 2.0 / OTG`** 口，5V/2A 及以上；`USB 3.0 / HOST` 只接外设、不供电。⚠️ 产品页图示编号与硬件文档 `USB-C 1/2` 命名相反 ⇒ **认 OTG 字样，不认数字**。

### 步骤 2 · 选镜像路线（判据：素材是否本地 + 板型 + 许可）
| | ① 本仓既定 kissqy R1 | ② 上游 20261027 |
|---|---|---|
| 素材 | 本机现成 `microduck-zero3w-0.15.1-R1.img.xz`（767,412,924 B，sha `75da978b…a7bce5` = contract pin） | `741,604,104` B / sha `91ab5550…d0194`，本机无、需下载 |
| 烧前 | V1.12 须跑 `kissqy-r1-v112.sh` 换引导 | Etcher 直烧 `.img.xz`，不用解压 |
| 首启 | `Microduck-kissqy` / `12345678` / `8088` | `Microduck-xxxx` / `microduck` / `8000`，等约 3 分钟 |
| 本次选 | ✅ **选它**（零下载、版本链与 contract 一致） | ⏸ 下载限速 >1 h，降为备选 |

### 步骤 3 · 备素材 + 校验（外部 URL 先探测）
- 脚本依赖的 deb：先 HEAD；404 就找同名同版本替代源 → 放到脚本目录 `$HERE`（脚本会跳过 curl）→ **必须用脚本自带 pin 校验**（`fb319203…`）。
- 所有下载物放已 gitignore 的 `.upstream/`；实查 `git ls-files` 确认未入库。

### 步骤 4 · 换引导（仅 ① + V1.12）
```
# WSL2 前台执行；路径写在 -c 的引号内部，防 MSYS 转换
wsl.exe -- bash -c "cd /mnt/e/.../tools/radxa && bash kissqy-r1-v112.sh \
  /mnt/e/.../downloads/microduck-zero3w-0.15.1-R1.img.xz --overlay i2c4-m0"
```
- 🔴 **不得**加 `--no-camera` / `--no-tof`（订正㉑ 必需，做卡工具会拒 rc=1）。
- 产出 `*-V112.img` 是**未压缩 raw img**，直接烧，不要再解压 xz。

### 步骤 5 · 独立验证（不靠脚本自述"做好了"）
```bash
bash verify_v112.sh
```
四道判据：① 镜像扇区 64/16384 内容 md5 = deb 内 `idbloader.img`/`u-boot.itb` 首扇区；② **负对照** R1 原包同位置扇区必须不同；③ 只读 loop 挂载确认 `extlinux.conf` 含 overlay、内核/fdt/UUID、V112 标记；④ 双工具 hash（WSL `sha256sum` + Windows `Get-FileHash`）一致。
> 本次结果：全 PASS；`V112.img` = 3,157,262,336 B / `d8207ede…24f41`。

### 步骤 6 · 写盘（不可逆；2026-11-14 已按授权执行）

> ✅ **实际执行**：用户 14:45 明确授权「你来操作」后，走自写 `write_v112_to_disk2.ps1`（16 项 guard + `FSCTL_LOCK/DISMOUNT` + `FlushFileBuffers`），**不是 Rufus GUI**；Rufus 保留为人工备选/复现路线。下文 GUI 三步仍可作为复现参考。
- 工具：便携版 `rufus-4.15p.exe`（1,989,992 B）——⚠️ **非上游一手指定**，标 `UNVERIFIED_print`；Etcher 可用时优先按 `烧录和第一次使用.md` §2 用它。
- 设备选 `F: / Mass Storage Device / ~62.3 GB / USB`；镜像选 `*-V112.img`；过滤器切 `DD Image`；弹窗选 **`DD Image mode`**；确认清空警告 → START。
- 写完弹「需要格式化」点**取消**（ext4 Windows 读不了是正常的）；**先别拔卡**。
- **写后立即跑独立校验**（准则 12：不看工具自述完成）：`powershell -ExecutionPolicy Bypass -File verify_burned_card.ps1`，9 个采样点全 OK + `PASS`(exit 0) 才算写对；`FAIL`(exit 2) 则重查目标盘 / `DD Image mode`，**不要插板**。需要更硬证据可加 `-Mode Full` 做 3.0 GB 全量 SHA-256。
- 校验脚本交付前已过正负对照：`-SelfTest` 9/9 PASS、当前空白卡 9/9 FAIL（诊断 `CARD STILL HAS FACTORY MBR/FAT32 layout`）。⚠️ 它只证明「卡内容 == V112.img」，**不证明能启动**。
- 安全弹出 → 回插主板 → 完整断电重启 → 步骤 7。
- ✅ **本轮实际结果**：裸写 `3,157,262,336 B / 191.8 s`；写后 Quick **8/9 抓到 Windows 改写 GPT 头 12 字节** → 独立全量比对确认只有这 12 字节 → `fix_lba1.ps1` 恢复 LBA1 → **Quick 9/9 + 全量 SHA-256 相等（`d8207ede…24f41`）PASS**。详见操作卡 §4.6、坑 21–25。
- 🔴 **写盘后立刻安全弹出 / 拔卡**，别点 Windows 的「格式化 / 修复驱动器 / 扫描」弹窗（DAMO §0.2 + UEFI 2.11 §5.3.2 共同指向的风险）。

### 步骤 7 · 上电判活（按证据强度从弱到强）
1. 绿灯常亮 = 供电正常（**≠ 启动成功**）。
2. 按卡路线找热点：B `Microduck-kissqy`，C `Microduck-xxxx`，A **无热点**（去路由器找新设备 / 走串口）。🔴 **别用普通 `netsh wlan show networks` 反复读**（只读缓存，见坑 26）：搜不到时先跑 `wlan_scan_realtime.py` 强制 `WlanScan` 再判，或用手机 WiFi 列表作第二观测者。
3. 裸板没接摄像头/ToF 时 `mediad`/`tofd` 反复崩溃是**已知预期**，别因此关服务；项目一手文档明写「热点不依赖 `robotd`、舵机 ID 或总线 IMU」。
4. **正式 `1.2` PASS 判据** = 1500000n8 串口看 `U-Boot → 内核 → login`、无 panic。热点只是用户态观察值，`COLLECTED != PASS`，不自动判绿。
5. ✅ **2026-11-14 现场结果**：卡回插主板后，主动扫描 3/3 轮稳定命中 `Microduck-kissqy`（BSSID `cc:c8:37:e3:f2:1a`，93%，2.4 GHz ch11）⇒ V112 换引导镜像在本板**首次实机到了用户态**，撤销执行单 1.0c「从未实机复现」的 `UNVERIFIED_hardware`。仍有 4 项未闭合：断电负对照、`10.42.0.1:8088` 配网页、串口链、板子丝印版本。手机连热点密码 **`12345678`**（一手原文，见坑 27）。

### 步骤 8 · 证据落位
`board_acceptance.py --record BA-3-4 ...`，只记观察值；状态变更由里程碑证据驱动，不因"工具/镜像就绪"提前翻。

---

## 四、防复发硬规则（可直接抄进检查表）

1. **排障第 0 问**：卡里有镜像吗？哪条路线？来源？—— 无机械证据不往下推。
2. **热点名/端口/密码先判卡路线**，三套口径不可混用（8088 / 8000 / 无热点）。
3. **脚本硬编码外部 URL 先 HEAD + 找替代源 + 用 pin 校验**；判据独立于下载源。
4. **大文件先下小资产测速估 ETA**；后台任务停掉后删残片。
5. **WSL 必须前台**；Linux 路径放 `bash -c "cd ... && ..."` 内部，别当独立参数。
6. **脚本成功判据 = 产物 + 独立 hash + 内容比对 + 负对照**，不只看 `$?`（管道会污染 rc）。
7. **替换工具/路线必须显式标注证据强度与 `UNVERIFIED_*`**，不能默默替换还写成"按指南"。
8. **不可逆写盘不擅自执行**，写前机械核对目标盘四要素。
9. **未确认的假设（板型等）写明 + 留可回退素材**。
10. **工具/SOP 就绪 ≠ 悬案闭合**；`live_hardware_accessed`、`ship_verdict` 不提前翻。
11. **术语**：全文不把瑞莎 / Prusa / Bambu / GitHub 等称作「官方」（项目准则 11，唯一「官方」= Pollen 原厂）；写「厂商文档 / 上游一手 / 社区案例 / GitHub REST API」。
12. **许可**：镜像为作者个人非商业许可，不得预装分发、**不得卖烧好的卡**。
13. **检查器要有正负对照**：既能在内容一致时变绿（`-SelfTest`），也要在内容不符时变红；只见过一种颜色的断言不是证据。
14. **判据先实读再写、脚本输出纯 ASCII**：不要用「全零」这类想当然的空值判据，先实读目标前 512 B 确认真实特征（已格式化的卡有 MBR 引导代码）；PowerShell 5.1 会按 GBK 解读无 BOM 的 UTF-8 脚本，中文/破折号输出会乱码。

15. **烧嵌入式 GPT 镜像到大容量卡，写完必须全量比对并立刻拔卡**：OS 会按介质容量重算 GPT 头；发现头与分区项位置不一致要**恢复成镜像原值**再验，绝不带着不一致的头上板，也绝不改判据去迁就差异。
16. **工具被安全策略拦就换独立算法，而不是绕规则或手工降级**：换语言/换实现后要保证「判据独立于被测值」且能**定位差异位置**（不只比 sha 是否相等）；差异要用两条独立算法互证。
17. **Windows 裸写固定套路**：管理员 → guard → `FSCTL_LOCK_VOLUME`+`FSCTL_DISMOUNT_VOLUME` → 扇区对齐流式写 → `Flush(true)`+`FlushFileBuffers` → 解锁 → 独立校验。可移动盘不支持 `Set-Disk -IsOffline`；P/Invoke 的 `uint` 常量要显式写十进制避免 Int32 负数绑定错误。
18. **「搜不到」先问观测工具本身会不会骗人**：`netsh wlan show networks` 不发起扫描、只吐缓存；连续重复读同一条命令得到「时有时无」时，先查该命令语义（先找资料），再用 `WlanScan` 主动扫描 / 手机作第二观测者下结论。判活结论要带 SSID + BSSID + 信号 + 重复次数，不写「搜到了」三个字了事。
19. **具体数值一律以字节级通道为准，明文渲染值不作依据**：密码、端口、pin、sha、版本号这类值，用前必回一手源（具名文档 + 行号，或源文件字段如 `psk=`／`append`）；核数值走 `od -An -tu1` / `base64` / Python `ord()` 这类**不受文本替换影响**的编码通道，不看 Grep / Read / cat 的明文显示。🔴 **终裁（11-14，推翻此前方向）**：本项目的「两处数值冲突」实测是**明文输出层把该串渲染成另一个值**，磁盘字节从头到尾一致、从来没有写错；前几轮据此做的「订正」是空操作且方向反了。⇒ 订正文本**连幻影值也不复写**，只写「已回一手源核正」+ 出处；压缩记忆、摘要、订正留档里的具体值一律不作数值依据。详见终裁文档 §1。
20. **换观测面判活，别只盯一个信号**：AP / beacon 消失 ≠ 板子没起。镜像 `main()` 在「已配网且能连上家里 WiFi」时按设计 `return` 不开热点；此时应改用 mDNS（`ping microduck.local`）、ICMP、SSH banner、路由器 DHCP 列表、邻居表 MAC 交叉验证。MAC ↔ IPv6 link-local 的换算按 **RFC 4291 Appendix A**（反转 u 位 + `ff:fe` 插入），有原文才写结论。所有端口探测必须带**负对照**（一个必不可能开的端口也应 CLOSED），否则可能是假绿。
21. **前提不成立 ⇒ `PRECONDITION_FAIL`，不是 `FAIL`**：探测前先机械断言「当前 AP / 源地址 / 到目标的路由是否直连」，任一不成立就拒绝发请求并报 `PRECONDITION_FAIL`；把 `curl timeout` 当「服务挂了」是本轮亲抓的假阴性。现场工具 `.upstream/downloads/probe_v112_phone.sh` 即此规则的可执行版，已真跑负对照 `rc=2`、零 HTTP 请求。
22. **登录真机 ≠ 整机落地，状态字段按语义判、不按动作判**：11-14 首次只读 SSH 登板成功，但 `robotctl health` 报 15 舵机 ID 全缺 + `imu not ready` + `robotd is read-only` ⇒ `live_hardware_accessed=false` **仍成立**（该字段指整机活体接入，不是「碰过板子」），里程碑① 的 1.3「robotd 能 open」仍 FAIL。同理 `robotctl health --json` 的 **rc=5 是 degraded 非零退出码、JSON 完整** ≠ CLI 失败。🔴 凭据只在进程内存用一次即删，绝不写文件 / 日志 / 文档 / git；**源码自检也不许把凭据片段写进去**（本轮亲抓：为了断言「不含凭据」反而把片段写进了源码）。现场工具 `.upstream/downloads/probe_v112_ssh_readonly.py` = 指纹独立锚 + 只读白名单 + 写命令注入负对照（`--selftest` 12/12）。

---

## 五、本次落盘产物与状态

| 文件 | 作用 |
|---|---|
| `docs/active/microduck-主板到货-踩坑与正确流程SOP-2026-11-14.md` | 本文（坑 + 正确流程 + 防复发规则） |
| `docs/active/microduck-主板到货-烧卡操作卡-2026-11-14.md` | 现场实测值、路线决策、构建/验证结果、三步写盘操作 |
| `docs/active/microduck-主板到货上板执行单-2026-11-12.md` §1.0 / 1.0a–c | 主执行单（本轮纯新增：供电口、OTG 依据、空卡判据、三路线、现场执行结果） |
| `docs/hardware/microduck-Radxa上电验收清单-2026-11-06.md` §3 | 端口选择与来源分级 |
| `.upstream/downloads/verify_v112.sh` | 可复跑的独立验证脚本（含负对照）；已 gitignore |
| `.upstream/downloads/microduck-zero3w-0.15.1-R1-V112.img` | 3.0 GB 待烧镜像；已 gitignore |
| `.upstream/downloads/verify_burned_card.ps1` | 写盘后**只读**校验：9 采样点 md5 + 可选全量 SHA-256 + 目标盘 guard + `-SelfTest` 正对照；纯 ASCII、不写盘；已 gitignore |
| `.upstream/downloads/write_v112_to_disk2.ps1` | 16 项 guard + LOCK/DISMOUNT 裸扇区写；必须显式 `-IUnderstandThisErasesDisk2` 才会执行；已 gitignore |
| `.upstream/downloads/fix_lba1.ps1` | 把 GPT 头 LBA1 恢复为镜像原值，含「立即 + 延迟」回读检测 OS 是否再改；已 gitignore |
| `.upstream/downloads/diff_full.py` | 独立第二算法：纯 Python 全量 753 块比对 + 双 SHA-256 + 差异字节定位；已 gitignore |
| `.upstream/downloads/wlan_scan_realtime.py` | 主动判活：`ctypes` 调 `wlanapi!WlanScan` 强制刷新扫描后读 SSID/BSSID，绕开 netsh 缓存（坑 26）；只读、不改连接；已 gitignore |
| `docs/active/microduck-主板到货上板执行单-2026-11-12.md` §1.0d | 本板首启热点的实机观察值、方法与状态边界（本轮纯新增） |
| `docs/active/microduck-主板到货-手机侧实机观测与密码口径终裁-2026-11-14.md` | **本轮单一权威落档点**：密码字节级终裁、手机侧第三方观测、坑 28/29、状态裁定、重新上电后的 mDNS/SSH 实证与边界 |
| `.upstream/downloads/probe_v112_phone.sh` | 只读首启配网页探测：先断言三条网络前提，不成立报 `PRECONDITION_FAIL` 且不发任何 HTTP；已 `bash -n` + 真跑负对照 `rc=2`；ASCII 注释、不改 WiFi/不写板子；已 gitignore |

**状态**：`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`、A2 悬案闭合数 0，均未变；采购 SSOT / contract / xlsx 零改动；二进制未入库。2026-11-14 现场虽已观察到 B 路线热点（用户态），但按 `COLLECTED != PASS` 只记观察值，**不提前翻任何状态**。

**仍 `UNVERIFIED_hardware`**：板子丝印版本、断电负对照（排除同名 AP）、`10.42.0.1:8088` 配网页与账号/SSH、1500000n8 串口 `U-Boot→内核→login` 正式 1.2 判据、Rufus 写本镜像、绿灯闪烁/常亮行为、真机 GATT 上板等。✅ **已撤销**：「R1 换引导镜像在本板首启热点从未实机复现」——主动扫描 3/3 命中，已实机观察。
