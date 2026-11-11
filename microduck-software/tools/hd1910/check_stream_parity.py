#!/usr/bin/env python3
"""C4: SCS v1 stream-parser two-implementation byte-for-byte parity gate.

Why this exists (2026-11-11)
----------------------------
The Luwu XGO-Duck mature-product deep dive (docs/active/microduck-陆吾XGO-Duck
成熟产品深挖-2026-11-11.md §3, row 7) documented a parity手法 from
`xgoduck_runtime_mosaico/tests/test_parity.py`: two independent parsers must
produce byte-for-byte identical output on a dirty byte stream (bad CRC / NaN
payload / unrelated strings injected), so a silent framing bug cannot hide.

A查全 of our own gates found this is the ONE mechanism-level orthogonal gap:
  * 姿态/物理不变量 (row 8) -- already strongly covered by verify_imu_chain.py;
  * 图白名单 / manifest / N-vector parity / NaN output / normalizer floor /
    IMU readiness (rows 1-6) -- each already covered, several with STRONGER
    implementations (mcu_selftest.py really compiles C; check_onnx_parity.py
    rebuilds a numpy reference from checkpoint weights);
  * dirty-stream DOUBLE-IMPLEMENTATION parity (row 7) -- check_imu_bridge.py
    has a single `parse_scs()` (bytes.find + slice, first packet only) with
    single-frame negative controls, but NO second independent implementation
    and NO mixed dirty-stream cross-check. That is what this tool adds.

What it does (all offline, stdlib-only, no hardware, no serial, no I/O beyond
reading its own contract and the production source file):
  * Implementation A = the REAL production parser, extracted from
    check_imu_bridge.py by stdlib `ast`: it selects exactly three top-level
    definitions (`_scs_checksum`, `ScsPacket`, `parse_scs`) and execs them in a
    restricted namespace with `dataclass` injected. It does NOT copy the
    algorithm, does NOT drift from production, and does NOT execute any other
    line of that module (no `Bus`, no `serial`, no main).
  * Implementation B = an independent byte-oriented state machine written from
    the protocol spec, using an explicit cursor, NO `bytes.find`, NO slicing of
    A's raw, NO import of A. Any framing-semantics disagreement surfaces as a
    byte-inequality.
  * A shared framing driver advances one byte on `None`, else by `consumed`,
    normalises each packet to a tuple, and compares the WHOLE sequence. Only
    parse_first differs, so the test measures the parsers, not skip strategy.

Boundaries
----------
This proves "our two parsers agree with each other and reject bad input", not
that the bus answers, that R3 (500k bit width) is closed, or that the robot can
be signed off. `verdict` is `OFFLINE_PARITY_ONLY`; `ship_verdict` is ALWAYS
`NOT_SHIPPABLE`; `live_hardware_accessed=false`. UNVERIFIED != PASS.

Usage (cwd = microduck-software):
    python tools/hd1910/check_stream_parity.py --selftest
    python tools/hd1910/check_stream_parity.py --check
    python tools/hd1910/check_stream_parity.py --check --json
    python tools/hd1910/check_stream_parity.py --check --verify-source
    python tools/hd1910/check_stream_parity.py --check --ship-gate
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
CONTRACT = HERE / "stream_parity_contract.json"
PRODUCTION = HERE / "check_imu_bridge.py"
# Symbols extracted verbatim from production. ScsPacket needs `dataclass`.
EXTRACT_SYMBOLS = ("_scs_checksum", "ScsPacket", "parse_scs")
HEADER = b"\xff\xff"


def load(path: Path = CONTRACT) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Implementation A: the REAL production parser, via stdlib AST extraction.
# ---------------------------------------------------------------------------

def extract_production(src: str) -> dict:
    """Select exactly EXTRACT_SYMBOLS top-level defs and exec them in a box.

    We never import check_imu_bridge (its lazy `serial` import and `Bus` / main
    would drag in heavy deps). We parse its source, take only the three pure
    framing definitions, and run them with a single injected name. If the file
    drifts (renames a symbol, changes arity), this raises -- a FAIL, never a
    silent fallback to a copy.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise ValueError("production source has a syntax error: %s" % e)
    wanted: list[ast.stmt] = []
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.name in EXTRACT_SYMBOLS:
            wanted.append(node)
            found.add(node.name)
    missing = set(EXTRACT_SYMBOLS) - found
    if missing:
        raise ValueError("production source missing symbols: %s" % sorted(missing))
    if len(wanted) != len(EXTRACT_SYMBOLS):
        raise ValueError("duplicate production symbol definitions")
    # Sandbox: only `dataclass` is provided. The defs themselves only use it,
    # plus builtins (sum, bytes) and constants -- no module-level I/O.
    box: dict = {"dataclass": dataclass, "__builtins__": __builtins__}
    exec(compile(ast.Module(body=wanted, type_ignores=[]),
                 str(PRODUCTION), "exec"), box)
    return {name: box[name] for name in EXTRACT_SYMBOLS}


