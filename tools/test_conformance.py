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
from circuit import board_refs, mechanical_refs, netlist  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# まだ基板に載せていない部品。**ここが減っていくことが進捗そのもの。**
# 電源部はケース内寸（スイッチに手が届く位置）が決まってから置く。
# **全部載った。**空になったので、あとは配線が終われば発注できる。
PENDING = set()


def board_parts(half):
    """基板に載っているフットプリントの参照名。"""
    txt = (ROOT / f"pcb/hhkb_split_{half}.kicad_pcb").read_text()
    return set(re.findall(r'\(property "Reference" "([^"]+)"', txt))


def expected_parts(half):
    """基板に載っているべき参照名の**全体**。

    電気部品（circuit.netlist）と機械部品（circuit.mechanical_refs）の和。
    **どちらの向きの検査もこの 1 つの集合で照合する。**片方だけ接頭辞で
    除外していると、その接頭辞を名乗るものが何でも素通りする。
    """
    return ({b for ref, kind, pins in netlist(half)
             for b in board_refs(ref, kind, pins)}
            | mechanical_refs(half))


def board_nets(half):
    """基板に張られているネット名。"""
    txt = (ROOT / f"pcb/hhkb_split_{half}.kicad_pcb").read_text()
    return {n for n in re.findall(r'\(net (?:\d+ )?"([^"]*)"\)', txt) if n}


@pytest.mark.parametrize("half", ["left", "right"])
def test_every_declared_part_is_on_the_board_or_listed_as_pending(half):
    """宣言した部品が、基板にあるか PENDING に書いてあるかのどちらかであること。

    スタビライザも見る。**以前は接頭辞で除外していたので、1 個欠けても
    誰も気づかなかった。**
    """
    # **基板上の名前で比べる。**リード線で繋ぐ部品（電池・電源スイッチ）は
    # ランド 2 個に分かれるので、宣言側を circuit.board_refs で展開する。
    missing = expected_parts(half) - board_parts(half) - PENDING
    assert not missing, (
        f"{half}: 宣言したのに基板に無く、PENDING にも書いていない部品:\n  "
        + "\n  ".join(sorted(missing)))


@pytest.mark.parametrize("half", ["left", "right"])
def test_nothing_on_the_board_is_undeclared(half):
    """基板にあるのに宣言されていない部品が無いこと。

    こちら向きも要る。基板だけに部品を足すと、回路の検査（パスコンの数など）
    をすり抜ける。

    **接頭辞で除外しない。**以前は `startswith(("H", "ST"))` を素通りさせて
    いたので、`HACK_ROGUE` を置いても検出できなかった（実際に確かめた）。
    機械部品は circuit.mechanical_refs が名前で宣言する。
    """
    extra = board_parts(half) - expected_parts(half)
    assert not extra, f"{half}: 基板にあるが宣言が無い部品 {sorted(extra)}"


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
    # **種類で選ぶ。参照名の接頭辞で選ばない。**`("SW", "D")` で拾うと
    # 電源スイッチ SW_PWR_1/2 とショットキー D_PWR まで巻き込む。
    # CLAUDE.md が名指しで禁じている型で、この案件で 5 回起きている。
    declared = set()
    for ref, kind, pins in netlist(half):
        if kind in ("keyswitch", "diode") and ref not in PENDING:
            declared |= {n for n in pins.values() if n != "NC"}
    missing = declared - board_nets(half)
    assert not missing, f"{half}: 宣言にあるが基板に無いネット {sorted(missing)[:10]}"


def test_the_pending_list_shrinks_to_nothing_before_ordering():  # noqa: D401
    """発注前に PENDING が空でなければならないことを、明文で残す。

    このテストは今は通る（残件があることを許す）。**発注の直前に
    PENDING を空にすること**が条件で、それを忘れないための場所。
    """
    assert not PENDING, f"まだ基板に載っていない部品がある: {sorted(PENDING)}"


def test_every_part_that_gets_assembled_has_a_row_in_the_parts_table():
    """基板に載る部品が、買う部品の表（tools/parts.py）に全部あること。

    **部品を足したときに書き忘れると、発注の直前に気づく。**そこで
    気づくのがいちばん高くつく（JLCPCB の見積もりを取り直すことになる）。

    番号そのものが埋まっているかは export_fab.py が見る。**ここは
    「行があるか」だけ。**番号は現物を確認しないと書けないので、
    埋まっていないことを検査で咎めるのは早すぎる。
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from circuit import daughterboard_netlist, netlist
    from parts import NOT_ASSEMBLED, PARTS

    need = {kind
            for parts in (netlist("left"), netlist("right"),
                          daughterboard_netlist())
            for _ref, kind, _pins in parts
            if kind not in NOT_ASSEMBLED}
    missing = sorted(need - set(PARTS))
    assert not missing, (
        f"買う部品の表に無い部品: {missing}\n"
        "  tools/parts.py の PARTS に足すこと")
    extra = sorted(set(PARTS) - need)
    assert not extra, (
        f"もう使っていない部品が表に残っている: {extra}\n"
        "  tools/parts.py から消すこと")
