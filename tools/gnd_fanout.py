"""GND のビア。パッドを地板へ落とすもの（ファンアウト）と、
地板どうしを繋ぎ直すもの（スティッチング）の 2 種類を立てる。

**GND は Freerouting に配線させない。両面のベタで受ける。**

2 層になってからの事情（2026-08-12・指摘 3/4/5）
--------------------------------------------------
4 層のときは GND 専用層（In1.Cu）が 1 枚あり、自動配線器に対して
「ここに信号を通すな」と全面予約できた。**2 層では信号層と GND 層が
同じ 2 枚を兼ねるので予約できない。**したがって GND ベタは最初から
配線を避けた歯抜けになり、長い配線はベタを分断する。

分断されたベタは、離れた場所どうしで電位が揃わない。だから 2 種類立てる。

  ファンアウト   GND パッド → すぐ脇のビア → 反対面のベタ
                 （パッドが地板に届くようにする）
  スティッチング 格子状に一定間隔で打つビア
                 （表と裏のベタを縫い合わせ、分断を迂回させる）

なぜスティッチングが要るか（指摘 5 の説明そのもの）
----------------------------------------------------
長い配線は、その配線を境にベタを 2 つに割る。割られた向こう側へ行くには
配線の端まで大回りするしかない。**反対面のベタを経由すれば最短距離で
横断できる**ので、配線をまたぐ位置にビアを打っておく。

なぜ数が要るか（指摘 4 の説明そのもの）
----------------------------------------
理屈の上ではビアが 1 個でも 2 面の電位は繋がる。しかし電流が流れると
その 1 個に全部が集中し、ビアの抵抗とインダクタンスが電位差として現れる。
**多いほど電位が揃う。**空いているところには打てるだけ打つ。

対象は電子部品（`ELEC`）の GND パッド。**接頭辞での走査はしない**
（`D`/`SW` で拾うと電源部を巻き込む。この案件で 4 回起きた）。
"""

import pcbnew

from circuit import ELEC_REF as ELEC

STUB_WIDTH_MM = 0.2
VIA_DIAMETER_MM = 0.6
VIA_DRILL_MM = 0.3

# 銅どうしのすき間に、規則の上乗せとして足す余裕（mm）。
#
# **これだけが判断で置いた数字。**残りは基板の設計規則から導く。
# 0.05mm は KiCad の丸め（内部単位は nm だが座標は 0.001mm 刻みで
# 書き出される）と、こちらの当たり判定が矩形近似であることに対する
# 保険。**規則ちょうどに置くと、丸め 1 つで DRC が赤になる。**
SAFETY_MM = 0.05


def _clearance_mm(board):
    """**この基板の設計規則が要求するクリアランス（mm）。**

    ⚠️ **数値を書かない。**以前は 0.2 を 4 か所に直書きしていて、
    設計規則を変えてもここが追随しなかった。規則より緩ければ DRC が
    捕まえるが、**厳しすぎても DRC は緑のまま**なので誰も気づけない。
    """
    d = board.GetDesignSettings()
    return max(pcbnew.ToMM(d.m_MinClearance),
               pcbnew.ToMM(d.m_NetSettings.GetDefaultNetclass().GetClearance()))


def _via_keepout_mm(board):
    """ビアの**中心**から、相手の銅の縁までに要る距離（mm）。

    ビアの半径 + クリアランス + 余裕。**半径を二重に数えない**
    （以前やって 0.3mm 過剰に厳しくなり、格子点の 8 割を捨てていた）。
    """
    return VIA_DIAMETER_MM / 2 + _clearance_mm(board) + SAFETY_MM


def _pad_escape_mm(board):
    """パッドの縁から、逃がすビアの中心までの距離（mm）。"""
    return _via_keepout_mm(board)


def _hole_keepout_mm(board):
    """ビアの**中心**から、相手の**穴の縁**までに要る距離（mm）。

    ⚠️ **銅の規則とは別物。**銅どうしのクリアランス（0.2mm）より
    `hole_to_hole`（0.5mm）のほうが厳しいので、銅で見ていると通り抜ける。

    **これが無い間、穴は障害物に入っていなかった**（2026-08-14）。
    `_obstacles` はパッドの**外接箱＝銅**しか見ておらず、
    NPTH は銅が無いか小さいので**穴の広がりを表せない。**
    結果、右基板で GND ビアが SW5 / SW18 の穴に **0.479 / 0.488mm**
    まで寄っていた（設計規則は 0.4995mm）。
    **`hole_to_hole` は KiCad の既定が `warning` なので、
    エラーだけ見ていた間は永久に表に出てこなかった。**

    要るのは ビアの穴の半径 + 穴どうしの最小距離 + 余裕。
    **数値は書かない**（`_clearance_mm` と同じ理由。設計規則が動いたら
    ここも動く）。
    """
    d = board.GetDesignSettings()
    return VIA_DRILL_MM / 2 + pcbnew.ToMM(d.m_HoleToHoleMin) + SAFETY_MM

# スティッチングビアの格子間隔（mm）。
#
# **2.4GHz を基準にする。**分割キーボードは左右で 2.4GHz の無線を動かす。
# 波長は空気中で 125mm、FR-4 の中では実効誘電率のぶん短くなって約 65mm。
# 地板の縫い目は λ/20 より細かくしておけば、その帯域で 1 枚の面として
# ふるまう。65 / 20 ≒ 3.25mm ……は打ちすぎで基板が穴だらけになるので、
# **λ/10 ≒ 6.5mm** を採る。キーピッチ 19.05mm の 1/3 に近く、
# ソケットの隙間にも収まる。
#
# **この値は「効いたか」を測って決めるものではない。**測るのは
# 「打った結果ベタが 1 つの島になったか」（test_pcb が見る）。
STITCH_PITCH_MM = 6.5