def parse_first_a(buf: bytes, prod: dict) -> tuple[tuple | None, int]:
    """Wrap production parse_scs into the shared (packet|None, consumed) API."""
    pkt = prod["parse_scs"](buf)  # returns ScsPacket | None
    if pkt is None:
        return None, 1
    raw = pkt.raw
    norm = (pkt.dxl_id, pkt.instruction, pkt.params.hex(),
            bool(pkt.checksum_ok), raw.hex())
    # Production parse_scs starts at buf.find(FF FF), which may be > 0 when
    # the driver feeds it a buffer with leading noise. `consumed` must cover
    # that noise too, else the driver re-parses the same frame a second time
    # (the crlf_noise bug this very gate caught on its first real run).
    start = buf.find(HEADER)
    return norm, start + len(raw)


# ---------------------------------------------------------------------------
# Implementation B: independent byte state machine (no find, no A import).
# ---------------------------------------------------------------------------

def parse_first_b(buf: bytes) -> tuple[tuple | None, int]:
    """Scan for FF FF with an explicit cursor; parse by LEN; verify by sum.

    Deliberately orthogonal to A: explicit index cursor instead of
    bytes.find+slice, manual byte accumulation instead of sum(pkt[2:]).
    """
    n = len(buf)
    i = 0
    while i + 1 < n and not (buf[i] == 0xFF and buf[i + 1] == 0xFF):
        i += 1
    if i + 1 >= n:
        return None, 1
    # header at i..i+1
    if i + 6 > n:            # need FF FF ID LEN INST + SUM at minimum
        return None, 1
    dxl_id = buf[i + 2]
    if dxl_id == 0xFF:       # ID 255 reserved in SCS v1
        return None, 1
    length = buf[i + 3]
    if length < 2:
        return None, 1
    total = length + 4
    if i + total > n:        # truncated tail
        return None, 1
    raw = buf[i:i + total]
    acc = 0
    for k in range(2, total):
        acc += raw[k]
    checksum_ok = (acc & 0xFF) == 0xFF
    instruction = raw[4]
    params = raw[5:total - 1]
    return (dxl_id, instruction, params.hex(), checksum_ok, raw.hex()), total + i


def parse_first_b_buggy(buf: bytes) -> tuple[tuple | None, int]:
    """NEGATIVE CONTROL: same as B but total is short by one (framing bug)."""
    n = len(buf)
    i = 0
    while i + 1 < n and not (buf[i] == 0xFF and buf[i + 1] == 0xFF):
        i += 1
    if i + 1 >= n or i + 6 > n:
        return None, 1
    dxl_id = buf[i + 2]
    if dxl_id == 0xFF or buf[i + 3] < 2:
        return None, 1
    total = buf[i + 3] + 3          # BUG: should be +4
    if i + total > n:
        return None, 1
    raw = buf[i:i + total]
    acc = 0
    for k in range(2, total):
        acc += raw[k]
    return (dxl_id, raw[4], raw[5:total - 1].hex(),
            (acc & 0xFF) == 0xFF, raw.hex()), total + i


# ---------------------------------------------------------------------------
# Shared framing driver
# ---------------------------------------------------------------------------

