# servo_probe 第三方代码署名 / Attribution

本目录含**来自第三方仓库的逐字节副本**。先读这一节再引用或分发。

## 1. 逐字节副本（未修改一行）

| 本地文件 | 上游路径 | 上游仓库 | 核对方式 |
|---|---|---|---|
| `hd1910_readonly.py` | `rl-series/scripts/hd1910_readonly.py` | `sxyseo/microduck-replica` @ `master` | sha256 与上游 raw 一致：`9cf2d21a89239c4f3b5dc06c8664d89fc58d02e2e8509c29044796d67b4f06ee`（4045 B） |

上游出处：commit `062f4d59`，作者 **abel**，2026-10-13，
提交说明「HD1910 台架四脚本入库:只读巡检(PING+遥测,摇晃法)、REBOOT 清锁判定、
原始字节诊断(零字节/乱码区分)、总线信号完整性」。

`hd1910_readonly.py` 提供协议帧拼装（`frame`）、`query`、`ping`、`signed_mag`
遥测解码，被本目录 `hd1910_ident.py` / `wobble_check.py` / `hd1910_snapshot.py`
**import 复用**（不复制实现 —— 两份实现会互抵，见项目记忆 §8）。

## 2. ⚠️ 许可状态：**未明确声明**（不是 Apache-2.0）

上游根 `LICENSE` 是**双许可证且按路径分配**，Apache-2.0 一栏只覆盖：

```
scripts/     渲染、导出、孔位分析脚本 / rendering, export, hole-analysis scripts
tools/       零依赖 STL 查看器 / zero-dependency STL viewer
```

CC BY-NC-SA 4.0 一栏覆盖的是上游 3D 模型衍生物与全部 `*.md` 文档。

**`rl-series/scripts/` 不在任何一栏里**，上游 `NOTICE.md` 的原创内容表也未列入。
上游仓库整体 `license: NOASSERTION`（GitHub 未识别出标准 SPDX 许可）。

第二处独立证据：`rl-series/README.md`（3585 B，该目录的说明文档）全文
**没有任何许可字样**（`licen/许可/apache/cc by` 零命中）；
`rl-series/` 下也不存在自己的 `LICENSE` 文件。
（对比：父仓 `fanhao375/microduck-replica` 的 `software/training/` 是**有**
自己的 `LICENSE` 的 —— 说明上游对子目录许可是「该写就写」，
`rl-series/` 没写就是漏了，不是「继承根许可」。）

查证顺序（可复跑）：`api.github.com/repos/sxyseo/microduck-replica` 取
`default_branch`（是 `master` 不是 `main`）→ `git/trees/master?recursive=1`
列全量路径 → raw 拉 `LICENSE` / `NOTICE.md` / `rl-series/README.md`。

⇒ 因此本目录的处理原则是：

- **不假设它是 Apache-2.0**（早期记录里写过这个推论，已查证推翻）。
- **不删除**：删掉副本会丢掉协议实现的出处，且本机脚本靠它 import。
- **保留逐字节原样**，不加本地改动，改动一律落在调用方（`*_check.py` / `*_ident.py`）。
- 若要**再分发**或**商用**，必须先向上游作者确认 `rl-series/scripts/` 的许可。

## 3. 同源但未入库的参考脚本

| 上游文件 | 本地位置 | 状态 |
|---|---|---|
| `rl-series/scripts/hl2915_bench.py`（32073 B） | `out/dl/ref_hl2915_bench.py` | 第三方参考，许可同上「未明确」，**不入库**（`out/` 被 gitignore） |
| `rl-series/scripts/hd1910_rawdebug.py`（1228 B） | `out/dl/ref_hd1910_rawdebug.py` | 同上 |

写寄存器的帧格式出处（`inst=0x03` 写指令）标注在
`hd1910_ident.py` docstring 里，指向 `hl2915_bench.py:156-159`，
因此即使参考脚本不在库里，也能追溯到上游来源。

## 4. 本目录原创实现（不涉及第三方许可）

`hd1910_ident.py`、`wobble_check.py`、`hd1910_snapshot.py`、`wobble.bat`
均为本项目原创，仅**复用**第 1 节的协议函数。
