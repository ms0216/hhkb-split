"""刷る部品を、刷る向き（上面をベッドへ）に裏返して OrcaSlicer の CLI に通す。tools/slice_check.py の道具を借りる。"""
import re, sys
from pathlib import Path
import numpy as np, trimesh
PRN = sys.argv[4]
WT, SRC, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
sys.path.insert(0, str(WT / "tools"))
import slice_check as sc
sc.OUT = OUT / "gcode"
(OUT / "in").mkdir(parents=True, exist_ok=True)
binary = sc.find_binary(); machine, filament, process = sc.find_profiles(PRN)
print("プリンタ", machine.stem, "／", filament.stem, "／", process.stem)
for stl in sorted(SRC.glob("*.stl")):
    m = trimesh.load(stl)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))
    m.apply_translation([-m.bounds[:, 0].mean(), -m.bounds[:, 1].mean(), -m.bounds[0][2]])
    f = OUT / "in" / stl.name; m.export(f)
    r, outdir = sc.slice_one(binary, f, machine, filament, process, PRN)
    out = (r.stdout or "") + (r.stderr or "")
    warns = sorted(set(l.strip()[:110] for l in out.splitlines() if re.search(r"warn|error|fail|cannot|invalid|outside|exceed", l, re.I)))
    g = sorted(outdir.glob("*.gcode"))
    info = sc.summarize_gcode(g[0]) if g else {}
    print(("OK " if r.returncode == 0 and g else "NG ") + f"{stl.stem:20s} 外形 {m.extents.round(1).tolist()} {info}")
    for w in warns[:4]: print("      ", w)
