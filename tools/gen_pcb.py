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
    BESIDE_GAP, DECOUPLE_ANGLE, DECOUPLE_BESIDE, DECOUPLE_OFFSET, JLC, MIN_ISLAND_MM2,
    POWER_CLASSES,
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
#
# ⚠️ **COPPER_LAYERS から導く**（2026-08-15）。同じ値を独立に書いていて、
# 上のコメントが「層数を変えるときはここだけ直す」と言っているのに
# **二重管理**だった。しかも `COPPER_LAYERS` はどこからも読まれておらず、
# `test_constants` が「読まれていないのに [記録のみ] が無い」と赤に
# なっていた（私の作業より前から）。**片方を消すのではなく繋ぐ**——
# 2 層のいまはベタを両面に敷くので、銅の層と一致するのが正しい。
GND_POUR_LAYERS = COPPER_LAYERS


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
        if not name.startswith("ROW_"):
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
    #
    # ⚠️ **行は無限に長い線ではない。x の範囲も持つ。**y だけで
    # 「跨ぐ」と判定すると、行が届いていない場所にまで橋を架ける
    # （2026-08-17・利用者「COL0 は全て B.Cu 側でよく、F.Cu 側に
    # ビアでもぐる必要はないはず」）。実測すると **COL0 は一番左の列で、
    # どの行も COL0 より右から始まっていた**（例: ROW_C は x 97.769 から
    # なのに COL0 は x=83.384）。**4 本とも跨いでいなかった。**
    row_span = {}
    for t in board.GetTracks():
        if t.GetClass() != "PCB_TRACK" or not t.GetNetname().startswith("ROW_"):
            continue
        y = round(t.GetStart().y / 1e6, 3)
        xs = (t.GetStart().x / 1e6, t.GetEnd().x / 1e6)
        lo, hi = row_span.get(y, (min(xs), max(xs)))
        row_span[y] = (min(lo, *xs), max(hi, *xs))
    row_y = sorted(row_span)

    def _row_blocks(ry, x):
        """行 ry が x のところに実在するか（端は余裕を見て広めに取る）。"""
        lo, hi = row_span[ry]
        return lo - clr - 1.0 <= x <= hi + clr + 1.0

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
        # 行のバス（横一直線）との距離。跨いだら当然アウト。
        #
        # ⚠️ **跨ぐ「その点の x」で見る。**端点の x で見てはいけない。
        # 斜めの区間は端点のどちらとも違う x で行を横切る（COL0 の
        # SW19→SW25 は 45° の途中 x=99.099 で y=122.7 を通り、ROW_B の
        # 左端 109.675 より左＝**当たらない**）。端点で見ると、行の
        # 無い場所に橋を架けたり、引けるはずのホップを弾いたりする。
        lo, hi = min(ay, by), max(ay, by)
        for ry in row_y:
            if not (lo - clr < ry < hi + clr):
                continue
            if by == ay:                     # 横の区間は範囲全体で見る
                if _row_blocks(ry, ax) or _row_blocks(ry, bx):
                    return False
                continue
            t = (ry - ay) / (by - ay)        # 交わる点を内挿する
            t = max(0.0, min(1.0, t))
            if _row_blocks(ry, ax + t * (bx - ax)):
                return False
        return True

    def _same_path(a, b):
        """2 つの経路が同じか（0.001mm まで）。"""
        if len(a) != len(b):
            return False
        for (p1, p2) in zip(a, b):
            if p1[4] != p2[4]:
                return False
            if any(abs(u - v) > 0.001 for u, v in zip(p1[:4], p2[:4])):
                return False
        return True

    def _is_standard(path, ax, ay, cx, cy, ry):
        """**標準形か。**縦 → 橋 → 縦 → 45° → 縦 だけで出来ていること。

        「横に走る区間」を持たないもの、かつ 45° が 1 回だけのものを
        標準とする。同じ dx のホップなら、この条件を満たす経路は
        （曲がる高さが違っても）見た目が揃う。

        ⚠️ **横の区間を許すと形が崩れる。**実測で、同じ dx=+9.525 の
        3 本が「45° 一本」「45° のあと横に 6.275mm」「45° のあと横に
        0.275mm」とばらばらになっていた（2026-08-18）。
        """
        diag = flat = 0
        for (x1, y1, x2, y2, _l) in path:
            dx, dy = abs(x2 - x1), abs(y2 - y1)
            if dx < 1e-6:                 # 縦
                continue
            if dy < 1e-6:                 # 横に走っている
                flat += 1
            elif abs(dx - dy) < 1e-6:     # 45°
                diag += 1
            else:
                return False              # 45° でない斜め
        return flat == 0 and diag <= 1

    def _margin(path, net):
        """経路の、穴・他ネットのパッドまでの最小の余裕（mm）。

        **「通るか」だけでなく「どれだけ余裕があるか」も見る。**
        規格ぎりぎり（0.25mm）で通る経路と、1.0mm 空いている経路の
        どちらも「合格」になってしまうため（2026-08-17）。
        """
        m = 9.0
        for (x1, y1, x2, y2, layer) in path:
            dx, dy = x2 - x1, y2 - y1
            ll = dx * dx + dy * dy

            def d(px, py):
                t = 0 if ll == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / ll))
                return math.dist((x1 + t * dx, y1 + t * dy), (px, py))
            for hx, hy, r in holes:
                m = min(m, d(hx, hy) - r - TRACK_W / 2)
            if layer != pcbnew.B_Cu:
                continue
            for sx, sy, nn, half in smd:
                if nn == net:
                    continue
                m = min(m, d(sx, sy) - half - TRACK_W / 2)
        return m

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
            # **本当に跨ぐ行だけ数える。**y が間にあっても、その行が
            # x 方向に届いていなければ障害物ではない（COL0 がこれ）。
            # ⚠️ **降りる場所の x で見る。**`or _row_blocks(ry, cx)` と
            # 書いて、**行き先の x に行があるだけで橋を架けていた**
            # （2026-08-17・利用者「どう見てもいらないんだけど」）。
            # COL0 の SW19→SW25 は x=95.290 で y=122.7 を通るのに、
            # ROW_B は x=109.675 からで 14.4mm 右。**そこに行は無い。**
            # 横へ寄るのは行を過ぎたあとなので、cx は関係ない。
            # 素直な形（縦 → 45°）が行を跨ぐかは、**その 45° が行と
            # 交わる点の x** で決まる。縦の区間で跨ぐなら x=ax。
            knee_c = abs(cy - ay) - abs(cx - ax)
            def _crosses(ry):
                if ry <= ay + max(knee_c, 0):     # 縦の区間で跨ぐ
                    return _row_blocks(ry, ax)
                t = ry - (ay + max(knee_c, 0))    # 45° に入ってからの距離
                return _row_blocks(ry, ax + t * (1 if cx > ax else -1))
            crossed = [ry for ry in row_y if ay < ry < cy and _crosses(ry)]

            if not crossed:
                # **跨ぐ行が無い。潜る必要が無いので裏だけで引く。**
                # 縦 → 45° → 縦。ビアは 1 個も要らない。
                knee0 = abs(cy - ay) - abs(cx - ax)
                cands = []
                if knee0 >= 0:
                    # 縦 → 45°（素直な形）
                    cands.append([(ax, ay, ax, ay + knee0, pcbnew.B_Cu),
                                  (ax, ay + knee0, cx, cy, pcbnew.B_Cu)])
                    # **先に 45° で寄ってから降りる。**縦の区間が元の x に
                    # 長く残る形だと、スタビの穴を抜けられないことがある
                    # （左 COL0 SW13→SW19 が ST19 に当たる）。
                    cands.append([(ax, ay, cx, ay + abs(cx - ax), pcbnew.B_Cu),
                                  (cx, ay + abs(cx - ax), cx, cy, pcbnew.B_Cu)])
                    # **途中で寄る（縦 → 45° → 縦）。**上の 2 つは
                    # 「元の x」か「行き先の x」のどちらかに長く留まる
                    # ので、その真上にスタビの穴があると詰む
                    # （左 COL0 SW13→SW19。ST19 が x=90.437 で列は 90.528、
                    # 一方 45° を先にやると SW13 自身の胴に当たる）。
                    # **寄る高さを選べるようにすれば抜けられる。**
                    step = 0.5
                    ky = ay + step
                    while ky < cy - abs(cx - ax):
                        cands.append([
                            (ax, ay, ax, ky, pcbnew.B_Cu),
                            (ax, ky, cx, ky + abs(cx - ax), pcbnew.B_Cu),
                            (cx, ky + abs(cx - ax), cx, cy, pcbnew.B_Cu)])
                        ky += step
                    # **縦 → 45° → 横 → 縦。**上の形は 45° をパッドの近くで
                    # 始めるので、**スイッチ自身の胴の角をかすめる**
                    # （左 COL0 SW19→SW25 で、SW19 の φ1.75 位置決めポスト
                    # まで 0.330mm しか無かった。規格 0.25mm は満たすが、
                    # 他の列は 1.030mm ある。2026-08-17・利用者
                    # 「配線が穴にかなりギリギリです」）。
                    # **胴を過ぎるまで真下に降りてから曲がる**と 1.030mm
                    # 取れる。横の区間で高さを合わせる。
                    ky = ay + 0.25
                    while ky < cy:
                        hy = ky + abs(cx - ax)
                        if hy <= cy:
                            cands.append([
                                (ax, ay, ax, ky, pcbnew.B_Cu),
                                (ax, ky, ax + (cx - ax), hy, pcbnew.B_Cu),
                                (cx, hy, cx, cy, pcbnew.B_Cu)])
                        # 45° を短く切り上げて、残りを横で詰める形も試す
                        for hy2 in (ky + 1.0, ky + 2.0, ky + 4.0, ky + 8.0):
                            if hy2 > cy:
                                continue
                            mx = ax + (hy2 - ky) * (1 if cx > ax else -1)
                            if (cx - mx) * (1 if cx > ax else -1) < 0:
                                continue
                            cands.append([
                                (ax, ay, ax, ky, pcbnew.B_Cu),
                                (ax, ky, mx, hy2, pcbnew.B_Cu),
                                (mx, hy2, cx, hy2, pcbnew.B_Cu),
                                (cx, hy2, cx, cy, pcbnew.B_Cu)])
                        ky += 0.25
                # **通る形のうち、一番余裕のあるものを採る。**
                # 「最初に通ったもの」で決めると、規格は満たすが余裕が
                # 無い経路が残る（COL0 が 0.330mm、他の列は 1.030mm）。
                ok = [c for c in cands
                      if all(_clear(x1, y1, x2, y2, name, la)
                             for (x1, y1, x2, y2, la) in c)]
                plain = max(ok, key=lambda c: _margin(c, name), default=None)
                if plain:
                    for (x1, y1, x2, y2, la) in plain:
                        if (x1, y1) == (x2, y2):
                            continue
                        t = pcbnew.PCB_TRACK(board)
                        t.SetStart(pcbnew.VECTOR2I_MM(x1, y1))
                        t.SetEnd(pcbnew.VECTOR2I_MM(x2, y2))
                        t.SetWidth(pcbnew.FromMM(TRACK_W))
                        t.SetLayer(la)
                        t.SetNet(a.GetNet())
                        board.Add(t)
                        n += 1
                    continue
                skipped += 1
                _why.append((name, '跨ぐ行が無いが裏だけで引けない'))
                continue

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
                # F: **跨いだあと、曲がる高さを選べるようにする。**
                #
                # C も D も曲がる y が 1 つに決まっている（C は cy-run、
                # D はレーン）。**その 1 点がスタビの穴の真横だと詰む**
                # （右 COL6 SW16→SW24。ST24 の φ3.05 が x=202.356 に
                # あり、どちらの形も 0.289mm しか空かなかった。
                # 2026-08-17・利用者「SW16-24 は工夫して」）。
                #
                # 曲がる高さを振り、足りない横移動は横の区間で詰める。
                # 45° を保ったまま**穴の左を抜ける**経路が見つかる
                # （実測で余裕 1.030mm ＝ 他の列と同じ値）。
                ky3 = ry + BRIDGE_DY + 0.2
                while ky3 < cy:
                    hy3 = ky3 + 0.25
                    while hy3 <= cy:
                        mx3 = ax + (hy3 - ky3) * (1 if cx > ax else -1)
                        if (cx - mx3) * (1 if cx > ax else -1) >= -0.001:
                            shapes.append([           # F
                                (ax, ay, ax, ry - BRIDGE_DY, pcbnew.B_Cu),
                                (ax, ry - BRIDGE_DY, ax, ry + BRIDGE_DY, pcbnew.F_Cu),
                                (ax, ry + BRIDGE_DY, ax, ky3, pcbnew.B_Cu),
                                (ax, ky3, mx3, hy3, pcbnew.B_Cu),
                                (mx3, hy3, cx, hy3, pcbnew.B_Cu),
                                (cx, hy3, cx, cy, pcbnew.B_Cu),
                            ])
                        hy3 += 1.0
                    ky3 += 0.5
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
            # **通る形のうち、余裕が一番大きいものを採る。**
            # 「最初に通ったもの」だと、規格は満たすが穴すれすれの経路が
            # 残る（右 COL6 が ST24 まで 0.289mm だった。2026-08-17）。
            # 同じ余裕なら短い方（_len）を選ぶ。
            path = None
            _ok = []
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
                _ok.append(cand)
            if _ok:
                # **標準形を先に採る**（2026-08-18・利用者「col のラインが、
                # 似ているが微妙に不規則です。なぜですか？」）。
                #
                # ⚠️ **「余裕が最大のもの」で選ぶと形が揃わない。**候補には
                # 曲がる高さを 0.25〜0.5mm 刻みで振ったものが何十通りも
                # 入っていて、**周りの障害物はキーごとに少しずつ違う**ので
                # 勝つ候補が列ごとに変わる。実測で、同じ dx=+9.525 の
                # ホップが 3 本とも違う形になっていた（曲がる y が
                # 67.400 / 66.400 / 66.400、45° の使い方もばらばら）。
                #
                # **同じ dx なら同じ形になる**ように、標準形（A → C の
                # 素直な順）が通るならそれを採り、通らないときだけ
                # 余裕の大きいものへ落とす。
                # **形 A ちょうどのものを探す**（縦 → 橋 → 縦 → 45° → 縦）。
                # 「横に走らない」だけでは、45° を始める高さが自由に
                # 選べてしまい**同じ dx でも形が変わる**（実測で
                # dx=+9.525 が 3 種類）。**A の座標そのもの**を標準とする。
                canon = [(ax, ay, ax, ry - BRIDGE_DY, pcbnew.B_Cu),
                         (ax, ry - BRIDGE_DY, ax, ry + BRIDGE_DY, pcbnew.F_Cu),
                         (ax, ry + BRIDGE_DY, ax, ay + knee, pcbnew.B_Cu),
                         (ax, ay + knee, cx, cy, pcbnew.B_Cu)]
                std = next((c for c in _ok if _same_path(c, canon)), None)
                if std is not None:
                    path = std
                else:
                    best_m = max(_margin(c, name) for c in _ok)
                    path = next(c for c in _ok
                                if _margin(c, name) >= best_m - 0.001)
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


