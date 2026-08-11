"""組み立て状態を、**人が見られる形**で書き出す。

**この案件でいちばん高くついた不具合（open-gaps #28）は、図にした瞬間に
分かった。**数字とテストだけでは、「そもそもモデルに入っていない物」は
見つからない。**入っているものを全部見せる**のがこの道具の役目。

出すもの（build/assembly/ 以下）:
  {half}_{部品名}.stl   組み立てた位置のまま、部品ごとに 1 ファイル
  {half}_iso.png        全体を色分けして重ねた絵
  {half}_section_*.png  子基板の位置で切った断面

**Blender で見るとき**は、続けて tools/blend_assembly.sh を叩く。
色とカメラの付いた build/assembly/{half}.blend が出るので、それを開く。
（Blender の操作は要らない。import も色付けも向こうがやる）

⚠️ **ここに出るのは「モデルに入っているもの」だけ。出てこない＝検査も
されていない。**#29 で「製品として存在する物」を一通り入れた（23 部品）。
入れない物とその理由は open-gaps #29 の表にある。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build123d import export_stl                      # noqa: E402
from gen_assembly import build_assembly               # noqa: E402
from gen_plate import halves, plate_positions         # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "assembly"

# STEP から起こした形（基板・キースイッチ）を STL にするときの粗さ。
#
# **効くのは角度のほうで、線形はほとんど効かない**（2026-08-11 に実測）。
# kiswitch の MX は全エッジに半径 0.05〜0.1mm のフィレットが入っている
# （円柱面 246 個のうち 86% が半径 0.5mm 未満・中央値 0.100mm）。**その
# 半径では線形許容差が先に満たされて制約にならない**ので、角度だけが
# 分割数を決める。つまり**目に見えない 0.1mm のフィレットが、大きな円柱と
# 同じ分割数をもらう。**
#
#   スイッチ 1 個の三角形数（線形 0.05 固定で角度だけ振った実測）
#     ang=0.1 → 1,250,764 / 0.3 → 130,131 / 0.5 → 54,174 / 0.8 → 21,938
#   線形は 0.01→0.3（30 倍）で 100,820 → 53,420 しか動かない
#
# 大きな面（最大 2.4mm）は線形許容差のほうが先に効くので、角度を緩めても
# 粗くならない。**目で並べて差が無いことを確認済み**（/tmp/switch_compare.png）。
# 締めたくなったら、まず「その面は見えるのか」を測ること。
MESH_LIN = 0.05
MESH_ANG = 0.8

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
    "foot":    ("#8d8d8d", 0.90),   # foot0 / foot1
    # ---- open-gaps #29 で足した実物 ----
    "sockets":   ("#4a7d3a", 0.85),  # Kailh ホットスワップ（保守的な箱）
    "pcb_parts": ("#2f2f2f", 1.00),  # 本体基板の実装部品（KiCad STEP の bbox）
    "db_parts":  ("#5a3d8a", 1.00),  # 子基板裏の FFC コネクタとコンデンサ
    "switches":  ("#c9c9d4", 0.70),  # キースイッチ（箱。実形状でないときだけ）
    # **実形状のキースイッチ。**色が無いと灰色になり、絵の中で見分けが
    # つかない＝見ていないのと同じ（2026-08-11 に利用者が 3D で気づいた）。
    "switches_real": ("#c9c9d4", 0.70),
    "keycaps":   ("#f2ead0", 0.55),  # DSA キーキャップ
    "stabs":     ("#7a5230", 1.00),  # スタビライザのハウジング
    "sw_pwr":    ("#d04040", 1.00),  # 電源スイッチの実物
    "usb_plug":  ("#20a0a0", 1.00),  # 利用者が挿す USB プラグ（挿さった状態）
    "ffc":       ("#e0a020", 0.90),  # FFC ケーブルの占有空間（経路は暫定）
    "inserts":   ("#b08d20", 1.00),  # M2 熱圧入インサート
    "screws":    ("#606870", 1.00),  # M2 ネジ
    "nut":       ("#8090a0", 1.00),  # 1/4-20 六角ナット（テンティング）
    "rubber":    ("#303030", 1.00),  # ゴム足
    # ---- 実形状（視覚確認用。KiCad の STEP を組み立て位置に置いたもの）----
    "pcb_real":  ("#1f4d18", 1.00),  # 本体基板＋全実装部品＋ソケット＋スタビ
    "db_real":   ("#1a2f80", 1.00),  # 子基板＋J_MAIN＋C1（XIAO はモデルが無い）
}


def style_for(name):
    """部品名 → (色, 透明度)。無ければ None。

    **色は種類ごとに 1 つ。**`foot0`/`foot1` は末尾の番号を落として
    `foot` を引く。#29 でスイッチが 61 個入っても、書く色は 1 行でよい。
    **知らない部品には既定色を与えない。**灰色は「落ちない見落とし」に
    なるので、test_assembly が色の無い部品を検出して止める。
    """
    return STYLE.get(name) or STYLE.get(name.rstrip("0123456789").rstrip("_"))


def export(half="left"):
    OUT.mkdir(parents=True, exist_ok=True)
    # 色は Blender 側（blend_assembly.py）でも使う。**そちらは build123d が
    # 無い Blender の Python で動く**ので、import ではなく JSON で渡す。
    (OUT / "style.json").write_text(json.dumps(STYLE, indent=2))
    keys = halves()[half]
    parts, _ = build_assembly(keys, half)
    written = []
    for name, part in parts.items():
        path = OUT / f"{half}_{name}.stl"
        export_stl(part, str(path))
        written.append(path)
    written += export_real(half)
    return parts, written


def export_real(half):
    """**実形状**（KiCad の STEP そのまま）を組み立て位置で STL に出す。

    視覚確認は完成品と同等の形で見たい（利用者の要望・open-gaps #29）。
    干渉検査は保守的な箱（予約地）が受け持ち、**見る方はこちら**を使う。
    Blender（blend_assembly.sh）が {half}_*.stl を全部拾うので、
    箱と実形状が同じ .blend に別レイヤーとして入る。

    ⚠️ XIAO は KiCad にモデルが無いので実形状にも出ない（#29 の表）。
    kicad-cli が無い環境では出せない。**黙って飛ばさず、その旨を出す。**
    """
    import pcb_parts

    if not Path(pcb_parts.KICAD_CLI).exists():
        print("      kicad-cli が無いので実形状（_pcb_real / _db_real）は出ていない")
        return []
    from build123d import Location
    from envelopes import place_pcb
    from gen_case import (BUMP_DEPTH, DB_BOSS_H, DB_D, DB_FROM_REAR, FLOOR,
                          PLATE_TOP_FRONT, WALL, daughterboard_x_center)
    from interface import PLATE_T, plan_depth

    keys = halves()[half]
    positions, (w, h_plate) = plate_positions(keys)
    rim_front = PLATE_TOP_FRONT - PLATE_T

    comp = pcb_parts.real_compound(half)
    board = max(comp.solids(), key=lambda s: s.volume)
    top_z = board.bounding_box().max.Z
    moved = Location((-pcb_parts.ORIGIN[0], pcb_parts.ORIGIN[1], -top_z)) * comp
    # 粗さは MESH_LIN / MESH_ANG（上の説明を読むこと）。既定（1e-3）だと
    # ソケットのフィレットが細分化されて **1 ファイル 900MB** になった。
    out = []
    path = OUT / f"{half}_pcb_real.stl"
    export_stl(place_pcb(moved, h_plate, rim_front), str(path),
               tolerance=MESH_LIN, angular_tolerance=MESH_ANG)
    out.append(path)

    h_case = plan_depth(h_plate)
    db_x = daughterboard_x_center(half, w)
    db_center_y = h_case / 2 + BUMP_DEPTH - WALL - DB_FROM_REAR - DB_D / 2
    dbc = pcb_parts.real_compound("db")
    moved = Location((db_x - pcb_parts.ORIGIN[0], db_center_y + pcb_parts.ORIGIN[1],
                      FLOOR + DB_BOSS_H)) * dbc
    path = OUT / f"{half}_db_real.stl"
    export_stl(moved, str(path), tolerance=MESH_LIN, angular_tolerance=MESH_ANG)
    out.append(path)

    # キースイッチの実形状（kiswitch SW_Cherry_MX_Plate）。**gen_assembly の
    # real_switches をそのまま呼ぶ。**座標の出し方を二重に持たない
    # （2026-08-11: 箱と実物の断面は一致していたが爪・ステム・ピン・LED窓は
    # 箱に無く、検査もされていなかった。同じ理由で「見る」側も置き去りに
    # しない）。third_party_model が無ければ None が返り、黙って飛ばす。
    from gen_assembly import plate_placement, real_switches
    pl = plate_placement(w, h_plate)
    sw = real_switches(positions, pl)
    if sw is not None:
        # 粗さは MESH_LIN / MESH_ANG。**角度を 0.3 のままにすると 192MB**
        # になる（キー 1 個 13 万三角形 × 27）。理由は上の説明。
        path = OUT / f"{half}_switches_real.stl"
        export_stl(sw, str(path), tolerance=MESH_LIN, angular_tolerance=MESH_ANG)
        out.append(path)
    else:
        print("      kiswitch のモデルが無いので switches_real は出ていない")
    return out


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

    layers = [(meshes[n], *(style_for(n) or ("#888888", 0.8))) for n in parts]
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
            color, opacity = style_for(n) or ("#888888", 0.8)
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
          "#29 でスイッチ・キャップ・実装部品・FFC・電源スイッチ・ネジ類まで"
          "入った。入れない物とその理由は open-gaps #29 の表。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
