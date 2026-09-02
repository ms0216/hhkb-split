"""**実際の発注に使う道具（Fabrication Toolkit）が読むものを板に焼き込む。**

（2026-09-02）

発注は `tools/export_fab.py` ではなく、KiCad のプラグイン
**Fabrication Toolkit（bennymeg/JLC-Plugin-for-KiCad）**で行う運用
（open-gaps #52）。そのプラグインを本番の板 3 枚に**実際に通してみた**ら、
こちらの `export_fab.py` では直したはずの誤りが**そのまま出ていた**:

    1. BOM の「LCSC Part #」が **全行空**（部品の番号はこの
       リポジトリの `parts.py` にしか無く、板には書かれていなかった）
    2. CPL がホットスワップソケット 61 個を **top** と書く
       （プラグインは `fp.GetLayer()` で面を決める。fab-checklist §1b と
       同じ穴。上流 perigoso のフットプリントは F.Cu に置いて
       パッドを B.Cu に持つ）
    3. XIAO（U_MCU）が BOM と CPL に**載っている**（利用者がピンソケットで
       着脱式に載せる部品。JLCPCB に実装させない）

プラグインはフットプリントのフィールドを読む:

    LCSC               → BOM の「LCSC Part #」
    FT Layer Override  → CPL の Layer（`bottom` / `top`）

属性 `FP_EXCLUDE_FROM_BOM | FP_EXCLUDE_FROM_POS_FILES` で BOM/CPL から外す。

**ここでは板に書くだけ。何を書くかは `parts.py` / `circuit.py` が決める。**
`finalize_pcb.py`（左右）と `gen_daughterboard.py`（子基板）が保存の
直前に呼ぶ。本番の板に単独で当て直すこともできる（冪等）:

    "$KPY" tools/fab_fields.py            # pcb/ の 3 枚
"""
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from circuit import board_refs, daughterboard_netlist, netlist   # noqa: E402
from parts import NOT_ASSEMBLED, PARTS                            # noqa: E402

LCSC_FIELD = "LCSC"
LAYER_FIELD = "FT Layer Override"
EXCLUDE = pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES


def kinds_of(half):
    parts = daughterboard_netlist() if half == "daughterboard" else netlist(half)
    return {b: kind for ref, kind, pins in parts for b in board_refs(ref, kind, pins)}


def solder_side(fp):
    """はんだ付けする面。**置いた面（GetLayer）ではなくパッドの銅箔で決める。**"""
    smd = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
    if not smd:
        return "bottom" if fp.IsFlipped() else "top"
    return "bottom" if all(p.IsOnLayer(pcbnew.B_Cu) for p in smd) else "top"


def _set_hidden(fp, name, value):
    fp.SetField(name, value)
    f = fp.GetField(name)
    f.SetVisible(False)
    f.SetLayer(pcbnew.B_Fab if fp.IsFlipped() else pcbnew.F_Fab)


def stamp(board, half):
    """フィールドと属性を焼き込む。戻り値は (LCSC を書いた数, 面を上書きした数, 除外した数)。"""
    kinds = kinds_of(half)
    n_lcsc = n_layer = n_excl = 0
    for fp in board.GetFootprints():
        kind = kinds.get(fp.GetReference())
        if kind is None:
            continue                         # スタビ・取付穴（回路に無い）
        if kind in NOT_ASSEMBLED:
            fp.SetAttributes(fp.GetAttributes() | EXCLUDE)
            n_excl += 1
            continue
        _set_hidden(fp, LCSC_FIELD, PARTS[kind]["lcsc"])
        n_lcsc += 1
        placed = "bottom" if fp.IsFlipped() else "top"
        side = solder_side(fp)
        if side != placed:
            _set_hidden(fp, LAYER_FIELD, side)
            n_layer += 1
        elif fp.HasField(LAYER_FIELD):
            fp.RemoveField(LAYER_FIELD)
    return n_lcsc, n_layer, n_excl


def main():
    for half in ("left", "right", "daughterboard"):
        path = ROOT / "pcb" / f"hhkb_split_{half}.kicad_pcb"
        board = pcbnew.LoadBoard(str(path))
        n = stamp(board, half)
        board.Save(str(path))
        print(f"   {half}: LCSC {n[0]} / 面の上書き {n[1]} / BOM・CPL から除外 {n[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
