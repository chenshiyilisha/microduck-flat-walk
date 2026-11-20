# MicroDuck 安卓 App — A2 配网 / A2' 加密：一手判决与固件对接规格

_2026-11-17。用户「A2 配网 + A2' 加密」+「都做」「按照最优的来」。_
_本文只做**技术判决 + 跨端对接契约**，不改固件源码、不宣称安全交付。_
_术语遵循 `docs/active/microduck-来源术语约定-2026-11-13.md`：「原厂/官方」只指 Pollen Robotics。_
_整机未落地 ⇒ `ship_verdict=NOT_SHIPPABLE` 不变；`UNVERIFIED != PASS`。_

> **2026-11-18 一手更新（跨版本翻案证据，不改下方原判决）**：原厂 `pollen-robotics/microduck@main`
> 的 `btd` **已经把默认加密做了进去**，技术路线从「应用层封密」转向「**链路层加密 + setup-code PSK**」：
> - 源码一手：`btd/src/main.rs:123` = `let require_pairing = args.require_pairing || !args.insecure_no_pairing;`
>   ⇒ **默认 require_pairing=true**（`--insecure-no-pairing` 变成显式的 bench-only 退路）；
>   `main.rs:44-46,128-152` 引入 `secure_psk_file` / systemd 导入的 `ble-psk` credential /
>   `btd::secure::Config::load(&path, id)`，`id` = `robotd_params::serial::this_first_name()`（SoC 序列派生的
>   "first name"，与 QR 上的 setup-code 同源）；`btd/src/bluez.rs` 有 `NoInputNoOutput` headless agent +
>   `encrypt_read/encrypt_write = require_pairing`。
> - 文档一手：`docs/design/app-path-design.md` 顶部 "Security update (production candidate)" +
>   §5.5 正文已改写：2026-11-08 真 Android 手机对 CI 候选镜像配对成功，加密 GATT read / pre-PIN 拒绝 /
>   post-PIN `system.info` 都成功。
> - **但关键边界仍全部挂着**：仍是 **just-works 未认证**（机器人无法比对数字，配对时的主动攻击者仍在
>   威胁模型内）；**iPhone、Wi-Fi provisioning、最终生产镜像全未测**；文档明写启动时的 agent 修复
>   "still needs end-to-end Android and iPhone validation"，且 `000000` factory PIN 必须被替换。
> - **🔴 2026-11-18 晚一手订正（读 `secure.rs`/`agent.rs`/`duck-auth/lib.rs`，上面「已把默认加密做进去」表述过头）**：
>   原厂默认加密的准确含义 = **just-works 链路加密（防被动嗅探、未认证）+ `000000` PIN 门**。`agent.rs` 明写
>   配对确认「does **not** authenticate the link」；真正能认证机器人的 `duck_auth` Noise
>   （`Noise_NNpsk0_25519_ChaChaPoly_SHA256` + per-robot 64hex PSK）`lib.rs:1-5` 自述 **"not wired into either
>   endpoint … Candidate … needs an independent protocol review"**，`secure.rs` 明写 **"must not be enabled by
>   default yet"**，且 `main.rs` 仅当 `psk_file` 存在（显式 flag / systemd `ImportCredential=ble-psk`）才启用 ⇒
>   **Noise 会话是未接线的候选原型，不是已交付的默认安全**。三方格局（原厂 Noise 原型 / kissqy 明文 /
>   Reachy 应用层已上线但自承 MITM）与路线裁决见
>   `docs/active/microduck-原厂Noise加密一手核证-三方格局与路线裁决-2026-11-18.md`。
> - **对本 App 的判定**：本 App 实际对接 fanhao fork（API40），本地同源副本
>   （`.upstream/DuckBuddy-main` / `ft1910` `btd/src/main.rs:123`）= `if !args.require_pairing { warn }`
>   ⇒ **默认仍不加密**，与下面 §1 原判决一致，原判决对当前对接目标**继续有效**。
> - **🔴 2026-11-18 晚一手翻案（纠正上面两处，源码已拉到本地）**：已把 `kissqy/Microduck-kissqy@main`
>   整包拉到本地（`/tmp/kissqy-src/Microduck-kissqy-main`，318MB gzip 校验通过、4903 文件），这才是本 App
>   对接的固件线（记忆里 `hd1910-v167-trunk-imu-i2c` 实为 `microduck-hd1910/firmware/`，版本 0.15.1 /
>   HD1910 control.43 / `API_VERSION=40` / R17 V167）。一手核证改写上面两条：
>   - **fanhao/kissqy 是否默认加密 = 已证实「不加密」，不再是 UNVERIFIED**：主线、
>     `versions/v167/`、`versions/v260/` 三份 `btd/src/main.rs` **sha256 完全相同**
>     （`181535f6...`），都是 `if !args.require_pairing { warn("...PIN and any wifi passphrase cross
>     this link in clear...") }`，且全仓 `grep secure_psk|setup_code|btd::secure` **零命中** ⇒ 它没有吸收
>     上面原厂 main 的链路层加密改动。原判决 §1「目标固件明文传密码、零加解密实现」**被一手源码直接坐实**。
>   - **§4 的 X25519 应用层方案不是「过时」，而是被对口项目验证过的正选之一（纠正上轮误判）**：
>     kissqy 自己的 `firmware/docs/design/app-path-design.md` §5.5 记录 **Reachy Mini 用
>     `x25519-hkdf-sha256-aesgcm`（ephemeral ECDH + PIN 作 HKDF salt + SSID 作 AAD）在两大手机平台生产在用、
>     过 App Review**，专防被动嗅探；§8.1 现列**三候选**（① 修链路层 ② 应用层封密 ③ **封整个会话**：
>     `hello` 后一次建 crypto 覆盖其后所有帧、唯一能覆盖 `system.authenticate`）。§5.5 还给出
>     2026-09-14 iPhone A/B 新证据：**手机上 CoreBluetooth 会发起 SMP、弹出配对提示（笔记本 macOS 才 hang）**，
>     故「默认不加密」的 mac hang 理由在手机侧不成立，但加密 read 是否完成仍未测。
>   - **裁决**：路线取舍仍需用户拍板 + 真机对拍（被动嗅探威胁下 ②/③ 可用、主动 MITM 三者都挡不住）；
>     §4 正文一字不改。完整一手核证见
>     `docs/active/microduck-kissqy源码核证-加密路线一手判决-2026-11-18.md`。
>   - **🔴 2026-11-18 晚再补（一手读 Reachy 源码，纠正上面措辞的可能误读）**：上面「生产在用、过 App Review」
>     只是**部署事实，不是安全证据**。一手读 `pollen-robotics/reachy_mini` 的
>     `wifi_config.py`/`BLE_WIFI_PROVISIONING.md` 发现：该方案**自承挡不住主动 MITM**（5 字符 PIN 可被离线爆破），
>     并明确把早先「active MITM can't derive the key without the PIN」宣称判为 **wrong 且已删除**，fix=PAKE(CPace/SPAKE2)
>     列为 follow-up。⇒ 不能因「Reachy 生产在用」就把它（或本 §4 同构方案）当成「安全已解决」；本 §4 用随机 salt 而非
>     PIN 更强，但链路未认证的根本面仍在，正式安全评审前不得对外称安全配网。逐项比对见
>     `docs/active/microduck-Reachy加密一手核证-与本项目方案比对-2026-11-18.md`。

