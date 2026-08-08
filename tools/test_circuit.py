"""回路の電気的な規則を機械で検査する（KiCad の ERC の代わり）。

**この案件で最も高くついた見落としは、すべて回路の側にあった。**
幾何には DRC と干渉検査があるのに、回路には検査が 1 つも無かった。
ここにある規則は、実際に見落とした 3 件をそれぞれ捕まえる。

  test_every_ic_has_a_decoupling_capacitor  ← パスコンの欠落
  test_there_is_a_bulk_capacitor            ← バルクの欠落
  test_the_shift_register_control_pins_are_tied ← MR/OE の浮き

規則を足すときは、**その規則が捕まえるはずの誤りを故意に作って
検出できることを確かめてから**足すこと（test_the_rules_actually_bite）。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import (  # noqa: E402
    BATT_CELLS, BATT_V_MAX, BATT_V_MIN, DIVIDER_R_HIGH, DIVIDER_R_LOW, ICS,
    IC_SUPPLY_RANGE,
    MCU_MARGIN, MCU_V_ABSMAX, MCU_V_MAX, MCU_V_MIN, POWER_NETS, SCHOTTKY_VF,
    daughterboard_netlist,
    netlist,
)

BOARDS = {
    "left": lambda: netlist("left"),
    "right": lambda: netlist("right"),
    "daughterboard": daughterboard_netlist,
}


def nets_of(parts):
    """ネット名 → [(参照名, 端子名), ...]"""
    out = {}
    for ref, _, pins in parts:
        for pin, net in pins.items():
            if net != "NC":
                out.setdefault(net, []).append((ref, pin))
    return out


# --------------------------------------------------------------------------
# 見落とした 3 件を、それぞれ捕まえる規則
# --------------------------------------------------------------------------

@pytest.mark.parametrize("board", list(BOARDS))
def test_every_ic_has_a_decoupling_capacitor(board):
    """IC の数だけ 0.1µF がある。

    74LVC595 は出力が同時に切り替わるとき電源へノイズを返す。パスコンが
    無いとそのノイズが行の入力へ回り込み、誤検出やチャタリングになる。
    ブレッドボードでは症状が出にくく、基板にしてから気づく類のもの。
    """
    parts = BOARDS[board]()
    n_ic = len([p for p in parts if p[1] in ICS])
    n_cap = len([p for p in parts if p[1] == "cap_100n"])
    assert n_cap >= n_ic, \
        f"{board}: IC が {n_ic} 個に対して 0.1µF が {n_cap} 個しかない"


@pytest.mark.parametrize("board", ["left", "right"])
def test_there_is_a_bulk_capacitor(board):
    """電源にバルク容量がある。

    アルカリ乾電池は消耗すると内部抵抗が上がる。BLE の送信は 10〜15mA の
    パルスなので、内部抵抗が上がった電池では電圧降下として現れる。
    バルクが無いと**電池を使い切る前にブラウンアウトする**。
    """
    parts = BOARDS[board]()
    assert any(p[1] == "cap_100u" for p in parts), \
        f"{board}: バルクコンデンサが無い"


@pytest.mark.parametrize("board", ["left", "right"])
def test_the_shift_register_control_pins_are_tied(board):
    """74LVC595 の MR が VCC、OE が GND に固定されている。

    浮かせると、MR はノイズで中身が消え、OE は出力が High-Z になって
    全キーが反応しない。**繋ぎ忘れても回路図上は見た目が変わらない。**
    """
    for ref, kind, pins in BOARDS[board]():
        if kind != "74LVC595":
            continue
        assert pins.get("MR") == "V3V3", f"{board} {ref}: MR が VCC に固定されていない"
        assert pins.get("OE") == "GND", f"{board} {ref}: OE が GND に固定されていない"


# --------------------------------------------------------------------------
# 安全
# --------------------------------------------------------------------------

def test_the_battery_never_reaches_the_bat_pin():
    """XIAO の BAT 端子に何も繋がっていないこと。

    **BAT 端子はリポ用充電回路に直結している。**乾電池を繋ぐと USB 接続時に
    一次電池を充電しようとして液漏れ・破裂の危険がある。
    """
    for ref, kind, pins in daughterboard_netlist():
        if kind == "xiao_nrf52840":
            assert pins.get("BAT") == "NC", f"{ref}: BAT 端子に {pins['BAT']} が繋がっている"


@pytest.mark.parametrize("board", ["left", "right"])
def test_the_battery_reaches_the_rail_only_through_the_diode(board):
    """電池が 3V3 へ直結していないこと。

    ショットキー経由でなければ、USB を挿したときに電池へ充電電流が流れる。
    """
    nets = nets_of(BOARDS[board]())
    on_rail = {ref for ref, _ in nets["V3V3"]}
    assert "D_PWR" in on_rail, f"{board}: 3V3 がショットキー経由になっていない"
    assert "BT1" not in on_rail, f"{board}: 電池が 3V3 へ直結している"
    assert "SW_PWR" not in on_rail, f"{board}: スイッチが 3V3 へ直結している"


@pytest.mark.parametrize("board", ["left", "right"])
def test_the_divider_sits_behind_the_power_switch(board):
    """電池電圧の分圧がスライドスイッチの後ろにあること。

    前に置くと、電源を切っても分圧に電流が流れ続けて電池が減る。
    """
    for ref, _, pins in BOARDS[board]():
        if ref == "R_HI":
            assert pins["1"] == "VBATT_SW", \
                f"{board}: 分圧がスイッチの手前にある（{pins['1']}）"
            return
    pytest.fail(f"{board}: 分圧抵抗が無い")


def test_the_adc_input_stays_below_the_supply():
    """分圧後の電圧が、そのときの電源電圧を超えないこと。

    超えると ADC の入力保護ダイオードに電流が流れ、測定値が狂う。
    新品の電池（1.65V/本）で最悪を見る。
    """
    v_in = BATT_V_MAX * DIVIDER_R_LOW / (DIVIDER_R_HIGH + DIVIDER_R_LOW)
    v_supply = BATT_V_MAX - SCHOTTKY_VF
    assert v_in < v_supply, f"分圧後 {v_in:.2f}V が電源 {v_supply:.2f}V を超える"


def test_the_mcu_still_runs_down_to_the_declared_cutoff():
    """打ち止めと決めた電圧まで、マイコンが動くこと。

    **この規則は初回に本物の不具合を見つけた。**当初 0.9V/本まで使い切る
    つもりで書いていたが、直列のショットキーが降下するぶん、マイコンには
    1.40V しか届かない（下限 1.7V）。打ち止めは回路で決まる。
    """
    v = BATT_V_MIN - SCHOTTKY_VF
    assert v >= MCU_V_MIN + MCU_MARGIN * 0.99, (
        f"電池 {BATT_V_MIN:.2f}V まで使うと マイコンへ {v:.2f}V しか届かない"
        f"（下限 {MCU_V_MIN}V）")


def test_the_rail_never_exceeds_what_the_mcu_can_take():
    """新品の電池でも、マイコンに入る電圧が上限を超えないこと。

    **この検査が無かった。**変異検査で `BATT_CELLS` を 2→3 に書き換えても
    271 件が全部通った。3 本なら新品で 4.95V、ショットキーを引いて 4.55V が
    XIAO の 3V3 ピン＝ nRF52840 の VDD へ直接入る（絶対最大 3.9V）。
    **一発で壊れる。**

    それまであった `test_power_is_two_aa_cells` は電池の**寸法**を見て
    いただけで、本数も電圧も見ていなかった。
    """
    v = BATT_V_MAX - SCHOTTKY_VF
    assert v <= MCU_V_MAX, (
        f"新品の電池でマイコンへ {v:.2f}V 入る。推奨上限 {MCU_V_MAX}V、"
        f"絶対最大 {MCU_V_ABSMAX}V。電池の本数か降圧を見直すこと")


def test_every_ic_runs_down_to_the_cutoff():
    """**打ち止めの電圧で、基板上のどの IC も規格内であること。**

    打ち止めをマイコンの下限 1.7V だけから計算していて、**74HC595 の
    下限 2.0V を見落としていた。**レールは打ち止めで 1.8V まで下がるので、
    シフトレジスタが規格外で動くことになっていた（列が正しく駆動されず、
    キーが反応しない）。**部品を選ぶとき「Basic かどうか」しか見ておらず、
    動作電圧の範囲を見ていなかった。**

    74LVC595（1.1〜3.6V）に替えて解いた。基板は変わらない（同じ TSSOP-16）。

    上側も見る。新品の電池でレールが IC の上限を超えないこと。
    """
    rail_min = BATT_V_MIN - SCHOTTKY_VF
    rail_max = BATT_V_MAX - SCHOTTKY_VF
    used = {kind for board in BOARDS.values() for _r, kind, _p in board()
            if kind in IC_SUPPLY_RANGE}
    assert used, "基板に IC が 1 つも無い。走査が壊れている"
    for kind in sorted(used):
        lo, hi = IC_SUPPLY_RANGE[kind]
        assert lo <= rail_min, (
            f"{kind} の下限 {lo}V に対して、打ち止めでレールが {rail_min:.2f}V "
            f"まで下がる。**規格外で動くことになる。**"
            f"打ち止めを上げるか、もっと低電圧の品種にすること")
        assert rail_max <= hi, (
            f"{kind} の上限 {hi}V に対して、新品の電池でレールが "
            f"{rail_max:.2f}V になる")


def test_the_cutoff_is_not_quietly_optimistic():
    """打ち止めが、乾電池として妥当な範囲にあること。

    ショットキーを高降下のものに替えると、気づかないうちに打ち止めが
    上がって電池がすぐ切れる。1N4007（0.7〜1.1V）に替えると 1.25V/本 で
    止まり、容量の半分近くを捨てることになる。
    """
    per_cell = BATT_V_MIN / BATT_CELLS
    assert per_cell <= 1.15, (
        f"打ち止めが {per_cell:.2f}V/本 と高すぎる。電池の容量を捨てている。"
        f"ショットキーの降下 {SCHOTTKY_VF}V を見直すこと")


def test_the_divider_current_is_negligible_against_sleep():
    """分圧に流れる電流が、スリープ電流に対して無視できること。"""
    i = BATT_V_MAX / (DIVIDER_R_HIGH + DIVIDER_R_LOW) * 1e6      # µA
    assert i < 5.0, f"分圧に {i:.1f}µA 流れる。抵抗を大きくすること"


# --------------------------------------------------------------------------
# 繋ぎ忘れ・繋ぎすぎ
# --------------------------------------------------------------------------

@pytest.mark.parametrize("board", list(BOARDS))
def test_no_net_is_left_with_a_single_pin(board):
    """1 本しか繋がっていないネットが無いこと。

    **これが繋ぎ忘れの主な現れ方。**名前を書いたのにどこにも行っていない。
    """
    lonely = {n: p for n, p in nets_of(BOARDS[board]()).items() if len(p) < 2}
    assert not lonely, f"{board}: 行き先の無いネット {lonely}"


@pytest.mark.parametrize("board", ["left", "right"])
def test_every_column_is_driven_by_exactly_one_output(board):
    """列がシフトレジスタの出力とちょうど 1 対 1 で対応すること。

    2 つの出力が同じ列に繋がると出力どうしがぶつかる（片方が High、
    もう片方が Low のとき短絡する）。
    """
    drivers = {}
    for ref, kind, pins in BOARDS[board]():
        if kind != "74LVC595":
            continue
        for pin, net in pins.items():
            if net.startswith("COL"):
                drivers.setdefault(net, []).append(f"{ref}.{pin}")
    dup = {n: d for n, d in drivers.items() if len(d) > 1}
    assert not dup, f"{board}: 同じ列を複数の出力が駆動している {dup}"

    from matrix import shape
    _, n_cols = shape(board)
    assert len(drivers) == n_cols, \
        f"{board}: 列 {n_cols} 本に対して駆動されているのは {len(drivers)} 本"


@pytest.mark.parametrize("board", ["left", "right"])
def test_the_cable_and_the_shift_registers_agree_on_the_spi_pins(board):
    """ケーブルで来る SPI が、そのままシフトレジスタへ届いていること。"""
    parts = BOARDS[board]()
    nets = nets_of(parts)
    # **種類で選ぶ。接頭辞ではない。**`"U"` で拾うのはたまたま今そう
    # 名付けているからで、部品が増えれば静かに巻き込む。
    registers = {ref for ref, kind, _ in parts if kind == "74LVC595"}
    assert registers, f"{board}: シフトレジスタが 1 個も宣言されていない"
    for net in ("SPI_SCK", "SPI_MOSI", "CS"):
        refs = {ref for ref, _ in nets[net]}
        assert "J_DB" in refs, f"{board}: {net} がケーブルに来ていない"
        assert refs & registers, \
            f"{board}: {net} がシフトレジスタに届いていない"


@pytest.mark.parametrize("board", ["left", "right"])
def test_the_chained_shift_registers_are_actually_chained(board):
    """右半分の 2 個目が、1 個目の Q7' から受けていること。"""
    parts = {ref: pins for ref, kind, pins in BOARDS[board]() if kind == "74LVC595"}
    if len(parts) < 2:
        pytest.skip("この半分はシフトレジスタが 1 個")
    assert parts["U2"]["DS"] == parts["U1"]["Q7S"] != "NC", \
        "2 個目が 1 個目の Q7' から受けていない"


