# 発注前の結線検証（fab-checklist §6・§7 の視点 B）

板の実体から全パッドの位置とネットを抜き、外部資料（TI / Seeed / Hirose）と
ファームの dtsi に突き合わせて、証拠ページを作る。2026-08-28。

    KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9
    "$KPY" tools/fab_check/dump_pads.py       # → build/fab_check/pads.json
    .venv/bin/python3 tools/fab_check/evidence.py   # → evidence.json と注釈画像
    .venv/bin/python3 tools/fab_check/report.py     # → build/fab_check/report.html

1:1 印刷用 PDF は `kicad-cli pcb export pdf --layers "Edge.Cuts,B.Cu,F.Cu,B.Fab,F.Fab,B.SilkS,F.SilkS"`。

## 1:1 PDF を測り直すとき（2026-08-30）

`build/fab_check/*_1to1_*.pdf` は `--scale 1`（既定）で **実寸**。300dpi に
ラスタライズして外形（Edge.Cuts）を測ると設計値と一致する:
left 138.52×97.45（設計 138.36×97.40）、daughterboard 21.08×32.09（設計 21.0×32.0）。
差の 0.1mm 弱は外形線の太さ（0.1mm）が線の外側にはみ出す分。

⚠️ **二値化のしきい値に注意。**角の円弧は細くアンチエイリアスされるので、
`< 200` で拾うと角が落ち、**left が 131×93、daughterboard が 18×30 に見えて
「1:1 でない」という誤った結論が出る**（実際に一度出した）。**`< 250` で拾うこと。**
測り方そのものは 100mm 角の合成 PDF で校正した（誤差 0.01mm）。

