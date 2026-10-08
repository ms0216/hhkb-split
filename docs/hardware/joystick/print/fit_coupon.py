"""はめ合いの試し片: 受け皿を丸ごと刷らずに、届いた部品が入るかを 5 分で確かめる小片。

  .venv/bin/python3 fit_coupon.py <wt-main> <出力.stl>

1 枚の板（厚み＝受け皿の床 1.5）に、左から順に
  [A] エンコーダ: 爪の穴 2（0.7×2.2・間隔 13.2）＋足の長穴 2 本（幅 2.6）… 実物の受け皿と同じ寸法
  [B] スティック: 爪の穴 4（0.8×1.5）＋突起の穴 2（φ1.8）＋足の長穴 … 同上
  [C] キャップの D 穴（φ4.1・平らな面まで 3.05）を持つ小さな筒（高さ 5）
  [D] 隙間の見本: 幅 0.3 / 0.4 / 0.5 の溝（くり抜きの隙間 CUT_CLR・TRAY_CLR の感触）
を並べる。入らなければ、寸法を直して受け皿を刷る前に知らせる。
"""
import sys
from pathlib import Path
from functools import reduce
WT = Path(sys.argv[1]); OUT = Path(sys.argv[2])
sys.path.insert(0, str(WT)); sys.path.insert(0, str(WT / "tools"))
import joystick_rkjxv as J  # noqa: E402
from build123d import Align, Box, Cylinder, Location, export_stl  # noqa: E402
CTR = (Align.CENTER, Align.CENTER, Align.MIN)
T = J.FLOOR_T
def bx(w, d, h, x, y, z=0): return Location((x, y, z)) * Box(w, d, h, align=CTR)
def cy(r, h, x, y, z=0): return Location((x, y, z)) * Cylinder(r, h, align=CTR)
hs = J.PIN_SLOT / 2
plate = bx(66, 24, T, 33, 0)
cut = []
# [A] エンコーダ（中心 x=10）
ax = 10
cut += [bx(0.7, 2.2, 9, ax + x, y, -1) for x, y in J.ENC_LUGS]
cut += [bx(5.0 + J.PIN_SLOT, J.PIN_SLOT, 9, ax, J.ENC_PINS_ABC[0][1], -1), bx(6.0 + J.PIN_SLOT, J.PIN_SLOT, 9, ax, J.ENC_PINS_SW[0][1], -1)]
# [B] スティック（中心 x=33）
bxc = 33
cut += [bx(0.8, 1.5, 9, bxc + a, b, -1) for a, b in J.LUGS] + [cy(0.9, 9, bxc + a, b, -1) for a, b in J.BOSS]
cut += [bx(5.0 + J.PIN_SLOT, J.PIN_SLOT, 9, bxc, J.PINS[0][1], -1), bx(J.PIN_SLOT, 5.0 + J.PIN_SLOT, 9, bxc + J.PINS[3][0], 0, -1)]
cut += [bx(J.PIN_SLOT, 4.5 + J.PIN_SLOT, 9, bxc + a, -8.0, -1) for a in (-3.25, 3.25)]
# [D] 隙間の見本（x=52〜）
for i, g in enumerate((0.3, 0.4, 0.5)):
    cut.append(bx(g, 10, 9, 52 + i * 3, -5, -1))
body = plate - reduce(lambda p, q: p + q, cut)
# [C] キャップの筒（x=58, y=7）: 受け皿とは別の部品相当なので板の上に立てる
sleeve = cy(J.CAP_SLEEVE[0], J.CAP_SLEEVE[1], 58, 7, T)
bore = cy(J.SHAFT_D / 2 + 0.05, 6.0, 58, 7, T) - bx(5, 3.0, 6.0, 58, 7 + 3.05 + 1.5, T)
body = body + sleeve - bore
export_stl(body, str(OUT))
print("出した:", OUT, "外形 66×24×", T + J.CAP_SLEEVE[1])
