"""凍結した取付ネジの位置が、今も有効であることを検査する。

interface.MOUNT_POSITIONS は tools/find_mounts.py が探索して選んだ値を
書き写したもの。配列やフットプリントを変えると無効になりうるが、
値そのものは動かないので気づけない。**毎回その場で検算する。**

当初はネジを外周に等間隔で並べており、取付穴が基板の外形を 0.3mm
はみ出していた。envelopes.py は矩形から円を引くだけなので、はみ出しても
黙ってクリップされて気づけなかった。同じ見落としを繰り返さないための検査。
"""

import pytest

from find_mounts import (
    BATTERY_CLEAR,
    BATTERY_HALF_W,
    BOSS_KEEPOUT_GAP,
    HOLE_EDGE_MARGIN,
    PCB_WALL_GAP,
    keepout_boxes,
)
from gen_plate import halves
from interface import (
    CASE_WALL,
    M2_BOSS_D,
    M2_CLEAR_D,
    MOUNT_POSITIONS,
    boss_positions,
    plate_size,
)
from layout import bounds_mm

HALVES = halves()
NAMES = ["left", "right"]


def _pcb_half(name):
    x0, y0, x1, y1 = bounds_mm(HALVES[name])
    pw, ph = plate_size(x1 - x0, y1 - y0)
    return pw / 2 - CASE_WALL - PCB_WALL_GAP, ph / 2 - CASE_WALL - PCB_WALL_GAP


@pytest.mark.parametrize("name", NAMES)
def test_holes_fit_inside_the_pcb(name):
    """取付穴が基板の外形の中に、余裕を持って収まること。

    これが崩れると、ネジが締まらない基板が届く。
    """
    hw, hh = _pcb_half(name)
    for x, y in boss_positions(name):
        mx = hw - (abs(x) + M2_CLEAR_D / 2)
        my = hh - (abs(y) + M2_CLEAR_D / 2)
        assert mx >= HOLE_EDGE_MARGIN, \
            f"{name}: ({x}, {y}) の穴が基板の左右端に近すぎる（余裕 {mx:.2f}mm）"
        assert my >= HOLE_EDGE_MARGIN, \
            f"{name}: ({x}, {y}) の穴が基板の前後端に近すぎる（余裕 {my:.2f}mm）"


@pytest.mark.parametrize("name", NAMES)
def test_bosses_do_not_touch_any_key(name):
    """ボス（φ5）がキーの占有範囲に食い込まないこと。

    占有範囲はスイッチのフットプリント・プレートの開口・スタビライザーの和。
    プレートの開口はフットプリントより広い（±16.14 対 ±13.93）ので、
    狭い方だけで判定すると Enter の開口にネジ穴を重ねてしまう（実際にやった）。
    """
    boxes = keepout_boxes(HALVES[name])
    r = M2_BOSS_D / 2 + BOSS_KEEPOUT_GAP
    for x, y in boss_positions(name):
        for bx0, by0, bx1, by1 in boxes:
            dx = max(bx0 - x, 0.0, x - bx1)
            dy = max(by0 - y, 0.0, y - by1)
            assert dx * dx + dy * dy >= r * r - 1e-9, \
                f"{name}: ({x}, {y}) のボスがキーの占有範囲に食い込む"


@pytest.mark.parametrize("name", NAMES)
def test_rear_bosses_clear_the_battery(name):
    """奥側のボスが電池室（幅 109mm）の外にあること。

    中に立てると電池室を貫く。以前 231mm^3 の食い込みを出した。
    """
    for x, y in boss_positions(name):
        if y > 0:
            assert abs(x) >= BATTERY_HALF_W + BATTERY_CLEAR, \
                f"{name}: 奥側のボス ({x}, {y}) が電池室にかかる"


@pytest.mark.parametrize("name", NAMES)
def test_seven_bosses_spread_around_the_perimeter(name):
    """7 箇所あり、四隅・手前中央・長辺中央に散っていること。

    数だけ合っていても片側に固まっていたらプレートを支えられない。
    """
    pts = boss_positions(name)
    assert len(pts) == 7
    hw, hh = _pcb_half(name)
    assert sum(1 for x, y in pts if x < 0 and y < 0) >= 1, "手前左が無い"
    assert sum(1 for x, y in pts if x > 0 and y < 0) >= 1, "手前右が無い"
    assert sum(1 for x, y in pts if x < 0 and y > 0) >= 1, "奥左が無い"
    assert sum(1 for x, y in pts if x > 0 and y > 0) >= 1, "奥右が無い"
    assert any(abs(x) < hw * 0.3 and y < 0 for x, y in pts), "手前中央が無い"
    assert any(abs(y) < hh * 0.3 for x, y in pts), "長辺の中央が無い"


def test_positions_are_defined_for_both_halves():
    assert set(MOUNT_POSITIONS) == {"left", "right"}
    with pytest.raises(ValueError):
        boss_positions("middle")
