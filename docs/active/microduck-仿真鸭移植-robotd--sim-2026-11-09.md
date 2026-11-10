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

### 5.3 平台边界：`robotd` 在 Windows 上编不过（WSL2 已绕开，见 §9）

```
robotd/src/main.rs:48     use tokio::net::{UnixListener, UnixStream};
robotd/src/main.rs:3326   UnixListener::bind(&socket_path)?
robotd/src/main.rs:3328   use std::os::unix::fs::PermissionsExt;
robotd/src/theremin.rs:33 use std::os::unix::net::UnixStream;
```

**没有 `cfg(unix)` 门控**（`main.rs` 的 `#[cfg(target_os="linux")]` 在 43/951/1080/1117，不覆盖上述行）。这是上游既有事实，不是本次改动引入。

后果：**`robotd` 整栈只能在 Linux 上跑**（`tokio::net::UnixListener` 文档标注 "Available on Unix and crate feature `net` only"）。给 unix socket 加 `cfg` 门控硬编到 Windows 没有意义：门控掉的正是控制面，`robotctl` 连不上，等于一个不可操控的空壳。所以 Windows 侧止步于 `duck-control`（编译、单元测试、对真 `body_server.py` 的端到端，见 §5.4），整栈走 Linux。

- ✅ **WSL2 路线已打通（2026-11-09 晚间）**：用户把 `wsl.exe` 从程序黑名单改为「询问」并以管理员运行，管理员 `wsl --install --no-distribution` + 重启后，用离线 rootfs `wsl --import` 装好 Ubuntu 24.04.5，编出 `robotd`/`robotctl`，整栈（50 Hz / IPC / 策略 / health / odom）**全部真跑通，零上游改动** —— 见 §9。
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

⚠️ **当时（本日早些时候）的边界**：这里验的只是「缝」本身（协议帧 + 客户端语义），50 Hz 循环、IPC/unix socket、`robotctl`、策略加载、health 门禁当时一个都没验。**这一层已在 §9 补齐**（WSL2 整栈真跑通），本节的门禁仍是独立可复跑的一层。

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

同一台 Linux 机器、两个进程都在本机时：

```bash
.venv-mjlab/Scripts/python.exe -m mjlab_microduck.sim.body_server --headless --port 7801
robotd --sim 127.0.0.1:7801
```

**本机实际用的是 WSL2 跨主机形态**（Windows 跑 body_server、WSL2 跑 robotd），地址要换成网关、body_server 要监听 `0.0.0.0`；且必须先 `robot.enable` 与 `torque on`，否则策略不驱动、关节不动。完整命令、参数与门禁见 §9。

`--sim` 与 `--fake` 互斥：`--fake` 是「空无组成的机器人」，`--sim` 是「在 MuJoCo 里的机器人」。

## 7. 这个移植**验不了**什么

❌ 总线时序（500k 位宽、帧间隔、`READ_TIMEOUT=30ms`）；❌ 蓝牙/相机/NPU/ToF 真实链路（`tof` op 存在但没接）；❌ 舵机固件 reg50/51 环路、齿隙、堵转。
⇒ **不能消 R3**。R3 仍只能靠台架、示波器或真上板。

## 8. 若继续，优先级（2026-11-09 晚间更新：1/2 已完成）

1. ~~放开 WSL、WSL2 里编整栈~~ ✅ **已完成**，见 §9。
2. ~~验 50 Hz / `robotctl health` / policy 名~~ ✅ **已完成**，见 §9；并额外抓出 torque 缺口。
3. ~~搬 `xgoduck_rl` 的 `roller_standup`/`sitstand`~~ **已撤销**：2026-11-09 核对发现 LIVE 训练包早已注册这两个任务，且 `roller_standup` 是带轮版专用。详见 `microduck-xgoduck任务定义与整机质量口径核对-2026-11-09.md`。
4. 剩下的真缺口：① 把 `torque on` 补进 `--sim` 的 bringup（见 §9.4，目前由门禁脚本外部发）；② `updaterd`/`configd` 未起，`health` 里这两块永远 unavailable；③ 真机总线时序 / R3 仍不在本链验证范围内（§7）。
5. Windows 侧已到极限且全部达成：§5.2 工具链配方（gnu + rust-lld 自包含 + zig dlltool shim）、§5.4 真服务器端到端门禁、§5.5 可重放移植包。

---

## 9. 整栈验证在 WSL2 真跑通（2026-11-09 晚间）

**结论先行**：`robotd --sim` + 真 `body_server.py` + `robotctl` IPC + ONNX 策略推理 + 50 Hz 循环，**全部真跑通**，零上游改动。此前 §5.3/§5.4 的「整栈未验」到此关闭。

### 9.1 环境与三个网络坑

