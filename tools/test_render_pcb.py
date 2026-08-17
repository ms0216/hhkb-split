"""render_pcb.py のスキップ判定を、両方向から確かめる。

見たいのは 2 つだけ:
  - 設計が変われば描き直す（0.1mm 動かして検出できるか）
  - 保存し直しただけなら描かない（UUID を全部振り直しても黙るか）

片方だけでは足りない。「常に描く」は前者を通し、「常に描かない」は後者を通す。

描画そのもの（kicad-cli・pdftoppm）はここでは呼ばない。遅いうえに
kicad-cli の有無に縛られる。**指紋の判定だけ**を見る。
"""

import re
import uuid
from pathlib import Path

import pytest

import boardhash
import render_pcb

PCB = Path(__file__).resolve().parent.parent / "pcb"
AT = re.compile(r"(\(footprint [\s\S]{0,600}?\n\t\t\(at )([-\d.]+)( [-\d.]+\))")
UUID = re.compile(r'\(uuid "[0-9a-f-]{36}"\)')
REF_OF = re.compile(r'\(property "Reference" "([^"]+)"')


@pytest.fixture(scope="module")
def board():
    p = PCB / "hhkb_split_daughterboard.kicad_pcb"
    if not p.exists():
        pytest.skip(f"{p.name} が無い")
    return p.read_text()


def _fingerprint(text, tmp_path, name):
    p = tmp_path / name
    p.write_text(text)
    return boardhash.fingerprint(p)


def test_moving_a_part_changes_the_fingerprint(board, tmp_path):
    """0.1mm 動かしたら気づく。気づかなければ絵が古いまま残る。"""
    m = AT.search(board)
    assert m, "フットプリントの (at x y) が見つからない（書式が変わった？）"
    moved = board[:m.start(2)] + f"{float(m.group(2)) + 0.1:.4f}" + board[m.end(2):]

    assert _fingerprint(board, tmp_path, "a.kicad_pcb") \
        != _fingerprint(moved, tmp_path, "b.kicad_pcb"), \
        "0.1mm 動かしても指紋が同じ。これでは変更を取り逃がす"


def test_pads_and_their_nets_are_actually_captured(board, tmp_path):
    """**パッドを 1 つも拾えていない状態で通らないこと。**

    実際に起きた（2026-08-16 に発見）: KiCad 10 が `(net "GND")` と
    番号なしで書くようになり、`(net \\d+ "...")` を要求していた正規表現が
    6 ファイル・全パッドで 0 件になった。それでも指紋は座標と外形から
    作られるので、**検査は通り続けた**。

    「拾えているか」を数で見る検査が無かったのが原因。ここで数える。
    """
    import ast
    rows, _ = ast.literal_eval(boardhash.canonical(board))
    pads = sum(len(r[5]) for r in rows)
    assert pads > 0, \
        "パッドを 1 つも拾えていない。指紋が結線を見ておらず、繋ぎ替えを検出できない"


def test_rewiring_a_pad_changes_the_fingerprint(board, tmp_path):
    """結線を変えたら気づく。座標だけ見ていると、ここが素通りする。"""
    if '(net "' not in board:
        pytest.skip("ネットを持つパッドが無い")
    rewired = board.replace('(net "GND")', '(net "V3V3")', 1)
    assert rewired != board, "GND のパッドが無い（書式が変わった？）"

    assert _fingerprint(board, tmp_path, "e.kicad_pcb") \
        != _fingerprint(rewired, tmp_path, "f.kicad_pcb"), \
        "パッドを別のネットに繋ぎ替えても指紋が同じ。結線の変更を取り逃がす"


def test_it_names_the_part_that_moved(board, tmp_path):
    """**動いた部品を名指しできること。**

    ここが「全部」や「空」を返すと拡大図が役に立たない。
    D_PWR を動かしたら D_PWR だけが挙がる、という粒度が要る
    （別セッションが D_PWR を動かして「読めない」となったのが発端）。
    """
    a = tmp_path / "a.kicad_pcb"
    a.write_text(board)
    before = render_pcb.parts(a)
    assert before, "部品を 1 つも拾えていない"

    # **どれを動かすかは parts() の戻り値から決めない。**
    # 位置を潰す壊し方（at を 0,0 にする）をしたとき、戻り値を頼りに
    # 場所を探すと「書き換えられなかった」で skip に落ちてしまう。
    # skip は緑に見えるので、440 件の中では気づけない（実際にそうなった）。
    # ここでは**ファイルの中身から直に**フットプリントを 1 つ選んで動かす。
    m = AT.search(board)
    assert m, "フットプリントの (at x y) が見つからない（書式が変わった？）"
    ref = REF_OF.search(board[m.end():])
    assert ref, "動かした部品の Reference が読めない"
    ref = ref.group(1)
    assert ref in before, f"{ref} が parts() に出てこない"

    moved_text = board[:m.start(2)] + f"{float(m.group(2)) + 1.0:.4f}" + board[m.end(2):]
    b = tmp_path / "b.kicad_pcb"
    b.write_text(moved_text)
    got = render_pcb.moved(before, render_pcb.parts(b))

    assert ref in got, f"動かした {ref} が挙がらない: {got}"
    assert len(got) == 1, f"動かしていない部品まで挙がっている: {got}"


