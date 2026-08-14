"""基板の外形・キー配置・取付穴を生成する（フェーズ D1）。

**KiCad に同梱の Python で動かす。** pcbnew は KiCad の Python にしか無い。

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/\\
        Versions/3.9/bin/python3.9 tools/gen_pcb.py

寸法の出どころは tools/interface.py（プレート・ケース・基板が共有する凍結境界）
と tools/layout.py（キー配列）。**このファイルは寸法を持たない。**
持たせるとプレートやケースとずれる（ネジ位置で実際にやらかした）。

座標系:
    layout / build123d は Y 上向き、KiCad は Y 下向き。変換は to_kicad() に集約する。
    基板の中心を KiCad 上の ORIGIN に置く。原点を 0,0 にすると座標が負になり、
    KiCad の GUI で扱いにくいため。
"""

import os
import re
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from interface import (
    PCB_INSET_Y,CORNER_R, PCB_INSET, boss_positions,        # noqa: E402
                       plate_positions, stab_offset_for)
from layout import load_layout, split_halves                       # noqa: E402
from matrix import assignments, keymap_order, shape                # noqa: E402
from bands import BAND_Y                                           # noqa: E402
from circuit import WIRE_PAD_KINDS                                 # noqa: E402
import gnd_fanout                                                   # noqa: E402
import pinmap                                                       # noqa: E402
# 設計規則の数値は **pcbnew を要らない側**（pcb_rules）に置いてある。
# 検査は母艦の venv（pcbnew 無し）から同じ値を読む。
from pcb_rules import (                                            # noqa: E402
    BESIDE_GAP, DECOUPLE_BESIDE, JLC, MIN_ISLAND_MM2, POWER_CLASSES,
    POWER_NETS, TRACK_W, VIA_D, VIA_DRILL)

# **銅の層。ここが唯一の出どころ。**層数を変えるときはここだけ直す。
# 2026-08-12 に 4 層（F/In1/In2/B）から 2 層に落とした（指摘 2）。
COPPER_LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)

# **GND ベタを敷く層。2 層なので両面とも。**
#
# 4 層のときは In1.Cu の 1 層を GND 専用にして、自動配線器に対して
# 「ここに信号を通すな」と全面予約できた（autoroute._protect_the_ground_plane）。
# 2 層では信号層と GND 層が同じ 2 枚を兼ねるので**予約はできない。**
# したがってベタは最初から配線を避けた歯抜けになる。
# その分断を繋ぎ直すのが gnd_fanout のスティッチングビア。
GND_POUR_LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)


KEYSWITCH_LIB = ROOT / "pcb/lib/keyswitch.pretty"
KICAD_FP = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints")
OUT = ROOT / "pcb"

# 基板の中心を置く KiCad 上の座標（mm）
ORIGIN = (150.0, 100.0)

# キー幅 → スイッチのフットプリント名
SWITCH_FP = {
    1.0: "SW_Hotswap_Kailh_MX_1.00u",
    1.5: "SW_Hotswap_Kailh_MX_1.50u",
    1.75: "SW_Hotswap_Kailh_MX_1.75u",
    2.25: "SW_Hotswap_Kailh_MX_2.25u",
    3.0: "SW_Hotswap_Kailh_MX_3.00u",
}
# スタビライザーの半間隔 → フットプリント名
STAB_FP = {11.938: "Stabilizer_Cherry_MX_2.00u", 19.05: "Stabilizer_Cherry_MX_3.00u"}
# 取付穴は feec08b（上ケース方式）で一度廃止したが、#36（2026-08-12・
# 本体基板に固定具が 1 つも無かった）で復活させた。左 6 / 右 8 箇所。
MOUNT_FP = ("MountingHole", "MountingHole_2.2mm_M2")  # M2 のバカ穴（#36）
DIODE_FP = ("Diode_SMD", "D_SOD-123")     # BAT46W（ショットキー）が入る

# ダイオードの置き場所（KiCad 座標・キー中心から mm）と向き。
#
# **縦置きにして、ソケットの端子 2（+5.842, -5.08）と同じ x に並べる。**
# こうすると スイッチ → ダイオード の配線が L 字 2 本で済む。
# 横置きだと 4 本必要で、しかも位置決めポストを避けて回り込む必要がある。
#
# x=7.0 を選んだ理由: 位置決めポスト（±5.08, 0 / φ1.75 → x 4.2〜5.96）を
# 避けつつ、キーの境界（±9.525）にも余裕を残せる。
#
# y=2.0（本体が y 0.35〜3.65 を占める）を選んだ理由: 中央ポスト（φ4 → y ±2）と
# 位置決めポスト（y ±0.875）を避け、行のバスを y=+3.65 に通せる。
#
# 当初は横置きで -Y 側へ置いていた。さらにその前は +Y 側に置いて機械穴と
# 重なり、DRC が npth_inside_courtyard を 27 件出した。
# x=7.3: 重なり禁止域が ±1.15 なので、位置決めポストの外周 5.955 を
#        避けるには 7.105 より外が要る。余裕を見て 7.3。
DIODE_OFFSET = (7.3, 2.0)     # KiCad 座標（Y 下向き）
DIODE_ANGLE = 90              # 縦置き


def to_kicad(x, y):
    """レイアウト座標（原点中心・Y 上向き・mm）を KiCad の座標へ。"""
    return pcbnew.VECTOR2I_MM(ORIGIN[0] + x, ORIGIN[1] - y)


def _load(lib_dir, name):
    fp = pcbnew.FootprintLoad(str(lib_dir), name)
    if fp is None:
        raise RuntimeError(f"フットプリントを読めない: {lib_dir} / {name}")
    return fp


