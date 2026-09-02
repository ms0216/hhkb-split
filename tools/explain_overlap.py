"""分割で全体幅が増える理由を図で説明する。

原機は 15u に収まるのに、左右に割ると 7.25u + 9u = 16.25u になる。
差の 1.25u は「行ずれによって左右の担当範囲が x 方向で重なっている」ぶん。
1 枚のときは同じ帯を上下の行で分け合えるが、切り離すと両方がその帯の幅を持つ。
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

BUILD = Path(__file__).resolve().parent.parent / "build"
UNIT = 19.05

L, R = "#2f6fb5", "#c0562f"          # 左半分 / 右半分

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from layout import load_layout, split_halves  # noqa: E402

# 配列は layout/ の JSON から読む（2026-09-03 まで 3u+3u の写しを持っていて、
# 2.75u 化に取り残されていた）。右の島は分割 JSON で右へ離して置いてあるので、
# 原機の位置に戻す: 数字段は全部 1u で一意なので、左の数字段のキー数 n を
# 数え、原機の数字段 n 番目の左端を右の島の元の左端とする。
_ORIG = load_layout(ROOT / "layout" / "hhkb_original.json")
_L, _R = split_halves(load_layout(ROOT / "layout" / "hhkb_split.json"))
_n_left_row0 = sum(1 for k in _L if k.row == 0)
_right_min_orig = sorted(k.left_u for k in _ORIG if k.row == 0)[_n_left_row0]
_shift = min(k.left_u for k in _R if k.row == 0) - _right_min_orig

# (row, x, w, side)  side: "L" or "R"。x は原機の座標（u）
KEYS = [(k.row, k.left_u, k.w_u, "L") for k in _L] + \
       [(k.row, k.left_u - _shift, k.w_u, "R") for k in _R]

LEFT_MAX = max(x + w for _, x, w, s in KEYS if s == "L")     # 7.25u
RIGHT_MIN = min(x for _, x, w, s in KEYS if s == "R")        # 6.00u
RIGHT_MAX = max(x + w for _, x, w, s in KEYS if s == "R")    # 15.00u


def draw_keys(ax, dx_left=0.0, dx_right=0.0, alpha=1.0):
    for row, x, w, side in KEYS:
        dx = dx_left if side == "L" else dx_right
        ax.add_patch(
            Rectangle((x + dx, row), w - 0.06, 0.94,
                      facecolor=(L if side == "L" else R), alpha=alpha * 0.55,
                      edgecolor=(L if side == "L" else R), lw=0.8)
        )


def span(ax, x0, x1, y, text, color, above=True):
    ax.annotate("", xy=(x0, y), xytext=(x1, y),
                arrowprops=dict(arrowstyle="<->", color=color, lw=1.1))
    ax.text((x0 + x1) / 2, y + (0.18 if above else -0.32), text,
            ha="center", va="bottom" if above else "top", color=color, fontsize=9)


def main():
    BUILD.mkdir(exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), dpi=150)

    # ---- 上: 原機（1枚） -------------------------------------------------
    ax = axes[0]
    draw_keys(ax)
    # 重なり帯
    ax.add_patch(Rectangle((RIGHT_MIN, -0.15), LEFT_MAX - RIGHT_MIN, 5.3,
                           facecolor="gold", alpha=0.35, edgecolor="none", zorder=0))
    ax.text((RIGHT_MIN + LEFT_MAX) / 2, 5.45,
            f"overlap band  x = {RIGHT_MIN}u .. {LEFT_MAX}u  ({LEFT_MAX - RIGHT_MIN}u)",
            ha="center", fontsize=9, color="#8a6d00")
    ax.plot([LEFT_MAX, LEFT_MAX], [-0.15, 5.15], color=L, lw=1.0, ls="--")
    ax.plot([RIGHT_MIN, RIGHT_MIN], [-0.15, 5.15], color=R, lw=1.0, ls="--")
    ax.text(LEFT_MAX + 0.15, 3.6, "left half\nreaches\nx=7.25u", ha="left",
            va="center", fontsize=8, color=L)
    ax.text(RIGHT_MIN - 0.15, 0.5, "right half\nstarts at\nx=6.0u", ha="right",
            va="center", fontsize=8, color=R)
    span(ax, 0, 15, -0.7, "one board = 15.00u = 285.75 mm", "black", above=False)
    ax.set_title("1) original: the two hands' key groups OVERLAP in the x direction",
                 fontsize=11)

    # ---- 下: 分割後（2枚） -----------------------------------------------
    ax = axes[1]
    GAP = 1.0
    dxr = LEFT_MAX - RIGHT_MIN + GAP
    draw_keys(ax, dx_left=0.0, dx_right=dxr)
    ax.add_patch(Rectangle((0, -0.15), LEFT_MAX, 5.3, fill=False,
                           edgecolor=L, lw=1.4, ls="--"))
    ax.add_patch(Rectangle((RIGHT_MIN + dxr, -0.15), RIGHT_MAX - RIGHT_MIN, 5.3,
                           fill=False, edgecolor=R, lw=1.4, ls="--"))
    span(ax, 0, LEFT_MAX, -0.7, f"left = {LEFT_MAX}u = {LEFT_MAX * UNIT:.1f} mm", L,
         above=False)
    span(ax, RIGHT_MIN + dxr, RIGHT_MAX + dxr, -0.7,
         f"right = {RIGHT_MAX - RIGHT_MIN}u = {(RIGHT_MAX - RIGHT_MIN) * UNIT:.1f} mm",
         R, above=False)
    total = LEFT_MAX + (RIGHT_MAX - RIGHT_MIN)
    ax.text(0, 5.6,
            f"once separated each half needs its own full width: "
            f"{LEFT_MAX} + {RIGHT_MAX - RIGHT_MIN} = {total}u "
            f"({total * UNIT:.1f} mm)  ->  +{(total - 15) * UNIT:.1f} mm vs original",
            fontsize=10, color="black")
    ax.set_title("2) split: the overlap can no longer be shared, so it is counted twice",
                 fontsize=11)

    for ax in axes:
        ax.set_xlim(-0.6, 17.6)
        ax.set_ylim(6.2, -1.4)          # 上が数字段になるよう y を反転
        ax.set_aspect("equal")
        ax.set_axis_off()

    out = BUILD / "explain_overlap.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"左半分  x = 0.00 .. {LEFT_MAX}u  ({LEFT_MAX * UNIT:.1f} mm)")
    print(f"右半分  x = {RIGHT_MIN} .. {RIGHT_MAX}u  ({(RIGHT_MAX - RIGHT_MIN) * UNIT:.1f} mm)")
    print(f"重なり  x = {RIGHT_MIN} .. {LEFT_MAX}u  ({(LEFT_MAX - RIGHT_MIN) * UNIT:.1f} mm)")
    print(f"合計 {LEFT_MAX + RIGHT_MAX - RIGHT_MIN}u = "
          f"{(LEFT_MAX + RIGHT_MAX - RIGHT_MIN) * UNIT:.1f} mm "
          f"(原機 285.75mm との差 {(LEFT_MAX + RIGHT_MAX - RIGHT_MIN - 15) * UNIT:.1f} mm)")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
