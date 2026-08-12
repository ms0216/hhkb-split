"""回路図（circuit.py 由来）と、実際の基板が食い違っていないことを見る。

**この検査が無かったせいで、74LVC595 の 16 パッドと D_PWR の 2 パッドが
ネット無しのまま基板になっていた**（open-gaps #37）。
DRC も未配線カウントも、この欠陥に対して完全に無力だった。

やっていること
--------------
    circuit.py ──→ .kicad_sch ──(kicad-cli)──→ netlist  ┐
                                                        ├─ 突き合わせる
    gen_pcb.py ──→ .kicad_pcb ──(pcbnew)────→ netlist   ┘

**どちらも固定ファイルと比べない。**毎回両方から実際に抽出する。
固定ファイルは古くなっても誰も気づけない。

**回路図側の解釈は KiCad 自身にさせる。**自分が書いた s 式を自分で
解釈しても、KiCad がどう読むかの証拠にはならない。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_sch                                                   # noqa: E402
import pinmap                                                    # noqa: E402
# 参照名の割り方は gen_sch.expanded に集約した

ROOT = Path(__file__).resolve().parent.parent
KPY = ("/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/"
       "Versions/3.9/bin/python3.9")
KICAD_CLI = gen_sch.KICAD_CLI

PROJECTS = ["hhkb_split_left", "hhkb_split_right", "hhkb_split_daughterboard"]

# KiCad は繋がっていないピンに `unconnected-(U1-Pad9)` という名前を振る。
# **ネットが無いことと同じ意味**なので、比較の前に落とす。
UNCONNECTED = re.compile(r"unconnected-\(.*\)")


def _pcb_netlist(project):
    """基板の {参照名: {パッド番号: ネット名}}。pcbnew は KiCad の Python にしか無い。"""
    pcb = ROOT / "pcb" / f"{project}.kicad_pcb"
    script = (
        "import json,pcbnew;"
        f"b=pcbnew.LoadBoard({str(pcb)!r});"
        "print(json.dumps({f.GetReference():"
        "{p.GetNumber():p.GetNetname() for p in f.Pads()}"
        " for f in b.GetFootprints()}))"
    )
    out = subprocess.run([KPY, "-c", script], capture_output=True, text=True,
                         check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    """(回路図 netlist, 基板 netlist) を 3 基板ぶん。"""
    d = tmp_path_factory.mktemp("sch")
    out = {}
    for p in PROJECTS:
        sch = gen_sch.write(p, d / f"{p}.kicad_sch")
        out[p] = (gen_sch.netlist_from_sch(sch), _pcb_netlist(p))
    return out


@pytest.mark.parametrize("project", PROJECTS)
def test_the_schematic_can_be_read_by_kicad(pair, project):
    """KiCad が回路図を読めて、ネットを取り出せる。

    **書き出せたことは、読めることの証拠にならない。**kiutils で
    書いたものは KiCad 10 に撥ねられた（「回路図の読み込みに失敗しました」）。
    """
    sch, _ = pair[project]
    assert sch, f"{project}: 回路図から 1 つもネットが取れていない"


@pytest.mark.parametrize("project", PROJECTS)
def test_the_schematic_and_the_board_agree_on_every_pin(pair, project):
    """**回路図と基板が、全ピンで同じネットを持っている。**

    故意に壊して確かめた: pinmap の 74LVC595 の "VCC" を "15" に変えると
    この検査が落ちる（回路図はパッド 15、基板もパッド 15 になるが、
    Q0 と衝突して別の食い違いが出る）。gen_pcb 側だけネットを塗らない
    ようにすると 16 件で落ちる。
    """
    sch, pcb = pair[project]
    # **回路図と同じ「割った姿」で回す。**割ったあとは回路図の参照名と
    # 基板の参照名が 1 対 1 になる（BT1_+ / BT1_-）。
    parts = gen_sch.expanded(gen_sch.SHEETS[project]())

    mismatch = []
    for ref, kind, pins in parts:
        for pin, want in pins.items():
            pad = pinmap.resolve(kind, pin)
            if pad is None:
                continue                    # 回路図にしか無いピン（XIAO の BAT）
            got_sch = sch.get(ref, {}).get(pad, "")
            got_pcb = pcb.get(ref, {}).get(pad, "")
            if UNCONNECTED.fullmatch(got_sch):
                got_sch = ""
            if want == "NC":
                want = ""
            if got_sch != want or got_pcb != want:
                mismatch.append(
                    f"  {ref}.{pin}(パッド{pad}): "
                    f"宣言={want!r} 回路図={got_sch!r} 基板={got_pcb!r}")

    assert not mismatch, (
        f"{project}: 回路図と基板が食い違う {len(mismatch)} 件\n"
        + "\n".join(mismatch[:40])
        + ("\n  ..." if len(mismatch) > 40 else ""))


@pytest.mark.parametrize("project", PROJECTS)
def test_the_schematic_passes_erc(project, tmp_path):
    """**ERC が通る。**回路図を作った目的の半分がこれ。

    ERC は電気的種別（power_in / output / …）を見て、
    「電源入力がどこからも駆動されていない」「出力どうしがぶつかっている」
    を見つける。**種別を書かないと ERC はただ通るだけの飾りになる**ので、
    pinmap.py に種別まで持たせてある。
    """
    sch = gen_sch.write(project, tmp_path / f"{project}.kicad_sch")
    rpt = tmp_path / "erc.json"
    subprocess.run(
        [KICAD_CLI, "sch", "erc", "--format", "json", "-o", str(rpt),
         "--severity-error", str(sch)],
        capture_output=True, text=True)
    data = json.loads(rpt.read_text())
    errors = [v for sheet in data.get("sheets", [])
              for v in sheet.get("violations", [])
              if v.get("severity") == "error"]
    assert not errors, (
        f"{project}: ERC のエラー {len(errors)} 件\n"
        + "\n".join(f"  {v.get('type')}: {v.get('description')}"
                    for v in errors[:20]))
