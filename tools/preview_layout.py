"""配列 JSON を図にして目視確認する。layout.py の出力だけを描く。"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout import UNIT, bounds_mm, load_layout, split_halves  # noqa: E402

BUILD = Path(__file__).resolve().parent.parent / "build"


def draw(ax, keys, title, colors=None):
    for k in keys:
        c = colors(k) if colors else "#8fb3d9"
        ax.add_patch(Rectangle((k.x_mm - k.w_mm / 2, k.y_mm - k.h_mm / 2),
                               k.w_mm - 1.0, k.h_mm - 1.0,
                               facecolor=c, edgecolor="#33465e", lw=0.7))
        ax.text(k.x_mm, k.y_mm, k.label, ha="center", va="center", fontsize=5.5)
    x0, y0, x1, y1 = bounds_mm(keys)
    ax.set_xlim(x0 - 6, x1 + 6)
    ax.set_ylim(y1 + 6, y0 - 6)
    ax.set_aspect("equal")
    ax.set_title(f"{title}   {x1 - x0:.1f} x {y1 - y0:.1f} mm   ({len(keys)} keys)",
                 fontsize=10)
    ax.set_axis_off()


def main():
    BUILD.mkdir(exist_ok=True)
    orig = load_layout("layout/hhkb_original.json")
    split = load_layout("layout/hhkb_split.json")
    left, right = split_halves(split)
    lset = set(id(k) for k in left)

    fig, axes = plt.subplots(2, 1, figsize=(13, 7), dpi=150)
    draw(axes[0], orig, "hhkb_original.json")
    draw(axes[1], split, "hhkb_split.json",
         colors=lambda k: "#8fb3d9" if id(k) in lset else "#e0a48c")
    out = BUILD / "layout_preview.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    for name, ks in (("original", orig), ("split", split)):
        x0, y0, x1, y1 = bounds_mm(ks)
        print(f"{name:9s} {len(ks):3d} keys  {x1 - x0:7.2f} x {y1 - y0:6.2f} mm")
    for name, ks in (("left", left), ("right", right)):
        x0, y0, x1, y1 = bounds_mm(ks)
        print(f"  {name:7s} {len(ks):3d} keys  {x1 - x0:7.2f} x {y1 - y0:6.2f} mm")
    print(out)


if __name__ == "__main__":
    main()
