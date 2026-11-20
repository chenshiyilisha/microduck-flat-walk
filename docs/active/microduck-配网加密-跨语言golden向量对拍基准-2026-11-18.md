# MicroDuck 配网加密 —— 跨语言 golden vector 对拍基准落地

_日期：2026-11-18　性质：把三方加密格局裁决（路线 B）推进为**可真跑、可真验证的工程资产**。_
_边界：`UNVERIFIED != PASS`；本轮只证明「两条独立代码路径算法一致」，不等于真机互通；_
_`INTEROP_UNVERIFIED` 恒真，`ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不变。_

## 0. 为什么做这个（跳出"第 8 份报告"）

前四轮已把加密三方格局闭合（原厂 Noise 未接线 / kissqy 全明文 / Reachy 自承 MITM 洞），
决议"路线 B：§4 应用层封密先落地，只差固件对接"。但 `ProvisioningCrypto.kt` 原有的 KAT
只测了**单个算法的标准向量**（RFC7748 X25519、RFC5869 HKDF 各自分开），且 `seal()` 用随机
nonce ⇒ **没有一条端到端确定性向量**可供固件端做互操作对拍。固件端即使照文档实现，也没有
权威 hex 可比对。这才是路线 B 落地前真正缺的一块砖——本轮补上。

## 1. 做了什么

新增/改动（**只动加密预埋资产，未接真实配网路径、未改功能代码、未碰契约/xlsx/采购**）：

| 文件 | 改动 |
|---|---|
| `core/.../ProvisioningCrypto.kt` | 新增 `object WireGolden`：10 个常量（client/robot 私钥公钥、salt、nonce、shared、key、plaintext、blob），标注"算法一致≠真机互通、INTEROP_UNVERIFIED 恒真" |
| `core/.../CoreSelfTest.kt` | `testProvisioningCrypto()` 加 KAT-5 共 6 条：3 条跨语言正对照 + 3 条负对照（篡改密文、错 salt、interop 边界断言）|
| `tools/check_provisioning_crypto.py` | 新工具：`--json` 用 Python `cryptography` 独立生成向量；`--check` 逐字节比对 App 常量（漂移即红）；`--selftest` 6 项注入式负对照 |

### 1.1 追加（同日 21:xx）：补上"App 加密发送方向"闭环 KAT-6

**发现的方向性空白**：初版 golden vector 只锁了「Python 加密 → Kotlin `open()` 解」单向。
但 App 真实运行时是**加密发送方**，固件要解的正是 `seal()` 的输出。若 `seal` 的 wire
（nonce 拼接头 / tag 长度 / AAD 编码 / 拼接顺序）与独立实现有语义差，单向 KAT 全绿也照不出来。

**改动**（纯新增，不改生产行为）：
| 文件 | 改动 |
|---|---|
| `core/.../ProvisioningCrypto.kt` | 新增 `sealWithNonce(key, plaintext, nonce, aad)`（可注入 nonce 的确定性封密，专供对拍）；`seal()` 改为复用它、行为不变（仍随机 nonce）|
| `core/.../CoreSelfTest.kt` | 加 KAT-6 共 5 条：Kotlin 封出 blob **逐字节 = Python BLOB**（发送方向）+ 自环解回 + 3 负对照（nonce/plaintext/AAD 变 → blob 必变）|

⇒ 三语言 golden vector 由单向闭合为**双向**：Python 加密 = Kotlin 加密（发送），Kotlin 解 Python（接收），
Rust 探针解同一 BLOB（固件侧）。任一方 wire 语义差必红。

### 1.2 一手新事实：官方 `duck-auth` 进度（纠正前几轮"纯纸面原型"的记录粒度）

同日再核官方 `pollen-robotics/microduck@main` 一手（contents API 解码 `app-path-design.md`
77KB + `docs/robot/authenticated-app-mvp.md` 11KB + `duck-auth/src/lib.rs` 9KB）：

- `duck-auth` **不是纸面候选**：是完整 host-tested 的 `Noise_NNpsk0_25519_ChaChaPoly_SHA256`
  握手——prologue=`microduck-ble-auth-v1:{robot_id}` 绑身份、双向 confirmation、
  replay/tamper 防护均有测试（`both_directions...`/`wrong_secret_and_identity_fail`/`replay_and_tampering_fail`）。
  `btd --secure-psk-file` 是 opt-in 开发模式。
- 🔴 **纠正上一轮记录**：配套 app 分支 `codex/authenticated-ble-mvp` 我上轮写"存在"是**错的**——
  MVP 文档确实链接到 `github.com/pollen-robotics/microduck-app/tree/codex/authenticated-ble-mvp`，
  但该仓库网页 404、GitHub API 搜索/读取均 Not Found（2026-11-18 21:3x 一手核）。即官方 app 侧
  Noise 实现当前**不可得**（私有/已删/改名），不是可抄的现成参考。
- **但默认仍明文**：`--require-pairing` 默认 off，`system.authenticate` 仍 6 位 PIN；
  MVP 文档明写 "opt-in development path, not the production provisioning"，
  产线唯一密钥/QR/受保护存储/独立安全评审（roadmap 第 3-5 步）均未完成。
- **官方自己承认缺 test vector**：`app-path-design.md` line 669 写 "require ... interoperable
  app/robot test vectors before shipping"；而 `duck-auth` 只有 3+2 个 roundtrip 单元测试、
  golden vector 关键词零命中。⇒ 本项目做的 golden vector 对拍**不是重复造轮子，恰填官方明列缺口**，
  只是我方 wire 是 §4 应用层方案、与官方 Noise wire 不同（不可互解，见 §4 边界）。
- 🔴 文档自相矛盾照旧：顶部"requires encrypted link by default"注记 vs 正文 §5.5/§8.1
  反复"默认明文"——信源码/正文，不信顶部注记（与前几轮教训一致）。

## 2. Golden vector（确定性，可复核）

wire 严格按 `docs/active/microduck-配网加密-一手判决与固件对接规格-2026-11-17.md` §4：

```
shared = X25519(client_priv, robot_pub)
key    = HKDF-SHA256(ikm = shared || client_pub || robot_pub,
                     salt = 32B, info = ASCII "microduck/wifi-provision/v1", L=32)
