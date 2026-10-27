# SPDX-License-Identifier: Apache-2.0
"""Package an exported ONNX as a policy the official runtime can actually load.

Why this file exists
--------------------
An `.onnx` alone is not a policy. `duck-control` loads it together with a `manifest.json`
whose `obs_len` has to equal 61 and whose `action_len` has to equal 14, and it refuses the
pair when either disagrees (`docs/policy-manifest.md`, schema 2). The manifest is also where
the honest part of a policy lives: what it was trained with, what it was measured in, and how
it did — the `eval` object is free-form on purpose.

Two things this checks that a plain exporter cannot:

  - the graph's input is named `obs` and is width `obs_len`, with a dynamic batch axis;
  - the manifest's `obs_len` is read off the graph rather than typed in, so the two cannot
    drift apart.

  python tools/make_manifest.py --policy out/deploy61.onnx --robustness out/robustness61.json \\
      --name duck-walk-61 --bundle out/publish/duck-walk-61

The bundle layout is the single-policy repo shape the Hub expects: `policy.onnx` beside
`manifest.json`, plus `media/preview.mp4` when a clip is given.
"""

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import sys

import onnx

ROOT = pathlib.Path(__file__).resolve().parent.parent


def inspect_graph(path):
  """Return (obs_len, act_len, input_name) and refuse anything the runtime would refuse."""
  model = onnx.load(str(path))
  if len(model.graph.input) != 1:
    raise SystemExit(f"FAIL: {len(model.graph.input)} graph inputs, the runtime feeds one")
  inp = model.graph.input[0]
  dims = inp.type.tensor_type.shape.dim
  if inp.name != "obs":
    raise SystemExit(f"FAIL: input is named {inp.name!r}; duck-control feeds 'obs'")
  if len(dims) != 2:
    raise SystemExit(f"FAIL: input has {len(dims)} dims, expected (batch, obs_len)")
  obs_len = dims[1].dim_value
  if not obs_len:
    raise SystemExit("FAIL: obs width is symbolic; it has to be a number the manifest can carry")
  if dims[0].dim_value:  # 0 means symbolic, which is what dynamic_axes produces
    raise SystemExit("FAIL: batch axis is fixed; the runtime batches with check_matrix")

  out = model.graph.output[0]
  act_len = out.type.tensor_type.shape.dim[1].dim_value
  ops = {n.op_type for n in model.graph.node}
  # The normalisation must be inside the graph. Sub and Div are exactly what it looks like;
  # a graph without them is a graph that expects someone else to normalise, which on the
  # robot means nobody does.
  if not {"Sub", "Div"} <= ops:
    raise SystemExit(f"FAIL: no Sub/Div in the graph ({sorted(ops)}); normalisation is not baked in")
  return obs_len, act_len, out.name


