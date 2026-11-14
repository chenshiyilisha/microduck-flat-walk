# microduck 主板到货 · SSH 只读实机验收与 App 适配（2026-11-14 21:00–21:20）

> 本文是**本轮实机的单一权威**。相关消费链（执行单 §1.0h、终裁文档 §10、SOP 坑 30 / 规则 22、审查报告 §8）只挂指针，不复制事实。
> 铁律：`UNVERIFIED != PASS`、`COLLECTED != PASS`、`ship_verdict=NOT_SHIPPABLE`。

---

## 0. 一句话结论

用户授权「全自动」并提供首次配网自设的系统口令后，**首次以只读 SSH 登录真板成功**。板子活着、已完成首次配网并连上家里 WiFi、软件栈在跑、BLE 前端对外广播可见；但 **15 个舵机 ID 全部缺失、IMU not ready、robotd 处于 read-only** ⇒ 登录的是 SBC 主板而不是整机，`live_hardware_accessed=false` 与 `ship_verdict=NOT_SHIPPABLE` **仍然成立且一个字没翻**。1.2 判据的三条替代验活路径中，「SSH 读 `cmdline` + `journalctl`」这条已由活体证据完成，**原判据仍 `N/A_BY_DESIGN`、原文不动**。

---

## 1. 方法与边界（凭据 / 身份 / 只读 / 负对照）

| 项 | 做法 | 证据 |
|---|---|---|
| 凭据 | 用户于 21:0x 提供，仅由进程环境 `MD_SSH_PASS` 读**一次**并立即 `pop`；不写入任何文件/日志/文档/git，不回显，最终回复不复述 | 全项目字节级扫描（片段以 base64 编码方式比对，**0 命中**）；脚本内 `source contains no credential assignment` 自检 PASS |
| 主机身份 | 源码内硬编码独立锚 `EXPECTED_FP`；该值由 IPv4 与 IPv6 link-local **两条 `ssh-keyscan` 通道**一致得到。指纹不符 ⇒ 断开且**零命令执行** | 三次登录均 `HOSTKEY_MATCH`；本地负对照「随机生成的 key 必不匹配」PASS；不写 `known_hosts`、不用 agent、不用公钥认证 |
| 只读约束 | 固定命令集 + 正向只读白名单；`--selftest` 注入 8 条写命令（`set-name` / `policy load` / `net connect` / `reboot` / `sudo` / 重定向 / `restart` / 命令拼接），**全部必须被拒** | `probe_v112_ssh_readonly.py --selftest` **12/12 PASS**（真跑两次，各抓一个真 bug：白名单漏 `=`；自检把凭据片段写进源码） |
| 现场工具 | `microduck-software/.upstream/downloads/probe_v112_ssh_readonly.py`（`.upstream/` 已忽略，不入库，与 `wlan_scan_realtime.py` / `probe_v112_phone.sh` 同惯例） | `--list` 三组 13/12/8 条；`--group all` 真跑 `rc=0`、340 行输出落 `/tmp`，凭据未落盘 |
| 未做 | **不** `sudo` / 重启 / 改配置 / 启停服务 / 连 BLE / 配对 / 改镜像 / 动采购 SSOT 或 xlsx / 下单 / 翻任何状态 | 命令集逐条只读；BLE 扫描仅 advertise 观测，零连接 |

---

## 2. 身份与网络：六条独立通道互证

