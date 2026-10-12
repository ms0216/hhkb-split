"""スティックの頭と、エンコーダのつまみを作る（2026-10-12 に使い方から作り直した版）。build123d だけで動く。

  .venv/bin/python3 docs/hardware/joystick/print/gen_heads.py [出力先]

使い方（利用者・2026-10-12）:
  スティック … 右手の親指。上面に載せて動かすことが多いが、勢いよく倒すときは手前の側面から押すこともある
  エンコーダ … 左手でつまんで回すのが主。上面を指の腹でなぞって回せると嬉しい

どれも**軸を挿す側をベッドに付けて、立てて刷る**（STL の z=0 が軸を挿す口）。下面は 45° の円すいで、支えは要らない。
上面のくぼみ・山・放射の筋は、最後に上向きで刷られる。

スティックの頭（right_stick_head_*.stl）
  軸: φ4・先端 5mm が二面取り幅 3（アルプス RKJXV の図面）。穴は前の版で合った φ4.1×幅 3.1（入口 1.2mm は丸）。
  径 14・側面の高さ 3.2。隣のキーキャップとの隙間は scripts/cap_clear.py で数える（STICK_PROFILE をそのまま渡す）。
    concave … 上面が皿（深さ 1.0）。親指の腹を載せる
    dome    … 上面が丸い山（高さ 1.0）＋輪の溝。どの向きから触っても同じ

エンコーダのつまみ（left_knob_*.stl）
  軸: φ6.0・先端 7.3mm がローレット 18 山・軸の先は取付面から 25.0・軸受け（φ6.8）の上は 12.0（TOP-UP EC12PSD-010）。
  径 20・つまむ側面の高さ 7.7（縦溝 24 本）。キーの上面より上で広がる（下は 45° で細い）。上面に放射の筋 12 本。
  （指を入れて回すくぼみも試したが、STL が閉じず、頼まれてもいないのでやめた）
  穴は丸穴 6.05（0.4mm ノズル）。きつく、一度はめるとなかなか抜けないが、利用者はこれで確定した（2026-10-12）。
  歯に合わせた穴（スプライン）の試し輪も作ったが、使わないことになったので消した（git の履歴 9be2493 にある）。
  スティックの頭は dome（山）で確定。concave は比べた相手として残してある。
"""
import math
import sys
from pathlib import Path

from build123d import Align, Axis, Box, Cone, Cylinder, Location, Plane, Polyline, extrude, make_face, revolve, export_stl

CTR = (Align.CENTER, Align.CENTER, Align.MIN)
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent


def lathe(pts):
    """(半径, 高さ) の折れ線を軸のまわりに回す。"""
    return revolve(make_face(Plane.XZ * Polyline(*pts, close=True)), Axis.Z)