def _drop_gnd_vias_hitting(board, clearance=0.25):
    """**あとから載せた配線に当たる GND のビアを外す。**

    `gnd_fanout.place` は配線より先に走るので、利用者が引いた線を
    知らない。銅の端どうしが `clearance` を割るものを落とす
    （ベタの塗り直しと離島の繋ぎ直しは呼び出し側でやる）。

    ⚠️ **ビアだけでなく、そのスタブの線も落とす。**ファンアウトは
    「パッド → 短い線 → ビア」の組で、ビアだけ消すと線が残る。
    2026-08-23 に実際に出た: COL8 を引き直したら、残った GND の
    スタブと `tracks_crossing` になった（ビアは既に外れていた）。
    """
    import math

    def near(ax, ay, bx, by, hw2):
        """区間 (ax,ay)-(bx,by) が、どれかの線と clearance を割るか。"""
        for (x1, y1, x2, y2, hw) in lines:
            # 端点 × 相手区間 の 4 通りで測る（区間どうしの最短距離の近似）
            def pt(px, py, x1_, y1_, x2_, y2_):
                dx, dy = x2_ - x1_, y2_ - y1_
                ll = dx * dx + dy * dy
                u = 0 if ll == 0 else max(0, min(1, ((px - x1_) * dx + (py - y1_) * dy) / ll))
                return math.dist((x1_ + u * dx, y1_ + u * dy), (px, py))
            d = min(pt(ax, ay, x1, y1, x2, y2), pt(bx, by, x1, y1, x2, y2),
                    pt(x1, y1, ax, ay, bx, by), pt(x2, y2, ax, ay, bx, by))
            if d - hw - hw2 < clearance:
                return True
        return False

    lines = []
    for t in board.GetTracks():
        if t.GetClass() != "PCB_TRACK" or t.GetNetname() in ("GND", ""):
            continue
        lines.append((t.GetStart().x / 1e6, t.GetStart().y / 1e6,
                      t.GetEnd().x / 1e6, t.GetEnd().y / 1e6,
                      pcbnew.ToMM(t.GetWidth()) / 2))
    dropped = 0
    for v in list(board.GetTracks()):
        if v.GetClass() != "PCB_VIA" or v.GetNetname() != "GND":
            continue
        vx, vy = v.GetPosition().x / 1e6, v.GetPosition().y / 1e6
        r = pcbnew.ToMM(v.GetWidth()) / 2
        for (x1, y1, x2, y2, hw) in lines:
            dx, dy = x2 - x1, y2 - y1
            ll = dx * dx + dy * dy
            s = 0 if ll == 0 else max(0, min(1, ((vx - x1) * dx + (vy - y1) * dy) / ll))
            if math.dist((x1 + s * dx, y1 + s * dy), (vx, vy)) - r - hw < clearance:
                board.Delete(v)
                dropped += 1
                break
    # **スタブの線も同じ基準で落とす。**残すと交差の相手になる。
    for t in list(board.GetTracks()):
        if t.GetClass() != "PCB_TRACK" or t.GetNetname() != "GND":
            continue
        if near(t.GetStart().x / 1e6, t.GetStart().y / 1e6,
                t.GetEnd().x / 1e6, t.GetEnd().y / 1e6,
                pcbnew.ToMM(t.GetWidth()) / 2):
            board.Delete(t)
            dropped += 1
    return dropped