def test_nothing_moved_means_no_zoom(board, tmp_path):
    """同じものどうしなら 1 つも挙げない。ここが緩いと毎回全部を拡大する。"""
    a = tmp_path / "c.kicad_pcb"
    a.write_text(board)
    p = render_pcb.parts(a)
    assert render_pcb.moved(p, p) == [], "変わっていないのに動いたと言っている"


def test_the_zoom_window_stays_on_the_board(board, tmp_path):
    """**窓が基板の外へ出ないこと。**

    実際に出た（2026-08-16）: 中心から一律 6mm で切っていたので、
    縁にいる BT1_-（y 84.28-87.33・外形の上辺は y=84.0）で窓が
    y=79.8 まで伸び、**絵の 3 分の 1 が紙の白**になった。
    「使えるものじゃない」と言われたのがこれ。
    """
    p = tmp_path / "w.kicad_pcb"
    p.write_text(board)
    bx0, by0, bx1, by1 = render_pcb.outline(p)

    for ref in render_pcb.parts(p):
        try:
            x0, y0, x1, y1 = render_pcb.window(p, ref)
        except RuntimeError:
            continue                              # パッドが無い部品は拡大しない
        assert x0 >= bx0 - 0.01 and y0 >= by0 - 0.01, f"{ref}: 窓が板の外（左上）"
        assert x1 <= bx1 + 0.01 and y1 <= by1 + 0.01, f"{ref}: 窓が板の外（右下）"


def test_the_zoom_window_contains_the_part(board, tmp_path):
    """**その部品が窓に入っていること。**囲みだけ出て中身が無いのでは意味がない。"""
    p = tmp_path / "c2.kicad_pcb"
    p.write_text(board)

    for ref in render_pcb.parts(p):
        try:
            px0, py0, px1, py1 = render_pcb.extent(p, ref)
            x0, y0, x1, y1 = render_pcb.window(p, ref)
        except RuntimeError:
            continue
        assert x0 <= px0 and y0 <= py0 and x1 >= px1 and y1 >= py1, \
            f"{ref}: 部品が窓からはみ出している"


def test_the_zoom_uses_the_side_the_part_is_on(board, tmp_path):
    """**裏の部品は裏面を描くこと。**

    実際に消えた（2026-08-16）: この子基板は discrete が全部 B.Cu に
    いるのに、F.Cu を重ねて描いていた。手前の面が塗り潰すので、
    **見たい部品が絵から消える**（BT1_- の枠の中が空になった）。
    """
    p = tmp_path / "s.kicad_pcb"
    p.write_text(board)

    sides = {ref: render_pcb.side_of(p, ref) for ref in render_pcb.parts(p)}
    assert set(sides.values()) <= {"F", "B"}, f"面の判定が壊れている: {sides}"
    # この基板は裏に部品がいる。全部 F と答えるなら判定が効いていない。
    assert "B" in sides.values(), \
        f"裏の部品を 1 つも認識していない: {sides}"
    for ref, s in sides.items():
        assert s in render_pcb.SIDE_LAYERS, f"{ref}: 面 {s} に対応する層が無い"
        assert f"{s}.Cu" in render_pcb.SIDE_LAYERS[s]


def test_resaving_does_not_change_the_fingerprint(board, tmp_path):
    """UUID の振り直しでは描き直さない。ここが緩いと毎回描いて用をなさない。"""
    resaved = UUID.sub(lambda _: f'(uuid "{uuid.uuid4()}")', board)
    assert resaved != board, "UUID が 1 つも置き換わっていない（書式が変わった？）"

    assert _fingerprint(board, tmp_path, "c.kicad_pcb") \
        == _fingerprint(resaved, tmp_path, "d.kicad_pcb"), \
        "UUID を振り直しただけで指紋が変わった。毎回描き直してしまう"
