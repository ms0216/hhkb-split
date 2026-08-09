"""部品を組み上げた状態を作り、干渉と嵌合を検査する。

個々の部品が正しくても、組み合わせて初めて分かる不具合がある。
プレートは打鍵面と同じ 7.3° に傾けてケースのリムに載るので、
平面図で見た奥行はケースの外形より短くなる。この種のずれは
部品を単体で見ていても気づけない。

いま実寸が確定していて検査できる組み合わせ:
    ケース ／ プレート ／ 電池蓋 ／ チルト脚 ／ 単3電池

まだ検査できないもの（実寸が無いため）:
    スイッチ ／ キーキャップ ／ 基板とソケット
    → 実測値が入った時点で PARTS に足せば、同じ枠組みで検査できる。
"""

import sys
from math import radians, tan
from pathlib import Path

from build123d import Align, Box, BuildPart, Location, Locations

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_case import (  # noqa: E402
    AA_D, AA_L, BATT_MARGIN_REAR, BATT_W, CLEARANCE, FLOOR, FOOT_PEG_H,
    LID_STOP, LID_T, PLATE_TOP_FRONT, RAIL_H, TILT_DEG, WALL, _foot_positions,
    _lid_opening, battery_center, battery_x_center, build_battery_lid, build_case,
    build_tilt_foot, case_heights,
)
from gen_plate import build_plate, halves, plate_positions  # noqa: E402
from envelopes import (  # noqa: E402
    battery_envelope, daughterboard_envelope, pcb_bottom_at, pcb_envelope,
    place_pcb, xiao_overhang_envelope,
)
from interface import PLATE_T  # noqa: E402


def plate_placement(w, h):
    """プレートをリム面に載せる位置。

    プレートは XY 平面上に平らに作られている。X 軸まわりに TILT_DEG 回すと
    底面が z = y·tan(TILT) の平面になるので、リム面の中央高さだけ持ち上げる。
    """
    rim_front = PLATE_TOP_FRONT - PLATE_T
    mid_z = rim_front + (h / 2) * tan(radians(TILT_DEG))
    return Location((0, 0, mid_z), (TILT_DEG, 0, 0))


def build_assembly(keys, half):
    """組み上げた各部品を、名前つきで返す。

    奥行には 2 種類あるので取り違えないこと。
      h_plate — 平らなプレートの奥行（103.25mm）
      h_case  — それを傾けた平面図での奥行（102.41mm）。ケースの外形はこちら。
    ケース側の造作（蓋の開口・チルト脚・電池室）は必ず h_case で計算する。
    当初 h_plate を渡しており、蓋が 0.42mm ずれてケースに食い込んだ。
    """
    _, (w, h_plate) = plate_positions(keys)
    case, (_, h_case), _ = build_case(keys, half)
    plate, _, _ = build_plate(keys, half)
    lid, (lw, lh) = build_battery_lid(half, keys)

    parts = {"case": case, "plate": plate_placement(w, h_plate) * plate}

    # まだ設計していない基板の占有空間。単体では見えない衝突を捕まえるため、
    # 検査には常に含める（電池を基板の真下に置いて 4,000mm^3 衝突させた反省）。
    rim_front = PLATE_TOP_FRONT - PLATE_T
    parts["pcb"] = place_pcb(pcb_envelope(w, h_plate, half, keys), h_plate, rim_front)

    # 電池蓋はレールの段に載る。開口の中心へ、レールの高さに置く。
    ox, oy, _, oh = _lid_opening(half, w, h_case)
    # 蓋の手前端はストッパーの奥に来る
    y_lid = oy - oh / 2 + LID_STOP + CLEARANCE + lh / 2
    parts["lid"] = Location((ox, y_lid, FLOOR - RAIL_H)) * lid

    # チルト脚は底面のピン穴に差す（ピンが上、脚が下）。
    for i, (fx, fy) in enumerate(_foot_positions(w, h_case)):
        foot, fz = build_tilt_foot(3.0, h_case)
        parts[f"foot{i}"] = Location((fx, fy, -fz), (180, 0, 0)) * foot

    # 単3電池 2 本（電極と配線の余裕を含めた占有空間として扱う）
    parts["batt"] = battery_envelope((battery_x_center(half, w),
                                      battery_center(h_case), FLOOR + AA_D / 2))

    # 子基板。**取付ボスの上に載る位置**に置く。ケース側の造作と同じ
    # 関数から座標を取るので、片方だけ動かしてもずれない。
    from gen_case import (BUMP_DEPTH, DB_BOSS_H, DB_D, DB_FROM_REAR, DB_T, DB_W,
                          WALL, daughterboard_x_center)
    db_x = daughterboard_x_center(half, w)
    db_rear = h_case / 2 + BUMP_DEPTH - WALL - DB_FROM_REAR
    parts["db"] = daughterboard_envelope(
        (db_x, db_rear - DB_D / 2, FLOOR + DB_BOSS_H), DB_W, DB_D, DB_T)
    # **子基板の外形からはみ出した XIAO の端**（open-gaps #28）。
    # 壁のポケットが足りているかは、これを置かないと検査できない。
    parts["xiao"] = xiao_overhang_envelope(db_x, db_rear, FLOOR + DB_BOSS_H + DB_T)

    # 上ケース（ベゼル）。プレートを押さえ、手前端を実機の 17mm にする。
    from gen_case import build_topcase
    parts["topcase"] = build_topcase(keys, half)[0]

    return parts, (w, h_case)