| 项 | 做法 / 实测 |
|---|---|
| WSL2 | 管理员 `wsl --install --no-distribution` → 重启 → `wsl --import MicroDuckUbuntu E:\WSL\MicroDuck <pkg> --version 2` |
| 发行版包 | `ubuntu-24.04.5-wsl-amd64.wsl`（388,975,696 B，清华镜像），**gzip tar**；sha256 `bb415d82…6039e` 与官方 `DistributionInfo.json` 逐位一致 |
| 为什么用 `--import` | `wsl --list --online` 拉 `raw.githubusercontent.com` 超时（0x80072ee2），`aka.ms/wsl-ubuntu-2404` 已失效跳必应；非交互下 `--install --no-launch` 静默失败，OOBE 要真 TTY。`--import` 跳过 OOBE、默认 root |
| rustup | 官方源卡 22 分钟只下 80 MB；设 `RUSTUP_DIST_SERVER=https://rsproxy.cn` / `RUSTUP_UPDATE_ROOT=https://rsproxy.cn/rustup` 后几秒装完。**被中断的半个 toolchain 要先 `rustup toolchain uninstall` + 清残留目录**，否则报 "missing manifest" |
| cargo | 官方 crates.io index 卡 14 分钟；`~/.cargo/config.toml` 配 `rsproxy-sparse` 后 **1m52s 编完 robotd**。`robotd`/`robotctl` 只需 `build-essential + pkg-config + libssl-dev`，`serialport` 已 `default-features=false`（无 libudev），gstreamer 在 `mediad`、libudev 在 `padd`，都不在 robotd 链上 |
| 网络 | WSL2 NAT：网关 `172.26.32.1` 就是 Windows 主机。实测 `0.0.0.0:7801` **REACHABLE**，防火墙未拦、无需加规则 |
| ONNX Runtime | GitHub release `onnxruntime-linux-x64-1.23.2.tgz`（≥ 1.23.x 硬下限）→ `libonnxruntime.so*` 进 `/usr/local/lib` + `ldconfig`；9 个 alpha 策略复制到 `RELEASE_DIR=/opt/robot/daemon/current/policies`，**不用写 toml**（避开 `deny_unknown_fields`） |

⚠️ 通道坑：Bash 里 `wsl.exe` 需 `export MSYS2_ARG_CONV_EXCL='*'` 才不被 MSYS 路径转换改坏；复杂 Linux 命令**必须落盘成 .sh/.py 再执行**（PowerShell/Bash 传参都会吃掉 `$var` 和引号）；`run_in_background:true` 的任务里 `wsl.exe` 会被沙箱拦，长驻 daemon 要用前台启动、超时自动转后台。

### 9.2 起栈

```bash
# Windows 侧（后台）
.venv-mjlab/Scripts/python.exe -m mjlab_microduck.sim.body_server \
    --headless --host 0.0.0.0 --port 7801
# WSL2 侧（前台启动，超时自动转后台）
robotd --sim 172.26.32.1:7801 --socket /run/robotd.sock
```

### 9.3 三件待验事的实测数字

| 待验 | 结果 |
|---|---|
| **50 Hz 稳不稳** | `robotctl health`: `50.0 of 50.0 Hz · 3840 ticks · 0 missed` → 64 s 后 `49.9 Hz · 7023 ticks · 0 missed`。带 ONNX 推理时 `hz 49.988–50.039 / missed=[0]`，`busy≈0.8ms / read≈0.5ms / write≈0.2ms`（远低于 20 ms 预算） |
| **`health` 绿不绿** | `robot healthy`；`bus ok`、`imu ready`、`battery 7.40 V (50%)`、`motors 32 °C`。⚠️ `updaterd`/`configd` unavailable 是这两个 OS 服务没起，与仿真链无关 |
| **策略名是否真变** | 启动日志 `policy loaded mode="walk" walk=.../alpha_walking.onnx …`；`robot.setMode roller` → 2 s 后 `policy loaded mode="roller" walk=.../roller.onnx stand=None ground_pick=.../roller_crouch.onnx`。**`setMode` 是异步的**（先回站姿再重载），`accepted=True` ≠ 立即生效，中途再发同名命令会报 "already in that mode" |

### 9.4 🔴 新发现的缺口：`--sim` 下扭矩没被打开

带策略启动后遥测一度全部 `policy: "held"`、`step_ms=0`、关节/odom 全不动。两个门槛：

