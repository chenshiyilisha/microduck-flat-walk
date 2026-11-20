# kissqy 最新源码核证 — HD1910 固件加密路线的一手判决

_2026-11-18 晚。用户「把 fanhao 源码拉下来」→「拉 kissqy 的最新源码」。_
_本文是一手源码核证 + 路线判决，不改固件、不改 App 功能代码、不宣称安全交付。_
_术语遵循 `docs/active/microduck-来源术语约定-2026-11-13.md`：「官方/原厂」只指 Pollen Robotics；kissqy / fanhao375 均为机构名+平台文档。_
_整机未落地 ⇒ `ship_verdict=NOT_SHIPPABLE` 不变；`UNVERIFIED != PASS`。_

---

## 0. 一句话结论

把 `kissqy/Microduck-kissqy@main` 整包拉到本地并逐字节核证后：**本 App 对接的这条固件线（HD1910 / control.43–102 / API40–42）从 V167 到主线，btd 加密开关一字未改，默认明文**——上一轮記的「fanhao 是否默认加密 = UNVERIFIED」被一手源码**证实为「不加密」**；同时上一轮说的「X25519 应用层方案过时」是**误判**，kissqy 自己的 §5.5/§8.1 反而把应用层封密列为对口项目（Reachy Mini）生产在用的正选，并新增第三候选「封整个会话」。

---

## 1. 源码来源与版本定性（一手，可复核）

| 项 | 值 | 一手依据 |
|---|---|---|
| 仓库 | `kissqy/Microduck-kissqy`（GitHub API 核：521★，社区个人项目，与 Pollen 无隶属） | API `/repos/kissqy/Microduck-kissqy`；README 「社区个人项目」 |
| 下载 | codeload `refs/heads/main` tar.gz，**318,339,339 B**，`gzip -t` 通过 | 本地 `/tmp/kissqy-main.tar.gz`，sha 见 §5「可复核命令」 |
| 解包 | 4903 文件，目录 `/tmp/kissqy-src/Microduck-kissqy-main` | `find -type f | wc -l` |
| 固件路径 | `microduck-hd1910/firmware/`（源码兼容位）；`versions/v167/`、`versions/v260/` 为版本快照 | `versions/README.md` |
| 软件基线 | 官方 Microduck **0.15.1** + 飞特 HD1910 适配 + R17 中控 | `microduck-hd1910/README.md:7` |
| 版本谱 | **V167**=control.43/R1（历史）；**V260**=control.102/R2/配网 R10（当前发布，2026-11-13）；**V297 BATE**=control.102（测试版，仅运行包无源码） | `versions/README.md:7-9`、`microduck-hd1910/README.md:11` |
| API 版本 | 主线/v167 `API_VERSION=40`；v260 `API_VERSION=42` | `duck-ipc-proto/src/lib.rs` `grep "API_VERSION: u32"` |
| 分支名澄清 | 记忆里 `hd1910-v167-trunk-imu-i2c` 是一个**已不存在的旧分支名**（`git ls-remote --heads` 无匹配）；其源码内容即现在的 `microduck-hd1910/firmware/` | ls-remote + tree 对比 |

> **为什么 fanhao 主线仓不是这次目标**：`fanhao375/microduck-replica@master`（82MB，已下载到 `/tmp/fanhao-src/`）是采购/打印/装配/训练/Studio 仓，README `software/README.md` 明写 robotd/padd/mediad 「在复刻镜像里已经装好」，**不开源主程序 Rust 源码**。本 App 对话的固件实现源是 kissqy 这条线。

---

## 2. 一手核证：btd 加密开关全程未改

**三份 `btd/src/main.rs` 逐字节相同**（`cmp` 三向比对通过），sha256 全部为：

```
181535f650331b7a21c77f21d333a8f4af713e58d7abff05cd52bfaa1aab9e16
```

| 文件 | sha256 前 16 |
|---|---|
| `microduck-hd1910/firmware/btd/src/main.rs` | `181535f650331b7a21c7` |
| `versions/v167/microduck-hd1910/firmware/btd/src/main.rs` | `181535f650331b7a21c7` |
| `versions/v260/firmware/btd/src/main.rs` | `181535f650331b7a21c7` |
| 本地 `.upstream/DuckBuddy-main/btd/src/main.rs`（旁证） | `181535f650331b7a21c7` |

关键代码（`main.rs:118-132`，三份一致）：

```rust
if args.insecure_no_pairing {
    tracing::warn!("--insecure-no-pairing is now the default and does nothing; ...");
}
if !args.require_pairing {
    tracing::warn!(
        "serving WITHOUT pairing: the PIN and any wifi passphrase cross this link in clear, \
         readable by anyone in range. Development only — see app-path-design.md §5.5"
    );
}
```

