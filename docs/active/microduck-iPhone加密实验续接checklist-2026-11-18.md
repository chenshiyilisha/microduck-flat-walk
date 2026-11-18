# MicroDuck §5.5 iPhone 加密实验 · 续接 checklist（2026-11-18）

_状态：🟡 **待硬件 · UNVERIFIED**。本文只固化「真板 + iPhone 到位当天照着走」的步骤与判据，_
_不记录任何未做的实验结论；`ship_verdict=NOT_SHIPPABLE` 不变。_

_一手依据（唯一官方仓库 `pollen-robotics/microduck` 的 fanhao/BoBo 快照副本）：_
- `out/bobo-src/MicroDuck-BoBoRedesign-main/03-DuckCode/microduck-hd1910/firmware/docs/design/app-path-design.md` §5.5:590–640、§8.1:787–805。
- `.../firmware/btd/systemd/btd.service` 第 53 行 `SupplementaryGroups=robot bluetooth`、第 79 行 `Environment=RUST_LOG=info`。

---

## 0. 前提核验（缺一即 `PRECONDITION_FAIL`，一步都不往下走）

| 前提 | 核验方式 | 2026-11-18 现场 |
|---|---|---|
| 真板在网 | `ping microduck.local` / SSH 22 OPEN + banner / 路由器 DHCP MAC | ❌ 解析失败、网关 `172.26.32.1` 100% 丢包、无串口 |
| **iPhone** 在旁 | Apple Mobile Device 服务 / 蓝牙列表见 iOS 设备 | ❌ 仅 vivo V2338A（Android）+ iQOO，**无 iOS 设备** |
| 板上可改 drop-in | SSH 登板、`/etc/systemd/system/btd.service.d/` 可写 | ❌ 无板 |
| 手机↔板同一链路 | 手机连板的 BLE 广播（`duck-*`，名字含 serial），非家用 WiFi / 蜂窝回落 | ❌ 无板 |

🔴 **安卓机不能替代 iPhone**：本次实验的关键事实是「**CoreBluetooth on a phone begins SMP where CoreBluetooth on a laptop does not**」（§5.5:632–634）——要在 **iPhone + CoreBluetooth** 上复现，Android 栈不是同一观测面，拿它做只能算旁证，不能关闭 §5.5。

🔴 **「扫不到」先换观测面**（SOP 坑 28/29）：AP 消失 ≠ 板坏；镜像已配网后按设计不再开 AP。判活用 mDNS / ICMP / SSH / DHCP / MAC，不盯 beacon；手机热点回落会让 HTTP 探测假阴性，探测前先断言当前 AP。

---

## 1. 基线：`bluetoothctl info <mac>` 判 bond（§5.5:602–605 / §8.1:802–805）

在**板上**执行（`<mac>` = 手机 BLE 地址），记录原文，不看字面推：

```bash
bluetoothctl info <mac> | grep -E 'Paired:|Bonded:|Trusted:|Connected:'
```

这是决定走哪条修复路线的**唯一事实**（逐字）：

> The fact that would decide the first row is still not known — whether a bond exists at all
> (`bluetoothctl info <mac>` on the robot). *Bonded but not encrypting* and *never bonded* need
> opposite repairs, and shipping the wrong one leaves the problem in place while looking solved.

- **`Paired: no`（从未 bond）** ⇒ 加密根本建立不起来，去改 `--require-pairing` flag 是**症状不是原因**（§5.5:604）；此时链路层路线基本被否，转向 §8.1 的应用层/会话封密。
- **bond 存在但未加密** ⇒ 才值得验「把 requirement 挪到 write 是否生效」。
- 判据独立于被测值：同时记 `bluetoothctl show` 的 `Pairable:`，但**别把 `Discoverable: no` 推断成「App 连不上」**——那是全局可见性开关，已撤回的过度推断（SOP 坑 30）。

---

## 2. 改 drop-in：让 `RUST_LOG=debug` 生效（§5.5:639–640 逐字）

原厂续接指引逐字：

> Anyone picking this up starts by adding `Environment=RUST_LOG=debug` to the same drop-in,
> connecting, and tapping the read rather than the connect.

unit 是 `btd.service`（`/etc/systemd/system/btd.service`，非 `robotd`）。**不改主 unit 文件**（会被升级覆盖），加 drop-in：

```bash
sudo mkdir -p /etc/systemd/system/btd.service.d
sudo tee /etc/systemd/system/btd.service.d/10-crypto-probe.conf >/dev/null <<'EOF'
[Service]
Environment=RUST_LOG=debug
EOF
sudo systemctl daemon-reload
sudo systemctl restart btd
```

**为什么必须改**：`version read` 那行日志是 `debug!`，而主 unit 第 79 行设 `RUST_LOG=info`（§5.5:637–639）——info 级别下**journal 里看不到它，但那不构成「read 没发生」的证据**。这是本实验最大的假绿陷阱。

**为什么是「same drop-in」**：§5.5:627 那次 A/B 已经用过一个 drop-in 让 `SupplementaryGroups=robot bluetooth`（btd.service 第 53 行）在重启后是真值；新环境若组没生效会出现 D-Bus 权限错误（btd.service 第 42–47 行注释），先确认 btd 正常启动再谈加密。

**回滚**（实验后必做，恢复默认 info，避免长期 debug 噪声）：

