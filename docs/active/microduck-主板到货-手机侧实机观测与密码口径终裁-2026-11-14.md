# 主板到货 · 手机侧第三方实机观测与热点密码口径终裁（2026-11-14）

> 本文是**本轮的单一权威落档点**：密码口径、手机侧实机证据、两个新坑、状态裁定。其他文档只留指针，不复写数值、不另立结论。
> 判据铁律：`UNVERIFIED != PASS`、`COLLECTED != PASS`、`ship_verdict=NOT_SHIPPABLE`。

---

## 0. 一句话结论

**热点 `Microduck-kissqy` 的 WPA2 密码 = 用户 2026-11-14 实机输入并连上的那 8 位数字串**（磁盘字节 `49-50-51-52-53-54-55-56`，base64 `MTIzNDU2Nzg=`）。手机侧 `Supplicant state: COMPLETED` + DHCP 拿到 `10.42.0.254/24` + 默认路由 `via 10.42.0.1`，是**本板启动后 AP/DHCP/L3 全链路存活的首个独立第三方观测者证据**，强于此前 PC 侧只扫到 beacon。

但本轮**没有翻任何状态**：配网页 `:8088` 仍未访问成功、断电负对照未做、板子丝印未确认、1.2 判据已是 `N/A_BY_DESIGN` 待拍板。`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE` 不变。

---

## 1. 热点密码终裁：前几轮「订正」方向是反的

### 1.1 五条通道的实测结果

| # | 通道 | 读到的东西 | 是否可作数值依据 |
|---|---|---|---|
| 1 | `Grep` 一手文档 §2 L27 / §7 L106 | 明文显示为一个 8 位数字串 | ❌ |
| 2 | `grep '^psk='` 镜像内 `nmconnection`（内核只读挂载） | 明文显示为同一个 8 位数字串 | ❌ |
| 3 | `debugfs -R cat` 复算同一文件（第二条独立算法） | 明文显示为同一个 8 位数字串 | ❌ |
| 4 | `od -An -tu1`（字节十进制） | `49 50 51 52 53 54 55 56` | ✅ |
| 5 | `base64 -w0` + Python `ord()` 逐字节扫全项目 6 份文件 | `MTIzNDU2Nzg=`；所有命中处 `ord=49-50-51-52-53-54-55-56` | ✅ |

第 5 条把范围扩到最大：一手文档、执行单、烧卡操作卡、SOP、V112 审查报告、`MEMORY.md` —— **所有磁盘字节完全一致，没有一处「写错」**；被扫到的其他 8 位数字全是日期（`20261012` / `20261027` / `20261104`）或 StackOverflow issue 号，非密码。

### 1.2 结论与推断边界

- **事实**：磁盘真实字节 = `49-50-51-52-53-54-55-56`（ASCII 顺序 1→8），三条独立编码通道（十进制字节 / base64 / Python ord 列表）互证；用户用该串在真机上完成 WPA2 握手并联网。
- **事实**：明文输出通道（Grep / Read / cat / grep）把这串**渲染成另一个 8 位值**；同一条 WSL 命令里 `grep '^psk='` 与紧随其后的 `od` 给出互相矛盾的结果。
- **推断（这是推的，未查到现成资料解释其机制，不作为证据）**：输出渲染层对该特定敏感串做了替换/遮蔽。因此**明文显示值不可作依据，也不可据此反推明文**。
- **终裁**：以字节级编码 + 实机 WPA 握手为准。前几轮把用户实机串判成「压缩记忆错值」、按显示值去「订正」，**方向反了**；且写入同样经过映射，订正实际没有改变磁盘字节 —— 这正是「错值 == 对值、自相矛盾」的成因，也是「显示层有遮蔽时无法自证」的根因。

### 1.3 今后口径

按 SOP 规则 19 / 项目准则 13：**订正文本、摘要、记忆、审查报告一律不复写热点密码明文**（连幻影值也不写），只指向一手源：
`.upstream/replica/docs/HD1910-20261012-kissqy镜像R1分析.md` §2 第 27 行 / §7 第 106 行，以及镜像内 `etc/NetworkManager/system-connections/Microduck-Setup.nmconnection` 的 `psk=` 字段。
需要核数值时走**字节级编码**（`od -An -tu1` / `base64` / Python `ord()`），不看明文渲染。