`main.rs:33-44` 的 doc comment 明写默认不加密的理由：强制配对会让 macOS CoreBluetooth 的 version read **hang**（BlueZ 因加密不足拒绝 read，无提示/无错误/无重试），「secure but unusable」不如「usable but insecure」。**`grep -r "secure_psk|setup_code|btd::secure" firmware/` 全仓零命中** ⇒ 它没有原厂 main 的链路层加密那套。

> **对上一轮结论的订正**：11-17 加密规格文档此前写「fanhao 是否默认加密 = UNVERIFIED，不许推断」。现在由一手源码**直接坐实为「不加密」**（不是推断）；原判决 §1「目标固件明文传 Wi-Fi 密码、零加解密实现」成立。注意 **V297 BATE 无源码、只有运行包**，其 btd 是否改动 = UNVERIFIED，不推断。

---

## 3. 与原厂 main 的分叉（两条固件线，别混）

| | kissqy 线（本 App 对接） | `pollen-robotics/microduck@main`（原厂主线） |
|---|---|---|
| `main.rs` sha | `181535f6...`（189 行） | `adfd5587...`（263 行） |
| 加密开关 | `if !args.require_pairing { warn }` ⇒ **默认不加密** | `require_pairing = args.require_pairing \|\| !args.insecure_no_pairing` ⇒ **默认加密** |
| 密钥 | 无 | `secure_psk_file` / systemd `ble-psk` / `btd::secure::Config::load(&path, id)`，`id` = SoC 序列派生的 first name（QR setup-code 同源） |
| agent | just-works `NoInputNoOutput`，未要求加密 | 同 just-works，但 `encrypt_read/encrypt_write = require_pairing` |
| 一手状态 | 本地整包核证（本文） | raw 源码 + 文档核证（11-18 上半场），2026-11-08 真 Android 配对成功；iPhone/Wi-Fi 配网/生产镜像仍未测 |

两条线行为**相反**。升级/替换固件时先认 API 版本与 btd sha，不能凭「都是 Microduck」推断加密行为。

> **🔴 2026-11-18 晚订正上表「原厂默认加密」的准确含义**：一手读原厂 `secure.rs`/`agent.rs`/`duck-auth/lib.rs` 后确认——原厂默认 = **just-works 链路加密（未认证）+ `000000` PIN 门**，仍是未认证链路；真正认证机器人的 Noise（`Noise_NNpsk0` + per-robot PSK）`lib.rs` 自述 **"not wired into either endpoint … needs an independent protocol review"**，`secure.rs` 写 **"must not be enabled by default yet"**，仅 `psk_file` 存在才启用 ⇒ **是未接线的候选原型，不是已交付的默认安全**。⇒ 两条线的真实差距比上表小：kissqy=全明文，原厂=just-works 加密+未接线 Noise。三方格局与路线裁决见 `microduck-原厂Noise加密一手核证-三方格局与路线裁决-2026-11-18.md`。

---

## 4. kissqy §5.5 / §8.1 的新证据（对口线自己的判决，非二手转述）

路径：`microduck-hd1910/firmware/docs/design/app-path-design.md`（本地一手）。

**§5.5（measured）**：
- `encrypt_read` 在 macOS 触发 hang 是**实测**，非猜测；但机器记录「bond 是否存在仍未建立（需 `bluetoothctl info <mac>` 看 `Paired:`）」——「bonded but not encrypting」与「never bonded」需要相反修复，选错会「看起来解决但问题还在」。
- **2026-09-14 iPhone A/B（新）**：关 `--require-pairing` 时 iPhone 直连发现服务无误；**开时 iOS 弹出配对提示**。结论：**手机 CoreBluetooth 会发起 SMP，macOS 笔记本才 hang**；hang 不是协议栈通病，「无法建 bond」也不成立。但加密 read 是否随后完成、`bluetoothctl` 的 bond 状态**未测**（`version read` 日志是 `debug!` 而 unit 设 `RUST_LOG=info`，缺日志不构成证据）。→ 复现入口：在同一 drop-in 加 `Environment=RUST_LOG=debug`，连接后「点 read 而非点 connect」。
- **参考实现不用链路层加密**：`reachy_mini` 的 BLE provisioning 特性无加密 flag，注册 `NoInputNoOutput` 但**不要求 bond**；理由原文「BLE pairing is Just-Works … so we encrypt at the application layer and mix the device PIN into the key derivation」——`x25519-hkdf-sha256-aesgcm`，ephemeral ECDH + PIN 作 HKDF salt + SSID 作 AAD，**两大手机平台生产在用、过 App Review**；能防被动嗅探，挡不住 setup 时的主动 MITM，PAKE 列为后续。**🔴 一手补证（2026-11-18 晚，直读 reachy_mini 源码）**：其 `BLE_WIFI_PROVISIONING.md:101-125` 自承主动 MITM 可用 5 字符 PIN 离线爆破 PSK，并明确把早先「active MITM 拿不到 key」宣称判为 **wrong 且删除**。⇒「生产在用」不等于安全；本项目 §4 用随机 salt 更强，但链路未认证的根本面仍在。逐项比对见 `microduck-Reachy加密一手核证-与本项目方案比对-2026-11-18.md`。
  - caveat（对口线独有）：他们每台机器人 PIN 是序列号后五位、印在机上、广告名匿名（都叫 `ReachyMini`），所以 PIN 作 salt 有意义；**kissqy 广告名由序列号派生（§8.2），这招被一个「为更好理由做的选择」关闭**，且 factory PIN `000000` 人人可读 ⇒ PIN-as-salt 在本线几乎白给。

