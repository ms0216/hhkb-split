"""スティックのキャップ（大きい版）と、エンコーダのつまみを作る。build123d だけで動く（筐体のモデルは要らない）。

  .venv/bin/python3 docs/hardware/joystick/print/gen_heads.py [出力先]

どちらも**上面をベッドに付けて刷る向き**で出す（STL の z=0 が上面）。張り出しは無い。

スティックのキャップ（right_stick_cap_d16.stl）
  軸: φ4・先端 5mm が二面取り幅 3（アルプス RKJXV の図面「操作部寸法」）。穴は刷って合った前の版と同じ φ4.1×幅 3.1（入口 1.2mm は丸）。
  径 16・軸の先を 2.0 覆う（前の版は径 10・1.0）。隣のキーキャップとの隙間は、最大に倒して押し込んだ姿で 1.14mm
  （相手は右スペース。前の版は 1.27mm。数え方は scripts/joystick_rkjxv.py の tilt_report と同じ式）。
  径 17 では H に 0.97、径 18 では N に 0.78。覆いを 1.0 のまま径 16 にすると 0.22 しか残らない。

エンコーダのつまみ（left_knob_d18_b*.stl）
  軸: φ6.0・先端 7.3mm がローレット 18 山・軸の先は取付面から 25.0（TOP-UP EC12PSD-010）。
  穴は丸穴で、山を食い込ませて留める。**合う径は刷ってみないと分からない**ので 3 通り出す（穴 5.95 / 6.05 / 6.15。裏の点の数 1 / 2 / 3）。
  径 18: 軸から T のキーキャップの縁まで 10.66・5 まで 12.59・開口の縁まで 12.27（モデルで測った）。付属品は径 15。
  付属品と違って引けば抜ける（付属品は一度挿すと外れない）。
"""
import math
import sys
from pathlib import Path

from build123d import Align, Axis, Box, Cone, Cylinder, Location, chamfer, export_stl

CTR = (Align.CENTER, Align.CENTER, Align.MIN)
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent

# ---- スティックのキャップ（z=0 が上面。上へ行くほど軸の根元の側）----
CAP_D, CAP_RIM, CAP_CONE, NECK_R = 16.0, 0.8, 2.0, 3.4
CAP_OVER, BORE_DEPTH = 2.0, 6.0          # 軸の先を覆う厚み／穴の深さ（軸の先から）
SHAFT_R = 2.0 + 0.05                     # 穴の半径（φ4.1）
FLAT_W = 3.1                             # 二面取りの幅
CAP_H = CAP_OVER + BORE_DEPTH


def stick_cap():
    body = Cylinder(CAP_D / 2, CAP_RIM, align=CTR)
    body += Location((0, 0, CAP_RIM)) * Cone(CAP_D / 2, NECK_R, CAP_CONE, align=CTR)
    body += Location((0, 0, CAP_RIM + CAP_CONE)) * Cylinder(NECK_R, CAP_H - CAP_RIM - CAP_CONE, align=CTR)
    body = chamfer(body.edges().sort_by(Axis.Z)[0], 0.4)                                # 上面の角（指に当たる所）
    # 穴: 軸の先（z=CAP_OVER）から奥 4.8mm は二面取り、入口の 1.2mm は丸（全部を幅 3.1 にすると最後の 1mm が入らない）
    bore = Location((0, 0, CAP_OVER)) * (Cylinder(SHAFT_R, BORE_DEPTH - 1.2, align=CTR) & Box(5, FLAT_W, BORE_DEPTH - 1.2, align=CTR))
    bore += Location((0, 0, CAP_H - 1.2)) * Cylinder(SHAFT_R, 1.2, align=CTR)
    # 滑り止めの輪の溝（上面。幅 0.8・深さ 0.4。上面を下にして刷ると 0.8mm の橋になる）
    for r in (3.0, 5.0):
        body -= Cylinder(r + 0.4, 0.4, align=CTR) - Cylinder(r - 0.4, 0.4, align=CTR)
    return body - bore


# ---- エンコーダのつまみ（z=0 が上面）----
KNOB_D, KNOB_ROOF, KNOB_BORE_DEPTH = 18.0, 1.5, 8.0     # 穴の深さ 8.0 ＝ ローレット 7.3 ＋ 0.7
STEM_R, STEM_L = 4.75, 4.0                               # 軸を隠す筒（軸受けの上 1.0mm まで）
FLUTES, FLUTE_R = 20, 1.0


def knob(bore_d, dots):
    wheel_h = KNOB_ROOF + KNOB_BORE_DEPTH
    body = chamfer(Cylinder(KNOB_D / 2, wheel_h, align=CTR).edges().sort_by(Axis.Z)[0], 0.6)
    for i in range(FLUTES):                                                             # 側面の縦溝
        a = 2 * math.pi * i / FLUTES
        body -= Location(((KNOB_D / 2 + 0.4) * math.cos(a), (KNOB_D / 2 + 0.4) * math.sin(a), 0)) * Cylinder(FLUTE_R, wheel_h, align=CTR)
    body += Location((0, 0, wheel_h)) * Cylinder(STEM_R, STEM_L, align=CTR)
    body -= Location((0, 0, KNOB_ROOF)) * Cylinder(bore_d / 2, KNOB_BORE_DEPTH, align=CTR)       # ローレットを食い込ませる穴
    body -= Location((0, 0, wheel_h)) * Cylinder(3.25, STEM_L, align=CTR)                        # 筒の中は軸（φ6）に触れない φ6.5
    for i in range(dots):                                                               # 見分けの点（裏面）
        a = math.radians(20 * i)
        body -= Location((6.6 * math.cos(a), 6.6 * math.sin(a), wheel_h - 0.6)) * Cylinder(0.7, 0.6, align=CTR)
    return body


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    export_stl(stick_cap(), str(OUT / "right_stick_cap_d16.stl"))
    for n, d in enumerate((5.95, 6.05, 6.15), 1):
        export_stl(knob(d, n), str(OUT / f"left_knob_d18_b{n}.stl"))
    print("出した:", sorted(p.name for p in OUT.glob("*d1[68]*.stl")))
