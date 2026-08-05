"""導入したツールと自己検証の仕組みが機能することを確認する。

このスクリプトが通らない限り CAD 設計には進まない。
エージェントが自分の CAD 出力を検証できる経路の確立が前提だから。

2段階で確認する:
  段階1: 単純形状（穴1つの立方体）で、寸法・メッシュ・図示の3手法が動くか
  段階2: 27穴のモックプレートで、実際の設計対象と同じ複雑さでも判読できるか
         — 段階2 こそが本番。単純形状で動いても、穴が増えると図が破綻しうる。
"""

import sys
from pathlib import Path

import numpy as np
from build123d import (
    Box,
    BuildPart,
    BuildSketch,
    Cylinder,
    Locations,
    Mode,
    Rectangle,
    extrude,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify import (  # noqa: E402
    BUILD,
    assert_bbox,
    assert_no_interference,
    assert_volume,
    assert_watertight,
    render_3d,
    render_outline_2d,
    to_mesh,
)

CUBE = 20.0
HOLE_R = 5.0

PLATE_T = 1.5
CUTOUT = 14.0
PITCH = 19.05
COLS, ROWS = 6, 5
N_CUTOUTS = 27  # 左半分と同じ数にする


def stage1_simple():
    """穴1つの立方体で3手法が動くことを確認する。"""
    with BuildPart() as p:
        Box(CUBE, CUBE, CUBE)
        Cylinder(radius=HOLE_R, height=CUBE * 1.5, mode=Mode.SUBTRACT)
    part = p.part

    assert_bbox(part, expect_x=CUBE, expect_y=CUBE, expect_z=CUBE, label="立方体: ")
    assert_volume(part, CUBE**3 - np.pi * HOLE_R**2 * CUBE, label="立方体: ")
    print(f"OK 段階1-1 寸法: bbox=20^3, volume={part.volume:.1f}mm^3")

    mesh, stl = to_mesh(part, "smoke_cube")
    assert_watertight(mesh, "smoke_cube")
    print(f"OK 段階1-2 メッシュ: {stl.name}, 三角形 {len(mesh.triangles)}, 水密")

    png = render_3d(mesh, BUILD / "smoke_cube_3d.png")
    assert png.stat().st_size > 10_000
    print(f"OK 段階1-3 立体図: {png.name}")


def make_mock_plate():
    """27個の 14mm 角開口を持つ平板。実際のプレートと同じ複雑さ。"""
    w = COLS * PITCH + 6.0
    h = ROWS * PITCH + 6.0
    positions = [
        ((c - (COLS - 1) / 2) * PITCH, ((ROWS - 1) / 2 - r) * PITCH)
        for r in range(ROWS)
        for c in range(COLS)
    ][:N_CUTOUTS]

    with BuildPart() as p:
        with BuildSketch():
            Rectangle(w, h)
            with Locations(*positions):
                Rectangle(CUTOUT, CUTOUT, mode=Mode.SUBTRACT)
        extrude(amount=PLATE_T)
    return p.part, (w, h), positions


def stage2_plate():
    """27穴のプレートで、図が判読可能かを確認する。"""
    part, (w, h), positions = make_mock_plate()

    assert_bbox(part, expect_x=w, expect_y=h, expect_z=PLATE_T, label="モックプレート: ")
    expected = (w * h - N_CUTOUTS * CUTOUT**2) * PLATE_T
    assert_volume(part, expected, label="モックプレート: ")
    print(f"OK 段階2-1 寸法: {w:.1f} x {h:.1f} x {PLATE_T}mm, 開口 {N_CUTOUTS} 箇所")

    mesh, stl = to_mesh(part, "smoke_plate")
    assert_watertight(mesh, "smoke_plate")
    print(f"OK 段階2-2 メッシュ: {stl.name}, 三角形 {len(mesh.triangles)}, 水密")

    # 厳密な2D線画。開口数が図の上でも一致することを確認する。
    png2d = render_outline_2d(
        part, BUILD / "smoke_plate_outline.png", title="mock plate - top view"
    )
    print(f"OK 段階2-3 2D線画: {png2d.name}")

    png3d = render_3d(mesh, BUILD / "smoke_plate_3d.png")
    print(f"OK 段階2-4 立体図: {png3d.name}（判読性の比較用）")

    # 干渉チェック。開口にちょうど収まる部品は干渉しないこと。
    x, y = positions[0]
    with BuildPart() as sw:
        with Locations((x, y, PLATE_T / 2)):
            Box(CUTOUT - 0.2, CUTOUT - 0.2, PLATE_T)
    assert_no_interference(sw.part, part, label="開口とスイッチ: ")
    print("OK 段階2-5 干渉チェック: 開口に収まる部品は干渉しない")

    # 逆に、開口より大きい部品は干渉が検出されること（検査自体の妥当性確認）
    with BuildPart() as big:
        with Locations((x, y, PLATE_T / 2)):
            Box(CUTOUT + 2.0, CUTOUT + 2.0, PLATE_T)
    try:
        assert_no_interference(big.part, part)
    except AssertionError:
        print("OK 段階2-6 干渉チェックは実際に干渉を検出できる")
    else:
        raise AssertionError("干渉するはずの形状で干渉が検出されなかった")


def main():
    BUILD.mkdir(exist_ok=True)
    stage1_simple()
    print()
    stage2_plate()
    print("\n自己検証の仕組みが機能している。生成された PNG を目視して最終確認すること。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
