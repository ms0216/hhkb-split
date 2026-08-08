"""GND のファンアウト（電子部品のパッド → 最寄りのビア）。

**GND は Freerouting に配線させない。ベタ（In1.Cu）で受ける。**
手書きルータの時代に効いていたのと同じ考え方。

なぜ要るか: GND のベタは In1.Cu の 1 層だけにあり、GND のパッドは
すべて B.Cu の SMD パッドなので、間をビアでつながないとベタに届かない。
ここを Freerouting 任せにすると、電子部品が詰まった区画でファンアウトが
失敗する（実測: 対応する SMD ピンの 42% しか成功しなかった）。

そこで配置の直後（`_place_electronics` の後）に、GND パッドの脇へ
決定的にビアを置いておく。**未配線の基板にビアが載っていることが大事。**
DSN 経由で Freerouting に「そこは通れない障害物」として伝わり、避けて
配線してくれる。

**向きは「支配軸」ではなく「パッドの長軸」で決める。**最初は縦横どちらか
広い方に単純に逃がそうとして失敗した（FFC の横並びパッドで隣の CS パッド
に刺さり、受動部品では隣の部品のパッドに接近した）。パッド自身の長軸
（幅と高さの大きい方。同寸なら y）に沿って、フットプリント中心から
遠ざかる側へ逃がすのが正解だった。

対象は電子部品（`ELEC`）の GND パッドのみ。**接頭辞での走査はしない**
（`D`/`SW` で拾うと電源部を巻き込む。この案件で 3 回起きた）。
"""

import pcbnew

from circuit import ELEC_REF as ELEC

# ビア半径 0.3mm + クリアランス 0.2mm + 余裕 0.05mm
CLEARANCE_MM = 0.55
STUB_WIDTH_MM = 0.2
VIA_DIAMETER_MM = 0.6
VIA_DRILL_MM = 0.3


def spots(board):
    """(パッド, ビアを置く mm 座標) の一覧。"""
    out = []
    for fp in board.GetFootprints():
        if not ELEC.fullmatch(fp.GetReference()):
            continue
        c = fp.GetPosition()
        for pad in fp.Pads():
            if pad.GetNetname() != "GND":
                continue
            q, s = pad.GetPosition(), pad.GetSize()
            long_y = s.y >= s.x  # パッドの長軸（同寸なら y）
            half = pcbnew.ToMM(s.y if long_y else s.x) / 2
            d = half + CLEARANCE_MM
            proj = (q.y - c.y) if long_y else (q.x - c.x)
            sign = 1.0 if proj >= 0 else -1.0
            x, y = pcbnew.ToMM(q.x), pcbnew.ToMM(q.y)
            vx, vy = (x, y + sign * d) if long_y else (x + sign * d, y)
            out.append((pad, (vx, vy)))
    return out


def place(board):
    """GND パッドごとにスタブとビアを置く。何個置いたかを返す。"""
    gnd = board.FindNet("GND")
    n = 0
    for pad, (vx, vy) in spots(board):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pad.GetPosition())
        t.SetEnd(pcbnew.VECTOR2I_MM(vx, vy))
        t.SetWidth(pcbnew.FromMM(STUB_WIDTH_MM))
        t.SetLayer(pcbnew.B_Cu)
        t.SetNet(gnd)
        board.Add(t)
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I_MM(vx, vy))
        v.SetWidth(pcbnew.FromMM(VIA_DIAMETER_MM))
        v.SetDrill(pcbnew.FromMM(VIA_DRILL_MM))
        v.SetNet(gnd)
        board.Add(v)
        n += 1
    return n
