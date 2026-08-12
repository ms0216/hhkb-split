"""部品が「実物の形」か「場所取りの箱」か。**ここが唯一の出どころ。**

⚠️ **この一覧は blend_assembly.py に手書きで置いてあった。**部品を足すのは
gen_assembly.py なのに分類は別ファイル——**片方だけ直る。**
2026-08-12 に `rear_lid` と `sw_pwr` で 2 回続けて踏んだ（実形状なのに
「箱」のコレクションへ入り、利用者が開いた実形状側に現れなかった）。

⚠️ **gen_assembly.py に置くのも駄目だった。**`blend_assembly.py` は
**Blender の Python** で動くので `build123d` が無く、gen_assembly を
import した瞬間に `ModuleNotFoundError` で落ちる。**.blend の生成が
丸ごと止まった**（2026-08-12。しかも `>/dev/null` で握り潰していたので
「出し直しました」と報告してしまった）。

→ **依存を持たないこのファイルに置く。**母艦の Python でも Blender の
Python でも読める。`test_every_part_declares_its_shape_kind` が、
build_assembly の返す部品すべてに行があることを見る。

**名前は 2 系統ある。**build_assembly の部品名（`foot0` / `foot1`）と、
Blender 側の種類名（STL の名前から数字を落とした `foot`）。
**両方を入れておく**——落とすと、その部品が箱の側へ回る。
"""

REAL_SHAPE = {
    "case", "topcase", "plate", "rear_lid",
    "foot", "foot0", "foot1",          # Blender 側は数字を落とした名前で来る
    "screws", "inserts", "nut", "rubber", "sw_pwr",
    "pcb_real", "db_real", "pcb_parts", "db_parts",
    "batt",            # 円柱 2 本が実形状（電極 2 箇所だけ箱のまま。dee89db）
    "switches_real",   # kiswitch SW_Cherry_MX_Plate（爪・ステム・ピン・LED窓）
}

BOX_SHAPE = {
    "pcb", "db", "xiao", "sockets", "switches", "keycaps", "stabs",
    "ffc", "usb_plug",
}
