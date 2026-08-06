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
def test_outer_size_matches_plate(name):
    """ケースの外形はプレートと同一（サンドイッチ構造）。"""
    part, (w, h), _ = build_case(HALVES[name])
    bb = part.bounding_box().size
    assert bb.X == pytest.approx(w, abs=0.01)
    assert bb.Y == pytest.approx(h, abs=0.01)


@pytest.mark.parametrize("name", ["left", "right"])
def test_rim_height_gives_the_intended_plate_top(name):
    """リムの高さ + 板厚 = 狙ったプレート上面高さ。"""
    part, (_, h), (z_front, z_rear) = build_case(HALVES[name])
    assert part.bounding_box().size.Z == pytest.approx(z_rear - PLATE_T, abs=0.01)
    assert z_front == pytest.approx(PLATE_TOP_FRONT)


@pytest.mark.parametrize("name", ["left", "right"])
def test_printable(name):
    part, _, _ = build_case(HALVES[name])
    mesh, _ = to_mesh(part, f"case_{name}")
    assert_watertight(mesh, f"case_{name}")


@pytest.mark.parametrize("name", ["left", "right"])
def test_two_aa_batteries_fit(name):
    """単3×2 がケースと干渉せずに収まること。

    電池を表す立体を電池室の位置に置き、ケース実体との重なりが 0 か見る。
    """
    part, (w, h), _ = build_case(HALVES[name])
    y = h / 2 - 2.4 - 6.0 - BATT_W / 2
    for dx in (-(AA_D + 0.5) / 2, (AA_D + 0.5) / 2):
        batt = Location((0, y + dx, FLOOR + AA_D / 2)) * Box(
            AA_L, AA_D, AA_D, align=(Align.CENTER, Align.CENTER, Align.CENTER))
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
    from gen_case import FOOT_INSET_REAR, build_tilt_foot, foot_height
    from gen_plate import plate_positions
    _, (w, h) = plate_positions(HALVES["left"])
    z = foot_height(h, deg)
    lever = h - FOOT_INSET_REAR
    assert math.degrees(math.atan(z / lever)) == pytest.approx(deg, abs=1e-9)
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