def check(keys, half, label=""):
    """組み立て状態を検査し、問題の一覧を返す。"""
    from verify import intersection_volume

    parts, (w, h_case) = build_assembly(keys, half)
    problems, notes = [], []

    # 1. 干渉。**設計上の接触**は許し、食い込みは許さない。
    #
    #    面どうしが接すると、ブーリアン演算とテッセレーションの誤差で
    #    わずかな重なりとして出る。支え合う関係にある組は許容量を広げる。
    #    許容を広げるのは「接触が設計意図である」と言える組だけにする。
    CONTACT = {
        frozenset({"case", "pcb"}): 30.0,    # 基板はネジボスの上に載る
        frozenset({"case", "plate"}): 30.0,  # プレートはリムに載る
        frozenset({"case", "lid"}): 30.0,    # 蓋はレールの段に載る
        frozenset({"case", "topcase"}): 30.0,   # 上ケースは下ケースの壁に載る
        frozenset({"plate", "topcase"}): 30.0,  # 上ケースはプレートを押さえる
        frozenset({"pcb", "batt"}): 30.0,    # 電池は基板の下面に触れうる
    }
    names = list(parts)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            v = intersection_volume(parts[a], parts[b])
            limit = CONTACT.get(frozenset({a, b}), 1.0)
            if v > limit:
                kind = "接触の域を超えて" if limit > 1.0 else ""
                problems.append(f"{a} と {b} が {kind}{v:.1f}mm^3 食い込んでいる")

    # 2. プレートがケースのリムを覆えているか。
    #    計算値ではなく、置いた後の実際の外形で比べる。
    case_bb = parts["case"].bounding_box()
    plate_bb = parts["plate"].bounding_box()
    # ケースはコブぶん長いので、プレートが覆うべきは**本体部分**だけ。
    gap_y = h_case - plate_bb.size.Y
    gap_x = case_bb.size.X - plate_bb.size.X
    notes.append(f"ケース全体 {case_bb.size.X:.2f}x{case_bb.size.Y:.2f} "
                 f"(本体 {h_case:.2f} + コブ) / "
                 f"プレート(傾斜後) {plate_bb.size.X:.2f}x{plate_bb.size.Y:.2f}mm")
    # **覆うのはプレートと上ケースの合計。** プレート単体はベゼルの壁ぶん
    # 小さくてよい（上ケース方式にした時点でそうなった）。
    from gen_case import BEZEL_WALL
    for axis, gap in (("X", gap_x), ("Y", gap_y)):
        if gap - BEZEL_WALL * 2 > 0.3:
            problems.append(f"プレートと上ケースの合計が {axis} 方向に "
                            f"{gap - BEZEL_WALL * 2:.2f}mm 足りない")
        if gap < -0.3:
            problems.append(f"プレートが {axis} 方向に {-gap:.2f}mm はみ出す")

    # 3. 蓋がレールに載っているか
    ox, oy, ow, oh = _lid_opening(half, w, h_case)
    _, (lw, lh) = build_battery_lid(half, keys)
    notes.append(f"電池蓋 {lw:.1f}x{lh:.1f} / 開口 {ow:.1f}x{oh:.1f}mm")

    return problems, notes, parts


def main():
    ok = True
    for name, keys in halves().items():
        problems, notes, parts = check(keys, name, name)
        print(f"{'OK ' if not problems else 'NG '}{name}  部品 {len(parts)} 個")
        for n in notes:
            print(f"      {n}")
        for p in problems:
            print(f"   !! {p}")
        ok &= not problems
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