def _rounded_rect_outline(board, w, h, r):
    """外形線を Edge.Cuts に引く。角は円弧で丸める。

    プレートと同じ角丸にする。ケースの内側に収まる形なので、
    ここが違うと基板がケースに入らない。
    """
    hw, hh = w / 2, h / 2
    segs = [
        ((-hw + r, -hh), (hw - r, -hh)),
        ((hw, -hh + r), (hw, hh - r)),
        ((hw - r, hh), (-hw + r, hh)),
        ((-hw, hh - r), (-hw, -hh + r)),
    ]
    for (x1, y1), (x2, y2) in segs:
        seg = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(to_kicad(x1, y1))
        seg.SetEnd(to_kicad(x2, y2))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(pcbnew.FromMM(0.1))
        board.Add(seg)
    corners = [(-hw + r, -hh + r), (hw - r, -hh + r), (hw - r, hh - r), (-hw + r, hh - r)]
    for i, (cx, cy) in enumerate(corners):
        arc = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
        # 角ごとに始点・中点・終点を与える（KiCad の円弧は 3 点で決まる）
        import math
        a0 = [180, 270, 0, 90][i]
        pts = []
        for t in (a0, a0 + 45, a0 + 90):
            rad = math.radians(t)
            pts.append((cx + r * math.cos(rad), cy + r * math.sin(rad)))
        # Y 上向きの角度で作ったので、そのまま to_kicad に渡せばよい
        arc.SetArcGeometry(to_kicad(*pts[0]), to_kicad(*pts[1]), to_kicad(*pts[2]))
        arc.SetLayer(pcbnew.Edge_Cuts)
        arc.SetWidth(pcbnew.FromMM(0.1))
        board.Add(arc)





def prewire_switch_diode(board):
    """スイッチ → ダイオードを裏面の L 字 2 本で結ぶ。**ビアを使わない。**

    ソケットの端子 2 とダイオードのアノードは同じ x に並べてある
    （DIODE_OFFSET はそのために選んだ値）。どちらも B.Cu の SMD なので、
    横 1 本・縦 1 本で届く。**経路に選択の余地が無い。**

    自動配線器に任せると、数 mm の接続のために内層へ往復してビアを
    2 個使う。実測で左 30 個・右 62 個がこれに費やされていた
    （右が多いのは列のバスが 9 本あって裏面が混むため）。
    ビアは穴あけ費用と信頼性の両方に効くので、ここは自分で引く。

    **autoroute.py も SES 取り込みのあとに呼ぶ。**取り込みは既存の配線を
    全部作り直すので、ここで引いたものが消えるため。
    """
    # **接頭辞で走査しない。**`SW` で拾うと電源のスライドスイッチ
    # （SW_PWR）を巻き込む。この案件で 4 回起きた事故。
    keys = sorted(int(m.group(1)) for m in
                  (re.fullmatch(r"SW(\d+)", fp.GetReference())
                   for fp in board.GetFootprints()) if m)
    for i in keys:
        a = board.FindFootprintByReference(f"SW{i}").FindPadByNumber("2")
        b = board.FindFootprintByReference(f"D{i}").FindPadByNumber("2")
        corner = pcbnew.VECTOR2I(b.GetPosition().x, a.GetPosition().y)
        for p, q in ((a.GetPosition(), corner), (corner, b.GetPosition())):
            if p == q:
                continue
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(p)
            t.SetEnd(q)
            t.SetWidth(pcbnew.FromMM(TRACK_W))
            t.SetLayer(pcbnew.B_Cu)
            t.SetNet(a.GetNet())
            board.Add(t)


