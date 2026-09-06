"""試し刷り用に、下シェル・上シェルの**手前の帯と奥の帯だけ**を切り出す。

利用者の要望（2026-09-06）: 変更は手前とコブに集中していて中央は変わらないので、
そこだけ刷って現物確認したい。

出力は `build/_partial_{front,rear}_{case,topcase}_{half}.stl`。**`_` 始まり**なので
slice_check は刷る対象に拾わない（本番の STL と混ざらない）。

  使い方:  .venv/bin/python3 tools/cut_for_test.py left
"""

import sys
from pathlib import Path

from build123d import Align, Box, Location

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_case import BUMP_DEPTH, build_case, build_topcase  # noqa: E402
from gen_plate import halves  # noqa: E402
from verify import BUILD, assert_watertight, to_mesh  # noqa: E402

FRONT_D = 25.0     # 手前の帯: 外面からこの奥行（ネジボス y=−50.9、ベゼル手前バー）
REAR_FROM = 12.0   # 奥の帯: 本体奥端のこの手前から奥面まで（仕切り壁 y≈47.6 を含む）


def main(half):
    keys = halves()[half]
    case, (w, h_body), _ = build_case(keys, half)
    top, _ = build_topcase(keys, half)
    y_out = h_body / 2 + BUMP_DEPTH
    strips = {
        "front": (-h_body / 2 - 1.0, -h_body / 2 + FRONT_D),
        "rear": (h_body / 2 - REAR_FROM, y_out + 1.0),
    }
    for name, (y0, y1) in strips.items():
        cutter = Location((0, (y0 + y1) / 2, 50)) * Box(w * 2, y1 - y0, 200)
        for label, part in (("case", case), ("topcase", top)):
            piece = part.intersect(cutter)
            # intersect は ShapeList を返すことがある。帯の中で切り離された小片
            # （覆いの端など）は捨てて、最大の立体を出す
            solids = list(piece.solids()) if hasattr(piece, "solids") else list(piece)
            piece = max(solids, key=lambda s_: s_.volume)
            mesh, stl = to_mesh(piece, f"_partial_{name}_{label}_{half}")
            assert_watertight(mesh, stl.name)
            b = piece.bounding_box()
            print(f"{stl.name}: {b.size.X:.1f} x {b.size.Y:.1f} x {b.size.Z:.1f}mm "
                  f"(y {b.min.Y:.1f}..{b.max.Y:.1f})  水密={mesh.is_watertight}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "left"))
