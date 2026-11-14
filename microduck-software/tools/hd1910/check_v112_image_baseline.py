#!/usr/bin/env python3
"""V112 image rootfs content baseline (candidate 9, 2026-11-14).

Why this exists
---------------
`verify_v112.sh` verifies the two boot sectors + one extlinux grep. It does NOT
cover the rootfs configuration at all. The 2026-11-14 image audit found several
facts that matter to the on-board acceptance criteria (cmdline has no
console=ttyS2, serial-getty@ttyS2 is masked, fstab has `defaults,,commit=120`,
the AP profile pins the B-route hotspot, journald already has an explicit
drop-in, ...), but those were only HUMAN notes in a markdown report. A later
edit to the image, or a different card, could silently change all of them.

This tool turns those facts into a machine-checkable, read-only content
baseline. It borrows the four-state verdict engine from
`check_procurement_baseline.py` (E2) instead of inventing a new one.

What it does NOT pretend to do
------------------------------
A BASELINE_MATCH proves "unchanged RELATIVE TO recorded_at" only. It does NOT
prove the configuration is correct (fstab's double comma and 120s commit are
registered AS-IS, not blessed), does NOT prove the image boots, and does NOT
turn any UNVERIFIED_hardware item into PASS. See `scope.not_proof_of`.

Design rules enforced
---------------------
  * criteria live in the CONTRACT (external expected values), never derived
    from the file under test (rule 4: a self-derived criterion is a false green).
  * anchors use field parsing / set containment / full-line regex, NEVER bare
    substring matching (rule 8: `grep 4210` once hit camera IQ coefficients).
  * no plaintext password is stored; only "key present and non-empty" (rule 13).
  * --selftest builds a SYNTHETIC rootfs with semantically-equivalent but
    textually DIFFERENT content, so a green selftest cannot be a copy-the-real-
    files false green. Every negative control must really turn red.
  * read-only: the only file ever written is this contract, and only via an
    explicit audited --rebaseline --confirm --reason.

Usage (cwd = microduck-software):
    python tools/hd1910/check_v112_image_baseline.py --selftest
    python tools/hd1910/check_v112_image_baseline.py --list
    # real check needs a read-only rootfs mount (WSL2, root):
    #   mount -o loop,ro,offset=16777216 V112.img /root/v112inspect
    python tools/hd1910/check_v112_image_baseline.py --check \
        --root /root/v112inspect --image .upstream/downloads/microduck-zero3w-0.15.1-R1-V112.img
    python tools/hd1910/check_v112_image_baseline.py --check --json --root /path
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
ROOT = SOFTWARE.parent
CONTRACT = HERE / "v112_image_baseline.json"

# External anchor for the contract's own image pin (rule 4: a criterion that
# can be silently edited together with the thing it judges is a false green).
# Same pattern as publish_release.py::EXPECTED_SIGNER_SHA256. Source of truth:
# read from V112.img on 2026-11-14 (WSL2 sha256sum) and independently confirmed
# by the burned-card full-image SHA-256 in 烧卡操作卡 §4.6. Deliberately NOT
# derived from the contract, so editing only the contract turns validation red.
EXPECTED_IMAGE_SHA256 = "d8207edea3a3abf8234cb16cf18c859c94292ca492e5f2eff3a981e2fbd24f41"
EXPECTED_IMAGE_SIZE = 3157262336

MATCH = "BASELINE_MATCH"
DRIFT = "DRIFT_UNCONFIRMED"
SUSPECT = "COVERAGE_SUSPECT"
UNVERIFIED = "UNVERIFIED"

ANCHOR_KINDS = (
    "field_options", "regex_lines", "line_tokens", "line_tokens_absent",
    "kv_equals", "kv_present", "no_active_kv", "terms_in_same_line",
    "service_set", "symlink_target", "absent_path",
)


def load(path: Path = CONTRACT) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_stream(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# contract self-validation (independent of any real file's state)
# ---------------------------------------------------------------------------

def validate(data: dict) -> list[str]:
    p: list[str] = []
    if data.get("schema_version") != 1:
        p.append("schema_version must be 1")
    scope = data.get("scope") or {}
    if scope.get("live_hardware_accessed") is not False:
        p.append("scope.live_hardware_accessed must be false")
    if scope.get("ship_verdict") != "NOT_SHIPPABLE":
        p.append("scope.ship_verdict must be NOT_SHIPPABLE")
    if not (scope.get("not_proof_of") or []):
        p.append("scope.not_proof_of must be non-empty")
    if not any("过去从未" in x for x in scope.get("not_proof_of", [])):
        p.append("scope must disclaim retrospective proof")
    base = data.get("baseline") or {}
    if not base.get("recorded_at"):
        p.append("baseline.recorded_at missing")
    if "--rebaseline" not in str(base.get("rebaseline_policy", "")):
        p.append("baseline.rebaseline_policy must require explicit --rebaseline")
    img = data.get("image") or {}
    if not re.fullmatch(r"[0-9a-f]{64}", str(img.get("sha256", ""))):
        p.append("image.sha256 must be 64 lowercase hex")
    if img.get("sha256") != EXPECTED_IMAGE_SHA256:
        p.append("image.sha256 does not match the external anchor in this tool "
                 "(editing only the contract must turn validation red)")
    if img.get("size_bytes") != EXPECTED_IMAGE_SIZE:
        p.append("image.size_bytes does not match the external anchor in this tool")
    if not isinstance(img.get("size_bytes"), int) or img["size_bytes"] <= 0:
        p.append("image.size_bytes must be positive int")
    if img.get("rootfs_offset_bytes") != 32768 * 512:
        p.append("image.rootfs_offset_bytes must be 16777216 (32768 sectors)")
    sem = data.get("scope_semantics") or {}
    for state in (MATCH, DRIFT, SUSPECT, UNVERIFIED):
        if state not in sem:
            p.append("scope_semantics missing %s" % state)
    files = data.get("files") or []
    if not files:
        p.append("empty files list")
        return p
    ids = [f.get("id") for f in files]
    if len(ids) != len(set(ids)):
        p.append("duplicate file ids")
    for f in files:
        fid = f.get("id", "<no id>")
        if not re.fullmatch(r"[0-9a-f]{64}", str(f.get("sha256", ""))):
            p.append("%s sha256 must be 64 lowercase hex" % fid)
        if not isinstance(f.get("size_bytes"), int) or f["size_bytes"] < 0:
            p.append("%s size_bytes invalid" % fid)
        rel = str(f.get("path", ""))
        if not rel.strip() or rel.startswith("/") or ".." in Path(rel).parts:
            p.append("%s path must be relative and not escape root" % fid)
        if not str(f.get("why_protected", "")).strip():
            p.append("%s empty why_protected" % fid)
    anchors = data.get("semantic_anchors") or []
    if not anchors:
        p.append("empty semantic_anchors: hash-only baseline is not enough")
    seen: set[str] = set()
    for a in anchors:
        aid = a.get("id", "<no id>")
        if aid in seen:
            p.append("duplicate anchor id %s" % aid)
        seen.add(aid)
        if a.get("file") not in ids:
            p.append("%s references unknown file %r" % (aid, a.get("file")))
        if a.get("kind") not in ANCHOR_KINDS:
            p.append("%s unknown anchor kind %r" % (aid, a.get("kind")))
        if not str(a.get("why", "")).strip():
            p.append("%s empty why" % aid)
        if a.get("kind") in ("service_set", "symlink_target", "absent_path"):
            if not str(a.get("path", a.get("dir", ""))).strip():
                p.append("%s needs path/dir" % aid)
    if not (data.get("negative_controls") or []):
        p.append("negative_controls must be declared")
    return p


# ---------------------------------------------------------------------------
# parsers: field extraction, never bare substring
# ---------------------------------------------------------------------------

def active_lines(text: str) -> list[str]:
    """Lines that are neither blank, nor comments, nor [section] headers."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith(";"):
            out.append(line)
    return out


