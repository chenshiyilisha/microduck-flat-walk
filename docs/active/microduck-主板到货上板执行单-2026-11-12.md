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

> 🔌 **1.0 供电口选择（2026-11-14 到货当天补，先于 1.1）**：裸板两个 Type-C 口，丝印 `USB 3.0 / HOST` 与 `USB 2.0 / OTG`。**5V/2A 及以上电源插 `OTG` 口**（瑞莎硬件文档称 `USB-C 1`，「供电使用 USB-C 1 接口」，仅支持 5V 输入）；`USB 3.0 HOST` 是下行输出口（Product Brief §6.2 限流 500 mA），接外设用，接电源不启动。
> ⚠️ 瑞莎产品页图示编号 `1 = USB 3.0 HOST / 2 = USB 2.0 OTG`，与硬件文档 `USB-C 1/2` 命名相反 ⇒ **认 OTG 字样，不认数字**。
> 📚 依据分级：供电口结论由**瑞莎硬件接口说明 + 产品页实访原文**直接支撑（2026-11-14）；500 mA 限流 / 5V 参数出自厂商 PDF 的检索摘录（PDF 直连因本机 TLS 吊销检查离线失败，未逐页实访），仅作旁证。详见 `microduck-Radxa上电验收清单-2026-11-06.md` §3 来源段。
> 本板为 **1GB / 无 eMMC**，从 microSD 启动 ⇒ 1.1 做卡在 PC 读卡器上完成，**不靠 OTG 刷机**；OTG 口在本里程碑只承担供电（兼 USB gadget 调试备用）。
>
> 🚫 **「能不能直接通过板子把镜像烧进 SD 卡」（2026-11-14 现场问，瑞莎文档实访补依据）：官方路径不存在，不建议绕。**
> - 瑞莎 `docs.radxa.com/zero/zero3/other-os/android/install-os`「系统安装」页原文把安装分成两条：**「从 SD 卡启动（推荐）— 通过读卡器将系统镜像烧写到 microSD 卡」**；**「从板载 eMMC 启动 — 使用 USB 线将系统镜像直接刷写到 eMMC 上」**；同页注意栏明写「**如果板子不带 eMMC，则无法从 eMMC 启动**」。该页准备清单逐条列「1x microSD 卡 / **1x SD 卡读卡器** / 1x 5V 电源适配器」，Etcher 第 1 步即「把 microSD 卡插入 SD 读卡器，然后把 SD 读卡器插入 PC 的 USB 接口上」。⇒ **「USB 线直接刷写」是 eMMC 专属路径，本板无 eMMC 不适用**；SD 卡的厂商流程就是在 PC 上用读卡器烧。
> - 瑞莎 `low-level-dev/install-os-on-emmc` 页标题即「**安装系统到 EMMC**」，Maskrom 进入步骤第 1 条是「**拔出 microSD 卡和电源线**」，第 3 条才是「USB-A 转 USB-C 线连接 PC」；「在 Maskrom 模式下，可使用 rkdevtool 或 upgrade-tool 来对您的产品进行擦写、线刷等操作」。⇒ 线刷时**卡本来就不该插着**，写的是板载 eMMC 而非可插拔 SD。
> - 本仓一手 `硬件规格速查.md` / `硬件方案逆向.md` 均记「USB-C = **供电 + maskrom 刷机**」（`硬件方案逆向.md` 另注「maskrom 刷机是 ROM code，不受 overlay 影响」）；Rockchip 开源 wiki「Boot option」页写 SD/TF 卡时同样是「Insert SD card to **PC** … dd」。
> - **概念澄清**：空卡时板子上没有任何程序在跑，既收不了镜像文件，也没有 USB gadget 驱动可把 SD 卡挂成 U 盘。即便 eMMC 板的「线刷」，也是 **PC 上的 rkdevtool 通过 Maskrom 协议直接写存储**，不是「板子自己写」。
> - ⚠️ **理论绕路（不推荐，这是推的）**：Maskrom → `rkdeveloptool db` 把 U-Boot 载入 RAM → 在 U-Boot 命令行用 `ums 0 mmc 1` 把 SD 卡暴露为 USB Mass Storage → PC 用 Etcher 写。U-Boot 文档确有 `ums` 命令且示例正是把 `mmc 1 (SD)` 暴露给 PC（需 `CONFIG_CMD_USB_MASS_STORAGE=y` + USB 控制器 peripheral 模式）。但**未查到瑞莎 ZERO 3W 上任何一手实操记录**，本仓 `u-boot-rk2410` 是否编入该 config、Windows 侧 libusb 驱动均未核实 ⇒ 标 `UNVERIFIED_hardware`，复杂度远高于「拔卡 + 读卡器」。
> - 📚 依据分级：瑞莎两页 = **2026-11-14 页面实访原文**；U-Boot `ums` = U-Boot 项目文档（通用能力，非本板验证）；理论绕路 = 推断，明确标注。
> 整机阶段供电改由 HAT 经 40-pin Pin 2/4 送 5V（`microduck-硬件清单-详细接线版.md`），届时不要与 USB-C 电源长期同时挂着——该点为保守建议，瑞莎文档未说明双路并联后果，标 `UNVERIFIED_hardware`，不写成硬规。

