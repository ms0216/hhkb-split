"""CI の依存が、実際に使っているものと一致することを守る。

**requirements を手で並べたせいで matplotlib が抜け、CI だけが落ちた。**
ローカルには入っていたので、手元では最後まで気づけなかった。
「テストが通る」と「CI で通る」は別の話。

ここは tools/ が実際に import している外部モジュールを走査し、
requirements-dev.txt がそれを網羅しているかを見る。
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
REQ = ROOT / "requirements-dev.txt"

# import 名 → 配布名（一致しないものだけ）
DIST = {"PIL": "pillow", "yaml": "PyYAML", "mpl_toolkits": "matplotlib"}
# KiCad 同梱の Python でしか使わないもの（CI には入れない）
KICAD_ONLY = {"pcbnew"}
# Blender 同梱の Python でしか使わないもの（pip では入らない）
BLENDER_ONLY = {"bpy", "mathutils"}
# 任意（入っていなくても検証は通る）
OPTIONAL = {"pyvista"}
# **listed している依存が連れてくるもの。**自分で pip に書かない。
#   OCP … build123d の実体（cadquery-ocp-novtk）。verify.shape_digest が
#         BinTools でシリアライズするのに直接触る。**別に固定すると、
#         build123d が決めた版と食い違ったときに壊れる。**
# ここに足すときは「listed のどれが連れてくるか」を必ず書くこと。
BUNDLED = {"OCP"}


def external_imports():
    std = set(sys.stdlib_module_names)
    local = {p.stem for p in TOOLS.glob("*.py")}
    mods = set()
    for f in TOOLS.rglob("*.py"):
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods.add(n.module.split(".")[0])
    return {m for m in mods if m not in std and m not in local
            and m not in KICAD_ONLY and m not in BLENDER_ONLY
            and m not in OPTIONAL and m not in BUNDLED}


def listed():
    return {line.split("==")[0].strip().lower()
            for line in REQ.read_text().splitlines()
            if line.strip() and not line.startswith("#")}


def test_every_import_is_listed_in_requirements():
    """使っているモジュールが漏れなく requirements にあること。"""
    have = listed()
    missing = sorted(m for m in external_imports()
                     if DIST.get(m, m).lower() not in have)
    assert not missing, f"requirements-dev.txt に無い: {missing}"


def test_the_bundled_modules_really_come_with_the_listed_ones():
    """**BUNDLED に逃がしたものが、本当に入っていること。**

    `BUNDLED` は「pip に書かないが使う」という抜け道なので、放っておくと
    「実は入っていない」を隠す穴になる。上流が同梱をやめたらここで落ちる。
    """
    import importlib.metadata as md

    bad = []
    for m in sorted(BUNDLED):
        dists = md.packages_distributions().get(m)
        if not dists:
            bad.append(f"{m}: import できない（どの配布も提供していない）")
    # 連れてくる側が requirements にある配布であること……までは辿れない
    # （pip は逆引きの依存を持たない）ので、**実在すること**を見る。
    assert not bad, "BUNDLED が実在しない:\n  " + "\n  ".join(bad)


def test_the_pinned_versions_match_the_environment():
    """固定したバージョンが、いま動かしている環境と一致すること。

    ずれていると「手元では通るが CI では通らない」が起きる。
    """
    import importlib.metadata as md
    bad = []
    for line in REQ.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, ver = line.split("==")
        try:
            got = md.version(name.strip())
        except Exception:
            bad.append(f"{name}: 環境に入っていない")
            continue
        if got != ver.strip():
            bad.append(f"{name}: 記載 {ver.strip()} / 実際 {got}")
    assert not bad, "requirements と環境がずれている:\n  " + "\n  ".join(bad)


def test_mesh_contains_works_which_needs_rtree():
    """**rtree が、コメントだけでなく検査で守られていること。**

    `rtree` は import 名で出てこない（trimesh が `mesh.contains()` の
    空間索引に使う transitive 依存）ので、上の AST 走査には見えない。
    **requirements-dev.txt の行を消しても全部緑になる**——matplotlib で
    2 回踏んだ轍と同じ形。

    ここは「入っているか」ではなく **`contains()` が実際に答えを出すか**を
    見る。無いと trimesh は例外を投げるか、黙って全部 False を返す。
    それは `test_assembly.py` の「電源スイッチの受けが中空か」
    （301 行・1697 行）が**静かに嘘になる**ということ。

    故意に外して確認済み（2026-08-13）:
      - `pip uninstall -y rtree` → ここと pinned_versions の 2 件が赤
      - **requirements-dev.txt の `rtree==` 行を消す** → **ここだけが赤。**
        他の 4 件は緑（記載が無いので突き合わせる相手も無い）。
        **これが matplotlib で 2 回踏んだ穴そのもの。**
    """
    import numpy as np
    import trimesh

    # 一辺 2 の立方体。中心は中、遠くの点は外。**答えが分かっている形。**
    box = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    got = box.contains(np.array([[0.0, 0.0, 0.0], [5.0, 5.0, 5.0]]))
    assert list(got) == [True, False], (
        f"mesh.contains() が中と外を見分けられない（得た値: {list(got)}）。"
        "rtree が入っていない可能性が高い——requirements-dev.txt を見ること")


def test_ci_installs_the_kicad_that_wrote_the_board_files():
    """CI が入れる KiCad の版が、基板ファイルを書いた版と一致すること。

    **これが無い間、実形状のジョブは一度も検査に到達していなかった。**
    CI は `ppa:kicad/kicad-9.0-releases` を入れていて、基板ファイルは
    KiCad 10 の書式（`(version 20260206)`）。9.0 の kicad-cli は読めずに
    終了コード 3 で落ち、5 件が真っ赤になる。**赤の中身は実形状の指摘
    ではなく、環境の不一致だった**（2026-08-10 に判明）。

    KiCad を上げたら基板ファイルの generator_version も上がるので、
    片方だけ動かすとここで落ちる。
    """
    import re

    wf = (ROOT / ".github" / "workflows" / "checks.yml").read_text()
    m = re.search(r"ppa:kicad/kicad-([\d.]+)-releases", wf)
    assert m, "checks.yml に KiCad の PPA が見当たらない"
    ci = m.group(1)                                  # 例 "10.0"

    for pcb in sorted((ROOT / "pcb").glob("*.kicad_pcb")):
        g = re.search(r'\(generator_version "([\d.]+)"\)', pcb.read_text())
        assert g, f"{pcb.name}: generator_version が無い"
        assert g.group(1) == ci, (
            f"{pcb.name} は KiCad {g.group(1)} が書いたのに、CI は "
            f"KiCad {ci} を入れている。kicad-cli が基板を読めず、実形状の"
            "検査は一度も走らない")
