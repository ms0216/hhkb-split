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
    L.slc_tick_of.restype = C.c_int
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

# ======================================================================
# 3 段目: 表示（色と次の tick までの ms）
#
# 2026-10-15 の監査で、**この switch が自動検査でまったく実行されていない**
# ことが分かった（3 つの表示退行を故意に入れて 32 件すべて緑だった）。
# 期待値は decisions/2026-08-16-led-state-table.md から起こす。
# ======================================================================

SLOW_MS, FAST_MS = 250, 125
PULSE_MS, PULSE_GAP_MS = 120, 280
BATT_LOW_MS, BATT_REPLACE_MS = 30000, 15000
BOOT_ON_MS, RECOVERED_ON_MS = 3000, 1000


class Render(C.Structure):
    _fields_ = [("shown", C.c_int), ("step", C.c_uint8),
                ("booting", C.c_bool), ("announce", C.c_int)]


def tick(lib, r, st, **kw):
    """1 tick 進めて (色, 次の ms) を返す。"""
    nxt = C.c_uint()
    kw.setdefault("activity", ACTIVE)
    kw.setdefault("booting", False)
    kw.setdefault("pct", 100)
    kw.setdefault("has_split", True)
    kw.setdefault("split", CONNECTED)
    kw.setdefault("has_host", True)
    kw.setdefault("host", CONNECTED)
    col = lib.slc_tick_of(C.byref(r), st,
                          kw["activity"], int(kw["booting"]), kw["pct"],
                          int(kw["has_split"]), kw["split"],
                          int(kw["has_host"]), kw["host"], C.byref(nxt))
    return col, nxt.value


def test_unbonded_blinks_four_times_a_second(lib):
    """⚠️ **4 回/秒 ＝ 未ボンド**（決定表）。速さを取り違えると、
    出荷直後に「もうペアリング済み」と読み違える。"""
    r = Render()
    _, ms = tick(lib, r, LINK_LOST, split=UNBONDED, has_host=False)
    assert ms == FAST_MS, f"未ボンドが {ms}ms（4 回/秒 = {FAST_MS}ms のはず）"


def test_bonded_but_disconnected_blinks_twice_a_second(lib):
    r = Render()
    _, ms = tick(lib, r, LINK_LOST, split=DISCONNECTED, has_host=False)
    assert ms == SLOW_MS, f"ボンド済み・未接続が {ms}ms（2 回/秒 = {SLOW_MS}ms のはず）"


def test_split_lost_is_green(lib):
    r = Render()
    col, _ = tick(lib, r, LINK_LOST, split=DISCONNECTED, has_host=False)
    assert col == GREEN, "左右間の未接続は緑"


def test_host_lost_is_blue(lib):
    r = Render()
    col, _ = tick(lib, r, LINK_LOST, has_split=False, host=DISCONNECTED)
    assert col == BLUE, "ホストの未接続は青"


def test_both_lost_alternate(lib):
    """⚠️ **両方未接続なら交互に出す。**

    片方だけ出すと、もう片方の異常が永久に見えない
    （2026-08-16 の利用者の判断）。
    """
    r = Render()
    seen = set()
    for _ in range(8):
        col, _ = tick(lib, r, LINK_LOST, split=DISCONNECTED, host=DISCONNECTED)
        if col != OFF:
            seen.add(col)
    assert seen == {GREEN, BLUE}, f"交互に出ていない（出た色: {seen}）"


def test_link_lost_toggles_on_and_off(lib):
    """点滅なので、点いたり消えたりすること。"""
    r = Render()
    cols = [tick(lib, r, LINK_LOST, split=DISCONNECTED, has_host=False)[0]
            for _ in range(4)]
    assert OFF in cols and GREEN in cols, f"点滅していない: {cols}"


def test_battery_low_blinks_once_then_rests_30s(lib):
    """橙 1 回点滅 → 30 秒休み。"""
    r = Render()
    col1, ms1 = tick(lib, r, BATT_LOW, pct=10)
    assert col1 == AMBER and ms1 == PULSE_MS
    col2, ms2 = tick(lib, r, BATT_LOW, pct=10)
    assert col2 == OFF and ms2 == BATT_LOW_MS, f"休みが {ms2}ms（{BATT_LOW_MS} のはず）"


def test_battery_replace_blinks_twice_then_rests_15s(lib):
    """⚠️ **橙 2 回点滅 ＝ 要交換**（1 回の「低下」と区別がつく唯一の手がかり）。"""
    r = Render()
    seq = [tick(lib, r, BATT_REPLACE, pct=3) for _ in range(4)]

    # ⚠️ **色の列だけでは 1 回点滅と区別できない**（変異検査で生き残った）。
    # 1 回点滅でも色は [橙, 消, 橙, 消] になる。**違うのは途中の間隔**:
    #   2 回点滅 … 橙120 / 消280  / 橙120 / 消15000
    #   1 回点滅 … 橙120 / 消15000 / 橙120 / 消15000
    # **ms の列まで突き合わせる。**
    assert seq == [(AMBER, PULSE_MS), (OFF, PULSE_GAP_MS),
                   (AMBER, PULSE_MS), (OFF, BATT_REPLACE_MS)], (
        f"2 回点滅の列になっていない: {seq}\n"
        f"（2 回点滅なら 2 発目の前は {PULSE_GAP_MS}ms。"
        f"{BATT_REPLACE_MS}ms なら 1 回点滅＝「低下」と見分けがつかない）")


def test_boot_lights_blue_then_clears_booting(lib):
    r = Render(booting=True)
    col, ms = tick(lib, r, BOOT)
    assert col == BLUE and ms == BOOT_ON_MS
    assert r.booting, "点灯しきる前に booting を降ろしている"
    col2, _ = tick(lib, r, BOOT)
    assert not r.booting, "2 tick 目で booting が降りていない"


def test_recovered_shows_the_announce_colour_then_clears(lib):
    r = Render(announce=GREEN)
    col, ms = tick(lib, r, RECOVERED)
    assert col == GREEN, "復帰の合図の色が違う"
    assert ms == RECOVERED_ON_MS
    assert r.announce == OFF, "合図を出したのに消していない（次も出てしまう）"


def test_idle_is_dark(lib):
    r = Render()
    col, ms = tick(lib, r, IDLE)
    assert col == OFF
    assert ms > 0, "消灯でも次の tick を予約すること（接続は見張る）"