def _candidates(board, fp, pad):
    """そのパッドからビアを逃がす候補を、良い順に返す。

    第 1 候補は**パッドの長軸**。最初は縦横どちらか広い方に単純に逃がそうと
    して失敗した（FFC の横並びパッドで隣の CS パッドに刺さり、受動部品
    では隣の部品のパッドに接近した）。パッド自身の長軸に沿って、
    フットプリント中心から遠ざかる側へ逃がすのが正解だった。

    **第 2 候補以降を持つのは、当たったときに諦めないため**（2026-08-12）。
    パスコンを IC の隣へ寄せた結果、U1 のパッド 13 のビアが C_U1 の
    V3V3 パッドに重なった。第 1 候補だけだと、そこで短絡する。
    """
    c, q, s = fp.GetPosition(), pad.GetPosition(), pad.GetSize()
    x, y = pcbnew.ToMM(q.x), pcbnew.ToMM(q.y)
    esc = _pad_escape_mm(board)
    hx = pcbnew.ToMM(s.x) / 2 + esc
    hy = pcbnew.ToMM(s.y) / 2 + esc
    long_y = s.y >= s.x
    sign_y = 1.0 if (q.y - c.y) >= 0 else -1.0
    sign_x = 1.0 if (q.x - c.x) >= 0 else -1.0

    along = [(x, y + sign_y * hy), (x, y - sign_y * hy)]
    across = [(x + sign_x * hx, y), (x - sign_x * hx, y)]
    out = (along + across) if long_y else (across + along)

    # **それでも置けないときのために、まわりを近い順に探す。**
    # 素直な 4 方向だけだと、0.65mm ピッチの TSSOP や、隣にパスコンを
    # 寄せたあとの IC で置き場所が無くなる（2026-08-12。U1 のパッド 13
    # と J_DB のパッド 2 が該当した）。
    #
    # **順序は決定的にする。**距離が近い順、同じ距離なら角度の小さい順。
    # 集合の反復順や乱数に頼ると生成のたびに位置が変わり、
    # 配線の前後で食い違う（この関数は両方から呼ばれる）。
    import math
    base = max(hx, hy)
    for k in range(1, 7):                    # 0.25mm 刻みで 1.5mm 外まで
        rad = base + 0.25 * k
        for i in range(16):                  # 22.5 度刻み
            a = math.radians(22.5 * i)
            out.append((x + rad * math.cos(a), y + rad * math.sin(a)))
    return out


def _blocked(p, boxes, r):
    """ビアの中心 p が、どれかの箱に近すぎるか。

    **箱どうしの重なりで見てはいけない。**ビアは丸いので、正方形の箱で
    近似すると角のぶん厳しくなりすぎる。実際 TSSOP-16 のように 0.65mm
    ピッチで並んだパッドでは、**パッドの列の外へ逃がしても隣のパッドの
    箱に当たったことになり、ビアが 1 つも置けなかった**（2026-08-12）。

    正しくは「相手の矩形を、ビアの半径＋クリアランスぶん膨らませた領域に、
    ビアの**中心**が入るか」。これが円と矩形の距離判定と同じになる。
    """
    for b in boxes:
        big = pcbnew.BOX2I(b.GetOrigin(), b.GetSize())
        big.Inflate(r)
        if big.Contains(p):
            return True
    return False


def _path_blocked(a, b, boxes, clearance_mm, step_mm=0.05):
    """a から b への直線（スタブ配線）が、どれかの箱に触れるか。

    線と矩形の厳密な判定はせず、線上を細かく標本化して点で見る。
    刻みが線幅の半分より細かければ取りこぼさない。
    """
    import math
    half = pcbnew.FromMM(STUB_WIDTH_MM / 2 + clearance_mm)  # 線の半幅+規則
    ax, ay = pcbnew.ToMM(a.x), pcbnew.ToMM(a.y)
    bx, by = pcbnew.ToMM(b.x), pcbnew.ToMM(b.y)
    n = max(2, int(math.dist((ax, ay), (bx, by)) / step_mm))
    for i in range(n + 1):
        t = i / n
        p = pcbnew.VECTOR2I_MM(ax + (bx - ax) * t, ay + (by - ay) * t)
        if _blocked(p, boxes, half):
            return True
    return False


def _pad_boxes(board, skip=None):
    """パッドの当たり判定用の箱。`skip`（参照名, パッド番号）だけ外す。

    ⚠️ **`pad is skip` で自分を外そうとしてはいけない。**pcbnew は SWIG の
    ラッパーで、`Pads()` を呼ぶたびに別のプロキシ物体が返る。同じパッドでも
    `is` は成り立たず、**自分自身を障害物と見なして候補が全滅する**
    （2026-08-12 に実際にやった。ファンアウトが 0 個になった）。
    """
    out = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            if skip is not None and (ref, pad.GetNumber()) == skip:
                continue
            out.append(pad.GetBoundingBox())
    # ⚠️ **ルール領域（アンテナの禁止域）もここに入れる**（2026-08-15）。
    #
    # 名前は `_pad_boxes` だがパッドだけでは足りない。**`spots()` は
    # `_obstacles()` を通らない**ので、禁止域を入れ忘れると、パッド直近の
    # ファンアウトのビアだけが禁止域に入る。実際 1 個入って DRC が
    # items_not_allowed を出した（中心 y=1.95・境界 1.80・外径ぶん食い込み）。
    #
    # `_obstacles` 側だけ直して「直した」と思ったが、**ビアを置く経路が
    # 2 つある**ことを見ていなかった（`spots` と `stitch`）。
    # **置き場所を決める経路を全部数えてから直す。**
    #
    # 箱はビアの外径ぶん膨らませる。判定側（`_blocked`）が見るのは
    # **ビアの中心**なので、そのままだと中心が外なら通り、銅は中に入る。
    via_r = pcbnew.FromMM(_via_keepout_mm(board))
    for z in board.Zones():
        if z.GetIsRuleArea():
            bb = z.GetBoundingBox()
            bb.Inflate(via_r)
            out.append(bb)
    return out


