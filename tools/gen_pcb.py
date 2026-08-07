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
