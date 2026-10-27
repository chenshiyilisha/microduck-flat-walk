import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
src = ROOT / ".upstream" / "j_hd1910_calibration_params_hd1910_characterization.json"
data = json.loads(src.read_text(encoding="utf-8"))


def flatten(node, prefix=""):
    if isinstance(node, dict):
        if "value" in node and len(node) <= 5:
            print(f"  {prefix:<34} {node['value']:<14} [{node.get('source', '?')}] {node.get('unit', '')}")
            return
        for k, v in node.items():
            flatten(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(node, list):
        print(f"  {prefix:<34} {node} (list)")
    else:
        print(f"  {prefix:<34} {node}")


print("顶层键:", list(data.keys()))
for key, val in data.items():
    if isinstance(val, (dict, list)):
        print(f"\n[{key}]")
        flatten(val)
    else:
        print(f"{key}: {val}")
