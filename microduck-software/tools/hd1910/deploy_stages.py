#!/usr/bin/env python3
"""Single authority for conductor stage sets and verdict re-derivation.

Two consumers must agree on what a `pre_deploy_check.py --json` report means:

  * bundle_bindings.py   -- the ARCHIVED deploy_check_*.json evidence
  * assert_ci_verdict.py -- the report CI produced SECONDS ago

Pass22/R6 fixed the archived side (re-derive the top-level verdict from its
stages, and bind the stage set to FULL_STAGES in the CURRENT conductor source).
Pass23/R7 found the LIVE side still trusted the self-reported `verdict`:

    stages = {s.get("name"): s.get("status") ...}   # duplicate names overwrite
    if verdict not in ("PASS", "PASS*"): ...        # top-level claim only

A tamper matrix on the real workspace proved ALL of these were ACCEPTED by the
old live assertion:
  * a report trimmed to a single `inference` stage (four stages dropped)
  * a duplicated stage name masking a FAIL behind a later PASS
  * an unknown sixth stage
  * skipped_stages disagreeing with the stage statuses
  * a FAIL stage masked while the top-level verdict still says PASS*

Official basis (GitHub Docs, "Troubleshooting required status checks"):
  a job skipped by a condition "reports success"; a job depending on a failed
  one is "skipped and does not report a failure"; the recommended fix is
  `always()` plus an explicit assertion on each dependency. A green aggregate
  is therefore NOT evidence that each component passed.
SLSA v1.0 "Verifying artifacts": untrusted externalParameters MUST be verified
downstream, and unrecognised ones SHOULD cause verification to fail.

Consequently the verdict is RE-DERIVED from per-stage results, the stage set
is compared with FULL_STAGES read from the conductor SOURCE via ast (never
imported or executed), and unknown --allow-skip names are refused.

Stdlib only. Python >= 3.11.
"""
from __future__ import annotations

import ast
from pathlib import Path

DEFAULT_AUTHORITY = Path(__file__).resolve().with_name("pre_deploy_check.py")


def stage_authority(source: Path) -> tuple[list[str], str | None]:
    """Read FULL_STAGES out of the conductor SOURCE (ast; never import/execute).

    The expected stage set is a property of the CURRENT gate, so it must be
    derived from the gate's own source. Keeping a second literal list in a
    consumer would rot exactly like Pass20's third copy of the onnx list.
    Fail loud if the constant is missing, unparsable or not a flat list of
    unique names.
    """
    try:
        tree = ast.parse(Path(source).read_text(encoding="utf-8"),
                         filename=str(source))
    except (OSError, SyntaxError, ValueError) as exc:
        return [], f"STAGE AUTHORITY UNREADABLE: {source}: {exc}"
    raw = None
    for node in tree.body:
        target = value = None
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        if isinstance(target, ast.Name) and target.id == "FULL_STAGES" \
                and value is not None:
            raw = value
            break
    if raw is None:
        return [], (f"STAGE AUTHORITY MISSING: {source} has no module-level "
                    "FULL_STAGES constant; refusing to guess the stage set")
    try:
        stages = ast.literal_eval(raw)
    except (ValueError, TypeError, SyntaxError) as exc:
        return [], f"STAGE AUTHORITY UNPARSEABLE: {source}: {exc}"
    if not isinstance(stages, (list, tuple)) or not stages \
            or not all(isinstance(s, str) and s for s in stages) \
            or len(set(stages)) != len(stages):
        return [], (f"STAGE AUTHORITY INVALID: {source} FULL_STAGES="
                    f"{stages!r}; expected a non-empty flat list of unique names")
    return list(stages), None


