#!/usr/bin/env bash
# 台架：reg46（速度上限）与 reg41（加速度斜坡）的单变量分离。
#
# 这脚本被推翻过两次，历史留在 docs/archive/05-flat-walk.md §20.3，结论只有四条：
#   ① reg46 = 速度上限，单位 ≈ 0.732 rpm/LSB ≈ 50 步/s 每 LSB；reg46=0 = 无上限。
#   ② reg41 = 加速度斜坡，越大越紧（整定越快）；reg41=0 = 无斜坡（最快）。
#   ③ reg46=0 时 reg41 被完全忽略（0/10 与 0/0 同速）；但上限本身单独生效
#      （accel=0, speed=5 → 峰速 286 ≈ 250+15%）。⇒ gate 在"斜坡"上，不在"上限"上。
#   ④ 扫参数必须扫到它开始响应的区间：reg46 从 150 到 4095 看着无差别，只是因为
#      那些上限（7500+ 步/s）远高于斜坡在 17.6° 内能达到的 ~640 步/s。
#
# 因此本脚本的设计是"各自隔离"，不是"两者互钉非零"：
#   ① reg46 扫描 → reg41 钉死 0（关掉斜坡，否则上限被斜坡掩盖）
#   ② reg41 扫描 → reg46 钉死 300（上限 15000 步/s，远超可达峰速 ⇒ 不约束）
# 上一版把另一路钉成非零（300/10）去扫，结果上限与斜坡两个效应叠在一起，
# 得到"reg46 从 150 到 4095 无差别"的假结论。
#
# 判据（先写，跑完再对）
# ---------------------
# - 峰速 p95 落在「50×reg46 步/s」的 0.8~1.3 倍内 ⇒ 上限生效；明显高于它 ⇒ 上限未生效。
# - 整定时间 settle_ms=None 表示 2~3 s 内没到位（上限很低时正常），不是失败。
# - 回读值 ≠ 请求值 ⇒ 被固件截断，该档不代表"设了就有"。
#
# 参数：
#   PORT=COM3 ID=10 REPS=3 bash tools/hd1910/ab_reg4641.sh
#   EXTRA="--kp 5 --kd 0"   在部署增益下做（出厂是 P=32/D=40）
#   HOLD=3                  每档保持秒数；reg46 很低时需要更长
#   OUT=out/ab_reg4641      输出目录
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
IDENT=tools/hd1910/servo_probe/hd1910_ident.py

PORT="${PORT:-COM3}"
ID="${ID:-10}"
REPS="${REPS:-3}"
HOLD="${HOLD:-3}"
BASE_SPEED="${BASE_SPEED:-300}"   # 扫 reg41 时钉死的 reg46（须大到不约束）
BASE_ACCEL="${BASE_ACCEL:-0}"    # 扫 reg46 时钉死的 reg41（须为 0，关掉斜坡）
EXTRA="${EXTRA:-}"               # 故意不加引号：按空格拆成多个参数
OUT="${OUT:-out/ab_reg4641}"
mkdir -p "$OUT"

echo "== 台架：reg46（速度上限）/ reg41（加速度斜坡）分离 =="
echo "port=$PORT id=$ID reps=$REPS hold=${HOLD}s  钉死: reg46=$BASE_SPEED reg41=$BASE_ACCEL"

# 防呆①：扫上限时斜坡必须关掉，否则上限被斜坡掩盖（上一版就错在这）。
if [ "$BASE_ACCEL" != "0" ]; then
  echo "⛔ 扫 reg46 时 BASE_ACCEL 必须为 0（关斜坡），当前=$BASE_ACCEL" >&2
  echo "   reg41≠0 会让整定停在上限与斜坡的混合效应上（见文档 §20.3 ④）。" >&2
  exit 2
fi
# 防呆②：扫斜坡时上限必须不约束。50 步/s per LSB，要求 ≥ 10× 需求峰速 640。
if [ "$BASE_SPEED" -lt 128 ]; then
  echo "⛔ 扫 reg41 时 BASE_SPEED 太小（=$BASE_SPEED ⇒ 上限≈$((BASE_SPEED*50)) 步/s），" >&2
  echo "   会与斜坡效应混在一起。用 ≥128（建议 300）。" >&2
  exit 2
fi

