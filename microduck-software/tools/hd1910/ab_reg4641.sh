#!/usr/bin/env bash
# A/B: reg46（目标速度）与 reg41（加速度）到底谁在限制阶跃整定时间。
#
# 为什么要重做
# ------------
# 第一次 A/B 的结论是「reg46 300 → 4095 把整定从 561 ms 压到 161 ms」，据此写下了
# 「部署必须写 reg46、默认 300 距需求差 7.6 倍」。但 `_arm()` 一次写三个寄存器
# （reg46 / reg41 / reg48），只盯着 reg46 就会漏看 reg41 —— 而后来单独测 reg46 的
# 150/300/450 三档在 mode=4 下**没有任何差别**，与那条结论直接矛盾。
# ⇒ 结论已撤回，但这个 A/B 本身从没被正确地跑过。本脚本把两个变量分开：
#   改 reg46 时把 reg41 钉死，改 reg41 时把 reg46 钉死，并且**回读**两者。
#
# 判据（先写好，跑完再对）
# ------------------------
# - 整定时间 settle_ms 与峰速 v_p95_steps 一起看：只有速度变了而整定没变，
#   才说明这个寄存器不是瓶颈（或在该 mode 下无效）。
# - 回读值 ≠ 请求值 ⇒ 该档被固件截断，这一档的数据不代表"设了就有"。
#
# 需要硬件：舵机上电、串口在线。参数：
#   PORT=COM3 ID=10 REPS=3 bash tools/hd1910/ab_reg4641.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv-mjlab/Scripts/python.exe
IDENT=tools/hd1910/servo_probe/hd1910_ident.py

PORT="${PORT:-COM3}"
ID="${ID:-10}"
REPS="${REPS:-3}"
# 出厂值：reg46=300、reg41=10、reg48=1000（见 eeprom_backup_id10.json）
BASE_SPEED="${BASE_SPEED:-300}"
BASE_ACCEL="${BASE_ACCEL:-10}"
OUT="out/ab_reg4641"
mkdir -p "$OUT"

echo "== A/B: reg46 vs reg41 =="
echo "port=$PORT id=$ID reps=$REPS  base: reg46=$BASE_SPEED reg41=$BASE_ACCEL"

# ---- ① reg46 单变量：reg41 钉死在出厂值 ----
echo
echo "--- ① reg46 ∈ {150,300,450,1000,4095}，reg41 钉死 $BASE_ACCEL ---"
for V in 150 300 450 1000 4095; do
  for R in $(seq 1 "$REPS"); do
    J="$OUT/reg46_${V}_r${R}.json"
    echo "  reg46=$V rep=$R -> $J"
    "$PY" "$IDENT" --port "$PORT" --id "$ID" step \
      --speed "$V" --accel "$BASE_ACCEL" --torque-limit 1000 \
      --json "$J" > "$OUT/reg46_${V}_r${R}.log" 2>&1 || {
        echo "    ⚠️ 退出码非 0，看 $OUT/reg46_${V}_r${R}.log"; }
  done
done

# ---- ② reg41 单变量：reg46 钉死在出厂值 ----
echo
echo "--- ② reg41 ∈ {0,10,50,100,254}，reg46 钉死 $BASE_SPEED ---"
for V in 0 10 50 100 254; do
  for R in $(seq 1 "$REPS"); do
    J="$OUT/reg41_${V}_r${R}.json"
    echo "  reg41=$V rep=$R -> $J"
    "$PY" "$IDENT" --port "$PORT" --id "$ID" step \
      --speed "$BASE_SPEED" --accel "$V" --torque-limit 1000 \
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

def group(prefix, key):
    g = {}
    for r in rows:
        if r["file"].startswith(prefix):
            g.setdefault(r[key], []).append(r)
    return g

for prefix, key, pinned in (("reg46", "reg46_req", "reg41"), ("reg41", "reg41_req", "reg46")):
    g = group(prefix, key)
    n = len(next(iter(g.values()))) if g else 0
    print(f"=== {key} 单变量（{pinned} 钉死，每档 {n} 次重复）===")
    print(f"{key:>8} {'回读':>8} | {'整定 ms':>10} | {'峰速 p95 步/s':>13} | 超调%")
    for v in sorted(group(prefix, key)):
        rs = group(prefix, key)[v]
        st_ = [r["settle_ms"] for r in rs if r["settle_ms"] is not None]
        vs = [r["v_p95"] for r in rs if r["v_p95"] is not None]
        rb_key = f"{prefix}_rb"
        rbs = {r[rb_key] for r in rs}
        trunc = "" if rbs == {v} else f"  ⚠️ 回读={sorted(rbs)}（被截断/未生效）"
        if st_:
            s_settle, s_v = f"{st.mean(st_):10.0f}", f"{st.mean(vs):13.0f}"
        else:
            s_settle, s_v = f"{'n/a':>10}", f"{'n/a':>13}"
        print(f"{v:>8} {sorted(rbs)[0] if len(rbs) == 1 else '?':>8} | "
              f"{s_settle} | {s_v} | "
              f"{st.mean([r['over_pct'] for r in rs]):.1f}{trunc}")
    print()
PYEOF
echo "证据 -> $OUT/  （跑完把这张表贴进 docs/05-flat-walk.md §15）"