def authority_variant(text: str, *, add: tuple[str, ...] = (),
                      drop: tuple[str, ...] = ()) -> str | None:
    """Rewrite the FULL_STAGES assignment in conductor SOURCE text.

    Used ONLY by negative controls: prove that editing the single authority
    invalidates existing evidence. Names are taken FROM the parsed authority,
    so this never becomes yet another hard-coded copy of the stage list.
    Returns None if the assignment cannot be located (caller must fail loud).
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    node = None
    for candidate in tree.body:
        target = value = None
        if isinstance(candidate, ast.AnnAssign):
            target, value = candidate.target, candidate.value
        elif isinstance(candidate, ast.Assign) and len(candidate.targets) == 1:
            target, value = candidate.targets[0], candidate.value
        if isinstance(target, ast.Name) and target.id == "FULL_STAGES" \
                and value is not None:
            node, raw = candidate, value
            break
    if node is None or getattr(node, "end_lineno", None) is None:
        return None
    try:
        names = list(ast.literal_eval(raw))
    except (ValueError, TypeError, SyntaxError):
        return None
    new = [n for n in names if n not in drop] + [n for n in add if n not in names]
    if not new:
        return None
    lines = text.splitlines(keepends=True)
    replacement = f"FULL_STAGES: tuple[str, ...] = {tuple(new)!r}\n"
    return ("".join(lines[:node.lineno - 1]) + replacement
            + "".join(lines[node.end_lineno:]))


def derive_verdict(report: dict, full_stages: list[str],
                   allow_skip: tuple[str, ...] = ()) -> tuple[str, list[str]]:
    """Re-derive the verdict from the report's OWN stages.

    Returns (derived_verdict, problems). `allow_skip` is the caller's policy:
    archived evidence must be all-PASS (no skips), while CI deliberately skips
    `contract` because the training stack is absent there. Two independent
    algorithms are cross-checked: the stage statuses/rc, and the declared
    `skipped_stages` / `full_stage_set` fields. Any disagreement makes the
    derived verdict FAIL.
    """
    problems: list[str] = []
    stages = report.get("stages")
    if not isinstance(stages, list) or not stages:
        return "FAIL", ["report has no structured stages -- its verdict cannot "
                        "be re-derived"]

    names: list[str] = []
    offenders: list[str] = []
    skipped: list[str] = []
    for i, stage in enumerate(stages):
        if not isinstance(stage, dict):
            offenders.append(f"stages[{i}]={stage!r}")
            continue
        name = stage.get("name")
        names.append(name if isinstance(name, str) else repr(name))
        status, rc = stage.get("status"), stage.get("rc")
        if status == "PASS" and rc in (0, None):
            continue
        # A SKIP that returned 0 is self-contradictory; a SKIP of a stage the
        # caller did not authorise is a missing verification, not a pass.
        if status == "SKIP" and name in allow_skip and rc != 0:
            skipped.append(name)
            continue
        offenders.append(f"{name}:{status}/rc={rc}")
    if offenders:
        problems.append("claims a PASS but its own stages disagree: "
                        + str(offenders))

    if len(set(names)) != len(names):
        dup = sorted({n for n in names if names.count(n) > 1}, key=str)
        problems.append(f"duplicate stage names {dup} -- a dict-style "
                        "aggregation would silently mask a FAIL")

    missing = [s for s in full_stages if s not in names]
    extra = [s for s in names if s not in full_stages]
    if missing or extra:
        problems.append(f"stage set {names} != current conductor FULL_STAGES "
                        f"{list(full_stages)} (missing={missing}, extra={extra}); "
                        "evidence belongs to a different gate version -- "
                        "regenerate it with pre_deploy_check.py --json")

    declared = report.get("skipped_stages", [])
    if not isinstance(declared, list):
        problems.append(f"skipped_stages is not a list: {declared!r}")
        declared = []
    if len(declared) != len(skipped) or sorted(map(str, declared)) != sorted(skipped):
        problems.append(f"skipped_stages {declared} disagrees with the SKIPs "
                        f"derived from stage statuses {skipped}")

    declared_full = report.get("full_stage_set")
    if declared_full is not None and (
            not isinstance(declared_full, list)
            or declared_full != list(full_stages)):
        problems.append(f"report full_stage_set={declared_full!r} != conductor "
                        f"FULL_STAGES={list(full_stages)}")

    derived = "FAIL" if problems else ("PASS*" if skipped else "PASS")
    return derived, problems
