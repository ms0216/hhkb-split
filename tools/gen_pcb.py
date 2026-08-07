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

from interface import (CORNER_R, PCB_INSET, boss_positions,        # noqa: E402
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
TRACK_W = 0.25          # JLCPCB の最小 0.127mm に対して余裕を見た値
VIA_D, VIA_DRILL = 0.6, 0.3
COL_VIA_DX = -1.8       # 列のビアを、ソケットのパッドからどれだけ左へ置くか

# 列のバスが行間で折れ曲がるときの通り道。**列ごとに高さをずらす。**
# 全部同じ高さにすると、行ずれのぶん横へ動く区間どうしが交差する
# （tracks_crossing が 30 件出た）。
# 行間の空きは キー中心 +4.4 〜 +12.7mm。0.8mm 間隔なら 8 列まで収まる。
LANE_SPACING = 0.8


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
    #    行ずれのせいで同じ列でも x が揃わないので、行間の空きで折れ曲がる。
    cols = {}
    for i, (_, c) in enumerate(rc, start=1):
        cols.setdefault(c, []).append(_pad(board, f"SW{i}", "1"))
    n_cols = len(cols)
    for c, pads in cols.items():
        pads.sort(key=lambda p: p.GetPosition().y)
        vias = []
        for p in pads:
            pos = p.GetPosition()
            vp = mm(pcbnew.ToMM(pos.x) + COL_VIA_DX, pcbnew.ToMM(pos.y))
            _track(board, pos, vp, pcbnew.B_Cu, p.GetNet())
            vias.append((_via(board, vp, p.GetNet()), vp))
        lane = (c - (n_cols - 1) / 2) * LANE_SPACING
        for (v1, p1), (v2, p2) in zip(vias, vias[1:]):
            mid = (pcbnew.ToMM(p1.y) + pcbnew.ToMM(p2.y)) / 2 + lane
            c1 = mm(pcbnew.ToMM(p1.x), mid)
            c2 = mm(pcbnew.ToMM(p2.x), mid)
            net = v1.GetNet()
            _track(board, p1, c1, pcbnew.F_Cu, net)
            _track(board, c1, c2, pcbnew.F_Cu, net)
            _track(board, c2, p2, pcbnew.F_Cu, net)


def build(half, keys):
    """片側ぶんの基板を作る。"""
    # **キーマップ順に並べ替えてから使う。**
    # layout.split_halves は x 順（列方向）で返すので、そのまま
    # matrix-transform と突き合わせると 61 キー全部の割り当てを取り違える
    # （実際にやった。詳しくは matrix.keymap_order の説明）。
    keys = keymap_order(keys)
    positions, (plate_w, plate_h) = plate_positions(keys)
    pcb_w = plate_w - PCB_INSET * 2
    pcb_h = plate_h - PCB_INSET * 2

    board = pcbnew.CreateEmptyBoard()
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

    # 取付穴
    for i, (mx, my) in enumerate(boss_positions(half), start=1):
        h = _load(KICAD_FP / f"{MOUNT_FP[0]}.pretty", MOUNT_FP[1])
        h.SetPosition(to_kicad(mx, my))
        h.SetReference(f"H{i}")
        board.Add(h)

    OUT.mkdir(exist_ok=True)
    path = OUT / f"hhkb_split_{half}.kicad_pcb"
    board.Save(str(path))
    rows, cols = shape(half)
    return (path, (pcb_w, pcb_h),
            (n_sw, n_stab, len(boss_positions(half)), rows, cols, len(nets)))


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
