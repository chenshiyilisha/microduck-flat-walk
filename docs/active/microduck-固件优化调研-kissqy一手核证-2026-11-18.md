# MicroDuck 固件优化调研 —— 基于 kissqy 最新源码一手核证

_日期：2026-11-18　来源：`kissqy/Microduck-kissqy@main` 整包（318MB / 4903 文件，已解包在_
_`/tmp/kissqy-src/Microduck-kissqy-main`，固件在 `microduck-hd1910/firmware/`）。_
_性质：只读调研 + 一个可复核的加密可行性探针；**未改任何固件源码、未上板、未下凭据**。_
_边界：`UNVERIFIED != PASS`，`ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不变。_

## 0. 结论先行

**固件本身不需要我们"从零优化"——它是成熟工程（942 tests、M1–M4 已扎实落地、idle CPU 已系统优化）。**
真正和我们项目相关的只有两类：

1. **已验证可做的**：固件端加密原语（X25519/HKDF/AES-GCM）用现成 crate 零障碍实现 —— 本轮已真编译真跑证明（见 §2）。这把"固件对接是深水区"翻案为"集成工作量"。
2. **设计封死、不能当优化点的**：通过 BLE 改配对 PIN —— `btd/route.rs` 有意拒绝且有测试守护（§3.2）。任何"App 引导改 PIN"的方案都是没读懂一手就乱提。

其余 roadmap 项（support bundle、maploc、NPU detector、recovery 上板验证、出厂 PIN 流程）
是**上游自己的产品化待办**，不是我们当前能做的优化——它们要么缺整机、要么缺产线、要么缺硬件。

## 1. 固件现状（一手事实）

- 成熟 Rust workspace：`edition 2024` / `rust-version 1.99` / resolver 3，20+ crate。
- `docs/project/roadmap.md`：M1（闭环）M2（dev channel）M3（robotd）**done**，M4（硬件 bring-up）closing，
  M5（mediad/WebRTC/SDK）in progress；942 tests passing（Mac/Linux，Linux 略多）。
- idle CPU 已优化过（`docs/project/idle-cpu.md`）：mediad 每帧 memcpy 55MB/s → 按需取；
  test pattern 720p30 29.4% core → 256x144@5 0.7%；tofd 100→45 reads/s；padd 50–100→10 msg/s；
  pet-detect 静音时不跑。50Hz 总线写**有意不做条件化**（省 940µs 不值得引入状态）。

## 2. 可直接做的优化：固件端加密原语 —— 已验证零障碍

新落盘参考实现 `microduck-android-app/tools/firmware-interop-probe/`，
用 `x25519-dalek 2.0.1` + `hkdf 0.12.4` + `aes-gcm 0.10.3` 按 §4 wire 实现：

- **6/6 断言全过**：X25519 shared = RFC7748 权威 K、双方对称、HKDF key = Python、Rust 解开 Python 密文 = plaintext、篡改密文/AAD 不符必失败。
- MSRV 全兼容（crate edition 2018/2021 ≤ 固件 1.99）；固件 workspace 已用 `sha2 0.11`/`rustls`，加密 crate 非禁区。
- 改坏必红实测：篡改 `EXPECT_KEY` 末字节 → rc=101 panic。
- 三语言互算闭环：Python 加密 → Kotlin（`ProvisioningCrypto`）解 → Rust 解，全部一致。

⇒ "固件端加 crypto 是深水区"**翻案**为"现成 crate + cargo add 级别的集成工作量"。
但注意：这是**可行性证明**，不是已集成固件；`INTEROP_UNVERIFIED` 恒真。

## 3. 不能当优化点的（一手驳回）

### 3.1 配对 PIN 出厂默认 000000 —— 缺产线，不是缺代码
`configd/src/store.rs:36` `DEFAULT_PIN="000000"`；有 `system.pairingPin`/`system.setPairingPin`
（`configd/src/main.rs:517-525`）与 `is_default` 标记，认证时每次都警告"factory PIN is public"
（`btd/src/session.rs:275-279`）。roadmap M6 明写这是 **a factory process, not a patch**
（生成 + 打印 + 记录印了什么）。我们改不了产线，这条对我们是死路（与 11-17 加密判决一致）。

### 3.2 通过 BLE 改 PIN —— 有意封死，有测试守护
`btd/src/route.rs:210` `SystemPairingPin | SystemSetPairingPin(_) => false`，
配套测试 `the_pairing_pin_is_not_reachable_over_ble`。设计理由（`route.rs` 注释 + `app-path-design.md` §5.1/§5.2）：
"一个未配对对端能读到或覆盖的 passkey 会让配对变成戏法"；btd 只通过 unix socket 读 PIN 应答 BlueZ。
⇒ App 侧"引导用户改 PIN"在架构上不可行，不要报为优化。

### 3.3 is_mutating / robot.enable authority 漏洞 —— 本地已记录
本地文档已有 `is_mutating` 与 `robot.enable`（grep 1/9 命中），且 roadmap M6 标 "authority arbitration finished,
including edge #52"——上游已修，不重复报。

## 4. 上游产品化待办（供参考，非我们当前可做）

| 项 | 状态（一手） | 为什么我们现在不做 |
|---|---|---|
| Support bundle（一键故障包） | roadmap M7 明确 missing | 需真实故障场景+整机 |
| maploc (#127) / NPU duck detector / chorale election (#151) | roadmap in flight | 上游功能开发，与我们主线无关 |
| Recovery net 上板验证 | "never exercised on a board"，M6 最便宜项 | 需刻意刷坏版本的整机 |
| 远程访问 bridge（rendezvous） | M5 account 已建、bridge 未建 | 依赖 HF OAuth 账号体系 |
| OAuth token scope 过宽 | roadmap: 收窄到 `openid profile read-repos`（公开 OAuth app + 一个常量） | 上游云侧，非我们固件 |
| Consent before stream | M5 明确 "not blocked on anything" | 属 WebRTC 线，见另一准备文档 |

## 5. 验证与边界

- 本轮新建：`tools/firmware-interop-probe/`（Cargo.toml/Cargo.lock/src/main.rs/run_probe.sh/README.md）。
- `run_probe.sh` 真跑 6/6、rc=0；改坏必红实测；三语言互算闭环。
- 未改固件源码、未改契约/xlsx、未上板、未下凭据。
- `ship_verdict=NOT_SHIPPABLE`、`live_hardware_accessed=false` 不变。

## 6. 复核命令

```bash
bash microduck-android-app/tools/firmware-interop-probe/run_probe.sh   # Rust 固件侧对拍
PY="microduck-software/.venv-mjlab/Scripts/python.exe"
"$PY" microduck-android-app/tools/check_provisioning_crypto.py --check # App 常量一致性
# 一手固件源码（本地已解包）
grep -n "DEFAULT_PIN" /tmp/kissqy-src/Microduck-kissqy-main/microduck-hd1910/firmware/configd/src/store.rs
sed -n '205,212p' /tmp/kissqy-src/Microduck-kissqy-main/microduck-hd1910/firmware/btd/src/route.rs
```
