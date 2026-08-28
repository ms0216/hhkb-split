# 発注前の結線検証（fab-checklist §6・§7 の視点 B）

板の実体から全パッドの位置とネットを抜き、外部資料（TI / Seeed / Hirose）と
ファームの dtsi に突き合わせて、証拠ページを作る。2026-08-28。

    KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9
    "$KPY" tools/fab_check/dump_pads.py       # → build/fab_check/pads.json
    .venv/bin/python3 tools/fab_check/evidence.py   # → evidence.json と注釈画像
    .venv/bin/python3 tools/fab_check/report.py     # → build/fab_check/report.html

1:1 印刷用 PDF は `kicad-cli pcb export pdf --layers "Edge.Cuts,B.Cu,F.Cu,B.Fab,F.Fab,B.SilkS,F.SilkS"`。
