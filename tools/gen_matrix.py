"""**キーマトリクスだけを配線した基板を作る。**（2026-08-17・利用者の提案）

    「先にキーマトリクスの配線 **だけ** を行なって、それはもう機械で
     確定してしまう、と言うのはどうでしょう？何も配線されていない状態で
     キーマトリクスを配線すると綺麗になりますし、そこはずっと変わらない
     部分なので、毎回計算させる理由がないです」

    「U1 とか J_DB とか、キーとダイオード以外の配線は一旦無視して、
     キーとダイオードだけでやって」

**対象はキーとダイオードだけ。**U1 / U2 / J_DB へ向かう分は引かない。
したがって出来た基板は**未配線が残るのが正常**（MCU へ繋がっていない）。

    "$KPY" tools/gen_matrix.py        # pcb/matrix/ に出す

本番の pcb/ と tools/gen_pcb.py は触らない。
"""
import re
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from gen_pcb import prewire_row_bus, prewire_switch_diode   # noqa: E402
from pcb_rules import TRACK_W, VIA_D, VIA_DRILL             # noqa: E402

OUT = ROOT / "pcb" / "matrix"
UNROUTED = ROOT / "pcb" / "unrouted"

# **キーとダイオード以外の部品。**この部品に付くパッドは列の一員として
# 数えない（利用者「U1 とか J_DB とかは一旦無視して」）。
NOT_A_KEY = re.compile(r"U\d+|J_DB|SW_PWR|BT\d+|D_PWR|C\d+|R\d+|H\d+|ST\d+|MP\d+")

# **行を跨ぐ橋の、行の線からの逃げ（mm）。**
#
# ビアの端（VIA_D/2）と行の線の端（TRACK_W/2）が、クリアランス 0.2mm を
# 空けて並ぶのに要る距離。0.6/2 + 0.2 + 0.2/2 = 0.6。**丸めで下回らない
# ように少しだけ足す**（Freerouting ではなく自分で引くので固定値でよい）。
BRIDGE_DY = VIA_D / 2 + 0.25 + TRACK_W / 2

# **行のバスの「パッドの列」から下へ逃げる距離（mm）。**
#
# 行のバスは線 1 本ではなく、ダイオードの K 側パッド（SOD-123・
# 半対角 0.75mm）が並んだ列でもある。線だけ避けてパッドを擦ると
# DRC が落ちる。0.75 + クリアランス 0.25 + 線幅の半分 0.1 = 1.10。
# 余裕を見て 1.30。
PAD_LANE_DY = 1.30

# **横に走るレーンの間隔（mm）。**
#
# ⚠️ **列ごとに別の y を使う。**全部を同じ y に流すと、最下段で
# 隣の列と正面衝突する（左 COL1/COL3/COL5 が y=124.000 に重なって
# tracks_crossing 2 件。2026-08-17）。**自分の障害物だけ見て、
# 自分どうしを見ていなかった。**
LANE_PITCH = 0.55


