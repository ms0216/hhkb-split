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
    """開口がキーキャップに当たらないこと。**左右と前後の両方**で見る。

    下限 1.0mm の出所は**実機の実測**（2026-08-24・利用者）: 実機の
    キャップ↔ベゼルの見える隙間は 1.0〜1.5mm。以前の下限 1.5 は
    実機より広い側に置いた保守値で、#51（A1 mini の幅詰め・候補 3）で
    開口の隙間を 0.9 に詰めたとき、見える隙間 1.225mm が実機の範囲に
    収まることを確認して下限を実機の下限に合わせた。
    """
    for name, keys_half, _ in _axes():
        gap = (keys_half + BEZEL_OPENING_GAP) - (keys_half - (U - CAP) / 2)
        assert gap >= 1.0, f"{name}: 開口とキャップの隙間が {gap:.2f}mm しかない"


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
    # 2026-09-05: 2.0 → 1.8。ネジを 0.64 内へ寄せた（インサートの外側の肉
    # 0.46 → 1.05）。ドライバーの軸はネジ頭（φ3.8）より細いので、頭の縁と
    # キャップの縁の距離がそのまま軸の余裕になる
    assert clear >= 1.8, f"キャップからネジ頭まで {clear:.2f}mm しかない"


def test_the_pcb_needs_no_notch():
    """基板がボスに当たらないこと。

    基板は JLCPCB へ出すので、加工が要らない形に収めておきたい。
    """
    # **基板の実寸から取る。** 以前ここを CASE_HALF - PCB_INSET - 2.0 と
    # 適当な式で書いており、実際の 51.0 ではなく 49.0 として通っていた
    # （＝基板が 2mm 重なるのに合格していた）。
    from interface import (CLEARANCE, FRONT_BOSS_WALL_IN, M2_INSERT_D,
                           PCB_FRONT_EDGE_PLAN)
    pcb_half = PCB_FRONT_EDGE_PLAN                    # 平面図（傾けた後）の縁
    # ボスは角柱で、内端は基板の縁 + CLEARANCE に置く（gen_case）。ここで見るのは
    # **インサートの内側の肉**が FRONT_BOSS_WALL_IN 残ること
    insert_inner = MOUNT_Y - M2_INSERT_D / 2
    boss_inner = pcb_half + CLEARANCE
    assert insert_inner - boss_inner >= FRONT_BOSS_WALL_IN - 1e-9, \
        f"インサートの内側の肉が {insert_inner - boss_inner:.2f}mm（要 {FRONT_BOSS_WALL_IN}）"
    from math import cos, radians
    from interface import TILT_DEG
    case_half_plan = CASE_HALF * cos(radians(TILT_DEG))   # 平面図の外面
    assert case_half_plan - (MOUNT_Y + M2_INSERT_D / 2) >= 1.0, \
        f"インサートの外側の肉が {case_half_plan - (MOUNT_Y + M2_INSERT_D / 2):.2f}mm しかない"


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