def _drop_stitch_vias(board, tol=0.001):
    """**どこにも繋がっていない GND のビアを外す。**

    （2026-08-22・利用者「どこにもつながってない GND ビアを一旦入れない
    ようにしてほしい。それは最後にやる工程なはずなので」）

    `gnd_fanout.stitch_islands` が打つ離島の縫い止めは、**ベタ以外の何にも
    触れていない。**パッドにも配線にも繋がらないので、配線が動けば要らなく
    なる／別の場所に要る。**配線が固まるまでは打たない。**

    ここでは「GND のパッドにも GND の配線にも触れていないビア」を落とす。
    `gnd_fanout.place` のファンアウト（パッドの真横）は残る。
    """
    import math
    keep = []
    for f in board.GetFootprints():
        for pad in f.Pads():
            if pad.GetNetname() == "GND":
                keep.append((pad.GetPosition().x / 1e6, pad.GetPosition().y / 1e6,
                             max(pcbnew.ToMM(pad.GetSize().x),
                                 pcbnew.ToMM(pad.GetSize().y)) / 2))
    lines = []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_TRACK" and t.GetNetname() == "GND":
            lines.append((t.GetStart().x / 1e6, t.GetStart().y / 1e6,
                          t.GetEnd().x / 1e6, t.GetEnd().y / 1e6,
                          pcbnew.ToMM(t.GetWidth()) / 2))
    dropped = 0
    for v in list(board.GetTracks()):
        if v.GetClass() != "PCB_VIA" or v.GetNetname() != "GND":
            continue
        vx, vy = v.GetPosition().x / 1e6, v.GetPosition().y / 1e6
        r = pcbnew.ToMM(v.GetWidth()) / 2
        touches = any(math.dist((px, py), (vx, vy)) - r - pr <= tol
                      for (px, py, pr) in keep)
        if not touches:
            for (x1, y1, x2, y2, hw) in lines:
                dx, dy = x2 - x1, y2 - y1
                ll = dx * dx + dy * dy
                u = 0 if ll == 0 else max(0, min(1, ((vx - x1) * dx + (vy - y1) * dy) / ll))
                if math.dist((x1 + u * dx, y1 + u * dy), (vx, vy)) - r - hw <= tol:
                    touches = True
                    break
        if not touches:
            board.Delete(v)
            dropped += 1
    return dropped



def _hole_label_boxes(board):
    """キーのシルクの枠を集める（名札の逃がし先を決めるため）。"""
    boxes = []
    for f in board.GetFootprints():
        if not f.GetReference().startswith("SW"):
            continue
        for g in f.GraphicalItems():
            if g.GetLayerName() == "F.Silkscreen":
                bb = g.GetBoundingBox()
                boxes.append((bb.GetLeft() / 1e6, bb.GetTop() / 1e6,
                              bb.GetRight() / 1e6, bb.GetBottom() / 1e6))
    return boxes