def prewire_col_bus(board):
    """**列のバスを裏面で引き、行を跨ぐ瞬間だけ表へ潜る。**（2026-08-17）

    利用者の指摘 2 つから出来ている:

      「SW5, 11 のような列の経路を他のキーにも展開してほしい」
      「SW5, 11 も完璧ではない。F.Cu に潜る時間はもっと短くできるはず」

    **段のずれは完全に規則的**なので、全部を同じ形にできる（実測: 隣の
    段との dx は +9.525 / +4.763 / +9.525 の繰り返し、dy は常に +19.05）。
    SW5/SW11 が綺麗なのは幾何が特別だからではなく、器械がたまたま
    そこを素直に引いただけ。**だから展開できる。**

    ⚠️ **潜り自体は省けない。**一度「潜る必要が無い」と判断して DRC を
    32 件赤にした（2026-08-17）。**衝突検査に行のバスを入れていなかった**
    ため。行は B.Cu の横一直線を占めており、列も B.Cu なので、
    **全 21 ホップが例外なく行を 1 本ずつ跨ぐ**（実測）。2 層である以上
    どこかで表へ逃げるしかない。**検査対象に入っていない部品は、
    検査していないのと同じ。**

    省けるのは**潜っている長さ**の方。跨ぐ y は行のバスの 5 本しかなく
    既知なので、**跨ぐ直前で潜り、跨いだ直後に戻る**。潜りは行の線を
    挟んだ上下 BRIDGE_DY だけで、残りは全部裏を通る。

    形は「真下 → （行の手前でビア）→ 表を真下 → （行の先でビア）→
    真下 → 45° で横へ寄る → 真下」。横に寄る分は 45° に閉じ込めるので
    縦の通り道から外へはみ出さない。

    **引けないホップは引かない。**本物の障害物（スタビの穴・取付穴・
    U2 のパッド）に当たるものは Freerouting に残す——**黙って別の形に
    すると、揃っていないことに気づけなくなる。**

    **autoroute.py も SES 取り込みのあとに呼ぶ**（取り込みが既存の配線を
    作り直すため）。DSN では `(type protect)` の障害物として渡る。
    """
    import math

    clr = 0.25 + TRACK_W / 2
    holes = [(p.GetPosition().x / 1e6, p.GetPosition().y / 1e6,
              pcbnew.ToMM(p.GetDrillSizeX()) / 2)
             for fp in board.GetFootprints() for p in fp.Pads()
             if p.GetDrillSizeX() > 0]
    # **パッドの大きさは 1 つずつ持つ。**一律 1.25mm と決め打ちして
    # U2（半対角 0.764mm）の上を通し、DRC に短絡を 2 件出した（2026-08-17）。
    #
    # ⚠️ **ネット名が空のパッドを「無視してよい」と思わないこと。**
    # U2 の 1〜7 番は空だが**本物のパッド**で、跨げば短絡する。
    # 除外してよいのは**自分と同じネット**だけ。
    smd = [(p.GetPosition().x / 1e6, p.GetPosition().y / 1e6, p.GetNetname(),
            math.hypot(pcbnew.ToMM(p.GetSizeX()), pcbnew.ToMM(p.GetSizeY())) / 2)
           for fp in board.GetFootprints() for p in fp.Pads()
           if p.GetDrillSizeX() == 0 and pcbnew.B_Cu in p.GetLayerSet().CuStack()]
    # **行のバスの y。これを検査に入れ忘れて DRC を 32 件赤にした。**
    # 既に引かれている B.Cu の線から取る（定数を別に持たない）。
    row_y = sorted({t.GetStart().y / 1e6 for t in board.GetTracks()
                    if t.GetClass() == "PCB_TRACK"
                    and t.GetNetname().startswith("ROW_")})

    def _clear(ax, ay, bx, by, net, layer):
        """穴・他ネットの裏パッド・行のバスに当たらないか。"""
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy

        def d(px, py):
            t = 0 if ll == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / ll))
            return math.dist((ax + t * dx, ay + t * dy), (px, py))
        if any(d(hx, hy) < r + clr for hx, hy, r in holes):
            return False
        if layer != pcbnew.B_Cu:
            return True                      # 表は行もパッドも居ない
        if any(d(sx, sy) < clr + half for sx, sy, n, half in smd if n != net):
            return False
        # 行のバス（横一直線）との距離。跨いだら当然アウト
        lo, hi = min(ay, by), max(ay, by)
        return not any(lo - clr < ry < hi + clr for ry in row_y)

    cols = {}
    for fp in board.GetFootprints():
        # **接頭辞で走査しない。**`SW` は電源スイッチ（SW_PWR）を巻き込む。
        if not re.fullmatch(r"SW\d+", fp.GetReference()):
            continue
        pad = fp.FindPadByNumber("1")
        if pad.GetNetname().startswith("COL"):
            cols.setdefault(pad.GetNetname(), []).append(pad)

    n = vias = skipped = 0
    _why = []
    for lane_i, (name, pads) in enumerate(sorted(cols.items())):
        pads.sort(key=lambda p: p.GetPosition().y)
        for a, b_ in zip(pads, pads[1:]):
            ax, ay = a.GetPosition().x / 1e6, a.GetPosition().y / 1e6
            cx, cy = b_.GetPosition().x / 1e6, b_.GetPosition().y / 1e6
            knee = abs(cy - ay) - abs(cx - ax)
            # ⚠️ **ここで `knee < 0` を弾かないこと。**形 C' は横が縦より
            # 長い場合のために書いてあるのに、その手前で return していて
            # **一度も呼ばれていなかった**（左 COL3/COL5。2026-08-17）。
            # 形 A / B は自分の条件で弾くので、ここでの門は要らない。
            crossed = [ry for ry in row_y if ay < ry < cy]
            if len(crossed) != 1:             # 想定は 1 本ちょうど
                skipped += 1
                _why.append((name, f'跨ぐ行 {len(crossed)} 本'))
                continue
            ry = crossed[0]

            # **形は 2 通り試す。**橋は必ず「縦に降りている区間」に置く
            # （斜めの上に置くと橋まで斜めになり、揃わない）。
            #
            #   A: 縦に降りる → 45° で寄る → 縦        跨ぎが上寄りのとき
            #   B: 45° で寄る → 縦に降りる            跨ぎが下寄りのとき
            #
            # 片方しか試さないと、跨ぎが斜めに掛かるホップを取りこぼす
            # （左 COL1 SW20→SW25 が実際にそうだった。2026-08-17）。
            shapes = []
            if ay + BRIDGE_DY < ry < ay + knee - BRIDGE_DY:
                shapes.append([                       # A
                    (ax, ay, ax, ry - BRIDGE_DY, pcbnew.B_Cu),
                    (ax, ry - BRIDGE_DY, ax, ry + BRIDGE_DY, pcbnew.F_Cu),
                    (ax, ry + BRIDGE_DY, ax, ay + knee, pcbnew.B_Cu),
                    (ax, ay + knee, cx, cy, pcbnew.B_Cu),
                ])
            # B は先に 45° で cx まで寄ってから、cx の縦線で跨ぐ
            by = ay + abs(cx - ax)                    # 斜めを終えた y
            if by + BRIDGE_DY < ry < cy - BRIDGE_DY:
                shapes.append([                       # B
                    (ax, ay, cx, by, pcbnew.B_Cu),
                    (cx, by, cx, ry - BRIDGE_DY, pcbnew.B_Cu),
                    (cx, ry - BRIDGE_DY, cx, ry + BRIDGE_DY, pcbnew.F_Cu),
                    (cx, ry + BRIDGE_DY, cx, cy, pcbnew.B_Cu),
                ])
            # E: **下のキーの x で降ろし、横移動は上のキーの側でやる。**
            #
            # 最下段は幅広キー（Alt / Meta 1.5u / L-Space 3.0u）なので、
            # **キーの中心が自分の列から大きく外れている**（左 COL5 の
            # L-Space は 24mm ずれ）。上のキーから真下に降ろすと、
            # 下のキーまで長い横断になる（実測: 最下段 3 本で 164.44mm）。
            #
            # ⚠️ **これは配線ではなく割り当ての問題**（open-gaps #46）。
            # dtsi が「キーの真上を通らない列」を選んでいる。ファームを
            # 直せば消えるが、それは後日なので**配線側で短くしておく**
            # （2026-08-17・利用者「とりあえず配線を」）。
            #
            # 上のキーの側（行の上）で横に寄せてから、下のキーの x で
            # まっすぐ降ろす。横移動が行の上に収まるので、下は素直な縦。
            up_lane = ry - PAD_LANE_DY - lane_i * LANE_PITCH
            if ay + BRIDGE_DY < up_lane and up_lane > ay:
                shapes.append([                       # E
                    (ax, ay, ax, up_lane, pcbnew.B_Cu),
                    (ax, up_lane, cx, up_lane, pcbnew.B_Cu),
                    (cx, up_lane, cx, ry - BRIDGE_DY, pcbnew.B_Cu),
                    (cx, ry - BRIDGE_DY, cx, ry + BRIDGE_DY, pcbnew.F_Cu),
                    (cx, ry + BRIDGE_DY, cx, cy, pcbnew.B_Cu),
                ])
            # C: **その場で真下に降りて跨ぎ、横移動は行の下でやる。**
            #
            # 最下段の 3 本（左 COL1/COL3/COL5）はこれでないと引けない。
            # 行 122.7 が 2 つのキーのちょうど間にあり、45° の斜めが
            # 行を跨いでしまうため（形 A も B も橋が斜めに乗る）。
            # さらに COL3/COL5 は横移動（28.575 / 23.812mm）が縦
            # （19.05mm）より大きく、**45° 1 回では届かない**。
            #
            # 降りる → 橋 → 45° で寄る → 縦、の順にすると、横移動が
            # どれだけ長くても行の下側だけで処理できる。
            if ay + BRIDGE_DY < ry < cy - BRIDGE_DY:
                dy_left = cy - (ry + BRIDGE_DY)       # 行の下に残る縦の余裕
                run = abs(cx - ax)
                if dy_left >= run:                    # 45° が収まる
                    ky = cy - run                     # 斜めを始める y
                    # 斜めの開始が行のパッド列に近すぎないこと
                    if ky >= ry + PAD_LANE_DY + lane_i * LANE_PITCH:
                        shapes.append([               # C
                            (ax, ay, ax, ry - BRIDGE_DY, pcbnew.B_Cu),
                            (ax, ry - BRIDGE_DY, ax, ry + BRIDGE_DY, pcbnew.F_Cu),
                            (ax, ry + BRIDGE_DY, ax, ky, pcbnew.B_Cu),
                            (ax, ky, cx, cy, pcbnew.B_Cu),
                        ])
                if True:
                    # D: **跨いだ直後にレーンで横へ寄り、そのあと降りる。**
                    #
                    # C は「斜めを cy - run から始める」ので、**縦の区間が
                    # 元の列の x に長く残る**。そこにスタビの穴があると
                    # 通れない（左 COL0 SW13→SW19。ST19 の穴が x=90.437 と
                    # 列の x=90.528 のほぼ真上にある）。
                    # 先に横へ逃げてから降りれば、その x を離れられる。
                    lane_d = ry + PAD_LANE_DY + lane_i * LANE_PITCH
                    if lane_d < cy - abs(cx - ax):
                        ky2 = cy - abs(cx - ax)
                        shapes.append([               # D
                            (ax, ay, ax, ry - BRIDGE_DY, pcbnew.B_Cu),
                            (ax, ry - BRIDGE_DY, ax, ry + BRIDGE_DY, pcbnew.F_Cu),
                            (ax, ry + BRIDGE_DY, ax, lane_d, pcbnew.B_Cu),
                            (ax, lane_d, cx, lane_d + abs(cx - ax), pcbnew.B_Cu),
                            (cx, lane_d + abs(cx - ax), cx, cy, pcbnew.B_Cu),
                        ]) if lane_d + abs(cx - ax) <= cy else None
                if dy_left < run:
                    # **横が縦より長い。**45° を 1 回では届かないので、
                    # 行の下で横に走ってから 45° で降りる。
                    #
                    # ⚠️ **横に走る y は、行のダイオードの下まで下げる。**
                    # `ry + BRIDGE_DY`（＝123.35）で走ると、行の K 側
                    # パッド（y=122.7・半対角 0.75）まで 0.65mm しか無く、
                    # 必要な 1.10mm を満たさない。**行のバスは線だけでなく
                    # パッドの列でもある**——線を避けても、パッドを擦る
                    # （左 COL1/COL3/COL5 が全部これで落ちていた）。
                    lane = ry + PAD_LANE_DY + lane_i * LANE_PITCH
                    # ⚠️ **符号に注意。**横に走るのを「行き過ぎて戻る」形に
                    # しないこと。45° で降りる分（cy - lane）だけ **cx の
                    # 手前で止める**。逆向きに取ると目標を追い越してから
                    # 戻ってくる（左 COL3 が x=117.1 まで行って 135.8 へ
                    # 戻り、18.7mm 無駄にしていた。2026-08-17）。
                    kx = cx - (cy - lane) * (1 if cx > ax else -1)
                    shapes.append([                   # C'
                        (ax, ay, ax, ry - BRIDGE_DY, pcbnew.B_Cu),
                        (ax, ry - BRIDGE_DY, ax, ry + BRIDGE_DY, pcbnew.F_Cu),
                        (ax, ry + BRIDGE_DY, ax, lane, pcbnew.B_Cu),
                        (ax, lane, kx, lane, pcbnew.B_Cu),
                        (kx, lane, cx, cy, pcbnew.B_Cu),
                    ])
            if not shapes:
                skipped += 1
                _why.append((name, '跨ぎが斜めに掛かる'))
                continue

            # **短い順に試す。**定義順に試すと、たまたま先に書いた形が
            # 勝って長い経路が残る（最下段で C が E に勝っていた）。
            def _len(cand):
                return sum(math.dist((x1, y1), (x2, y2))
                           for (x1, y1, x2, y2, _l) in cand)
            path = None
            for cand in sorted(shapes, key=_len):
                # ⚠️ **引数の順を間違えない。**seg の末尾は層なので、
                # `_clear(*seg, name)` だと層と net が入れ替わり、
                # 「表なので検査不要」の枝に落ちて**パッドを一切見なくなる**
                # （右で U2 の上を通し、DRC に短絡 2 件。2026-08-17）。
                if not all(_clear(x1, y1, x2, y2, name, layer)
                           for (x1, y1, x2, y2, layer) in cand):
                    continue
                # 橋のビアは、跨ぐ行以外の行からも離れていること
                vx = next(x1 for (x1, _a, _b, _c, l) in cand if l == pcbnew.F_Cu)
                if any(abs(ry2 - vy) < VIA_D / 2 + 0.25 + TRACK_W / 2
                       for vy in (ry - BRIDGE_DY, ry + BRIDGE_DY)
                       for ry2 in row_y if ry2 != ry):
                    continue
                path = cand
                break
            if path is None:
                skipped += 1
                _why.append((name, '障害物'))
                continue
            # **橋の x は F.Cu の区間から取る。**`path[1]` 決め打ちだと
            # 橋が 2 番目に無い形（E）でビアが別の場所に落ちる。
            vx = next(x1 for (x1, _y1, _x2, _y2, layer) in path
                      if layer == pcbnew.F_Cu)
            for (x1, y1, x2, y2, layer) in path:
                if (x1, y1) == (x2, y2):
                    continue
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(pcbnew.VECTOR2I_MM(x1, y1))
                t.SetEnd(pcbnew.VECTOR2I_MM(x2, y2))
                t.SetWidth(pcbnew.FromMM(TRACK_W))
                t.SetLayer(layer)
                t.SetNet(a.GetNet())
                board.Add(t)
                n += 1
            for vy in (ry - BRIDGE_DY, ry + BRIDGE_DY):
                v = pcbnew.PCB_VIA(board)
                # **橋の x を使う。**`ax` 決め打ちだと形 B（先に 45° で
                # 寄る形）でビアだけ元の列に取り残される。
                v.SetPosition(pcbnew.VECTOR2I_MM(vx, vy))
                v.SetWidth(pcbnew.FromMM(VIA_D))
                v.SetDrill(pcbnew.FromMM(VIA_DRILL))
                v.SetNet(a.GetNet())
                # **層の対を明示する。**忘れると KiCad が「片側しか
                # 繋がっていないビア」と見なし、via_dangling が出る
                # （2026-08-17。guide_vias は最初から書いていた）。
                v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                board.Add(v)
                vias += 1
    for _n, _r in _why:
        print(f'      引かなかった: {_n} … {_r}')
    return n, vias, skipped



