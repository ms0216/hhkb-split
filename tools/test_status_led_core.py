"""LED の状態machine を**机の上で**動かして確かめる。

`status_led.c`（560 行）は実機でしか確かめられておらず、
**優先順位と遷移（純粋なロジック）が一度も自動で検査されていなかった。**
`firmware/src/status_led_core.h` に切り出して、ここで全組み合わせを流す。

出典（実機の表）: docs/hardware/decisions/2026-08-16-led-state-table.md
作りは既存の tools/test_encoder_gated.py と同じ（cc → ctypes）。
"""

import ctypes as C
import itertools
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# status_led_core.h の enum と同じ並び
ACTIVE, IDLE_ACT, SLEEP = 0, 1, 2
UNBONDED, DISCONNECTED, CONNECTED = 0, 1, 2
BOOT, RECOVERED, BATT_REPLACE, BATT_LOW, LINK_LOST, IDLE = range(6)
OFF, BLUE, AMBER, GREEN = range(4)


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("C コンパイラが無い")
    so = tmp_path_factory.mktemp("slc") / "libslc.so"
    subprocess.run(
        [cc, "-shared", "-fPIC", "-std=c11", "-o", str(so),
         str(ROOT / "tools/stick_pod/slc_wrap.c")],
        check=True,
    )
    L = C.CDLL(str(so))
    L.slc_state_of.restype = C.c_int
    L.slc_announce_of.restype = C.c_int
    return L


def state(lib, activity=ACTIVE, booting=False, pct=100,
          has_split=True, split=CONNECTED, has_host=True, host=CONNECTED):
    return lib.slc_state_of(activity, int(booting), pct,
                            int(has_split), split, int(has_host), host)


def announce(lib, st, a):
    out = C.c_int()
    r = lib.slc_announce_of(st, a, C.byref(out))
    return r, out.value


# --- 1 段目: 優先順位 ---------------------------------------------------

def test_sleep_turns_everything_off(lib):
    """**sleep のときだけ消す。**電池が切れかけていても消す。"""
    assert state(lib, activity=SLEEP, pct=1, split=UNBONDED) == IDLE


def test_idle_does_not_hide_the_warning(lib):
    """⚠️ **idle では消さない。**

    idle は 30 秒無操作で入るので、ここで消すと未接続の警告が
    30 秒で勝手に消える（2026-08-16 に利用者の指摘で直した）。
    **この検査が無いと、同じ後退に誰も気づけない。**
    """
    assert state(lib, activity=IDLE_ACT, split=DISCONNECTED) == LINK_LOST


def test_boot_wins_over_battery_and_links(lib):
    assert state(lib, booting=True, pct=1, split=UNBONDED, host=UNBONDED) == BOOT


def test_battery_replace_wins_over_low(lib):
    """5% 以下は「要交換」。15% 以下の「低下」より先。"""
    assert state(lib, pct=5) == BATT_REPLACE
    assert state(lib, pct=6) == BATT_LOW
    assert state(lib, pct=15) == BATT_LOW
    assert state(lib, pct=16) == IDLE


def test_battery_wins_over_link_lost(lib):
    assert state(lib, pct=1, split=UNBONDED) == BATT_REPLACE


def test_connected_is_dark(lib):
    """実機どおり、全部繋がっていれば消灯。"""
    assert state(lib) == IDLE


# --- 持っていないリンクを見ない（右で青が点滅した件）---------------------

def test_peripheral_never_reports_a_host_link(lib):
    """⚠️ **右（ペリフェラル）にホストとの接続は無い。**

    2026-08-16 に、この囲いを忘れて**右で青が点滅し続けた。**
    `has_host_link=False` なら、host が何であれ LINK_LOST にしない。
    """
    for h in (UNBONDED, DISCONNECTED, CONNECTED):
        assert state(lib, has_host=False, host=h) == IDLE


def test_non_split_build_ignores_split_link(lib):
    for s in (UNBONDED, DISCONNECTED, CONNECTED):
        assert state(lib, has_split=False, split=s) == IDLE


# --- 2 段目: 復帰の合図 -------------------------------------------------

def test_announce_only_when_everything_is_connected(lib):
    """合図は「全部繋がって消灯に落ちる」ときだけ。"""
    st, left = announce(lib, IDLE, GREEN)
    assert st == RECOVERED
    assert left == GREEN  # 出すので残す（消すのは表示側）


def test_announce_is_dropped_when_something_else_shows(lib):
    """まだ他が未接続なら、そちらを優先して**合図は捨てる**。"""
    st, left = announce(lib, LINK_LOST, GREEN)
    assert st == LINK_LOST
    assert left == OFF


def test_announce_survives_recovered(lib):
    """既に RECOVERED なら捨てない（出している最中）。"""
    st, left = announce(lib, RECOVERED, BLUE)
    assert left == BLUE


def test_no_announce_means_no_change(lib):
    for st in (IDLE, LINK_LOST, BATT_LOW, BOOT):
        assert announce(lib, st, OFF)[0] == st


# --- 全組み合わせを流す -------------------------------------------------

def test_every_combination_returns_a_valid_state(lib):
    """**総当たり。**未定義の値や、落ちる組み合わせが無いこと。"""
    n = 0
    for act, boot, pct, hs, sp, hh, ho in itertools.product(
        (ACTIVE, IDLE_ACT, SLEEP), (False, True), (0, 5, 6, 15, 16, 100),
        (False, True), (UNBONDED, DISCONNECTED, CONNECTED),
        (False, True), (UNBONDED, DISCONNECTED, CONNECTED),
    ):
        r = state(lib, act, boot, pct, hs, sp, hh, ho)
        assert r in (BOOT, RECOVERED, BATT_REPLACE, BATT_LOW, LINK_LOST, IDLE), \
            f"未定義の状態 {r}"
        n += 1
    assert n == 3 * 2 * 6 * 2 * 3 * 2 * 3, f"組み合わせが足りない: {n}"
