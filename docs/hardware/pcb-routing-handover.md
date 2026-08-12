# 基板の配線 — 現状と経緯

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
.venv/bin/pytest tools -q        # 402 件（約 14 分）
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

→ `J_DB` とその玉突きで `C_BULK` / `C_MCU` をダイオードの隙間へ移した。

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

## 取付穴（2026-08-12 に足した。**配線の制約が 1 つ増えた**）

**本体基板に取付穴がある**（左 6・右 8・φ2.2 / M2）。open-gaps #36。
それまで本体基板には**固定具が 1 つも無く**、保持はスイッチ 54 本のピンの
摩擦だけだった（スイッチを抜くとソケットのはんだに剥離力がかかる）。
プレートの裏から柱が降りてきて、基板を下から M2 で締める。

位置は `tools/interface.py` の `PCB_MOUNT_POSITIONS`。**手で決めない。**
次の 4 つを**同時に**満たす場所しか使えない:

| 条件 | 何で見ているか |
|---|---|
| 基板の縁から 1.0mm 内側 | `test_the_pcb_is_actually_fastened_to_the_plate` |
| **キーとプレート開口**に当たらない | 同上（`find_mounts.keepout_boxes`） |
| **実装部品**に当たらない | 同上（`pcb_parts.json` の bbox） |
| **コートヤード**に当たらない | DRC（`Courtyards overlap`） |

⚠️ **この 4 つを別々に確かめて 3 往復した**（2026-08-12）。コートヤードだけ
見て置いたらキーに当たり、キーを避けたらコートヤードに当たった。
**穴を動かしたら `gen_pcb → autoroute → drc` をやり直すこと。**

⚠️ **配線が通らないからといって穴を減らさないこと**（利用者の指示）。
位置を工夫する。現に左 6・右 8 のまま DRC 0 で通っている。

---

## 機械で守っていること

| 検査 | 守るもの |
|---|---|
| `test_the_ground_plane_is_not_cut_by_routing` | **`In1.Cu` に配線 0 本。**保護を外すと左 38・右 65 本引かれる。**DRC は何も言わない** |
| `test_every_ground_pad_reaches_the_plane` | GND パッドの脇にビア。外すと未配線が左 6・右 7 件 |
| `test_the_electronics_fit_inside_their_band` | 帯 9.25mm からのはみ出し。走査の正解は `circuit.py` の宣言から導く |
| `test_the_board_declares_the_netclass_used_for_routing` | **自動配線器はネットクラスしか見ない。**既定値頼みにしない |
| `test_the_routing_was_made_from_the_current_placement` | 配置を変えたのに配線し直していない状態 |
| `test_the_ffc_cable_reaches_the_daughterboard` | FFC が子基板まで届くこと。**部品を動かすと黙って届かなくなる** |
| `test_both_halves_can_use_the_same_ffc_cable` | 左右で同じケーブルが使えること（部品表を 2 種類にしない） |

いずれも**故意に壊して落ちることを確認してから**足した。

---

## 配線の質（手書き → Freerouting）

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

**`F.Cu` は 0 本。**信号は `In2.Cu` と `B.Cu` で足りている。4 層をやめられる
という意味ではない（`In1.Cu` の GND ベタは分割の 2.4GHz のために残す）が、
部品が増えても入る余地がある。

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
