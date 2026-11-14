"""CLI regression tests for check_v112_image_baseline.py (candidate 9, 2026-11-14).

Why this exists
---------------
This repo has been bitten twice by the same silent failure: "50 unit tests
green while the CLI dies at argparse rc=2" (tests/test_hd1910_tooling.py:714),
and "only internal functions tested, never the CLI entry point"
(live_viewer, see tests/test_live_viewer_cli.py). The V112 baseline tool has a
10-flag argparse surface plus an audited --rebaseline write path, so a green
selftest alone proves nothing about the shipped command line.

Design (stdlib-only, no image / no mount / no hardware / no network)
--------------------------------------------------------------------
* Every assertion runs the tool as a REAL subprocess (`sys.executable TOOL
  <args>`), never by importing its functions.
* Criteria are EXTERNAL: the flag whitelist is hardcoded here, file/anchor
  lower bounds are hardcoded here, and --list numbers are cross-checked
  against the contract JSON read independently by this test. Nothing is
  scraped out of the tool under test.
* Flag presence uses a TOKEN-BOUNDARY regex, not a bare substring (rule 8/10:
  a compound `--json-verbose` must not mask a deleted `--json`).
* Negative controls copy BOTH the tool and the contract into tmp_path and
  tamper the COPIES. That matters: --rebaseline writes to
  `HERE/v112_image_baseline.json`, so a tampered script that loses its
  --confirm guard can only ever rewrite the COPY, never the repo contract.
* Positive control: an empty --root must be UNVERIFIED with rc!=0. A clean CI
  checkout has no mounted rootfs; silently returning MATCH there would be the
  exact "COLLECTED != PASS" false green this project forbids.

These tests pass under both the lean CI python and .venv-mjlab (pytest 9.1.1).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
HD = HERE / "tools" / "hd1910"
TOOL = HD / "check_v112_image_baseline.py"
CONTRACT = HD / "v112_image_baseline.json"
PY = sys.executable

# External contract truth. NOT derived from the tool's --help output.
EXPECTED_FLAGS = (
    "--check", "--selftest", "--list", "--json", "--root", "--image",
    "--rebaseline", "--confirm", "--reason", "--help",
)
# Lower bounds are independent of the contract: if someone empties the
# baseline, both sides shrinking together must not self-certify.
# 2026-11-14 correction: a verbal "24/24 anchors" in the previous turn was a
# NUMBER CROSS-CONTAMINATION from unrelated 24/24 tallies (C2+, B2 selftest,
# check_closure). First-hand truth: contract semantic_anchors has 23 entries
# and the real V112.img --check reports 23/23 ok. Criterion corrected to 23.
MIN_REGISTERED_FILES = 16
MIN_SEMANTIC_ANCHORS = 23
# Independent whitelist: a trimmed contract must not pass on a mere count.
REQUIRED_ANCHOR_IDS = frozenset({
    "A_FSTAB_ROOT_OPTIONS", "A_CMDLINE_NO_TTYS2", "A_AP_PSK_PRESENT",
    "A_JOURNAL_DROPIN", "A_SERVICE_SET", "A_SERIAL_MASK",
})


def _flag_re(flag: str) -> re.Pattern:
    return re.compile(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])")


FLAG_RES = {f: _flag_re(f) for f in EXPECTED_FLAGS}


def run(script: Path, *args: str, cwd: Path = HERE) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(script), *args], cwd=str(cwd),
        capture_output=True, text=True, encoding="utf-8", timeout=90,
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """Copy tool + contract into an isolated dir; return (tool, contract)."""
    t = tmp_path / "check_v112_image_baseline.py"
    c = tmp_path / "v112_image_baseline.json"
    shutil.copy2(TOOL, t)
    shutil.copy2(CONTRACT, c)
    return t, c


def tamper(tool: Path, old: str, new: str, name: str) -> Path:
    """Write a broken COPY; assert the anchor exists so source drift fails loud."""
    src = tool.read_text(encoding="utf-8")
    assert old in src, "tamper anchor not found -- source drifted, fix the test"
    dst = tool.with_name(name)
    dst.write_text(src.replace(old, new, 1), encoding="utf-8")
    return dst


def empty_root_properly_refused(script: Path, root: Path) -> bool:
    """Reusable verdict: an unmounted root must be refused, not silently passed."""
    r = run(script, "--check", "--root", str(root))
    return r.returncode != 0 and "verdict = UNVERIFIED" in r.stdout


def cli_surface_problems(script: Path) -> list[str]:
    """Pure over `script` so negative controls point at tampered copies."""
    problems: list[str] = []
    h = run(script, "--help")
    if h.returncode != 0:
        problems.append("--help rc=%d (expected 0)" % h.returncode)
    else:
        for flag in EXPECTED_FLAGS:
            if not FLAG_RES[flag].search(h.stdout):
                problems.append("--help missing declared flag %s" % flag)
    return problems


# ---------------------------------------------------------------------------
# positive controls: real shipped CLI
# ---------------------------------------------------------------------------

def test_help_surface_is_intact():
    assert cli_surface_problems(TOOL) == [], cli_surface_problems(TOOL)


def test_selftest_really_runs_and_prints_pass():
    """Not just argparse: the shipped command must complete its own 42 checks."""
    r = run(TOOL, "--selftest")
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-500:]
    assert "verdict: PASS" in r.stdout
    assert "self-test: PASS" in r.stdout
    # A green selftest must actually contain negative controls, not only OKs.
    assert re.search(r"负对照[①-⑳\d]", r.stdout), "no negative controls printed"
    m = re.search(r"selftest: (\d+)/(\d+) passed", r.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) >= 40, r.stdout[-800:]


def test_list_numbers_match_contract_and_floor():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    r = run(TOOL, "--list")
    assert r.returncode == 0, r.stderr
    got = {}
    for key, pat in (("files", r"^registered files = (\d+)$"),
                     ("anchors", r"^semantic anchors = (\d+)$"),
                     ("controls", r"^negative controls = (\d+)$")):
        m = re.search(pat, r.stdout, re.M)
        assert m, "missing/invalid --list field %s:\n%s" % (key, r.stdout[:600])
        got[key] = int(m.group(1))  # full-value regex, NOT a bare substring
    assert got["files"] == len(data["files"]) >= MIN_REGISTERED_FILES
    assert got["anchors"] == len(data["semantic_anchors"]) >= MIN_SEMANTIC_ANCHORS
    assert got["controls"] == len(data["negative_controls"]) > 0
    ids = {a["id"] for a in data["semantic_anchors"]}
    assert REQUIRED_ANCHOR_IDS <= ids, "required semantic anchors missing: %s" % (
        sorted(REQUIRED_ANCHOR_IDS - ids))


def test_list_is_cwd_independent(tmp_path):
    """#129 CWD-dependency lesson: same answer from a foreign working dir."""
    a = run(TOOL, "--list", cwd=HERE)
    b = run(TOOL, "--list", cwd=tmp_path)
    assert a.returncode == b.returncode == 0
    assert a.stdout == b.stdout