| # | 通道 | 读数 |
|---|---|---|
| 1 | PC ARP / `Get-NetNeighbor` | `192.168.50.216` → `CC-C8-37-E3-F2-1A`（WLAN） |
| 2 | mDNS + RFC 4291 Appendix A | `microduck.local` → `fe80::cec8:37ff:fee3:f21a`，去 `ff:fe`、首字节 `ce→cc` 还原同一 MAC；**只有 AAAA 无 A**，解释了 `ping -4 microduck.local` 失败 |
| 3 | 手机侧（上一轮） | WPA2-PSK `COMPLETED`、DHCP `10.42.0.254/24`、BSSID `cc:**:**:**:f2:1a` |
| 4 | SSH banner 双栈 | IPv4 `192.168.50.216:22` 与 IPv6 `%10` 均为 `SSH-2.0-OpenSSH_10.0p2 Debian-7`；主机公钥 ed25519 指纹双通道一致 |
| 5 | **板上自述** `ip -4 addr` | `inet 192.168.50.216/24`，`altname wlxccc837e3f21a` |
| 6 | **板上自述** `robotctl net status` | `state Connected` / `ssid 我家的WiFi (82%)` / `ipv4 192.168.50.216` / `ipv6 fe80::cec8:37ff:fee3:f21a` / `iface wlan0 CC:C8:37:E3:F2:1A` |

补充身份一手读数：
- `/proc/device-tree/model` = `Radxa ZERO 3` —— **板型活体证据**；⚠️ 这不等于「板子背面丝印版本已确认」，丝印仍欠账。
- `/etc/os-release` = `Armbian 26.2.1 trixie`（Debian 13.3）；`uname -a` = `6.1.115-vendor-rk35xx aarch64`。
- `/etc/microduck-v112-image.txt` 板上原文：本卡由 `kissqy-r1-v112.sh` 改出、原包 sha `75da978b…`、换 `u-boot-rk2410` 引导、overlays 含 `uart2-m0 i2c3-pihat aic3104-i2c3 … i2c4-m0 npu-enable`，并明写「换引导后改 overlay 要改 `extlinux.conf`，`armbianEnv.txt` 不再生效」——**镜像身份的活体确认**。
- `robotctl system info`：`name duck-6a07`、SoC serial 已取得、`uptime 56m`。

---

## 3. 1.2 / 1.3 判据：替代验活路径完成，判据原文不动

裁定文档 `microduck-主板到货-1.2判据适用性裁定-2026-11-14.md` 的三条替代路径中，**②「SSH 读 `cmdline` + `journalctl -b`」本轮已实跑**：

```
/proc/cmdline:
root=UUID=34d3c17e-… rootwait rw console=tty1 consoleblank=0 cma=256M androidboot.fwver=ddr-v1.25-…
systemctl is-enabled serial-getty@ttyS2 → masked      (rc=1)
systemctl is-active  serial-getty@ttyS2 → inactive    (rc=3)
systemctl is-enabled ssh               → enabled
systemctl is-active  ssh               → active
nmcli -t -f NAME,TYPE,DEVICE con show --active → Microduck-Home:802-11-wireless:wlan0
```

- ⇒ 「无 `console=ttyS2` + mask getty + UART2 归 robotd」从**镜像静态推断升级为活体证据**；1.2 原判据 `N/A_BY_DESIGN`（对象错配）裁定不变，**仍 `UNVERIFIED_hardware`**，不判 PASS/FAIL。
- 🔴 **里程碑 ① 仍不能判 PASS**：执行单 1.3 的 PASS 判据是「无 `console=ttyS2` **且 robotd 能 open(`BA-3-4`)」**，而实机 `robotctl health` 报 `motor bus startup ... Feetech Sync Read timeout`，15 个舵机 ID 全缺 ⇒ 第二半判据 **FAIL**。证据强度提高 ≠ 里程碑闭合。
- `journalctl -u padd -b` / `-u updaterd -b` 均返回 `-- No entries --`（`systemctl status` 亦提示 journal 已轮转），**该路径的时间线证据不可用，不拿来凑数**。

---

## 4. 软件栈与服务：一手读数（不是推断）

### 4.1 版本
```
robotctl version:
  robotctl   0.15.1  rev 1fa8438
  robotd     0.15.1  rev unknown
  configd    0.15.1  rev 1fa8438
  warning: robotd speaks API v40 and this robotctl speaks v37, so they were not built together
```
🔴 **新发现的真实版本错配**：`/usr/local/bin/robotctl` 与 `/opt/robot/daemon/current/bin/robotctl` 的 sha256 **完全相同**（`8594234e…a4a4`），所以不是「残留旧副本」，而是**镜像内 `robotctl`(v37) 与 daemon(v40) 本身不配套**。⇒ 登记为审查报告**候选 10**，本轮只记录、不改镜像（sha pin 可复现链 + 无实机全量验证通道）。

