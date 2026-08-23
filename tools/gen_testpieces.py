"""実機と比べて判断するための小さな印刷物を作る。

数値の妥当性を図や表で説明しても、専門外の人には判断できない。
手に取って実機と並べれば誰でも分かる形に落とす。

出力は 3 種類:

  1. front_edge_*.stl  — 前縁の断面を短冊にしたもの。傾き違いを数種類。
                          実機の手前に並べて、当たりの近いものを選ぶ。
  2. height_gauge.stl  — 各列のキートップ高さを段にしたブロック。
                          実機の横に立てて、段の高さが合うか見る。
  3. keycap_row_*.stl  — 参考: 各列のキャップ断面を立体にしたもの。
  4. clearance_coupon.stl — **はめ合いの逃げを決めるクーポン。**
                          穴・軸・ポケットを逃げ違いで並べたもの。
                          K1 Max ＋ 実際のフィラメントで 1 枚刷り、
                          どの逃げが「入るが緩くない」かを見る。

  5. rf_spacer_*.stl   — **アンテナの実測（open-gaps #23・手 0）で、
                          アルミ箔や電池をアンテナから決まった距離に
                          置くための台。**紙を数えるより正確で、
                          C と F で同じものを使い回せる。

いずれも数分で刷れる大きさ。材料はどれでもよい。

⚠️ **rf_spacer だけは材料に条件がある**——**金属を混ぜたフィラメントは
使わない**（カーボン入り・金属入りは導電性がある）。PLA・PETG でよい。
"""

import sys
from math import radians, tan
from pathlib import Path