def prewire_row_bus(board):
    """**行のバスを裏面の一直線で引く。**（2026-08-14・利用者の指摘）

    「ROW0 がなぜこんなにクネクネして表裏を行き来するのか。同じ面で
    横一直線にした方が絶対効率的では」——実測すると指摘のとおりだった:

        ROW0  222.2mm  ビア 7 本  区間 54
        ROW1  207.7mm  ビア 7 本  区間 27
        ROW4  148.3mm  ビア 0 本  区間  9  ← 片面で一直線

    **一直線が引けることは幾何が保証している。**同じ行のダイオードの
    K 側パッド（pad 1）は **y が完全に一致**しており（実測: 各行とも
    y の種類は 1 つ）、**全部が B.Cu の SMD**。行のライン上に
    スルーホールは 1 つも無い（ROW1 だけ J_DB のパッド 11 個が
    近いが、これらも SMD で同じ裏面）。

    `DIODE_OFFSET` の注記にある「行のバスを y=+3.65 に通せる」が
    最初からの設計意図で、守っていなかったのは自動配線器の側。

    ⚠️ **via_costs では直せない。**DSN に `(autoroute_settings)` を
    足すと左が未配線 66 本に壊れた（autoroute.py の冒頭を読むこと）。
    **自分で引くのが正しい道。**

    **autoroute.py も SES 取り込みのあとに呼ぶ**（取り込みが既存の
    配線を作り直すため）。DSN からは ROW\\d+ を外してあるので、
    Freerouting はここを避けて配線する。
    """
    rows = {}
    for fp in board.GetFootprints():
        if not re.fullmatch(r"D\d+", fp.GetReference()):
            continue
        pad = fp.FindPadByNumber("1")          # K 側＝行
        name = pad.GetNetname()
        if not name.startswith("ROW"):
            continue
        rows.setdefault(name, []).append(pad)

    n = 0
    for name, pads in sorted(rows.items()):
        pads.sort(key=lambda p: p.GetPosition().x)
        ys = {p.GetPosition().y for p in pads}
        # **揃っていることを確かめてから引く。**ずれていたら黙って
        # 斜めに引かず、気づけるように止める。
        if len(ys) != 1:
            raise RuntimeError(
                f"{name}: ダイオードの K 側が同じ y に並んでいない "
                f"（{sorted(pcbnew.ToMM(y) for y in ys)}）。"
                "DIODE_OFFSET か行の割り当てが変わった")
        for a, b_ in zip(pads, pads[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(a.GetPosition())
            t.SetEnd(b_.GetPosition())
            t.SetWidth(pcbnew.FromMM(TRACK_W))
            t.SetLayer(pcbnew.B_Cu)
            t.SetNet(a.GetNet())
            board.Add(t)
            n += 1
    return n


# **Freerouting が自力では見つけない経路への「中継ビア」**（2026-08-13）。
#
# COL8（SW17-SW31 間）は、パッド同士のクリアランスだけ見れば
# ST24（スタビライザー）の右穴の左側に幅 1.7mm の通路がある
# （手計算・DRC 双方で確認済み）。にもかかわらず Freerouting は
# 毎回この 1 本だけを配線し損ねた。
#
# 得られた部分配線を見ると、Freerouting は SW17 から**南（SW31 方向）
# への探索を一度も試みず**、北（既に混雑した領域）へ迷い込んで
# 力尽きていた。基板の物理的な制約ではなく、**探索ヒューリスティックが
# 局所解にはまった**もの。
#
# 対策は、2 点間の中間に同じネットのビアを 1 個置くこと。
# Freerouting にとっては「SW17→ビア」「ビア→SW31」という 2 つの
# 近距離問題に分割され、どちらも迷わず解ける（実測 5 回連続成功）。
#
# **副作用があった。**COL8 側にビアを足すと、無関係なはずの V3V3
# （D_PWR→J_DB、J_DB のパッド幅 0.30mm で元々ギリギリ）が
# 5 回連続で未配線になった。物理的な干渉ではなく、ビアの追加で
# Freerouting 内部の配線順序が変わり、際どいネットにしわ寄せが
# 行っただけと判断（座標を変えても同じネットが詰まった）。
# そこで V3V3 側にも中継ビアを足し、両立させた（2 回連続成功で確認）。
#
# **右基板専用。**左基板ではこの詰まりが起きていないので足さない。
GUIDE_VIAS = {
    # COL8: SW17(214.35,78.41) - SW31(219.12,116.51) 間。
    # ST24 右穴の左側の通路（x=223.2、実測クリアランス 1.0mm 以上）の中間。
    "COL8": (223.2, 91.5),
    # V3V3: D_PWR(95.65,69.12) - J_DB pad6(72.75,85.38) 間。
    # J_DB は 0.5mm ピッチの SMD で、隣のパッドとの隙間(0.2mm)にビアは
    # 物理的に入らない。パッド 6 の長辺の外側、真上ぎりぎりに置く。
    "V3V3": (72.75, 84.0),
}


def guide_vias(board, half):
    """詰まりが再現された経路に、Freerouting 向けの中継ビアを打つ。

    **消してはいけない。**探索の局所解を避けるためのヒントであって、
    決まりきった配線ではない。DSN からもネットごと外さない
    （PREWIRED に入れない）——Freerouting に「ここも経由候補」として
    普通に見せる必要がある。
    """
    if half != "right":
        return
    for netname, (x, y) in GUIDE_VIAS.items():
        n = board.FindNet(netname)
        if n is None:
            raise SystemExit(f"guide_vias: ネットが無い: {netname}")
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        via.SetWidth(pcbnew.FromMM(VIA_D))
        via.SetDrill(pcbnew.FromMM(VIA_DRILL))
        via.SetNet(n)
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        board.Add(via)


def _apply_jlcpcb_rules(board):
    d = board.GetDesignSettings()
    mm = pcbnew.FromMM
    d.m_TrackMinWidth = mm(JLC["track_min"])
    d.m_MinClearance = mm(JLC["clearance_min"])
    d.m_ViasMinSize = mm(JLC["via_dia_min"])
    d.m_ViasMinDrill = mm(JLC["via_drill_min"])
    d.m_MinThroughDrill = mm(JLC["hole_min"])
    d.m_HoleToHoleMin = mm(JLC["hole_to_hole"])
    d.m_CopperEdgeClearance = mm(JLC["edge_clearance"])
    d.m_SilkClearance = mm(JLC["silk_width"])
    d.m_ViasMinAnnularWidth = mm(JLC["annular_ring"])

    # **ネットクラスを明示する。**
    #
    # 上の m_* は「これを下回るな」という最小値であって、実際に何 mm で
    # 引くかを決めるのはネットクラス。ここを設定していなかったので、
    # KiCad の既定値（偶然 TRACK_W と同じ 0.2mm）で配線されていた。
    #
    # 自動配線器はネットクラスしか見ないので、既定値頼みにはできない。
    nc = d.m_NetSettings.GetDefaultNetclass()
    nc.SetTrackWidth(mm(TRACK_W))
    nc.SetClearance(mm(TRACK_W))       # 0.2mm。線幅と同じ
    nc.SetViaDiameter(mm(VIA_D))
    nc.SetViaDrill(mm(VIA_DRILL))

    # **電源用のネットクラスを足す**（指摘 8）。
    #
    # 自動配線器はネットクラスしか見ない。ここに登録しないと、
    # POWER_TRACK_W をいくら定義しても**1 本も太くならない**
    # （「設定しただけでは効いていない」——CLAUDE.md）。
    # 効いたかどうかは配線後に実測する
    # （test_pcb.test_power_nets_are_routed_with_the_wider_track）。
    _add_power_netclasses(d, mm)
    return board


def _add_power_netclasses(d, mm):
    """電源のネットクラスを作り、ネットを割り当てる。

    API は pcbnew を実際に叩いて確かめたもの（推測で書かない）。

        SetNetclass(name, netclass)
        SetNetclassPatternAssignment(pattern, netclass_name)
        RecomputeEffectiveNetclasses()

    **最後の Recompute を忘れると割り当てが効かない。**「設定しただけで
    効いていない」の典型で、太くしたつもりで細いまま出る。

    **クラスは複数作れる。**KiCad はそれを DSN にそのまま書き出し、
    Freerouting も受け取る（生の DSN を読んで確認済み）。
    """
    ns = d.m_NetSettings
    for name, (width, nets) in POWER_CLASSES.items():
        cls = pcbnew.NETCLASS(name)
        cls.SetTrackWidth(mm(width))
        cls.SetClearance(mm(TRACK_W))
        cls.SetViaDiameter(mm(VIA_D))
        cls.SetViaDrill(mm(VIA_DRILL))
        ns.SetNetclass(name, cls)
        for net in nets:
            ns.SetNetclassPatternAssignment(net, name)
    ns.RecomputeEffectiveNetclasses()


# 電子部品は**段と段の間**に置く。
#
# 当初は奥の帯（10.3mm）に置く計画だったが、取付ボスを基板の外へ出すために
# 基板の前後を詰めた結果、奥の帯は 3.40mm になり 595 も FFC も入らなくなった。
# 段の間なら 9.25mm x 全幅 の帯が 4 本ある。裏面はソケットとダイオードの
# 実装面なので、同じ面に置けば JLCPCB の実装が片面で済む。
# 帯の中心。**段と段の中間ではない。**
# ソケットの占有はキー中心に対して非対称（-2.6 〜 +7.2mm）なので、
# 中間に置くと 0.9mm ソケットに掛かる（実際に掛かって SW10_D などと
# 短絡した）。ソケットの中心ぶん 2.3mm ずらす。
# 定義は bands.py（BAND_H, BAND_Y）。生成側と検査側で共有する。

ELEC_FP = {
    # SOIC-16 はコートヤード 10.49mm で、帯 9.25mm に**入らない**。
    # 位置の微調整で逃がそうとしていたが、どちら側にはみ出すかを
    # 選んでいるだけだった。TSSOP-16 は 5.59mm で 3.66mm 余る。
    "74LVC595": ("Package_SO", "TSSOP-16_4.4x5mm_P0.65mm"),
    "cap_100n": ("Capacitor_SMD", "C_0805_2012Metric"),
    "cap_100u": ("Capacitor_SMD", "C_1206_3216Metric"),
    "res_1M": ("Resistor_SMD", "R_0805_2012Metric"),
    "schottky": ("Diode_SMD", "D_SOD-123"),
    "ffc_12p": ("Connector_FFC-FPC",
                "Hirose_FH12-12S-0.5SH_1x12-1MP_P0.50mm_Horizontal"),
    # **電源スイッチは基板に載らない。**背面のパネルに付けて配線で繋ぐ。
    # 基板の後端から背面まで 23.3mm あり、基板上のどこに置いても手が届かない
    # （open-gaps #17）。基板側はランド 2 個で受ける。
    "wire_pads": ("TestPoint", "TestPoint_Pad_2.0x2.0mm"),
    "battery_holder": ("TestPoint", "TestPoint_Pad_2.0x2.0mm"),
}


# 参照名 → (帯の番号, 帯の中での x)。
#
# **全部を帯 0（奥から 1 本目）に置く。**帯をまたぐと配線が段を縦断して
# 途中の穴と他のネットに当たる。
#
# 電源スイッチ（SW_PWR）はここに「ランド 2 個」として現れる。実物は
# ケース背面のパネルに付く（decisions/2026-08-08-power-switch.md）。
# 基板の後端から背面まで 23.3mm あり、基板上には置けない。
PLACE = {
    # **並びは FFC のピン順に合わせる。**子基板で効いたのと同じ考え方。
    #
    # FFC は裏面に付くので基板上では鏡像になり、左から右へ
    #   GND(12) ROW4 ROW3 ROW2 ROW1 ROW0(7) VBATT_SENSE(6) V3V3(5)
    #   MOSI(4) SCK(3) GND(2) CS(1)
    # の順に並ぶ。行は下（マトリクス）へ降りるので横の順序に関わらない。
    # 残りは**J_DB 側に分圧と電池、その反対側に V3V3 の消費側と 595**
    # と置けば、扇状の広がりが交差しない（2026-08-14 まで「左に電池、
    # 右に 595」と書いていたが、それだと左基板で J_DB が反対端に来る）。
    #
    # 全部をひとつの帯（奥から 1 本目）に置く。帯をまたぐと配線が段を
    # 縦断して途中の穴と他のネットに当たる。
    "left": {
        # **鎖の順に並べる。**BT1_-(GND) / SW_PWR_1 →(VBATT_SW)→ D_PWR
        # →(V3V3)→ 消費側。分圧 R_HI/R_LO は VBATT_SW から分岐する。
        #
        # **電池の + は基板を通らない**（スイッチへ直結・open-gaps #41）。
        # ランドは BT1_- と SW_PWR_1 の 2 個だけになった（前は 4 個）。
        #
        # ⚠️ **鎖は U1 の左（マイナス側）に置く。**2026-08-14 まで
        # BT1 が -62.0 で、整流点 D_PWR が板の左端にあるのに V3V3 の
        # 消費側（C_U1 11.6 / U1 13.6 / J_DB 63.3）は全部プラス側だった
        # （V3V3 の銅 132.4mm・VBATT_SENSE 109.8mm）。左側には V3V3 を
        # 必要とするものが何も無い。
        #
        # ⚠️ **プラス側へは出せない。**帯 0 は U1(12.6..20.4) と
        # 取付穴 H4(33.0..38.0) で分断されている。一度そこへ置いて
        # DRC 13 件・未配線 7 件を出した（R_HI が C_U1 と、D_PWR が U1 と
        # 重なった）。J_DB(63.0) が遠くに見えるのは帯 1 にいるため。
        #
        # ⚠️ **座標は手で試さず、コートヤードの幅から積む。**
        # ランドは 3.08mm、D_PWR は 4.80mm、R_HI/R_LO は 3.44mm。
        # H5 の右端(-19.01) から隙間 0.4mm で積むと下の値になり、
        # C_U1(8.87) の手前で 8mm 余る。
        "BT1": (0, -17.07), "SW_PWR": (0, -13.59), "D_PWR": (0, -9.25),
        "R_HI": (0, -4.73), "R_LO": (0, -0.89),
        # **J_DB は帯 1・x=63.0（子基板コネクタの直近）に置く**
        # （2026-08-13・利用者の提案「FFC を曲げなくていい位置に」）。
        #
        # 帯 0（電源鎖と同じ帯）に置くと、J_DB が帯高さの 86% を占め
        # （外接 7.95mm／帯 9.25mm）、5 本の行バスがその両脇の
        # 1.3mm の隙間を全部くぐる必要があった。未配線を 0 にできる
        # 帯 0 上の位置は無く（実測。ダイオード列の隙間・電源鎖の
        # 圧縮・分散を数十通り試した）、**帯をまたいで逃がして初めて
        # 未配線が 0〜2 まで減った。**
        #
        # x は総当たりで実測（45〜65 を 5mm 刻み、当たりの周辺をさらに
        # 詰めた）。63.0 が最良。子基板コネクタの中心 X は +59.5mm
        # （gen_case.daughterboard_x_center）で、63.0 はそこから 3.5mm
        # ——ほぼ真横に来る。
        #
        # ⚠️ **未配線の本数は DSN_CLEARANCE_MARGIN_UM（autoroute.py）と
        # 連動する。**左右で同じマージン値を使う制約（利用者の要望）の下、
        # 両方の DRC 違反 0 と未配線最小を両立する値が 15µm で、
        # そのとき左の未配線は 2 本（うち 1 本は COL1 の信号、
        # もう 1 本は GND ベタの浮島）。マージンを動かすとここも動く。
        "J_DB": (1, 63.0),
        # **C_BULK はここに無い。子基板へ移した**（open-gaps #41）。
        # C_U1 はここに書かない。**DECOUPLE_BESIDE が U1 から算出する。**
        "U1": (0, 16.5),
    },
    "right": {
        # 電池の + は基板を通らない（スイッチへ直結・open-gaps #41）。
        # ランドは BT1_-(GND) と SW_PWR_1(VBATT_SW) の 2 個だけ。
        # 右は J_DB(-77.5) と鎖が同じ側なので、元の位置のまま詰める。
        "BT1": (0, -74.0), "SW_PWR": (0, -70.0), "D_PWR": (0, -65.0),
        "R_HI": (0, -60.0), "R_LO": (0, -56.0),
        # **J_DB は帯 1・x=-77.5。**左と同じ理由（帯 0 に置くと未配線が
        # 3〜27 本残る）。右基板は列が 9 本あり 595 系が 2 個あるぶん
        # 帯 0 の混雑が左よりきつく、**0 まで詰め切れなかった。**
        # x を 0.5mm 刻みで再探索し、-77.5 で未配線 1 本まで減った
        # （M=15µm で 3 回実行して決定的）。残る 1 本（COL8-SW31、
        # 基板最遠端の列）は gnd_fanout の格子や周辺部品の再配置では
        # 解消しなかった（2026-08-13 に系統的に確認。故意に固定してみて
        # 毎回同じネットが落ちることを確かめた——揺れではなく構造的な残り）。
        # 子基板コネクタの中心 X は -76.2mm、-77.5 はそこから 1.3mm。
        "J_DB": (1, -77.5),
        # **C_BULK はここに無い。子基板へ移した**（open-gaps #41）。
        # U1 と U2 の間は C_U2 のぶん空けてある（DECOUPLE_BESIDE が埋める）。
        "U1": (0, 2.0), "U2": (0, 15.0),
    },
}



def _center_courtyard_in_band(fp, band):
    """コートヤードの中心が帯の中心へ来るよう、フットプリントを縦にずらす。"""
    for layer in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
        shape = fp.GetCourtyard(layer)
        if not shape.IsEmpty():
            break
    else:
        raise RuntimeError(f"{fp.GetReference()}: コートヤードが無い")
    bb = shape.BBox()
    mid = (bb.GetTop() + bb.GetBottom()) / 2
    want = pcbnew.FromMM(ORIGIN[1] - BAND_Y[band])
    pos = fp.GetPosition()
    fp.SetPosition(pcbnew.VECTOR2I(pos.x, int(pos.y + want - mid)))


def _courtyard_x_extent(fp):
    """コートヤードの x の範囲（mm）。無ければ外形の箱で代用する。"""
    for layer in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
        shape = fp.GetCourtyard(layer)
        if not shape.IsEmpty():
            bb = shape.BBox()
            return pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())
    bb = fp.GetBoundingBox(False, False)
    return pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetRight())


