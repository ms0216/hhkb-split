"""左手のエンコーダの小さな帯（ユニバーサル基板 6×4 穴・15.2×10.2mm）。検査と図は pod_layout.py の道具を借りる。

  .venv/bin/python3 build/joystick/pod_layout/left_layout.py

載せるもの: プルアップ 2 本（A 相・B 相 → 3V3）、押し込みのダイオード、雑音よけのコンデンサ 2 個（**最初は付けない**。
B 相がばたついてスリープに入れないときだけ足す）。ダイオードは**帯のある側がカソード＝行 4（XIAO D5）の側**。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import pod_layout as L

L.ROWS, L.COLS, L.PINS, L.JUMPERS, L.UNUSED_PINS = 4, 6, {}, [], set()
L.PARTS = {
    "Rpu_A": ("100kΩ", ((0, 0), (1, 0)), "hair"),
    "Rpu_B": ("100kΩ", ((0, 3), (1, 3)), "hair"),
    "Ca":    ("1nF※", ((2, 0), (3, 0)), "cap"),
    "Cb":    ("1nF※", ((2, 3), (3, 3)), "cap"),
    "D":     ("BAT43", ((1, 4), (1, 5)), "diode"),      # 足 1 = アノード（スイッチ側）、足 2 = カソード（行 4 の側）
}
L.WIRES = {
    (0, 1): ("XIAO", "3V3"), (2, 1): ("XIAO", "D4 (A 相)"), (2, 2): ("XIAO", "D9 (B 相)"), (3, 2): ("XIAO", "GND"), (0, 5): ("XIAO", "D5 (行 4)"),
    (1, 1): ("エンコーダ", "A"), (1, 2): ("エンコーダ", "B"), (3, 1): ("エンコーダ", "C"), (0, 4): ("エンコーダ", "スイッチの端子 1"),
}
L.CHAINS = [
    [(0, 0), (0, 1), (0, 2), (0, 3)],                 # 3V3
    [(1, 0), (1, 1), (2, 1), (2, 0)],                 # A 相
    [(1, 3), (1, 2), (2, 2), (2, 3)],                 # B 相
    [(3, 0), (3, 1), (3, 2), (3, 3)],                 # GND
    [(0, 4), (1, 4)],                                 # スイッチ → ダイオードのアノード
    [(1, 5), (0, 5)],                                 # カソード → 行 4
]
L.EXPECT = {
    "3V3": {"Rpu_A.1", "Rpu_B.1", "線:XIAO:3V3"},
    "A":   {"Rpu_A.2", "Ca.1", "線:XIAO:D4 (A 相)", "線:エンコーダ:A"},
    "B":   {"Rpu_B.2", "Cb.1", "線:XIAO:D9 (B 相)", "線:エンコーダ:B"},
    "GND": {"Ca.2", "Cb.2", "線:XIAO:GND", "線:エンコーダ:C"},
    "SW":  {"D.1", "線:エンコーダ:スイッチの端子 1"},
    "ROW4": {"D.2", "線:XIAO:D5 (行 4)"},
}
L.COLORS = {"3V3": "#d62728", "A": "#1f77b4", "B": "#2ca02c", "GND": "#444444", "SW": "#17becf", "ROW4": "#9467bd"}
L.TITLE = "左手のエンコーダの帯（ユニバーサル基板 6×4 穴・15.2×10.2mm）"
L.KEY = "● 黄 = XIAO へ行く線   ● 緑 = エンコーダへ行く線   太い色帯 = はんだブリッジ（はんだ面）   橙 = 抵抗  水色 = コンデンサ（※最初は付けない）  灰 = ダイオード"
L.LEGEND = "網の色: 赤 3V3／青 A 相／緑 B 相／灰 GND\n水色 スイッチ／紫 行 4\nダイオードは帯の印（カソード）を\n「XIAO D5 へ行く線」の側（この図の右）へ\nエンコーダのスイッチの端子 4 は、帯を通さず\n「5」のキーのソケットの「キーの列の側」のパッドへ直接"

errs, risky, find = L.check()
for e in errs: print("NG", e)
print("検査:", "問題なし" if not errs else f"{len(errs)} 件")
if errs: sys.exit(1)
out = Path(__file__).parent
L.draw(find, out / "left_layout_parts_side.png"); L.draw(find, out / "left_layout_solder_side.png", solder_side=True)
print("図:", out / "left_layout_parts_side.png")
