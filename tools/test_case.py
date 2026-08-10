"""ボトムケースが物理的に成立することを検証する。"""
import pytest
from build123d import Align, Box, BuildPart, Location, Locations
from gen_case import (
    AA_D, AA_L, BATT_H, BATT_W, FLOOR, PLATE_T, PLATE_TOP_FRONT, TILT_DEG,
    build_case, case_heights,
)
from gen_plate import halves
from verify import assert_watertight, intersection_volume, to_mesh

HALVES = halves()


@pytest.mark.parametrize("name", ["left", "right"])
def test_outer_size_matches_the_tilted_plate(name):
    """ケースの外形は、傾けたプレートの平面図と一致する。

    平らなプレートを 7.3° 傾けると平面図の奥行は cos 倍に縮む。
    プレートの平らな寸法をそのまま使うとリムが 0.84mm 長くなる。

    **奥行はコブぶんだけプレートより長い。** 実機も同じで、本体 108mm に
    電池コブ 12mm が足されて全長 120mm になる。
    """
    from gen_case import BUMP_DEPTH
    from gen_plate import plate_positions
    from interface import plan_depth
    part, (w, h_body), _ = build_case(HALVES[name], name)
    _, (pw, h_plate) = plate_positions(HALVES[name])
    bb = part.bounding_box().size
    assert bb.X == pytest.approx(pw, abs=0.01)
    assert h_body == pytest.approx(plan_depth(h_plate), abs=0.01), \
        "プレートが載る範囲が、傾けたプレートの平面図と違う"
    assert bb.Y == pytest.approx(h_body + BUMP_DEPTH, abs=0.01), \
        "ケース全体の奥行が「プレートの範囲 ＋ コブ」になっていない"


@pytest.mark.parametrize("name", ["left", "right"])
def test_rim_height_gives_the_intended_plate_top(name):
    """リムの高さ + 板厚 = 狙ったプレート上面高さ。"""
    from math import radians, tan
    from gen_case import BEZEL_TOP_FRONT, BUMP_DEPTH
    from interface import plan_depth
    from gen_plate import plate_positions
    part, (_, h_body), (z_front, z_rear) = build_case(HALVES[name], name)
    # **最も高いのはコブの後端（ベゼル上面）。**
    # 以前はプレートのリムが最高点だったが、上ケース方式でコブがベゼル面まで
    # 上がったので基準が変わった。
    z_top = BEZEL_TOP_FRONT + (h_body + BUMP_DEPTH) * tan(radians(TILT_DEG))
    assert part.bounding_box().size.Z == pytest.approx(z_top, abs=0.05)
    assert z_front == pytest.approx(PLATE_TOP_FRONT)


@pytest.mark.parametrize("name", ["left", "right"])
def test_printable(name):
    part, _, _ = build_case(HALVES[name], name)
    mesh, _ = to_mesh(part, f"case_{name}")
    assert_watertight(mesh, f"case_{name}")


@pytest.mark.parametrize("name", ["left", "right"])
def test_two_aa_batteries_fit(name):
    """単3×2（左右方向に直列）がケースと干渉せずに収まること。

    電極と配線の余裕を含めた占有空間で判定する。前後に並べる案は
    傾いた基板と 4,000mm^3 衝突したため、左右方向に改めた。
    """
    from envelopes import battery_envelope
    from gen_case import battery_center
    part, (_, h_body), _ = build_case(HALVES[name], name)
    from gen_case import battery_x_center
    from gen_plate import plate_positions
    _, (w, _) = plate_positions(HALVES[name])
    batt = battery_envelope((battery_x_center(name, w),
                             battery_center(h_body), FLOOR + AA_D / 2))
    v = intersection_volume(batt, part)
    assert v < 1e-3, f"{name}: 電池がケースと干渉している ({v:.2f}mm^3)"


def test_tilt_matches_the_measured_value():
    """傾斜は実機の実測値 7.3° であること。"""
    assert TILT_DEG == 7.3
    zf, zr = case_heights(100.0)
    import math
    assert math.degrees(math.atan((zr - zf) / 100.0)) == pytest.approx(7.3, abs=1e-6)


