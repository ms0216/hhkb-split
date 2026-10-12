"""足した部品どうしの食い込み（check_inside.py は足した部品どうしを比べていなかった）。"""
import trimesh, numpy as np, sys, itertools, os
A = sys.argv[1]
for h in sys.argv[2:]:
    names = [n for n in ("joystick", "joystick_seat", "joystick_wire", "joystick_cap", "pod_board", "pod_mcu") if os.path.exists(f"{A}{h}_{n}.stl")]
    M = {n: trimesh.load(f"{A}{h}_{n}.stl") for n in names}
    for a, b in itertools.permutations(names, 2):
        p, _ = trimesh.sample.sample_surface(M[a], 40000)
        ins = int(M[b].contains(p).sum())      # split は networkx が要るので使わない
        if ins: print(f"{h}: {a} の表面 {ins}/40000 点が {b} の中")

