#!/usr/bin/env python3
"""B2: image / firmware / console / IMU-node version-pairing contract gate.

Why this exists (2026-11-11, four-source comparison, follow-up B2)
------------------------------------------------------------------
kissqy README line 22 says "firmware/BUILD.json 与 V167 随包固件的 BUILD
记录一致，两个中控的程序源码与各自 ZIP 同步". That is a *claim of pairing*,
not a local check of it. Project SSOT pins 路① to R17→V167 (not `uv run
publish`), preinstalls control.40 in R1 and requires an upgrade to
control.43. Without a single owner for the four-slot tuple, a mixed batch
looks perfectly reasonable and only fails on the robot.

Rules borrowed, not invented:
  - official docs/policy-manifest.md: "Absent fields are not evidence".
    A published checksum is evidence that somebody published it, NOT that
    the local file matches it.
  - kissqy README: version pairing between BUILD.json / bundled firmware /
    console ZIP; "源码公开不扩大原有模型的实机验收范围".
  - fanhao verification: "Verified locally" vs "Board acceptance still
    required". VALIDATION.md explicitly says the real bus, servos, T_resp
    and DE release timing are still untested.
  - open-microduck check_book.py: id set equality + output hashes.
  - hd1910m audit_native_observation_contract.py: report carries
    live_hardware_accessed=false and states what it does NOT prove.

Single source of truth: image_pairing_contract.json. Stdlib only.

Two different hashes are pinned for the IMU HEX (do not conflate them):
  - sha256 of the Intel HEX *text file*;
  - sha256 of the *decoded 10,724-byte Flash image* it encodes.
The second is recomputed here with an independent Intel HEX decoder and
matches upstream VALIDATION.md exactly.

Usage (cwd = microduck-software):
    .venv-mjlab/Scripts/python.exe tools/hd1910/check_image_pairing.py --check
    .venv-mjlab/Scripts/python.exe tools/hd1910/check_image_pairing.py --check --json
    .venv-mjlab/Scripts/python.exe tools/hd1910/check_image_pairing.py --check --ship-gate
    .venv-mjlab/Scripts/python.exe tools/hd1910/check_image_pairing.py --check --verify-sources .upstream
    .venv-mjlab/Scripts/python.exe tools/hd1910/check_image_pairing.py --selftest
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
ROOT = SOFTWARE.parent
CONTRACT = HERE / "image_pairing_contract.json"
SHA = re.compile(r"sha256:([0-9a-f]{64})")
SLOT_FIELDS = ("id", "name", "expected", "pin_kind", "evidence_kind",
               "local_file_present", "why_not_closed", "still_owed",
               "source_refs")


def load(path: Path = CONTRACT) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_of(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def decode_intel_hex(path: Path) -> bytes:
    """Independent Intel HEX decoder -> contiguous Flash image bytes.

    Handles 00 (data), 01 (EOF), 04 (extended linear address), 05 (start
    linear address). Every record checksum is verified. A gap in the
    addressed bytes raises instead of silently zero-filling: a missing
    record must never look like a valid image.
    """
    base = 0
    chunks: dict[int, int] = {}
    for raw in io.open(path, encoding="ascii", errors="replace").read().splitlines():
        line = raw.strip()
        if not line or not line.startswith(":"):
            continue
        rec = bytes.fromhex(line[1:])
        if (sum(rec) & 0xFF) != 0:
            raise ValueError("Intel HEX checksum error: %s" % line[:24])
        n = rec[0]
        addr = (rec[1] << 8) | rec[2]
        typ = rec[3]
        data = rec[4:4 + n]
        if typ == 0:
            for i, value in enumerate(data):
                chunks[base + addr + i] = value
        elif typ == 4:
            base = int.from_bytes(data, "big") << 16
        elif typ in (1, 5):
            pass
        else:
            raise ValueError("unsupported Intel HEX record type %d" % typ)
    if not chunks:
        raise ValueError("Intel HEX contains no data records")
    lo, hi = min(chunks), max(chunks)
    if hi - lo + 1 != len(chunks):
        raise ValueError("Intel HEX has address gaps (%d addresses, %d bytes)"
                         % (hi - lo + 1, len(chunks)))
    return bytes(chunks[a] for a in range(lo, hi + 1))


def hexrec(addr: int, data: bytes, typ: int = 0) -> str:
    """Build one Intel HEX record (used by the selftest's real fixtures)."""
    body = bytes([len(data), (addr >> 8) & 0xFF, addr & 0xFF, typ]) + data
    return ":" + (body + bytes([(-sum(body)) & 0xFF])).hex().upper()


def validate(data: dict) -> list[str]:
    p: list[str] = []
    if data.get("schema_version") != 1:
        p.append("schema_version must be 1")
    rule = data.get("rule") or ""
    if "NOT_SHIPPABLE" not in rule or "LOCAL_COMPUTED" not in rule:
        p.append("rule must state that non-LOCAL_COMPUTED pins are NOT_SHIPPABLE")
    required = data.get("required_slots") or []
    slots = data.get("slots") or []
    if not required or not slots:
        p.append("empty required_slots/slots: refusing to call an empty contract verified")
        return p
    kinds = set(data.get("pin_kinds") or [])
    ids = [s.get("id", "") for s in slots]
    if len(ids) != len(set(ids)):
        p.append("duplicate slot ids")
    if set(ids) != set(required):
        p.append("slot id set != required_slots: %s" % sorted(set(ids) ^ set(required)))
    for s in slots:
        sid = s.get("id", "<no id>")
        for k in SLOT_FIELDS:
            if k not in s:
                p.append("%s missing field %s" % (sid, k))
        kind = s.get("pin_kind")
        if kind not in kinds:
            p.append("%s invalid pin_kind %r" % (sid, kind))
        present = s.get("local_file_present")
        if kind == "LOCAL_COMPUTED" and present is not True:
            p.append("%s LOCAL_COMPUTED requires a local file" % sid)
        if kind == "UNOBTAINABLE" and present is not False:
            p.append("%s UNOBTAINABLE must not claim a local file" % sid)
        if present is True and not SHA.findall(s.get("expected") or ""):
            p.append("%s has a local file but no sha256 pin" % sid)
        for k in ("evidence_kind", "still_owed", "source_refs"):
            if k in s and isinstance(s[k], list) and not s[k]:
                p.append("%s empty %s" % (sid, k))
        if not str(s.get("why_not_closed") or "").strip():
            p.append("%s empty why_not_closed" % sid)
    if not (data.get("cross_slot_rules") or []):
        p.append("cross_slot_rules must not be empty")
    for c in data.get("cross_slot_rules") or []:
        for k in ("id", "rule", "source"):
            if not c.get(k):
                p.append("cross_slot_rule missing %s" % k)
    if not (data.get("blocked_actions") or []):
        p.append("blocked_actions must not be empty")
    scope = data.get("scope") or {}
    if scope.get("live_hardware_accessed") is not False:
        p.append("scope.live_hardware_accessed must be explicitly false")
    if not (scope.get("not_proof_of") or []):
        p.append("scope.not_proof_of must be non-empty")
    signoff = data.get("signoff") or {}
    if signoff.get("status") == "PASS" and not (signoff.get("evidence") or []):
        p.append("signoff claims PASS without evidence")
    return p


def overall_verdict(data: dict) -> str:
    """Only a fully locally-computed, signed-off tuple is shippable."""
    slots = data.get("slots") or []
    required = data.get("required_slots") or []
    if not slots or not required or set(s.get("id") for s in slots) != set(required):
        return "NOT_SHIPPABLE"
    if any(s.get("pin_kind") != "LOCAL_COMPUTED" for s in slots):
        return "NOT_SHIPPABLE"
    if (data.get("signoff") or {}).get("status") != "PASS":
        return "NOT_SHIPPABLE"
    return "SHIPPABLE"


def verify_sources(upstream: Path, data: dict) -> dict:
    """Actually recompute the pins from local first-party files.

    This is opt-in: .upstream/ is gitignored, so a fresh clone cannot be
    expected to have it. Missing sources are reported as not verified,
    never silently skipped and never upgraded to a pass.
    """
    out: dict = {"root": str(upstream), "root_exists": upstream.is_dir(),
                 "checks": [], "all_ok": False}

    def add(name: str, ok: bool, note: str = "") -> None:
        out["checks"].append({"name": name, "ok": bool(ok), "note": note})

    if not upstream.is_dir():
        add("source root present", False, "no .upstream directory")
        return out
    add("source root present", True)

    imu = next((s for s in data["slots"] if s["id"] == "imu_node_firmware_020"), None)
    r1 = next((s for s in data["slots"] if s["id"] == "system_image_r1"), None)
    pins = SHA.findall((imu or {}).get("expected") or "")
    hex_path = (upstream / "replica" / "hardware" / "imu_to_dxl" / "firmware"
                / "Build" / "imu_to_dxl.hex")
    if hex_path.is_file() and imu and len(pins) >= 2:
        raw = hex_path.read_bytes()
        try:
            img = decode_intel_hex(hex_path)
            add("IMU HEX file sha256", sha256_bytes(raw) == pins[0],
                "got %s" % sha256_bytes(raw)[:16])
            add("IMU decoded Flash image sha256", sha256_bytes(img) == pins[1],
                "image bytes=%d" % len(img))
            add("IMU Flash image size 10724", len(img) == 10724, "got %d" % len(img))
        except (ValueError, IndexError) as e:
            add("IMU HEX decode", False, str(e))
        validation = hex_path.parents[1] / "VALIDATION.md"
        if validation.is_file():
            add("VALIDATION.md records the same decoded image sha",
                pins[1] in io.open(validation, encoding="utf-8").read())
    else:
        add("IMU HEX present and pinned", False, "missing hex or missing sha pins")

    card = upstream / "replica" / "tools" / "radxa" / "kissqy-r1-v112.sh"
    r1_pin = SHA.findall((r1 or {}).get("expected") or "")
    if card.is_file() and r1_pin:
        text = io.open(card, encoding="utf-8", errors="replace").read()
        m = re.search(r"^R1_SHA=([0-9a-f]{64})", text, re.M)
        add("R1 sha from fanhao script matches contract",
            bool(m) and m.group(1) == r1_pin[0],
            "script=%s" % (m.group(1)[:16] if m else "not found"))
    else:
        add("R1 sha script present", False, "missing script or missing pin")

    build_json = upstream / "kissqy" / "firmware" / "BUILD.json"
    out["control43_build_json_present"] = build_json.is_file()
    out["all_ok"] = all(c["ok"] for c in out["checks"])
    return out


def selftest() -> int:
    data = load()
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    base = validate(data)
    ck("盘上契约结构自校验通过", not base, "; ".join(base[:3]))
    ck("slot id 集合与 required_slots 相等",
       set(s["id"] for s in data["slots"]) == set(data["required_slots"]))
    ck("当前整体判 NOT_SHIPPABLE", overall_verdict(data) == "NOT_SHIPPABLE")
    ck("scope 明确未碰硬件", data["scope"]["live_hardware_accessed"] is False)
    ck("control.43 如实标 UNOBTAINABLE",
       any(s["id"] == "robot_firmware_control43" and s["pin_kind"] == "UNOBTAINABLE"
           for s in data["slots"]))
    ck("IMU HEX 如实标 LOCAL_COMPUTED 且带两个 sha",
       any(s["id"] == "imu_node_firmware_020" and s["pin_kind"] == "LOCAL_COMPUTED"
           and len(SHA.findall(s["expected"])) == 2 for s in data["slots"]))

    good = copy.deepcopy(data)
    for s in good["slots"]:
        s["pin_kind"] = "LOCAL_COMPUTED"
        s["local_file_present"] = True
    good["signoff"] = {"status": "PASS", "evidence": ["selftest synthetic"]}
    ck("正对照：四槽全本地实算且签署则 SHIPPABLE", overall_verdict(good) == "SHIPPABLE")
    back = copy.deepcopy(good)
    back["slots"][0]["pin_kind"] = "UNPINNED"
    ck("负对照：塞回一个 UNPINNED 立刻 NOT_SHIPPABLE",
       overall_verdict(back) == "NOT_SHIPPABLE")

    def must_fail(name: str, mutate) -> None:
        bad = copy.deepcopy(data)
        mutate(bad)
        ck(name, bool(validate(bad)))

    must_fail("负对照：删一个 slot 必红", lambda d: d["slots"].pop())
    must_fail("负对照：重复 slot id 必红",
              lambda d: d["slots"].append(copy.deepcopy(d["slots"][0])))
    must_fail("负对照：非法 pin_kind 必红",
              lambda d: d["slots"][0].update({"pin_kind": "MAGICALLY_VERIFIED"}))
    must_fail("负对照：LOCAL_COMPUTED 无本地文件必红",
              lambda d: d["slots"][3].update({"local_file_present": False}))
    must_fail("负对照：UNOBTAINABLE 假称有本地文件必红",
              lambda d: d["slots"][1].update({"local_file_present": True}))
    must_fail("负对照：抹掉 rule 语义必红", lambda d: d.update({"rule": "everything passes"}))
    must_fail("负对照：scope 声称碰过硬件必红",
              lambda d: d["scope"].update({"live_hardware_accessed": True}))
    must_fail("负对照：空 slots 必红", lambda d: d.update({"slots": []}))
    must_fail("负对照：signoff 无证据称 PASS 必红",
              lambda d: d["signoff"].update({"status": "PASS"}))
    must_fail("负对照：清掉 cross_slot_rules 必红",
              lambda d: d.update({"cross_slot_rules": []}))
    must_fail("负对照：清掉 blocked_actions 必红",
              lambda d: d.update({"blocked_actions": []}))
    must_fail("负对照：有本地文件却无 sha 针必红",
              lambda d: d["slots"][3].update({"expected": "no hash here"}))

    # Real Intel HEX fixtures: prove the decoder is content-sensitive and
    # that verify_sources refuses a tampered HEX (not a mocked boolean).
    with tempfile.TemporaryDirectory(prefix="md_hex_") as td:
        tmp = Path(td)
        fw = tmp / "replica" / "hardware" / "imu_to_dxl" / "firmware"
        (fw / "Build").mkdir(parents=True)
        tools = tmp / "replica" / "tools" / "radxa"
        tools.mkdir(parents=True)
        body = bytes([1, 2, 3, 4])
        lines = [hexrec(0, bytes([0x08, 0x00]), 4), hexrec(0, body),
                 ":00000001FF"]
        good_hex = fw / "Build" / "imu_to_dxl.hex"
        good_hex.write_text("\n".join(lines) + "\n", encoding="ascii")
        ck("真对照：Intel HEX 解码含扩展线性地址记录",
           decode_intel_hex(good_hex) == body)
        ck("真对照：解码镜像 sha 与独立实算一致",
           sha256_bytes(decode_intel_hex(good_hex)) == sha256_bytes(body))
        tampered = body[:-1] + bytes([body[-1] ^ 0xFF])
        bad_hex = fw / "Build" / "tampered.hex"
        bad_hex.write_text("\n".join([hexrec(0, bytes([0x08, 0x00]), 4),
                                      hexrec(0, tampered), ":00000001FF"]) + "\n",
                           encoding="ascii")
        ck("负对照：篡改 1 字节后解码镜像 sha 必变",
           sha256_bytes(decode_intel_hex(bad_hex)) != sha256_bytes(body))
        r1sha = SHA.findall(data["slots"][0]["expected"])[0]
        (tools / "kissqy-r1-v112.sh").write_text("R1_SHA=%s\n" % r1sha, encoding="utf-8")
        (fw / "VALIDATION.md").write_text(
            "decoded %s" % SHA.findall(data["slots"][3]["expected"])[1], encoding="utf-8")
        # Swap in the tampered HEX under the expected name: source check must go red.
        good_hex.write_text("\n".join([hexrec(0, bytes([0x08, 0x00]), 4),
                                       hexrec(0, tampered), ":00000001FF"]) + "\n",
                            encoding="ascii")
        res = verify_sources(tmp, data)
        ck("负对照：--verify-sources 遇到篡改 HEX 必报 not ok",
           res["all_ok"] is False
           and any(c["name"].startswith("IMU") and not c["ok"] for c in res["checks"]),
           "checks=%d" % len(res["checks"]))

    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name, ("  <- " + note) if note else ""))
    bad_n = [n for n, ok, _ in checks if not ok]
    print("\ncheck_image_pairing selftest: %d/%d passed" % (len(checks) - len(bad_n), len(checks)))
    if bad_n:
        print("FAILED: " + "; ".join(bad_n))
        return 1
    print("scope: version-pairing structure + optional local sha recompute; no flashing, no download.")
    print("self-test: PASS")
    return 0