def spots(board):
    """(パッド, ビアを置く mm 座標) の一覧。

    **置けない候補は避ける。**当たり判定を持たずに機械的に逃がしていた
    ころは、部品が近づくと隣のパッドの上にビアを置いて短絡していた
    （2026-08-12 に実際に起きた。DRC が短絡・クリアランス・穴・
    ハンダマスクの 4 種類で鳴った）。

    どの候補も置けなければ**その GND パッドは飛ばす**。黙って消えるが、
    `test_every_ground_pad_reaches_the_plane` が「ビアが無い」と落とすので
    気づける。**握り潰しにはならない。**

    ⚠️ **判定材料に配線を入れてはいけない。**この関数は配線の前
    （gen_pcb。Freerouting へ「避けるべき障害物」として渡すため）と
    配線の後（autoroute。SES 取り込みで消えるので立て直すため）の
    両方から呼ばれる。**両方で同じ位置を返さないと、Freerouting が
    避けた場所と違うところにビアが立ち、その上を配線が通る。**
    だからパッドだけを見る（パッドは配線で動かない）。
    """
    r = pcbnew.FromMM(_via_keepout_mm(board))
    out = []
    taken = []
    # ⚠️ **参照名で並べ替えてから回す。**
    #
    # KiCad は保存のたびにフットプリントの書き出し順を変える
    # （pcb-routing-handover.md に記録がある）。順序が変わると
    # `taken`（先に置いたビア）の積み上がり方が変わり、**配線の前と後で
    # ビアの位置が食い違う。**Freerouting は配線前の位置を避けて配線して
    # いるので、後から違う場所に立てると、その上を配線が通る
    # （2026-08-12 に右基板で SPI_SCK と GND ビアが 0.19mm で接触した）。
    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        if not ELEC.fullmatch(fp.GetReference()):
            continue
        for pad in fp.Pads():
            if pad.GetNetname() != "GND":
                continue
            blockers = _pad_boxes(
                board, skip=(fp.GetReference(), pad.GetNumber())) + taken
            q = pad.GetPosition()
            for vx, vy in _candidates(board, fp, pad):
                p = pcbnew.VECTOR2I_MM(vx, vy)
                if _blocked(p, blockers, r):
                    continue
                # **ビアの place だけでなく、そこへ引くスタブの経路も見る。**
                # ビア自体は空いていても、パッドからビアまでの線が隣の
                # パッドを横切ることがある。0.5mm ピッチの FFC で実際に
                # 起きた（J_DB のパッド 2 のスタブが、隣の CS を横切って
                # 短絡した。2026-08-12）。
                if _path_blocked(q, p, blockers, _clearance_mm(board)):
                    continue
                out.append((pad, (vx, vy)))
                taken.append(pcbnew.BOX2I(
                    pcbnew.VECTOR2I(p.x - r // 2, p.y - r // 2),
                    pcbnew.VECTOR2I(r, r)))
                break
    return out


def _add_via(board, gnd, x, y):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I_MM(x, y))
    v.SetWidth(pcbnew.FromMM(VIA_DIAMETER_MM))
    v.SetDrill(pcbnew.FromMM(VIA_DRILL_MM))
    v.SetNet(gnd)
    board.Add(v)
    return v


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
        _add_via(board, gnd, vx, vy)
        n += 1
    return n


# ---------------------------------------------------------------- スティッチング

def _segment_obstacles(board):
    """配線を「線分＋半幅」として集める。

    ⚠️ **配線を外接矩形で扱ってはいけない。**斜めの配線の外接矩形は
    その対角線を含む巨大な長方形になり、**斜め線の周囲一帯が「置けない」**
    ことになる。実際それで、長い斜めのバス（列のバス）に沿ってビアが
    1 本も立たなかった（2026-08-13。利用者が絵を見て気づいた）。
    格子のスティッチングが 8 割方失敗していたのも同じ原因。

    返すのは (x1, y1, x2, y2, 半幅) の並び。単位は mm。
    """
    out = []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            r = pcbnew.ToMM(t.GetWidth()) / 2
            x, y = pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)
            out.append((x, y, x, y, r))
            continue
        for ax, ay, bx, by, _L, w in _as_segments(t):
            out.append((ax, ay, bx, by, w / 2))
    return out


def _near_segment(px, py, segs, need_mm):
    """点 (px,py) が、どれかの線分に need_mm より近いか。"""
    for ax, ay, bx, by, half in segs:
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 == 0:
            d2 = (px - ax) ** 2 + (py - ay) ** 2
        else:
            u = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
            qx, qy = ax + u * dx, ay + u * dy
            d2 = (px - qx) ** 2 + (py - qy) ** 2
        if d2 < (need_mm + half) ** 2:
            return True
    return False


