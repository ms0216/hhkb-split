"""右手 XIAO 裏面の SWD 配線図を描く（docs/development/ へ入れる）。

出典:
  パッドの位置  … Seeed 公式 XIAO_nRF52840_Sense_back_pinout.png
  浮き          … envelopes.py DB_SOCKET_SEAT 8.5 + DB_HEADER_PLASTIC 2.0
  外形          … electrical-design.md「XIAO (21x17.8mm)」
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, FancyArrowPatch
import matplotlib.font_manager as fm

# 日本語が出るフォントを探す（macOS）
for cand in ("Hiragino Sans", "Hiragino Maru Gothic Pro", "AppleGothic", "Arial Unicode MS"):
    if any(cand in f.name for f in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = cand
        break

fig, (ax, ax2) = plt.subplots(1, 2, figsize=(14, 7.2))

# ---------------- 左: 裏面から見た図 ----------------
W, H = 21.0, 17.8          # XIAO の外形 mm
ax.add_patch(Rectangle((0, 0), W, H, fc="#1b1b1b", ec="#444", lw=1.5, zorder=1))

# USB-C（裏から見て上辺の中央）
ax.add_patch(Rectangle((W/2 - 4.5, H - 1.2), 9.0, 1.9, fc="#999", ec="#666", zorder=3))
ax.text(W/2, H + 1.3, "USB-C", ha="center", va="bottom", fontsize=11, color="#333")

# 端のヘッダ（左右 7 本ずつ）。裏から見ているので左右が入れ替わる
for i in range(7):
    y = H - 2.6 - i * 2.2
    ax.add_patch(Rectangle((-0.1, y - 0.75), 2.0, 1.5, fc="#c8a200", ec="#8a7000", zorder=2))
    ax.add_patch(Rectangle((W - 1.9, y - 0.75), 2.0, 1.5, fc="#c8a200", ec="#8a7000", zorder=2))

# SWD の 4 パッド（USB 直下に 2x2）
PAD_R = 0.78
cx1, cx2 = W/2 - 2.3, W/2 + 2.3
cy1, cy2 = H - 4.6, H - 7.2
pads = [
    (cx1, cy1, "SWCLK", "#e8a33d"),
    (cx2, cy1, "SWDIO", "#e8a33d"),
    (cx1, cy2, "GND",   "#d8d8d8"),
    (cx2, cy2, "RST",   "#7ec8e3"),
]
for x, y, name, col in pads:
    ax.add_patch(Circle((x, y), PAD_R, fc=col, ec="#5a4500", lw=1.2, zorder=4))

# 引き出し線
ann = dict(fontsize=12, fontweight="bold", va="center")
ax.annotate("SWCLK", xy=(cx1 - PAD_R, cy1), xytext=(-7.5, cy1 + 0.9),
            arrowprops=dict(arrowstyle="-", color="#b36b00", lw=1.4),
            ha="left", color="#b36b00", **ann)
ax.annotate("GND", xy=(cx1 - PAD_R, cy2), xytext=(-7.5, cy2 - 0.9),
            arrowprops=dict(arrowstyle="-", color="#555", lw=1.4),
            ha="left", color="#555", **ann)
ax.annotate("SWDIO", xy=(cx2 + PAD_R, cy1), xytext=(W + 2.2, cy1 + 0.9),
            arrowprops=dict(arrowstyle="-", color="#b36b00", lw=1.4),
            ha="left", color="#b36b00", **ann)
ax.annotate("RST", xy=(cx2 + PAD_R, cy2), xytext=(W + 2.2, cy2 - 0.9),
            arrowprops=dict(arrowstyle="-", color="#2b7fa0", lw=1.4),
            ha="left", color="#2b7fa0", **ann)

ax.text(W/2, 3.2, "XIAO nRF52840\n(裏面から見た図)", ha="center", va="center",
        color="#bbb", fontsize=10)
ax.text(W/2, -2.6,
        "⚠ 基板の版で SWDIO/SWCLK の並びが違う。\n"
        "半田前にテスターで GND を特定すること（本文 3.）",
        ha="center", va="top", fontsize=10.5, color="#b00",
        bbox=dict(fc="#fff4f4", ec="#e0a0a0"))

ax.set_xlim(-9, W + 9)
ax.set_ylim(-6.5, H + 3.5)
ax.set_aspect("equal")
ax.axis("off")
ax.set_title("① どこに付けるか（裏面）", fontsize=14, fontweight="bold", pad=14)

# ---------------- 右: 横から見た図 ----------------
ax2.set_title("② 線の引き回し（横から）", fontsize=14, fontweight="bold", pad=14)

# 子基板
ax2.add_patch(Rectangle((0, 0), 22, 1.6, fc="#2e6b3e", ec="#1d4528", lw=1.2))
ax2.text(11, 0.8, "子基板", ha="center", va="center", color="white", fontsize=11)

# ソケット（座高 8.5）
for x in (1.6, 18.4):
    ax2.add_patch(Rectangle((x, 1.6), 2.0, 8.5, fc="#333", ec="#111"))
ax2.annotate("", xy=(0.7, 1.6), xytext=(0.7, 10.1),
             arrowprops=dict(arrowstyle="<->", color="#c00", lw=1.5))
ax2.text(0.2, 5.8, "ソケット\n8.5mm", ha="right", va="center",
         fontsize=10.5, color="#c00", fontweight="bold")

# ヘッダ樹脂 2.0
for x in (1.6, 18.4):
    ax2.add_patch(Rectangle((x, 10.1), 2.0, 2.0, fc="#555", ec="#222"))
ax2.text(20.6, 13.9, "ヘッダ樹脂 2.0mm", ha="left", va="center", fontsize=10, color="#555")

# XIAO 本体
ax2.add_patch(Rectangle((0.6, 12.1), 20.8, 1.5, fc="#1b1b1b", ec="#444", lw=1.3))
ax2.text(11, 12.85, "XIAO（裏面が下）", ha="center", va="center", color="white", fontsize=10.5)

# SWD パッドと線
for i, (xp, col, nm) in enumerate([(8.5, "#e8a33d", ""), (10.5, "#e8a33d", ""),
                                   (12.5, "#d8d8d8", "")]):
    ax2.add_patch(Circle((xp, 12.1), 0.33, fc=col, ec="#5a4500", zorder=5))

# 線: パッド → 横へ逃がす → 下へ
for xp, col in ((8.5, "#e8a33d"), (10.5, "#cc7a00"), (12.5, "#888")):
    ax2.plot([xp, xp, 24.5], [12.1, 10.9, 10.9], color=col, lw=2.0, zorder=4,
             solid_capstyle="round")

ax2.annotate("", xy=(5.2, 10.1), xytext=(5.2, 12.1),
             arrowprops=dict(arrowstyle="<->", color="#060", lw=1.5))
ax2.text(4.7, 11.1, "10.5mm\n空いている", ha="right", va="center",
         fontsize=10.5, color="#060", fontweight="bold")

ax2.text(25.0, 10.9, "→ ケース外へ\n（3〜4 本）", ha="left", va="center", fontsize=11)

ax2.text(11, -3.4,
         "XIAO はソケットに挿さっているだけ（DB_SOCKET_SEAT=8.5）。\n"
         "抜いて、机の上で半田付けできる。基板を分解する必要はない。",
         ha="center", va="top", fontsize=11,
         bbox=dict(fc="#f2f8f2", ec="#8ab88a"))

ax2.set_xlim(-3, 33)
ax2.set_ylim(-6, 17)
ax2.set_aspect("equal")
ax2.axis("off")

plt.tight_layout()
out = "docs/development/swd-wiring.png"
plt.savefig(out, dpi=165, bbox_inches="tight", facecolor="white")
print("wrote", out)
