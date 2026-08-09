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


def test_the_breadboard_figure_is_generated_from_this_file():
    """配線図の SVG が、生成器の出力と一致していること。

    docs/hardware/img/ の他の図は手書きだが、C2-b の全体図だけは
    2 枚のブレッドボードと板をまたぐ 7 本の配線があって手では追えないので
    tools/gen_breadboard.py で生成している。

    **手で SVG を直すと、生成器と食い違って次の変更で消える。**
    配線を変えるときは生成器を直して実行すること。

    落ちたときは `.venv/bin/python3 tools/gen_breadboard.py` を実行する。
    """
    import gen_breadboard

    svg = gen_breadboard.OUT
    assert svg.exists(), f"{svg.name} が無い。tools/gen_breadboard.py を実行すること"
    assert svg.read_text() == gen_breadboard.SVG, (
        f"{svg.name} が tools/gen_breadboard.py の出力と食い違っている。\n"
        "  手で SVG を編集したか、生成器を直して実行し忘れている。\n"
        "  .venv/bin/python3 tools/gen_breadboard.py")


def test_the_c4_breadboard_figure_is_generated_from_this_file():
    """C4・C5 の配線図の SVG が、生成器の出力と一致していること。

    落ちたときは `.venv/bin/python3 tools/gen_breadboard_c4.py` を実行する。
    """
    import gen_breadboard_c4 as g

    assert g.OUT.exists(), f"{g.OUT.name} が無い。tools/gen_breadboard_c4.py を実行すること"
    assert g.OUT.read_text() == g.SVG, (
        f"{g.OUT.name} が tools/gen_breadboard_c4.py の出力と食い違っている。\n"
        "  手で SVG を編集したか、生成器を直して実行し忘れている。\n"
        "  .venv/bin/python3 tools/gen_breadboard_c4.py")


@pytest.mark.parametrize("module", ["gen_breadboard", "gen_breadboard_c3", "gen_breadboard_c4"])
def test_the_xiao_straddles_the_gutter_by_its_real_pin_pitch(module):
    """配線図の XIAO が、実際に挿さる行に描かれていること。

    **これを 2 枚の図で間違えた。**ピン間隔は 0.6 インチ＝6 ピッチ。
    行の間隔は 2.54mm、中央の溝は 7.62mm なので、下半分 a..e が 0..4、
    上半分 f..j が 7..11 ピッチ。差が 6 になる組は b/f・c/g・d/h・e/i だけで、
    **i 行と c 行は 8 ピッチあり物理的に入らない**。

    図が間違っていると、本文の穴番号と食い違って組めない。実際
    task-c2-keyscan.md の「3V3 の空きは 1 穴」という記述は、この誤りから
    出ていた（2026-08-08 に両方直した）。
    """
    import importlib

    pitch = dict(zip("abcdefghij", (0, 1, 2, 3, 4, 7, 8, 9, 10, 11)))
    top, bottom = importlib.import_module(module).XIAO_ROWS
    assert pitch[top] - pitch[bottom] == 6, (
        f"{module}: XIAO を {top} 行と {bottom} 行に描いている。"
        f"{pitch[top] - pitch[bottom]} ピッチでは挿さらない（0.6 インチ＝6 ピッチ）")


def _holes(module):
    """配線から (使っている穴 → 誰が, 部品の胴体で塞がる穴) を作る。"""
    import importlib

    g = importlib.import_module(module)
    used, blocked = {}, set(g.COVERED)
    for hole, pin in g.XIAO_PINS.items():
        used[hole] = f"XIAO の {pin}"
    for name, p, q, kind in g.LINKS:
        for h in (p, q):
            if h is None:
                continue
            assert h not in used, f"{h} を {used[h]} と {name} が取り合っている"
            used[h] = name
        if kind in ("part", "series"):
            # 胴体が上に乗るので、両端のあいだの穴は使えない
            lo, hi = sorted((p[0], q[0]))
            blocked |= {(n, p[1]) for n in range(lo + 1, hi)}
    for h in getattr(g, "SWITCH_FEET", ()):
        used.setdefault(h, "スイッチの足")
    return used, blocked


