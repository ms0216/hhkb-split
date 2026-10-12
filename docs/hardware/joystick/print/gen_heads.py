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
  穴は丸穴 6.05 のまま（**これは挿さない**: 0.4mm ノズルの丸穴は、一番ゆるい 6.15 の輪でも抜けにくかった）。
  歯に合わせた穴に作り直す。筋の出は spline_ring_*.stl（0.2mm ノズル）で先に確かめる。
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


# ---- 歯に合わせた穴（スプライン）。軸のローレットは 18 山・山の先 φ6.0（図面）。谷の深さは図面に無いので、筋の出を 3 通り試す ----
# 丸穴に山を食い込ませる留め方は、一番ゆるい 6.15 でも「一度はめるとなかなか抜けない」（利用者・2026-10-12）。
# 回す力は形（筋が谷に入る）で伝え、穴そのものは山の先より大きくして、抜き差しを軽くする。
# 筋の間隔は約 1.1mm なので、0.4mm ノズルでは潰れる。**0.2mm ノズルで刷る。**
SPLINE_MAJOR = 6.25                          # 筋と筋の間の径（山の先 6.0 に触れない）


def spline_bore(tip_d, height, n=18, major=SPLINE_MAJOR):
    """筋つきの穴の「抜く形」: 径 major の円柱から、内向きの三角の筋 n 本を引いたもの。"""
    rm, rt = major / 2 + 0.05, tip_d / 2
    hw = math.pi * major / n * 0.30          # 筋の根元の半幅（間隔の 6 割を筋に）
    rib = extrude(make_face(Polyline((rm, -hw), (rm, hw), (rt, 0.07), (rt, -0.07), close=True)), height)
    cut = Cylinder(major / 2, height, align=CTR)
    for i in range(n):
        cut -= Location((0, 0, 0), (0, 0, 360 / n * i)) * rib
    return cut


RING_H, RING_R = 4.0, 5.0                    # 試し輪は低く小さく（刷る時間を縮める）。本番の掛かりは 7.3mm なので、抜く力は約 2 倍になる


def _ring(cut, notches):
    ring = Cylinder(RING_R, RING_H, align=CTR) - cut
    for i in range(notches):
        ring -= Location((0, 0, 0), (0, 0, 25 * i)) * (Location((RING_R, 0, 0)) * Cylinder(0.7, RING_H, align=CTR))
    return ring


def spline_ring(tip_d, notches):
    return _ring(spline_bore(tip_d, RING_H) + Cone(SPLINE_MAJOR / 2 + 0.3, SPLINE_MAJOR / 2, 0.3, align=CTR), notches)


def round_ring(bore_d, notches):
    return _ring(Cylinder(bore_d / 2, RING_H, align=CTR) + Cone(bore_d / 2 + 0.3, bore_d / 2, 0.3, align=CTR), notches)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for k in SIDE:
        export_stl(stick_head(k), str(OUT / f"right_stick_head_{k}.stl"))
    export_stl(knob(), str(OUT / "left_knob_d20.stl"))
    for n, d in enumerate((5.85, 5.70, 5.55), 1):          # 筋の先の径: 浅い → 深い（切り欠き 1 / 2 / 3）
        export_stl(spline_ring(d, n), str(OUT / f"spline_ring_{n}.stl"))
    for n, d in ((4, 6.25), (5, 6.35)):                    # 比べる用の丸穴（切り欠き 4 / 5）。0.2mm ノズルでの出来を見る
        export_stl(round_ring(d, n), str(OUT / f"spline_ring_{n}_round.stl"))
    print("出した:", sorted(p.name for p in OUT.glob("*.stl") if p.name.startswith(("right_stick_head", "left_knob_d", "spline_ring"))))