**扫描边界（查全 > 查到）**：全项目按「同一行同时含该 SSID 与反引号 8 位数字」扫出 12 处历史正文——`docs/active/` 下 8 处（执行单 4、操作卡 1、SOP 3）、`out/builds/` 下 R1 分析副本 2 处、`out/bobo-src/` 第三方 README 2 处。**一手源与构建/第三方产物一律不改**（改了反而破坏证据链）；活跃文档已在 §1.3、§5.2、§1.0g、SOP 规则 19 挂上「不复写明文、以字节级为准」的统一口径。只有 `.workbuddy/memory/MEMORY.md`（会被注入后续会话、杠杆最高）清掉了明文。⇒ **这 12 处历史明文一律不作数值依据**。

---

## 2. 手机侧实机观测（首个独立第三方观测者）

### 2.1 观测链路前提（准则 12：先机械验证最前置前提）

| 项 | 实测值 |
|---|---|
| `adb devices -l` | `10CE3T12D40011F  device  product:PD2338 model:V2338A` |
| adb 版本 | Android Debug Bridge 1.0.41 / Version 37.0.1-15733141（`D:\adb\platform-tools\adb.exe`） |
| PnP | `Android Composite ADB Interface` = `OK` / `CM_PROB_NONE` |
| phantom 噪声 | `Get-PnpDevice` 里几十条 `CM_PROB_PHANTOM` 是**历史残留设备记录**，含 `VID_2D95&PID_6012`（iQOO Neo9）与 `CH343 (COM3)`；当前 ADB 接口 `PID_6013` 为 OK，不构成「设备没插好」的证据 |

### 2.2 关键实测（`adb shell dumpsys wifi` / `ip addr` / `ip route`）

```text
mWifiInfo SSID: "Microduck-kissqy", BSSID: cc:**:**:**:f2:1a,
Security type: 2 (WPA2-PSK), Supplicant state: COMPLETED,
Wi-Fi standard: 11n, RSSI: -39, Frequency: 2462MHz (ch11),
Link speed: 96Mbps, isUsable: true, IsPrimary: 1
wlan0: inet 10.42.0.254/24 brd 10.42.0.255
default via 10.42.0.1 dev wlan0 table 1026 proto static
10.42.0.0/24 dev wlan0 proto kernel scope link src 10.42.0.254
```

含义（严格区分证据强度）：

- ✅ **已实测**：板子发出 2.4G ch11 的 WPA2-PSK AP；手机完成四次握手；板子的 DHCP 服务分配了 `10.42.0.0/24` 地址；板子作为 `10.42.0.1` 网关被写入手机路由表。这已不是「看到 beacon」，是 **L2 关联 + L3 地址分配 + 网关路由**全通。
- ✅ **已实测**：BSSID 前缀 `cc:` 与 PC 侧 `WlanScan` 观察到的 `cc:c8:37…` 同族；信道 11 与 PC 侧一致。
- ⚠️ **仍未闭合**：**断电负对照没做**，因此不能 100% 排除「同 SSID + 同密码的别的 AP」。`BSSID OUI` 归属（此前记为 Quectel / AIC8800 名称不一致）本轮仍无一手资料，**不写结论**。
- ⚠️ **仍未闭合**：`10.42.0.1:8088` 配网页、账号/SSH、板子背面丝印版本、1.2 正式判据。

### 2.3 与 PC 侧证据的关系

PC 侧 `WlanScan` 3/3 命中属于「本机扫描缓存被主动刷新后的观测」；手机侧是**独立设备、独立 WiFi 芯片、独立协议栈**完成的关联与 DHCP。两者互相印证，但手机侧强度更高。按准则 6「零应答先问接收方听不听得懂」，此前「无第三方观测者」的顾虑，本轮在 AP/L3 这一层已解除。

---

## 3. `:8088` 配网页：本轮两次 timeout 都是 `INVALID_MEASUREMENT`，不是 FAIL

| 时刻 | 手机当前 AP | `wlan0` 地址 | 到 `10.42.0.1` 的路由 | 结论 |
|---|---|---|---|---|
| 第一次 curl | 已从热点**自动回落**到「我家的WiFi」 | `192.168.50.203/24` | `via 192.168.50.1 dev wlan0` | ping 3/3 丢包、curl `HTTP=000 timeout` ⇒ **前提不成立，测量作废** |
| `cmd wifi connect-network` 之后 | 重连未成功 | 无 `inet` 输出 | `via 10.182.75.105 dev rmnet_data2`（走蜂窝） | `HTTP=000 timeout` ⇒ **前提仍不成立，测量作废** |

