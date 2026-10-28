# 阶段 0 · 到货当天照做（HD-1910-C001 + URT-2 / URT-1）

对应 `docs/active/microduck-HD1910阶段C软件清单.md` §3、`docs/hardware/microduck-采购清单.md` §7.5–7.6、
`docs/hardware/路线B-HD1910-今日下单清单.md`。

操作步骤以 **fanhao375/microduck-replica 的《调试记录 · 舵机配置》**（他 2026-09-13 真的把 15 颗配完了）
为骨架，闸门数字取本仓 §7.6。**第一次上电前把本文读完，别跳步。**

---

## 0. 三条铁律

1. **一次只接一颗**改 ID（出厂 ID 全是 1，接两颗就撞车）。
2. **上电顺序：先插 USB，再给舵机上电。** 反了总线被压在 2.1 V，一颗都不应答（fanhao 实测踩过）。
   改任何线之前**断电**。
3. **别在满电 8.4 V 上做堵转测试** —— 8.4 V 是 HD-1910 的电压上限，零余量。台架一律 **7.4 V 限流 2 A**。

---

## 1. 到货前就能做（无硬件）

| # | 动作 | 到哪拿 |
|---|---|---|
| 1 | 装 **FD 调试软件**（Windows，解压即用免安装） | 原始出处 **gitee.com/ftservo/fddebug**；镜像 `fanhao375/microduck-replica` 仓库内 `tools/飞特/FD1.9.8.5(250729).7z`（MIT，带 sha256）；备用 `feetech.cn/software.html`（另有 macOS 版与 Web Serial 的 Servo Web） |
| 2 | 准备 CH340 驱动（**只是备用**） | URT-2 是 **CH343**，Win10/11 自带驱动；老款 URT-1 才要 CH340（`wch.cn`）。设备管理器出现 `USB-Enhanced-SERIAL CH343 (COMx)` 就不用管 |
| 3 | 跑一遍骨架 dry-run | `.venv-mjlab/Scripts/python.exe tools/hd1910/urt1_bench.py --dry-run` |
| 4 | 收藏 kissqy 镜像入口 | 见本文末尾「部署镜像入口（有板再刷）」 |

---

## 2. 接线

### 脚序 —— **认脚号，别认颜色**（三根线可能全黑）

```
HD-1910（AMP2.0-3P，2.0 mm 间距）   脚 1 = Signal / TTL
                                     脚 2 = Vcc        ← 中间那根一定是 V，飞特和 Dynamixel 一致
                                     脚 3 = GND
```

- ⚠️ **只有 V 接错才会烧**；S 与 G 反了不会烧，只是搜不到，对调即可。
- 脚 1 在插头上有小三角/缺口标记，或看舵机本体插座旁丝印；拿不准就万用表通断档量。

### URT-2 上认准左边两个白色 3 针口（丝印 `TTL-Bus`，`G V1 S`）

右边 4 针是 **RS485，不用**。拨码拨 **5 V**——那是 **TTL 信号电平选择（3.3/5 V），不是供电切换**。

### ⚠️ 插不上的必然性

**舵机线 2.0 mm 插头插不进 URT-2 的白座（更大）。** 两条路：

- 买「**舵机转接线 2.0 转 2.5 3P**」（采购清单里的"PH2.0 转接线"就是这一项，到货当天先插一次确认）；
- 等不及就**剪一根舵机线飞过去**（15 根牺牲一根，线头镀锡插进白座孔）。

### 三种供电，阶段 0 用第三种

| 方式 | 接法 | 什么时候用 |
|---|---|---|
| USB 5 V | V1 自带 5 V，什么都不接 | 只配 ID / 改参数（HD-1910 从 4 V 起工作，空载够 |
| 外电 → **V1 端子** | + 进 V1、− 进 G | 厂家标准接法，但**端子标 6 A**，15 颗堵转能到十几安 |
| **外电 → 舵机 V/G，URT-2 只共地，V1 空着** | + 接舵机 V；− 接舵机 G **和** URT-2 的 G | ✅ **台架用这个**：电流不过 URT-2；也防 7.4 V 反灌烧电脑 USB |