---

## 0. 一句话结论

**App 侧能做的已全部做完并可真跑（配网数据层 + 写路径 + 加密原语 KAT）；但「安全配网」这一端到端能力无法只靠 App 交付**——因为目标固件当前**明文**传 Wi-Fi 密码、且**零**应用层加解密实现。要真正闭合，必须**固件端同步实现**本文 §4 的 wire，并在真机上与 App 对拍（`INTEROP_UNVERIFIED` 目前恒真）。把它包装成「已加密可交付」即是假绿。

---

## 1. 一手核验链（2026-11-17 逐字核，非推断）

### 1.1 明文传输的铁证

本 App 对接目标是 fanhao fork（API40）。本地一手副本
`out/bobo-src/MicroDuck-BoBoRedesign-main/03-DuckCode/microduck-hd1910/firmware/btd/src/route.rs:139-155`
逐字写明：

> Carries a wifi passphrase … The characteristic sets `encrypt_write`, not `encrypt_authenticated_write` …
> from `--require-pairing`, which is **off by default**, so on an ordinary board there is no encryption on
> this link at all … the bond is just-works … the passphrase **crosses in clear**. That is a known, accepted,
> **pre-shipping cost** — `btd` warns about it at every start — and **§8.1 is the blocker that has to close
> before a robot goes to anyone**.

