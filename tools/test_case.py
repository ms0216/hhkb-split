"""ボトムケースが物理的に成立することを検証する。"""
import pytest
from build123d import Align, Box, Location
from gen_case import (
    AA_D, AA_L, BATT_H, BATT_W, FLOOR, PLATE_T, PLATE_TOP_FRONT, TILT_DEG,
    build_case, case_heights,
)
from gen_plate import halves
from verify import assert_watertight, intersection_volume, to_mesh

HALVES = halves()


@pytest.mark.parametrize("name", ["left", "right"])
def test_outer_size_matches_the_tilted_plate(name):
    """ケースの外形は、傾けたプレートの平面図と一致する。

    平らなプレートを 7.3° 傾けると平面図の奥行は cos 倍に縮む。
    プレートの平らな寸法をそのまま使うとリムが 0.84mm 長くなる。

    **奥行はコブぶんだけプレートより長い。** 実機も同じで、本体 108mm に
    電池コブ 12mm が足されて全長 120mm になる。
    """
    from gen_case import BUMP_DEPTH
    from gen_plate import plate_positions
    from interface import plan_depth
    part, (w, h_body), _ = build_case(HALVES[name], name)
    _, (pw, h_plate) = plate_positions(HALVES[name])
    bb = part.bounding_box().size
    assert bb.X == pytest.approx(pw, abs=0.01)
    assert h_body == pytest.approx(plan_depth(h_plate), abs=0.01), \
        "プレートが載る範囲が、傾けたプレートの平面図と違う"
    assert bb.Y == pytest.approx(h_body + BUMP_DEPTH, abs=0.01), \
        "ケース全体の奥行が「プレートの範囲 ＋ コブ」になっていない"


@pytest.mark.parametrize("name", ["left", "right"])
def test_rim_height_gives_the_intended_plate_top(name):
    """リムの高さ + 板厚 = 狙ったプレート上面高さ。"""
    from math import radians, tan
    from gen_case import BEZEL_TOP_FRONT, BUMP_DEPTH
    from interface import plan_depth
    from gen_plate import plate_positions
    part, (_, h_body), (z_front, z_rear) = build_case(HALVES[name], name)
    # **最も高いのはコブの後端（ベゼル上面）。**
    # 以前はプレートのリムが最高点だったが、上ケース方式でコブがベゼル面まで
    # 上がったので基準が変わった。
    z_top = BEZEL_TOP_FRONT + (h_body + BUMP_DEPTH) * tan(radians(TILT_DEG))
    assert part.bounding_box().size.Z == pytest.approx(z_top, abs=0.05)
    assert z_front == pytest.approx(PLATE_TOP_FRONT)


@pytest.mark.parametrize("name", ["left", "right"])
def test_printable(name):
    part, _, _ = build_case(HALVES[name], name)
    mesh, _ = to_mesh(part, f"case_{name}")
    assert_watertight(mesh, f"case_{name}")


@pytest.mark.parametrize("name", ["left", "right"])
def test_two_aa_batteries_fit(name):
    """単3×2（左右方向に直列）がケースと干渉せずに収まること。

    電極と配線の余裕を含めた占有空間で判定する。前後に並べる案は
    傾いた基板と 4,000mm^3 衝突したため、左右方向に改めた。
    """
    from envelopes import battery_envelope
    from gen_case import battery_center
    part, (_, h_body), _ = build_case(HALVES[name], name)
    from gen_case import battery_x_center
    from gen_plate import plate_positions
    _, (w, _) = plate_positions(HALVES[name])
    batt = battery_envelope((battery_x_center(name, w),
                             battery_center(h_body), FLOOR + AA_D / 2))
    v = intersection_volume(batt, part)
    assert v < 1e-3, f"{name}: 電池がケースと干渉している ({v:.2f}mm^3)"


def test_tilt_matches_the_measured_value():
    """傾斜は実機の実測値 7.3° であること。"""
    assert TILT_DEG == 7.3
    zf, zr = case_heights(100.0)
    import math
    assert math.degrees(math.atan((zr - zf) / 100.0)) == pytest.approx(7.3, abs=1e-6)


# --------------------------------------------------------------------------
# 電池蓋・チルト脚・三脚ナット・ゴム足
# --------------------------------------------------------------------------

def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


