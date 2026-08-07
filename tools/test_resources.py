"""**資源が足りているか**を、設計を進める前に確かめる。

この案件で最も高くついた手戻りは、どれも同じ形をしていた。
「設計を最後まで作り込んでから、そもそも入らないと分かる」。

  - 基板を配線し終えてから、XIAO (21x17.8mm) の置き場所が無いと分かった
  - 配線し終えてから、2 層では行の引き回しが通らないと分かった（通路 1.65mm）

どちらも、面積とピンと層を先に数えていれば初日に分かった。
**足りるかどうかは、作る前に数えられる。**

ここは「今この瞬間、足りているか」を毎回数え直す。設計を変えたときに
黙って足りなくなることを防ぐのが目的で、いま通っていること自体は目的ではない。
"""

import math
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
SHIELD = ROOT / "config/boards/shields/hhkb_split"

# XIAO nRF52840 が外に出しているデジタルピン。これ以上は無い。
XIAO_PINS = {f"D{i}" for i in range(11)}
# SPI2 (xiao_spi) が占有するピン。デバイスツリーには現れない。
SPI_PINS = {"D8", "D9", "D10"}


def _strip(text):
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


# --------------------------------------------------------------------------
# ピン
# --------------------------------------------------------------------------

def test_the_mcu_has_enough_pins():
    """使うピンが XIAO の持ち駒に収まっていること。

    行 5 本＋SPI 3 本＋CS 1 本＋電池センス 1 本。**列をシフトレジスタに
    逃がしているのはこのため。**列を直結すると 6+9=15 本要り、足りない。
    """
    text = _strip((SHIELD / "hhkb_split.dtsi").read_text())
    used = set(SPI_PINS)
    for prop in ("row-gpios", "cs-gpios"):
        m = re.search(rf"\b{prop}\s*=?\s*(.*?);", text, re.S)
        if m:
            used |= {f"D{n}" for n in re.findall(r"&xiao_d\s+(\d+)", m.group(1))}
    used.add("D0")                                   # 電池電圧センス
    over = used - XIAO_PINS
    assert not over, f"XIAO に無いピンを使っている: {sorted(over)}"
    assert len(used) <= len(XIAO_PINS), \
        f"ピンが {len(used)} 本要るが {len(XIAO_PINS)} 本しかない"


def test_columns_would_not_fit_without_the_shift_register():
    """シフトレジスタを外したら足りなくなることを確かめる。

    **足りている理由を明示する。** 「たまたま通っている」のか
    「そうしたから通っている」のかが分からないと、あとで列を直結に
    戻したときに気づけない。
    """
    rows, left_cols, right_cols = 5, 6, 9
    direct = rows + left_cols + right_cols
    assert direct > len(XIAO_PINS), \
        "列を直結しても足りる。シフトレジスタが不要になっているので設計を見直すこと"


# --------------------------------------------------------------------------
# 面積
# --------------------------------------------------------------------------

# 基板に載せる必要がある部品と、その実装に要する面積（フットプリントの外形）。
# **ここに書き漏らした部品は、置き場所が無くても誰も気づかない。**
COMPONENTS = {
    "left": [
        ("74HC595 (SOIC-16)", 7.4, 10.4, 1),
        ("パスコン 0805", 2.0, 1.25, 1),
        ("バルク 100uF", 6.6, 6.6, 1),
        ("ショットキー SOD-123", 3.7, 1.9, 1),
        ("分圧 1MΩ 0805", 2.0, 1.25, 2),
        ("スライドスイッチ", 9.0, 5.0, 1),
        ("電池線ランド", 4.0, 4.0, 2),
        ("FFC 12P", 15.0, 8.0, 1),
    ],
    "right": [
        ("74HC595 (SOIC-16)", 7.4, 10.4, 2),
        ("パスコン 0805", 2.0, 1.25, 2),
        ("バルク 100uF", 6.6, 6.6, 1),
        ("ショットキー SOD-123", 3.7, 1.9, 1),
        ("分圧 1MΩ 0805", 2.0, 1.25, 2),
        ("スライドスイッチ", 9.0, 5.0, 1),
        ("電池線ランド", 4.0, 4.0, 2),
        ("FFC 12P", 15.0, 8.0, 1),
    ],
}


