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
from gen_plate import build_plate, halves, plate_positions  # noqa: E402
from interface import (  # noqa: E402
    CORNER_R,
    boss_positions_plan,
    plan_depth,
    M2_BOSS_D,
    M2_PILOT_D,
    PLATE_T,
    boss_positions,
)

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
FLOOR = 2.4              # 底板。0.4mm の 6 倍。
                         # 当初 2.0mm にしていたが、蓋(1.6mm)をレールに落とし込むと
                         # 床の内面より上に出て電池に食い込んだため厚くした。
CLEARANCE = 0.2          # 収縮を見込んだ嵌合の逃げ

# --------------------------------------------------------------------------
# 内部に収めるもの
# --------------------------------------------------------------------------
# 単3電池は**左右方向に 2 本直列**で寝かせる。
#
# 当初は前後方向に 2 本並べ（奥行 30mm 必要）、基板の真下に置いた。しかし
# 打鍵面が 7.3° 傾いているので基板も傾いて入り、手前側で 4,000mm^3 衝突した。
# 実機はこれを本体後ろの 12mm のコブで逃がしている。
#
# 占有空間から先に組み直したところ、左右方向に並べれば奥行は 15.5mm で済み、
# 傾いた基板の下の「奥側の背の高い領域」に収まることが分かった。
# コブを足す必要がなく、分割版として小さく収まる。
AA_D, AA_L = 14.5, 50.5
BATT_H = AA_D + 1.0              # 占有高さ
BATT_W = AA_D + 1.0              # 占有奥行（左右に寝かせるので 1 本ぶん）
BATT_X = AA_L * 2 + 8.0          # 占有幅（2 本直列＋電極）
BATT_MARGIN_REAR = 2.0           # 電池と後壁の間隔
BUMP_DEPTH = 0.0                 # コブは不要になった

from envelopes import PCB_T, PLATE_TO_PCB, SOCKET_DROP  # noqa: E402


