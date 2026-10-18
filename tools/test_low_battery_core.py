"""打ち止めの判定を**机の上で**動かして確かめる。

2026-10-15 の監査で、`low_battery_off.c` の判定ロジックが
**自動検査で一度も実行されていない**ことが分かった。
既存の検査が見ていたのは「USB の門がどう書かれているか」という**文字列**だけで、
数える／閾値を跨ぐ／リセットする、という挙動は走っていなかった。

作りは tools/test_encoder_gated.py と同じ（cc → ctypes）。
"""

import ctypes as C
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

WAIT, POWER_OFF = 0, 1
EMPTY_MV = 2400  # hhkb_split.dtsi の empty-millivolts
SAMPLES = 2      # HHKB_LOW_BATTERY_SOFT_OFF_SAMPLES の既定


class State(C.Structure):
    _fields_ = [("consecutive", C.c_uint8)]


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("C コンパイラが無い")
    so = tmp_path_factory.mktemp("lbc") / "liblbc.so"
    subprocess.run(
        [cc, "-shared", "-fPIC", "-std=c11", "-o", str(so),
         str(ROOT / "tools/stick_pod/lbc_wrap.c")],
        check=True,
    )
    L = C.CDLL(str(so))
    L.lbc_step_of.restype = C.c_int
    L.lbc_count.restype = C.c_int
    return L


def step(lib, st, mv=3000, usb=False, readable=True, samples=SAMPLES):
    return lib.lbc_step_of(C.byref(st), int(usb), int(readable), mv, EMPTY_MV, samples)


# --- 基本 ---------------------------------------------------------------

def test_healthy_battery_never_powers_off(lib):
    st = State()
    for _ in range(100):
        assert step(lib, st, mv=3000) == WAIT
    assert lib.lbc_count(C.byref(st)) == 0


def test_two_consecutive_lows_power_off(lib):
    """**既定は 2 回。**1 回では止めない（BLE 送信中の電圧降下を拾わないため）。"""
    st = State()
    assert step(lib, st, mv=2300) == WAIT, "1 回目で止まっている"
    assert step(lib, st, mv=2300) == POWER_OFF, "2 回続いたのに止まらない"


def test_the_threshold_is_inclusive(lib):
    """ちょうど打ち止め電圧は「下回った」側に数える（元の実装と同じ）。"""
    st = State()
    step(lib, st, mv=EMPTY_MV)
    assert lib.lbc_count(C.byref(st)) == 1
    st2 = State()
    step(lib, st2, mv=EMPTY_MV + 1)
    assert lib.lbc_count(C.byref(st2)) == 0


def test_a_recovery_resets_the_count(lib):
    """**連続でなければ数え直す。**間に 1 回でも回復したらリセット。"""
    st = State()
    step(lib, st, mv=2300)
    assert lib.lbc_count(C.byref(st)) == 1
    step(lib, st, mv=3000)                       # 回復
    assert lib.lbc_count(C.byref(st)) == 0
    assert step(lib, st, mv=2300) == WAIT, "リセットされていない"


# --- USB の門（2026-09-26 に実機で踏んだ不具合）--------------------------

def test_usb_power_never_powers_off(lib):
    """⚠️ **USB 給電中は止めない。**

    2026-09-26 に実機で踏んだ: 電源スイッチ OFF ＋ USB だと分圧が 0mV を
    返すので、そのまま数えると**約 2 分で勝手に電源が落ちた。**
    """
    st = State()
    for _ in range(100):
        assert step(lib, st, mv=0, usb=True) == WAIT
    assert lib.lbc_count(C.byref(st)) == 0, "USB 給電中に数えている"


def test_usb_power_resets_an_existing_count(lib):
    """電池で数え始めたあと USB を挿したら、**数えはリセット**される。"""
    st = State()
    step(lib, st, mv=2300)
    assert lib.lbc_count(C.byref(st)) == 1
    step(lib, st, mv=0, usb=True)
    assert lib.lbc_count(C.byref(st)) == 0


# --- 読めなかったとき ---------------------------------------------------

def test_an_unreadable_sample_holds_the_count(lib):
    """**読めない回は据え置き。**リセットもカウントもしない。

    1 回の読み取り失敗で、それまで数えた連続を捨てない
    （捨てると、失敗が混ざるだけで永久に止まらなくなる）。
    逆に「下回った」とも数えない（値が無いのに数えるのは根拠が無い）。
    """
    st = State()
    step(lib, st, mv=2300)
    assert lib.lbc_count(C.byref(st)) == 1
    assert step(lib, st, readable=False) == WAIT
    assert lib.lbc_count(C.byref(st)) == 1, "読めない回で数えが変わった"
    assert step(lib, st, mv=2300) == POWER_OFF, "据え置きのあと 2 回目で止まらない"


def test_unreadable_alone_never_powers_off(lib):
    st = State()
    for _ in range(100):
        assert step(lib, st, readable=False) == WAIT
    assert lib.lbc_count(C.byref(st)) == 0


# --- 設定を変えたとき ---------------------------------------------------

def test_samples_setting_is_honoured(lib):
    for n in (1, 3, 5):
        st = State()
        for i in range(1, n):
            assert step(lib, st, mv=2300, samples=n) == WAIT, f"{n} 回設定で {i} 回目に止まった"
        assert step(lib, st, mv=2300, samples=n) == POWER_OFF, f"{n} 回設定で止まらない"


def test_the_count_does_not_wrap(lib):
    """**数えが 255 を越えて 0 に戻らないこと。**

    `samples` を大きくしたとき、折り返すと永久に止まらなくなる。
    """
    st = State()
    for _ in range(300):
        step(lib, st, mv=2300, samples=255)
    assert lib.lbc_count(C.byref(st)) == 255, "数えが折り返している"