def test_the_two_boards_agree_on_the_cable():
    """本体基板と子基板で、ケーブルの各線の行き先が一致すること。

    **別々に書いた表どうしを突き合わせる。**片方だけ直すと必ずここで落ちる。
    """
    main = next(p for r, k, p in netlist("left") if r == "J_DB")
    db = next(p for r, k, p in daughterboard_netlist() if r == "J_MAIN")
    assert main == db, f"ケーブルの結線が食い違っている\n本体 {main}\n子基板 {db}"


# --------------------------------------------------------------------------
# 規則そのものが効いているか
# --------------------------------------------------------------------------

def test_the_rules_actually_bite():
    """**故意に壊して、規則が検出することを確かめる。**

    通ったことは調べた証拠にならない。この案件では、誤った並び順どうしを
    突き合わせてテストが全部通ってしまった前科がある。
    """
    import circuit

    original = circuit.netlist
    checks = [
        ("パスコンを消す",
         lambda ps: [p for p in ps if p[1] != "cap_100n"],
         test_every_ic_has_a_decoupling_capacitor),
        ("バルクを消す",
         lambda ps: [p for p in ps if p[1] != "cap_100u"],
         test_there_is_a_bulk_capacitor),
        ("MR を浮かせる",
         lambda ps: [(r, k, {**p, "MR": "NC"} if k == "74LVC595" else p)
                     for r, k, p in ps],
         test_the_shift_register_control_pins_are_tied),
        ("電池を 3V3 へ直結する",
         lambda ps: [(r, k, {**p, "2": "V3V3"} if r == "SW_PWR" else p)
                     for r, k, p in ps],
         test_the_battery_reaches_the_rail_only_through_the_diode),
        ("分圧をスイッチの手前へ移す",
         lambda ps: [(r, k, {**p, "1": "VBATT_RAW"} if r == "R_HI" else p)
                     for r, k, p in ps],
         test_the_divider_sits_behind_the_power_switch),
        # 文書を写しただけの表は静かにずれる。**回路の側を動かしても
        # 落ちること**をここで確かめる（文書を壊す向きは別に確認済み）。
        ("ケーブルの 3 番を SCK から MOSI へ変える",
         lambda ps: [(r, k, {**p, "3": "SPI_MOSI"} if r == "J_DB" else p)
                     for r, k, p in ps],
         lambda _half: test_the_cable_pinout_table_matches_the_circuit()),
    ]
    missed = []
    for label, break_it, rule in checks:
        circuit.netlist = lambda half, _b=break_it: _b(original(half))
        BOARDS["left"] = lambda: circuit.netlist("left")
        try:
            rule("left")
            missed.append(label)
        except AssertionError:
            pass
        finally:
            circuit.netlist = original
            BOARDS["left"] = lambda: netlist("left")
    assert not missed, f"故意に壊しても検出できない規則がある: {missed}"