def _place_hole_label(board, fp, off=3.15, clr=0.15):
    """取付穴の名札を、キーのシルクの枠に当たらない向きへ回す。

    **当たらない向きが無ければ既定のまま置く。**動かせないことを
    DRC に出させる。名札を消して黙らせない（消すと基板上で穴が
    識別できなくなり、組む人が困る）。
    """
    boxes = _hole_label_boxes(board)
    t = fp.Reference()
    px, py = fp.GetPosition().x / 1e6, fp.GetPosition().y / 1e6
    bb = t.GetBoundingBox()
    hw = (bb.GetRight() - bb.GetLeft()) / 2e6
    hh = (bb.GetBottom() - bb.GetTop()) / 2e6
    for dx, dy in ((0, -off), (0, off), (-off, 0), (off, 0)):
        cx, cy = px + dx, py + dy
        x0, y0, x1, y1 = cx - hw - clr, cy - hh - clr, cx + hw + clr, cy + hh + clr
        if not any(x0 < b[2] and b[0] < x1 and y0 < b[3] and b[1] < y1 for b in boxes):
            t.SetPosition(pcbnew.VECTOR2I(int(cx * 1e6), int(cy * 1e6)))
            return True
    return False



def apply_matrix_routing(board, half):
    """**利用者が引いた配線（pcb/matrix_routing.json）を載せる。**

    （2026-08-22・利用者「**今の** matrix_only からスクリプト化すれば？」）

    `tools/export_matrix_routing.py` が `pcb/matrix_only/` から書き出した
    座標をそのまま置く。**規則を推測して引き直さない**——私は 3 回失敗して
    いる（着地で U1 の他のパッドを横切る／レーンを縦に伸ばして交差する／
    跨がない行に橋を架ける）。**利用者が引いた座標そのものが仕様。**

    ⚠️ **GND は入っていない。**ベタとファンアウトで別に配り直すため
    （書き出しに含めると古い塗りが固定される）。

    ここが載る分は `prewire_*` が引いたものと重なるので、**同じネットの
    既存の配線は一度消してから置く。**
    """
    import json
    f = ROOT / "pcb" / "matrix_routing.json"
    if not f.exists():
        return 0, 0
    data = json.loads(f.read_text()).get(half)
    if not data:
        return 0, 0

    nets = {d["net"] for d in data["tracks"]} | {d["net"] for d in data["vias"]}
    for t in list(board.GetTracks()):
        if t.GetNetname() in nets:
            board.Delete(t)

    n = v = 0
    for d in data["tracks"]:
        net = board.FindNet(d["net"])
        if net is None:
            continue
        w = pcbnew.PCB_TRACK(board)
        w.SetStart(pcbnew.VECTOR2I_MM(d["x1"], d["y1"]))
        w.SetEnd(pcbnew.VECTOR2I_MM(d["x2"], d["y2"]))
        w.SetWidth(pcbnew.FromMM(d["w"]))
        w.SetLayer(board.GetLayerID(d["layer"]))
        w.SetNet(net)
        board.Add(w)
        n += 1
    for d in data["vias"]:
        net = board.FindNet(d["net"])
        if net is None:
            continue
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I_MM(d["x"], d["y"]))
        via.SetWidth(pcbnew.FromMM(d["d"]))
        via.SetDrill(pcbnew.FromMM(d["drill"]))
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNet(net)
        board.Add(via)
        v += 1

    # **GND のビアも、利用者が置いた位置へ置き直す**（2026-08-23）。
    #
    # 利用者「GND ビアの位置を変えています。3V3 の近くにあるのは
    # 危ないのかなと」。実測すると U1/U2 の GND ビアが V3V3 まで
    # **0.302 / 0.312mm** しか無く、利用者はそれを **1.26〜1.86mm** へ
    # 離していた。DRC の規定 0.25mm は通るが、**通るのと余裕があるのは別。**
    # 相手が電源と GND なので、短絡すれば信号線どうしより結果が重い。
    #
    # `gnd_fanout.place` はパッドの形だけから機械的に決めるので、
    # **手で寄せた位置は次の生成で消える。**だから写して置き直す。
    #
    # ⚠️ **「電源から N mm 離す」という規則にしようとして失敗した**
    # （同日）。候補を弾くと逆に V3V3 の**配線**側へ押し出され、
    # `_drop_gnd_vias_hitting` が 7 個中 4 個を落として U1/U2 の GND
    # パッドがベタに繋がらなくなった。**パッドしか見ない探索に、
    # 配線の都合は表現できない。**現物の座標を写すのが正しい。
    #
    # **スタブの線は写さない。**ここで置き直したビアへ引き直す。
    g = data.get("gnd_vias") or []
    gv = 0
    if g:
        gnd = board.FindNet("GND")
        for t in list(board.GetTracks()):
            if t.GetNetname() == "GND" and t.GetClass() == "PCB_VIA":
                board.Delete(t)
        for d in g:
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I_MM(d["x"], d["y"]))
            via.SetWidth(pcbnew.FromMM(gnd_fanout.VIA_DIAMETER_MM))
            via.SetDrill(pcbnew.FromMM(gnd_fanout.VIA_DRILL_MM))
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            via.SetNet(gnd)
            board.Add(via)
            gv += 1
        # **スタブも写す。**引き直そうとして層を取り違え、F.Cu に引いて
        # ROW_D / ROW_E と交差した（同日）。利用者の板では B.Cu。
        # `gnd_fanout.place` が引いた古いスタブは先に全部消す。
        import math
        for t in list(board.GetTracks()):
            if t.GetNetname() == "GND" and t.GetClass() == "PCB_TRACK" \
                    and math.dist((t.GetStart().x / 1e6, t.GetStart().y / 1e6),
                                  (t.GetEnd().x / 1e6, t.GetEnd().y / 1e6)) < 8.0:
                board.Delete(t)
        for d in data.get("gnd_stubs") or []:
            w = pcbnew.PCB_TRACK(board)
            w.SetStart(pcbnew.VECTOR2I_MM(d["x1"], d["y1"]))
            w.SetEnd(pcbnew.VECTOR2I_MM(d["x2"], d["y2"]))
            w.SetWidth(pcbnew.FromMM(d["w"]))
            w.SetLayer(board.GetLayerID(d["layer"]))
            w.SetNet(gnd)
            board.Add(w)

    # **名札（シルク）の位置も写す**（2026-08-23・利用者「左右ともに
    # シルクの位置を修正しました」）。IC とコネクタの名札を、部品の
    # 輪郭や配線から外へ逃がしてある（右で silk の警告が 20 → 4 件）。
    # **フットプリントの既定位置は生成のたびに戻る**ので、写さないと消える。
    for d in data.get("labels") or []:
        fp = board.FindFootprintByReference(d["ref"])
        if fp is None:
            continue
        fp.Reference().SetPosition(pcbnew.VECTOR2I_MM(
            fp.GetPosition().x / 1e6 + d["dx"],
            fp.GetPosition().y / 1e6 + d["dy"]))
    return n, v, gv


