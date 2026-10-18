"""左手のエンコーダの新しい読み方（firmware/drivers/encoder_gated_core.h）を、模擬した波形で確かめる。

EC12PL（24 クリック / 24 パルス）の 1 刻み（時計回り）は「a 閉 → b 閉 → a 開 → b 開」。
ドライバは a が変わった瞬間に b を読む（その時点の b の値）。ここでは
  速く回す・途中まで回して戻す・a のチャタリング・反転・起動時に a が閉じている
を流し、数えた刻みが「掣子を越えた正味の数」と一致することを見る。
**符号は ZMK 標準の alps,ec11 と同じ**（図一の時計回り = −1。下の test_sign_matches_zmk_ec11 が ec11 の表と突き合わせる）。
**実機の代わりではない。**接点の実際の位相やばたつき方は現物でしか分からない。
"""
import ctypes as C
import random
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class Core(C.Structure):
    # ⚠️ **C 側（encoder_gated_core.h）と型を合わせること。**
    # ずれるとメモリ配置が食い違い、読める値が壊れる。
    # 2026-10-15 に int8_t → int16_t（溢れで向きが反転するため）。
    _fields_ = [("a_closed", C.c_bool), ("b_at_close", C.c_bool), ("pulses", C.c_int16)]


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("C コンパイラが無い")
    so = tmp_path_factory.mktemp("eg") / "libeg.so"
    subprocess.run([cc, "-shared", "-fPIC", "-std=c11", "-o", str(so), str(ROOT / "tools/stick_pod/eg_core_wrap.c")], check=True)
    L = C.CDLL(str(so))
    L.eg_edge.restype = C.c_int
    L.eg_pulses.restype = C.c_int
    return L


# 1 刻みの中の状態 (a, b) の並び。位置 0 が掣子（止まる所: a 開・b 開）。時計回りは順方向
CW = [(0, 0), (1, 0), (1, 1), (0, 1)]


def feed(lib, core, events, invert=0):
    """events: (a, b) の列。a が変わったときだけドライバが呼ばれる（b の割り込みは無い）。"""
    total = 0
    prev_a = core.a_closed
    for a, b in events:
        if a != prev_a:
            total += lib.eg_edge(C.byref(core), a, b, invert)
            prev_a = a
    return total


def walk(start, steps, settle=True):
    """掣子の位置 start から、+1/-1 を steps 回（4 分の 1 刻みずつ）。状態の列と、正味の刻みの数を返す。
    正味の数は「a が閉じている区間の真ん中（位置 1 と 2 の間）を越えた回数」で数える（ドライバとは別の数え方）。
    settle なら最後に、最後の向きのまま次の掣子まで進める（実物は掣子に落ち着く）。"""
    pos, events, net = start, [], 0
    for s in steps:
        if s > 0 and pos % 4 == 1: net += 1
        if s < 0 and pos % 4 == 2: net -= 1
        pos += s
        events.append(CW[pos % 4])
    if settle and pos % 4 != 0:
        s = 1 if steps[-1] > 0 else -1
        while pos % 4 != 0:
            if s > 0 and pos % 4 == 1: net += 1
            if s < 0 and pos % 4 == 2: net -= 1
            pos += s
            events.append(CW[pos % 4])
    return events, net


def test_full_clicks_each_direction(lib):
    core = Core(); lib.eg_start(C.byref(core), 0, 0)
    ev, d = walk(0, [1] * 4 * 10); assert feed(lib, core, ev) == -10 and lib.eg_pulses(C.byref(core)) == -10
    core = Core(); lib.eg_start(C.byref(core), 0, 0)
    ev, d = walk(0, [-1] * 4 * 7); assert feed(lib, core, ev) == 7


def test_invert_flips_direction(lib):
    core = Core(); lib.eg_start(C.byref(core), 0, 0)
    ev, _ = walk(0, [1] * 8); assert feed(lib, core, ev, invert=1) == 2


def test_partial_turn_and_back_counts_nothing(lib):
    core = Core(); lib.eg_start(C.byref(core), 0, 0)
    for n in (1, 2, 3):                      # 4 分の 1〜4 分の 3 まで回して戻す
        ev, _ = walk(0, [1] * n + [-1] * n, settle=False); assert feed(lib, core, ev) == 0
    ev, _ = walk(0, [-1] * 2 + [1] * 2, settle=False); assert feed(lib, core, ev) == 0


def test_a_bounce_does_not_count(lib):
    core = Core(); lib.eg_start(C.byref(core), 0, 0)
    # a が閉じる所で 5 回ばたつく（b は 0 のまま）→ その後 1 刻み
    ev = [(1, 0), (0, 0)] * 5 + [(1, 0), (1, 1), (0, 1), (0, 0)]
    assert feed(lib, core, ev) == -1
    # a が開く所でばたつく（b は 1 のまま）: 最初の「開」で数え、以後の閉→開は b が同じなので数えない
    ev = [(1, 0), (1, 1), (0, 1), (1, 1), (0, 1), (1, 1), (0, 1), (0, 0)]
    assert feed(lib, core, ev) == -1


def test_random_walk_matches_net_detents(lib):
    rng = random.Random(7)
    for trial in range(200):
        core = Core(); lib.eg_start(C.byref(core), 0, 0)
        steps = [rng.choice((1, 1, 1, -1)) for _ in range(rng.randrange(1, 400))]
        ev, d = walk(0, steps)
        # 読み出し（channel_get）で 0 に戻る前提なので、int8 の範囲に収める
        assert abs(d) < 120
        assert feed(lib, core, ev) == -d, (trial, steps[:20])


