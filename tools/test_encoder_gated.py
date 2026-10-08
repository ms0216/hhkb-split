"""左手のエンコーダの新しい読み方（firmware/drivers/encoder_gated_core.h）を、模擬した波形で確かめる。

EC12PL（24 クリック / 24 パルス）の 1 刻み（時計回り）は「a 閉 → b 閉 → a 開 → b 開」。
ドライバは a が変わった瞬間に b を読む（その時点の b の値）。ここでは
  速く回す・途中まで回して戻す・a のチャタリング・反転・起動時に a が閉じている
を流し、数えた刻みが「掣子を越えた正味の数」と一致することを見る。
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
    _fields_ = [("a_closed", C.c_bool), ("b_at_close", C.c_bool), ("pulses", C.c_int8)]


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
    ev, d = walk(0, [1] * 4 * 10); assert feed(lib, core, ev) == 10 and lib.eg_pulses(C.byref(core)) == 10
    core = Core(); lib.eg_start(C.byref(core), 0, 0)
    ev, d = walk(0, [-1] * 4 * 7); assert feed(lib, core, ev) == -7


def test_invert_flips_direction(lib):
    core = Core(); lib.eg_start(C.byref(core), 0, 0)
    ev, _ = walk(0, [1] * 8); assert feed(lib, core, ev, invert=1) == -2


def test_partial_turn_and_back_counts_nothing(lib):
    core = Core(); lib.eg_start(C.byref(core), 0, 0)
    for n in (1, 2, 3):                      # 4 分の 1〜4 分の 3 まで回して戻す
        ev, _ = walk(0, [1] * n + [-1] * n, settle=False); assert feed(lib, core, ev) == 0
    ev, _ = walk(0, [-1] * 2 + [1] * 2, settle=False); assert feed(lib, core, ev) == 0


def test_a_bounce_does_not_count(lib):
    core = Core(); lib.eg_start(C.byref(core), 0, 0)
    # a が閉じる所で 5 回ばたつく（b は 0 のまま）→ その後 1 刻み
    ev = [(1, 0), (0, 0)] * 5 + [(1, 0), (1, 1), (0, 1), (0, 0)]
    assert feed(lib, core, ev) == 1
    # a が開く所でばたつく（b は 1 のまま）: 最初の「開」で数え、以後の閉→開は b が同じなので数えない
    ev = [(1, 0), (1, 1), (0, 1), (1, 1), (0, 1), (1, 1), (0, 1), (0, 0)]
    assert feed(lib, core, ev) == 1


def test_random_walk_matches_net_detents(lib):
    rng = random.Random(7)
    for trial in range(200):
        core = Core(); lib.eg_start(C.byref(core), 0, 0)
        steps = [rng.choice((1, 1, 1, -1)) for _ in range(rng.randrange(1, 400))]
        ev, d = walk(0, steps)
        # 読み出し（channel_get）で 0 に戻る前提なので、int8 の範囲に収める
        assert abs(d) < 120
        assert feed(lib, core, ev) == d, (trial, steps[:20])


def test_start_with_a_closed(lib):
    # 起動時に a が閉じた位置（4 分の 1 か 2 分の 1 の所）で止まっていた → そこから正方向へ回すと、
    # 最初の刻みは「a 閉」を見ていないぶん 1 つ抜けるか正しく数えるかのどちらか。幻（逆向き）は出ないこと
    for start in (1, 2):
        core = Core(); a, b = CW[start]; lib.eg_start(C.byref(core), a, b)
        ev, d = walk(start, [1] * (4 * 3))
        got = feed(lib, core, ev)
        assert got in (d, d - 1) and got >= 0, (start, got, d)
