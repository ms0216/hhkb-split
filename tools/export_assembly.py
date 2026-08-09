"""組み立て状態を、**人が見られる形**で書き出す。

**この案件でいちばん高くついた不具合（open-gaps #28）は、図にした瞬間に
分かった。**数字とテストだけでは、「そもそもモデルに入っていない物」は
見つからない。**入っているものを全部見せる**のがこの道具の役目。

出すもの（build/assembly/ 以下）:
  {half}_{部品名}.stl   組み立てた位置のまま、部品ごとに 1 ファイル
  {half}_iso.png        全体を色分けして重ねた絵
  {half}_section_*.png  子基板の位置で切った断面

**Blender で見るとき**は、File > Import > STL で
build/assembly/left_*.stl を**全部まとめて選ぶ**（位置は入っているので
そのまま組み上がる）。

⚠️ **ここに出るのは「モデルに入っているもの」だけ。**キースイッチも
キーキャップも本体基板の実装部品も FFC ケーブルも入っていない
（open-gaps #29）。**出てこない＝検査もされていない。**
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build123d import export_stl                      # noqa: E402
from gen_assembly import build_assembly               # noqa: E402
from gen_plate import halves, plate_positions         # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "assembly"

# 部品ごとの色と透明度。**中を見せたいものほど薄く。**
STYLE = {
    "case":    ("#9fb3c8", 0.35),   # 外殻。中が見えないと意味がないので薄く
    "topcase": ("#b9c6d4", 0.30),
    "plate":   ("#d7dee6", 0.45),
    "pcb":     ("#7fae6b", 0.55),   # 本体基板（板＋キー下のソケット）
    "batt":    ("#c8a24a", 0.80),
    "lid":     ("#a8b6c4", 0.60),
    "db":      ("#3f7fd0", 0.95),   # 子基板
    "xiao":    ("#e0752c", 1.00),   # 板からはみ出した XIAO の端
    "foot0":   ("#8d8d8d", 0.90),
    "foot1":   ("#8d8d8d", 0.90),
}


def export(half="left"):
    OUT.mkdir(parents=True, exist_ok=True)
    keys = halves()[half]
    parts, _ = build_assembly(keys, half)
    written = []
    for name, part in parts.items():
        path = OUT / f"{half}_{name}.stl"
        export_stl(part, str(path))
        written.append(path)
    return parts, written


def render(half, parts):
    """絵にする。**pyvista が無い環境では飛ばす**（STL は出ている）。"""
    try:
        import render3d
    except Exception as exc:                            # pragma: no cover
        print(f"      描画は飛ばした（{exc}）。STL は出ている")
        return []

    import pyvista as pv
    from gen_case import daughterboard_x_center

    _, (w, _h) = plate_positions(halves()[half])
    meshes = {n: pv.read(str(OUT / f"{half}_{n}.stl")) for n in parts}
    shots = []

    layers = [(meshes[n], *STYLE.get(n, ("#888888", 0.8))) for n in parts]
    for view in ("iso", "bottom"):
        out = OUT / f"{half}_{view}.png"
        # **図中の文字は英数字だけ。**VTK の既定フォントに日本語が無く、
        # 日本語を渡すと**黙って消える**（一度タイトルが消えて気づいた）。
        render3d.assembly(layers, out, view=view,
                          title=f"{half} assembly ({view}) - only what is in the model")
        shots.append(out)

    # 子基板の真ん中で前後に切る。**USB とアンテナの周りが見える切り方。**
    #
    # **部品の色を残したまま切る。**全部を 1 つに merge してから切ると、
    # どれがどれだか分からない灰色の塊になる（一度そうした）。
    # カメラは**コブのあたりに寄せる**。全体を写すと子基板が数 px になる。
    from interface import plan_depth
    from gen_case import BUMP_DEPTH
    _, (_w2, h_plate) = plate_positions(halves()[half])
    h_body = plan_depth(h_plate)
    x = daughterboard_x_center(half, w)

    for tag, (y0, y1, zoom) in {
        "db": (h_body / 2 - 26, h_body / 2 + BUMP_DEPTH + 4, 1.0),
        "all": (-h_body / 2, h_body / 2 + BUMP_DEPTH, 0.9),
    }.items():
        p = render3d._plot((1500, 950))
        for n in parts:
            m = meshes[n]
            color, opacity = STYLE.get(n, ("#888888", 0.8))
            kept = m.clip(normal="x", origin=(x, 0, 0), invert=True)
            if kept.n_points:
                p.add_mesh(kept, color=color, opacity=opacity, smooth_shading=False)
            cut = m.slice(normal="x", origin=(x, 0, 0))
            if cut.n_points:
                p.add_mesh(cut, color=color, line_width=5, opacity=1.0)
        p.enable_lightkit()
        focus = pv.Box(bounds=(x - 1, x + 1, y0, y1, -2, 36))
        render3d._aim(p, focus, (1.0, -0.15, 0.25), zoom=zoom)
        p.add_text(f"{half}: section at daughterboard x={x:.1f} "
                   f"({'rear bump' if tag == 'db' else 'whole'})",
                   font_size=10, color="black")
        out = OUT / f"{half}_section_{tag}.png"
        p.screenshot(str(out))
        p.close()
        shots.append(out)
    return shots


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    halves_ = argv or ["left", "right"]
    for half in halves_:
        parts, written = export(half)
        print(f"OK {half}: 部品 {len(written)} 個 → {OUT}")
        print("      " + " / ".join(sorted(parts)))
        for shot in render(half, parts):
            print(f"      {shot.name}")
    print("\n**ここに出るのはモデルに入っているものだけ。**"
          "キースイッチ・キーキャップ・本体基板の実装部品・FFC ケーブル・"
          "電源スイッチの実物は入っていない（open-gaps #29）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