> 🃏 **1.0a 最前置判据：卡里到底有没有可启动镜像（2026-11-14 现场补，优先于 1.0b / 1.0c）**
> - 本板 **1GB / 无 eMMC**，microSD 是**唯一**启动介质（见 1.0 第 4 条）。**一张空白新卡 = 无启动介质 ⇒ 绿灯只表示有电，不会有 U-Boot、不会有内核、不会有任何热点**。这是正常现象，**不是硬件故障**。
> - 2026-11-14 现场：用户答「卡是插在主板上的，新卡，没有任何东西」⇒ 空卡。此前 1.0b「断电重启 / 卡槽方向 / 换引导」、1.0c「三路线热点 / 端口」**全部以「卡已烧好」为前提，对空卡不适用**；搜不到 `Microduck-*` 的根因就是卡里没有系统。
> - **最短路径**：断电 → 拔卡 → 插 PC 读卡器 → 烧入镜像 → 回插主板 → 上电（再走 1.0b / 1.0c）。卡容量 **≥ 8 GB，推荐 32 GB**（`.upstream/replica/software/image/烧录和第一次使用.md` §1）。Windows 烧完若弹「需要格式化」一律点**取消**（同文档 §2 第 4 条）。
> - **两条镜像路线（均有项目/上游一手依据，需用户拍板）**
>   | | ① 本仓既定：kissqy R1 | ② 上游最新：20261027 复刻镜像 |
>   |---|---|---|
>   | 文件 | **本机已有**：`.upstream/downloads/microduck-zero3w-0.15.1-R1.img.xz`，732 MB / 767,412,924 B，2026-11-14 本机实算 sha256 `75da978b…a7bce5` 与 `image_pairing_contract.json` pin **逐字一致**，零下载 | `microduck-replica-20261027.img.xz`，741,604,104 B / sha256 `91ab5550…`（`superpowers/verification/2026-10-27-web-updates-publication.md`），**本机没有，需下载** |
>   | 烧前处理 | ⚠️ **V1.12（AIC8800）板须先跑 `kissqy-r1-v112.sh` 换引导**，产出 `*-V112.img` 再烧；需 Linux/WSL2 + sudo（本机 `MicroDuckUbuntu` WSL2 可用，2026-11-14 实查） | **Etcher 直接烧 `.img.xz`、不用解压**（同文档 §2 第 3 条），无需换引导、无需串口 |
>   | 首启热点 | `Microduck-kissqy` / `12345678` / `http://10.42.0.1:8088` | `Microduck-xxxx` / 密码 **`microduck`** / `http://10.42.0.1:8000/`，等 **3 分钟左右**（首次开机扩容 + 起名 + 认 IMU） |
>   | 一手依据 | `kissqy-r1-v112.sh` 头注、`card_build_contract.json::source_scripts[1]`、`HD1910-20261012-kissqy镜像R1分析.md` §2/§7 | `烧录和第一次使用.md` §2–§4、`热点与主板型号排查.md` |
>   | 未验证点 | R1 分析 §6.1 自述改引导镜像「**还没上机**」⇒ 该路线首启热点在本项目这块板上从未实机复现 | 该文档实测板为 ZERO 3W 无 eMMC + 32 GB 卡，**未写明板子丝印版本**；能否直接适配 V1.12 无一手依据 ⇒ `UNVERIFIED_hardware` |
> - ⚠️ **关键未知**：板子背面丝印版本（V1.12 / V1.12J / 其他）与卡容量均未确认。R1 分析 §4/§7 明写 V1.12 用 Armbian 主线 U-Boot 起不来、2026-09 批 V1.12J 可能还要换设备树。
> - ⚠️ 许可：两份镜像均为作者**个人非商业**许可，不得随套件预装/分发、**不得卖烧好的卡**（`烧录和第一次使用.md` 开头）。
> - ✅ **2026-11-14 现场执行结果（路线 ① 已做完，详见 `microduck-主板到货-烧卡操作卡-2026-11-14.md`）**
>   - F 盘实测：**Disk 2 / USB / 62,325,260,288 B / MBR / FAT32 / 空白**（盘内仅 `System Volume Information`），与 Disk 0/Disk 1 两块 NVMe 系统盘可明确区分；本机原本无任何烧卡工具。
>   - ① 依赖的瑞莎 u-boot deb 原 URL 实测 **404**（连目录根亦 404）；检索到南阳理工镜像站 `mirror4.nyist.edu.cn/radxa-deb/.../u-boot-rk2410_2017.09-64-39cd993_arm64.deb`，下载到脚本目录，实算 sha256 `fb319203…bce7` 与脚本内 pin **逐字一致** ⇒ 脚本跳过 curl，全程离线可执行。
>   - WSL2 `MicroDuckUbuntu` 跑 `kissqy-r1-v112.sh … --overlay i2c4-m0`，**7/7 步通过** → `microduck-zero3w-0.15.1-R1-V112.img`（3,157,262,336 B，sha256 `d8207ede…24f41`；WSL `sha256sum` 与 Windows `Get-FileHash` 双工具一致）。
>   - 独立验证 `verify_v112.sh`：镜像扇区 64 / 16384 内容 md5 **=** deb 内 `idbloader.img` / `u-boot.itb` 首扇区；**负对照** R1 原包同位置扇区完全不同；只读 loop 挂载确认 `extlinux.conf` 含 `i2c4-m0` + V112 标记齐全 ⇒ 改动真实发生，非脚本空转。
>   - ② 资源经 GitHub REST API 核实（741,604,104 B / sha `91ab5550…d0194` 与项目验证文档一致），但实测下载 ~120 KB/s、ETA >1 h ⇒ 停止任务并删除 31,289,344 B 残片，**本次不采用**，降为「以后要新功能时」的备选。
>   - 烧卡工具改用便携版 `rufus-4.15p.exe`（1,989,992 B，`DD Image mode` 逐字节写 raw img）。⚠️ **非上游指南指定的 Etcher**（Etcher 便携版 284 MB 下载限速），标 `UNVERIFIED_print`。写盘为不可逆整盘覆盖，**留待用户在工具内核对目标盘后手动 START**，本轮未擅自写 F 盘。
>   - ⚠️ 板子丝印版本仍未确认，本次按「V1.12」假设换引导；若非 V1.12，R1 原包仍在本机可随时重烧。状态口径不变：`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`。

