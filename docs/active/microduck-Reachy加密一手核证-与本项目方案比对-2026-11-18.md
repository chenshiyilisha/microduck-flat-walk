# Reachy Mini 加密实现一手核证 — 与本项目 §4 方案的逐项比对

_2026-11-18 晚。用户「继续，按最优的来，多查资料」。_
_缘起：kissqy `app-path-design.md` §5.5 转述 Reachy Mini 用 `x25519-hkdf-sha256-aesgcm` 生产在用；按准则一手核验该转述，避免拿二手当判据。_
_只做一手核证 + 比对裁决，不改固件/App 源码，不宣称安全交付。_
_术语：Reachy Mini 是 Pollen Robotics 的另一个产品（官方 `pollen-robotics/reachy_mini`，1673★，2026-11-18 仍在更新）；与 MicroDuck 同源组织但**不同产品、不同 wire**。_
_整机未落地 ⇒ `ship_verdict=NOT_SHIPPABLE` 不变；`UNVERIFIED != PASS`。_

---

## 0. 一句话结论

一手读通 Reachy 的加密实现后：**它和本项目 §4 方案是"同算法族、不同 wire"，不能互通，也不该照抄**。你的 §4 在两处（随机 salt、会话级覆盖）**比 Reachy 生产方案更强**；Reachy 值得抄的只有 `kid` 轮换和它**主动撤回错误安全宣称**的诚实纪律。更重要的是：Reachy 方案**自己承认挡不住主动 MITM**（5 字符 PIN 可离线爆破），且明确把曾写下的"MITM 拿不到 key"判为 **wrong 并删除**——所以绝不能因为"生产在用、过 App Review"就把它（或你同构的 §4）当成"安全已解决"。

---

## 1. 一手来源（全部本地可复核）

| 文件 | 来源 | 大小 | 关键内容 |
|---|---|---|---|
| `src/reachy_mini/daemon/app/routers/wifi_config.py` | GitHub contents API（base64 解码） | 19,754 B | **真正做加密的地方**：`X25519PrivateKey`/`X25519PublicKey`/`HKDF`/`AESGCM` import（L12-17）；scheme 注释 L245-282；`_current_provisioning_pubkey()` / `_open_sealed_psk()` / `GET /prov_key` / `POST /connect_sealed` |
| `src/reachy_mini/daemon/app/services/bluetooth/bluetooth_service.py` | contents API | 73,601 B | **只 relay，不做 crypto**：L1463-1468 明写 "system Python … does NO crypto … all the X25519/AES-GCM work [is] in the daemon venv"；L1579-1708 `WIFI_KEYEX` 转发 pubkey、`WIFI_CONNECT_ENC` 转发 blob |
| `src/reachy_mini/daemon/app/services/bluetooth/BLE_WIFI_PROVISIONING.md` | raw | 9,458 B | wire flow L68-84；**Security properties L85-130**，含主动 MITM 漏洞、错误宣称撤回、PAKE follow-up |

下载到 `/tmp/reachy-{bs-full,bs-full,wifi-full}.py` 与 `/tmp/reachy-BLE_WIFI_PROVISIONING.md`；目录树 `/tmp/t-reachy.json`（`truncated=false`，1015 文件）。

> **订正二手转述**：kissqy §5.5 说 "Reachy 把 PIN 混进 key derivation"。一手确认属实，但漏了三个限定：salt 是 **5 字符序列号后缀的 raw UTF-8**（不是任意 PIN）、info 是固定串 `"reachy-mini-wifi-psk-v1"`、**AAD=ssid**。转述不足以指导互操作。

---

## 2. Reachy scheme 的一手精确定义

```
1. WIFI_KEYEX → {kid, pk};  pk = base64(X25519 pub, 32B raw)
                             robot 临时对 ~600s TTL，kid = 6B urlsafe b64（L282-310）
2. Phone 生成自己的临时 X25519 对 → ecdh_shared
   key = HKDF-SHA256(ecdh_shared, salt=PIN_utf8, info=b"reachy-mini-wifi-psk-v1", L=32)
3. ct = AES-GCM(key, nonce=12B, plaintext=psk, aad=ssid_utf8)
4. WIFI_CONNECT_ENC + JSON {ssid, kid, epk:<b64 phone pub>, nonce:<b64 12B>, ct:<b64 ct||16B tag>}
5. daemon 本地算同一个 PIN，重复 ECDH+HKDF 解密，nmcli 连接
```

- **AAD=ssid** 的作用：把封密的 PSK 绑到目标网络，抓到的 blob 不能重放到别的 SSID。
- **kid 不匹配**（轮换中）→ 400 → 手机重新 `KEYEX`。
- **公钥故意公开**：注释明写裸公钥没有 PIN 就没用。
- 动机：WiFi 密码不得明文过 BLE（App Store 审核硬要求）。

---

## 3. 与本项目 §4 方案的逐项比对（裁决核心）

