# 固件侧 §4 wire 参考实现（跨语言对拍探针）

**目的**：证明"固件端加 X25519/HKDF/AES-GCM"在技术上零障碍，并提供一个可复核的
固件侧参考实现，与 App 的 `ProvisioningCrypto`、Python `check_provisioning_crypto.py`
构成**三语言互算闭环**（Python 加密 → Kotlin 解 → Rust 解）。

## 一键运行

```bash
bash run_probe.sh     # 期望 SELFTEST: 6/6 passed, rc=0
```

## 一手核实的结论

- crate 版本（Cargo.lock 锁定）：`x25519-dalek 2.0.1` / `hkdf 0.12.4` / `aes-gcm 0.10.3`，
  MSRV 均 ≤ 固件 workspace 的 `rust-version=1.99`（crate 源码 edition 2018/2021，固件 edition2024）。
- **工具链一致性已固化（2026-11-19）**：`Cargo.toml` 用 `edition=2024` + `rust-version=1.99`，
  与固件 `rust-toolchain.toml`（channel=1.99.0、target=aarch64-unknown-linux-gnu）对齐；
  `run_probe.sh` 编译前正则提取这两个完整键值校验，漂移回 2021/低版本即 rc=3。
  实测：edition 2024 下 GNU toolchain 6/6 passed（rc=0），改回 2021 → `CONTRACT_FAIL` rc=3（负对照）。
  ⇒ "固件侧可行性"的编译条件不再隐含是 edition 2021。
- 固件 workspace（`microduck-hd1910/firmware/Cargo.toml`）已用 `sha2 0.11`、`rustls`，
  加密 crate 非禁区，只差 X25519/HKDF/AES-GCM 三个原语。
- 本机 GNU toolchain 真编译耗时 ~2.5s（依赖缓存后），6/6 断言全过。
- 改坏必红：`EXPECT_KEY` 末字节篡改 → "会话 key = Python HKDF" FAIL + panic（rc=101），已实测。

## 🔴 运行时环境坑（已写进 run_probe.sh）

1. Windows 默认 MSVC toolchain 缺 C++ build tools → `link.exe` 失败（非 crate 问题），
   脚本自动切到已装的 `stable-x86_64-pc-windows-gnu`。
2. `E:/WorkBuddy` 是 junction（实指 `E:/WorkBuddyData`），rustc 在其下编译 `subtle` 时
   `STATUS_ACCESS_VIOLATION (0xc0000005)`；脚本把源码拷到非 junction 临时目录编译。

## 边界

- 本探针**不是**已集成固件的代码，只证明"实现这条 wire 的技术可行性 + 参考算法正确"。
- 三语言算法一致 ≠ 真机互通：`INTEROP_UNVERIFIED` 恒真，`ship_verdict=NOT_SHIPPABLE`，
  `live_hardware_accessed=false` 不变。
- 明文凭据是测试值 `TestPass123`，非真实密码；凭据不落库。
