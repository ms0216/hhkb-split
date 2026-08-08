"""子基板を生成する。XIAO を載せてケース奥に置く小さな基板。

経緯は docs/hardware/decisions/2026-08-07-daughterboard.md。
HHKB のキー配列は本体基板をほぼ埋め尽くすので、XIAO (21x17.8mm) の
置き場所が無い。別基板に載せ、USB-C を実機と同じ奥面へ出す。

回路は tools/circuit.py の daughterboard_netlist() が唯一の出所。
ここはそれを読んで置くだけで、独自にネットを持たない。

**RESET のボタンは載せない。** XIAO nRF52840 は RST を外に出していない
（裏面のパッドは側面ピンの複製と BAT +/−、NFC だけ）。復旧はキー操作で行う。

KiCad の Python で走らせる:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/\\
  Versions/3.9/bin/python3.9 tools/gen_daughterboard.py
"""

import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import daughterboard_netlist  # noqa: E402
from gen_pcb import (  # noqa: E402
    CORNER_R, JLC, KICAD_FP, TRACK_W, VIA_D, VIA_DRILL, _apply_jlcpcb_rules,
    _load, _rounded_rect_outline,
)

def _track(board, p1, p2, layer, net):
    """配線を 1 本引く。

    **かつては gen_pcb にあった。**本体基板が Freerouting に移ったとき
    一緒に消してしまい、子基板の生成が壊れた（誰も再生成していなかったので
    しばらく気づかなかった）。**いま使うのは子基板だけ**なのでここへ移した。
    """
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(p1)
    t.SetEnd(p2)
    t.SetWidth(pcbnew.FromMM(TRACK_W))
    t.SetLayer(layer)
    t.SetNet(net)
    board.Add(t)


def _via(board, pos, net):
    """ビアを 1 個立てる。上の _track と同じ理由でここにある。"""
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pos)
    v.SetWidth(pcbnew.FromMM(VIA_D))
    v.SetDrill(pcbnew.FromMM(VIA_DRILL))
    v.SetNet(net)
    board.Add(v)
    return v


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pcb"
# **gen_pcb と同じ原点を使う。**外形を描く _rounded_rect_outline が
# gen_pcb.ORIGIN を参照しているので、ここだけ別の値にすると外形と部品が
# 50mm ずれる（レンダリングが空になって気づいた）。
from gen_pcb import ORIGIN  # noqa: E402

# 外形はケース側の造作と一致させる（tools/gen_case.py の DB_W / DB_D）。
DB_W, DB_D = 21.0, 32.0
DB_BOSS_POS = [(-8.0, -13.5), (8.0, 13.5)]

XIAO_FP = (ROOT / "pcb/lib/hhkb_split.pretty", "XIAO_nRF52840")

FFC_FP = ("Connector_FFC-FPC", "Hirose_FH12-12S-0.5SH_1x12-1MP_P0.50mm_Horizontal")
CAP_FP = ("Capacitor_SMD", "C_0805_2012Metric")
MOUNT_FP = ("MountingHole", "MountingHole_2.2mm_M2")


def to_kicad(x, y):
    """CAD 座標（Y 上向き＝奥）を KiCad 座標（Y 下向き）に直す。"""
    return pcbnew.VECTOR2I_MM(ORIGIN[0] + x, ORIGIN[1] - y)


