"""ファームに書いた数字が、回路の設計値とずれていないことを守る。

**ファームは手元でビルドできない**（Zephyr SDK が要る。CI の ZMK ビルドが
唯一のコンパイル確認）。だから「コードとして正しいか」はここでは見られない。

見られるのは**数字の出所が 1 つであること**で、それがこの案件で
繰り返し落とし穴になってきた形（同じ数字を 2 か所に書き、片方だけ動く）。
ゴム足の厚み・bands.py と同じ轍を、ファーム側でも踏まないようにする。
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
SHIELD = ROOT / "config/boards/shields/hhkb_split"
DTSI = SHIELD / "hhkb_split.dtsi"


def _dt_prop(name):
    m = re.search(rf"^\s*{re.escape(name)}\s*=\s*<(\d+)>", DTSI.read_text(), re.M)
    assert m, f"{DTSI.name} に {name} が無い"
    return int(m.group(1))


def test_the_empty_voltage_comes_from_the_circuit():
    """残量 0% ＝ **この回路が動かなくなる電圧**であること。

    「電池が空になる電圧」ではない。マイコン・74LVC595・マトリクス・
    ホットスワップソケットの下限のうち最も厳しいもの ＋ ショットキーの Vf で
    決まり、tools/circuit.py の BATT_V_MIN が唯一の出所。

    **ここがずれると、まだ動くのに 0% と出る（または 0% にならないまま
    ブラウンアウトする）。**後者は #25b の停止が効かないということ。
    """
    from circuit import BATT_V_MIN

    assert _dt_prop("empty-millivolts") == round(BATT_V_MIN * 1000), (
        f"dtsi の empty-millivolts {_dt_prop('empty-millivolts')} と "
        f"circuit.BATT_V_MIN {BATT_V_MIN}V が食い違っている")


def test_the_full_voltage_comes_from_the_circuit():
    """残量 100% ＝ 新品のアルカリの開路電圧（1.65V × 2 本）。"""
    from circuit import BATT_V_MAX

    assert _dt_prop("full-millivolts") == round(BATT_V_MAX * 1000), (
        f"dtsi の full-millivolts {_dt_prop('full-millivolts')} と "
        f"circuit.BATT_V_MAX {BATT_V_MAX}V が食い違っている")


def test_the_battery_gauge_is_actually_the_alkaline_one():
    """**乾電池用の残量計が実際に選ばれていること。**

    compatible を ZMK 標準へ戻すと、firmware/drivers/battery_alkaline.c は
    どこからも実体化されず、**ビルドは通るのに % はリチウムイオンの曲線に
    戻る**（＝設定しただけで効いていない、そのもの）。
    """
    text = DTSI.read_text()
    assert 'compatible = "hhkb,battery-alkaline"' in text, \
        "vbatt の compatible が hhkb,battery-alkaline でない"
    assert "zmk,battery = &vbatt" in text, "chosen zmk,battery が vbatt を指していない"


def test_both_halves_use_the_state_of_charge_fetch_mode():
    """**driver が出した % を使うモードであること。**

    LITHIUM_VOLTAGE モードだと ZMK 側が自前のリチウム曲線で計算し直すので、
    driver を差し替えた意味が消える。左右とも同じでないと、
    左右で違う % が出る。
    """
    for name in ("hhkb_split_left.conf", "hhkb_split_right.conf"):
        text = (SHIELD / name).read_text()
        assert "CONFIG_ZMK_BATTERY_REPORTING_FETCH_MODE_STATE_OF_CHARGE=y" in text, \
            f"{name} に STATE_OF_CHARGE モードの指定が無い"
        assert "CONFIG_ZMK_BATTERY_REPORTING_FETCH_MODE_LITHIUM_VOLTAGE=y" not in text, \
            f"{name} がリチウムのモードを選んでいる"


def test_the_soft_off_is_enabled_on_both_halves():
    """打ち止めで止まる仕組みが、左右とも積まれていること（#25b）。

    `HHKB_LOW_BATTERY_SOFT_OFF` は `ZMK_PM_SOFT_OFF` に依存しているので、
    それが無いと**黙って機能ごと消える**。
    """
    for name in ("hhkb_split_left.conf", "hhkb_split_right.conf"):
        text = (SHIELD / name).read_text()
        assert "CONFIG_ZMK_PM_SOFT_OFF=y" in text, \
            f"{name} に CONFIG_ZMK_PM_SOFT_OFF=y が無い（#25b が消える）"


def test_this_repository_is_registered_as_a_zmk_module():
    """`zephyr/module.yml` が無いと、firmware/ は**まるごとビルドされない**。

    ZMK 公式の再利用ワークフローは、これがあるときだけ
    `-DZMK_EXTRA_MODULES=<リポジトリ直下>` を付ける。
    消えると driver も停止機能も静かに消え、ビルドは緑のまま。
    """
    import yaml

    mod = yaml.safe_load((ROOT / "zephyr/module.yml").read_text())
    assert mod["build"]["cmake"] == "firmware"
    assert mod["build"]["kconfig"] == "firmware/Kconfig"
    assert mod["build"]["settings"]["dts_root"] == "firmware", \
        "dts_root が無いと hhkb,battery-alkaline のバインディングが見つからない"
    for path in ("firmware/CMakeLists.txt", "firmware/Kconfig",
                 "firmware/drivers/battery_alkaline.c",
                 "firmware/src/low_battery_off.c",
                 "firmware/dts/bindings/sensor/hhkb,battery-alkaline.yaml"):
        assert (ROOT / path).exists(), f"{path} が無い"


def test_the_zmk_config_validator_passes():
    """ZMK 設定の静的検査（check_zmk_config.py）が通ること。

    この検証器は shields_list_contains の綴りずれなど**ビルドが無言で
    無視する失敗**を捕まえるために書かれたのに、どこからも呼ばれておらず、
    settings_reset（ZMK 本体のシールド）を誤検出して exit 1 のまま
    放置されていた（2026-08-13 に発見）。検査対象に入っていない検査器は、
    無いのと同じ。ここで毎回回す。
    """
    import contextlib
    import io

    import check_zmk_config

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = check_zmk_config.main()
    assert rc == 0, buf.getvalue()
