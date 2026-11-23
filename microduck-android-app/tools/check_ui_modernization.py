#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
现代 UI 闸门（2026-11-21）：Material 3 弹窗 + 真扫码入口 + M3 顶栏/导航骨架。

判据刻意绑「结构」而不是截图观感：
  1. 全 App 不能再有 `android.app.AlertDialog.Builder`；写操作确认统一走 AppDialogs。
  2. AppDialogs 必须用 `MaterialAlertDialogBuilder`，且提供 confirm/input 两类入口。
  3. QR 扫码必须是 CameraX + ML Kit bundled（无 GMS）+ QR-only；Manifest 有 CAMERA 权限。
  4. BLE 面板必须真的有「扫码导入配对码」和「手动输入」两个入口；
     两者都汇入 BlePairingStore.parsePairingUri 单一权威。
  5. 主壳必须仍然保留四个顶层目的地与门禁硬串（重构不能把可测性弄丢）。
  6. 设置页滑块必须有基准稿要求的「危险阈值分段轨道」：单一权威切点 0.7f、
     按 bounds 比例两段着色、胶囊裁剪、接入 SeekBar 背景层、警示色低透明。

--selftest 用真实源码注入负对照：改坏任一支必须变红；只跑绿断言不算自检。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
APP = BASE / "app" / "src" / "main"

FILES = {
    "app_dialogs": APP / "kotlin/io/microduck/app/ui/AppDialogs.kt",
    "main": APP / "kotlin/io/microduck/app/MainActivity.kt",
    "threshold": APP / "kotlin/io/microduck/app/ui/ThresholdTrackDrawable.kt",
    "ble": APP / "kotlin/io/microduck/app/ble/BleConnectPanel.kt",
    "scan": APP / "kotlin/io/microduck/app/ble/PairScanActivity.kt",
    "firmware": APP / "kotlin/io/microduck/app/update/FirmwarePanel.kt",
    "ssh": APP / "kotlin/io/microduck/app/ssh/SshPanel.kt",
    "gradle": BASE / "app/build.gradle.kts",
    "manifest": APP / "AndroidManifest.xml",
    "layout": APP / "res/layout/activity_pair_scan.xml",
}

REQUIRED = tuple(FILES.values())


