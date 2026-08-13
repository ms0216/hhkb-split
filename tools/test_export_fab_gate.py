"""**発注の門が、本当に閉まっていることを確かめる。**

なぜ要るか
----------
**2026-08-11 に、アンテナの門が開きっぱなしだったことが分かった。**

`export_fab.py` の `_gate_antenna()` は
`"### 承知して発注する" in doc` で判定していた。ところが open-gaps.md には
**この門を説明する文**が 2 か所あり、そこに

    「### 承知して発注する」が無い限りガーバーを出さない

と書かれている。**門を説明する文そのものが、門を開けていた。**
承知の節は一度も作られていないのに、製造ファイルは出せる状態だった。

**この案件でいちばん高くつく形（設定しただけで効いていない）そのもの。**

`export_fab.py` は KiCad 同梱の Python でしか動かない（`pcbnew` を読む）ので、
**判定だけを `export_fab_gate.py` に分けてある。ここはその実物を import して、
合成した文書を食わせた挙動で確かめる。**

⚠️ **以前ここは規則の文字列を自前で二重定義していた**（実物のソースに
その文字列が含まれるかを見るだけ）。**両方とも自分で書いた文字列なので、
規則そのものが間違っていても通る**——CLAUDE.md 規則 3。いまは実物を呼ぶ。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs/hardware/open-gaps.md"

sys.path.insert(0, str(ROOT / "tools"))

from export_fab_gate import UNRESOLVED_HEADING, is_gate_open  # noqa: E402


def test_the_gate_is_not_opened_by_prose_that_merely_mentions_it():
    """**本文で「### 承知して発注する」に言及しても、門は開かないこと。**

    これが 2026-08-11 に実際に起きていた壊れ方。
    """
    prose = (
        "## 23. ★未解決★ アンテナが地板に挟まれている（発注前に必ず読む）\n"
        "\n"
        "**「### 承知して発注する」が無い限りガーバーを出さない。**\n"
    )
    assert not is_gate_open(prose), "本文の引用で門が開いてしまう"


def test_the_gate_opens_only_for_a_real_heading():
    """**見出しとして書けば、ちゃんと開くこと。**

    閉じっぱなしで開かない門は、いずれ検査ごと消される。
    """
    accepted = (
        "## 23. ★未解決★ アンテナが地板に挟まれている（発注前に必ず読む）\n"
        "\n"
        "### 承知して発注する\n"
        "\n"
        "2026-08-11 に誰それが承知した。駄目だったら子基板を作り直す。\n"
    )
    assert is_gate_open(accepted)


def test_the_gate_opens_when_the_gap_is_resolved():
    """**#23 が解決したら、承知の節が無くても通ること。**"""
    resolved = "## 23. アンテナが地板に挟まれている（解決済み）\n"
    assert is_gate_open(resolved)


def test_the_gate_is_currently_armed():
    """**いまの open-gaps.md では、門が閉まっていること。**

    #23 は未解決で、承知の節はまだ無い。**この検査が赤くなったら、
    「承知して発注する」が書かれたか、#23 が解決したかのどちらか。**
    どちらも、気づかずに通ってよい変化ではない。
    """
    doc = DOC.read_text()
    if UNRESOLVED_HEADING not in doc:
        return                          # #23 が解決した。門は不要
    assert not is_gate_open(doc), (
        "承知の節ができている。**発注してよい状態か、人が確かめること**")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