> 🔁 **1.0b 卡插好之后，先做一次完整断电重启（2026-11-14 补）**：拔 OTG 电源 → 等 5–10 s → 再插回。理由：瑞莎 FAQ Q6 原文「**连接串口后上电**」，U-Boot 输出只在上电瞬间出现；若卡是在板子已通电时插入，boot ROM 不会重扫启动介质（厂商文档未明写热插行为，此处按保守操作，不赌）。
> **上电后按这个顺序判，别一上来判板子坏**（来源见下）：
> 1. **电源灯**：瑞莎 FAQ Q2「正常启动时，电源指示灯应常亮；闪烁或不亮可能是电源问题」⇒ 先排供电，且 Q5 明写「请勿使用高于 5V 的电源适配器，可能损坏设备」。
> 2. **绿灯常亮但 HDMI/串口无输出 ≠ 板子坏**：Radxa 社区论坛有同系列无 eMMC 板（`RS107-D2E0H0W15`）完全相同症状，真因是 **microSD 卡槽方向与官网产品页示意图相反，卡要字面朝上（能看到 logo）插**，翻过来即启动。⚠️ 该帖是 **2GB 无 eMMC SKU 的用户案例、非厂商文档**，本板为 1GB 无 eMMC（`RS107-D1E0H?W15`），同系列不同 SKU、推测同 PCB，**未实机确认**，仅作排障线索。
> 3. **卡是不是按 1.1 配方做的**：本仓 `card_build_contract.json` 一手口径 —— `kissqy-r1-v112.sh` 的作用是「在 kissqy Public Image R1 上**只换引导**，使 V1.12 板也能开机」（须写 idbloader/u-boot.itb 到指定扇区、把 overlay 从 armbianEnv.txt 搬进 extlinux.conf）。**R1 原包直接 Etcher 烧进卡、没跑换引导脚本 ⇒ 黑屏/只亮灯属预期，不是硬件故障**。
> 4. 上述都过仍无输出，再接 1500000n8 串口看 U-Boot 报错（FAQ Q2 末步），或走 R1 保留的「**首次热点配网**」+ SSH（contract `keeps_unchanged`）。
> 📚 依据：瑞莎 `docs.radxa.com/zero/zero3/faq` Q2/Q5/Q6（2026-11-14 检索原文，厂商 FAQ）；`forum.radxa.com/t/zero-3w-not-booting-from-microsd/27134`（社区用户案例，非厂商）；本仓 `tools/hd1910/card_build_contract.json` + `.upstream/replica/tools/radxa/kissqy-r1-v112.sh`（项目一手）。

