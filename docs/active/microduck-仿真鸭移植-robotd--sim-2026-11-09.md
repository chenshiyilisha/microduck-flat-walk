# 仿真鸭移植：给 B 代 robotd 加 `--sim`（2026-11-09）

_记录：为什么移植、移植了什么、改哪几行、验证到什么程度、以及**一个必须知道的平台死结**。_

---

## 1. 为什么做

现状是「台架 PC + URT-2 + 单舵机，没有整机」。因此这些**从来没验证过**：50 Hz 环的真实调度抖动、策略槽位热替换、跌倒检测/FallPredictor/`gain_limp`、odom、health 门禁、updater 回滚链路、全部 IPC。

官方做法是把**唯一一层**——舵机总线——换掉，上面全部原样跑。`duck-control` 的 `RobotIo` trait 就是这个缝。

## 2. 上游事实（带 `file:line`）

| 事实 | 出处 |
|---|---|
| `RemoteIo` 实现在 pollen 线（`ft1910`），B 代没有 | `.upstream/ft1910/duck-control/src/sim.rs` 全文 |
| B 代零命中 `--sim` / `RemoteIo` | `grep -rn "RemoteIo\|--sim" .upstream/DuckBuddy-main/` 空 |
| 线协议由**对端**定义：`PROTOCOL = 1` | `mjlab_microduck/sim/body_server.py:59` |
| op = `hello`/`read`/`write`/`gain`/`torque`/`slow`（+`tof`） | `body_server.py:407-431` |
| `hello` 应答 `{"protocol":1}`，不符则抛错 | `body_server.py:409-415` |
| `read` 返回 `positions`/`velocities`/`currents_ma`/`imu{gyro,gravity,quat}`，另附 `trunk_z`/`trunk`/`sim_time` | `body_server.py:320-341` |
| `slow` 返回 `{"volts":7.4,"temps_c":[32.0]×15}` | `body_server.py:103-104,342` |
| 15 关节 ↔ 模型 14 关节的插入/删除在 **Python 侧**做 | `body_server.py:31-36` |
| 重力向量在 Python 侧算（`mju_quat2Mat`） | `body_server.py:162-167` |
| 仿真器按**墙钟**步进（health 门禁低于 45/50 Hz 判 unhealthy） | `body_server.py` `run()` 文档串 |

## 3. 移植时**故意不照抄**的三处

1. **无 `measures_load`/`measures_velocity`** —— B 代 trait 没有这两个方法；`Sensors.currents_ma` 是定长数组，「没测」和「测到 0」同值。上游的 `load_reported` 在这里无消费者，删掉而非留成死状态。
2. **无 `reboot`** —— 仿真舵机没有锁存硬件故障，B 代 trait 也没有（`ft1910` 为协议 2 Dynamixel 加过）。
3. **`set_limp` 走 trait 默认实现**（返回 `IoError::Bus`）。仿真侧只有整机 `torque`；实测发 `{"op":"limp"}` 被回 `unknown op 'limp'`。**已知缺口不是疏忽** —— rest 姿态在 `--sim` 下记一条 bus error，而不是假装卸了力。

## 4. 改了哪些文件（纯新增 / 纯接线）

| 文件 | 改动 |
|---|---|
| `duck-control/src/sim.rs` | **新增** 513 行：`RemoteIo` + 9 个单元测试 |
| `duck-control/src/lib.rs` | 加 `pub mod sim;` |
| `duck-control/Cargo.toml` | 加 `serde_json.workspace = true` |
| `robotd/src/main.rs` | 加 `--sim <host:port>`（`conflicts_with="fake"`）+ 控制线程内分支 + `let sim = args.sim.clone();` |

`robotd` 那段**不调用 `open_bus_waiting`**：`RemoteIo` 懒连接、每 tick 重连，先起 duck 后起仿真器时 duck 只报 unhealthy 直到对端应答 —— 与「总线上没上电」同一条路径。

`sim.rs` 里几个非显然决定：`set_nodelay(true)`（Nagle 会把小写入压 ~40 ms＝两个 tick，表现成「仿真器很慢」的静默故障）；连接/读/写超时都 200 ms；**任何错误都丢连接**（解析不了的帧意味着两端对「一条消息从哪开始」不一致，行协议除了重来没法重新同步）。

