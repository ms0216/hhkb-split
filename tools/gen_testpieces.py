"""実機と比べて判断するための小さな印刷物を作る。

数値の妥当性を図や表で説明しても、専門外の人には判断できない。
手に取って実機と並べれば誰でも分かる形に落とす。

出力は 3 種類:

  1. front_edge_*.stl  — 前縁の断面を短冊にしたもの。傾き違いを数種類。
                          実機の手前に並べて、当たりの近いものを選ぶ。
  2. height_gauge.stl  — 各列のキートップ高さを段にしたブロック。
                          実機の横に立てて、段の高さが合うか見る。
  3. keycap_row_*.stl  — 参考: 各列のキャップ断面を立体にしたもの。

いずれも数分で刷れる大きさ。材料はどれでもよい。
"""

import sys
from math import radians, tan
from pathlib import Path

from build123d import (
    Axis,
    BuildLine,
    BuildPart,
    BuildSketch,
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
GAUGE_BASE = 3.0          # 台座の厚み


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

    print("\n高さゲージ（実機の横に立てて各列の高さを見比べる）")
    part, heights = build_height_gauge()
    mesh, stl = to_mesh(part, "height_gauge")
    assert_watertight(mesh, stl.name)
    names = [r[0] for r in ROWS]
    for n, z in zip(names, heights):
        print(f"  {n:8s} 段の高さ {z:5.1f}mm")
    bb = part.bounding_box().size
    print(f"  全体 {bb.X:.1f} x {bb.Y:.1f} x {bb.Z:.1f}mm  -> {stl.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
