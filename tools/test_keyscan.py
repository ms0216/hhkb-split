"""キースキャン方式と行列対応表が壊れていないことを守る。

基板を発注したあとで matrix-transform を間違えていたと分かると、
41 キーぶんの配線がすべて無駄になる。ここは目視では守れないので機械で守る。

方式そのものも固定する。チャープレックスへ戻すのは禁止（理由は
docs/hardware/decisions/2026-08-07-keyscan.md）。nRF52840 の 3.3V では
ダイオードの電圧降下だけでゴーストを消せないため、Shift や Ctrl との
同時押しが誤検出されうる。
"""

import re
from pathlib import Path

import pytest

SHIELD = Path(__file__).resolve().parent.parent / "config/boards/shields/hhkb_split"
DTSI = SHIELD / "hhkb_split.dtsi"
KEYMAP = SHIELD / "hhkb_split.keymap"
LEFT = SHIELD / "hhkb_split_left.overlay"
RIGHT = SHIELD / "hhkb_split_right.overlay"

LEFT_KEYS, RIGHT_KEYS = 27, 34
LEFT_COLS, RIGHT_COLS = 6, 9
ROWS = 5


def _strip(text):
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def _map_entries():
    body = re.search(r"map\s*=\s*<(.*?)>\s*;", DTSI.read_text(), re.S).group(1)
    return [(int(r), int(c))
            for r, c in re.findall(r"RC\(\s*(\d+)\s*,\s*(\d+)\s*\)", _strip(body))]


def _gpio_count(path, prop):
    text = _strip(path.read_text())
    m = re.search(rf"\b{prop}\s*=?\s*(.*?);", text, re.S)
    return len(re.findall(r"<[^>]*>", m.group(1))) if m else 0


# --------------------------------------------------------------------------
# 方式そのもの
# --------------------------------------------------------------------------

def test_keyscan_is_a_plain_diode_matrix():
    """行×列マトリクス。チャープレックスへ戻さない。

    コメントには経緯として charlieplex の語が残っているので、
    実際の compatible プロパティだけを見る。
    """
    compatibles = re.findall(r'compatible\s*=\s*"(zmk,kscan-[\w-]+)"',
                             _strip(DTSI.read_text()))
    assert compatibles == ["zmk,kscan-gpio-matrix"], compatibles


def test_diode_direction_is_col2row():
    """列が出力・行が入力。ダイオードのアノードが列側。

    逆にすると全キーが反応しない。基板のダイオード実装向きと直結する。
    """
    assert 'diode-direction = "col2row"' in DTSI.read_text()


def test_rows_are_wired_to_the_mcu_not_the_shift_register():
    """入力は MCU 直結でなければならない。

    ZMK 公式の指示。入力を MCU に繋いでおくと割り込みで起こせるので、
    常時スキャンせずに済み電池が持つ。シフトレジスタは列（出力）専用。
    """
    rows = re.search(r"row-gpios(.*?);", _strip(DTSI.read_text()), re.S).group(1)
    assert "xiao_d" in rows and "shifter" not in rows


def test_columns_come_from_the_shift_register():
    for path in (LEFT, RIGHT):
        cols = re.search(r"col-gpios(.*?);", _strip(path.read_text()), re.S).group(1)
        assert "shifter" in cols, path.name


# --------------------------------------------------------------------------
# ピン数（XIAO nRF52840 は D0..D10 の 11 本しかない）
# --------------------------------------------------------------------------

def test_row_pin_count_matches_the_physical_rows():
    assert _gpio_count(DTSI, "row-gpios") == ROWS


def test_column_counts_match_the_shift_registers():
    """左は 595 が 1 個（8 出力）、右は 2 個の数珠つなぎ（16 出力）。

    右の最上段が 9 キーあるため、右だけ 9 列要る。当初は ` を最下段の空きへ
    回して 8 列に収めていたが、物理的に最上段のキーが論理的に最下段になり、
    90mm の配線が 4 段ぶんのスイッチを横切ることになった。部品を 1 個
    足す方が配線の素直さに見合う。
    """
    assert _gpio_count(LEFT, "col-gpios") == LEFT_COLS == 6
    assert _gpio_count(RIGHT, "col-gpios") == RIGHT_COLS == 9
    assert "ngpios = <16>" in _strip(RIGHT.read_text()), "右は 595 を 2 個使う"


# --------------------------------------------------------------------------
# 行列対応表
# --------------------------------------------------------------------------

def test_transform_is_shared_and_right_half_is_offset():
    """分割の標準的な書き方。左右で別々の transform を定義しない。"""
    assert "default_transform" in DTSI.read_text()
    assert re.search(r"&default_transform\s*\{[^}]*col-offset\s*=\s*<6>",
                     _strip(RIGHT.read_text()), re.S)
    assert "col-offset" not in _strip(LEFT.read_text())


def test_every_key_has_exactly_one_matrix_position():
    entries = _map_entries()
    assert len(entries) == LEFT_KEYS + RIGHT_KEYS
    assert len(set(entries)) == len(entries), "同じ位置に 2 キー割り当てている"


def test_positions_stay_inside_the_declared_matrix():
    for r, c in _map_entries():
        assert 0 <= r < ROWS
        assert 0 <= c < LEFT_COLS + RIGHT_COLS


