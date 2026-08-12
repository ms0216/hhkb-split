"""STL を Blender に**開ける状態で**まとめる。ダブルクリックで見えるまでを作る。

export_assembly.py が出した build/assembly/{half}_*.stl を読み込み、
部品ごとに色と透明度を付け、カメラと視点を置いて {half}.blend に保存する。

**Blender を触ったことが無くても使える**ようにするのがこの道具の目的。
開いたら組み上がった状態が色分けで見えている。マウス中ボタンのドラッグで
回る。それ以上の操作は要らない。

使い方（Blender の Python で動かす。母艦の .venv では動かない）:

    .venv/bin/python3 tools/export_assembly.py     # 先に STL を出す
    tools/blend_assembly.sh                        # ← これを叩くだけ

中身は
    /Applications/Blender.app/Contents/MacOS/Blender -b -P tools/blend_assembly.py -- left right

出すもの:
    build/assembly/{half}.blend         Blender で開くファイル
    build/assembly/{half}_blender.png   カメラから見た絵（**検査用**）

PNG は飾りではない。**材質とカメラが本当に効いたかを、開かずに確かめる**
ための証拠。真っ黒・真っ白・空なら、この道具が壊れている。

⚠️ 入っているのはモデルに入っているものだけ（open-gaps #29）。
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

OUT = Path(__file__).resolve().parent.parent / "build" / "assembly"

# **実物の形か、場所取りの箱か。**一覧は gen_assembly.py にある。
# **ここに手書きで持たない。**部品を足すのは gen_assembly なので、
# 分類を別ファイルに置くと片方だけ直る（2026-08-12 に 2 回踏んだ）。
# **gen_assembly からは読めない。**ここは Blender の Python で動くので
# build123d が無く、import した瞬間に落ちて .blend が作られない。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from part_kinds import REAL_SHAPE  # noqa: E402

# 見下ろす向き。export_assembly.py の "iso" と同じ側から見る。
VIEW_DIR = Vector((1.0, -1.0, 0.8)).normalized()


def _clear():
    """既定のキューブ・ライト・カメラを消す。**空から始める。**"""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_stl(path):
    """STL を読む。**インポータの名前は Blender の版で違う**ので両方試す。"""
    before = set(bpy.data.objects)
    try:
        bpy.ops.wm.stl_import(filepath=str(path))       # 4.2 以降
    except AttributeError:
        bpy.ops.import_mesh.stl(filepath=str(path))     # 4.1 以前
    new = set(bpy.data.objects) - before
    if not new:
        raise RuntimeError(f"読み込めなかった: {path}")
    return new.pop()


def _material(name, hex_color, alpha):
    """色と透明度を持つ材質。**Material Preview で見える**ようにする。"""
    r, g, b = (int(hex_color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    bsdf.inputs["Alpha"].default_value = alpha
    bsdf.inputs["Roughness"].default_value = 0.45
    if alpha < 1.0:
        # blend_method の選べる値は版で変わった（4.2 で 'BLEND' が消えた）。
        # **通ったものを使う。**通らなければ不透明のまま（形は見える）。
        for mode in ("BLEND", "HASHED"):
            try:
                mat.blend_method = mode
                break
            except TypeError:
                continue
    # Solid 表示（Blender を開いた既定）でも色が付くように、ここにも入れる。
    mat.diffuse_color = (r, g, b, alpha)
    return mat


def _corners(objects):
    """全部の角の点。囲む箱とカメラの画角の両方に使う。"""
    return [obj.matrix_world @ Vector(c) for obj in objects for c in obj.bound_box]


def _bounds(pts):
    lo = Vector((min(p[i] for p in pts) for i in range(3)))
    hi = Vector((max(p[i] for p in pts) for i in range(3)))
    return (lo + hi) / 2, max(hi - lo)


def _camera(pts, center, size, aspect):
    """平行投影のカメラ。**遠近が付くと寸法を目で比べられない。**

    画角は勘で決めない。**角の点をカメラ座標へ落として実測する。**
    最初は 1.25 倍という当て推量で置いて、右側が切れていた。
    """
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.type = "ORTHO"
    cam_data.clip_start = 1.0
    cam_data.clip_end = size * 20
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.rotation_euler = (-VIEW_DIR).to_track_quat("-Z", "Y").to_euler()
    cam.location = center + VIEW_DIR * size * 3
    bpy.context.view_layer.update()

    # カメラから見た左右上下の広がりを測り、はみ出さない大きさに合わせる。
    inv = cam.matrix_world.inverted()
    local = [inv @ p for p in pts]
    xs = [p.x for p in local]
    ys = [p.y for p in local]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    # ortho_scale は長いほうの辺に掛かる。短辺側の要求を aspect で換算する。
    need = max(max(xs) - min(xs), (max(ys) - min(ys)) * aspect)
    cam_data.ortho_scale = need * 1.06        # 縁の余白
    cam.location += cam.matrix_world.to_3x3() @ Vector((cx, cy, 0))
    bpy.context.scene.camera = cam
    return cam


def _lights(center, size):
    """太陽 1 灯と、影を潰す弱い太陽 1 灯。

    環境光だけだと、**全部の面が同じ明るさになって形が読めない**
    （最初にそうなった）。角度の差を明暗に変えるのが灯りの仕事。
    """
    for name, direction, energy in (
        ("key", Vector((1.0, -0.8, 1.2)), 4.0),
        ("fill", Vector((-1.0, 0.6, 0.4)), 1.2),
    ):
        data = bpy.data.lights.new(name, type="SUN")
        data.energy = energy
        data.angle = math.radians(15)         # 少しぼけた影
        obj = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = center + direction.normalized() * size * 3
        obj.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()


def _world():
    """暗めの背景。**半透明の部品は、背景が明るいと白く飛ぶ。**"""
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.09, 0.10, 0.12, 1)
    bpy.context.scene.world = world


def _viewport(center, size):
    """**開いた瞬間に見えている状態**を仕込む。

    保存された .blend は画面の状態も持つ。材質表示に切り替え、視点を
    部品の位置へ寄せておく。これをやらないと、開いても遠くに点があるだけ。
    """
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                space.shading.type = "MATERIAL"
                space.clip_start = 1.0
                space.clip_end = size * 20
                space.overlay.show_floor = False
                space.overlay.show_axis_x = False
                space.overlay.show_axis_y = False
                space.region_3d.view_location = center
                space.region_3d.view_distance = size * 2.2
                space.region_3d.view_rotation = (-VIEW_DIR).to_track_quat(
                    "-Z", "Y").to_euler().to_quaternion()


def build(half, style):
    _clear()

    scene = bpy.context.scene
    # STL は mm で出ている。Blender の 1 単位を 1mm として読ませる。
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001
    scene.unit_settings.length_unit = "MILLIMETERS"

    objects, materials, collections = [], {}, {}
    for path in sorted(OUT.glob(f"{half}_*.stl")):
        name = path.stem[len(half) + 1:]
        # 種類 = 末尾の番号を落とした名前（export_assembly.style_for と同じ）。
        # 色・材質・コレクションは**種類ごとに 1 つ**。スイッチが 61 個
        # 入っても、材質 61 個・アウトライナ 61 行にはしない。
        kind = name.rstrip("0123456789").rstrip("_") or name
        color, alpha = style.get(name) or style.get(kind) or ("#888888", 0.8)

        obj = _import_stl(path)
        obj.name = name
        if kind not in materials:
            materials[kind] = _material(kind, color, alpha)
        obj.data.materials.append(materials[kind])
        obj.color = tuple(int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5)) + (alpha,)

        # コレクションは**二段**。上が「実形状 / 箱」、下が種類。
        #
        # **名前だけでは、どれが実物の形でどれが場所取りの箱か分からない。**
        # 混ざった絵は、見ても判断の材料にならない（利用者の指摘・2026-08-10）。
        # 上の段の目玉アイコン 1 つで、箱を全部消す／実形状を全部消す、が
        # できるようにする。下の段は従来どおり種類ごと。
        group = "01_real_実形状" if kind in REAL_SHAPE else "02_box_箱"
        if group not in collections:
            collections[group] = bpy.data.collections.new(group)
            bpy.context.scene.collection.children.link(collections[group])
        if kind not in collections:
            collections[kind] = bpy.data.collections.new(kind)
            collections[group].children.link(collections[kind])
        for holder in obj.users_collection:      # STL は scene 直下に入ってくる
            holder.objects.unlink(obj)
        collections[kind].objects.link(obj)
        objects.append(obj)

    if not objects:
        raise RuntimeError(
            f"{half} の STL が無い。先に export_assembly.py を動かすこと")

    scene.render.resolution_x, scene.render.resolution_y = 1400, 900

    pts = _corners(objects)
    center, size = _bounds(pts)
    _camera(pts, center, size,
            scene.render.resolution_x / scene.render.resolution_y)
    _lights(center, size)
    _world()
    _viewport(center, size)

    blend = OUT / f"{half}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))

    # **効いたことを絵で確かめる。**材質もカメラも、保存できただけでは
    # 効いた証拠にならない。
    png = OUT / f"{half}_blender.png"
    scene.render.filepath = str(png)
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)

    return blend, png, len(objects)


def _refuse_if_stale(half):
    """STL が設計より古かったら止める。**古い絵を黙って作らない。**

    2026-08-12 に実際に起きたこと: 利用者が `left.blend` を開いて
    「本当に目で確認したのか」と指摘した。**その .blend は前日 22:27 の
    STL から作られていて、その日の変更が 1 つも入っていなかった。**
    右側に至っては STL 自体が 8 時間前のままで、`.blend` はそれを黙って
    読み込んでいた。

    **絵は「設計を目で確かめる」ための道具**なので、中身が古いと
    検証そのものが嘘になる。設定しただけで効いていない類の失敗と同じ。
    """
    # 比べる相手は「**STL の形を決めうるファイル**」。検査（test_*.py）と
    # この描画スクリプト自身は形を作らないので外す。**外しすぎない**——
    # 迷ったら入れる側（止まりすぎるのは安全側、通しすぎは古い絵になる）。
    tools = Path(__file__).resolve().parent
    src = max(p.stat().st_mtime for p in tools.glob("*.py")
              if not p.name.startswith("test_") and p.name != "blend_assembly.py")
    stls = sorted(OUT.glob(f"{half}_*.stl"))
    if not stls:
        raise SystemExit(f"{half} の STL が無い。先に export_assembly.py を動かすこと")
    old = [p.name for p in stls if p.stat().st_mtime < src]
    if old:
        raise SystemExit(
            f"{half}: STL が tools/*.py より古い（{len(old)}/{len(stls)} 個）。"
            f"例: {old[0]}\n"
            f"  古い絵を作らないために止めた。先に次を動かすこと:\n"
            f"    .venv/bin/python3 tools/export_assembly.py {half}")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    halves = argv or ["left", "right"]

    style_path = OUT / "style.json"
    if not style_path.exists():
        raise SystemExit("style.json が無い。先に export_assembly.py を動かすこと")
    for half in halves:
        _refuse_if_stale(half)
    style = {k: tuple(v) for k, v in json.loads(style_path.read_text()).items()}

    for half in halves:
        blend, png, n = build(half, style)
        print(f"OK {half}: 部品 {n} 個 → {blend.name} / {png.name}")
    print("\n開き方: build/assembly/left.blend をダブルクリック。"
          "回すのはマウス中ボタンのドラッグ。")


if __name__ == "__main__":
    main()
