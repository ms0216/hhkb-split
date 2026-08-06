"""生成した部品を PNG の一覧にする。3D ビューアが無くても中身を確認できる。

各部品を 4 方向から描き、寸法を添える。STL を開く手段が無い環境でも
「何ができたか」を目で確かめられるようにするためのもの。
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

BUILD = Path(__file__).resolve().parent.parent / "build"
VIEWS = [(25, -60), (90, -90), (-90, -90), (0, -90)]
VIEW_NAMES = ["iso", "top", "bottom", "front"]


def panel(ax, mesh, elev, azim, title):
    lo, hi = mesh.bounds
    e, a = np.radians(elev), np.radians(azim)
    view = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
    tris = mesh.triangles
    order = np.argsort(tris.mean(axis=1) @ view)
    ax.add_collection3d(Poly3DCollection(
        tris[order], facecolor="#9fb6d4", edgecolor="#33465e", linewidths=0.05))
    ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_zlim(lo[2], hi[2])
    ax.set_box_aspect(hi - lo)
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    ax.set_title(title, fontsize=8)


def main(names=None):
    stls = sorted(p for p in BUILD.glob("*.stl")
                  if not p.stem.startswith(("smoke", "dbg")))
    if names:
        stls = [p for p in stls if p.stem in names]
    for p in stls:
        mesh = trimesh.load(str(p))
        size = mesh.bounds[1] - mesh.bounds[0]
        fig = plt.figure(figsize=(4.2 * len(VIEWS), 4.4), dpi=130)
        for i, ((elev, azim), vn) in enumerate(zip(VIEWS, VIEW_NAMES), start=1):
            panel(fig.add_subplot(1, len(VIEWS), i, projection="3d"),
                  mesh, elev, azim, vn)
        fig.suptitle(f"{p.stem}    {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm    "
                     f"watertight={mesh.is_watertight}", fontsize=11)
        out = BUILD / f"view_{p.stem}.png"
        fig.savefig(out, bbox_inches="tight")
        plt.close(fig)
        print(f"{size[0]:7.1f} x {size[1]:6.1f} x {size[2]:6.1f} mm  {out.name}")


if __name__ == "__main__":
    main(sys.argv[1:] or None)
