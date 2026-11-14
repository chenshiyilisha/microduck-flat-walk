# 主板到货上板执行单 §1.2 判据适用性裁定（2026-11-14）

> 触发：用户「继续，按照最优的来」。授权边界不变 —— **不采购下单**（不可逆，须明确点头）、**不改镜像**（破坏 sha pin 可复现链）、**不放宽判据去洗白状态**。
> 本文只做「适用性裁定」：判 1.2 判据与本板这张卡是否对象匹配，给出等价强度的替代验活路径与可执行命令。**不修改 §1.2 / §1.3 判据原文，不翻任何状态。**

## 0. 一句话结论

§1.2 与 §1.3 对同一张 V112 卡提出了**设计上互斥**的要求：1.2 要串口出现 `U-Boot→内核→login`，1.3 要 `cmdline` 无 `console=ttyS2` 且 mask `serial-getty@ttyS2`。镜像实读证明后者是这张卡的真实设计（且 UART2 要给舵机总线用），所以 **1.2 对 V112 是「判据对象错配 / 不适用」，不是「板子没过」，也不是「可以放宽」**。判据原文保留并加适用性注解；`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`、`COLLECTED != PASS`、1.2 仍 `UNVERIFIED_hardware`、A2 闭合数 0，全部不变。

## 1. 一手事实（全部来自 V112.img 只读实读，非推断）

2026-11-14 用 WSL2 `mount -o loop,ro,offset=16777216` 挂载 `microduck-zero3w-0.15.1-R1-V112.img`（3,157,262,336 B，sha256 `d8207ede…24f41`），并用 `debugfs` 作为**第二条独立算法**复算 7/7 文件哈希一致后读到：

| 项 | 实读值 | 含义 |
|---|---|---|
| `boot/extlinux/extlinux.conf` | `append … console=tty1 consoleblank=0 cma=256M` | 内核 console 指向 **tty1（HDMI/本地终端）**，没有 `console=ttyS2` |
| `/etc/systemd/system/serial-getty@ttyS2.service` | 符号链接 → `/dev/null`（mask） | 串口上**不会**起 getty，**不会有 login prompt** |
| `robotd` drop-in | `--port /dev/ttyS2 --commissioning`，`DeviceAllow=/dev/ttyS2 rw` | UART2 被 robotd 用作舵机总线；`robotd.toml` 实读 `port="/dev/ttyS2"`、`hz=50` |
| `extlinux.conf` overlay | `rk3568-uart2-m0` / `i2c4-m0` / `aic3104-i2c3` / `rpi-camera-v2` / `npu-enable` |  uart2 是功能总线，不是调试 console |
| `Microduck-Setup.nmconnection` + `microduck-setup.service` + `portal.py` | `mode=ap` / `10.42.0.1/24` / `PORT=8088` / `Restart=on-failure` | 镜像设计内的**首启入口就是 AP + 配网页**，不是串口 |

依据分级：以上全是**镜像内一手文件实读**（最高）；串口硬件参数 1500000n8 / 40-pin Pin8 TX·Pin10 RX 出自瑞莎硬件文档与项目验收清单（厂商/项目文档）；`console=tty1` 需要外接 HDMI 才能看到，属平台常识但**本机没有 HDMI 实测记录**，标 `UNVERIFIED_hardware`。

## 2. 冲突的机械证明

| 判据 | 原文要求 | 与镜像设计的关系 |
|---|---|---|
| §1.2 | 「串口看 U-Boot→内核→login」，验收「无 panic，进 login」 | 需要 `console=ttyS2` **且** `serial-getty@ttyS2` 未 mask ⇒ 两条都不成立 |
| §1.3 | `cat /proc/cmdline` 要求「无 `console=ttyS2`」；「做卡时 mask getty 未生效→重做卡」 | **明确要求** mask；与 1.2 直接互斥 |

⇒ 1.2 写的是「通用 Armbian 调试卡 / 自制作卡」的验活方式（`build-armbian-card.sh` 路线 A 可保留串口 console），而本板走的是 kissqy R1 换引导的成品镜像（路线 B）。**同一个执行单里混装了两条路线的判据**，这是对象错配，不是执行不到位。

⚠️ 另一个独立事实：本机串口链目前也没打通（`Win32_SerialPort` 为空，PnP 仅 `CH343 (COM3)` 且 `Status=Unknown`，与 11-14 实测 phantom(Code 45) 同型；CH343 在 1500000 非常规波特的支持未验证）。**即使判据适用也执行不了**，但这不能反过来当作「判据不适用」的理由 —— 裁定只依据镜像设计。

## 3. 裁定