# --------------------------------------------------------------------------
# 電池蓋・チルト脚・三脚ナット・ゴム足
# --------------------------------------------------------------------------

def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


@pytest.mark.parametrize("name", ["left", "right"])
def test_battery_lid_is_printable_and_fits_the_opening(name):
    from gen_case import CLEARANCE, LID_STOP, _lid_opening, build_battery_lid
    from gen_plate import plate_positions
    lid, (lw, lh) = build_battery_lid(name, HALVES[name])
    mesh, _ = to_mesh(lid, f"battery_lid_{name}")
    assert_watertight(mesh, f"battery_lid_{name}")
    _, (w, h) = plate_positions(HALVES[name])
    _, _, ow, oh = _lid_opening(name, w, h)
    assert lw < ow, "蓋が開口より大きい"
    assert lh < oh - LID_STOP, "蓋がストッパーに当たって入らない"
    assert ow - lw == pytest.approx(CLEARANCE), "嵌合の逃げが設計値と違う"


@pytest.mark.parametrize("deg", [3.0, 6.0])
def test_tilt_foot_height_gives_the_intended_angle(deg):
    """脚の高さが、後縁を deg だけ持ち上げる値になっていること。"""
    import math
    from gen_case import FOOT_BASE_H, RUBBER_INSET, build_tilt_foot, foot_height
    from gen_plate import plate_positions
    _, (w, h) = plate_positions(HALVES["left"])
    z = foot_height(h, deg)
    lever = h - RUBBER_INSET * 2
    assert math.degrees(math.atan((z - FOOT_BASE_H) / lever)) == pytest.approx(deg, abs=1e-9)
    foot, fz = build_tilt_foot(deg, h)
    mesh, _ = to_mesh(foot, f"tilt_foot_{int(deg)}")
    assert_watertight(mesh, f"tilt_foot_{int(deg)}")
    assert fz == pytest.approx(z)


@pytest.mark.parametrize("name", ["left", "right"])
def test_bottom_features_do_not_overlap(name):
    """底面の座ぐり・ピン穴・三脚ボスが互いに干渉しないこと。

    ゴム足の隅にチルト脚を置いて重なった実例があるので、必ず数値で見る。
    """
    from gen_case import (
        FOOT_D, FOOT_PEG_D, NUT_BOSS_D, RUBBER_D, _foot_positions,
        _rubber_positions,
    )
    from gen_plate import plate_positions
    _, (w, h) = plate_positions(HALVES[name])
    items = ([(p, RUBBER_D / 2) for p in _rubber_positions(w, h)]
             + [(p, FOOT_D / 2) for p in _foot_positions(w, h)]
             + [((0.0, 0.0), NUT_BOSS_D / 2)])
    for i, (pa, ra) in enumerate(items):
        for pb, rb in items[i + 1:]:
            assert _dist(pa, pb) > ra + rb, f"{name}: {pa} と {pb} が重なる"


# --------------------------------------------------------------------------
# 部品どうしの突き合わせ
#
# 「プレートの穴 vs 共有定義」だけを見ていて、ケースの実物と照合していなかった。
# そのためケースがボス位置の独自実装を持ち続けていることに長く気づけず、
# ボスが電池室の中に立っていた。実物どうしを比べる。
# --------------------------------------------------------------------------

def _boss_solid_centers(part, expect_d):
    """部品の中から、直径 expect_d のボスらしき柱の中心を拾う。"""
    out = []
    for s in part.solids():
        bb = s.bounding_box()
        if abs(bb.size.X - expect_d) < 0.2 and abs(bb.size.Y - expect_d) < 0.2:
            out.append((bb.center().X, bb.center().Y))
    return out


@pytest.mark.parametrize("name", ["left", "right"])
def test_case_bosses_come_from_the_shared_definition(name):
    """ケースのボス位置が共有定義と一致すること。

    ケース側に独自実装を残すと、プレートの穴と食い違う。実際に食い違っていた。
    """
    from gen_case import _boss_positions
    from gen_plate import plate_positions
    from interface import boss_positions_plan
    _, (w, h_plate) = plate_positions(HALVES[name])
    assert _boss_positions(name) == boss_positions_plan(name)