def arc(c_r, c_z, rad, a0, a1, n=8):
    return [(c_r + rad * math.cos(math.radians(a0 + (a1 - a0) * i / n)), c_z + rad * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def flutes(r, z0, z1, n, fr, sink):
    out = None
    for i in range(n):
        a = 2 * math.pi * i / n
        c = Location(((r + fr - sink) * math.cos(a), (r + fr - sink) * math.sin(a), z0)) * Cylinder(fr, z1 - z0, align=CTR)
        out = c if out is None else out + c
    return out


# ---- スティックの頭。高さは「軸の先」を 0 として書き、刷る向きでは +BORE して z=0 を口にする ----
BORE = 6.0                                  # 穴の深さ（＝首の下端は軸の先の 6.0 下）
NECK_R, SHAFT_R, FLAT_W = 3.4, 2.05, 3.1
HEAD_R, HEAD_F = 7.0, 1.2                   # 径 14・上の縁の丸み
SIDE = {"concave": (-0.5, 2.7), "dome": (-0.5, 2.4)}   # 側面の下端・上面（軸の先から）


def stick_profile(kind):
    """隙間の検査に渡す輪郭: [(軸の先からの高さ, 半径)]。上面の造作（皿・山）は隙間に効かないので平らで表す。"""
    s0, s1 = SIDE[kind]
    return [(-BORE, NECK_R), (s0 - (HEAD_R - NECK_R), NECK_R), (s0, HEAD_R)] + [(z, r) for r, z in arc(HEAD_R - HEAD_F, s1 - HEAD_F, HEAD_F, 0, 90)] + [(s1, 0.0)]


def cap_arc(r_edge, z_edge, rise, n=10, flat=0.3):
    """縁 (r_edge, z_edge) から中心までの球面の輪郭（rise が負なら皿）。中心は半径 flat の平らな点で終える
    （球面を軸まで回すと、極で三角形がつぶれて STL が閉じない。実際に起きた）。"""
    rs = (r_edge ** 2 + rise ** 2) / (2 * abs(rise)); zc = z_edge + rise - math.copysign(rs, rise)
    rr = [r_edge + (flat - r_edge) * i / n for i in range(n + 1)]
    pts = [(r, zc + math.copysign(math.sqrt(rs ** 2 - r ** 2), rise)) for r in rr]
    return pts + [(0.0, pts[-1][1])]


TOP_R = {"concave": 5.2, "dome": 5.8}       # 皿／山の半径
TOP_RISE = {"concave": -1.0, "dome": 1.0}


def stick_head(kind):
    s0, s1 = SIDE[kind]
    edge = [] if TOP_R[kind] == HEAD_R - HEAD_F else [(TOP_R[kind], s1)]
    pts = [(0, -BORE)] + [(r, z) for z, r in stick_profile(kind)[:-1]] + edge + cap_arc(TOP_R[kind], s1, TOP_RISE[kind])[1:]
    body = Location((0, 0, BORE)) * lathe(pts)
    if kind == "dome":                       # 山には輪の溝 2 本（幅 0.6・深さ 0.4）
        for r in (2.4, 4.4):
            zr = [z for rr, z in cap_arc(TOP_R[kind], s1, TOP_RISE[kind], n=200) if rr <= r][0] + BORE
            body -= Location((0, 0, zr - 0.4)) * (Cylinder(r + 0.3, 2.0, align=CTR) - Cylinder(r - 0.3, 2.0, align=CTR))
    body -= flutes(HEAD_R, s0 + BORE + 0.2, s1 + BORE - HEAD_F, 28, 0.5, 0.35)    # 側面の縦溝（手前から押すときの掛かり）
    bore = Cylinder(SHAFT_R, 1.2, align=CTR) + Location((0, 0, 1.2)) * (Cylinder(SHAFT_R, BORE - 1.2, align=CTR) & Box(5, FLAT_W, BORE - 1.2, align=CTR))
    bore += Cone(SHAFT_R + 0.3, SHAFT_R, 0.3, align=CTR)                           # 口の面取り（1 層めの太りよけ）
    return body - bore


# ---- 低い皿の頭（2026-10-12・利用者「キーより高くて、指を高くあげないといけない」「クリックは皿のほうがよい」）----
# 下げられる量は小さい: 軸の先がキーの上面より 5.15 高く、真上に置く面はそれ＋屋根より下がらない。
# まわりへ低く広げる案（つば）は、倒したときに**スティック自身の本体の上面**（キーの上面より 2.6 低い）に当たる
# （scripts/cap_clear.py の BODY。つばの下面をキーの上面 +0.8 まで下げると、較正した条件でも食い込む）。
# だから: 屋根を 0.8 に薄く・皿を 0.8 に浅く・側面の壁をやめて斜めの肩に。皿の縁 7.9 → 6.8、肩の下端 5.0（キーの上面から）。
LOW_R, LOW_CONE0, LOW_EDGE, LOW_RIM_R, LOW_RIM_Z, LOW_DISH = 7.5, -4.7, 0.5, 5.4, 1.6, 0.8


def low_profile():
    """隙間の検査に渡す輪郭（上面は平らで表す）。"""
    ze = LOW_CONE0 + (LOW_R - NECK_R)
    return [(-BORE, NECK_R), (LOW_CONE0, NECK_R), (ze, LOW_R), (ze + LOW_EDGE, LOW_R), (LOW_RIM_Z, LOW_RIM_R), (LOW_RIM_Z, 0.0)]


def stick_bore(depth=BORE, r=SHAFT_R, flat=FLAT_W):
    """軸の穴（z=0 が口）。丸い入口 1.2mm → 二面取り。**立てて刷るので、丸から二面取りへは 45° でつなぐ**:
    段のままだと、二面取りの始まりが宙に浮いた棚になって垂れ、丸い所を狭める。"""
    hw = flat / 2
    slab = extrude(make_face(Plane.YZ * Polyline((-r, 1.2), (r, 1.2), (hw, 1.2 + r - hw), (hw, depth), (-hw, depth), (-hw, 1.2 + r - hw), close=True)), 2.5, both=True)
    return Cylinder(r, 1.2, align=CTR) + (Cylinder(r, depth, align=CTR) & slab) + Cone(r + 0.4, r, 0.4, align=CTR)


def stick_head_low():
    prof = low_profile()
    pts = [(0, -BORE)] + [(r, z) for z, r in prof[:-2]]
    pts += arc(LOW_RIM_R - 0.0, LOW_RIM_Z - 0.4, 0.4, 20, 90)[1:]            # 皿の縁の丸み
    pts += cap_arc(LOW_RIM_R - 0.4, LOW_RIM_Z, -LOW_DISH)[1:]
    body = Location((0, 0, BORE)) * lathe(pts)
    ze = LOW_CONE0 + (LOW_R - NECK_R)
    body -= flutes(LOW_R, ze + BORE - 0.6, LOW_RIM_Z + BORE, 30, 0.5, 0.3)   # 肩の縦溝（手前から押すときの掛かり）
    return body - stick_bore()


# ---- つばの広い皿の頭（2026-10-12・利用者「真ん中の皿は良い。つばが狭くて斜めから押しにくい。もっと大きく」）----
# 径 18（つばの幅 3.6。低い皿は 2.1）。**これ以上は右スペースのキーキャップに当たる**（手前右・倒して押し込んだとき）:
#   径 18 … 較正した条件で 1.15 / 0.73mm、径 19 … 0.74 / 0.33、径 20 … 0.29 / 当たる（scripts/cap_clear.py・BODY=True）
# 下面は 20° の浅い円すい。45° だと縁が高くなるか、内側が本体に近づく。**層 0.08mm で刷る**（1 層の張り出し 0.22mm = 線幅の半分）。
WIDE_R, WIDE_NECK, WIDE_ANG, WIDE_EDGE_TOP = 9.0, -3.5, 20.0, 0.0     # 縁の上面は軸の先の高さ（キーの上面 +5.2）


def wide_profile():
    ze = WIDE_NECK + (WIDE_R - NECK_R) * math.tan(math.radians(WIDE_ANG))
    return [(-BORE, NECK_R), (WIDE_NECK, NECK_R), (ze, WIDE_R), (WIDE_EDGE_TOP, WIDE_R), (LOW_RIM_Z, LOW_RIM_R), (LOW_RIM_Z, 0.0)]


def stick_head_wide():
    prof = wide_profile()
    pts = [(0, -BORE)] + [(r, z) for z, r in prof[:-3]]
    pts += arc(WIDE_R - 0.6, WIDE_EDGE_TOP - 0.6, 0.6, 0, 70)                 # 縁の丸み
    pts += arc(LOW_RIM_R, LOW_RIM_Z - 0.4, 0.4, 20, 90)[1:]                   # 皿の縁の丸み
    pts += cap_arc(LOW_RIM_R - 0.4, LOW_RIM_Z, -LOW_DISH)[1:]
    body = Location((0, 0, BORE)) * lathe(pts)
    # つばの上面に溝は付けない（層 0.08 の段がそのまま輪の筋になる。溝を斜面に合わせて切ろうとして、中に空洞を作ってしまった）
    return body - stick_bore()


# ---- つばを下げた皿の頭（2026-10-12・利用者「広げるのではなく、つばを下げるのは？」）----
# つばの外端をキーの上面 +3.8 まで下げる（広い皿は +5.2）。**広さと低さは両立しない**: 倒すと縁は「半径 × sin(倒れ角)」だけ下がるので、
# 低い縁は径を大きくできない。径 17 で、較正した条件の隙間が 1.12 / 1.01mm（相手はスティック自身の本体と右スペース）。径 18 だと 0.96 / 0.55。
# 上面は、皿の縁から外へ向かって下がり、**外端でほぼ水平になる**曲面（鐘の裾の形）。低い所に親指を置く棚ができ、内側の立ち上がりを押せる。
SKIRT_ANG = 20.0
# 名前: (径の半分, 首の上端, 皿の縁の半径, 底の平らな所の半径, 外端の厚み, 丸み)。
# 私の計算は「倒すと下面の内側がスティック本体に当たる」と出て、首 -5.0 を限界と見ていた（scripts/cap_clear.py の BODY）。
# **実物は違った**: 首 -5.0 の lowest でも本体の側は「全然余裕」で、いちばん近いのは右スペースの側（利用者・2026-10-12）。
# ⚠️ ただし同じ日に「いっぱいに倒すと、中心に戻らず止まったままになる。最初の山の形では起きなかった」とも報告があった。
#    倒しきった所でどこかが触れて引っかかっている（下面の内側と本体か、つばの先とキーキャップ）。**どこが触れているか分かるまで、
#    drop1 / drop2 は刷らない**（下げるほど悪くなる向きの変更）。形の定義だけ残してある。
# drop1 / drop2: 丸みも直す:「つばの付け根と先が尖っている」→ 皿の縁の丸み 0.3 → 0.8、外端は上下とも丸める。
#   drop1 … 首なし（下面が筒の下端からすぐ 20° で広がる）。外端の上面はキーの上面 +1.6
#   drop2 … 底を半径 5.0 まで平らにしてから広げる。外端 +1.1。**筒の下端より下へは作れない**（その 0.45mm 下が本体の軸受けの山）
# ⚠️ 2026-10-12 追記: lower / lowest は「どの向きへ倒しても、中心に戻らず止まる」（利用者）。最初の山（dome）は戻る。
#    アルプスの図面（操作部寸法・外形図）を読み直した: 軸は先端 5mm が二面取り、**先から 6.5mm の所に、ひと回り太いつば（軸の根元の部品）がある**。
#    筒の下端はそのつばの 0.5mm 上まで来る設計だった。山の頭は穴の段の垂れで奥まで入らず、高い位置で止まっていた → 当たらない。
#    穴を直して奥まで入るようにした頭だけが戻らない → **筒の下端が根元の部品に触れている疑い**（推定。利用者に頭を 1mm 浮かせて確かめてもらう）。
#    *_s は、形は同じで筒だけ 1mm 短くした物（下端は軸の先から 5.0＝つばの 1.5mm 上。穴の深さ 5.0 で、軸の先が屋根に当たって止まる）。
SKIRTS = {"skirt": (8.5, -4.0, LOW_RIM_R, NECK_R, 0.8, 0.3, 6.0), "skirt_lower": (7.5, -4.5, 4.6, NECK_R, 0.8, 0.3, 6.0), "skirt_lowest": (7.5, -5.0, 4.6, NECK_R, 0.8, 0.3, 6.0),
          "skirt_drop1": (7.5, -BORE, 4.6, NECK_R, 1.0, 0.8, 6.0), "skirt_drop2": (7.5, -BORE, 4.6, 5.0, 1.0, 0.8, 6.0),
          "skirt_lower_s": (7.5, -4.5, 4.6, NECK_R, 1.0, 0.8, 5.0)}


def skirt_profile(kind="skirt"):
    R, neck, rim_r, base_r, edge, _, bore = SKIRTS[kind]
    ze = neck + (R - base_r) * math.tan(math.radians(SKIRT_ANG))
    return [(-bore, NECK_R), (neck, NECK_R), (neck, base_r), (ze, R), (ze + edge, R), (LOW_RIM_Z, rim_r), (LOW_RIM_Z, 0.0)]


def stick_head_skirt(kind="skirt"):
    R, neck, rim_r, base_r, edge, rnd, bore = SKIRTS[kind]
    prof = skirt_profile(kind); ze = prof[3][0]; top_e = ze + edge
    pts = [(0, -bore)] + [(r, z) for i, (z, r) in enumerate(prof[:3]) if i == 0 or (r, z) != (prof[i - 1][1], prof[i - 1][0])]
    if rnd > 0.3:                                                              # 外端: 上下とも丸める（指に当たる所）
        h = edge / 2
        pts += arc(R - h, ze + h, h, -70, 90)
    else:
        pts += [(R, ze)] + arc(R - 0.4, top_e - 0.4, 0.4, 0, 90)
    n = 12                                                                     # 外端から皿の縁へ: 高さ = 外端 + (縁 − 外端) × t²（外端で水平）
    r0, r1 = pts[-1][0], rim_r + rnd * 0.5
    z1 = LOW_RIM_Z - rnd * 0.5
    pts += [(r0 + (r1 - r0) * i / n, top_e + (z1 - top_e) * (i / n) ** 2) for i in range(1, n + 1)]
    pts += arc(rim_r - rnd * 0.37, LOW_RIM_Z - rnd, rnd, 30, 90)[1:]           # 皿の縁の丸み
    pts += cap_arc(rim_r - rnd * 0.37, LOW_RIM_Z, -LOW_DISH)[1:]
    return Location((0, 0, bore)) * lathe(pts) - stick_bore(bore)


# ---- 丸い頭（2026-10-12・利用者「角を可能な限り丸く」「つばを外へ反らせる意図が分からない。親指はそれに沿うほど小さくない」）----
# 親指は頭より大きい。細かい棚や反りは指に合わないので、やめる。**外へふくらむ丸い肩**だけにする（角はどこにも無い）:
#   真ん中: なめらかなくぼみ（深さ 0.8。縁で傾き 0 になる形なので、肩とのつなぎ目に折れ目ができない）
#   肩    : くぼみの縁から外端まで、4 分の 1 のだ円（縁で水平・外端で垂直）
#   外端  : 半径 0.8 の丸みで下面へ回り込む。下面は 20°
# 筒は短い版（下端は軸の先から 5.0。穴の深さ 5.0 で、軸の先が屋根に当たって止まる）。
# (径の半分, 下面が筒に届く高さ, 筒の下端（軸の先から）, 根元の半径)。round_low は首なしで、いちばん下げた形
# ⚠️ round / round_low（筒が短い）は「いっぱいに倒すと戻らない」（利用者・2026-10-12）。操作性は round_low が「非常にいい」。
#    利用者の見立て: **最初の山の頭は、軸のまわりの筒が本体に当たって、倒れきる手前で止めていた。だから離すと戻る。**
#    数えると合う: 半径 3.4・下端 6.0 の筒の角は、約 21° で本体の枠の上面に届く（データシートの最大は 23°）。筒を 5.0 に縮めると届かない。
#    私は逆に「筒が根元に触れて戻らない」と見て筒を縮めていた（外れ）。
#    *_stop は、上の形は round_low のまま、根元を山の頭と同じ（下端 6.0）に戻した物。_stop_thick は根元を太くして、もっと手前（約 18°）で止める。
ROUNDS = {"round": (7.5, -4.5, 5.0, NECK_R), "round_low": (7.5, -5.0, 5.0, NECK_R),
          "round_low_stop": (7.5, -5.0, 6.0, NECK_R), "round_low_stop_thick": (7.5, -5.0, 6.0, 4.2)}
ROUND_NOSE, ROUND_DISH_R = 0.8, 4.6
# 穴: φ4.1×幅 3.1 は「ちょっときつすぎる」（利用者・2026-10-12。立てて刷った頭で）→ *_stop は φ4.2×幅 3.2。
# **奥まで入らないと、根元の筒が止めの位置に来ない**ので、きつさは形と同じくらい効く。
ROUND_BORE_R, ROUND_FLAT = {"round_low_stop": 2.10, "round_low_stop_thick": 2.10}, 3.2


def round_edge_z(kind):
    """外端（肩が垂直になる点）の高さ。下面の 20° と丸みから逆算する。"""
    R, neck, _, _ = ROUNDS[kind]
    t = math.radians(SKIRT_ANG)
    r_end = R - ROUND_NOSE + ROUND_NOSE * math.cos(math.radians(-70))
    return neck + (r_end - NECK_R) * math.tan(t) + ROUND_NOSE * math.sin(math.radians(70))


def round_profile(kind):
    """隙間の検査に渡す輪郭（上面は平らで表す）。"""
    R, neck, bore, root = ROUNDS[kind]; ze = round_edge_z(kind)
    return [(-bore, root), (neck + (root - NECK_R) * math.tan(math.radians(SKIRT_ANG)), root), (ze - ROUND_NOSE, R - 0.5), (ze, R), (LOW_RIM_Z, ROUND_DISH_R), (LOW_RIM_Z, 0.0)]


def stick_head_round(kind):
    R, neck, bore, root = ROUNDS[kind]; ze = round_edge_z(kind); n = 16
    z_root = neck + (root - NECK_R) * math.tan(math.radians(SKIRT_ANG))      # 根元の筒が下面（20°）と交わる高さ
    pts = [(0, -bore), (root - 0.3, -bore), (root, -bore + 0.3)] + ([(root, z_root)] if z_root > -bore + 0.3 else [])
    pts += arc(R - ROUND_NOSE, ze, ROUND_NOSE, -70, 0)                        # 外端の下の丸み
    pts += [(ROUND_DISH_R + (R - ROUND_DISH_R) * math.cos(math.radians(90 * i / n)), ze + (LOW_RIM_Z - ze) * math.sin(math.radians(90 * i / n))) for i in range(1, n + 1)]   # 肩（だ円）
    pts += [(ROUND_DISH_R * (1 - i / n), LOW_RIM_Z - LOW_DISH * (1 - math.cos(math.pi * i / n)) / 2) for i in range(1, n)]            # くぼみ
    pts += [(0.3, LOW_RIM_Z - LOW_DISH), (0, LOW_RIM_Z - LOW_DISH)]
    loose = kind in ROUND_BORE_R
    return Location((0, 0, bore)) * lathe(pts) - (stick_bore(bore, ROUND_BORE_R[kind], ROUND_FLAT) if loose else stick_bore(bore))


# ---- エンコーダのつまみ。高さは取付面から。刷る向きでは −KNOB_BOT ----
SHAFT_TIP, BUSH_TOP = 25.0, 12.0
KNOB_BOT, KNOB_TOP = 13.0, 27.2             # 下端は軸受けの 1.0 上（押し込み 0.5 ぶんを空ける）／屋根 2.2
KNOB_R, STEM_R, KNOB_F = 10.0, 5.5, 1.0
GRIP_FROM = 17.5                            # ここから上がローレットを掴む穴（ローレットは 17.7〜25.0）
SIDE_FROM = 18.5                            # 側面の下端。キーの上面（5 のキーで取付面から 17.3）より上


def knob(bore_d=6.05):
    z = lambda h: h - KNOB_BOT              # noqa: E731
    pts = [(0, z(KNOB_BOT)), (STEM_R, z(KNOB_BOT)), (STEM_R, z(SIDE_FROM) - (KNOB_R - STEM_R)), (KNOB_R, z(SIDE_FROM))]
    pts += arc(KNOB_R - KNOB_F, z(KNOB_TOP) - KNOB_F, KNOB_F, 0, 90) + [(0, z(KNOB_TOP))]
    body = lathe(pts)
    body -= flutes(KNOB_R, z(SIDE_FROM), z(KNOB_TOP) - KNOB_F, 24, 1.0, 0.6)
    for i in range(12):                     # 上面の放射の筋（高さ 0.5・幅 0.9）
        rib = Location((0, 0, z(KNOB_TOP))) * Box(5.0, 0.9, 0.5, align=(Align.MIN, Align.CENTER, Align.MIN))
        body += Location((0, 0, 0), (0, 0, 30 * i)) * (Location((3.6, 0, 0)) * rib)
    body -= Cylinder(3.25, z(GRIP_FROM), align=CTR) + Cone(3.55, 3.25, 0.3, align=CTR)       # 軸（φ6）に触れない所
    body -= Location((0, 0, z(GRIP_FROM))) * Cylinder(bore_d / 2, SHAFT_TIP - GRIP_FROM, align=CTR)
    return body


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for k in SIDE:
        export_stl(stick_head(k), str(OUT / f"right_stick_head_{k}.stl"))
    export_stl(stick_head_low(), str(OUT / "right_stick_head_low.stl"))
    export_stl(stick_head_wide(), str(OUT / "right_stick_head_wide.stl"))
    for k in ROUNDS:
        export_stl(stick_head_round(k), str(OUT / f"right_stick_head_{k}.stl"))
    for k in ("skirt_lower_s",):          # ほかの形は、刷った物の STL をそのまま残してある（作り直すと丸みの式の変更ぶんだけ変わる）
        export_stl(stick_head_skirt(k), str(OUT / f"right_stick_head_{k}.stl"))
    export_stl(knob(), str(OUT / "left_knob_d20.stl"))
    print("出した:", sorted(p.name for p in OUT.glob("*.stl") if p.name.startswith(("right_stick_head", "left_knob_d"))))
