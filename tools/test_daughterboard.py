"""子基板へ渡すケーブルの信号一覧が、ファームウェアの使うピンと一致することを守る。

XIAO を子基板へ載せると、**ファームウェアが使うピンは全部ケーブルを渡る**。
あとからピンを 1 本増やしたのにケーブルが 12 本のままだと、基板を発注してから
「その信号が届かない」と分かる。ここは目視では守れないので機械で守る。

決定の経緯は docs/hardware/decisions/2026-08-07-daughterboard.md。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIELD = ROOT / "config/boards/shields/hhkb_split"
DOC = ROOT / "docs/hardware/decisions/2026-08-07-daughterboard.md"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import daughterboard_netlist  # noqa: E402

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


def _mcu_pins():
    """XIAO のピン名 → ネット名。"""
    return next(p for r, _, p in daughterboard_netlist() if r == "U_MCU")


def cable_signals():
    """ケーブルに通す信号。番号 → ネット名。

    **出所は circuit.py。**以前はここが決定文書の表を読んでいた。
    文書は自己完結して正しく見えるので、**この 4 件は誤った表を相手に
    通り続けていた**（表は 12 本すべてが旧い並び順のままだった）。
    文書とファームを突き合わせても、基板を作っているのは circuit.py なので
    何も守っていなかった。文書と circuit.py の照合は
    test_circuit.test_the_cable_pinout_table_matches_the_circuit が見る。
    """
    j = next(p for r, _, p in daughterboard_netlist() if r == "J_MAIN")
    return {int(n): net for n, net in j.items()}


def firmware_nets():
    """ファームが使う XIAO のピンが載っているネット名。"""
    mcu = _mcu_pins()
    return {mcu[p] for p in firmware_pins() if p in mcu}


def test_the_cable_carries_every_pin_the_firmware_uses():
    """ファームが使うピンが 1 本残らずケーブルに載っていること。

    **これを外すと、そのキーの行が届かず 1 段まるごと反応しない。**
    """
    mcu = _mcu_pins()
    unknown = firmware_pins() - set(mcu)
    assert not unknown, f"回路が知らないピンをファームが使っている: {sorted(unknown)}"
    missing = firmware_nets() - set(cable_signals().values())
    assert not missing, f"ケーブルに無い信号: {sorted(missing)}"


def test_the_cable_carries_power_and_two_grounds():
    """電源と GND。GND が 2 本なのは戻り電流の経路を短くするため。"""
    sigs = cable_signals()
    assert "V3V3" in sigs.values(), "電源が無い"
    assert list(sigs.values()).count("GND") == 2, "GND は 2 本"


def test_ground_sits_next_to_the_fastest_signal():
    """SCK の隣が GND であること。

    ループ面積が小さいほど放射も受信も減る。並び順は設計であって偶然ではない。

    **両端が GND でないことは承知の上。**1 番は CS。配線の交差を避ける
    制約が先に決まり、両端 GND にすると交差が戻る。CS は 1 スキャンに
    1 回しか動かないので端に置く害が最も小さい。
    """
    sigs = cable_signals()
    n = next((k for k, v in sigs.items() if v == "SPI_SCK"), None)
    assert n is not None, "SCK がケーブルに無い"
    assert "GND" in (sigs.get(n - 1), sigs.get(n + 1)), \
        f"SCK は {n} 番。両隣は {sigs.get(n - 1)} と {sigs.get(n + 1)}"


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
    bat = _mcu_pins()["BAT"]
    assert bat == "NC", f"BAT 端子に {bat} が繋がっている"
    assert bat not in cable_signals().values(), "BAT の信号がケーブルに載っている"


def test_the_connector_spec_matches_the_board():
    """文書に書いたコネクタの仕様が、実基板のフットプリントと一致すること。

    **文書は「1.0mm ピッチ・12 本が 12mm」と書いていたが、実基板は
    最初から 0.5mm ピッチだった。**それまでの検査は本数（`"12 ピン"` と
    いう文字列）しか見ていなかったので通っていた。

    ピッチを間違えたままケーブルを買うと、届いてから挿さらないと分かる。
    """
    doc = DOC.read_text()
    m = re.search(r"\*\*(\d+) ピン・([\d.]+)mm ピッチ", doc)
    assert m, "文書のコネクタ指定（**N ピン・X.Xmm ピッチ**）が読めない"
    pins, pitch = int(m.group(1)), float(m.group(2))

    # 実基板から読む。**両方の基板を見る。**片方だけだと食い違いに気づかない。
    found = {}
    for half in ("hhkb_split_left", "hhkb_split_right", "hhkb_split_daughterboard"):
        text = (ROOT / f"pcb/{half}.kicad_pcb").read_text()
        for blk in re.split(r"\n\t\(footprint ", text)[1:]:
            ref = re.search(r'\(property "Reference" "(J_[A-Z]+)"', blk)
            if ref:
                found[f"{half}/{ref.group(1)}"] = blk.split('"')[1]
    assert len(found) == 3, f"FFC コネクタが 3 個見つからない: {sorted(found)}"

    for where, fp in found.items():
        n = re.search(r"1x(\d+)", fp)
        p = re.search(r"P([\d.]+)mm", fp)
        assert n and p, f"{where}: フットプリント名から本数とピッチが読めない ({fp})"
        assert int(n.group(1)) == pins, \
            f"{where}: 実基板は {n.group(1)} ピン、文書は {pins} ピン"
        assert float(p.group(1)) == pitch, \
            f"{where}: 実基板は {p.group(1)}mm ピッチ、文書は {pitch}mm ピッチ"


def test_the_firmware_and_the_circuit_agree_on_the_battery_divider():
    """ファームの分圧宣言が、回路の抵抗値と一致すること。

    ZMK の `zmk,battery-voltage-divider` は `output-ohms` と `full-ohms` から
    実電圧を復元する。**回路とファームで別々に書かれていて、一致を見る検査が
    無かった。**片方だけ変えても DRC も検査も通り、**残量表示だけが静かに
    狂う。**電池が空なのに 60% と出る、あるいはその逆になる。

    変異検査で `DIVIDER_R_HIGH` を 1MΩ → 1.1MΩ にしても 271 件が全部通った。
    """
    dtsi = _strip((SHIELD / "hhkb_split.dtsi").read_text())
    m = re.search(r"battery-voltage-divider[\s\S]*?output-ohms\s*=\s*<(\d+)>"
                  r"[\s\S]*?full-ohms\s*=\s*<(\d+)>", dtsi)
    assert m, "ファームに battery-voltage-divider の宣言が見つからない"
    output_ohms, full_ohms = int(m.group(1)), int(m.group(2))

    from circuit import DIVIDER_R_HIGH, DIVIDER_R_LOW

    assert output_ohms == DIVIDER_R_LOW, (
        f"ファームの output-ohms={output_ohms} が、回路の下側抵抗 "
        f"{DIVIDER_R_LOW} と違う")
    assert full_ohms == DIVIDER_R_HIGH + DIVIDER_R_LOW, (
        f"ファームの full-ohms={full_ohms} が、回路の合計 "
        f"{DIVIDER_R_HIGH + DIVIDER_R_LOW} と違う")


# **ケーブルの界面（凍結）。**
#
# アンテナの件（open-gaps #23）は発注前に直せないので、駄目だったときに
# **子基板 1 枚だけを作り直せば済む**ようにしておく。そのために、本体基板と
# ケーブルに触れる部分をここで凍結する。ここが動くと、子基板の作り直しが
# 本体基板 2 枚（発注済み）とケーブル（購入済み）まで巻き込む。
FROZEN_FOOTPRINT = "Hirose_FH12-12S-0.5SH_1x12-1MP_P0.50mm_Horizontal"
FROZEN_LAYER = "B.Cu"
FROZEN_ROTATION = 180.0
FROZEN_FROM_FRONT_EDGE = 5.0     # 子基板の前端からコネクタ中心まで（mm）


def test_the_cable_interface_is_frozen():
    """ケーブルの界面が凍結どおりであること。

    **これが手戻りの範囲を決める。**アンテナが駄目だったとき、ここが
    動いていなければ作り直すのは子基板 1 枚（21x32mm）だけで済む。
    動いていると、本体基板 2 枚とケーブルまで巻き込む。

    凍結するのは「相手がある」ものだけ。子基板の中の配置や外形は
    自由に変えてよい（ケースは 3D プリントなので作り直せる）。
    """
    import re as _re

    found = {}
    for name in ("hhkb_split_left", "hhkb_split_right", "hhkb_split_daughterboard"):
        text = (ROOT / f"pcb/{name}.kicad_pcb").read_text()
        for blk in _re.split(r"\n\t\(footprint ", text)[1:]:
            ref = _re.search(r'\(property "Reference" "(J_[A-Z]+)"', blk)
            if not ref:
                continue
            at = _re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", blk)
            lay = _re.search(r'\(layer "([^"]+)"\)', blk)
            found[f"{name}/{ref.group(1)}"] = {
                "fp": blk.split('"')[1],
                "x": float(at.group(1)), "y": float(at.group(2)),
                "rot": float(at.group(3) or 0), "layer": lay.group(1)}
    assert len(found) == 3, f"FFC コネクタが 3 個見つからない: {sorted(found)}"

    for where, d in sorted(found.items()):
        assert d["fp"] == FROZEN_FOOTPRINT, \
            f"{where}: コネクタが {d['fp']}。凍結は {FROZEN_FOOTPRINT}"
        # **面と回転はケーブルの向き（同面/対向）を決める。**買う部品が変わる。
        assert d["layer"] == FROZEN_LAYER, \
            f"{where}: {d['layer']} 面にある。凍結は {FROZEN_LAYER}"
        assert d["rot"] == FROZEN_ROTATION, \
            f"{where}: 回転 {d['rot']}。凍結は {FROZEN_ROTATION}"

    # 子基板の前端からの距離。**ケーブルの必要長がここで決まる。**
    text = (ROOT / "pcb/hhkb_split_daughterboard.kicad_pcb").read_text()
    ys = [float(b) for _a, b in
          _re.findall(r"\(gr_line[\s\S]{0,120}?\(start ([-\d.]+) ([-\d.]+)\)", text)]
    front = max(ys)                      # KiCad は Y 下向き。手前＝大きい y
    got = front - found["hhkb_split_daughterboard/J_MAIN"]["y"]
    assert abs(got - FROZEN_FROM_FRONT_EDGE) < 0.01, (
        f"子基板の前端からコネクタまで {got:.2f}mm。"
        f"凍結は {FROZEN_FROM_FRONT_EDGE}mm。ケーブルの必要長が変わる")

    # 2 つのコネクタのピン割り当てが一致すること（向きの取り違え防止）
    main = next(p for r, _k, p in _import_netlist("left") if r == "J_DB")
    db = next(p for r, _k, p in daughterboard_netlist() if r == "J_MAIN")
    assert main == db, "本体基板と子基板でケーブルのピン割り当てが違う"


def _import_netlist(half):
    from circuit import netlist
    return netlist(half)
