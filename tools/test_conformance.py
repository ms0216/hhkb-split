"""**宣言した回路と、実際の基板が一致していること**を検査する。

tools/circuit.py に回路を宣言しても、基板がそれに従っているかを誰も
照合しなければ意味がない。部品を置き忘れても、ネットを繋ぎ違えても、
どちらの側も単独では正しく見える。

**未実装のものは PENDING に書く。** 書かずに黙って欠けていると、
「検査に通った」が「まだ作っていない」の同義語になる。実装したら
PENDING から消す。消し忘れれば、この検査が落ちる。
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import board_refs, netlist  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# まだ基板に載せていない部品。**ここが減っていくことが進捗そのもの。**
# 電源部はケース内寸（スイッチに手が届く位置）が決まってから置く。
# **全部載った。**空になったので、あとは配線が終われば発注できる。
PENDING = set()


def board_parts(half):
    """基板に載っているフットプリントの参照名。"""
    txt = (ROOT / f"pcb/hhkb_split_{half}.kicad_pcb").read_text()
    return set(re.findall(r'\(property "Reference" "([^"]+)"', txt))


def board_nets(half):
    """基板に張られているネット名。"""
    txt = (ROOT / f"pcb/hhkb_split_{half}.kicad_pcb").read_text()
    return {n for n in re.findall(r'\(net (?:\d+ )?"([^"]*)"\)', txt) if n}


@pytest.mark.parametrize("half", ["left", "right"])
def test_every_declared_part_is_on_the_board_or_listed_as_pending(half):
    """宣言した部品が、基板にあるか PENDING に書いてあるかのどちらかであること。"""
    # **基板上の名前で比べる。**リード線で繋ぐ部品（電池・電源スイッチ）は
    # ランド 2 個に分かれるので、宣言側を circuit.board_refs で展開する。
    declared = {b for ref, kind, pins in netlist(half)
                for b in board_refs(ref, kind, pins)}
    on_board = {r
                for r in board_parts(half)}
    missing = declared - on_board - PENDING
    assert not missing, (
        f"{half}: 宣言したのに基板に無く、PENDING にも書いていない部品:\n  "
        + "\n  ".join(sorted(missing)))


@pytest.mark.parametrize("half", ["left", "right"])
def test_nothing_on_the_board_is_undeclared(half):
    """基板にあるのに回路に宣言されていない部品が無いこと。

    こちら向きも要る。基板だけに部品を足すと、回路の検査（パスコンの数など）
    をすり抜ける。
    """
    declared = {b for ref, kind, pins in netlist(half)
                for b in board_refs(ref, kind, pins)}
    extra = {r
             for r in board_parts(half)
             if not r.startswith(("H", "ST"))} - declared
    assert not extra, f"{half}: 基板にあるが回路に宣言が無い部品 {sorted(extra)}"


@pytest.mark.parametrize("half", ["left", "right"])
def test_pending_parts_are_actually_still_missing(half):
    """PENDING に書いたものが、本当にまだ載っていないこと。

    **消し忘れを防ぐ。** 実装したのに PENDING に残っていると、
    以後その部品は検査されない。
    """
    stale = PENDING & board_parts(half)
    assert not stale, (
        f"{half}: 基板に載ったのに PENDING に残っている {sorted(stale)}。"
        f"PENDING から消すこと")


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_matrix_nets_match_the_declaration(half):
    """行・列・スイッチのネットが、宣言どおり基板に存在すること。

    ここは実装済みなので、名前が 1 つでも欠けたら落ちる。
    """
    declared = set()
    for ref, _, pins in netlist(half):
        if ref.startswith(("SW", "D")) and ref not in PENDING:
            declared |= {n for n in pins.values() if n != "NC"}
    missing = declared - board_nets(half)
    assert not missing, f"{half}: 宣言にあるが基板に無いネット {sorted(missing)[:10]}"


def test_the_pending_list_shrinks_to_nothing_before_ordering():  # noqa: D401
    """発注前に PENDING が空でなければならないことを、明文で残す。

    このテストは今は通る（残件があることを許す）。**発注の直前に
    PENDING を空にすること**が条件で、それを忘れないための場所。
    """
    assert not PENDING, f"まだ基板に載っていない部品がある: {sorted(PENDING)}"
