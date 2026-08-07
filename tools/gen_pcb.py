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
MOUNT_FP = ("MountingHole", "MountingHole_2.2mm_M2")
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
# 配線
# --------------------------------------------------------------------------
TRACK_W = 0.2           # JLCPCB の最小 0.127mm に対して余裕を見た値。
                        # 列の通り道が 3.8mm しかないので 0.4mm 間隔で並べる必要があり、
                        # 0.25mm だと隣との隙間が 0.15mm になって既定の 0.2mm を割る。
VIA_D, VIA_DRILL = 0.6, 0.3
COL_VIA_DX = -1.8       # 列のビアを、ソケットのパッドからどれだけ左へ置くか

# 列のバスが行間で折れ曲がるときの通り道。**列ごとに高さをずらす。**
# 全部同じ高さにすると、行ずれのぶん横へ動く区間どうしが交差する。
#
# 通れる帯は狭い。スイッチの機械穴は非メッキ貫通穴なので表も裏もふさぐ。
# キー中心からの位置（KiCad 座標）で数えると:
#
#   ピン穴      y −6.61〜−3.55、−4.07〜−1.01
#   中央ポスト  y −2.00〜+2.00
#   位置決め    y −0.88〜+0.88
#   スタビ穴    y −8.50〜−5.46、**+6.23〜+10.22**
#   次の段のスタビ穴  +10.55〜+13.59
#
# → 確実に空いているのは **+2.2 〜 +6.0mm の 3.8mm** だけ。
#   ここに 0.4mm 間隔で並べれば 9 列（右半分）がちょうど収まる。
#
# 当初は行間の中央（+9.5 付近）に通していたが、そこはスタビの穴の帯で、
# DRC が hole_clearance を 5 件出した。
LANE_CENTER = 4.1       # キー中心からの距離（KiCad 座標・下向き）
LANE_SPACING = 0.4


def _track(board, p1, p2, layer, net):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(p1)
    t.SetEnd(p2)
    t.SetWidth(pcbnew.FromMM(TRACK_W))
    t.SetLayer(layer)
    t.SetNet(net)
    board.Add(t)


def _via(board, pos, net):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pos)
    v.SetWidth(pcbnew.FromMM(VIA_D))
    v.SetDrill(pcbnew.FromMM(VIA_DRILL))
    v.SetNet(net)
    board.Add(v)
    return v


def _pad(board, ref, num):
    return board.FindFootprintByReference(ref).FindPadByNumber(num)