def replay_matrix(board, src):
    """**未配線の板に引いてあるマトリクスの配線を、そのまま写す。**

    （2026-08-17・利用者「このキーマトリクスの配線を凍結させてください」）

    ⚠️ **配線後の板で `prewire_col_bus` を呼び直してはいけない。**
    経路は「そのとき板の上に何があるか」から決まるので、**同じ答えに
    ならない**。実測: `gen_pcb` 直後は 21 ホップ全部引けたのに、
    SES 取り込み後の板（ビアが 38 → 1217 個に増えている）に対して
    呼ぶと **13 ホップが「障害物」で落ちた。**

    凍結とは「同じ手順をもう一度回す」ことではなく、**同じ結果を
    置き直す**こと。未配線の板（`pcb/unrouted/`）が唯一の出どころで、
    そこには `gen_pcb` が引いた線がそのまま残っている。

    ROW / COL / SW*_D の配線とビアを写す。既にあるものは消してから。
    """
    # ⚠️ **V3V3 も写す**（2026-08-22）。正本（pcb/matrix_only/）には
    # 利用者が引いた V3V3（U1↔C_U1↔J_DB）が入っている。ここに入れないと
    # 写されず、Freerouting が別の経路を引いてパスコンのループが伸びる。
    # **GND は写さない**——ベタとファンアウトで別に配り直すため。
    keep = re.compile(r"ROW_[A-E]|COL\d+|SW\d+_D|V3V3")

    # **写す線の座標をあらかじめ集める。**
    #
    # ⚠️ **「そのネットの線を全部消す」をしないこと**（2026-08-18）。
    # ROW/COL は最後の 1 本（U1 へ / J_DB へ）だけ Freerouting に
    # 引かせる約束なのに、全部消すと**その 1 本も道連れになる。**
    # 実測で COL→U1 が 8 本・ROW→J_DB が 5 本まるごと未配線になり、
    # 「Freerouting が引けていない」と誤診した。**引けていたものを、
    # 私が消していた。**
    #
    # 消してよいのは**これから同じ場所へ置き直す線だけ**。
    def _key(x1, y1, x2, y2, layer):
        return (layer, tuple(sorted([(round(x1, 3), round(y1, 3)),
                                     (round(x2, 3), round(y2, 3))])))
    mine = set()
    for t in src.GetTracks():
        if not keep.fullmatch(t.GetNetname()):
            continue
        if t.GetClass() == "PCB_VIA":
            mine.add(("V", round(t.GetPosition().x / 1e6, 3),
                      round(t.GetPosition().y / 1e6, 3)))
        else:
            mine.add(_key(t.GetStart().x / 1e6, t.GetStart().y / 1e6,
                          t.GetEnd().x / 1e6, t.GetEnd().y / 1e6, t.GetLayer()))

    for t in list(board.GetTracks()):
        if not keep.fullmatch(t.GetNetname()):
            continue
        if t.GetClass() == "PCB_VIA":
            k = ("V", round(t.GetPosition().x / 1e6, 3), round(t.GetPosition().y / 1e6, 3))
        else:
            k = _key(t.GetStart().x / 1e6, t.GetStart().y / 1e6,
                     t.GetEnd().x / 1e6, t.GetEnd().y / 1e6, t.GetLayer())
        if k in mine:
            board.Delete(t)          # これから置き直すので消す
    n = vias = 0
    for t in src.GetTracks():
        name = t.GetNetname()
        if not keep.fullmatch(name):
            continue
        net = board.FindNet(name)
        if net is None:
            raise SystemExit(f"replay_matrix: ネットが無い: {name}")
        if t.GetClass() == "PCB_VIA":
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(t.GetPosition())
            v.SetWidth(t.GetWidth())
            v.SetDrill(t.GetDrill())
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            v.SetNet(net)
            board.Add(v)
            vias += 1
        else:
            w = pcbnew.PCB_TRACK(board)
            w.SetStart(t.GetStart())
            w.SetEnd(t.GetEnd())
            w.SetWidth(t.GetWidth())
            w.SetLayer(t.GetLayer())
            w.SetNet(net)
            board.Add(w)
            n += 1
    return n, vias


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
}

# **J_DB のパッドの真上に置く中継ビア。**座標は書かない。
#
# ⚠️ **かつて (72.75, 84.0) と直書きしていた。**J_DB が子基板と X を
# 揃えるために 1.35mm 動いた瞬間、このビアは V3V3 のパッド(76.10)から
# 外れ、**ROW_B のパッド(72.60)の上に乗った。**結果 ROW_B が未配線に
# なった（2026-08-15）。**動くものの座標を写して持たない。**
#
# J_DB は 0.5mm ピッチの SMD で、隣のパッドとの隙間(0.2mm)にビアは
# 物理的に入らない。パッドの長辺の外側、真上ぎりぎりに置く。
GUIDE_VIAS_ABOVE_JDB_PAD = {"V3V3": 1.375}   # ネット → パッドから上へ何 mm


def guide_vias(board, half):
    """詰まりが再現された経路に、Freerouting 向けの中継ビアを打つ。

    **消してはいけない。**探索の局所解を避けるためのヒントであって、
    決まりきった配線ではない。DSN からもネットごと外さない
    （PREWIRED に入れない）——Freerouting に「ここも経由候補」として
    普通に見せる必要がある。
    """
    if half != "right":
        return
    spots = dict(GUIDE_VIAS)
    # **J_DB のパッドから座標を取る。**直書きすると、J_DB が動いた日に
    # 黙って別のパッドの上に乗る（上の注記）。
    jdb = board.FindFootprintByReference("J_DB")
    for netname, up in GUIDE_VIAS_ABOVE_JDB_PAD.items():
        pad = _pad_with_net(jdb, netname)
        if pad is None:
            raise SystemExit(f"guide_vias: J_DB に {netname} のパッドが無い")
        spots[netname] = (pcbnew.ToMM(pad.GetPosition().x),
                          pcbnew.ToMM(pad.GetPosition().y) - up)
    for netname, (x, y) in spots.items():
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

# 3 要素目は基板の Value フィールドに書く文字列。
# **kind（FP_MAP のキー）をそのまま Value に使わないこと。**
# kind は「フットプリントを引くための内部の名前」であって、部品の
# 型番でも規格値でもない。JLCPCB の部品マッチはこの Value 欄を見るので、
# kind のままだと `schottky`/`ffc_12p`/`res_1M` が「該当部品なし」で
# 赤字（要手動選定）になる。`cap_100n` は数字が近いぶん
# コメント不一致の警告で済むが、それも同じ原因。
# 値は parts-audit.md に確定記録済みの型番・規格をそのまま使う。
ELEC_FP = {
    # SOIC-16 はコートヤード 10.49mm で、帯 9.25mm に**入らない**。
    # 位置の微調整で逃がそうとしていたが、どちら側にはみ出すかを
    # 選んでいるだけだった。TSSOP-16 は 5.59mm で 3.66mm 余る。
    "74LVC595": ("Package_SO", "TSSOP-16_4.4x5mm_P0.65mm", "74LVC595"),
    "cap_100n": ("Capacitor_SMD", "C_0805_2012Metric", "100nF"),
    "res_1M": ("Resistor_SMD", "R_0805_2012Metric", "1M"),
    "schottky": ("Diode_SMD", "D_SOD-123", "B5819W"),
    "ffc_12p": ("Connector_FFC-FPC",
                "Hirose_FH12-12S-0.5SH_1x12-1MP_P0.50mm_Horizontal",
                "FH12-12S-0.5SH(55)"),
    # **電源スイッチは基板に載らない。**背面のパネルに付けて配線で繋ぐ。
    # 基板の後端から背面まで 23.3mm あり、基板上のどこに置いても手が届かない
    # （open-gaps #17）。基板側はランド 2 個で受ける。
    # ランド自体は部品ではないので Value は kind のままでよい
    # （JLCPCB の BOM には出てこない・footprint 名で区別できれば足りる）。
    "wire_pads": ("TestPoint", "TestPoint_Pad_2.0x2.0mm", "wire_pads"),
    "battery_holder": ("TestPoint", "TestPoint_Pad_2.0x2.0mm", "battery_holder"),
}