```
外电 7.4 V（限流 2 A）  →  舵机 V(2)、G(3)
URT-2 S                →  舵机 Signal(1)
URT-2 G                →  与电源负极共地
URT-2 V1               →  空着          ← 勿灌 7.4 V
URT-2 USB-C            →  PC（FD）
```

**忘了共地 = 扫描不到舵机或乱码，新手第一大故障。**

---

## 3. FD 八步（一颗约两分钟）

```
1  插 URT-2 → 设备管理器「端口」记下 COMx（CH343）
2  接好线，万用表通断档确认电源正负极没短路
3  先插 USB，再开外电 7.4 V / 限流 2 A        ← 顺序别反
4  FD：选 COMx → 波特率 1000000 → 点「打开」
5  点「搜索」→ 列表出现 ID 1、型号 HD-1910（旧版 FD 显示 unknown 可忽略）
6  切「编程」页改 EPROM（下表）→ 保存
7  断电 → 重新上电 → 再「搜索」，新 ID 出现才算写进去   ← 别省，EPROM 要断电重启才确定
8  贴标签（写「关节名 + ID」，别只写数字）→ 拔掉换下一颗，回第 4 步
```

### EPROM 改什么（**每颗都改这几项，别的别动**）

| 参数 | 出厂 | 改成 | 为什么 |
|---|---|---|---|
| **ID** | 1 | 按下表 | 运行时按 ID 找关节 |
| **过流保护** | **关** | **开** | 装机后堵转是常事，不开就是烧舵机 |
| **过压保护** | **关** | **开** | 8.4 V 满电落在 4–10 V 窗口内，不会误触发 |
| 过热保护 | 开（80 ℃） | 不动 | — |
| 波特率 | 1 Mbps | 不动 | 出厂就是官方要的 |
| 运行模式 | 模式 4（纯位置 PD） | 不动 | 正是 RL 落地要的那个 |
| Return delay | 0 | 不动 | STS 系列上这项不起作用 |
| 中位 | — | **装机时再校** | FD 的"中位校准"只会把当前位置当 2048，**只能在腿伸直时用** |

### ID 表（上游 `duck-control/src/model.rs`，注释说是对着硬件量出来的）

| ID | 关节 | ID | 关节 | ID | 关节 |
|---|---|---|---|---|---|
| 10 | 右髋 yaw | 20 | 左髋 yaw | 30 | 颈俯仰 |
| 11 | 右髋 roll | 21 | 左髋 roll | 31 | 头俯仰 |
| 12 | 右髋 pitch | 22 | 左髋 pitch | 32 | 头 yaw |
| 13 | 右膝 | 23 | 左膝 | 33 | 头 roll |
| 14 | 右踝 | 24 | 左踝 | 34 | 嘴 |

记法：**十位 = 部位**（1 右腿 / 2 左腿 / 3 颈头），**个位 = 从躯干往末端数**（0 髋 yaw → 4 踝）。
ID 200 是 `imu_to_dxl` 板，固件写死，不在这里配。

### 看它转（可选）

主页面点中舵机、拉位置滑杆 —— USB 5 V 空载能转但没力，**接 7.4 V 才是真实工况**。

---

## 4. 闸门（本仓 §7.6 · 不过就换货，别买齐 15 颗）

| # | 判据 | 怎么做 | 参照 |
|---|---|---|---|
| 0.1 | ping 通 / ID 改得动 / **1 Mbps** | FD 第 4–7 步 | — |
| 0.2 | **50 Hz 事务 ≤5 ms、0 CRC** | `urt1_bench.py --port COMx --id 1` 或 FD 连续读写 | fanhao 实测：整机 15 颗同步读 **4.8 ms @7.2 V**，0 超时 0 校验错；单机应更快 |
| 0.3 | **kt / R / 死区 / 齿隙 / 最高速** | 见下节 | 与 `bam_param_compare.md` 对照 |
| 0.4 | **温升**：额定 **0.36 N·m**（不是堵转 1.47）@7.4 V 连续 60 s，外壳 **<60 ℃** | 外电直供、限流 2 A | 过热保护 80 ℃ 是兜底，不是目标 |
| 0.5 | **固件 P（reg 50）= 32** | FD 读寄存器 50，或 `urt1_bench` gate 0.4 | 与训练 `kp_fw=32` 一致 |