from build123d import (
    Align,
    Axis,
    Box,
    BuildLine,
    BuildPart,
    BuildSketch,
    Cylinder,
    Location,
    Locations,
    Mode,
    Plane,
    Polyline,
    add,
    extrude,
    make_face,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_hhkb import (  # noqa: E402
    FRONT_TOP_R,
    H_FRONT,
    ROWS,
    solve,
)
from verify import BUILD, assert_watertight, render_outline_2d, to_mesh  # noqa: E402

STRIP_WIDTH = 25.0        # 短冊の幅（指で摘める程度）
STRIP_DEPTH = 30.0        # 前縁から奥へどこまで作るか
LEAN_ANGLES = [8.0, 12.0, 16.0]   # 前面の傾き候補。目測値 12° を挟む
GAUGE_STEP_W = 12.0       # 段の幅
GAUGE_BASE = 3.0          # [記録のみ] 台座の厚み（いまの治具では使っていない）


def front_edge_profile(lean_deg, r=FRONT_TOP_R, h=H_FRONT, depth=STRIP_DEPTH):
    """前縁だけの断面。左が前、右が奥。"""
    import math

    lean = radians(lean_deg)
    cy, cz = r, h - r
    arc = []
    for k in range(13):
        a = math.radians(90) * k / 12 - lean * (k / 12)
        arc.append((cy - r * math.sin(a), cz + r * math.cos(a)))
    y_face_top, z_face_top = arc[-1]
    y_bottom = y_face_top + z_face_top * tan(lean)
    return [(y_bottom, 0.0)] + arc[::-1] + [(depth, h), (depth, 0.0)]


def build_strip(points, width):
    with BuildPart() as p:
        with BuildSketch(Plane.YZ):
            with BuildLine():
                Polyline(*points, close=True)
            make_face()
        extrude(amount=width)
    return p.part


def build_height_gauge():
    """各列のキートップ高さを段にしたブロック。

    段の上面が、その列のキートップ高さ（机上面から）に一致する。
    実機の横に置き、段の天面とキートップの高さを見比べる。
    """
    g = solve(4.0)
    heights = list(g.rows_cap_top_z)          # 手前から奥へ
    with BuildPart() as p:
        for i, z in enumerate(heights):
            with BuildSketch(Plane.XY.offset(0)):
                with BuildLine():
                    x0 = i * GAUGE_STEP_W
                    Polyline((x0, 0), (x0 + GAUGE_STEP_W, 0),
                             (x0 + GAUGE_STEP_W, STRIP_WIDTH), (x0, STRIP_WIDTH),
                             close=True)
                make_face()
            extrude(amount=z)
    return p.part, heights


# はめ合いのクーポン（open-gaps #11）
#
# **CLEARANCE = 0.2 は実測でなく仮定。**蓋のレール・脚のピン・
# インサートナット・子基板・電源スイッチのポケットが全部これを使っている。
# 3Dプリントは穴が縮み、XY と Z で収縮量も違う。1 枚刷れば決まる。
#
# 相手方の代表寸法。実際に使っている数値から採る。
COUPON_CLEARANCES = [0.0, 0.1, 0.2, 0.3, 0.4]
COUPON_PEG_D = 4.0        # 脚のピン相当（丸）
COUPON_SLOT = (8.6, 4.4)  # 電源スイッチ相当（角）
COUPON_T = 4.0            # 板厚
COUPON_PITCH = 14.0


# アンテナの実測（open-gaps #23・task-c3-ble-split §6-6b）で使う台の厚み。
#
# **数字は設計の実測から来ている。**手で決めた値ではない:
#
#   5.0mm  アンテナ → 本体基板の最短距離 **5.24mm**
#          （`test_the_antenna_keeps_its_distance_from_the_main_board`
#            が守っている値。C の測定で使う）
#   4.0mm  **作り直す前の姿**（アンテナの真上に地板があった頃）。
#          F の測定で使う。現在の幾何とは一致しなくてよい
#
# ⚠️ **17mm（D の電池）は刷らない。**§6-6b に「**定規で測って置くだけ
# （スペーサー不要）**」と書いてある。**電池は横に置くだけ**なので、
# 浮かせる台は要らない。刷ると層が 85 になり、**3 個ぶんの印刷時間の
# 半分以上をここが占める**（2026-08-23・利用者「とにかく高速に」）。
#
# ⚠️ **薄いほうが厳しい側**なので、刷り上がりが少し薄くても安全側に外れる。
# **測って記録すれば読める**（§6-6b「ぴったりでなくてよい」）。
RF_SPACER_MM = (4.0, 5.0)

# **小さい柱を 3 本。**（2026-08-23・利用者「あくまで実験用なので、
# とにかく高速に印刷できるものがいい」）
#
# ⚠️ **測定に要るのは「厚み」だけで、面積は要らない。**
# 最初は 40×40mm の枠にしたが、**載せるのはアルミ箔か電池**なので
# 支える点が 3 つあれば足りる。**体積が 1/10 以下になる。**
#
# **3 本なのは、3 点で面が決まるから。**4 本だとガタつく。
RF_PILLAR_D = 8.0          # 柱の直径
RF_PILLAR_SPREAD = 30.0    # 3 本を置く円の直径


def build_rf_spacer_pair():
    """**4mm と 5mm を 1 部品にした台**（2026-08-23）。

    利用者「同時に両方印刷した方が早いと思うので、並べられないでしょうか？」

    ⚠️ **2 個を並べるより、1 部品にするほうが速い。**別々に置くと
    **層ごとに 2 個を行き来する**ので、その移動が全層ぶん積み上がる。
    繋げてしまえば移動は 1 回で済む。

    **形**: 柱 3 本の台を 2 つ、桟で繋いだもの。**低いほうが 4mm・高いほうが 5mm。**
    ⚠️ **目印は要らない。**溝を彫ろうとしたが、柱は円周上の 3 点で
    中央には何も無いので**彫る相手がいなかった**（実測で確認）。
    **高さが 4mm と 5mm なので、並べれば目で分かる。**

    ⚠️ **使うときは折らない。**そのまま 2 つの高さの台として使える
    （C では 5mm 側に、F では 4mm 側にアルミ箔を載せる）。
    """
    a = build_rf_spacer(RF_SPACER_MM[0])
    b = build_rf_spacer(RF_SPACER_MM[1])
    gap = RF_PILLAR_SPREAD + RF_PILLAR_D + 6.0
    with BuildPart() as pair:
        add(a.moved(Location((-gap / 2, 0, 0))))
        add(b.moved(Location((gap / 2, 0, 0))))
        # 2 つを繋ぐ桟（薄い板）。**折らずにそのまま使う**ので、
        # 강度は要らない。バラけないためだけ。
        Box(gap, RF_PILLAR_D * 0.5, 1.2,
            align=(Align.CENTER, Align.CENTER, Align.MIN))
    return pair.part


def build_rf_spacer(h):
    """アンテナの実測で使う台。**厚みが分かっていることだけが大事。**

    **柱 3 本と、それを繋ぐ細い桟。**載せるのはアルミ箔か電池なので
    強度は要らない。**速く刷ることを優先する。**

    ⚠️ **金属入りフィラメントで刷らないこと。**導電性があると
    測っているもの（導体を近づけた影響）に混ざる。
    """
    import math
    r = RF_PILLAR_SPREAD / 2
    pts = [(r * math.cos(math.radians(a)), r * math.sin(math.radians(a)))
           for a in (90, 210, 330)]
    with BuildPart() as sp:
        # 柱 3 本
        for x, y in pts:
            with Locations((x, y, 0)):
                Cylinder(RF_PILLAR_D / 2, h,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
        # 桟。**柱どうしを細い角材で繋ぐだけ**（バラけないように）。
        # 薄いので刷る時間はほとんど増えない。
        base = min(h, 1.2)
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            L = math.dist((x1, y1), (x2, y2))
            ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
            with Locations(Location((mx, my, 0), (0, 0, ang))):
                Box(L, RF_PILLAR_D * 0.5, base,
                    align=(Align.CENTER, Align.CENTER, Align.MIN))
    return sp.part


def build_clearance_coupon():
    """逃げ違いの穴を並べた板。丸穴と角穴の両方を見る。

    **丸と角で縮み方が違う。**角は隅に材料が寄るので、同じ逃げでも
    きつくなる。片方だけ見て決めると、もう片方で外す。
    """
    n = len(COUPON_CLEARANCES)
    w = COUPON_PITCH * n + 6.0
    with BuildPart() as coupon:
        Box(w, COUPON_PITCH * 2 + 6.0, COUPON_T,
            align=(Align.CENTER, Align.CENTER, Align.MIN))
        for i, c in enumerate(COUPON_CLEARANCES):
            x = -w / 2 + 3.0 + COUPON_PITCH * (i + 0.5)
            with Locations((x, COUPON_PITCH / 2, 0)):
                Cylinder(( COUPON_PEG_D + c) / 2, COUPON_T * 3,
                         mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.CENTER))
            with Locations((x, -COUPON_PITCH / 2, 0)):
                Box(COUPON_SLOT[0] + c, COUPON_SLOT[1] + c, COUPON_T * 3,
                    mode=Mode.SUBTRACT,
                    align=(Align.CENTER, Align.CENTER, Align.CENTER))
    return coupon.part


# A1 mini のベッド端の実効幅を測る試し板（open-gaps #51）。
#
# 右ケースの分割面を 2.1mm 詰めると 177.6mm になる（外側の縁は実機再現
# なので触れない）。**この幅が A1 mini（公称 180×180）で実際に刷れるかは
# 位置決め誤差と初層の潰れ次第で、機械では決められない**ので現物で測る。
#
# 使い方: スライサーで**回転させず**、ベッドの手前端いっぱいに手で置いて
# 刷る。端が欠ける・剥がれる・置けないなら、その幅は使えない。
#
# 幅は 2 種類:
#   177.6  分割面+外側とも最大に詰めた案（✅ 2026-08-24 実測で刷れた）
#   178.5  推奨案（隙間0.9 + ベゼル壁1.2 + ケース側壁2.0・基板無傷）の幅
A1_STRIP_WIDTHS = (177.6, 178.5)
A1_STRIP_D, A1_STRIP_H = 10.0, 1.0


def build_bed_edge_strip(w):
    """幅 w の細長い板。数分・数円で「置けるか」だけを見る。"""
    with BuildPart() as strip:
        Box(w, A1_STRIP_D, A1_STRIP_H,
            align=(Align.CENTER, Align.CENTER, Align.MIN))
    return strip.part


def main():
    BUILD.mkdir(exist_ok=True)

    print("前縁テストピース（実機の手前に並べて当たりを比べる）")
    for lean in LEAN_ANGLES:
        part = build_strip(front_edge_profile(lean), STRIP_WIDTH)
        mesh, stl = to_mesh(part, f"front_edge_{int(lean)}deg")
        assert_watertight(mesh, stl.name)
        bb = part.bounding_box().size
        print(f"  傾き {lean:4.1f}°  {bb.X:.1f} x {bb.Y:.1f} x {bb.Z:.1f}mm  -> {stl.name}")
    render_outline_2d(
        build_strip(front_edge_profile(LEAN_ANGLES[1]), STRIP_WIDTH),
        BUILD / "front_edge_profile.png", axis="X",
        title=f"front edge test piece  lean={LEAN_ANGLES[1]} deg",
        annotate_count=False,
    )

    print("\nはめ合いクーポン（1 枚刷って CLEARANCE を決める / open-gaps #11）")
    part = build_clearance_coupon()
    mesh, stl = to_mesh(part, "clearance_coupon")
    assert_watertight(mesh, stl.name)
    print(f"  丸穴 φ{COUPON_PEG_D}  角穴 {COUPON_SLOT[0]}x{COUPON_SLOT[1]}mm")
    print("  逃げ " + " / ".join(f"{c:.1f}" for c in COUPON_CLEARANCES) + "mm（左から）")
    bb = part.bounding_box().size
    print(f"  全体 {bb.X:.1f} x {bb.Y:.1f} x {bb.Z:.1f}mm  -> {stl.name}")

    print("\n高さゲージ（実機の横に立てて各列の高さを見比べる）")
    part, heights = build_height_gauge()
    mesh, stl = to_mesh(part, "height_gauge")
    assert_watertight(mesh, stl.name)
    names = [r[0] for r in ROWS]
    for n, z in zip(names, heights):
        print(f"  {n:8s} 段の高さ {z:5.1f}mm")
    bb = part.bounding_box().size
    print(f"  全体 {bb.X:.1f} x {bb.Y:.1f} x {bb.Z:.1f}mm  -> {stl.name}")

    print("\nアンテナ実測用のスペーサー（open-gaps #23 の手 0 / §6-6b）")
    print("  ⚠️ **金属入りフィラメントで刷らないこと**（導電性がある）")
    print("  **4mm と 5mm を 1 部品にした**（別々に置くより速い）")
    part = build_rf_spacer_pair()
    mesh, stl = to_mesh(part, "rf_spacer_pair")
    assert_watertight(mesh, stl.name)
    bb = part.bounding_box().size
    print(f"  全体 {bb.X:.1f} x {bb.Y:.1f} x {bb.Z:.1f}mm  -> {stl.name}")
    print("     **低いほう** 4.0mm  F: ホイルを真上 4mm（作り直す前の姿）")
    print("     **高いほう** 5.0mm  C: ホイルを斜め上 5mm（本体基板）")

    print("\nA1 mini ベッド端の試し板（open-gaps #51・幅詰め案の可否）")
    print("  ⚠️ スライサーで**回転させず**、ベッド端いっぱいに手で置くこと")
    for w in A1_STRIP_WIDTHS:
        part = build_bed_edge_strip(w)
        name = f"bed_edge_strip_{w:.1f}".replace(".", "p")
        mesh, stl = to_mesh(part, name)
        assert_watertight(mesh, stl.name)
        bb = part.bounding_box().size
        print(f"  {bb.X:.1f} x {bb.Y:.1f} x {bb.Z:.1f}mm  -> {stl.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
