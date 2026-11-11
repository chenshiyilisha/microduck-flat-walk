"""B6 regression: every document mentioning VL53L8CX must carry a supersede pointer.

The ToF decision was closed in the SSOT (VL53L5CX V2; L8CX 33.4 mm cannot fit
the 20 mm face-shell hole pitch). Historical docs may keep the old part number
as a historical fact, but a reader must not be able to mistake it for a live
BOM line. Negative controls prove the pointer check is not a no-op.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
DOCS = REPO / "docs"

# A document is "pointed" if it names the replacement part or explicitly marks
# the old text as superseded / historical / revised.
POINTER_TOKENS = ("VL53L5CX", "L5CX", "作废", "过时", "改判", "订正", "归档界线")
SSOT_REF = "microduck-最优方案-价格硬件软件-2026-11-06.md"


def l8cx_docs() -> list[pathlib.Path]:
    return [f for f in sorted(DOCS.rglob("*.md"))
            if "L8CX" in f.read_text(encoding="utf-8", errors="replace")]


def has_pointer(text: str) -> bool:
    return any(tok in text for tok in POINTER_TOKENS)


def strict_target_ok(text: str) -> bool:
    """The exact predicate applied to the two B6 target documents."""
    return "L8CX" in text and "VL53L5CX" in text and SSOT_REF in text and has_pointer(text)


def test_all_l8cx_documents_have_a_supersede_pointer():
    files = l8cx_docs()
    assert files, "no L8CX documents found -- the scan itself is broken"
    missing = [str(f.relative_to(REPO)) for f in files
               if not has_pointer(f.read_text(encoding="utf-8", errors="replace"))]
    assert not missing, "L8CX without a supersede pointer: %s" % missing


def test_the_two_previously_unpointed_docs_name_the_replacement_and_ssot():
    targets = [
        DOCS / "active" / "microduck-阶段3-自动跟随.md",
        DOCS / "archive" / "microduck-研究报告.md",
    ]
    for f in targets:
        text = f.read_text(encoding="utf-8", errors="replace")
        assert strict_target_ok(text), f


def test_negative_control_bare_l8cx_without_pointer_is_red():
    assert not has_pointer("| ToF | VL53L8CX | 1 | I2C @0x29 |")
    assert not strict_target_ok("| ToF | VL53L8CX | 1 | I2C @0x29 |")


def test_negative_control_removing_the_replacement_part_turns_red():
    text = (DOCS / "active" / "microduck-阶段3-自动跟随.md").read_text(
        encoding="utf-8", errors="replace")
    assert strict_target_ok(text)
    stripped = text.replace("VL53L5CX", "VL53L8CX")
    assert not strict_target_ok(stripped), "deleting the replacement part must be red"
