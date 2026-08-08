"""組み上げた状態で部品どうしが食い込まないことを守る。

**この検査はこれまで pytest から呼ばれていなかった。**
tools/gen_assembly.py を手で叩いたときにしか動かず、その結果
「単体のテストは全部通るのに、組み上げると食い込む」状態を何度も作った。
実際にこのファイルを足した時点でも、電池と仕切り壁で 2 件見つかっている。

部品を 1 つ足したら、必ず gen_assembly.build_assembly の parts へも足すこと。
**検査対象に入っていない部品は、検査されていないのと同じ。**
"""

import sys
from pathlib import Path

import pytest

CLEARANCE_HALF = 0.1   # gen_case.CLEARANCE / 2（空所は片側 0.1mm 広い）

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_assembly import build_assembly, check  # noqa: E402
from gen_plate import halves  # noqa: E402

HALVES = halves()

# 組み立てに含まれていなければならない部品。
# 名前を書いておくことで、あとから足した部品が検査から漏れるのを防ぐ。
REQUIRED = {"case", "plate", "pcb", "lid", "batt", "db", "topcase"}


@pytest.mark.parametrize("half", ["left", "right"])
def test_nothing_bites_into_anything_else(half):
    problems, _ = check(HALVES[half], half)[:2]
    assert not problems, f"{half}:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("half", ["left", "right"])
def test_every_part_is_in_the_check(half):
    """検査対象から部品が漏れていないこと。

    子基板を足したとき、ケースには造作を入れたのに検査には入れ忘れていた。
    そうすると「通った」が「調べていない」の同義語になる。
    """
    parts, _ = build_assembly(HALVES[half], half)
    missing = REQUIRED - set(parts)
    assert not missing, f"{half}: 検査に入っていない部品 {sorted(missing)}"


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_check_actually_detects_a_collision(half):
    """**検査そのものが効いていることを確かめる。**

    通ったことは、調べた証拠にならない。故意に壊して検出できることを
    毎回確かめる。この案件では、誤った並び順どうしを突き合わせて
    テストが全部通ってしまった前科がある。
    """
    import envelopes

    original = envelopes.DB_STACK_H
    try:
        envelopes.DB_STACK_H = original + 15.0     # 子基板の部品を背高にする
        problems, _ = check(HALVES[half], half)[:2]
        assert any("db" in p for p in problems), \
            "子基板を 15mm 背高にしても検出できない。検査が効いていない"
    finally:
        envelopes.DB_STACK_H = original


# --------------------------------------------------------------------------
# 電源スイッチが背面パネルに収まるか
# --------------------------------------------------------------------------