> 💡 **1.0c 免接线验活：先认清卡是哪条路线（2026-11-14 补 / 当日二次订正）**
>
> 🔴 **订正留档**：本段初版把 `Microduck-kissqy` 热点当成「本项目这张卡」的通用验活手段，**口径错了**。该热点只属于 **kissqy R1 一键镜像**（含其换引导版）；项目 `card_build_contract.json` 的另一条主线 `build-armbian-card.sh` 做的是纯 Armbian 卡，**根本不发热点**。用户 2026-11-14 质疑「为什么叫这个名字、这对吗」后回查三份一手脚本/文档确认，遂补下表的路线判别。原「搜不到 ⇒ 优先怀疑没换引导」的排序同样不成立：先验卡路线，再谈引导。
>
> **三条互不相同的卡路线（决定该不该有热点）**
>
> | 路线 | 一手来源 | 首次开机网络行为 | 该搜什么 / 怎么进 |
> |---|---|---|---|
> | **A. Armbian 底包卡** | `tools/hd1910/card_build_contract.json` 引用的 `.upstream/replica/tools/radxa/build-armbian-card.sh`（`card_build_contract.json::source_scripts[0]`） | `WIFI_SSID` 填了 → `wpa_supplicant` **直连家里 WiFi**；留空 → 公开镜像模式，**只能走 USB 串口进去连网**。脚本头注明写「基础镜像没有安装 NetworkManager/nmtui」 | **无热点是预期行为**。填了 WiFi 就去路由器后台找新设备 / 扫 IP；留空就接 1500000n8 串口 |
> | **B. kissqy R1（含 V1.12 换引导版）** | `kissqy-r1-v112.sh` 头注 + `card_build_contract.json::source_scripts[1]` 的 `keeps_unchanged` 明列「首次热点配网」；`HD1910-20261012-kissqy镜像R1分析.md` §2/§7 两处明文 | 首次开机自发 AP，之后才生成 SSH 密钥、打开 SSH | 搜 **`Microduck-kissqy`** / 密码 **`12345678`** / 配网页 **`http://10.42.0.1:8088`**。**账号默认锁着**（root/radxa 无密码，首次配网自设，配网页要求登录密码 ≥12 位）⇒ 瑞莎 FAQ Q7 的 `radxa/radxa` 不适用 |
> | **C. 20261027 / 20261104 复刻镜像** | `.upstream/replica/docs/热点与主板型号排查.md`、`更新说明-20261104.md`（**不在本仓做卡 contract 内**） | 由 `microduck-netcheck` 管 WiFi 与回退热点；源码修复候选为「累计 **123 秒**离线后触发回退判定，设备枚举另有耗时」（该候选 37 项离线测试通过，**实机断网回退未验证**） | 搜 **`Microduck-xxxx`**（带后缀）→ 密码 **`microduck`** → `http://10.42.0.1:8000/`，首启等 **3 分钟**（`烧录和第一次使用.md` §3–§4 一手）。**≠ 路线 B 的 8088**，两个端口不要混 |
>
> - **卡路线的离线判别法**（把卡插回 PC，WSL2 可读 ext4）：有 `/boot/extlinux/extlinux.conf` + R1 的 `armbianEnv.txt` ⇒ B；有 `/root/先连WiFi.txt` + `/etc/wpa_supplicant/wpa_supplicant-wlan0.conf` ⇒ A；有 `microduck-netcheck.service` ⇒ C。三者文件特征均取自上述脚本/文档一手原文。
> - **绿灯常亮 = 供电正常**（瑞莎 FAQ Q2「正常启动时电源指示灯应常亮」），**≠ 启动成功**：Radxa 社区有 ZERO 3W「solid green LED, no boot from SD/eMMC, no MASKROM」案例（`forum.radxa.com/t/zero-3w-suddenly-stopped-booting-solid-green-led-no-maskrom-detected/31347`）。⚠️ 口径冲突：第一代 Radxa Zero 社区称绿灯闪烁 = heartbeat = 已启动，与 ZERO 3 厂商 FAQ「闪烁=供电问题」相反；**不同板/不同镜像不可互推**，本板行为未实机标定，标 `UNVERIFIED_hardware`。
> - **热点出现** ⇒ 已启动到**用户态**，是比绿灯强得多的「板子活了」证据；但 **≠ 1.2 的正式 PASS 判据**（判据原文是「串口看 U-Boot→内核→login」）。按 `COLLECTED != PASS`，只记观察值，不自动判绿。
> - **搜不到热点的排障顺序**（按证据强度，逐条挂源）：
>   1. **先判卡路线**（上表）——路线 A 本来就没热点，别当故障查。
>   2. **热点不依赖舵机 / IMU / 摄像头 / ToF**：`热点与主板型号排查.md` 一手原文「服务只依赖网络管理和首次初始化顺序，不依赖 `robotd`、舵机 ID 或总线 IMU 在线。首次初始化先创建热点配置，再尝试识别 I²C IMU；没有找到 IMU 也会完成热点配置」。⇒ 裸板没接 HAT/摄像头/ToF **不是**搜不到的原因；`mediad`/`tofd` 反复崩溃（`kissqy-r1-v112.sh` 头注）属已知预期，**不得**因此勾 `--no-camera`/`--no-tof`（订正㉑ 必需、B8 拒 rc=1）。
>   3. **板型**：瑞莎 preparation 页明写 **Zero 3E 无板载 WiFi**（3W 有）。3E 不加无线网卡就永远搜不到热点（项目一手排查文档 §11）。
>   4. **已连上家里 WiFi 就不再发回退热点**：`wlan0` 已连接时，应改用同网段访问鸭子当前 IP 的 `8000` 端口（项目一手排查文档 §17）。
>   5. **等待时长**：路线 C 的 123 秒离线回退 + 枚举耗时有一手依据；本段初版写的「等 1–2 分钟」对 R1 **无一手依据，是推断**，保守改为 **3–5 分钟**再看，标 `UNVERIFIED_hardware`。
>   6. **仍无热点且确属路线 B** ⇒ 再怀疑「R1 原包直接烧、没换引导」（V1.12 板用 Armbian 主线 U-Boot 起不来，`HD1910-20261013-夜-掉电-舵机D与蹭地.md` §1.1 实证「换成瑞莎的引导以后真机开机成功」）。换引导命令（脚本一手用法，需 Linux/WSL2 + sudo，含 loop mount，`dd` 只写镜像文件不碰物理盘）：
>      `sudo bash .upstream/replica/tools/radxa/kissqy-r1-v112.sh <microduck-zero3w-0.15.1-R1.img.xz> --overlay i2c4-m0` → 产出 `*-V112.img` 再烧卡；脚本会 `curl` 拉 `u-boot-rk2410` deb 并 `sha256sum -c` 校验（contract pin `fb319203…`），写 idbloader@64 / u-boot.itb@16384、生成 `extlinux.conf`。⚠️ R1 分析文档 §6.1 自述该改引导镜像「**还没上机**」，故 B 路线的首次热点配网在本项目这块板上**从未实机复现**，标 `UNVERIFIED_hardware`。
> - 📚 依据分级：三路线网络行为 / SSID / 密码 / 端口 = **本仓 `.upstream` 项目一手脚本与文档原文**（除下述 B 路线首启热点已现场观察外，其余均未在本板实机复现）；绿灯含义 = 瑞莎厂商 FAQ + 社区案例；`radxa.com` 产品页/硬件接口说明 = 本板型号页面实访；等待时长与 2.4G 频段建议 = 推断，未找到厂商明文。