# PLACE の x に書ける印。**置くときに実際の値へ解決する。**
# J_DB の x は子基板の J_MAIN と揃える必要があり、それはケースの幅
# （＝キー配列）から決まるので、モジュールを読む時点では出せない。
J_DB_X = "align_with_daughterboard"


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
        # ⚠️ **電源系は帯 1（J_DB と同じ帯）。帯 0 に置かない。**
        #
        # 2026-08-14・利用者の指摘「こんな配線が混み合っている y に
        # 置くべきか。U1/U2 への SPI の邪魔になっているように見える」。
        # そのとおりだった。**帯 0 は SPI の唯一の通り道**で、
        # J_DB(x≈-77) から U1(x≈149) まで 75mm を SCK/MOSI/CS の 3 本が
        # 走る。そこへ電源系 5 点を並べたので、U1 の際で COL3/COL4 が
        # 押し出されてクリアランス違反が出ていた（右 6 件）。
        #
        # 電源系は µA〜15mA の DC で経路の自由度が高い。**行き先が
        # 固定されている SPI に帯 0 を譲る。**帯 1 は J_DB と H0 しか
        # 居らず、30mm 以上空いている。分圧が J_DB と同じ帯に来るので
        # VBATT_SENSE も短くなる。
        # **電源部はこの基板に無い。子基板へ移した**（open-gaps #41）。
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
        # ⚠️ **x は手で書かない。子基板の J_MAIN と揃える**（2026-08-15・
        # 利用者の指摘「コネクタの X 座標が互いに合っていない」）。
        # かつて総当たりで 63.0 を選んでいたが、子基板コネクタの中心は
        # +59.48mm で **3.52mm ずれていた。**両方とも口が手前を向いている
        # ので、ずれたぶん FFC が横へ折れる。J_DB_X が
        # interface.daughterboard_x_center から実際の値を取る。
        #
        # ⚠️ **未配線の本数は DSN_CLEARANCE_MARGIN_UM（autoroute.py）と
        # 連動する。**左右で同じマージン値を使う制約（利用者の要望）の下、
        # 両方の DRC 違反 0 と未配線最小を両立する値が 15µm。
        # マージンを動かすとここも動く。
        "J_DB": (1, J_DB_X),
        # **C_BULK はここに無い。子基板へ移した**（open-gaps #41）。
        # C_U1 はここに書かない。**DECOUPLE_BESIDE が U1 から算出する。**
        #
        # ⚠️ **U1 は帯 1（J_DB と同じ帯）。**2026-08-17 に帯 0 から移した
        # （利用者が基板上で直接動かし、その配置で配線し直した）。
        # 帯 0 は SPI の唯一の通り道で、その途中に U1 が居ると
        # SCK/MOSI/CS が U1 の際で押し出されていた。J_DB(帯 1・x=63.3)
        # の手前へ寄せると、FFC から来た 3 本がそのまま U1 に入る。
        # 3 つ目は裏面での向き。利用者は 180° ではなく 0° で置いた
        # （FFC から来る SPI がそのままピンに入る向き）。
        "U1": (1, 45.1375, 0, 0.55),
    },
    "right": {
        # 電池の + は基板を通らない（スイッチへ直結・open-gaps #41）。
        # ランドは BT1_-(GND) と SW_PWR_1(VBATT_SW) の 2 個だけ。
        # 右は J_DB(-77.5) と鎖が同じ側なので、元の位置のまま詰める。
        # **帯 1（J_DB と同じ帯）。**理由は左と同じ（上の注記）。
        # **電源部はこの基板に無い。子基板へ移した**（open-gaps #41）。
        # **J_DB は帯 1・x=-77.5。**左と同じ理由（帯 0 に置くと未配線が
        # 3〜27 本残る）。右基板は列が 9 本あり 595 系が 2 個あるぶん
        # 帯 0 の混雑が左よりきつく、**0 まで詰め切れなかった。**
        # x を 0.5mm 刻みで再探索し、-77.5 で未配線 1 本まで減った
        # （M=15µm で 3 回実行して決定的）。残る 1 本（COL8-SW31、
        # 基板最遠端の列）は gnd_fanout の格子や周辺部品の再配置では
        # 解消しなかった（2026-08-13 に系統的に確認。故意に固定してみて
        # 毎回同じネットが落ちることを確かめた——揺れではなく構造的な残り）。
        # ⚠️ **x は手で書かない。**左と同じ理由（上の注記）。かつて -77.5 で、
        # 子基板コネクタの中心 -76.15 から 1.35mm ずれていた。
        "J_DB": (1, J_DB_X),
        # **C_BULK はここに無い。子基板へ移した**（open-gaps #41）。
        # U1 と U2 の間は C_U2 のぶん空けてある（DECOUPLE_BESIDE が埋める）。
        # **U1 / U2 とパスコンは利用者が置いた位置**（2026-08-18・
        # 「試しに matrix の右手 U1, U2 パスこんの位置を考えてみた」）。
        #
        # **J_DB の真下に縦一列**に並べてある（実測）:
        #
        #   J_DB  x=73.850  y= 87.225
        #   U1    x=73.832  y= 96.455   C_U1 x=68.070（V3V3 まで 2.76mm）
        #   U2    x=73.830  y=102.995   C_U2 x=68.070（V3V3 まで 2.74mm）
        #
        # **パスコンはそれぞれ自分の IC の真横。**U1↔U2 は 6.54mm。
        # ⚠️ **COL0 の縦線（x=76.240）を避けて下へ 0.91mm ずらしてある**
        # （2026-08-18・利用者「B ずらしました」）。列は部品より先に
        # 引かれるので、重ねて置いても止まらない。**U1 のパッド 1 が
        # COL0 に 0.781mm 食い込んでいた。**
        # FFC・595・パスコンが 1 本の列にまとまるので、**列のバスが
        # 通る帯を塞がない。**以前は U1/U2 が別々の帯に散っていて、
        # COL4・COL5 の通り道と重なっていた。
        "U1": (1, -62.787, None, 1.375), "U2": (1, -76.170, 90, 8.038),
    },
}



def _center_courtyard_in_band(fp, band, dy_mm=0.0):
    """コートヤードの中心が帯の中心へ来るよう、フットプリントを縦にずらす。

    `dy_mm` は帯の中心からの意図的なずらし（KiCad の Y は下向き）。
    **既定は 0。**使うのは、利用者が基板上で直接置いた位置を再現する
    ときや、中心では通らないと実測で分かったときだけ（U1 の +0.55mm）。
    """
    for layer in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
        shape = fp.GetCourtyard(layer)
        if not shape.IsEmpty():
            break
    else:
        raise RuntimeError(f"{fp.GetReference()}: コートヤードが無い")
    bb = shape.BBox()
    mid = (bb.GetTop() + bb.GetBottom()) / 2
    want = pcbnew.FromMM(ORIGIN[1] - BAND_Y[band] + dy_mm)
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


