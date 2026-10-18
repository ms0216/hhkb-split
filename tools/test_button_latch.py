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

# ======================================================================
# 2026-10-15 の監査: **`.c` 側の判断が一度も実行されていなかった。**
# core が見ていたのは bl_code 1 関数だけで、
#   - どの入力を扱うか（type / code の門）
#   - レイヤーの OR
# は `.c` に埋まっていた。切り出して、ここで動かす。
# ======================================================================

GATE_HARNESS = r"""
#include <stdio.h>
#include "button_latch_core.h"
enum { KEY = 1, REL = 2, FROM = 0x110, OTHER = 0x999 };
int main(void) {
    int bad = 0;
    /* 扱うのは「種類が KEY かつ code が from」のときだけ */
    if (!bl_applies(KEY, KEY, FROM, FROM)) bad = 1;        /* 合致 → 扱う */
    if (bl_applies(REL, KEY, FROM, FROM)) bad = 2;         /* 種類が違う → 扱わない */
    if (bl_applies(KEY, KEY, OTHER, FROM)) bad = 3;        /* code が違う → 扱わない */
    if (bl_applies(REL, KEY, OTHER, FROM)) bad = 4;        /* 両方違う → 扱わない */

    /* レイヤーは OR（どれか 1 つでも有効なら置き換える） */
    bool none[3] = {false, false, false};
    bool one[3]  = {false, true,  false};
    bool all[3]  = {true,  true,  true};
    if (bl_any_layer_active(none, 3)) bad = 5;
    if (!bl_any_layer_active(one, 3)) bad = 6;             /* ← AND だとここで落ちる */
    if (!bl_any_layer_active(all, 3)) bad = 7;
    if (bl_any_layer_active(one, 0)) bad = 8;              /* 長さ 0 は偽 */
    printf("%d\n", bad);
    return bad;
}
"""


def _run_src(tmp_path, harness, name="g.c"):
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("C コンパイラが無い")
    src = tmp_path / name
    src.write_text(harness)
    exe = tmp_path / "g"
    subprocess.run(
        [cc, "-std=c11", "-Wall", "-Werror", "-I", str(ROOT / "firmware/src"),
         "-o", str(exe), str(src)],
        check=True,
    )
    return subprocess.run([str(exe)], capture_output=True, text=True)


def test_only_the_configured_key_is_rewritten(tmp_path):
    """**関係ないイベントのコードを書き換えないこと。**

    取り違えると、ほかのキーやセンサの値まで置き換わる。
    """
    r = _run_src(tmp_path, GATE_HARNESS)
    assert r.returncode == 0 and r.stdout.strip() == "0", (
        f"bl_applies / bl_any_layer_active が期待どおりでない（印: {r.stdout.strip()}）")


def test_the_driver_delegates_to_the_core(tmp_path):
    """**`.c` が自前で判断し直していないこと。**

    2 つ実装を持つと必ずずれる（この案件が繰り返し踏んできた型）。
    """
    import re
    src = (ROOT / "firmware/src/input_button_latch.c").read_text()
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)

    assert "bl_applies(" in code, "入力の門を core に委ねていない"
    assert "bl_any_layer_active(" in code, "レイヤーの OR を core に委ねていない"
    # 自前のループで OR を作り直していないこと
    assert "alt_now = alt_now ||" not in code, (
        "レイヤーの OR を .c 側で作り直している。**core と 2 つ実装になる**")

