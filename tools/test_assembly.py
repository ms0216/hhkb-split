"""組み上げた状態で部品どうしが食い込まないことを守る。

**この検査はこれまで pytest から呼ばれていなかった。**
tools/gen_assembly.py を手で叩いたときにしか動かず、その結果
「単体のテストは全部通るのに、組み上げると食い込む」状態を何度も作った。
実際にこのファイルを足した時点でも、電池と仕切り壁で 2 件見つかっている。

部品を 1 つ足したら、必ず gen_assembly.build_assembly の parts へも足すこと。
**検査対象に入っていない部品は、検査されていないのと同じ。**
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_assembly import build_assembly, check  # noqa: E402
from gen_plate import halves  # noqa: E402

HALVES = halves()

# 組み立てに含まれていなければならない部品。
# 名前を書いておくことで、あとから足した部品が検査から漏れるのを防ぐ。
REQUIRED = {"case", "plate", "pcb", "lid", "batt", "db"}


@pytest.mark.parametrize("half", ["left", "right"])
def test_nothing_bites_into_anything_else(half):
    problems, _ = check(HALVES[half], half)[:2]
    assert not problems, f"{half}:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("half", ["left", "right"])
def test_every_part_is_in_the_check(half):
    """検査対象から部品が漏れていないこと。

    子基板を足したとき、ケースには造作を入れたのに検査には入れ忘れていた。
    そうすると「通った」が「調べていない」の同義語になる。
    """
    parts, _ = build_assembly(HALVES[half], half)
    missing = REQUIRED - set(parts)
    assert not missing, f"{half}: 検査に入っていない部品 {sorted(missing)}"


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_check_actually_detects_a_collision(half):
    """**検査そのものが効いていることを確かめる。**

    通ったことは、調べた証拠にならない。故意に壊して検出できることを
    毎回確かめる。この案件では、誤った並び順どうしを突き合わせて
    テストが全部通ってしまった前科がある。
    """
    import envelopes

    original = envelopes.XIAO_H
    try:
        envelopes.XIAO_H = original + 15.0     # 子基板の部品を背高にする
        problems, _ = check(HALVES[half], half)[:2]
        assert any("db" in p for p in problems), \
            "子基板を 15mm 背高にしても検出できない。検査が効いていない"
    finally:
        envelopes.XIAO_H = original
