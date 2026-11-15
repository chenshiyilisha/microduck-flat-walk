#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
debug-only AI 调试通道的**产物级隔离核验**（stdlib-only，可进 CI）。

为什么不能只做源码树检查：`check_ai_debug_channel.py` 证明的是「debug sourceSet 才有
Receiver 源码」，但 AGP manifest 合并、R8 shrink、变体 sourceSet 配置任一处被改坏，
都可能让 release APK 悄悄带上调试组件。源码绿 ≠ 产物绿。这里直接读**真实 APK**：
  ① binary AndroidManifest.xml 的 ResStringPool（结构化解析，不是裸字节扫子串）
  ② classes*.dex 里的类名 / Logcat TAG 引用（ASCII 计数）
把「debug 有、release 无」做成自动派生的 verdict，而不是一句口头结论。

🔴 历史读数坑（本文件就是为了修它）：临时核验脚本曾用
   h.get("AiDebugReceiver") + h.get(b"AiDebugReceiver".decode())
   把同一个 key 加两遍、漏算 UTF-16LE 项，于是打印 `xml_AiDebugReceiver=0`，
   与 aapt 明明列出的 receiver 直接矛盾 —— 错的永远是读数，不是算术。
   ⇒ 这里改为解析字符串池得到**字符串集合**，用集合包含 / 集合差做判据。

verdict 语义（别拿它当整机验收）：
    DEBUG_ONLY_ISOLATION_CONFIRMED = 只证明「发布包不含调试组件」这一件事
    ISOLATION_BROKEN               = 隔离被破坏，必须修
    UNVERIFIED_ARTIFACTS_ABSENT   = 本机没产物，如实不判 PASS
任何情况都不写 `PASS` / 不改 ship_verdict（项目铁律 COLLECTED != PASS）。

用法：
    python tools/check_apk_debug_isolation.py
    python tools/check_apk_debug_isolation.py --json
    python tools/check_apk_debug_isolation.py --selftest   # 注入式负对照
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
APK_DIR = BASE / "app/build/outputs/apk"

SCHEMA = 1
TARGET_FQCN = "io.microduck.app.AiDebugReceiver"
TARGET_REL = ".AiDebugReceiver"
TAG = "MicroDuckAiDebug"
RECEIVER_HINT = re.compile(r"Receiver$")

# binary AXML / dex 里可能出现的三种编码，分开记，别再混成同一个 key。
NEEDLES = {
    "class_ascii": TARGET_FQCN.split(".")[-1].encode("ascii"),  # AiDebugReceiver
    "fqcn_ascii": TARGET_FQCN.encode("ascii"),
    "tag_ascii": TAG.encode("ascii"),
}


# ---------------------------------------------------------------- AXML 字符串池

def _read_len8(buf: bytes, pos: int) -> tuple[int, int]:
    v = buf[pos]
    pos += 1
    if v & 0x80:
        v = ((v & 0x7F) << 8) | buf[pos]
        pos += 1
    return v, pos


def _read_len16(buf: bytes, pos: int) -> tuple[int, int]:
    v = struct.unpack_from("<H", buf, pos)[0]
    pos += 2
    if v & 0x8000:
        v = ((v & 0x7FFF) << 16) | struct.unpack_from("<H", buf, pos)[0]
        pos += 2
    return v, pos


