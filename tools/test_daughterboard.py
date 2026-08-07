"""子基板へ渡すケーブルの信号一覧が、ファームウェアの使うピンと一致することを守る。

XIAO を子基板へ載せると、**ファームウェアが使うピンは全部ケーブルを渡る**。
あとからピンを 1 本増やしたのにケーブルが 12 本のままだと、基板を発注してから
「その信号が届かない」と分かる。ここは目視では守れないので機械で守る。

決定の経緯は docs/hardware/decisions/2026-08-07-daughterboard.md。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIELD = ROOT / "config/boards/shields/hhkb_split"
DOC = ROOT / "docs/hardware/decisions/2026-08-07-daughterboard.md"

# xiao_spi (= SPI2) が固定で使うピン。デバイスツリーには現れないので、
# ボード定義（seeed_xiao_ble）の事実としてここに書く。
SPI_PINS = {"D8", "D10"}       # SCK, MOSI。MISO(D9) はキーボードでは使わない


def _strip(text):
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def firmware_pins():
    """シールドが使う XIAO のピンを集める。"""
    pins = set(SPI_PINS)
    for path in SHIELD.glob("*.dtsi"):
        text = _strip(path.read_text())
        # row-gpios / cs-gpios など、実際の &xiao_d 参照だけを見る
        for prop in ("row-gpios", "cs-gpios"):
            m = re.search(rf"\b{prop}\s*=?\s*(.*?);", text, re.S)
            if m:
                pins |= {f"D{n}" for n in re.findall(r"&xiao_d\s+(\d+)", m.group(1))}
    return pins


def cable_signals():
    """決定文書の表から、ケーブルに通す信号を読む。"""
    rows = re.findall(r"^\|\s*(\d+)\s*\|\s*\*{0,2}([\w.]+)\*{0,2}\s*\|",
                      DOC.read_text(), re.M)
    return {int(n): sig for n, sig in rows}


def test_the_cable_carries_every_pin_the_firmware_uses():
    """ファームが使うピンが 1 本残らずケーブルに載っていること。

    **これを外すと、そのキーの行が届かず 1 段まるごと反応しない。**
    """
    missing = firmware_pins() - set(cable_signals().values())
    assert not missing, f"ケーブルに無いピン: {sorted(missing)}"


def test_the_cable_carries_power_and_two_grounds():
    """電源と GND。GND が 2 本なのは戻り電流の経路を短くするため。"""
    sigs = cable_signals()
    assert "3V3" in sigs.values(), "電源が無い"
    assert list(sigs.values()).count("GND") == 2, "GND は 2 本"


def test_ground_sits_next_to_the_fastest_signal():
    """SCK (D8) の隣が GND であること。

    ループ面積が小さいほど放射も受信も減る。並び順は設計であって偶然ではない。
    """
    sigs = cable_signals()
    i = [k for k, v in sigs.items() if v == "D8"]
    assert i, "SCK (D8) がケーブルに無い"
    n = i[0]
    assert "GND" in (sigs.get(n - 1), sigs.get(n + 1)), \
        f"SCK は {n} 番。両隣は {sigs.get(n-1)} と {sigs.get(n+1)}"


def test_the_pin_count_matches_the_connector():
    """本数がコネクタのピン数と一致すること。"""
    sigs = cable_signals()
    assert sorted(sigs) == list(range(1, 13)), f"番号が飛んでいる: {sorted(sigs)}"
    assert "12 ピン" in DOC.read_text(), "文書のコネクタ指定と本数が食い違う"


def test_the_battery_never_reaches_the_bat_pin():
    """BAT 端子がケーブルに載っていないこと。

    **XIAO の BAT 端子はリポ用充電回路に直結している。**乾電池をつなぐと
    USB 接続時に一次電池を充電しようとして液漏れ・破裂の危険がある。
    """
    assert "BAT" not in [v.upper() for v in cable_signals().values()]