`btd/src/route.rs:155` 仍 `NetConnect(_) => true`（放行）——理由紧随其后：无网机器人没有别的入口可配网。

### 1.2 原厂给出的三条修复路径（都需要固件端动手）

原厂 `docs/design/app-path-design.md` §8.1（同一副本）原文：

| 候选 | 做法 | 反制 |
|---|---|---|
| Fix the link layer | 让整条 routed surface 保密、App 不写 crypto | bond 只能是 just-works ⇒ `encrypt_authenticated_write` 永远不可达（§5.5） |
| Seal at the application layer | Reachy Mini 的答案，双端上架生产；无 bond 也能防被动嗅探 | 只保护「记得封密」的字段，而本链路还传设备码、日志、PIN 本身（§3.1） |
| Seal the session rather than the call | `hello` 后建立一次，覆盖其后每帧；唯一覆盖 `system.authenticate` 的方案 | 工作量最大 |

§8.1 结尾明确：决定第一行能否修的事实**仍未知**——板子到底有没有 bond（`bluetoothctl info <mac>` on the robot）。「bonded but not encrypting」与「never bonded」需要**相反**的修法，修错等于没修却看着像修好了。

### 1.3 固件端零实现、App 平台 API 缺失

- 全 firmware 树 grep `x25519|hkdf|aesgcm|aes_gcm|chacha20poly1305|shared_secret`：命中的全是普通文件 `open()`/`reopen()`，**无一处**应用层加解密；所有 `Cargo.toml` **无** crypto 依赖。
- 本 App `minSdk=26`。Android 平台 X25519 到 API 34 才「有限支持」、HPKE 到 API 37（Conscrypt 官方发布说明，2026-11-17 查）。⇒ 纯 JVM 参考实现不能假定在低版本真机可用。

**推论**：App 单侧加密既无法与当前固件互操作，也没有稳定平台 API 兜底 ⇒ 绝不接入真实配网路径。

---

## 2. App 侧本轮已落地（可真跑，非文档空谈）

| 能力 | 文件 | 证据 |
|---|---|---|
| `net.status` / `net.scan` 只读解析 | `core/.../NetSnapshot.kt` | CoreSelfTest KAT：7 字段全读、未连接缺字段保持 null（不填 0/假 IP）、security 原样不猜、缺 state 视为未读到 |
| `net.connect` / `net.forget` 写路径 | `core/.../NetProvisioning.kt` | 请求仅 `{ssid, psk?}`（deny_unknown_fields）、开放网络不写 psk、`ConnectResult` tag 枚举按 ConnectFailure 分类、缺 outcome 不伪造成功 |
| 明文风险显性化 | `NetProvisioning.PLAINTEXT_TRANSPORT_WARNING` | 逐字点名 §8.1 / 明文 / 仅内部自测，UI 必须原样显示 |
| 加密原语能力预埋 | `core/.../ProvisioningCrypto.kt` | RFC7748 §6.1 X25519 KAT、RFC5869 §A.1 HKDF KAT、AES-256-GCM roundtrip + 篡改/AAD 负对照、低阶点拒绝、临时密钥前向保密 |
| 自检 | `core/src/test/.../CoreSelfTest.kt` | `RESULT: 613 passed, 0 failed`（原 571 + 配网 27 + 加密 15）；负对照真红 |

🔴 **边界**：`ProvisioningCrypto` 无任何 UI/Repository 调用；`NetProvisioning.connectParams` 仍走明文（原厂现状）。`INTEROP_UNVERIFIED=true` 是常量，禁止改成 PASS。

---

## 3. 配网写路径的行为契约（App 端）

1. **Mock 会话不写真网络**：`kind == "MOCK"` 时 `net.connect`/`net.forget` 不发起，UI 显示「演示模式不写真实配置」。
2. **警示不可省略**：任何 `net.connect` 入口必须先显示 `PLAINTEXT_TRANSPORT_WARNING`，用户确认后才发请求。
3. **密码不落盘/不进日志**：`psk` 只出现在出站 JSON 一次；不写 SharedPreferences、不进 logcat、不进任何 data class 的 `toString()`。固件侧同样以手写 `Debug` 脱敏（lib.rs:2965）。
4. **缺数据不造假**：`net.status` 未连接时 ssid/signal/ip4 全缺是**正常**（lib.rs:4017 明写），UI 显示「未连接 / 未读到」，不显示 0 或假 IP。
5. **失败按 ConnectFailure 分类**：bad_key→「密码错误」、not_found→「靠近路由器」、timeout→「可重试」、unsupported→「网络类型不支持」，不得笼统报「失败」。