## 5. 验证到什么程度

### 5.1 线协议：对**真实** `body_server.py` 跑过，10/10 PASS

不是 mock：真起 `body_server.py --headless`，再用与 `sim.rs` **逐字节相同**的帧对话。

```
server up in 1.4s
PASS hello  -> protocol 1
PASS read   -> 15 joints, imu ok, 额外键(serde 忽略) = ['sim_time','trunk','trunk_z']
PASS write  -> {}   PASS gain -> {}   PASS torque -> {}
PASS slow   -> volts=7.4 temps=15
PASS 负对照 protocol 99 被拒 / 'limp' 不在线上 / 14 个 target 被拒
PASS write 真的动了关节 2 -> +0.0054 rad
```

⚠️ 最后一条**第一次是 FAIL（+0.0000），原因是我测量错不是协议错**：写完立刻 `read`，两读之间仿真器一步都没走。加延迟后同一写命令确实把关节推向目标。

顺带测出真实现象：**不给任何命令，0.3 s 内关节 2 自漂 −0.0113 rad** —— 与 `body_server.py` 自称「双足静态姿态靠纯位置控制稳不住」一致。

### 5.2 Rust 编译与测试：**已验证，119/119 全绿（2026-11-09 晚间补验）**

本机没有 MSVC（`gcc`/`clang`/`link.exe` 全无，Windows Kits 的 Lib 目录为空），GitHub release 域名走代理 502 拿不到 llvm-mingw。解法是**三件套拼出免 MSVC 的自包含工具链**：

1. **rustup `stable-x86_64-pc-windows-gnu`** 自带 `rust-lld.exe` + `self-contained` mingw CRT（`crt2.o`、`libkernel32.a` 等）⇒ `-C linker=rust-lld -C link-self-contained=yes` 不需要任何外部 C 编译器即可链接；
2. `windows-sys` 在 gnu 目标上走 raw-dylib 需要 `dlltool.exe` ⇒ **PyPI `ziglang`（0.17.1）自带 `llvm-dlltool`**，用能跑的 rustc 编了一个转发 shim `dlltool.exe` 放进 PATH；
3. 沙箱拦 `.rcgu.o` 的删除（`os error 5`）⇒ 免沙箱 + 全新 `CARGO_TARGET_DIR`。

结果：

```
cargo +stable-x86_64-pc-windows-gnu test -p duck-control --target x86_64-pc-windows-gnu
test result: ok. 119 passed; 0 failed; 0 ignored   （含 sim::tests 全部用例：
  set_limp 报错语义 / protocol 不匹配双向报版本 / 未知键忽略 / targets 按关节序交叉 /
  无 load 块默认 0 / 拒答即错误 / read 携带 loop 期望的传感器 / 坏帧丢连接 / 仿真器重启下 tick 重连）
```

负对照说明这不是假绿：此前的 `cargo check` 两轮**真实失败过**（`link.exe` 不存在、`dlltool` 缺失、沙箱删除被拒），每修一处才前进——失败模式可复现，绿是修出来的不是绕出来的。

### 5.3 🔴 平台死结仍在：`robotd` 在 Windows 上编不过

```
robotd/src/main.rs:48     use tokio::net::{UnixListener, UnixStream};
robotd/src/main.rs:3326   UnixListener::bind(&socket_path)?
robotd/src/main.rs:3328   use std::os::unix::fs::PermissionsExt;
robotd/src/theremin.rs:33 use std::os::unix::net::UnixStream;
```

**没有 `cfg(unix)` 门控**（`main.rs` 的 `#[cfg(target_os="linux")]` 在 43/951/1080/1117，不覆盖上述行）。这是上游既有事实，不是本次改动引入。

后果：**robotd 整栈只能在 Linux 上跑**。`tokio::net::UnixListener` 文档标注 "Available on Unix and crate feature `net` only" ⇒ 就算给 unix socket 加 `cfg` 门控，Windows 版会失去控制面，`robotctl` 连不上，**等于做一个不可操控的空壳**——所以 Windows 侧止步于 `duck-control`（编译、单元测试、以及**对真 `body_server.py` 的端到端**均已达成，见 §5.4），整栈验证的正确出口是 Linux：