def summarise_robustness(path):
  """Condense a robustness run into the few numbers a reader of the manifest needs."""
  if not path:
    return None
  data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
  conds = data.get("conditions", {})
  nom = conds.get("nominal", {})
  worst = min(conds.items(), key=lambda kv: kv[1]["tracking_ratio"]) if conds else None
  gate_rows = data.get("gates", [])
  return {
    "harness": "tools/robustness.py (MuJoCo CPU, plant variants + control-loop perturbations)",
    "command": data.get("command"),
    "seconds": data.get("seconds"),
    "envs": data.get("envs"),
    "nominal_tracking": round(nom.get("tracking_ratio", 0.0), 3),
    "nominal_falls": nom.get("falls"),
    "nominal_survival": round(nom.get("survival", 0.0), 3),
    "nominal_tilt_max_deg": round(nom.get("tilt_max_deg", 0.0), 1),
    "nominal_heading_error_deg": round(nom.get("heading_error_deg_median", 0.0), 1),
    "speed_mps": {
      "median": round(nom.get("speed_mps_median", 0.0), 3),
      "p10": round(nom.get("speed_p10", 0.0), 3),
      "p90": round(nom.get("speed_p90", 0.0), 3),
    },
    "worst_condition": worst[0] if worst else None,
    "worst_tracking": round(worst[1]["tracking_ratio"], 3) if worst else None,
    "gates_passed": sum(1 for r in gate_rows if r["pass_"]),
    "gates_total": len(gate_rows),
    "per_condition": {
      k: {"tracking": round(v["tracking_ratio"], 3), "falls": v["falls"], "plant": v["plant"]}
      for k, v in conds.items()
    },
  }


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--policy", type=pathlib.Path, required=True, help="exported .onnx")
  ap.add_argument("--name", default=None, help="policy name; defaults to the file stem")
  ap.add_argument("--kind", default="perpetual", choices=("perpetual", "episodic", "scripted"))
  ap.add_argument("--slot", default="walk", help="slot a perpetual gait loads into")
  ap.add_argument("--action-scale", type=float, default=1.0)
  ap.add_argument("--description", default=None)
  ap.add_argument("--robustness", type=pathlib.Path, default=None, help="json from robustness.py")
  ap.add_argument("--preview", type=pathlib.Path, default=None, help="mp4 shown by policy search")
  ap.add_argument("--trained-in", default=None, help="free text: which plant/checkpoint")
  ap.add_argument("--status", default="sim-only-hardware-candidate",
                  help="honest headline: has this ever run on hardware?")
  ap.add_argument("--dr", default="none beyond reset jitter",
                  help="domain randomisation actually used during training")
  ap.add_argument("--force-limit", type=float, default=0.96, help="torque ceiling the policy saw")
  ap.add_argument("--timestep", type=float, default=0.005, help="physics timestep the policy saw")
  ap.add_argument("--out", type=pathlib.Path, default=None, help="where to write manifest.json")
  ap.add_argument("--bundle", type=pathlib.Path, default=None, help="build a publishable repo dir")
  args = ap.parse_args()

  obs_len, act_len, out_name = inspect_graph(args.policy)
  if act_len != 14:
    raise SystemExit(f"FAIL: action width {act_len}, the robot has 14 joints")
  name = args.name or args.policy.stem
  sha = hashlib.sha256(args.policy.read_bytes()).hexdigest()

  manifest = {
    "schema_version": 2,
    "model_api": 1,
    "obs_len": obs_len,
    "action_len": act_len,
    "robot": {"model": "microduck", "hw_rev": 1, "servos": "xl330", "control_hz": 50},
    "name": name,
    "description": args.description
    or f"Velocity-tracking gait, {obs_len}-D deployable observation, trained and measured on CPU.",
    "status": args.status,
    "kind": args.kind,
    "action_scale": args.action_scale,
    "entry_pose": "standing",
    "command": {
      "encoding": "constant",
      "layout": "twist(3), head_pose(4), body_pose(6)",
      "idle": [0, 0, 0],
      "twist": "vx, vy, vyaw in m/s and rad/s; the runtime writes this block every tick",
      "head": "unused (zeros): this policy holds the nominal head pose",
      "body": "unused (zeros): nominal stance, not a placeholder",
    },
    "deployment": {
      "observation_normalizer_baked": True,
      "expected_action_filter": "none",
      "action_offset": "ctrl = stand_keyframe + action_scale * action (the graph emits the delta)",
      "runtime_lowpass_pass_through": {"head_lowpass": 1.0, "legs_lowpass": 1.0},
    },
    "training": {
      "task_id": "velocity",
      "repo": "tailong-wu/microduck-mjbatch (PPO/CPU) + local train_official.py observation layout",
      "checkpoint": args.policy.stem,
      "exported": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
      "environment": {
        "actuator": f"stock MuJoCo position servo, kp {5.0}, kv {0.3}, torque ceiling "
        f"{args.force_limit:.4f} N m",
        "backlash": False,
        "domain_randomisation": args.dr,
        "control_hz": 50,
        "sim_timestep_s": args.timestep,
      },
      "note": args.trained_in
      or "no BAM motor model, no backlash; see the eval block for what the missing pieces cost",
    },
    "eval": {
      "onnx_sha256": sha,
      "graph_input": "obs",
      "graph_output": out_name,
      "normalisation": "baked in (Sub/Div present in graph)",
      "robustness": summarise_robustness(args.robustness),
    },
  }
  if args.kind == "perpetual":
    manifest["slot"] = args.slot
  if args.preview and args.preview.exists():
    manifest["media"] = {"preview": "media/preview.mp4", "audio": False}

  text = json.dumps(manifest, indent=2, ensure_ascii=False)
  out = args.out or args.policy.with_name("manifest.json")
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text(text, encoding="utf-8")
  print(f"graph        obs[{obs_len}] -> {out_name}[{act_len}]  sha256 {sha[:16]}...")
  print(f"manifest     {out}")

  if args.bundle:
    bundle = args.bundle
    (bundle / "media").mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.policy, bundle / "policy.onnx")
    (bundle / "manifest.json").write_text(text, encoding="utf-8")
    if args.preview and args.preview.exists():
      shutil.copy2(args.preview, bundle / "media" / "preview.mp4")
    print(f"bundle       {bundle}  (policy.onnx, manifest.json"
          f"{', media/preview.mp4' if args.preview and args.preview.exists() else ''})")

  if obs_len != 61:
    print(f"WARNING      obs_len is {obs_len}, not 61: duck-control will refuse this policy")


if __name__ == "__main__":
  main()
