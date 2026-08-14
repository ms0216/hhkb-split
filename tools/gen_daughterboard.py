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

# 外形はケース側の造作と一致させる（tools/gen_case.py の DB_W / DB_D）。
DB_W, DB_D = 21.0, 32.0
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
POWER_PLACE = {                 # 参照名 → (x, y)
    "R_HI":     (-4.60, 14.40),   # 分圧の上（VBATT_SW → SENSE）。D0 の隣
    "R_LO":     (-4.60, 11.60),   # 分圧の下（SENSE → GND）
    "D_PWR":    ( 4.00, 14.20),   # VBATT_SW → V3V3。3V3 パッド側
    "SW_PWR":   (-3.10,  8.70),   # 電池から来る線を受ける
    "BT1":      ( 4.60,  7.00),   # 電池の −（GND）
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
    c.SetPosition(to_kicad(5.0, 11.0))      # 0805（2.05mm）→ 3.98..6.02
    c.SetReference("C_DB")
    c.SetValue("0.1uF")
    board.Add(c)
    c.Flip(c.GetPosition(), False)

    # **バルク。2026-08-14 に主基板から移した**（open-gaps #41）。
    # 守る相手は XIAO が µs 級の無線送信で引く電流変動
    # （electrical-design.md 1-5）。主基板に置くと FFC 100mm の
    # インダクタンスの外側から供給することになり、間に合わない。
    b_ = _load(KICAD_FP / f"{BULK_FP[0]}.pretty", BULK_FP[1])
    b_.SetPosition(to_kicad(0, 11.0))
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
        lib, name = ELEC_FP[kind]
        # 電池ボックスと電源スイッチは「基板に載らない部品」で、
        # 基板側はランドで受ける。**端子の数だけランドを置く**
        # （主基板の gen_pcb と同じ規則。BT1 は GND だけ・
        #  SW_PWR は VBATT_SW だけなので、どちらも 1 個）。
        wire = kind in WIRE_PAD_KINDS
        for k, pin in enumerate(pins if wire else [None]):
            fp = _load(KICAD_FP / f"{lib}.pretty", name)
            fp.SetPosition(to_kicad(x + k * 4.0, y))
            fp.SetReference(f"{ref}_{pin}" if wire else ref)
            fp.SetValue(kind)
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
    # レーンは**経路に選択の余地が無い**（下の docstring の順序が唯一解）。
    # 主基板の行バスと同じ理屈で、ここは自分で引くほうが良い。
    # 一方、電源 5 点の配線は**選択の余地があり、手で書くと破綻した**
    # （DRC 41 件）。そこは Freerouting に渡す。
    #
    # ここで引いた線は DSN に `(type protect)` で乗り、自動配線器は
    # これを避けて電源だけを解く。
    _route(board)
    _antenna_keepout(board)
    _add_power_netclasses(board)

    UNROUTED.mkdir(parents=True, exist_ok=True)
    path = UNROUTED / "hhkb_split_daughterboard.kicad_pcb"
    board.Save(str(path))
    return path, len(nets)


def _antenna_keepout(board):
    """**アンテナの真下の銅を、両面とも抜く**（open-gaps #23）。

    アンテナを塞いでいたものは 3 つあった。上（本体基板の地板 4.09mm）と
    横（FFC コネクタ 0.5mm）は、XIAO を奥端へ寄せたことで外れた
    （#28 と同じ変更）。**残るのが、この子基板自身の地板 1.6mm。**

    一度この案は「アンテナの影 3mm のうち 2mm が FFC コネクタの下なので、
    空くのは 1mm 幅だけ」として捨てられていた。**XIAO が奥へ動いた今、
    コネクタはアンテナから 7mm 以上離れており、影の下には何も無い。**

    位置は interface.antenna_y_span（ケース側と同じ式）から取る。
    """
    from interface import antenna_x_band, antenna_y_span

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
    lo, hi = antenna_y_span(DB_D / 2)         # 板の中心を原点とした座標
    x_lo, x_hi = antenna_x_band()
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
    # **抜くのはベタだけ。配線は通す。**
    #
    # FFC コネクタ（板の手前）から XIAO のパッドへ行く 12 本は、
    # **必ずこの帯を横切る**（アンテナが XIAO の先端にあるため）。
    # 配線まで禁止すると 14 件の違反になり、迂回路も無い（帯が板の全幅）。
    #
    # アンテナに効くのは**面積の大きい地板**で、0.25mm の線 12 本とは
    # 桁が違う。**「完全な禁止域」ではない。**そう書かないこと。
    zone.SetIsRuleArea(True)
    zone.SetDoNotAllowZoneFills(True)
    # **既定は「全部禁止」。**明示的に許可しないと配線まで止まる（14 件出た）。
    zone.SetDoNotAllowTracks(False)
    zone.SetDoNotAllowVias(False)
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
    # 正しい範囲は `interface.antenna_x_band()`——アンテナの実寸
    # 3.5mm に逃げ 0.5mm を両側。**同じ関数を _route も使っている**
    # （レーンがアンテナの下を通らないようにするため）。出所を 1 つに揃える。
    from interface import antenna_x_band
    x_lo, x_hi = antenna_x_band()
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
    # LANE_STEP 0.65: 片側 5 本（ROW4 を D9 へ移して 6 → 5 本になった）を
    # 6.4 から 0.65 刻みで置くと最内が 3.8mm。アンテナの実外形
    # （interface.ANTENNA_X±W/2 = 1.9±1.75）の外に出る。0.7 のままだと
    # 最内 3.6mm が外形に 0.05mm 掛かる。0.65 でもビアと隣レーンの配線は
    # 0.225mm（規則 0.2）で足りる。
    LANE0, LANE_STEP = 6.4, 0.65  # 6.5 は D6 のパッドと 0.17mm（規則 0.2）で落ちた
    # **アンテナの真下を通さない**（open-gaps #23）。
    #
    # 縦のレーンは表面を走り、アンテナの y 帯を必ず横切る。だが**横切る
    # 場所（x）は選べる。**アンテナは 3.5mm 角の小さな部品で、XIAO の
    # 全幅 18.3mm のうち 2 割弱しか占めていない。**その帯だけ空ければよい。**
    #
    # 一度「迂回路が無い」と書いたが、**アンテナが XIAO の全幅にあるという
    # 誤った前提**で考えていた。利用者の実測（3.5x1.5mm）で覆った。
    from interface import antenna_x_band
    BAND_LO, BAND_HI = antenna_x_band()
    # ビアの間隔。**x を詰めるぶん、y を離す。**同じ量で詰めると
    # ビアの対角が 0.778mm になり、φ0.6 どうしが 0.178mm しか離れない（規則 0.2）。
    ROW_STEP = 0.9
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
        # **レーンの x を先に決める。**外から内へ 0.7mm 刻み。
        #
        # 内側ほどアンテナに近づく。**帯に入る候補を飛ばして外側だけ使う**
        # ことも試したが、飛んだ 1 本が他のレーンと交差して DRC が落ちた。
        # 間隔を詰める方法も駄目（ビア φ0.6 と隣の配線が 0.11mm。必要 0.6mm）。
        #
        # **いまは LANE0 を 6.0 → 6.5 へ動かして全体を外へ寄せてある。**
        # それでも、この側の**いちばん内側の 1 本はアンテナの下に残る**
        # （open-gaps #23。アンテナの正確な位置が実測できたら詰める）。
        lanes = [sign * (LANE0 - k * LANE_STEP) for k in range(len(targets))]
        under = [x for x in lanes if BAND_LO <= x <= BAND_HI]
        if under:
            print(f"      ⚠ アンテナの帯に入るレーン {len(under)} 本: "
                  f"{[round(x, 2) for x in under]}")
        for i, (ty, fpad, xpad) in enumerate(targets):
            # **絶対座標にする。**相対値のまま fx/ty（絶対）と混ぜていて、
            # 145.9mm の配線ができていた。DRC の「配線の長さ」が異常値だった
            # ことで気づいた。
            lane = ORIGIN[0] + lanes[i]
            fx = pcbnew.ToMM(fpad.GetPosition().x)
            fy = pcbnew.ToMM(fpad.GetPosition().y)
            tx = pcbnew.ToMM(xpad.GetPosition().x)
            net = fpad.GetNet()
            row = fy - (1.4 + i * ROW_STEP)   # 外側へ行くものほど手前で曲げる

            # 1. 裏面でファンアウト（縦 → 横）。**順序のおかげで交差しない。**
            #    先に曲がるのは外側のレーンへ行くもので、その横枝は
            #    まだ上へ伸びている他の縦線より外側にしか来ない。
            for a, b in (((fx, fy), (fx, row)), ((fx, row), (lane, row))):
                if a != b:
                    _track(board, mm(*a), mm(*b), pcbnew.B_Cu, net)

            # 2. 縦に走る（レーンごとに x が違うので交差しない）。
            #
            # **アンテナの帯に入るレーンだけ、裏面のまま走らせる。**
            # 表面（F.Cu）はアンテナから 1.6mm、裏面（B.Cu）は 3.2mm。
            # **金属を消せないなら、せめて倍の距離へ離す。**
            # 板厚 1.6mm ぶん遠ざかるだけだが、**あとから直せない場所**なので
            # 無料でできることはやっておく（open-gaps #23）。
            if BAND_LO <= lanes[i] <= BAND_HI:
                _track(board, mm(lane, row), mm(lane, ty), pcbnew.B_Cu, net)
            else:
                _via(board, mm(lane, row), net)
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

    # パスコンとバルク。**GND 側はベタで受けるので配線しない。**
    # 両方を配線すると、GND の枝が基板を横断して他のネットと交差した。
    for fp in (c, board.FindFootprintByReference("C_BULK")):
        for pad in fp.Pads():
            n = pad.GetNetname()
            if n == "GND" or n not in xiao:
                continue
            near = min(xiao[n],
                       key=lambda p: (p.GetPosition() - pad.GetPosition()).EuclideanNorm())
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
