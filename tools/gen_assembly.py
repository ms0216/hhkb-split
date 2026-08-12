"""部品を組み上げた状態を作り、干渉と嵌合を検査する。

個々の部品が正しくても、組み合わせて初めて分かる不具合がある。
プレートは打鍵面と同じ 7.3° に傾けてケースのリムに載るので、
平面図で見た奥行はケースの外形より短くなる。この種のずれは
部品を単体で見ていても気づけない。

**「製品として存在する物」は全部ここに置く**（open-gaps #29）。
#28（USB が挿さらない）は寸法の間違いではなく、**利用者が挿すケーブルが
モデルに 1 つも入っていなかった**ことが原因だった。検査対象に入って
いない部品は、検査していないのと同じ。

入っている物と、あえて入れない物の一覧は open-gaps #29 の表。
寸法が未確定の物も [暫定] で入れる（provisional-values.md に載せる）。
"""

import sys
from math import radians, tan
from pathlib import Path

from build123d import Align, Box, BuildPart, Location, Locations

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_case import (  # noqa: E402
    BATT_MARGIN_REAR, BATT_W, CLEARANCE, FLOOR, FOOT_PEG_H,
    battery_center_z,
    LID_STOP, LID_T, PLATE_TOP_FRONT, RAIL_H, TILT_DEG, WALL, _foot_positions,
    _lid_opening, battery_center, battery_x_center, build_battery_lid, build_case,
    build_tilt_foot, case_heights,
)
from gen_plate import build_plate, halves, plate_positions  # noqa: E402
from envelopes import (  # noqa: E402
    battery_envelope, daughterboard_envelope, pcb_envelope,
    place_pcb, xiao_overhang_envelope,
)
from interface import PLATE_T  # noqa: E402


# **予約の箱 × その箱が予約している実物**の組。包んでいる（または嵌合で
# 入り込む）のが当たり前なので、干渉としては見ない（#31 案 A・利用者の
# 決定 2026-08-11）。干渉検査は 1 パスで 2 つの質問に答える:
#   1. **実物どうしがぶつからないか**（実形状）
#   2. **予約が守られているか**（条件 1・2 の箱 × ケース等）
# 箱は実形状の劣化版ではなく、2 の質問に答える道具。
#
# **見ない組には、代わりの「箱 ⊇ 実物」の検査を必ず置く**——除外は
# 「見ない」宣言であり、代わりが効いていなければ穴を開けたのと同じ:
#   sockets × pcb_real       … test_the_socket_box_contains_the_third_party_model
#   stabs   × pcb_real       … test_the_stab_box_contains_the_third_party_model
#   db      × db_real        … test_the_db_reservation_contains_the_real_parts
#   xiao    × db_real        … 同上（xiao の箱の寸法自体が記録から作られている）
#   sockets × switches_real  … ピンが予約帯に入る嵌合。
#                              test_the_switch_boxes_match_the_real_switch
#                              （ピン ⊆ 基板の穴）が縛る
# 実測（2026-08-11・右側）: この 5 組以外に、箱と real の重なりは無い
# （ケース・プレート・上ケースとの想定外の重なり 0）。
RESERVATION_CONTAINS = {("sockets", "pcb_real"), ("stabs", "pcb_real"),
                        ("db", "db_real"), ("xiao", "db_real"),
                        ("sockets", "switches_real")}


# **部品ごとに「何で留まっているか」**（2026-08-12・利用者の
# 「固定が弱いところは無いか」から）。
#
# **干渉検査は「ぶつからないこと」しか見ない。**組み上げた瞬間に成立して
# いても、**持ち上げた・裏返した・打鍵した**ときに落ちる／浮くものは
# 別の話で、そこを見る仕組みが無かった。実際に 2 つ見つかった:
#   - 電池蓋が外から開かない（#35）
#   - テンティング用ナットが落ちる（逃げ 0.30mm・ポケットは底面に開放）
#
# ここに書いていない部品を組み立てに足すと `test_every_part_declares_how_it_is_held`
# が落ちる。**「留め方が書かれていない部品は、留まっていないのと同じ。」**
# ⚠️ は「まだ弱い／未解決」。潰したら本文ごと直す。
# 実形状か箱かの一覧は part_kinds.py にある（Blender 側とも共用）。
from part_kinds import BOX_SHAPE, REAL_SHAPE  # noqa: F401,E402

HELD_BY = {
    "case":       "外殻そのもの（基準）",
    "topcase":    "手前 M2×3（熱圧入インサート）。⚠️ 奥は未解決（#12）",
    "plate":      "上ケースとリムで挟む＋手前 M2×3。⚠️ 奥は未解決（#12）",
    "pcb":        "⚠️ 固定具なし。スイッチのピン 54 本の摩擦のみ（#36 で対応中）",
    "pcb_real":   "同上",
    "pcb_parts":  "基板に半田付け",
    "sockets":    "基板に半田付け",
    "stabs":      "プレートとスタビの爪",
    "switches":   "プレートの爪（スナップフィット）",
    "switches_real": "プレートの爪（スナップフィット）",
    "keycaps":    "スイッチのステムへの圧入",
    "db":         "M2×2（手前）＋奥の壁のポケットが上・後・左右を押さえる",
    "db_real":    "同上",
    "db_parts":   "子基板に半田付け",
    "xiao":       "ソケットへの挿入＋壁のポケット（プロトタイプ期。#27）",
    "batt":       "⚠️ 仕切り壁・側壁・蓋・基板で囲うだけ。#35 と一緒に決める",
    "lid":        "⚠️ レール＋手前ストッパー。**外から開かない**（#35）",
    "ffc":        "コネクタのラッチ＋たるみ 25mm",
    "sw_pwr":     "上から落とし込む溝。奥のリブが押し込み側を剛体で止める（#18）",
    "screws":     "ねじ込み",
    "inserts":    "熱圧入",
    "nut":        "ポケットの入口の唇で噛む（2026-08-12 に追加）",
    "rubber":     "座ぐり＋粘着",
    "foot":       "φ4×2.4mm のピン圧入 ＋ 先端の返しφ4.4／穴の奥の溝φ4.7（2026-08-12）",
    "usb_plug":   "利用者が挿すケーブル（留めるものではない）",
    "rear_lid":   "座ぐりに沈み、下は床の溝・上は壁の内面に爪が掛かる（#35・2026-08-12）",
}