**§8.1（blocker）从两候选变三候选**：

| 候选 | 机制 | 一手评价 |
|---|---|---|
| ① Fix the link layer | `--require-pairing` + bond | 覆盖面最大（整条 routed surface 保密）；但 bond 只能 just-works ⇒ `encrypt_authenticated_write` 永远够不着；且决定成败的 bond 事实**仍未测** |
| ② Seal at the application layer | Reachy Mini 的 x25519-hkdf-sha256-aesgcm | 生产验证过，无 bond 也能防嗅探；但只保护「记得封的字段」，本 transport 还带 device code / journal / PIN 本身（§3.1） |
| ③ Seal the session rather than the call | `hello` 后一次建 crypto，覆盖其后所有帧 | 比 ② 多工，但**唯一能覆盖 `system.authenticate`**，后来加的方法不会成为「没人封的那个」 |

§8.1 明确：三者都挡不住**配对时的主动 MITM**；且「关掉加密」的 gate 是**任何机器人交付给用户前必须闭合**的。

---

## 5. 对 App 的裁决影响与边界

1. **原判决 §1 继续有效并被坐实**：目标固件当前明文传 Wi-Fi 密码、零加解密实现；App 单侧不能交付「安全配网」。`INTEROP_UNVERIFIED` 恒真。
2. **上一轮「§4 X25519 过时」的误判撤回**：11-17 §4 的应用层封密方案与对口项目生产路线同源；new info 不是「它错了」，而是「它还多了一个会话级选项（③），且对口线把链路层降级为 bond-待测定项」。§4 正文不改，路线取舍待用户拍板。
3. **与 App 现有架构的契合**：③「封整个会话」天然落在 `RobotSession` / `RobotRepository` 的会话边界（已有 hello 降级、authenticate、错误码语义），比逐方法改 crypto 更省；但这是**架构契合度判断，不是已实现**，本轮未写任何功能代码。
4. **仍需拍板/未验证**：① 的 bond 是否存在（`bluetoothctl info` 实机）；iPhone 加密 read 是否完成；V297 运行包的 btd 是否改动；任何真机 interop。全部 `UNVERIFIED`，不因「源码读了」升级为 PASS。
5. **未做**：未改固件/App 源码、未改 `closure_contract.json`/采购表/xlsx、未上板、未下任何凭据。`ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不变。

---

## 6. 可复核命令

```bash
# 下载 + 校验
curl -sSL "https://codeload.github.com/kissqy/Microduck-kissqy/tar.gz/refs/heads/main" -o /tmp/kissqy-main.tar.gz
gzip -t /tmp/kissqy-main.tar.gz && sha256sum /tmp/kissqy-main.tar.gz
tar -xzf /tmp/kissqy-main.tar.gz -C /tmp/kissqy-src

# btd 三份一致性 + 默认不加密
sha256sum /tmp/kissqy-src/Microduck-kissqy-main/{microduck-hd1910/firmware/btd/src/main.rs,\
versions/v167/microduck-hd1910/firmware/btd/src/main.rs,versions/v260/firmware/btd/src/main.rs}
grep -nE "require_pairing|insecure_no_pairing" <任一份> | head
grep -rlnE "secure_psk|setup_code|btd::secure" /tmp/kissqy-src/Microduck-kissqy-main/microduck-hd1910/firmware/   # 应为空

# 版本/API
grep "API_VERSION: u32" <各版本 duck-ipc-proto/src/lib.rs>
sed -n '590,680p' microduck-hd1910/firmware/docs/design/app-path-design.md   # §5.5
sed -n '787,815p' microduck-hd1910/firmware/docs/design/app-path-design.md   # §8.1 三候选
```