# 跑之前的现场状态
"$PY" - "$PORT" "$ID" <<'PYEOF' || echo "  ⚠️ 预读失败，继续但结论需人工核对"
import sys
sys.path.insert(0, "tools/hd1910/servo_probe")
import serial
from hd1910_readonly import query
port, sid = sys.argv[1], int(sys.argv[2])
s = serial.Serial(port, 1000000, timeout=0.1)
for name, addr, n in (("reg41 accel", 41, 1), ("reg46 speed", 46, 1),
                      ("reg48 torque", 48, 2), ("reg21 P", 21, 1),
                      ("reg22 D", 22, 1), ("reg33 mode", 33, 1)):
    v = query(s, sid, addr, n)
    print(f"  pre  {name:12s} = {v if not isinstance(v, list) else int.from_bytes(bytes(v), 'little')}")
s.close()
PYEOF

# ---- ① reg46 单变量（速度上限）：reg41=0 关掉斜坡 ----
echo
echo "--- ① reg46 ∈ {0,3,5,10,20,46,100,300,4095}，reg41 钉死 $BASE_ACCEL ---"
for V in 0 3 5 10 20 46 100 300 4095; do
  for R in $(seq 1 "$REPS"); do
    J="$OUT/reg46_${V}_r${R}.json"
    echo "  reg46=$V rep=$R -> $J"
    "$PY" "$IDENT" --port "$PORT" --id "$ID" step \
      --speed "$V" --accel "$BASE_ACCEL" --hold "$HOLD" --torque-limit 1000 $EXTRA \
      --json "$J" > "$OUT/reg46_${V}_r${R}.log" 2>&1 || {
        echo "    ⚠️ 退出码非 0，看 $OUT/reg46_${V}_r${R}.log"; }
  done
done

# ---- ② reg41 单变量（加速度斜坡）：reg46=300 不约束 ----
echo
echo "--- ② reg41 ∈ {0,5,10,50,100,254}，reg46 钉死 $BASE_SPEED ---"
for V in 0 5 10 50 100 254; do
  for R in $(seq 1 "$REPS"); do
    J="$OUT/reg41_${V}_r${R}.json"
    echo "  reg41=$V rep=$R -> $J"
    "$PY" "$IDENT" --port "$PORT" --id "$ID" step \
      --speed "$BASE_SPEED" --accel "$V" --hold "$HOLD" --torque-limit 1000 $EXTRA \
      --json "$J" > "$OUT/reg41_${V}_r${R}.log" 2>&1 || {
        echo "    ⚠️ 退出码非 0，看 $OUT/reg41_${V}_r${R}.log"; }
  done
done

# ---- 汇总 ----
echo
"$PY" - "$OUT" <<'PYEOF'
import glob, json, os, statistics as st, sys

out = sys.argv[1]
rows = []
for p in sorted(glob.glob(os.path.join(out, "*.json"))):
    d = json.load(open(p, encoding="utf-8"))
    a = d["armed"]
    ph = (d.get("phases") or {}).get("up")
    if not ph:
        continue
    rows.append({
        "file": os.path.basename(p),
        "reg46_req": a.get("reg46_speed_req"), "reg46_rb": a.get("reg46_speed_rb"),
        "reg41_req": a.get("reg41_accel_req"), "reg41_rb": a.get("reg41_accel_rb"),
        "settle_ms": ph.get("settle_ms"),
        "v_p95": ph.get("v_p95_steps"), "over_pct": ph.get("over_pct"),
    })

def mean(xs, fmt="{:.0f}"):
    v = [x for x in xs if x is not None]
    return fmt.format(st.mean(v)) if v else "n/a"

def group(prefix, key):
    g = {}
    for r in rows:
        if r["file"].startswith(prefix):
            g.setdefault(r[key], []).append(r)
    return g

for prefix, key in (("reg46", "reg46_req"), ("reg41", "reg41_req")):
    g = group(prefix, key)
    n = len(next(iter(g.values()))) if g else 0
    hdr_extra = "上限 50×V 步/s" if prefix == "reg46" else "—"
    print(f"=== {key} 单变量（每档 {n} 次重复）===")
    print(f"{key:>8} {'回读':>6} | {'整定 ms':>9} | {'峰速 p95 步/s':>13} | {hdr_extra}")
    for v in sorted(g):
        rs = g[v]
        rbs = {r[f"{prefix}_rb"] for r in rs}
        trunc = "" if rbs == {v} else f"  ⚠️ 回读={sorted(rbs)}"
        theo = f"{v * 50}" if prefix == "reg46" else "-"
        print(f"{v:>8} {(sorted(rbs)[0] if len(rbs) == 1 else -1):>6} | "
              f"{mean([r['settle_ms'] for r in rs]):>9} | "
              f"{mean([r['v_p95'] for r in rs]):>13} | {theo:>10}{trunc}")
    print()
PYEOF
echo "证据 -> $OUT/"
echo "把两张表贴进 docs/archive/05-flat-walk.md §20.3，并按「50×reg46 步/s」核对上限是否生效。"