def _obstacles(board):
    """ビアを置いてはいけない場所を、箱の一覧として集める。

    **GND のベタは障害物にしない。**ベタは避ける相手ではなく、繋ぐ相手。

    **禁止域（アンテナの真上）は障害物にする。**ここにビアを打つと、
    地板からアンテナを逃がすためにわざわざ空けた穴が埋まる（open-gaps #23）。
    禁止域は矩形なので外接箱がそのまま禁止域になる。
    """
    boxes = []
    # ⚠️ **フットプリントの外接箱を障害物にしてはいけない。**
    #
    # MX スイッチのフットプリントは約 19mm 角あるが、中身はパッドが数枚で
    # ほとんど空き。外接箱で塞ぐと**基板の全面が「置けない」ことになる。**
    # 実際そうなっていて、格子の 324 点中 260 点が飛ばされ、
    # 51.99mm² もある大きな離島にすらビアが入らなかった（2026-08-12）。
    #
    # **ビアを実際に妨げるのはパッドと穴。**そちらで見る。
    #
    # ⚠️ **穴は銅と別に数える**（2026-08-14 に追加）。
    # パッドの外接箱は**銅**の広がりでしかなく、NPTH のように銅が無いか
    # 小さいものは、穴の大きさを表せない。しかも要求される距離が違う
    # （銅どうし 0.2mm に対し `hole_to_hole` は 0.5mm）。
    # **銅の箱だけ見ていたので、ビアが穴の 0.479mm まで寄れていた。**
    #
    # 判定側（`_room_for_a_via` / `_near_segment`）は箱を
    # `_via_keepout_mm` ぶん膨らませる。穴に要るのはそれより
    # `_hole_keepout_mm` との**差だけ大きい**ので、その差を先に足しておけば
    # 同じ経路で正しく効く。
    extra = pcbnew.FromMM(max(0.0, _hole_keepout_mm(board)
                              - _via_keepout_mm(board)))
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            boxes.append(pad.GetBoundingBox())
            drill = pad.GetDrillSizeX()
            if drill <= 0:
                continue                    # SMD。穴は無い
            p = pad.GetPosition()
            hx, hy = pad.GetDrillSizeX() // 2, pad.GetDrillSizeY() // 2
            hole = pcbnew.BOX2I(
                pcbnew.VECTOR2I(p.x - hx - extra, p.y - hy - extra),
                pcbnew.VECTOR2I(2 * (hx + extra), 2 * (hy + extra)))
            boxes.append(hole)
    # **配線はここに入れない。**外接矩形だと斜め線が一帯を塞ぐ。
    # 線分として _segment_obstacles / _near_segment で見る。
    for d in board.GetDrawings():
        boxes.append(d.GetBoundingBox())
    # ⚠️ **ルール領域は「ビアの外径ぶん」膨らませる**（2026-08-15）。
    #
    # 判定側（`_room_for_a_via`）が見るのは**ビアの中心**なので、箱を
    # そのまま入れると**中心が外なら通ってしまい、銅は中に入る。**
    # 実際そうなった: 禁止域の境界 y=1.80 に対しビアの中心 y=1.95、
    # 外径 0.30 の半分がちょうど食い込んで、**DRC が items_not_allowed を
    # 1 件出した**（自作の検算スクリプトも中心で見ていたので気づけず、
    # KiCad の DRC のほうが正しかった）。
    #
    # 上のパッドの穴と同じ型（銅の箱だけ見てビアが 0.479mm まで寄れた）。
    # **距離を要求する側の寸法を、箱のほうに先に足しておく。**
    via_r = pcbnew.FromMM(_via_keepout_mm(board))
    for z in board.Zones():
        if z.GetIsRuleArea():
            bb = z.GetBoundingBox()
            bb.Inflate(via_r)
            boxes.append(bb)
    return boxes


def stitch(board, pitch_mm=STITCH_PITCH_MM):
    """基板の全面に、格子状の GND スティッチングビアを打つ。

    **表と裏のベタを縫い合わせる。**長い配線がベタを割っても、
    反対面を経由して最短距離で横断できるようになる（指摘 5）。
    数が多いほど 2 面の電位が揃う（指摘 4）。

    置けるのは「まわりに何も無いところ」だけ。部品・配線・外形・
    禁止域に触れる場所は飛ばす。**飛ばした数も返す**ので、
    どれだけ打てたかを検査が見られる。
    """
    gnd = board.FindNet("GND")
    if gnd is None:
        return 0, 0

    box = board.GetBoardEdgesBoundingBox()
    x0, x1 = pcbnew.ToMM(box.GetLeft()), pcbnew.ToMM(box.GetRight())
    y0, y1 = pcbnew.ToMM(box.GetTop()), pcbnew.ToMM(box.GetBottom())
    # 外形から十分内側だけ。銅から基板の縁までの規則（0.30mm）に
    # ビアの半径ぶんを足した余裕を取る。
    margin = VIA_DIAMETER_MM / 2 + 0.5

    obstacles = _obstacles(board)
    segs = _segment_obstacles(board)
    need = _via_keepout_mm(board)
    r = pcbnew.FromMM(need)

    placed = skipped = 0
    missed = []                 # 塞がっていた格子点（下で近くへ逃がす）
    y = y0 + margin
    while y <= y1 - margin:
        x = x0 + margin
        while x <= x1 - margin:
            p = pcbnew.VECTOR2I_MM(x, y)
            if _blocked(p, obstacles, r) or _near_segment(x, y, segs, need):
                skipped += 1
                missed.append((x, y))
            else:
                # **置いたビアも次からは障害物にする。**そうしないと
                # 格子が詰まったときにビアどうしが重なる。
                v = _add_via(board, gnd, x, y)
                obstacles.append(v.GetBoundingBox())
                segs.append((x, y, x, y, VIA_DIAMETER_MM / 2))
                placed += 1
            x += pitch_mm
        y += pitch_mm

    # **格子点が塞がっていたら、その近くで空いている所へ逃がす**
    # （2026-08-15・利用者「D6, D7 の下の領域、GND とビア打てないの？」）。
    #
    # 格子は λ/10 = 6.5mm と粗く、子基板は 21x32mm しか無いので**格子点
    # そのものが十数個**しかない。1 点が部品や配線に当たるだけで、
    # その周りが丸ごと空白になる。実測（2026-08-15・D6/D7 の下、
    # x 145..156・y 96..104 を 0.5mm 刻みで走査）: **打てる点が 168 箇所**
    # あるのに、格子がそこを外していたので 1 個も立っていなかった。
    #
    # **ピッチは動かさない**（λ/10 に根拠がある）。**外れた点だけ**を
    # 半ピッチ以内で探し直す。見つからなければ従来どおり飛ばす。
    step = pitch_mm / 8
    reach = pitch_mm / 2
    for gx, gy in list(missed):
        for k in range(1, int(reach / step) + 1):
            d = k * step
            found = None
            # 同心の四角を外へ広げながら、最初に空いた点を採る。
            for dx, dy in ((d, 0), (-d, 0), (0, d), (0, -d),
                           (d, d), (d, -d), (-d, d), (-d, -d)):
                x, y = gx + dx, gy + dy
                if not (x0 + margin <= x <= x1 - margin
                        and y0 + margin <= y <= y1 - margin):
                    continue
                p = pcbnew.VECTOR2I_MM(x, y)
                if _blocked(p, obstacles, r) or _near_segment(x, y, segs, need):
                    continue
                found = (x, y)
                break
            if found:
                v = _add_via(board, gnd, *found)
                obstacles.append(v.GetBoundingBox())
                segs.append((found[0], found[1], found[0], found[1],
                             VIA_DIAMETER_MM / 2))
                placed += 1
                skipped -= 1
                break
    return placed, skipped


