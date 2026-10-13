"""ポインタの動きを BLE で「溜めない・捨てない」で送る規則（firmware/src/ble_pointer_pace_core.h）を、遅い相手を模して確かめる。

模す状況（2026-10-13 の報告）: 動きは 12ms ごとに来る（スティック）。相手は 37ms に 1 個しか受け取れない（1 秒に 27 個）。
見るのは 3 点: (1) 動きの合計が減らない (2) 送信中は次を送らない (3) 止めたあと、残りが相手の 2 回ぶん以内に出きる。
同じ条件で ZMK の標準の送り方（20 個の列・あふれたら古い物を捨てる）も模して、差があることを確かめる（検査が何かを見分けている証拠）。
実機の代わりではない（BLE の実際の振る舞い・属性の探し方は CI のビルドと実機で見る）。
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = r'''
#include <stdio.h>
#include "ble_pointer_pace_core.h"
#define GEN_MS 12
#define LINK_MS 37
#define MOVE_MS 2000
#define STEP 5
int main(void) {
    struct bpp p = {0}; long made = 0, got = 0, reports = 0; int busy_until = -1, last_out = -1, overlap = 0;
    /* 標準の送り方の模型: 20 個の列。あふれたら古い物を捨てる */
    int q[20], qn = 0; long q_got = 0; int q_last_out = -1;
    for (int t = 0; t < MOVE_MS + 3000; t++) {
        if (t == busy_until) { TAKE_DONE(&p); }
        if (t % LINK_MS == 0 && qn > 0) { q_got += q[0]; for (int i = 1; i < qn; i++) q[i - 1] = q[i]; qn--; q_last_out = t; }
        if (t < MOVE_MS && t % GEN_MS == 0) {
            bpp_add(&p, true, STEP); made += STEP;
            if (qn == 20) { for (int i = 1; i < qn; i++) q[i - 1] = q[i]; qn--; }
            q[qn++] = STEP;
        }
        int16_t dx, dy;
        if (bpp_take(&p, &dx, &dy)) {
            if (busy_until > t) overlap = 1;
            got += dx; reports++; last_out = t;
            busy_until = (t / LINK_MS + 1) * LINK_MS;      /* 次の通信の機会に届く */
        }
    }
    printf("%ld %ld %ld %d %d %ld %d\n", made, got, reports, last_out - MOVE_MS, overlap, q_got, q_last_out - MOVE_MS);
    return 0;
}
'''


def _run(tmp_path, done="bpp_done"):
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("C コンパイラが無い")
    src = tmp_path / "t.c"; src.write_text(HARNESS)
    exe = tmp_path / "t"
    subprocess.run([cc, "-std=c11", "-Wall", "-Werror", f"-DTAKE_DONE={done}", "-I", str(ROOT / "firmware/src"), "-o", str(exe), str(src)], check=True)
    made, got, reports, tail, overlap, q_got, q_tail = map(int, subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split())
    return dict(made=made, got=got, reports=reports, tail=tail, overlap=overlap, q_got=q_got, q_tail=q_tail)


def test_slow_link_loses_nothing_and_does_not_lag(tmp_path):
    r = _run(tmp_path)
    assert r["got"] == r["made"], r                       # 動きは減らない
    assert r["overlap"] == 0, r                           # 送信中に次を送っていない
    assert r["reports"] <= 2000 // 37 + 3, r              # 送った数は、相手が受け取れる数まで
    assert r["tail"] <= 2 * 37, r                         # 止めたあと、相手の 2 回ぶん以内に出きる
    # 同じ条件で、標準の送り方は減り、遅れる（この検査が差を見分けていること）
    assert r["q_got"] < r["made"] * 0.6, r
    assert r["q_tail"] > 500, r


def test_the_check_notices_a_sender_that_never_finishes(tmp_path):
    """送信完了を受け取らない作り（in_flight が戻らない）だと、最初の 1 個しか出ない。それを拾うこと。"""
    r = _run(tmp_path, done="(void)")
    assert r["got"] < r["made"], r
