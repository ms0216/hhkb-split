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
from circuit import WIRE_PAD_KINDS, daughterboard_netlist  # noqa: E402
import pinmap  # noqa: E402
from gen_pcb import (  # noqa: E402
    CORNER_R, JLC, KICAD_FP, TRACK_W, VIA_D, VIA_DRILL, _apply_jlcpcb_rules,
    _load, _rounded_rect_outline,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pcb"
UNROUTED = OUT / "unrouted"
# **gen_pcb と同じ原点を使う。**外形を描く _rounded_rect_outline が
# gen_pcb.ORIGIN を参照しているので、ここだけ別の値にすると外形と部品が
# 50mm ずれる（レンダリングが空になって気づいた）。
from gen_pcb import ORIGIN  # noqa: E402

# 外形はケース側の造作と一致させる。**DB_W の出所は interface.py 1 つ**
# （ケース・子基板・本体基板の 3 つが読む。前は 21.0 を 2 か所に書いていた）。
from interface import DB_W  # noqa: E402
DB_D = 32.0
DB_BOSS_POS = [(-8.0, -13.5), (8.0, -13.5)]

XIAO_FP = (ROOT / "pcb/lib/hhkb_split.pretty", "XIAO_nRF52840")

FFC_FP = ("Connector_FFC-FPC", "Hirose_FH12-12S-0.5SH_1x12-1MP_P0.50mm_Horizontal")
CAP_FP = ("Capacitor_SMD", "C_0805_2012Metric")
BULK_FP = ("Capacitor_SMD", "C_1206_3216Metric")   # 100µF（C15008）
MOUNT_FP = ("MountingHole", "MountingHole_2.2mm_M2")

# 電源部の置き場所（板の中心が原点・Y 上向き＝奥・裏面）。
#
# **2026-08-14 に主基板から移した**（open-gaps #41）。理由は
# circuit.daughterboard_netlist の docstring。
#
# 座標は総当たりで求めた（0.25mm 刻み・隙間 0.3mm）。**XIAO の
# スルーホールは両面を貫くので裏面でも障害物**になる（一度これを
# 忘れて D_PWR と SW_PWR_1 をパッドに重ねた）。パッド列は原点から
# ±7.62、幅 1.7 なので ±6.77..8.47 を避ける。
#
# 板は 21x32mm のまま。**外形を変える必要は無かった**（実測: 必要
# 44.3mm² に対し裏面の空きは 557mm²、5 点とも収まる）。
# **並びは信号の流れで決める**（2026-08-14）。行き先が盤面の左右に
# 分かれているので、順序を間違えると配線が盤面を横断して他のパッドを
# 貫く（実際に 41 件出した）。
#
#     VBATT_SENSE の行き先 … XIAO の D0（x=-7.62）→ **分圧は左**
#     V3V3 の行き先        … XIAO の 3V3（x=+7.62）→ **ショットキーは右**
#     VBATT_SW は両方に触る → **スイッチのランドは中央**
#     BT1_- は GND（ベタで受ける）→ 空いたところでよい
# ⚠️ **レーンの上に置かないこと**（2026-08-14）。内側のレーンは
# x=±6.40 / ±5.75 を縦に走る。R_HI/R_LO を x -6.32..-2.88 に置いていて、
# レーンと 0.08mm しか離れていなかった。**配線を障害物に入れて総当たりで
# 求めた座標**を使う（目分量で置くと必ずどこかに当たる）。
# 部品の向き（度）。**信号の流れに合わせて入口と出口を向ける。**
# 書かないものは 0°。
POWER_ROT = {
    # **縦向きに置く**（2026-08-14・利用者「R_LO/HI, D_PWR を横向きに配置
    # するからそうなるのでは？縦向きに配置してみて」）。
    #
    # 横置きだと長辺がそのまま x を食う。一列に並べると
    #   R_LO 3.45 + R_HI 3.45 + SW_PWR 3.09 + D_PWR 4.79 = 14.78mm
    # だが、**XIAO の THT パッド列（±6.77..8.47）が両面を貫く**ので
    # 使えるのは中央の 13.54mm しかなく、1.24mm 足りなかった
    # （R_LO が D0 に乗って短絡・PTH 侵入・マスクブリッジの 3 件）。
    #
    # 縦向きにすると x の占有が **3.45 → 1.99mm**（1206 の D_PWR は
    # 4.79 → 2.39）。3 部品で 4.9mm 空くので中央に収まる。
    #
    # 90° と 270° の違いは端子の向き。信号は左（SENSE）→右（VBATT_SW）
    # へ流れるので、鎖の順に入口と出口が向くほうを選ぶ。
    # **ここから下の角度は、利用者が KiCad で直した基板から読み取った値**
    # （2026-08-14）。総当たりで解けなかった配置を利用者が手で解いた。
    # `pcb/hhkb_split_daughterboard.kicad_pcb` が出所。
    #
    #   R_LO   -90°  … VBATT_SENSE が右（R_HI 側）、GND が左
    #   R_HI    90°  … VBATT_SW が左、VBATT_SENSE が右で R_LO と隣り合う
    #   SW_PWR 180°  … 1 パッドのランドなので向きは配線の都合
    #   D_PWR  180°  … 横置き。VBATT_SW が左、V3V3 が右（C_BULK 側）
    #
    # ⚠️ **ここに書くのは Flip する前の角度。**裏面部品は `fp.Flip()` を
    # 通るので、**基板上の見かけの角度とは 180° ずれる**（`SetOrientation`
    # → `Flip` の順）。実測して合わせること: 0 と書くと基板では 180° に
    # なる。R_LO/R_HI/C_* の ±90 は Flip で符号が入れ替わるだけなので
    # 見かけと一致する。
    "R_LO": -90,
    # **R_HI は横置き**（2026-08-15・利用者が KiCad で直した基板から読んだ。
    # 基板上 180° = Flip 前 0）。90°（縦）から変わっている。
    "R_HI": 0,
    "SW_PWR": 0,      # 基板上では 180°
    "D_PWR": 0,       # 基板上では 180°
}

# **座標は利用者が KiCad で直した基板から読み取った**（2026-08-14）。
#
# 電源の鎖を「盤面の奥に一列 → 中央へ降りる」形に置く案は利用者の図から。
# **総当たりでは解けなかった**（一列・コンデンサ・BT1 が同じ帯を奪い合い、
# 私の探索は解ゼロを返した）。利用者が手で解いた結果がこれで、出所は
# `pcb/hhkb_split_daughterboard.kicad_pcb`。
#
# ⚠️ **この値を推測で動かさないこと。**動かすなら、KiCad で直して
# そのファイルから読み直す。私が総当たりで出した座標は、BT1 を固定扱いに
# したり一列の間隔を 0.35mm 一律にしたりと、**制約の立て方そのものを
# 間違えて何度も解ゼロを出した**（利用者の指摘で判明）。
#
# 並び（CAD 座標・x は右が正、y は奥が正、原点は板の中心）:
#
#   奥の分圧   y … R_LO(-5.40, 13.59) → R_HI(-2.00, 14.00)。R_HI は横置き
#   スイッチ           … SW_PWR(-0.50, 10.00)。一列から外して手前へ
#
# ⚠️ **2026-08-15 に利用者が R_HI と SW_PWR を動かした。**
# R_HI (-3.00, 13.59) 縦 90° → **(-2.00, 14.00) 横 0°**、
# SW_PWR (-0.50, 12.00) → **(-0.50, 10.00)**（2mm 手前へ）。
# 出所はいつもどおり `pcb/hhkb_split_daughterboard.kicad_pcb`。
#   整流               … D_PWR(3.50, 7.50) 横置き。**C_BULK の真下**
#   3V3 の隣           … C_BULK(3.00, 10.97) → C_DB(5.40, 10.50)
#
# V3V3 は D_PWR → C_BULK → C_DB → XIAO の 3V3 と、ほぼ一直線に並ぶ。
POWER_PLACE = {                 # 参照名 → (x, y)
    "R_LO":     (-5.40, 13.59),   # 分圧の下（SENSE → GND）
    "R_HI":     (-2.00, 14.00),   # 分圧の上（VBATT_SW → SENSE）。横置き
    "SW_PWR":   (-0.50, 10.00),   # 電池から来る線を受けるランド
    "D_PWR":    ( 3.50,  7.50),   # VBATT_SW → V3V3。C_BULK の真下
    "BT1":      (-0.50,  3.50),   # 電池の −（GND）。ベタで受ける
}


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


# 直角の折れに入れる 45 度の面取り（mm）。**可能な限り小さく**
# （2026-08-14・利用者「可能な限り最小のコーナーで 135 度 *2 に」）。
#
# 直角のまま曲げると、外側の角で銅が尖り、エッチングの際に
# 過剰腐食（アンダーカット）を受けやすい。45 度 2 回に割れば角が鈍る。
#
# **見た目はほぼ角のまま**にしたいので、値は最小の一辺にする。
# 線幅と同じだけ落とせば、外側の角は完全に消えて 135 度が 2 つになる。
# それ以上大きくしても角の鋭さは変わらない（斜めが長くなるだけ）。
MITER_MM = TRACK_W


def _polyline(board, pts, layer, net, miter_mm=MITER_MM):
    """点列を配線でつなぐ。**直角の折れは 45 度 2 回に割る。**

    折れ点そのものは通らず、その手前と先に `miter_mm` ずつ寄った 2 点を
    斜めで結ぶ。**線分が短くて両側に取れないときは、その半分までに
    切り詰める**（詰めすぎて線が裏返るのを防ぐ）。

    返すのは引いた区間の本数。
    """
    m = pcbnew.FromMM(miter_mm)
    out = []
    for i, p in enumerate(pts):
        if i == 0 or i == len(pts) - 1:
            out.append(p)
            continue
        a, b = pts[i - 1], pts[i + 1]
        # **入ってくる向きと出ていく向きが同じなら折れていない。**
        if (a.x == p.x and p.x == b.x) or (a.y == p.y and p.y == b.y):
            out.append(p)
            continue

        def _back(q):
            """p から q の方へ、m だけ（ただし半分を超えずに）戻った点。"""
            dx, dy = q.x - p.x, q.y - p.y
            L = max(abs(dx), abs(dy))          # 直角なのでどちらかは 0
            if L == 0:
                return p
            k = min(m, L // 2)
            return pcbnew.VECTOR2I(p.x + dx * k // L, p.y + dy * k // L)

        c1, c2 = _back(a), _back(b)
        if c1 == p or c2 == p:                 # 面取りが取れないほど短い
            out.append(p)
            continue
        out.append(c1)
        out.append(c2)

    n = 0
    for s, e in zip(out, out[1:]):
        if s != e:
            _track(board, s, e, layer, net)
            n += 1
    return n


def _via(board, pos, net):
    """ビアを 1 個立てる。上の _track と同じ理由でここにある。"""
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pos)
    v.SetWidth(pcbnew.FromMM(VIA_D))
    v.SetDrill(pcbnew.FromMM(VIA_DRILL))
    v.SetNet(net)
    board.Add(v)
    return v


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
    # **奥端へ寄せ、さらに板から XIAO_OVERHANG だけはみ出させる。**
    # 理由は 2 つあり、どちらも同じ向きに効く。
    #
    #   open-gaps #28 … 中央に置くと USB のメスが奥壁の外面から 8.9mm 奥になり、
    #                   プラグの金属 6.5mm では届かない（＝ケーブルが挿さらない）
    #   open-gaps #23 … アンテナは USB と反対の端にあるので、奥へ寄せるほど
    #                   本体基板の全面 GND ベタの下から出る
    #
    # **一度この案を「得られるのは 1.1mm だけ」として捨てていた。**理由は
    # 「奥側の取付穴が入らなくなる」だったが、ケースは 3D プリントなので
    # ネジをやめて壁のポケットで受ければよい。前提のほうが間違っていた。
    #
    # 位置は interface.xiao_y_offset が唯一の出所（ケース側の壁のポケットと
    # 同じ式から取る）。**片方だけ動かすと壁を突き破る。**
    from interface import xiao_y_offset
    x = _load(*XIAO_FP)
    x.SetPosition(to_kicad(0, xiao_y_offset(DB_D)))
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

    # パスコンとバルク（どちらも裏面・XIAO の下）。
    #
    # **電源ピンに近い側がパスコン（C_DB）。**2026-08-14 に入れ替えた
    # （利用者の指摘「バルクがパスコンを兼ねられないのか」を検討した
    # 副産物）。**兼ねられない。**同じ 100µF でも自己共振を超えると
    # インダクタになるので、帯域が違う:
    #
    #     C_BULK 100µF/1206  自己共振 約 0.5MHz   µs 級のバースト担当
    #     C_DB   0.1µF/0805  自己共振 約 19MHz    ns 級の縁を担当
    #
    #   300µs・15mA のバーストでの降下 … 100µF なら 45mV、0.1µF だと 45V
    #   （＝支えられない）。逆に 0.1MHz 超では 100µF が容量として働かない。
    #
    # **ループ長が効くのは高周波側**なので、電源ピンに近い枠は C_DB に
    # 与える。C_BULK は µs 級なので数 mm 遠くても構わない。
    # 入れ替える前は逆で、C_BULK が 2.04mm・C_DB が 6.82mm だった。
    #
    # ⚠️ **x は XIAO のパッド列（原点から ±7.62）の内側に収める。**
    # 一度 7.62 ちょうどに置いて、パッドと 0.146mm まで寄り（規則 0.2）、
    # コートヤードにも THT が 2 本入って DRC 3 件を出した。
    # パッドは幅 1.7 なので列は ±6.77..8.47。
    c = _load(KICAD_FP / f"{CAP_FP[0]}.pretty", CAP_FP[1])
    # **3V3 パッドの隣を取る**（2026-08-14）。ここが一等地で、他の部品より
    # 先に決める。V3V3/GND 両パッドへの**往復ループ長**で総当たりし
    # 10.17 → **4.49mm**（効くのは距離ではなくループ長）。
    c.SetPosition(to_kicad(5.40, 10.50))
    # **縦置き・V3V3 が手前／GND が奥**（2026-08-14・利用者「C_DB を
    # 180 度回転しては？」）。
    #
    # ⚠️ 一度 -90° にして「向きは合っている」と報告したが**逆だった**。
    # 実測すると -90° では V3V3 が奥(+0.95)・GND が手前(-0.95) で、
    # XIAO の 3V3(9.59 手前)／GND(12.13 奥) と上下が逆。**2 本が交差して
    # ループが伸びる。**90° にすると C_BULK と同じ並びになる。
    c.SetOrientationDegrees(90)
    c.SetReference("C_DB")
    c.SetValue("0.1uF")
    board.Add(c)
    c.Flip(c.GetPosition(), False)

    # **バルク。2026-08-14 に主基板から移した**（open-gaps #41）。
    # 守る相手は XIAO が µs 級の無線送信で引く電流変動
    # （electrical-design.md 1-5）。主基板に置くと FFC 100mm の
    # インダクタンスの外側から供給することになり、間に合わない。
    b_ = _load(KICAD_FP / f"{BULK_FP[0]}.pretty", BULK_FP[1])
    # **C_DB の真横**（2026-08-14・利用者が KiCad で確定）。V3V3 パッドが
    # C_DB の V3V3 と同じ高さに揃い、2 つのコンデンサが 3V3 の隣に並ぶ。
    # 出所は POWER_PLACE と同じく `pcb/hhkb_split_daughterboard.kicad_pcb`。
    b_.SetPosition(to_kicad(3.00, 10.97))
    # **縦置き**（2026-08-14・利用者の指摘「横向きに置く理由は？」）。
    # 1206 のコートヤードは 3.5x2.1mm。縦にすると x 方向の占有が
    # 3.5 → 2.1mm になり、**1.4mm を左右に返せる**。
    #
    # ⚠️ **向きは +90°。**XIAO は 3V3 が手前(y=9.59)・GND が奥(y=12.13)。
    # +90° にすると C_BULK も V3V3 が手前(9.53)・GND が奥(12.47) で
    # **同じ並び**になり、2 本が平行に短く届く。
    # -90° だと上下が逆になって交差する（利用者の指摘「向きが逆」）。
    b_.SetOrientationDegrees(90)
    b_.SetReference("C_BULK")
    b_.SetValue("100uF")
    board.Add(b_)
    b_.Flip(b_.GetPosition(), False)

    # **電源部（裏面）。2026-08-14 に主基板から移した**（open-gaps #41）。
    #
    # 種類 → フットプリントは **gen_pcb.ELEC_FP が唯一の出所**。
    # ここに書き写すと主基板と食い違う（同じ部品なので必ず一致させる）。
    from gen_pcb import ELEC_FP
    for ref, (x, y) in POWER_PLACE.items():
        kind, pins = parts[ref]
        lib, name, value = ELEC_FP[kind]
        # 電池ボックスと電源スイッチは「基板に載らない部品」で、
        # 基板側はランドで受ける。**端子の数だけランドを置く**
        # （主基板の gen_pcb と同じ規則。BT1 は GND だけ・
        #  SW_PWR は VBATT_SW だけなので、どちらも 1 個）。
        wire = kind in WIRE_PAD_KINDS
        for k, pin in enumerate(pins if wire else [None]):
            fp = _load(KICAD_FP / f"{lib}.pretty", name)
            fp.SetPosition(to_kicad(x + k * 4.0, y))
            if ref in POWER_ROT:
                fp.SetOrientationDegrees(POWER_ROT[ref])
            fp.SetReference(f"{ref}_{pin}" if wire else ref)
            fp.SetValue(value)
            board.Add(fp)
            fp.Flip(fp.GetPosition(), False)
            if wire:
                fp.Pads()[0].SetNet(net(pins[pin]))

    # 取付穴（ケースのボスと同じ位置）
    for i, (mx, my) in enumerate(DB_BOSS_POS, start=1):
        h = _load(KICAD_FP / f"{MOUNT_FP[0]}.pretty", MOUNT_FP[1])
        h.SetPosition(to_kicad(mx, my))
        h.SetReference(f"H{i}")
        board.Add(h)

    # ネットを割り当てる。**回路の宣言をそのまま使う。**
    for ref, (kind, pins) in parts.items():
        # ランドで受ける部品は、置くときに 1 個ずつネットを付けてある
        # （基板上では `BT1_-` のように割れていて `BT1` は存在しない）。
        if kind in WIRE_PAD_KINDS:
            continue
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            raise RuntimeError(f"{ref} が基板に無い（回路には宣言されている）")
        for pin, netname in pins.items():
            if netname == "NC":
                continue
            # **本体基板と同じ経路（pinmap）を通す。**この子基板は
            # ピン名とパッド名が偶然そろっていたので無事だったが、
            # 本体基板は同じ場所で 74LVC595 を丸ごと落としていた。
            pad_no = pinmap.resolve(kind, pin)
            if pad_no is None:
                continue          # 回路図だけにあるピン（XIAO の BAT）
            pad = fp.FindPadByNumber(pad_no)
            if pad is None:
                raise RuntimeError(f"{ref} に端子 {pin}（パッド {pad_no}）が無い")
            pad.SetNet(net(netname))

    _shrink_silk(board)

    # **順序が効く**（2026-08-14・利用者の指摘）。
    #
    #   1. アンテナの禁止域 … 配置と配線の**制約**なので最初。
    #      以前は _route のあとに置いていた（＝配線は禁止域を知らずに
    #      引かれていた）。
    #   2. ネットクラス      … 配線の幅を決めるので配線より前。
    #
    # **3. 配線と 4. ベタ・ビアは autoroute.py の仕事**（2026-08-14）。
    #
    # **FFC → XIAO のレーンは自分で引き、電源だけ自動配線器に任せる。**
    #
    # 2026-08-14 に一度この `_route` を捨てて全部 Freerouting にしたが、
    # **絵を見たら明らかに無駄だった**（利用者の指摘）。ROW0 が直線
    # 22.4mm のところを **39.1mm**（75% 増）かけて盤面を斜めに横断し、
    # ROW3 は板の縁の外（x=-9.68）まで回り込んでいた。
    #
    # **手配線はやめた**（2026-08-14・利用者「手配線をやめてください」）。
    #
    # ここは長く `_route()` でレーンを手で引いていた。理屈は「レーンは
    # 経路に選択の余地が無いので自分で引くほうが良い。引いた線は DSN に
    # `(type protect)` で乗るので自動配線器は避ける」だった。
    #
    # ⚠️ **その前提が実装と食い違っていた。**protect にするのは
    # `autoroute._strip_prewired` だが、対象は `PREWIRED = GND|SW\d+_D`
    # だけで、**ROW/CS/SPI は protect にならず DSN に「未配線」として
    # 残る。**Freerouting が同じネットをもう一度引き、**同じネットの
    # 2 本の経路どうしが交差した**（2026-08-14 に実測: 交差 5 件のうち
    # 左列 3 件が ROW2/ROW3/ROW4 の自分自身との交差）。
    #
    # 2026-08-14 まで気づかなかったのは、`autoroute.py` の
    # `if __name__` がファイル中央にあり、**子基板の処理が NameError で
    # 落ちて手配線のまま保存されていた**ため（同日に修正）。落下が
    # 直った瞬間に二重配線が表に出た。
    _antenna_keepout(board)
    _add_power_netclasses(board)
    _prewire_power(board)
    # **外側レーンの 3 本は列の外の帯を通す**（2026-08-14・利用者の指定）。
    #
    # ⚠️ **ファンアウトのビアはこの線を避けない。**`gnd_fanout.spots` は
    # 意図的にパッドだけを見る（配線前後で同じ座標を返すため）。
    # ここで引いた線とビアがぶつかっていないかは **DRC で確かめる**。
    _prewire_rows(board)
    # **右列も同じ形で引く**（2026-08-14・利用者「左右対称に」）。
    _prewire_rows(board, RIGHT_OUTER_LANE_PADS, side=+1)
    # **GND のファンアウトを配線より前に打つ**（2026-08-14）。
    #
    # ⚠️ **主基板にあってここに無かった。**`gen_pcb` は配置段階で
    # `gnd_fanout.place` を呼ぶので、ビアが DSN に載って Freerouting が
    # 避ける（実測: 未配線の左 5 個・右 10 個）。**子基板は 0 個だった。**
    #
    # `autoroute` は SES 取り込みのあとに `place` をもう一度呼び、
    # 「位置は決定的なので配線前と同じところに戻り、Freerouting は
    # そこを避けて配線済み」と書いてある。**その前提が子基板では
    # 成り立っていなかった。**空き地だと思って引かれた ROW1 の上に、
    # あとからビアが立った（DRC のクリアランス違反 1 件・**0.0091mm**
    # ＝実質短絡。2026-08-14 に実測）。
    #
    # `spots()` はパッドだけを見るので、ここで呼んでも `autoroute` が
    # 呼んでも同じ座標を返す（実測で一致を確認済み）。
    import gnd_fanout
    gnd_fanout.place(board)

    UNROUTED.mkdir(parents=True, exist_ok=True)
    path = UNROUTED / "hhkb_split_daughterboard.kicad_pcb"
    board.Save(str(path))
    return path, len(nets)


def _prewire_power(board):
    """電源のパッドどうしを、**パッドの座標から計算して**直線で繋ぐ。

    **座標を書かない。**`POWER_PLACE` を動かせば配線も追随する。

    ⚠️ **なぜ自動配線器に任せないか**（2026-08-14・利用者が絵で指摘）。
    V3V3 は 4 つのパッドがほぼ一直線に並んでいるのに、Freerouting は
    **8.37mm・6 セグメント**で斜めに蛇行していた。行バスと同じ理屈で、
    **経路に選択の余地が無いものは自分で引く**（autoroute.py の冒頭に
    「一直線にしたいなら DSN の設定ではなく自分で引く」と実測つきで
    書いてある。`(autoroute_settings)` を足すと未配線が 1 → 66 に激増した）。

    ⚠️ **GND パッドの引き出しも、ここが唯一の出所。**
    2026-08-14 に手配線 `_route` を消したとき、この引き出しも一緒に
    消えて **FFC の GND パッドが未配線になった**（ベタの上にあるだけでは
    繋がらない。DRC の「Missing connection」1 件がこれだった）。

    引いた線は `autoroute._strip_prewired` が `(type protect)` にして
    DSN へ渡す。**PREWIRED に V3V3 を足してあるのが対**——足し忘れると
    Freerouting が同じネットを二重に引く。
    """
    def cad(p):
        return (pcbnew.ToMM(p.x) - ORIGIN[0], ORIGIN[1] - pcbnew.ToMM(p.y))

    pads = {}
    for fp in board.Footprints():
        for pad in fp.Pads():
            n = pad.GetNetname()
            if n in ("V3V3", "GND"):
                pads.setdefault(n, []).append((fp.GetReference(), pad))

    # ---- V3V3 ----
    #
    # **上の群（D_PWR → C_BULK → C_DB → XIAO）だけ引く。**
    #
    # ⚠️ **FFC の 1 本（0.75, -9.15）は x 順の鎖に入れない。**混ぜると
    # D_PWR(2.50) の左に入り、板を縦断する線が他のパッドを横切って
    # DRC が 4 件出た（2026-08-14 に実測）。17mm 上がる経路は
    # 「縦に降ろしてから横」の別扱いが要る——下の `_v3_from_ffc` がそれ。
    # ⚠️ **一列から外れているものを鎖に挟まないこと**（2026-08-15・利用者
    # 「C_DB と D_PWR の間で不要に 2 本配線が伸びてる」）。
    #
    # 鎖は x 順なので `C_BULK(153.0) → D_PWR(155.15) → C_DB(155.4)` の順に
    # なるが、**D_PWR だけ y=92.5 と 2mm 下にある。**そのため鎖が
    # 「C_BULK から下へ降りて D_PWR、また上がって C_DB」と往復し、
    # C_DB と D_PWR の間に**縦線が 2 本**並んでいた（実測: 155.15 を
    # 降りる 1.995mm と 155.4 を上がる 2.050mm）。
    #
    # **横一列に乗っているものだけで鎖を作り、外れたものは最寄りへ 1 本。**
    # 一列の y は最頻値で決める（数字を書かない）。
    v_all = [(cad(p.GetPosition()), ref, p) for ref, p in pads.get("V3V3", [])
             if ref != "J_MAIN"]
    ys = [pcbnew.ToMM(p.GetPosition().y) for _c, _r, p in v_all]
    row = max(set(ys), key=ys.count)        # 一列が居る y（最頻値）
    tol = TRACK_W + pcbnew.ToMM(                     # 「同じ列」とみなす幅
        board.GetDesignSettings().m_NetSettings
        .GetDefaultNetclass().GetClearance())
    v = [t for t in v_all
         if abs(pcbnew.ToMM(t[2].GetPosition().y) - row) <= tol]
    off = [t for t in v_all if t not in v]  # 列から外れたもの（D_PWR）
    v.sort(key=lambda t: t[0][0])           # x の小さい順＝流れの順
    n_v3 = 0
    for _c, _r, pf in off:
        # **最寄りの一列パッドへ L 字で 1 本。**往復にならない。
        near = min(v, key=lambda t: abs(t[2].GetPosition().x
                                        - pf.GetPosition().x))[2]
        corner = pcbnew.VECTOR2I(pf.GetPosition().x, near.GetPosition().y)
        for s, e in ((pf.GetPosition(), corner), (corner, near.GetPosition())):
            if s != e:
                _track(board, s, e, pcbnew.B_Cu, pf.GetNet())
                n_v3 += 1
    for (a, _ra, pa), (b, _rb, pb) in zip(v, v[1:]):
        # **L 字で繋ぐ。**y が完全に一致していれば横 1 本になる
        # （`_track` は同じ点なら引かないので、余分な線は残らない）。
        # 先に x を合わせてから y——縦に降ろす区間を右側（消費側）に
        # 寄せると、左から来る他の枝と当たりにくい。
        corner = pcbnew.VECTOR2I(pb.GetPosition().x, pa.GetPosition().y)
        for s, e in ((pa.GetPosition(), corner), (corner, pb.GetPosition())):
            if s != e:
                _track(board, s, e, pcbnew.B_Cu, pa.GetNet())
                n_v3 += 1

    # **FFC への V3V3 は、右列のレーンが引く**（2026-08-14・利用者
    # 「左右対称に」）。かつてここに「FFC のパッド列の右外を回って
    # 上の群へ繋ぐ」経路があったが、**3V3 パッド ↔ FFC 2 番を
    # `_prewire_rows` が外側レーンで引くようになり、二重になった**
    # （実測: V3V3 が 2 経路で FFC に繋がっていた。利用者の指摘）。
    # 上の群へは 3V3 パッド経由で届くので、ここでは何もしない。
    # ---- GND ----
    #
    # **ベタへ短く引き出すだけ。**GND はベタで配るので、パッドどうしを
    # 繋ぐ必要は無い。**ベタの上にあるだけでは繋がらない**ので、
    # パッドから短い枝を 1 本出してベタに食い込ませる。
    #
    # ⚠️ **向きは「部品の外側へ」。**「板の中心へ」で書いて、C_DB の
    # GND(y=11.85) から下へ 1.5mm 引いたら**同じ部品の V3V3(9.95) に
    # 突き当たった**（短絡・クリアランス・マスクブリッジで 3 件。
    # 2026-08-14）。2 端子の部品は、相手の端子と反対を向く。
    fps = {fp.GetReference(): fp for fp in board.Footprints()}
    # **ビアで受けるパッドには引かない**（2026-08-15・利用者
    # 「GND は同じベタに 2 つ生えています。両方いるか、という事です」）。
    #
    # ここの引き出しと `gnd_fanout.place` のスタブは**どちらも同じパッドから
    # B.Cu へ出る**ので、両方走ると 1 つのパッドに 2 本生える。実測
    # （2026-08-15・配線後の子基板）: GND パッド 6 個に対しスタブ **11 本**。
    # うち 4 組は始点も向きも同じで、**こちらの 1.2mm が、ビアへ向かう
    # スタブの完全な部分区間**（手前で止まるだけ）だった。
    #
    #   R_LO   1.250 → ビア ／ 1.200 ここ
    #   BT1_-  1.550 → ビア ／ 1.200 ここ
    #   C_BULK 1.450 → ビア ／ 1.200 ここ
    #   C_DB   1.275 → ビア ／ 1.200 ここ
    #   J_MAIN 0.700 → ビア ／ 1.200 ここ（向きは違うが両方ベタに届く）
    #
    # **ビアはベタの両面に繋ぐ**ので、ビアが立つパッドではこちらの
    # 引き出しは電気的に何も足していない。
    #
    # ⚠️ **スルーホールのパッドには引かない**（2026-08-15・利用者
    # 「GND から伸びている配線が治ってない」）。
    #
    # **穴そのものが両面のベタを貫いている**ので、ベタへの引き出しは
    # 要らない。実測: 子基板の GND パッド 6 個のうち **U_MCU だけが PTH**
    # （穴 1.00mm・F.Cu と B.Cu の両方に乗る）で、残り 5 個は SMD。
    #
    # ⚠️ **「最寄りのビアまで 3.22mm あるから残す」と書いたのは誤り。**
    # あれは**スタブの端**から測った値で、パッドの中心からは 2.13mm。
    # そして距離の問題ですらなかった——PTH なら距離に関係なく繋がる。
    #
    # 残す条件は「ビアが立たない **SMD**」。478-481 行の
    # 「消したら未配線になった」
    # はこの状態のこと。
    #
    # ⚠️ **`place()` ではなく `spots()` を呼ぶ。**副作用が無く、パッドしか
    # 見ないので配線の前後で同じ答えを返す（gnd_fanout.py:227-232）。
    import gnd_fanout
    by_via = {(r.GetReference(), p.GetNumber())
              for p, _xy in gnd_fanout.spots(board)
              for r in (p.GetParentFootprint(),)}
    n_gnd = 0
    n_skip = 0
    for ref, pad in pads.get("GND", []):
        # **穴が両面を貫いているものは、それだけでベタに繋がる。**
        if pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH,
                                  pcbnew.PAD_ATTRIB_NPTH):
            n_skip += 1
            continue
        if (ref, pad.GetNumber()) in by_via:
            n_skip += 1
            continue
        # ⚠️ **FFC は向きを縦に固定する**（2026-08-14）。パッドは 0.5mm
        # ピッチで**横に並ぶ**ので、縦（板の内側）へ伸ばすぶんには隣に
        # 当たらない。部品の中心から見た向きで決めると、端のパッドほど
        # 斜めを向いて隣の CS に突っ込んだ（実測で 2 回短絡）。
        if ref == "J_MAIN":
            p = pad.GetPosition()
            # **列の外側（＝板の手前・下）へ逃がす**
            # （2026-08-14・利用者「反対側（列の外側 = J_MAIN 側）に」）。
            #
            # 縦（板の内側＝上）へ 1.2mm 伸ばしていたが、**そこは
            # 外側レーンが列の左へ抜ける通路**で、3 本ともこの先端を
            # 越えるために一度上がって降り直していた
            # （往復 2.70mm × 3 本 = **8.1mm** の無駄）。
            #
            # 反対の下へ向ければ通路が空く。**下は MP パッドが居るので
            # そこだけ避ける**（MP は y -13.50..-11.30・x ±3.75..5.55）。
            e = pcbnew.VECTOR2I(p.x, p.y + pcbnew.FromMM(1.2))       # 列の外側へ
            _track(board, p, e, pcbnew.B_Cu, pad.GetNet())
            n_gnd += 1
            continue
        fp = fps[ref]
        c = fp.GetPosition()
        p = pad.GetPosition()
        # 部品の中心 → このパッド の向きへ伸ばす（＝相手の端子から離れる）。
        # 1 端子のランド（BT1/SW_PWR）は中心と一致するので、そのときだけ
        # 板の中心から離れる向きを使う。
        dx, dy = p.x - c.x, p.y - c.y
        if dx == 0 and dy == 0:
            x, y = cad(p)
            dx, dy = 0, (1 if y > 0 else -1)
        L = (dx * dx + dy * dy) ** 0.5
        # ⚠️ **長さを一律にしない。**1.2mm 固定で書いたら、0.5mm ピッチの
        # FFC で GND の枝が隣の CS まで届いて短絡した（2026-08-14）。
        #
        # ⚠️ **「隣のパッドまでの距離」で測るのも駄目。**FFC はパッドが
        # 横に並ぶので隣までは 0.5mm しかなく、**縦に伸ばす枝まで 0.25mm に
        # 縮んで**ベタに届かず未配線になった（長さ 0.0000mm の線ができた）。
        #
        # **伸ばす向きに実際に何があるか**で決める。他のパッドを、
        # 進行方向へ射影して測り、当たるものだけ見る。
        ux, uy = dx / L, dy / L
        room = pcbnew.FromMM(1.2)
        for q in fp.Pads():
            if q is pad:
                continue
            v = q.GetPosition() - p
            t = v.x * ux + v.y * uy                 # 進行方向の成分
            if t <= 0:
                continue                            # 後ろにあるものは無関係
            side = abs(-v.x * uy + v.y * ux)        # 横へのずれ
            if side < pcbnew.FromMM(0.9):           # 進路上にある
                room = min(room, int(t * 0.5))
        step = max(room, pcbnew.FromMM(0.4))        # ベタに食い込む最低限
        e = pcbnew.VECTOR2I(int(p.x + ux * step), int(p.y + uy * step))
        _track(board, p, e, pcbnew.B_Cu, pad.GetNet())
        n_gnd += 1
    print(f"      電源を自分で配線: V3V3 {n_v3} 区間 / GND 引き出し {n_gnd} 本"
          f"（ビアで受ける {n_skip} 本はビア側に任せた）")


# リファレンスの文字高（mm）。**この基板だけ小さくする。**
#
# 主基板は 1.0mm のままでよい（`silk_overlap` は左 5・右 6 件）。
# **子基板だけ 14 件**あった——板が 21mm 幅しかないのに電源部 5 個が
# 奥に固まっていて、`SW_PWR_1` のような 8 文字が隣の部品へ乗る。
#
# **0.8mm が下限。**総当たりで測った（2026-08-14。ゾーンを塗り直して
# いない仮の基板なので `copper_edge_clearance` は無視して警告だけ見る）:
#
#     1.0mm … silk_overlap 14
#     0.9mm … silk_overlap  8
#     0.8mm … silk_overlap  6   ← ここ
#     0.7mm … silk_overlap  6 ＋ **text_height 11**（KiCad の下限に触れる）
#
# **線幅（0.15mm）は動かさない。**JLCPCB のシルク最小線幅で、
# `pcb_rules.JLC["silk_width"]` が唯一の出所。細くするとかすれる。
# 高さだけ縮めるので、線幅との比は 0.8/0.15 ≒ 5.3 倍で読める範囲に残る。
SILK_REF_MM = 0.8


def _shrink_silk(board):
    """リファレンスの文字を `SILK_REF_MM` まで縮める。

    **全部品を置き終えてから呼ぶ**（gen_pcb の線幅の正規化と同じ理由。
    先に呼ぶと、あとで足した部品だけ 1.0mm のまま残る）。
    """
    n = 0
    for fp in board.GetFootprints():
        r = fp.Reference()
        if pcbnew.ToMM(r.GetTextWidth()) > SILK_REF_MM:
            r.SetTextSize(pcbnew.VECTOR2I_MM(SILK_REF_MM, SILK_REF_MM))
            n += 1
    print(f"      シルクの参照名 {n} 個を {SILK_REF_MM}mm へ")
    _place_silk(board)


# **参照名の位置**（部品ローカル mm・文字角度）。
#
# ⚠️ **自動で逃がすのはやめた**（2026-08-15）。4 方向を試して空きを探す
# 実装を書いたが、判定を厳しくするほど「どこも当たる＝動かさない」が
# 増え、**警告が 13 → 10 → 13 → 15 件と、直すたびに悪化した。**
# 21x32mm に部品が固まっているので、機械的な 4 方向では解が無い。
#
# **利用者が KiCad で並べたものを、そのまま出所にする**
# （`POWER_PLACE` と同じ方針。総当たりで解けないものは手で解く）。
# 出所は `pcb/hhkb_split_daughterboard.kicad_pcb`。
#
# ⚠️ **この値を推測で動かさないこと。**動かすなら KiCad で直して
# ここへ読み直す（下の `_read_silk_from` で吸い出せる）。
#
# **2026-08-16 に利用者が KiCad で並べ直した**（`_read_silk_from` で吸い出し）。
# それまでは `silk_overlap` が 5 件残っていた。全部が「ラベルが自分の
# 部品の外形線に近すぎる」型で、**この基板の警告は 0 件になった**
# （違反 0 / 未配線 0 / 警告 0。`kicad-cli pcb drc` で確認）。
#
# ⚠️ **余白は 0.15mm ぎりぎりで釣り合っている。**`SW_PWR_1` は最後の
# 1 件を消すのに 0.01mm 動かして通した（不足は 0.0035mm だった）。
# **1 つでも動かすと再発する。**動かしたら必ず DRC を回し直すこと。
SILK_REF = {                  # 参照名 → (dx, dy, 文字角度)
    "BT1_-":    (-0.010, -1.940,   0.0),
    "C_BULK":   ( 1.540, -1.570, 270.0),
    "C_DB":     ( 3.140, -0.360,   0.0),
    "D_PWR":    ( 0.010, -1.730,   0.0),
    "H1":       ( 0.000, -2.300,   0.0),
    "H2":       ( 0.000, -2.300,   0.0),
    "J_MAIN":   ( 0.000,  3.906,   0.0),
    "R_HI":     ( 0.350, -1.550,   0.0),
    "R_LO":     ( 3.890, -0.020, 270.0),
    "SW_PWR_1": ( 1.930, -1.310, 270.0),
    "U_MCU":    ( 0.000, 11.656,   0.0),
}


def _place_silk(board):
    """`SILK_REF` のとおりに参照名を置く。

    **表に無い部品は触らない**（フットプリントの既定のまま）。
    表にあるのに基板に無い名前は、綴り違いに気づけるよう報告する。
    """
    seen = set()
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref not in SILK_REF:
            continue
        dx, dy, ang = SILK_REF[ref]
        r = fp.Reference()
        r.SetFPRelativePosition(pcbnew.VECTOR2I_MM(dx, dy))
        r.SetTextAngle(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T))
        seen.add(ref)
    missing = sorted(set(SILK_REF) - seen)
    if missing:
        raise RuntimeError(
            f"SILK_REF に基板に無い参照名がある: {missing}。"
            "**綴りを直すか、表から消すこと**")
    print(f"      参照名 {len(seen)} 個を SILK_REF のとおりに置いた")


