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
from matrix import assignments, shape                              # noqa: E402

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

# ダイオードをキー中心からどれだけずらして置くか（レイアウト座標・Y 上向き）。
#
# **スイッチのピン穴もソケットのパッドも、レイアウト座標では中心より「上」**に
# ある（KiCad の座標では下）。当初 +Y へ逃がしてしまい、機械穴と重なって
# DRC が npth_inside_courtyard を 27 件出した。下側は完全に空いている。
DIODE_OFFSET = (0.0, -7.0)


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


def build(half, keys):
    """片側ぶんの基板を作る。"""
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
        d.SetPosition(to_kicad(kx + DIODE_OFFSET[0], ky + DIODE_OFFSET[1]))
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