@pytest.mark.parametrize("name", ["left", "right"])
def test_battery_lid_is_printable_and_fits_the_opening(name):
    from gen_case import CLEARANCE, LID_STOP, _lid_opening, build_battery_lid
    from gen_plate import plate_positions
    lid, (lw, lh) = build_battery_lid(name, HALVES[name])
    mesh, _ = to_mesh(lid, f"battery_lid_{name}")
    assert_watertight(mesh, f"battery_lid_{name}")
    _, (w, h) = plate_positions(HALVES[name])
    _, _, ow, oh = _lid_opening(name, w, h)
    assert lw < ow, "蓋が開口より大きい"
    assert lh < oh - LID_STOP, "蓋がストッパーに当たって入らない"
    assert ow - lw == pytest.approx(CLEARANCE), "嵌合の逃げが設計値と違う"


@pytest.mark.parametrize("deg", [3.0, 6.0])
def test_tilt_foot_height_gives_the_intended_angle(deg):
    """脚の高さが、後縁を deg だけ持ち上げる値になっていること。"""
    import math
    from gen_case import FOOT_BASE_H, RUBBER_INSET, build_tilt_foot, foot_height
    from gen_plate import plate_positions
    _, (w, h) = plate_positions(HALVES["left"])
    z = foot_height(h, deg)
    lever = h - RUBBER_INSET * 2
    assert math.degrees(math.atan((z - FOOT_BASE_H) / lever)) == pytest.approx(deg, abs=1e-9)
    foot, fz = build_tilt_foot(deg, h)
    mesh, _ = to_mesh(foot, f"tilt_foot_{int(deg)}")
    assert_watertight(mesh, f"tilt_foot_{int(deg)}")
    assert fz == pytest.approx(z)


@pytest.mark.parametrize("name", ["left", "right"])
def test_bottom_features_do_not_overlap(name):
    """底面の座ぐり・ピン穴・三脚ボスが互いに干渉しないこと。

    ゴム足の隅にチルト脚を置いて重なった実例があるので、必ず数値で見る。
    """
    from gen_case import (
        FOOT_D, FOOT_PEG_D, NUT_BOSS_D, RUBBER_D, _foot_positions,
        _rubber_positions,
    )
    from gen_plate import plate_positions
    _, (w, h) = plate_positions(HALVES[name])
    items = ([(p, RUBBER_D / 2) for p in _rubber_positions(w, h)]
             + [(p, FOOT_D / 2) for p in _foot_positions(w, h)]
             + [((0.0, 0.0), NUT_BOSS_D / 2)])
    for i, (pa, ra) in enumerate(items):
        for pb, rb in items[i + 1:]:
            assert _dist(pa, pb) > ra + rb, f"{name}: {pa} と {pb} が重なる"


# --------------------------------------------------------------------------
# 部品どうしの突き合わせ
#
# 「プレートの穴 vs 共有定義」だけを見ていて、ケースの実物と照合していなかった。
# そのためケースがボス位置の独自実装を持ち続けていることに長く気づけず、
# ボスが電池室の中に立っていた。実物どうしを比べる。
# --------------------------------------------------------------------------

def _boss_solid_centers(part, expect_d):
    """部品の中から、直径 expect_d のボスらしき柱の中心を拾う。"""
    out = []
    for s in part.solids():
        bb = s.bounding_box()
        if abs(bb.size.X - expect_d) < 0.2 and abs(bb.size.Y - expect_d) < 0.2:
            out.append((bb.center().X, bb.center().Y))
    return out


@pytest.mark.parametrize("name", ["left", "right"])
def test_case_bosses_come_from_the_shared_definition(name):
    """ケースのボス位置が共有定義と一致すること。

    ケース側に独自実装を残すと、プレートの穴と食い違う。実際に食い違っていた。
    """
    from gen_case import _boss_positions
    from gen_plate import plate_positions
    from interface import boss_positions_plan
    _, (w, h_plate) = plate_positions(HALVES[name])
    assert _boss_positions(name) == boss_positions_plan(name)