# --------------------------------------------------------------------------
# 電池蓋（底面のスライド蓋）
#
# 実機と同じく底面から電池を出し入れする。蓋は奥へスライドして抜ける。
# レールは 1.2mm の段。K1 Max ならサポート無しでブリッジできる。
# --------------------------------------------------------------------------
LID_T = 1.6              # 蓋の厚み（0.4mm の 4 倍）
RAIL_W = 2.0             # レールの掛かり幅
RAIL_H = LID_T           # 段の深さ＝蓋の厚み。こうすると蓋が床の内面と面一になる。
                         # 段を蓋より浅くすると蓋が内側へ出っ張り、電池と干渉する
                         # （組み立て検査で 233mm^3 の食い込みとして検出された）。
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
# 脚は**後ろの隅**に差し、そこが設置点になる。実機の折りたたみ脚と同じ役割。
# 0° 用の短い脚も作るので、脚は常に 2 個使う（外すのではなく差し替える）。
# 当初は脚を内側に置き、電池室と蓋の中にボスが立っていた。
TILT_STEPS = [0.0, 3.0, 6.0]
FOOT_BASE_H = 2.0        # 0° の脚の高さ。前側のゴム足と同じ厚み

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
    """トレイ型ボトムケースを作る。

    奥行はプレートの平面図での長さ（傾けたぶん cos(TILT) 倍に縮む）に合わせる。
    プレートの平らな寸法をそのまま使うと、リムがプレートより 0.84mm 長くなり
    覆いきれない（組み立て検査で検出）。
    """
    positions, (w, h_plate) = plate_positions(keys)
    h_body = plan_depth(h_plate)          # プレートが載る範囲
    h = h_body + BUMP_DEPTH               # 後部のコブを足した全体の奥行
    # 座標の基準は**本体部分の中心**（＝プレートの中心＝原点）に固定する。
    # コブは後ろへ張り出すだけなので、外形の矩形は BUMP/2 だけ後ろへずらす。
    # 外形の中心を原点にするとプレートと基板が前へずれる（実際にずらして
    # 2,680mm^3 の食い込みを出した）。
    y_off = BUMP_DEPTH / 2
    z_front, z_rear = case_heights(h)
    rim_front = z_front - PLATE_T          # プレートを載せるリムの高さ（前縁）
    rim_rear = z_rear - PLATE_T
    z_max = rim_rear + 5.0

    # 切削用の立体は BuildPart に入る前に作る。
    # コンテキストの中で Box() を作ると、その時点で部品に合体されてしまい、
    # 「原点で合体 → 傾けた位置で減算」という食い違いが起きる。
    cutter = tilted_cutter(w, h_body, rim_front)
    # ボスの頭を止める面（基板の下面）。これも**必ず**コンテキストの外で作る。
    # 中で作ると即座に部品へ合体され、外形が 538x614mm に膨れる（実際にやった）。
    cutter_pcb = tilted_cutter(w, h_body, rim_front - PLATE_TO_PCB - PCB_T)

    with BuildPart() as case:
        # 1. 外形を最大高さまで立ち上げる（コブぶん後ろへずらす）
        with BuildSketch():
            with Locations((0, y_off)):
                RectangleRounded(w, h, CORNER_R)
        extrude(amount=z_max)

        # 2. 上面を傾いた平面で切り落とす（＝プレートの裏面）
        add(cutter, mode=Mode.SUBTRACT)

        # 3. 内側をくり抜く
        with BuildSketch(Plane.XY.offset(FLOOR)):
            with Locations((0, y_off)):
                RectangleRounded(w - WALL * 2, h - WALL * 2,
                                 max(CORNER_R - WALL, 0.5))
        extrude(amount=z_max, mode=Mode.SUBTRACT)

        # 4. 電池室。後壁ぎわ（コブの中）に置き、仕切り壁と天井を作る。
        #    天井を張らないと、傾いた基板が電池室の上に落ちてきて衝突する。
        y_batt = battery_center(h_body)
        # 仕切り壁は電池からわずかに離す。ちょうど接する位置に置くと
        # 干渉として検出される（接触は 0 にならない）。
        y_div = y_batt - BATT_W / 2 - WALL / 2 - CLEARANCE
        with Locations((0, y_div, FLOOR)):
            Box(w - WALL * 2, WALL, BATT_H,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 天井は張らない。電池の上には基板が来るので、板を入れると
        # 傾いた基板の下端を突き上げる（2,817mm^3 の食い込みとして検出）。
        # 電池は 手前=仕切り壁 / 左右と奥=側壁 / 下=蓋 / 上=基板 で保持される。

        # 5. ネジボス。四隅と長辺の中央に立てる
        for bx, by in _boss_positions(w, h_plate):
            with Locations((bx, by, FLOOR)):
                Cylinder(M2_BOSS_D / 2, z_max, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # ボスの頭は**基板の下面**で止める。リムまで伸ばすと基板を貫いて
        # ぶつかる（組み立て検査で 17,000mm^3 の食い込みとして検出）。
        # 基板はボスの上に載り、ネジはプレート→基板→ボスの順に通る。
        add(cutter_pcb, mode=Mode.SUBTRACT)
        for bx, by in _boss_positions(w, h_plate):
            with Locations((bx, by, FLOOR)):
                Cylinder(M2_PILOT_D / 2, z_max, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))

        # 6. 電池蓋の開口とレール（底面）
        #
        # 順序が肝心。**狭い方を貫通させ、広い方を上側だけ削る**。
        # 逆にすると（広い開口を先に貫通させてから狭い座ぐりを削ると）、
        # 蓋を受ける段が一切できない。当初これを間違えており、組み立て検査で
        # ケースと蓋が食い込むという形で発覚した。
        ox, oy, ow, oh = _lid_opening(w, h_body)
        # 6-1. 貫通させるのは狭い方（両側に RAIL_W の段を残す）
        with Locations((ox, oy, 0)):
            Box(ow - RAIL_W * 2, oh, FLOOR * 3, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # 6-2. 蓋が落ち込む座ぐりは広い方。床の上側 RAIL_H だけ削る
        with Locations((ox, oy, FLOOR - RAIL_H)):
            Box(ow, oh, RAIL_H, mode=Mode.SUBTRACT,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 6-3. 手前側のストッパー（蓋は奥へ抜ける）
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
        for fx, fy in _rubber_positions(w, h_body):
            with Locations((fx, fy, 0)):
                Cylinder(RUBBER_D / 2, RUBBER_RECESS, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        # ピン穴は床(2.0mm)より深い(4.0mm)ので、そのまま開けると内部へ貫通する。
        # メッシュの種数が 4 になって発覚した。内側にボスを立てて盲穴にする。
        for fx, fy in _foot_positions(w, h_body):
            with Locations((fx, fy, 0)):
                Cylinder(FOOT_PEG_D / 2 + 2.0, FOOT_PEG_H + 1.6,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        for fx, fy in _foot_positions(w, h_body):
            with Locations((fx, fy, 0)):
                Cylinder(FOOT_PEG_D / 2 + CLEARANCE / 2, FOOT_PEG_H,
                         mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))

    return case.part, (w, h_body), (z_front, z_rear)


def battery_center(h_body):
    """電池室の中心（本体中心を原点とする Y 座標）。

    ケース・蓋の開口・組み立て検査がすべてこの 1 つの関数を使う。
    同じ式を複数箇所に書いたせいで 14mm ずれた前科があるため。

    奥へ寄せるほど傾いた基板との余裕が増えるので、後壁ぎわに置く。
    """
    y_rear_inner = h_body / 2 - WALL
    return y_rear_inner - BATT_MARGIN_REAR - BATT_W / 2


def _lid_opening(w, h_body):
    """電池蓋の開口（中心 x, y と 大きさ）。電池室の真下に開ける。

    y は**本体部分の中心を原点**とした座標。コブの中に電池があるので、
    本体の後端より後ろに来る。
    """
    return (0.0, battery_center(h_body), BATT_X, BATT_W)


def _rubber_positions(w, h_body):
    """ゴム足は**前の 2 箇所**だけ。後ろはチルト脚が接地点を兼ねる。"""
    ix = w / 2 - RUBBER_INSET
    iy = h_body / 2 - RUBBER_INSET
    return [(-ix, -iy), (ix, -iy)]


def _foot_positions(w, h_body):
    """チルト脚の位置。**後ろの隅**。ここが接地点になる。

    内側に寄せると電池室と電池蓋の中にボスが立つ。実際にそうなっており、
    断面図で「電池室の中に 2 本の柱」として見えて発覚した。
    隅なら電池（幅 109mm）にも蓋の開口にも当たらない。
    """
    y = h_body / 2 - RUBBER_INSET
    x = w / 2 - RUBBER_INSET
    return [(-x, y), (x, y)]


def foot_height(h, add_deg):
    """後ろを add_deg だけ持ち上げるのに要る脚の高さ。

    支点は前側のゴム足。脚は後ろの隅にあるので、支点からの距離は
    前後のゴム足／脚の間隔になる。0° の脚はゴム足と同じ高さ。
    """
    lever = h - RUBBER_INSET * 2
    return FOOT_BASE_H + lever * tan(radians(add_deg))


def build_battery_lid(keys):
    """電池蓋。ケースのレールに差し込んで奥へスライドさせる。

    開口の位置と大きさはケース側の造作なので、平面図の奥行で計算する。
    プレートの平らな奥行を渡すと 0.42mm ずれる。
    """
    _, (w, h_plate) = plate_positions(keys)
    _, _, ow, oh = _lid_opening(w, plan_depth(h_plate))
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


def tilted_cutter(w, h, rim_front, y_offset=0.0):
    """z = rim_front + (y + h/2)·tan(TILT) の平面より上を占める立体。

    y_offset は、傾斜の基準（本体部分の中心）が外形の中心とずれている場合に
    与える。後部にコブを足すと外形の中心が後ろへ寄るため。

    BuildPart の中で add(..., mode=Mode.SUBTRACT) して使う。
    builder.part への直接代入はビルダーの内部状態を更新せず、
    切削用の立体がそのまま残る不具合を起こしたので使わない。
    """
    mid_z = rim_front + (h / 2 + y_offset) * tan(radians(TILT_DEG))
    box = Box(w * 3, h * 6, 200, align=(Align.CENTER, Align.CENTER, Align.MIN))
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