寄存器（SMS/STS 内存表，与 `urt1_bench.py` 常量一致）：`ID=5`、`波特率=6`、`扭矩使能=40`、
`目标电流=44`、`P=50`；波特率索引 **0 = 1 Mbps**。

`urt1_bench.py` 目前**不内嵌 FTServo SDK**：live 需要你先 `pip` 装官方 SMS/STS 端口再接到
`try_open_live()`，否则**先用 FD 过闸**（不要在这里自写 daemon，方案 §5 / 阶段C §6 禁止）。

---

## 5. 0.3 kt/R 对照（资料已在仓）

- OpenMicroDuck 台架表征：`.upstream/j_hd1910_calibration_params_hd1910_characterization.json`
- 训练用汇总：`tools/bam_params/hd1910/m5.json`
- 对照表：`bam_param_compare.md`

采购文曾写 `record_pendulum_bench.py`：**公开树里未检索到同名文件**（2026-10-26）。到货后优先
① FD / 官方协议读电流·速度做简易估计，或 ② 复用 BAM / 社区摆锤流程。测完与上表比对即可，不必等"同名脚本"。

---

## 6. 搜不到舵机 · 按顺序查

1. 驱动装没装（CH343 应免驱）/ COM 口选对没
2. 波特率是不是 **1000000**
3. **上电顺序**：先 USB 后舵机（反了总线被压 2.1 V）
4. **共地**接了没（第一大故障）
5. S 线接触好不好（临时插孔最可疑）
6. S / G 是不是反了
7. 外电是不是真到了舵机 V/G（万用表量，别看电源屏显）

---

## 7. 记录模板（跑完就写，别靠记忆）

```json
{
  "date": "YYYY-MM-DD",
  "servo": "HD-1910-C001",
  "adapter": "URT-2 (CH343, COMx)",
  "supply_V": 7.4, "current_limit_A": 2.0,
  "fd_version": "1.9.8.5",
  "id_set": 1,
  "protection": {"over_current": true, "over_voltage": true},
  "gates": {
    "0.1_ping_1mbps": true,
    "0.2_txn_ms_median": null, "0.2_crc_errors": null,
    "0.3_kt": null, "0.3_R": null, "0.3_backlash_deg": null,
    "0.4_case_temp_C_after_60s": null,
    "0.5_reg50_P": null
  },
  "verdict": "pass | fail(换货)",
  "note": "urt1_bench 输出见 out/urt1_bench_stage0.json"
}
```

写进 `out/`（脚本自动生成）+ 当天日记忆。**sim2real 结论必须带：植物指纹（m5）+ 镜像版本 + P/D。**

---

## 8. 明确别做

- ❌ 用 **U2D2**（HD1910 上不能用，¥260 打水漂）
- ❌ 一次买齐 15 颗（0.2 不过就全砸手里）
- ❌ 满电 8.4 V 做堵转（那是上限，零余量）
- ❌ 腿没伸直时用 FD 的"中位校准"（只会把当前位置当 2048）
- ❌ 拿陆吾 `1910_m6.json` 当主训（`actuator: sts3215`，是改名不是实测）
- ❌ 在这里写总线 daemon / robotd

---

## 部署镜像入口（有板再刷；现在可收藏）

来源：本地 `.upstream/kissqy/README.md` / [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy)

| 件 | 链接 |
|---|---|
| 系统镜像 R1 | https://github.com/kissqy/Microduck-kissqy/releases/tag/public-image-r1 （`microduck-zero3w-0.15.1-R1.img.xz`） |
| 机器人中控 V167 | https://github.com/kissqy/Microduck-kissqy/raw/refs/heads/main/release-assets/Microduck-Console-R17-V167.zip |
| 训练中控（可选） | `release-assets/Microduck-Training-Studio-R1.5.27.zip` |

许可：作者原创部分**个人非商业**。不自写 robotd。
上板勾选见 **`deploy_import_checklist.md`**（镜像 V167、方向表、P=32、运行端 0.9/0.5/0.7）。

## 本仓已跑通的软件闸门

```bash
# ONNX parity（obs 61 → act 14）
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/parity_smoke.sh

# 回头续训（默认接到 6000 iter）
"D:/Program Files/Git/bin/bash.exe" tools/hd1910/resume_train.sh
```
