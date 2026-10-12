"""キャップとつまみを 1 枚の 3MF に。設定は 9/29 のプレートの 3MF（A1 mini 0.4・Bambu PLA Basic）を元に、小物向けに 4 項目だけ変える。STL は刷る向きで出ているので裏返さない。"""
import json, sys, zipfile
from pathlib import Path
import trimesh
R = Path(sys.argv[1]); SRC = Path(sys.argv[2]); OUT = Path(sys.argv[3])
TPL = R / "build/print_3mf_20260929/right_3_plate.3mf"
OVERRIDE = {"layer_height": "0.12", "wall_loops": "6", "sparse_infill_density": "100%", "sparse_infill_pattern": "zig-zag"}
parts = ["right_stick_cap_d16", "left_knob_d18_b1", "left_knob_d18_b2", "left_knob_d18_b3"]
ms = []
for s in parts:
    m = trimesh.load(SRC / f"{s}.stl"); assert m.is_watertight, s
    m.apply_translation([-m.bounds[:, 0].mean(), -m.bounds[:, 1].mean(), -m.bounds[0][2]]); ms.append((s, m))
gap = 8.0; w = sum(m.extents[0] for _, m in ms) + gap * (len(ms) - 1); x = 90 - w / 2
objs, items, cfg = [], [], []
for i, (s, m) in enumerate(ms, 1):
    v = "".join(f'<vertex x="{a:.5f}" y="{b:.5f}" z="{c:.5f}"/>' for a, b, c in m.vertices)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in m.faces)
    objs.append(f'<object id="{i}" type="model"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>')
    cx = x + m.extents[0] / 2; x += m.extents[0] + gap; items.append((100 + i, i, cx))
    cfg.append(f'<object id="{100 + i}"><metadata key="name" value="{s}"/><metadata key="extruder" value="1"/><part id="{i}" subtype="normal_part"><metadata key="name" value="{s}"/></part></object>')
with zipfile.ZipFile(TPL) as z:
    files = {n: z.read(n) for n in z.namelist()}
head = files["3D/Objects/caps.model"].decode().split("<resources>")[0]
files["3D/Objects/caps.model"] = (head + "<resources>" + "".join(objs) + "</resources></model>").encode()
top = files["3D/3dmodel.model"].decode().split("<resources>")[0]
files["3D/3dmodel.model"] = (top + "<resources>" + "".join(f'<object id="{o}" type="model"><components><component p:path="/3D/Objects/caps.model" objectid="{i}"/></components></object>' for o, i, _ in items)
    + "</resources><build>" + "".join(f'<item objectid="{o}" transform="1 0 0 0 1 0 0 0 1 {cx:.3f} 90.000 0" printable="1"/>' for o, _, cx in items) + "</build></model>").encode()
files["Metadata/model_settings.config"] = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>' + "".join(cfg) + "</config>").encode()
c = json.loads(files["Metadata/project_settings.config"])
for k, val in OVERRIDE.items():
    assert k in c, k; print("  ", k, c[k], "→", val); c[k] = val
files["Metadata/project_settings.config"] = json.dumps(c, indent=4).encode()
out = OUT / "joystick_4_cap_d16+knobs.3mf"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for n, b in files.items(): z.writestr(n, b)
print(out.name, [(s, m.extents.round(1).tolist()) for s, m in ms])