def _route(board, positions, rc):
    """マトリクスを配線する。位置は生成済みのフットプリントから読む。"""
    mm = pcbnew.VECTOR2I_MM

    # 1. スイッチ → ダイオード（L 字 2 本、裏面）
    #    ソケットの端子 2 とダイオードのアノードは同じ x に並べてあるので、
    #    横へ 1 本・縦へ 1 本で届く。
    for i in range(1, len(positions) + 1):
        a = _pad(board, f"SW{i}", "2")
        b = _pad(board, f"D{i}", "2")
        net = a.GetNet()
        corner = pcbnew.VECTOR2I(b.GetPosition().x, a.GetPosition().y)
        _track(board, a.GetPosition(), corner, pcbnew.B_Cu, net)
        _track(board, corner, b.GetPosition(), pcbnew.B_Cu, net)

    # 2. 行のバス（裏面・水平）
    #    同じ行のキーは y が揃うので、カソードどうしを直線で結べる。
    rows = {}
    for i, (r, _) in enumerate(rc, start=1):
        rows.setdefault(r, []).append(_pad(board, f"D{i}", "1"))
    for r, pads in rows.items():
        pads.sort(key=lambda p: p.GetPosition().x)
        for p1, p2 in zip(pads, pads[1:]):
            _track(board, p1.GetPosition(), p2.GetPosition(),
                   pcbnew.B_Cu, p1.GetNet())

    # 3. 列のバス（表面・ビア経由）
    #
    # **段を飛ばす列がある。** 右半分の列 2 は 行0 の次が 行2 で、行1 にキーが無い。
    # そこを縦一直線で結ぶと、行ずれのぶん途中の段の真ん中を突っ切り、
    # 位置決めポストに当たる（hole_clearance が出た）。
    # そこで **段の切れ目ごとに折れ曲がる**。各段では、その段の中で物理的に
    # 最も近いキーの脇（＝安全な通り道）を通す。
    cols = {}
    for i, (r, c) in enumerate(rc, start=1):
        cols.setdefault(c, []).append((r, _pad(board, f"SW{i}", "1")))
    n_cols = len(cols)

    # 段ごとの「キーの脇」の x 一覧（安全な通り道の候補）
    row_keys = {}
    for i, (r, _) in enumerate(rc, start=1):
        pos = board.FindFootprintByReference(f"SW{i}").GetPosition()
        row_keys.setdefault(r, []).append(pcbnew.ToMM(pos.x))
    row_y = {}
    for i, (r, _) in enumerate(rc, start=1):
        row_y[r] = pcbnew.ToMM(board.FindFootprintByReference(f"SW{i}").GetPosition().y)

    def corridor_x(r, near_x):
        """段 r の中で near_x に最も近いキーの脇を通る x。"""
        kx = min(row_keys[r], key=lambda x: abs(x - near_x))
        return kx - 7.085 + COL_VIA_DX

    # 機械穴（非メッキ貫通穴）の一覧。表も裏もふさぐので、縦に抜けるときは
    # これを避ける必要がある。位置は生成済みの基板から読む（推測しない）。
    holes = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                q = pad.GetPosition()
                holes.append((pcbnew.ToMM(q.x), pcbnew.ToMM(q.y),
                              pcbnew.ToMM(pad.GetSize().x) / 2))

    def vertical_is_clear(x, y0, y1, margin=0.45):
        """x を通る縦線が y0〜y1 の範囲で穴に当たらないか。"""
        lo, hi = min(y0, y1), max(y0, y1)
        for hx, hy, hr in holes:
            if lo - hr <= hy <= hi + hr and abs(hx - x) < hr + margin:
                return False
        return True

    def find_clear_x(near, y0, y1):
        """near の近くで、縦に抜けられる x を探す。見つからなければ None。"""
        for d in [i * 0.1 for i in range(0, 61)]:
            for cand in ((near - d), (near + d)):
                if vertical_is_clear(cand, y0, y1):
                    return round(cand, 2)
        return None

    for c, entries in cols.items():
        entries.sort(key=lambda t: t[1].GetPosition().y)
        lane = (c - (n_cols - 1) / 2) * LANE_SPACING
        vias = []
        for r, p in entries:
            pos = p.GetPosition()
            vp = mm(pcbnew.ToMM(pos.x) + COL_VIA_DX, pcbnew.ToMM(pos.y))
            _track(board, pos, vp, pcbnew.B_Cu, p.GetNet())
            vias.append((r, _via(board, vp, p.GetNet()), vp))
        for (ra, v1, p1), (rb, v2, p2) in zip(vias, vias[1:]):
            net = v1.GetNet()
            x1, y1 = pcbnew.ToMM(p1.x), pcbnew.ToMM(p1.y)
            x2, y2 = pcbnew.ToMM(p2.x), pcbnew.ToMM(p2.y)
            lane_a = row_y[ra] + LANE_CENTER + lane
            if rb == ra + 1:
                # 隣り合う段。通り道を 1 本使うだけで届く。
                pts = [(x1, y1), (x1, lane_a), (x2, lane_a), (x2, y2)]
            else:
                # 段を飛ばす。途中の段を縦に抜けられる x を探してから渡る。
                lane_b = row_y[rb - 1] + LANE_CENTER + lane
                sx = find_clear_x(x1, lane_a, lane_b)
                if sx is None:
                    raise RuntimeError(
                        f"列 {c}: 段 {ra}→{rb} を縦に抜ける経路が見つからない")
                pts = [(x1, y1), (x1, lane_a), (sx, lane_a),
                       (sx, lane_b), (x2, lane_b), (x2, y2)]
            for a, b in zip(pts, pts[1:]):
                if a != b:
                    _track(board, mm(*a), mm(*b), pcbnew.F_Cu, net)


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
_SOCK_MID = (7.2 + (-2.6)) / 2
BAND_Y = [28.575 + _SOCK_MID, 9.525 + _SOCK_MID,
          -9.525 + _SOCK_MID, -28.575 + _SOCK_MID]

ELEC_FP = {
    "74HC595": ("Package_SO", "SOIC-16_3.9x9.9mm_P1.27mm"),
    "cap_100n": ("Capacitor_SMD", "C_0805_2012Metric"),
    "cap_100u": ("Capacitor_SMD", "C_1206_3216Metric"),
    "res_1M": ("Resistor_SMD", "R_0805_2012Metric"),
    "schottky": ("Diode_SMD", "D_SOD-123"),
    "ffc_12p": ("Connector_FFC-FPC",
                "Hirose_FH12-12S-0.5SH_1x12-1MP_P0.50mm_Horizontal"),
    # スライドスイッチは 9.78x4.72mm。段の間の 9.25mm 帯に収まる
    "slide_switch": ("Button_Switch_SMD",
                     "SW_DIP_SPSTx01_Slide_9.78x4.72mm_W8.61mm_P2.54mm"),
    "battery_holder": ("TestPoint", "TestPoint_Pad_2.0x2.0mm"),
}