def _pad_with_net(fp, netname):
    """そのフットプリントで指定ネットに繋がっているパッド。無ければ None。"""
    for pad in fp.Pads():
        if pad.GetNetname() == netname:
            return pad
    return None


def _place_beside(board, cap_ref, ic_ref, band):
    """パスコンを IC の**電源ピンがある側**へ、触れない最短距離で寄せる。

    どちら側に置くかを手で書かない。**IC の V3V3 パッドが中心のどちら側に
    あるかを実際の座標から決める。**IC の向きを変えてもついてくる。

    寄せる先はコートヤードの縁 + BESIDE_GAP。DRC のコートヤード重なりを
    出さない最短の位置になる。
    """
    ic = board.FindFootprintByReference(ic_ref)
    cap = board.FindFootprintByReference(cap_ref)
    vcc = _pad_with_net(ic, "V3V3")
    if vcc is None:
        raise RuntimeError(
            f"{ic_ref} に V3V3 のパッドが無い。パスコンをどちら側に置くか"
            "決められない（ネットの割り当てが先に済んでいる必要がある）")

    side = 1.0 if vcc.GetPosition().x >= ic.GetPosition().x else -1.0
    ic_l, ic_r = _courtyard_x_extent(ic)
    cap_l, cap_r = _courtyard_x_extent(cap)
    cx = pcbnew.ToMM(cap.GetPosition().x)
    # コートヤードは原点に対して対称とは限らないので、縁からの寸法で測る
    if side > 0:
        want_left = ic_r + BESIDE_GAP
        dx = want_left - cap_l
    else:
        want_right = ic_l - BESIDE_GAP
        dx = want_right - cap_r
    cap.SetPosition(pcbnew.VECTOR2I_MM(cx + dx,
                                       pcbnew.ToMM(cap.GetPosition().y)))
    _center_courtyard_in_band(cap, band)

    # **コンデンサの V3V3 側のパッドが IC を向いているか。**
    # 逆を向いていると、わざわざ寄せた意味が半分になる（電流が部品を
    # 回り込む）。向いていなければ 180 度回す。
    p_v3 = _pad_with_net(cap, "V3V3")
    p_gnd = _pad_with_net(cap, "GND")
    if p_v3 is not None and p_gnd is not None:
        toward_ic = (p_v3.GetPosition().x - p_gnd.GetPosition().x) * side < 0
        if not toward_ic:
            cap.SetOrientationDegrees(cap.GetOrientationDegrees() + 180)


