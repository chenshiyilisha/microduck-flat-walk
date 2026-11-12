#!/usr/bin/env python3
"""B9: LOCAL sha256 evidence for the downloaded kissqy base artifacts.

Why this exists (2026-11-12, motherboard-ordered preparation)
------------------------------------------------------------
B2 (image_pairing_contract.json) deliberately describes the *distribution-
independent* state of the four-slot tuple: pin_kind stays UNOBTAINABLE /
UNPINNED / UPSTREAM_PUBLISHED because ``.upstream/`` is gitignored and a
fresh clone has no artifacts. That is correct and must NOT be weakened.

This tool is the OPT-IN local counterpart (same spirit as
check_image_pairing.py --verify-sources): when the real downloaded files
happen to be present on THIS machine, recompute their sha256 from bytes and
cross-check against three independent witnesses each:

  * local_evidence_manifest.json       (this repo, published-value pins)
  * the published metadata / manifests (firmware-control43.json,
    BUILD_MANIFEST.json, the two .sha256 files, GitHub API digest/blob-sha)
  * image_pairing_contract.json        (the authoritative expected values)

It NEVER edits the contract, NEVER claims SHIPPABLE, NEVER touches hardware,
NEVER runs dd / flashes / mounts. live_hardware_accessed=false, always.
A declared/published value is NOT evidence the local bytes match it -- this
tool is what turns "somebody published it" into "these exact local bytes
hash to it".

Negative control: tamper any byte of any artifact and that slot MUST go red.

Usage (cwd = microduck-software):
    .venv-mjlab/Scripts/python.exe tools/hd1910/local_evidence.py --verify --json
    .venv-mjlab/Scripts/python.exe tools/hd1910/local_evidence.py --verify
    .venv-mjlab/Scripts/python.exe tools/hd1910/local_evidence.py --local-selftest
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
CONTRACT = HERE / "image_pairing_contract.json"
MANIFEST = HERE / "local_evidence_manifest.json"
DOWNLOADS = SOFTWARE / ".upstream" / "downloads"
SHA = __import__("re").compile(r"sha256:([0-9a-f]{64})")


def load(path: Path) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_of(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git_blob_sha1(b: bytes) -> str:
    """SHA-1 of a git blob object = sha1(b'blob <len>\\0' + content)."""
    return hashlib.sha1(b"blob " + str(len(b)).encode("ascii") + b"\x00" + b).hexdigest()


def slot_of(data: dict, sid: str) -> dict:
    return next((s for s in data["slots"] if s["id"] == sid), {})


def expected_sha(slot: dict, index: int = 0) -> str | None:
    pins = SHA.findall(slot.get("expected") or "")
    return pins[index] if len(pins) > index else None


def grade(manifest: dict, contract: dict, downloads: Path) -> dict:
    """Recompute every artifact that is present; report honestly what is absent.

    Each artifact result carries: local sha256 (or None), the published value,
    the contract pin (when the contract pins a sha), size, and witnesses that
    agreed. Verdict is per-slot; overall is ALL_LOCAL_COMPUTED only when every
    artifact matched AND no download is pending.
    """
    results: list[dict] = []
    overall = "ALL_LOCAL_COMPUTED"
    for art in manifest["artifacts"]:
        aid = art["id"]
        path = downloads / art["file"]
        published = art["published_sha256"]
        slot = slot_of(contract, art.get("contract_slot", ""))
        contract_pin = expected_sha(slot, art.get("contract_pin_index", 0))
        rec: dict = {
            "id": aid,
            "file": art["file"],
            "contract_slot": art.get("contract_slot"),
            "published_sha256": published,
            "contract_pin_sha256": contract_pin,
            "size_expected": art.get("size_expected"),
            "witnesses": art.get("witnesses", []),
            "local_sha256": None,
            "size_actual": None,
            "verdict": "PENDING_DOWNLOAD",
            "notes": [],
        }
        if not path.is_file():
            rec["notes"].append("local file absent (gitignored .upstream/downloads)")
            if overall == "ALL_LOCAL_COMPUTED":
                overall = "PENDING"
            results.append(rec)
            continue
        b = path.read_bytes()
        local = sha256_bytes(b)
        rec["local_sha256"] = local
        rec["size_actual"] = len(b)
        # independent witnesses must agree with each other AND with local bytes
        pin_values = [v for v in (published, contract_pin) if v]
        mismatches = [v for v in pin_values if v != local]
        size_ok = rec["size_expected"] is None or len(b) == rec["size_expected"]
        # optional extra: git blob SHA-1 (V167) or embedded-pkg sha (control.43)
        if art.get("git_blob_sha1"):
            got_blob = git_blob_sha1(b)
            blob_ok = got_blob == art["git_blob_sha1"]
            rec["notes"].append("git_blob_sha1=%s match=%s" % (got_blob[:16], blob_ok))
            if not blob_ok:
                mismatches.append("blob-sha1-mismatch")
        if art.get("embedded_in"):
            host = downloads / art["embedded_in"]["zip"]
            if host.is_file():
                try:
                    with zipfile.ZipFile(host) as z:
                        inner = z.read(art["embedded_in"]["member"])
                    inner_sha = sha256_bytes(inner)
                    inner_ok = inner_sha == local and len(inner) == len(b)
                    rec["notes"].append("embedded_pkg_sha=%s match=%s" %
                                        (inner_sha[:16], inner_ok))
                    if not inner_ok:
                        mismatches.append("embedded-mismatch")
                except (KeyError, zipfile.BadZipFile) as e:
                    rec["notes"].append("embedded read failed: %s" % e)
                    mismatches.append("embedded-unreadable")
            else:
                rec["notes"].append("host zip absent for embedded check")
                mismatches.append("host-missing")
        size_short = (art.get("size_expected") is not None
                      and len(b) < art["size_expected"])
        if art.get("size_expected") is not None and not size_ok:
            mismatches.append("size-mismatch")
        if size_short:
            # A file smaller than the published size is almost always a
            # download still in progress. Report INCOMPLETE, not "corrupt" --
            # calling it MISMATCH would fabricate a damage conclusion.
            rec["verdict"] = "INCOMPLETE_DOWNLOAD"
            rec["notes"].append("local size %d < expected %d (download in progress)"
                                % (len(b), art["size_expected"]))
            if overall == "ALL_LOCAL_COMPUTED":
                overall = "PENDING"
        elif mismatches:
            rec["verdict"] = "MISMATCH"
            rec["notes"].append("mismatched witnesses/pins: %d" % len(mismatches))
            overall = "MISMATCH"
        else:
            rec["verdict"] = "LOCAL_COMPUTED"
            rec["notes"].append("local bytes hash to all %d independent pins" %
                                len(pin_values))
        results.append(rec)
    return {
        "tool": "local_evidence.py",
        "manifest_sha256": sha256_of(MANIFEST),
        "contract_sha256": sha256_of(CONTRACT),
        "downloads_dir": str(downloads),
        "verdict": overall,
        "all_local_computed": overall == "ALL_LOCAL_COMPUTED",
        "results": results,
        "live_hardware_accessed": False,
        "ship_verdict": "NOT_SHIPPABLE",  # local sha never closes board acceptance
        "not_proof_of": [
            "镜像可开机 / 可连 WiFi / 可进 SSH",
            "control.43 可自编译或已刷入并在真机运行（元数据 physical_robot_operated=false、hardware_verified=false）",
            "V167 中控能加载 p8head_2999",
            "人人 ¥80 IMU 板与 fanhao 复刻 HEX / FT6 bin 同硬件",
            "任何一条 board_acceptance 上板判据",
        ],
        "scope": "本机对已下载底座产物的 sha256 实算与多源对账；contract pin_kind 不因此自动改动。",
    }


def local_selftest() -> int:
    """Negative controls on synthetic bytes -- no real artifacts required."""
    manifest = load(MANIFEST)
    with tempfile.TemporaryDirectory(prefix="md_local_ev_") as td:
        tdir = Path(td)
        # smallest synthetic artifact with a known sha and size
        art = {
            "id": "selftest_art", "file": "a.bin", "contract_slot": "",
            "published_sha256": sha256_bytes(b"hello"), "size_expected": 5,
            "witnesses": ["synthetic"],
        }
        (tdir / "a.bin").write_bytes(b"hello")
        m = {"artifacts": [art]}
        c = {"slots": []}
        good = grade(m, c, tdir)
        checks = [
            ("正对照：匹配文件必须进 results（防 append 漏写）",
             len(good["results"]) == 1),
            ("正对照：匹配字节判 LOCAL_COMPUTED",
             len(good["results"]) == 1
             and good["results"][0]["verdict"] == "LOCAL_COMPUTED"),
            ("正对照：整体 ALL_LOCAL_COMPUTED", good["all_local_computed"]),
        ]
        # negative 1: tamper one byte at same length -> MISMATCH (not incomplete)
        (tdir / "a.bin").write_bytes(b"hellX"[:5])
        bad = grade(m, c, tdir)
        checks.append(("负对照：等长篡改 1 字节必红 MISMATCH",
                       len(bad["results"]) == 1
                       and bad["results"][0]["verdict"] == "MISMATCH"
                       and bad["verdict"] == "MISMATCH"))
        # negative 2: shorter than published size -> INCOMPLETE, NOT "corrupt"
        (tdir / "a.bin").write_bytes(b"hel")
        short = grade(m, c, tdir)
        checks.append(("负对照：半成品报 INCOMPLETE_DOWNLOAD 不误报损坏",
                       len(short["results"]) == 1
                       and short["results"][0]["verdict"] == "INCOMPLETE_DOWNLOAD"
                       and short["verdict"] != "MISMATCH"))
        # negative 3: missing file -> PENDING, must NOT claim computed
        (tdir / "a.bin").unlink()
        missing = grade(m, c, tdir)
        checks.append(("负对照：缺文件报 PENDING_DOWNLOAD 不假绿",
                       len(missing["results"]) == 1
                       and missing["results"][0]["verdict"] == "PENDING_DOWNLOAD"
                       and not missing["all_local_computed"]))
        # negative 4: a MATCHING git_blob_sha1 must not pollute mismatches
        # (regression: appending the local sha on success -> false MISMATCH)
        (tdir / "a.bin").write_bytes(b"hello")
        art_blob = dict(art, git_blob_sha1=git_blob_sha1(b"hello"))
        r_blob = grade({"artifacts": [art_blob]}, c, tdir)
        checks.append(("负对照：git_blob_sha1 匹配不得假红",
                       len(r_blob["results"]) == 1
                       and r_blob["results"][0]["verdict"] == "LOCAL_COMPUTED"))
        bad_blob = dict(art, git_blob_sha1="0" * 40)
        r_bad = grade({"artifacts": [bad_blob]}, c, tdir)
        checks.append(("负对照：git_blob_sha1 不符必红",
                       len(r_bad["results"]) == 1
                       and r_bad["results"][0]["verdict"] == "MISMATCH"))
        # negative 5: local sha never implies SHIPPABLE
        checks.append(("负对照：ship_verdict 恒 NOT_SHIPPABLE",
                       good["ship_verdict"] == "NOT_SHIPPABLE"))
        for name, ok in checks:
            print("  [%s] %s" % ("ok" if ok else "XX", name))
        n_bad = sum(1 for _, ok in checks if not ok)
        print("local_evidence self-test: %d/%d passed" % (len(checks) - n_bad, len(checks)))
        return 1 if n_bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true",
                    help="recompute sha256 of all locally present artifacts")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--local-selftest", action="store_true",
                    help="run negative controls on synthetic bytes")
    args = ap.parse_args()
    if args.local_selftest:
        return local_selftest()
    if not args.verify:
        ap.print_help()
        return 2
    manifest = load(MANIFEST)
    contract = load(CONTRACT)
    rep = grade(manifest, contract, DOWNLOADS)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("verdict = %s" % rep["verdict"])
        for r in rep["results"]:
            print("  [%s] %-26s local=%s published=%s" %
                  (r["verdict"], r["id"],
                   (r["local_sha256"] or "ABSENT")[:16],
                   (r["published_sha256"] or "")[:16]))
            for n in r["notes"]:
                print("        - " + n)
        print("all_local_computed = %s" % str(rep["all_local_computed"]).lower())
        print("ship verdict = %s (local sha != board acceptance)" % rep["ship_verdict"])
        print("live_hardware_accessed = false")
    # --verify is a report, not a gate: PENDING is a normal state on a fresh clone
    return 1 if rep["verdict"] == "MISMATCH" else 0


if __name__ == "__main__":
    sys.exit(main())
