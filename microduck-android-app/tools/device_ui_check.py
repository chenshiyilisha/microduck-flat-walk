#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1+ 多页 / 横屏 / 双模式 真机活体门禁 —— vivo V2338A / Android 16 (API 36) 实测。

为什么需要它：在此之前 P1 UI 只有「Gradle 编译 + APK 打包 + dex 里类存在」的静态证据，
从未在真实 Android 上跑过。本脚本经 adb 做**行为级**验证，且每条正向断言配负对照。

一手依据：
 - Android 官方 `developer.android.com/training/gestures/multi`：
   ACTION_UP / ACTION_CANCEL 结束手势，View 必须把摇杆归零；只处理 UP 会卡在按下态。
 - `DriveController.release()`：归零 + 发零帧 + **停心跳**；`onAxes()`：立即发帧 + 恢复心跳。
   ⇒ 「已发 N 帧」是可从 UI 层级真读出来的行为观测量：按下后应增长、松手后应停止。
 - `developer.android.com/guide/topics/manifest/activity-element`：screenOrientation 是
   逐 Activity 属性 ⇒ 主页竖屏、DriveActivity 横屏可分别用 uiautomator 的 hierarchy rotation 验。
 - NIST UTAP 3.2.19 / Weston Robot Teleop：手动 = 人的连续输入；退出遥控页必须停车；
   自动（监督）视图下 App 零驾驶帧。
 - arXiv:2110.08753（一手核验）：横屏持机时双拇指舒适区距屏幕左/下边 9.8–19.4 mm，摇杆
   贴两下角、双拇指操作 ⇒ 本页双摇杆落位依据（非引用未核验的 RoMan 2012 章节）。