def _place_electronics(board, half, net):
    """回路に宣言された電子部品を、段の間の帯に置いてネットを割り当てる。"""
    from circuit import netlist
    decl = {ref: (kind, pins) for ref, kind, pins in netlist(half)}

    # 置く場所の一覧。**パスコンは PLACE に座標を持たない**（手で書いた
    # 座標が 17mm ずれていたのが指摘 6 の原因）。いったん相手の IC と
    # 同じところに出し、ネットを塗り終えてから _place_beside が寄せる。
    spots = dict(PLACE[half])
    for cap_ref, ic_ref in DECOUPLE_BESIDE.items():
        if cap_ref in decl and ic_ref in spots:
            spots[cap_ref] = spots[ic_ref]

    for ref, spec in spots.items():
        band, x = spec[0], spec[1]
        kind, pins = decl[ref]
        lib, name = ELEC_FP[kind]
        # **ケースの中で配線する部品は、基板側をランド 2 個で受ける。**
        # 電池ボックスと電源スイッチがこれ。どちらもリード線が生えていて、
        # 基板の上には載らない（電源スイッチは背面のパネルに付く。
        # 基板の後端から背面まで 23.3mm あり、基板上には置けない）。
        pin_order = list(pins)
        # **数は宣言した端子の数から取る。**2 に決め打ちしていたが、
        # 2026-08-14 に BT1 が 1 端子（GND だけ）・SW_PWR が 1 端子
        # （VBATT_SW だけ）になった（電池 + はスイッチへ直結して基板を
        # 通らない）。決め打ちのままだとネットの無いランドが余る。
        n = len(pins) if kind in WIRE_PAD_KINDS else 1
        for k in range(n):
            fp = _load(KICAD_FP / f"{lib}.pretty", name)
            fp.SetPosition(to_kicad(x + k * 4.0, BAND_Y[band]))
            # **接尾辞は端子の数に関わらず付ける。**「どの端子か」を
            # 表すものなので、1 個になっても `BT1_-` のまま。
            # 数で分けると、端子が 1 個になった瞬間に `BT1` へ化けて
            # 回路図の配置表・board_refs・検査が一斉にずれる。
            wire = kind in WIRE_PAD_KINDS
            fp.SetReference(f"{ref}_{pin_order[k]}" if wire else ref)
            fp.SetValue(kind)
            board.Add(fp)
            fp.Flip(fp.GetPosition(), False)
            # **原点ではなくコートヤードを帯の中心に合わせる。**
            #
            # フットプリントのコートヤードは原点に対して対称とは限らない
            # （FFC コネクタは 0.95mm ずれていて、帯から 0.275mm はみ出していた）。
            # 原点を中心に置くと、部品ごとに違う量だけずれる。
            # ここで揃えておけば、部品ごとの手当て（dy）が要らなくなる。
            _center_courtyard_in_band(fp, band)
            if wire:
                # ランド 1 個につき 1 ネット。**数ではなく種類で分ける**
                # （端子が 1 個になっても経路は同じ）。
                fp.Pads()[0].SetNet(net(pins[pin_order[k]]))
        if kind not in WIRE_PAD_KINDS:
            fp = board.FindFootprintByReference(ref)
            for pin, netname in pins.items():
                if netname == "NC":
                    continue
                # **ピン名をパッド番号に直してから引く。**
                #
                # circuit.py は名前（VCC / MR / A / K）で宣言し、
                # フットプリントは番号（1..16）でパッドを持つ。
                # ここを直接 FindPadByNumber(pin) に渡していたので、
                # 74LVC595 の 16 パッドと D_PWR の 2 パッドが**ネット無しの
                # まま基板になっていた**（2026-08-12 発見）。
                # 列を駆動する回路と電源経路が丸ごと欠けていたのに、
                # DRC 0 件・未配線 0 件で緑だった。
                pad_no = pinmap.resolve(kind, pin)
                if pad_no is None:
                    continue          # 回路図だけにあるピン（XIAO の BAT）
                pad = fp.FindPadByNumber(pad_no)
                # **見つからなければ落とす。**以前はここが
                # `if pad is not None:` で、黙って飛ばしていた。
                if pad is None:
                    raise RuntimeError(
                        f"{ref}({kind}) のピン {pin} = パッド {pad_no} が "
                        f"フットプリント {lib}:{name} に無い。"
                        "pinmap.py かフットプリントのどちらかが間違っている")
                pad.SetNet(net(netname))

    # **パスコンを IC へ寄せるのは、ネットを塗り終えたあと。**
    # どちら側へ寄せるかを V3V3 パッドの位置から決めるので、
    # ネットが付いていないと決められない。
    for cap_ref, ic_ref in DECOUPLE_BESIDE.items():
        if cap_ref in decl and ic_ref in PLACE[half]:
            _place_beside(board, cap_ref, ic_ref, PLACE[half][ic_ref][0])


