#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
硬件监控 + 3D 仿真模型的**结构化静态检查器**（stdlib-only）。

为什么还需要它：core 自检（Kotlin/JVM 真跑）证明的是「函数算得对」，证明不了
「UI 真的接上了」「阈值没被人悄悄改掉」「两条消费链调的是同一个函数」。
本项目踩过的坑：只测内部函数不测 CLI、陈腐读数假绿、两消费链各自漂移、
docstring 写死数量随权威漂移。这里用**结构化正向断言 + 注入式负对照**补上。

🔴 判据独立于被测值：阈值期望值硬编码在 [EXPECTED_THRESHOLDS]（并注明一手出处），
不取自被检源码；关节 ID 表硬编码在 [EXPECTED_JOINT_IDS]（ft1910 lib.rs:560-564）。
若本地存在 `.upstream/ft1910` 一手 Rust 源码，再做一次第三方交叉核对。

verdict 只输出 RESULT: N errors；不写 PASS、不改 ship_verdict。

用法：
    python tools/check_hardware_monitor.py
    python tools/check_hardware_monitor.py --selftest
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent          # microduck-android-app
ROOT = BASE.parent                                      # 仓库根
CORE = BASE / "core/src/main/kotlin/io/microduck/app/core"
APP = BASE / "app/src/main/kotlin/io/microduck/app"
TESTS = BASE / "core/src/test/kotlin/io/microduck/app/core"
# 🔴 真机网格两份产物：core/resources 供 JVM 自检，app/assets 供 Android AssetManager。
# 两者一旦字节漂移，就会出现「core 自检全绿、真机静默降级」的假绿（11-15 实测踩过）。
CORE_MESH = BASE / "core/src/main/resources/duck_mesh.bin"
APP_MESH = BASE / "app/src/main/assets/duck_mesh.bin"

FILES = {
    "monitor": CORE / "HardwareMonitor.kt",
    "parts": CORE / "RobotParts.kt",
    "geometry": CORE / "DuckModelGeometry.kt",
    "mesh": CORE / "DuckMesh.kt",
    "holo": CORE / "HoloRenderer.kt",
    "health": CORE / "HealthSnapshot.kt",
    "policy": CORE / "AiDebugPolicy.kt",
    "view": APP / "monitor/DuckModelView.kt",
    "main": APP / "MainActivity.kt",
    "viewmodel": APP / "MainViewModel.kt",
    "holder": APP / "SessionHolder.kt",
    "receiver": BASE / "app/src/debug/kotlin/io/microduck/app/AiDebugReceiver.kt",
    "selftest": TESTS / "CoreSelfTest.kt",
    "doc": ROOT / "docs/active/microduck-安卓App-硬件监控与3D仿真模型-2026-11-15.md",
}

# ── 独立锚（门禁阈值绝不取自被测量）──
# 出处见 docs/active/... §阈值一手依据：
#   Feetech STS3215 规格书 §7-11（>70°C 关扭矩 / 工作 -10~60°C）
#   Radxa ZERO 3W Product Brief Rev1.8 §6.5（85°C thermal governor）
#   duck-control/src/model.rs:170-191（6.6V empty / 8.2V full 线性映射）
EXPECTED_THRESHOLDS = {
    "BATTERY_WARN_PERCENT": 20.0,
    "BATTERY_CRITICAL_PERCENT": 10.0,
    "BATTERY_CRITICAL_VOLTS": 6.6,
    "BATTERY_WARN_VOLTS": 6.92,
    "SERVO_WARN_C": 60.0,
    "SERVO_CRITICAL_C": 70.0,
    "CPU_WARN_C": 80.0,
    "CPU_CRITICAL_C": 85.0,
    "LOOP_DEGRADE_RATIO": 0.9,
}

# ft1910 duck-ipc-proto/src/lib.rs:560-564
EXPECTED_JOINT_IDS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14]
EXPECTED_JOINT_NAMES = [
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll", "mouth",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
]


def read(src: dict, key: str) -> str:
    return src.get(key, "")