```bash
sudo rm /etc/systemd/system/btd.service.d/10-crypto-probe.conf
sudo systemctl daemon-reload && sudo systemctl restart btd
```

---

## 3. 手机侧操作：**tap READ，不是 tap connect**（§5.5:640）

1. iPhone 连接板的 BLE 广播（名字含 serial，§8.2 每台不同）。
2. `--require-pairing` 保持**出厂默认 off**先跑一轮（§5.5:630 iPhone 在此配置下「connected and discovered the service without complaint」）；随后**同机重启 btd、开 on 再跑一轮**（A/B）。
3. **发现服务后点「读取 characteristic」（READ）**，不是只点连接——§5.5:640 明确 `tapping the read rather than the connect`。只 connect 不 read，实验等于没做。

---

## 4. 三个观测点与判据（缺一即 `INCONCLUSIVE_*`）

开两个观测面，**任一缺失就标 INCONCLUSIVE，不许写 PASS**：

### 4.1 板上 journal（debug 已生效）

```bash
journalctl -u btd -f
# 或实验后：journalctl -u btd --since "10 min ago" | grep -iE 'version|pair|smp|encrypt|error|agent'
```

| 观测 | 一手预期 | 判据 |
|---|---|---|
| `version read` 日志 | `debug!` 级，debug 下应出现 | **出现** = read 真发生了；缺席且 RUST_LOG=info = 无证据（不算失败也不算成功） |
| SMP 配对提示 | iPhone on 时弹（§5.5:630–634） | on 弹 / off 不弹 = CoreBluetooth _phone_ 会发起 SMP 的复现 |
| 加密 read 结果 | §5.5:592–595：macOS **hang**（BlueZ 拒 insufficient encryption，无提示无错误无重试）；iPhone 上**未测**（本次要补的就是它） | 返回明文 / hang / 报错，三种都要逐字记录，**不要预设** |

### 4.2 `bluetoothctl info <mac>`（实验后再读一次）

与步骤 1 的基线对比：bond 状态有没有变？`Paired:` 从 no→yes 说明 SMP 真建立了；不变说明 iPhone 弹窗只是 UI、没落 bond。

### 4.3 iPhone 屏幕

配对提示是否出现、read 是否返回、有无错误弹窗——截图留证。

---

## 5. 结论矩阵（§8.1 三候选 ← 证据，不先选路线）

| 观测到的证据 | 指向 |
|---|---|
| `Paired: no` + flag off 就能连（§5.5 现状） | 无 bond，链路层 flag 是症状 ⇒ **应用层/会话封密**（参考 reachy_mini `x25519-hkdf-sha256-aesgcm`，§5.5:642–660） |
| bond 存在 + 加密 read 在 iPhone 上**成功返回** | 链路层路线**可能**可行，仍需验证是否默认开启后所有客户端都不 hang |
| bond 存在 + 加密 read **hang**（同 macOS） | 链路层死路（just-works bond 达不到 `encrypt_authenticated_write`，§8.1:798）⇒ 应用层封密 |
| 任一观测缺失 | `INCONCLUSIVE_*`，重跑，不选路线 |

**注意**（§8.1:789–792）：关闭 blocker = 让机密配置**可用**且**成为默认**；只做前者、默认仍 off，等于每块板依旧不安全。

---

## 6. 负对照 / 防假绿（每条都来自本项目或原厂真实踩坑）

1. **RUST_LOG=info 下无 `version read` ≠ read 没发生**（§5.5:637–639）——必须 debug 级才作证据。
2. **只 connect 不 tap read = 实验无效**（§5.5:640）。
3. **`Discoverable: no` / `Pairable: no` 不能推断「App 连不上」**——BlueZ Adapter1 全局开关，ActiveInstances 才是 LE 广播实例数（SOP 坑 30，已撤回的推断）。
4. **AP 消失 ≠ 板坏**；手机热点回落会让探测假阴性，探测前断言当前 AP（SOP 坑 28/29）。
5. **bond 状态必须两份观测互证**：`bluetoothctl info` + journal 的 SMP 事件；iPhone 弹窗不是 bond 落地的证据。
6. **具体值以字节级通道为准**（psk/端口/pin/版本）：用 `od -An -tu1` / `base64` / `ord()`，不信明文渲染（SOP 硬规则 19）。
7. **commit 报 nothing added 先 `rev-parse HEAD` + `show --stat`**（项目铁律 10）——固件分支改动提交后核状态再 push。

---

## 7. 当前可复用资产（真板一到直接用，不必重推）

- `ProvisioningCrypto.kt`（core，纯 JVM）：X25519 / HKDF-SHA256 / AES-256-GCM 参考实现，带 RFC7748 / RFC5869 权威向量 KAT + 低阶点负对照，15 项 core 自检已真跑通过。与 reachy_mini 路线（§5.5:658 `x25519-hkdf-sha256-aesgcm`，PIN 作 salt、SSID 作 AAD）方向一致。
- `docs/active/microduck-配网加密-一手判决与固件对接规格-2026-11-17.md`：固件端需实现什么、nonce/AAD 结构、握手顺序的对接规格。
- `bluetoothctl info <mac>` 判 Paired 的分支逻辑见本文 §1——它是选路线的第一步，别跳过。

_写完时间：2026-11-18。实验未做，全部判据待真板 + iPhone 到位后逐项填；未填项一律 `UNVERIFIED`。_