def parse_kv(text: str) -> dict[str, list[str]]:
    """key -> list of values. Keeps duplicates (systemd allows repeated keys).

    Handles `k=v`, `k = v`, TOML `"k" = "v"`, and python `K = 'v'`.
    Values are quote-stripped; comments are skipped.
    """
    out: dict[str, list[str]] = {}
    for line in active_lines(text):
        if line.lstrip().startswith("["):
            continue
        m = re.match(r"^\s*([A-Za-z0-9_\-\"']+)\s*=\s*(.*?)\s*$", line)
        if not m:
            continue
        key = m.group(1).strip().strip("\"'")
        val = m.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out.setdefault(key, []).append(val)
    return out


def find_line(text: str, prefix: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s == prefix or s.startswith(prefix + " ") or s.startswith(prefix + "\t"):
            return s
    return ""


def line_tokens(text: str, prefix: str, basename_only: bool = False) -> list[str]:
    line = find_line(text, prefix)
    if not line:
        return []
    toks = line.split()[1:]
    if basename_only:
        toks = [os.path.basename(t) for t in toks]
    return toks


# ---------------------------------------------------------------------------
# anchor evaluation
# ---------------------------------------------------------------------------

def evaluate_anchor(a: dict, root: Path, texts: dict[str, str]) -> str:
    """Return 'ok' or a concrete problem string. Never a bare boolean."""
    kind = a["kind"]
    fid = a["file"]
    if kind in ("service_set", "symlink_target", "absent_path"):
        # these read the filesystem, but still require the owning file to exist
        if fid not in texts:
            return "dependency file unavailable"
    else:
        if fid not in texts:
            return "dependency file unavailable"
    text = texts.get(fid, "")

    if kind == "field_options":
        idx = int(a["field_index"])
        found = None
        for line in active_lines(text):
            parts = line.split()
            if len(parts) > idx and parts[1] == "/":
                found = parts[idx].split(",")
                break
        if found is None:
            return "no root mount line found"
        exp = list(a["expected"])
        return "ok" if found == exp else "options %r != expected %r" % (found, exp)

    if kind == "line_tokens":
        got = line_tokens(text, a["line_prefix"], bool(a.get("basename_only")))
        missing = [t for t in a["expected_subset"] if t not in got]
        return "ok" if not missing else "missing tokens %s (got %s)" % (missing, got)

    if kind == "line_tokens_absent":
        got = line_tokens(text, a["line_prefix"])
        present = [t for t in a["forbidden"] if t in got]
        return "ok" if not present else "forbidden tokens present %s" % present

    if kind == "kv_equals":
        kv = parse_kv(text)
        bad = []
        for k, v in a["expected"].items():
            if k not in kv or v not in kv[k]:
                bad.append("%s=%r (got %r)" % (k, v, kv.get(k)))
        return "ok" if not bad else "mismatched %s" % bad

    if kind == "kv_present":
        kv = parse_kv(text)
        bad = [k for k in a["keys"] if k not in kv or not any(x for x in kv[k])]
        return "ok" if not bad else "missing/empty keys %s" % bad

    if kind == "no_active_kv":
        kv = {k: v for k, v in parse_kv(text).items()
              if not k.startswith("[")}
        return "ok" if not kv else "unexpected active keys %s" % sorted(kv)

    if kind == "regex_lines":
        bad = [pat for pat in a["patterns"]
               if not any(re.search(pat, ln) for ln in text.splitlines())]
        return "ok" if not bad else "no line matched %s" % bad

    if kind == "terms_in_same_line":
        terms = a["terms"]
        hit = any(all(t in ln for t in terms) for ln in text.splitlines())
        return "ok" if hit else "no single line contains all of %s" % terms

    if kind == "service_set":
        d = root / a["dir"]
        if not d.is_dir():
            return "service dir missing"
        got = {p.name for p in d.iterdir() if p.name.endswith(".service")}
        missing = [s for s in a["expected_subset"] if s not in got]
        return "ok" if not missing else "missing units %s" % missing

    if kind == "symlink_target":
        p = root / a["path"]
        if not p.is_symlink():
            return "not a symlink (mask removed?)"
        got = os.readlink(str(p))
        return "ok" if got == a["expected"] else "target %r != %r" % (got, a["expected"])

    if kind == "absent_path":
        p = root / a["path"]
        return "ok" if not os.path.lexists(str(p)) else "path unexpectedly exists"

    return "unknown kind %s" % kind


# ---------------------------------------------------------------------------
# real check
# ---------------------------------------------------------------------------

def check(data: dict, root: Path, image: Path | None = None) -> dict:
    problems: list[str] = []
    file_states: dict[str, dict] = {}
    texts: dict[str, str] = {}

    # Gate 0: mechanical prerequisite -- is this actually a mounted rootfs?
    root_ok = root.is_dir() and (root / "etc").is_dir()
    if not root_ok:
        problems.append("root 不是已挂载的 rootfs（缺 etc/）：未挂载 / CI 干净 checkout / Windows 侧不可见")

    for f in data["files"]:
        fid, rel = f["id"], f["path"]
        p = root / rel
        if not p.is_file():
            file_states[fid] = {"state": UNVERIFIED, "path": rel,
                                "note": "file missing (未挂载 / CI checkout / 镜像不同)"}
            continue
        h, size = sha256_of(p), p.stat().st_size
        ok = (h == f["sha256"] and size == f["size_bytes"])
        file_states[fid] = {
            "state": MATCH if ok else DRIFT, "path": rel,
            "sha256": h, "size_bytes": size,
            "recorded_sha256": f["sha256"], "recorded_size_bytes": f["size_bytes"],
            "hash_match": ok,
        }
        try:
            texts[fid] = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            # unreadable file must not be green
            file_states[fid]["state"] = SUSPECT
            file_states[fid]["note"] = "read failed: %s" % e

    # image-level pin (optional input, but when supplied it must match)
    image_state = "NOT_CHECKED"
    if image is not None:
        if not image.is_file():
            image_state = UNVERIFIED
            problems.append("镜像文件缺失，无法核 pin")
        else:
            ih, isz = sha256_stream(image), image.stat().st_size
            exp = data["image"]
            if ih != exp["sha256"] or isz != exp["size_bytes"]:
                image_state = SUSPECT
                problems.append("镜像 pin 不符: sha=%s size=%s" % (ih[:12], isz))
            else:
                image_state = MATCH

    anchor_states: list[dict] = []
    for a in data["semantic_anchors"]:
        fid = a["file"]
        if fid not in texts:
            anchor_states.append({"id": a["id"], "state": UNVERIFIED,
                                  "note": "依赖文件缺失，无法抽取锚点"})
            continue
        res = evaluate_anchor(a, root, texts)
        anchor_states.append({"id": a["id"], "state": "ok" if res == "ok" else "BROKEN",
                              "note": res})

    broken = [a for a in anchor_states if a["state"] == "BROKEN"]
    deps_missing = [a for a in anchor_states if a["state"] == UNVERIFIED]
    missing = [k for k, v in file_states.items() if v["state"] == UNVERIFIED]
    dirty = [k for k, v in file_states.items() if v["state"] == DRIFT]
    suspect_files = [k for k, v in file_states.items() if v["state"] == SUSPECT]

    # precedence: SUSPECT > UNVERIFIED > DRIFT > MATCH
    if broken or suspect_files or image_state == SUSPECT:
        verdict = SUSPECT
        for a in broken:
            problems.append("锚点破裂 %s: %s" % (a["id"], a["note"]))
        for k in suspect_files:
            problems.append("文件不可读 %s" % k)
    elif not root_ok or missing or deps_missing or image_state == UNVERIFIED:
        verdict = UNVERIFIED
        if missing:
            problems.append("登记文件缺失: %s" % missing)
        if deps_missing:
            problems.append("锚点依赖缺失: %s" % [x["id"] for x in deps_missing])
    elif dirty:
        verdict = DRIFT
        problems.append("字节漂移但语义锚点全在（镜像可复现链已被破坏，须人工 diff + 显式 re-baseline）: %s" % dirty)
    else:
        verdict = MATCH

    return {
        "tool": "check_v112_image_baseline.py",
        "verdict": verdict,
        "ship_verdict": "NOT_SHIPPABLE",
        "live_hardware_accessed": False,
        "root_is_mounted_rootfs": root_ok,
        "image_pin_state": image_state,
        "recorded_at": data.get("baseline", {}).get("recorded_at"),
        "proves": data.get("scope", {}).get("proves"),
        "not_proof_of": data.get("scope", {}).get("not_proof_of", []),
        "files": file_states,
        "anchors": anchor_states,
        "problems": problems,
        "contract_sha256": sha256_of(CONTRACT),
        "scope": "V112 镜像 rootfs 相对 baseline 时点的字节+语义一致性；不验硬件、不追溯历史、不作签收",
    }


# ---------------------------------------------------------------------------
# synthetic fixture for --selftest (textually DIFFERENT from the real image)
# ---------------------------------------------------------------------------

FIXTURE: dict[str, str] = {
    "etc/fstab": (
        "# synthetic fixture -- textually different, semantically equivalent\n"
        "UUID=aaaa0000-test-fixture-0000-bbbb / ext4 defaults,,commit=120,errors=remount-ro 0 1\n"
        "tmpfs /tmp tmpfs defaults,nosuid 0 0\n"
    ),
    "boot/extlinux/extlinux.conf": (
        "default fixture\ntimeout 9\nmenu title SYNTHETIC\n"
        "label fixture\n  linux /boot/vmlinuz-fixture\n  initrd /boot/initrd-fixture\n"
        "  fdt /boot/dtb/fixture.dtb\n"
        "  fdtoverlays /x/rk3568-uart2-m0.dtbo /x/rk3568-i2c3-pihat.dtbo "
        "/x/rk3568-aic3104-i2c3.dtbo /x/rk3568-radxa-zero3-rpi-camera-v2.dtbo "
        "/x/rk3568-npu-enable.dtbo /x/rk3568-i2c4-m0.dtbo\n"
        "  append root=UUID=aaaa0000 extraflag rootwait rw console=tty1 consoleblank=0 cma=256M\n"
    ),
    "etc/NetworkManager/system-connections/Microduck-Setup.nmconnection": (
        "[connection]\nid=Microduck-kissqy\ntype=wifi\ninterface-name=wlan0\nautoconnect=false\n"
        "[wifi]\nmode=ap\nssid=Microduck-kissqy\nsecurity=802-11-wireless-security\nband=bg\n"
        "[wifi-security]\nkey-mgmt=wpa-psk\npsk=fixture-placeholder-not-a-secret\n"
        "[ipv4]\nmethod=shared\naddress1=10.42.0.1/24\n"
        "[ipv6]\nmethod=disabled\n"
    ),
    "etc/systemd/system/microduck-setup.service": (
        "[Unit]\nDescription=synthetic onboarding\n[Service]\nType=simple\n"
        "ExecStart=/usr/bin/python3 /usr/local/libexec/microduck-setup-portal.py --serve wlan0\n"
        "Restart=on-failure\nRestartSec=8\nNoNewPrivileges=no\n"
        "[Install]\nWantedBy=multi-user.target\n"
    ),
    "usr/local/libexec/microduck-setup-portal.py": (
        "from http.server import ThreadingHTTPServer\n"
        "SETUP_IP = '10.42.0.1'\nPORT = 8088\nCAPTIVE_HTTP_PORT = 80\n"
        "def main():\n    server = ThreadingHTTPServer((SETUP_IP, PORT), Handler)\n"
    ),
    "etc/systemd/journald.conf": (
        "# synthetic main config: every line is a comment\n# Storage=auto\n# SystemMaxUse=\n"
    ),
    "etc/systemd/journald.conf.d/10-robot.conf": (
        "[Journal]\nStorage=persistent\nSystemMaxUse=200M\nSystemMaxFileSize=20M\n"
        "SystemMaxFiles=10\nMaxRetentionSec=3month\nCompress=yes\nForwardToSyslog=no\n"
    ),
    "etc/systemd/system/btd.service": (
        "# synthetic BLE front door\n# It stays UNPRIVILEGED on purpose.\n"
        "# On the Radxa, hci0 does not exist until ~73s after power-on.\n"
        "[Unit]\nDescription=fixture btd\n[Service]\nExecStart=/bin/true\n"
    ),
    "etc/systemd/system/padd.service": (
        "# synthetic pad client\n# on this board hci0 does not exist until roughly 73 seconds after power-on\n"
        "[Unit]\nDescription=fixture padd\n[Service]\nExecStart=/bin/true\n"
    ),
    "etc/systemd/system/mediad.service": "[Unit]\nDescription=fixture mediad\n[Service]\nExecStart=/bin/true\n",
    "etc/robot/feetech-ft5/robotd.toml": (
        "[\"bus\"]\n\"port\" = \"/dev/ttyS2\"\n\"hz\" = 50\n"
    ),
    "etc/systemd/system/robotd.service.d/zzzz-r17-0151.conf": (
        "[Service]\nExecStart=\n"
        "ExecStart=/opt/robotd --socket /run/robotd.sock --port /dev/ttyS2 --commissioning\n"
        "DeviceAllow=/dev/ttyS2 rw\nRestart=always\nRestartSec=2s\n"
        "TimeoutStartSec=30s\nPrivateDevices=no\n"
    ),
    "etc/systemd/system/robotd.service": "[Unit]\nDescription=fixture robotd\n[Service]\nExecStart=/bin/true\n",
    "etc/systemd/system/tofd.service": "[Unit]\nDescription=fixture tofd\n",
    "etc/systemd/system/robot-boot-check.service": "[Unit]\nDescription=fixture bootcheck\n",
    "etc/microduck-v112-image.txt": (
        "synthetic marker\n原包 sha256: 0000fixture\n"
        "overlays=uart2-m0 i2c4-m0; no-camera=0 no-tof=0\n"
        "换引导后改 overlay 要改 extlinux.conf，armbianEnv.txt 不再生效。\n"
    ),
}

EXTRA_UNITS = [
    "aic3104-init.service", "configd.service", "updaterd.service",
    "gamesir-xboxd.service", "microduck-setup-setup.service",
    "dbus-org.bluez.service", "robot-boot-check-dummy.service",
]


def build_fixture(root: Path) -> None:
    for rel, text in FIXTURE.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    unit_dir = root / "etc/systemd/system"
    for name in EXTRA_UNITS:
        (unit_dir / name).write_text("[Unit]\nDescription=synthetic extra\n", encoding="utf-8")
    # expected_subset units that FIXTURE does not already create
    for name in ["robotd.service", "mediad.service", "tofd.service", "padd.service",
                 "btd.service", "microduck-setup.service", "robot-boot-check.service"]:
        p = unit_dir / name
        if not p.exists():
            p.write_text("[Unit]\nDescription=synthetic\n", encoding="utf-8")
    mask = unit_dir / "serial-getty@ttyS2.service"
    if mask.exists() or mask.is_symlink():
        mask.unlink()
    mask.symlink_to("/dev/null")


def inject_contract(data: dict, root: Path) -> dict:
    """Re-record hashes against the FIXTURE (criteria stay external).

    A missing file keeps its recorded hash on purpose: negative control 8
    deliberately removes btd.service, and the contract injector must not crash
    before check() gets to report UNVERIFIED / SUSPECT. Caught by the first real
    --selftest run (FileNotFoundError).
    """
    d = copy.deepcopy(data)
    for f in d["files"]:
        p = root / f["path"]
        if p.is_file():
            f["sha256"] = sha256_of(p)
            f["size_bytes"] = p.stat().st_size
    return d


def selftest() -> int:
    data = load()
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    def must_fail(name: str, mutate) -> None:
        bad = copy.deepcopy(data)
        mutate(bad)
        ck(name, bool(validate(bad)))

    base_problems = validate(data)
    ck("盘上契约结构自校验通过", not base_problems, "; ".join(base_problems[:3]))
    ck("四态结论齐备", all(s in data["scope_semantics"] for s in (MATCH, DRIFT, SUSPECT, UNVERIFIED)))
    ck("scope 明确未碰硬件", data["scope"]["live_hardware_accessed"] is False)
    ck("ship_verdict 恒 NOT_SHIPPABLE", data["scope"]["ship_verdict"] == "NOT_SHIPPABLE")
    ck("契约不复写 psk 明文（正向断言：不存在 psk=<值> 形态）",
       not re.search(r"psk\s*[:=]\s*[\"']?[A-Za-z0-9]{6,}",
                     json.dumps(data, ensure_ascii=False)))
    ck("镜像 pin 为 64 位小写 hex", bool(re.fullmatch(r"[0-9a-f]{64}", data["image"]["sha256"])))
    ck("登记 16 个 rootfs 文件", len(data["files"]) == 16, "n=%d" % len(data["files"]))
    ck("语义锚点数 >= 20", len(data["semantic_anchors"]) >= 20,
       "n=%d" % len(data["semantic_anchors"]))

    must_fail("负对照：删掉全部语义锚点必红", lambda d: d.update({"semantic_anchors": []}))
    must_fail("负对照：sha256 非 hex 必红", lambda d: d["files"][0].update({"sha256": "z" * 64}))
    must_fail("负对照：sha256 长度不足必红", lambda d: d["files"][0].update({"sha256": "0" * 63}))
    must_fail("负对照：file path 越界必红", lambda d: d["files"][0].update({"path": "../../etc/passwd"}))
    must_fail("负对照：file path 绝对路径必红", lambda d: d["files"][0].update({"path": "/etc/fstab"}))
    must_fail("负对照：删 recorded_at 必红", lambda d: d["baseline"].pop("recorded_at"))
    must_fail("负对照：ship_verdict 改 SHIPPABLE 必红", lambda d: d["scope"].update({"ship_verdict": "SHIPPABLE"}))
    must_fail("负对照：live_hardware_accessed 改 true 必红",
              lambda d: d["scope"].update({"live_hardware_accessed": True}))
    must_fail("负对照：锚点引用不存在的文件必红",
              lambda d: d["semantic_anchors"][0].update({"file": "GHOST"}))
    must_fail("负对照：重复锚点 id 必红",
              lambda d: d["semantic_anchors"].append(copy.deepcopy(d["semantic_anchors"][0])))
    must_fail("负对照：未知锚点类型必红",
              lambda d: d["semantic_anchors"][0].update({"kind": "bare_substring"}))
    must_fail("负对照：镜像 sha 改错必红", lambda d: d["image"].update({"sha256": "f" * 64}))
    must_fail("负对照：抹掉 rebaseline 显式策略必红",
              lambda d: d["baseline"].update({"rebaseline_policy": "just do it"}))
    must_fail("负对照：删掉 negative_controls 必红", lambda d: d.update({"negative_controls": []}))
    must_fail("负对照：rootfs offset 改错必红",
              lambda d: d["image"].update({"rootfs_offset_bytes": 1048576}))

    # parser unit checks (real semantics, not vacuous)
    ck("解析 TOML 带引号键", parse_kv('"port" = "/dev/ttyS2"\n"hz" = 50').get("port") == ["/dev/ttyS2"])
    ck("解析 systemd 重复键", parse_kv("DeviceAllow=/dev/ttyS2 rw\nDeviceAllow=char-alsa rw")
       .get("DeviceAllow") == ["/dev/ttyS2 rw", "char-alsa rw"])
    ck("fstab 双逗号解析出空选项", "defaults,,commit=120".split(",")[1] == "")
    ck("注释行不算生效 kv", not parse_kv("# Storage=auto\n# comment\n"))

    with tempfile.TemporaryDirectory(prefix="md_v112_") as td:
        root = Path(td)
        build_fixture(root)
        inj = inject_contract(data, root)
        rep = check(inj, root)
        ck("正对照：合成 rootfs 全部锚点通过 → BASELINE_MATCH", rep["verdict"] == MATCH,
           "%s / %s" % (rep["verdict"], rep["problems"][:2]))
        ck("正对照：合成 fixture 文本与真实镜像不同（防复制式假绿）",
           sha256_of(root / "etc/fstab") != data["files"][0]["sha256"])
        ck("正对照：锚点全绿数量 == 契约锚点数",
           sum(1 for a in rep["anchors"] if a["state"] == "ok") == len(data["semantic_anchors"]),
           "%d/%d" % (sum(1 for a in rep["anchors"] if a["state"] == "ok"), len(data["semantic_anchors"])))

        # --- negative controls that really mutate state ---
        fstab = root / "etc/fstab"
        orig_fstab = fstab.read_bytes()

        # 1) pure byte drift, anchors intact -> DRIFT (never green)
        fstab.write_bytes(orig_fstab + b"\n")
        ck("负对照①：fstab 追加一字节 → DRIFT_UNCONFIRMED（非 MATCH）",
           check(inj, root)["verdict"] == DRIFT, check(inj, root)["verdict"])
        fstab.write_bytes(orig_fstab)

        # 2) semantic break WITH re-recorded hash -> SUSPECT (proves hash alone is not enough)
        fstab.write_text(orig_fstab.decode().replace("commit=120", "commit=5"), encoding="utf-8")
        inj2 = inject_contract(data, root)
        r2 = check(inj2, root)
        ck("负对照②：commit=120→5 且同步更新 hash → COVERAGE_SUSPECT（纯 hash 不足）",
           r2["verdict"] == SUSPECT and any("A_FSTAB_ROOT_OPTIONS" in p for p in r2["problems"]),
           r2["verdict"])
        fstab.write_bytes(orig_fstab)

        # 3) cmdline gains console=ttyS2 -> SUSPECT
        ext = root / "boot/extlinux/extlinux.conf"
        orig_ext = ext.read_text(encoding="utf-8")
        ext.write_text(orig_ext.replace("console=tty1", "console=tty1 console=ttyS2"), encoding="utf-8")
        inj3 = inject_contract(data, root)
        r3 = check(inj3, root)
        ck("负对照③：append 加 console=ttyS2 → COVERAGE_SUSPECT",
           r3["verdict"] == SUSPECT and any("A_CMDLINE_NO_TTYS2" in p for p in r3["problems"]),
           r3["verdict"])
        ext.write_text(orig_ext, encoding="utf-8")

        # 4) AP psk emptied -> SUSPECT (and no plaintext leaked in output)
        ap = root / "etc/NetworkManager/system-connections/Microduck-Setup.nmconnection"
        orig_ap = ap.read_text(encoding="utf-8")
        ap.write_text(re.sub(r"^psk=.*$", "psk=", orig_ap, flags=re.M), encoding="utf-8")
        inj4 = inject_contract(data, root)
        r4 = check(inj4, root)
        ck("负对照④：psk 置空 → COVERAGE_SUSPECT", r4["verdict"] == SUSPECT, r4["verdict"])
        ap.write_text(orig_ap, encoding="utf-8")

        # 5) remove an overlay -> SUSPECT
        ext.write_text(orig_ext.replace("/x/rk3568-i2c4-m0.dtbo", ""), encoding="utf-8")
        r5 = check(inject_contract(data, root), root)
        ck("负对照⑤：删掉 i2c4-m0 overlay → COVERAGE_SUSPECT",
           r5["verdict"] == SUSPECT and any("A_OVERLAYS" in p for p in r5["problems"]), r5["verdict"])
        ext.write_text(orig_ext, encoding="utf-8")

        # 6) unmask serial getty -> SUSPECT
        mask = root / "etc/systemd/system/serial-getty@ttyS2.service"
        mask.unlink()
        mask.write_text("[Unit]\nDescription=unmasked\n", encoding="utf-8")
        r6 = check(inject_contract(data, root), root)
        ck("负对照⑥：serial-getty mask 被拆 → COVERAGE_SUSPECT",
           r6["verdict"] == SUSPECT and any("A_SERIAL_MASK" in p for p in r6["problems"]), r6["verdict"])
        mask.unlink()
        mask.symlink_to("/dev/null")

        # 7) journal dir created -> SUSPECT
        jdir = root / "var/log/journal"
        jdir.mkdir(parents=True, exist_ok=True)
        r7 = check(inject_contract(data, root), root)
        ck("负对照⑦：创建 var/log/journal → COVERAGE_SUSPECT",
           r7["verdict"] == SUSPECT and any("A_JOURNAL_DIR_ABSENT" in p for p in r7["problems"]),
           r7["verdict"])
        jdir.rmdir()

        # 8) delete btd.service -> SUSPECT
        btd = root / "etc/systemd/system/btd.service"
        btd.rename(root / "btd.hidden")
        r8 = check(inject_contract(data, root), root)
        ck("负对照⑧：删掉 btd.service → COVERAGE_SUSPECT",
           r8["verdict"] == SUSPECT and any("A_SERVICE_SET" in p for p in r8["problems"]), r8["verdict"])
        (root / "btd.hidden").rename(btd)

        # 9) missing registered file -> UNVERIFIED (CI clean checkout)
        (root / "etc/microduck-v112-image.txt").unlink()
        r9 = check(inject_contract(data, root), root)
        ck("负对照⑨：登记文件缺失 → UNVERIFIED（不冒充 PASS）",
           r9["verdict"] == UNVERIFIED, r9["verdict"])
        (root / "etc/microduck-v112-image.txt").write_text(FIXTURE["etc/microduck-v112-image.txt"],
                                                            encoding="utf-8")

        # 10) totally empty root -> UNVERIFIED, never green
        empty = root / "empty_root"
        empty.mkdir(exist_ok=True)
        r10 = check(inject_contract(data, root), empty)
        ck("负对照⑩：空 root（未挂载 / CI）→ UNVERIFIED 且 problems 非空",
           r10["verdict"] == UNVERIFIED and bool(r10["problems"]), r10["verdict"])

        # 11) image pin mismatch -> SUSPECT
        fake_img = root / "fake.img"
        fake_img.write_bytes(b"not the real image")
        r11 = check(inject_contract(data, root), root, fake_img)
        ck("负对照⑪：镜像 sha 不符 pin → COVERAGE_SUSPECT",
           r11["verdict"] == SUSPECT and any("pin" in p for p in r11["problems"]), r11["verdict"])

        # 12) valid image pin is accepted (positive control for the optional input)
        good_img = root / "good.img"
        good_img.write_bytes(b"x" * 16)
        good_data = inject_contract(data, root)
        good_data["image"]["sha256"] = sha256_of(good_img)
        good_data["image"]["size_bytes"] = good_img.stat().st_size
        r12 = check(good_data, root, good_img)
        ck("正对照：镜像 pin 一致 → image_pin_state=MATCH",
           r12["image_pin_state"] == MATCH and r12["verdict"] == MATCH, r12["verdict"])

    for name, ok, note in checks:
        print("  %s %s%s" % ("ok  " if ok else "FAIL", name, ((" -- " + note) if note and not ok else "")))
    bad = [n for n, ok, _ in checks if not ok]
    print("\ncheck_v112_image_baseline selftest: %d/%d passed" % (len(checks) - len(bad), len(checks)))
    if bad:
        print("FAILED: " + "; ".join(bad))
        return 1
    print("scope: V112 镜像 rootfs 相对 baseline 时点的一致性；不验硬件、不追溯历史、不签收。")
    print("verdict: PASS")
    print("self-test: PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="verify a read-only mounted rootfs against baseline")
    ap.add_argument("--selftest", action="store_true", help="synthetic rootfs fixtures + negative controls")
    ap.add_argument("--list", action="store_true", help="list registered files and anchors")
    ap.add_argument("--json", action="store_true", help="emit JSON (with --check)")
    ap.add_argument("--root", default="/root/v112inspect", help="read-only mounted rootfs path")
    ap.add_argument("--image", default="", help="optional: image file to verify the sha pin against")
    ap.add_argument("--rebaseline", action="store_true", help="capture current rootfs bytes as new baseline")
    ap.add_argument("--confirm", action="store_true", help="required with --rebaseline")
    ap.add_argument("--reason", default="", help="required audited reason with --rebaseline")
    args = ap.parse_args()
    data = load()

    if args.selftest:
        return selftest()
    if args.list:
        print("registered files = %d" % len(data["files"]))
        for f in data["files"]:
            print("  %-18s %-18s %s" % (f["id"], f["kind"], f["path"]))
        print("semantic anchors = %d" % len(data["semantic_anchors"]))
        for a in data["semantic_anchors"]:
            print("  %-28s %s" % (a["id"], a["kind"]))
        print("negative controls = %d" % len(data["negative_controls"]))
        return 0

    if args.rebaseline:
        problems = validate(data)
        if problems:
            print("[REFUSE] contract invalid: " + "; ".join(problems), file=sys.stderr)
            return 2
        if not (args.confirm and args.reason.strip()):
            print("[REFUSE] --rebaseline requires --confirm --reason <audited reason>", file=sys.stderr)
            return 2
        root = Path(args.root)
        rep = check(data, root)
        old = data.get("baseline", {})
        previous = {
            "at": old.get("recorded_at"),
            "sha256": {f["id"]: f["sha256"] for f in data["files"]},
            "size_bytes": {f["id"]: f["size_bytes"] for f in data["files"]},
            "verdict_before_rebaseline": rep["verdict"],
            "reason": args.reason.strip(),
        }
        for f in data["files"]:
            p = root / f["path"]
            if p.is_file():
                f["sha256"], f["size_bytes"] = sha256_of(p), p.stat().st_size
        if rep["verdict"] == SUSPECT:
            previous["anchor_broken_accepted"] = True
            previous["warning"] = "在锚点破裂状态下强行接受，须人工确认非镜像污染"
        now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
        history = old.get("history", [])
        history.append(previous)
        data["baseline"]["recorded_at"] = now
        data["baseline"]["recorded_by"] = "显式 --rebaseline --confirm；理由见 history[-1].reason"
        data["baseline"]["history"] = history
        CONTRACT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("re-baseline 写入 %s（未触碰镜像与 rootfs）" % CONTRACT.name)
        print("recorded_at = %s" % now)
        print("verdict_before_rebaseline = %s" % rep["verdict"])
        return 0

    if not args.check:
        ap.print_help()
        return 2

    problems = validate(data)
    if problems:
        print("[REFUSE] contract invalid: " + "; ".join(problems), file=sys.stderr)
        return 2
    image = Path(args.image) if args.image else None
    rep = check(data, Path(args.root), image)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("verdict = %s" % rep["verdict"])
        print("ship_verdict = %s" % rep["ship_verdict"])
        print("recorded_at = %s" % rep["recorded_at"])
        print("root_is_mounted_rootfs = %s" % rep["root_is_mounted_rootfs"])
        print("image_pin_state = %s" % rep["image_pin_state"])
        print("proves: %s" % rep["proves"])
        for fid, info in rep["files"].items():
            if info["state"] == MATCH:
                print("  [MATCH]       %-18s %s" % (fid, info["path"]))
            elif info["state"] == DRIFT:
                print("  [DRIFT?]      %-18s hash/size 变了 %s" % (fid, info["path"]))
            elif info["state"] == SUSPECT:
                print("  [SUSPECT]     %-18s %s" % (fid, info.get("note", "")))
            else:
                print("  [UNVERIFIED]  %-18s %s" % (fid, info["path"]))
        for a in rep["anchors"]:
            mark = "ok" if a["state"] == "ok" else ("MISSING" if a["state"] == UNVERIFIED else "BROKEN")
            print("  [anchor %-9s] %-28s %s" % (mark, a["id"], a["note"]))
        for prob in rep["problems"]:
            print("  PROBLEM: %s" % prob)
        print("scope: " + rep["scope"])
        print("live_hardware_accessed = false")
        print("not proof of: " + "; ".join(rep["not_proof_of"]))
    return 0 if rep["verdict"] == MATCH else 1


if __name__ == "__main__":
    sys.exit(main())