def _c4_holes():
    return _holes("gen_breadboard_c4")


@pytest.mark.parametrize("module", ["gen_breadboard_c3", "gen_breadboard_c4"])
def test_no_two_things_share_a_hole(module):
    """1 つの穴を 2 つが取り合っていないこと。

    **穴の取り違えは、実物を組むまで気づけない。**しかも C4 は乾電池を
    XIAO の 3V3 へ直接入れるので、取り違えると壊れる側の間違いになる。
    """
    _holes(module)  # 重複があれば assert で落ちる


@pytest.mark.parametrize("module", ["gen_breadboard_c3", "gen_breadboard_c4"])
def test_nothing_is_plugged_into_a_hole_under_a_part(module):
    """部品やジャンパを、本体の下に隠れる穴へ挿していないこと。

    **XIAO は 21.0 x 18.0mm で、ピンの端から端（6 ピッチ＝15.24mm）より
    大きい。**両端に 1.1 列ぶんはみ出すので、8 列にもかぶさる。
    タクトスイッチも胴体が間の列を覆う。

    図の上では穴が空いて見えるので、**実物を組むまで気づけない。**
    """
    import importlib

    g = importlib.import_module(module)
    used, blocked = _holes(module)
    feet = set(getattr(g, "SWITCH_FEET", ()))
    bad = [f"{name}: {h} は本体の下" for name, p, q, _k in g.LINKS
           for h in (p, q) if h is not None and h in blocked and h not in feet]
    assert not bad, "本体の下の穴に挿している\n    " + "\n    ".join(bad)


def test_the_c3_wiring_forms_the_intended_circuit():
    """C3 の配線をたどると、意図した回路になっていること。

    **2 列は上下で別の節点**（上半分が GND、下半分が D1）。列だけで
    数えると同じに見えるので、溝で分けて数える。

    **C1 の図をそのまま使うと D0 につないでしまい、キーが一生反応しない。**
    Task C5 で D0 を ADC に取られてキーを D1・D2 へ移したのに、C3 の
    配線表が C1 のままだった（2026-08-09 に直した）。ここで見張る。
    """
    import gen_breadboard_c3 as g

    parent = {}

    def find(n):
        parent.setdefault(n, n)
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    def union(x, y):
        parent[find(x)] = find(y)

    def node(h):
        return (h[0], g.half(h[1]))

    for _name, p, q, kind in g.LINKS:
        if kind == "wire":
            union(node(p), node(q))

    pin = {t: node((n, r)) for (n, r), t in g.XIAO_PINS.items()}
    same = lambda x, y: find(x) == find(y)

    assert not same(pin["D1"], pin["GND"]), "押していないのに D1 が GND に落ちている"
    assert not same(pin["D2"], pin["GND"]), "押していないのに D2 が GND に落ちている"
    assert not same(pin["D1"], pin["D2"]), "D1 と D2 が短絡している"
    assert not same(pin["GND"], pin["5V"]), "GND と 5V が短絡している"
    assert not same(pin["GND"], pin["3V3"]), "GND と 3V3 が短絡している"
    assert not same(pin["D0"], pin["GND"]), (
        "D0 に配線が届いている。**C1 の図を流用したときの典型的な間違い。**"
        "いまのファームは D1・D2 を使う")

    # スイッチを押すと、狙ったピンが GND へ落ちること
    for name, want in (("① スイッチ 1", "D1"), ("② スイッチ 2", "D2")):
        p, q = g.LINK[name]
        assert same(node(p), pin[want]), f"{name} の片側が {want} につながっていない"
        assert same(node(q), pin["GND"]), f"{name} のもう片側が GND につながっていない"


