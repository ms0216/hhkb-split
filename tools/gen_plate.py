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
    Align,
    BuildLine,
    Cylinder,
    Circle,
    BuildPart,
    BuildSketch,
    Kind,
    Locations,
    Mode,
    Polyline,
    Rectangle,
    RectangleRounded,
    add,
    extrude,
    make_face,
    offset,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout import bounds_mm, load_layout, split_halves  # noqa: E402

from interface import (
    CORNER_R,
    M2_CLEAR_D,
    PLATE_MARGIN_X,
    PLATE_MARGIN_Y,
    plate_positions,
    PLATE_T,
    STAB_KERF,
    SWITCH_CUTOUT,
    boss_positions,
    stab_offset_for,
    switch_plate_size,
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


def stab_cutout_face(s, at=(0.0, 0.0), kerf=None):
    """スタビ開口の面を、規格の輪郭から `kerf` だけ**外へ広げて**返す。

    **点列に ±kerf を足してはいけない。**28 点は凹凸が入り混じっていて
    点ごとに外向きが違うので、符号を手で並べると必ず間違える（#30）。
    多角形のオフセットに任せる。Kind.INTERSECTION は辺を延長して交わらせる
    ので、角が丸まらず規格の形のまま相似に広がる。

    **既定値を引数に書かない**（`kerf=STAB_KERF` は def の時点で束縛され、
    後から STAB_KERF を差し替えても効かない）。変異検査が値を壊しても
    素通りしてしまうので、呼ばれるたびに読む。
    """
    if kerf is None:
        kerf = STAB_KERF
    with BuildSketch(mode=Mode.PRIVATE) as sk:
        with BuildLine():
            Polyline(*stab_polygon(s, at=at), close=True)
        make_face()
        if kerf:
            offset(amount=kerf, kind=Kind.INTERSECTION)
    return sk.sketch




def build_plate(keys, half):
    """キーの並びから 1 枚のプレートを作る。

    half は "left" / "right"。取付ネジの位置が左右で違うため必須。
    """
    positions, (case_w, case_h) = plate_positions(keys)
    # **寸法は interface.switch_plate_size が 1 つだけ持つ。**
    # ここで自前に計算していたせいで、上ケースの座ぐりとの整合が崩れていた
    # （あちらの注記を読むこと）。
    w, h = switch_plate_size(case_w - PLATE_MARGIN_X * 2,
                             case_h - PLATE_MARGIN_Y * 2)
    stabs = [(pos, stab_offset_for(k.w_u)) for pos, k in zip(positions, keys)]
    stabs = [(pos, s) for pos, s in stabs if s is not None]

    with BuildPart() as plate:
        with BuildSketch():
            RectangleRounded(w, h, CORNER_R)
            with Locations(*positions):
                Rectangle(SWITCH_CUTOUT, SWITCH_CUTOUT, mode=Mode.SUBTRACT)
            for pos, s in stabs:
                add(stab_cutout_face(s, at=pos), mode=Mode.SUBTRACT)
            # 取付ネジの逃げ。**手前の 3 箇所は縁を跨ぐので切り欠きになる。**
            # プレートの縁 y=±52.40 に対して逃げが 50.30〜52.70 なので、
            # 穴ではなく開いた切り欠きとして抜ける（設計どおり）。
            with Locations(*boss_positions(half)):
                Circle(M2_CLEAR_D / 2, mode=Mode.SUBTRACT)
        extrude(amount=PLATE_T)
        # 本体基板を締める柱（open-gaps #36・2026-08-12）。
        #
        # **プレートの裏（−z 側）へ PLATE_TO_PCB だけ伸ばす。**基板は下から
        # ネジで締めるので、**ネジの頭が打鍵面に出ない。**位置は
        # interface.pcb_mount_positions が正本（基板・組み立てと共有）。
        from envelopes import PLATE_TO_PCB
        from interface import PCB_POST_D, PCB_POST_PILOT_D, pcb_mount_positions
        for px, py in pcb_mount_positions(half):
            with Locations((px, py, 0)):
                Cylinder(PCB_POST_D / 2, PLATE_TO_PCB,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
        # 下穴。**柱を立ててから抜く**（先に抜くと柱が埋め戻す）。
        for px, py in pcb_mount_positions(half):
            with Locations((px, py, 0)):
                Cylinder(PCB_POST_PILOT_D / 2, PLATE_TO_PCB + PLATE_T,
                         mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MAX))
    return plate.part, (w, h), positions


def halves():
    """左右それぞれのキー列を返す。"""
    left, right = split_halves(load_layout(SPLIT))
    return {"left": left, "right": right}


def main():
    from verify import BUILD, render_outline_2d, to_mesh

    BUILD.mkdir(exist_ok=True)
    for name, keys in halves().items():
        part, (w, h), _ = build_plate(keys, name)
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
