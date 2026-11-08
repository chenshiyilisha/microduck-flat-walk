#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
"""HD1910 deploy rehearsal — same instrument as ``tools/rehearse_deploy.py``.

Upstream ``infer_policy.load_bam_model`` hardcodes XL330 / m6 / ``kp_fw=200``.
This wrapper keeps that file untouched and patches the loaded module so the
rehearsal plant matches an HD1910 plant spec from ``plant_spec.py``.

Which plant
-----------
``--plant live`` (the default) reads the plant actually installed in the live
``microduck_constants.py`` and rehearses against **that**. Two reasons it is the
default rather than a fixed preset:

* the policy being rehearsed was trained against the live plant, so anything
  else is a plant mismatch (the XL330<->HD1910 incident, docs/archive/05-flat-walk §10);
* a hardcoded preset silently keeps working after the live plant changes, and
  the rehearsal numbers then describe a robot nobody trained on.

Pass ``--plant p3|p8|m5|ftservo`` only to rehearse a plant you are NOT live on, and
read the echoed ``plant:`` line + the ``settings.plant`` block in the JSON back.

Presets (``tools/hd1910/plant_spec.py``)::

    p3      hd1910_official_m6_kp5   official STS3215 law, kp_fw=5   <- ruled target
    p8      hd1910_official_m6_kp8   same law + same JSON, kp_fw=8   <- bench sweet spot
    m5      hd1910_openmicroduck_m5  local m5.json,        kp_fw=32
    ftservo hd1910_ftservo_official_m6  official params,   kp_fw=32

``p3`` and ``p8`` share one params JSON, so ``--plant p8`` and ``--plant p3 --kp-fw 8``
are the same plant. Prefer ``--plant p8``: it keeps the preset's P in the report even
if you forget ``--kp-fw``.

Usage (from ``microduck-software/``)::

  .venv-mjlab/Scripts/python.exe tools/hd1910/rehearse_hd1910.py --sweep
  .venv-mjlab/Scripts/python.exe tools/hd1910/rehearse_hd1910.py --condition nominal
  .venv-mjlab/Scripts/python.exe tools/hd1910/rehearse_hd1910.py --plant p3 --onnx out/x.onnx

Extra argv is forwarded to ``rehearse_deploy.main`` (``--command``/``--cmd-vx``,
``--seconds``, ``--out``, …).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "hd1910"))

# Register HD1910Actuator before any bam.model.load_model(json_file=…).
import bam_actuators  # noqa: E402,F401
import rehearse_deploy as rd  # noqa: E402
from plant_spec import (  # noqa: E402
    HD1910_FTSERVO_OFFICIAL_M6,
    HD1910_OFFICIAL_M6_KP5,
    HD1910_OFFICIAL_M6_KP8,
    HD1910_OPENMICRODUCK_M5,
)

#: rsl_rl writes one directory per run: logs/rsl_rl/<task>/<timestamp>_<name>/,
#: each holding model_*.pt and (since the exporter hook) a same-named .onnx.
RUNS_ROOT = ROOT / "logs" / "rsl_rl"


#: Checkpoints at or below this iteration are not a trained policy: a run killed
#: in its first minute leaves ``model_0.pt`` + an ONNX behind, and a 5-iteration
#: smoke leaves ``model_4.pt``. Both are *newer* than last night's real
#: checkpoint, so mtime ordering happily serves an untrained graph as "the latest
#: policy" -- the exact failure mode mtime resolution was introduced to avoid.
MIN_TRAINED_ITER = 50


def resolve_latest_onnx(runs_root: pathlib.Path = RUNS_ROOT) -> pathlib.Path:
    """Newest *trained* exported policy under the training log tree.

    This wrapper used to hardcode ``out/onnx_p3head030_it1600.onnx``, so a
    rehearsal run on the day after a fresh checkpoint silently judged a stale
    policy -- twice. Resolve by mtime instead, and print what was picked.

    mtime alone is still not safe: an aborted run or a smoke exports its ONNX
    before anything has been learned. Candidates whose newest companion
    checkpoint is at or below ``MIN_TRAINED_ITER`` are therefore skipped (and
    named), falling back to the newest of them only if nothing else exists.
    """
    cands = sorted(
        (p for p in runs_root.rglob("*.onnx") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    if not cands:
        raise SystemExit(
            f"no exported ONNX under {runs_root} (train first, or pass --onnx)"
        )
    untrained = []
    for p in reversed(cands):
        _, it = _onnx_companion(p)
        if it >= MIN_TRAINED_ITER:
            return p
        untrained.append((p, it))
    print(f"⚠️  every ONNX under {runs_root} is at iteration < {MIN_TRAINED_ITER} "
          f"(smoke / aborted run); using the newest anyway:")
    for p, it in untrained[:5]:
        print(f"    iter {it:>5}  {_rel(p)}")
    return cands[-1]


def _onnx_companion(onnx: pathlib.Path) -> tuple[pathlib.Path | None, int]:
    """Newest sibling checkpoint + its iteration, for the staleness check."""
    ckpts = [p for p in onnx.parent.glob("model_*.pt") if p.is_file()]
    if not ckpts:
        return None, -1
    newest = max(ckpts, key=lambda p: p.stat().st_mtime)
    try:
        return newest, int(newest.stem.split("_")[1])
    except (IndexError, ValueError):
        return newest, -1


def _flag_value(argv: list[str], flag: str) -> str | None:
    try:
        return argv[argv.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def _normalize_plant(raw: object) -> str | None:
    """Map a raw ``plant`` field — however the training side wrote it — to a
    rehearsal preset key (``p3|p8|m5|ftservo``), or ``None`` if unresolvable.

    The training side emits the plant under *two* incompatible shapes and *two*
    name namespaces, and the rehearsal guard must understand all of them or it
    silently (or crash-ingly) lets a cross-plant rehearsal through:

    * runmeta_*.json  -> top-level ``plant`` is a **string**. It is either the
      rehearsal preset *id* (``hd1910_official_m6_kp8``) or the training-side /
      DETECTED name (``hd1910_kp8``); only the former was ever in
      ``PLANT_ID_TO_KEY``, so the latter used to return ``None``.
    * heading_meta_*.json -> top-level ``plant`` is a **dict** whose ``name`` is
      the training-side name. For the generic name ``"hd1910"`` the ``kp_fw``
      field is the only disambiguator (m5=32, p3=5, p8=8) — and passing the dict
      straight into ``PLANT_ID_TO_KEY.get`` raised ``TypeError: unhashable``,
      taking the whole rehearsal down on the real deploy-candidate ONNX.

    Never raises; a crash here would disable the very guard that is supposed to
    stop the XL330<->HD1910 plant-mismatch incident from repeating.
    """
    name = None
    kp_fw = None
    if isinstance(raw, str):
        name = raw
    elif isinstance(raw, dict):
        name = raw.get("name")
        kp_fw = raw.get("kp_fw")
    else:
        return None

    # 1) Rehearsal preset id (the canonical single source of truth in plant_spec).
    if name in PLANT_ID_TO_KEY:
        return PLANT_ID_TO_KEY[name]
    # 2) Training-side / DETECTED name (the constants-file "detected" string).
    if name in DETECTED_TO_PRESET:
        key = DETECTED_TO_PRESET[name]
        # The generic name "hd1910" is shared by three plants; kp_fw decides.
        if name == "hd1910" and kp_fw is not None:
            kp_map = {32.0: "m5", 5.0: "p3", 8.0: "p8"}
            return kp_map.get(float(kp_fw), key)
        return key
    return None


def _plant_from_filename(stem: str) -> str | None:
    """Infer the plant preset key from an ONNX filename when no companion meta
    exists.

    The deploy-candidate exports ship with a short name and NO runmeta /
    heading_meta — ``p8head_2999.onnx`` -> p8, ``onnx_p3head030_it1600.onnx`` ->
    p3 — so the meta lookup alone returns ``None`` and the cross-plant guard
    silently passes the single most important policy. Only names that
    *explicitly* carry the plant target are inferred; anything ambiguous stays
    ``None`` so the guard reports "unknown" rather than guessing (a wrong guess
    would either block a valid rehearsal or pass a real mismatch). The
    deprecated XL330-origin samples (deploy61, walk56, walk_std*) deliberately
    fall through to ``None``.
    """
    for prefix, key in (
        ("p8head", "p8"), ("p8ctl", "p8"),
        ("p3head", "p3"), ("p3ctl", "p3"),
        ("onnx_p3", "p3"),
    ):
        if stem == prefix or stem.startswith(prefix) or f"_{prefix}" in stem:
            return key
    return None


def _onnx_plant_key(onnx: pathlib.Path) -> str | None:
    """Best-effort plant preset key of an ONNX.

    Resolution order, so the guard never silently passes the deploy candidate:
      1. companion meta (runmeta_<RUN>.json / heading_meta_<RUN>.json) ->
         ``_normalize_plant`` (preset-id string, DETECTED string, or nested dict)
      2. file-name heuristic (deploy candidates ship without a companion meta)

    Returns the preset key, or ``None`` when neither resolves — callers treat
    ``None`` as "unknown", never as a match.
    """
    stem = onnx.stem
    # rsl_rl names the exported ONNX after its run directory, which carries a leading
    # timestamp: ``2026-11-07_22-12-33_p8head_030_...`` . The companion runmeta_*.json /
    # heading_meta_*.json are written WITHOUT that prefix, so strip it before the meta
    # lookup -- otherwise the real exported policy resolves to None and the cross-plant
    # guard goes silent on exactly the artifact that goes onto the robot (Pass9 found
    # the groundpick / standup onnxs returning None).
    m = re.match(r"\A\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_", stem)
    if m:
        stem = stem[m.end():]
    run = stem
    # Strip a trailing _it<digits> (rsl_rl export names) if present.
    if "_it" in run:
        run = run.rsplit("_it", 1)[0]
    meta = ROOT / "out" / f"runmeta_{run}.json"
    if not meta.is_file():
        # Heading runs record provenance under out/heading_meta_<run>.json too.
        meta = ROOT / "out" / f"heading_meta_{run}.json"
    if meta.is_file():
        try:
            d = json.load(open(meta))
        except (OSError, ValueError):
            d = {}
        raw = d.get("plant")
        if raw is None:
            raw = (d.get("provenance") or {}).get("plant")
        resolved = _normalize_plant(raw)
        if resolved is not None:
            return resolved
    # 2) file-name heuristic for deploy candidates without a companion meta
    #    (e.g. p8head_2999.onnx -> p8, onnx_p3head030_it1600.onnx -> p3).
    return _plant_from_filename(stem)


def _onnx_task(onnx: pathlib.Path) -> str | None:
    """Training task name recorded in the ONNX's companion runmeta/heading_meta.

    Used to decide whether the rehearsal's forward-motion gate applies. Only
    Velocity / Walk policies are expected to move under a velocity command;
    GroundPick / StandUp policies ignore it and would otherwise trip a spurious
    ``moves_forward`` failure (see ``_inject_defaults``).
    """
    stem = onnx.stem
    m = re.match(r"\A\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_", stem)
    if m:
        stem = stem[m.end():]
    run = stem
    if "_it" in run:
        run = run.rsplit("_it", 1)[0]
    meta = ROOT / "out" / f"runmeta_{run}.json"
    if not meta.is_file():
        meta = ROOT / "out" / f"heading_meta_{run}.json"
    if meta.is_file():
        try:
            d = json.load(open(meta))
        except (OSError, ValueError):
            return None
        task = d.get("task")
        if task is None:
            task = (d.get("provenance") or {}).get("task")
        return task
    return None


def _is_walking_task(task: str | None) -> bool:
    """A policy that should respond to a velocity command."""
    if not task:
        return False
    t = task.lower()
    return "velocity" in t or "walk" in t


def _rel(p: pathlib.Path) -> str:
    """Path relative to the repo when possible -- user-supplied ones may be outside."""
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _report_onnx(onnx: pathlib.Path, out_path: pathlib.Path) -> None:
    """Say which policy is being judged -- silence here is how the wrong ckpt wins."""
    import datetime as _dt

    try:
        st = onnx.stat()
    except OSError:
        print(f"onnx: {_rel(onnx)}  (file missing -- cannot read size/provenance)")
        print(f"out : {_rel(out_path)}")
        return
    mtime = _dt.datetime.fromtimestamp(st.st_mtime)
    print(f"onnx: {_rel(onnx)}  ({st.st_size / 1e3:.0f} kB, "
          f"{mtime:%m-%d %H:%M})")
    print(f"out : {_rel(out_path)}")
    ckpt, it = _onnx_companion(onnx)
    if ckpt is None:
        print("  (no sibling model_*.pt -- provenance of this ONNX is unknown)")
        return
    print(f"  companion checkpoint: {ckpt.name}  (iter {it})")
    lag = ckpt.stat().st_mtime - st.st_mtime
    if lag > 5:
        print(f"  ⚠️  onnx is {lag:.0f}s older than {ckpt.name} -- it may not match "
              f"that checkpoint; re-export before trusting the numbers")
    if _dt.datetime.now().timestamp() - st.st_mtime < 120:
        print("  ⚠️  this file was written <2 min ago -- a live training run may "
              "still be overwriting it")

#: Pristine copy of rehearse_deploy's parity note. _publish_parity() rewrites
#: rd.TRAINING_PARITY, so it must always build from this, never from rd's current
#: value — otherwise two calls in one process would stack annotations.
_BASE_PARITY = {
    "same": list(rd.TRAINING_PARITY["same"]),
    "differs": list(rd.TRAINING_PARITY["differs"]),
}

#: ``--plant`` value -> preset. "live" is resolved through apply_to_live._readback.
PLANTS = {
    "p3": HD1910_OFFICIAL_M6_KP5,
    # Same JSON + same control law as p3; only reg 50 differs (bench sweet spot).
    "p8": HD1910_OFFICIAL_M6_KP8,
    "m5": HD1910_OPENMICRODUCK_M5,
    "ftservo": HD1910_FTSERVO_OFFICIAL_M6,
}

#: ``detected`` string in microduck_constants.py -> preset key.
DETECTED_TO_PRESET = {
    "hd1910_kp5": "p3",
    "hd1910_kp8": "p8",
    "hd1910": "m5",
    "hd1910_ftservo_m6": "ftservo",
}

#: Reverse of PLANTS: a plant *id* (as written into runmeta / heading_meta) -> preset key.
#: Lets us read an ONNX's companion runmeta and refuse a cross-plant rehearsal.
PLANT_ID_TO_KEY = {v["id"]: k for k, v in PLANTS.items()}

#: Filled in by main() before rd.main() runs; _patch_upstream reads it.
_STATE: dict[str, object] = {"key": None, "plant": None}


def resolve_plant(spec: str) -> tuple[str, dict]:
    """Return (preset key, preset dict) for a --plant value, refusing mismatches."""
    if spec != "live":
        if spec not in PLANTS:
            raise SystemExit(f"--plant {spec!r} not one of: live,{','.join(PLANTS)}")
        return spec, PLANTS[spec]

    import apply_to_live as atl  # local: keeps import cost off the --help path

    info = atl._readback()
    det = info.get("detected")
    if det not in DETECTED_TO_PRESET:
        raise SystemExit(
            f"live plant is {det!r}, which is not an HD1910 plant (or the constants "
            "file could not be parsed); pass --plant p3|m5|ftservo explicitly"
        )
    key = DETECTED_TO_PRESET[det]
    want_kp = float(PLANTS[key]["kp_fw"])
    got_kp = info.get("kp_fw")
    if got_kp is None or abs(float(got_kp) - want_kp) > 1e-9:
        raise SystemExit(
            f"live plant {det} reports kp_fw={got_kp} but preset {key} says {want_kp}; "
            "the live constants file is inconsistent — fix it with apply_to_live.py "
            "before rehearsing"
        )
    return key, PLANTS[key]


def _patch_upstream(mod):
    """Replace XL330 motor_name lookup with the resolved HD1910 preset."""
    plant = _STATE["plant"]
    if plant is None:  # pragma: no cover - main() always resolves first
        raise SystemExit("bug: plant not resolved before load_upstream")
    json_file = str(pathlib.Path(plant["json_path"]).resolve())
    if not pathlib.Path(json_file).is_file():
        raise SystemExit(f"HD1910 plant JSON missing: {json_file}")

    def load_bam_model(kp_fw: float, vin: float, max_current):
        from bam.model import load_model

        # Case-insensitive actuator table key is HD1910 (see tools/bam_actuators.py).
        bam_model = load_model(json_file=json_file)
        bam_model.actuator.kp = kp_fw
        bam_model.actuator.vin = vin
        bam_model.actuator.max_current = (
            max_current if (max_current and max_current > 0) else None
        )
        return bam_model

    mod.load_bam_model = load_bam_model
    mod.BAM_MOTOR_NAME = "hd1910"
    mod.BAM_MODEL = plant["model"]
    mod.BAM_KP_FW = float(plant["kp_fw"])
    return mod


_orig_load_upstream = rd.load_upstream


def _load_upstream_hd1910(path: pathlib.Path):
    return _patch_upstream(_orig_load_upstream(path))


rd.load_upstream = _load_upstream_hd1910


def _publish_parity(key: str, plant: dict, kp_fw: float) -> None:
    """Annotate the JSON so readers cannot confuse this with an XL330 rehearsal.

    ``kp_fw`` is the **effective** gain, i.e. the one ``--kp-fw`` asked for when
    given. The old code always printed ``plant['kp_fw']``, so a kp sweep wrote
    four reports whose top-level plant fingerprint all read "kp_fw=5" — only the
    per-run ``settings.kp_fw`` told the truth. A sweep is exactly when readers
    compare fingerprints, so this must not lie.
    """
    json_name = pathlib.Path(plant["json_path"]).name
    rd.TRAINING_PARITY = {
        "same": [
            f"HD1910 plant '{key}' = {plant['id']} (json={json_name}, "
            f"kp_fw={kp_fw:g}, model={plant['model']}, "
            "target_names_expr excludes passive_*) — patched via rehearse_hd1910.py",
            *list(_BASE_PARITY["same"][1:]),
        ],
        "differs": [
            *list(_BASE_PARITY["differs"]),
            f"plant is {plant['id']} (kp_fw={kp_fw:g}), not XL330 m6 "
            "(kp_fw=200); infer_policy.py itself is unchanged",
        ],
    }


def _strip_plant(argv: list[str]) -> list[str]:
    """Drop ``--plant VAL`` / ``--plant=VAL`` *including its value*.

    Stripping only the flag leaves the preset name as a stray positional in the
    argv forwarded to rehearse_deploy, which then dies on an unrecognised
    argument — so consume the value too.
    """
    out: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--plant":
            i += 2  # flag + value
            continue
        if a.startswith("--plant="):
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def _inject_defaults(argv: list[str], kp_fw: float) -> list[str]:
    """Ensure --onnx / --kp-fw / --out exist; leave user overrides alone."""
    out = list(argv)
    if "--onnx" not in out:
        onnx = resolve_latest_onnx()
        out = ["--onnx", str(onnx), *out]
    else:
        onnx = pathlib.Path(_flag_value(out, "--onnx") or "")
    # Cross-plant guard: the ONNX was trained on some plant; rehearsing it at a
    # different one is the XL330<->HD1910 incident all over again. Read the
    # companion meta (best effort) and refuse the mismatch loudly. We check as
    # long as the plant is resolvable from the meta -- the ONNX file itself need
    # not exist yet (e.g. a dry-run guard before the export lands).
    rehearse_key = _STATE["key"]
    if onnx and rehearse_key is not None:
        onnx_key = _onnx_plant_key(onnx)
        if onnx_key and onnx_key != rehearse_key:
            print(
                f"⚠️  CROSS-PLANT REHEARSAL: ONNX {_rel(onnx)} was trained on "
                f"plant '{PLANTS[onnx_key]['id']}' (kp_fw={PLANTS[onnx_key]['kp_fw']:g}) "
                f"but you are rehearsing at '{PLANTS[rehearse_key]['id']}' "
                f"(kp_fw={kp_fw:g}). The BAM duty/command numbers will NOT match the "
                f"policy's training plant. Pass --plant {onnx_key} to rehearse it at home."
            )
    if "--kp-fw" not in out:
        # rehearse_deploy hardcodes 200 when kp_fw is None — always pin the plant's P.
        out = ["--kp-fw", str(kp_fw), *out]
    if "--out" not in out:
        # Name the report after the run, not after some long-gone iteration --
        # a file called *it1600.json holding iter-2500 numbers is a trap.
        tag = onnx.parent.name or onnx.stem or "unknown"
        out = ["--out", str(ROOT / "out" / f"rehearse_{tag}.json"), *out]
    # Non-walking policies (GroundPick / StandUp) do not respond to a velocity
    # command, so a non-zero cmd_vx makes rehearsal's moves_forward gate fail
    # spuriously. Feeding 0 turns that gate into not_applicable in
    # rehearse_deploy (cmd_vx < 0.2 => forward_gate True + not_applicable). Walk
    # policies keep rehearsal's default and are genuinely exercised.
    if "--cmd-vx" not in out and not _is_walking_task(_onnx_task(onnx)):
        out = ["--cmd-vx", "0", *out]
    _report_onnx(onnx, pathlib.Path(_flag_value(out, "--out") or ""))
    return out


def main(argv: list[str] | None = None) -> int:
    # Lightweight pre-parse so ``-h`` mentions the defaults; real parse is inside
    # rehearse_deploy.main.
    pre = argparse.ArgumentParser(
        description="HD1910 deploy rehearsal. Forwards all flags to tools/rehearse_deploy.py.",
        add_help=False,
    )
    pre.add_argument("-h", "--help", action="store_true")
    pre.add_argument("--plant", default="live", help="live|p3|p8|m5|ftservo")
    known, rest = pre.parse_known_args(argv)

    if known.help:
        try:
            newest = str(resolve_latest_onnx().relative_to(ROOT))
        except SystemExit:
            newest = "(none found -- pass --onnx)"
        print(
            "HD1910 wrapper defaults:\n"
            f"  --plant : {known.plant}   (p3={HD1910_OFFICIAL_M6_KP5['id']}, "
            f"p8={HD1910_OFFICIAL_M6_KP8['id']}, "
            f"m5={HD1910_OPENMICRODUCK_M5['id']}, "
            f"ftservo={HD1910_FTSERVO_OFFICIAL_M6['id']})\n"
            f"  --onnx  : newest under logs/rsl_rl/  ->  {newest}\n"
            f"  --out   : out/rehearse_<run-dir>.json  (derived from the ONNX)\n"
            "\nForwarded to rehearse_deploy (pass any of its flags):\n"
        )
        return rd.main(["--help"])

    # --plant was consumed above, so it must not reach the forwarded argv.
    rest = _strip_plant(rest)
    key, plant = resolve_plant(known.plant)
    _STATE["key"], _STATE["plant"] = key, plant
    # --kp-fw wins over the preset: the caller is pinning the firmware P, and
    # every report must say which P it was actually run at (kp sweep).
    override = _flag_value(rest, "--kp-fw")
    kp_fw = float(override) if override is not None else float(plant["kp_fw"])
    _publish_parity(key, plant, kp_fw)

    print(
        f"plant: {key} -> {plant['id']}  json={pathlib.Path(plant['json_path']).name}  "
        f"kp_fw={kp_fw:g}"
        + ("" if override is None else f"  (--kp-fw overrides preset "
           f"{float(plant['kp_fw']):g})")
    )
    return rd.main(_inject_defaults(rest, kp_fw))


if __name__ == "__main__":
    raise SystemExit(main())