### 4.2 健康与只读态
- `robotctl health --json` **rc=5**：这是健康状态的**非零退出码**（`degraded`），JSON 内容完整 —— 不是 CLI 报错，别误记成「命令失败」。
  - `robot.degraded=true`，`reason = motor bus startup: … Feetech Sync Read timeout; missing IDs [10,11,12,13,14,20,21,22,23,24,30,31,32,33,34]`，`request_sent=true, rx_bytes=0, bad_checksums=0`；
  - `control_loop`: target 50.0 Hz、`achieved_hz=null`、0 ticks、0 missed；`imu not ready`；`central not signed in`。
- `robotctl policy list` rc=1：`error: robotd is read-only: motor commands are disabled; uncalibrated telemetry is available via robot.busStatus` ⇒ 无整机时控制面被禁用，**App 发控制命令现在会被拒**。

### 4.3 服务状态与失败根因
| unit | 状态 | 说明 |
|---|---|---|
| `robotd` / `configd` / `btd` / `tofd` | `active` | 软件栈主体在跑 |
| `mediad` | `activating` | 尚未进 active |
| `padd` | **failed** | `startup_gate.py --timeout 60 --max-head 2.5 …` 退出码 **78**；drop-in 明写 `RestartPreventExitStatus=78` |
| `gamesir-xboxd` | **failed** | 同一 `startup_gate.py`，同样码 78、同样 21min 后退出 |
| `updaterd` | `inactive` / **disabled** | drop-in `zzzz-r17-manual.conf` ⇒ **镜像故意设为手动**，不是故障；`/run/updaterd.sock` 不存在是设计结果 |

⇒ 两个 `failed` 是**同一因果链**：启动门等头部姿态达标（`--max-head 2.5`），无整机/无舵机 ⇒ 永远等不到 ⇒ 超时 78 ⇒ systemd 放弃。与 `health degraded` 自洽，**不是镜像缺陷**。

### 4.4 端口真相（订正上一轮的谨慎表述）
`ss -lntup` 板上实读：仅 `0.0.0.0:22` / `[::]:22` / `53` / `5355` 在监听；`/run/*.sock` 只有 `configd.sock` 与 `robotd.sock`。
⇒ 上一轮「80/8080/8088/8000/8443/4210 全部 `TimeoutError`，不能反推服务没运行」现在可以收窄为**确定结论**：**板上确实没有任何 TCP 应用监听**，不是防火墙丢包。镜像侧一手也吻合：`robotd.toml` 的 `port = "/dev/ttyS2"` 是串口，`updater.toml` 的 `robot_socket = "/run/robotd.sock"` 是 Unix socket，`robotd.service` 用 `--socket /run/robotd.sock`。

---

## 5. 与安卓 App 互相适配（用户追加维度，本轮实机化）

### 5.1 协议版本：对上了
板上 `robotd speaks API v40` ↔ App `README.md` 契约 `API_VERSION=40`、`hello`(带 api_version) → `system.authenticate`(v4 起 BLE 必过) ⇒ **API 版本口径一致**。但 App 的 `Tcp` 后端在本板上**没有对应 TCP 服务**；本板的 front door 是 `btd` 的 BLE。

### 5.2 BLE 前端：广播真实对外可见（首个 App 侧独立第三方实机证据）
板上自述：
- `hciconfig -a`：`hci0 UP RUNNING`，BD `CC:C8:37:E3:7C:90`，`Name: duck-6a07`，HCI 5.4。
- `bluetoothctl show`：`Powered: yes`、`Name: microduck`、`Alias: duck-6a07`、`Discoverable: no`、`Pairable: no`、`Discovering: no`、`Roles: central + peripheral`、已注册 `Vendor specific 6f5d2a10-3b47-4c8e-9a1f-2d7e8c4b6019`，`ActiveInstances: 0x02`。