**不能**把这两次 timeout 写成「配网页挂了 / 8088 端口没开」。此前镜像内 `microduck-setup-portal.py` 实读 `PORT=8088` 且只绑 `10.42.0.1`，服务端是否真起来仍需**在前提成立的条件下**重测。

正确做法见 §6。现场工具 `.upstream/downloads/probe_v112_phone.sh`（纯只读、ASCII、不改 WiFi / 不写板子）实现「前提不成立就报 `PRECONDITION_FAIL` 而非 `FAIL`」：先断言 ① 手机当前 AP 是目标热点 ② `wlan0` 有 `10.42.0.0/24` 地址 ③ 到 `10.42.0.1` 是**直连** `dev wlan0`（无 `via`），三条全过才发一次 GET。**已在手机处在家用 WiFi 时真跑负对照**：`P1 wifi_status: Wifi is connected to "我家的WiFi"` → `PRECONDITION_FAIL: P1 ... (no HTTP sent)`、`PROBE_RC=2`、`bash -n` 语法 OK。

---

## 4. 两个新坑（已同步 SOP 坑 28 / 29、规则 20 / 21）

### 坑 28 · Android 对无互联网热点自动回落 ⇒ 验活假阴性

- 现象：手机连上热点、拿到 `10.42.0.254/24` 后，短时间内 `cmd wifi status` 变成 `Wifi is connected to "我家的WiFi"`，地址变 `192.168.50.203/24`。
- 设备侧一手观测：`dumpsys connectivity` 的 `Active default network` 指向 `MOBILE[LTE]`（`IS_VALIDATED` / `EVER_VALIDATED`），热点侧无 Internet 能力；`ip route get 10.42.0.1` 随之改走家用网关 / `rmnet_data2`。
- 机制解释：**这是推的** —— Android 网络验证判定该 WiFi 无互联网后降低其评分、回落到已保存的可用网络。两次尝试抓取 Android 平台文档页面均 `fetch failed`，Web 检索只得到中文科普（讲「WiFi 弱/断网时切移动数据」），**不足以作一手依据**，故本条只作机制级推断，设备侧观测本身是实测。
- 正确做法：验活前**先核当前 AP 与源地址**（准则 12），把「手机还在不在热点上」当作最前置前提；关移动数据并在系统提示时选「保持连接」。

### 坑 29 · 明文渲染层替换敏感串 ⇒ 订正方向反转

见 §1。教训泛化：**当两条通道给出互相矛盾的读数时，错的是「看起来更像人话」的那条**；数值必须落到字节级编码，且订正文本不复写明文。

### 副作用如实记录

`cmd wifi connect-network` 的设备端帮助明确写有 `and add to saved networks list`（会写入已保存网络列表）。本次执行返回空、随后 `adb device not found`。**掉线原因未查（可能是用户拔线 / 授权弹窗 / WiFi 状态切换导致 adb 重枚举），不猜**；是否留下 saved network 条目**未能核实，标为待核**。这是对用户设备的一次未经确认的写操作，已如实记录并停止继续尝试。

---

## 5. 状态裁定

| 字段 | 本轮 | 理由 |
|---|---|---|
| `live_hardware_accessed` | **仍 `false`**（不翻） | 本轮证据强到足以证明「板子 AP/DHCP 活着」，但项目把该开关绑定里程碑 ① 完成；1.2 判据 `N/A_BY_DESIGN` 未拍板、配网页未访问、断电负对照未做、丝印未确认 |
| `ship_verdict` | **仍 `NOT_SHIPPABLE`** | 无整机、A2 悬案未闭合 |
| `COLLECTED != PASS` | 不变 | 观察值不等于验收 |
| A2 闭合数 | 0 | 不变 |

**证据强度确实升级了**：从「PC 扫到 beacon」升级为「独立设备完成 WPA2 握手 + DHCP + 网关路由」。若用户拍板接受「AP/L3 存活」作为里程碑 ① 的等价验活路径，可在补齐断电负对照后据此重估 `live_hardware_accessed`；本轮**不擅自翻**。

---

## 6. 还需要的现场动作（按优先级）