def _read_silk_from(path):
    """**基板から `SILK_REF` を吸い出して表示する**（保守用）。

    利用者が KiCad でシルクを並べ直したら、これを実行して
    上の `SILK_REF` に貼り替える。**手で座標を書き写さない。**

        KPY=/Applications/KiCad/.../python3.9
        "$KPY" -c "import sys;sys.path.insert(0,'tools');\
    import gen_daughterboard as g;g._read_silk_from('pcb/hhkb_split_daughterboard.kicad_pcb')"
    """
    b = pcbnew.LoadBoard(str(path))
    print("SILK_REF = {")
    for fp in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
        r = fp.Reference()
        if not r.IsVisible():
            continue
        lp = r.GetFPRelativePosition()
        print(f'    "{fp.GetReference()}": '
              f'({pcbnew.ToMM(lp.x):6.3f}, {pcbnew.ToMM(lp.y):6.3f}, '
              f'{r.GetTextAngle().AsDegrees():5.1f}),')
    print("}")


# 「列の外の帯」を通す 3 本。**外周から内側へ。**
#
# ⚠️ **ROW の名前で持たない**（2026-08-14・利用者。3 度指摘された）。
# 「どのレーンを通るか」は **XIAO のパッド**の話であって、そこに載る
# 信号が ROW0 か ROW2 かは無関係。ROW 名で書くと、利用者が内外を
# 入れ替えるたびに表と実物がずれ、**ここで実際に交差を 2 件出した。**
# **パッド番号で持ち、ネット名はパッドから引く。**
#
# 列の外は D1（最も板端）→ D2（真ん中）→ D3（最も内側）。
# **D1 は用途未定の予備**だが、後から線は足せないので今のうちに通す。
OUTER_LANE_PADS = ("D1", "D2", "D3")