# **配線後に 1 本ずつ太らせる後処理は消した**（2026-08-13）。
#
# 指摘 8 は gen_pcb.POWER_CLASSES のクラス分けで達成できている
# （V3V3 = 0.3mm＝FFC の 0.30mm パッドに載る上限、他 = 0.6mm）。
# そのうえで「開けたところだけさらに太く」する後処理も書いたが、
# **自前の当たり判定が取りこぼして DRC 違反を 3 回続けて出した。**
# さらに実測すると、**Freerouting は狭いところで自分から幅を絞っており**、
# 後から一律に太らせるのはその正しい判断を壊す行為だった
# （VBATT 系は 100%、V3V3 は 97% が規定幅で出ている）。
#
# **使わないものを残さない**（CLAUDE.md「置き換えたら古い方を消す」）。


# **`_gnd_anchor_points` はここにあった（2026-08-14 に削除）。**
# 「GND のビアとパッドの中心」を返すだけの関数で、`_islands` が
# 「区画の中にアンカーがあるか」を見るために使っていた。
# その判定ごと連結成分に置き換えたので、呼ぶ側が無くなった。


def _islands(board):
    """(ゾーン, 層, 区画の多角形, その区画が浮いているか) を返す。

    **「浮いている」＝本土（最大の区画）まで辿り着けない。**

    ⚠️ **かつては「区画の中に GND のビアかパッドがあるか」で見ていた
    （2026-08-14 に修正）。**それだと**ビアの行き先を見ていない。**
    ビアが 1 本立っていても、その裏側が B.Cu の**別の孤島**に落ちて
    いれば本土には繋がらない。実測（右基板）では **23 区画すべてが
    「浮いていない」と判定されるのに、KiCad の DRC は未配線を
    1 件出していた。**検査と DRC が同じ銅について逆の結論を出しており、
    `test_few_pieces_of_ground_copper_are_left_floating` は
    「DRC はこれを何も言わない」と書いたまま**素通りしていた。**

    なので**繋がりを辿る。**区画を点、区画を繋ぐものを辺として
    連結成分を作り、本土と同じ成分に入らないものを浮きとする。

    区画を繋ぐのは 3 つ（右基板の実測: ビア 1170 / 配線 8 / パッド 8）。

      ビア    貫通するので**表と裏の区画を繋ぐ**（これが主役）
      配線    同じ層で、両端が乗る区画どうしを繋ぐ
      パッド  この基板の GND パッドは全部 SMD なので片面だけ。
              繋ぐ力は無いが、**本土の判定には要る**ので点として扱う
    """
    return [(z, lay, poly, floating)
            for kind, z, lay, poly, floating in _gnd_pieces(board)
            if kind == "zone"]