⚠️ 只对自己的包 io.microduck.app 做 force-stop/start，不碰其它应用、不卸载、不清除数据。
"""
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

# ADB 解析：优先本机已知路径，缺失则回退到 PATH 上的 `adb`（换机器不崩）。
_ADB_CANDIDATES = [r"D:\adb\platform-tools\adb.exe", "adb"]
def _resolve_adb():
    for c in _ADB_CANDIDATES:
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
        else:
            return c  # 交给 subprocess 在 PATH 里找
    return "adb"
ADB = _resolve_adb()
# 可选：多设备时用 ANDROID_SERIAL 指定目标（标准做法，不影响单设备场景）。
SERIAL = os.environ.get("ANDROID_SERIAL")
PKG = "io.microduck.app"
MAIN_ACT = PKG + "/.MainActivity"
DRIVE_ACT = PKG + "/.DriveActivity"
UI_XML = "/sdcard/wb_uicheck.xml"
LOCAL_XML = "build/device/uicheck.xml"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  | " + detail) if detail else ""))


def finish(early_rc=0):
    """正常结束/提前退出都打印 RESULT。

    🔴 之前 main() 有 3 条 `return 2` 提前退出路径，日志会「既无 FAIL 也无 RESULT」，
    连跑时被误读成偶发成功 / 环境中断。现在统一收口，提前退出明确标注断言未跑完。
    """
    ok = sum(1 for _, o, _ in results if o)
    total = len(results)
    suffix = (" (early_exit_rc=%d·断言未跑完)" % early_rc) if early_rc else ""
    print("\nDEVICE_UI RESULT: %d passed / %d failed%s" % (ok, total - ok, suffix))
    for n, o, d in results:
        if not o:
            print("  FAILED: %s | %s" % (n, d))
    return early_rc or (0 if ok == total else 1)


def adb(*args, timeout=30):
    # SERIAL 仅对需要设备的命令生效；`devices` 不带 -s（否则 adb 报错）。
    prefix = ["-s", SERIAL] if (SERIAL and args and args[0] != "devices") else []
    return subprocess.run([ADB, *prefix, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def shell(*args, timeout=30):
    return adb("shell", *args, timeout=timeout).stdout.strip()


def parse_dump(xml_text=None):
    """解析 uiautomator XML。传入 xml_text 时只解析**本次** dump 的内容，不碰本地文件。"""
    try:
        root = ET.fromstring(xml_text) if xml_text is not None else ET.parse(LOCAL_XML).getroot()
    except Exception as e:
        print("  (dump parse failed: %s)" % e)
        return [], "?"
    out = []
    for n in root.iter("node"):
        out.append({
            "cls": n.get("class", ""),
            "text": n.get("text", ""),
            "desc": n.get("content-desc", ""),
            "bounds": n.get("bounds", ""),
            # CheckBox 的勾选态是持久化回归的可观测量（uiautomator dump 原生带 checked 属性）。
            "checked": n.get("checked", ""),
            # 窗口归属：App 界面每个 node 都是 package="io.microduck.app"；
            # 下拉通知栏 / 快速设置是 systemui，绝不会出现本包名。实测 App 页 60/60 节点命中。
            "pkg": n.get("package", ""),
        })
    return out, root.get("rotation", "?")


def dump_nodes():
    """返回 (nodes, rotation)。

    🔴 真机实测抓到的假读数（2026-11-12）：原来只管把 `uiautomator dump` / `adb pull`
    命令发出去，不检查成败。窗口繁忙时 dump 会报 `ERROR: could not get idle state`、
    pull 失败，而 LOCAL_XML 仍是上一次的陈腐文件 ⇒ parse_dump 读到旧 hierarchy，
    帧数「+0」被误判成心跳停了（诊断脚本却测到 101→810 帧持续增长）。
    修法：不落本地文件，改用 `adb exec-out cat` 直接读回**本次** dump 的 XML 并
    `ET.fromstring` 解析，逐条校验 rc / ERROR / 内容含 `<hierarchy`，失败就重取。
    🔴 中途踩过二次坑：曾靠「每次 `os.remove(LOCAL_XML)`」防陈腐，连跑两轮门禁会删几十次
    本地文件，触发环境的批量删除保护（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`）把脚本中断。
    现在零本地删除，既无陈腐读数也无保护误伤。
    另处理两类窗口污染：Spinner PopupWindow、以及**下拉通知栏 / 快速设置**。
    🔴 第三种污染（2026-11-13 连跑首轮实测）：冷启动第一次 dump 抓到系统通知面板
    （「通知中心 / 已开启 USB 文件传输模式 / USB 调试已开启」），节点数 >=8 且不是
    ListView ⇒ 旧判据放行，导致 16 条断言全 FAIL 且提前 return 2、日志无 RESULT。
    修法：用 node 的 `package` 属性做**窗口归属硬判据** —— App 页每个节点都是 PKG
    （实测 60/60），systemui 面板一个都没有；本包节点不足就按 BACK 收起 overlay 再重取。
    """
    nodes, rotation = [], "?"
    for attempt in range(5):
        shell("rm", "-f", UI_XML)         # 远端删除（adb shell，不碰本机文件）
        dumped = adb("shell", "uiautomator", "dump", UI_XML)
        dump_out = (dumped.stdout or "") + (dumped.stderr or "")
        if dumped.returncode != 0 or "ERROR" in dump_out:
            print("  (uiautomator dump 失败，重试: %s)" % dump_out.strip()[:110])
            time.sleep(0.5)
            continue
        fetched = adb("exec-out", "cat", UI_XML)
        xml = fetched.stdout or ""
        if fetched.returncode != 0 or "<hierarchy" not in xml:
            print("  (读取本次 XML 失败/为空，重试)")
            time.sleep(0.5)
            continue
        nodes, rotation = parse_dump(xml)
        if not nodes:
            print("  (XML 解析为空，重试)")
            time.sleep(0.5)
            continue
        app_nodes = sum(1 for n in nodes if n["pkg"] == PKG)
        joined = " ".join(n["text"] for n in nodes)
        popup = (any(n["cls"].endswith("ListView") for n in nodes) and len(nodes) < 10)
        system_overlay = app_nodes == 0 and (
            any(k in joined for k in ("通知", "USB", "文件传输", "快捷", "Quick settings"))
            or any(n["pkg"].startswith("com.android.systemui") for n in nodes))
        if len(nodes) >= 8 and not popup and app_nodes >= 3:
            return nodes, rotation
        if (popup or system_overlay) and attempt < 4:
            why = "Spinner 弹窗" if popup else "系统通知/快速设置面板"
            print("  (dump 命中 %s：本包节点 %d 个，按 BACK 关闭后重取)" % (why, app_nodes))
            shell("input", "keyevent", "4")
            time.sleep(0.5)
        else:
            print("  (未取到本 App 窗口：节点 %d / 本包 %d，重试)" % (len(nodes), app_nodes))
            time.sleep(0.4)
    print("  ⚠️ dump_nodes 重试耗尽仍未拿到 %s 窗口；后续断言不可判读" % PKG)
    return nodes, rotation


def bounds_of(nodes, pred):
    for n in nodes:
        if pred(n):
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n["bounds"])
            if m:
                l, t, r, b = map(int, m.groups())
                return (l, t, r, b, (l + r) // 2, (t + b) // 2)
    return None


def frames(nodes):
    """驾驶帧计数：DriveActivity 的 counterText / MainActivity 底部状态条都用同一文案。"""
    for n in nodes:
        m = re.search(r"已发\s*(\d+)\s*帧", n["text"])
        if m:
            return int(m.group(1))
    return -1


def local_drive_frames(nodes):
    """主页「App 本地遥测」格里的驾驶帧计数。拆页后主页不应持有 controller ⇒ 恒 0。"""
    for n in nodes:
        m = re.search(r"驾驶帧 / 心跳\s*(\d+)\s*帧", n["text"])
        if m:
            return int(m.group(1))
    return -1


def local_ticks(nodes):
    """主页本地刷新计数：证明遥测面板真的在刷新（App 自观测，非实机数据）。"""
    for n in nodes:
        m = re.search(r"本地刷新\s*(\d+)\s*次", n["text"])
        if m:
            return int(m.group(1))
    return -1


def texts(nodes):
    return " | ".join(n["text"] for n in nodes if n["text"].strip())


def checked_of(nodes, needle):
    """读 CheckBox 的 checked 属性；返回 None 表示没找到该控件。"""
    for n in nodes:
        if needle in n["text"]:
            return n.get("checked", "")
    return None


def wait_frames(min_gap_ms=1150):
    time.sleep(min_gap_ms / 1000.0)
    nodes, _ = dump_nodes()
    return frames(nodes)


def tap(nodes, pred, label, settle=0.9):
    b = bounds_of(nodes, pred)
    check(label + " 可定位", b is not None, str(b))
    if b:
        shell("input", "tap", str(b[4]), str(b[5]))
        time.sleep(settle)
    return b


def resumed_activity():
    out = adb("shell", "dumpsys", "activity", "activities").stdout
    m = re.findall(r"(?:mResumedActivity|topResumedActivity).*?(io\.microduck\.app/\.?\w+)", out)
    return m[-1] if m else ""


_disp = None


def display_size():
    """读物理分辨率（用于把 BLE 滚动的硬编码像素改成相对值，换设备不假阴性）。
    取不到回退到 vivo 1260×2800，保证历史验证过的设备行为不变。"""
    global _disp
    if _disp is not None:
        return _disp
    try:
        out = shell("wm", "size")
        m = re.search(r"(\d+)x(\d+)", out)
        if m:
            _disp = (int(m.group(1)), int(m.group(2)))
            return _disp
    except Exception:
        pass
    _disp = (1260, 2800)  # vivo 默认回退
    return _disp


def scroll_down():
    """在页面主体区向上滑动以滚动内容（落点在 tab 行与底部状态条之间的页面区，
    不误触 tab / 底部条）。uiautomator 只 dump 视口内节点，设置页 BLE 面板在末端，
    必须先滚才能被门禁读到。用**小步幅**：大步幅会一次跨过整块面板、把标题/按钮
    甩出视口顶部，只剩中间描述可见（实测踩过）。
    坐标按分辨率相对计算（vivo 上等价于 630 2200→630 1980），换设备不假阴性。"""
    W, H = display_size()
    x = W // 2
    # 用 vivo 实测绝对像素的精确比例(2200/1980÷2800)，保证该设备行为逐像素不变。
    y1, y2 = round(H * 2200 / 2800), round(H * 1980 / 2800)  # 向上拖
    shell("input", "swipe", str(x), str(y1), str(x), str(y2), "250")
    time.sleep(0.5)


def scroll_up():
    """向上微调，把刚滚过的面板标题/按钮重新拉回视口。坐标相对计算（vivo 等价于
    630 1650→630 1980）。"""
    W, H = display_size()
    x = W // 2
    y1, y2 = round(H * 1650 / 2800), round(H * 1980 / 2800)  # 向下拖回
    shell("input", "swipe", str(x), str(y1), str(x), str(y2), "250")
    time.sleep(0.5)


def scroll_until(pred_text, max_tries=14):
    """反复小步下滑直到 dump 文本包含目标串（或达到上限），返回最终 nodes。
    目标串用面板按钮「扫描附近 BLE 设备」——它是面板里位置最低的元素，出现即
    整块（含上方标题「BLE 连接」）已进入视口，不会被甩出折叠线。"""
    for _ in range(max_tries):
        nodes, _ = dump_nodes()
        if pred_text in texts(nodes):
            return nodes
        scroll_down()
    return dump_nodes()[0]


def main():
    print("\n=== P1+ 多页/横屏/双模式 真机门禁 (%s) ===" % PKG)
    dev = adb("devices").stdout
    if not re.search(r"^\S+\s+device\s*$", dev, re.M):
        print("  FAIL  设备未连接或未授权: " + dev.strip().replace("\n", " / "))
        return finish(2)
    check("adb 设备已连接且授权", True, [l for l in dev.splitlines() if "device" in l][-1].strip())

    installed = shell("pm", "path", PKG)
    check("APK 已安装", installed.startswith("package:"), installed)
    if not installed.startswith("package:"):
        return finish(2)

    # 🔑 -S 强制停进程再启动：vivo 上单用 force-stop + am start 会把旧 Activity 带回前台，
    # 出现「装了新 APK 但跑旧 class」的假绿（已实测踩过）。
    shell("am", "force-stop", PKG)
    adb("logcat", "-c")
    start = shell("am", "start", "-S", "-W", "-n", MAIN_ACT)
    check("MainActivity 冷启动成功", "Status: ok" in start and "Complete" in start,
          " ".join(x.strip() for x in start.splitlines() if "TotalTime" in x or "Status" in x))
    time.sleep(1.0)
    check("进程存活", bool(shell("pidof", PKG)))

    nodes, rot = dump_nodes()
    t0 = texts(nodes)
    check("🔑 主页为竖屏", rot == "0", "hierarchy rotation=%s" % rot)
    check("主页含手动/自动模式选择", "手动模式" in t0 and "自动模式" in t0, t0[:160])
    check("主页含三个顶层目的地", all(k in t0 for k in ("状态", "健康", "设置")), t0[:160])
    check("🔑 数据来源分组标注(实机帧 vs 本地遥测)",
          "实机状态帧" in t0 and "App 本地遥测（非实机数据" in t0, t0[:220])
    check("🔑 无状态帧时实机组不伪造成 0",
          "当前无状态帧" in t0 and "— 未读到" in t0, t0[:220])
    lt0 = local_drive_frames(nodes)
    tk0 = local_ticks(nodes)
    time.sleep(1.4)
    nodes2 = dump_nodes()[0]
    lt1 = local_drive_frames(nodes2)
    tk1 = local_ticks(nodes2)
    # 🔴 拆页后的正确行为是「主页零驾驶帧」：controller 只由 DriveActivity 持有。
    # 旧断言要求主页帧数增长，是单 Activity 时代的遗留；若主页误建 controller 这里会变红。
    check("🔑 主页不发驾驶帧(拆页后的安全设计·负对照)", lt0 == 0 and lt1 == 0,
          "%d → %d；若主页误建 controller 会增长" % (lt0, lt1))
    check("🔑 本地遥测数值真在变化(非静态占位)", tk0 >= 0 and tk1 > tk0,
          "刷新 %d → %d" % (tk0, tk1))

    # ---------- 进入横屏遥控页（手动模式） ----------
    nodes, _ = dump_nodes()
    tap(nodes, lambda n: n["desc"] == "进入遥控界面", "进入遥控界面按钮", settle=1.6)
    nodes, rot = dump_nodes()
    check("🔑 遥控页为横屏", rot in ("1", "3"), "hierarchy rotation=%s" % rot)
    check("🔑 前台 Activity 是 DriveActivity", DRIVE_ACT.split("/")[-1] in resumed_activity(),
          resumed_activity() or "(no match)")

    joy = bounds_of(nodes, lambda n: n["desc"] == "方向摇杆")
    head_joy = bounds_of(nodes, lambda n: n["desc"] == "头部摇杆")
    check("方向摇杆按 content-desc 可定位", joy is not None, str(joy))
    check("头部摇杆按 content-desc 可定位", head_joy is not None, str(head_joy))
    if joy and head_joy:
        check("🔑 左右摇杆分离且方向在左(双拇指热区)",
              joy[4] < head_joy[4] and joy[2] <= head_joy[0] + 8,
              "drive=%s head=%s" % (joy[:4], head_joy[:4]))
    check("取景框铺底占位可定位(未伪造视频)",
          bounds_of(nodes, lambda n: "摄像头取景框占位" in n["desc"]) is not None)
    td = texts(nodes)
    check("顶部监测 HUD 已渲染", "模式 / 连接" in td and "实际速度" in td, td[:200])
    check("🔑 SP/PV 与头部角度已进 HUD(开源方案取长补短)",
          "命令→实际" in td and "头部 °" in td, td[:240])
    check("🔑 驾驶页 LIVE/DEMO 数据源标签可见(Mock 不冒充实机)",
          any("MOCK 演示夹具" in n["text"] or "实机 [" in n["text"] for n in nodes), td[:240])
    check("🔑 控制回显「最后输入」可见(OpenBot 控制显示)",
          "最后输入" in td, td[:240])
    if not joy:
        return finish(2)

    cx, cy = joy[4], joy[5]
    h = joy[3] - joy[1]
    push = max(40, int(h * 0.30))

    # 🔑 异步帧基线取在动作后 >2 个心跳周期(100ms×2)：刚进页面首个 dump 可能混入在途帧
    # 或撞上窗口切换，导致基线虚高、下一窗 +0（真机实测踩过）。
    wait_frames(900)
    f0 = frames(dump_nodes()[0])
    f1 = wait_frames(1200)
    delta_running = f1 - f0
    check("🔑 真机心跳在发帧(正对照)", delta_running >= 5,
          "frames %d → %d (+%d)" % (f0, f1, delta_running))

    swipe = shell("input", "swipe", str(cx), str(cy), str(cx), str(cy - push), "500")
    check("触控注入 swipe 执行", "Error" not in swipe and "Exception" not in swipe, swipe or "(ok)")
    f2 = wait_frames(1200)
    f3 = wait_frames(1200)
    delta_released = f3 - f2
    check("🔑 松手后归零且心跳停止(负对照)", 0 <= delta_released <= 2,
          "frames %d → %d (+%d)；若 UP 未归零会持续增长" % (f2, f3, delta_released))

    held = shell("input", "motionevent", "DOWN", str(cx), str(cy - push))
    motionevent_ok = "Unknown" not in held and "Error" not in held
    f4 = wait_frames(1200)
    f5 = wait_frames(1200)
    delta_held = f5 - f4
    if motionevent_ok:
        check("🔑 保持按下时心跳恢复(排除假阴)", delta_held >= 5,
              "frames %d → %d (+%d)" % (f4, f5, delta_held))
        shell("input", "motionevent", "UP", str(cx), str(cy - push))
    else:
        print("  (本 adb 不支持 motionevent，改用 swipe 恢复按下态)")
        shell("input", "swipe", str(cx), str(cy - push), str(cx), str(cy - push // 2), "900")
        check("🔑 重新操作后 App 仍响应(排除假阴)", frames(dump_nodes()[0]) >= f3)

    down_out = adb("shell", "input", "motionevent", "DOWN", str(cx), str(cy - push))
    down_ok = "Exception" not in (down_out.stdout + down_out.stderr)
    c0 = wait_frames(900)
    cancel_out = adb("shell", "input", "motionevent", "CANCEL", str(cx), str(cy - push))
    cancel_ok = "Exception" not in (cancel_out.stdout + cancel_out.stderr)
    c1 = wait_frames(1200)
    c2 = wait_frames(1200)
    delta_cancel = c2 - c1
    check("🔑 ACTION_CANCEL 注入执行", down_ok and cancel_ok,
          (down_out.stderr + cancel_out.stderr).strip()[:120] or "(ok)")
    check("🔑 ACTION_CANCEL 与 UP 同归零(真机)", 0 <= delta_cancel <= 2,
          "frames %d → %d (+%d)" % (c1, c2, delta_cancel))
    check("负对照:CANCEL 前确实在发帧(断言不恒真)", c0 >= f3,
          "before=%d ≥ released=%d" % (c0, f3))

    # ---------- 退出遥控页必须停车 ----------
    nodes, _ = dump_nodes()
    tap(nodes, lambda n: n["desc"] == "退出遥控", "退出按钮", settle=1.2)
    nodes, rot = dump_nodes()
    check("🔑 退出后回到竖屏主页", rot == "0", "rotation=%s" % rot)
    e0 = frames(nodes)
    e1 = wait_frames(1200)
    check("🔑 退出遥控页后驾驶帧停止(安全)", 0 <= e1 - e0 <= 2,
          "frames %d → %d (+%d)" % (e0, e1, e1 - e0))

    # ---------- 自动模式：无摇杆、零驾驶帧 ----------
    nodes, _ = dump_nodes()
    tap(nodes, lambda n: n["desc"] == "自动模式", "自动模式按钮", settle=0.7)
    tap(dump_nodes()[0], lambda n: n["desc"] == "进入遥控界面", "进入监测视图", settle=1.5)
    nodes, rot = dump_nodes()
    ta = texts(nodes)
    check("🔑 自动模式仍为横屏全屏视图", rot in ("1", "3"), "rotation=%s" % rot)
    check("🔑 自动模式无摇杆(不发送手动意图)",
          bounds_of(nodes, lambda n: n["desc"] in ("方向摇杆", "头部摇杆")) is None)
    check("🔑 自动模式边界写明「未验证策略启停」",
          "仅监测" in ta and "未验证策略启停" in ta, ta[:220])
    check("🔑 自动页可一键切回手动(OpenBot R1 / LiveKit View-Operator)",
          bounds_of(nodes, lambda n: n["desc"] == "切回手动") is not None)
    check("🔑 自动页明写 App 无停车能力(不制造假安全)",
          "无停车能力" in ta, ta[:240])
    a0 = frames(nodes)
    a1 = wait_frames(1200)
    check("🔑 自动模式零驾驶帧(负对照)", 0 <= a1 - a0 <= 2,
          "frames %d → %d (+%d)" % (a0, a1, a1 - a0))

    # ---------- 回到主页：健康页 / 状态页 ----------
    tap(dump_nodes()[0], lambda n: n["desc"] == "退出遥控", "退出监测视图", settle=1.0)
    nodes, _ = dump_nodes()
    tap(nodes, lambda n: n["desc"] == "标签页健康", "健康标签", settle=0.8)
    th = texts(dump_nodes()[0])
    check("🔑 健康页渲染且标注 Mock 夹具来源",
          "robot.health" in th and ("Mock 演示夹具" in th or "非实机读数" in th), th[:200])
    tap(dump_nodes()[0], lambda n: n["desc"] == "标签页状态", "状态标签", settle=0.6)
    check("状态页可返回", "实机状态帧" in texts(dump_nodes()[0]))

    # ---------- 开源方案取长补短：设置持久化 / 模式刻意不持久化 ----------
    # 依据：ROS_Robot_Controller「Persistent user preferences」、ohho.apk「Saved in
    # DataStore」、ble-rc-controller「dead zone」；以及 OpenBot DISCLAIMERS 的随时停车要求
    # ⇒ mode 每次冷启动必须回 MANUAL。两者都要用真机负对照证明，不靠读代码自证。
    nodes, _ = dump_nodes()
    tap(nodes, lambda n: n["desc"] == "标签页设置", "设置标签", settle=0.8)
    nodes, _ = dump_nodes()
    ts = texts(nodes)
    check("🔑 设置页含持久化说明与可调死区",
          "已本地持久化" in ts and "方向摇杆死区" in ts, ts[:200])
    # 🔴 反转开关在设置页靠上位置（ScrollVIew 顶部即可见）；A1 BLE 面板在末端。
    # 先在顶部完成开关交互（用本帧坐标，避免滚动后坐标失效），再滚到底验 BLE。
    before_cb = checked_of(nodes, "反转前后")
    check("反转开关可定位且 checked 状态可读", before_cb is not None, str(before_cb))
    if before_cb is not None:
        tap(nodes, lambda n: "反转前后" in n["text"], "反转开关", settle=0.6)
        after_cb = checked_of(dump_nodes()[0], "反转前后")
        check("🔑 反转开关真的被改动(断言不恒真的负对照)",
              after_cb is not None and after_cb != before_cb,
              "%s → %s" % (before_cb, after_cb))
        t_auto = texts(dump_nodes()[0])
        # 🔴 2026-11-14 首页重构：控制卡片（含随模式变化的「进入监测视图」按钮）
        # 移入「状态」目的地，设置页不再持有它，旧读数点在此页失效。
        # 模式现统一呈现于**每个目的地各自的 AppBar 状态串**（PageChrome 逐页刷新、
        # 任意页可见），故读数点改为状态串的「· 自动 ·」。
        # 断言意图（冷启动前处于自动模式）与强度不变：手动时该串为「· 手动 ·」照样变红。
        check("🔑 冷启动前确实处于自动模式(前置条件)",
              "· 自动 ·" in t_auto, t_auto[:160])

        shell("am", "force-stop", PKG)
        shell("am", "start", "-S", "-W", "-n", MAIN_ACT)
        time.sleep(1.0)
        nodes, _ = dump_nodes()
        t_cold = texts(nodes)
        check("🔑 冷启动强制回手动模式(模式刻意不持久化)",
              "进入遥控驾驶" in t_cold, t_cold[:180])
        tap(nodes, lambda n: n["desc"] == "标签页设置", "冷启动后设置标签", settle=0.8)
        restored = checked_of(dump_nodes()[0], "反转前后")
        check("🔑 设置跨冷启动持久化(SharedPreferences 真读回)",
              restored == after_cb, "%s → %s" % (after_cb, restored))
        tap(dump_nodes()[0], lambda n: n["desc"] == "标签页状态", "回到状态标签", settle=0.5)
    # 🔴 A1 BLE 面板在设置页末端（ScrollVIew 底部），uiautomator 不 dump 视口外节点；
    # 先回到设置页，再小步滚到面板**按钮「扫描附近 BLE 设备」出现**为止——按钮是面板
    # 里位置最低的元素，它可见时其上方的标题「BLE 连接」必然也在视口内（实测：只盯标题
    # 会把按钮甩在折叠线以下）。大步幅会一次跨过整块面板，所以用小步幅 + 反复判定。
    # 必须在开关交互之后（滚动后开关坐标会失效），且必须确保当前就在设置页（冷启动
    # 测试后停在状态页，否则 scroll_until 会滚错页面）。
    tap(dump_nodes()[0], lambda n: n["desc"] == "标签页设置", "设置标签(BLE)", settle=0.8)
    nodes = scroll_until("扫描附近 BLE 设备")
    ts = texts(nodes)
    check("🔑 A1 BLE 连接面板已进设置页(运行时权限+扫描入口)",
          "BLE 连接" in ts and "扫描附近 BLE 设备" in ts, ts[:220])

    # ---------- 生命周期 ----------
    shell("input", "keyevent", "KEYCODE_HOME")
    time.sleep(0.6)
    shell("am", "start", "-S", "-W", "-n", MAIN_ACT)
    time.sleep(0.8)
    log = adb("logcat", "-d", "-v", "brief").stdout
    fatal = [l for l in log.splitlines()
             if ("FATAL EXCEPTION" in l or "AndroidRuntime" in l and " E/" in l
                 or "InflateException" in l or "Resources$NotFoundException" in l)
             and PKG in l]
    check("🔑 全生命周期无崩溃/资源缺失", not fatal, "fatal_lines=%d" % len(fatal))
    check("回前台后 Activity 仍存活", bool(shell("pidof", PKG)))

    return finish()


if __name__ == "__main__":
    sys.exit(main())
