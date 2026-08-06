"""ボトムケースを生成する。

外形はプレートと同じ輪郭。プレートがそのまま天板になるサンドイッチ構造で、
ケースはプレートを載せるトレイになる。上面は打鍵面と同じ 7.3° に傾く。

高さの基準:
  PLATE_TOP_FRONT — 前縁でのプレート上面の高さ。**唯一の調整つまみ**。
  スイッチとキーキャップの実寸が分かったら、ホーム段のキートップが
  31.6mm（実機の値、docs/hardware/dimensions.md §4.5）になるよう
  この 1 つを動かす。ケースは 3Dプリントなので刷り直しの費用はほぼゼロで、
  基板には影響しない。

電池は単3×2 を奥側に寝かせる。実機も同じ配置（背面の電池コブ）。
"""

import sys
from math import degrees, radians, tan
from pathlib import Path

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    BuildSketch,
    Cylinder,
    Location,
    Locations,
    Mode,
    add,
    Plane,
    RectangleRounded,
    extrude,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_plate import CORNER_R, PLATE_T, build_plate, halves, plate_positions  # noqa: E402

# --------------------------------------------------------------------------
# 実機から確定した値（docs/hardware/dimensions.md §4.5）
# --------------------------------------------------------------------------
TILT_DEG = 7.3           # 打鍵面の傾斜。topre_key の実測値
PLATE_TOP_FRONT = 17.5   # 前縁でのプレート上面高さ。実機の手前縁 17mm に合わせた暫定値。
                         # 実測後に調整する唯一のつまみ

# --------------------------------------------------------------------------
# 3Dプリント（K1 Max / PLA / ノズル 0.4mm）に合わせた値
# --------------------------------------------------------------------------
WALL = 2.4               # 側壁。0.4mm の 6 倍
FLOOR = 2.0              # 底板。0.4mm の 5 倍
CLEARANCE = 0.2          # 収縮を見込んだ嵌合の逃げ

# --------------------------------------------------------------------------
# 内部に収めるもの
# --------------------------------------------------------------------------
AA_D, AA_L = 14.5, 50.5          # 単3電池
BATT_W = AA_D * 2 + 1.0          # 2 本並べた幅（接触を避ける 1mm を加える）
BATT_H = AA_D + 1.0
BATT_MARGIN_REAR = 6.0           # 電池室と後壁の間隔（配線と端子のぶん）

PCB_T = 1.6                      # 基板
SOCKET_DROP = 3.2                # ホットスワップソケットが基板下へ出る量

M2_BOSS_D = 5.0                  # ネジボスの外径
M2_PILOT_D = 1.7                 # タッピング用の下穴


def case_heights(depth):
    """前縁・後縁でのプレート上面高さを返す。"""
    rise = depth * tan(radians(TILT_DEG))
    return PLATE_TOP_FRONT, PLATE_TOP_FRONT + rise


