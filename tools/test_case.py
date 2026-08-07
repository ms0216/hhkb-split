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
    """
    from gen_plate import plate_positions
    from interface import plan_depth
    part, (w, h_body), _ = build_case(HALVES[name])
    _, (pw, h_plate) = plate_positions(HALVES[name])
    bb = part.bounding_box().size
    assert bb.X == pytest.approx(pw, abs=0.01)
    assert h_body == pytest.approx(plan_depth(h_plate), abs=0.01)
    assert bb.Y == pytest.approx(h_body, abs=0.01)


@pytest.mark.parametrize("name", ["left", "right"])
def test_rim_height_gives_the_intended_plate_top(name):
    """リムの高さ + 板厚 = 狙ったプレート上面高さ。"""
    part, _, (z_front, z_rear) = build_case(HALVES[name])
    assert part.bounding_box().size.Z == pytest.approx(z_rear - PLATE_T, abs=0.05)
    assert z_front == pytest.approx(PLATE_TOP_FRONT)


@pytest.mark.parametrize("name", ["left", "right"])
def test_printable(name):
    part, _, _ = build_case(HALVES[name])
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
    part, (_, h_body), _ = build_case(HALVES[name])
    batt = battery_envelope((0, battery_center(h_body), FLOOR + AA_D / 2))
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
    lid, (lw, lh) = build_battery_lid(HALVES[name])
    mesh, _ = to_mesh(lid, f"battery_lid_{name}")
    assert_watertight(mesh, f"battery_lid_{name}")
    _, (w, h) = plate_positions(HALVES[name])
    _, _, ow, oh = _lid_opening(w, h)
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
    assert _boss_positions(w, h_plate) == boss_positions_plan(w, h_plate)


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

    _, (w, h_plate) = plate_positions(HALVES[name])
    batt = battery_envelope((0, battery_center(plan_depth(h_plate)),
                             FLOOR + AA_D / 2))
    for bx, by in _boss_positions(w, h_plate):
        with BuildPart() as b:
            with Locations((bx, by, FLOOR)):
                Cylinder(M2_BOSS_D / 2, 40,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        v = intersection_volume(batt, b.part)
        assert v < 1e-3, f"{name}: ボス({bx:.1f},{by:.1f}) が電池室を貫く ({v:.1f}mm^3)"