def load_all() -> dict:
    out = {}
    for k, p in FILES.items():
        try:
            out[k] = p.read_text(encoding="utf-8")
        except OSError:
            out[k] = ""
    return out


def mesh_artifacts(app_override: bytes | None = None) -> tuple[bytes, bytes]:
    """读两份网格产物；app_override 仅供负对照注入「漂移读数」，绝不写盘。"""
    core = CORE_MESH.read_bytes() if CORE_MESH.is_file() else b""
    if app_override is not None:
        app = app_override
    else:
        app = APP_MESH.read_bytes() if APP_MESH.is_file() else b""
    return core, app


def const_values(kotlin: str) -> dict:
    return {m.group(1): float(m.group(2))
            for m in re.finditer(r"const val (\w+)\s*=\s*(\d+(?:\.\d+)?)", kotlin)}


def called_names(kotlin: str) -> set[str]:
    """AST 等价：结构化提取调用名，避免裸子串扫描自反噬（本项目实测踩过）。"""
    names: set[str] = set()
    for m in re.finditer(r"\b(?:[A-Za-z_]\w*\.)?(\w+)\s*\(", kotlin):
        names.add(m.group(1))
    return names


def code_only(kotlin: str) -> str:
    """剥掉块注释/行注释，只留代码 —— 判据若扫裸子串会被注释里的示例代码反噬。
    项目踩过：类注释写「旧版 `DuckMesh.load()` 用 classpath」被当成真调用判红。"""
    s = re.sub(r"/\*.*?\*/", "", kotlin, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)


def kotlin_string_list(kotlin: str, var: str) -> list[str]:
    m = re.search(r"val\s+" + re.escape(var) + r"\s*:\s*List<String>\s*=\s*listOf\((.*?)\)",
                  kotlin, re.S)
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


def kotlin_int_list(kotlin: str, var: str) -> list[int]:
    m = re.search(r"val\s+" + re.escape(var) + r"\s*:\s*List<Int>\s*=\s*listOf\((.*?)\)",
                  kotlin, re.S)
    if not m:
        return []
    body = re.sub(r"//.*", "", m.group(1))
    return [int(x) for x in re.findall(r"\b(\d+)\b", body)]


def main_block(kotlin: str) -> str:
    """只取 JVM 自检 main 的调用区块：函数定义里出现同名字符串不算「挂进 main」。"""
    m = re.search(r"fun main\(args:\s*Array<String>\)\s*\{(.*?)\n    \}", kotlin, re.S)
    return m.group(1) if m else ""