1. **§1.2 对 V112 / 路线 B：判 `N/A_BY_DESIGN`（对象错配）**，在判据表加适用性注解，原文不删、不改、不降强度。
2. **不判 PASS、也不判 FAIL**：`N/A_BY_DESIGN` 是适用性结论，不是验证结果。1.2 的验收状态仍是 `UNVERIFIED_hardware`；已观察到的首启热点按 `COLLECTED != PASS` 只记观察值。
3. **不把「热点出现」升格成 1.2 PASS**：热点证明的是「U-Boot→内核→systemd→NetworkManager AP→portal」这条链到了用户态，强度不低，但缺断电负对照与配网页正对照，因果尚未闭合。
4. **不改镜像**：为凑 1.2 而加 `console=ttyS2` / 解 mask，会占用舵机总线、破坏 §1.3，且改动 rootfs 会使 sha pin 失效、丢掉可复现链。明确不采取。
5. **状态全部不变**：`live_hardware_accessed=false`、`ship_verdict=NOT_SHIPPABLE`、A2 闭合数 0、`UNVERIFIED != PASS`。

## 4. 等价强度替代验活路径（按证据强度排序，均需现场动作）

原 1.2 想证明的三件事：**引导链完整 / 内核起来了 / 进到用户态可交互**。三条替代路径分别覆盖：

### ① 首启热点 + 配网页正对照 + 断电负对照（推荐，镜像设计内入口）
```bash
# PC 侧：主动扫描，绕开 netsh wlan show networks 的缓存假象（SOP 坑 26）
python microduck-software/.upstream/downloads/wlan_scan_realtime.py
# 手机侧：关移动数据 → 连 Microduck-kissqy（密码见一手文档 §2/§7 与镜像 nmconnection，
#         按准则 13 此处不复写明文）→ 浏览器开 http://10.42.0.1:8088 回报页面
```
- **正对照**：配网页可访问 ⇒ systemd 已起、NetworkManager AP 生效、portal.py 在监听。
- **负对照（必做）**：拔 OTG 电源 5 s，前后各做一次主动扫描，SSID 应消失／重现 ⇒ 排除同名 AP、闭合因果。
- 已完成的只有「`WlanScan` 3/3 命中 SSID」这一项观察；正/负对照都还没做。

### ② SSH 进系统读运行时证据（覆盖 1.3 且能补内核阶段）
配网页设完密码后：
```bash
ssh radxa@10.42.0.1
cat /proc/cmdline                    # 直接交付 1.3 要的证据
uname -a
systemctl is-system-running
journalctl -b -o short-precise | head -40   # 补偿 1.2 想看的内核启动阶段
ip -br addr
systemctl status microduck-setup btd robotd --no-pager
```
⚠️ 镜像侧 SSH 服务是否启用**本轮未核实**，标 `UNVERIFIED_hardware`；若未开则此路不通，需先走 ①。

### ③ HDMI + USB 键盘进 tty1（`console=tty1` 的原生通道）
接 HDMI 显示器与 USB 键盘到 `USB 3.0 HOST`（下行口，OTG 继续供电），直接看内核日志末尾与 login prompt。⚠️ 需要现场有显示器/键盘，本机无 HDMI 实测记录，标 `UNVERIFIED_hardware`。

### ④ 临时改 cmdline 开串口 console（**不推荐，仅登记不执行**）
改 `extlinux.conf` 加 `console=ttyS2,1500000n8` 并解 mask，理论上可看串口，但会与 robotd 抢 UART2、破坏 §1.3、改写镜像并使 sha pin 失效，且**未查到本板一手实操记录**（这是推的，未找到现成方案）。仅作为「诊断备选且必须可回滚」登记。

## 5. 明确不做的事

- ❌ 删掉或改写 §1.2 判据文字、把「进 login」改成「有热点」。
- ❌ 把 3/3 热点观察写成 1.2 PASS 或整机签收。
- ❌ 改 `V112.img` / 解 mask / 改 `extlinux.conf`。
- ❌ 翻 `live_hardware_accessed`、`ship_verdict`、A2 闭合数。
- ❌ 采购下单、动采购 SSOT / contract / xlsx。

## 6. 待用户现场动作（3 项，均可直接闭合悬案）

1. 手机连首启热点开 `10.42.0.1:8088` 回报页面（正对照）。
2. 拔 OTG 电源 5 s，前后各做一次 `WlanScan` 主动扫描（负对照）。
3. 二选一：报板子背面丝印版本；或重插串口线 / 改接 HDMI+键盘，并报绿灯常亮还是闪烁。

## 7. 关联文档

- 执行单 §1.0e / §1.2 / §1.3：`docs/active/microduck-主板到货上板执行单-2026-11-12.md`
- 镜像审查（候选 1/6/9、App 适配）：`docs/active/microduck-V112镜像-按开发规范审查与优化候选-2026-11-14.md`
- 现场坑与规则：`docs/active/microduck-主板到货-踩坑与正确流程SOP-2026-11-14.md`
- 烧卡与首启观察：`docs/active/microduck-主板到货-烧卡操作卡-2026-11-14.md`
- 基线工具与契约：`microduck-software/tools/hd1910/check_v112_image_baseline.py`、`v112_image_baseline.json`
- 开发规范依据：`docs/active/microduck-安卓App-开发规范-2026-11-14.md` §3.2 / §6.2 / §6.3 / §7.4
