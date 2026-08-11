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
**ここでは判定の規則だけを、ソースから読み出して確かめる。**
関数を呼べないぶん、**規則の文字列が実物と一致していることも確かめる。**
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs/hardware/open-gaps.md"
SRC = ROOT / "tools/export_fab.py"

# `_gate_antenna()` が使う 2 つの文字列。**実物から読む。**
_UNRESOLVED = "## 23. ★未解決★ アンテナが地板に挟まれている"
_ACCEPTED = r"^### 承知して発注する\s*$"


def _rule_is_the_one_in_the_source():
    """検査が見ている規則が、`export_fab.py` の中身と同じであること。"""
    src = SRC.read_text()
    assert _UNRESOLVED in src, "未解決の見出しの文字列が export_fab.py と違う"
    assert _ACCEPTED in src, "承知の節を探す正規表現が export_fab.py と違う"


def test_the_rule_matches_the_real_gate():
    _rule_is_the_one_in_the_source()


def test_the_gate_is_not_opened_by_prose_that_merely_mentions_it():
    """**本文で「### 承知して発注する」に言及しても、門は開かないこと。**

    これが 2026-08-11 に実際に起きていた壊れ方。
    """
    prose = (
        "## 23. ★未解決★ アンテナが地板に挟まれている（発注前に必ず読む）\n"
        "\n"
        "**「### 承知して発注する」が無い限りガーバーを出さない。**\n"
    )
    assert _UNRESOLVED in prose                       # 門は armed のはず
    assert re.search(_ACCEPTED, prose, re.M) is None, (
        "本文の引用で門が開いてしまう")


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
    assert re.search(_ACCEPTED, accepted, re.M) is not None


def test_the_gate_is_currently_armed():
    """**いまの open-gaps.md では、門が閉まっていること。**

    #23 は未解決で、承知の節はまだ無い。**この検査が赤くなったら、
    「承知して発注する」が書かれたか、#23 が解決したかのどちらか。**
    どちらも、気づかずに通ってよい変化ではない。
    """
    doc = DOC.read_text()
    if _UNRESOLVED not in doc:
        return                          # #23 が解決した。門は不要
    assert re.search(_ACCEPTED, doc, re.M) is None, (
        "承知の節ができている。**発注してよい状態か、人が確かめること**")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