def enum_names(kotlin: str, enum: str) -> list[str]:
    """取 enum class 体里的大写标识符。兼容单行声明 `{ A, B }` 与多行声明。"""
    m = re.search(r"enum class\s+" + re.escape(enum) + r"\b[^{]*\{(.*?)\}", kotlin, re.S)
    if not m:
        return []
    body = m.group(1)
    body = re.sub(r"//.*", "", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return re.findall(r"\b([A-Z][A-Z0-9_]*)\b", body)


def evaluate(src: dict, app_mesh_override: bytes | None = None) -> tuple[str, list[str]]:
    errs: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errs.append(msg)

    m, p, g = read(src, "monitor"), read(src, "parts"), read(src, "geometry")
    h, v = read(src, "health"), read(src, "view")
    main, holder, receiver = read(src, "main"), read(src, "holder"), read(src, "receiver")
    vm = read(src, "viewmodel")
    st, doc, policy = read(src, "selftest"), read(src, "doc"), read(src, "policy")

    for k, label in (("monitor", "HardwareMonitor.kt"), ("parts", "RobotParts.kt"),
                     ("geometry", "DuckModelGeometry.kt"), ("view", "DuckModelView.kt"),
                     ("main", "MainActivity.kt"), ("selftest", "CoreSelfTest.kt"),
                     ("doc", "单一权威文档")):
        need(bool(read(src, k)), f"{label} 缺失或为空")

    # ⓪ 产物级判据：两份真实网格必须都存在且字节完全一致。
    # 这是「core JVM 自检绿但真机降级」假绿的唯一产物层防线（源码判据看不到漂移）。
    core_mesh, app_mesh = mesh_artifacts(app_mesh_override)
    need(len(core_mesh) > 0, "core/src/main/resources/duck_mesh.bin 缺失或为空")
    need(len(app_mesh) > 0,
         "app/src/main/assets/duck_mesh.bin 缺失或为空（真机走 AssetManager，缺了必降级）")
    need(core_mesh == app_mesh,
         "duck_mesh.bin 两份字节漂移：JVM 自检与真机看到的不是同一个模型")

    # ① 阈值：值必须与独立锚一致，且源码里必须带一手依据注释
    vals = const_values(m)
    for name, want in EXPECTED_THRESHOLDS.items():
        need(name in vals, f"阈值 {name} 消失")
        if name in vals:
            need(abs(vals[name] - want) < 1e-9,
                 f"阈值 {name}={vals[name]} 与独立锚 {want} 不符（改阈值须同步依据与锚）")
    for token in ("Feetech STS3215", "Radxa ZERO 3W", "battery_percent", "Reported, never judged"):
        need(token in m, f"HardwareMonitor 缺一手依据注释：{token}")

    # ② 关节表：与 ft1910 一手表逐项一致
    ids = kotlin_int_list(p, "JOINT_IDS")
    names = kotlin_string_list(p, "JOINT_NAMES")
    need(ids == EXPECTED_JOINT_IDS, f"JOINT_IDS 漂移：{ids}")
    need(names == EXPECTED_JOINT_NAMES, f"JOINT_NAMES 漂移：{names}")
    need("partOfId" in p and "partOfName" in p, "RobotParts 缺 ID/名称映射函数")
    need("severityArgb" in p, "RobotParts 缺语义色单一真源")

    # ③ 可选第三方交叉核对：本地若有一手 Rust 源码，必须也一致（不阻断 CI）
    rust = ROOT / "microduck-software/.upstream/ft1910/duck-ipc-proto/src/lib.rs"
    cross = "UNAVAILABLE"
    if rust.is_file():
        try:
            rtxt = rust.read_text(encoding="utf-8", errors="replace")
            rid = re.search(r"pub const JOINT_IDS:\s*\[u8;\s*15\]\s*=\s*\[(.*?)\]", rtxt, re.S)
            rnm = re.search(r"pub const JOINT_NAMES:\s*\[&str;\s*15\]\s*=\s*\[(.*?)\]", rtxt, re.S)
            if rid and rnm:
                rids = [int(x) for x in re.findall(r"\b(\d+)\b", re.sub(r"//.*", "", rid.group(1)))]
                rnames = re.findall(r'"([^"]+)"', rnm.group(1))
                need(rids == ids and rnames == names, "Kotlin 关节表与 ft1910 一手 Rust 源码不一致")
                cross = "MATCH" if rids == ids and rnames == names else "MISMATCH"
        except OSError:
            cross = "UNREADABLE"

    # ④ 判定链：绝不输出 PASS；三档数据源分层齐全
    verdicts = enum_names(m, "MonitorVerdict")
    need(bool(verdicts), "解析不出 MonitorVerdict 枚举")
    need("PASS" not in verdicts, "MonitorVerdict 混入 PASS（观测值不得冒充验收结论）")
    need(all(x in verdicts for x in ("NO_DATA", "DEMO_ONLY", "NOMINAL", "WARNING", "CRITICAL")),
         f"MonitorVerdict 档位不全：{verdicts}")
    need("demo -> MonitorVerdict.DEMO_ONLY" in m, "Mock 源不再恒为 DEMO_ONLY")
    need("MonitorVerdict.NO_DATA, notes" in m or "MonitorVerdict.NO_DATA" in m,
         "无数据分支丢失")
    need("alerts += HwAlert(sev, part, message, basis, demo)" in m,
         "告警缺 demo 标记或依据字段")
    need("val demo = source == MonitorSource.MOCK_FIXTURE" in m, "demo 标记来源被改")

    # ⑤ 缺失语义 + 部位绑定（结构化调用名，不用裸子串）
    calls = called_names(m)
    for fn in ("partOfId", "partOfName", "merge", "evaluate"):
        need(fn in calls, f"HardwareMonitor 未真调用 {fn}")
    need("pct == null && volts == null" in m, "电池缺失语义被删（会渲染成 0 V）")
    need("maxC == null" in m and "cpuC == null" in m, "温度缺失语义被删")
    need("missingFieldPresent" in m and "不据此判总线正常" in m,
         "bus.missing 省略/空数组语义被删")
    need("不提供无线 RSSI" in m, "协议边界声明被删（会诱导伪造 RSSI）")
    need("逐舵机温度 UNVERIFIED" in m, "前向兼容的 UNVERIFIED 标注被删")

    # ⑥ 几何：第二条独立算法 + 深度排序 + 自检真跑
    need("fun rotateYTwice" in g and "R(a)=R(a/2)" in g, "第二条独立旋转算法被删")
    need("rotateY(p, degrees / 2.0)" in g, "旋转群复合律实现被改（不再是独立路径）")
    need("sortedBy { it.second.depth }" in g and "sortedBy { it.avgDepth }" in g,
         "深度排序被删（遮挡会画错）")
    need("CAMERA_DISTANCE" in g and "FOCAL_RATIO" in g, "透视投影参数缺失")
    need("两条独立" in st and "rotateYTwice" in st, "core 自检没真跑旋转互算")
    main_calls = main_block(st)
    need(bool(main_calls) and "testHardwareMonitor()" in main_calls and
         "testDuckModelGeometry()" in main_calls, "新增自检函数没挂进 main 调用区块")
    need("舵机 60.0°C WARN / 70.0°C CRITICAL" in st and
         "边界 20.0% 不 WARN" in st, "动态自检缺阈值边界负对照")

    # ⑦ UI 接入 + 真机门禁回归防护
    # 阶段 2 UDF：渲染由 uiState.collect 驱动，renderMonitor 改为接收 state 参数
    # （旧形态 renderMonitor() 已不存在）——用正则锁「渲染入口存在」而非写死参数签名。
    need("DuckModelView" in main and re.search(r"renderMonitor\s*\(", main) is not None,
         "健康页没接 3D 模型")
    need("DuckModelView(this@MainActivity)" in main,
         "健康页没有真的构造 DuckModelView（只留 import/字段声明不算接入）")
    need("advanceFrame()" in main, "模型没有旋转驱动")
    need("setTextIfChanged" in main, "1s tick 的 setText 节流被删（uiautomator idle 死锁）")
    need("setRotating(i == 1)" in main, "离开健康页未暂停旋转")
    need('"robot.health 真字段：' in main, "健康页顶部断言文本被挤掉（真机 59/59 会红）")
    need("Mock 演示夹具" in main, "健康页 Mock 来源标注被删（真机 59/59 会红）")
    viewCode = code_only(v)
    # 阶段 4：视图不再自己算颜色/画圆点，改为把 report 的 severityOf 注入 core 投影链。
    # 🔴 2026-11-17 阶段 5：投影链升为全息管线（core HoloRenderer，像素级 z-buffer + 提边），
    # 判据同步改为「视图把 sevOf 注入 HoloRenderer.render」+「状态色仍取自 severityArgb
    # 单一真源」——断言意图不变（颜色即状态不断链），不靠字符串残留。
    holo = src.get("holo", "")
    # 判据必须锁「sevOf 作为第 5 实参真的传进去」，而不是「文件里出现过 sevOf」
    # （实测：只查标识符存在时，把实参换成 { Severity.UNKNOWN } 仍假绿）。
    need(re.search(
        r"HoloRenderer\.render\(\s*m\s*,\s*angleDeg\.toDouble\(\)\s*,\s*iw\s*,\s*ih\s*,\s*sevOf\s*,",
        viewCode) is not None,
        "3D 视图未把状态注入 core 全息渲染链（颜色即状态断链）")
    need("RobotParts.severityArgb" in holo,
         "全息渲染自造状态色（必须取 RobotParts.severityArgb 单一真源）")
    need("r?.severityOf(p) ?: Severity.UNKNOWN" in viewCode,
         "3D 视图状态真源未接 MonitorReport（无证据时必须 UNKNOWN=基色）")
    # z 测试必须以代码形式存在（注释里出现「z-buffer」不算）——负对照会把 zbuf 全改掉。
    need(re.search(r"if \(z > zbuf\[idx\]\)", holo) is not None,
         "全息渲染缺 z 测试（内部零件会从缝隙漏线）")
    need(re.search(r"\bdrawCircle\s*\(", viewCode) is None,
         "3D 视图仍在画状态圆点（阶段 4 要求去圆点、部件本体着色）")
    need("Severity.UNKNOWN" in viewCode and "按部件状态着色" in v,
         "3D 视图 contentDescription 未说明部件着色（真机门禁可观测）")
    need("非运动学解算" in v, "3D 视图缺「非运动学解算」声明")
    # 🔴 资源可达性（2026-11-15 真因固化）：core/src/main/resources 是 Java resource，
    # 打进 APK 根目录后 ART ClassLoader 读不到；真机必须走 assets + AssetManager.open。
    # 上一轮 core 自检 476/476 全绿却真机降级线框，就是因为缺这条判据。
    need("assets.open(MESH_ASSET)" in viewCode and "DuckMesh.loadFromBytes" in viewCode,
         "真机网格未走 assets + loadFromBytes（classpath 在 Android 读不到，会静默降级）")
    need("DuckMesh.load()" not in viewCode,
         "3D 视图仍在用 classpath DuckMesh.load()，Android 上必然返回 null")
    need("contentDescription" in viewCode and "已加载" in viewCode,
         "网格加载状态不可观测（contentDescription 必须写明已加载/未加载）")
    need(re.search(r"\b\w+\.drawText\(", viewCode) is None,
         "模型 Canvas 内仍在 drawText，会压在模型上遮挡（声明/图例应移到卡片外 TextView）")
    mesh_code = read(src, "mesh")
    need("fun shadeColor(" in mesh_code,
         "网格缺 Lambert 光照（半透明+无光照会把模型画成碎片）")
    need("(0xFF shl 24)" in mesh_code,
         "网格填充 alpha 未强制不透明（无 z-buffer 时半透明叠色会画成碎片）")

    # ⑦b 阶段 4：DMSH v2 部件映射 + 状态着色（源码结构 + 产物字节双重判据）。
    # 源码判据防「有人把 project 切回四参版/把 UNKNOWN 默认成绿」；
    # 产物判据直接读字节，防「源码写了 v2 但 bin 还是 v1」的假绿。
    need("VERSION_V2" in mesh_code and "n_parts" in mesh_code and "partIndices" in mesh_code,
         "DuckMesh 缺 DMSH v2 解析（n_parts/partIndices 分支）")
    need("VERSION_V1" in mesh_code and "ModelPart.NO_PART" in mesh_code,
         "DuckMesh 缺 v1 兼容解析（老网格无部件索引必须保持基色）")
    need("nParts != ModelPart.SLOT_COUNT" in mesh_code,
         "v2 n_parts 未与单一真源槽位数校验（生成期/core 会静默错位）")
    need("severityOf: (RobotPart) -> Severity" in mesh_code and "statusTint" in mesh_code,
         "project 缺 severityOf 状态着色重载（颜色即状态未接入投影链）")
    need("project(mesh, angleDegrees, width, height, { Severity.UNKNOWN })" in mesh_code,
         "四参 project 未委托到状态着色版（两条消费链会漂移）")
    need("MIX_OK < MIX_WARN" in st and "MIX_WARN < MIX_CRITICAL" in st,
         "core 自检缺「OK 低强度 < WARN < CRITICAL」强度梯度断言")
    need("ModelPart" in p and "SLOT_COUNT" in p,
         "RobotParts 缺 ModelPart 部件槽位单一映射")
    need("partIndexOf" in mesh_code and "ModelPart.of" in mesh_code,
         "状态着色未按部件槽位取 severity（会整只刷同色）")

    # 产物字节判据（独立 struct 解析，不复用生成脚本自报数字）：
    # v2 header = magic + version + n_verts + n_tris + n_parts = 20B，末尾 n_tris×u8 部件索引。
    if core_mesh:
        try:
            mg, ver, nv, nt, nparts = struct.unpack_from("<4sIIII", core_mesh, 0)
            p_off = 20 + nv * 3 * 4 + nt * 3 * 4 + nt * 4
            parts = list(core_mesh[p_off:p_off + nt])
            need(mg == b"DMSH" and ver == 2, f"网格产物不是 v2: magic={mg!r} version={ver}")
            need(nparts == 21, f"网格产物 n_parts={nparts} 与 21 槽位不符")
            need(len(parts) == nt, "网格产物部件索引数组长度 != n_tris")
            need(all(x <= 20 or x == 255 for x in parts),
                 "网格产物存在越界部件索引(非 0..20/255)")
            need(any(x != 255 for x in parts), "网格产物没有任何可着色三角形")
            need(all(x in parts for x in (16, 17, 18)),
                 "网格产物缺 BATTERY/CPU/IMU 系统件槽位")
            need(len(core_mesh) == p_off + nt, "网格产物尾部长度与部件索引数组不符")
        except struct.error:
            need(False, "网格产物太短，无法解析 v2 header")

    # ⑧ 三条消费链汇聚同一个真源：RobotRepository.snapshot().monitorReport
    #    阶段 2 UDF 后 UI 链经 MainViewModel 中转，不再直连 SessionHolder：
    #      UI 链   = MainActivity.renderMonitor 读 uiState.monitorReport
    #                ← MainViewModel.onSnapshot 从 snap.monitorReport 派生（snap=repository 快照）
    #      AI 链   = AiDebugReceiver → SessionHolder.monitorReport() → repository 快照
    #      报告入口 = SessionHolder.monitorReport()（委托 repository 快照）
    #    三链最终仍读同一快照；不允许任何一链另起炉灶重算。
    need("fun monitorReport(" in holder, "SessionHolder 缺统一报告入口")
    need(receiver.count("SessionHolder.monitorReport()") >= 1,
         "AI 通道 monitor 命令未复用统一报告入口")
    need("snapshot()" in holder and "monitorReport" in holder,
         "SessionHolder.monitorReport 未委托 repository 快照（真源分叉）")
    need("state.monitorReport" in main, "健康页未从 uiState 消费 monitorReport（UDF 断链）")
    need("snap.monitorReport" in vm and "onSnapshot" in vm,
         "MainViewModel 未从 repository 快照派生 monitorReport（UI 链真源分叉）")
    need('"monitor"' in policy, "AI 通道命令白名单缺 monitor")

    # ⑨ 单一权威文档必须写清可行性边界与 UNVERIFIED
    for token in ("能不能实现", "bus.missing", "PATCH_PROPOSED_NOT_APPLIED",
                  "UNVERIFIED", "逐舵机", "70", "85"):
        need(token in doc, f"单一权威文档缺关键结论：{token}")

    verdict = "UNVERIFIED_ARTIFACTS_ABSENT" if any(
        not read(src, k) for k in ("monitor", "parts", "geometry", "view", "main", "viewmodel",
                                   "selftest", "doc")
    ) else ("NOT_PASS" if errs else "OK")
    print(f"first_source_cross_check: {cross}")
    return verdict, errs


def selftest(src: dict) -> list[tuple[str, bool]]:
    """注入式负对照：改坏源码，检查必须变红。只见过绿的判据不是证据。"""
    def variant(**kw) -> dict:
        return {**src, **kw}

    m, g, p, main, holder, policy, st, doc, v, mesh, vm, holo = (
        read(src, "monitor"), read(src, "geometry"), read(src, "parts"),
        read(src, "main"), read(src, "holder"), read(src, "policy"),
        read(src, "selftest"), read(src, "doc"), read(src, "view"), read(src, "mesh"),
        read(src, "viewmodel"), read(src, "holo"),
    )
    cases: list[tuple[str, dict]] = [
        ("阈值 70→90 必红", variant(monitor=m.replace("SERVO_CRITICAL_C = 70.0", "SERVO_CRITICAL_C = 90.0"))),
        ("电池阈值 20→35 必红", variant(monitor=m.replace("BATTERY_WARN_PERCENT = 20.0", "BATTERY_WARN_PERCENT = 35.0"))),
        ("MonitorVerdict 混入 PASS 必红",
         variant(monitor=m.replace("enum class MonitorVerdict { NO_DATA,",
                                   "enum class MonitorVerdict { PASS, NO_DATA,"))),
        ("Mock 不再 DEMO_ONLY 必红",
         variant(monitor=m.replace("demo -> MonitorVerdict.DEMO_ONLY", "demo -> MonitorVerdict.NOMINAL"))),
        ("删掉 partOfId 绑定必红",
         variant(monitor=m.replace("RobotParts.partOfId(", "UNRELATED_CALL("))),
        ("删掉「不提供无线 RSSI」边界必红",
         variant(monitor=m.replace("协议不提供无线 RSSI", ""))),
        ("删掉第二条独立旋转算法必红",
         variant(geometry=g.replace("fun rotateYTwice", "fun unusedRotateHelper"))),
        ("关节 ID 表漂移必红", variant(parts=p.replace("20, 21, 22, 23, 24,", "20, 21, 22, 23, 25,"))),
        ("健康页删掉 3D 接入必红",
         variant(main=main.replace("DuckModelView(this@MainActivity)", "View(this@MainActivity)"))),
        ("删掉 setTextIfChanged 节流必红",
         variant(main=main.replace("setTextIfChanged", "setTextDirect"))),
        ("删掉健康页顶部断言文本必红",
         variant(main=main.replace("robot.health 真字段：", "已删除："))),
        ("AI 通道白名单删掉 monitor 必红",
         variant(policy=policy.replace('"monitor",', ""))),
        # 🔴 阶段 2 UDF 真源链负对照：UI 链脱离 uiState / ViewModel 脱离快照 都必须判红，
        # 否则上面两条新判据只是摆设（注入式负对照，非只看绿）。
        ("健康页脱离 uiState.monitorReport 必红",
         variant(main=main.replace("state.monitorReport", "SessionHolder.monitorReport()"))),
        ("ViewModel 脱离 repository 快照必红",
         variant(viewmodel=vm.replace("snap.monitorReport", "null"))),
        ("自检函数没挂进 main 必红",
         variant(selftest=st.replace("        testHardwareMonitor()\n", ""))),
        ("文档删掉 UNVERIFIED 边界必红",
         variant(doc=doc.replace("UNVERIFIED", "已验证"))),
        ("产物缺失必红", variant(monitor="")),
        # 🔴 2026-11-15 真因负对照：删掉 assets 读取 / 恢复 classpath / 恢复 canvas 文字
        # / 删掉光照 —— 任一改坏都必须判红，否则这道判据是摆设。
        ("真机网格改回 classpath 必红",
         variant(view=v.replace("assets.open(MESH_ASSET)", "DuckMesh::class.java.getResourceAsStream"))),
        ("删掉 loadFromBytes 必红",
         variant(view=v.replace("DuckMesh.loadFromBytes", "SomeOtherLoader.parse"))),
        ("恢复 DuckMesh.load() 必红",
         variant(view=v + "\nprivate val broken = DuckMesh.load()\n")),
        ("模型内恢复 canvas.drawText 必红",
         variant(view=v + "\nprivate fun brokenDraw(c: android.graphics.Canvas, p: android.graphics.Paint) { c.drawText(\"x\", 0f, 0f, p) }\n")),
        ("删掉 Lambert 光照必红",
         variant(mesh=mesh.replace("fun shadeColor", "fun unusedShade"))),
        ("删掉不透明 alpha 必红",
         variant(mesh=mesh.replace("(0xFF shl 24)", "(0x80 shl 24)"))),
        # 🔴 阶段 4 v2/着色负对照：改坏任一条新判据都必须判红。
        ("删掉 v2 n_parts 真源校验必红",
         variant(mesh=mesh.replace("nParts != ModelPart.SLOT_COUNT", "nParts < 0"))),
        ("删掉 severityOf 着色重载必红",
         variant(mesh=mesh.replace("severityOf: (RobotPart) -> Severity", "unused: Int"))),
        ("四参 project 脱离着色版必红",
         variant(mesh=mesh.replace("project(mesh, angleDegrees, width, height, { Severity.UNKNOWN })",
                                   "projectLegacy(mesh, angleDegrees, width, height)"))),
        ("部件映射槽位数消失必红",
         variant(parts=p.replace("SLOT_COUNT", "SOMETHING_ELSE"))),
        ("自检删掉强度梯度断言必红",
         variant(selftest=st.replace("MIX_WARN < MIX_CRITICAL", "MIX_WARN > MIX_CRITICAL"))),
        # 🔴 阶段 5 全息管线负对照（2026-11-17）：视图不把 sevOf 注入 HoloRenderer /
        # 渲染器自造状态色 / 删掉 z-buffer 遮挡 —— 任一改坏都必须判红。
        ("视图删除全息状态注入链必红",
         variant(view=v.replace(
             "HoloRenderer.render(m, angleDeg.toDouble(), iw, ih, sevOf, ss)",
             "HoloRenderer.render(m, angleDeg.toDouble(), iw, ih, { Severity.UNKNOWN }, ss)"))),
        ("全息自造状态色必红",
         variant(holo=holo.replace("RobotParts.severityArgb", "unusedStatusColor"))),
        ("全息删掉 z-buffer 遮挡必红",
         variant(holo=holo.replace("zbuf", "unusedDepthBuf"))),
        ("视图恢复状态圆点必红",
         variant(view=v.replace("        canvas.drawOval(w * 0.22f",
                                "        canvas.drawCircle(1f, 1f, 1f, triFillPaint)\n        canvas.drawOval(w * 0.22f"))),
        ("视图 severify 真源脱离 report 必红",
         variant(view=v.replace("r?.severityOf(p) ?: Severity.UNKNOWN", "Severity.UNKNOWN"))),
    ]
    out = []
    for label, evidence in cases:
        verdict, errs = evaluate(evidence)
        if label.startswith("产物缺失"):
            out.append((label, verdict == "UNVERIFIED_ARTIFACTS_ABSENT"))
        else:
            out.append((label, verdict != "OK" and len(errs) > 0))
    # 🔴 产物级负对照（源码注入覆盖不到）：直接注入一份「漂移的 assets 读数」，
    # 检查器必须判红 —— 只见过绿色的字节判据不是证据。
    drift_verdict, drift_errs = evaluate(src, app_mesh_override=b"DRIFTED_MESH_BYTES")
    out.append(("网格两份产物字节漂移必红",
                drift_verdict != "OK" and len(drift_errs) > 0))
    base_verdict, base_errs = evaluate(src)
    out.append(("正对照:未改动源码零错误", base_verdict == "OK" and not base_errs))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="跑注入式负对照")
    args = ap.parse_args()
    src = load_all()
    verdict, errs = evaluate(src)
    for e in errs:
        print("  ERROR  " + e)
    print(f"VERDICT = {verdict}")
    print(f"RESULT: {len(errs)} errors")
    rc = 1 if (errs or verdict != "OK") else 0
    if args.selftest:
        print("\n=== 注入式负对照 ===")
        checks = selftest(src)
        for label, ok in checks:
            print(("  PASS  " if ok else "  FAIL  ") + label)
            if not ok:
                rc = 1
        print(f"SELFTEST: {sum(1 for _, ok in checks if ok)}/{len(checks)} passed")
    return rc


if __name__ == "__main__":
    sys.exit(main())
