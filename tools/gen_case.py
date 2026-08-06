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

3Dプリント向け CAD ではまった落とし穴（同じ轍を踏まないこと）:
  - BuildPart のコンテキスト内で Box() 等を作ると、その時点で部品に合体される。
    切削用の立体はコンテキストに入る前に作ること。
  - builder.part への直接代入はビルダーの内部状態を更新しない。
    add(..., mode=Mode.SUBTRACT) を使うこと。
  - 既に空洞の中を削っても何も起きない。仕切りは「壁を立てる」操作。
  - **形状どうしをちょうど接する位置に置かない。** 接線接触や同一平面は
    非多様体メッシュ（印刷不能）になる。1mm 程度めり込ませるか離すこと。
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
    RegularPolygon,
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

# --------------------------------------------------------------------------
# 電池蓋（底面のスライド蓋）
#
# 実機と同じく底面から電池を出し入れする。蓋は奥へスライドして抜ける。
# レールは 1.2mm の段。K1 Max ならサポート無しでブリッジできる。
# --------------------------------------------------------------------------
LID_T = 1.6              # 蓋の厚み（0.4mm の 4 倍）
RAIL_W = 2.0             # レールの掛かり幅
RAIL_H = 1.2             # レールの段の深さ
LID_STOP = 2.0           # 手前側のストッパー

# --------------------------------------------------------------------------
# チルト脚
#
# 実機はヒンジ式の折りたたみ脚が 2 組。3Dプリントでヒンジを作ると壊れやすいので、
# 高さの違う差し込み脚を 2 組用意して 0° / 3° / 6° を作る。機能は同じ。
# 脚は前縁を支点に後縁を持ち上げるので、必要な高さは支点からの距離で決まる。
# --------------------------------------------------------------------------
FOOT_INSET_REAR = 10.0   # 後縁から脚中心までの距離
FOOT_D = 12.0            # 脚の直径
FOOT_PEG_D = 4.0         # 差し込みピンの径
FOOT_PEG_H = 4.0
TILT_STEPS = [3.0, 6.0]  # 追加する傾斜（0° は脚なし）

# --------------------------------------------------------------------------
# 三脚ネジ穴（テンティング用。普段は使わない）
# 1/4-20 の六角ナットを埋め込む。二面幅 11.1mm / 厚み 5.5mm
# --------------------------------------------------------------------------
NUT_AF = 11.1 + 0.3      # 二面幅＋逃げ
NUT_T = 5.5 + 0.2
NUT_BOSS_D = 18.0
NUT_BOSS_H = 9.0
NUT_THRU_D = 7.0