# 参照名 → (帯の番号, 帯の中での x)。**手前の帯に電源、奥の帯に論理。**
# 電源スイッチは手前＝手が届く側に置く。
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
        "BT1": (0, -62.0), "SW_PWR": (0, -50.0),
        "R_HI": (0, -40.0), "R_LO": (0, -35.0), "D_PWR": (0, -28.0),
        "J_DB": (0, -16.0),
        "C_BULK": (0, -2.0), "C_MCU": (0, 6.0),
        "U1": (0, 20.0, -1.8), "C_U1": (0, 32.0),
    },
    "right": {
        "BT1": (0, -78.0), "SW_PWR": (0, -66.0),
        "R_HI": (0, -56.0), "R_LO": (0, -51.0), "D_PWR": (0, -44.0),
        "J_DB": (0, -32.0),
        "C_BULK": (0, -18.0), "C_MCU": (0, -10.0),
        "U1": (0, 4.0, -1.8), "C_U1": (0, 16.0),
        "U2": (0, 30.0, -1.8), "C_U2": (0, 42.0),
    },
}


def _place_electronics(board, half, net):
    """回路に宣言された電子部品を、段の間の帯に置いてネットを割り当てる。"""
    from circuit import netlist
    decl = {ref: (kind, pins) for ref, kind, pins in netlist(half)}
    for ref, spec in PLACE[half].items():
        # 3 つ目は帯の中での y の微調整（省略可）。
        # **SOIC-16 は縦 10.4mm あり、帯 9.25mm からはみ出して
        # 行のバスに寄る。**回転させると配線の順序が崩れて悪化したので
        # （24→144 件）、位置で逃がす。
        band, x = spec[0], spec[1]
        dy = spec[2] if len(spec) > 2 else 0.0
        kind, pins = decl[ref]
        lib, name = ELEC_FP[kind]
        # 電池線は 2 箇所のランドとして置く
        n = 2 if kind == "battery_holder" else 1
        for k in range(n):
            fp = _load(KICAD_FP / f"{lib}.pretty", name)
            fp.SetPosition(to_kicad(x + k * 4.0, BAND_Y[band] + dy))
            fp.SetReference(ref if n == 1 else f"{ref}_{'+-'[k]}")
            fp.SetValue(kind)
            board.Add(fp)
            fp.Flip(fp.GetPosition(), False)
            if n == 2:
                pad = fp.Pads()[0]
                pad.SetNet(net(pins["+" if k == 0 else "-"]))
        if n == 1:
            fp = board.FindFootprintByReference(ref)
            for pin, netname in pins.items():
                if netname == "NC":
                    continue
                pad = fp.FindPadByNumber(pin)
                if pad is not None:
                    pad.SetNet(net(netname))


def _npth_holes(board):
    """非メッキ貫通穴（スイッチの機械穴）の一覧。**全層をふさぐ。**

    表・裏の配線では避けていたが、内層では避けていなかった。
    穴は層を選ばないので、内層でも同じ仕組みを通す必要がある。
    """
    out = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                q = pad.GetPosition()
                out.append((pcbnew.ToMM(q.x), pcbnew.ToMM(q.y),
                            pcbnew.ToMM(pad.GetSize().x) / 2))
    return out


def _fcu_verticals(board):
    """表面（F.Cu）の縦配線の x 一覧。

    **列のバスはここにいる。**穴だけ避けても、行のビアが列のバスに
    乗って短絡する。`_clear_x` に渡して避ける。
    """
    out = []
    for t in board.GetTracks():
        if t.Type() != pcbnew.PCB_TRACE_T or t.GetLayer() != pcbnew.F_Cu:
            continue
        a, b = t.GetStart(), t.GetEnd()
        if abs(a.x - b.x) < pcbnew.FromMM(0.05):
            out.append((pcbnew.ToMM(a.x),
                        pcbnew.ToMM(min(a.y, b.y)), pcbnew.ToMM(max(a.y, b.y))))
    return out


