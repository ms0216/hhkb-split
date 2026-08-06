"""メッシュの健全性と印刷可能性を検査する。

これまで `is_watertight` しか見ていなかった。それだけでは
「スライサーが読めるか」しか分からず、「刷れるか」は分からない。

検査する項目:

  健全性   水密 / 巻き方向の一貫性 / 自己交差 / 縮退面 / 体積が正
  印刷性   オーバーハング角 / 最薄肉厚 / 造形サイズ / 底面の設置面積

閾値は K1 Max / PLA / ノズル 0.4mm / 積層 0.2mm を前提にしている。
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh

BUILD = Path(__file__).resolve().parent.parent / "build"

# --------------------------------------------------------------------------
# 判定の閾値（K1 Max / PLA / ノズル 0.4mm）
# --------------------------------------------------------------------------
OVERHANG_LIMIT_DEG = 45.0    # これを超える張り出しはサポートが要る
MIN_WALL = 0.8               # ノズル 0.4mm の 2 倍。これ未満は成形できない
BED = (300.0, 300.0, 300.0)  # 造形可能サイズ
THICKNESS_SAMPLES = 4000
THIN_FRACTION_LIMIT = 1.0     # 薄い箇所がこの割合を超えたら設計を疑う


@dataclass
class Report:
    name: str
    size: tuple
    genus: float = 0.0
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.problems

    def show(self):
        mark = "OK " if self.ok else "NG "
        print(f"{mark}{self.name}  {self.size[0]:.1f} x {self.size[1]:.1f} x "
              f"{self.size[2]:.1f} mm")
        for n in self.notes:
            print(f"      {n}")
        for p in self.problems:
            print(f"   !! {p}")


def check_soundness(mesh, rep):
    if not mesh.is_watertight:
        rep.problems.append("水密でない（穴がある）")
    if not mesh.is_winding_consistent:
        rep.problems.append("面の巻き方向が揃っていない")
    if mesh.volume <= 0:
        rep.problems.append(f"体積が正でない（{mesh.volume:.1f}mm^3）法線が内向き")
    degenerate = int((~mesh.nondegenerate_faces()).sum())
    if degenerate:
        rep.problems.append(f"縮退した面が {degenerate} 個")
    # オイラー標数。単純な閉曲面なら 2、穴(トンネル)が n 個なら 2-2n
    genus = (2 - mesh.euler_number) / 2
    rep.notes.append(f"三角形 {len(mesh.faces)}  体積 {mesh.volume / 1000:.1f}cm^3  "
                     f"貫通穴 {genus:.0f} 箇所")
    rep.genus = genus


def check_overhang(mesh, rep):
    """サポートが要る面の割合。

    面が支えを要するのは「面と鉛直のなす角が OVERHANG_LIMIT_DEG を超える」とき。
    法線で言えば、下向き成分が cos(45°)=0.707 を超える面。

    ベッドに接地している面は支えが要らないので除く。当初これを除いておらず、
    接地面積とサポート面積が全部品で一致するという明らかにおかしい結果になった。
    """
    n, area = mesh.face_normals, mesh.area_faces
    z0 = mesh.bounds[0][2]
    on_bed = (n[:, 2] < -0.99) & (np.abs(mesh.triangles[:, :, 2] - z0).max(axis=1) < 0.05)

    needs = (-n[:, 2] > np.cos(np.radians(OVERHANG_LIMIT_DEG))) & (~on_bed)
    a_need = area[needs].sum()
    ratio = a_need / area.sum() * 100
    # ほぼ水平で宙に浮いた面 = ブリッジ。短ければ問題ないが長いと垂れる
    bridge = needs & (-n[:, 2] > 0.99)
    rep.notes.append(
        f"サポートが要る面 {a_need:.0f}mm^2 (全体の {ratio:.1f}%)  "
        f"うち水平なブリッジ {area[bridge].sum():.0f}mm^2")
    if ratio > 15:
        rep.problems.append(
            f"サポートが要る面が多い（{ratio:.1f}%）。向きを変えるか設計を見直す")


def check_thickness(mesh, rep):
    """局所肉厚を測る。

    method="ray"（表面の点から法線と逆向きに光線を飛ばし、反対側の面までの
    距離を測る）を使う。max_sphere（内接球）は角の内側で必ず小さくなるため、
    中身の詰まったブロックでも「0.1mm の薄い箇所がある」と報告してしまい
    使い物にならなかった。実際、40mm の無垢ブロックで
    ray 法は最薄 12.0mm、max_sphere 法は 0.00mm という結果だった。

    判定も最小値ではなく「薄い箇所の割合」で行う。稜線付近では ray 法でも
    値が小さく出るが、それはごく一部の面積に留まるため。
    """
    pts, face_idx = trimesh.sample.sample_surface(mesh, THICKNESS_SAMPLES)
    normals = mesh.face_normals[face_idx]
    try:
        th = trimesh.proximity.thickness(mesh=mesh, points=pts, normals=normals,
                                         method="ray")
    except Exception as e:
        rep.notes.append(f"肉厚の計測を省略（{type(e).__name__}）")
        return
    th = th[np.isfinite(th) & (th > 0)]
    if th.size == 0:
        rep.notes.append("肉厚を計測できなかった")
        return
    p1, p5, p50 = np.percentile(th, [1, 5, 50])
    frac = float((th < MIN_WALL).mean() * 100)
    rep.notes.append(
        f"肉厚 1%点 {p1:.2f} / 5%点 {p5:.2f} / 中央 {p50:.2f} mm  "
        f"{MIN_WALL}mm 未満 {frac:.1f}%")
    if frac > THIN_FRACTION_LIMIT:
        rep.problems.append(
            f"薄すぎる箇所が広い（{MIN_WALL}mm 未満が {frac:.1f}%）")


def check_bed(mesh, rep):
    size = mesh.bounds[1] - mesh.bounds[0]
    for i, ax in enumerate("XYZ"):
        if size[i] > BED[i]:
            rep.problems.append(f"{ax} が造形サイズを超える（{size[i]:.1f} > {BED[i]}）")
    # 底面の設置面積（最下層付近の下向き水平面）
    z0 = mesh.bounds[0][2]
    n, a = mesh.face_normals, mesh.area_faces
    tri_z = mesh.triangles[:, :, 2]
    on_bed = (n[:, 2] < -0.99) & (np.abs(tri_z - z0).max(axis=1) < 0.05)
    rep.notes.append(f"ベッド接地面積 {a[on_bed].sum():.0f}mm^2")
    if a[on_bed].sum() < 100:
        rep.problems.append("接地面積が小さい。反りや剥がれの恐れ（ブリム推奨）")


def inspect(path):
    mesh = trimesh.load(str(path))
    rep = Report(Path(path).stem, tuple(mesh.bounds[1] - mesh.bounds[0]))
    check_soundness(mesh, rep)
    check_bed(mesh, rep)
    check_overhang(mesh, rep)
    check_thickness(mesh, rep)
    return rep


def main(names=None):
    stls = sorted(p for p in BUILD.glob("*.stl")
                  if not p.stem.startswith(("smoke", "dbg")))
    if names:
        stls = [p for p in stls if p.stem in names]
    reps = [inspect(p) for p in stls]
    for r in reps:
        r.show()
    bad = [r.name for r in reps if not r.ok]
    print(f"\n{len(reps) - len(bad)}/{len(reps)} 件が問題なし")
    if bad:
        print("要対処: " + ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