@pytest.mark.parametrize("name", ["left", "right"])
def test_bosses_do_not_stand_inside_the_battery_compartment(name):
    """ネジボスが電池室を貫かないこと。

    後ろ側のボスは電池（幅109mm）の外に出す必要がある。中央に置いて231mm^3、
    w/4 に置いて77mm^3 の食い込みを出した。
    """
    from build123d import Align, BuildPart, Cylinder, Locations
    from envelopes import battery_envelope
    from gen_case import AA_D, FLOOR, M2_BOSS_D, _boss_positions, battery_center
    from gen_plate import plate_positions
    from interface import plan_depth
    from verify import intersection_volume

    from gen_case import battery_x_center
    _, (w, h_plate) = plate_positions(HALVES[name])
    # **電池の実際の X 位置を使う。** 0 のまま書いていて、電池を外側へ
    # 寄せたあとも中央にあるものとして検査していた（＝別の場所を見ていた）。
    batt = battery_envelope((battery_x_center(name, w),
                             battery_center(plan_depth(h_plate)),
                             FLOOR + AA_D / 2))
    for bx, by in _boss_positions(name):
        with BuildPart() as b:
            with Locations((bx, by, FLOOR)):
                Cylinder(M2_BOSS_D / 2, 40,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        v = intersection_volume(batt, b.part)
        assert v < 1e-3, f"{name}: ボス({bx:.1f},{by:.1f}) が電池室を貫く ({v:.1f}mm^3)"


@pytest.mark.parametrize("name", ["left", "right"])
def test_the_antenna_is_kept_away_from_the_battery(name):
    """XIAO のアンテナと単3電池の距離を確保すること。

    **幾何が干渉しないことと、電波が届くことは別の話。**
    電池を外へ寄せて子基板の場所を作ったとき、幾何だけを見ていて
    アンテナから 1.0mm の位置に置いていた。単3 電池は金属の塊で、
    至近距離では 2.4GHz のアンテナを大きく狂わせる。
    左右間の BLE 接続はこのキーボードの中核要件で、その通信距離を
    自分で潰すことになっていた。
    """
    from gen_case import (BATT_X, DB_ANTENNA_KEEPOUT, DB_W, battery_x_center,
                          daughterboard_x_center, inner_sign)
    from gen_plate import plate_positions
    _, (w, _) = plate_positions(HALVES[name])
    s = inner_sign(name)
    gap = abs((daughterboard_x_center(name, w) - s * DB_W / 2)
              - (battery_x_center(name, w) + s * BATT_X / 2))
    assert gap >= DB_ANTENNA_KEEPOUT, (
        f"{name}: アンテナと電池が {gap:.1f}mm しか離れていない"
        f"（必要 {DB_ANTENNA_KEEPOUT}mm）")





# --------------------------------------------------------------------------
# プリンタの制約（Creality K1 Max / PLA / ノズル 0.4mm）
# --------------------------------------------------------------------------
K1MAX_BED = (300.0, 300.0, 300.0)
NOZZLE = 0.4


@pytest.mark.parametrize("name", ["left", "right"])
def test_every_part_fits_the_printer(name):
    """全部品が K1 Max の造形範囲に収まること。

    **造形できない部品を設計しても意味がない。**寸法を大きくしたときに
    黙って超えることを防ぐ。
    """
    from gen_case import build_case, build_topcase, build_battery_lid
    from gen_plate import build_plate
    parts = {
        "case": build_case(HALVES[name], name)[0],
        "topcase": build_topcase(HALVES[name], name)[0],
        "lid": build_battery_lid(name, HALVES[name])[0],
        "plate": build_plate(HALVES[name], name)[0],
    }
    for label, part in parts.items():
        s = part.bounding_box().size
        fits = (min(s.X, s.Y) <= min(K1MAX_BED[0], K1MAX_BED[1])
                and max(s.X, s.Y) <= max(K1MAX_BED[0], K1MAX_BED[1])
                and s.Z <= K1MAX_BED[2])
        assert fits, (f"{name} の {label} が造形範囲を超える "
                      f"({s.X:.1f}x{s.Y:.1f}x{s.Z:.1f} > {K1MAX_BED})")


def test_wall_thicknesses_are_multiples_of_the_nozzle():
    """壁と床がノズル径の整数倍であること。

    半端な厚みにすると、スライサが埋めきれず隙間が残る。
    **上ケースの壁 1.6mm はノズル 4 本ぶん**で、これは意図した値。
    """
    from gen_case import FLOOR, LID_T, WALL
    from interface import BEZEL_WALL
    for label, t in (("側壁", WALL), ("床", FLOOR), ("蓋", LID_T),
                     ("上ケースの壁", BEZEL_WALL)):
        n = t / NOZZLE
        assert abs(n - round(n)) < 1e-6, \
            f"{label} {t}mm がノズル {NOZZLE}mm の整数倍でない（{n:.2f} 本）"


def test_the_daughterboard_can_carry_both_the_mcu_and_its_screws():
    """子基板に XIAO とネジが**同時に**載ること。

    22x22mm で設計を始めたが、取付穴の置ける場所が 0 箇所だった。
    XIAO は 17.8x21mm で、ネジの逃げ（半径 2.2mm）が入る余地が残らない。
    **入るかどうかは、置き始める前に数えられる。**
    """
    from gen_case import DB_BOSS_POS, DB_D, DB_W
    from interface import M2_CLEAR_D
    XW, XL = 17.8, 21.0
    r = M2_CLEAR_D / 2 + 1.0
    for x, y in DB_BOSS_POS:
        assert abs(x) + r <= DB_W / 2, f"ネジ({x},{y}) が基板の幅から出る"
        assert abs(y) + r <= DB_D / 2, f"ネジ({x},{y}) が基板の奥行から出る"
        assert abs(x) - r >= XW / 2 or abs(y) - r >= XL / 2, \
            f"ネジ({x},{y}) が XIAO の下に入る"
    assert len(DB_BOSS_POS) >= 2, "ネジが 1 本では回る"
    assert DB_BOSS_POS[0][0] != DB_BOSS_POS[1][0], \
        "ネジが中心線上に並んでいる。回り止めにならない"


@pytest.mark.parametrize("name", ["left", "right"])
def test_the_battery_bump_has_a_lid(name):
    """コブに天井があること（電池が上から露出しないこと）。

    **「メッシュが水密」は「箱として閉じている」を意味しない。**
    内側のくり抜きを奥まで通していたため、コブが上に開いたままだった。
    本体側はプレートと上ケースが覆うが、コブの上には何も載らない。
    干渉検査も水密検査もこれを見つけられなかった。
    """
    from build123d import Align, Box, BuildPart, Locations
    from gen_case import battery_center, battery_x_center, build_case
    from gen_plate import plate_positions
    from verify import intersection_volume

    case, (w, h_body), _ = build_case(HALVES[name], name)
    bx = battery_x_center(name, w)
    by = battery_center(h_body)
    found = False
    for z in range(18, 34):
        with BuildPart() as probe:
            with Locations((bx, by, float(z))):
                Box(60.0, 8.0, 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        if intersection_volume(probe.part, case) > 1.0:
            found = True
            break
    assert found, f"{name}: 電池の真上にケースの材料が無い（コブが開いている）"


def test_the_bosses_take_heat_set_inserts():
    """ボスが熱圧入インサートを受ける寸法であること。

    **PLA に M2 を直接タッピングすると、数回の開け閉めで舐める。**
    インサート外径 3.2mm に対して肉厚 1.2mm 以上を確保する。
    """
    from interface import M2_BOSS_D, M2_INSERT_D, M2_PILOT_D
    wall = (M2_BOSS_D - M2_INSERT_D) / 2
    assert wall >= 1.2 - 1e-9, f"ボスの肉厚が {wall:.2f}mm しかない（インサートが割る）"
    assert M2_PILOT_D == M2_INSERT_D, \
        "ケース側の下穴がインサート外径になっていない（タッピング用のまま）"


def test_the_m2_inserts_fit_the_bosses():
    """買う M2 インサートが、いちばん浅いボスに収まること。

    **外径だけでは足りない。**`interface.M2_INSERT_D` は外径 3.2mm を
    規定しているが、**長さはどこにも規定が無かった**。子基板のボスは
    下穴を 5.0mm しか掘っておらず、市販の 5.7mm を買うと入らない
    （open-gaps #24）。

    買う製品を変えたら `envelopes.M2_INSERT_L` を差し替える。
    それだけでここが判定し直す。
    """
    from envelopes import M2_INSERT_L
    from gen_case import DB_BOSS_H
    deepest = DB_BOSS_H + 1.0          # gen_case が実際に掘っている深さ
    assert M2_INSERT_L <= deepest, (
        f"M2 インサートの長さ {M2_INSERT_L}mm が、子基板のボスに掘った "
        f"{deepest}mm を超える。短いものを買うか、DB_BOSS_H を深くすること")


@pytest.mark.parametrize("name", ["left", "right"])
def test_a_real_cable_can_reach_the_socket(name):
    """**利用者が挿す本物のケーブル**が、壁を通ってメスまで届くこと。

    以前ここは「切り欠きが XIAO の積み上げを囲めているか」しか見ていなかった。
    **利用者が挿すケーブルは検査の対象に入っていなかった**（open-gaps #28）。

    穴の大きさを決めるのは**金属のシェル**であって樹脂ではない。
    実機の写真では、樹脂は完全にケースの外にあり、金属が 1mm ほど見えたまま
    挿さっている。**一度ここを樹脂の大きさ（12.4x7.4mm）で作っていたが誤り。**
    """
    import gen_case as g
    from envelopes import (DB_STACK_H, USB_PLUG_H, USB_PLUG_W,
                           USB_SHELL_EXPOSED, USB_SHELL_H, USB_SHELL_W,
                           XIAO_H_WITH_USB)
    from gen_plate import plate_positions

    part, (w, h_body), _ = build_case(HALVES[name], name)
    _, (pw, _ph) = plate_positions(HALVES[name])
    y_out = h_body / 2 + g.BUMP_DEPTH
    x = g.daughterboard_x_center(name, pw)
    z = g.usb_center_z()

    def probe(dw, dh, depth):
        """幅 dw・高さ dh の角柱を、奥面から depth だけ差し込んで当たりを測る。

        ⚠️ **Box は (X, Y, Z) の順。**ここは Y が奥行・Z が高さなので
        `Box(dw, depth, dh)`。以前は `Box(dw, dh, depth)` と書いていて
        **高さと奥行が入れ替わっていた**（2026-08-10 に発覚）。
        そのため差し込み棒は 7mm も奥へ伸び、測っていたのは壁ではなく
        XIAO のポケットだった。**#28 の見張り役が、見張る場所を間違えていた。**
        """
        with BuildPart() as b:
            with Locations((x, y_out - depth / 2, z)):
                Box(dw, depth, dh, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        return intersection_volume(b.part, part)

    # 1. 金属のシェルが、メスまで貫通できること
    v = probe(USB_SHELL_W, USB_SHELL_H, g.USB_PLUG_ENTRY)
    assert v < 1.0, f"{name}: プラグの金属が壁に {v:.1f}mm^3 当たる"

    # 2. 樹脂は座ぐりのぶんだけ入れること（露出の短いケーブルへの保険）
    v = probe(USB_PLUG_W, USB_PLUG_H, g.USB_COUNTERBORE)
    assert v < 1.0, f"{name}: 樹脂が座ぐりに {v:.1f}mm^3 当たる"

    # 3. **穴が大きすぎないこと。**樹脂が壁を貫通できてはいけない
    #    （貫通できる＝実機と違う大きな口が開いている）。
    v = probe(USB_PLUG_W, USB_PLUG_H, g.WALL)
    assert v > 1.0, (
        f"{name}: 樹脂が壁を素通りする。穴が大きすぎる"
        f"（外から見える口が {g.USB_W:.1f}x{g.USB_H:.1f}mm を超えている）")

    # 4. 実測したケーブルが挿さること
    need = g.USB_PLUG_ENTRY - g.USB_COUNTERBORE
    assert need <= USB_SHELL_EXPOSED, (
        f"金属の露出が {USB_SHELL_EXPOSED}mm のケーブルでは {need:.2f}mm 足りない")

    # 5. 高さ方向の余裕（XIAO の積み上げに対して）
    assert DB_STACK_H >= XIAO_H_WITH_USB
    bottom = g.FLOOR + g.DB_BOSS_H + g.DB_T
    lo, hi = z - g.USB_H / 2, z + g.USB_H / 2
    assert lo >= bottom - 1.0 and hi <= bottom + DB_STACK_H + 1.0, (
        f"穴 {lo:.2f}〜{hi:.2f} が XIAO の積み上げ "
        f"{bottom:.2f}〜{bottom + DB_STACK_H:.2f} から外れている")


@pytest.mark.parametrize("name", ["left", "right"])
def test_the_antenna_is_no_longer_under_the_main_board(name):
    """XIAO のアンテナが、本体基板の下から出ていること（open-gaps #23）。

    **これがこの案件の中心にある問題。**アンテナの上 4.09mm に本体基板の
    全面 GND ベタがあり、チップアンテナの指針（全層 5〜10mm の禁止域）を
    真上で破っていた。XIAO を子基板の中央から奥端へ寄せ、さらに板から
    はみ出させることで、アンテナは基板の後端より奥へ出る。

    **アンテナの位置は interface.antenna_y_span が唯一の出所。**
    ケース側（電池の寄せ方・壁厚・XIAO の位置）が動けばここが落ちる。
    """
    from gen_case import BUMP_DEPTH, DB_FROM_REAR, WALL
    from gen_plate import plate_positions
    from interface import PCB_INSET_Y, antenna_y_span, plan_depth

    _, (_pw, ph) = plate_positions(HALVES[name])
    h_body = plan_depth(ph)
    db_rear = h_body / 2 + BUMP_DEPTH - WALL - DB_FROM_REAR
    ant_lo, ant_hi = antenna_y_span(db_rear)
    pcb_rear = ph / 2 - PCB_INSET_Y
    assert ant_lo >= pcb_rear, (
        f"{name}: アンテナ y {ant_lo:.2f}〜{ant_hi:.2f} が"
        f" 本体基板の後端 {pcb_rear:.2f} より手前"
        f"（{pcb_rear - ant_lo:.2f}mm 潜っている）")


@pytest.mark.parametrize("name", ["left", "right"])
def test_the_battery_does_not_sit_under_the_board(name):
    """電池が基板の下に入っていないこと。

    **裸の単3 の外装はマイナス極そのもの。**基板の裏には電池と電源
    スイッチのランド（`BT1_+` `BT1_-` `SW_PWR_1` `SW_PWR_2`）が露出して
    いるので、電池が基板の真下に来ると**電池を直接短絡しうる**。

    いまの設計では電池は基板の後端より後ろ（コブの中）にあるので当たらない。
    **文書には「上＝基板」と書いてあったが誤り**で、実際はコブの天井。
    電池室を前へ動かしたくなったときに、ここが止める。
    """
    from gen_case import BATT_W, battery_center
    from gen_plate import plate_positions
    from interface import PCB_INSET_Y

    _, (_w, h) = plate_positions(HALVES[name])
    pcb_rear = h / 2 - PCB_INSET_Y
    batt_front = battery_center(h) - BATT_W / 2
    assert batt_front >= pcb_rear, (
        f"{name}: 電池の前端 y={batt_front:.1f} が基板の後端 y={pcb_rear:.1f} "
        f"より前にある。**基板裏の露出ランドと電池の外装が触れうる。**"
        f"電池を後ろへ戻すか、ランドを表面へ移すこと")


def test_the_zero_degree_state_is_actually_level():
    """「0°」の脚を差したとき、前後の接地高さが等しいこと。

    **ゴム足は座ぐりに沈み、チルト脚は沈まない。**接地までの高さは
    ゴム足が（厚み − 座ぐり）、チルト脚が全高。ここを揃えないと
    「0°」でも傾く。

    `FOOT_BASE_H = 2.0`（＝ゴム足の厚みそのもの）と置いていたため、
    **後ろが 0.6mm 高く、打鍵面が 7.3° ではなく 7.71° になっていた**
    （2026-08-08 に発見）。傾斜は動かしてはならない値。
    """
    import math

    from gen_case import (FOOT_BASE_H, RUBBER_INSET, RUBBER_RECESS, RUBBER_T,
                          foot_height)
    from gen_plate import plate_positions

    front = RUBBER_T - RUBBER_RECESS
    rear = foot_height(plate_positions(HALVES["left"])[1][1], 0.0)
    assert rear == pytest.approx(front, abs=1e-9), (
        f"「0°」で前 {front}mm / 後 {rear}mm と食い違っている。"
        f"FOOT_BASE_H はゴム足の**接地までの高さ**（厚み − 座ぐり）に揃えること")

    # 念のため、傾きに直したときの誤差も見る
    for name in ("left", "right"):
        _, (_w, h) = plate_positions(HALVES[name])
        lever = h - RUBBER_INSET * 2
        err = math.degrees(math.atan((rear - front) / lever))
        assert abs(err) < 0.05, f"{name}: 「0°」なのに {err:+.2f}° 傾いている"


@pytest.mark.parametrize("name", ["left", "right"])
def test_the_usb_receptacle_does_not_stick_out_of_the_case(name):
    """**USB-C のメスがケースの外へ出ていないこと。**

    2026-08-10 に実形状の総当たりで、メスが奥面から **0.26mm はみ出す**
    ことが分かった。**モデルの誤りではなく、完成品がそうなる。**
    飛び出したコネクタは抜き差しの外力を直に受け、もぎ取れる原因になる。

    はみ出し量は `WALL + DB_FROM_REAR` だけで決まる（コブを深くすると
    子基板も一緒に奥へ動くので `BUMP_DEPTH` は効かない）。

    ⚠️ **直し方に制約がある。子基板を前へ動かしてはいけない。**
    アンテナは XIAO の反対端にあり、本体基板の後端より 0.11mm 外に
    出ているだけ（#23）。前へ動かせばアンテナが基板の下へ戻る。
    だから `DB_FROM_REAR` を増やし、**同じだけコブを深くして**
    子基板の絶対位置を保っている。片方だけ動かすとどちらかが落ちる
    （もう片方は `test_the_antenna_is_no_longer_under_the_main_board`）。

    メスの寸法は KiCad の STEP の記録（`pcb_parts.usb_receptacle`）で、
    ケースの奥面は**実際に作った立体の bbox**から取る。
    """
    from gen_case import DB_FROM_REAR, USB_RECESS, WALL, build_case
    import pcb_parts

    rec = pcb_parts.load()["db"]
    out = pcb_parts.usb_receptacle()[4] - rec["board_bbox"][4]   # 板の端からの張り出し

    # ケースの奥面までの距離（子基板の奥端 → 壁の外面）
    room = WALL + DB_FROM_REAR
    assert out <= room - USB_RECESS + 1e-9, (
        f"{name}: USB-C のメスが奥面から {out - room:+.3f}mm 出る"
        f"（メスの張り出し {out:.3f} / 壁まで {room:.3f} / "
        f"引っ込めたい量 {USB_RECESS}）")

    # 作った立体でも確かめる。**定数の計算どうしの一致では検証にならない。**
    case, (_, h_body), _ = build_case(HALVES[name], name)
    from gen_case import BUMP_DEPTH
    outer = case.bounding_box().max.Y
    nominal = h_body / 2 + BUMP_DEPTH
    assert abs(outer - nominal) < 0.01, (
        f"{name}: ケースの奥面 {outer:.3f} が設計値 {nominal:.3f} と違う")