def _gnd_pieces(board):
    """GND を作る**すべての**要素と、それぞれが浮いているかを返す。

    返すのは (種類, 物, 層, 多角形か None, 浮いているか) の並び。
    種類は "zone" / "track" / "via"。

    ⚠️ **ベタだけを見ると足りない**（2026-08-14 に実測）。
    浮いたベタを消したら、**そこにしか繋がっていなかった配線とビアが
    残って宙に浮いた。**未配線の中身が「ゾーン×2」から
    「配線＋ビア」に変わっただけで、件数は 1 のまま減らなかった。
    構造はこうだった。

        消したベタ ──> 配線 1.54mm ──> ビア(150.675, 68.8)

    **1 段だけ見る判定では追えない**（「配線に触れているか」で見て、
    その配線自身が浮いていることを見落とした）。だから
    **ベタ・配線・ビアを最初から同じ連結成分に載せる。**
    """
    # ---- 要素を集める ----
    items = []          # (種類, 物, 層, 多角形か None)
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != "GND":
            continue
        for layer in z.GetLayerSet().CuStack():
            if not z.HasFilledPolysForLayer(layer):
                continue
            polys = z.GetFilledPolysList(layer)
            for i in range(polys.OutlineCount()):
                one = pcbnew.SHAPE_POLY_SET()
                one.AddOutline(polys.Outline(i))
                items.append(("zone", z, layer, one))
    tracks = []
    for t in board.GetTracks():
        if t.GetNetname() != "GND":
            continue
        kind = "via" if t.GetClass() == "PCB_VIA" else "track"
        items.append((kind, t, t.GetLayer(), None))
        tracks.append((len(items) - 1, kind, t))

    zone_idx = [i for i, (k, _o, _l, _p) in enumerate(items) if k == "zone"]

    def find_zone(layer, pt):
        """その層のその点を含むベタの番号。無ければ None。

        **外接箱で先に振るう。**多角形の内外判定は重く、
        区画 × 点（ビアだけで 1000 超）を総当たりすると分単位でかかる。
        """
        for i in zone_idx:
            _k, _z, lay, poly = items[i]
            if lay != layer:
                continue
            if poly.BBox().Contains(pt) and poly.Contains(pt):
                return i
        return None

    # ---- union-find ----
    parent = list(range(len(items)))

    def root(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[ra] = rb

    # 点を共有するものどうしを繋ぐ。**配線とビアも要素なので、
    # ベタが無くても配線どうし・配線とビアで繋がりが残る。**
    at = {}
    cu = list(board.GetEnabledLayers().CuStack())
    for idx, kind, t in tracks:
        if kind == "via":
            for lay in cu:
                if t.IsOnLayer(lay):
                    at.setdefault((lay, tuple(t.GetPosition())), []).append(idx)
                    z = find_zone(lay, t.GetPosition())
                    if z is not None:
                        union(idx, z)
        else:
            lay = t.GetLayer()
            for p in (t.GetStart(), t.GetEnd()):
                at.setdefault((lay, tuple(p)), []).append(idx)
                z = find_zone(lay, p)
                if z is not None:
                    union(idx, z)
    for group in at.values():
        for g in group[1:]:
            union(group[0], g)

    # パッドに乗っているものは本土側とみなす（パッドは必ず GND に繋がる）
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() != "GND":
                continue
            for lay in cu:
                if not pad.IsOnLayer(lay):
                    continue
                z = find_zone(lay, pad.GetPosition())
                if z is not None:
                    for idx, kind, t in tracks:
                        if kind == "via" and t.IsOnLayer(lay) \
                                and pad.HitTest(t.GetPosition()):
                            union(idx, z)
                        elif kind == "track" and t.GetLayer() == lay \
                                and (pad.HitTest(t.GetStart())
                                     or pad.HitTest(t.GetEnd())):
                            union(idx, z)

    # ---- 本土を決めて、届かないものを浮きとする ----
    #
    # **本土＝面積が最大のベタ**の成分。基板全面に広がるベタが
    # 必ずいちばん大きい（実測: 右 F.Cu 14257mm² 対 次点 155mm²）。
    if not zone_idx:
        return []
    main = max(zone_idx, key=lambda i: abs(items[i][3].Outline(0).Area()))
    home = root(main)
    return [(k, o, lay, poly, root(i) != home)
            for i, (k, o, lay, poly) in enumerate(items)]


def _room_for_a_via(poly, obstacles, r):
    """その区画にビアを置けるか。置けるなら座標を、置けなければ None。

    **標本化しない。**格子で点を試す方法は刻みに依存し、粗いと
    置ける場所を見落とす。実際 0.5mm 刻みのとき、**ビアを置ける点が
    512 個あった 23.80mm² の区画を「置けない」と判定して捨てていた**
    （2026-08-13）。刻みという調整値そのものを無くす。

    やることは幾何の引き算だけ。

        区画 − （障害物を r だけ膨らませたもの）

    残りが空でなければ、そこがビアの中心を置ける領域。空なら
    どうやっても置けない。**「細かく調べれば見つかるかも」が無くなる。**
    """
    room = pcbnew.SHAPE_POLY_SET()
    room.AddOutline(poly.Outline(0))

    box = poly.BBox()
    box.Inflate(r)
    blockers = pcbnew.SHAPE_POLY_SET()
    n = 0
    for b in obstacles:
        if not box.Intersects(b):
            continue
        big = pcbnew.BOX2I(b.GetOrigin(), b.GetSize())
        big.Inflate(r)
        blockers.NewOutline()
        for x, y in ((big.GetLeft(), big.GetTop()), (big.GetRight(), big.GetTop()),
                     (big.GetRight(), big.GetBottom()), (big.GetLeft(), big.GetBottom())):
            blockers.Append(int(x), int(y))
        n += 1
    if n:
        blockers.Simplify()
        room.BooleanSubtract(blockers)
    # ⚠️ **ここで区画の縁から Deflate してはいけない。**
    #
    # 一度やって、標本化なら 24 点置ける区画を「置けない」と誤判定した
    # （2026-08-13）。**ビアは区画の内側に丸ごと収まる必要が無い。**
    # 区画は GND で、ビアも GND だから、はみ出しても同じネットどうし。
    # 守るべきは**他のネットとの距離**だけで、それは上の引き算で
    # すでに課してある。両方やるとクリアランスを二重に課すことになる。
    room.Simplify()
    if room.IsEmpty() or room.OutlineCount() == 0:
        return None
    # 残った領域の代表点。**重心ではなく頂点**（凹んだ形だと重心は外に出る）
    out = room.Outline(0)
    if out.PointCount() == 0:
        return None
    c = out.CPoint(0)
    return pcbnew.VECTOR2I(c.x, c.y)


# **`_via_has_other_support` はここにあった（2026-08-14 に削除）。**
# 「ビアが配線かパッドにも繋がっているか」を 1 段だけ見る関数だったが、
# **その配線自身が浮いていることを見落とす**（実測: ベタ → 配線 →
# ビアの連鎖で、ビアが 1 本も消えなかった）。判定を `_gnd_pieces` の
# 連結成分に一本化したので、呼ぶ側が無くなった。


def stitch_islands(board, rounds=4):
    """**離島になった GND に、ビアを打って本土へ繋ぎ戻す。**

    2 層では配線がベタを割るので、GND のどこにも触れない区画ができる。
    そういう銅は電位が決まっておらず、**GND ではない**——遮蔽の役に
    立たず、囲んでいる配線どうしを容量結合させ、2.4GHz では寸法次第で
    アンテナになる。

    **消すのではなく繋ぐ。**離島の中にビアを 1 本立てれば、反対面の
    ベタを経由して本土に戻る。これが指摘 5 の「反対側を経由して最短距離で
    横断する」の実体でもある。

    塗る → 浮いている区画を探す → ビアを打つ → 塗り直す、を繰り返す。
    ビアを打つとベタの形が変わり、区画の分かれ方も変わるため 1 回では
    終わらない。**変化が無くなったら止める。**

    どうしてもビアが入らない小片（ビア径 + クリアランスより狭いもの）は
    残る。それは gen_pcb の MIN_ISLAND_MM2 が塗りの段階で捨てる。
    """
    gnd = board.FindNet("GND")
    if gnd is None:
        return 0, 0

    # ⚠️ **島の削除を一時的に止めてから探す。**
    #
    # ゾーンは `ISLAND_REMOVAL_MODE_ALWAYS` にしてある（浮いた銅を
    # 残さないため）。**そのまま塗ると、浮いた区画は塗った瞬間に消える。**
    # 消えたあとに探しても見つからないので、**繋げられるものまで
    # 問答無用で捨てていた**（2026-08-13 発見。23.80mm² の区画に
    # ビアを置ける点が 512 個あったのに、1 個も打たれていなかった）。
    #
    # 正しい順序:
    #   1. 削除を止めて塗る  → 浮いた区画が見える
    #   2. 置けるものにビアを打つ → 本土に繋がる
    #   3. 削除を戻して塗る  → **本当に置けなかったものだけが消える**
    zones = [z for z in board.Zones() if not z.GetIsRuleArea()]
    saved = [(z, z.GetIslandRemovalMode()) for z in zones]
    for z in zones:
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)

    filler = pcbnew.ZONE_FILLER(board)
    r = pcbnew.FromMM(_via_keepout_mm(board))
    added = 0
    for _ in range(rounds):
        filler.Fill(board.Zones())
        obstacles = _obstacles(board) + [
            pcbnew.BOX2I(pcbnew.VECTOR2I_MM(min(a, c) - h, min(b, d) - h),
                         pcbnew.VECTOR2I_MM(abs(c - a) + 2 * h,
                                            abs(d - b) + 2 * h))
            for a, b, c, d, h in _segment_obstacles(board)]
        floating = [(lay, poly) for _z, lay, poly, is_float in _islands(board)
                    if is_float]
        if not floating:
            break
        placed_this_round = 0
        for _lay, poly in floating:
            spot = _room_for_a_via(poly, obstacles, r)
            if spot is None:
                continue           # この区画にはどうやってもビアが入らない
            v = _add_via(board, gnd, pcbnew.ToMM(spot.x), pcbnew.ToMM(spot.y))
            obstacles.append(v.GetBoundingBox())
            added += 1
            placed_this_round += 1
        if not placed_this_round:
            break                      # これ以上は繋げない

    # 削除を元に戻して塗り直す（小片はここで消える）
    for z, mode in saved:
        z.SetIslandRemovalMode(mode)
    filler.Fill(board.Zones())

    # ---- それでも浮いている区画を、名指しで消す ----
    #
    # **面積の閾値（`MIN_ISLAND_MM2`）では分けられない**（2026-08-14 に実測）。
    # 3 枚の全区画を並べると、**浮きの最大 3.01mm² が、繋がっている島の
    # 最小 1.51mm² より大きい。**範囲が重なっているので、どんな値を選んでも
    # 「浮きが残る」か「正常な島を巻き添えにする」かのどちらかになる。
    # 実際 3.5mm² にすると、繋がっている右 1.51 と子基板 2.67 まで消えた。
    #
    # **面積で代理するのをやめる。**`_islands` が「浮いているか」を
    # 正確に答えられるのだから、**その区画だけ**を名指しで消せばよい。
    # 消し方は、その輪郭にベタ禁止のルールエリアを置いて塗らせないこと
    # （KiCad に「この区画だけ削除」は無い）。
    #
    # ⚠️ **抜くのはベタだけ。**配線・ビア・パッドは通す（既定は全部禁止
    # なので明示的に許可する。`_antenna_keepout` で 14 件出した経緯と同じ）。
    # **浮いているものを、種類を問わず一括で消す。**
    #
    # ベタだけ消すと残骸（配線・ビア）が宙に浮く。`_gnd_pieces` は
    # 三者を同じ連結成分で見ているので、**1 回で全部を名指しできる。**
    # 段階的に消して数え直す必要が無い（対症療法の積み重ねを避ける）。
    dropped = 0
    for kind, obj, layer, poly, floating in _gnd_pieces(board):
        if not floating:
            continue
        if kind == "zone":
            # ベタは消せないので、**輪郭にベタ禁止のルールエリアを置く。**
            # ⚠️ 抜くのはベタだけ。配線・ビア・パッドは通す（既定は
            # 全部禁止なので明示的に許可する。`_antenna_keepout` で
            # 14 件出した経緯と同じ）。
            ka = pcbnew.ZONE(board)
            ka.SetIsRuleArea(True)
            ka.SetDoNotAllowZoneFills(True)
            ka.SetDoNotAllowTracks(False)
            ka.SetDoNotAllowVias(False)
            ka.SetDoNotAllowPads(False)
            lset = pcbnew.LSET()
            lset.addLayer(layer)
            ka.SetLayerSet(lset)
            ka.Outline().AddOutline(poly.Outline(0))
            board.Add(ka)
        else:
            board.Remove(obj)
        dropped += 1
    if dropped:
        filler.Fill(board.Zones())

    left = sum(1 for _z, _l, _p, f in _islands(board) if f)
    return added, left