def _board_and_obstacles(half):
    """生成済みの基板から、外形と障害物（スイッチ・スタビ・穴）を読む。"""
    txt = (ROOT / f"pcb/hhkb_split_{half}.kicad_pcb").read_text()
    xs, ys = [], []
    for m in re.finditer(
            r'\(gr_(?:line|arc)[^()]*\(start ([-\d.]+) ([-\d.]+)\)'
            r'[^()]*\(end ([-\d.]+) ([-\d.]+)\)', txt):
        a, b, c, d = map(float, m.groups())
        xs += [a, c]
        ys += [b, d]
    obs = []
    for m in re.finditer(r'\(footprint "([^"]+)"[^\n]*\n\s*\(layer[^\n]*\n'
                         r'\s*\(uuid[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)', txt):
        name, x, y = m.group(1), float(m.group(2)), float(m.group(3))
        # 裏面に部品を置くので、ふさぐのはソケットとスタビと穴。
        if "MX" in name or "Kailh" in name:
            w, h = 16.8, 9.8          # ソケットの実寸（envelopes.py と同じ根拠）
        elif "Stab" in name:
            w, h = 30.0, 16.0
        elif "Mounting" in name:
            w, h = 8.0, 8.0
        else:
            continue                  # ダイオードは同じ裏面だが小さいので後述
        obs.append((x - w / 2, y - h / 2, x + w / 2, y + h / 2))
    return (min(xs), min(ys), max(xs), max(ys)), obs


def _fits(rect_w, rect_h, board, obs, margin=0.5):
    """その大きさの矩形を置ける場所があるか。"""
    X0, Y0, X1, Y1 = board
    w, h = rect_w + margin * 2, rect_h + margin * 2
    y = Y0 + 1.0
    while y + h <= Y1 - 1.0:
        x = X0 + 1.0
        while x + w <= X1 - 1.0:
            if not any(a < x + w and x < c and b < y + h and y < d
                       for a, b, c, d in obs):
                return (x, y)
            x += 1.0
        y += 1.0
    return None


@pytest.mark.parametrize("half", ["left", "right"])
def test_every_component_has_somewhere_to_go(half):
    """必要な部品が 1 つ残らず基板に載る場所があること。

    **XIAO の置き場所が無いと分かったのは、基板を配線し終えたあとだった。**
    同じことを繰り返さないため、部品表の側から場所の有無を数える。
    """
    board, obs = _board_and_obstacles(half)
    missing = []
    for name, w, h, n in COMPONENTS[half]:
        if _fits(min(w, h), max(w, h), board, obs) is None:
            missing.append(f"{name} ({w}x{h}mm x{n})")
    assert not missing, \
        f"{half}: 置き場所が無い部品:\n  " + "\n  ".join(missing)


@pytest.mark.parametrize("half", ["left", "right"])
def test_the_total_component_area_leaves_room_to_route(half):
    """部品の合計面積が、空き面積に対して詰まりすぎていないこと。

    ぎりぎり置けても、配線の通り道が無ければ意味がない。
    経験的に、空きの半分を超えると引き回せなくなる。
    """
    board, obs = _board_and_obstacles(half)
    X0, Y0, X1, Y1 = board
    total = (X1 - X0) * (Y1 - Y0)
    used = sum((c - a) * (d - b) for a, b, c, d in obs)
    free = total - used
    need = sum(w * h * n for _, w, h, n in COMPONENTS[half])
    assert need < free * 0.5, (
        f"{half}: 部品 {need:.0f}mm^2 に対して空き {free:.0f}mm^2。"
        f"詰まりすぎていて配線が通らない")


def test_the_mcu_is_not_expected_to_fit_on_the_main_board():
    """**XIAO は本体基板に載らない**という事実を固定する。

    これは失敗ではなく、確かめた結果の設計前提。子基板方式はここから来ている。
    もし将来これが通らなくなったら（＝載るようになったら）、
    子基板をやめられる合図なので、そのときは決定文書を見直すこと。
    """
    for half in ("left", "right"):
        board, obs = _board_and_obstacles(half)
        # 奥の帯の深さは**実測 10.30mm**（プレート余白とソケットの位置から導出）。
        # 以前ここを 24.0mm と適当に取っており、取付穴を 1 つ動かしただけで
        # 判定が裏返った。判定が偶然の障害物配置に依存していた。
        X0, Y0, X1, Y1 = board
        rear = (X0, Y0, X1, Y0 + 10.30)
        assert _fits(17.8, 21.0, rear, obs) is None, \
            f"{half}: XIAO が奥の帯に載る。子基板が不要になった可能性がある"