1. **`robot.enable {on:true,toggle:false}`**：上游刻意的安全不变量「*nothing here runs because a process started*」，`Bringup::Limp` 下只发 `robot.move` 不会让策略接管。enable 后回到 `enabled — driving`，`policy` 变 `stand`/`walk`、`step_ms` 变 0.14–0.50 ms。
2. **必须显式给 `body_server` 发 `torque on`（+ `gain`）**：enable 之后 `targets` 跨度已达 **2.90 rad**（策略在算、目标在写），但 `joints` 跨度 **全 0**、`odom` 只有 1 个值。`set_torque(true)` 在 `sim.rs` 里是实现了的，但 `--sim` 的 bringup 路径没走到它（与 `set_limp` 走 trait 默认返回 Err 同属一块边界）。

**负对照**（改坏必须变红，反过来这里「补上必须变绿」）：外部发 `{"op":"torque","on":true}` + `{"op":"gain","kp":8}` 之前，15 个关节跨度全 `0.00000`；之后 **0.13–1.40 rad**、`odom` 27 个不同位置、首末关节角明显不同 ⇒ `TORQUE_WAS_MISSING`。

补齐后完整 drive（`vx=0.3`，5 s @20 Hz）：`policy stand 27 / walk 45`，`step_ms 0.1418–0.5018`，`hz 49.988–50.039`，`missed=0`，`joint_span 0.1–0.61 rad`，`odom x` 前进 **0.586 m**，`odom_distinct=72`，`limited_by` 48 帧为空 ⇒ **VERDICT: PASS**。

### 9.5 可复跑门禁（2026-11-10 重写，见 §9.6）

> ⚠️ 此节描述的**旧版**门禁（脚本手发 `torque/gain`、断言 `dx>0.01`）已于 2026-11-10 作废：
> 它自己补扭矩，会把 `at_powered` 的功劳据为己有（换回裸 `at` 也 PASS），且 `dx` 符号随采样窗口
> 抖动（同一二进制 8 s 窗口实跑 `dx=+0.94`，10 s 窗口 `dx=-0.74`）。现行门禁见 §9.6，判据改为
> 「位移**跨度** + 关节跨 + walk + 观测鸭冻结 + torque 声明日志」，脚本**不碰** torque/gain。

```bash
# 双鸭服务器（duck0 给 robotd，duck1 当无-torque 观测者）
.venv-mjlab/Scripts/python.exe -m mjlab_microduck.sim.body_server \
    --headless --host 0.0.0.0 --port 7801 --ducks 2
# WSL 内：gate 只发 hello + robot.*，从不发 torque/gain
python3 /mnt/e/.../tools/hd1910/sim_stack_check.py --sim-host 172.26.32.1 \
    --observer-port 7802 --seconds 8
# 独立负对照：那只没人认领、没有 torque 的鸭必须全程冻结
python3 /mnt/e/.../tools/hd1910/sim_stack_check.py --sim-host 172.26.32.1 \
    --observer-port 7802 --no-torque --seconds 5
```

⚠️ 仍然**验不了** §7 列的那些（总线时序、蓝牙/相机/NPU/ToF、EEPROM/齿隙/堵转），**不能消 R3**。仿真鸭验证的是「循环 / 策略 / 安全 / IPC / odom 全是真的」，不是硬件。

### 9.6 `--sim` 上电扭矩：`at_powered` 修复与门禁三层判据（2026-11-10）

**修复**：`robotd --sim` 分支从 `RemoteIo::at(addr)` 改为 `RemoteIo::at_powered(addr)`（`main.rs:1055`）。
`at_powered` 在首次 TCP 握手后发一帧 `torque on`（并把最后已知扭矩状态记住、断线重连后重施），
对齐真机「上电即有扭矩」；裸 `at` 是纯协议客户端、一帧 torque 都不发。动机的精确表述在
`sim.rs:173-196` 的文档串里：`setMode` 在 `enable` 之前到达、把 bringup 推到 `Ready` 时，
`body_server` 的 `World.step` 会每步 `restore()` 钉住 `released=false` 的身体 —— 策略在算、
目标在写、关节/odom 全不动，且无任何报错。**这不是疏忽，是仿真协议与真机语义的差**。

**`body_server.py` 语义（一手源码，判据的物理基础）**：
- `World.step`：`if not body.released: body.restore()` —— 未被认领的鸭每步被摁回 `held` 姿态；
- `released` 是**每只鸭**的状态（多鸭共享一个 `World` 物理、但各自独立释放），唯一能清它的帧是
  `Body.set_torque(on=True)`（`:371-372`）；`--limp` 默认 `released=false`；
- 推论：同一 MuJoCo 世界里让 duck0 被 `robotd` 驱动、duck1 只回 `hello/read` 不发 torque，
  **一静一动**即可证明「是 torque 帧释放了身体」，而非物理漂移/时钟/策略。

