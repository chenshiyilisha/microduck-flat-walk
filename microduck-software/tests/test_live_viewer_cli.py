"""Regression test for the one CLI entry point that escaped the gate suite.

Why this exists (multi-angle self-audit, 2026-11-11)
--------------------------------------------------
All 49 gated tools in tools/hd1910/ have BOTH a --selftest AND at least one
test that runs their CLI as a real subprocess. live_viewer.py is the sole
exception in the repo: it has 8 argparse flags and a __main__ entry point,
but the only existing coverage (test_hd1910_viewer_mesh.py) loads it via
importlib and calls internal functions -- it never runs `python live_viewer.py
...`. That is exactly the project's most painful recorded lesson: "50 tests
green while the CLI dies at argparse rc=2" (tests/test_hd1910_tooling.py:714).

The argparse layer CAN rot silently: we proved offline that deleting the
`type=int` on --interval-ms turns `--interval-ms notanint` from rc=2 into
rc=0, with zero existing tests going red.

Design (stdlib-only, no render / no network / no hardware)
---------------------------------------------------------
live_viewer.py is module-level stdlib-only (numpy/matplotlib/viser are lazy
imports inside functions, marked noqa: PLC0415), so --help and bad-flag paths
run under a bare system python too (verified rc=0 / rc=2 on Python 3.13).
This test therefore passes in BOTH the lean CI and the full .venv-mjlab.
It exercises only argparse-time exits; it never reaches a viewer/renderer.

`check_cli(script)` is a pure function over a script PATH, so the SAME
assertions run against the real script (positive control) and against
tampered copies in tmp_path (negative controls): a test that only ever sees
green proves nothing without a "break it -> must go red" companion.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "hd1910" / "live_viewer.py"

# External contract truth, NOT derived from the script under test. If it were
# scraped from the source, deleting a flag would shrink both sides and the
# check would self-certify. These 8 flags are the stable CLI surface.
EXPECTED_FLAGS = (
    "--source", "--demo", "--host", "--renderer", "--interval-ms",
    "--mesh-source", "--mesh-mode", "--mesh-stride",
)
# (flag, bad value) pairs that argparse MUST reject with rc=2 and an
# "invalid" diagnostic, before any render path is entered.
BAD_VALUE_CASES = (
    ("--mesh-mode", "BOGUS"),      # choices guard
    ("--renderer", "BOGUS"),       # choices guard
    ("--source", "BOGUS"),         # choices guard
    ("--interval-ms", "notanint"),  # type=int guard
)
# Token-boundary match, NOT a bare substring. Rule 10: a bare `--mesh-mode in
# help` is bitten by a compound flag like `--mesh-mode-verbose` (proven by the
# negative control below, where renaming to --mesh-mode-REMOVED kept the bare
# substring true). A flag counts as present only when not adjacent to a word
# char or hyphen on either side.
def _flag_re(flag: str) -> re.Pattern:
    return re.compile(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])")


FLAG_RES = {f: _flag_re(f) for f in EXPECTED_FLAGS}


def _run(script: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )


def check_cli(script: pathlib.Path) -> list[str]:
    """Return a list of problems; empty means the CLI surface is intact.

    Pure over `script` so negative controls can point it at tampered copies.
    """
    problems: list[str] = []

    help_r = _run(script, "--help")
    if help_r.returncode != 0:
        problems.append(
            "--help rc=%d (expected 0: argparse layer must not import a "
            "renderer at module scope)" % help_r.returncode)
    else:
        for flag in EXPECTED_FLAGS:
            if not FLAG_RES[flag].search(help_r.stdout):
                problems.append("--help missing declared flag %s" % flag)

    for flag, bad in BAD_VALUE_CASES:
        r = _run(script, flag, bad)
        if r.returncode != 2:
            problems.append(
                "%s %s rc=%d (expected 2: bad value must be rejected at "
                "argparse time, not silently accepted)" % (flag, bad, r.returncode))
        elif "invalid" not in (r.stderr + r.stdout).lower():
            problems.append(
                "%s %s rejected without an argparse 'invalid' message" % (flag, bad))
    return problems


def _tamper(tmp_path: pathlib.Path, name: str, old: str, new: str) -> pathlib.Path:
    """Write a tampered copy of the script under tmp_path; never touch the real one."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert old in src, "tamper anchor not found -- source drifted, fix the test"
    dst = tmp_path / name
    dst.write_text(src.replace(old, new, 1), encoding="utf-8")
    return dst