def _clear_x(holes, near, y0, y1, margin=0.6, used=(), keep=2.0,
             verticals=()):
    # keep は行の通路どうしの最小間隔。1.0/1.6/2.0/2.5 を試し、
    # 左右の合計が最小になる 2.0 を採った（左 23 / 右 37）。
    """near の近くで、y0〜y1 を縦に抜けられる x を探す。"""
    lo, hi = min(y0, y1), max(y0, y1)

    def ok(x):
        # **すでに使った通路から離す。**行ごとに別の x を使わないと、
        # 内層で縦配線どうしが重なって短絡する（14 件出た）。
        if any(abs(x - u) < keep for u in used):
            return False
        # 表面の縦配線（列のバス）にも乗らないこと
        if any(not (vy1 < lo or vy0 > hi) and abs(vx - x) < 0.8
               for vx, vy0, vy1 in verticals):
            return False
        return not any(lo - hr <= hy <= hi + hr and abs(hx - x) < hr + margin
                       for hx, hy, hr in holes)

    # 基板の幅ぶん探す。**80 ステップ（±20mm）では足りなかった。**
    # 最下段まで降りる行は、途中の段の穴をすべて避ける必要がある。
    for d in [i * 0.25 for i in range(0, 360)]:
        for cand in (near - d, near + d):
            if ok(cand):
                return round(cand, 2)
    return None


def _route_electronics(board, half, net):
    """電子部品を結線する。

    **GND はベタ（In1.Cu）で受ける。**各 GND パッドの脇にビアを 1 本立てる
    だけでよく、配線が要らない。これで結線するネットが大きく減る。

    残りは In2.Cu を使う。ここは行の引き回しと電源のために空けた層で、
    表（列のバス）とも裏（ソケットと行のバス）とも衝突しない。
    """
    mm = pcbnew.VECTOR2I_MM
    refs = [f.GetReference() for f in board.GetFootprints()]
    elec = [r for r in refs if r in PLACE[half] or r.startswith("BT1_")]

    pads = {}
    for fp in board.GetFootprints():
        if fp.GetReference() not in elec:
            continue
        for pad in fp.Pads():
            n = pad.GetNetname()
            if n:
                pads.setdefault(n, []).append(pad)

    # 1. GND はベタへ落とす
    for pad in pads.pop("GND", []):
        pos = pad.GetPosition()
        off = mm(pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y) + 1.8)
        _track(board, pos, off, pcbnew.B_Cu, pad.GetNet())
        _via(board, off, pad.GetNet())

    # 2. 行を各段のバスへ降ろす。**ここが 2 層では通らなかった箇所。**
    #    内層 2 を縦に降り、スイッチの非メッキ穴を避ける x を選ぶ。
    holes = _npth_holes(board)
    verticals = _fcu_verticals(board)
    rows = {}
    for fp in board.GetFootprints():
        if not re.fullmatch(r"D\d+", fp.GetReference()):
            continue
        pad = fp.FindPadByNumber("1")
        n = pad.GetNetname()
        if n.startswith("ROW"):
            rows.setdefault(n, []).append(pad)
    used_x = []
    for k, (name, cathodes) in enumerate(sorted(rows.items())):
        src = next((p for p in pads.get(name, [])), None)
        if src is None:
            continue
        tgt = min(cathodes, key=lambda p: abs(p.GetPosition().x - src.GetPosition().x))
        sx = pcbnew.ToMM(src.GetPosition().x)
        sy = pcbnew.ToMM(src.GetPosition().y)
        tx = pcbnew.ToMM(tgt.GetPosition().x)
        ty = pcbnew.ToMM(tgt.GetPosition().y)
        x = _clear_x(holes, sx, sy, ty, used=used_x, verticals=verticals)
        if x is None:
            raise RuntimeError(f"{name}: 内層を縦に抜ける経路が見つからない")
        used_x.append(x)
        # **コネクタのパッド列に沿って走らせない。**
        # 横に長く走ると、隣のパッドとレジストのアパーチャで橋を作る
        # （49.5mm の配線が 24 件のブリッジを出した）。
        # 直角に 1.6mm 離れてからビアで内層へ落とし、横移動は内層で行う。
        # **行ごとに高さをずらす。**同じ y に並べると、隣の行のビアと
        # 0.5mm（コネクタのピッチ）しか離れず当たる。
        oy = sy + (1 if ty > sy else -1) * (1.6 + k * 1.1)
        _track(board, src.GetPosition(), mm(sx, oy), pcbnew.B_Cu, src.GetNet())
        _via(board, mm(sx, oy), src.GetNet())
        _track(board, mm(sx, oy), mm(x, oy), pcbnew.In2_Cu, src.GetNet())
        _track(board, mm(x, oy), mm(x, ty), pcbnew.In2_Cu, src.GetNet())
        _via(board, mm(x, ty), src.GetNet())
        _track(board, mm(x, ty), tgt.GetPosition(), pcbnew.B_Cu, src.GetNet())
        pads.pop(name, None)

    # 3. 残りは In2.Cu で結ぶ。ネットごとに y のレーンをずらす。
    for i, (name, group) in enumerate(sorted(pads.items())):
        group = sorted(group, key=lambda p: p.GetPosition().x)
        if name.startswith("COL"):
            continue                      # 列は 4 で別に扱う
        for a, b in zip(group, group[1:]):
            # **レーンはネットごとに固有にする。**6 本で使い回していて
            # 重なっていた（違反 29/49 件）。帯は 9.25mm あるので足りる。
            # **帯の中（±3.4mm）に均等に配る。**上限で頭打ちにすると
            # 複数のネットが同じ y に重なる（V3V3 と VBATT_SENSE が 10 件）。
            _link(board, a, b, lane=-3.2 + (i % 9) * 0.8)

    # 4. 595 の出力を列のバスへ。列のバスは表（F.Cu）にあるので、
    #    In2 で近くまで運んでからビアで表へ上げる。
    k = 0
    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        if not fp.GetReference().startswith("U"):
            continue
        for pad in fp.Pads():
            n = pad.GetNetname()
            if not n.startswith("COL"):
                continue
            target = _nearest_via(board, n, pad.GetPosition())
            if target is not None:
                _link(board, pad, target, lane=3.2 - (k % 9) * 0.7,
                      to_via=True)
                k += 1


