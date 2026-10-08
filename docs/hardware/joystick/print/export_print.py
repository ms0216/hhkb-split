"""刷る部品の STL を出す（試作・未コミット）。joystick_rkjxv.py の形をそのまま使う。

  プレート・受け皿・キャップ・つまみ … 平らな向き（プレート座標）に戻して出す
  上ケースは変えない（押さえをやめた・2026-10-06）。刷り直すのはプレートだけ
"""
import sys
from pathlib import Path

WT = Path(sys.argv[1])
OUT = Path(sys.argv[2])
sys.path.insert(0, str(WT)); sys.path.insert(0, str(WT / "tools"))
import joystick_rkjxv as J  # noqa: E402
from build123d import Align, Box, Cone, Cylinder, Location, export_stl, fillet, Axis  # noqa: E402
from gen_case import plate_placement  # noqa: E402
from gen_plate import halves  # noqa: E402
from interface import plate_positions  # noqa: E402

CTR = (Align.CENTER, Align.CENTER, Align.MIN)
OUT.mkdir(parents=True, exist_ok=True)
for half in ("left", "right"):
    keys = halves()[half]
    _, (w, h_plate) = plate_positions(keys)
    inv = plate_placement(w, h_plate).inverse()
    parts = J.build(half)
    export_stl(inv * parts["plate"], str(OUT / f"{half}_plate.stl"))
    export_stl(inv * parts["joystick_seat"], str(OUT / f"{half}_tray.stl"))

# 右手のキャップ: 円板＋軸にかぶせる筒。穴は φ4 の D カット（平らな面まで 3.0）に 0.1 の遊び
# 円板は下の縁を斜めに落とした円すい台（倒して押し込んだとき右スペースへ届くのは下の縁）。上面を下にして刷れば張り出さない
disc = Location((0, 0, J.CAP_SLEEVE[1])) * Cone(J.CAP_D_BOT / 2, J.CAP_D / 2, J.CAP_T, align=CTR)
sleeve = Cylinder(*J.CAP_SLEEVE, align=CTR)
bore = Cylinder(J.SHAFT_D / 2 + 0.05, 6.0, align=CTR) - Location((0, 3.05 + 1.5, 0)) * Box(5, 3.0, 6.0, align=CTR)   # 軸の中心から 1.05 に平らな面（3.0 − 2.0 ＋遊び）
export_stl(disc + sleeve - bore, str(OUT / "right_stick_cap.stl"))

# 左手のつまみ（予備。付属品 φ15×12.5 の代わり）: 穴 φ6.1・深さ 8・割り 0.8
knob = fillet(Cylinder(7.5, 12.5, align=CTR).edges().sort_by(Axis.Z)[-1], 1.2)
knob -= Cylinder(3.05, 8.0, align=CTR) + Box(0.8, 9.0, 8.0, align=CTR)
export_stl(knob, str(OUT / "left_knob_spare.stl"))
print("出した:", sorted(p.name for p in OUT.glob("*.stl")))
