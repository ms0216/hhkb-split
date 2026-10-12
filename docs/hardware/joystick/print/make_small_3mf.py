"""小物の STL を 1 枚の 3MF に並べる。設定は利用者が Bambu Studio で保存した 3MF（雛形）のものを使い、指定した項目だけ変える。

  .venv/bin/python3 make_small_3mf.py <雛形.3mf> <出力.3mf> <STL の場所> key=value ... -- 部品名 ...

STL は刷る向きで出ている前提（向きは変えない）。雛形の例:
  0.4mm ノズル: build/print_3mf_20260929/right_3_plate.3mf
  0.2mm ノズル: build/print_3mf_20260929/keycaps_0.2nozzle/left_r0.3mf
"""
import json, sys, zipfile
from pathlib import Path
import trimesh
tpl, out, src = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
i = sys.argv.index("--"); override = dict(a.split("=", 1) for a in sys.argv[4:i]); parts = sys.argv[i + 1:]
ms = []
for s in parts:
    m = trimesh.load(src / f"{s}.stl"); assert m.is_watertight, f"{s} が閉じていない"
    m.apply_translation([-m.bounds[:, 0].mean(), -m.bounds[:, 1].mean(), -m.bounds[0][2]]); ms.append((s, m))
gap = 12.0; w = sum(m.extents[0] for _, m in ms) + gap * (len(ms) - 1); x = 90 - w / 2
assert w < 170, f"並べた幅 {w:.0f}mm がベッドに入らない"
objs, items, cfg = [], [], []
for n, (s, m) in enumerate(ms, 1):
    v = "".join(f'<vertex x="{a:.5f}" y="{b:.5f}" z="{c:.5f}"/>' for a, b, c in m.vertices)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in m.faces)
    objs.append(f'<object id="{n}" type="model"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>')
    cx = x + m.extents[0] / 2; x += m.extents[0] + gap; items.append((100 + n, n, cx))
    cfg.append(f'<object id="{100 + n}"><metadata key="name" value="{s}"/><metadata key="extruder" value="1"/><part id="{n}" subtype="normal_part"><metadata key="name" value="{s}"/></part></object>')
with zipfile.ZipFile(tpl) as z:
    files = {n: z.read(n) for n in z.namelist()}
mesh_name = [n for n in files if n.startswith("3D/Objects/")][0]
head = files[mesh_name].decode().split("<resources>")[0]
files[mesh_name] = (head + "<resources>" + "".join(objs) + "</resources></model>").encode()
top = files["3D/3dmodel.model"].decode().split("<resources>")[0]
files["3D/3dmodel.model"] = (top + "<resources>" + "".join(f'<object id="{o}" type="model"><components><component p:path="/{mesh_name}" objectid="{n}"/></components></object>' for o, n, _ in items)
    + "</resources><build>" + "".join(f'<item objectid="{o}" transform="1 0 0 0 1 0 0 0 1 {cx:.3f} 90.000 0" printable="1"/>' for o, _, cx in items) + "</build></model>").encode()
files["Metadata/model_settings.config"] = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>' + "".join(cfg) + "</config>").encode()
c = json.loads(files["Metadata/project_settings.config"])
print("  雛形:", c["printer_settings_id"], "/", c["print_settings_id"], "/", c["filament_settings_id"])
for k, val in override.items():
    assert k in c, f"雛形に無い項目: {k}"; print("  ", k, c[k], "→", val); c[k] = val
files["Metadata/project_settings.config"] = json.dumps(c, indent=4).encode()
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for n, b in files.items(): z.writestr(n, b)
print(out.name, "幅", round(w, 1), [(s, m.extents.round(1).tolist()) for s, m in ms])