> 🟢 **1.0d 现场实机观察：B 路线首启热点在本板出现（2026-11-14 用户回报「插上了」后）**
> - **最前置机械前提已核**（准则 12）：`Get-Disk` 只剩两块 NVMe 系统盘，**原 `Disk 2 / USB / 62.3 GB` 读卡器已不在** ⇒ 卡确已从 PC 拔出、插回主板；该卡写后 Quick 9/9 + 全量 SHA-256 = `V112.img` 的 `d8207ede…24f41`（操作卡 §4.6）。
> - 🔴 **踩坑：普通 `netsh wlan show networks` 只读「上一次扫描的缓存」，不发起新扫描**（2026-11-14 查资料核实：StackOverflow 46428202 / 30786358、`access_points` issue #11、roamr ADR-0004，均明确 netsh 显示缓存、`WlanScan` 才刷新、缓存可陈旧约 60 s）。现场第一次扫到 4 个 SSID 含 `Microduck-kissqy`，紧接着 5 次普通扫描只剩 1 个 ⇒ **一度像「热点消失了」，其实是缓存假象，不是板子掉线**。
> - ✅ **改判据为主动扫描**：`.upstream/downloads/wlan_scan_realtime.py`（纯 `ctypes` 调 `wlanapi!WlanOpenHandle/WlanEnumInterfaces/WlanScan`，只读、不改 profile / 不改连接 / 不写盘）强制刷新后等 4 s（Windows logo 扫描完成时限）再读，**连续 3/3 轮稳定命中 `Microduck-kissqy`**（每轮 `WlanScan rc=0`）。
> - **实读观察值**：SSID `Microduck-kissqy`，BSSID `cc:c8:37:e3:f2:1a`，信号 **93%**，2.4 GHz / 信道 11，WPA2-个人 / CCMP，802.11ac。信号极强且 BSSID 稳定，符合「近处同一台设备」；⚠️ 但**尚未做断电负对照**，不能 100% 排除同名 AP，标为强观察值而非因果证明。
> - **结论收窄（不放大）**：R1 分析 §6.1 自述「改引导镜像还没上机」这一条 `UNVERIFIED_hardware` **就此撤销** —— V112 换引导镜像在本板**首次开机确实到了用户态并发出了 B 路线热点**。但**不等于 1.2 PASS**：串口 `U-Boot→内核→login` 未看、`10.42.0.1:8088` 配网页未访问、账号/SSH 未验、板子背面丝印版本仍未确认。`COLLECTED != PASS`，只记观察值。
> - **下一步（按证据强度）**：① 手机关移动数据后连 `Microduck-kissqy` / 密码 **`12345678`** → 浏览器开 `http://10.42.0.1:8088` 看配网页（正对照）；② 断电 5 s 前后各做一次主动扫描，`Microduck-kissqy` 应随之消失／重现（负对照，闭合因果）；③ 接 1500000n8 串口走正式 1.2 判据。
>   > 🔴 **2026-11-14 自查订正**：本行初稿把密码误写成 `12345678`（受压缩记忆错值污染）。回一手 `HD1910-20261012-kissqy镜像R1分析.md` §2 第 27 行 + §7 第 106 行，以及**镜像内部** `Microduck-Setup.nmconnection` 的 `psk=`，三处均为 `12345678`，已按此改正。⇒ 具体数值不能只信摘要，用前必须回一手源核；**订正留档本身也要回读**，别把错值写成对值（本段首稿就犯了这个错，已二次订正）。
> - **状态口径不变**：`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`、A2 悬案闭合数 0；采购 SSOT / contract / xlsx 零改动；扫描脚本在已 gitignore 的 `.upstream/downloads/`，未入库。