def report(data: dict, problems: list[str], sources: dict | None) -> dict:
    counts: dict[str, int] = {}
    for s in data.get("slots") or []:
        k = s.get("pin_kind", "?")
        counts[k] = counts.get(k, 0) + 1
    return {
        "tool": "check_image_pairing.py",
        "contract_sha256": sha256_of(CONTRACT),
        "slots": [s["id"] for s in data["slots"]],
        "pin_kind_counts": counts,
        "problems": problems,
        "structure_verdict": "PASS" if not problems else "FAIL",
        "ship_verdict": overall_verdict(data),
        "source_files_verified": bool(sources and sources.get("all_ok")),
        "source_verification": sources,
        "live_hardware_accessed": False,
        "not_proof_of": data["scope"]["not_proof_of"],
        "known_gaps": data["scope"]["known_gaps"],
        "scope": "镜像/固件/中控/IMU 四元组版本配对的结构与 sha 校验；未本地实算的 pin 不算闭环",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the on-disk contract")
    ap.add_argument("--selftest", action="store_true", help="run negative controls")
    ap.add_argument("--ship-gate", action="store_true",
                    help="with --check, rc=1 unless the whole tuple is signed off")
    ap.add_argument("--verify-sources", metavar="DIR", default=None,
                    help="recompute pins against a local .upstream directory")
    ap.add_argument("--json", action="store_true", help="emit a machine-readable report")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    data = load()
    problems = validate(data)
    sources = None
    if args.verify_sources:
        sources = verify_sources(Path(args.verify_sources), data)
        if not sources.get("all_ok"):
            problems.append("source verification failed: see source_verification.checks")
    rep = report(data, problems, sources)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("image_pairing_contract.json sha256 = " + rep["contract_sha256"])
        print("slots = " + ", ".join(rep["slots"]))
        print("pin kinds = " + json.dumps(rep["pin_kind_counts"], ensure_ascii=False))
        print("source_files_verified = %s" % str(rep["source_files_verified"]).lower())
        for x in problems:
            print("  [FAIL] " + x)
        print("structure_verdict = " + rep["structure_verdict"])
        print("ship verdict = " + rep["ship_verdict"] + "  (published sha != local proof)")
        print("live_hardware_accessed = false")
        print("scope: " + rep["scope"])

    if problems:
        return 1
    if args.ship_gate and rep["ship_verdict"] != "SHIPPABLE":
        if not args.json:
            print("SHIP GATE REFUSED: %d slot(s) not locally computed" %
                  sum(v for k, v in rep["pin_kind_counts"].items() if k != "LOCAL_COMPUTED"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
