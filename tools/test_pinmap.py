"""ピン対応表が、宣言側（circuit）と実物側（フットプリント・基板）の
両方と噛み合っていることを見る。

**この検査が無かったせいで、74LVC595 の 16 パッドと D_PWR の 2 パッドが
ネット無しのまま緑になっていた**（2026-08-12 発見）。DRC も未配線も
何も言わなかった。ネットの付いていないパッドは、繋ぐ相手が居ないので
「未配線」に数えられないため。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pinmap
from circuit import (WIRE_PAD_KINDS, board_refs, daughterboard_netlist,
                     netlist)

ROOT = Path(__file__).resolve().parent.parent
KPY = ("/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/"
       "Versions/3.9/bin/python3.9")

BOARDS = {
    "left": (lambda: netlist("left"), "hhkb_split_left.kicad_pcb"),
    "right": (lambda: netlist("right"), "hhkb_split_right.kicad_pcb"),
    "daughterboard": (daughterboard_netlist, "hhkb_split_daughterboard.kicad_pcb"),
}


def _board_pads(pcb_name):
    """基板上の {参照名: {パッド番号: ネット名}}。**pcbnew は KiCad の Python に
    しか無い**ので別プロセスで読む。"""
    script = (
        "import json,pcbnew;"
        f"b=pcbnew.LoadBoard({str(ROOT / 'pcb' / pcb_name)!r});"
        "print(json.dumps({f.GetReference():"
        "{p.GetNumber():p.GetNetname() for p in f.Pads()}"
        " for f in b.GetFootprints()}))"
    )
    out = subprocess.run([KPY, "-c", script], capture_output=True, text=True,
                         check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def board_pads():
    return {name: _board_pads(pcb) for name, (_, pcb) in BOARDS.items()}


@pytest.mark.parametrize("board", list(BOARDS))
def test_every_declared_pin_is_in_the_pin_map(board):
    """circuit.py が使うピンが全部 pinmap にある。

    足りないと resolve が落ちる。**落ちるのが正しい。**以前は
    gen_pcb が None を握り潰して、そのピンだけ静かに消えていた。
    """
    for ref, kind, pins in BOARDS[board][0]():
        for pin in pins:
            pinmap.resolve(kind, pin)      # 引けなければここで KeyError


@pytest.mark.parametrize("board", list(BOARDS))
def test_the_pin_map_points_at_pads_that_really_exist(board, board_pads):
    """対応表が指すパッド番号が、基板上の実物に存在する。

    **対応表を自分で書いた以上、外の事実と突き合わせないと意味がない**
    （CLAUDE.md「自分の生成物どうしの一致は検証ではない」）。
    フットプリントは KiCad が配っているもので、こちらの生成物ではない。
    """
    actual = board_pads[board]
    missing = []
    for ref, kind, pins in BOARDS[board][0]():
        if kind in WIRE_PAD_KINDS:
            continue                        # ランド 2 個は別の参照名に割れる
        pads = actual.get(ref)
        if pads is None:
            continue                        # 基板に載らない部品は別の検査で見る
        for pin in pins:
            pad = pinmap.resolve(kind, pin)
            if pad is not None and pad not in pads:
                missing.append(f"{board} {ref}({kind}).{pin} → パッド {pad} が無い")
    assert not missing, "\n".join(missing)


@pytest.mark.parametrize("board", list(BOARDS))
def test_no_declared_pin_is_left_without_a_net_on_the_board(board, board_pads):
    """**宣言したネットが、基板のパッドに実際に塗られている。**

    2026-08-12 に見つかった欠陥そのもの。故意に壊して確かめた:
    pinmap の "VCC" の行を消すと resolve が落ち、
    gen_pcb がネットを塗らないようにすると、この検査が 16 件で落ちる。
    """
    actual = board_pads[board]
    holes = []
    for ref, kind, pins in BOARDS[board][0]():
        for pin, want in pins.items():
            if want == "NC":
                continue
            # ランド 2 個の部品は基板上で `BT1_+` のように割れ、
            # それぞれ単独のパッド "1" を持つ（circuit.board_refs）。
            if kind in WIRE_PAD_KINDS:
                board_ref, pad = f"{ref}_{pin}", "1"
            else:
                board_ref, pad = ref, pinmap.resolve(kind, pin)
            if pad is None:
                continue                    # 回路図だけにあるピン（XIAO の BAT）
            pads = actual.get(board_ref)
            if pads is None:
                continue                    # 基板に載らない部品は別の検査で見る
            got = pads.get(pad, "")
            if got != want:
                holes.append(
                    f"{board} {board_ref}.{pin}(パッド{pad}): "
                    f"宣言={want!r} 基板={got!r}")
    assert not holes, (
        "宣言したネットが基板に乗っていない:\n" + "\n".join(holes))