def test_empty_root_is_unverified_never_match(tmp_path):
    """Clean CI has no mounted rootfs: UNVERIFIED + rc!=0, never a false PASS."""
    empty = tmp_path / "empty_root"
    empty.mkdir()
    r = run(TOOL, "--check", "--json", "--root", str(empty))
    assert r.returncode != 0, "empty root must NOT exit 0"
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "UNVERIFIED", rep["verdict"]
    assert rep["ship_verdict"] == "NOT_SHIPPABLE"
    assert rep["live_hardware_accessed"] is False
    assert rep["proves"], "missing explicit scope statement"


def test_check_without_json_also_refuses_empty_root(tmp_path):
    empty = tmp_path / "empty_root2"
    empty.mkdir()
    r = run(TOOL, "--check", "--root", str(empty))
    assert r.returncode != 0
    assert "verdict = UNVERIFIED" in r.stdout


def test_no_mode_prints_help_and_refuses(tmp_path):
    r = run(TOOL)
    assert r.returncode == 2
    assert "usage:" in r.stdout


def test_rebaseline_without_confirm_is_refused_and_contract_untouched(tmp_path):
    """The tool claims read-only by default: prove the guard, not just its text."""
    before = sha(CONTRACT)
    r = run(TOOL, "--rebaseline", "--root", str(tmp_path))
    assert r.returncode == 2, (r.returncode, r.stdout[-500:], r.stderr[-500:])
    assert "[REFUSE]" in (r.stdout + r.stderr)
    assert sha(CONTRACT) == before, "contract was written without --confirm --reason"