def axml_string_pool(axml: bytes) -> set[str]:
    """解析 ResXMLTree 的 RES_STRING_POOL_TYPE，返回**完整字符串集合**。

    只认 chunk 头与字符串池，不猜 XML 节点树；用集合包含判组件是否存在，
    避免裸子串扫描被注释 / `_BROKEN` 之类字面量反噬。
    """
    if len(axml) < 8:
        return set()
    typ, header_size = struct.unpack_from("<HH", axml, 0)
    if typ != 0x0003:                       # RES_XML_TYPE
        return set()
    pos = header_size
    out: set[str] = set()
    while pos + 8 <= len(axml):
        ctype, cheader = struct.unpack_from("<HH", axml, pos)
        csize = struct.unpack_from("<I", axml, pos + 4)[0]
        if csize < 8 or pos + csize > len(axml):
            break
        if ctype == 0x0001:                 # RES_STRING_POOL_TYPE
            (string_count, _style_count, flags, strings_start, _styles_start) = \
                struct.unpack_from("<IIIII", axml, pos + 8)
            utf8 = bool(flags & 0x100)
            offsets = struct.unpack_from("<%dI" % string_count, axml, pos + cheader)
            data_base = pos + strings_start
            for off in offsets:
                p = data_base + off
                if p >= len(axml):
                    continue
                try:
                    if utf8:
                        _nchars, p = _read_len8(axml, p)
                        nbytes, p = _read_len8(axml, p)
                        s = axml[p:p + nbytes].decode("utf-8", "replace")
                    else:
                        nchars, p = _read_len16(axml, p)
                        s = axml[p:p + nchars * 2].decode("utf-16-le", "replace")
                except (IndexError, struct.error, UnicodeDecodeError):
                    continue
                out.add(s)
        if ctype == 0x0003:                 # 到 XML 节点区就不用再找池了
            break
        pos += csize
    return out


# ---------------------------------------------------------------- 产物读取

def read_artifact(apk: Path) -> dict | None:
    if not apk.is_file():
        return None
    strings: set[str] = set()
    dex_class_refs = 0
    dex_tag_refs = 0
    with zipfile.ZipFile(apk) as z:
        for name in z.namelist():
            data = z.read(name)
            if name == "AndroidManifest.xml":
                strings |= axml_string_pool(data)
            elif name.endswith(".dex"):
                dex_class_refs += data.count(NEEDLES["class_ascii"])
                dex_tag_refs += data.count(NEEDLES["tag_ascii"])
    return {
        "apk": str(apk),
        "size_bytes": apk.stat().st_size,
        "string_count": len(strings),
        "receiver_like": sorted(s for s in strings if RECEIVER_HINT.search(s)),
        "strings": strings,
        "dex_class_refs": dex_class_refs,
        "dex_tag_refs": dex_tag_refs,
    }


def collect() -> dict:
    d = read_artifact(APK_DIR / "debug/app-debug.apk")
    r = read_artifact(APK_DIR / "release/app-release.apk")
    present = d is not None and r is not None
    ds = d["strings"] if d else set()
    rs = r["strings"] if r else set()
    return {
        "schema": SCHEMA,
        "present": present,
        "debug_apk": d["apk"] if d else None,
        "release_apk": r["apk"] if r else None,
        "debug_strings": ds,
        "release_strings": rs,
        "debug_only_strings": sorted(s for s in (ds - rs) if RECEIVER_HINT.search(s)),
        "debug_manifest_receivers": (d or {}).get("receiver_like", []),
        "release_manifest_receivers": (r or {}).get("receiver_like", []),
        "debug_dex_class_refs": (d or {}).get("dex_class_refs", 0),
        "release_dex_class_refs": (r or {}).get("dex_class_refs", 0),
        "debug_dex_tag_refs": (d or {}).get("dex_tag_refs", 0),
        "release_dex_tag_refs": (r or {}).get("dex_tag_refs", 0),
    }


# ---------------------------------------------------------------- 自动派生判据

