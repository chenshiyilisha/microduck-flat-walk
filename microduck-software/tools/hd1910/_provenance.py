"""Training-run provenance capture for reproducible HD-1910 RL runs.

Why this exists
---------------
The project's explicit goal is to train "perfect" locomotion/skill policies, but
a good run is worthless if it cannot be reproduced or identified later. The
official `microduck_rl` pins every bundle with git commit + uncommitted diff +
exact command + parent checkpoint; this module is the HD-1910 line's equivalent.

It is consumed by:
  * `train_heading_variant.py`  -- folds a `provenance` block into heading_meta_*.json
  * `log_run_provenance.py`     -- merges a `provenance` block into runmeta_*.json
                                  (standup / roller / groundpick runs)

Captured fields
---------------
  git_commit          current HEAD sha (or "<no-git>" / "<error>")
  git_branch          branch name (or detached)
  git_dirty           bool -- any tracked/untracked change vs HEAD
  git_diff_patch_id   sha256 of `git diff HEAD` (stable fingerprint of uncommitted
                      work; equal for identical edits regardless of author/time)
  git_diff_stat       `git diff HEAD --stat` (human-readable, may be empty)
  git_toplevel        repo root actually used
  seed                training seed (passed in, or read from --agent.seed in argv)
  command             exact launch command (passed in, or reconstructed from argv)
  versions            torch / rsl_rl / mjlab / onnxruntime / onnx / numpy
  captured_at         ISO timestamp
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _git_toplevel(start: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start), capture_output=True, text=True,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, ValueError):
        pass
    return None


def _git(toplevel: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(toplevel), *args],
            capture_output=True, text=True,
        )
        return out.stdout
    except (OSError, ValueError):
        return ""


def _coerce_int(s: str) -> Any:
    try:
        return int(s)
    except (TypeError, ValueError):
        return s


def seed_from_argv(argv: list[str] | None = None) -> Any:
    """Read `--agent.seed` from a command line (handles `42` and `=42` forms)."""
    argv = list(sys.argv if argv is None else argv)
    for i, tok in enumerate(argv):
        if tok == "--agent.seed" and i + 1 < len(argv):
            return _coerce_int(argv[i + 1])
        if tok.startswith("--agent.seed="):
            return _coerce_int(tok.split("=", 1)[1])
    return None


def _versions() -> dict[str, str]:
    import importlib.metadata as md

    vers: dict[str, str] = {}
    for mod in ("torch", "rsl_rl", "mjlab", "onnxruntime", "onnx", "numpy"):
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", None)
            if v is None:
                # Many local/namespace packages expose no __version__; fall back
                # to the installed distribution metadata.
                v = md.version(mod)
            vers[mod] = v
        except Exception:  # noqa: BLE001
            vers[mod] = "<absent>"
    return vers


def capture_provenance(
    root: Path,
    *,
    seed: Any = None,
    command: Any = None,
) -> dict[str, Any]:
    """Build the provenance block. `root` is used to locate the git repo."""
    top = _git_toplevel(root)
    if top is None:
        git_block = {
            "git_commit": "<no-git>",
            "git_branch": "<no-git>",
            "git_dirty": None,
            "git_diff_patch_id": "<no-git>",
            "git_diff_stat": "",
            "git_toplevel": None,
        }
    else:
        commit = _git(top, "rev-parse", "HEAD").strip() or "<error>"
        branch = _git(top, "rev-parse", "--abbrev-ref", "HEAD").strip() or "<detached>"
        raw_diff = _git(top, "diff", "HEAD")
        dirty = bool(_git(top, "status", "--porcelain").strip())
        git_block = {
            "git_commit": commit,
            "git_branch": branch,
            "git_dirty": dirty,
            "git_diff_patch_id": hashlib.sha256(raw_diff.encode("utf-8", "replace")).hexdigest()[:16],
            "git_diff_stat": _git(top, "diff", "HEAD", "--stat").strip(),
            "git_toplevel": str(top),
        }

    if seed is None:
        seed = seed_from_argv()
    if command is None:
        command = " ".join(sys.argv)

    return {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        **git_block,
        "seed": seed,
        "command": command,
        "versions": _versions(),
    }
