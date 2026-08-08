# このリポジトリで作業するときに

HHKB Professional HYBRID Type-S（US 配列・無刻印）を**完全分割型**として
作り直すプロジェクト。基板は JLCPCB、ケースは Creality K1 Max で 3D プリント。

## まずここを読む

| | |
|---|---|
| **[docs/hardware/pcb-routing-handover.md](docs/hardware/pcb-routing-handover.md)** | 基板の作り方と、配線を自動配線器に移した経緯。**3 基板とも DRC 0** |
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
.venv/bin/pytest tools -q                      # 全検査（289 件）
.venv/bin/python3 tools/gen_case.py            # ケース・上ケース・蓋・脚
.venv/bin/python3 tools/gen_assembly.py        # 組み立て干渉（0 でなければならない）
.venv/bin/python3 tools/slice_check.py         # K1 Max でスライスできるか
.venv/bin/python3 tools/drc.py                 # 基板の DRC（記録も更新）
.venv/bin/python3 tools/mutate.py              # 定数を壊して検査が気づくか測る（遅い）

# 部品の区分・在庫・単価を調べる。**JLCPCB の API を直接叩ける。**
.venv/bin/python3 tools/jlcpcb_lookup.py --parts        # 記録済みの全部品
.venv/bin/python3 tools/jlcpcb_lookup.py "100uF 1206"   # 探す

# 基板の生成は KiCad の Python で
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9
"$KPY" tools/gen_pcb.py          # 未配線の基板を pcb/unrouted/ に出す
"$KPY" tools/autoroute.py        # Freerouting で配線して pcb/ に出す（数分）
"$KPY" tools/gen_daughterboard.py
"$KPY" tools/export_fab.py       # ガーバー・BOM・CPL（2 つの門を通る）
```

**部品を推測で書かないこと。**ブラウザが要ると思い込んで見積もりを 3 回外し、
在庫 0 の部品を指定しかけた。`jlcpcb_lookup.py` で必ず実データを見る。

CI は push のたびに ZMK のビルドと全検査を走らせる。
