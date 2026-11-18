# MicroDuck 安卓 App — A2 配网 / A2' 加密：一手判决与固件对接规格

_2026-11-17。用户「A2 配网 + A2' 加密」+「都做」「按照最优的来」。_
_本文只做**技术判决 + 跨端对接契约**，不改固件源码、不宣称安全交付。_
_术语遵循 `docs/active/microduck-来源术语约定-2026-11-13.md`：「原厂/官方」只指 Pollen Robotics。_
_整机未落地 ⇒ `ship_verdict=NOT_SHIPPABLE` 不变；`UNVERIFIED != PASS`。_

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
