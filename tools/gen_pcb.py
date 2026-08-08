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
# 取付穴は feec08b（上ケース方式）で廃止した。基板はプレートとスイッチで
# 一体になり、上下ケースに挟まれる。ボスは基板の外にある。
# 定数だけが使われないまま残っていたので消した。
DIODE_FP = ("Diode_SMD", "D_SOD-123")     # JLCPCB の基本部品 1N4148W が入る

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



# --------------------------------------------------------------------------
# 配線の寸法
#
# **配線そのものはここではやらない。**Freerouting に委ねる
# （tools/autoroute.py）。ここで持つのは、自動配線器へ渡す値だけ。
#
# 手書きのルータは削除した。衝突判定を持たないので任意のネット対を
# 短絡させ、それは経路の調整では 0 にならなかった。経緯は
# docs/superpowers/specs/2026-08-08-pcb-autoroute-design.md。
#
# **この 3 つは _apply_jlcpcb_rules がネットクラスに書き込む。**
# 自動配線器はネットクラスしか見ないので、ここが唯一の出どころ。
# --------------------------------------------------------------------------
TRACK_W = 0.2           # JLCPCB の最小 0.127mm に対して余裕を見た値
VIA_D, VIA_DRILL = 0.6, 0.3
# --------------------------------------------------------------------------
# JLCPCB の製造能力を、基板の設計規則として書き込む。
#
# **これが無い間、DRC は KiCad の既定値で通していただけだった。**
# 「違反 0 件」は「JLCPCB で製造できる」を意味していない。規則を入れて
# 初めて、線幅・ビア・アニュラリング・外形までの距離が能力の内側に
# あることを機械が確かめられる。
#
# 値は JLCPCB の Capabilities（2層/4層・1oz・標準工程）から。
# 追加費用のかかる高精度オプションは使わない前提で、標準値を採る。
# --------------------------------------------------------------------------
JLC = {
    "track_min": 0.127,       # 最小線幅 5mil
    "clearance_min": 0.127,   # 最小クリアランス 5mil
    "via_dia_min": 0.45,      # 最小ビア外径
    "via_drill_min": 0.20,    # 最小ビアドリル
    "hole_min": 0.20,         # 最小 PTH ドリル
    "hole_to_hole": 0.50,     # 穴どうしの最小距離
    "edge_clearance": 0.30,   # 銅から基板外形までの最小距離
    "silk_width": 0.15,       # シルクの最小線幅
    "annular_ring": 0.13,     # 最小アニュラリング。KiCad 既定は 0.1 で足りない
}


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
    return board


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
    "74HC595": ("Package_SO", "TSSOP-16_4.4x5mm_P0.65mm"),
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
    # 残りは**左に分圧と電池、右に V3V3 の消費側と 595** と置けば、
    # 扇状の広がりが交差しない。
    #
    # 全部をひとつの帯（奥から 1 本目）に置く。帯をまたぐと配線が段を
    # 縦断して途中の穴と他のネットに当たる。
    "left": {
        # **鎖の順に並べる。**BT1 →(VBATT_RAW)→ SW_PWR →(VBATT_SW)→ D_PWR
        # →(と R_HI)→ R_LO →(VBATT_SENSE)→ J_DB。
        # 以前は R_HI/R_LO が SW_PWR と D_PWR の間にあり、VBATT_SW が
        # 2 部品を飛び越して他のネットと交差していた。
        # **J_DB はダイオード列を避けた隙間に置く。**
        #
        # 上段キーのダイオードは帯に 1.75mm 食い込み（y 61.55..66.25）、
        # 19.05mm ピッチで並ぶ。帯の部品の中で J_DB だけ背が高く
        # （y 65.175〜）、以前の x がちょうど D3 の列と重なっていた。
        # Freerouting に通したときの短絡・コートヤード重なり・ROW0 未配線は
        # 全部これが原因だった（実測）。D3..D4 の隙間へ動かし、玉突きで
        # C_BULK・C_MCU も少しだけ空ける。
        "BT1": (0, -62.0), "SW_PWR": (0, -50.0), "D_PWR": (0, -40.0),
        "R_HI": (0, -32.0), "R_LO": (0, -27.0),
        "J_DB": (0, -6.9),
        "C_BULK": (0, 2.5), "C_MCU": (0, 7.0),
        "U1": (0, 13.0), "C_U1": (0, 26.0),
    },
    "right": {
        "BT1": (0, -78.0), "SW_PWR": (0, -66.0), "D_PWR": (0, -56.0),
        "R_HI": (0, -48.0), "R_LO": (0, -43.0),
        "J_DB": (0, -23.5),
        "C_BULK": (0, -13.0), "C_MCU": (0, -5.0),
        "U1": (0, 4.0), "C_U1": (0, 16.0),
        "U2": (0, 30.0), "C_U2": (0, 42.0),
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


def _place_electronics(board, half, net):
    """回路に宣言された電子部品を、段の間の帯に置いてネットを割り当てる。"""
    from circuit import netlist
    decl = {ref: (kind, pins) for ref, kind, pins in netlist(half)}
    for ref, spec in PLACE[half].items():
        band, x = spec[0], spec[1]
        kind, pins = decl[ref]
        lib, name = ELEC_FP[kind]
        # **ケースの中で配線する部品は、基板側をランド 2 個で受ける。**
        # 電池ボックスと電源スイッチがこれ。どちらもリード線が生えていて、
        # 基板の上には載らない（電源スイッチは背面のパネルに付く。
        # 基板の後端から背面まで 23.3mm あり、基板上には置けない）。
        pin_order = list(pins)
        n = 2 if kind in WIRE_PAD_KINDS else 1
        for k in range(n):
            fp = _load(KICAD_FP / f"{lib}.pretty", name)
            fp.SetPosition(to_kicad(x + k * 4.0, BAND_Y[band]))
            fp.SetReference(ref if n == 1 else f"{ref}_{pin_order[k]}")
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
            if n == 2:
                fp.Pads()[0].SetNet(net(pins[pin_order[k]]))
        if n == 1:
            fp = board.FindFootprintByReference(ref)
            for pin, netname in pins.items():
                if netname == "NC":
                    continue
                pad = fp.FindPadByNumber(pin)
                if pad is not None:
                    pad.SetNet(net(netname))


def _pour(board, netitem, layer, w, h):
    """その層いっぱいにベタを敷く。"""
    zone = pcbnew.ZONE(board)
    zone.SetNet(netitem)
    zone.SetLayer(layer)
    zone.SetLocalClearance(pcbnew.FromMM(0.25))
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
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
    # **4 層。**行の引き回しが 2 層では通らない（通路が 1.65mm しかない）。
    # 経緯は docs/hardware/decisions/2026-08-07-four-layer.md。
    #   F.Cu   列のバス・信号
    #   In1.Cu GND ベタ（全面）
    #   In2.Cu 行の引き回し・電源
    #   B.Cu   ソケット・ダイオード・行のバス・部品
    board.SetCopperLayerCount(4)
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
        d.SetValue("1N4148W")
        board.Add(d)
        # **Flip は board.Add の後で呼ぶ。** 基板に属していない状態で反転すると
        # segfault する（実際に落とした）。
        d.Flip(d.GetPosition(), False)          # ソケットと同じ裏面へ
        sw = board.FindFootprintByReference(f"SW{i}")
        sw.FindPadByNumber("1").SetNet(net(f"COL{c}"))
        sw.FindPadByNumber("2").SetNet(net(f"SW{i}_D"))
        d.FindPadByNumber("2").SetNet(net(f"SW{i}_D"))   # アノード
        d.FindPadByNumber("1").SetNet(net(f"ROW{r}"))    # カソード

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
    prewire_switch_diode(board)
    _place_electronics(board, half, net)
    gnd_fanout.place(board)

    # 取付穴は**もう開けない。**
    #
    # 上ケース方式では、基板はプレートとスイッチで機械的に一体になり、
    # 上下のケースに挟まれて保持される。ネジは上ケースから、基板の外側
    # （y=±51.5、基板の縁 49.0 より外）にあるボスへ入る。
    # 基板に穴が要らないぶん、配線の自由度も上がる。

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
    _pour(board, net("GND"), pcbnew.In1_Cu, pcb_w, pcb_h)

    # **未配線のまま pcb/unrouted/ に出す。**
    # 配線済みの pcb/hhkb_split_*.kicad_pcb は autoroute.py が作る。
    (OUT / "unrouted").mkdir(parents=True, exist_ok=True)
    path = OUT / "unrouted" / f"hhkb_split_{half}.kicad_pcb"
    board.Save(str(path))
    rows, cols = shape(half)
    return (path, (pcb_w, pcb_h),
            (n_sw, n_stab, 0, rows, cols, len(nets)))


def main():
    keys_l, keys_r = split_halves(load_layout(str(ROOT / "layout/hhkb_split.json")))
    for half, keys in (("left", keys_l), ("right", keys_r)):
        path, (w, h), (n_sw, n_stab, n_hole, rows, cols, n_net) = build(half, keys)
        print(f"{half:5s} 基板 {w:7.2f} x {h:6.2f}mm  "
              f"スイッチ {n_sw} / ダイオード {n_sw} / スタビ {n_stab} / 取付穴 {n_hole}（不要）")
        print(f"      行列 {rows} 行 × {cols} 列 / ネット {n_net} 本")
        print(f"      {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
