"""Regression tests for the P0-2 roller policy contract.

CPU-only, stdlib-only, no robot. A catalog entry is not a downloaded ONNX,
a QEMU ARM64 inference audit is not a board acceptance, and a green offline
gate is never a sign-off.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
HERE = ROOT / "tools" / "hd1910"
sys.path.insert(0, str(HERE))


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rp = _load("check_roller_policy_test", HERE / "check_roller_policy.py")


def _authorities():
    return (rp.load(rp.LABELS), rp.load(rp.CLOSURE), rp.load(rp.CHAIN))


def test_contract_structure_and_cross_contract_links():
    data = rp.load()
    labels, closure, chain = _authorities()
    assert not rp.validate(data, labels, closure, chain)
    assert data["status"] == "UNVERIFIED"
    assert data["line"] == labels["policy"]["current_line"]
    assert data["deploy_chain"]["chain_id"] in chain["required"]["chain_ids"]
    assert any(c["id"] == data["closure_ref"] and c["status"] == "UNVERIFIED"
               for c in closure["contracts"])
    assert set(data["policy_catalog"]["kissqy_v167"]["ids"]) \
        == set(data["required"]["kissqy_roller_ids"])


def test_no_single_authoritative_action_scale():
    data = rp.load()
    labels, closure, chain = _authorities()
    conflict = data["action_scale_conflict"]
    assert conflict["resolution"] == "UNRESOLVED"
    assert len(conflict["sources"]) == 2
    claims = " ".join(s["claim"] for s in conflict["sources"])
    assert "0.8" in claims and "1.0" in claims

    def must_fail(mutate):
        bad = copy.deepcopy(data)
        mutate(bad)
        assert rp.validate(bad, labels, closure, chain), "tampered contract accepted"

    must_fail(lambda d: d.update({"status": "PASS"}))
    must_fail(lambda d: d.update({"resolved_action_scale": 0.8}))
    must_fail(lambda d: d["action_scale_conflict"].update({"resolution": "RESOLVED"}))
    must_fail(lambda d: d["action_scale_conflict"]["sources"].pop())
    must_fail(lambda d: d["policy_catalog"]["kissqy_v167"]["ids"].pop())
    must_fail(lambda d: d["policy_catalog"]["other_source_five_names"].update(
        {"different_source": False}))
    must_fail(lambda d: d["deploy_chain"]["forbidden_commands"].pop())
    must_fail(lambda d: d["acceptance"].update({"metric": "请求已发即算通过"}))
    must_fail(lambda d: d["scope"].update({"live_hardware_accessed": True}))


def test_catalog_verification_is_evidence_not_a_skip():
    data = rp.load()
    src = rp.catalog_path()
    if not src.is_file():
        # On a clean CI checkout .upstream is gitignored. An explicit
        # --verify-sources request must then FAIL, never quietly pass.
        assert rp.verify_catalog(data, src), "missing catalog was accepted"
        return
    assert not rp.verify_catalog(data, src)
    rows = json.loads(pathlib.Path(src).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="md_roller_test_") as td:
        for r in rows:
            if r.get("id") == "kissqy-roller_swizzle":
                r["sha256"] = "f" * 64
        fake = pathlib.Path(td) / "catalog.json"
        fake.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        problems = rp.verify_catalog(data, fake)
        assert any("sha256" in x for x in problems), problems
        empty = pathlib.Path(td) / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        assert rp.verify_catalog(data, empty), "empty catalog was accepted"


def test_cli_selftest_check_and_ship_gate():
    script = str(HERE / "check_roller_policy.py")
    selftest = subprocess.run([sys.executable, script, "--selftest"],
                              cwd=str(ROOT), capture_output=True, text=True)
    assert selftest.returncode == 0, selftest.stdout + selftest.stderr
    m = re.search(r"(\d+)/(\d+) passed", selftest.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) >= 20, selftest.stdout

    check = subprocess.run([sys.executable, script, "--check"],
                           cwd=str(ROOT), capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr
    assert "NOT_SHIPPABLE" in check.stdout

    gate = subprocess.run([sys.executable, script, "--check", "--ship-gate"],
                          cwd=str(ROOT), capture_output=True, text=True)
    assert gate.returncode == 1 and "SHIP GATE REFUSED" in gate.stdout

    js = subprocess.run([sys.executable, script, "--check", "--json"],
                        cwd=str(ROOT), capture_output=True, text=True)
    assert js.returncode == 0
    rep = json.loads(js.stdout)
    assert rep["live_hardware_accessed"] is False
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"
    assert rep["status"] == "UNVERIFIED"
    assert rep["action_scale"] == "UNRESOLVED"
