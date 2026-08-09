"""プレートが物理的に正しいことを検証する。

目視だけでは「開口が原点に固まる」ような不具合を見落とすので、
位置と寸法を数値で確かめる。
"""

import pytest
from build123d import Axis
from gen_plate import (
    CORNER_R,
    PLATE_T,
    SWITCH_CUTOUT,
    build_plate,
    halves,
    stab_offset_for,
)
from interface import PLATE_MARGIN_X, PLATE_MARGIN_Y
from layout import UNIT
from verify import assert_bbox, assert_watertight, to_mesh

HALVES = halves()


def top_face(part):
    return part.faces().sort_by(Axis.Z)[-1]


def cutouts(part):
    """上面の内側輪郭（＝開口）を bbox とともに返す。"""
    out = []
    for w in top_face(part).inner_wires():
        bb = w.bounding_box()
        out.append((bb.center().X, bb.center().Y, bb.size.X, bb.size.Y))
    return out


@pytest.mark.parametrize("name", ["left", "right"])
def test_thickness(name):
    part, _, _ = build_plate(HALVES[name], name)
    assert_bbox(part, expect_z=PLATE_T, label=f"{name}: ")


@pytest.mark.parametrize("name", ["left", "right"])
def test_outline_covers_the_keys(name):
    """プレートがキーの並びを覆い、縁まで材料が残っていること。"""
    keys = HALVES[name]
    part, (w, h), _ = build_plate(keys, name)
    span_x = max(k.right_u for k in keys) - min(k.left_u for k in keys)
    # 端のキーの開口の外側に残る材料。ここが 0 になると縁が抜ける。
    margin_x = (w - (span_x * UNIT - UNIT + SWITCH_CUTOUT)) / 2
    margin_y = (h - (5 * UNIT - UNIT + SWITCH_CUTOUT)) / 2
    assert margin_x > 1.0 and margin_y > 1.0, (
        f"{name}: 開口から縁までの材料が {margin_x:.2f} / {margin_y:.2f}mm しかない")
    assert_bbox(part, expect_x=w, expect_y=h, label=f"{name}: ")


@pytest.mark.parametrize("name", ["left", "right"])
def test_the_tilted_plate_fits_inside_the_bezel(name):
    """**傾けた**プレートが、上ケースの座ぐりに隙間を持って収まること。

    **平面図で比べる。**平らな寸法どうしで比べると 2 つ取りこぼす:
      - 傾けると奥行が cos(7.3°) 倍に縮む
      - 板厚のぶん平面での占有が sin(7.3°) 倍だけ増える（1.5 → 0.19mm）

    実際、プレートは平らな奥行から壁を引いて作られ、上ケースの座ぐりは
    平面図の奥行から引かれていたため、**プレートが 0.217mm 大きく、
    手前の縁が壁に当たって座ぐりに落ちなかった**（2026-08-10 に発見）。
    左右方向も隙間 0 だった。**式を写すのではなく、収まるかどうかを見る。**
    """
    from math import cos, radians, sin
    from interface import (BEZEL_WALL, CLEARANCE, TILT_DEG, plan_depth,
                           plate_positions)

    keys = HALVES[name]
    _, (case_w, case_h) = plate_positions(keys)
    _, (w, h), _ = build_plate(keys, name)
    t = radians(TILT_DEG)
    plan_w, plan_h = w, h * cos(t) + PLATE_T * sin(t)   # 傾けた平面図での占有
    cavity_w = case_w - BEZEL_WALL * 2                   # 上ケースの壁の内側
    cavity_h = plan_depth(case_h) - BEZEL_WALL * 2
    for axis, gap in (("X", cavity_w - plan_w), ("Y", cavity_h - plan_h)):
        assert gap == pytest.approx(CLEARANCE, abs=1e-6), (
            f"{name}: {axis} 方向の隙間が {gap:+.3f}mm（設計は {CLEARANCE}mm）。"
            "負なら座ぐりに落ちない。0 なら公差で当たる")


@pytest.mark.parametrize("name", ["left", "right"])
def test_is_printable(name):
    part, _, _ = build_plate(HALVES[name], name)
    mesh, _ = to_mesh(part, f"plate_{name}")
    assert_watertight(mesh, f"plate_{name}")


@pytest.mark.parametrize("name,keys_n", [("left", 27), ("right", 34)])