def build_case(keys):
    """プレートと同じ輪郭のトレイ型ボトムケースを作る。"""
    positions, (w, h) = plate_positions(keys)
    z_front, z_rear = case_heights(h)
    rim_front = z_front - PLATE_T          # プレートを載せるリムの高さ（前縁）
    rim_rear = z_rear - PLATE_T
    z_max = rim_rear + 5.0

    # 切削用の立体は BuildPart に入る前に作る。
    # コンテキストの中で Box() を作ると、その時点で部品に合体されてしまい、
    # 「原点で合体 → 傾けた位置で減算」という食い違いが起きる。
    cutter = tilted_cutter(w, h, rim_front)

    with BuildPart() as case:
        # 1. 外形を最大高さまで立ち上げる
        with BuildSketch():
            RectangleRounded(w, h, CORNER_R)
        extrude(amount=z_max)

        # 2. 上面を傾いた平面で切り落とす（＝プレートの裏面）
        add(cutter, mode=Mode.SUBTRACT)

        # 3. 内側をくり抜く
        with BuildSketch(Plane.XY.offset(FLOOR)):
            RectangleRounded(w - WALL * 2, h - WALL * 2, max(CORNER_R - WALL, 0.5))
        extrude(amount=z_max, mode=Mode.SUBTRACT)

        # 4. 電池室の仕切り壁を立てる
        #
        # 当初はここで空洞を「削って」いたが、既に空洞の中を削っても何も起きない。
        # 電池室は壁を立てる操作である。奥側に単3×2 を寝かせ、手前側を仕切る。
        y_batt = h / 2 - WALL - BATT_MARGIN_REAR - BATT_W / 2
        y_div = y_batt - BATT_W / 2 - WALL / 2          # 仕切り壁の中心
        with Locations((0, y_div, FLOOR)):
            Box(w - WALL * 2, WALL, BATT_H,
                align=(Align.CENTER, Align.CENTER, Align.MIN))

        # 5. ネジボス。四隅と長辺の中央に立てる
        for bx, by in _boss_positions(w, h):
            with Locations((bx, by, FLOOR)):
                Cylinder(M2_BOSS_D / 2, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
        add(cutter, mode=Mode.SUBTRACT)   # ボスの頭も揃える
        for bx, by in _boss_positions(w, h):
            with Locations((bx, by, FLOOR)):
                Cylinder(M2_PILOT_D / 2, z_max, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))

    return case.part, (w, h), (z_front, z_rear)


def tilted_cutter(w, h, rim_front):
    """z = rim_front + (y + h/2)·tan(TILT) の平面より上を占める立体。

    BuildPart の中で add(..., mode=Mode.SUBTRACT) して使う。
    builder.part への直接代入はビルダーの内部状態を更新せず、
    切削用の立体がそのまま残る不具合を起こしたので使わない。
    """
    mid_z = rim_front + (h / 2) * tan(radians(TILT_DEG))
    box = Box(w * 3, h * 3, 200, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return Location((0, 0, mid_z), (TILT_DEG, 0, 0)) * box


def _boss_positions(w, h):
    """ネジボスの位置。キー開口と干渉しない外周寄りに置く。"""
    # 壁に 1mm めり込ませる。ちょうど接する位置に置くと接線接触になり、
    # 非多様体（水密でない）メッシュになる。
    overlap = 1.0
    ix = w / 2 - WALL - M2_BOSS_D / 2 + overlap
    iy = h / 2 - WALL - M2_BOSS_D / 2 + overlap
    return [(-ix, -iy), (ix, -iy), (-ix, iy), (ix, iy), (0, -iy), (0, iy)]


def main():
    from verify import BUILD, assert_watertight, render_outline_2d, to_mesh

    BUILD.mkdir(exist_ok=True)
    for name, keys in halves().items():
        part, (w, h), (z_front, z_rear) = build_case(keys)
        mesh, stl = to_mesh(part, f"case_{name}")
        assert_watertight(mesh, stl.name)
        render_outline_2d(part, BUILD / f"case_{name}_section.png", axis="X",
                          title=f"case {name} - side section", annotate_count=False)
        bb = part.bounding_box()
        print(f"{name:5s} 設計値 {w:6.2f} x {h:6.2f}mm  "
              f"プレート上面 前 {z_front:.1f} / 奥 {z_rear:.1f}mm  傾斜 {TILT_DEG}°")
        print(f"      実測値 {bb.size.X:6.2f} x {bb.size.Y:6.2f} x {bb.size.Z:6.2f}mm  "
              f"水密={mesh.is_watertight}")
        assert abs(bb.size.X - w) < 0.01 and abs(bb.size.Y - h) < 0.01, "外形が設計値と違う"
        assert abs(bb.size.Z - (z_rear - PLATE_T)) < 0.01, "高さが設計値と違う"
    return 0


if __name__ == "__main__":
    sys.exit(main())