def test_the_c4_probe_points_are_reachable():
    """測定点が、空いていて、かつ部品の胴体の下でないこと。

    **ここを 2 回間違えた。**R2 が b 行を、ダイオードが d 行をふさぐので、
    レールと D0 は a 行から取っている。図の穴番号を動かすとまた埋まる。
    """
    import gen_breadboard_c4 as g

    used, blocked = _c4_holes()
    bad = []
    for what, p, q in g.PROBES:
        for hole in (p, q):
            if hole in used:
                bad.append(f"{what} の {hole} は {used[hole]} が使っている")
            if hole in blocked:
                bad.append(f"{what} の {hole} は部品の胴体の下でテスターを挿せない")
    assert not bad, "測定点が使えない穴を指している\n    " + "\n    ".join(bad)


def test_the_c4_wiring_forms_the_intended_circuit():
    """配線をたどると、意図した回路になっていること。

    **図を眺めて確かめたことにしない。**ジャンパだけを短絡として列をつなぎ、
    できた節点が設計どおりかを見る。とくに次の 2 つは安全に関わる。

      * 電池 ＋ とレールが**直結していない**（かならずダイオードを通る）
      * レールと GND が短絡していない
    """
    import gen_breadboard_c4 as g

    parent = {n: n for n in range(1, 31)}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for _name, p, q, kind in g.LINKS:
        if kind not in ("wire", "series") or p is None or q is None:
            continue
        parent[find(p[0])] = find(q[0])

    def same(x, y):
        return find(x) == find(y)

    batt, rail, gnd, tap, node_a = 29, 14, 12, 17, 20
    assert not same(batt, rail), "電池 ＋ とレールが直結している。ダイオードを迂回している"
    assert not same(rail, gnd), "レールと GND が短絡している"
    assert not same(tap, gnd) and not same(tap, node_a), "分圧のタップが片側へ短絡している"
    assert same(batt, node_a), "スイッチを入れても電池が節点 A に届かない"
    assert same(gnd, 2), "GND バスが XIAO の GND（2 列）につながっていない"
    assert same(rail, 3), "レールが XIAO の 3V3（3 列）につながっていない"
    assert same(tap, 1), "分圧のタップが XIAO の D0（1 列）につながっていない"

    # ダイオードの向き: アノードが節点 A、カソードがレール
    (anode, cathode) = g.LINK["③ 1N5819"]
    assert same(anode[0], node_a) and same(cathode[0], rail), (
        "ダイオードの向きが逆。帯（カソード）はレール側でなければならない")
    # コンデンサの極性: ＋がレール、−が GND
    (plus, minus) = g.LINK["⑥ 100µF"]
    assert same(plus[0], rail) and same(minus[0], gnd), "100µF の極性が逆"
    # 分圧は タップ を挟んで レール側ではなく 節点 A 側から取る（ショットキーの手前）
    assert same(g.LINK["④ R1 1MΩ"][0][0], node_a), "分圧の上側がショットキーの手前になっていない"
    assert same(g.LINK["⑤ R2 1MΩ"][1][0], gnd), "分圧の下側が GND に落ちていない"


def test_provisional_tags_sit_on_the_assignment_line():
    """`[暫定]` が代入行に書かれていること。

    **注記の中へ書いても検出されない。**provisional() は代入行しか見ない
    ので、説明のかたまりの中に `[暫定]` と書くと、暫定値なのに一覧にも
    載らず、誰も追わなくなる。**実際にやった**（SCHOTTKY_VF の出所を
    直したとき、注記の先頭に書いて素通りした）。

    モジュールの説明文（凡例を書く場所）だけは除く。
    """
    import ast

    bad = []
    for path in MODULES:
        src = path.read_text()
        lines = src.splitlines()
        # モジュールの説明文の行範囲を除く
        skip = set()
        tree = ast.parse(src)
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)):
            skip = set(range(tree.body[0].lineno, tree.body[0].end_lineno + 1))
        for i, line in enumerate(lines, 1):
            if "[暫定]" not in line or i in skip:
                continue
            if not re.match(r"\s*([A-Z_][A-Z0-9_,\s]*)\s*=", line):
                bad.append(f"{path.name}:{i}  {line.strip()[:60]}")
    assert not bad, (
        "`[暫定]` が代入行の外に書かれている。この書き方だと一覧に載らず、"
        "**暫定値が見えないまま残る**:\n  " + "\n  ".join(bad))
