# 原厂 secure/Noise 一手核证 — 三方加密格局与 App 路线裁决

_2026-11-18 晚。用户「继续，按最优的来，多查资料」。_
_补齐上一轮三方对比缺的一块：原厂 `pollen-robotics/microduck@main` 的"链路层加密 + setup-code PSK"完整实现。_
_只做一手核证 + 裁决，不改固件/App 源码，不宣称安全交付。_
_整机未落地 ⇒ `ship_verdict=NOT_SHIPPABLE` 不变；`UNVERIFIED != PASS`。_

---

## 0. 一句话结论（纠正前两轮的理解）

前两轮我把原厂 main 说成"已完成链路层加密 + setup-code PSK 默认加密"——**一手读源码后发现这个表述过头了**。真相是三层：

1. **链路层**：`require_pairing` 默认 true（BLE 要求加密），但 agent 是 **just-works 未认证**（`agent.rs` 明写直接接受确认、不比对数字、不提供 MITM 保护）⇒ 只防被动嗅探。
2. **应用层强认证**：`duck_auth` 用 `Noise_NNpsk0_25519_ChaChaPoly_SHA256` + per-robot 64-hex PSK，challenge/confirm/ready 握手 + seal/open 全帧加密——但 `lib.rs:1-5` 明写 **"not wired into either endpoint … Candidate … needs a provisioned secret, protected phone storage, and an independent protocol review"**，且 `main.rs` 只在 `psk_file` 存在（显式 flag 或 systemd `ImportCredential=ble-psk`）时才 `Some(config)` ⇒ **默认路径不走 Noise**，是可选、未接线的候选原型。
3. **PIN gate**：普通路径仍是 `000000` 出厂 PIN + `system.authenticate`。

⇒ 原厂"默认加密"的准确含义 = **just-works 链路加密（防嗅探）+ PIN 门**；真正能认证机器人的 Noise 会话**尚未接线、未做协议评审**。不能把它当成"安全问题已解决"。

---

## 1. 一手来源（本地可复核）

| 文件 | 大小 | 关键内容 |
|---|---|---|
| `btd/src/main.rs` | 10,999 B | `require_pairing = args.require_pairing \|\| !args.insecure_no_pairing`（默认 true）；`psk_file` → `Config::load` → `Option<Config>`；`imported_psk()` 读 `CREDENTIALS_DIRECTORY/ble-psk` |
| `btd/src/agent.rs` | 2,956 B | `CAPABILITY = "NoInputNoOutput"`；`request_confirmation` 直接接受，"just-works consent, not numeric comparison or MITM protection" |
| `btd/src/secure.rs` | 9,470 B | Noise 会话状态机 Start→Confirm→Ready；`ProvisionedKey` PSK；**"must not be enabled by default yet"**；seal/open 覆盖每条 RPC（含 replies）；Idle 60s |
| `duck-auth/src/lib.rs` | 9,226 B | `PATTERN = "Noise_NNpsk0_25519_ChaChaPoly_SHA256"`；`snow 0.10`；"Candidate BLE authentication … **not wired into either endpoint** … needs … independent protocol review"；`robot_id` 绑定进握手，wrong key/id 握手即失败 |
| `docs/design/app-path-design.md` 顶部 | 77,583 B | "Security update (production candidate)… requires encrypted paired link by default… agent fix still needs end-to-end Android and iPhone validation… `000000` PIN must be replaced" |

全部经 GitHub contents API（base64 解码）落到 `/tmp/pd-*.rs` / `/tmp/pd-appdesign-full.md`。

---

## 2. 原厂安全架构的准确分层

```
默认路径（无 psk_file）：
  BLE just-works bond（链路加密，未认证） + GATT read require_encrypt
  → NDJSON JSON-RPC → PIN gate (000000, system.authenticate) → 明文 RPC 过链路
  ⇒ 防被动嗅探；主动 MITM 可在配对时介入

可选路径（psk_file 存在，未接线为默认）：
  Noise_NNpsk0_25519_ChaChaPoly_SHA256 + per-robot 64hex PSK
  → Frame Start/Challenge/Confirm/Ready 握手 → 所有 Data 帧 seal/open
  → authenticated=true 替代 PIN gate
  ⇒ 认证机器人身份 + 全帧加密，但需预置 PSK、手机安全存储、独立协议评审（都未完成）
```

**Noise pattern 解读**（`NNpsk0`）：双方无静态身份密钥（NN），靠预共享密钥在握手第 0 条消息注入（psk0）。所以安全性完全系于 **PSK 不泄露**；`robot_id`（SoC 序列派生的 first name，与 setup-code QR 同源）绑定进握手，防错机器人。`snow` 是成熟 Noise 库，但 pattern 选型本身需协议评审（源码自己说）。