def evaluate(e: dict) -> tuple[str, list[str]]:
    """verdict 由证据派生，绝不手工翻字符串。"""
    if not e["present"]:
        return "UNVERIFIED_ARTIFACTS_ABSENT", [
            "debug / release APK 未同时存在（本机没跑 :app:assembleDebug + :app:assembleRelease）"
        ]
    errs: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errs.append(msg)

    ds, rs = e["debug_strings"], e["release_strings"]
    declared_d = TARGET_FQCN in ds or TARGET_REL in ds
    declared_r = TARGET_FQCN in rs or TARGET_REL in rs
    need(declared_d, f"debug manifest 字符串池里没有 {TARGET_FQCN}（调试组件没编进去）")
    need(not declared_r, f"release manifest 字符串池里出现了 {TARGET_FQCN}（隔离被破坏）")
    # 负对照锚：拼错的名字不算声明，防裸子串假绿。
    need(TARGET_FQCN + "_BROKEN" not in ds or declared_d,
         "字符串池判据疑似恒真（_BROKEN 被当成真组件）")
    need(TARGET_FQCN in (ds - rs) or TARGET_REL in (ds - rs),
         "debug/release 字符串池差集里没有调试组件（说明 release 也带了它）")
    need(e["debug_dex_class_refs"] > 0, "debug dex 里找不到 AiDebugReceiver 类引用")
    need(e["release_dex_class_refs"] == 0,
         f"release dex 里仍有 AiDebugReceiver 类引用 {e['release_dex_class_refs']} 处")
    need(e["release_dex_tag_refs"] == 0,
         f"release dex 里仍有 Logcat TAG {TAG} 引用 {e['release_dex_tag_refs']} 处")
    need(e["debug_dex_tag_refs"] > 0, "debug dex 里找不到 Logcat TAG（结构化输出链断了）")
    return ("ISOLATION_BROKEN" if errs else "DEBUG_ONLY_ISOLATION_CONFIRMED"), errs


# ---------------------------------------------------------------- 注入式负对照

def make_axml(strings: list[str], utf8: bool) -> bytes:
    """合成最小 ResXMLTree（只有字符串池），用于独立测解析层而不是只测判定层。"""
    flags = 0x100 if utf8 else 0
    encoded: list[bytes] = []
    for s in strings:
        if utf8:
            b = s.encode("utf-8")
            # 长度都 < 0x80，单字节 varint 即可；顺序 = charLen, byteLen, bytes, 0x00
            encoded.append(bytes([len(s), len(b)]) + b + b"\x00")
        else:
            b = s.encode("utf-16-le")
            encoded.append(struct.pack("<H", len(s)) + b + b"\x00\x00")
    offsets: list[int] = []
    data = b""
    for e in encoded:
        offsets.append(len(data))
        data += e
    while len(data) % 4:
        data += b"\x00"
    header_size = 28
    strings_start = header_size + 4 * len(offsets)
    chunk_size = strings_start + len(data)
    pool = struct.pack("<HHIIIIII", 0x0001, header_size, chunk_size,
                       len(offsets), 0, flags, strings_start, 0)
    pool += struct.pack("<%dI" % len(offsets), *offsets) + data
    # RES_XML_TYPE: type/headerSize/fileSize，随后就是 string pool chunk
    return struct.pack("<HHI", 0x0003, 8, 8 + len(pool)) + pool


def selftest(fixture: dict) -> list[tuple[str, bool]]:
    """改坏证据，判定必须变。只见过绿的判据不是证据。"""
    def variant(**kw) -> dict:
        return {**fixture, **kw}

    ds, rs = fixture["debug_strings"], fixture["release_strings"]
    parse_cases: list[tuple[str, bool]] = []
    for enc, use_utf8 in (("UTF-16", False), ("UTF-8", True)):
        pool = axml_string_pool(make_axml([TARGET_FQCN, "android.app.Application"], use_utf8))
        parse_cases.append((f"AXML {enc} 字符串池提取出完整组件名（非裸子串）",
                            TARGET_FQCN in pool))
        broken = axml_string_pool(make_axml([TARGET_FQCN + "_BROKEN"], use_utf8))
        parse_cases.append((f"负对照:AXML {enc} 池里只有拼错名不算声明",
                            TARGET_FQCN not in broken))
    cases = [
        ("debug 声明被删必红",
         variant(debug_strings=ds - {TARGET_FQCN, TARGET_REL})),
        ("release 混入组件必红",
         variant(release_strings=rs | {TARGET_FQCN})),
        ("release dex 残留类名必红",
         variant(release_dex_class_refs=1)),
        ("release dex 残留 TAG 必红",
         variant(release_dex_tag_refs=1)),
        ("debug dex 无类名必红",
         variant(debug_dex_class_refs=0)),
        ("产物缺失必须 UNVERIFIED 而非 PASS",
         variant(present=False)),
        ("负对照:_BROKEN 拼错名不能冒充声明",
         variant(debug_strings=(ds - {TARGET_FQCN, TARGET_REL})
                 | {TARGET_FQCN + "_BROKEN"})),
    ]
    out = list(parse_cases)
    for label, e in cases:
        verdict, _ = evaluate(e)
        if label.startswith("产物缺失"):
            out.append((label, verdict == "UNVERIFIED_ARTIFACTS_ABSENT"))
        else:
            out.append((label, verdict == "ISOLATION_BROKEN"))
    verdict, errs = evaluate(fixture)
    out.append(("正对照:未改动证据零错误",
                verdict == "DEBUG_ONLY_ISOLATION_CONFIRMED" and not errs))
    return out


