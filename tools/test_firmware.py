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
                 "firmware/src/status_led.c",
                 "firmware/dts/bindings/sensor/hhkb,battery-alkaline.yaml"):
        assert (ROOT / path).exists(), f"{path} が無い"


def test_the_status_led_is_actually_compiled_in():
    """**設定しただけで効いていない、を防ぐ。**

    LED が光るには **3 つが揃わないといけない**:
      1. firmware/src/status_led.c がある
      2. CMakeLists.txt が CONFIG_HHKB_STATUS_LED で**それを足している**
      3. シールドの .conf が =y にしている

    どれが欠けても**ビルドは通り、CI は緑のまま、LED だけ死ぬ**。
    2 を書き忘れる形は、この案件で battery_alkaline.c でも起きかけた。

    **実際にビルドが通るか**（led0 のエイリアスが実在するか・ヘッダ名・
    リンク）は手元では見られない。GitHub Actions の ZMK ビルドが唯一の確認。
    """
    cmake = (ROOT / "firmware/CMakeLists.txt").read_text()
    assert "CONFIG_HHKB_STATUS_LED" in cmake, \
        "CMakeLists.txt が status_led.c を足していない（=y にしても光らない）"
    assert "src/status_led.c" in cmake

    assert "config HHKB_STATUS_LED" in (ROOT / "firmware/Kconfig").read_text(), \
        "Kconfig に symbol が無いと、.conf の =y は無言で捨てられる"

    # **本番と、実際に試す治具の両方**で有効になっていること。
    for shield, names in (
            ("hhkb_split", ("hhkb_split_left.conf", "hhkb_split_right.conf")),
            ("proto_split", ("proto_split_left.conf", "proto_split_right.conf")),
    ):
        for name in names:
            conf = ROOT / "config/boards/shields" / shield / name
            assert "CONFIG_HHKB_STATUS_LED=y" in conf.read_text(), \
                f"{name} で LED が有効になっていない"


def test_the_status_led_uses_only_public_zmk_api_for_peripheral_state():
    """**左手が右手の接続状態を、公開 API から取っていること。**

    central.c の peripherals[] は static で、zmk/split/central.h にも
    接続状態を返す関数は無い。使えるのは transport 層の
    get_status() だけで、これは STRUCT_SECTION_ITERABLE_NAMED 経由で
    列挙できる（2026-08-16 に上流を読んで確定）。

    **内部実装に手を伸ばすと、ZMK の更新で無言で壊れる。**
    ここが変わったら、決定記録を読み直すこと。
    """
    src = (ROOT / "firmware/src/status_led.c").read_text()
    assert "STRUCT_SECTION_FOREACH(zmk_split_transport_central" in src, \
        "左手が右手の接続状態を取る経路が変わっている"

    # **コメントを外してから見る。**この方針は文章でも説明しているので、
    # 素朴に grep すると自分の解説文に当たって落ちる（実際に落ちた）。
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    assert "peripherals[" not in code, \
        "central.c の内部 static に触っている（公開 API ではない）"


def test_the_peripheral_never_reports_a_host_connection():
    """**右にホストとの接続は無い。無いものを未接続として警告しない。**

    2026-08-16 に実機で露見。`if (!host_connected)` を役割で囲っておらず、
    **右でも評価されていた。**host_connected を更新するのはセントラル側の
    コードだけなので、右では永久に false のまま
    ＝ **キーが打てているのに青が点滅し続けた。**

    「左右で同じソースを使う」と決めた以上、**片側にしか無い概念は
    必ず #if で囲う**。囲い忘れは「変数が既定値のまま使われる」という
    静かな壊れ方をする（ビルドは通る・CI も緑）。
    """
    src = (ROOT / "firmware/src/status_led.c").read_text()
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)

    # host_connected を読み書きする行は、すべて CENTRAL の #if の中にあること。
    # #if / #endif の入れ子を追い、「いま ROLE_CENTRAL の中か」を持つ。
    stack = []  # 各 #if が ROLE_CENTRAL を条件に含むか
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("#if"):
            stack.append("ZMK_SPLIT_ROLE_CENTRAL" in s)
        elif s.startswith("#endif"):
            if stack:
                stack.pop()
        elif "host_connected" in s:
            assert any(stack), (
                f"host_connected が役割の #if の外にある: {s!r}\n"
                "右でも評価され、永久に false のまま青が点滅し続ける")


def test_an_unusable_transport_counts_as_disconnected():
    """**「分からない」を「繋がっている」に倒さないこと。**

    2026-08-16 に実機で出たバグ。get_status() の available / enabled が
    偽のときに `continue` していたため、見るべき transport が 1 つも
    残らず、関数末尾の `return true`（＝全部繋がっている）に落ちていた。
    **右の電源を切っても左の緑が出ない**という形で露見した。

    available は「まだ settings が読めていない」、enabled は「止めている」で、
    **どちらも『繋がっている』ではない。**警告灯は安全側（未接続）に倒す。

    ここは「実機で 1 回踏んだ」ものなので、形で固定しておく。
    """
    src = (ROOT / "firmware/src/status_led.c").read_text()
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)

    # 左右とも、この判定を持っていること（片方だけ直すのを防ぐ）
    guards = re.findall(r"if\s*\(!st\.available\s*\|\|\s*!st\.enabled\)\s*\{([^}]*)\}", code)
    assert len(guards) == 2, (
        f"available/enabled の判定が {len(guards)} 箇所しかない。"
        "左（central）と右（peripheral）の両方に要る")

    # **1 箇所でも continue に戻したら落ちること**（この検査自体を
    # 故意に壊して確かめた。全件を個別に見ないと片側の退行を見逃す）
    for i, body in enumerate(guards):
        assert "continue" not in body, (
            f"{i + 1} 箇所目が continue。これは 2026-08-16 のバグそのもので、"
            "『判定材料なし』が『繋がっている』になる")
        assert "return false" in body, (
            f"{i + 1} 箇所目が未接続へ倒していない")


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
