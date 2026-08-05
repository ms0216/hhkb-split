"""配列 JSON が確定した寸法どおりかを、既知の事実で検証する。

期待値の出典はすべて docs/hardware/dimensions.md（QMK の info.json と
Wikimedia Commons の KLE 図が一致した内容）。
"""

import math

import pytest
from layout import UNIT, bounds_mm, load_layout, split_halves

ORIGINAL = "layout/hhkb_original.json"
SPLIT = "layout/hhkb_split.json"


# --------------------------------------------------------------------------
# 原機
# --------------------------------------------------------------------------


def test_original_has_60_keys():
    assert len(load_layout(ORIGINAL)) == 60


def test_original_keyfield_is_15u():
    x0, _, x1, _ = bounds_mm(load_layout(ORIGINAL))
    assert (x1 - x0) == pytest.approx(15 * UNIT)      # 285.75mm


def test_original_upper_four_rows_are_15u_each():
    """上4段はいずれも合計 15u。最下段だけは余白があるので別扱い。"""
    keys = load_layout(ORIGINAL)
    for row in range(4):
        total = sum(k.w_u for k in keys if k.row == row)
        assert total == pytest.approx(15.0), f"row {row} = {total}u"


def test_original_bottom_row_spans_1_5_to_12_5():
    """最下段は 左余白1.5u / 右余白2.5u で非対称（dimensions.md §3）。"""
    bottom = [k for k in load_layout(ORIGINAL) if k.row == 4]
    assert min(k.left_u for k in bottom) == pytest.approx(1.5)
    assert max(k.right_u for k in bottom) == pytest.approx(12.5)


def test_original_bottom_row_widths():
    """外側が 1u、スペース寄りが 1.5u（当初の想定と逆だった箇所）。"""
    bottom = sorted((k for k in load_layout(ORIGINAL) if k.row == 4),
                    key=lambda k: k.left_u)
    assert [k.w_u for k in bottom] == [1.0, 1.5, 6.0, 1.5, 1.0]


def test_original_row_key_counts():
    keys = load_layout(ORIGINAL)
    counts = [sum(1 for k in keys if k.row == r) for r in range(5)]
    assert counts == [15, 14, 13, 13, 5]


# --------------------------------------------------------------------------
# 分割版
# --------------------------------------------------------------------------


def test_split_has_61_keys():
    assert len(load_layout(SPLIT)) == 61


def test_split_has_two_3u_spaces():
    spaces = [k for k in load_layout(SPLIT) if k.w_u == pytest.approx(3.0)]
    assert len(spaces) == 2
    assert {k.label for k in spaces} == {"L-Space", "R-Space"}


def test_split_half_key_counts():
    left, right = split_halves(load_layout(SPLIT))
    assert (len(left), len(right)) == (27, 34)


def test_split_half_widths():
    """左 7.25u / 右 9u。重なり 1.25u のぶん合計は原機より広くなる。"""
    left, right = split_halves(load_layout(SPLIT))
    lw = max(k.right_u for k in left) - min(k.left_u for k in left)
    rw = max(k.right_u for k in right) - min(k.left_u for k in right)
    assert lw == pytest.approx(7.25)
    assert rw == pytest.approx(9.0)
    assert (lw + rw) - 15.0 == pytest.approx(1.25)     # 重なりぶん


def test_split_preserves_row_stagger():
    """行ずれが原機と同一であること。各行の左端が 0 / 0 / 0 / 0 で、
    右の島の左端が 0 / 0.5 / 0.75 / 1.25u ずれること。"""
    left, right = split_halves(load_layout(SPLIT))
    for row, expect in enumerate([0.0, 0.0, 0.0, 0.0]):
        got = min(k.left_u for k in left if k.row == row)
        assert got == pytest.approx(expect), f"左 row {row}"
    base = min(k.left_u for k in right if k.row == 0)
    for row, expect in enumerate([0.0, 0.5, 0.75, 1.25]):
        got = min(k.left_u for k in right if k.row == row) - base
        assert got == pytest.approx(expect), f"右 row {row}"


def test_split_key_pitch_is_19_05mm():
    """1u キーが隣り合う箇所の中心間隔が 19.05mm であること。"""
    keys = load_layout(SPLIT)
    for row in range(5):
        ones = sorted((k for k in keys if k.row == row and k.w_u == 1.0),
                      key=lambda k: k.x_mm)
        for a, b in zip(ones, ones[1:]):
            d = b.x_mm - a.x_mm
            if d < UNIT * 1.5:                       # 島の切れ目や幅広キーを跨ぐ箇所は除く
                assert d == pytest.approx(UNIT), f"row {row}: {d}"


def test_split_and_original_have_same_key_set_plus_one_space():
    """分割で増えるのはスペース1つだけ。他のキーは増減しない。"""
    o = load_layout(ORIGINAL)
    s = load_layout(SPLIT)
    assert len(s) - len(o) == 1
    o_non_space = sorted(k.label for k in o if k.label != "Space")
    s_non_space = sorted(k.label for k in s if not k.label.endswith("Space"))
    assert o_non_space == s_non_space


def test_all_widths_are_quarter_unit_multiples():
    """キーキャップの規格サイズは 0.25u 刻み。外れていたら配列が誤っている。"""
    for path in (ORIGINAL, SPLIT):
        for k in load_layout(path):
            assert math.isclose(k.w_u * 4, round(k.w_u * 4)), f"{path}: {k.label} {k.w_u}u"