def build():
    board = pcbnew.CreateEmptyBoard()
    _apply_jlcpcb_rules(board)
    _rounded_rect_outline(board, DB_W, DB_D, CORNER_R)

    nets = {}

    def net(name):
        if name not in nets:
            n = pcbnew.NETINFO_ITEM(board, name)
            board.Add(n)
            nets[name] = n
        return nets[name]

    parts = {ref: (kind, pins) for ref, kind, pins in daughterboard_netlist()}

    # XIAO。USB は CAD の +Y（奥）を向く。フットプリントの y=-7.62 側が
    # USB 端なので、回転させずに置けばそのまま奥を向く。
    #
    # **中央に置く。**奥へ寄せてアンテナを本体基板の下から出す案を検討したが、
    # USB の隙間 2.9mm が要るうえ奥側の取付穴が入らなくなり（帯 2.90mm、
    # M2 は 4.4mm 必要）、得られるのは 1.1mm だけだった。open-gaps #23。
    x = _load(*XIAO_FP)
    x.SetPosition(to_kicad(0, 0))
    x.SetReference("U_MCU")
    x.SetValue("XIAO nRF52840")
    board.Add(x)

    # FFC コネクタ（裏面）。**XIAO のパッド列の間に収める。**
    # 1.0mm ピッチ（幅 15mm）だと XIAO の THT パッド（x=±7.62）と重なる。
    # 0.5mm ピッチなら幅 9.3mm で、列の間の 13.5mm に収まる。
    j = _load(KICAD_FP / f"{FFC_FP[0]}.pretty", FFC_FP[1])
    j.SetPosition(to_kicad(0, -11.0))
    j.SetReference("J_MAIN")
    j.SetValue("FFC 12P 0.5mm")
    board.Add(j)
    j.Flip(j.GetPosition(), False)

    # パスコン（裏面）
    c = _load(KICAD_FP / f"{CAP_FP[0]}.pretty", CAP_FP[1])
    c.SetPosition(to_kicad(0, 11.0))
    c.SetReference("C_DB")
    c.SetValue("0.1uF")
    board.Add(c)
    c.Flip(c.GetPosition(), False)

    # 取付穴（ケースのボスと同じ位置）
    for i, (mx, my) in enumerate(DB_BOSS_POS, start=1):
        h = _load(KICAD_FP / f"{MOUNT_FP[0]}.pretty", MOUNT_FP[1])
        h.SetPosition(to_kicad(mx, my))
        h.SetReference(f"H{i}")
        board.Add(h)

    # ネットを割り当てる。**回路の宣言をそのまま使う。**
    for ref, (kind, pins) in parts.items():
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            raise RuntimeError(f"{ref} が基板に無い（回路には宣言されている）")
        for pin, netname in pins.items():
            if netname == "NC":
                continue
            pad = fp.FindPadByNumber(pin)
            if pad is None:
                raise RuntimeError(f"{ref} に端子 {pin} が無い")
            pad.SetNet(net(netname))

    _route(board)
    _pour_ground(board, net("GND"))

    OUT.mkdir(exist_ok=True)
    path = OUT / "hhkb_split_daughterboard.kicad_pcb"
    board.Save(str(path))
    return path, len(nets)


def _pour_ground(board, gnd):
    """裏面に GND のベタを敷く。

    **GND を配線から外せるのが効く。**12 本のうち 2 本が GND なので、
    ベタで受けるとファンアウトが 10 本になり、ピン順を素直にできる。
    2.4GHz の基準電位が安定する効果もある。
    """
    zone = pcbnew.ZONE(board)
    zone.SetNet(gnd)
    zone.SetLayer(pcbnew.B_Cu)
    zone.SetLocalClearance(pcbnew.FromMM(0.25))
    # **サーマルリリーフを使わずベタ付けにする。**
    # GND は放熱より接続の確実さと低インピーダンスを優先する。
    # リリーフのままだと FFC の GND パッドでスポークが 1 本しか取れず、
    # DRC が「接続が不完全」と出た。
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    pts = pcbnew.VECTOR_VECTOR2I()
    for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        pts.append(pcbnew.VECTOR2I_MM(ORIGIN[0] + dx * DB_W / 2,
                                      ORIGIN[1] + dy * DB_D / 2))
    zone.AddPolygon(pts)
    board.Add(zone)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