def test_real_live_viewer_cli_surface_is_intact():
    """Positive control: the shipped CLI advertises all flags and rejects bad values."""
    assert check_cli(SCRIPT) == [], check_cli(SCRIPT)


def test_negative_control_deleted_flag_goes_red(tmp_path):
    """Deleting a flag's declaration must make the --help surface check fail.

    This is the case that a bare `rc != 0` assertion CANNOT catch: argparse
    also returns non-zero for an unknown flag, so rc alone stays "green".
    Only the explicit 8-flag whitelist notices the missing declaration.
    """
    bad = _tamper(
        tmp_path, "lv_no_mesh_mode.py",
        'ap.add_argument("--mesh-mode", default="auto", choices=["auto", "mesh", "cylinder"],\n'
        '                    help="auto=有源用 mesh 否则圆柱; mesh=强制 mesh(无源则警告); cylinder=强制圆柱")',
        'pass  # --mesh-mode declaration deleted',
    )
    problems = check_cli(bad)
    assert any("--mesh-mode" in p for p in problems), problems
    # And it is NOT merely an rc failure: --help must specifically lose the flag.
    h = _run(bad, "--help")
    assert h.returncode == 0 and not FLAG_RES["--mesh-mode"].search(h.stdout)


def test_token_boundary_does_not_backfire_on_compound_flag(tmp_path):
    """Rule-10 guard: a NEW compound flag must not hide a deleted base flag.

    If someone adds --mesh-mode-verbose while --mesh-mode is gone, a bare
    substring check stays green. The token-boundary matcher must still report
    the base flag missing. This pins the exact bug the first draft had.
    """
    bad = _tamper(
        tmp_path, "lv_compound_flag.py",
        'ap.add_argument("--mesh-mode", default="auto", choices=["auto", "mesh", "cylinder"],',
        'ap.add_argument("--mesh-mode-verbose", default="auto", choices=["auto", "mesh", "cylinder"],',
    )
    h = _run(bad, "--help")
    assert h.returncode == 0
    assert "--mesh-mode" in h.stdout  # bare substring IS present ...
    assert not FLAG_RES["--mesh-mode"].search(h.stdout)  # ... but token is not
    assert check_cli(bad), "compound flag must NOT mask the missing base flag"


def test_negative_control_deleted_type_guard_goes_red(tmp_path):
    """Removing type=int turns a bad --interval-ms into rc=0; the check must catch it.

    This is the live, reproduced silent-rot: the program accepts garbage and
    carries on, with no existing test going red.
    """
    bad = _tamper(
        tmp_path, "lv_no_int_type.py",
        'ap.add_argument("--interval-ms", type=int, default=100)',
        'ap.add_argument("--interval-ms", default=100)',
    )
    problems = check_cli(bad)
    assert any("--interval-ms" in p and "rc=0" in p for p in problems), problems


def test_negative_control_relaxed_choices_goes_red(tmp_path):
    """Widening a choices list must make the bad-value rejection check fail."""
    bad = _tamper(
        tmp_path, "lv_wide_choices.py",
        'choices=["auto", "mesh", "cylinder"],',
        'choices=["auto", "mesh", "cylinder", "BOGUS"],',
    )
    problems = check_cli(bad)
    assert any("--mesh-mode BOGUS" in p for p in problems), problems
