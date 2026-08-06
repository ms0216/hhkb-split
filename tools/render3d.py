"""PyVista（VTK）で厳密な陰影付き描画と断面表示を行う。

matplotlib による描画は三角形を奥行き順に並べているだけで、厳密な陰面消去を
しない。中空のケースでは内側の面が透けて判断できなかった。VTK は本物の
深度バッファを持つので、見えているものがそのまま形状である。

提供するもの:
  shots()    — 複数視点からの陰影付き描画
  section()  — 任意の平面で切った断面（内部構造の確認用）
  assembly() — 複数部品を色分けして重ね、組み立て状態を見る

すべてオフスクリーンで動く。表示環境は要らない。
"""

import sys
from pathlib import Path

import numpy as np
import pyvista as pv

pv.OFF_SCREEN = True

BUILD = Path(__file__).resolve().parent.parent / "build"

BG = "white"
FG = "#8fb0d6"
VIEWS = {
    "iso": (1.0, -1.0, 0.8),
    "top": (0.0, 0.0, 1.0),
    "bottom": (0.0, 0.0, -1.0),
    "front": (0.0, -1.0, 0.0),
    "rear": (0.0, 1.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "right": (1.0, 0.0, 0.0),
}


def _plot(window=(900, 700)):
    p = pv.Plotter(off_screen=True, window_size=window)
    p.set_background(BG)
    return p


def _aim(p, mesh, direction, zoom=1.0):
    c = np.array(mesh.center)
    r = float(np.linalg.norm(np.array(mesh.bounds[1::2]) - np.array(mesh.bounds[::2])))
    d = np.array(direction, dtype=float)
    d /= np.linalg.norm(d)
    up = (0, 0, 1) if abs(d[2]) < 0.99 else (0, 1, 0)
    p.camera_position = [tuple(c + d * r * 1.6), tuple(c), up]
    p.camera.zoom(zoom)


def shots(stl, out_png, views=("iso", "top", "bottom", "front"), title=None):
    """複数視点を 1 枚に並べる。"""
    mesh = pv.read(str(stl))
    p = pv.Plotter(off_screen=True, shape=(1, len(views)),
                   window_size=(560 * len(views), 560))
    for i, v in enumerate(views):
        p.subplot(0, i)
        p.set_background(BG)
        p.add_mesh(mesh, color=FG, smooth_shading=False)
        p.enable_lightkit()
        _aim(p, mesh, VIEWS[v], zoom=1.3)
        p.add_text(v, font_size=10, color="black")
    p.screenshot(str(out_png))
    p.close()
    return Path(out_png)


def section(stl, out_png, normal="x", origin=None, view=None, title=None):
    """平面で切って中身を見る。切り口を色分けする。

    view を省略すると、切り落とした側にカメラを置く。切り口の反対側から
    見ると外壁しか写らず、断面の意味がなくなるため（実際にそれをやった）。
    """
    mesh = pv.read(str(stl))
    org = origin if origin is not None else mesh.center
    kept = mesh.clip(normal=normal, origin=org, invert=True)
    cut = mesh.slice(normal=normal, origin=org)
    if view is None:
        base = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}[normal]
        # 真正面だと平面的になるので少し振る
        direction = tuple(b + 0.35 * o for b, o in zip(base, (0.0, -0.3, 0.5)))
    else:
        direction = VIEWS[view]
    p = _plot()
    p.add_mesh(kept, color=FG, smooth_shading=False)
    p.add_mesh(cut, color="#c0562f", line_width=4)
    p.enable_lightkit()
    _aim(p, mesh, direction, zoom=1.25)
    if title:
        p.add_text(title, font_size=10, color="black")
    p.screenshot(str(out_png))
    p.close()
    return Path(out_png)


def assembly(parts, out_png, view="iso", title=None, window=(1100, 850)):
    """複数部品を重ねて描く。

    parts: [(stl または pyvista mesh, 色, 不透明度), ...]
    """
    p = _plot(window)
    meshes = []
    for item, color, opacity in parts:
        m = pv.read(str(item)) if isinstance(item, (str, Path)) else item
        meshes.append(m)
        p.add_mesh(m, color=color, opacity=opacity, smooth_shading=False)
    p.enable_lightkit()
    merged = meshes[0]
    for m in meshes[1:]:
        merged = merged.merge(m)
    _aim(p, merged, VIEWS[view], zoom=1.2)
    if title:
        p.add_text(title, font_size=10, color="black")
    p.screenshot(str(out_png))
    p.close()
    return Path(out_png)


def main(names=None):
    stls = sorted(p for p in BUILD.glob("*.stl")
                  if not p.stem.startswith(("smoke", "dbg", "mut", "_")))
    if names:
        stls = [p for p in stls if p.stem in names]
    for s in stls:
        out = shots(s, BUILD / f"pv_{s.stem}.png")
        print(f"  {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
