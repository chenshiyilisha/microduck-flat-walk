"""把 setuptools 已经构建好的 wheel 目录重新打成真正的 .whl。

为什么需要这个：`uv pip install .upstream/bam-mjlab_frictionloss` 会走 PEP 517
in-tree build，setuptools 把 wheel 内容写进 `build/bdist.win-amd64/wheel/` 之后
**要删掉这个目录**（85 个文件）。本机沙箱有「单轮删除超过 50 个文件需确认」的保护，
删除被拦 -> uv 判定构建失败 -> bam 装不上。dist-info 里的 RECORD 恰好被删掉。

规避办法：不重新构建，只给已有目录补一个 RECORD 再 zip 成 wheel。
装 wheel 文件不触发构建，也就不触发删除。

用法：
    python tools/make_bam_wheel.py            # 用默认目录
    python tools/make_bam_wheel.py --check    # 只校验不写文件
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHEEL_DIR = ROOT / ".upstream/bam-mjlab_frictionloss/build/bdist.win-amd64/wheel"
DIST_INFO = "better_actuator_models-1.0.1.dist-info"
OUT = ROOT / ".upstream/wheels/better_actuator_models-1.0.1-py3-none-any.whl"


def urlsafe_b64_nopad(digest: bytes) -> str:
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def collect(wheel_dir: Path) -> list[Path]:
    files = [p for p in wheel_dir.rglob("*") if p.is_file()]
    # RECORD 必须在最后写入（它是描述其它文件的清单）
    files = [p for p in files if p.name != "RECORD"]
    files.sort(key=lambda p: p.relative_to(wheel_dir).as_posix())
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wheel-dir", type=Path, default=WHEEL_DIR)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true", help="只列出将被打包的文件")
    args = ap.parse_args()

    if not args.wheel_dir.is_dir():
        print(f"FAIL: wheel dir 不存在: {args.wheel_dir}", file=sys.stderr)
        return 2

    files = collect(args.wheel_dir)
    if not files:
        print("FAIL: wheel dir 是空的", file=sys.stderr)
        return 2

    # 前置校验：WHEEL 里声明的 tag 决定文件名，二者必须一致
    wheel_meta = args.wheel_dir / DIST_INFO / "WHEEL"
    tag = None
    if wheel_meta.is_file():
        for line in wheel_meta.read_text(encoding="utf-8").splitlines():
            if line.startswith("Tag:"):
                tag = line.split(":", 1)[1].strip()
    print(f"文件数 {len(files)}  Tag={tag}")

    has_params = sum(1 for f in files if f.suffix == ".json")
    print(f"其中 .json（BAM 的舵机参数表）{has_params} 个")
    if has_params == 0:
        print("FAIL: 没有 params/**/*.json，装上去也没有舵机模型", file=sys.stderr)
        return 2

    if args.check:
        for f in files[:10]:
            print("  ", f.relative_to(args.wheel_dir).as_posix())
        print("   ...")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, str, str]] = []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in files:
            arc = f.relative_to(args.wheel_dir).as_posix()
            data = f.read_bytes()
            zf.writestr(arc, data)
            digest = hashlib.sha256(data).digest()
            records.append((arc, "sha256=" + urlsafe_b64_nopad(digest), str(len(data))))

        # RECORD 自身不记 hash/size
        record_path = f"{DIST_INFO}/RECORD"
        sio = io.StringIO()
        w = csv.writer(sio, lineterminator="\n")
        w.writerows(records)
        w.writerow((record_path, "", ""))
        zf.writestr(record_path, sio.getvalue().encode("utf-8"))

    args.out.write_bytes(buf.getvalue())
    print(f"写出 {args.out}  ({args.out.stat().st_size / 1024:.1f} KiB, RECORD {len(records) + 1} 行)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
