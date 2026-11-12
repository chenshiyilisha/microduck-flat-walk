"""Reconcile the DECLARED twist command-resampling override with its EFFECTIVE value.

Why this exists (E4-5 low-level retrain)
----------------------------------------
The low-level retrain changes ``env.commands["twist"].resampling_time_range``
from the task default ``(3.0, 8.0)`` to a narrow ``(0.1, 0.5)`` so the policy can
learn to track time-varying velocity commands (E3 found ``p8head_2999`` cannot:
``PATH_3``, undershoot ~45%). The override is declared on the training wrapper's
``EXTRA_ARGS`` and resolved by tyro inside ``train_heading_variant.py``.

A declared override is NOT evidence that it took effect. A typo in the flag
name, a space in the tuple (``0.1 0.5``), or an old trainer that does not record
the field would all let a 2.6-10.3 h GPU run train on the WRONG command
distribution while the run name claims otherwise. This module is the single
authority for that reconciliation, reused by the wrapper's post-run gate and by
the preflight tests, so the check cannot drift between the two.

It reads two independent sources and refuses to call them equal unless they
actually agree:
  * DECLARED: the ``--env.commands.twist.resampling-time-range`` value parsed
    out of the wrapper's ``EXTRA_ARGS`` string.
  * EFFECTIVE: ``resampling_time_range_effective`` in ``heading_meta_<run>.json``,
    written by the trainer from the very command object the env is built from.

Usage (cwd = microduck-software):
    python tools/hd1910/resampling_gate.py --check \
        --meta out/heading_meta_<run>.json \
        --extra-args "--env.commands.twist.resampling-time-range 0.1,0.5"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# tyro's flag spelling is --env.commands.twist.resampling-time-range; accept the
# underscore spelling too so a source edit of the flag name alone cannot silently
# disable the gate. Both ``0.1,0.5`` and ``(0.1, 0.5)`` forms are parsed.
_FLAG_RE = re.compile(
    r"--env\.commands\.twist\.resampling[-_]time[-_]range\s+([0-9.,()\s]+?)(?=\s+--|\s*$)"
)
_NUM_RE = re.compile(r"[0-9]+\.?[0-9]*")


def declared_window(extra_args: str) -> list[float] | None:
    """Return the DECLARED 2-float window from an EXTRA_ARGS string.

    ``None`` means no resampling override is declared (a control run; the task
    default applies). A malformed declared value raises ``ValueError`` so the
    caller can refuse the run instead of training on an unintended distribution.
    """
    m = _FLAG_RE.search(extra_args or "")
    if not m:
        return None
    nums = _NUM_RE.findall(m.group(1))
    if len(nums) < 2:
        raise ValueError(f"cannot parse two floats from declared value {m.group(1)!r}")
    return [float(nums[0]), float(nums[1])]


def _valid_window(value: Any) -> bool:
    """A usable window is two finite numbers with lo <= hi and lo >= 0."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return False
    try:
        lo, hi = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return False
    return lo >= 0.0 and hi >= lo


def grade(meta: dict, extra_args: str) -> dict:
    """Reconcile DECLARED (EXTRA_ARGS) vs EFFECTIVE (meta). Pure, no I/O.

    Verdict contract:
      * no override declared + a valid effective window recorded -> PASS
        (provenance still works; this is the control/default case).
      * override declared + effective missing -> FAIL_MISSING_EFFECTIVE.
      * override declared + effective malformed -> FAIL_BAD_EFFECTIVE.
      * override declared + effective != declared -> FAIL_MISMATCH (the core
        negative-control case: a declared override that did not take effect).
      * override declared + effective == declared -> PASS.
    A malformed DECLARED value propagates ``ValueError`` (caller refuses to run).
    """
    declared = declared_window(extra_args)
    effective = meta.get("resampling_time_range_effective")
    result: dict = {"declared": declared, "effective": effective, "passed": True}

    if declared is None:
        if _valid_window(effective):
            result["verdict"] = "PASS_NO_OVERRIDE"
        else:
            result["verdict"] = "FAIL_MISSING_EFFECTIVE"
            result["passed"] = False
        return result

    if effective is None:
        result["verdict"] = "FAIL_MISSING_EFFECTIVE"
    elif not _valid_window(effective):
        result["verdict"] = "FAIL_BAD_EFFECTIVE"
    elif [float(x) for x in effective] != declared:
        result["verdict"] = "FAIL_MISMATCH"
    else:
        result["verdict"] = "PASS_OVERRIDE_TOOK_EFFECT"
    result["passed"] = result["verdict"].startswith("PASS")
    return result


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="reconcile declared EXTRA_ARGS with the meta's effective value")
    ap.add_argument("--meta", required=True, help="path to heading_meta_<run>.json")
    ap.add_argument("--extra-args", default="",
                    help="the wrapper's EXTRA_ARGS string containing the declaration")
    args = ap.parse_args(argv)

    if not args.check:
        ap.error("pass --check")

    try:
        declared = declared_window(args.extra_args)
    except ValueError as e:
        print(f"FAIL: malformed declared override: {e}", file=sys.stderr)
        return 6
    meta_path = Path(args.meta)
    if not meta_path.is_file():
        print(f"FAIL: meta not found: {meta_path}", file=sys.stderr)
        return 6
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    g = grade(meta, args.extra_args)
    print(f"resampling_gate: {g['verdict']} declared={g['declared']} effective={g['effective']}")
    return 0 if g["passed"] else 6


if __name__ == "__main__":
    raise SystemExit(_main())