@pytest.mark.parametrize("name", ["left", "right"])
def test_bosses_do_not_stand_inside_the_battery_compartment(name):
    """ネジボスが電池室を貫かないこと。

    後ろ側のボスは電池（幅109mm）の外に出す必要がある。中央に置いて231mm^3、
    w/4 に置いて77mm^3 の食い込みを出した。
    """
    from build123d import Align, BuildPart, Cylinder, Locations
    from envelopes import battery_envelope
    from gen_case import AA_D, FLOOR, M2_BOSS_D, _boss_positions, battery_center
    from gen_plate import plate_positions
    from interface import plan_depth
    from verify import intersection_volume

    from gen_case import battery_x_center
    _, (w, h_plate) = plate_positions(HALVES[name])
    # **電池の実際の X 位置を使う。** 0 のまま書いていて、電池を外側へ
    # 寄せたあとも中央にあるものとして検査していた（＝別の場所を見ていた）。
    batt = battery_envelope((battery_x_center(name, w),
                             battery_center(plan_depth(h_plate)),
                             FLOOR + AA_D / 2))
    for bx, by in _boss_positions(name):
        with BuildPart() as b:
            with Locations((bx, by, FLOOR)):
                Cylinder(M2_BOSS_D / 2, 40,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        v = intersection_volume(batt, b.part)
        assert v < 1e-3, f"{name}: ボス({bx:.1f},{by:.1f}) が電池室を貫く ({v:.1f}mm^3)"


@pytest.mark.parametrize("name", ["left", "right"])
def test_the_antenna_is_kept_away_from_the_battery(name):
    """XIAO のアンテナと単3電池の距離を確保すること。

    **幾何が干渉しないことと、電波が届くことは別の話。**
    電池を外へ寄せて子基板の場所を作ったとき、幾何だけを見ていて
    アンテナから 1.0mm の位置に置いていた。単3 電池は金属の塊で、
    至近距離では 2.4GHz のアンテナを大きく狂わせる。
    左右間の BLE 接続はこのキーボードの中核要件で、その通信距離を
    自分で潰すことになっていた。
    """
    from gen_case import (BATT_X, DB_ANTENNA_KEEPOUT, DB_W, battery_x_center,
                          daughterboard_x_center, inner_sign)
    from gen_plate import plate_positions
    _, (w, _) = plate_positions(HALVES[name])
    s = inner_sign(name)
    gap = abs((daughterboard_x_center(name, w) - s * DB_W / 2)
              - (battery_x_center(name, w) + s * BATT_X / 2))
    assert gap >= DB_ANTENNA_KEEPOUT, (
        f"{name}: アンテナと電池が {gap:.1f}mm しか離れていない"
        f"（必要 {DB_ANTENNA_KEEPOUT}mm）")





# --------------------------------------------------------------------------
# プリンタの制約（Creality K1 Max / PLA / ノズル 0.4mm）
# --------------------------------------------------------------------------
K1MAX_BED = (300.0, 300.0, 300.0)
NOZZLE = 0.4


@pytest.mark.parametrize("name", ["left", "right"])
def test_every_part_fits_the_printer(name):
    """全部品が K1 Max の造形範囲に収まること。

    **造形できない部品を設計しても意味がない。**寸法を大きくしたときに
    黙って超えることを防ぐ。
    """
    from gen_case import build_case, build_topcase, build_battery_lid
    from gen_plate import build_plate
    parts = {
        "case": build_case(HALVES[name], name)[0],
        "topcase": build_topcase(HALVES[name], name)[0],
        "lid": build_battery_lid(name, HALVES[name])[0],
        "plate": build_plate(HALVES[name], name)[0],
    }
    for label, part in parts.items():
        s = part.bounding_box().size
        fits = (min(s.X, s.Y) <= min(K1MAX_BED[0], K1MAX_BED[1])
                and max(s.X, s.Y) <= max(K1MAX_BED[0], K1MAX_BED[1])
                and s.Z <= K1MAX_BED[2])
        assert fits, (f"{name} の {label} が造形範囲を超える "
                      f"({s.X:.1f}x{s.Y:.1f}x{s.Z:.1f} > {K1MAX_BED})")


def test_wall_thicknesses_are_multiples_of_the_nozzle():
    """壁と床がノズル径の整数倍であること。

    半端な厚みにすると、スライサが埋めきれず隙間が残る。
    **上ケースの壁 1.6mm はノズル 4 本ぶん**で、これは意図した値。
    """
    from gen_case import FLOOR, LID_T, WALL
    from interface import BEZEL_WALL
    for label, t in (("側壁", WALL), ("床", FLOOR), ("蓋", LID_T),
                     ("上ケースの壁", BEZEL_WALL)):
        n = t / NOZZLE
        assert abs(n - round(n)) < 1e-6, \
            f"{label} {t}mm がノズル {NOZZLE}mm の整数倍でない（{n:.2f} 本）"


def test_the_daughterboard_can_carry_both_the_mcu_and_its_screws():
    """子基板に XIAO とネジが**同時に**載ること。

    22x22mm で設計を始めたが、取付穴の置ける場所が 0 箇所だった。
    XIAO は 17.8x21mm で、ネジの逃げ（半径 2.2mm）が入る余地が残らない。
    **入るかどうかは、置き始める前に数えられる。**
    """
    from gen_case import DB_BOSS_POS, DB_D, DB_W
    from interface import M2_CLEAR_D
    XW, XL = 17.8, 21.0
    r = M2_CLEAR_D / 2 + 1.0
    for x, y in DB_BOSS_POS:
        assert abs(x) + r <= DB_W / 2, f"ネジ({x},{y}) が基板の幅から出る"
        assert abs(y) + r <= DB_D / 2, f"ネジ({x},{y}) が基板の奥行から出る"
        assert abs(x) - r >= XW / 2 or abs(y) - r >= XL / 2, \
            f"ネジ({x},{y}) が XIAO の下に入る"
    assert len(DB_BOSS_POS) >= 2, "ネジが 1 本では回る"
    assert DB_BOSS_POS[0][0] != DB_BOSS_POS[1][0], \
        "ネジが中心線上に並んでいる。回り止めにならない"


@pytest.mark.parametrize("name", ["left", "right"])
def test_the_battery_bump_has_a_lid(name):
    """コブに天井があること（電池が上から露出しないこと）。

    **「メッシュが水密」は「箱として閉じている」を意味しない。**
    内側のくり抜きを奥まで通していたため、コブが上に開いたままだった。
    本体側はプレートと上ケースが覆うが、コブの上には何も載らない。
    干渉検査も水密検査もこれを見つけられなかった。
    """
    from build123d import Align, Box, BuildPart, Locations
    from gen_case import battery_center, battery_x_center, build_case
    from gen_plate import plate_positions
    from verify import intersection_volume

    case, (w, h_body), _ = build_case(HALVES[name], name)
    bx = battery_x_center(name, w)
    by = battery_center(h_body)
    found = False
    for z in range(18, 34):
        with BuildPart() as probe:
            with Locations((bx, by, float(z))):
                Box(60.0, 8.0, 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        if intersection_volume(probe.part, case) > 1.0:
            found = True
            break
    assert found, f"{name}: 電池の真上にケースの材料が無い（コブが開いている）"


def test_the_bosses_take_heat_set_inserts():
    """ボスが熱圧入インサートを受ける寸法であること。

    **PLA に M2 を直接タッピングすると、数回の開け閉めで舐める。**
    インサート外径 3.2mm に対して肉厚 1.2mm 以上を確保する。
    """
    from interface import M2_BOSS_D, M2_INSERT_D, M2_PILOT_D
    wall = (M2_BOSS_D - M2_INSERT_D) / 2
    assert wall >= 1.2 - 1e-9, f"ボスの肉厚が {wall:.2f}mm しかない（インサートが割る）"
    assert M2_PILOT_D == M2_INSERT_D, \
        "ケース側の下穴がインサート外径になっていない（タッピング用のまま）"


def test_the_m2_inserts_fit_the_bosses():
    """買う M2 インサートが、いちばん浅いボスに収まること。

    **外径だけでは足りない。**`interface.M2_INSERT_D` は外径 3.2mm を
    規定しているが、**長さはどこにも規定が無かった**。子基板のボスは
    下穴を 5.0mm しか掘っておらず、市販の 5.7mm を買うと入らない
    （open-gaps #24）。

    買う製品を変えたら `envelopes.M2_INSERT_L` を差し替える。
    それだけでここが判定し直す。
    """
    from envelopes import M2_INSERT_L
    from gen_case import DB_BOSS_H
    deepest = DB_BOSS_H + 1.0          # gen_case が実際に掘っている深さ
    assert M2_INSERT_L <= deepest, (
        f"M2 インサートの長さ {M2_INSERT_L}mm が、子基板のボスに掘った "
        f"{deepest}mm を超える。短いものを買うか、DB_BOSS_H を深くすること")


def test_the_usb_opening_clears_the_connector():
    """USB-C の切り欠きが、XIAO の積み上げを余裕を持って囲むこと。

    **USB は書き込みに要る。**ここがずれると、組み上げてからケーブルが
    挿さらないと分かる。

    以前は「子基板の上面から 1.6mm」と直書きしていて、**上側の余裕が
    0.10mm しか無かった。**XIAO の厚み 4.5mm は「ぐらい」で渡された概数
    なので、0.1mm は余裕ではない。`XIAO_H_WITH_USB` は記録されていただけで
    どこからも使われておらず、変異検査でも生き残った。
    """
    import gen_case as g
    from envelopes import DB_STACK_H, XIAO_H_WITH_USB

    assert DB_STACK_H >= XIAO_H_WITH_USB, (
        f"積み上げ {DB_STACK_H}mm が XIAO 単体 {XIAO_H_WITH_USB}mm より薄い。"
        "ソケットを挟むならもっと高いはず")

    bottom = g.FLOOR + g.DB_BOSS_H + g.DB_T
    center = g.usb_center_z()
    lo, hi = center - g.USB_H / 2, center + g.USB_H / 2
    margin = min(bottom - lo, hi - (bottom + DB_STACK_H))
    assert margin >= 0.5, (
        f"USB 切り欠きの余裕が {margin:.2f}mm しかない"
        f"（切り欠き {lo:.2f}〜{hi:.2f} / XIAO {bottom:.2f}〜"
        f"{bottom + DB_STACK_H:.2f}）")


@pytest.mark.parametrize("name", ["left", "right"])
def test_the_antenna_keepout_covers_the_real_antenna(name):
    """本体基板に開けた禁止域が、本物のアンテナの真上にあること。

    禁止域の位置は interface.ANTENNA_KEEPOUT に数字で書いてある。
    **書いただけでは、そこにアンテナがある保証にならない。**子基板の
    位置はケース側（電池の寄せ方・壁厚）から決まるので、そちらが動くと
    黙ってずれる。ここで両方から計算して突き合わせる。

    右は入れられなかった（None）。裏面を列のバス 9 本が横断しており、
    子基板の x をどこに置いても配線が掛かる。理由は interface.py。
    """
    from interface import ANTENNA_KEEPOUT
    from gen_case import (BUMP_DEPTH, DB_D, DB_FROM_REAR, WALL,
                          daughterboard_x_center)
    from gen_plate import plate_positions

    spec = ANTENNA_KEEPOUT[name]
    if spec is None:
        return
    cx, cy, w, h = spec
    _, (pw, ph) = plate_positions(HALVES[name])

    # 本物のアンテナ（ケース座標）。子基板の前端 3mm、幅は XIAO の 18mm。
    dbx = daughterboard_x_center(name, pw)
    db_hi = ph / 2 + BUMP_DEPTH - WALL - DB_FROM_REAR
    ant_x_lo, ant_x_hi = dbx - 9.0, dbx + 9.0
    ant_y_lo = db_hi - DB_D
    ant_y_hi = ant_y_lo + 3.0

    # 基板の座標系はケースと同じ原点・同じ向き（どちらも中心・Y 上向き）
    # ではない。基板の y=0 は基板の中心、ケースの y=0 は本体の中心。
    # 基板は PCB_INSET_Y ぶん前後を詰めてあるので、後端どうしで合わせる。
    from interface import PCB_INSET_Y
    pcb_rear_case_y = ph / 2 - PCB_INSET_Y          # 基板の後端（ケース座標）
    pcb_h = ph - 2 * PCB_INSET_Y
    def to_pcb_y(case_y):
        return case_y - (pcb_rear_case_y - pcb_h / 2)

    ky_lo, ky_hi = to_pcb_y(ant_y_lo), to_pcb_y(ant_y_hi)
    kx_lo, kx_hi = ant_x_lo, ant_x_hi

    lo_x, hi_x = cx - w / 2, cx + w / 2
    lo_y, hi_y = cy - h / 2, cy + h / 2
    assert lo_x <= kx_lo and kx_hi <= hi_x, (
        f"{name}: 禁止域 x {lo_x:.1f}〜{hi_x:.1f} が"
        f" アンテナ x {kx_lo:.1f}〜{kx_hi:.1f} を覆っていない")
    assert lo_y <= ky_lo and ky_hi <= hi_y, (
        f"{name}: 禁止域 y {lo_y:.1f}〜{hi_y:.1f} が"
        f" アンテナ y {ky_lo:.1f}〜{ky_hi:.1f} を覆っていない")
