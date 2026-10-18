"""乾電池の残量計（電圧 → %）を**実際に動かして**確かめる。

2026-10-15 の監査で、`alkaline_mv_to_pct` と ADC の換算が
**自動検査で一度も実行されていない**ことが分かった。
open-gaps #13 の「新品アルカリで 91%」という実測の読み替えは、
この関数が正しいことを前提にしている。

⚠️ **式を写さない。**写すと「自分の生成物どうしの一致」になる
（CLAUDE.md の作法 3）。`battery_alkaline.c` から**関数本体を抜き出して**
コンパイルし、**実機と同じコード**を動かす。
"""

import ctypes as C
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "firmware/drivers/battery_alkaline.c"

# hhkb_split.dtsi の値（ここが唯一の出所ではないので、下の検査で突き合わせる）
EMPTY_MV = 2400
FULL_MV = 3300


def _extract_fn():
    """`.c` から alkaline_mv_to_pct の本体をそのまま抜き出す。"""
    src = SRC.read_text()
    i = src.index("static uint8_t alkaline_mv_to_pct(")
    # 波括弧の対応で関数の終わりを探す
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError("alkaline_mv_to_pct の終わりが見つからない")


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("C コンパイラが無い")
    d = tmp_path_factory.mktemp("alk")
    (d / "alk_fn.inc").write_text(_extract_fn())
    so = d / "libalk.so"
    subprocess.run(
        [cc, "-shared", "-fPIC", "-std=c11", f"-I{d}", "-o", str(so),
         str(ROOT / "tools/stick_pod/alk_wrap.c")],
        check=True,
    )
    L = C.CDLL(str(so))
    L.alk_pct.restype = C.c_int
    return L


def pct(lib, mv, empty=EMPTY_MV, full=FULL_MV):
    return lib.alk_pct(empty, full, mv)


# --- 端 -----------------------------------------------------------------

def test_full_and_empty(lib):
    assert pct(lib, FULL_MV) == 100
    assert pct(lib, FULL_MV + 500) == 100, "満タンを越えても 100 を超えない"
    assert pct(lib, EMPTY_MV) == 0
    assert pct(lib, EMPTY_MV - 500) == 0, "打ち止めを割っても負にならない"
    assert pct(lib, 0) == 0


def test_never_exceeds_100(lib):
    """**uint8_t に入らない値を返さない。**"""
    for mv in range(0, 5000, 7):
        v = pct(lib, mv)
        assert 0 <= v <= 100, f"{mv}mV で {v}% を返した"


# --- 単調であること（唯一主張している性質）------------------------------

def test_monotonic(lib):
    """**減り続ける。増えたように見えない。**

    コメントが「単調」を性質として挙げている。放電曲線ではないので
    精度は主張しないが、単調性だけは守る。
    """
    prev = -1
    for mv in range(EMPTY_MV, FULL_MV + 1):
        v = pct(lib, mv)
        assert v >= prev, f"{mv}mV で下がった（{prev} → {v}）"
        prev = v


# --- 線形であること -----------------------------------------------------

def test_midpoint_is_about_half(lib):
    mid = (EMPTY_MV + FULL_MV) // 2
    v = pct(lib, mid)
    assert 49 <= v <= 51, f"窓の真ん中が {v}%（線形なら 50 前後）"


def test_matches_the_recorded_measurement(lib):
    """**open-gaps #13 の実測と合うこと。**

    「2026-09-12 実機: 新品アルカリで 91%（逆算 3,219mV）」。
    この読み替えが成り立つかを、実機と同じコードで確かめる。
    **外部の事実（記録された実測）と突き合わせる**ので、
    自分の生成物どうしの一致にならない。
    """
    assert pct(lib, 3219) == 91, (
        "記録の「3,219mV = 91%」と合わない。"
        "open-gaps #13 の読み替えか、この関数のどちらかが間違っている")


# --- 設定（devicetree）との突き合わせ ------------------------------------

def test_the_window_matches_the_devicetree():
    """**この検査が使っている窓が、実機の devicetree と同じであること。**

    ここがずれると、上の検査は「別の設定での正しさ」を確かめることになる。
    """
    dtsi = (ROOT / "config/boards/shields/hhkb_split/hhkb_split.dtsi").read_text()
    m_e = re.search(r"empty-millivolts\s*=\s*<(\d+)>", dtsi)
    m_f = re.search(r"full-millivolts\s*=\s*<(\d+)>", dtsi)
    assert m_e and m_f, "devicetree に empty/full-millivolts が無い"
    assert int(m_e.group(1)) == EMPTY_MV, "empty-millivolts がこの検査とずれている"
    assert int(m_f.group(1)) == FULL_MV, "full-millivolts がこの検査とずれている"


def test_a_narrow_window_does_not_divide_by_zero(lib):
    """**窓が 0 幅でも落ちないこと。**設定ミスでそうなりうる。"""
    assert pct(lib, 2400, empty=2400, full=2400) == 100  # mv >= full で先に返る
    assert pct(lib, 2399, empty=2400, full=2400) == 0    # mv <= empty で返る