def _pour(board, netitem, layers, w, h):
    """指定した層いっぱいに GND のベタを敷く。

    **2 層なので両面に敷く**（指摘 3）。配線やビアが載っているところは
    KiCad が自動でよけるので、「配線を避けた歯抜けのベタ」になる。
    その歯抜けで分断された島を繋ぎ直すのが gnd_fanout のスティッチングビア。

    `layers` は単層でも並びでも受ける。
    """
    if isinstance(layers, int):
        layers = (layers,)
    for layer in layers:
        zone = pcbnew.ZONE(board)
        zone.SetNet(netitem)
        zone.SetLayer(layer)
        zone.SetLocalClearance(pcbnew.FromMM(0.25))
        # **サーマルリリーフを使わずベタ付けにする。**リフロー実装なので
        # 手はんだの熱の逃げを気にする必要が無く、GND のインピーダンスは
        # 低いほどよい。
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        # **浮いた銅は 1 つも残さない。**
        #
        # 2 層では配線がベタを割るので、GND のどこにも触れない区画が
        # できる。そういう銅は**電位が決まっておらず、GND ではない**——
        # 遮蔽の役に立たず、囲んでいる配線どうしを容量結合させ、
        # 2.4GHz では寸法次第で再放射する。
        #
        # **取り得る手は常に 2 つあり、どちらかは必ず選べる。**
        #
        #   1. 繋ぐ  ビアが入るなら（gnd_fanout.stitch_islands）
        #   2. 消す  ビアが入らないなら、その銅を残す理由が無い ← ここ
        #
        # **残さなければならない場面は無いので、0 を必達にする。**
        # 一時「面積のしきい値より小さいものだけ消す」にしていたが、
        # それは**問題を解かずに一部だけ隠す**やり方だった。
        #
        # ⚠️ 以前 ALWAYS にしたとき J_DB の GND パッドが切れた
        # （2026-08-12）。原因は**当時そのパッドにファンアウトビアが
        # 立てられていなかった**こと。パッドを含む区画は「繋がっている」
        # と判定されるので消えない。全 GND パッドにビアが立つように
        # なった今は前提が変わっている。**それでも DRC の未配線が
        # 増えていないかを毎回確かめること。**
        zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        pts = pcbnew.VECTOR_VECTOR2I()
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pts.append(pcbnew.VECTOR2I_MM(ORIGIN[0] + dx * w / 2,
                                          ORIGIN[1] + dy * h / 2))
        zone.AddPolygon(pts)
        board.Add(zone)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