---

## 3. 三方加密格局（本轮闭合）

| | 原厂 main | kissqy（本 App 对接） | Reachy Mini |
|---|---|---|---|
| BLE 链路 | just-works 加密，默认开（`require_pairing=true`） | **明文**，默认关（上轮一手坐实） | 不要求 bond，明文 |
| PIN gate | `000000` + authenticate | `000000` + authenticate | 序列号后 5 位 + 会话 TTL |
| 应用层加密 | **Noise_NNpsk0（候选原型，未接线默认）** | 无（全仓零 crypto） | `x25519-hkdf-sha256-aesgcm`（已上线，自承 MITM 洞） |
| 主动 MITM | Noise 若接上可解（需 PSK 不泄露）；默认路径未解 | 未解 | 自承未解，PAKE follow-up |
| 官方定性 | "Candidate / prototype / needs protocol review" | "development only / §8.1 blocker" | "App Store 要求，passive-only" |
| 验证状态 | 2026-11-08 真 Android 链路配对（agent 修复待双端验证） | 源码核证，无整机 | 两平台生产（但不是 MicroDuck） |

**关键洞察**：三条线**没有一条**是"已交付的安全配网"。原厂强认证方案还没接线、kissqy 明文、Reachy 只防被动嗅探还自承漏洞。这从三个独立来源共同印证：配网加密是整个生态的 open blocker，不是本项目的疏漏。

---

## 4. 对本项目 App 的路线裁决

三条可选路线（供用户拍板，本轮不替选、不改代码）：

| 路线 | 做法 | 评价 |
|---|---|---|
| A. 等原厂 Noise 落地 | 等 `duck_auth` 接线 + PSK provisioning + 协议评审完成，App 对接 Noise 握手 | 安全上限最高（认证+全帧加密），但**依赖尚未完成的上游工作**，时间不可控；且需手机侧 PSK 安全存储方案 |
| B. 本项目 §4 应用层封密 | 固件端按 §4 wire（随机 salt + 会话封密）实现，App 预埋的 `ProvisioningCrypto` 转接 | **自主可控、比 Reachy 更强**（随机 salt、会话覆盖 authenticate）；但同样挡不住主动 MITM（除非后续上 PAKE），且需要改 kissqy 固件 |
| C. 维持明文 | 内部/台架用，不对外 | 零成本，但 `INTEROP_UNVERIFIED` 恒真、不得称安全配网 |

**我的最优建议**：若目标是"尽快有可自证的安全配网"，选 **B**（§4 已被一手证明方向正确且比 Reachy 强，App 侧原语已预埋，只差固件对接）；若有上游协同资源，对齐 **A** 的 Noise pattern 做长期演进（可把 §4 的会话密钥派生成 PAKE/Noise 的输入）。无论哪条，**真机 interop + 独立安全评审**都是不可省的闸门，`ship_verdict` 不变。

**可借鉴（不抄代码）**：原厂"PSK + robot_id 绑定握手、错误 PSK/id 握手即失败"的测试纪律（`duck_auth` 单测 `wrong_secret_and_robot_identity_fail_before_rpc`）；把它作为你 §4 KAT 的补充负对照思路。

---

## 5. 边界与未做

- 本轮只读一手源码 + 比对，**未改任何固件/App 功能代码、未改契约/xlsx/采购表、未上板、未下任何凭据**。
- Noise 是否会正式接线、setup-code PSK provisioning 何时可用、agent 修复的 Android/iPhone 端到端结果、本项目真机 interop —— 全部 **UNVERIFIED**。
- "Noise 默认路径未启用"是源码事实（psk_file 分支 + lib.rs 自述）；"which route 最优"是工程判断，不是已验证结论。
- `ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不变。

---

## 6. 可复核命令

```bash
# 一手源码（contents API）
for f in main.rs agent.rs secure.rs; do
  curl -sS "https://api.github.com/repos/pollen-robotics/microduck/contents/btd/src/$f?ref=main" \
   | python -c "import sys,json,base64;print(base64.b64decode(json.load(sys.stdin)['content']).decode())" > /tmp/pd-$f
done
curl -sS "https://api.github.com/repos/pollen-robotics/microduck/contents/duck-auth/src/lib.rs?ref=main" \
 | python -c "import sys,json,base64;print(base64.b64decode(json.load(sys.stdin)['content']).decode())" | sed -n '1,20p'
# 关键判据
grep -nE "Noise_NNpsk0|not wired|independent protocol review|must not be enabled by default" /tmp/pd-*.rs /tmp/pd-duckauth-lib.rs
```
