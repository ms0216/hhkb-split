"""上ケース方式の寸法が閉じていることを守る。

**この寸法は 4 つの制約が同時に成立する狭い帯にしかない。**
どれか一つを動かすと黙って崩れるので、関係を式のまま検査する。

決定の経緯は docs/hardware/decisions/2026-08-07-top-case.md。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from interface import (  # noqa: E402
    BEZEL_OPENING_GAP, BEZEL_WALL, M2_BOSS_D, M2_CLEAR_D, MOUNT_Y,
    PLATE_MARGIN_X, PLATE_MARGIN_Y,
)

U, CAP, KEYS_HALF_H = 19.05, 18.0, 47.625
M2_HEAD_D = 3.8

CASE_HALF = KEYS_HALF_H + PLATE_MARGIN_Y
PLATE_HALF = CASE_HALF - BEZEL_WALL
BEZEL_IN = KEYS_HALF_H + BEZEL_OPENING_GAP
CAP_EDGE = KEYS_HALF_H - (U - CAP) / 2


def _axes():
    """左右（X）と前後（Y）の両方を返す。

    **効くのは余白の小さい左右（4.125mm）の方。** 最初この検査を前後
    （6.375mm）だけで書いており、壁を 2.4mm にしても通ってしまった
    （＝実際に効く軸を見ていなかった）。負のテストで発覚した。
    """
    from gen_plate import halves
    from layout import Key  # noqa: F401
    keys = halves()["left"]
    half_w = (max(k.x_mm + k.w_u * U / 2 for k in keys)
              - min(k.x_mm - k.w_u * U / 2 for k in keys)) / 2
    return [
        ("左右", half_w, PLATE_MARGIN_X),
        ("前後", KEYS_HALF_H, PLATE_MARGIN_Y),
    ]


def test_the_bezel_overlaps_the_plate_enough_to_hold_it():
    """ベゼルがプレートの縁に十分かぶること。**左右と前後の両方**で見る。"""
    for name, keys_half, margin in _axes():
        overlap = (keys_half + margin - BEZEL_WALL) - (keys_half + BEZEL_OPENING_GAP)
        assert overlap >= 1.0, \
            f"{name}: ベゼルとプレートの重なりが {overlap:.2f}mm しかない"


def test_the_bezel_opening_clears_the_keycaps():
    """開口がキーキャップに当たらないこと。**左右と前後の両方**で見る。"""
    for name, keys_half, _ in _axes():
        gap = (keys_half + BEZEL_OPENING_GAP) - (keys_half - (U - CAP) / 2)
        assert gap >= 1.5, f"{name}: 開口とキャップの隙間が {gap:.2f}mm しかない"


def test_the_screw_head_fits_inside_the_bezel():
    """ネジ頭がベゼルの幅に収まること。

    はみ出すと開口に掛かるか、ケースの外へ出る。
    """
    lo, hi = MOUNT_Y - M2_HEAD_D / 2, MOUNT_Y + M2_HEAD_D / 2
    assert BEZEL_IN <= lo, f"ネジ頭が開口に掛かる（{lo:.2f} < {BEZEL_IN:.3f}）"
    assert hi <= CASE_HALF, f"ネジ頭がケースの外へ出る（{hi:.2f} > {CASE_HALF:.2f}）"


def test_a_screwdriver_reaches_the_screw():
    """キーキャップを外さずにドライバーが入ること。

    **これが今回の作り直しの主目的。** 以前は 14 本中 9 本がキャップの下にあり、
    開けるのに 5〜9 個のキャップを外す必要があった。
    """
    clear = (MOUNT_Y - M2_HEAD_D / 2) - CAP_EDGE
    assert clear >= 2.0, f"キャップからネジ頭まで {clear:.2f}mm しかない"


def test_the_pcb_needs_no_notch():
    """基板がボスに当たらないこと。

    基板は JLCPCB へ出すので、加工が要らない形に収めておきたい。
    """
    # **基板の実寸から取る。** 以前ここを CASE_HALF - PCB_INSET - 2.0 と
    # 適当な式で書いており、実際の 51.0 ではなく 49.0 として通っていた
    # （＝基板が 2mm 重なるのに合格していた）。
    from interface import PCB_INSET_Y
    pcb_half = (KEYS_HALF_H + PLATE_MARGIN_Y) - PCB_INSET_Y
    boss_inner = MOUNT_Y - M2_BOSS_D / 2
    assert pcb_half <= boss_inner + 1e-9, \
        f"基板の縁 {pcb_half:.2f} がボスの内端 {boss_inner:.2f} に掛かる"


def test_the_plate_notch_is_expected():
    """プレートには切り欠きが要る、という前提を明示しておく。

    穴で済むと思い込んで実装すると、縁が 0.2mm しか残らず割れる。
    """
    assert MOUNT_Y + M2_CLEAR_D / 2 > PLATE_HALF - 0.8, \
        "プレートは穴で済む。切り欠きの実装を外してよい"


def test_no_screw_sits_on_the_left_or_right_edge():
    """左右の辺にはネジを置けないこと（余白 4.125mm）。

    置けるようになったら、この確認を見直す合図。
    """
    usable = PLATE_MARGIN_X - 2.4                  # 壁を引いた残り
    assert usable < M2_BOSS_D / 2 + 1.0, \
        f"左右の辺にボスが入る（{usable:.2f}mm）。配置を見直せる"
