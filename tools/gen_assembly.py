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
    parts["sockets"] = place_pcb(socket_envelope(keys), h_plate, rim_front)

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

    # ----------------------------------------------------------------------
    # ここから下は open-gaps #29 で足した「製品として存在する実物」。
    # 足せない物と、その理由は #29 の表にある。**黙って外さない。**
    # ----------------------------------------------------------------------
    import pcb_parts
    from math import cos
    from build123d import BuildSketch, Cylinder, Plane, RegularPolygon, extrude
    from envelopes import (FFC_RIBBON_W, NUT_QUARTER_AF, NUT_QUARTER_T,
                           PCB_T, PLATE_TO_PCB, RUBBER_FOOT_D, RUBBER_FOOT_T,
                           SCREW_HEAD_D, SCREW_HEAD_H, SCREW_L_DB, SCREW_L_MAIN,
                           SW_PWR_D, SW_PWR_H, SW_PWR_W, M2_INSERT_L,
                           key_stack_envelopes, stab_envelope, usb_plug_envelope)
    import envelopes
    from gen_case import (BEZEL_TOP_FRONT, CAP_LIFT, DB_BOSS_POS, OUR_CAPS,
                          _boss_positions, _rubber_positions,
                          power_switch_center_z, power_switch_x_center,
                          usb_center_z)
    from interface import M2_INSERT_D, XIAO_OVERHANG, stab_offset_for

    tilt = tan(radians(TILT_DEG))
    pl = plate_placement(w, h_plate)
    db_center_y = db_rear - DB_D / 2

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
    sw_env, cap_env = key_stack_envelopes(positions, keys, _plate_t,
                                          CAP_LIFT, OUR_CAPS["home"])
    parts["switches"] = pl * sw_env
    parts["keycaps"] = pl * cap_env
    stabs = [(pos, stab_offset_for(k.w_u))
             for pos, k in zip(positions, keys) if stab_offset_for(k.w_u)]
    parts["stabs"] = pl * stab_envelope(stabs)

    # 電源スイッチの実物（受け箱の中の本体＋壁を貫く操作部）
    from gen_case import WALL as _wall
    y_rear_outer = h_case / 2 + BUMP_DEPTH
    y_rear_inner = y_rear_outer - _wall
    sw_x, sw_z = power_switch_x_center(half, w), power_switch_center_z()
    with BuildPart() as _sw:
        with Locations((sw_x, y_rear_inner - SW_PWR_D / 2, sw_z)):
            Box(SW_PWR_W, SW_PWR_D, SW_PWR_H,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
        # アクチュエータ 4.0mm は壁 2.4mm を貫いて 1.6mm 出る
        with Locations((sw_x, y_rear_inner, sw_z)):
            Box(2.4, _wall + 1.6, 2.5, align=(Align.CENTER, Align.MIN, Align.CENTER))
    parts["sw_pwr"] = _sw.part

    # 利用者が挿す USB ケーブルのプラグ（open-gaps #28 の再発防止）。
    # **メス（XIAO の奥端面）から位置を導く。**メスが壁から遠のけば、
    # 樹脂の胴体が壁に食い込む形でここに出る。
    parts["usb_plug"] = usb_plug_envelope(db_x, db_rear + XIAO_OVERHANG,
                                          usb_center_z())

    # FFC ケーブル。**経路は未発注・未決定なので、仮置きの占有空間。**
    # J_DB（本体・口は手前向き）から下りて床の上を這い、J_MAIN（子基板の
    # 裏・口は手前向き）へ入る。位置は両方とも STEP の実体から取る。
    rec = pcb_parts.load()
    jdb = [c["bbox"] for c in rec[half]["components"] if c["label"] == "ffc_conn"]
    jx = (min(b[0] for b in jdb) + max(b[3] for b in jdb)) / 2
    jy = min(b[1] for b in jdb)                        # 口（手前端）
    jm = [c["bbox"] for c in rec["db"]["components"] if c["label"] == "ffc_conn"]
    jm_y = db_center_y + min(b[1] for b in jm)         # J_MAIN の口（手前端）
    z_board_bottom = (rim_front + (jy + h_plate / 2) * tilt
                      - PLATE_TO_PCB - PCB_T)
    z_lo = FLOOR + 1.9                                 # 走行部は床の少し上
    hw = FFC_RIBBON_W / 2
    with BuildPart() as _ffc:
        # J_DB の口の前で下へ折り下げる幕。**薄く（1.0mm）**。
        # 口の 1.1mm 手前からソケットの保守的な箱（はんだ余裕込み）が
        # 始まるので、ケーブルは口を出てすぐ折れる必要がある（FFC の
        # 静的な折りなら可能）。折りの膨らみが箱の角に触れるぶんは
        # CONTACT の {sockets, ffc} で根拠つきで許す。
        # 上端は基板の下面の少し手前で止める（平面近似の誤差で板を
        # 突かないため。コネクタの口 −3.6〜−1.6 は覆えている）。
        with Locations((jx, jy - 0.5, z_lo)):
            Box(FFC_RIBBON_W, 1.0, z_board_bottom - 0.5 - z_lo,
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
        # J_MAIN へ差し込まれる先端（設計上の嵌合）
        with Locations((db_x, jm_y + 1.25, FLOOR + DB_BOSS_H - 1.6)):
            Box(6.0, 2.5, 0.8, align=(Align.CENTER, Align.CENTER, Align.MIN))
    parts["ffc"] = _ffc.part

    # M2 熱圧入インサート（本体ボス 3＋子基板ボス 2）。
    # **本体ボスの頭は 7.3° の傾斜面で切られている**ので、水平な上面の
    # 円柱を面の中心高さに置くと、後ろ半分が r·tan(7.3°)=0.21mm 突き出て
    # 上ケース・プレートに 0.19mm 食い込む（隙間レポートで発覚。体積が
    # 0.8mm^3 で検査の閾値 1.0 の下に潜っていた）。実物は面より下へ押し
    # 込むので、傾斜の振れぶん 0.25mm 沈めて置く。
    with BuildPart() as _ins:
        for bx, by in _boss_positions(half):
            top = rim_front + (by + h_case / 2) * tilt - 0.25
            with Locations((bx, by, top)):
                Cylinder(M2_INSERT_D / 2, M2_INSERT_L,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
        for dx_, dy_ in DB_BOSS_POS:
            with Locations((db_x + dx_, db_center_y + dy_, FLOOR + DB_BOSS_H)):
                Cylinder(M2_INSERT_D / 2, M2_INSERT_L,
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
                Cylinder(1.0, SCREW_L_MAIN,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
        for dx_, dy_ in DB_BOSS_POS:
            with Locations((db_x + dx_, db_center_y + dy_,
                            FLOOR + DB_BOSS_H + DB_T)):
                Cylinder(SCREW_HEAD_D / 2, SCREW_HEAD_H,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
                Cylinder(1.0, SCREW_L_DB,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
    parts["screws"] = _scr.part

    # テンティング用 1/4-20 六角ナット（底面のポケットに埋め込む）
    with BuildPart() as _nut:
        with BuildSketch(Plane.XY):
            RegularPolygon(NUT_QUARTER_AF / 2 / cos(radians(30)), 6)
        extrude(amount=NUT_QUARTER_T)
    parts["nut"] = _nut.part

    # ゴム足（前の 2 箇所。座ぐり 0.6mm に沈む）
    from gen_case import RUBBER_RECESS
    with BuildPart() as _rub:
        for fx, fy in _rubber_positions(w, h_case):
            with Locations((fx, fy, RUBBER_RECESS)):
                Cylinder(envelopes.RUBBER_FOOT_D / 2, RUBBER_FOOT_T,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
    parts["rubber"] = _rub.part

    return parts, (w, h_case)


def check(keys, half, label="", focus=None):
    """組み立て状態を検査し、問題の一覧を返す。

    focus に部品名を渡すと、**その部品が絡む組だけ**を検査する。
    変異検査（故意に壊して検出できるか）が全組 253 を回すと遅すぎるため。
    通常の検査（focus=None）は必ず全組を見る。
    """
    from verify import intersection_volume

    parts, (w, h_case) = build_assembly(keys, half)
    problems, notes = [], []

    # 1. 干渉。**設計上の食い込み**だけを、実測した量ぶんだけ許す。
    #
    # **許容は「実測 + わずかな余白」にする。**以前はここに 30.0 が並んで
    # いたが、実測すると 30 組のうち 17 組は重なり 0 だった。つまり
    # 30mm^3 の窓が開いたままで、その下の回帰は永久に見えなかった。
    # 実際、傾斜面で切られたボスに水平な円柱を置いた誤り（インサートが
    # 上ケースへ 0.19mm 食い込む）は、既定の 1.0mm^3 の下に潜っていた。
    #
    # **表の値を疑うときは、実測し直して比べること**（2026-08-10 実施）:
    #     parts, _ = build_assembly(halves()[half], half)
    #     intersection_volume(parts[a], parts[b])
    # 実測より大きく広げてよいのは、**なぜその量が要るかを書ける**ときだけ。
    #
    # 面どうしがぴったり接する組は、厳密な B-rep 演算では 0 になる
    # （左右 68 組で確認）。だから接触するだけの組は表に載せず、既定へ落とす。
    DEFAULT = 0.1        # 接するだけの組の許容。0.19mm^3 の食い込みを捕まえる
    CONTACT = {
        # 値の後ろは 2026-08-10 の実測（左 / 右）。
        frozenset({"case", "pcb"}): 30.0,        # 基板はネジボスの上に載る 26.5/26.5
        frozenset({"plate", "topcase"}): 30.0,   # 上ケースがプレートを押さえる 21.9/27.4
        # **ソケットの箱は実体より太い**（フットプリント実測＋はんだ余裕）。
        # 実体のダイオード（STEP）はその余白に入るので重なって見えるが、
        # 基板上の部品どうしの離隔は DRC のコートヤード（違反 0）と
        # test_real_board_parts_do_not_collide_in_3d が実体で検査している。
        # **ここだけ余白が広い**（右 138.7 に対し 170）。1 個 4.1mm^3 なので
        # 実質「ダイオード 7 個ぶん」の窓が開いている。狭めるには箱ではなく
        # 実物のソケット断面が要る（現物のノギス待ち）。
        frozenset({"sockets", "pcb_parts"}): 170.0,
        frozenset({"db", "usb_plug"}): 95.0,     # メスの奥は db の箱の中 89.7
        frozenset({"inserts", "screws"}): 65.0,  # ねじ込み（嵌合）59.1
        frozenset({"db", "screws"}): 50.0,       # 頭が載り軸が板を貫く 46.3
                                                 # （占有空間の箱には穴が無い）
        frozenset({"xiao", "usb_plug"}): 42.0,   # 金属がメスに入る（嵌合）38.4
        frozenset({"db_parts", "ffc"}): 14.0,    # 先端がコネクタに入る（嵌合）12.0
        frozenset({"sockets", "ffc"}): 10.0,     # 折り下げの幕が箱の角に触れる 8.8/8.7
        frozenset({"pcb", "pcb_parts"}): 3.0,    # 部品が基板の面に載る 1.4/1.7
                                                 # （STEP の板厚 1.51 と公称 1.6 の差 0.09）
        frozenset({"case", "sockets"}): 2.0,     # 仕切り壁の頭をソケット下端の
                                                 # 面で切ってある 1.3/1.2
        # **占有空間は実基板より 2.3mm 手前まで張り出している**（envelope の
        # 手前端 y=-51.0 に対し実基板 -48.7）。インサート φ3.2 が、その
        # 張り出しぶんと逃げ穴 φ2.4 の差を削る。**実基板とは 1.2mm 離れて
        # いるので実物の衝突ではない**（2026-08-10 に STEP で確認）。
        frozenset({"pcb", "inserts"}): 0.5,      # 0.19/0.19
        # 同径の円筒どうし（母線が一致する）。解析的には 0 だが、演算系が
        # 変わるとごく薄い欠片が出うるので、ここだけ保険を残す。実測 0.0。
        frozenset({"case", "inserts"}): 0.5,     # 下穴 φ3.2 とインサート φ3.2
        frozenset({"case", "rubber"}): 0.5,      # 座ぐり φ10 とゴム足 φ10
    }
    names = list(parts)
    # bbox が離れている組は体積 0 で確定なので、ブーリアン演算を省く。
    # 部品が 10 → 22 個になり、総当たり 231 組を全部計算すると遅すぎる。
    bbs = {n: parts[n].bounding_box() for n in names}

    def _bb_touch(a, b, margin=0.5):
        A, B = bbs[a], bbs[b]
        return (A.min.X < B.max.X + margin and B.min.X < A.max.X + margin
                and A.min.Y < B.max.Y + margin and B.min.Y < A.max.Y + margin
                and A.min.Z < B.max.Z + margin and B.min.Z < A.max.Z + margin)

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if focus is not None and focus not in (a, b):
                continue
            if not _bb_touch(a, b):
                continue
            v = intersection_volume(parts[a], parts[b])
            limit = CONTACT.get(frozenset({a, b}), DEFAULT)
            if v > limit:
                kind = "接触の域を超えて" if limit > DEFAULT else ""
                problems.append(
                    f"{a} と {b} が {kind}{v:.2f}mm^3 食い込んでいる（許容 {limit}）")

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