# **片側あたりのレーン本数。**右列は GND を外して 2 本だが、
# 位置は 3 本ぶんの幅に散らす（真ん中を空ける）。上の `span` を参照。
LANES_PER_SIDE = 3


def _lane_nets(board, pad_numbers):
    """XIAO のパッド番号の並び → そこに載っているネット名の並び。

    **レーンの並びはパッドで決まり、信号はパッドから引く**（利用者・
    2026-08-14）。ROW 名を表に書くと、内外の割り当てを変えるたびに
    表と実物がずれる。ここで一度だけ実物を見て名前に直す。
    """
    mcu = board.FindFootprintByReference("U_MCU")
    out = []
    for num in pad_numbers:
        pad = mcu.FindPadByNumber(pinmap.resolve("xiao_nrf52840", num))
        n = pad.GetNetname()
        if not n:
            raise RuntimeError(
                f"{num}: ネットが付いていない。**レーンに載せる以上、"
                "circuit.py で何かに繋いでおくこと**")
        out.append(n)
    return tuple(out)


def _prewire_rows(board, pad_names=None, side=-1):
    """**外側レーンの 3 本（D1/D2/D3）を XIAO のパッド列の外側に通す**
    （2026-08-14・利用者）。

    自動配線器はこの帯を使わない。実測（配線後の基板）では列の外へ出て
    いたのは 2 本だけで、ROW4 はパッドの x=-7.62 で止まっていた。
    **経路に選択の余地が無いものは自分で引く**——`_prewire_power` と
    同じ理屈（autoroute.py 冒頭の「一直線にしたいなら DSN の設定では
    なく自分で引く」）。

    帯に何本入るかは**設計規則から出す。数字を書かない**:

        板の左端 -10.50 + 端クリアランス 0.30 + 線幅/2  →  -10.10
        パッドの左端 -8.47 − クリアランス 0.20 − 線幅/2 →  -8.77
        使える幅 1.33mm ／ 1 本あたり 0.40mm → **4 本入る**（要るのは 3 本）

    経路は **L 字 3 回だけ**（2026-08-14・利用者「クネクネ迂回はやめて。
    最短で」）:

        FFC パッド → 列の端をこえる高さまで上へ → **外周レーンまで一気に
        左へ** → レーンを上がる → XIAO パッドへ右に入る

    ⚠️ **途中で上下に振らないこと。**一度は「上へ → 左へ → **下へ** →
    左へ → 上へ」と 5 回折れていた。中ほどの上下は 12 番 GND の引き出しが
    列の内側へ伸びていた頃の名残で、その引き出しを列の外側（下）へ
    向けた時点で**不要になっていた**。消したら 3 本の総長が
    **83.37 → 71.07mm**（各行とも外周経由の最短と一致）。

    横へ抜ける高さ（`over`）だけ行ごとにずらせば 3 本は交差しない。

    ⚠️ **`autoroute.PREWIRED_DB` に `ROW[234]` を入れるのが対。**
    入れないと DSN に未配線として残り、Freerouting が二重に引いて
    **同じネットが自分自身と交差する**（2026-08-14 に実際に起きた）。
    """
    d = board.GetDesignSettings()
    edge = pcbnew.ToMM(d.m_CopperEdgeClearance)
    clr = pcbnew.ToMM(d.m_NetSettings.GetDefaultNetclass().GetClearance())

    outer = _lane_nets(board, pad_names or OUTER_LANE_PADS)
    pads = {}
    for fp in board.Footprints():
        ref = fp.GetReference()
        if ref not in ("U_MCU", "J_MAIN"):
            continue
        for pad in fp.Pads():
            n = pad.GetNetname()
            if n in outer:
                pads.setdefault(n, {})[ref] = pad

    # パッド列の左端（=帯の内側の限界）と板の左端から、レーンの中心を出す。
    # **`side` は列の向き**（-1 = 左列 / +1 = 右列。2026-08-14・利用者
    # 「D1〜D6 を完璧に真似る形で、左右対称に」）。以前は左向きが
    # `min` や `-DB_W/2` として直書きされていた。**符号 1 つで両方を
    # 引けるようにし、規則は 1 か所に保つ。**
    xs = [pcbnew.ToMM(p.GetPosition().x) - ORIGIN[0]
          + side * pcbnew.ToMM(p.GetSize().x) / 2
          for n in outer for r, p in pads[n].items() if r == "U_MCU"]
    pad_edge = min(xs) if side < 0 else max(xs)   # 列の、板端に近いほうの縁
    inner = pad_edge + side * (clr + TRACK_W / 2)  # いちばんパッド寄りのレーン
    outer_limit = side * (DB_W / 2 - edge - TRACK_W / 2)
    pitch = TRACK_W + clr

    # **横へ出る帯は、FFC のパッド列と取付パッド（MP）の間に収める。**
    #
    # ⚠️ MP はネットを持たない機構用のパッドなので「GND でも ROW でも
    # ない相手」で、クリアランスがそのまま効く。最初これを見ずに
    # y=-10.75..-11.55 へ降ろしたら、**MP（y -13.50..-11.30）に刺さって
    # 短絡・クリアランス・マスクブリッジの 3 件を出した**（2026-08-14）。
    # `_prewire_power` が同じ罠を踏んでいて、そこにも同じ注意書きがある。
    row_y = max(p.GetPosition().y for n_ in outer
                for r, p in pads[n_].items() if r == "J_MAIN")
    mp_top = min((q.GetPosition().y - q.GetSize().y // 2)
                 for fp in board.Footprints() if fp.GetReference() == "J_MAIN"
                 for q in fp.Pads() if q.GetNumber() == "MP")
    need = pcbnew.FromMM(TRACK_W / 2 + clr)
    lo, hi = row_y + need, mp_top - need         # 使える帯（y は下が正）
    if hi - lo < (len(outer) - 1) * pcbnew.FromMM(pitch):
        raise RuntimeError(
            "FFC の列と取付パッドの隙間に横枝 3 本が入らない"
            f"（{pcbnew.ToMM(hi - lo):.2f}mm）。**黙って詰めないこと**")

    # **束は「板端」と「パッドの縁」のまん中に置く**（2026-08-14・利用者
    # 「右に寄せるというより、絶縁部も含めて中央揃えが正しいのでは」）。
    #
    # ⚠️ **クリアランスを足した内側で中央を取ると、まん中にならない。**
    # 板端側は端クリアランス 0.30、パッド側は銅間クリアランス 0.20 と
    # **足す量が違う**ので、その差 0.10mm がそのまま偏りになる
    # （実測: 板端 0.56mm に対しパッド側 0.46mm）。
    #
    # どちらへ寄せても「規則は満たすが余裕が無い」側ができる:
    #   板端へ寄せる  … ROW2 が板端まで 0.30mm（規則ちょうど）
    #   パッドへ寄せる … ROW4 が D6 のパッドまで 0.20mm（規則ちょうど）
    #
    # **障害物の縁そのもの**（板端 -10.50 と パッドの左端 -8.47）で
    # まん中を取り、そこへ束の中心を置く。左右の空きが等しくなる。
    # ⚠️ **束の幅は「左列の本数」で取る**（2026-08-14・利用者）。
    #
    # 右列は GND を外したので 2 本しか無いが、素朴に 2 本ぶんの幅で
    # 束ねると**帯の中央に寄って 3V3 と D10 が隣り合う。**利用者の
    # 指示は「D10 と離す意図で、両方を可能な限り離せるように、鏡像の
    # 3 本ラインの左端と右端と同様の配線に」。
    #
    # そこで幅は常に `LANES_PER_SIDE`（＝左列の本数）で取り、
    # **本数が足りない側は真ん中の枠を空ける。**
    lanes = max(len(outer), LANES_PER_SIDE)
    span = (lanes - 1) * pitch
    mid = (side * DB_W / 2 + pad_edge) / 2       # 板端とパッド縁のまん中
    innermost = mid - side * span / 2            # 束の内側の端
    # **どちらの列でも「内側へはみ出す」「板端を越える」を見る。**
    # 左列は x が負の側なので、素朴な大小比較は向きが逆になる。
    # `side` を掛けて「内側が正」に揃えてから比べる。
    if (innermost - inner) * side < 0 \
            or (innermost + side * span - outer_limit) * side > 0:
        raise RuntimeError(
            f"列の外の帯に {len(outer)} 本入らない"
            f"（{outer_limit:.2f}..{inner:.2f}・要 {span:.2f}mm）")

    n = 0
    for i, name in enumerate(outer):
        # i=0 が最も外（D1）。いちばん内側のレーンを基準に、外へ 1 本ずつ。
        # **本数が足りないときは、外から詰めずに両端へ寄せる。**
        # i=0 を最外、最後の 1 本を最内に固定し、間を空ける。
        slot = i if i == 0 else lanes - (len(outer) - i)
        lane = innermost + side * (lanes - 1 - slot) * pitch
        if (lane - outer_limit) * side > 0:   # 板端を越えた
            raise RuntimeError(
                f"{name}: レーン x={lane:.2f} が板の端を越える"
                f"（限界 {outer_limit:.2f}）。**黙って詰めないこと**")
        mcu = pads[name]["U_MCU"]
        ffc = pads[name]["J_MAIN"]
        # **外周へ行くものほど、深い（＝ FFC から遠い）帯で左へ抜ける。**
        #
        # ⚠️ 逆に書いて 3 交差を出した（2026-08-14）。ROW2 は最も外の
        # レーン（-10.10）まで行くので、浅い帯で折れると **ROW3/ROW4 の
        # 縦のレーンを横切ってしまう。**深い帯で折れれば、内側の 2 本の
        # レーンの**下**をくぐって外へ抜けられる。
        #
        #   最も内のレーン（D3）… 浅い帯で折れる
        #   最も外のレーン（D1）… 深い帯で折れる
        # **帯は最も外のものが最も深い**（総当たりで求めた解。2026-08-14）。
        drop = lo + (lanes - 1 - slot) * pcbnew.FromMM(pitch)
        lane_x = pcbnew.FromMM(ORIGIN[0] + lane)
        # ⚠️ **パッド列の下を横切らない**（2026-08-14）。
        #
        # 最初は FFC パッドの真下へ降りてから左へ走らせていたが、
        # 列は 0.5mm ピッチなので **隣のパッド（12 番 GND など）を
        # 横断して短絡した**（tracks_crossing 2・shorting 2・
        # マスクブリッジ 5 の計 9 件）。列の下に横断する余地は無い。
        #
        # **列の左端の外へ出てから降りる。**12 番（x=-2.75・縁 -2.90）が
        # 列の左端なので、その外側を通れば列とは交わらない。
        # **列の上（内側）を、行ごとに違う高さで左へ抜ける。**
        # パッドは y=-9.15 から上へ 0.65mm（高さ 1.3）なので、その上に
        # 行ごとの通路を作る。外周へ行くものほど**上**を通り、
        # 列の左端より外の**行ごとに違う x** で下へ降りる。そうすると
        # 3 本は最後まで一度も同じ線に乗らない。
        # **並びは総当たりで求めた**（2026-08-14）。手で推論して 3 回外した
        # （12 交差 → 6 → 6）。上下の順序を揃えるという直感は**成り立たない**。
        #
        #   通路 y … ROW2 が最も上（＝列から最も離れる）
        #   降りる x … **ROW2 が最も内側**（ここだけ逆。外周へ行くものが
        #              手前で降り、外側の帯を通って外のレーンへ向かう）
        #   帯 y   … ROW2 が最も深い
        # ⚠️ **GND の引き出しの先端より内側を通す**（2026-08-14）。
        # 12 番（GND）はパッドから列の内側へ 1.2mm 伸びており
        # （x=-2.75・y=-9.15 → -7.95）、通路がその横腹を貫いていた
        # （交差 1・短絡 1）。**`_prewire_power` が先に引くので、
        # ここでは「そこにある」前提で避ける。**
        # **通路は列の内側（上）に取る。この往復は無駄ではない**
        # （2026-08-14・利用者「迂回するような動きはしてほしくない。最短で」
        #  を受けて総当たりで確認した）。
        #
        # 「下へ出てそのまま左」なら往復が消えて短くなるが、**交差 0 の解が
        # 1 つも無い**（3 折れでも 4 折れでも必ず 3 交差）。外周レーンは
        # FFC パッドより左にあるので、下を横に走ると他のレーンを必ず貫く。
        #
        # 上に出す形での交差 0 は **1 通りだけ**（総長 77.97mm）。下へ出す
        # 案の最短 78.27mm より**むしろ短い**ので、迂回に見えるこの形が
        # 実は最短だった。
        #
        # ⚠️ **GND の引き出しの先端より内側を通す。**12 番（GND）は
        # パッドから列の内側へ 1.2mm 伸びており（x=-2.75・y=-9.15 → -7.95）、
        # 通路がその横腹を貫いていた（交差 1・短絡 1）。
        # **通路は列のすぐ上まで下げる**（2026-08-14）。
        #
        # 以前は 12 番（GND）の引き出しが列の**内側**へ 1.2mm 伸びていて、
        # その先端（y=-7.95）を越える高さまで上がる必要があった。
        # **利用者が引き出しを列の外側（下）へ向けたので、この制約は消えた。**
        # パッドの端（0.65mm）だけ越えれば横へ抜けられ、そのぶん
        # 降り直しが縮む。
        # ⚠️ **`i` ではなく `slot` で数える**（2026-08-15・利用者
        # 「この微妙に高さ違うのを直してほしい」）。`i` は「この列の何本目か」
        # なので、**本数が違う列では同じ役割の線が違う高さになる。**
        # 右列は GND をレーンに載せない（2 本）ので、左列（3 本）と
        # 比べて通路が 1 ピッチぶん浅くなり、肩の高さが左右で揃わなかった。
        #
        # `slot` は上の `lane` / `drop` が既に使っている「枠の番号」で、
        # 本数が足りない側は真ん中の枠を空ける（774 行）。**同じ枠なら
        # 左右で同じ高さ**になる。
        #
        # 交差は増えない（2026-08-15 に実測。右列を 1 ピッチ上げた状態で
        # 全 11 ネットの線分を総当たりで交差判定して **0 件**）。
        #
        # ⚠️ **V3V3 だけは鏡像にならない。これで良い**（2026-08-15・
        # 利用者「やっぱり V3V3 はこのままでいいです」）。
        # 揃うのは 4 組（SPARE↔SPARE2 / ROW_A↔SPI_SCK / ROW_B↔CS /
        # ROW_C↔SPI_MOSI がいずれも同じ y）。V3V3 は 107.80 ではなく
        # **108.20** に残る。
        #
        # 理由: `slot` の詰め方（下の 827 行）が「1 本目を最外・最後を
        # 最内に固定して真ん中を空ける」なので、外周が 2 本しかない右列は
        # slot 0 と slot 2 を使い、**空くのは真ん中**。一方 MCU パッドの
        # y で見た鏡像は ROW_E(87.87)↔GND(87.87) なので、**空くべきなのは
        # 最外の枠**——ここが食い違う。直すなら `slot` を y の順位から
        # 出すことになるが、**利用者の判断で現状維持**。
        over = row_y - pcbnew.FromMM(0.65 + TRACK_W / 2 + clr) \
            - slot * pcbnew.FromMM(pitch)
        # **折れは 3 回だけ。上げてから下げる往復を作らない**
        # （2026-08-14・利用者「まだクネクネ迂回してる。やめてほしい」）。
        #
        # 直前まで「上へ → 左へ → **下へ** → 左へ → 上へ」と 5 回折れて
        # いた。中ほどの上下は **12 番 GND の引き出しが列の内側へ
        # 伸びていた頃の名残**で、利用者がその引き出しを列の外側（下）へ
        # 向けた時点で**不要になっていた**。残したまま「意図がある」と
        # 言えなくなっていたのはこちらの見落とし。
        #
        # いまは「上へ → 左へ（外周レーンまで一気に） → 上へ → 右へ」の
        # **3 折れ**。総長も 83.37 → **71.07mm** に縮む（総当たりで確認）。
        pts = [pcbnew.VECTOR2I(ffc.GetPosition().x, over),
               pcbnew.VECTOR2I(lane_x, over),
               pcbnew.VECTOR2I(lane_x, mcu.GetPosition().y),
               mcu.GetPosition()]
        n += _polyline(board, [ffc.GetPosition()] + pts,
                       pcbnew.B_Cu, mcu.GetNet())
    print(f"      列の外へ {'/'.join(outer)} を {n} 区間")
    _prewire_inner_rows(
        board, row_y, clr, pitch, side=side,
        pad_names=INNER_LANE_PADS if side < 0 else RIGHT_INNER_LANE_PADS,
        vertical_pad=VERTICAL_PAD if side < 0 else RIGHT_VERTICAL_PAD)


# 列の**内側**（XIAO のパッド列と FFC のあいだ）を通す 2 本。
# 利用者の指定（2026-08-14）:
#   D6 … 垂直に下ろして、直角に曲げて FFC へ
#   残り … 外側レーンの最内と同じ長さだけ**逆向き（右）**へ水平に
#          伸ばしてから垂直に下ろし、直角に曲げて FFC へ
# 列の**内側**を通る 3 本。**先頭が「垂直に下ろす」もの。**
#
# D6 が垂直（FFC の真ん中＝9 番）、そこから外へ D5・D4。
# ⚠️ **ここも ROW 名で持たない**（上の OUTER_LANE_PADS と同じ理由）。
#
# **順序は「XIAO で奥のものほど、FFC では外側」。**D4(y 95.49) が
# FFC 7(x 149.75)、D5(98.03) が 8(149.25)、D6(100.57) が 9(148.75) と
# **両端が逆順**なので、奥のものほど降りる x を右に・帯を深く取る。
# 逆に並べると D4 と D5 が丸ごと重なる（2026-08-14 に実測・交差 2 件）。
INNER_LANE_PADS = ("D6", "D5", "D4")
VERTICAL_PAD = "D6"            # **唯一、真下へ下ろす 1 本**

# ---- 右列（2026-08-14・利用者「D1〜D6 を完璧に真似る形で、左右対称に」）
#
# XIAO は x=150.0 を挟んで左右対称（左列 142.38 / 右列 157.62）なので、
# 左列と同じ規則をそのまま鏡像にできる。板端に近い順に並べる。
#
# ⚠️ **GND はレーンに載せない**（利用者の指定）。ベタで受けるほうが
# 戻りが短い。そのぶん外側が 3 本ではなく 2 本になり、余裕ができる
# （実測: 使える帯 1.58mm に 2 本なら各 0.6mm まで取れる。ただし
# **FFC のパッドから出る区間は 0.5mm ピッチのせいで 0.2mm が上限**
# なので、太らせても両端が律速のまま。利用者の判断で 0.2mm を維持）。
#
# 左列の D6（垂直）に対応する枠は GND だったので、**右列に垂直は無い。**
# **鏡像は「同じ y のパッドどうし」**。D1↔GND / D2↔3V3 / D3↔D10 /
# D4↔D9 / D5↔D8 / **D6↔D7**（＝右列の垂直は D7）。
# FFC は n ↔ 13-n で写る。
#
# ⚠️ **GND はレーンに載せない**（利用者の指定）。ベタで受けるほうが
# 戻りが短い。そのぶん外側が 3 本ではなく 2 本になる。
RIGHT_OUTER_LANE_PADS = ("3V3", "D10")         # 板端 → 内側
# 左列 ("D6","D5","D4") の鏡像＝("D7","D8","D9")。先頭が垂直。
RIGHT_INNER_LANE_PADS = ("D7", "D8", "D9")
RIGHT_VERTICAL_PAD = "D7"


def _prewire_inner_rows(board, row_y, clr, pitch,
                        pad_names=None, vertical_pad=None, side=-1):
    """**内側レーンの 3 本（D6/D5/D4）を列の内側で L 字に引く**
    （2026-08-14・利用者）。

    Freerouting に任せると盤面を斜めに横断していた（実測 ROW0 は
    直線 22.4mm に対し 39.1mm）。外側レーンと同じ理屈で、経路に選択の
    余地が無いものは自分で引く。

    ⚠️ **横枝の帯は外側レーンの帯より「上」に取る**（＝ y が小さい側。
    2026-08-14）。最初 外側レーンと同じ `lo..hi`（FFC と MP のあいだ）を
    使ったら **y=110.6/111.0**、つまり外周組の帯（107.4/107.8/108.2）と
    FFC のパッド（109.15）の**両方より下**に降りた。縦に下りる 2 本が
    横に走る 3 本を必ず突き抜けるので、**不要な交差が 7 件**出た
    （利用者の指摘）。

    内側の 3 本は FFC へ**上から**入るだけなので、外周組の帯より下へ
    行く理由が無い。帯を外周組より上に置けば、縦の 2 本は横の 3 本と
    出会う前に FFC のパッドへ落ちる。

    ⚠️ **`autoroute.PREWIRED_DB` に `ROW[01]` を入れるのが対。**
    入れないと DSN に未配線として残り、Freerouting が二重に引く
    （ROW2/3/4 で実際に起きた）。
    """
    inner = _lane_nets(board, pad_names or INNER_LANE_PADS)
    outer = _lane_nets(board, OUTER_LANE_PADS if side < 0
                       else RIGHT_OUTER_LANE_PADS)
    # **垂直に下ろす 1 本が無い列もある**（右列。GND はベタで受けるので
    # レーンに載せない。2026-08-14・利用者）。その場合は None を渡す。
    vp = vertical_pad if vertical_pad is not None else VERTICAL_PAD
    vertical = _lane_nets(board, (vp,))[0] if vp else None
    pads = {}
    for fp in board.Footprints():
        ref = fp.GetReference()
        if ref not in ("U_MCU", "J_MAIN"):
            continue
        for pad in fp.Pads():
            if pad.GetNetname() in inner:
                pads.setdefault(pad.GetNetname(), {})[ref] = pad

    # **外側レーンの最も内側の 1 本（D3）が、パッドから出る水平の枝**と
    # 同じ長さ。垂直に下ろさない線は、この長さだけ横へ伸ばしてから下ろす。
    # **数字を書かず実物から測る。**
    #
    # ⚠️ **「その行の水平区間」で最大を取ってはいけない**（2026-08-14）。
    # 水平区間は 2 つある:
    #   パッドから出る枝  ← こちらが基準
    #   FFC の近くの帯    ← 別物
    # `max` で拾って長い方を使い、**D2 が BT1_- のパッドの上を
    # 縦断して短絡した。**MCU のパッドに接している方だけを見る。
    #
    # ⚠️ **基準の行を固定の名前で書かない**（2026-08-14）。以前は
    # `"ROW4"` と直書きしていたが、**利用者が D ピンの内外を入れ替えた
    # 時点で ROW4 は内側へ移り、この枝自体が消えた。**基準は
    # 「外側レーンのうち最も内側」——`outer` の末尾。
    mcu_y = {p.GetPosition().y for fp in board.Footprints()
             if fp.GetReference() == "U_MCU" for p in fp.Pads()}
    run = next(abs(t.GetStart().x - t.GetEnd().x) for t in board.GetTracks()
               if t.GetNetname() == outer[-1]
               and t.GetStart().y == t.GetEnd().y
               and t.GetStart().y in mcu_y)

    # ⚠️ **縦に降りる線が、列のパッドの上を通らないこと**（2026-08-14）。
    #
    # 左列ではたまたま `run`（1.465mm）がパッド半幅 0.85 + クリアランス
    # + 線半幅 を超えていたので問題にならなかった。**右列で 1.265mm に
    # なった瞬間、SPI_SCK の縦線が D7 のパッドを貫いて短絡した**
    # （短絡 2・交差 1・マスクブリッジ 1）。
    # **たまたま足りていたものは、条件が変われば足りなくなる。**
    half = max(pcbnew.ToMM(p.GetSize().x) for fp in board.Footprints()
               if fp.GetReference() == "U_MCU" for p in fp.Pads()) / 2
    floor = pcbnew.FromMM(half + clr + TRACK_W / 2)
    run = max(run, floor)

    # **外周組の帯より上**。いちばん上の帯（ROW2 のもの）からさらに
    # 1 ピッチずつ上へ積む。
    #
    # ⚠️ **横に走る区間なら何でも良いわけではない。**`_prewire_rows` は
    # MCU のパッドへ入る短い横枝も引いており（ROW2 なら y=92.95）、
    # 素朴に `min` を取るとそれを掴んで **y=92.55**、つまり MCU の列の
    # ど真ん中に帯を作ってしまう（2026-08-14 に実際に例外で止まった）。
    # **FFC 寄り＝ MCU のパッド列より下にある横区間**だけを見る。
    col_y = max(p.GetPosition().y for fp in board.Footprints()
                if fp.GetReference() == "U_MCU"
                for p in fp.Pads() if p.GetNetname() in outer)
    top = min(t.GetStart().y for t in board.GetTracks()
              if t.GetNetname() in outer
              and t.GetStart().y == t.GetEnd().y
              and t.GetStart().y > col_y)
    # ⚠️ **ここで本数の差を埋め合わせないこと**（2026-08-15）。
    # `over` を `slot` で数えるようにした時点で、**外周組の帯は既に
    # 左右で同じ高さ**になっている（実測: ROW_C と SPI_MOSI がどちらも
    # y=107.40）。ここでさらに `LANES_PER_SIDE - len(outer)` を引くと
    # **内側 3 本だけが 1 ピッチ余計に上がり、右が 105.80 と
    # 左（106.20）を追い越した。**`top` をそのまま使えば揃う。

    n = 0
    k = 0                      # **垂直でない線の通し番号**（下の drop_x 用）
    for i, name in enumerate(inner):
        mcu = pads[name]["U_MCU"]
        ffc = pads[name]["J_MAIN"]
        band = top - (i + 1) * pcbnew.FromMM(pitch)
        # ⚠️ **y は下が正。**「帯が MCU パッドより下」は band > mcu.y。
        # 逆に書いて、正しい帯なのに例外で止めた（2026-08-14）。
        if band <= mcu.GetPosition().y:
            raise RuntimeError(
                f"{name}: 横枝の帯（y={pcbnew.ToMM(band):.2f}）が"
                f" MCU パッド（y={pcbnew.ToMM(mcu.GetPosition().y):.2f}）"
                "より上。**黙って詰めないこと**")
        if name == vertical:
            # 垂直に下ろす → 帯で右へ → FFC の真上で下ろす
            drop_x = mcu.GetPosition().x
        else:
            # **外側レーンの最内と同じ長さだけ右へ伸ばしてから下ろす**
            # （利用者の指定。当時の言葉では「D5 と同じ長さ」）。
            #
            # ⚠️ **ここで勝手に長さを変えないこと**（2026-08-14）。
            # 一度 BT1_- に当たると見て 8.42mm へ伸ばしたが、
            # **「同じ長さ」という指定そのものを書き換えていた。**
            # 当たるなら当たると報告して判断を仰ぐ。黙って動かさない。
            # ⚠️ **2 本以上あるときは、降りる x もずらす**（2026-08-14）。
            # 以前は内側が 1 本しか無く、`run` を足すだけで足りていた。
            # **利用者が D ピンの内外を入れ替えて内側が 2 本になった**
            # 時点で、両方が同じ x=143.84 に降りて**丸ごと重なった**
            # （tracks_crossing 2 件）。帯と同じピッチで外へ 1 本ずつ。
            # ⚠️ **`i` ではなく「垂直でない何本目か」で数える**
            # （2026-08-14）。以前は `(i - 1)` と書いており、**垂直の
            # 1 本が必ず i=0 を占める**ことに暗黙で頼っていた。右列には
            # 垂直が無いので 1 本目が `run - pitch` になり、**縦線が
            # D7 のパッドを貫いて短絡した。**
            drop_x = mcu.GetPosition().x - side * (
                run + k * pcbnew.FromMM(pitch))
            k += 1
        pts = [pcbnew.VECTOR2I(drop_x, mcu.GetPosition().y),
               pcbnew.VECTOR2I(drop_x, band),
               pcbnew.VECTOR2I(ffc.GetPosition().x, band),
               ffc.GetPosition()]
        n += _polyline(board, [mcu.GetPosition()] + pts,
                       pcbnew.B_Cu, mcu.GetNet())
    print(f"      列の内へ {'/'.join(inner)} を {n} 区間")


def _antenna_keepout(board):
    """**アンテナの真下の銅を、両面とも抜く**（open-gaps #23）。

    アンテナを塞いでいたものは 3 つあった。上（本体基板の地板 4.09mm）と
    横（FFC コネクタ 0.5mm）は、XIAO を奥端へ寄せたことで外れた
    （#28 と同じ変更）。**残るのが、この子基板自身の地板 1.6mm。**

    一度この案は「アンテナの影 3mm のうち 2mm が FFC コネクタの下なので、
    空くのは 1mm 幅だけ」として捨てられていた。**XIAO が奥へ動いた今、
    コネクタはアンテナから 7mm 以上離れており、影の下には何も無い。**

    位置は interface.antenna_y_keepout（実体 + 逃げ）から取る。
    """
    from interface import antenna_x_keepout, antenna_y_keepout

    # **アンテナの実体をそのまま使う。切り詰めも水増しもしない**
    # （2026-08-14・利用者の指摘「ぱっと見ズレている」）。
    #
    # 直前まで 2 つの細工が入っていて、**アンテナの 57% しか
    # 覆っていなかった**（x は 100%・y が 57%。帯の中心が
    # -3.21 で、アンテナの中心 -1.95 から 1.26mm ずれていた）:
    #
    #   `hi = min(hi, pad_front - 0.3)`
    #       XIAO のパッドに掛からないよう奥端を切り詰めていた。
    #       **だが y だけを見て x を見ていない。**利用者の指摘
    #       「x 座標も両方かからないと領域として被らないのでは」の
    #       とおりで、実測すると**この帯の x に掛かるパッドは 1 つも
    #       無い**（J_MAIN と電源部は x が重なるが y が遠い）。
    #       **何も守っていない切り詰めだった。**
    #   `margin = 1.0`
    #       手前側を 1mm 広げていた。アンテナの外を広げるだけで、
    #       禁止域が全幅だった頃の名残。
    lo, hi = antenna_y_keepout(DB_D / 2)      # 板の中心を原点とした座標
    x_lo, x_hi = antenna_x_keepout()
    # **パッドと本当に重なるなら止める**（黙って縮めない）。
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            px = pcbnew.ToMM(pad.GetPosition().x) - ORIGIN[0]
            py = ORIGIN[1] - pcbnew.ToMM(pad.GetPosition().y)
            hx = pcbnew.ToMM(pad.GetSize().x) / 2
            hy = pcbnew.ToMM(pad.GetSize().y) / 2
            if (not (px + hx < x_lo or px - hx > x_hi)
                    and not (py + hy < lo or py - hy > hi)):
                raise RuntimeError(
                    f"アンテナの禁止域が {fp.GetReference()}.{pad.GetNumber()} と"
                    f"重なる（({px:.2f},{py:.2f})）。**黙って縮めないこと**——"
                    "部品を動かすか、アンテナの位置を見直す")
    zone = pcbnew.ZONE(board)
    # **ベタ・配線・ビアを全部禁止する**（2026-08-15・利用者の指示）。
    #
    # **以前は配線とビアを許可していた。**その理由は「FFC から XIAO へ行く
    # 12 本が必ずこの帯を横切り、禁止すると 14 件の違反になる」だったが、
    # **これは帯が板の全幅だった頃の記録。**帯を x 4.5mm に絞った
    # 2026-08-14（#41）以降は当てはまらない。
    #
    # 実測（2026-08-15・`pcb/hhkb_split_daughterboard.kicad_pcb`）:
    # **いまの帯に掛かる配線・ビア・パッドは 0 件。**だから配線とビアを
    # 禁止しても、追加の違反は出ない。**許可を残す理由がもう無い。**
    #
    # パッドだけは許可のまま。禁止域とパッドが重なったら、この関数の
    # 手前にある検査が `RuntimeError` で止める（黙って縮めないため）。
    zone.SetIsRuleArea(True)
    zone.SetDoNotAllowZoneFills(True)
    zone.SetDoNotAllowTracks(True)
    zone.SetDoNotAllowVias(True)
    zone.SetDoNotAllowPads(False)
    layers = pcbnew.LSET()
    for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
        layers.addLayer(lay)
    zone.SetLayerSet(layers)
    # **x はアンテナの帯だけ。XIAO の全幅ではない**（2026-08-14・#41）。
    #
    # 利用者の指摘「こんなに広い必要あるでしょうか。アンテナの位置を
    # 踏まえて考えて」。実測すると **18.30mm 幅で、アンテナは 3.5mm**
    # ——4.1 倍だった。`XIAO_OUTLINE_W`（モジュールの外形）を使っており、
    # **アンテナの寸法と取り違えていた。**
    #
    # 抜きすぎた 41mm²/面 はただの地板の損失で、**2.4GHz の基準電位を
    # いちばん要る基板で削っていた**（この節の目的と逆）。
    #
    # 正しい範囲は `interface.antenna_x_keepout()`——アンテナの実寸に
    # 逃げ `ANTENNA_CLEAR_KEEPOUT` を足したもの（2026-08-15 に広げた）。
    #
    # `antenna_x_band()`（_route が使う、狭い対称の帯）とは**別の関数**。
    # 禁止域は「銅を抜く範囲」で、あるだけ広いほうが良い。帯は「レーンを
    # 通さない範囲」で、広げるほど引ける線が減る。**用途が逆なので
    # 同じ値を使わない。**
    #
    # 上の `x_lo, x_hi` を再代入せずそのまま使う（同じ関数から取った値）。
    pts = pcbnew.VECTOR_VECTOR2I()
    for dx, dy in ((x_lo, lo), (x_hi, lo), (x_hi, hi), (x_lo, hi)):
        pts.append(to_kicad(dx, dy))
    zone.AddPolygon(pts)
    board.Add(zone)


def _add_power_netclasses(board):
    """電源のネットクラスを作る。**主基板と同じ設定を使う。**

    2026-08-14 まで子基板だけ既定（0.2mm）のままだった（利用者の指摘
    「MAIN PCB に施していて DB に施していないものがある」）。
    **電源が子基板へ来た以上、ここを細いまま残す理由が無い。**

    幅の出所は `pcb_rules.POWER_CLASSES` の 1 か所だけ
    （V3V3 は FFC のパッド列を抜けるので 0.2mm、GND 系は 0.6mm）。
    """
    from pcb_rules import POWER_CLASSES, TRACK_W, VIA_D, VIA_DRILL
    ns = board.GetDesignSettings().m_NetSettings
    for name, (width, nets) in POWER_CLASSES.items():
        cls = pcbnew.NETCLASS(name)
        cls.SetTrackWidth(pcbnew.FromMM(width))
        cls.SetClearance(pcbnew.FromMM(TRACK_W))
        cls.SetViaDiameter(pcbnew.FromMM(VIA_D))
        cls.SetViaDrill(pcbnew.FromMM(VIA_DRILL))
        ns.SetNetclass(name, cls)
        for n in nets:
            ns.SetNetclassPatternAssignment(n, name)
    # **忘れると効かない。**「設定しただけで効いていない」の典型。
    ns.RecomputeEffectiveNetclasses()



def main():
    path, n_net = build()
    print(f"子基板 {DB_W} x {DB_D}mm / ネット {n_net} 本")
    print(f"      {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