# ---------------------------------------------------- 長い配線に沿ってビアを並べる

# この長さを超える配線を「長いパターン」として扱う（mm）。
#
# **戻り電流の迂回が問題になる長さ**を基準にする。配線がベタを割ると、
# 戻り電流はスリットの端まで回り込む。回り込みの距離がスリットの長さで
# 決まるので、10mm を超えたら途中に横断口を作る。
# （キーピッチ 19.05mm の約半分。行のバスは 1 段ぶんで 19mm 級になる）
FENCE_MIN_LEN_MM = 10.0

# 長い配線に沿ってビアを置く間隔（mm）。格子のスティッチングと同じ考え方。
FENCE_STEP_MM = 3.0

# 配線の中心線からビアの中心までの距離は、**その配線の幅から決める**。
#
# 固定値（0.85mm）にしたら 1 個も置けなかった（2026-08-12）。
# 当たり判定は「相手の外接箱をビア半径＋クリアランスぶん膨らませて、
# ビアの中心が入るか」で見るので、**配線自身の箱に食い込んでしまう。**
# 必要な距離は 配線の半幅 + ビア半径 + クリアランス + 余裕。
# 配線の脇へ置くときの上乗せ（mm）。
#
# 当たり判定は矩形近似なので、**境界ちょうどに置くと判定が揺れる。**
# 0 にしたらフェンスが 121 個 → 20 個に減った（自分の配線の箱に
# 食い込んで弾かれた）。半歩ぶん外へ出す。
FENCE_MARGIN_MM = 0.05