blob   = nonce(12) || AES-256-GCM(key, plaintext, aad = ASCII "net.connect")
```

- 私钥/公钥取 **RFC7748 §6.1 权威向量**（非自造）；`shared` 已独立核对等于 RFC 权威 K
  `4a5d9d5ba4ce2de1…161742`。
- salt=32B 递增、nonce=12B 递增；plaintext=`{"ssid":"DS1002","psk":"TestPass123"}`（**测试凭据，非真实密码**）。
- 完整 10 个常量的 hex 见 `ProvisioningCrypto.WireGolden` 或 `check_provisioning_crypto.py --json`。

**固件端对拍方法**（将来）：用 robot_priv + client_pub 复现 shared/key，用 key + NONCE + AAD
解开 BLOB 得 plaintext；任何一步不符即 wire 实现有偏差。

## 3. 验证（两独立实现互算 + 负对照，全部真跑）

| 检查 | 结果 |
|---|---|
| `selftest.sh`（真编译+真运行 JVM） | **640 passed, 0 failed**（初版 635，KAT-6 加 5 条）|
| 跨语言：Python 加密 → Kotlin 解开 = plaintext | PASS |
| 跨语言：Kotlin 加密（`sealWithNonce`）逐字节 = Python BLOB（发送方向）| PASS（KAT-6）|
| 负对照：仅让"发送方向"断言恒假 → 639 passed / **1 failed**（正是该条）| PASS（改坏必红精确实测）|
| 负对照：篡改 WireGolden.BLOB → selftest rc=1（KAT-5 解密处抛 AEADBadTag，提前终止）| PASS |
| 恢复后干净重跑 | 640/640，字节级 diff clean |
| `check_provisioning_crypto.py --check` | PASS（10 常量逐字节一致；篡改 KEY 末字节必红实测）|
| `check_provisioning_crypto.py --selftest` | 6/6（含 X25519 clamp 坑负对照）|
| `check_all_app_gates.py`（统一门禁） | **ALL_PASS**（含 core 640）|
| `assembleDebug`（Android 主链真编译） | BUILD SUCCESSFUL（APK 21:32 新产物）|
| `check_closure.py --check`（契约门禁） | rc=0，9 markers==9 ids，ship NOT_SHIPPABLE |

### 本轮抓到的一个真实知识点（负对照自证价值）

新工具初版负对照 2 用"改 client_priv 首字节 bit0"想让 shared 变，结果 **FAIL**——
一手查证是 RFC7748 §5 的 clamp 会清 byte0 低 3 位，改动被吞。改用 `byte0 ^= 1<<3` 才生效。
这个坑已写进判据注释。若负对照只有绿色，这个语义差就会潜伏。

## 4. 边界与未做

- 本轮**没有**写任何真实配网功能代码：`NetProvisioning.connectParams` 仍走明文，
  `ProvisioningCrypto` 仍不被任何配网 UI 调用。
- 固件端零 crypto 依赖的现状未变；golden vector 只提供对拍基准，**互操作仍需真固件实现 + 真机对拍**。
- 🔴 **wire 不可互解**：本 golden vector 是 §4 应用层方案（X25519 临时对 + 随机 salt +
  AES-GCM，AAD=`net.connect`）；官方 `duck-auth` 走 Noise_NNpsk0 + per-robot PSK +
  prologue 绑 robot_id。**两者算法族相近但 wire 完全不同，密文互不可解**。未来若决定对齐官方
  Noise（路线 A），需另做一套 Noise golden vector，本套不能直接复用。
- 🔴 身份认证局限：§4 用随机 salt、无 per-robot PSK，与 Reachy 同类——挡被动嗅探，不挡主动 MITM
  （这是基于密码学结构的推论，标"这是推的"，无针对性攻击分析）。官方 Noise+PSK/PAKE 才是认证方向，
  但产线/独立评审未完成。正式安全评审前一律不得称"安全配网"。
- 🔴 **路线 A（对齐官方 Noise）短期不可落地 —— 一手裁决**：即便官方 duck-auth host-tested，
  App 侧复现它有三个独立障碍，任何一个都不是"cargo add/JCA 现成调用"能过的：
  ① **参考不可得**：官方配套 app 分支 404（见 §1.2），没有可抄的 wire 实现；
  ② **Android Noise 库坑**（2026-11-18 WebSearch 一手核，FlyingCarpet 加密设计文档 + 各库 README）：
     `noise-java`(rweather) 用 2018 前废弃 PSK 方案、与 snow **不兼容**（cacophony 向量核过）；
     `java-noise`(jchambers) 需 **Java 17 + JCA X25519，Android 到 API 34 才有**——本项目
     `minSdk=26`，直接排除；`sander/noise-kotlin` MIT 但**未独立审计**、需自己实现 Cryptography 后端；
     `trancee/noise-protocol` _support_ 38+ pattern 含 psk0、带跨平台 test-vectors，但同为第三方未审计。
  ③ **方向性决定**：引入未审计第三方 Noise 库或手搓 Noise 状态机 = 新依赖 + 安全审计缺口，
     属"是否扩大信任面"的产品决定，不由工程侧单方面拍板。
  ⇒ 维持现状：§4 自主方案的对拍基准已双向闭环；路线 A 若启动，须先由用户拍板"引库 vs 手搓 vs 等官方 app 分支"，
     不是纯工程增量。**不要因为'官方有 Noise'就直接抄**——这正是用户纪律"先找现成方案，但找不等于可用"。
- 主动 MITM / PAKE / 原厂 Noise 接线 —— 延续前一裁决，全部 UNVERIFIED。
- 本轮未上板、未下任何凭据、未碰用户手改的 xlsx/采购表/既有文档。

## 5. 复核命令

```bash
PY="microduck-software/.venv-mjlab/Scripts/python.exe"
cd microduck-android-app
"$PY" tools/check_provisioning_crypto.py --json      # 独立生成的 golden vector
"$PY" tools/check_provisioning_crypto.py --check      # App 常量一致性
"$PY" tools/check_provisioning_crypto.py --selftest   # 注入式负对照
"$PY" tools/check_all_app_gates.py                    # 统一门禁
bash tools/selftest.sh                                # core JVM 真跑
```