- **WSL 路线（当前唯一可行）**：`wsl.exe` 目前在沙箱程序黑名单里（用户已同意开 WSL，需在 WorkBuddy 安全中心 → 命令安全 → 程序黑名单中移除 `wsl.exe`，且 `wsl --install` 需管理员）；放开后整栈（robotd/robotctl/_unix socket/50Hz/health）可在 WSL2 原生跑，**零上游改动**。
- 将来真上板也是 Linux（Radxa/Yocto），这条验证天然复用。

### 5.4 Rust 客户端 ↔ 真 MuJoCo 服务器：**端到端 2/2 PASS，负对照真红**

§5.1 的 10/10 是 **Python 手写帧**，§5.2 的 119/119 是 **mock `TcpListener`**。中间留着一个真空：`sim.rs` 的 `Deserialize` 从没解析过 Python `json.dumps` 产出的真帧（额外键、float 拼写、换行），也从没量过真一步 MuJoCo 的往返耗时。本节补上。

- 新增 `duck-control/tests/sim_e2e.rs`（两个 `#[ignore]` 测试），编排 `microduck-software/tools/hd1910/sim_e2e_check.py`：起真 `body_server.py --headless` → 跑编译好的 harness → **杀掉服务器，用同一 harness 再跑一遍并要求它变红**。一个从不连服务器的测试会两轮全绿，因此绿结果不可能是空跑。
- 门禁刻意**不把「编译失败」算作负对照的红**：必须失败在断言/连接上。

本机实跑输出（2026-11-09）：

```
read: pos0=-0.002727 vel0=0.002116 cur0=0.225700 |g|=1.000000 |q|=1.000000
      gravity=[-0.053284, 0.022474, -0.998326]
slow: volts=7.4 temps[0]=32 count=15
read RTT over 50 live ticks: p50=151.2us max=257.4us
joint 2: uncommanded 300ms drift=-0.011355 | commanded +0.20 -> delta=+0.119049
test result: ok. 2 passed; 0 failed
--- server stopped ---
test result: FAILED. 0 passed; 2 failed   (both: connection timed out)
VERDICT: PASS
```

读数与结论：

1. **真帧被全量吃下**：`trunk_z`/`trunk`/`sim_time` 等额外键、Python float、行分隔都没让 serde 掉连接；`|g|=|q|=1` 且 gravity 非 `[0,0,0]` 的全零假帧——这正是「输出落在看起来合理区间」的静默 bug 该挡的地方。
2. **50 次 live `read` RTT p50 151.2 µs / max 257.4 µs**，比 20 ms tick 小两个数量级；`set_nodelay(true)` 生效，没有 ~40 ms 的 Nagle 尾巴。注意这是**单次请求往返**，不是整 tick 预算（不含策略推理、IPC）。
3. **`write` 真推动关节**：+0.20 rad 目标、300 ms 后实动 +0.119 rad，同期无命令自漂只有 −0.011355（10.5×）。这个自漂与 §5.1 用 Python 独立测出的 −0.0113 对上了——两条独立测量互证。
4. **负对照真红**：关掉服务器后两个测试同时 FAILED（`TcpStream::connect_timeout` 在 Windows loopback 无监听端口上表现为 *timed out* 而非 *refused*，属真实现象）。第一次实跑时 cargo 的 `.cargo-build-lock` 被拒访问，门禁如实报 `VERDICT: FAIL` 并指出「负对照没红」，**没有假绿**；随后把编译前置、脚本只托管服务器+测试二进制，问题解决。

复现（编译一次，门禁可反复跑）：

```bash
export PATH="$HOME/.cargo/bin:$HOME/.wb_tmp/tools:$PATH"
export CARGO_TARGET_DIR="C:/Users/hejih/.wb_tmp/ct_dc5" CARGO_INCREMENTAL=0
export RUSTFLAGS="-C linker=rust-lld -C link-self-contained=yes"
cd microduck-software/.upstream/DuckBuddy-main
cargo +stable-x86_64-pc-windows-gnu test -p duck-control --test sim_e2e \
    --target x86_64-pc-windows-gnu --no-run
cd <repo root>
CARGO_TARGET_DIR=<same> microduck-software/.venv-mjlab/Scripts/python.exe \
    microduck-software/tools/hd1910/sim_e2e_check.py
```