def _route(board):
    """FFC と XIAO を結ぶ。

    **ファンアウトの順序が要点。** FFC は基板の手前、XIAO のパッドは
    左右 2 列。手前から上がってくる配線は、**近いパッドへ行くものほど
    外側のレーン**を使う。そうすると、パッドへ抜ける横向きの枝が、
    まだ上へ伸びている他のレーンを横切らない。

    順序を無視して素直に結んだら、ネットどうしが 6 箇所で短絡した。

    縦のレーンは表面（F.Cu）。裏面は FFC とパスコンの実装面で、
    2 列のパッドの間しか通せず 12 本は入らない。
    """
    mm = pcbnew.VECTOR2I_MM
    j = board.FindFootprintByReference("J_MAIN")
    u = board.FindFootprintByReference("U_MCU")
    c = board.FindFootprintByReference("C_DB")

    # ネット名 → XIAO 側のパッド
    xiao = {}
    for pad in u.Pads():
        n = pad.GetNetname()
        if n:
            xiao.setdefault(n, []).append(pad)

    # 外側のレーンの x と間隔。
    # **6.9 だと XIAO のパッド列（原点から 7.62）に 0.72mm まで寄り、
    # ビアがパッドに当たる。**間隔 0.55 もビアの対角が 0.778mm で、
    # φ0.6 のビアどうしが 0.178mm しか離れない（規則は 0.2）。
    LANE0, LANE_STEP = 6.0, 0.7
    used = []

    for sign in (-1, +1):               # 左の列 / 右の列
        targets = []
        for pad in j.Pads():
            n = pad.GetNetname()
            # **GND はベタで受ける。**レーンを使わないので、ファンアウトの
            # 順序にも影響しない。これがピン順を素直にできた理由。
            if not n or n == "GND" or n not in xiao:
                continue
            for xp in xiao[n]:
                # **原点と比べる。**0 と比べていて、絶対座標の x は常に
                # 正なので全ネットが右の群に入っていた。
                if (pcbnew.ToMM(xp.GetPosition().x) < ORIGIN[0]) == (sign < 0):
                    targets.append((pcbnew.ToMM(xp.GetPosition().y), pad, xp))
        # FFC は手前（KiCad の +y）にある。手前に近いパッドから順に外側へ。
        targets.sort(key=lambda t: -t[0])
        for i, (ty, fpad, xpad) in enumerate(targets):
            # **絶対座標にする。**相対値のまま fx/ty（絶対）と混ぜていて、
            # 145.9mm の配線ができていた。DRC の「配線の長さ」が異常値だった
            # ことで気づいた。
            lane = ORIGIN[0] + sign * (LANE0 - i * LANE_STEP)
            fx = pcbnew.ToMM(fpad.GetPosition().x)
            fy = pcbnew.ToMM(fpad.GetPosition().y)
            tx = pcbnew.ToMM(xpad.GetPosition().x)
            net = fpad.GetNet()
            row = fy - (1.4 + i * LANE_STEP)  # 外側へ行くものほど手前で曲げる

            # 1. 裏面でファンアウト（縦 → 横）。**順序のおかげで交差しない。**
            #    先に曲がるのは外側のレーンへ行くもので、その横枝は
            #    まだ上へ伸びている他の縦線より外側にしか来ない。
            for a, b in (((fx, fy), (fx, row)), ((fx, row), (lane, row))):
                if a != b:
                    _track(board, mm(*a), mm(*b), pcbnew.B_Cu, net)
            _via(board, mm(lane, row), net)

            # 2. 表面で縦に走る（レーンごとに x が違うので交差しない）
            _track(board, mm(lane, row), mm(lane, ty), pcbnew.F_Cu, net)
            _via(board, mm(lane, ty), net)

            # 3. 裏面でパッドへ。**FFC のパッド列より外側なので、
            #    裏面の縦線とも交差しない。**
            _track(board, mm(lane, ty), mm(tx, ty), pcbnew.B_Cu, net)
            used.append(net.GetNetname())

    # GND のパッドはベタへ短く引き出す。**ベタの上にあるだけでは
    # 繋がったことにならない**（DRC が「未接続」と出た）。
    for pad in j.Pads():
        if pad.GetNetname() == "GND":
            pos = pad.GetPosition()
            out = pcbnew.VECTOR2I(pos.x, pos.y + pcbnew.FromMM(2.0))
            _track(board, pos, out, pcbnew.B_Cu, pad.GetNet())

    # パスコン。**GND 側はベタで受けるので配線しない。**
    # 両方を配線すると、GND の枝が基板を横断して他のネットと交差した。
    for pad in c.Pads():
        n = pad.GetNetname()
        if n == "GND" or n not in xiao:
            continue
        near = min(xiao[n], key=lambda p: (p.GetPosition() - pad.GetPosition()).EuclideanNorm())
        pa, pb = pad.GetPosition(), near.GetPosition()
        # **縦から曲げる。**横から曲げると、パッド列に沿って降りる途中で
        # 別の（ネットの無い）パッドを貫く。5V のパッドを貫いて短絡していた。
        corner = pcbnew.VECTOR2I(pa.x, pb.y)
        _track(board, pa, corner, pcbnew.B_Cu, pad.GetNet())
        _track(board, corner, pb, pcbnew.B_Cu, pad.GetNet())


def main():
    path, n_net = build()
    print(f"子基板 {DB_W} x {DB_D}mm / ネット {n_net} 本")
    print(f"      {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
