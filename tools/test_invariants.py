"""HHKB の使い勝手を規定する値が変わっていないことを守る。

これらは実機の調査から得た値で、**設計の都合で動かしてはならない**。
部品が収まらないときに傾斜や高さを妥協するのが最も起きやすい失敗なので、
機械的に止める。

出典はすべて docs/hardware/dimensions.md。値を変えたくなったら、まず
そこの根拠を更新すること。根拠なしにこのファイルを緩めない。
"""

import pytest
from layout import UNIT, bounds_mm, load_layout, split_halves

ORIGINAL = "layout/hhkb_original.json"
SPLIT = "layout/hhkb_split.json"


# --------------------------------------------------------------------------
# 指が触れる面の形（最優先。これが崩れたら別のキーボードになる）
# --------------------------------------------------------------------------

def test_key_pitch_is_19_05mm():
    """業界標準かつ実機の公称値。"""
    assert UNIT == 19.05


def test_typing_plane_tilt_is_7_3deg():
    """topre_key の実機ノギス実測値（"Angle measured on the HHKB"）。

    ケースに部品が収まらないからといって寝かせたり立てたりしない。
    """
    from gen_case import TILT_DEG
    assert TILT_DEG == 7.3


def test_front_edge_height():
    """Tom's Hardware の実測 17mm と別レビューの約18mm の中間。手首が当たる。"""
    from gen_case import PLATE_TOP_FRONT
    assert PLATE_TOP_FRONT == 17.5


def test_keytop_heights_match_the_real_machine():
    """各列のキートップ高さ（机上面から）。

    公称全高 40mm と各列のキャップ高さから導いた値で、
    cap_lift の不確かさに依存しない。ホーム段 31.6mm が最重要。
    """
    from reference_hhkb import solve
    got = [round(z, 1) for z in solve(4.0).rows_cap_top_z]
    assert got == [26.7, 29.2, 31.6, 35.6, 40.0]


def test_tilt_steps_are_0_3_6_deg():
    """実機は 0/3/6° の3段階。**達成できる角度**で判定する。

    当初 TILT_STEPS == [3.0, 6.0]（0° は脚なし）と書いていたが、脚を後ろの隅へ
    移し「0° 用の短い脚も差す」方式に変えたため [0.0, 3.0, 6.0] になった。
    段数も角度も変わっていないので、実装の表現ではなく意味を検査する。
    """
    from gen_case import TILT_STEPS
    assert set(TILT_STEPS) | {0.0} == {0.0, 3.0, 6.0}, "0/3/6° の3段階から外れた"


# --------------------------------------------------------------------------
# 配列（HHKB そのもの）
# --------------------------------------------------------------------------

def test_split_keeps_61_keys():
    """原機 60 キー ＋ 分割で増えるスペース 1 つ。増やさない。"""
    assert len(load_layout(SPLIT)) == 61


def test_split_halves_are_27_and_34():
    left, right = split_halves(load_layout(SPLIT))
    assert (len(left), len(right)) == (27, 34)


def test_rows_are_15u_and_stagger_is_preserved():
    """行ずれは HHKB と同一。格子配列にしない。"""
    keys = load_layout(ORIGINAL)
    for row in range(4):
        assert sum(k.w_u for k in keys if k.row == row) == pytest.approx(15.0)
    left, right = split_halves(load_layout(SPLIT))
    base = min(k.left_u for k in right if k.row == 0)
    for row, expect in enumerate([0.0, 0.5, 0.75, 1.25]):
        got = min(k.left_u for k in right if k.row == row) - base
        assert got == pytest.approx(expect)


def test_bottom_row_is_the_real_hhkb_arrangement():
    """外側 1u / スペース寄り 1.5u。左右の余白は 1.5u と 2.5u で非対称。"""
    bottom = sorted((k for k in load_layout(ORIGINAL) if k.row == 4),
                    key=lambda k: k.left_u)
    assert [k.w_u for k in bottom] == [1.0, 1.5, 6.0, 1.5, 1.0]
    assert min(k.left_u for k in bottom) == pytest.approx(1.5)
    assert max(k.right_u for k in bottom) == pytest.approx(12.5)


def test_both_spaces_are_3u():
    """6u を 3u+3u に割る。左右とも Space。"""
    spaces = [k for k in load_layout(SPLIT) if k.w_u == pytest.approx(3.0)]
    assert len(spaces) == 2


def test_key_field_depth_is_5u():
    """5 段。段を減らしたり足したりしない。"""
    _, y0, _, y1 = bounds_mm(load_layout(SPLIT))
    assert (y1 - y0) == pytest.approx(5 * UNIT)


# --------------------------------------------------------------------------
# 電源（実機と同じ思想）
# --------------------------------------------------------------------------

def test_power_is_two_aa_cells():
    """単3×2。リポに逃げない。"""
    from gen_case import AA_D, AA_L
    assert (AA_D, AA_L) == (14.5, 50.5)
