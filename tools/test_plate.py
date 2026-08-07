"""プレートが物理的に正しいことを検証する。

目視だけでは「開口が原点に固まる」ような不具合を見落とすので、
位置と寸法を数値で確かめる。
"""

import pytest
from build123d import Axis
from gen_plate import (
    CORNER_R,
    PLATE_MARGIN,
    PLATE_T,
    SWITCH_CUTOUT,
    build_plate,
    halves,
    stab_offset_for,
)
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
    part, _, _ = build_plate(HALVES[name])
    assert_bbox(part, expect_z=PLATE_T, label=f"{name}: ")


@pytest.mark.parametrize("name", ["left", "right"])
def test_outline_size_matches_keys_plus_margin(name):
    keys = HALVES[name]
    part, (w, h), _ = build_plate(keys)
    span_x = max(k.right_u for k in keys) - min(k.left_u for k in keys)
    assert w == pytest.approx(span_x * UNIT + 2 * PLATE_MARGIN)
    assert h == pytest.approx(5 * UNIT + 2 * PLATE_MARGIN)
    assert_bbox(part, expect_x=w, expect_y=h, label=f"{name}: ")


@pytest.mark.parametrize("name", ["left", "right"])
def test_is_printable(name):
    part, _, _ = build_plate(HALVES[name])
    mesh, _ = to_mesh(part, f"plate_{name}")
    assert_watertight(mesh, f"plate_{name}")


@pytest.mark.parametrize("name,keys_n", [("left", 27), ("right", 34)])
def test_cutout_count_matches_keys_plus_screws(name, keys_n):
    """開口の総数 = キー数 + 取付ネジ穴の数。

    スタビライザー開口はそれぞれのスイッチ開口と繋がって 1 つになるので、
    キーの分はキー数と一致する。隣のキーを飲み込むと数が減る。
    ネジ穴はケース側のボスと同じ位置に開ける（開け忘れると締結できない）。
    """
    from interface import boss_positions
    part, (w, h), _ = build_plate(HALVES[name])
    expect = keys_n + len(boss_positions(w, h))
    assert len(cutouts(part)) == expect


@pytest.mark.parametrize("name", ["left", "right"])
def test_screw_holes_align_with_case_bosses(name):
    """プレートのネジ穴が、ケース側のボスと同じ位置にあること。

    両者が別々に位置を計算していると、いつかずれる。共有定義から導く。
    """
    from interface import M2_CLEAR_D, boss_positions
    part, (w, h), _ = build_plate(HALVES[name])
    holes = [c for c in cutouts(part)
             if c[2] == pytest.approx(M2_CLEAR_D, abs=0.01)]
    want = boss_positions(w, h)
    assert len(holes) == len(want)
    for wx, wy in want:
        assert any(h[0] == pytest.approx(wx, abs=0.01)
                   and h[1] == pytest.approx(wy, abs=0.01) for h in holes), \
            f"{name}: ({wx:.2f}, {wy:.2f}) にネジ穴が無い"


@pytest.mark.parametrize("name", ["left", "right"])
def test_plain_cutouts_are_14mm(name):
    """スタビライザーの無いキーの開口は 14.0mm 角ちょうど。"""
    keys = HALVES[name]
    n_plain = sum(1 for k in keys if stab_offset_for(k.w_u) is None)
    part, _, _ = build_plate(keys)
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
    part, (w, h), positions = build_plate(keys)
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
    part, (w, h), _ = build_plate(HALVES[name])
    for cx, cy, cw, ch in cutouts(part):
        assert w / 2 - (abs(cx) + cw / 2) > 1.0, f"{name}: 開口が左右端に近すぎる"
        assert h / 2 - (abs(cy) + ch / 2) > 1.0, f"{name}: 開口が上下端に近すぎる"


def test_stab_offset_rejects_unknown_width():
    """未知の幅を黙って通さないこと。"""
    with pytest.raises(ValueError):
        stab_offset_for(2.5)


def test_corner_radius_is_applied():
    """外形の角が丸められていること（直角なら頂点が 4 つのはず）。"""
    part, _, _ = build_plate(HALVES["left"])
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
