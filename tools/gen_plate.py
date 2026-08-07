"""スイッチプレートを生成する。

配列は tools/layout.py から取る。このファイルは配列の値を持たない。

座標系: CAD は X 右 / Y 上 / Z 上。layout.py は Y が下向きなので反転する。
プレートは原点中心に置く。

取付ネジ穴はここでは開けない。位置がケースの壁に依存するため、
ケース設計（フェーズ B2）で決める。ネジ穴はプレートと PCB の両方に効く
「凍結すべき境界」なので、基板を発注する前に必ず確定させること。
"""

import sys
from pathlib import Path

from build123d import (
    BuildLine,
    Circle,
    BuildPart,
    BuildSketch,
    Locations,
    Mode,
    Polyline,
    Rectangle,
    RectangleRounded,
    extrude,
    make_face,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout import bounds_mm, load_layout, split_halves  # noqa: E402

from interface import (  # noqa: E402
    CORNER_R,
    M2_CLEAR_D,
    PLATE_MARGIN,
    PLATE_T,
    SWITCH_CUTOUT,
    boss_positions,
    stab_offset_for,
)

SPLIT = "layout/hhkb_split.json"

# 設計値は tools/interface.py（プレートとケースと基板が共有する境界）に置く。
# ここで独自に定義するとケース側とずれる。

# --------------------------------------------------------------------------
# Cherry 規格のスタビライザー開口
#
# 出典: swillkb Plate & Case Builder の実装 `swill/kad` の key.go
#   - GetCherryStabOffset(): キー中心からスタビライザー中心までの距離
#   - DrawCherryStab():      開口のポリゴン（kerf=0 の座標をそのまま採用）
# 推測値ではなく、実際に基板・プレートを起こすのに使われている実装の値。
#
# 2u 未満のキーにはスタビライザーを入れない（業界慣行）。
# 本設計で該当するのは 左Shift 2.25u / Enter 2.25u / L-Space 3u / R-Space 3u。
# --------------------------------------------------------------------------
# スタビライザー間隔は interface.py（凍結境界）から読む。基板と共有するため。

def stab_polygon(s, at=(0.0, 0.0)):
    """半間隔 s のスタビライザー開口を、中心 `at` に置いた点列で返す。

    平行移動は Locations に頼らず自分で行う。BuildLine の中身には
    Locations が効かず、すべての開口が原点に重なる不具合を起こしたため。

    key.go の DrawCherryStab のパス（28点、kerf=0）をそのまま転記する。
    自分で組み立て直すと間違えるので、係数の並びを変えない。
    swillkb は Y 下向き、build123d は Y 上向きなので最後に符号を反転する。
    """
    pts = [
        (s - 3.375, -2.3), (s - 3.375, -5.53), (s + 3.375, -5.53),
        (s + 3.375, -2.3), (s + 4.2, -2.3), (s + 4.2, 0.5),
        (s + 3.375, 0.5), (s + 3.375, 6.77), (s + 1.65, 6.77),
        (s + 1.65, 7.97), (s - 1.65, 7.97), (s - 1.65, 6.77),
        (s - 3.375, 6.77), (s - 3.375, 2.3), (-s + 3.375, 2.3),
        (-s + 3.375, 6.77), (-s + 1.65, 6.77), (-s + 1.65, 7.97),
        (-s - 1.65, 7.97), (-s - 1.65, 6.77), (-s - 3.375, 6.77),
        (-s - 3.375, 0.5), (-s - 4.2, 0.5), (-s - 4.2, -2.3),
        (-s - 3.375, -2.3), (-s - 3.375, -5.53), (-s + 3.375, -5.53),
        (-s + 3.375, -2.3),
    ]
    ax, ay = at
    return [(ax + x, ay - y) for x, y in pts]




def plate_positions(keys):
    """キー中心を CAD 座標（原点中心・Y 上向き）に直す。"""
    x0, y0, x1, y1 = bounds_mm(keys)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    size = (x1 - x0 + PLATE_MARGIN * 2, y1 - y0 + PLATE_MARGIN * 2)
    return [(k.x_mm - cx, cy - k.y_mm) for k in keys], size


def build_plate(keys):
    """キーの並びから 1 枚のプレートを作る。"""
    positions, (w, h) = plate_positions(keys)
    stabs = [(pos, stab_offset_for(k.w_u)) for pos, k in zip(positions, keys)]
    stabs = [(pos, s) for pos, s in stabs if s is not None]

    with BuildPart() as plate:
        with BuildSketch():
            RectangleRounded(w, h, CORNER_R)
            with Locations(*positions):
                Rectangle(SWITCH_CUTOUT, SWITCH_CUTOUT, mode=Mode.SUBTRACT)
            for pos, s in stabs:
                with BuildLine():
                    Polyline(*stab_polygon(s, at=pos), close=True)
                make_face(mode=Mode.SUBTRACT)
            # 取付ネジのバカ穴。ケース側のボスと同じ位置に開ける。
            # これが無いとプレートとケースを締結できない（当初開け忘れていた）。
            with Locations(*boss_positions(w, h)):
                Circle(M2_CLEAR_D / 2, mode=Mode.SUBTRACT)
        extrude(amount=PLATE_T)
    return plate.part, (w, h), positions


def halves():
    """左右それぞれのキー列を返す。"""
    left, right = split_halves(load_layout(SPLIT))
    return {"left": left, "right": right}


def main():
    from verify import BUILD, render_outline_2d, to_mesh

    BUILD.mkdir(exist_ok=True)
    for name, keys in halves().items():
        part, (w, h), _ = build_plate(keys)
        mesh, stl = to_mesh(part, f"plate_{name}")
        png = render_outline_2d(
            part, BUILD / f"plate_{name}.png",
            title=f"plate {name} - top view  {w:.1f} x {h:.1f} mm",
        )
        print(f"{name:5s} {len(keys):2d} keys  {w:6.2f} x {h:6.2f} x {PLATE_T}mm  "
              f"水密={mesh.is_watertight}")
        print(f"      {stl}")
        print(f"      {png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