def build(half):
    src = UNROUTED / f"hhkb_split_{half}.kicad_pcb"
    board = pcbnew.LoadBoard(str(src))
    # **既存の配線を全部消してから引き直す。**「何も配線されていない
    # 状態でキーマトリクスを配線すると綺麗になる」が提案の要点なので、
    # まっさらから始める。
    # ⚠️ **board.Remove を使わない。**SWIG がフットプリントの反復子まで
    # 壊し、次の GetFootprints() が SwigPyObject を返すようになる（実測）。
    for t in list(board.GetTracks()):
        board.Delete(t)
    prewire_switch_diode(board)
    n_row = prewire_row_bus(board)
    n_col, n_via, n_skip = prewire_col_bus(board)
    # **ベタを塗り直す。**配線を消して引き直したので、GND ゾーンは
    # 古い形のまま。塗り直さないと自分のビアと重なって、DRC が
    # クリアランス違反を 204 件出す（実測 2026-08-17）。
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    OUT.mkdir(exist_ok=True)
    dst = OUT / f"hhkb_split_{half}.kicad_pcb"
    board.Save(str(dst))
    print(f"{half}: 行 {n_row} 区間 / 列 {n_col} 区間 / 橋のビア {n_via} 個 "
          f"（引かなかったホップ {n_skip}）→ {dst.name}")
    return dst


if __name__ == "__main__":
    for h in ("left", "right"):
        build(h)