---

## 4. 固件端对接规格（要真正安全配网，固件必须实现）

> 这一节是**跨仓交付物**，App 仓无法代做。固件端实现后，用 §5 的 KAT 与 App 对拍。

### 4.1 前置：先解决 bond 未知（§8.1 第一行）

在真板上执行 `bluetoothctl info <mac>`：
- **Bonded but not encrypting** → 修链路层：启用 `encrypt_write` + `require-pairing`，并处理 just-works 无 MITM 的限制（§5.5）。
- **Never bonded** → 走应用层封密或会话封密（下行），链路层保持现状。
- 结论不同 ⇒ 修法相反。未确认前不要二选一。

### 4.2 Wire（应用层封密方案，与 App 预埋实现一致）

- **算法**：X25519 ECDH → HKDF-SHA256 → AES-256-GCM。
- **握手**：App 每次配网生成临时密钥对（前向保密），在 `hello` 之后（或新的加密握手方法）把 `client_pub(32B)` 送给固件；固件返 `robot_pub(32B)` + `salt(32B)`。
- **共享密钥**：`K = X25519(app_priv, robot_pub) = X25519(robot_priv, client_pub)`；全零（低阶点）必须拒绝。
- **会话密钥**：`key = HKDF-SHA256(ikm = K || client_pub || robot_pub, salt, info = ASCII "microduck/wifi-provision/v1", L=32)`。
- **封密**：`nonce = 12B 随机/每条消息`，`AAD = ASCII "net.connect"`，`ciphertext = AES-256-GCM(key, nonce, AAD, UTF-8(params JSON))`；线上格式 `nonce(12) || ciphertext || tag(16)`。
- **参数 JSON 不变**：仍是 `{"ssid":...,"psk":...}`，只是整体作为明文被封密；固件解开后再按原 `deny_unknown_fields` 反序列化。
- **nonce 唯一性**：同一会话密钥下 nonce 绝不可重用（GCM 灾难性失效）；建议计数器 + 随机数，或每条消息新 salt。

### 4.3 推荐：会话封密优于单调用封密

原厂 §8.1 指出应用层封密「只保护记得封密的字段」，而该 BLE 链路还传设备码、日志、PIN（`system.authenticate`）。**推荐会话封密**：`hello` 后建立一次密钥，其后所有帧（含 `system.authenticate`）统一封密，新增方法不会漏封。App 预埋的 `deriveSessionKey` 已按可复用会话密钥设计。

### 4.4 交付闸门

- 固件端实现 + App 端接入（`ProvisioningCrypto` 从预埋转接 `NetProvisioning`）+ 真机对拍 + 确认 bond 状态，四者齐全后 `INTEROP_UNVERIFIED` 才可由真人按证据改判。
- 在此之前：`net.connect` 明文可用（内部/台架自测），**不得**对外宣称安全配网；整机 `ship_verdict=NOT_SHIPPABLE`。

---

## 5. 跨端对拍向量（固件端实现后必须复现）

| 层 | 输入 | 期望输出 |
|---|---|---|
| X25519 | a=`77076d0a...92c2a`, B_pub=`de9edb7d...82b4f`（RFC7748 §6.1） | K=`4a5d9d5b...161742` |
| HKDF-SHA256 | IKM=22×`0b`, salt=`000102030405060708090a0b0c`, info=`f0f1f2f3f4f5f6f7f8f9`, L=42（RFC5869 §A.1） | OKM=`3cb25f25...7185865` |
| GCM | key=`000102...1e1f`, nonce=`000102030405060708090a0b0c`, AAD=`net.connect` | 双端互解 + 篡改 tag 失败 |

（完整 hex 见 `ProvisioningCrypto.Rfc7748` / `Rfc5869Tc1`；App 自检已逐条真跑通过。）

---

## 6. 本轮边界与未决

- **未改**任何固件源码；**未宣称**安全配网可交付。
- **未验证**：真板 bond 状态、真机 App↔固件加密互通、低版本 Android 的 X25519 可用性。
- **待用户/整机**：确认 bond → 选固件修复路径 → 固件实现 → 真机对拍 → 才谈 `ship_verdict` 变化。