def build(half, keys):
    """片側ぶんの基板を作る。"""
    # **キーマップ順に並べ替えてから使う。**
    # layout.split_halves は x 順（列方向）で返すので、そのまま
    # matrix-transform と突き合わせると 61 キー全部の割り当てを取り違える
    # （実際にやった。詳しくは matrix.keymap_order の説明）。
    keys = keymap_order(keys)
    positions, (plate_w, plate_h) = plate_positions(keys)
    pcb_w = plate_w - PCB_INSET * 2
    pcb_h = plate_h - PCB_INSET_Y * 2

    board = pcbnew.CreateEmptyBoard()
    _apply_jlcpcb_rules(board)
    # **2 層。**（2026-08-12。指摘 2。経緯は decisions/2026-08-07-four-layer.md
    # の冒頭の追記）
    #
    #   F.Cu   信号（旧 In2.Cu ぶん）＋ GND ベタ
    #   B.Cu   ソケット・ダイオード・部品・信号 ＋ GND ベタ
    #
    # 4 層にしたときの根拠は「行の引き回しが 2 層では通らない」だったが、
    # その後 Freerouting に切り替えて配線をやり直したときに、
    # **信号は実際には 2 層（In2.Cu と B.Cu）に収まっていた。**F.Cu は
    # ビアのランドだけで配線 0 本、まるごと空いていた（実測）。
    # 決定記録がその事実に追いついていなかった。
    #
    # **部品は全部 B.Cu 側のまま。**JLCPCB は片面実装と両面実装で
    # 段取り費が倍（$25 → $50）違い、しかも安い枠（Economic PCBA）は
    # 片面限定なので、実装面は動かさない。動かすのは銅箔だけ。
    board.SetCopperLayerCount(2)
    _rounded_rect_outline(board, pcb_w, pcb_h, CORNER_R)

    # スイッチ
    n_sw = n_stab = 0
    for i, ((kx, ky), k) in enumerate(zip(positions, keys), start=1):
        name = SWITCH_FP.get(k.w_u)
        if name is None:
            raise RuntimeError(f"{k.w_u}u のスイッチ用フットプリントが未定義")
        fp = _load(KEYSWITCH_LIB, name)
        fp.SetPosition(to_kicad(kx, ky))
        fp.SetReference(f"SW{i}")
        fp.SetValue(k.label or f"{k.w_u}u")
        board.Add(fp)
        n_sw += 1
        s = stab_offset_for(k.w_u)
        if s is not None:
            st = _load(KEYSWITCH_LIB, STAB_FP[s])
            st.SetPosition(to_kicad(kx, ky))
            st.SetReference(f"ST{i}")
            board.Add(st)
            n_stab += 1

    # 裏面のシルクにキー名を入れる。
    #
    # ソケットもダイオードも裏面に付くので、**組み立てる人が見るのは裏面**。
    # そこに SW1 のような通し番号しか無いと、どのキーか分からないまま
    # 61 個を半田付けすることになる。実機で「このキーだけ反応しない」と
    # なったときも、名前が刷ってあれば探す手間が要らない。
    for (kx, ky), k in zip(positions, keys):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(k.label)
        t.SetPosition(to_kicad(kx, ky + 8.2))
        t.SetLayer(pcbnew.B_SilkS)
        t.SetMirrored(True)
        t.SetTextSize(pcbnew.VECTOR2I_MM(1.1, 1.1))
        t.SetTextThickness(pcbnew.FromMM(0.18))
        board.Add(t)

    # ダイオードとマトリクスのネット
    #
    # 行と列の割り当ては tools/matrix.py がファームウェアの matrix-transform から
    # 読む。**基板とファームで別々に持つと、いつか片方だけ直して破綻する。**
    #
    # col2row なので、電流は 列 → スイッチ → ダイオード → 行 と流れる。
    # ダイオードのアノードが列側、カソード（KiCad の D_SOD-123 では pad 1）が行側。
    nets = {}

    def net(name):
        if name not in nets:
            n = pcbnew.NETINFO_ITEM(board, name)
            board.Add(n)
            nets[name] = n
        return nets[name]

    rc = assignments(half)
    for i, ((kx, ky), (r, c)) in enumerate(zip(positions, rc), start=1):
        d = _load(KICAD_FP / f"{DIODE_FP[0]}.pretty", DIODE_FP[1])
        d.SetPosition(pcbnew.VECTOR2I_MM(ORIGIN[0] + kx + DIODE_OFFSET[0],
                                         ORIGIN[1] - ky + DIODE_OFFSET[1]))
        d.SetOrientationDegrees(DIODE_ANGLE)
        d.SetReference(f"D{i}")
        d.SetValue("BAT46W")
        board.Add(d)
        # **Flip は board.Add の後で呼ぶ。** 基板に属していない状態で反転すると
        # segfault する（実際に落とした）。
        d.Flip(d.GetPosition(), False)          # ソケットと同じ裏面へ
        # **パッド番号は pinmap から引く。**ここで直に "1" / "2" と書くと、
        # 回路図側（同じ pinmap を読む）と静かにずれる。
        sw = board.FindFootprintByReference(f"SW{i}")
        sw.FindPadByNumber(pinmap.resolve("keyswitch", "1")).SetNet(net(f"COL{c}"))
        sw.FindPadByNumber(pinmap.resolve("keyswitch", "2")).SetNet(net(f"SW{i}_D"))
        d.FindPadByNumber(pinmap.resolve("diode", "A")).SetNet(net(f"SW{i}_D"))
        d.FindPadByNumber(pinmap.resolve("diode", "K")).SetNet(net(f"ROW{r}"))

    # ------------------------------------------------------------------
    # 配線はここではやらない
    # ------------------------------------------------------------------
    # **このファイルは配置・ネット・ゾーン・設計規則だけを持つ。**
    # 配線は tools/autoroute.py が Freerouting に委ねる。
    #
    # 例外は**決まりきった局所配線**の 2 つだけ。どちらも経路に選択の
    # 余地が無く、自動配線器に任せると却って悪くなる。DSN からはネットごと
    # 外し、配線材は (type protect) で「避けるべき障害物」として渡す。
    #
    #   1. スイッチ → ダイオード（prewire_switch_diode）
    #   2. GND のパッド → ベタ（tools/gnd_fanout.py）
    #   3. 行のバス（prewire_row_bus・2026-08-14）
    prewire_switch_diode(board)
    # **行のバスはここで引く。**DSN からネットごと外すのではなく、
    # 引いた線を `(type protect)` の障害物として渡す（ROW は J_DB へ
    # 戻る 1 本だけ自動配線器に任せるので、ネットは外せない）。
    prewire_row_bus(board)
    _place_electronics(board, half, net)
    gnd_fanout.place(board)
    guide_vias(board, half)

    # 取付穴（open-gaps #36・2026-08-12）。
    #
    # **一度は「もう開けない」としていた。**上ケース方式では基板はプレートと
    # スイッチで一体になり、上下のケースに挟まれて保持される——という理屈
    # だったが、**測ったら挟まれていなかった。**ネジ 3 本は y=±51.5 で
    # 基板の縁（±48.7）より外にあり、**基板に触れてもいない。**下の支えも
    # 無く（床まで 3.0〜14.5mm）、保持はスイッチ 54 本のピンの摩擦だけ。
    # **スイッチを抜くとソケットのはんだに剥離力**がかかる。
    #
    # → **プレートの裏の柱へ、下からネジで締める。**穴の位置は
    # interface.pcb_mount_positions が正本（プレート・組み立てと共有）。
    from interface import pcb_mount_positions
    for i, (mx, my) in enumerate(pcb_mount_positions(half)):
        h = _load(KICAD_FP / f"{MOUNT_FP[0]}.pretty", MOUNT_FP[1])
        h.SetPosition(to_kicad(mx, my))
        h.SetReference(f"H{i}")
        board.Add(h)

    # シルクの線幅を製造能力まで太らせる。
    #
    # **全部品を置き終えてから実行する。** 以前ここがダイオードより前に
    # あり、61 個のダイオードだけ 0.12mm のまま残っていた。
    #
    # KiCad の標準フットプリントは 0.12mm で描かれているが、**JLCPCB の
    # シルク最小線幅は 0.15mm**。細いままだとかすれるか印字されない。
    # DRC はシルクの線幅を見ないので、これは自分で担保するしかない。
    silk = (pcbnew.F_SilkS, pcbnew.B_SilkS)
    for fp in board.GetFootprints():
        for it in fp.GraphicalItems():
            if it.GetLayer() in silk and it.GetWidth() < pcbnew.FromMM(JLC["silk_width"]):
                it.SetWidth(pcbnew.FromMM(JLC["silk_width"]))
        for fld in (fp.Reference(), fp.Value()):
            if fld.GetLayer() in silk:
                fld.SetTextThickness(max(fld.GetTextThickness(),
                                         pcbnew.FromMM(JLC["silk_width"])))

    # 左右の識別。**2 種類が届いて見分けがつかないと、組み立ても修理も誤る。**
    label = pcbnew.PCB_TEXT(board)
    label.SetText(f"HHKB Split  {half.upper()}")
    label.SetPosition(pcbnew.VECTOR2I_MM(ORIGIN[0], ORIGIN[1] + pcb_h / 2 - 3.0))
    label.SetLayer(pcbnew.B_SilkS)
    label.SetMirrored(True)
    label.SetTextSize(pcbnew.VECTOR2I_MM(2.5, 2.5))
    label.SetTextThickness(pcbnew.FromMM(0.3))
    board.Add(label)


    # GND ベタ（内層 1）。**分割の左右で 2.4GHz を至近距離で動かすので、
    # 基準電位が連続していることの価値が大きい。**
    # **禁止域を先に置く。**ベタを流す前・配線する前でないと意味がない。
    _pour(board, net("GND"), GND_POUR_LAYERS, pcb_w, pcb_h)

    # **未配線のまま pcb/unrouted/ に出す。**
    # 配線済みの pcb/hhkb_split_*.kicad_pcb は autoroute.py が作る。
    (OUT / "unrouted").mkdir(parents=True, exist_ok=True)
    path = OUT / "unrouted" / f"hhkb_split_{half}.kicad_pcb"
    board.Save(str(path))
    rows, cols = shape(half)
    return (path, (pcb_w, pcb_h),
            (n_sw, n_stab, len(pcb_mount_positions(half)), rows, cols, len(nets)))


def main():
    keys_l, keys_r = split_halves(load_layout(str(ROOT / "layout/hhkb_split.json")))
    for half, keys in (("left", keys_l), ("right", keys_r)):
        path, (w, h), (n_sw, n_stab, n_hole, rows, cols, n_net) = build(half, keys)
        print(f"{half:5s} 基板 {w:7.2f} x {h:6.2f}mm  "
              f"スイッチ {n_sw} / ダイオード {n_sw} / スタビ {n_stab} / 取付穴 {n_hole}")
        print(f"      行列 {rows} 行 × {cols} 列 / ネット {n_net} 本")
        print(f"      {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