# ゴム足（市販 Φ10 × 厚 2mm を想定）
RUBBER_D = 10.0
RUBBER_RECESS = 0.6      # 座ぐりの深さ
RUBBER_INSET = 12.0      # 縁からの距離


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

        # 6. 電池蓋の開口とレール（底面）
        ox, oy, ow, oh = _lid_opening(w, h)
        with Locations((ox, oy, 0)):
            Box(ow, oh, FLOOR * 3, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # 長辺 2 本に蓋が乗る段を作る（開口より内側へ RAIL_W だけ残す）
        with Locations((ox, oy, FLOOR - RAIL_H)):
            Box(ow - RAIL_W * 2, oh, RAIL_H * 3, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 手前側のストッパー（蓋は奥へ抜ける）
        with Locations((ox, oy - oh / 2 + LID_STOP / 2, FLOOR - RAIL_H)):
            Box(ow, LID_STOP, RAIL_H, align=(Align.CENTER, Align.CENTER, Align.MIN))

        # 7. 三脚ネジ穴（1/4-20 の六角ナットを底面から埋め込む）
        with Locations((0, 0, FLOOR)):
            Cylinder(NUT_BOSS_D / 2, NUT_BOSS_H,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
        with Locations((0, 0, 0)):
            Cylinder(NUT_THRU_D / 2, NUT_BOSS_H + FLOOR * 2, mode=Mode.SUBTRACT,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
        with BuildSketch(Plane.XY):
            RegularPolygon(NUT_AF / 2 / __import__("math").cos(radians(30)), 6)
        extrude(amount=NUT_T, mode=Mode.SUBTRACT)

        # 8. ゴム足の座ぐりと、チルト脚の差し込み穴（いずれも底面）
        for fx, fy in _rubber_positions(w, h):
            with Locations((fx, fy, 0)):
                Cylinder(RUBBER_D / 2, RUBBER_RECESS, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        for fx, fy in _foot_positions(w, h):
            with Locations((fx, fy, 0)):
                Cylinder(FOOT_PEG_D / 2 + CLEARANCE / 2, FOOT_PEG_H,
                         mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))

    return case.part, (w, h), (z_front, z_rear)


def _lid_opening(w, h):
    """電池蓋の開口（中心 x, y と 大きさ）。電池室の真下に開ける。"""
    y_batt = h / 2 - WALL - BATT_MARGIN_REAR - BATT_W / 2
    return (0.0, y_batt, AA_L + 6.0, BATT_W)


def _rubber_positions(w, h):
    ix, iy = w / 2 - RUBBER_INSET, h / 2 - RUBBER_INSET
    return [(-ix, -iy), (ix, -iy), (-ix, iy), (ix, iy)]


def _foot_positions(w, h):
    """チルト脚の位置。後縁寄りの左右 2 箇所。

    隅はゴム足に使うので、脚は内側へ寄せる。隅に両方を置くと座ぐりと
    ピン穴が重なる（底面図で発覚）。
    """
    y = h / 2 - FOOT_INSET_REAR
    x = w / 2 - RUBBER_INSET - RUBBER_D / 2 - FOOT_D
    return [(-x, y), (x, y)]


def foot_height(h, add_deg):
    """後縁を add_deg だけ持ち上げるのに要る脚の高さ。

    支点は前縁。脚は後縁から FOOT_INSET_REAR の位置にあるので、
    支点からの距離はケース奥行から FOOT_INSET_REAR を引いた値になる。
    """
    lever = h - FOOT_INSET_REAR
    return lever * tan(radians(add_deg))


def build_battery_lid(keys):
    """電池蓋。ケースのレールに差し込んで奥へスライドさせる。"""
    _, (w, h) = plate_positions(keys)
    _, _, ow, oh = _lid_opening(w, h)
    lw = ow - CLEARANCE                      # 開口より少し小さく
    lh = oh - LID_STOP - CLEARANCE
    with BuildPart() as lid:
        with BuildSketch():
            RectangleRounded(lw, lh, 1.5)
        extrude(amount=LID_T)
        # 指掛かりの窪み。切削用の立体は上面より外へ突き出させる。
        # 上面とちょうど同一平面にすると境界が縮退し、水密でないメッシュになる。
        with Locations((0, -lh / 2 + 6.5, LID_T + 1.0)):
            Cylinder(4.0, 1.8, mode=Mode.SUBTRACT,
                     align=(Align.CENTER, Align.CENTER, Align.MAX))
    return lid.part, (lw, lh)


def build_tilt_foot(add_deg, h):
    """差し込み式のチルト脚。add_deg だけ後縁を持ち上げる。"""
    z = foot_height(h, add_deg)
    with BuildPart() as foot:
        with BuildSketch():
            RectangleRounded(FOOT_D, FOOT_D, 3.0)
        extrude(amount=z)
        with Locations((0, 0, z)):
            Cylinder(FOOT_PEG_D / 2, FOOT_PEG_H,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
    return foot.part, z


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

        lid, (lw, lh) = build_battery_lid(keys)
        lmesh, lstl = to_mesh(lid, f"battery_lid_{name}")
        assert_watertight(lmesh, lstl.name)
        print(f"      電池蓋 {lw:.1f} x {lh:.1f} x {LID_T}mm -> {lstl.name}")

        for deg in TILT_STEPS:
            foot, fz = build_tilt_foot(deg, h)
            fmesh, fstl = to_mesh(foot, f"tilt_foot_{int(deg)}deg_{name}")
            assert_watertight(fmesh, fstl.name)
            print(f"      チルト脚 +{deg:.0f}° 高さ {fz:.2f}mm -> {fstl.name}")
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