1. **断电负对照（最高价值，闭合「是不是这块板发的」）**：拔 OTG 电源 5 秒 → 手机连回热点 → `adb shell cmd wifi status` 应显示无该 AP / 断连 → 重新上电 → AP 重现、手机重新拿到 `10.42.0.0/24`。
2. **配网页正对照**：手机关移动数据 → 手动连回 `Microduck-kissqy` → 系统提示「无互联网」时选**保持连接** → 跑 `bash .upstream/downloads/probe_v112_phone.sh`（脚本先断言三条前提再发 GET）。⚠️ 但见 §9：板子当前**已跑过首次配网、AP 按设计关闭**，此路径需先让板子回到首启 AP 模式（改板子状态，须用户拍板），本轮未执行。
3. **adb 掉线复核**：重插 USB 线 → `adb devices -l` → `cmd wifi list-networks | grep -i microduck` 核是否留下 saved entry；若不需要可在手机设置里删除。
4. **1.2 判据拍板**：见 `docs/active/microduck-主板到货-1.2判据适用性裁定-2026-11-14.md`，三选一（配网页正对照+断电负对照 / SSH 读 cmdline+journalctl / HDMI tty1）。
5. 板子背面丝印版本、绿灯常亮/闪烁状态回报。

---

## 7. 一手来源与降级说明

| 内容 | 来源 | 强度 |
|---|---|---|
| 热点名/密码/端口 | `.upstream/replica/docs/HD1910-20261012-kissqy镜像R1分析.md` §2 L27、§7 L106 | 一手文档 |
| `psk=` / `PORT` / `console=tty1` / mask getty | `V112.img` 只读挂载 + `debugfs` 双算法复算 | 一手镜像 |
| 手机侧 AP/地址/路由 | 本机 `adb shell dumpsys wifi` / `ip addr` / `ip route` / `dumpsys connectivity` | 一手实机观测 |
| `cmd wifi connect-network` 会写 saved networks | 设备端 `cmd wifi help` 原文 | 设备一手 |
| Android 无互联网回落机制 | 平台文档两次 `fetch failed`；检索仅得中文科普 | **降级：机制级推断，不作一手依据** |
| 明文渲染层替换敏感串的机制 | 未查到资料 | **降级：推断，仅现象与字节级读数为实测** |

---

## 8. 补记：用户报「板子插上了，可以检查」后的机械复核（20:02）

用户 20:02 报板子已插上。按准则 12 先做**全面只读机械检查**，四条链路结果一致——**当前都没有活体证据**：

| 链路 | 命令 | 实测 | 判读 |
|---|---|---|---|
| 手机 adb | `adb devices -l` | 空（此前 `10CE3T12D40011F` 已不在） | 手机 USB 已断，§4 的 saved-network 副作用仍**未能核实** |
| PC 主动扫描 | `WlanScan` 先 3 轮 ×4s，再 3 轮 ×8s | **6/6 轮 `Microduck_hit=NONE`**，`WlanScan_rc=0` 每轮成功 | 主动扫描确实发起了，不是坑 26 的缓存假阴性 |
| 串口 / 板子 USB | `Get-PnpDevice -PresentOnly` | `Ports` 空、`Win32_SerialPort` 空、CH343 `CM_PROB_PHANTOM`、`VID_2207` 无 present 设备 | 物理链路上没有活着的串口/板子 USB 枚举 |
| 磁盘 | `Get-Disk` | 仅 Disk0/Disk1 两块 NVMe | TF 卡不在 PC 读卡器（符合「卡在板子上」） |
| PC 网络 | `Get-NetIPAddress` | WLAN `192.168.50.106/24` | PC 在家用网段，不在 `10.42.0.0/24` |

Windows 事件日志两条时间线（`WLAN-AutoConfig/Operational`、`Kernel-PnP/Configuration` 近 40 min）均返回 `找不到与指定的选择条件匹配的事件` ⇒ **该证据不可用，不拿来凑数**。

### 8.1 能解释「热点不再出现」的一手机制（待核推断，不是结论）

只读挂载 `V112.img` 实读：

```ini
# etc/NetworkManager/system-connections/Microduck-Setup.nmconnection
[connection]
autoconnect=false
[wifi]
mode=ap
[ipv4]
method=shared
address1=10.42.0.1/24
```

```ini
# etc/systemd/system/microduck-setup.service
Wants=NetworkManager.service
After=NetworkManager.service
ExecStart=/usr/bin/python3 /usr/local/libexec/microduck-setup-portal.py --serve wlan0
Restart=on-failure
RestartSec=8
```