⚠️ **边界没变**：这里验的是「缝」本身（协议帧 + 客户端语义）。50 Hz 循环、IPC/unix socket、`robotctl`、策略加载、health 门禁**一个都没验**，整栈仍 Linux-only，见 §5.3。

### 5.5 🔴 改动持久化：`.upstream/` 被 gitignore

`microduck-software/.gitignore:5` 忽略整个 `.upstream/` ⇒ `sim.rs`、六处接线、`sim_e2e.rs` **全都不入库**，换机器 / 重新解包就全丢。已补一份可重放移植包（本轮入库）：

```
microduck-software/tools/hd1910/sim_port/
  sim.rs                 duck-control/src/sim.rs 的字节副本
  sim_e2e.rs             duck-control/tests/sim_e2e.rs 的字节副本
  apply_sim_port.py      6 处幂等接线：lib.rs(1) / 两个 Cargo.toml(2) / main.rs(3)
```

- `--check`：验 2 个源文件字节一致 + 6 处接线在位（现况 PASS）。
- `--selftest` 是带负对照的往返：把六处插入**剥掉**造干净树 → `--check` 报 8 个问题（红）→ 重放 → 0 问题（绿）→ **重放出来的 4 个文件与现用树逐字节一致（0 差异）** → 二次 apply 0 文件改写（幂等）。
- 这条比对抓出一个真 bug：Windows `Path.write_text` 把 `\n` 静默转成 CRLF，`read_text` 又静默转回来，**文本 diff 全绿而字节全变**；读写都已钉 `newline=""`。又一个「文本看着对 ≠ 字节对」的实例。
- 再补一层跨机器防护：`core.autocrlf=true` 会在 clone 时把本目录转成 CRLF，而 tarball 解出的 `.upstream` 是 LF ⇒ 锚点与字节比对会全线崩。已加 `.gitattributes` 强制 `eol=lf`，并让 `read_text` 规范化 CRLF、源比对按内容哈希。**CRLF 负对照**：整棵临时树转 CRLF → `--check` 0 problems；把 `sim.rs` 改坏一个字节 → 恰好 1 条 `MISMATCH`（证明不是恒绿）。
- 故意不重放：`fake` 参数注释里提到 `--sim` 的文案（纯措辞，无功能影响）。

`--check` 也是 clone 后的第一道自检，与 `apply_to_live.py --check` 同一习惯。

## 6. 怎么用（Linux）

```bash
.venv-mjlab/Scripts/python.exe -m mjlab_microduck.sim.body_server --headless --port 7801
robotd --sim 127.0.0.1:7801
```

`--sim` 与 `--fake` 互斥：`--fake` 是「空无组成的机器人」，`--sim` 是「在 MuJoCo 里的机器人」。

## 7. 这个移植**验不了**什么

❌ 总线时序（500k 位宽、帧间隔、`READ_TIMEOUT=30ms`）；❌ 蓝牙/相机/NPU/ToF 真实链路（`tof` op 存在但没接）；❌ 舵机固件 reg50/51 环路、齿隙、堵转。
⇒ **不能消 R3**。R3 仍只能靠台架、示波器或真上板。

## 8. 若继续，优先级

1. **放开 WSL（用户已同意，2026-11-09 19:23 复测仍被程序黑名单硬拦，且策略明确不可重试/绕行）**：安全中心移除 `wsl.exe` 黑名单 + 管理员装发行版；WSL2 里编 robotd（Linux 原生，unix socket 直接可用）+ `body_server.py` 同机跑。**这是整栈验证唯一的剩余阻塞项**。
2. 起栈后先只验三件：**50 Hz 是否稳 / `robotctl health` 是否绿 / 策略 load 后日志里的 policy 名是否真的变了**。
3. 再搬 `xgoduck_rl` 的 `roller_standup`/`sitstand` —— P3 缺这两个，而「跌倒后自己起来」是整机验收硬项。
4. Windows 侧已到极限且全部达成：§5.2 工具链配方（gnu + rust-lld 自包含 + zig dlltool shim）、§5.4 真服务器端到端门禁、§5.5 可重放移植包。`duck-control` 后续改动本机跑 `cargo test`，再跑 `sim_e2e_check.py` 与 `apply_sim_port.py --check` 即可。