> 📌 **1.0e 镜像内部配置核验 + 判据冲突与待办留档（2026-11-14「先记下来」）**
> - **只读挂载 `V112.img`**（offset `16777216`）核到的镜像内部一手事实：`Microduck-Setup.nmconnection`（`mode=ap` / `psk=12345678` / `band=bg` / `10.42.0.1/24`）、`microduck-setup.service`（描述 "independent of robotd"、`Restart=on-failure`）、`microduck-setup-portal.py`（`PORT=8088`；SSID 1–32 B / 家庭 WiFi 密码 8–63 B / 系统密码 ≥12 位；`chpasswd radxa:`；配网失败回退重发热点）、`microduck-public-image`（`test_hotspot()`、`skip-until-sealed`）。⇒ 热点参数由「项目文档 / 实机扫描 / 镜像内部配置」三方一致。
> - 🔴 **1.2 判据冲突（本轮发现，未擅自修改任何判据或镜像）**：`extlinux.conf` append = `console=tty1 consoleblank=0 cma=256M`，**无 `console=ttyS2`**；`/etc/systemd/system/serial-getty@ttyS2.service → /dev/null` 已 mask ⇒ 该镜像设计上串口**不会有内核日志、也不会有 login prompt**。而 1.2 要求「1500000n8 串口看 U-Boot→内核→login」，1.3 又要求「无 `console=ttyS2`」（UART2 留给舵机总线，overlay 含 `rk3568-uart2-m0.dtbo`）。⇒ 1.2 属通用板验收清单沿用口径，与本镜像冲突；**换验活方式须用户拍板**，备选：配网后 SSH / HDMI+键盘走 tty1 / 临时改 cmdline（后者会占用 UART2，风险高）。
> - 🔴 **串口硬件未就绪**：`Win32_SerialPort` 为空；PnP 仅 `USB-Enhanced-SERIAL CH343 (COM3)`、`Status=Unknown`、`Win32_PnPEntity` 查无此设备 ⇒ 与 11-14 实测 phantom(Code 45) 同型（本机 `ProblemCode` 属性读不到，不硬断言码值），物理层须**重新插线**；`.venv-mjlab` 内 `pyserial` 可用，但 CH343 在 1500000 非常规波特的支持未验证。
> - ⚠️ **BSSID 口径待核**：`cc:c8:37` OUI 实查 = Quectel Wireless Solutions（移远），与项目记录「V1.12 板 AIC8800 WiFi」不是同一名字（芯片 vs 模组厂可能不同，也可能是别的 IoT 设备）⇒ 不判矛盾，但把「热点来自本板」由「强观察值」收窄为「因果待证」，**断电负对照不能省**。
> - **待办清单（按执行者分组，未擅自开工）**
>   - **A · 我能直接做（需点头/配合）**：A① PC 连热点抓 `http://10.42.0.1:8088` 页面作硬证据（会短暂断家里 WiFi、建临时 profile，用完删）；A② 断电 5 s 前后各做一次 `WlanScan` 主动扫描（负对照）。
>   - **B · 需用户动手、我落证据**：B① 手机关移动数据连 `Microduck-kissqy` / `12345678` → `10.42.0.1:8088` 并回报页面；B② 报板子背面丝印版本（确认 V1.12 假设）；B③ 重插串口线或改接 HDMI+键盘；B④ 报绿灯常亮/闪烁。
>   - **C · 需用户拍板**：C① **1.2 判据改法**（SSH / HDMI tty1 / 临时 cmdline 三选一，本轮最该定）；C② 整机采购下单（软件线饱和，唯一杠杆，碰采购须拍板）；C③ A2 配网加密（Q3 决策）；C④ 安卓 App 真机 GATT 上板等悬案（等整机）。
> - **状态口径不变**：`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`、`COLLECTED != PASS`、A2 闭合数 0。本段纯新增，未动 1.2/1.3 判据、采购 SSOT、contract、任何 xlsx。