def test_start_with_a_closed(lib):
    # 起動時に a が閉じた位置（4 分の 1 か 2 分の 1 の所）で止まっていた → そこから正方向へ回すと、
    # 最初の刻みは「a 閉」を見ていないぶん 1 つ抜けるか正しく数えるかのどちらか。幻（逆向き）は出ないこと
    for start in (1, 2):
        core = Core(); a, b = CW[start]; lib.eg_start(C.byref(core), a, b)
        ev, d = walk(start, [1] * (4 * 3))
        got = feed(lib, core, ev)
        assert -got in (d, d - 1) and got <= 0, (start, got, d)


def test_sign_matches_zmk_ec11(lib):
    """同じ配線で A 案（ZMK 標準の alps,ec11）と B 案を入れ替えても、回す向きが変わらないこと。
    ec11.c の表（prev<<2 | new。値は (A<<1)|B の「レベル」で、プルアップなので閉 = 0）を写して、同じ波形を流す。"""
    minus = {0b0010, 0b0100, 0b1101, 0b1011}; plus = {0b0001, 0b0111, 0b1110, 0b1000}
    def ec11(events, start=(0, 0)):
        lv = lambda a, b: ((0 if a else 1) << 1) | (0 if b else 1)      # noqa: E731
        prev, pulses = lv(*start), 0
        for a, b in events:
            v = lv(a, b); k = (prev << 2) | v
            pulses += -1 if k in minus else 1 if k in plus else 0
            prev = v
        return pulses // 4 if pulses >= 0 else -((-pulses) // 4)       # steps = 96 → 4 パルスで 1 刻み
    for steps in ([1] * 20, [-1] * 20, [1] * 8 + [-1] * 12):
        ev, _ = walk(0, steps)
        core = Core(); lib.eg_start(C.byref(core), 0, 0)
        assert feed(lib, core, ev) == ec11(ev), steps

def test_pulses_saturate_instead_of_wrapping(lib):
    """**溜まりすぎても向きが反転しないこと。**

    2026-10-15 の監査で見つかった。`int8_t pulses` に `+=` していたので、
    読み出しが遅れて 127 刻み溜まると **−128 に折り返して逆回転**になった。
    ZMK は普通トリガで即座に読む（1〜2 刻み）が、スリープ中や
    ワークキューが詰まったときは溜まりうる。

    **型を広げても限界が遠のくだけ**なので飽和させた。
    溢れるほど溜まったら刻み数はもう意味を持たない——
    **向きだけは絶対に間違えない**方を採る。
    """
    core = Core()
    lib.eg_start(C.byref(core), 0, 0)

    # 同じ向きに 300 刻み（旧実装なら int8_t を 2 回以上まわる）。
    # CW は ec11 と符号を合わせてあるので **−1 が正**（eg_core_edge の注記）。
    n = 0
    for _ in range(300):
        n += feed(lib, core, CW)
    assert n == -300, f"刻みの数が合わない: {n}"

    total = lib.eg_pulses(C.byref(core))
    assert total < 0, (
        f"溜めた向きと符号が逆（{total}）。**折り返して逆回転している**")
    assert total == -300, f"飽和の手前なのに値が違う: {total}"


def test_pulses_do_not_flip_sign_at_the_limit(lib):
    """**限界まで溜めても符号が変わらない。**"""
    core = Core()
    lib.eg_start(C.byref(core), 0, 0)
    for _ in range(5000):          # EG_PULSES_MAX(4096) を越える
        feed(lib, core, CW)
    total = lib.eg_pulses(C.byref(core))
    assert total < 0, f"限界を越えたら符号が反転した（{total}）"
    assert total == -4096, f"飽和していない: {total}"

def test_the_python_struct_matches_the_c_struct(lib):
    """**Python 側の型が C 側とずれていないこと。**

    ずれるとメモリ配置が食い違い、読める値が静かに壊れる。
    2026-10-15 に C 側を int8_t → int16_t にしたとき、ここも直す必要があった。
    """
    src = (ROOT / "firmware/drivers/encoder_gated_core.h").read_text()
    import re
    m = re.search(r"(int\d+_t)\s+pulses\s*;", src)
    assert m, "C 側の pulses の型が読めない"
    c_type = m.group(1)
    py_type = dict(Core._fields_)["pulses"]
    want = {"int8_t": C.c_int8, "int16_t": C.c_int16, "int32_t": C.c_int32}[c_type]
    assert py_type is want, (
        f"C 側は {c_type} なのに Python 側が {py_type.__name__}。**配置がずれる**")

def test_trigger_set_flushes_pending_pulses():
    """**登録より前に回した刻みを取りこぼさないこと。**

    2026-10-15 の監査で見つかった。`eg_init` が `eg_start()` で割り込みを
    有効にするのは、ZMK が `trigger_set` を呼ぶ**前**。起動直後につまみを
    回すと `eg_work` が `handler == NULL` で素通りする。

    **刻み自体は失われない**（割り込みが core.pulses に積む）が、
    次に回すまで反映が遅れる。登録した時点で溜まっていれば 1 回知らせる。

    ⚠️ ここは Zephyr の API を使う側なので、ctypes では動かせない。
    **「その処理が在るか」を見る**（在れば CI のビルドが通ることまでは確かめられる）。
    """
    import re
    src = (ROOT / "firmware/drivers/encoder_gated.c").read_text()
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)

    m = re.search(r"static int eg_trigger_set\(.*?\n\}", code, re.S)
    assert m, "eg_trigger_set が見つからない"
    body = m.group(0)

    assert "k_work_submit" in body, (
        "登録時に溜まりを知らせていない。**起動直後の 1 刻みが次まで遅れる**")
    assert "core.pulses" in body, (
        "溜まっているかを見ていない。**毎回 submit すると空振りする**")
    assert "handler != NULL" in body, (
        "handler が未登録のときにも submit している")