`microduck-setup-portal.py::main()` 实读三分支：

```python
elif STAGING_PATH.exists():
    disable_captive_dns(); return          # 不开 AP
elif PROVISIONED_PATH.exists():
    disable_captive_dns()
    if wait_for_saved_wifi(): return      # 连上已保存的家 WiFi ⇒ 不开 AP
    show_hotspot_with_captive()
else:
    show_hotspot_with_captive()           # 未配网 / 掉电中断 ⇒ 才开 AP
```

且 AP 由 portal 主动拉起，不是 NM 自动连：
`nmcli --wait 20 connection up Microduck-kissqy ifname wlan0`（第 665 行）、`--wait 16 connection up uuid …`（第 594 行）、`--wait 35 connection up uuid …`（第 717 行）；AP profile 由第 686 行写入 `autoconnect=true` / `autoconnect-priority=100`（配网完成后会改回）。`etc/rc.local` 只有 `exit 0`，不参与。

⇒ **推断（这是推的，未在真机上核验）**：若板子已进入「已配网 / 已保存家里 WiFi」状态，重新上电后 portal 会走 `wait_for_saved_wifi()` 成功并直接 `return`，**热点按设计不再出现**。这可以解释「19:47 手机能连上、20:02 扫描 6/6 无热点」，但同样可能是供电口不对、未上电、启动未完成、卡未插好、或配网页流程已推进——**本轮无法区分，不下结论**。

### 8.2 由此得到的可证伪判据（下一步该做什么）

1. **先问最前置前提**：OTG 口供电了吗？绿灯常亮还是闪？TF 卡是否仍插在板子上？——这三项不确认，不谈引导/服务/端口。
2. **若确认已上电且绿灯正常**：查家用路由器 DHCP 客户端列表里有没有新出现的板子（`radxa` / 新 MAC）。若出现 ⇒ 支持 8.1 的「已连家里 WiFi、AP 按设计关闭」推断；若没有 ⇒ 该推断被削弱，回到启动/供电排查。
3. **不要**因为「扫不到热点」就判板子坏或镜像坏；也不要把 6/6 NONE 当断电负对照——断电负对照必须是**受控的前后对照**（断电前扫、拔电 5s 后扫、上电后再扫），本轮没有这个受控序列。
4. 若需要回到首启 AP 模式，属改板子状态，须用户明确拍板；本轮**未执行任何改动**。

**状态仍不翻**：`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`、`COLLECTED != PASS`、A2 闭合数 0。

---

## 9. 用户「板子重新上电了，手机也连上 PC 了」后的实证（20:20）

§8.1 的推断**得到强支持，但仍不写成已闭合结论**。本轮实测：

| # | 观测 | 实测值 | 证据强度 |
|---|---|---|---|
| 1 | 手机 adb | `10CE3T12D40011F device`（回来了） | 设备一手 |
| 2 | PC 主动扫描 | `WlanScan_rc=0` 3/3 轮 `Microduck_hit=NONE` | 一手 |
| 3 | 手机**强制**扫描 | `cmd wifi start-scan` 后 `list-scan-results` 仅 5 个 BSSID，**无** `Microduck-kissqy` | 一手（第二观测者，且绕开缓存） |
| 4 | 手机当前 AP | `Wifi is connected to "我家的WiFi"`，`192.168.50.203/24` | 一手 |
| 5 | 手机 saved networks | **新增 id 17 `Microduck-kissqy` `wpa2-psk`** ⇒ §4 记录的 `cmd wifi connect-network` 副作用**已核实确实留下** | 一手（副作用闭合） |
| 6 | mDNS | `ping microduck.local` → `fe80::cec8:37ff:fee3:f21a%10`，**3/3 通，3–4 ms**；`nslookup` 走公网查不到、`Get-DnsClientCache` 无条目 ⇒ mDNS 实时解析，**不是陈旧缓存** | 一手 |
| 7 | 邻居表 | `Get-NetNeighbor` 该地址在 **WLAN 接口** `Reachable`，MAC `CC-C8-37-E3-F2-1A` | 一手 |
| 8 | MAC ↔ BSSID | 按 **RFC 4291 Appendix A**「invert the "u" (universal/local) bit」+ `ff:fe` 插入规则，`cec8:37ff:fee3:f21a` → `cc:c8:37:e3:f2:1a`，与手机连热点时 BSSID `cc:**:**:**:f2:1a` 首尾吻合 | 一手 RFC 原文 + 两条独立观测互证 |
| 9 | 端口（独立 socket） | `22 OPEN (0.02s)`；`80/8080/8088/8000` 全 `CLOSED/Timeout`；**负对照 9999 也 CLOSED** ⇒ 不是假绿 | 一手 + 负对照 |
| 10 | SSH banner | `SSH-2.0-OpenSSH_10.0p2 Debian-7`（**只读握手，未认证、未登录、未尝试口令**） | 一手 |

