"""製造ファイル（ガーバー・ドリル・BOM・CPL）を出す。

**KiCad に同梱の Python で動かす。**

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/\\
        Versions/3.9/bin/python3.9 tools/export_fab.py

**出す前に 2 つの門を通る。**どちらも黙って越えられないようにしてある。

  1. アンテナの risk を承知した記録があること（open-gaps #23）
     基板を 1 回でまとめて発注すると決めた以上、アンテナは組み上げてから
     しか測れない。**承知して出すこと自体は構わないが、黙ってはやらない。**

  2. すべての部品に LCSC の部品番号があること
     JLCPCB に実装まで頼む方針なので、番号が欠けていると発注できない。
     **「あとで埋める」を許すと、発注直前に気づいて止まる。**

出力先は pcb/fab/<基板名>/。JLCPCB の既定の命名に合わせる。
"""

import csv
import re
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from circuit import board_refs, daughterboard_netlist, netlist  # noqa: E402
from parts import NOT_ASSEMBLED, PARTS                          # noqa: E402

OUT = ROOT / "pcb" / "fab"

BOARDS = {
    "hhkb_split_left": lambda: netlist("left"),
    "hhkb_split_right": lambda: netlist("right"),
    "hhkb_split_daughterboard": daughterboard_netlist,
}

LAYERS = [
    (pcbnew.F_Cu, "F_Cu"), (pcbnew.In1_Cu, "In1_Cu"),
    (pcbnew.In2_Cu, "In2_Cu"), (pcbnew.B_Cu, "B_Cu"),
    (pcbnew.F_Paste, "F_Paste"), (pcbnew.B_Paste, "B_Paste"),
    (pcbnew.F_SilkS, "F_Silkscreen"), (pcbnew.B_SilkS, "B_Silkscreen"),
    (pcbnew.F_Mask, "F_Mask"), (pcbnew.B_Mask, "B_Mask"),
    (pcbnew.Edge_Cuts, "Edge_Cuts"),
]


# 回転補正は export_fab_rotation.py にある（pcbnew 抜きで検査するため）。
from export_fab_rotation import (  # noqa: E402
    ROTATION_UNVERIFIED, rotation_for_jlcpcb,
)


def _gate_antenna():
    """アンテナの risk を承知した記録があること。

    ⚠️ **2026-08-11 に、この門が開きっぱなしだったことが分かった。**

    もとは `"### 承知して発注する" in doc` と書いてあった。ところが
    open-gaps.md には**この門を説明する文**が 2 か所あり、そこに
    `「### 承知して発注する」が無い限りガーバーを出さない` と
    書かれている。**門を説明する文そのものが、門を開けていた。**

    承知の節は一度も作られていないのに、`export_fab.py` は通っていた。
    **設定しただけで効いていない**の典型。

    直し方は「行頭から始まる見出しであること」を見る。本文の引用は
    鉤括弧の中にあるので行頭には来ない。
    """
    doc = (ROOT / "docs/hardware/open-gaps.md").read_text()
    if "## 23. ★未解決★ アンテナが地板に挟まれている" not in doc:
        return                                  # 解決済み
    if re.search(r"^### 承知して発注する\s*$", doc, re.M):
        return                                  # 承知の記録がある（見出しとして）
    raise SystemExit(
        "\n★ アンテナの risk を承知した記録が無い ★\n"
        "\n"
        "  子基板のアンテナは上下を地板に挟まれており、チップアンテナの\n"
        "  指針を満たしていない（open-gaps #23）。**発注前に直す手は無い**\n"
        "  （6 案すべて数字で潰した）。基板を 1 回でまとめて発注する以上、\n"
        "  測れるのは組み上げた後になる。\n"
        "\n"
        "  承知して出すなら、open-gaps #23 に「### 承知して発注する」の節を\n"
        "  作り、**誰がいつ承知したか**と、駄目だったときに何を作り直すかを\n"
        "  書いてから、もう一度実行すること。\n")


def _gate_parts():
    """すべての部品に LCSC の番号があること。"""
    need = set()
    for parts in (netlist("left"), netlist("right"), daughterboard_netlist()):
        for _ref, kind, _pins in parts:
            if kind not in NOT_ASSEMBLED:
                need.add(kind)
    unknown = sorted(k for k in need if k not in PARTS)
    if unknown:
        raise SystemExit(
            f"\n★ PARTS に載っていない部品がある: {unknown} ★\n"
            "  tools/export_fab.py の PARTS に足すこと\n")
    missing = sorted(k for k in need if not PARTS[k]["lcsc"])
    if missing:
        raise SystemExit(
            "\n★ LCSC の部品番号が埋まっていない ★\n\n"
            + "\n".join(f"    {k:12s} {PARTS[k]['desc']}" for k in missing)
            + "\n\n"
            "  JLCPCB に実装まで頼む方針なので、番号が無いと発注できない。\n"
            "  在庫ページで現物を確認し、**パッケージが pcb/ の実物と\n"
            "  合っているか**を見てから tools/export_fab.py に書くこと。\n"
            "  型番だけ合っていてもパッケージが違えば実装できない。\n")