def _as_segments(track):
    """配線を、直線の並びとして返す。円弧は細かく割る。

    ⚠️ **`GetClass() == "PCB_TRACK"` で絞ってはいけない。**
    KiCad の配線は直線（PCB_TRACK）だけでなく**円弧（PCB_ARC）**もある。
    絞ると円弧が丸ごと素通りし、そこにビアが 1 本も立たない。
    **いまの基板に円弧は 0 本**（Freerouting は直線しか出さない）が、
    KiCad で手直しすれば生じる。**そのとき黙って無視されるのが困る。**

    返すのは (始点x, 始点y, 終点x, 終点y, 長さ, 線幅) の並び。単位は mm。
    """
    import math
    cls = track.GetClass()
    if cls == "PCB_VIA":
        return []
    w = pcbnew.ToMM(track.GetWidth())

    def seg(ax, ay, bx, by):
        L = math.dist((ax, ay), (bx, by))
        return (ax, ay, bx, by, L, w) if L > 0 else None

    if cls == "PCB_ARC":
        # 円弧は弦の集まりに割る。1 本あたり 0.5mm を目安に。
        n = max(2, int(pcbnew.ToMM(track.GetLength()) / 0.5))
        c = track.GetCenter()
        cx, cy = pcbnew.ToMM(c.x), pcbnew.ToMM(c.y)
        rad = pcbnew.ToMM(track.GetRadius())
        a0 = math.radians(track.GetArcAngleStart().AsDegrees())
        sweep = math.radians(track.GetAngle().AsDegrees())
        pts = [(cx + rad * math.cos(a0 + sweep * i / n),
                cy + rad * math.sin(a0 + sweep * i / n)) for i in range(n + 1)]
        out = [seg(*pts[i], *pts[i + 1]) for i in range(n)]
        return [s for s in out if s]

    a, b = track.GetStart(), track.GetEnd()
    s = seg(pcbnew.ToMM(a.x), pcbnew.ToMM(a.y),
            pcbnew.ToMM(b.x), pcbnew.ToMM(b.y))
    return [s] if s else []


def fence(board, min_len_mm=FENCE_MIN_LEN_MM, step_mm=FENCE_STEP_MM):
    """**長い配線に沿って、GND のビアを一定間隔で並べる**（指摘 5）。

    なぜ要るか（離島の救済とは別の話）
    ------------------------------------
    信号の戻り電流は、その信号配線の**直近**を流れたがる。長い配線が
    ベタを割ると、割られた向こう側へ戻る電流は**スリットの端まで
    大回り**するしかない。往復のループ面積が大きくなり、放射も、
    隣の配線との結合も増える。配線をまたぐ位置にビアがあれば、
    反対面のベタを経由して**その場で横断できる。**
    「繋がっている」と「最短で行ける」は別。ここが要点。

    ⚠️ 踏んだ穴を 2 つ残す（どちらも利用者が絵を見て気づいた）
    -----------------------------------------------------------
    **(1) 「長い」を線分 1 本の長さで判定しない。**
    列のバスのような斜めの経路は、キーごとの短い線分の連なりでできて
    いる。COL0 は合計 152mm あるのに 10mm 以上の線分は 4 本しかなく、
    **全 406 本のうち 87% が対象外**になっていた。
    見るのは**そのネットが同じ面に持つ経路の合計長**。

    **(2) 配線を外接矩形で避けない。**
    斜めの配線の外接矩形は対角線を含む巨大な長方形になり、
    **斜め線の周囲一帯が「置けない」**ことになる。線分として距離で見る
    （_near_segment）。矩形で見ていたときは、まさに一番ビアが要る
    斜めのバスの脇に 1 本も立たなかった。
    """
    import math
    from collections import defaultdict

    gnd = board.FindNet("GND")
    if gnd is None:
        return 0, 0

    boxes = _obstacles(board)
    segs = _segment_obstacles(board)
    need = _via_keepout_mm(board)
    r = pcbnew.FromMM(need)

    # ネットと層ごとに経路を集める。**順序は決定的に**（始点で並べ替え）。
    runs = defaultdict(list)
    for t in board.GetTracks():
        if t.GetNetname() == "GND":
            continue
        for seg in _as_segments(t):
            runs[(t.GetNetname(), t.GetLayer())].append(seg)

    placed = 0
    n_long = 0
    for key in sorted(runs, key=lambda k: (k[0], k[1])):
        pieces = sorted(runs[key])
        total = sum(s[4] for s in pieces)
        if total < min_len_mm:
            continue                      # この面でのこのネットは短い
        n_long += 1
        acc = step_mm / 2                 # 経路をまたいで間隔を保つ
        for ax, ay, bx, by, length, w in pieces:
            ux, uy = (bx - ax) / length, (by - ay) / length
            nx, ny = -uy, ux
            off = w / 2 + need + FENCE_MARGIN_MM
            d = (step_mm - acc) if acc < step_mm else 0.0
            while d < length:
                cx, cy = ax + ux * d, ay + uy * d
                for sign in (1.0, -1.0):
                    vx, vy = cx + nx * off * sign, cy + ny * off * sign
                    if _blocked(pcbnew.VECTOR2I_MM(vx, vy), boxes, r):
                        continue
                    if _near_segment(vx, vy, segs, need):
                        continue
                    v = _add_via(board, gnd, vx, vy)
                    boxes.append(v.GetBoundingBox())
                    segs.append((vx, vy, vx, vy, VIA_DIAMETER_MM / 2))
                    placed += 1
                d += step_mm
            acc = (acc + length) % step_mm
    return placed, n_long
