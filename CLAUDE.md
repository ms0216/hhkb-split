# このリポジトリで作業するときに

HHKB Professional HYBRID Type-S（US 配列・無刻印）を**完全分割型**として
作り直すプロジェクト。基板は JLCPCB、ケースは Creality K1 Max で 3D プリント。

## まずここを読む

| | |
|---|---|
| **[docs/hardware/pcb-routing-handover.md](docs/hardware/pcb-routing-handover.md)** | **いまの作業の続き。**本体基板の引き回しが残っている |
| [docs/hardware/open-gaps.md](docs/hardware/open-gaps.md) | 実機と違うところ・未解決のもの。**差があること自体は悪くない。気づけないことが悪い** |
| [docs/hardware/decisions/](docs/hardware/decisions/) | なぜそう決めたかの記録。覆す前に読む |
| [docs/hardware/provisional-values.md](docs/hardware/provisional-values.md) | まだ実測していない値の一覧 |

## 基本方針（揺らがせない）

**HHKB オリジナルの使い勝手を極力踏襲する。** キー配列・寸法・段のずれ・
手前端の高さ・キートップの高さは実機に合わせる。交渉可能なのは打鍵感
（Topre → MX ホットスワップ）だけ。

品質とは、実機再現に加えて**ソフトの正しさ・回路の綺麗さ・ノイズ耐性**を
含む。完成品の使用者の体験を損なわないこと。

## 検証の作法（この案件で高くついた教訓）

1. **結論を書く前に測る。** 「〜のはず」と書きそうになったら、その場で測る
2. **通ったことは調べた証拠にならない。** 故意に壊して検出できることを
   確かめてから検査を足す
3. **自分の生成物どうしの一致は検証ではない。** 外部の事実と突き合わせる
4. **検査対象に入っていない部品は、検査していないのと同じ**
5. **設定しただけでは効いていない。** 実際に塗られたか・繋がったかまで見る
6. **接頭辞での走査をしない。** `D`/`SW` で拾うと電源部を巻き込む（3 回起きた）
7. **見えるものは見る。** DRC の数字が読めないときはレンダリングする

## よく使うコマンド

```
.venv/bin/pytest tools -q                      # 全検査（239 件）
.venv/bin/python3 tools/gen_case.py            # ケース・上ケース・蓋・脚
.venv/bin/python3 tools/gen_assembly.py        # 組み立て干渉（0 でなければならない）
.venv/bin/python3 tools/slice_check.py         # K1 Max でスライスできるか
.venv/bin/python3 tools/drc.py                 # 基板の DRC（記録も更新）

# 基板の生成は KiCad の Python で
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9
"$KPY" tools/gen_pcb.py
"$KPY" tools/gen_daughterboard.py
```

CI は push のたびに ZMK のビルドと全検査を走らせる。