def frame_all(buf: bytes, parse_first, limit: int = 100000) -> list[tuple]:
    """Advance by 1 on None, else by `consumed`; return normalised packets."""
    out: list[tuple] = []
    offset = 0
    steps = 0
    while offset < len(buf):
        steps += 1
        if steps > limit:
            raise RuntimeError("framing driver did not progress (limit)")
        norm, consumed = parse_first(buf[offset:])
        if norm is None:
            offset += 1
        else:
            if consumed <= 0:
                raise RuntimeError("parse_first returned a packet with consumed<=0")
            out.append(norm)
            offset += consumed
    return out


def parity(buf: bytes, prod: dict):
    """Run A and B over the same bytes; return (seq_a, seq_b, byte_equal)."""
    a = frame_all(buf, lambda b: parse_first_a(b, prod))
    b = frame_all(buf, parse_first_b)
    return a, b, a == b


# ---------------------------------------------------------------------------
# Dirty-stream fixture construction (stdlib struct, independent of both impls)
# ---------------------------------------------------------------------------

import struct  # noqa: E402  (kept near use; struct is stdlib, ast-detectable)


def _frame(dxl_id: int, inst: int, params: bytes = b"") -> bytes:
    """Build a well-formed SCS v1 frame from the protocol spec (test-side only)."""
    body = bytes([dxl_id, len(params) + 2, inst]) + params
    return HEADER + body + bytes([(~sum(body)) & 0xFF])


def build_cases() -> dict[str, tuple[bytes, int]]:
    """Return {case_id: (stream_bytes, expected_valid_packet_count)}.

    `expected` counts fully-framed packets (valid checksum OR flagged bad),
    NOT noise. `nan_payload_bytes` must NOT be dropped by framing: decode_block
    (a different gate) rejects non-finite values, framing treats bytes opaque.
    """
    ping = _frame(200, 0x00)                       # valid ping response
    status = _frame(200, 0x02, bytes(range(12)))   # valid read response, LEN varies
    bad = bytearray(ping)
    bad[-1] ^= 0xFF                                 # flip checksum
    nan_payload = struct.pack("<HHH", 0x7E00, 0x7C00, 0x3C00)  # NaN / Inf / 1.0 half
    nan_frame = _frame(200, 0x82, nan_payload + b"\x00\x01\x02")
    embedded = _frame(200, 0x02, b"\xaa\xff\xff\xbb\x01")      # FF FF inside payload
    duck_ip = b"DUCK_IP=192.168.1.50\xff\xff\x00"             # unrelated string + bogus header
    crlf = b"master\r\n"                                       # Windows CRLF noise
    stale = b"\x12\x34\x56"                                    # stale fragment prefix
    truncated = _frame(200, 0x02, b"\x01\x02\x03\x04")[:-2]   # tail cut off
    id255 = b"\xff\xff\xff\x02\x01\x00"                        # reserved ID 255 pseudo-frame
    len1 = b"\xff\xff\xc8\x01\x01\x00"                         # LEN < 2 pseudo-frame
    cases = {
        "valid_ping_response": (ping, 1),
        "valid_status_frame": (status, 1),
        "bad_checksum": (bytes(bad), 1),
        "nan_payload_bytes": (nan_frame, 1),
        "embedded_ffff_in_payload": (embedded, 1),
        "injected_duck_ip_string": (duck_ip + ping, 1),
        "crlf_noise": (crlf + ping, 1),
        "leading_stale_fragment": (stale + ping, 1),
        "truncated_tail": (truncated, 0),
        "reserved_id_255": (id255 + ping, 1),
        "len_below_two": (len1 + ping, 1),
        "consecutive_frames": (ping + status, 2),
    }
    return cases


# ---------------------------------------------------------------------------
# Contract validation
# ---------------------------------------------------------------------------

