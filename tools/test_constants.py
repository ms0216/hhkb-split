"""設計定数が、重複せず・出所つきで書かれていることを守る。

**同じ名前を二度定義すると、後から書いた方が黙って勝つ。**
実際に XIAO_H（XIAO 単体の高さ 5.0mm）を、子基板まわりの別の意味の 4.0mm で
上書きしていた。どちらの利用側もエラーにならないので気づけない。

**推定で埋めた値と、実測で確かめた値が区別できないと、
「どこがまだ確かめられていないか」が分からなくなる。**
この案件では、タクトスイッチの向きや XIAO のピンピッチを推定のまま断定し、
どちらも利用者に指摘されて初めて誤りだと分かった。
出所のタグ（[確定] / [暫定]）を機械が数え、暫定のものを一覧にする。
"""

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
MODULES = sorted(p for p in TOOLS.glob("*.py") if not p.name.startswith("test_"))


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_constant_is_defined_twice(path):
    """モジュール直下で同じ名前を二度代入していないこと。

    後から書いた方が黙って勝つので、単体では誰もエラーにならない。
    """
    tree = ast.parse(path.read_text())
    seen, dup = set(), set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            names = ([t.id] if isinstance(t, ast.Name)
                     else [e.id for e in getattr(t, "elts", []) if isinstance(e, ast.Name)])
            for n in names:
                if n.isupper():
                    (dup if n in seen else seen).add(n)
    assert not dup, f"{path.name}: 二度定義されている定数 {sorted(dup)}"


def provisional():
    """[暫定] と書かれた定数を集める。"""
    out = []
    for path in MODULES:
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if "[暫定]" in line:
                m = re.match(r"\s*([A-Z_][A-Z0-9_,\s]*)\s*=", line)
                if m:
                    out.append((path.name, i, m.group(1).strip()))
    return out


def test_provisional_values_are_listed_where_they_can_be_seen():
    """暫定値が、実測タスクの文書に一覧として載っていること。

    **見えない暫定値は、確定値と区別がつかない。**
    実測して差し替えるべきものが分からなくなる。
    """
    doc = (ROOT / "docs/hardware/provisional-values.md")
    assert doc.exists(), "docs/hardware/provisional-values.md が無い"
    text = doc.read_text()
    missing = [f"{f}:{n}" for f, _, n in provisional() if n.split(",")[0].strip() not in text]
    assert not missing, f"文書に載っていない暫定値: {missing}"


def test_the_provisional_list_has_no_stale_entries():
    """文書に載っているのに、もう暫定でなくなった値が残っていないこと。"""
    doc = (ROOT / "docs/hardware/provisional-values.md").read_text()
    live = {n.split(",")[0].strip() for _, _, n in provisional()}
    # **`XIAO_L/W/H` のような「まとめ書き」も読む。**以前この形の行は
    # 正規表現に掛からず、暫定でなくなっても検出されなかった（2026-08-08）。
    listed = set()
    for cell in re.findall(r"^\| `([^`]+)`", doc, re.M):
        head = cell.split("/")[0].strip()
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", head):
            continue
        listed.add(head)
        for suffix in cell.split("/")[1:]:
            suffix = suffix.strip()
            # XIAO_L/W/H → XIAO_W, XIAO_H
            prefix = head.rsplit("_", 1)[0]
            listed.add(f"{prefix}_{suffix}" if "_" not in suffix else suffix)
    stale = listed - live
    assert not stale, f"もう暫定ではない値が文書に残っている: {sorted(stale)}"


def test_the_provisional_list_shows_the_same_numbers_as_the_code():
    """文書に書いてある暫定値が、コードの実際の値と一致すること。

    **名前が載っているだけでは足りない。**この検査が無い間、
    `SW_PWR_H` はコードで 8.6mm、文書で 4.0mm と**倍以上ずれていた**。
    文書を見て部品を買えば、入らないものを買う。実際、同じ型で
    電池ボックスを買い直すことになっている（open-gaps #22）。

    暫定値は「これから実物と突き合わせる値」なので、**文書とコードが
    ずれていると、どちらを信じて買えばよいか分からなくなる。**
    """
    import importlib

    doc = (ROOT / "docs/hardware/provisional-values.md").read_text()
    # 表の行から「定数名」と「最初に出てくる数値」を拾う。
    #   | `SW_PWR_W` | 4.4mm | ... |
    #   | `XIAO_L/W/H` | 21.0 / 18.0 / 3.0mm | ...
    rows = {}
    for name_cell, value_cell in re.findall(
            r"^\|\s*`([^`]+)`\s*\|([^|]*)\|", doc, re.M):
        names = [n.strip() for n in name_cell.split("/")]
        nums = re.findall(r"-?\d+(?:\.\d+)?", value_cell)
        if len(names) == 1 and nums:
            rows[names[0]] = float(nums[0])
        elif len(names) == len(nums) > 1:
            head = names[0]
            prefix = head.rsplit("_", 1)[0]
            for n, v in zip(names, nums):
                full = n if "_" in n else f"{prefix}_{n}"
                rows[full] = float(v)

    assert rows, "文書から暫定値の数値をひとつも読めなかった"

    bad = []
    for path, _line, decl in provisional():
        mod = importlib.import_module(path[:-3])
        for name in (n.strip() for n in decl.split(",")):
            if name not in rows:
                continue          # 一覧に載っているかは別の検査が見る
            actual = getattr(mod, name, None)
            if actual is None or abs(float(actual) - rows[name]) > 1e-6:
                bad.append(f"{name}: コード {actual} / 文書 {rows[name]}")
    assert not bad, (
        "暫定値の文書とコードで数値が食い違っている\n    "
        + "\n    ".join(bad)
        + "\n  文書を見て部品を買うと間違える。どちらかを直すこと")