def _place_beside(board, cap_ref, ic_ref, band, dy_mm=0.0, off=(0.0, 0.0),
                  angle=None):
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
    cap.SetPosition(pcbnew.VECTOR2I_MM(cx + dx + off[0],
                                       pcbnew.ToMM(cap.GetPosition().y)))
    # **IC と同じずらしを使う。**中心へ戻すと、寄せた相手だけが
    # 帯の中心から外れていて、往復ループが余計に伸びる。
    _center_courtyard_in_band(cap, band, dy_mm + off[1])

    # **コンデンサの V3V3 側のパッドが IC を向いているか。**
    # 逆を向いていると、わざわざ寄せた意味が半分になる（電流が部品を
    # 回り込む）。向いていなければ 180 度回す。
    # **向きが指定されていればそれに従う**（利用者が IC を回した場合）。
    if angle is not None:
        cap.SetOrientationDegrees(angle)
        return
    p_v3 = _pad_with_net(cap, "V3V3")
    p_gnd = _pad_with_net(cap, "GND")
    if p_v3 is not None and p_gnd is not None:
        toward_ic = (p_v3.GetPosition().x - p_gnd.GetPosition().x) * side < 0
        if not toward_ic:
            cap.SetOrientationDegrees(cap.GetOrientationDegrees() + 180)


def _courtyard_bbox(fp):
    """フットプリントのコートヤードの外接箱。無ければ None。"""
    for layer in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
        shape = fp.GetCourtyard(layer)
        if not shape.IsEmpty():
            return shape.BBox()
    return None


def _snap_clear_of_courtyards(board, fp, want_x, step=0.05, reach=16.0):
    """`want_x` へ寄せる。**当たるなら、当たらない最寄りへ逃がす。**

    子基板の FFC コネクタと X を揃えたいが、**揃えた先に部品が居ることが
    ある**（2026-08-15 に実測: 左は揃えた位置にダイオード D12 が 0.36mm
    掛かっていて、0.40mm 逃げると空く）。重なったまま置くと DRC が
    コートヤード重なりを出す。

    **ここで妥協の量を測って返す。**手で座標を書き直すと、キー配列や
    ケースの幅が動いたときに黙ってずれる。ずれ量は呼び出し側が印字する
    （2026-08-15 時点で 左 +0.40mm・右 +0.00mm）。
    """
    bb = _courtyard_bbox(fp)
    if bb is None:
        raise RuntimeError(f"{fp.GetReference()}: コートヤードが無い")
    half_w = pcbnew.ToMM(bb.GetWidth()) / 2
    top, bot = pcbnew.ToMM(bb.GetTop()), pcbnew.ToMM(bb.GetBottom())
    # **コートヤードの中心は原点とずれる**（FFC コネクタで 0.95mm）。
    # 「中心をどこへ置きたいか」から原点の移動量を出す。
    origin_to_center = (pcbnew.ToMM(bb.GetLeft() + bb.GetRight()) / 2
                        - pcbnew.ToMM(fp.GetPosition().x))

    # **同じ y の帯に居るものだけが邪魔になる。**全部と比べると、遠くの
    # 段のスイッチまで障害物に数えて逃げ場が無くなる。
    # **自分を除くのは参照名で。**`is` では外せない（pcbnew は
    # Footprints() のたびに別のラッパを返すので、自分自身を障害物に
    # 数えて 12.25mm 逃げた。2026-08-15 に実際に起きた）。
    # ⚠️ **スイッチは障害物に数えない。**スイッチのコートヤードは帯へ
    # はみ出すが、実装面が違う（スイッチは表・コネクタは裏の SMD）ので
    # 重なってよい。移設前の -77.5 も SW10 と重なったうえで DRC 0 だった。
    # ここを数えると右が 3.95mm 逃げ、**揃える前（1.35mm）より悪くなる。**
    obstacles = []
    for other in board.Footprints():
        if other.GetReference() == fp.GetReference():
            continue
        # **接頭辞 `SW` で拾わない**（電源スイッチのランドを巻き込む。
        # CLAUDE.md にある 3 回起きた失敗）。キースイッチだけを、
        # 参照名の形（SW + 数字）で見分ける。
        if re.fullmatch(r"SW\d+", other.GetReference()):
            continue
        ob = _courtyard_bbox(other)
        if ob is None:
            continue
        if pcbnew.ToMM(ob.GetBottom()) > top and pcbnew.ToMM(ob.GetTop()) < bot:
            obstacles.append((pcbnew.ToMM(ob.GetLeft()),
                              pcbnew.ToMM(ob.GetRight())))

    def clear(cx):
        lo, hi = cx - half_w, cx + half_w
        return not any(lo < r and hi > l for l, r in obstacles)

    want_kicad = ORIGIN[0] + want_x
    # 0 から外へ広げて、最初に空いたところを採る（＝最寄り）。
    for i in range(int(reach / step) + 1):
        for cand in ((want_kicad + i * step, want_kicad - i * step)
                     if i else (want_kicad,)):
            if clear(cand):
                pos = fp.GetPosition()
                fp.SetPosition(pcbnew.VECTOR2I(
                    pcbnew.FromMM(cand - origin_to_center), pos.y))
                return cand - want_kicad
    raise RuntimeError(
        f"{fp.GetReference()}: x={want_x:.2f} の周り {reach}mm に空きが無い")