**一手资料（BlueZ D-Bus API 文档，原文实访）**：
- `org.bluez.Adapter.rst`：`Discoverable` 默认 false，语义为「make it visible or hide it」的全局设置；`Pairable` 只影响**入站配对请求**；`Discovering` 指本端扫描他人。且 `SetDiscoveryFilter` 明确写着可发现「**regardless of they are connectable or discoverable**」的设备。
- `org.bluez.LEAdvertisingManager.rst`：`ActiveInstances` = **"Number of active advertising instances"**；`RegisterAdvertisement` 即「to be sent over the LE Advertising channel」。

🔴 **订正我在本轮中途的过度推断**：我曾把 `Discoverable: no` 说成「App 连接的前置条件不成立」，这是错的 —— `Discoverable` 是 adapter 全局可见性开关，不等于 LE 广播停止；`ActiveInstances: 0x02` 才是广播实例数。**该推断撤回**。

**PC 侧独立 BLE 扫描（`bleak` 临时装到系统临时目录、未改项目环境；只读，零连接零配对，7 s）**：
```
DEVICES = 6
  CC:C8:37:E3:7C:90  name='duck-6a07'  rssi=-39  uuids=6f5d2a10-3b47-4c8e-9a1f-2d7e8c4b6019   <== MICRODUCK_CANDIDATE
  （另 5 个非 duck 设备，负对照：证明是真实无线电扫描，不是固定列表）
```
命中项的 **MAC / 名称 / Vendor UUID** 与板上三项一一对应 ⇒ **BLE 前端正在广播且 App 侧可扫描到**。（工具两次因新版 bleak 属性迁移崩溃，已改为属性兜底 + 逐设备异常隔离，最终 `rc=0`；如实记录，不掩盖。）

### 5.3 适配判决（不放宽）
| 项 | 判决 |
|---|---|
| API 版本 v40 | ✅ 实机回读对齐 |
| BLE 广播可见 | ✅ 实机第三方扫描确认 |
| 真机 GATT 连接 / bonding / CCCD / `system.authenticate` PIN 时序 | 🔴 **仍 UNVERIFIED** —— 扫描 ≠ 连接；`BA-X-5` 不判 PASS |
| `netpad :4210` | 🔴 板上无 TCP 监听、镜像侧无该服务配置 ⇒ 确证不是镜像应开放的服务（上一轮 grep `4210` 的 IQ 系数假阳性结论维持） |
| `body_server :7801` | 排除：Windows MuJoCo 台架仿真通道，不是板上服务 |
| `mediad :8080 / :8443` | `mediad` 仍 `activating`、无 TCP 监听；App `WebRtc` 属 P2 未实现 ⇒ **镜像超前、App 无场景**，维持上一轮判断 |
| 控制命令 | `robotd is read-only` ⇒ 整机落地前 App 发驾驶指令会被拒，属**预期**而非 bug |

---

## 6. 相对上一轮审查报告的事实订正 / 新增

| 项 | 上一轮口径 | 本轮实机 | 处理 |
|---|---|---|---|
| `robotctl` 与 daemon 版本 | 未发现 | v37 vs v40，两路径同 sha | **新增候选 10**，只记录不改镜像 |
| `updaterd` | 记作 stopped | `disabled` + `zzzz-r17-manual.conf` | 订正为**镜像故意手动**，非故障 |
| TCP 端口 CLOSED | 谨慎：可能是被丢弃、不能反推 | `ss` 实读无应用监听 | 升级为确定结论 |
| `Discoverable: no` | 本轮中途误判为 App 前置缺口 | BlueZ 一手 + PC 扫描命中 | **撤回推断并订正** |
| 1.2 裁定 | 基于镜像静态事实 | 活体 `cmdline` + `getty masked` | 证据强度升级，**判据原文/状态不动** |
| 板型 | 丝印未确认 | `device-tree model = Radxa ZERO 3` | 只闭合「型号」，**丝印版本仍欠账** |