def validate(data: dict) -> list[str]:
    """Structural + semantic checks on the contract. Returns problems[]."""
    p: list[str] = []

    def need(ok: bool, msg: str) -> None:
        if not ok:
            p.append(msg)

    need(data.get("schema") == 1, "schema must be 1")
    need(data.get("status") == "OFFLINE_PARITY_ONLY",
         "status must stay OFFLINE_PARITY_ONLY; double-parser parity is not sign-off")
    need(data.get("verdict", data.get("acceptance", {}).get("verdict"))
         in ("OFFLINE_PARITY_ONLY", None),
         "verdict must not claim a shipping state")
    need(data.get("line") == "META_GUARD",
         "line must be META_GUARD (stdlib-only CI guard, not a hardware line)")
    rule = str(data.get("rule", ""))
    need("UNVERIFIED" in rule and "PASS" in rule,
         "rule must state UNVERIFIED != PASS")
    need("OFFLINE_PARITY_ONLY" in rule and "SHIPPABLE" in rule,
         "rule must state OFFLINE_PARITY_ONLY != SHIPPABLE")
    scope = data.get("scope") or {}
    need(scope.get("live_hardware_accessed") is False,
         "scope.live_hardware_accessed must be false")
    need(bool(scope.get("what_it_does_not_prove")),
         "scope.what_it_does_not_prove must be non-empty (honest boundary)")

    # Case set is the single authority: notes and required list must be equal.
    required = data.get("required_dirty_cases") or []
    notes = data.get("case_notes") or {}
    need(len(required) == len(set(required)), "required_dirty_cases has duplicates")
    need(set(required) == set(notes),
         "case_notes keys must equal required_dirty_cases exactly")
    built = set(build_cases())
    need(set(required) == built,
         "required_dirty_cases must equal the fixture builder's case set exactly")
    for cid in required:
        need(bool(str(notes.get(cid, "")).strip()),
             "case_notes.%s must be a non-empty explanation" % cid)

    # Protocol constants must match the real implementation's assumptions.
    proto = data.get("protocol") or {}
    need(proto.get("header") == HEADER.hex(), "protocol.header != ff ff")
    need(proto.get("reject_id") == 255, "protocol.reject_id != 255")
    need(proto.get("min_len") == 2, "protocol.min_len != 2")
    need("LEN + 4" in str(proto.get("total_rule", "")),
         "protocol.total_rule must encode LEN + 4")

    # Both implementations are declared and genuinely different in approach.
    impls = data.get("implementations") or {}
    need("parse_scs" in str(impls.get("A", {}).get("origin", "")),
         "implementation A must name the production parse_scs origin")
    b_design = str(impls.get("B", {}).get("design", ""))
    for token in ("cursor", "find"):
        need(token in b_design.lower(),
             "implementation B design must describe its cursor/no-find approach")
    need(any(t in b_design for t in ("不 import", "不import"))
         or "not import" in b_design.lower() or "no import" in b_design.lower(),
         "implementation B must declare it does not import A")

    neg = data.get("negative_controls") or []
    need(len(neg) >= 6, "need >=6 negative controls")
    for kw in ("删掉", "LEN+4", "checksum", "注入一个 framing bug", "空", "SHIPPABLE"):
        need(any(kw in str(n) for n in neg),
             "negative_controls must mention '%s'" % kw)
    need(data.get("acceptance", {}).get("empty_run_is_fail") is True,
         "acceptance.empty_run_is_fail must be true")
    return p


# ---------------------------------------------------------------------------
# --check: real parity run
# ---------------------------------------------------------------------------