def _nearest_via(board, netname, pos):
    """そのネットのビアのうち、pos に最も近いものの位置を返す。"""
    best, bd = None, None
    for it in board.GetTracks():
        if it.Type() != pcbnew.PCB_VIA_T or it.GetNetname() != netname:
            continue
        d = (it.GetPosition() - pos).EuclideanNorm()
        if bd is None or d < bd:
            best, bd = it.GetPosition(), d
    return best


def _link(board, a, b, lane, to_via=False):
    """2 点を In2.Cu で結ぶ（両端にビアを立てる）。"""
    mm = pcbnew.VECTOR2I_MM
    pa = a.GetPosition()
    pb = b if to_via else b.GetPosition()
    netitem = a.GetNet()
    ax, ay = pcbnew.ToMM(pa.x), pcbnew.ToMM(pa.y)
    bx, by = pcbnew.ToMM(pb.x), pcbnew.ToMM(pb.y)
    # **ビアはパッドの真上に置かない。**穴が重なって
    # 「穴のクリアランス 0.00mm」になる。少しずらして引き出す。
    # **引き出す距離もレーンに応じてずらす。**FFC のパッドは 0.5mm ピッチ
    # なので、同じ距離で引き出すとビアが横並びで当たる（V3V3 と
    # VBATT_SENSE が 10 件）。レーンと同じ順に離せば重ならない。
    d = 1.4 + (lane + 3.4) * 0.55
    va, vb = (ax, ay + d), (bx, by + d)
    _track(board, mm(ax, ay), mm(*va), pcbnew.B_Cu, netitem)
    _via(board, mm(*va), netitem)
    if not to_via:
        _track(board, mm(bx, by), mm(*vb), pcbnew.B_Cu, netitem)
        _via(board, mm(*vb), netitem)
    else:
        vb = (bx, by)
    # **横配線は帯（段と段の間）の中に収める。**パッドからの相対だと
    # 部品ごとのパッド位置のぶんはみ出し、スイッチの非メッキ穴を通る。
    band = min(BAND_Y, key=lambda b: abs((ORIGIN[1] - b) - ay))
    y = (ORIGIN[1] - band) + max(-3.4, min(3.4, lane))
    for p, q in ((va, (va[0], y)), ((va[0], y), (vb[0], y)), ((vb[0], y), vb)):
        if p != q:
            _track(board, mm(*p), mm(*q), pcbnew.In2_Cu, netitem)


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
    # 配線
    # ------------------------------------------------------------------
    # 層の使い分け:
    #   B.Cu  スイッチ→ダイオード、行のバス（パッドがすべて裏面にあるため）
    #   F.Cu  列のバス（行と直交するので別の層に逃がす）
    #
    # スイッチの機械穴（中央 φ4・位置決め φ1.75・ピン穴 φ3.05）は
    # **非メッキ貫通穴なので両面をふさぐ**。列を表に逃がしても避けて通る必要がある。
    _route(board, positions, rc)

    _place_electronics(board, half, net)
    _route_electronics(board, half, net)

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

    OUT.mkdir(exist_ok=True)
    path = OUT / f"hhkb_split_{half}.kicad_pcb"
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