def test_cutout_count_matches_keys_plus_screws(name, keys_n):
    """**すべてのキー位置に開口が開いていること。**

    以前は内周の数を数えていたが、数が合っていても位置が違えば意味がない。
    キーの位置ごとに実際に貫通しているかを見る（外部の事実との照合）。
    """
    from build123d import Align, Box, BuildPart, Locations
    from interface import plate_positions
    from verify import intersection_volume
    part, _, _ = build_plate(HALVES[name], name)
    positions, _ = plate_positions(HALVES[name])
    blocked = []
    for (x, y) in positions:
        with BuildPart() as probe:
            with Locations((x, y, -1)):
                Box(13.0, 13.0, 10.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
        if intersection_volume(probe.part, part) > 1e-3:
            blocked.append((round(x, 1), round(y, 1)))
    assert not blocked, f"{name}: 開口が無いキー位置 {blocked[:5]}"
    assert len(positions) == keys_n


@pytest.mark.parametrize("name", ["left", "right"])

def test_screw_holes_align_with_case_bosses(name):
    """ネジがプレートに当たらずに通ること。

    **手前の 3 箇所はプレートの縁を跨ぐので切り欠きになる。**
    以前は円形の穴を数えていたが、切り欠きは円として現れないので
    「0 個」と判定してしまう。**通るかどうかを直接見る。**
    """
    from build123d import Align, BuildPart, Cylinder, Locations
    from interface import M2_CLEAR_D, boss_positions
    from verify import intersection_volume
    part, _, _ = build_plate(HALVES[name], name)
    hit = []
    for (x, y) in boss_positions(name):
        with BuildPart() as probe:
            with Locations((x, y, -1)):
                Cylinder(M2_CLEAR_D / 2, 10.0,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        v = intersection_volume(probe.part, part)
        if v > 1e-3:
            hit.append((round(x, 1), round(y, 1), round(v, 2)))
    assert not hit, f"{name}: ネジがプレートに当たる {hit}"


@pytest.mark.parametrize("name", ["left", "right"])
def test_plain_cutouts_are_14mm(name):
    """スタビライザーの無いキーの開口は 14.0mm 角ちょうど。"""
    keys = HALVES[name]
    n_plain = sum(1 for k in keys if stab_offset_for(k.w_u) is None)
    part, _, _ = build_plate(keys, name)
    plain = [c for c in cutouts(part)
             if c[2] == pytest.approx(SWITCH_CUTOUT, abs=1e-6)]
    assert len(plain) == n_plain
    for _, _, w, h in plain:
        assert h == pytest.approx(SWITCH_CUTOUT, abs=1e-6)


@pytest.mark.parametrize("name", ["left", "right"])
def test_stab_cutouts_are_where_the_wide_keys_are(name):
    """2u 以上のキーにだけ、正しい位置と大きさのスタビライザー開口があること。

    Cherry の開口は前後非対称で、手前側に長い（swillkb の座標で y=-5.53..+7.97、
    Y を反転して -7.97..+5.53）。スイッチ開口 14mm 角と結合した外接矩形は:
      幅   = 2*(s + 4.2)
      高さ = 7.0 - (-7.97) = 14.97
      中心 = キー中心から Y に -0.485mm（手前へずれる）
    左右方向は対称なので X はキー中心と厳密に一致する。
    """
    keys = HALVES[name]
    part, (w, h), positions = build_plate(keys, name)
    wide = [(pos, stab_offset_for(k.w_u))
            for pos, k in zip(positions, keys) if stab_offset_for(k.w_u)]
    assert wide, f"{name}: 2u 以上のキーが 1 つも無いのはおかしい"

    found = [c for c in cutouts(part) if c[2] > SWITCH_CUTOUT + 1e-6]
    assert len(found) == len(wide), f"{name}: 幅広開口 {len(found)} != 対象キー {len(wide)}"

    expect_h = 7.0 + 7.97
    expect_dy = (-7.97 + 7.0) / 2

    for (px, py), s in wide:
        match = [c for c in found if c[0] == pytest.approx(px, abs=1e-6)]
        assert match, f"{name}: X={px:.2f} に幅広開口が無い（左右非対称になっている）"
        cx, cy, cw, ch = match[0]
        assert cw == pytest.approx(2 * (s + 4.2), abs=1e-6), (
            f"{name}: 開口幅 {cw:.3f} != 期待 {2 * (s + 4.2):.3f} (s={s})"
        )
        assert ch == pytest.approx(expect_h, abs=1e-6), (
            f"{name}: 開口高さ {ch:.3f} != 期待 {expect_h:.3f}"
        )
        assert cy - py == pytest.approx(expect_dy, abs=1e-6), (
            f"{name}: Y ずれ {cy - py:.3f} != 期待 {expect_dy:.3f}"
            "（前後の向きが逆になっている可能性）"
        )


@pytest.mark.parametrize("name", ["left", "right"])
def test_no_cutout_reaches_the_edge(name):
    """どの開口も外形から離れていること。角丸ぶんを見て 1mm 以上の余裕を要求する。"""
    part, (w, h), _ = build_plate(HALVES[name], name)
    for cx, cy, cw, ch in cutouts(part):
        assert w / 2 - (abs(cx) + cw / 2) > 1.0, f"{name}: 開口が左右端に近すぎる"
        assert h / 2 - (abs(cy) + ch / 2) > 1.0, f"{name}: 開口が上下端に近すぎる"


def test_stab_offset_rejects_unknown_width():
    """未知の幅を黙って通さないこと。"""
    with pytest.raises(ValueError):
        stab_offset_for(2.5)


def test_corner_radius_is_applied():
    """外形の角が丸められていること（直角なら頂点が 4 つのはず）。"""
    part, _, _ = build_plate(HALVES["left"], "left")
    outer = top_face(part).outer_wire()
    assert len(outer.edges()) > 4, "角丸が適用されていない"
    assert CORNER_R > 0


def test_stabilizer_offsets_come_from_the_shared_definition():
    """スタビライザー間隔をプレート側で独自に持たない。

    プレートの開口と基板の逃げ穴は同じ位置に来る必要がある。以前ネジボスの
    位置をプレートとケースで別々に持っていて食い違わせたので、同じ轍を踏まない。

    値そのものも Cherry の規格（11.938 / 19.05mm）と一致していること。
    基板用フットプリント（kiswitch）がこの値を使うため、ここがずれると
    プレートと基板が合わなくなる。
    """
    import gen_plate
    import interface

    assert not hasattr(gen_plate, "STAB_OFFSET"), \
        "gen_plate が独自にスタビライザー間隔を持っている"
    assert gen_plate.stab_offset_for is interface.stab_offset_for
    assert interface.STAB_OFFSET[2.25] == 11.938
    assert interface.STAB_OFFSET[3.0] == 19.05
    assert interface.stab_offset_for(1.75) is None, "2u 未満にスタビは付けない"