def _place_electronics(board, half, net, plate_w):
    """回路に宣言された電子部品を、段の間の帯に置いてネットを割り当てる。"""
    from circuit import netlist
    from interface import daughterboard_x_center
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
        # 3 つ目があれば裏面での向き（度）。無ければ Flip のまま（180°）。
        turn = spec[2] if len(spec) > 2 else None
        # 4 つ目があれば帯の中心からのずらし（mm・Y 下向き）。
        dy = spec[3] if len(spec) > 3 else 0.0
        align_to = None
        if x is J_DB_X:
            # 子基板の FFC コネクタ（J_MAIN）は子基板の中心にあるので、
            # 子基板の中心 X がそのまま揃える先になる。
            align_to = x = daughterboard_x_center(half, plate_w)
        kind, pins = decl[ref]
        lib, name, value = ELEC_FP[kind]
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
            fp.SetValue(value)
            board.Add(fp)
            fp.Flip(fp.GetPosition(), False)
            # **向きの指定は Flip のあと・帯合わせの前。**Flip は 180° を
            # 与えるので、上書きするならここ。コートヤードの中心は
            # 向きで変わるので、_center_courtyard_in_band より先に回す。
            if turn is not None:
                fp.SetOrientationDegrees(turn)
            # **原点ではなくコートヤードを帯の中心に合わせる。**
            #
            # フットプリントのコートヤードは原点に対して対称とは限らない
            # （FFC コネクタは 0.95mm ずれていて、帯から 0.275mm はみ出していた）。
            # 原点を中心に置くと、部品ごとに違う量だけずれる。
            # ここで揃えておけば、部品ごとの手当て（dy）が要らなくなる。
            _center_courtyard_in_band(fp, band, dy)
            if align_to is not None:
                off = _snap_clear_of_courtyards(board, fp, align_to)
                print(f"   {half}: {ref} を子基板と揃えた"
                      f"（ずれ {off:+.2f}mm）")
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
            _spec = PLACE[half][ic_ref]
            _place_beside(board, cap_ref, ic_ref, _spec[0],
                          _spec[3] if len(_spec) > 3 else 0.0,
                          DECOUPLE_OFFSET[half].get(cap_ref, (0.0, 0.0)),
                          DECOUPLE_ANGLE[half].get(cap_ref))


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
        # **JLCPCBのBOM照合に使える値を入れる。**以前はキーのレジェンド
        # （"[" など）を入れていたが、それではJLCPCBの部品マッチングが
        # 一致せず、61個のソケットが実装BOMから静かに漏れていた
        # （fab-checklist.mdの「補正表に無い。確認していない」は、
        # そもそもBOMの行として認識されていなかったのが真因だった）。
        # レジェンドを見せる役目は下のB.SilkSテキストが別途担っている
        # ので、Valueをここで潰しても組み立て時の視認性は落ちない。
        fp.SetValue("CPG151101S11-2")
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
    # 行 r → ケーブルのネット名（左右の overlay の row-gpios が出所）。
    # **行番号をそのまま名前にしない**——左右で違う行を同じ線に載せるので、
    # 行番号の名前は片側で嘘になる（2026-08-15・利用者の指摘）。
    from matrix import row_nets
    rows = row_nets(half)
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
        d.FindPadByNumber(pinmap.resolve("diode", "K")).SetNet(net(rows[r]))

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
    # **列のバスもここで引く**（2026-08-17・利用者「このキーマトリクスの
    # 配線を凍結させてください。基本的にはこの配線は変更せず、自動配線の
    # 前に機械的に配線しておく形にしておいてください」）。
    #
    # ⚠️ **行のバスのあとに呼ぶ。**`prewire_col_bus` は既に引かれた
    # ROW の配線から「行が x 方向にどこからどこまであるか」を読む。
    # 先に呼ぶと行が 1 本も見えず、**跨いでいないと誤判定して橋を
    # 架けなくなる**（列と行が同じ B.Cu なので短絡になる）。
    # 幅は**プレートの幅**を渡す。ケースの造作（daughterboard_x_center）は
    # plate_positions の w で決まっており、基板もプレートも X=0 中心なので
    # 値がそのまま移る（PCB_INSET は左右対称に引くだけ）。
    _place_electronics(board, half, net, plate_w)
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
        # **名札をキーの枠から逃がす**（2026-08-22）。
        #
        # フットプリントの既定は穴の 3.15mm 手前（KiCad の Y は下向きなので
        # -Y）で、そこはたいてい**すぐ手前のキーのシルクの枠の中**。
        # DRC が `silk_overlap` を右で 5 件出していた（H0/H1/H3/H6/H7）。
        # **H0 を動かして 5 件目が増えたので気づいた**——残りの 4 件は
        # 前から出ていて、silk は警告なので誰も見ていなかった。
        #
        # **枠に当たらない側へ回す。**手前・奥・左・右の 4 方向を実際に
        # 試し、どのキーのシルクにも当たらない最初の向きを採る。
        # 全部当たるなら既定のまま（**黙って隠さない**——DRC に出させる）。
        _place_hole_label(board, h)

    # ⚠️ **列のバスは電子部品を置いたあとに引く。**
    #
    # 先に引くと、**J_DB / U1 / U2 がまだ板の上に無い**ので、
    # 衝突検査がそれらを 1 つも見られない。実際にそうなっていて、
    # 右の COL0 が J_DB の V3V3 パッドまで **0.140mm**（要 1.017mm）の
    # ところを通り、DRC が短絡を出した（2026-08-18・利用者
    # 「COL0 の配線が J_DB と U1 と干渉するように変わっている」）。
    # **凍結した時点から入っていた欠陥**で、私は「全ホップ・最小
    # 1.030mm」と報告していたが、その数字は穴とスイッチしか見ていなかった。
    n_col, n_via, n_skip = prewire_col_bus(board)
    print(f"      {half}: 列のバスを裏面で {n_col} 区間 / 橋のビア {n_via} 個"
          + (f"（引けなかったホップ {n_skip}）" if n_skip else "（全ホップ）"))
    # **利用者が引いた配線を載せる**（2026-08-22）。列のバスのあとに呼ぶ
    # ——同じネットの既存の配線を消してから置くので、順番が逆だと
    # せっかく載せたものを prewire が上書きしてしまう。
    n_ur, n_uv, n_gv = apply_matrix_routing(board, half)
    if n_ur:
        print(f"      {half}: 利用者の配線を載せた {n_ur} 区間 / ビア {n_uv} 個"
              + (f" / GND ビア {n_gv} 個" if n_gv else ""))
        if n_gv:
            # **GND のビアも写したので、当たり判定で外す必要は無い。**
            # 利用者が自分で避けた位置に置いてある。
            pass
        else:
            # ⚠️ **利用者の配線と当たる GND のビアを打ち直す**（2026-08-22）。
            # `gnd_fanout.place` は**この配線より前**に呼ばれるので、
            # あとから載る線を知らない。実測で GND のビアが COL8 のレーンに
            # 乗り、DRC が短絡 1・クリアランス 1 を出した。
            n_rm = _drop_gnd_vias_hitting(board)
            if n_rm:
                print(f"      {half}: 利用者の配線に当たる GND ビアを {n_rm} 個 外した")
    # 列を MCU へ戻すレーン（表面）。**列のバスのあとに呼ぶ**——
    # バスの端点をレーンへの降り口として使うため。

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

    # **ベタを塗り直し、離島を繋ぎ直す**（2026-08-22）。
    #
    # ⚠️ **配線を載せたあとにやる。**`_pour` はこの関数の途中で走るので、
    # そのあとに載る「利用者の配線」を知らない。塗りが古いままだと
    # DRC が `isolated_copper` を大量に出す（実測 左 36 / 右 60 件）。
    # 利用者「GND ベタ塗りとか、私が直せてないところは直してほしい」。
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    # **離島を繋ぐビアは、既定では打たない**（2026-08-22・利用者「どこにも
    # つながってない GND ビアを一旦入れないようにしてほしい。それは最後に
    # やる工程なはずなので」）。
    #
    # 打つと**ベタの形が変わる**ので、配線がまだ動く段階でやっても
    # 次の変更で無駄になる。**しかも浮いたビアは配線の邪魔をする。**
    # 配線が固まってから `GND_STITCH=1` を付けて 1 回だけ打つ。
    # 打つまでは DRC に `isolated_copper` が出るが、**それが正しい状態**。
    if os.environ.get("GND_STITCH") == "1":
        n_is, n_left = gnd_fanout.stitch_islands(board)
        if n_is or n_left:
            print(f"      {half}: ベタを塗り直し / 離島に打ったビア {n_is} 個"
                  f" / 繋げ切れなかった区画 {n_left}")
    else:
        n_is = _drop_stitch_vias(board)
        if n_is:
            print(f"      {half}: 浮いた GND ビアを外した {n_is} 個"
                  f"（打ち直すには GND_STITCH=1）")

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