def code_only(src: str) -> str:
    """去掉 Kotlin/XML 注释，避免注释里的旧文案冒充实现（正向断言用真代码）。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    return src


def load() -> dict[str, str]:
    missing = [str(p.relative_to(BASE)) for p in REQUIRED if not p.is_file()]
    if missing:
        raise FileNotFoundError("缺文件: " + ", ".join(missing))
    return {k: p.read_text(encoding="utf-8") for k, p in FILES.items()}


def check(s: dict[str, str]) -> list[str]:
    errs: list[str] = []
    d = {k: code_only(v) for k, v in s.items()}

    # 1) 弹窗单一权威：MaterialAlertDialogBuilder 只在 AppDialogs 出现
    dialogs = d["app_dialogs"]
    if "MaterialAlertDialogBuilder" not in dialogs:
        errs.append("AppDialogs 未用 MaterialAlertDialogBuilder")
    if not re.search(r"fun\s+confirm\s*\(", dialogs):
        errs.append("AppDialogs 缺 confirm 入口")
    if not re.search(r"fun\s+input\s*\(", dialogs):
        errs.append("AppDialogs 缺手动输入入口 input")
    all_kt = "\n".join(v for k, v in d.items() if k.endswith(("main", "ble", "scan", "firmware", "ssh")))
    if "AppDialogs.confirm" not in all_kt:
        errs.append("业务面板未走 AppDialogs.confirm 单一权威")
    if re.search(r"android\.app\.AlertDialog", all_kt) or "AlertDialog.Builder" in all_kt:
        errs.append("仍有平台默认 AlertDialog.Builder（旧弹窗回退）")

    # 2) 扫码技术链：bundled 无 GMS、QR-only、CameraX MLKitAnalyzer
    gradle = d["gradle"]
    for dep in ("androidx.camera:camera-core", "androidx.camera:camera-view",
                "androidx.camera:camera-mlkit-vision", "com.google.mlkit:barcode-scanning"):
        if dep not in gradle:
            errs.append(f"build.gradle 缺扫码依赖 {dep}")
    if "play-services-mlkit-barcode-scanning" in gradle:
        errs.append("误用 unbundled 模型（需要 Google Play services，国内不可靠）")
    scan = d["scan"]
    for token in ("LifecycleCameraController", "MlKitAnalyzer", "Barcode.FORMAT_QR_CODE",
                  "EXTRA_SCAN_VALUE", "setBarcodeFormats"):
        if token not in scan:
            errs.append(f"PairScanActivity 缺 {token}（扫码链不完整）")
    camera_perm = re.search(r'android:name\s*=\s*"android\.permission\.CAMERA"', s["manifest"])
    if "PairScanActivity" not in d["manifest"] or not camera_perm:
        errs.append("Manifest 缺 PairScanActivity 或 CAMERA 权限")
    if "camera_preview" not in d["layout"]:
        errs.append("扫码页布局缺 PreviewView")

    # 3) BLE 面板真实入口：不能只改文案，必须能跳转 + 有手动兜底
    ble = d["ble"]
    for label in ("扫码导入配对码", "手动输入配对码", "PairScanActivity::class.java",
                  "AppDialogs.input", "BlePairingStore.parsePairingUri"):
        if label not in ble:
            errs.append(f"BleConnectPanel 缺 {label}（扫码入口/解析链不完整）")
    if "未配对，请扫码导入配对码" not in ble:
        errs.append("未配对提示仍是做不到的「扫描配对码」文案")

    # 4) 主壳可测性：四目的地 + 关键门禁硬串仍在
    main = d["main"]
    for label in ("状态", "健康", "设置", "终端", "实机状态帧"):
        if label not in main:
            errs.append(f"重构后丢门禁锚点 {label}")
    if "扫描附近 BLE 设备" not in ble:
        errs.append("重构后丢扫描按钮门禁锚点")
    # 动态生成的 contentDescription 不是裸字符串，绑完整表达式而非臆造四份副本。
    if not re.search(r'contentDescription\s*=\s*"标签页\$label"', main):
        errs.append("底部导航 contentDescription 表达式被改掉（真机门禁靠它定位）")
    if "MaterialToolbar" not in main:
        errs.append("MainActivity 未使用 MaterialToolbar（不是 M3 顶栏）")

    # 5) 设置页滑块危险阈值可视化（基准稿设置页 note：轨道右侧 70% 变红）。
    #    正向断言绑「分段 Drawable + 单一权威切点 + 被进度层引用」，不靠截图观感。
    th = d["threshold"]
    if not re.search(r"class\s+ThresholdTrackDrawable", th):
        errs.append("缺 ThresholdTrackDrawable 分段轨道类（基准稿阈值可视化未落地）")
    if "DANGER_FROM" not in th or not re.search(r"DANGER_FROM\s*=\s*0\.7f", th):
        errs.append("缺 DANGER_FROM=0.7f 单一权威切点（与基准稿 70% 不一致）")
    # 必须真的按 bounds 比例画两段（切点用 dangerFrom 参与计算），不能只是个空壳类。
    if "w * dangerFrom" not in th and "width * dangerFrom" not in th:
        errs.append("ThresholdTrackDrawable 未按比例计算切点（两段着色是假实现）")
    if "clipPath" not in th:
        errs.append("ThresholdTrackDrawable 缺胶囊裁剪（两段圆角接缝会凹陷）")
    # MainActivity 必须把分段轨道接到 SeekBar 的背景层，且用低透明警示色。
    if "ThresholdTrackDrawable(" not in main:
        errs.append("MainActivity 未把阈值分段轨道接到设置滑块")
    if not re.search(r"ThresholdTrackDrawable\.dangerTint\(", main):
        errs.append("警示色未走 dangerTint 低透明封装（会盖过进度 fill）")

    return errs


# 负对照试验单一权威：meta_negative_control 跑它，main 计数也读它，避免写死数量。
TRIALS: tuple[tuple[str, str, str, str], ...] = (
    ("弹窗退回平台默认", "main", "AppDialogs.confirm", "AlertDialog.Builder"),
    ("删扫码入口按钮", "ble", "扫码导入配对码", "配对码"),
    ("删手动兜底", "ble", "AppDialogs.input", "AppDialogs.manualMissing"),
    ("扫码改成全格式", "scan", "Barcode.FORMAT_QR_CODE", "Barcode.FORMAT_ALL_FORMATS"),
    ("删相机权限", "manifest", "android.permission.CAMERA", "android.permission.CAMERA_REMOVED"),
    ("删 MLKit Analyzer", "gradle", "androidx.camera:camera-mlkit-vision", "androidx.camera:camera-unused"),
    ("顶栏退回普通 View", "main", "MaterialToolbar", "PlainToolbar"),
    ("阈值切点改成 0.9", "threshold", "DANGER_FROM = 0.7f", "DANGER_FROM = 0.9f"),
    ("阈值轨道不改比例", "threshold", "w * dangerFrom", "w * 0.5f"),
    ("阈值轨道不接进滑块", "main", "ThresholdTrackDrawable(", "SingleColorTrackDrawable("),
    ("警示色不走低透明封装", "main", "ThresholdTrackDrawable.dangerTint(", "ThresholdTrackDrawable.solidTint("),
    ("阈值轨道去掉胶囊裁剪", "threshold", "canvas.clipPath(capsule)", "canvas.clipRect(b)"),
)


def meta_negative_control() -> list[str]:
    """每个改坏试验都必须让 check() 变红，否则这个门禁是假绿。"""
    errs: list[str] = []
    base = load()
    if check(base):
        errs.append("前置失败：正常源码下门禁就不绿")
        return errs
    for label, key, old, new in TRIALS:
        patched = dict(base)
        patched[key] = patched[key].replace(old, new)
        if not check(patched):
            errs.append(f"负对照失效：{label} 后仍绿")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="注入式负对照自检")
    args = ap.parse_args()
    if args.selftest:
        errs = meta_negative_control()
        n = 1 + len(TRIALS)
        ok = n - len(errs)
        print(f"SELFTEST: {ok}/{n} passed")
        for e in errs:
            print("  META_FAIL:", e)
        print(f"RESULT: {ok} passed, {len(errs)} failed")
        return 1 if errs else 0
    try:
        errs = check(load())
    except FileNotFoundError as e:
        print(f"PRECONDITION_FAIL: {e}")
        return 2
    if errs:
        print("VERDICT: NOT_PASS")
        for e in errs:
            print("  ERR:", e)
        print(f"RESULT: 0 passed, {len(errs)} failed")
        return 1
    print("VERDICT: OK — M3 弹窗/扫码入口/主壳结构通过（非真机签收）")
    print("RESULT: 0 errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