def plate_placement(w, h):
    """プレートをリム面に載せる位置。

    プレートは XY 平面上に平らに作られている。X 軸まわりに TILT_DEG 回すと
    底面が z = y·tan(TILT) の平面になるので、リム面の中央高さだけ持ち上げる。
    """
    rim_front = PLATE_TOP_FRONT - PLATE_T
    mid_z = rim_front + (h / 2) * tan(radians(TILT_DEG))
    return Location((0, 0, mid_z), (TILT_DEG, 0, 0))


def build_assembly(keys, half, real=False):
    """組み上げた各部品を、名前つきで返す。

    奥行には 2 種類あるので取り違えないこと。
      h_plate — 平らなプレートの奥行（103.25mm）
      h_case  — それを傾けた平面図での奥行（102.41mm）。ケースの外形はこちら。
    ケース側の造作（蓋の開口・チルト脚・電池室）は必ず h_case で計算する。
    当初 h_plate を渡しており、蓋が 0.42mm ずれてケースに食い込んだ。
    """
    positions, (w, h_plate) = plate_positions(keys)
    case, (_, h_case), _ = build_case(keys, half)
    plate, _, _ = build_plate(keys, half)
    lid, (lw, lh) = build_battery_lid(half, keys)

    parts = {"case": case, "plate": plate_placement(w, h_plate) * plate}

    # まだ設計していない基板の占有空間。単体では見えない衝突を捕まえるため、
    # 検査には常に含める（電池を基板の真下に置いて 4,000mm^3 衝突させた反省）。
    rim_front = PLATE_TOP_FRONT - PLATE_T
    parts["pcb"] = place_pcb(pcb_envelope(w, h_plate, half, keys), h_plate, rim_front)
    # Kailh ホットスワップソケット。KiCad に 3D モデルが無く STEP に出ない
    # 実物なので、保守的な箱として別部品で置く（open-gaps #29）
    from envelopes import socket_envelope
    parts["sockets"] = place_pcb(socket_envelope(half), h_plate, rim_front)

    # 電池蓋はレールの段に載る。開口の中心へ、レールの高さに置く。
    ox, oy, _, oh = _lid_opening(half, w, h_case)
    # 蓋の手前端はストッパーの奥に来る
    y_lid = oy - oh / 2 + LID_STOP + CLEARANCE + lh / 2
    parts["lid"] = Location((ox, y_lid, FLOOR - RAIL_H)) * lid

    # コブの奥面の電池蓋（open-gaps #35）。**座ぐりに沈めて面一に置く。**
    # 蓋は XY 平面で作ってあるので、奥面（XZ 平面）へ立てる。
    from gen_case import (BUMP_DEPTH as _BD, REAR_LID_T, battery_center_z,
                          build_rear_battery_lid)
    from gen_case import rear_lid_rebate
    # **ケース座標で作ってあるので動かさない**（回すと上下が入れ替わり、
    # 同じ取り違えを 5 回繰り返した。2026-08-12）。
    parts["rear_lid"] = build_rear_battery_lid(half, keys)[0]

    # チルト脚は底面のピン穴に差す（ピンが上、脚が下）。
    for i, (fx, fy) in enumerate(_foot_positions(w, h_case)):
        foot, fz = build_tilt_foot(3.0, h_case)
        parts[f"foot{i}"] = Location((fx, fy, -fz), (180, 0, 0)) * foot

    # 電池ボックス BH-325-1A150（単3×2・たて一列）。高さの基準は
    # gen_case.battery_center_z() だけ。ここで足し引きしない。
    parts["batt"] = battery_envelope((battery_x_center(half, w),
                                      battery_center(h_case),
                                      battery_center_z()))

    # 子基板。**取付ボスの上に載る位置**に置く。ケース側の造作と同じ
    # 関数から座標を取るので、片方だけ動かしてもずれない。
    from gen_case import (BUMP_DEPTH, DB_BOSS_H, DB_BOSS_POS as DB_BOSS_POS_,
                          DB_FROM_REAR, DB_T,
                          WALL, daughterboard_x_center)
    from gen_case import _RECEPT          # メスの実寸（幅・高さ・張り出し・中心高さ）
    # 箱の xy は**実物の記録**から（#31 の「先にやること 2」）。設計定数
    # DB_W/DB_D は基板・ケースの生成側の入力として残る。今日は両者が一致
    # しているが、ずれた日に検査が見るべきは実物の側。鮮度は
    # test_the_recorded_step_data_* が見張っている。
    import pcb_parts
    _dbb = pcb_parts.load()["db"]["board_bbox"]
    db_w, db_d = _dbb[3] - _dbb[0], _dbb[4] - _dbb[1]
    db_x = daughterboard_x_center(half, w)
    db_rear = h_case / 2 + BUMP_DEPTH - WALL - DB_FROM_REAR
    parts["db"] = daughterboard_envelope(
        (db_x, db_rear - db_d / 2, FLOOR + DB_BOSS_H), db_w, db_d, DB_T,
        holes=[(db_x + hx, db_rear - db_d / 2 + hy) for hx, hy in DB_BOSS_POS_],
        usb=(db_x, db_rear + _RECEPT[2]))
    # **子基板の外形からはみ出した XIAO の端**（open-gaps #28）。
    # 壁のポケットが足りているかは、これを置かないと検査できない。
    # **メスの面は XIAO の基板の端ではない**（その先に 1.25mm ある）。
    parts["xiao"] = xiao_overhang_envelope(db_x, db_rear, FLOOR + DB_BOSS_H + DB_T,
                                           usb_x=db_x,
                                           usb_face=db_rear + _RECEPT[2])

    # 上ケース（ベゼル）。プレートを押さえ、手前端を実機の 17mm にする。
    from gen_case import build_topcase
    parts["topcase"] = build_topcase(keys, half)[0]

    # ----------------------------------------------------------------------
    # ここから下は open-gaps #29 で足した「製品として存在する実物」。
    # 足せない物と、その理由は #29 の表にある。**黙って外さない。**
    # ----------------------------------------------------------------------
    import pcb_parts
    from math import cos
    from build123d import (BuildSketch, Cylinder, Mode, Plane, RegularPolygon,
                           extrude)
    from envelopes import (FFC_RIBBON_W, NUT_QUARTER_AF, NUT_QUARTER_T,
                           PCB_T, PLATE_TO_PCB,
                           SCREW_HEAD_D, SCREW_HEAD_H, SCREW_SHAFT_D,
                           SCREW_L_DB, SCREW_L_MAIN,
                           SW_PWR_BODY_D, SW_PWR_D, SW_PWR_H, SW_PWR_KNOB,
                           SW_PWR_KNOB_W, SW_PWR_LEAD_D, SW_PWR_PIN_W,
                           SW_PWR_TRAVEL, SW_PWR_W, M2_INSERT_L,
                           key_stack_envelopes, stab_reservation,
                           usb_plug_envelope)
    import envelopes
    from gen_case import (BEZEL_TOP_FRONT, CAP_LIFT, DB_BOSS_POS, cap_height,
                          _boss_positions, _rubber_positions,
                          power_switch_center_z, power_switch_x_center,
                          usb_center_z)
    from interface import M2_INSERT_D

    tilt = tan(radians(TILT_DEG))
    pl = plate_placement(w, h_plate)
    db_center_y = db_rear - db_d / 2

    # 本体基板の実装部品（KiCad の STEP から数えて記録した bbox。pcb_parts.py）
    parts["pcb_parts"] = place_pcb(pcb_parts.build_envelope(half),
                                   h_plate, rim_front)

    # 子基板の裏面の部品（FFC コネクタ J_MAIN とコンデンサ）。
    # db の占有空間は板の**上**（XIAO の積み上げ）しか持っていないので、
    # 裏へ出るコネクタ 2.1mm は別に置かないと検査されない。
    # **裏面（z0 < 0）だけ。**上面の XIAO のモデル（84 立体）は `db` と
    # `xiao` の占有空間が受け持つ（実形状の視覚確認は {half}_db_real.stl）。
    with BuildPart() as _dbp:
        for x0, y0, z0, x1, y1, z1 in pcb_parts.component_boxes("db"):
            if z0 >= -0.05:
                continue
            with Locations((db_x + (x0 + x1) / 2, db_center_y + (y0 + y1) / 2,
                            FLOOR + DB_BOSS_H + z0)):
                Box(x1 - x0, y1 - y0, z1 - z0,
                    align=(Align.CENTER, Align.CENTER, Align.MIN))
    parts["db_parts"] = _dbp.part

    # キースイッチ（61）・キーキャップ（61）・スタビライザ
    from interface import PLATE_T as _plate_t
    # **キャップの高さは段ごとに違う**（上 2 段だけ背が高い。#21）。
    # 以前ここが OUR_CAPS["home"] 固定で、混ぜても検査に出なかった。
    sw_env, cap_env = key_stack_envelopes(positions, keys, _plate_t,
                                          CAP_LIFT, cap_height)
    parts["switches"] = pl * sw_env
    parts["keycaps"] = pl * cap_env
    parts["stabs"] = pl * stab_reservation(half)

    # 電源スイッチの実物（受け箱の中の本体＋壁を貫く操作部）
    from gen_case import WALL as _wall
    y_rear_outer = h_case / 2 + BUMP_DEPTH
    y_rear_inner = y_rear_outer - _wall
    sw_x, sw_z = power_switch_x_center(half, w), power_switch_center_z()
    # SS12D01G4-G の実形状（2026-08-12 に品番確定）。
    # **本体・端子・ツマミを分けて置く。**1 個の箱で置くと、端子ぶんの
    # 奥行（5.0mm）まで本体の太さがあることになり、**上から落とし込む
    # 溝の奥のリブと当たる**（そのリブが押し込み側の抜け止めそのもの）。
    with BuildPart() as _sw:
        # 本体（壁の内面に当たる）
        with Locations((sw_x, y_rear_inner - SW_PWR_BODY_D / 2, sw_z)):
            Box(SW_PWR_W, SW_PWR_BODY_D, SW_PWR_H,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # 端子 3 本（2.5mm ピッチで**上下に並ぶ**。本体を縦向きに付けるため）
        for _i in (-1, 0, 1):
            with Locations((sw_x, y_rear_inner - SW_PWR_BODY_D,
                            sw_z + _i * 2.5)):
                Box(SW_PWR_PIN_W, SW_PWR_LEAD_D, 0.3,
                    align=(Align.CENTER, Align.MAX, Align.CENTER))
        # ツマミ。**ストロークぶん掃いた範囲**を置く（動く先も当たっては困る）
        with Locations((sw_x, y_rear_inner, sw_z)):
            Box(SW_PWR_KNOB_W, _wall + (SW_PWR_KNOB - _wall),
                SW_PWR_KNOB_W + SW_PWR_TRAVEL,
                align=(Align.CENTER, Align.MIN, Align.CENTER))
    parts["sw_pwr"] = _sw.part

    # 利用者が挿す USB ケーブルのプラグ（open-gaps #28 の再発防止）。
    # **メス（XIAO の奥端面）から位置を導く。**メスが壁から遠のけば、
    # 樹脂の胴体が壁に食い込む形でここに出る。
    # **基準はメスの実物の面**（KiCad の STEP）。XIAO の基板の端
    # （db_rear + XIAO_OVERHANG）ではない。**その先にコネクタがもう
    # 1.25mm ある**ので、基板の端を使うとプラグはそのぶん深く挿さった
    # ことになり、メスの端子の上に乗る（#28 と同じ形。2026-08-10）。
    parts["usb_plug"] = usb_plug_envelope(db_x, db_rear + _RECEPT[2],
                                          usb_center_z())

    # FFC ケーブル。**経路は未発注・未決定なので、仮置きの占有空間。**
    # J_DB（本体・口は手前向き）から下りて床の上を這い、J_MAIN（子基板の
    # 裏・口は手前向き）へ入る。位置は両方とも STEP の実体から取る。
    rec = pcb_parts.load()
    jdb = [c["bbox"] for c in rec[half]["components"] if c["label"] == "ffc_conn"]
    jx = (min(b[0] for b in jdb) + max(b[3] for b in jdb)) / 2
    from interface import to_plan
    jy = to_plan((jx, min(b[1] for b in jdb)))[1]      # 口（手前端・平面図）
    # **端子も含める。**本体だけ見て経路を決めたら、端子に当たった
    sock_boxes = (pcb_parts.keyswitch_boxes(half, "kailh_socket")
                  + pcb_parts.keyswitch_boxes(half, "kailh_socket_leg"))
    jm = [c["bbox"] for c in rec["db"]["components"] if c["label"] == "ffc_conn"]
    jm_y = db_center_y + min(b[1] for b in jm)         # J_MAIN の口（子基板は水平）
    z_board_bottom = (rim_front + (jy + h_plate / 2) * tilt
                      - PLATE_TO_PCB - PCB_T)
    z_lo = FLOOR + 1.9                                 # 走行部は床の少し上
    hw = FFC_RIBBON_W / 2
    with BuildPart() as _ffc:
        # J_DB の口の前で下へ折り下げる幕。**薄く（1.0mm）**。
        # 口の 1.1mm 手前からソケットの保守的な箱（はんだ余裕込み）が
        # 始まるので、ケーブルは口を出てすぐ折れる必要がある（FFC の
        # 静的な折りなら可能）。
        # 上端は基板の下面の少し手前で止める（平面近似の誤差で板を
        # 突かないため。コネクタの口 −3.6〜−1.6 は覆えている）。
        # **折り下げる場所は、置いたあとのソケットの形から決める。**
        # 帯（キーの列の間）にコネクタがあり、その手前にはすぐ後ろの列の
        # ソケットが来る。**記録の座標（平らなプレート）と組み立ての座標
        # （平面図）を混ぜて計算し、0.2mm ずれて当たった。**置いた部品から
        # 直接測る。
        near = [b for b in (s_.bounding_box() for s_ in parts["sockets"].solids())
                if b.min.X < jx + FFC_RIBBON_W / 2
                and b.max.X > jx - FFC_RIBBON_W / 2 and b.max.Y < jy]
        y_free = max((b.max.Y for b in near), default=jy - 1.0)
        drop_d = jy - y_free
        assert drop_d > 0.3, (
            f"{half}: J_DB の口とソケットの間が {drop_d:.2f}mm しかなく、"
            "FFC を折り下げる場所が無い")
        with Locations((jx, (y_free + jy) / 2, z_lo)):
            Box(FFC_RIBBON_W, drop_d, z_board_bottom - 0.5 - z_lo,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 床の上を左右方向へ走る
        x0, x1 = sorted((jx, db_x))
        with Locations(((x0 + x1) / 2, jy - 2.0, z_lo)):
            Box(x1 - x0 + FFC_RIBBON_W, 4.0, 1.8,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 奥へ走って J_MAIN の口の手前まで
        with Locations((db_x, (jy - 4.0 + jm_y) / 2, z_lo)):
            Box(FFC_RIBBON_W, jm_y - (jy - 4.0), 1.8,
                align=(Align.CENTER, Align.CENTER, Align.MIN))
        # **差込口ぴったりで止める。**中まで描くと、塞がった箱に食い込む
        # ことになり、許容値でごまかす羽目になる（上の走行部の終端が
        # そのまま J_MAIN の口の面）。**届くかどうか**はケーブルの長さの
        # 検査（test_pcb の FFC 長）が別に見る。
    parts["ffc"] = _ffc.part

    # M2 熱圧入インサート（本体ボス 3＋子基板ボス 2）。
    # **本体ボスの頭は 7.3° の傾斜面で切られている**ので、水平な上面の
    # 円柱を面の中心高さに置くと、後ろ半分が r·tan(7.3°)=0.21mm 突き出て
    # 上ケース・プレートに 0.19mm 食い込む（隙間レポートで発覚。体積が
    # 0.8mm^3 で検査の閾値 1.0 の下に潜っていた）。実物は面より下へ押し
    # 込むので、傾斜の振れぶん 0.25mm 沈めて置く。
    # **筒として描く。**中身の詰まった棒にすると、通したネジが必ず
    # 「食い込んでいる」ことになり、許容値でごまかす羽目になる。
    # 穴の径はネジの軸と同じにする（実物はここがネジ山で噛み合う）。
    with BuildPart() as _ins:
        seats = [(bx, by, rim_front + (by + h_case / 2) * tilt - 0.25)
                 for bx, by in _boss_positions(half)]
        seats += [(db_x + dx_, db_center_y + dy_, FLOOR + DB_BOSS_H)
                  for dx_, dy_ in DB_BOSS_POS]
        for x_, y_, z_ in seats:
            with Locations((x_, y_, z_)):
                Cylinder(M2_INSERT_D / 2, M2_INSERT_L,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
        for x_, y_, z_ in seats:
            with Locations((x_, y_, z_)):
                Cylinder(SCREW_SHAFT_D / 2, M2_INSERT_L, mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
    parts["inserts"] = _ins.part

    # M2 ネジ（上ケースの 3 本＋子基板の 2 本）。
    # 上ケースの頭は座ぐり（ベゼル上面 −0.4 の深さ）に沈む。
    with BuildPart() as _scr:
        for bx, by in _boss_positions(half):
            zt = (BEZEL_TOP_FRONT + (by + h_case / 2) * tilt
                  - SCREW_HEAD_H - 0.4)
            with Locations((bx, by, zt)):
                Cylinder(SCREW_HEAD_D / 2, SCREW_HEAD_H,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
                Cylinder(SCREW_SHAFT_D / 2, SCREW_L_MAIN,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
        for dx_, dy_ in DB_BOSS_POS:
            with Locations((db_x + dx_, db_center_y + dy_,
                            FLOOR + DB_BOSS_H + DB_T)):
                Cylinder(SCREW_HEAD_D / 2, SCREW_HEAD_H,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
                Cylinder(SCREW_SHAFT_D / 2, SCREW_L_DB,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
        # 本体基板をプレートの柱へ締める M2（open-gaps #36・2026-08-12）。
        # **下から入れる。**頭は基板の裏、軸は板を貫いて柱へ入る。
        # **穴と柱だけ作ってネジを置かないと、検査対象に入らない**
        # （#29 の原則。利用者の指摘で気づいた）。
        from envelopes import SCREW_L_PCB
        from interface import pcb_mount_positions
        # **プレートと同じ姿勢**（傾いた板に垂直）で置く。pl は上で作った
        # プレートの置き方そのもの。座標を別に計算しない。
        # **柱の中の軸は下穴の径で描く。**タッピングねじは、ねじ山の谷に
        # 樹脂が入り込んで噛む。φ2.0 の丸棒として描くと下穴 φ1.6 と必ず
        # 重なり、**干渉検査から除外する羽目になる**（除外した瞬間、ネジは
        # 検査されない部品に戻る。ナットで学んだ）。**噛み方を描く。**
        from interface import PCB_POST_PILOT_D
        for mx, my in pcb_mount_positions(half):
            with Locations(pl * Location((mx, my, -PLATE_TO_PCB - PCB_T))):
                Cylinder(SCREW_HEAD_D / 2, SCREW_HEAD_H,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
                Cylinder(SCREW_SHAFT_D / 2, PCB_T,      # 基板のバカ穴の中
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
            with Locations(pl * Location((mx, my, -PLATE_TO_PCB))):
                Cylinder(PCB_POST_PILOT_D / 2, SCREW_L_PCB - PCB_T,  # 柱の中
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
    parts["screws"] = _scr.part

    # テンティング用 1/4-20 六角ナット（底面のポケットに埋め込む）。
    #
    # **唇の上に座る**（2026-08-12）。入口の帯 NUT_LIP_H だけ二面幅を
    # 狭めてあり、**押し込んだナットはそこを越えて上に収まる。**
    # だから最終位置は z = NUT_LIP_H から。**押し込む途中の食い込みを
    # 定位置として描かない**——描くと干渉検査から外す羽目になり、
    # 外した瞬間にナットは「検査されていない部品」に戻る
    # （実際に test_each_added_part_is_actually_checked[nut] が落ちて分かった）。
    from gen_case import NUT_LIP_H
    with BuildPart() as _nut:
        with BuildSketch(Plane.XY.offset(NUT_LIP_H)):
            RegularPolygon(NUT_QUARTER_AF / 2 / cos(radians(30)), 6)
        extrude(amount=NUT_QUARTER_T)
    parts["nut"] = _nut.part

    # ゴム足（前の 2 箇所。座ぐり RUBBER_RECESS に沈む）。
    # **寸法は gen_case の 1 つの出所から取る。**一度 envelopes 側に
    # RUBBER_FOOT_D/T を別に持たせ、「RUBBER_T と同値のこと」と
    # コメントで縛ったが、**一致は誰も確かめていなかった**（変異検査で
    # RUBBER_FOOT_T を 3mm 太らせても何も落ちなかった）。bands.py で
    # 同じ轍を踏んでいる。重複を持たない。
    from gen_case import RUBBER_D, RUBBER_RECESS, RUBBER_T
    with BuildPart() as _rub:
        for fx, fy in _rubber_positions(w, h_case):
            with Locations((fx, fy, RUBBER_RECESS)):
                Cylinder(RUBBER_D / 2, RUBBER_T,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
    parts["rubber"] = _rub.part

    if real:
        parts = _swap_in_real_boards(parts, half, h_plate, rim_front,
                                     db_x, db_center_y)
        # **キースイッチも実物にする。**箱と実物の断面は一致していたが、
        # ステム・ピン・LED 窓・爪は箱が持っていない。**持っていない形は
        # 検査していない**（利用者の指摘・2026-08-11）。
        sw_real = real_switches(positions, pl)
        if sw_real is not None:
            parts = dict(parts)
            parts.pop("switches", None)
            parts["switches_real"] = sw_real
    return parts, (w, h_case)


def real_switches(positions, pl):
    """**キースイッチ 61 個を実形状で置く**（kiswitch の SW_Cherry_MX_Plate）。

    モデルの原点は**基板の上面**（z=0）。組み立ての平らなプレート座標では
    基板の上面は z = −PLATE_TO_PCB なので、そこへ落とす。

    **1 個は 7 立体でできているが、1 つの製品にまとめる。**上下ハウジング・
    ステム・ピン・LED 窓は「別々の部品」ではないので、まとめないと
    自分自身と衝突していると報告される（基板の実装部品と同じ扱い）。
    まとめないともう 1 つ悪いことが起きる: 立体数が 61×7 に増え、
    総当たり（立体数の 2 乗）が実用外になる。
    """
    from build123d import Compound, Location, import_step
    import pcb_parts
    from envelopes import PLATE_TO_PCB

    model = pcb_parts.third_party_model("SW_Cherry_MX_Plate")
    if model is None:
        return None
    sols = import_step(str(model)).solids()
    one = sols[0]
    for t in sols[1:]:
        one = one + t
    return Compound(children=[
        (pl * Location((kx, ky, -PLATE_TO_PCB))) * one for kx, ky in positions])


def _swap_in_real_boards(parts, half, h_plate, rim_front, db_x, db_center_y):
    """基板まわりの**近似の箱を、KiCad の実形状に差し替える**。

    箱（占有空間）は「まだ設計していないものの場所取り」だった。基板は
    設計済みなので、**正確に見るときは実物を置く。**GitHub Actions の
    実形状ジョブがこちらを使う（kicad-cli が要る）。

    差し替えるのは基板とその上の部品だけ。ケース・プレート・上ケース・
    蓋・脚・ネジ・インサート・ゴム足は**元から実物の形**なのでそのまま。
    """
    from build123d import Location
    import pcb_parts
    from envelopes import place_pcb
    from gen_case import DB_BOSS_H, FLOOR

    from build123d import Compound

    def _moved(compound, loc, name):
        """立体ごとに動かし、**製品単位にまとめて**から束ねる。

        - Compound に Location を掛けただけだと、交差の結果が元の
          （KiCad の生の）座標を持ったまま返り、まったく別の場所で
          重なったように見える（2026-08-10 に踏んだ）。だから立体ごとに動かす。
        - 組分けの中身と根拠は pcb_parts.compute_product_groups に。
          **実測は片側 139 秒かかり、基板が変わらない限り結果は同じ**なので、
          記録（pcb_product_groups.json）を経由する（#31）。
        """
        raw = compound.solids()
        board_i, groups = pcb_parts.product_groups(name, raw)
        sols = [s_.moved(loc) for s_ in raw]
        out = [sols[board_i]]
        for g in groups:
            fused = sols[g[0]]
            for i in g[1:]:
                fused = fused + sols[i]
            out.append(fused)
        return Compound(children=out)

    ox, oy = pcb_parts.ORIGIN
    main = pcb_parts.real_compound(half)
    board = max(main.solids(), key=lambda s_: s_.volume)
    parts = dict(parts)
    # **外すのは「実物の写し」だけ**（板・実装部品の記録 bbox。実物が
    # pcb_real / db_real として入るので、残すと同じ物が二重になる）。
    # **予約の箱（sockets / stabs / db / xiao）は外さない**（#31 案 A・
    # 利用者の決定 2026-08-11）。箱は実形状の劣化版ではなく、
    # 「**予約が守られているか**」という別の質問に答える道具。
    # 1 パスで 2 つの質問に答える:
    #   1. 実物どうしがぶつからないか（実形状）
    #   2. 予約が守られているか（条件 1・2 の箱 × ケース等）
    for name in ("pcb", "pcb_parts"):
        parts.pop(name, None)
    parts["pcb_real"] = place_pcb(
        _moved(main, Location((-ox, oy, -board.bounding_box().max.Z)), half),
        h_plate, rim_front)

    dbc = pcb_parts.real_compound("db")
    parts.pop("db_parts", None)
    db_real = _moved(dbc, Location((db_x - ox, db_center_y + oy,
                                    FLOOR + DB_BOSS_H)), "db")

    # **ソケットで XIAO が浮く（open-gaps #27・構成 A）。実形状も浮かせる。**
    #
    # 記録（KiCad の 3D モデル）の XIAO は**直付けの高さ**で入っている。
    # ここで持ち上げないと、絵も干渉検査も直付けのままになる。しかも
    # 下の USB の空洞は usb_center_z()（＝浮いた高さ）で彫るので、
    # **空洞が実物のメスから外れ**、「どんなプラグも食い込む」状態に戻る。
    #
    # 持ち上げる対象は「**板の上面より上にある立体**」。記録では板の上に
    # 立っているのは XIAO 一式だけで、ほかの部品（ffc_conn・cap_0805）は
    # 板の裏（z < 0）にある。
    #
    # **選んだ結果を記録と突き合わせてから動かす。**接頭辞や番号で拾うと
    # 別の物を黙って持ち上げる（この案件で 3 回起きた型）。
    # **数では突き合わせない**（STEP の取り込みで立体が融合し、記録の
    # 84 個に対し 66 個になる。2026-08-12 に実測）。**占める範囲**で見る。
    from envelopes import DB_XIAO_LIFT, db_spacer_bodies
    from interface import xiao_y_offset
    _rec = pcb_parts.load()["db"]
    _z_top = FLOOR + DB_BOSS_H + _rec["board_step_thickness"]
    _xa = [c["bbox"] for c in _rec["components"] if c["label"] == "xiao_asm"]
    _want = (db_x + min(b[0] for b in _xa), db_center_y + min(b[1] for b in _xa),
             db_x + max(b[3] for b in _xa), db_center_y + max(b[4] for b in _xa),
             FLOOR + DB_BOSS_H + max(b[5] for b in _xa))
    lifted, picked = [], []
    for s_ in db_real.solids():
        if s_.bounding_box().min.Z >= _z_top - 1e-3:
            picked.append(s_.bounding_box())
            lifted.append(s_.moved(Location((0, 0, DB_XIAO_LIFT))))
        else:
            lifted.append(s_)
    if not picked:
        raise ValueError("板の上に立つ立体が 1 つも無い。記録か配置が変わった")
    _got = (min(b.min.X for b in picked), min(b.min.Y for b in picked),
            max(b.max.X for b in picked), max(b.max.Y for b in picked),
            max(b.max.Z for b in picked))
    if max(abs(a - b) for a, b in zip(_got, _want)) > 0.05:
        raise ValueError(
            "板の上で拾った立体の範囲が記録の xiao_asm と違う。持ち上げる"
            f"対象を取り違えている:\n  拾った {[round(v, 2) for v in _got]}"
            f"\n  記録   {[round(v, 2) for v in _want]}")
    # 板と XIAO の間に実際に入っている物（ヘッダの樹脂＋ソケット）。
    # **置かないと XIAO が宙に浮いた絵になる**（2026-08-12・利用者の指摘）。
    _db_d = _rec["board_bbox"][4] - _rec["board_bbox"][1]
    lifted += db_spacer_bodies(db_x, db_center_y + xiao_y_offset(_db_d),
                               _z_top).solids()
    db_real = Compound(children=lifted)

    # **第三者モデルは USB-C のメスの口を塞いで描いている。**
    # 前面から 0.5mm を切ると 8.94x3.21 の中実の塊で、穴が無い。実物は
    # 中空（Seeed の公式モデルで確認済み。`envelopes._usb_cavity` の注記）。
    # このままだと**どんなプラグも必ず食い込む**ので、箱の側に入れたのと
    # 同じ補正を実形状にも入れる。入れないと #28 の再発検査が成立しない。
    from envelopes import _usb_cavity
    from gen_case import _RECEPT
    from gen_case import usb_center_z as _ucz
    # 板の奥行は**実物の記録**から（箱側と同じ出所。#31）。設計定数と
    # ずれた日に、口の位置だけ設計側に残ると穴が実物から外れる。
    _dbb2 = pcb_parts.load()["db"]["board_bbox"]
    cav = _usb_cavity(db_x, db_center_y + (_dbb2[4] - _dbb2[1]) / 2
                      + _RECEPT[2], _ucz())
    db_real = Compound(children=[s - cav for s in db_real.solids()])

    parts["db_real"] = db_real
    return parts


def check(keys, half, label="", focus=None, real=False):
    """組み立て状態を検査し、問題の一覧を返す。

    focus に部品名を渡すと、**その部品が絡む組だけ**を検査する。
    変異検査（故意に壊して検出できるか）が全組 253 を回すと遅すぎるため。
    通常の検査（focus=None）は必ず全組を見る。

    **本番の干渉検査は real=True**（#31 案 A・利用者の決定 2026-08-11）。
    実形状＋予約の箱の 1 パスで「実物どうしがぶつからないか」と
    「予約が守られているか」の両方に答える。real=False の箱だけの組み立ては
    変異検査（mutate.py・自己確認テスト）と視覚確認が速さのために使う道具で、
    **検査の本体ではない**。
    """
    from verify import (load_interference_memo, memoized_intersection_volume,
                        save_interference_memo)

    parts, (w, h_case) = build_assembly(keys, half, real=real)
    problems, notes = [], []

    # **結果の記憶**（#31・利用者の決定 2026-08-11）。鍵は 2 立体の
    # BRep（形＋位置）のハッシュ。基準を持たない内容アドレスなので、
    # 基準が古くなる型が入らない。詳細は verify.load_interference_memo。
    memo, touched, digests = load_interference_memo(), set(), {}
    memo_n0 = len(memo)

    # 1. 干渉。**許容値は無い。0 が合格。**
    #
    # **以前はここに許容値の表があった。**「設計上ここは接する」と称して
    # 30mm^3 まで許していたが、実測すると 30 組のうち 17 組は重なり 0 で、
    # 窓だけが開いていた。そして**実物どうしの組にまで許容が掛かっていて、
    # プレートが上ケースに 0.217mm 食い込む不具合を黙って通していた。**
    #
    # 許容値が要るように見えたときは、**例外なくモデルが実物と違っている。**
    # 実際、13 組すべてが次のどれかだった（2026-08-10 に全部潰した）:
    #   - 中空を実体で描いていた（インサート・USB の差込口・取付穴）
    #   - 予約の箱が実物より太かった（基板の外形・ソケット）
    #   - 基準面がずれていた（板厚 1.51 と 1.6／平らな奥行と平面図の奥行）
    #   - 差し込んだ先を塞がった箱に入れていた（FFC）
    #   - **本物の不具合**（プレート）
    # **許容値を足す前に、どれに当たるかを必ず先に調べること。**
    #
    # EPS は設計上の許容ではなく、**ブーリアン演算の分解能**。面どうしが
    # ちょうど接する組は厳密には 0 になるが、円筒と平面が 1 点で触れる
    # ような退化した接触では 1e-8mm^3 級の欠片が出る（一辺 0.004mm）。
    EPS = 1e-6
    # **立体ごとに総当たりする。名前ごとではない。**
    #
    # 以前は名前 23 個の 253 通りしか見ていなかった。**名前は 23 でも物は
    # 175 個**（switches 54・pcb_parts 35・sockets 27・keycaps 27 …）で、
    # まとめた時点で**同じ名前の中どうしの重なりは融合して消える**。
    # 隣り合うキーキャップの隙間（設計 0.65mm）を誰も見ていなかった。
    #
    # 15,225 通りを全部ブーリアン演算すると終わらないので、**bbox で絞って
    # から精密に測る**。bbox が離れていれば体積 0 は確定なので省いてよい。
    items = []                      # (表示名, 立体, bbox)
    for name in parts:
        sols = parts[name].solids()
        for k, sol in enumerate(sols):
            label = name if len(sols) == 1 else f"{name}#{k}"
            items.append((label, sol, sol.bounding_box()))

    # **鍵は総当たりを始める前に、全立体ぶん先に計算する。**遅延で
    # 計算すると鍵が安定しない: 同じ形の立体（キーキャップ等）は 1 つの
    # TShape を共有しており、ブーリアン演算が入力の許容差を書き換えるので、
    # 「先にどの組を演算したか」で後からハッシュした立体のバイト列が変わる
    # （2026-08-11 に実測。キャップ 31 個が毎回 130 組のミスを出していた。
    # 組んだ直後なら 3 回組んでも 277 個全部が一致することも実測済み）。
    from verify import shape_digest
    for _, sol, _ in items:
        digests.setdefault(id(sol), shape_digest(sol))

    def _bb_touch(A, B, margin=0.0):
        return (A.min.X < B.max.X + margin and B.min.X < A.max.X + margin
                and A.min.Y < B.max.Y + margin and B.min.Y < A.max.Y + margin
                and A.min.Z < B.max.Z + margin and B.min.Z < A.max.Z + margin)

    # **板そのものと、その板に載る部品の組は見ない。**
    #
    # 実装部品は板の穴に入るのが正しい姿（ソケットのカップは φ3.05 の穴へ、
    # スタビの爪は φ3.048/φ3.9878 の穴へ）。ここに出る重なりは「基板の設計」
    # ではなく「**第三者モデルの置き位置**」を映す。実際、最後まで残っていた
    # 0.136mm^3 は kiswitch がソケットのカップを穴の中心から最大 0.13mm
    # ずらして置いているだけで、カップは φ2.92・穴は φ3.05 なので**実物は
    # 入る**（2026-08-10 に両方を測って確認）。
    #
    # **代わりの検査を置いてある**（外さずに移した）:
    #   - test_the_hotswap_cups_fit_the_drilled_holes … カップ ⊂ 穴 を寸法で
    #   - test_real_component_boxes_do_not_collide … 部品が板へ沈むのは箱側で
    #   - DRC のコートヤード … 平面の重なり
    # 部品どうしの組は**これまでどおり全部見る**。
    # 板は「その部品の中でいちばん体積の大きい立体」。番号（#0）で決め打つと、
    # 立体の並び順が変わった日に黙って別の物を除外する。
    # **嵌合する組は「重なって当たり前」。**弾性変形するか、穴を通るか。
    # ここに足すときは、**代わりの検査を必ず置く**（外すのではなく移す）。
    #
    #   plate × switches_real … MX の爪のスナップフィット。胴は 14.00 角
    #     ちょうどで開口 14.0 に入るが、**爪は当たって撓む**（実測：板厚を
    #     貫く厚さ 0.01〜0.16mm の膜が開口の縁に多数）。**逃げを入れては
    #     いけない。**入れた瞬間にスイッチが保持されなくなる（スタビとは逆）
    #   pcb_real × switches_real … ピンが基板の穴を通る（実測 0.06mm）。
    #     ソケットのカップと同じ
    #
    # 代わりの検査は test_the_switch_boxes_match_the_real_switch
    #（胴 ⊆ 開口 / ピン ⊆ 穴 / ステム ⊆ キャップの空洞）。
    #
    MATING = {("plate", "switches_real"), ("pcb_real", "switches_real")}

    boards = set()
    for n in ("pcb_real", "db_real"):
        if n in parts:
            sols = parts[n].solids()
            k = max(range(len(sols)), key=lambda j: sols[j].volume)
            boards.add(f"{n}#{k}")

    def _board_and_its_own_part(la, lb):
        for b in boards:
            base = b.split("#")[0]
            if (la == b and lb.startswith(base + "#")) or \
               (lb == b and la.startswith(base + "#")):
                return True
        return False

    seen, hidden = set(), {}
    for i, (la, sa, ba) in enumerate(items):
        for lb, sb, bb_ in items[i + 1:]:
            if focus is not None and focus not in (la.split("#")[0],
                                                   lb.split("#")[0]):
                continue
            if _board_and_its_own_part(la, lb):
                continue
            if tuple(sorted((la.split("#")[0], lb.split("#")[0]))) in {
                    tuple(sorted(m)) for m in (MATING | RESERVATION_CONTAINS)}:
                continue
            if not _bb_touch(ba, bb_):
                continue
            v = memoized_intersection_volume(sa, sb, memo, touched, digests)
            if v > EPS:
                # **同じ名前の組は 1 行にまとめるが、隠さず数える。**
                # 以前は 2 件目以降を黙って捨てていたので、1 件直すたびに
                # 「新しい指摘」が湧いて出た（usb_plug × db_real は端子と舌の
                # 2 件で、舌のほう 20.3mm^3 が 0.064mm^3 の陰に隠れていた）。
                key = (la.split("#")[0], lb.split("#")[0])
                if key in seen:
                    hidden[key] = hidden.get(key, 0) + 1
                    continue
                seen.add(key)
                problems.append(f"{la} と {lb} が {v:.3f}mm^3 食い込んでいる")

    for key, n in hidden.items():
        for k, line in enumerate(problems):
            if line.startswith(f"{key[0]}") and f" と {key[1]}" in line:
                problems[k] = line + f"（ほかに同じ組が {n} 件）"
                break

    if len(memo) != memo_n0:
        save_interference_memo(memo, touched)

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


def main(argv=None):
    """干渉検査（実形状＋予約の箱・両側）。片側だけなら `left`/`right` を渡す。

    kicad-cli が無ければ**検査せず赤で終わる**（利用者の決定 2026-08-11。
    「検査が飛んで緑」がこの案件で 4 回起きた。「できなかった」を
    緑で素通りさせない）。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    import pcb_parts
    if not pcb_parts.kicad_available():
        print("NG kicad-cli が無いので実形状の干渉検査ができない。"
              "検査していない状態を緑にしない", file=sys.stderr)
        return 1
    names = list(halves())
    if argv and argv[0] in names:
        names = [argv[0]]
    ok = True
    for name in names:
        keys = halves()[name]
        problems, notes, parts = check(keys, name, name, real=True)
        print(f"{'OK ' if not problems else 'NG '}{name}  部品 {len(parts)} 個"
              f"（実形状＋予約の箱）")
        for n in notes:
            print(f"      {n}")
        for p in problems:
            print(f"   !! {p}")
        ok &= not problems
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