@pytest.mark.parametrize("board", list(BOARDS))
def test_no_two_parts_share_a_reference(board):
    """参照名が重複していないこと。

    **初回に本物の衝突を見つけた規則。**電源スイッチを SW1 と名づけていて、
    キースイッチの SW1 とぶつかっていた。基板上で 2 つの別部品が同じ名前に
    なると、実装機も人も取り違える。
    """
    refs = [ref for ref, _, _ in BOARDS[board]()]
    dup = {r for r in refs if refs.count(r) > 1}
    assert not dup, f"{board}: 参照名が重複している {sorted(dup)}"


def test_the_firmware_can_be_recovered_without_opening_the_case():
    """復旧手段が存在すること。

    **XIAO nRF52840 は RST を外に出していない。**裏面のパッドは
    VUSB/GND/3V3/10/9/8/7・0〜6（側面ピンの複製）と BAT +/−、NFC だけ
    （実機の写真で確認）。押しボタンを載せることはできない。

    そこで復旧はキー操作で行う。Fn+Ctrl+Esc（左）／Fn+Ctrl+6（右）。
    それも効かないほど壊れたときは上ケースの 3 本のネジを外す
    （キーキャップを外す必要は無い ＝ 上ケース方式にした効果）。
    """
    from pathlib import Path as _P
    keymap = (_P(__file__).resolve().parent.parent
              / "config/boards/shields/hhkb_split/hhkb_split.keymap").read_text()
    assert "&bootloader" in keymap, "キーからブートローダへ入れない"
    # RST が出ていない以上、子基板に押しボタンは載せない
    for ref, kind, pins in daughterboard_netlist():
        assert kind != "tact_switch", \
            "XIAO は RST を出していないので、押しボタンは繋げられない"


