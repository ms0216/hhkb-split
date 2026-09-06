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
    PCB_POST_D,
    boss_positions,
    pcb_mount_positions,
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
    """**ボスが基板の外にあること。**

    上ケース方式では基板に穴を開けない。以前はここが「穴が基板の中に
    収まること」で、向きが逆だった。
    """
    # 2026-09-05: 手前のボスは円柱ではなく角柱で、内面は基板の縁（平面図）+
    # CLEARANCE に置く。インサートの内側の肉 FRONT_BOSS_WALL_IN を残して
    # ネジの中心を決めている（interface.MOUNT_Y の注記）。**平面図の座標**で見る
    from interface import (CLEARANCE, FRONT_BOSS_WALL_IN, M2_INSERT_D,
                           PCB_FRONT_EDGE_PLAN)
    for x, y in boss_positions(name):
        boss_inner = abs(y) - M2_INSERT_D / 2 - FRONT_BOSS_WALL_IN
        assert boss_inner >= PCB_FRONT_EDGE_PLAN + CLEARANCE - 1e-6, \
            f"{name}: ボス({x},{y}) の内面 {boss_inner:.2f} が基板（平面図の縁 {PCB_FRONT_EDGE_PLAN:.2f}）に掛かる"


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
def test_pcb_posts_do_not_touch_any_key(name):
    """基板を留める柱（φ4・PCB_MOUNT_POSITIONS）もキーの占有範囲に食い込まないこと。

    上の検査はケースのボスしか見ておらず、柱は見ていなかった。2026-09-02 に
    スペースを内側端へ寄せたら、右 H4 が R-Space の真下に立っていたのを
    プレートの開口数の検査が偶然拾った。柱そのものを見る。

    余裕は柱の半径だけ（BOSS_KEEPOUT_GAP は足さない）。凍結済みの柱は占有範囲
    から 2.1〜2.4mm にあり、そこは DRC（コートヤード）と実形状の組み立て検査が
    別に見ている。ここで見たいのは**柱がキーの真下に立つ**取り違え。
    """
    boxes = keepout_boxes(HALVES[name])
    r = PCB_POST_D / 2
    for x, y in pcb_mount_positions(name):
        for bx0, by0, bx1, by1 in boxes:
            dx = max(bx0 - x, 0.0, x - bx1)
            dy = max(by0 - y, 0.0, y - by1)
            assert dx * dx + dy * dy >= r * r - 1e-9, \
                f"{name}: ({x}, {y}) の柱がキーの占有範囲 ({bx0:.1f},{by0:.1f})-({bx1:.1f},{by1:.1f}) に食い込む"


@pytest.mark.parametrize("name", NAMES)
def test_rear_bosses_clear_the_battery(name):
    """ボスが電池室を貫かないこと。

    中に立てると電池室を貫く。以前 231mm^3 の食い込みを出した。

    **以前は「|x| が 109/2 より外」しか見ておらず、Y を見ていなかった。**
    電池を外側へ寄せ、さらにコブの中へ移したあとも中央にあるものとして
    検査していたので、**別の場所を見ていた**。実際の電池の占有範囲で見る。
    """
    from gen_case import (BATT_W, BATT_X, battery_center, battery_x_center)
    from gen_plate import plate_positions, halves
    from interface import plan_depth
    _, (w, h_plate) = plate_positions(halves()[name])
    bx = battery_x_center(name, w)
    by = battery_center(plan_depth(h_plate))
    # **余裕は 0.5mm。** battery_envelope の側に既に余裕が入っている
    # （電極とバネで長手 8.0mm、直径 +1.0mm）。ここで更に 3mm 積むと
    # 二重計上になり、実際には 0.7mm 離れているボスを不合格にしていた。
    # ここで見たいのは「占有空間に食い込まないこと」と印刷公差ぶんの隙間だけ。
    r = M2_BOSS_D / 2 + 0.5
    for x, y in boss_positions(name):
        inside_x = bx - BATT_X / 2 - r < x < bx + BATT_X / 2 + r
        inside_y = by - BATT_W / 2 - r < y < by + BATT_W / 2 + r
        assert not (inside_x and inside_y), \
            f"{name}: ボス ({x}, {y}) が電池室 "\
            f"(x {bx-BATT_X/2:.1f}..{bx+BATT_X/2:.1f}, "\
            f"y {by-BATT_W/2:.1f}..{by+BATT_W/2:.1f}) にかかる"


@pytest.mark.parametrize("name", NAMES)

def test_three_bosses_sit_along_the_front_edge(name):
    """**手前の 3 本だけ。奥はフックで引っ掛ける。**

    以前は 7 本を四方に置いていたが、14 本中 9 本がキーキャップの下に入り、
    開けるのにキャップを外す必要があった。奥にも置こうとしたが、ボスの
    外端 y=54.00 が電池の手前端 y=52.10 と 1.90mm 重なる。
    """
    from interface import MOUNT_Y
    pts = boss_positions(name)
    assert len(pts) == 3, f"{name}: ボスが {len(pts)} 本ある"
    assert all(y == pytest.approx(-MOUNT_Y) for _, y in pts), \
        f"{name}: 手前の帯（y=-{MOUNT_Y}）に無いボスがある"
    xs = sorted(x for x, _ in pts)
    assert xs[0] < -30 and xs[1] == pytest.approx(0.0) and xs[2] > 30, \
        f"{name}: 3 本が散っていない {xs}"


def test_positions_are_defined_for_both_halves():
    assert set(MOUNT_POSITIONS) == {"left", "right"}
    with pytest.raises(ValueError):
        boss_positions("middle")