| 项 | 本项目 §4 | Reachy 一手 | 裁决 |
|---|---|---|---|
| 算法族 | X25519 → HKDF-SHA256 → AES-256-GCM | 同 | 同构， crypto 原语可复用 |
| ECDH | 临时对 × 对端 pub | 同 | 同构 |
| **HKDF salt** | **32B 随机**（固件握手返回） | **PIN_utf8（5 字符，低熵）** | ✅ **本项目更强**：不把密钥强度系于低熵 PIN；Reachy 的 salt 正是它离线爆破洞的根源 |
| HKDF info | `"microduck/wifi-provision/v1"` | `"reachy-mini-wifi-psk-v1"` | 🔴 不同 ⇒ **两者互不可解**，这是刻意域分隔，不是 bug |
| HKDF L | 32 | 32 | 同 |
| **AES-GCM AAD** | `"net.connect"`（绑方法） | `ssid_utf8`（绑网络） | 🔴 目标不同：本项目防跨方法重放，Reachy 防跨 SSID 重放。**可考虑双 AAD**（方法+SSID）取两者之长，但需两端同步改，属设计增强非互操作必需 |
| nonce | 12B 随机/每消息 | 12B 随机 | 同 |
| 封密明文 | 整个 UTF-8 params JSON `{ssid,psk}` | 只封 PSK（SSID 在 blob 里明文） | 🔴 本项目覆盖更全 |
| 线上格式 | `nonce\|\|ct\|\|tag` 二进制 | JSON `{ssid,kid,epk,nonce,ct}` | 🔴 wire 不兼容；若将来真 interoperate 需明确选一个 |
| 密钥轮换 | 每次配网新临时对 | robot 临时对 600s TTL + kid + 重取 | 🟡 **值得抄 kid 机制**：轮换中途失败时给手机明确的"重取"信号，否则 400 来源不清 |
| 会话覆盖 | §4.3 推荐会话封密，覆盖 `system.authenticate` 及后续所有方法 | 单调用，只覆盖 PSK | ✅ **本项目 §4.3 更彻底**，正对应 kissqy §8.1 第三候选 |
| 主动 MITM | 继承局限，未接 PAKE | **自承漏洞**，PAKE=follow-up | 🔴 同一局限，两边都不能称"安全交付" |

**裁决**：
1. **不照抄 Reachy**。它的 salt=PIN 是已知弱点；本项目用随机 salt 更安全。抄实现细节反而降级。
2. **可借鉴两点**：`kid` 轮换 + 明确的重取语义；以及文档纪律（见 §4）。
3. **wire 不互通是特性不是缺陷**：两个不同产品，域分隔串不同反 prevents cross-protocol replay。真要互通需显式协商，不在当前范围。

---

## 4. 🔴 最重要的一条：Reachy 自己撤回了错误安全宣称

原文 `BLE_WIFI_PROVISIONING.md:101-125`（一手，逐字要点）：

- 标题即 **"Known limitation — active MITM can recover the PSK (offline PIN brute-force)"**。
- 攻击链 4 步：Just-Works 无设备身份 ⇒ MITM 用自己的 X25519 pub 应答 `WIFI_KEYEX` ⇒ 手机把 PSK 用 `HKDF(secret, salt=PIN)` 封给攻击者 ⇒ 只剩 5 字符 PIN 未知，**离线**穷举 ~10⁵ 次瞬间完成，且**不再碰机器人**，在线 wrong-PIN 限流完全无效。
- 结论原文：**"The earlier 'active MITM can't derive the key without the PIN' claim was wrong and has been removed."**
- Fix：**PAKE（CPace / SPAKE2）** 把 PIN 喂进密钥协商本身，让不知道 PIN 的一方拿到无用密钥、每次猜测都变成机器人可见的在线尝试。其余 scheme 不变，仍用 AES-GCM 封 PSK、SSID 作 AAD。

**对本项目的意义**：
- 本项目 §4 用随机 salt 而非 PIN，能挡住上述"离线爆破 PIN"的具体路径（攻击者没有 salt 对应的 PIN 依赖）——但**只要链路未认证、手机不验机器人身份，主动 MITM 替换 pubkey 的根本面仍在**，只是收益不同。此判断是基于密码学结构的推论（**这是推的，未找到针对本项目 §4 的现成攻击分析**）；真机/正式安全评审前，不得对外称"安全配网"。
- Reachy 把错误宣称**公开撤回**的做法，独立印证你的铁律 `UNVERIFIED != PASS`、禁止假绿。建议把它作为文档纪律的外部旁证写进项目约定。

---

## 5. 边界与未做

- 本轮只读一手源码 + 参数比对，**未改任何固件/App 功能代码、未改契约/xlsx/采购表、未上板、未下任何凭据**。
- Reachy 的 PAKE follow-up 是否已落地、MicroDuck 原厂 main 的 setup-code PSK 是否真能防主动 MITM、本项目 §4 在真机上的互通与安全——全部 **UNVERIFIED**。
- `ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不变。

---

## 6. 可复核命令

```bash
# 一手源码（contents API 规避 raw 超时）
curl -sS "https://api.github.com/repos/pollen-robotics/reachy_mini/contents/src/reachy_mini/daemon/app/routers/wifi_config.py" \
  | python -c "import sys,json,base64;print(base64.b64decode(json.load(sys.stdin)['content']).decode())" | sed -n '245,360p'
curl -sS "https://raw.githubusercontent.com/pollen-robotics/reachy_mini/main/src/reachy_mini/daemon/app/services/bluetooth/BLE_WIFI_PROVISIONING.md" \
  | sed -n '68,130p'
```
