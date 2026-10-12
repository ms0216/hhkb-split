"""スティックの押し込みを右クリックに置き換える規則（firmware/src/button_latch_core.h）。

見るのは 1 点: **押したときに決めたボタンで離す。**レイヤーを先に離しても、ボタンが押されたまま残らない。
実機の代わりではない（レイヤーの番号・listener の配線は CI のビルドと実機で見る）。
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include "button_latch_core.h"
enum { L = 0x110, R = 0x111 };
int main(void) {
    bool h = false; int down[2] = {0, 0}, bad = 0;
#define EV(press, alt) do { uint16_t c = CODE(&h, press, alt, L, R); down[c - L] += (press) ? 1 : -1; } while (0)
#define CLEAN() do { if (down[0] != 0 || down[1] != 0) { bad = 1; } down[0] = down[1] = 0; } while (0)   /* 1 組ごとに見る（2 組まとめると、逆向きの誤りどうしが打ち消し合う） */
    EV(1, 0); if (down[0] != 1) { bad = 1; } EV(0, 0); CLEAN();          /* ふつうの押し込み = 左 */
    EV(1, 1); if (down[1] != 1) { bad = 1; } EV(0, 1); CLEAN();          /* Ctrl の間 = 右 */
    EV(1, 1); EV(0, 0); CLEAN();                                         /* Ctrl を先に離す → 右のまま離す */
    EV(1, 0); EV(0, 1); CLEAN();                                         /* 押してから Ctrl → 左のまま離す */
    printf("%d\n", bad);
    return bad;
}
'''


def _run(tmp_path, code_fn):
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("C コンパイラが無い")
    src = tmp_path / "t.c"; src.write_text(HARNESS)
    exe = tmp_path / "t"
    subprocess.run([cc, "-std=c11", "-Wall", "-Werror", f"-DCODE={code_fn}", "-I", str(ROOT / "firmware/src"), "-o", str(exe), str(src)], check=True)
    return subprocess.run([str(exe)], capture_output=True, text=True)


def test_release_uses_the_button_chosen_at_press(tmp_path):
    r = _run(tmp_path, "bl_code")
    assert r.returncode == 0 and r.stdout.strip() == "0", r.stdout


def test_the_check_notices_a_stateless_mapping(tmp_path):
    """その時点のレイヤーだけで決める作り（listener の上書きと同じ）は、押されたまま残る。それをこの検査が拾うこと。"""
    (tmp_path / "naive.h").write_text("static inline uint16_t naive(bool *h, bool p, bool alt, uint16_t f, uint16_t t) { (void)h; (void)p; return alt ? t : f; }\n")
    global HARNESS
    saved = HARNESS
    try:
        HARNESS = saved.replace('#include "button_latch_core.h"', '#include "button_latch_core.h"\n#include "' + str(tmp_path / "naive.h") + '"')
        r = _run(tmp_path, "naive")
    finally:
        HARNESS = saved
    assert r.returncode != 0, "置き換えを毎回その場で決める作りでも通ってしまった"