def public_report(e: dict, verdict: str, errs: list[str]) -> dict:
    return {
        "schema": SCHEMA,
        "scope": "只核验 debug/release 产物是否隔离调试组件；不验证硬件、不作整机签收",
        "verdict": verdict,
        "evidence": "COLLECTED_ONLY_NOT_PASS",
        "errors": errs,
        "debug_apk": e["debug_apk"],
        "release_apk": e["release_apk"],
        "debug_manifest_receivers": e["debug_manifest_receivers"],
        "release_manifest_receivers": e["release_manifest_receivers"],
        "debug_only_receiver_strings": e["debug_only_strings"],
        "debug_dex_class_refs": e["debug_dex_class_refs"],
        "release_dex_class_refs": e["release_dex_class_refs"],
        "debug_dex_tag_refs": e["debug_dex_tag_refs"],
        "release_dex_tag_refs": e["release_dex_tag_refs"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="核验 release APK 不含 debug-only AI 调试组件")
    ap.add_argument("--selftest", action="store_true", help="跑注入式负对照")
    ap.add_argument("--json", action="store_true", help="只输出结构化 JSON")
    args = ap.parse_args()

    e = collect()
    verdict, errs = evaluate(e)
    report = public_report(e, verdict, errs)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if verdict == "DEBUG_ONLY_ISOLATION_CONFIRMED" else 1

    print(f"VERDICT: {verdict}   evidence={report['evidence']}")
    print(f"  debug  manifest receivers = {e['debug_manifest_receivers']}")
    print(f"  release manifest receivers = {e['release_manifest_receivers']}")
    print(f"  debug-only strings        = {e['debug_only_strings']}")
    print(f"  dex class refs  debug/release = {e['debug_dex_class_refs']}/"
          f"{e['release_dex_class_refs']}")
    print(f"  dex TAG refs    debug/release = {e['debug_dex_tag_refs']}/"
          f"{e['release_dex_tag_refs']}")
    for x in errs:
        print("  FAIL  " + x)

    rc = 0 if verdict == "DEBUG_ONLY_ISOLATION_CONFIRMED" else 1
    if args.selftest:
        # 自检用**合成证据**，不依赖本机是否编译过 APK；换机器也能跑。
        fixture = {
            "present": True,
            "debug_strings": {TARGET_FQCN, "android.app.Application"},
            "release_strings": {"android.app.Application"},
            "debug_dex_class_refs": 2,
            "release_dex_class_refs": 0,
            "debug_dex_tag_refs": 1,
            "release_dex_tag_refs": 0,
            "debug_only_strings": [],
            "debug_manifest_receivers": [],
            "release_manifest_receivers": [],
            "debug_apk": "<fixture>", "release_apk": "<fixture>",
        }
        print("\n=== 注入式负对照（合成证据，不依赖产物） ===")
        results = selftest(fixture)
        for label, ok in results:
            print(("  PASS  " if ok else "  FAIL  ") + label)
            if not ok:
                rc = 1
        print(f"SELFTEST: {sum(1 for _, ok in results if ok)}/{len(results)} passed")
    return rc


if __name__ == "__main__":
    sys.exit(main())