---

## 7. 状态裁定（一个字没翻）

- **`live_hardware_accessed=false` 仍然正确**：该字段对应的是「**整机**（15 舵机 + IMU + 结构件 + 电池）活体接入」，本轮登录的只是 SBC 主板。`health` 明写 15 个 ID 全缺、`imu not ready`、`robotd read-only` ⇒ 整机未接入，不存在「状态与事实不符」。
- `ship_verdict=NOT_SHIPPABLE`、`COLLECTED != PASS`、`UNVERIFIED != PASS`、A2 闭合数 **0**、里程碑 ① **不 PASS**（1.3 第二半判据 FAIL）。
- 未改镜像 / 1.2 与 1.3 判据 / 采购 SSOT / contract / 任何 xlsx；未下单；未对板子做任何写操作。

---

## 8. 一手来源与降级说明

| 来源 | 用途 |
|---|---|
| 板上命令实读（`robotctl` / `systemctl` / `nmcli` / `bluetoothctl` / `hciconfig` / `ss` / `/proc` / `/etc`） | 本文全部实机事实 |
| BlueZ `doc/org.bluez.Adapter.rst`、`doc/org.bluez.LEAdvertisingManager.rst` | `Discoverable` / `Pairable` / `ActiveInstances` 语义（原文实访，非推断） |
| RFC 4291 Appendix A（上一轮已实访） | EUI-64 MAC 还原 |
| `V112.img` 只读挂载（内核 ext4 与 `debugfs` 两算法） | 镜像侧静态配置、串口 / Unix socket 口径 |
| `microduck-android-app/README.md` | App 侧 `API_VERSION=40` / BLE 契约 / WebRtc P2 状态 |
| 执行单、`microduck-主板到货-1.2判据适用性裁定-2026-11-14.md` | 判据原文与裁定 |

**降级 / 不可用，如实记录**：① `journalctl -u padd/updaterd -b` 无条目（journal 已轮转），时间线证据不可用；② 手机 `cmd bluetooth_manager` 只有开关、无扫描能力，改走 PC 侧 `bleak`；③ `bleak` 装在系统临时目录、未改项目 venv，两次 API 属性错误已修；④ Android 无互联网热点自动回落的**平台文档两次抓取失败**，该机制仍标**推断**；⑤ `grep` 板上 `microduck-setup-portal.py` 返回 `Permission denied`（radxa 无读权限，未提权），`/var/lib/microduck/` 不存在 ⇒ **不编造 provisioned 标记路径**。

---

## 9. 仍 UNVERIFIED / 下一步（按价值排序）

1. **真机 GATT 上板**：用 App 连 `duck-6a07` 验 bonding / CCCD / `onCharacteristicWrite` / `system.authenticate` PIN 时序（需整机 + Android 真机，`BA-X-5`）。
2. **整机采购下单**：软件线已饱和，唯一杠杆；碰采购须用户明确拍板，本轮不代办。
3. **`netpad :4210` 上板 / 50 Hz 状态流 / 真视频 / 策略启停 / 手感标定** —— 均需整机。
4. **受控断电负对照**（拔 OTG 5 s，前后各一次 `WlanScan`）：闭合「热点确由本板发出」的因果（现已由 mDNS + MAC + SSH + 板上 `nmcli` 多通道强支撑，但负对照仍欠）。
5. **板子背面丝印版本**：`device-tree` 只给型号，丝印仍未见。
6. **`:8088` 首启配网页**：AP 已按设计关闭，需重新触发首启状态才可能验，属破坏性操作，不擅自做。
7. **候选 10（robotctl v37 / robotd v40 错配）**：若要修需重做镜像并重新 pin，须单独立项与全量验证，本轮只登记。

---

_本文纯新增。凭据未落盘、未入库、未回显；未改镜像/判据/SSOT/xlsx，未下单，未翻任何状态。_