**🔴 诚实订正：整栈「能不能走路」层，`at` 与 `at_powered` 不可区分。**
负对照实测把 `main.rs` 改回裸 `at`（重编 3.79 s）后，正常门禁**仍 PASS**：
duck0 `joint_span=0.61 rad / odom_span=0.98 m / walk 73/76`。原因在 `main.rs:2485-2501`：
控制循环里 `Bringup::Limp → Homing/Ready` 在 `robot.enable`（`enabled=true`）时**兜底发
`set_torque(true)`**，把握手帧的缺失掩盖了。所以门禁**不能**靠「走没走路」来分辨两者 ——
那样一定是恒绿的假象。真正的判据落在下面两层，均已实测改坏必红：

| 层 | 正常 `at_powered` | 改坏裸 `at` | 载体 |
|---|---|---|---|
| **静态接线** `--check` | RC=0 | **RC=1**，2 条 WIRING 报错 | `apply_sim_port.py`（已入库）|
| **整栈运行** harness | PASS + `simulated body torque state declared on=true` 日志行 | **FAIL**（MISSING 该行）| `gate_run.sh`（临时 harness）/ 日志行 |
| 库行为单测 | `at_powered` 发 hello→torque→read 三帧；裸 `at` 零 torque 帧 | （库能力仍在，**故单测守不住接线**）| `sim::tests` 4 个新测试，123 passed |

**🔴 门禁缺口修复（本轮找到并补上）**：`apply_sim_port.py --check` 旧版只查 6 个 marker +
`sim.rs`/`sim_e2e.rs` 两份内容哈希，**检查不到 `main.rs` 里 `at_powered` 这一个词**（marker
`--sim: the body is in MuJoCo` 仍在、`sim.rs` 哈希仍对）。改回裸 `at` 时 `--check` 照样 PASS
= 假绿。现已在 `inspect()` 增加接线断言：从 `SIM_LOOP_BLOCK` 派生 `POWERED_WIRING` 常量，
校验 `--sim` 分支必须含 `RemoteIo::at_powered(addr),` 且不含裸 `RemoteIo::at(addr),`。
`--selftest` 往返负对照仍 PASS（strip 掉 `SIM_LOOP_BLOCK` → 断言自然红 → 重放恢复绿）。

**门禁判据重构（为什么不用 `dx>0`）**：`+vx`（体坐标）命令在本栈稳态 walking 下积分到世界系
**-x**（kp=200 与 kp=8 两种增益实测 10 s 分别 `dx=-0.73 / -0.68`），且短窗口跨「站起暂态」时
符号会翻（8 s 窗口同二进制 `dx=+0.94`）。`odometry` 用 IMU quat 的 yaw 把 FK 步幅投到世界系
（`odometry/src/lib.rs:104-191`），`at_powered` 根本不碰 quat 约定或速度符号 —— 这是既有现象。
故判据用 **per-axis 位移跨度 `odom_span>0.05 m`**（问「动没动」，不问「往哪动」），净 `dx`
保留打印但不参与判定；「改坏必红」由静态接线断言 + 握手 torque 日志行保证，不靠位移符号。

**实测闭环（2026-11-10，Windows `body_server --ducks 2` + WSL `robotd --sim`）**：
- 正常：torque 行 `FOUND on=true`；duck0 `frames=76 policy={walk:72,stand:4} step_ms max 0.3443
  hz=[49.962,50.006] missed=[0] joint_span=0.59817 rad odom_span=1.0052 m`，duck1 观测鸭
  `frames=183 joint_span=0 trunk_disp=0` ⇒ **PASS (RC=0)**；
- 改坏裸 `at`：`MISSING torque` + harness 追加 FAIL ⇒ **FAIL (RC=1)**；
- 独立负对照（无 torque 鸭）：`frames=99 joint_span=0 trunk_disp=0` ⇒ **PASS (RC=0)**；
- `duck-control` 单测 **123 passed**；`apply_sim_port.py --check` 绿 / `--selftest` PASS /
  改坏树 `--check` 红。

**环境备忘（踩坑，均为已复现的现成坑）**：`robotd` 不能用后台任务常驻 —— `wsl.exe` 在非交互/
后台上下文报 `Permission denied (126)`（同类见 microsoft/WSL#10190），改由 WSL 内**前台 harness**
（`gate_run.sh`）一次性托管 robotd 全生命周期（起→等 socket→跑门禁→kill）。`wsl.exe ... bash -lc` 里
单引号包裹的 `$VAR` 会被 Git Bash 层提前展开成空 → harness/路径一律写死、不用 shell 变量；
`/mnt/c/...` 路径参数要带 `MSYS2_ARG_CONV_EXCL='*'` 否则被 MSYS 改写成 `D:/Program Files/.../mnt/c/...`。
Windows 侧依赖在 `microduck-software/.venv-mjlab/`（mujoco 3.7.0），不是 `.venv`。