def test_unknown_flag_is_rejected_at_argparse_time():
    r = run(TOOL, "--no-such-flag")
    assert r.returncode == 2
    assert "unrecognized arguments" in (r.stdout + r.stderr)


# ---------------------------------------------------------------------------
# negative controls: break a COPY, the check MUST go red
# ---------------------------------------------------------------------------

def test_negative_control_deleted_flag_goes_red(tmp_path):
    t, _ = sandbox(tmp_path)
    bad = tamper(
        t, 'ap.add_argument("--json", action="store_true", help="emit JSON (with --check)")',
        'pass  # --json declaration deleted', "no_json_flag.py",
    )
    problems = cli_surface_problems(bad)
    assert any("--json" in p for p in problems), problems
    h = run(bad, "--help")
    assert h.returncode == 0
    assert not FLAG_RES["--json"].search(h.stdout)


def test_negative_control_compound_flag_does_not_mask_deletion(tmp_path):
    """rule 8/10: `--json-verbose` keeps the bare substring true; token must fail."""
    t, _ = sandbox(tmp_path)
    bad = tamper(
        t, 'ap.add_argument("--json", action="store_true", help="emit JSON (with --check)")',
        'ap.add_argument("--json-verbose", action="store_true", help="emit JSON (with --check)")',
        "compound_flag.py",
    )
    h = run(bad, "--help")
    assert h.returncode == 0
    assert "--json" in h.stdout                      # bare substring IS present
    assert not FLAG_RES["--json"].search(h.stdout)  # ... but token is not
    assert cli_surface_problems(bad), "compound flag must NOT mask deletion"


def test_negative_control_removed_confirm_guard_rewrites_copy(tmp_path):
    """Deleting the --confirm guard must be detectable by the contract hash.

    Deliberately runs against the SANDBOX copy pair, so even a fully broken
    tool can only rewrite tmp_path's contract, never the repository's.
    """
    t, c = sandbox(tmp_path)
    real_before = sha(CONTRACT)
    bad = tamper(
        t,
        'if not (args.confirm and args.reason.strip()):',
        'if False:',
        "no_confirm_guard.py",
    )
    before = sha(c)
    r = run(bad, "--rebaseline", "--root", str(tmp_path), cwd=tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout[-600:], r.stderr[-400:])
    assert sha(c) != before, "guard removal did not actually write; control is vacuous"
    # The repository contract must still be byte-identical after the tampered
    # copy ran its write path (independent of the tool's own output).
    assert sha(CONTRACT) == real_before, "tampered copy leaked a write into the repo"


def test_negative_control_forced_rc_zero_goes_red(tmp_path):
    """Returning 0 for a non-MATCH verdict is the exact false-green pattern."""
    t, _ = sandbox(tmp_path)
    bad = tamper(
        t, 'return 0 if rep["verdict"] == MATCH else 1',
        'return 0', "always_green.py",
    )
    empty = tmp_path / "empty_root"
    empty.mkdir()
    r = run(bad, "--check", "--root", str(empty))
    assert r.returncode == 0 and "verdict = UNVERIFIED" in r.stdout, (
        "tamper failed to reproduce the false green")
    assert not empty_root_properly_refused(bad, empty), "broken tool went undetected"
    assert empty_root_properly_refused(TOOL, empty), "real tool must reject the same root"