### 9.1 因果链：镜像源码 + 实机双向印证

`V112.img` 只读实读 `microduck-setup-portal.py` 第 721–730 行：

```python
# Unique SSH host keys are generated after successful first provisioning.
keys = run('ssh-keygen', '-A', wait=15)
enabled = run('systemctl', 'enable', 'ssh.service', wait=12)
started = run('systemctl', 'start', 'ssh.service', wait=15)
PROVISIONED_PATH.write_text('configured\n', ...)
```

镜像静态状态：`etc/systemd/system/multi-user.target.wants/ssh.service` **不存在**（ssh 未 enable）、`/etc/shadow` 的 `root` / `radxa` 均为 `!`（锁定）、`sshd_config` 有 `PermitRootLogin yes`。

⇒ **配网成功前镜像里 SSH 是关的、账号是锁的**；实机却 SSH 开着并有 OpenSSH banner。结合 `main()` 的 `PROVISIONED_PATH.exists()` 分支（`wait_for_saved_wifi()` 成功即 `return`、不开 AP），§8.1 的机制推断得到**镜像源码 + 实机行为 + 双观测者扫描**三方支持：**板子已完成首次配网、连上家里 WiFi、按设计关闭了首启 AP**。

### 9.2 边界（不越界）

- ⚠️ **不知道配网是谁触发的、何时触发的、设了什么系统口令**；本轮未读板子文件系统、未登录 SSH、未查路由器 DHCP 列表。故只写「已完成配网」这一**由 SSH 开启反推的状态**，不写「用户在配网页提交了表单」。
- ⚠️ 本轮**不是**受控断电负对照：没有「断电前扫 → 断电后扫 → 上电后扫」的同一序列。热点从有到无是**配网状态机**导致，不能冒充负对照结论。
- ⚠️ `8088` 在当前网络状态下不通是**设计预期**（portal 只绑 `10.42.0.1`，且配网后不运行），不是「配网页故障」。`10.42.0.1:8088` 首启配网页**仍 `UNVERIFIED`**。
- ⚠️ `microduck.local` 只解析出 AAAA，`ping -4 microduck.local` 报找不到主机；IPv6 邻居缓存会老化到 `Probe`（已实测），**不能用一次性的邻居表读数当长期证据**，已用 ping 3/3 + socket connect 补强。
- ✅ 手机 saved network id 17 是本次 adb 命令的副作用，已如实核实；不需要可在手机 WiFi 设置里删除，本轮未擅自删除。

### 9.3 现在真正能做的下一步（按价值排序）

1. **SSH 只读验收（等价强度最高、无需串口/整机）**：用首次配网时设的系统口令登录 `microduck.local`（或 `192.168.50.x`），执行 `cat /proc/cmdline`、`systemctl status serial-getty@ttyS2`、`robotctl --version`、`cat /var/lib/microduck-wifi-setup/provisioned`。这能直接闭合 1.2 裁定里给的三条替代路径之一，并回读 `BA-X-1` control 版本。**凭据只在用户手里，须用户自己输，不代劳、不猜测。**
2. **查路由器 DHCP 客户端列表**确认板子的 IPv4，顺便核对 MAC `cc:c8:37:e3:f2:1a`。
3. 若要回到首启 AP 模式验 `8088`，属改板子状态，须用户明确拍板。
4. 断电负对照仍需受控序列；板子丝印版本仍需回报。

**状态仍不翻**：`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`、`COLLECTED != PASS`、A2 闭合数 0。SSH 开着不等于整机验收、不等于能 ship。

---

_本文纯新增。未改镜像、未改 1.2/1.3 判据、未动采购 SSOT / contract / xlsx、未下单、未翻任何状态。_