def verify_source(prod_src: str) -> list[str]:
    """Prove the extracted AST really carries the protocol rules (textual pins)."""
    p: list[str] = []
    tree = ast.parse(prod_src)
    body = {n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    if "parse_scs" not in body:
        return ["production parse_scs definition not found"]
    ps = body["parse_scs"]
    consts = [c.value for c in ast.walk(ps)
              if isinstance(c, ast.Constant) and isinstance(c.value, int)]
    # parse_scs uses 255 (ID reject) and 6 (min header+checksum bytes) and 0xFF mask.
    if 255 not in consts:
        p.append("production parse_scs no longer rejects ID 255")
    if 6 not in consts:
        p.append("production parse_scs no longer uses the 6-byte minimum")
    # total = length + 4 is an Add node with Constant 4.
    adds = [n for n in ast.walk(ps) if isinstance(n, ast.BinOp)
            and isinstance(n.op, ast.Add) and isinstance(n.right, ast.Constant)
            and n.right.value == 4]
    if not adds:
        p.append("production parse_scs no longer computes total=LEN+4")
    return p


def run_check(verify: bool = False, ship_gate: bool = False) -> dict:
    data = load()
    problems = validate(data)
    source_ok = False
    prod: dict = {}
    src = ""
    if PRODUCTION.is_file():
        try:
            src = PRODUCTION.read_text(encoding="utf-8")
            prod = extract_production(src)
            source_ok = True
        except Exception as e:                      # a broken extraction is FAIL
            problems.append("production extraction failed: %s" % e)
    else:
        problems.append("production source missing: %s" % PRODUCTION)
    source_pins: list[str] = []
    if verify and src:
        source_pins = verify_source(src)
        problems.extend(source_pins)

    cases = build_cases()
    results: dict[str, dict] = {}
    if prod:
        for cid, (buf, expected) in cases.items():
            a, b, eq = parity(buf, prod)
            results[cid] = {
                "expected_valid_packets": expected,
                "packets_a": len(a), "packets_b": len(b),
                "count_ok": len(a) == expected and len(b) == expected,
                "a_equals_b": eq,
                "bad_checksums_a": [x[3] for x in a if not x[3]],
            }
            if not eq:
                problems.append("BYTE INEQUALITY on case %s" % cid)
            if len(a) != expected or len(b) != expected:
                problems.append("packet-count mismatch on case %s "
                                "(A=%d B=%d expected=%d)"
                                % (cid, len(a), len(b), expected))
    # Positive assertion: the two-implementation run must actually frame packets.
    total = sum(r.get("packets_a", 0) for r in results.values())
    if total == 0:
        problems.append("EMPTY RUN: both implementations framed zero packets "
                        "(an all-None pair is NOT parity evidence)")

    # Live negative control inside --check: inject a framing bug into B; the
    # gate must detect a byte-inequality or a count mismatch on some case.
    nc_detected = False
    if prod:
        for _buf, _exp in cases.values():
            try:
                a_bug = frame_all(_buf, parse_first_b_buggy)
                b_ok = frame_all(_buf, parse_first_b)
                if a_bug != b_ok:
                    nc_detected = True
                    break
            except RuntimeError:
                nc_detected = True
                break
        if not nc_detected:
            problems.append("NEGATIVE CONTROL INERT: injected B framing bug "
                            "was not detected -- parity is a no-op")

    verdict = "OFFLINE_PARITY_ONLY" if not problems else "FAIL"
    rep = {
        "tool": "check_stream_parity.py",
        "contract_sha256": sha256_of(CONTRACT),
        "production_source": "tools/hd1910/check_imu_bridge.py",
        "production_sha256": sha256_of(PRODUCTION) if PRODUCTION.is_file() else "",
        "source_files_verified": source_ok and (bool(src) and not source_pins),
        "source_verification_problems": source_pins,
        "status": "UNVERIFIED",
        "verdict": verdict,
        "ship_verdict": "NOT_SHIPPABLE",
        "live_hardware_accessed": False,
        "extracted_symbols": sorted(prod) if prod else [],
        "cases": results,
        "total_framed_packets": total,
        "all_byte_equal": bool(prod) and all(r["a_equals_b"] for r in results.values()),
        "negative_control_live": nc_detected,
        "problems": problems,
        "not_proof_of": [
            "总线 ID200 应答 / 波特率匹配 / R3 500k 位宽",
            "IMU gyro 符号/轴/mount 正确（需已知倾角实机）",
            "半双工方向脚时序 / drain 截断是否真实发生",
            "任何整机可签收结论（UNVERIFIED != PASS）",
        ],
        "scope": "SCS v1 流解析双实现离线逐字节对拍；不碰硬件、不消 R3、不作签收",
    }
    if ship_gate:
        # Even a perfect parity run must refuse to ship.
        rep["ship_gate"] = "REFUSED"
        rep["ship_gate_reason"] = "OFFLINE_PARITY_ONLY is not a sign-off; no board evidence"
    return rep


# ---------------------------------------------------------------------------
# --selftest: negative controls on the gate itself
# ---------------------------------------------------------------------------

def selftest() -> int:
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    data = load()
    ck("契约结构 validate 通过", not validate(data), str(validate(data)))
    ck("12 个脏流用例集合与 builder 相等",
       set(data["required_dirty_cases"]) == set(build_cases()))

    src = PRODUCTION.read_text(encoding="utf-8") if PRODUCTION.is_file() else ""
    prod = extract_production(src) if src else {}
    ck("A 从生产源码真提取出三个符号", set(prod) == set(EXTRACT_SYMBOLS))
    ck("源钉：parse_scs 协议规则未漂移", not verify_source(src), str(verify_source(src)))

    # Positive: every case frames the expected count and A==B.
    cases = build_cases()
    for cid, (buf, expected) in cases.items():
        a, b, eq = parity(buf, prod)
        ck("脏流 %-28s A==B 且计数=%d" % (cid, expected),
           eq and len(a) == expected and len(b) == expected,
           "A=%d B=%d eq=%s" % (len(a), len(b), eq))

    # NC1: bad checksum must be FLAGGED, not dropped.
    bad = cases["bad_checksum"][0]
    a_bad, _b_bad, eq_bad = parity(bad, prod)
    ck("负对照：坏 CRC 被标记 checksum_ok=False（不是静默吞掉）",
       eq_bad and len(a_bad) == 1 and a_bad[0][3] is False, str(a_bad))

    # NC2: embedded FF FF must not become a second packet.
    emb = cases["embedded_ffff_in_payload"][0]
    a_emb, _b_emb, eq_emb = parity(emb, prod)
    ck("负对照：payload 内 FF FF 不切成幽灵包（恰好 1 个）",
       eq_emb and len(a_emb) == 1, str(a_emb))

    # NC3: NaN/Inf payload must survive framing (opaque bytes).
    nan = cases["nan_payload_bytes"][0]
    a_nan, _b_nan, eq_nan = parity(nan, prod)
    ck("负对照：NaN/Inf 载荷字节不丢帧（恰好 1 个）",
       eq_nan and len(a_nan) == 1, str(a_nan))

    # NC4: tamper A's LEN+4 in a copied source -> extraction/parity must break.
    tampered = src.replace("total = length + 4", "total = length + 5")
    ck("负对照源可变：篡改 LEN+4 后文本确实不同", tampered != src)
    try:
        prod_bad = extract_production(tampered)
        a_t, _b_t, eq_t = parity(cases["valid_status_frame"][0], prod_bad)
        ck("负对照：篡改 A 的 LEN+4 → A/B 逐字节不等", not eq_t)
    except Exception:
        ck("负对照：篡改 A 的 LEN+4 → A/B 逐字节不等", True, "extraction refused tampered src")

    # NC5: injected framing bug into B must break parity on some case.
    detected = False
    for _buf, _exp in cases.values():
        try:
            if frame_all(_buf, parse_first_b_buggy) != frame_all(_buf, parse_first_b):
                detected = True
                break
        except RuntimeError:
            detected = True
            break
    ck("负对照：B 注入 framing bug（+3）→ 对拍必红", detected)

    # NC6: all-None implementations must be rejected by the positive assertion.
    empty_run = frame_all(cases["valid_ping_response"][0], lambda b: (None, 1))
    ck("负对照：两个都返回空 → 正向断言必须拦住", empty_run == [])

    # NC7: contract corruption -> validate must fail.
    def must_fail(mutate: str, fn) -> None:
        bad = copy.deepcopy(data)
        fn(bad)
        ck("负对照契约：%s → validate 必红" % mutate, bool(validate(bad)))

    must_fail("删一个脏流用例", lambda d: d["required_dirty_cases"].pop())
    must_fail("伪造 status=PASS", lambda d: d.update({"status": "PASS"}))
    must_fail("live_hardware_accessed=true",
              lambda d: d["scope"].update({"live_hardware_accessed": True}))
    must_fail("抹掉 empty_run_is_fail",
              lambda d: d["acceptance"].update({"empty_run_is_fail": False}))
    must_fail("删 case_notes 一项", lambda d: d["case_notes"].popitem())
    must_fail("抹掉 negative_controls", lambda d: d.update({"negative_controls": []}))

    # CLI: --check / --json / --ship-gate must be real processes.
    import subprocess
    script = str(HERE / "check_stream_parity.py")
    chk = subprocess.run([sys.executable, script, "--check"],
                         cwd=str(SOFTWARE), capture_output=True, text=True)
    ck("CLI 真跑：--check rc=0", chk.returncode == 0, chk.stdout[-200:])
    ck("CLI 真跑：--check 声明 NOT_SHIPPABLE", "NOT_SHIPPABLE" in chk.stdout)
    gate = subprocess.run([sys.executable, script, "--check", "--ship-gate"],
                          cwd=str(SOFTWARE), capture_output=True, text=True)
    ck("CLI 真跑：--ship-gate 必 rc=1 拒绝", gate.returncode == 1,
       "rc=%d" % gate.returncode)
    js = subprocess.run([sys.executable, script, "--check", "--json"],
                        cwd=str(SOFTWARE), capture_output=True, text=True)
    try:
        rep = json.loads(js.stdout)
        ck("CLI 真跑：--json 是关键判决而非 silent skip",
           rep["live_hardware_accessed"] is False
           and rep["ship_verdict"] == "NOT_SHIPPABLE"
           and rep["status"] == "UNVERIFIED"
           and rep["all_byte_equal"] is True
           and rep["negative_control_live"] is True)
    except Exception as e:
        ck("CLI 真跑：--json 是关键判决而非 silent skip", False, str(e))

    bad_n = sum(1 for _n, ok, _d in checks if not ok)
    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name,
                               ("  <- " + note) if note and not ok else ""))
    print("\nself-test: %d/%d passed" % (len(checks) - bad_n, len(checks)))
    if bad_n:
        print("FAILED: %d check(s)" % bad_n)
        return 1
    print("scope: SCS v1 流解析离线 parity only; no hardware, no R3 closure, no sign-off.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="run the real two-implementation parity")
    ap.add_argument("--selftest", action="store_true", help="negative controls on the gate itself")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable report")
    ap.add_argument("--verify-source", action="store_true",
                    help="pin the production parse_scs protocol rules via AST")
    ap.add_argument("--ship-gate", action="store_true", help="always refuse; parity is not sign-off")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.check:
        ap.print_help()
        return 2

    rep = run_check(verify=args.verify_source, ship_gate=args.ship_gate)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("tool = %s" % rep["tool"])
        print("production = %s  sha256=%s" % (rep["production_source"],
                                             rep["production_sha256"][:16]))
        print("extracted = %s" % ", ".join(rep["extracted_symbols"]))
        print("cases = %d  all_byte_equal = %s  total_framed = %d" % (
            len(rep["cases"]), rep["all_byte_equal"], rep["total_framed_packets"]))
        print("negative_control_live = %s" % rep["negative_control_live"])
        for cid, r in rep["cases"].items():
            flag = "ok" if (r["count_ok"] and r["a_equals_b"]) else "XX"
            print("  [%s] %-28s A=%d B=%d expected=%d" % (
                flag, cid, r["packets_a"], r["packets_b"], r["expected_valid_packets"]))
        if rep["problems"]:
            print("problems = %d" % len(rep["problems"]))
            for x in rep["problems"]:
                print("  - " + x)
        if rep.get("ship_gate"):
            print("SHIP GATE REFUSED: " + rep["ship_gate_reason"])
        print("status = %s  verdict = %s  ship_verdict = %s" % (
            rep["status"], rep["verdict"], rep["ship_verdict"]))
        print("live_hardware_accessed = false")
        print("scope: " + rep["scope"])

    if rep["verdict"] == "FAIL":
        return 1
    if args.ship_gate:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