def test_left_and_right_occupy_their_own_columns():
    """左が列 0..5、右が列 6..13。重なるとキーが入れ替わる。"""
    entries = _map_entries()
    left, right = entries[:LEFT_KEYS], entries[LEFT_KEYS:]
    assert all(c < LEFT_COLS for _, c in left)
    assert all(LEFT_COLS <= c for _, c in right)


def test_right_half_local_columns_fit_its_own_shift_register():
    """右半分は基板上では列 0..7。col-offset を引いて確かめる。"""
    right = _map_entries()[LEFT_KEYS:]
    local = [c - LEFT_COLS for _, c in right]
    assert min(local) == 0
    assert max(local) == RIGHT_COLS - 1


def test_bindings_match_the_transform_in_every_layer():
    text = _strip(KEYMAP.read_text())
    layers = re.findall(r"(\w+)\s*\{[^{}]*?bindings\s*=\s*<(.*?)>\s*;", text, re.S)
    assert layers, "キーマップからレイヤーを読めなかった"
    for name, body in layers:
        assert len(re.findall(r"&\w+", body)) == len(_map_entries()), name


def test_matrix_rows_follow_the_physical_rows():
    """論理の行が物理の段と一致すること。

    ` を最下段へ回していた時期があり、そのせいで基板に 90mm の配線が生まれた。
    行がずれると配線が段をまたいで長くなるので、一致させておく。
    """
    right = _map_entries()[LEFT_KEYS:]
    counts = {}
    for r, _ in right:
        counts[r] = counts.get(r, 0) + 1
    assert counts == {0: 9, 1: 8, 2: 7, 3: 7, 4: 3}, \
        f"右の各段のキー数が物理配列と違う: {counts}"


# --------------------------------------------------------------------------
# キーマップと配列の対応（最も強い検証）
# --------------------------------------------------------------------------

# ラベル → 期待される ZMK のキーコード。複数ありうるものはリストで許す。
_EXPECT = {
    "Esc": "ESC", "Tab": "TAB", "Ctrl": "LCTRL",
    "Shift": ["LSHFT", "RSHFT"], "Alt": ["LALT", "RALT"],
    "Meta": ["LGUI", "RGUI"], "L-Space": "SPACE", "R-Space": "SPACE",
    "Del": "BSPC", "Enter": "RET", "-": "MINUS", "=": "EQUAL", "\\": "BSLH",
    "`": "GRAVE", "[": "LBKT", "]": "RBKT", ";": "SEMI", "'": "SQT",
    ",": "COMMA", ".": "DOT", "/": "SLASH", "Fn": "mo FN",
}


def _base_bindings():
    text = _strip(KEYMAP.read_text())
    body = re.search(r"base_mac\s*\{[^{}]*?bindings\s*=\s*<(.*?)>\s*;",
                     text, re.S).group(1)
    found = re.findall(r"&kp (\w+)|&(\w+)\s+(\w+)", body)
    return [a or f"{b} {c}" for a, b, c in found]


def test_keymap_bindings_match_the_physical_layout():
    """キーマップの各バインディングが、配列上のそのキーと一致すること。

    **これが最も強い検証。** 他のテストは個数や範囲しか見ておらず、
    「Esc の位置に Q が割り当たっている」ような取り違えを見逃す。
    配列 JSON のキー名（外部の事実）と突き合わせる。

    実際に一度、キーの並び順を取り違えたまま基板を生成し、
    テストが揃って通ったことがある。個数の一致は正しさの証明にならない。
    """
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent))
    from layout import load_layout, split_halves
    from matrix import keymap_order

    left, right = split_halves(load_layout(
        str(_P(__file__).resolve().parent.parent / "layout/hhkb_split.json")))
    labels = ([k.label for k in keymap_order(left)]
              + [k.label for k in keymap_order(right)])
    binds = _base_bindings()
    assert len(binds) == len(labels) == LEFT_KEYS + RIGHT_KEYS

    bad = []
    for i, (label, bind) in enumerate(zip(labels, binds)):
        exp = _EXPECT.get(label, f"N{label}" if label.isdigit() else label.upper())
        ok = bind in exp if isinstance(exp, list) else bind == exp
        if not ok:
            bad.append(f"[{i}] 配列の {label!r} にバインド {bind!r}（期待 {exp!r}）")
    assert not bad, "キーマップと配列がずれている:\n  " + "\n  ".join(bad)


def test_fn_layer_puts_the_system_layer_on_ctrl():
    """FN レイヤーの Ctrl の位置に &mo SYS があること。

    HHKB の Fn+Ctrl を再現する仕掛け。位置がずれると、意図しないキーで
    Bluetooth 切替に入ってしまう。
    """
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent))
    from layout import load_layout, split_halves
    from matrix import keymap_order

    left, _ = split_halves(load_layout(
        str(_P(__file__).resolve().parent.parent / "layout/hhkb_split.json")))
    idx = [k.label for k in keymap_order(left)].index("Ctrl")

    text = _strip(KEYMAP.read_text())
    body = re.search(r"\bfn\s*\{[^{}]*?bindings\s*=\s*<(.*?)>\s*;", text, re.S).group(1)
    binds = re.findall(r"&\w+(?:\s+\w+)*", body)
    assert binds[idx].split()[0:2] == ["&mo", "SYS"], \
        f"FN レイヤーの Ctrl の位置（{idx}）が {binds[idx]!r} になっている"