def test_the_cable_pinout_table_matches_the_circuit():
    """決定文書の FFC ピン表が、回路の宣言と一致していること。

    **文書の表は 12 本すべてが旧い並び順のままだった。**動作には影響が
    無かった（ファームのピン割り当ては別に合っていた）が、配線を追う人を
    確実に間違えさせる。しかも表は「両端を GND にしてある」と書いており、
    実際は 1 番が CS だった。

    写しただけの表は静かにずれる。**機械で照合する。**
    """
    import re as _re

    doc = (Path(__file__).resolve().parent.parent
           / "docs/hardware/decisions/2026-08-07-daughterboard.md").read_text()
    rows = _re.findall(
        r"^\|\s*(\d+)\s*\|\s*`([A-Z0-9_]+)`\s*\|\s*([A-Za-z0-9]+)\s*\|",
        doc, _re.M)
    assert len(rows) == 12, (
        f"文書の FFC ピン表が読めない（{len(rows)} 行しか取れなかった）。"
        "表の形を変えたなら、この検査も直すこと")

    # **BOARDS 経由で読む。**モジュール直下の netlist を掴むと、
    # test_the_rules_actually_bite の差し替えが効かない。
    j_db = next(p for r, _, p in BOARDS["left"]() if r == "J_DB")
    mcu = next(p for r, _, p in daughterboard_netlist() if r == "U_MCU")

    for num, net, xiao_pin in rows:
        assert j_db[num] == net, (
            f"FFC {num} 番: 文書は {net}、circuit.py は {j_db[num]}")
        # XIAO のピン列も照合する。**ここがずれると実配線を間違える。**
        assert mcu.get(xiao_pin) == net, (
            f"FFC {num} 番: 文書は XIAO の {xiao_pin} と書いているが、"
            f"circuit.py の {xiao_pin} は {mcu.get(xiao_pin)}（期待 {net}）")
