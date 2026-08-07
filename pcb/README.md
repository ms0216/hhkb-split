# 基板（KiCad）

## 現在の状態

| 段階 | 内容 | 状態 |
|---|---|---|
| D1 | 外形・キー配置・取付穴 | ✅ 完了。DRC 違反 0 |
| D2a | マトリクス（61キー ＋ 61ダイオード ＋ 行列のネット） | ✅ 完了。DRC 違反 0 |
| D2b | XIAO・74HC595・電源の搭載 | ⬜ 3D 実装の検討が要る（下記） |
| D3 | 配線（行・列・電源） | ⬜ |
| D4 | JLCPCB 向け出力（ガーバー・BOM・CPL） | ⬜ |

マトリクスのネットまで入っている。未配線は「まだ配線していない」だけで、
左 70 / 右 89 はパッド数 − ネット数と完全に一致する（左 108−38、右 136−47）。

### D2b でまず決めること — XIAO をどこに置くか

XIAO は基板の**裏面**に付く（表に置くとキーキャップと当たる）。ところが
USB-C は実機と同じく**背面**に出す必要があり、基板の裏の背面側には
**電池室（幅 109mm）**が横断している。左半分では電池の外側に
15mm ほどしか残らず、XIAO の 17.8mm が入らない。

取りうる案:
  1. USB-C を基板端のコネクタとして別に載せ、XIAO は空いている隅に置く
  2. 電池を左右に振り分けて中央を空ける（ケースの作り直しが要る）
  3. USB の位置を実機と変える（使い勝手の方針に反するので最後）

**ケースの 3D モデルと合わせて検討する必要がある。** 実測（Task C4）で
電源部の構成が確定してから着手するのが順序として正しい。

## 生成のしかた

`pcbnew` は KiCad 同梱の Python にしか無いので、そちらで動かす。

```bash
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9 \
    tools/gen_pcb.py
```

## 検証のしかた

```bash
# デザインルール検査（違反があれば終了コードが非 0）
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb drc \
    --severity-error --exit-code-violations pcb/hhkb_split_left.kicad_pcb

# 生成物が設計値と一致するか（通常の pytest から実行できる）
python -m pytest tools/test_pcb.py

# 目で見る
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb render \
    --output /tmp/pcb.png --side top pcb/hhkb_split_left.kicad_pcb
```

`.kicad_pcb` はテキスト（S 式）なので、`tools/test_pcb.py` は pcbnew 無しで
読める。**生成した基板を読み返して、プレート・ケースと突き合わせる**のが要点。
別々に生成される以上、同じ設計値から導いていても座標変換を間違えれば静かに
ずれる。ずれたまま発注すると数万円が無駄になる。

## 寸法

| | 左 | 右 |
|---|---|---|
| 基板 | 140.36 × 102.00mm | 173.70 × 102.00mm |
| スイッチ | 27 | 34 |
| スタビライザー | 2 | 2 |
| 取付穴 | 7 | 7 |

外形はプレートより片側 3.0mm 小さい（`interface.PCB_INSET`）。ケースの
側壁 2.4mm の内側に収める必要があるため。

奥行 102.00mm ＝ プレート 108.00mm − 6.0mm。プレートの 108.00mm は
HHKB 実機の本体奥行そのもの。

## ライブラリ

`lib/` を参照。KiCad 標準に無い 3.00u とホットスワップソケットだけを
kiswitch から取り込み、寸法を規格値と照合してある。
