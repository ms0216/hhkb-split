# Blender: 案 R（RKJXV122400R）を撮る
import bpy, sys
from mathutils import Vector
half, out = sys.argv[sys.argv.index("--") + 1:][:2]
objs = [o for o in bpy.data.objects if o.type == "MESH"]
names = {o.name for o in objs}
boxes = {o.name for c in bpy.data.collections if c.name.startswith("02_box") for o in c.all_objects}
k = [o for o in objs if o.name in ("joystick", "joystick_cap")]
has_tilt = "joystick_tilt" in names
kp = [o.matrix_world @ Vector(q) for o in k for q in o.bound_box]
c1 = sum(kp, Vector()) / len(kp)
a = [o for o in objs if o.name.startswith("joystick") or o.name.startswith("pod_")]
ap = [o.matrix_world @ Vector(q) for o in a for q in o.bound_box]
c2 = sum(ap, Vector()) / len(ap)
cam = bpy.context.scene.camera
cam.data.type = "ORTHO"
sc = bpy.context.scene
sc.render.resolution_x, sc.render.resolution_y = 1400, 1100
def shot(name, c, d, scale, only=None, show=()):
    for o in objs:
        o.hide_render = (o.name in boxes and o.name not in show) if only is None else o.name not in only
    d = Vector(d).normalized()
    cam.location = c + d * 300
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    if name == "top": cam.rotation_euler = (0, 0, 0)
    cam.data.ortho_scale = scale
    sc.render.filepath = f"{out}/{half}_r_{name}.png"
    bpy.ops.render.render(write_still=True)
sx = -1 if half == "right" else 1
J = [n for n in ("joystick", "joystick_cap", "joystick_tilt", "joystick_seat", "joystick_collar", "joystick_wire", "pod_mcu", "pod_board") if n in names]
shot("keys", c1, (sx * 0.7, -1, 0.8), 85, show=("keycaps",))                 # キーキャップつきの外観
shot("tilt", c1, (sx * 0.2, -1, 0.25), 70, show=("keycaps",))
shot("nocollar", c1, (sx * 0.7, -1, 0.8), 60, only=[n for n in names if n not in boxes and n not in ("joystick_collar", "topcase", "joystick_tilt")])                # 倒した姿を横から
shot("top", c1, (0, 0, 1), 70, show=("keycaps",))
shot("cut", c1, (sx * 0.7, -1, 0.9), 70, only=[n for n in J if n not in ("joystick_tilt", "joystick_collar")] + ["plate", "pcb_real"])
shot("section", c1, (0, -1, 0.03), 60, only=[n for n in J if n != "joystick_tilt"] + ["plate", "pcb_real"])
J = [n for n in J if n in names]
shot("inside", c2, (sx * 0.5, -1, 1.3), 150, only=[n for n in J if n not in ("joystick_tilt", "joystick_collar")] + ["case"])
shot("under", c1, (sx * 0.5, -0.6, -1), 60, only=[n for n in J if n != "joystick_tilt"] + ["plate"])   # 受け皿を下から（主基板なし）
# 線の道: 主基板・子基板（XIAO とソケット）・帯・線だけを、奥の上から
RT = [n for n in ("joystick", "joystick_seat", "joystick_wire", "pod_board", "pod_mcu", "pcb_real", "db_real") if n in names]
if "joystick_wire" in names:
    w_ = [o for o in objs if o.name == "joystick_wire"][0]
    wp = [w_.matrix_world @ Vector(q) for q in w_.bound_box]; cw_ = sum(wp, Vector()) / 8
    shot("route", cw_, (-sx * 0.35, 1, 0.9), 150 if half == "right" else 80, only=RT)