> 📌 **1.0f 候选 9 落地 + 1.2 判据适用性裁定（2026-11-14「继续，按照最优的来」）**
> - ✅ **候选 9「镜像内容基线清单」已实施**（唯一零风险项）：`microduck-software/tools/hd1910/v112_image_baseline.json`（16 文件 + 23 锚点 + 镜像 pin + 四态语义）与 `check_v112_image_baseline.py`（纯 stdlib 只读），配套 `tests/test_v112_image_baseline_cli.py`。两条独立算法（内核只读挂载 / 用户态 `debugfs`）7/7 哈希一致；`--selftest` **42/42**、CLI 回归 **13/13**、真镜像 `--check` = **`BASELINE_MATCH`（16/16 文件、23/23 锚点、image pin 一致）**；真镜像数据负对照「改 `commit=120`→`5` 必红，连 hash 一起重登记仍必红」通过。详见 `microduck-V112镜像-按开发规范审查与优化候选-2026-11-14.md` §7。
> - 🔴 **顺带订正两处事实**：① 候选 6 原写「journald 无显式上限」不准确，`10-robot.conf` 实读有 `Storage=persistent` / `SystemMaxUse=200M` / `MaxRetentionSec=3month`（判决「暂不实施」不变）；② 上一轮口述「24/24 锚点」是历史 24/24 数字串扰，一手 = **23 条锚点 / 23 ok**。数值用前必回一手源核（准则 13 再命中）。
> - ✅ **全量验证抓到并修掉两处真回归**：新工具未登记 `line_labels.json` → 6 个 pytest + 门禁红，已补登记 `META_GUARD`（51→52）；docs 里 `INCONCLUSIVE_LIVE_STATE_STREAM` 自 11-13 未进悬案契约 → `check_closure` 结构红，已按工具设计意图**补登记为 `UNVERIFIED` / `evidence=[]`**（7→8 条未闭合），**未**标 CLOSED/PASS、**未**动 `ship_verdict`。
> - ⚖️ **C① 1.2 判据已出裁定，未改判据**：见 `microduck-主板到货-1.2判据适用性裁定-2026-11-14.md`。1.2 与 1.3 对 V112 设计上互斥（1.3 要求无 `console=ttyS2` + mask getty，UART2 归 robotd）⇒ 判 **`N/A_BY_DESIGN`（对象错配）**，§1.2 原文一字不改、不判 PASS/FAIL、仍 `UNVERIFIED_hardware`；替代验活三条（配网页正对照+断电负对照 / SSH 读 `cmdline`+`journalctl -b` / HDMI tty1），临时改 cmdline 明确不推荐。**C① 由「待拍板」变「已裁定」；C② 采购下单、C③ A2 加密、C④ 真机 GATT 仍待拍板/等整机。**
> - ✅ **最终全量验证（开发规范 §6.2）**：`pytest tests/ -q` **319 passed / rc=0**；`run_all_gates.py --check` **ALL_PASS 51/51、NOT_PASS 0、coverage gap 0**；新工具已在门禁 `--list`（第 21 行 `hd1910/check_v112_image_baseline.py`）。过程中两次全量分别红 6 项 / 7 项，均按真因补登记修复（未删断言、未放宽判据）。
> - **状态口径仍不变**：`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`、`COLLECTED != PASS`、A2 闭合数 0。未改镜像、未动 1.2/1.3 判据、未动采购 SSOT/contract/xlsx、未下单。

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
