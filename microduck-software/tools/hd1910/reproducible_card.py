#!/usr/bin/env python3
"""B8: reproducible card recipe guard + honest rollback boundary.

Why this exists (2026-11-11, four-source comparison, follow-up B8)
------------------------------------------------------------------
fanhao's two Radxa card scripts are the most reusable "build your own
image" asset we have: they pin the Radxa U-Boot deb sha, the R1 original
sha, the dd sectors, extlinux overlays, and mask the login console off the
servo UART. But a recipe is not a card. And the official Yocto repository
has A/B RAUC signed updates with health-check rollback -- which our 路①
single-partition extlinux card does NOT have. Borrowing a mechanism is not
the same as owning it.

This tool:
  1. validates ONE owner file (card_build_contract.json);
  2. optionally re-reads the two upstream scripts and cross-checks their
     constants (two independent witnesses for the same sha);
  3. audits a proposed flag string and refuses --no-camera / --no-tof,
     because SSOT 订正㉑ pins both camera and ToF as mandatory;
  4. reports rollback as NOT_IMPLEMENTED until it is actually implemented.

It NEVER runs dd, mounts a loop device, writes a TF card, flashes firmware,
or edits an upstream script. Stdlib only.

Usage (cwd = microduck-software):
    .venv-mjlab/Scripts/python.exe tools/hd1910/reproducible_card.py --check
    .venv-mjlab/Scripts/python.exe tools/hd1910/reproducible_card.py --check --json
    .venv-mjlab/Scripts/python.exe tools/hd1910/reproducible_card.py --check --verify-sources .upstream
    .venv-mjlab/Scripts/python.exe tools/hd1910/reproducible_card.py --check --ship-gate
    .venv-mjlab/Scripts/python.exe tools/hd1910/reproducible_card.py --flags "--overlay i2c4-m0"
    .venv-mjlab/Scripts/python.exe tools/hd1910/reproducible_card.py --flags "--no-camera"
    .venv-mjlab/Scripts/python.exe tools/hd1910/reproducible_card.py --flags=--no-camera
    .venv-mjlab/Scripts/python.exe tools/hd1910/reproducible_card.py --selftest

Note: argparse refuses a value starting with `--` in the space-separated
form ("expected one argument", rc=2). normalise_argv() rewrites that shape
into the `--flags=...` form so neither spelling can produce a false rc=2,
which run_all_gates.py classifies as GUARD INVOCATION BROKEN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE = HERE.parents[1]
ROOT = SOFTWARE.parent
CONTRACT = HERE / "card_build_contract.json"
UB_SHA = re.compile(r"^UBOOT_DEB_SHA=([0-9a-f]{64})", re.M)
UB_URL = re.compile(r"^UBOOT_DEB_URL=(\S+)", re.M)
R1_SHA = re.compile(r"^R1_SHA=([0-9a-f]{64})", re.M)
PIN_FIELDS = ("id", "value", "kind", "witnesses", "why")


def load(path: Path = CONTRACT) -> dict:
    return json.loads(io.open(path, encoding="utf-8").read())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def forbidden(data: dict) -> set[str]:
    return {x.get("flag", "") for x in (data.get("forbidden_flags") or [])}


def normalise_argv(argv: list[str]) -> list[str]:
    """Let `--flags "--no-camera"` work as well as `--flags=--no-camera`.

    argparse treats a dash-prefixed token after a space-separated option as
    another option and exits rc=2. That is not a guard verdict -- it is an
    invocation failure, and the project's gate treats rc=2 as a hard FAIL.
    """
    out: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--flags" and i + 1 < len(argv) and argv[i + 1].startswith("-"):
            out.append("--flags=" + argv[i + 1])
            i += 2
        else:
            out.append(a)
            i += 1
    return out


def audit_flags(flag_text: str, data: dict) -> list[str]:
    """Positive assertion only: refuse exactly the declared forbidden flags.

    Deliberately NOT a bare `--no-` prefix match: --overlay / --no-something
    else may be legitimate, and substring rules get bitten by their own
    negative-control text (project rule).
    """
    given = set(flag_text.split())
    return sorted(given & forbidden(data))


def validate(data: dict) -> list[str]:
    p: list[str] = []
    if data.get("schema_version") != 1:
        p.append("schema_version must be 1")
    rule = data.get("rule") or ""
    if "NOT_SHIPPABLE" not in rule or "可复现" not in rule:
        p.append("rule must state that a recipe is not a card")
    scripts = data.get("source_scripts") or []
    pins = data.get("pins") or []
    if not scripts or not pins:
        p.append("empty source_scripts/pins: refusing to call an empty recipe verified")
        return p
    script_ids = [s.get("id") for s in scripts]
    if len(script_ids) != len(set(script_ids)):
        p.append("duplicate source_script ids")
    for s in scripts:
        if not s.get("path") or not s.get("role") or not (s.get("pinned_facts") or []):
            p.append("source_script %s missing path/role/pinned_facts" % s.get("id"))
    pin_ids = [x.get("id") for x in pins]
    if len(pin_ids) != len(set(pin_ids)):
        p.append("duplicate pin ids")
    for x in pins:
        pid = x.get("id", "<no id>")
        for k in PIN_FIELDS:
            if k not in x:
                p.append("%s missing field %s" % (pid, k))
        for w in x.get("witnesses") or []:
            if w not in script_ids:
                p.append("%s references unknown witness %s" % (pid, w))
        if not str(x.get("why") or "").strip():
            p.append("%s empty why" % pid)
    if not (data.get("forbidden_flags") or []):
        p.append("forbidden_flags must not be empty (camera + ToF are mandatory)")
    for f in data.get("forbidden_flags") or []:
        if not f.get("flag") or not f.get("why"):
            p.append("forbidden flag missing flag/why")
    if not (data.get("preconditions") or []):
        p.append("preconditions must not be empty")
    rb = data.get("rollback_contract") or {}
    if not rb.get("borrowed_from") or not rb.get("current_reality"):
        p.append("rollback_contract must record both the borrowed mechanism and current reality")
    if rb.get("status") not in ("NOT_IMPLEMENTED", "IMPLEMENTED", "UNVERIFIED"):
        p.append("rollback_contract.status invalid")
    if rb.get("status") == "IMPLEMENTED" and not (rb.get("evidence") or []):
        p.append("rollback claims IMPLEMENTED without evidence")
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
    """A recipe with an unimplemented rollback and published-only pins is not shippable."""
    if (data.get("rollback_contract") or {}).get("status") != "IMPLEMENTED":
        return "NOT_SHIPPABLE"
    if any(x.get("kind") == "UPSTREAM_PUBLISHED" for x in (data.get("pins") or [])):
        return "NOT_SHIPPABLE"
    if (data.get("signoff") or {}).get("status") != "PASS":
        return "NOT_SHIPPABLE"
    if not (data.get("pins") or []) or not (data.get("source_scripts") or []):
        return "NOT_SHIPPABLE"
    return "SHIPPABLE"


def pins_from_sources(upstream: Path, data: dict) -> dict:
    """Re-read the two scripts and cross-check their constants.

    Missing sources are reported as not verified, never silently skipped.
    """
    out: dict = {"root": str(upstream), "checks": [], "all_ok": False}

    def add(name: str, ok: bool, note: str = "") -> None:
        out["checks"].append({"name": name, "ok": bool(ok), "note": note})

    paths = {}
    for s in data["source_scripts"]:
        rel = Path(*s["path"].split("/")[1:])  # strip the leading .upstream/
        paths[s["id"]] = upstream / rel
    for sid, p in paths.items():
        add("source script present: %s" % sid, p.is_file(), str(p))
    if not all(p.is_file() for p in paths.values()):
        return out

    texts = {k: io.open(v, encoding="utf-8", errors="replace").read()
             for k, v in paths.items()}
    shas = {k: UB_SHA.search(t) for k, t in texts.items()}
    urls = {k: UB_URL.search(t) for k, t in texts.items()}
    add("both scripts pin a U-Boot deb sha", all(m for m in shas.values()))
    vals = [m.group(1) for m in shas.values() if m]
    add("two independent scripts agree on U-Boot sha",
       len(vals) == len(texts) and len(set(vals)) == 1,
       "values=%s" % sorted(set(vals)))
    contract_ub = next((x["value"] for x in data["pins"]
                        if x["id"] == "uboot_deb_sha256"), "")
    add("U-Boot sha matches contract",
       bool(vals) and all(v == contract_ub for v in vals))
    url_vals = [m.group(1) for m in urls.values() if m]
    add("two scripts agree on U-Boot deb URL",
       len(url_vals) == len(texts) and len(set(url_vals)) == 1)
    contract_url = next((x["value"] for x in data["pins"]
                         if x["id"] == "uboot_deb_url"), "")
    add("U-Boot URL matches contract",
       bool(url_vals) and all(v == contract_url for v in url_vals))
    r1m = R1_SHA.search(texts.get("kissqy_r1_v112", ""))
    contract_r1 = next((x["value"] for x in data["pins"]
                        if x["id"] == "r1_original_sha256"), "")
    add("R1 sha from script matches contract",
       bool(r1m) and r1m.group(1) == contract_r1)
    for sid, t in texts.items():
        add("%s writes idbloader @64 / u-boot.itb @16384" % sid,
            "seek=64" in t and "seek=16384" in t)
    add("R1 script enforces root partition >= 32768",
        "32768" in texts.get("kissqy_r1_v112", ""))
    armb = texts.get("build_armbian_card", "")
    add("Armbian script masks servo UART getty and uses console=tty1",
        "serial-getty@ttyS2" in armb and "console=tty1" in armb)
    add("forbidden flags really exist in the R1 script",
        "--no-camera" in texts.get("kissqy_r1_v112", "")
        and "--no-tof" in texts.get("kissqy_r1_v112", ""))
    out["all_ok"] = all(c["ok"] for c in out["checks"])
    return out


def selftest() -> int:
    data = load()
    checks: list[tuple[str, bool, str]] = []

    def ck(name: str, ok: bool, note: str = "") -> None:
        checks.append((name, bool(ok), note))

    base = validate(data)
    ck("盘上配方结构自校验通过", not base, "; ".join(base[:3]))
    ck("当前整体判 NOT_SHIPPABLE", overall_verdict(data) == "NOT_SHIPPABLE")
    ck("回滚如实标 NOT_IMPLEMENTED",
       data["rollback_contract"]["status"] == "NOT_IMPLEMENTED")
    ck("scope 明确未碰硬件", data["scope"]["live_hardware_accessed"] is False)
    ck("正对照：合法 --overlay 不被拒",
       audit_flags("--overlay i2c4-m0", data) == [])
    ck("负对照：--no-camera 必被拒",
       audit_flags("--no-camera", data) == ["--no-camera"])
    ck("负对照：--no-tof 必被拒",
       audit_flags("--no-tof", data) == ["--no-tof"])
    ck("负对照：两个禁用 flag 同时给会全部列出",
       audit_flags("--no-camera --no-tof", data) == ["--no-camera", "--no-tof"])
    ck("负对照：相近但不相同的 --no-camera-debug 不被裸前缀误杀",
       audit_flags("--no-camera-debug --overlay i2c4-m0", data) == [])

    good = copy.deepcopy(data)
    good["rollback_contract"]["status"] = "IMPLEMENTED"
    good["rollback_contract"]["evidence"] = ["selftest synthetic"]
    for x in good["pins"]:
        if x["kind"] == "UPSTREAM_PUBLISHED":
            x["kind"] = "LOCAL_COMPUTED"
    good["signoff"] = {"status": "PASS", "evidence": ["selftest synthetic"]}
    ck("正对照：回滚实装 + 全部本地实算 + 签署则 SHIPPABLE",
       overall_verdict(good) == "SHIPPABLE")
    back = copy.deepcopy(good)
    back["rollback_contract"]["status"] = "NOT_IMPLEMENTED"
    ck("负对照：塞回未实装回滚立刻 NOT_SHIPPABLE",
       overall_verdict(back) == "NOT_SHIPPABLE")

    def must_fail(name: str, mutate) -> None:
        bad = copy.deepcopy(data)
        mutate(bad)
        ck(name, bool(validate(bad)))

    must_fail("负对照：清空 forbidden_flags 必红",
              lambda d: d.update({"forbidden_flags": []}))
    must_fail("负对照：清空 pins 必红", lambda d: d.update({"pins": []}))
    must_fail("负对照：重复 pin id 必红",
              lambda d: d["pins"].append(copy.deepcopy(d["pins"][0])))
    must_fail("负对照：pin 引用不存在的见证脚本必红",
              lambda d: d["pins"][0].update({"witnesses": ["ghost_script"]}))
    must_fail("负对照：回滚无证据称 IMPLEMENTED 必红",
              lambda d: d["rollback_contract"].update({"status": "IMPLEMENTED"}))
    must_fail("负对照：抹掉 rule 语义必红", lambda d: d.update({"rule": "all good"}))
    must_fail("负对照：scope 声称碰过硬件必红",
              lambda d: d["scope"].update({"live_hardware_accessed": True}))
    must_fail("负对照：清掉 preconditions 必红",
              lambda d: d.update({"preconditions": []}))
    must_fail("负对照：清掉 blocked_actions 必红",
              lambda d: d.update({"blocked_actions": []}))
    must_fail("负对照：signoff 无证据称 PASS 必红",
              lambda d: d["signoff"].update({"status": "PASS"}))

    # Real fixture: two scripts with a mismatched U-Boot sha must turn the
    # source cross-check red (not a mocked boolean).
    with tempfile.TemporaryDirectory(prefix="md_card_") as td:
        tmp = Path(td)
        radxa = tmp / "replica" / "tools" / "radxa"
        radxa.mkdir(parents=True)
        good_sha = next(x["value"] for x in data["pins"] if x["id"] == "uboot_deb_sha256")
        good_url = next(x["value"] for x in data["pins"] if x["id"] == "uboot_deb_url")
        good_r1 = next(x["value"] for x in data["pins"] if x["id"] == "r1_original_sha256")
        common = ("UBOOT_DEB_URL=%s\nUBOOT_DEB_SHA=%s\n"
                  "dd if=x of=y bs=512 seek=64\n"
                  "dd if=x of=y bs=512 seek=16384\n"
                  "console=tty1\nserial-getty@ttyS2\n" % (good_url, good_sha))
        (radxa / "build-armbian-card.sh").write_text(common, encoding="utf-8")
        (radxa / "kissqy-r1-v112.sh").write_text(
            common + "R1_SHA=%s\n32768\n--no-camera\n--no-tof\n" % good_r1,
            encoding="utf-8")
        ok = pins_from_sources(tmp, data)
        ck("真对照：两脚本常量一致时源互证通过",
           ok["all_ok"] is True, "checks=%d" % len(ok["checks"]))
        bad_sha = "0" * 64
        (radxa / "kissqy-r1-v112.sh").write_text(
            common.replace(good_sha, bad_sha)
            + "R1_SHA=%s\n32768\n--no-camera\n--no-tof\n" % good_r1,
            encoding="utf-8")
        res = pins_from_sources(tmp, data)
        ck("负对照：任一脚本 U-Boot sha 被改必红",
           res["all_ok"] is False
           and any("agree on U-Boot sha" in c["name"] and not c["ok"]
                   for c in res["checks"]))

    # CLI real runs: only testing audit_flags() in-process would miss the
    # argparse rc=2 trap. Both spellings must give a real refusal (rc=1),
    # and a legitimate overlay must stay rc=0.
    script = str(HERE / "reproducible_card.py")
    cli_space = subprocess.run(
        [sys.executable, script, "--check", "--flags", "--no-camera"],
        cwd=str(SOFTWARE), capture_output=True, text=True)
    ck("真对照：CLI 空格写法 --flags --no-camera 必 rc=1 而非 rc=2",
       cli_space.returncode == 1 and "forbidden flags refused" in cli_space.stdout,
       "rc=%d" % cli_space.returncode)
    cli_eq = subprocess.run(
        [sys.executable, script, "--check", "--flags=--no-camera"],
        cwd=str(SOFTWARE), capture_output=True, text=True)
    ck("真对照：CLI 等号写法同样 rc=1", cli_eq.returncode == 1)
    cli_ok = subprocess.run(
        [sys.executable, script, "--check", "--flags", "--overlay i2c4-m0"],
        cwd=str(SOFTWARE), capture_output=True, text=True)
    ck("真对照：CLI 合法 --overlay 仍 rc=0", cli_ok.returncode == 0,
       "rc=%d" % cli_ok.returncode)

    for name, ok, note in checks:
        print("  [%s] %s%s" % ("ok" if ok else "XX", name, ("  <- " + note) if note else ""))
    bad_n = [n for n, ok, _ in checks if not ok]
    print("\nreproducible_card selftest: %d/%d passed" % (len(checks) - len(bad_n), len(checks)))
    if bad_n:
        print("FAILED: " + "; ".join(bad_n))
        return 1
    print("scope: recipe + flag audit only; no dd, no TF card, no flashing, no upstream edits.")
    print("self-test: PASS")
    return 0


def report(data: dict, problems: list[str], sources: dict | None) -> dict:
    return {
        "tool": "reproducible_card.py",
        "contract_sha256": sha256_of(CONTRACT),
        "source_scripts": [s["id"] for s in data["source_scripts"]],
        "pins": [x["id"] for x in data["pins"]],
        "forbidden_flags": sorted(forbidden(data)),
        "rollback_status": data["rollback_contract"]["status"],
        "problems": problems,
        "structure_verdict": "PASS" if not problems else "FAIL",
        "ship_verdict": overall_verdict(data),
        "source_files_verified": bool(sources and sources.get("all_ok")),
        "source_verification": sources,
        "live_hardware_accessed": False,
        "not_proof_of": data["scope"]["not_proof_of"],
        "known_gaps": data["scope"]["known_gaps"],
        "scope": "可复现做卡配方与禁用 flag 审计；回滚是借用目标不是路① 现状",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the on-disk recipe")
    ap.add_argument("--selftest", action="store_true", help="run negative controls")
    ap.add_argument("--ship-gate", action="store_true",
                    help="with --check, rc=1 unless the recipe is fully closed")
    ap.add_argument("--verify-sources", metavar="DIR", default=None,
                    help="cross-check constants against a local .upstream directory")
    ap.add_argument("--flags", default=None, metavar="TEXT",
                    help="audit a proposed flag string; forbidden flags give rc=1")
    ap.add_argument("--json", action="store_true", help="emit a machine-readable report")
    args = ap.parse_args(normalise_argv(sys.argv[1:]))

    if args.selftest:
        return selftest()

    data = load()
    problems = validate(data)
    sources = None
    if args.verify_sources:
        sources = pins_from_sources(Path(args.verify_sources), data)
        if not sources.get("all_ok"):
            problems.append("source cross-check failed: see source_verification.checks")
    refused = audit_flags(args.flags or "", data) if args.flags is not None else []
    if refused:
        problems.append("forbidden flags refused: %s" % ", ".join(refused))
    rep = report(data, problems, sources)
    rep["refused_flags"] = refused
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("card_build_contract.json sha256 = " + rep["contract_sha256"])
        print("source scripts = " + ", ".join(rep["source_scripts"]))
        print("pins = %d  forbidden flags = %s" %
              (len(rep["pins"]), ", ".join(rep["forbidden_flags"])))
        print("rollback status = " + rep["rollback_status"] + " (borrowed, not owned)")
        print("source_files_verified = %s" % str(rep["source_files_verified"]).lower())
        if args.flags is not None:
            print("audited flags = %r  refused = %s" % (args.flags, refused or "none"))
        for x in problems:
            print("  [FAIL] " + x)
        print("structure_verdict = " + rep["structure_verdict"])
        print("ship verdict = " + rep["ship_verdict"])
        print("live_hardware_accessed = false")
        print("scope: " + rep["scope"])

    if problems:
        return 1
    if args.ship_gate and rep["ship_verdict"] != "SHIPPABLE":
        if not args.json:
            print("SHIP GATE REFUSED: rollback not implemented / published-only pins")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
