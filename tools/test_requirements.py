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
            and m not in OPTIONAL}


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