def rear_panel_gaps(half):
    """背面パネルぞいの、障害物が無い x 区間と、使える奥行を返す。

    コブの中には電池と子基板が入っていて、どちらも背面壁の 1〜2mm 手前まで
    来ている。**スイッチを置けるのは、その左右の隙間だけ。**
    """
    from gen_case import (BUMP_DEPTH, DB_W, WALL, battery_x_center,
                          daughterboard_x_center)
    from gen_case import BATT_X
    from gen_plate import halves
    from interface import plate_positions
    from matrix import keymap_order
    _, (w, _h) = plate_positions(keymap_order(halves()[half]))
    bx, dx = battery_x_center(half, w), daughterboard_x_center(half, w)
    obstacles = sorted([(bx - BATT_X / 2, bx + BATT_X / 2),
                        (dx - DB_W / 2, dx + DB_W / 2)])
    gaps, cur = [], -w / 2 + WALL
    for a, b in obstacles:
        if a > cur:
            gaps.append((cur, a))
        cur = max(cur, b)
    if w / 2 - WALL > cur:
        gaps.append((cur, w / 2 - WALL))
    return gaps, BUMP_DEPTH - WALL


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_power_switch_fits_on_the_rear_panel(half):
    """電源スイッチが背面パネルの空きに収まること。

    **これは目で見て判断してはいけない。**左半分は電池と子基板の間に
    10.6mm しか無く、電池は左端まで 0.2mm・子基板は右端まで 0.8mm しか
    余っていないので、どちらもずらせない。買ってから入らないと分かると、
    リードタイムがもう一往復する（open-gaps #17 / #18）。

    買う製品を変えたら envelopes.py の SW_PWR_W / _D / _H を差し替える。
    それだけでここが判定し直す。
    """
    from envelopes import SW_PWR_D, SW_PWR_H, SW_PWR_W
    from gen_case import BATT_H
    gaps, depth = rear_panel_gaps(half)
    widest = max(b - a for a, b in gaps)
    assert SW_PWR_W <= widest, (
        f"{half}: スイッチの幅 {SW_PWR_W}mm が背面の空き {widest:.1f}mm に入らない\n"
        f"  空き区間: {[f'{a:+.1f}..{b:+.1f}' for a, b in gaps]}")
    assert SW_PWR_D <= depth, (
        f"{half}: スイッチの奥行 {SW_PWR_D}mm がコブの内寸 {depth:.1f}mm を超える")
    # 高さはコブの内部（電池が入る高さ）に収まること
    assert SW_PWR_H <= BATT_H, (
        f"{half}: スイッチの高さ {SW_PWR_H}mm がコブの内部 {BATT_H}mm を超える")


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_power_switch_holder_exists_and_is_hollow(half):
    """スイッチの受けが「足されて」いて、中身が空いていること。

    **奥の壁の内側は電池室の空洞で、もともと材料が無い。**座ぐりを掘る
    設計にしていたが、それは空気を削るだけでスイッチを受ける面ができない。
    **故意に「彫るのをやめる」実験をしたら検査が落ちなかった**ことで
    見つかった（壊しても落ちない＝検査していない）。

    そこで見るのは 3 つ。
      1. 空所の**まわりに壁がある**（受けの箱が足されている）
      2. 空所そのものは**空いている**（スイッチが入る）
      3. 操作部のスロットが**壁を貫いている**
    """
    import numpy as np
    import trimesh
    from envelopes import SW_PWR_D, SW_PWR_H, SW_PWR_W
    from gen_case import (BUMP_DEPTH, SW_RIB, WALL, power_switch_center_z,
                          power_switch_x_center)
    from interface import plate_positions
    from matrix import keymap_order

    stl = Path(__file__).resolve().parent.parent / f"build/case_{half}.stl"
    if not stl.exists():
        pytest.skip("ケースがまだ生成されていない（tools/gen_case.py）")
    _, (w, hb) = plate_positions(keymap_order(halves()[half]))
    mesh = trimesh.load(stl)
    x, z = power_switch_x_center(half, w), power_switch_center_z()
    y_out = hb / 2 + BUMP_DEPTH
    y_mid = y_out - WALL - SW_PWR_D / 2          # 空所の中心 y

    def solid(pts):
        return float(np.mean(mesh.contains(np.array(pts))))

    cavity = [(x + dx, y_mid + dy, z + dz)
              for dx in np.linspace(-SW_PWR_W * 0.35, SW_PWR_W * 0.35, 5)
              for dy in np.linspace(-SW_PWR_D * 0.3, SW_PWR_D * 0.3, 5)
              for dz in np.linspace(-SW_PWR_H * 0.35, SW_PWR_H * 0.35, 3)]
    # 受けの箱の壁（左右と上下）。**ここに材料が無ければスイッチは宙に浮く。**
    off_w = SW_PWR_W / 2 + CLEARANCE_HALF + SW_RIB / 2
    off_h = SW_PWR_H / 2 + CLEARANCE_HALF + SW_RIB / 2
    walls = ([(x + s_ * off_w, y_mid, z) for s_ in (-1, 1)]
             + [(x, y_mid, z + s_ * off_h) for s_ in (-1, 1)])
    slot = [(x + dx, y_out - WALL / 2, z + dz)
            for dx in np.linspace(-0.6, 0.6, 3)
            for dz in np.linspace(-1.0, 1.0, 3)]

    assert solid(walls) == 1.0, (
        f"{half}: スイッチの受けの壁が無い（材料 {solid(walls):.0%}）。"
        "空所を彫っただけでは、奥の壁の内側は元から空洞なので受けにならない")
    assert solid(cavity) == 0.0, \
        f"{half}: スイッチの空所に材料が残っている"
    assert solid(slot) == 0.0, \
        f"{half}: 操作部のスロットが壁を貫通していない"
