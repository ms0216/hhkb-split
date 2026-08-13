# 基板の配線 — 現状と経緯

## ✅ 2026-08-13 — 回路レビュー 8 件、対応完了

熟練エンジニアの指摘 8 件（回路図・2 層化・GND ベタ・GND ビア・
スティッチングビア・パスコン配置・バルクコン検証・電源ライン太さ）を
すべて反映済み（コミット履歴・[open-gaps #37](open-gaps.md) 参照）。
その過程で **74LVC595（左 U1・右 U1/U2）と D_PWR にネットが 1 本も
付いていない**という致命的欠陥が見つかり、直した。

> **「DRC 0・未配線 0」は、回路が正しいことの根拠にならない。**
> ネットの付いていないパッドは、繋ぐ相手が居ないので**「未配線」に
> 数えられない」**。この欠陥に対して DRC も未配線カウントも完全に無力だった。

回路図（`tools/gen_sch.py`）と ERC、そして**回路図と基板の netlist を
突き合わせる検査**（`tools/test_schematic.py`）を導入して塞いだ。
**発注前の正しい順序は「回路図 → ERC → アートワーク → DRC」。**

**この文書の下は、2026-08-08 頃（手書きルータ → Freerouting 移行時、
基板がまだ 4 層だった時期）に書かれたまま、2026-08-12 の 2 層化
（指摘 2/3）を経て更新されていなかった。**`In1.Cu`（GND 専用の内層）
への言及は、2 層化後は「両面（F.Cu・B.Cu）の GND ベタ」に読み替える
こと。数値（違反件数・ビア数・配線総長）は 4 層時代の実測のままなので、
**2 層化後の値ではない。**最新の値は `pcb/drc_left.json` /
`pcb/drc_right.json` と、この節の上にある「いまの状態」の表を見ること。

## いまの状態

| | 違反 | 未配線 |
|---|---|---|
| 本体基板 左 | **0** ✅ | **0** ✅ |
| 本体基板 右 | **0** ✅ | **0** ✅ |
| 子基板 | **0** ✅ | **0** ✅ |

`tools/test_pcb.py` の `WIP_BOARDS` は空。DRC の検査が skip ではなく
PASS で通っている。

```
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9
"$KPY" tools/gen_pcb.py          # 未配線の基板を pcb/unrouted/ に出す
"$KPY" tools/autoroute.py        # Freerouting で配線（数分）
.venv/bin/python3 tools/drc.py   # 確かめる
.venv/bin/pytest tools -q        # 258 件
```

Java（`brew install openjdk`）と Freerouting v2.3.0 の jar
（`~/.local/share/freerouting/`。`FREEROUTING_JAR` で変更可）が要る。
**CI では走らせない。**DRC と同じく手元専用で、CI は記録の鮮度だけ見る。

---

## 役割分担

```
tools/gen_pcb.py     配置・ネット・ゾーン・設計規則（配線は持たない）
      ↓  pcb/unrouted/hhkb_split_{half}.kicad_pcb
tools/autoroute.py   DSN → Freerouting → SES → ゾーン塗り直し
      ↓  pcb/hhkb_split_{half}.kicad_pcb
tools/drc.py         ハッシュつきで記録
```

例外は**決まりきった局所配線**の 2 つだけ。どちらも経路に選択の余地が無く、
自動配線器に任せると却って悪くなる。DSN からはネットごと外し、配線材は
`(type protect)` で「避けるべき障害物」として渡す。

| | |
|---|---|
| スイッチ → ダイオード | `gen_pcb.prewire_switch_diode`。裏面の L 字 2 本。ビア 0 |
| GND のパッド → ベタ | `tools/gnd_fanout.py`。パッドの長軸方向へビア 1 個 |

---

## 手書きルータをやめた理由

**「残りは引き回しの微調整」という診断が誤っていた。**

- `ROW4` と `ROW1` のような**任意のネット対**が短絡していた。これは経路の
  良し悪しではなく、**自分が引いた線を見ていない**ことの帰結。衝突判定を
  持つルータは構造的に出せない
- リップアップも大域的なコスト関数も無いので収束しない。25→34、24→144、
  23→36 と何度も戻した
- `SOIC-16` はコートヤード 10.49mm で、帯 9.25mm に**そもそも入らなかった**。
  位置の微調整（`-1.8`）は、どちら側にはみ出すかを選んでいただけ

設計: [2026-08-08-pcb-autoroute-design.md](../../superpowers/specs/2026-08-08-pcb-autoroute-design.md)

---

## Freerouting を通すために要った 3 つ（全部つまずいた）

### 1. `J_DB`（FFC）がダイオード列に載っていた

上段キーのダイオードは帯へ **1.75mm 食い込み、19.05mm ピッチ**で並ぶ。
帯の部品で `J_DB` だけ背が高く（7.9mm）、その x がちょうど `D3` の列だった。
短絡・コートヤード重なり・`ROW0` の未配線は**全部これ**。

→ `J_DB` とその玉突きで `C_BULK` / `C_MCU`（現 `C_RAIL`。2026-08-12 に
改名。「この基板に MCU は無い」ため） をダイオードの隙間へ移した。

**帯に部品を足すときは、ダイオード列の x を避けること。**

### 2. GND パッドがベタに届かない

GND ベタは `In1.Cu` の 1 層だけ、GND パッドは全部 `B.Cu` の SMD。
間のビアを Freerouting 任せにすると、混んだ区画で失敗する
（対応する SMD ピンの **42% しかファンアウトできなかった**）。

→ `tools/gnd_fanout.py` が配置段階に決定的に立てる。向きは**パッドの長軸**
（支配軸でやると FFC の横並びパッドで隣に刺さる。実際にやった）。

**`ImportSpecctraSES` は既存の配線を全部作り直すので、取り込みのたびに
自分で引いたものが消える**（実測: GND のビア 7 個 → 0 個）。
`autoroute.py` が上の 2 つとも立て直す。

### 3. DSN に GND を残すと Freerouting が NPE で落ちる

ピンだけ消してネット定義を残す、のような中途半端なやり方をすると
`NullPointerException` で GUI ごと落ちる。ネット定義・クラスの一覧・
plane 宣言を**まとめて**消すこと（`_strip_prewired`）。

ファンアウトの配線材は `(type protect)` に変えて、ネットを持たない
固定障害物として渡す。**消すと避けてくれない。**

---

## 機械で守っていること

| 検査 | 守るもの |
|---|---|
| `test_the_main_board_is_two_layers_with_ground_poured_on_both` | 層構成が F.Cu・B.Cu の 2 層で、**両面とも** GND ベタが実際に塗られていること（2026-08-12 の 2 層化で `test_the_ground_plane_is_not_cut_by_routing`〈`In1.Cu` に配線 0 本〉から置き換わった） |
| `test_every_ground_pad_reaches_the_plane` | GND パッドの脇にビア。外すと未配線が左 6・右 7 件 |
| `test_there_are_enough_ground_vias_to_tie_the_two_planes` | GND ビアが下限（`MIN_GND_VIAS`）以上あること（指摘 4） |
| `test_few_pieces_of_ground_copper_are_left_floating` | 浮いた GND の区画が増えていないこと（指摘 5 の番人。必達は 0 個） |
| `test_the_electronics_fit_inside_their_band` | 帯 9.25mm からのはみ出し。走査の正解は `circuit.py` の宣言から導く |
| `test_the_board_declares_the_netclass_used_for_routing` | **自動配線器はネットクラスしか見ない。**既定値頼みにしない |
| `test_the_routing_was_made_from_the_current_placement` | 配置を変えたのに配線し直していない状態 |
| `test_the_ffc_cable_reaches_the_daughterboard` | FFC が子基板まで届くこと。**部品を動かすと黙って届かなくなる** |
| `test_both_halves_can_use_the_same_ffc_cable` | 左右で同じケーブルが使えること（部品表を 2 種類にしない） |

いずれも**故意に壊して落ちることを確認してから**足した。

---

## 配線の質（手書き → Freerouting）

⚠️ **この表は 2026-08-08 頃、基板がまだ 4 層だった時期の実測。**
2 層化・GND ビア増量（指摘 4/5）後の値ではない。**現在のビア数は
GND だけで左 732 個・右 913 個**（84df0cb・86e0101 の実測）で、
この表の数値とは前提が違う。層構成の推移を示す歴史的記録として残す。

| | 左 | 右 |
|---|---|---|
| DRC 違反 | 33 → **0** | 32 → **0** |
| 総長 | 1817 → **1538mm** | 2290 → **1902mm** |
| ビア | 58 → **40** | 68 → **51** |
| 遠回りの最大 | 2.3 → **1.6** | 2.3 → **1.6** |
| `In1.Cu` の配線 | 0 → 0 | 0 → 0 |
| GND の島 | 1 → 1 | 1 → 1 |

**ビアは手書きより減った。**一度は左 68・右 111 まで増えたが、原因は
`SW*_D`（スイッチ → ダイオード）だった。数 mm の接続のために自動配線器が
内層へ往復し、左 30 個・右 62 個をそこに使っていた。**この配線は経路に
選択の余地が無い**ので `prewire_switch_diode` で自分で引き、DSN から
外した。左右の比（51/40 = 1.28）がキー数の比（34/27 = 1.26）とほぼ
一致し、非対称は規模差だけで説明がつくようになった。

**`F.Cu` は 0 本。**信号は `In2.Cu` と `B.Cu` で足りている。

**この実測が、2026-08-12 の 2 層化の根拠になった**
（[decisions/2026-08-07-four-layer.md](decisions/2026-08-07-four-layer.md)）。
当時は「4 層をやめられるという意味ではない」と判断していたが、
これは誤りだった。信号が 2 層に収まっている以上、`In1.Cu`（GND 専用の
内層）を残す理由は無く、実際にその後 2 層へ確定した。GND ベタは
両面（F.Cu・B.Cu）で受ける形に変わっている。

---

## やってはいけないこと（実際に悪化させた）

1. **接頭辞でフットプリントを走査する。**`D`／`SW`／`SW_` で拾うと
   電源部の `D_PWR`／`SW_PWR`／スライドスイッチと、61 個のダイオード・
   スイッチを巻き込む。**同じ事故が 4 回起きている。**
   `re.fullmatch(r"D\d+")` のように絞る
2. **原因を特定せずにパラメータを振る。**必ず
   `kicad-cli pcb drc --format json` で「どのネットとどのネットが、
   どこで」当たっているかを見てから動かす
3. **正規表現でコードを書き換えるとき、置換後を確認しない**

---

## 知っておくとよいこと

- **`.kicad_pcb` のバイト列は保存のたびに変わる。**KiCad が UUID を振り直し、
  フットプリントの書き出し順も変える（同じスクリプト 2 回で 11632 行の差。
  設計は完全に一致）。陳腐化の検出は `tools/boardhash.py` の指紋で行う
- **Freerouting のログの「N violations」は当てにしない。**protect にした
  ファンアウトどうしの接触を数えている。**判定は KiCad の DRC**
- **DRC の件数は実行ごとに数件ゆらぐ**（ゾーンの塗りとの兼ね合い）。
  1〜2 件の差で良否を判断しない

---

## 次にやること

1. ガーバー・BOM・CPL を出す（`kicad-cli pcb export gerbers` ほか）
2. **FFC ケーブルを決める。**`FFC_LENGTH` / `FFC_SLACK` は暫定値
   （[provisional-values](provisional-values.md)）。届くことは
   `test_the_ffc_cable_reaches_the_daughterboard` が見ている
   （左 92.1mm / 右 78.5mm 要る。100mm なら足りる）

---

## この設計で守られていること（壊さないこと）

- `tools/interface.py` は**凍結境界**。プレート・基板・ケースが共有する
- 検査は「通ること」ではなく「**効いていること**」まで見る。
  故意に壊して検出できることを確かめてから足す
- 実機と違うところは [open-gaps](open-gaps.md) に書く。
  差があること自体は悪くない。**気づけないことが悪い**