def _plot(board, outdir):
    """ガーバーとドリルを出す。"""
    pc = pcbnew.PLOT_CONTROLLER(board)
    po = pc.GetPlotOptions()
    po.SetOutputDirectory(str(outdir))
    po.SetPlotFrameRef(False)
    po.SetAutoScale(False)
    po.SetScale(1)
    po.SetMirror(False)
    po.SetUseGerberProtelExtensions(False)
    po.SetUseGerberX2format(True)
    po.SetIncludeGerberNetlistInfo(True)
    po.SetCreateGerberJobFile(True)
    po.SetSubtractMaskFromSilk(True)
    for layer, name in LAYERS:
        pc.SetLayer(layer)
        pc.OpenPlotfile(name, pcbnew.PLOT_FORMAT_GERBER, name)
        if not pc.PlotLayer():
            raise RuntimeError(f"{name} のプロットに失敗した")
    pc.ClosePlot()

    dw = pcbnew.EXCELLON_WRITER(board)
    dw.SetFormat(True)                      # メートル法
    dw.SetOptions(False, False, pcbnew.VECTOR2I(0, 0), False)
    dw.CreateDrillandMapFilesSet(str(outdir), True, False)


def _cpl(board, outdir, kinds):
    """実装機用の座標表（CPL）。**基板に載る部品だけ。**"""
    rows, unverified = [], set()
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        kind = kinds.get(ref)
        if kind is None or kind in NOT_ASSEMBLED:
            continue
        p = fp.GetPosition()
        bottom = fp.IsFlipped()
        name = fp.GetFPIDAsString().split(":")[-1]
        if any(name.startswith(u) for u in ROTATION_UNVERIFIED):
            unverified.add(name)
        rows.append({
            "Designator": ref,
            "Mid X": f"{pcbnew.ToMM(p.x):.4f}mm",
            "Mid Y": f"{pcbnew.ToMM(p.y):.4f}mm",
            "Layer": "bottom" if bottom else "top",
            "Rotation": f"{rotation_for_jlcpcb(name, fp.GetOrientationDegrees(), bottom):.1f}",
        })
    rows.sort(key=lambda r: r["Designator"])
    for name in sorted(unverified):
        print(f"  ⚠ 回転が未確認: {name}"
              f" — 発注ページの配置プレビューで目視確認すること")
    path = outdir / f"{outdir.name}-cpl.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def _bom(outdir, parts):
    """部品表。同じ種類をまとめる。"""
    groups = {}
    for ref, kind, pins in parts:
        if kind in NOT_ASSEMBLED:
            continue
        for b in board_refs(ref, kind, pins):
            groups.setdefault(kind, []).append(b)
    path = outdir / f"{outdir.name}-bom.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for kind, refs in sorted(groups.items()):
            w.writerow([PARTS[kind]["desc"], ",".join(sorted(refs)),
                        "", PARTS[kind]["lcsc"]])
    return len(groups)


def main():
    _gate_antenna()
    _gate_parts()
    for name, getparts in BOARDS.items():
        src = ROOT / "pcb" / f"{name}.kicad_pcb"
        board = pcbnew.LoadBoard(str(src))
        outdir = OUT / name
        outdir.mkdir(parents=True, exist_ok=True)
        parts = getparts()
        kinds = {b: kind for ref, kind, pins in parts
                 for b in board_refs(ref, kind, pins)}
        _plot(board, outdir)
        n_cpl = _cpl(board, outdir, kinds)
        n_bom = _bom(outdir, parts)
        n_gbr = len(list(outdir.glob("*.g*"))) + len(list(outdir.glob("*.drl")))
        print(f"OK {name}: ガーバー等 {n_gbr} 個 / BOM {n_bom} 行 / CPL {n_cpl} 点")
    print(f"\n→ {OUT}")
    print("\n**発注する前に docs/hardware/fab-checklist.md を開くこと。**")
    print("  部品の向きは機械では確かめられない。配置プレビューで目視確認し、")
    print("  結果を書くまで pytest が落ちる。")


if __name__ == "__main__":
    main()
