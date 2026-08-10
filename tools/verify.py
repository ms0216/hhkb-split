"""CAD 出力を検証する。エージェントが自分の設計を確認するための道具一式。

3つの方法を使い分ける:

  1. 寸法アサーション  — bbox・体積・肉厚を数値で検証する（最も信頼できる）
  2. 干渉チェック      — 2形状のブーリアン積の体積が 0 か
  3. 図示              — PNG に落として目視する

図示には2種類ある。用途を間違えると誤った判断をする。

  render_outline_2d() : 形状の稜線を厳密に投影した線画。キー配置・穴位置の検証用。
                        面の前後関係の問題が原理的に起きないので、これが主役。
  render_3d()         : 陰影付きの立体図。全体の姿を掴む用。
                        matplotlib は面の前後関係を厳密には解けないため、
                        穴の多い形状では内壁が透けて見える。細部の判断に使わない。
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from build123d import Axis, export_stl  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

BUILD = Path(__file__).resolve().parent.parent / "build"


# --------------------------------------------------------------------------
# メッシュ変換
# --------------------------------------------------------------------------


def to_mesh(part, name):
    """build123d の形状を STL 経由で trimesh に変換する。STL も残す。"""
    BUILD.mkdir(exist_ok=True)
    stl = BUILD / f"{name}.stl"
    export_stl(part, str(stl))
    return trimesh.load(str(stl)), stl


# --------------------------------------------------------------------------
# 検証1: 寸法アサーション
# --------------------------------------------------------------------------


def assert_watertight(mesh, name):
    assert mesh.is_watertight, f"{name}: STL が水密でない（このままでは印刷できない）"


def assert_bbox(part, expect_x=None, expect_y=None, expect_z=None, tol=0.05, label=""):
    size = part.bounding_box().size
    for axis, expected in (("X", expect_x), ("Y", expect_y), ("Z", expect_z)):
        if expected is None:
            continue
        actual = getattr(size, axis)
        assert abs(actual - expected) < tol, (
            f"{label}{axis} が想定と違う: {actual:.3f}mm (期待 {expected:.3f}mm)"
        )


def assert_volume(part, expected, rel_tol=1e-3, label=""):
    error = abs(part.volume - expected) / expected
    assert error < rel_tol, (
        f"{label}体積が想定と違う: {part.volume:.1f}mm^3 (期待 {expected:.1f}mm^3)"
    )


# --------------------------------------------------------------------------
# 検証2: 干渉チェック
# --------------------------------------------------------------------------


def intersection_volume(a, b):
    """2形状の重なり体積(mm^3)。0 なら干渉なし。"""
    common = a & b
    if common is None:
        return 0.0
    try:
        return float(common.volume)
    except (AttributeError, ValueError):
        return 0.0


def shape_digest(shape):
    """立体の**形と位置**を丸ごと表すハッシュ（BRep のバイト列の SHA-256）。

    結果の記憶（#31）の鍵。0.001mm 動かしただけで別の値になることを
    実測で確認済み。弱い指紋（bbox＋体積など）は別の形を同じと誤認して
    嘘の緑を作るので使わない。
    """
    import hashlib
    import os
    import tempfile

    from OCP.BinTools import BinTools

    fd, p = tempfile.mkstemp()
    os.close(fd)
    try:
        BinTools.Write_s(shape.wrapped, p)
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:24]
    finally:
        os.unlink(p)


MEMO_PATH = BUILD / "interference_memo.json"


def load_interference_memo():
    """結果の記憶を読む。**ただのキャッシュ。**消しても遅くなるだけ。

    鍵は 2 立体のハッシュ（形＋位置）の組。「前回から何が変わったか」という
    基準を持たない内容アドレスなので、基準が古くなる失敗の型（#29 で
    一日かけて潰したもの）が構造的に入らない。1 bit 違えば必ず測り直す。
    """
    import json

    try:
        return json.loads(MEMO_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_interference_memo(memo, touched):
    import json

    # ponytail: 記憶は増える一方なので、5 万組を超えたら今回触った組だけ残す
    if len(memo) > 50_000:
        memo = {k: memo[k] for k in touched if k in memo}
    BUILD.mkdir(exist_ok=True)
    MEMO_PATH.write_text(json.dumps(memo))


def memoized_intersection_volume(a, b, memo, touched, digests=None):
    """記憶があればそれを、無ければ実測して覚える。返り値は体積(mm^3)。

    digests に dict を渡すと、立体のハッシュを id() で使い回す
    （同じ立体を何百組も突き合わせる総当たりで、毎回シリアライズしない）。
    """
    if digests is None:
        digests = {}
    ka = digests.get(id(a)) or digests.setdefault(id(a), shape_digest(a))
    kb = digests.get(id(b)) or digests.setdefault(id(b), shape_digest(b))
    key = "|".join(sorted((ka, kb)))
    touched.add(key)
    if key not in memo:
        memo[key] = intersection_volume(a, b)
    return memo[key]


def assert_no_interference(a, b, label="", tol_mm3=1e-3):
    v = intersection_volume(a, b)
    assert v < tol_mm3, f"{label}干渉している（重なり体積 {v:.3f}mm^3）"


def assert_fits_inside(inner, outer, label="", tol_mm3=1e-3):
    """inner が outer の空洞に収まること（= inner と outer の実体が干渉しない）。"""
    assert_no_interference(inner, outer, label=label, tol_mm3=tol_mm3)


# --------------------------------------------------------------------------
# 検証3-a: 厳密な2D線画（主役）
# --------------------------------------------------------------------------


def _sample_wire(wire, n_per_edge=24):
    """ワイヤを点列に離散化する。曲線も直線も同じ扱いで近似できる。"""
    pts = []
    for edge in wire.edges():
        ts = np.linspace(0.0, 1.0, n_per_edge)
        pts.extend((edge @ float(t)) for t in ts)
    return np.array([[p.X, p.Y, p.Z] for p in pts])


def render_outline_2d(part, out_png, axis="Z", title="", annotate_count=True):
    """指定軸から見た面の輪郭を厳密に描く。

    平板の検証はこれで行う。稜線を実座標から取るため、面の前後関係の
    問題が原理的に起きない。穴が何個あるかも数えて表示する。
    """
    BUILD.mkdir(exist_ok=True)
    ax_map = {"Z": (Axis.Z, 0, 1, "X", "Y"), "Y": (Axis.Y, 0, 2, "X", "Z"),
              "X": (Axis.X, 1, 2, "Y", "Z")}
    sort_axis, i0, i1, xlabel, ylabel = ax_map[axis]

    faces = part.faces().sort_by(sort_axis)
    face = faces[-1]

    fig, ax = plt.subplots(figsize=(12, 6), dpi=160)

    outer = _sample_wire(face.outer_wire())
    ax.plot(outer[:, i0], outer[:, i1], color="black", linewidth=1.4)

    inner_wires = face.inner_wires()
    for w in inner_wires:
        p = _sample_wire(w)
        ax.plot(p[:, i0], p[:, i1], color="#c0392b", linewidth=0.9)

    ax.set_aspect("equal")
    ax.set_xlabel(f"{xlabel} [mm]", fontsize=8)
    ax.set_ylabel(f"{ylabel} [mm]", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.3, alpha=0.4)
    heading = title or f"outline from {axis}"
    if annotate_count:
        heading += f"   ({len(inner_wires)} cutouts)"
    ax.set_title(heading, fontsize=10)
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
    return Path(out_png)


def render_profile(part, out_png, title=""):
    """側面（YZ 断面の外形）を描く。ケースの傾斜や高さの確認用。"""
    return render_outline_2d(part, out_png, axis="X", title=title, annotate_count=False)


# --------------------------------------------------------------------------
# 検証3-b: 陰影付き立体図（補助）
# --------------------------------------------------------------------------


def render_3d(mesh, out_png, views=((28, -60), (90, -90), (0, -90))):
    """全体の姿を掴むための立体図。

    三角形を視線方向の奥行きで並べ替えて描くため、単純な形状なら正しく
    見える。ただし厳密な陰面消去ではないので、穴の多い形状では内壁が
    透けることがある。細部の判定には render_outline_2d を使うこと。
    """
    BUILD.mkdir(exist_ok=True)
    lo, hi = mesh.bounds
    fig = plt.figure(figsize=(4.5 * len(views), 4.5), dpi=140)
    for i, (elev, azim) in enumerate(views, start=1):
        ax = fig.add_subplot(1, len(views), i, projection="3d")

        # 視線方向を求め、その向きの奥行きで三角形を並べ替える（画家のアルゴリズム）
        e, a = np.radians(elev), np.radians(azim)
        view = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
        tris = mesh.triangles
        depth = tris.mean(axis=1) @ view
        order = np.argsort(depth)

        ax.add_collection3d(
            Poly3DCollection(
                tris[order], facecolor="#9fb6d4", edgecolor="#33465e", linewidths=0.05
            )
        )
        ax.set_xlim(lo[0], hi[0])
        ax.set_ylim(lo[1], hi[1])
        ax.set_zlim(lo[2], hi[2])
        ax.set_box_aspect(hi - lo)
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        ax.set_title(f"elev={elev} azim={azim}", fontsize=8)
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
    return Path(out_png)
