# フェーズ1: 電気・ファームウェア検証 実装計画

> [!WARNING]
> **Task 2 と Task 3 はこの計画のままでは実施しない（2026-08-07）。**
>
> キースキャンをチャープレックスから「行×列マトリクス ＋ 74HC595」へ変更した。
> nRF52840 の 3.3V ではダイオードの電圧降下だけで 2 キー同時押しのゴーストを
> 消せないことが計算で判明したため。判断根拠は
> [decisions/2026-08-07-keyscan.md](../../hardware/decisions/2026-08-07-keyscan.md)、
> 差し替え後の手順は [task-c2-keyscan.md](../../hardware/task-c2-keyscan.md)。
>
> 以下の記述はチャープレックス前提のまま残してある（経緯の記録として）。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PCB を発注する前に、ブレッドボード上で「チャープレックス配線・BLE 分割・乾電池給電・HHKB キーマップ」の4つが成立することを実測で確定させる。

**Architecture:** ZMK の設定リポジトリを本プロジェクト内の `firmware/` に置き、GitHub Actions でファームウェアをビルドする。XIAO nRF52840 を 2 個使い、ブレッドボードに少数のキーだけを配線して、方式の可否を1つずつ潰す。ローカルに Zephyr SDK を入れる必要はない。

**Tech Stack:** ZMK Firmware / Zephyr devicetree / GitHub Actions / Seeed XIAO nRF52840 (`seeeduino_xiao_ble`)

## Global Constraints

- 対象仕様書: [docs/superpowers/specs/2026-08-04-hhkb-split-keyboard-design.md](../specs/2026-08-04-hhkb-split-keyboard-design.md)
- ZMK ボード名は `seeeduino_xiao_ble` を使う。他のボードに置き換えない（技適の要件）。
- 左右間の無線接続は必須要件。有線分割（TRRS）にフォールバックしない。
- HHKB に存在しない機能（RGB / OLED / エンコーダ / タップダンス / ホールドタップ / コンボ / マクロ）は最終ファームに入れない。検証用の一時ファームでは使ってよい。
- キーマップのレイヤー番号は以下で固定する。以降の全タスクがこの番号を前提にする。

  | 番号 | 名前 | 役割 |
  |---|---|---|
  | 0 | `BASE_MAC` | Mac モードのベース配列（起動時の既定） |
  | 1 | `BASE_WIN` | Windows モードのベース配列 |
  | 2 | `FN` | HHKB の Fn 面 |
  | 3 | `SYS` | BT 切替・OS モード切替 |

- `Fn + Ctrl` の再現方法: `FN` レイヤー上の Ctrl の位置に `&mo 3` を置く。これにより「Fn を押しながら Ctrl」で `SYS` レイヤーに入り、Ctrl 単独では通常の Ctrl のまま残る。ZMK の conditional-layers は「レイヤー同士」の組み合わせしか扱えないため、この方式を採る。
- GPIO 割り当ては以下で固定する。XIAO nRF52840 で ADC が使えるのは D0〜D5 のみ（P0.02/P0.03/P0.28/P0.29/P0.04/P0.05）であり、電池電圧測定に 1 本必要なため、チャープレックスは D2 以降を使う。

  | | チャープレックス | 電池電圧 ADC | 空き |
  |---|---|---|---|
  | 左（6ピン） | D3, D4, D5, D6, D7, D8 | D0 | D1, D2, D9, D10 |
  | 右（7ピン） | D2, D3, D4, D5, D6, D7, D8 | D0 | D1, D9, D10 |

---

## 事前に用意するもの

このフェーズは基板を作らずに進めるため、以下だけで開始できる。

| 品目 | 数量 | 用途 | 概算 |
|---|---|---|---|
| Seeed XIAO nRF52840（Sense でない通常版） | 2 | 左右の MCU | ¥3,600 |
| ブレッドボード | 2 | 左右 | ¥1,000 |
| ピンヘッダ（XIAO 用、2.54mm 7ピン） | 4 | XIAO をブレッドボードに挿すため。**要はんだ付け** | ¥200 |
| ジャンパワイヤ | 1 セット | 配線 | ¥800 |
| タクトスイッチ（2.54mm ピッチ） | 12 | 検証用キー | ¥300 |
| 1N4148（スルーホール） | 12 | チャープレックス用ダイオード | ¥200 |
| 抵抗 1MΩ | 4 | 電池電圧の分圧 | ¥100 |
| 単3電池ボックス（2本用・リード線付き） | 2 | 乾電池給電 | ¥400 |
| ショットキーダイオード 1N5817 | 2 | 電池側の逆流防止 | ¥200 |
| スライドスイッチ | 2 | 電源 | ¥200 |
| **デジタルテスター（µA レンジのあるもの）** | 1 | **逆流・消費電流の実測に必須** | ¥3,000〜 |
| USB-C ケーブル（データ通信対応） | 2 | 書き込み・給電 | 手持ち可 |

**注意**: XIAO nRF52840 にはピンヘッダが付属していないため、最初にはんだ付けが必要。ここが本フェーズで唯一のはんだ作業。

**GitHub アカウントとリモートリポジトリが必要**。ファームウェアは GitHub Actions でビルドするため、本プロジェクトを GitHub にプッシュできる状態にしておく。

---

## File Structure

```
.github/workflows/build.yml          ZMK 公式の再利用ワークフローを呼ぶだけ
firmware/
  build.yaml                         ビルド対象（ボード × シールド）の一覧
  config/
    west.yml                         ZMK 本体の取得先
    boards/shields/proto_direct/     Task 1: 疎通確認用（direct GPIO・2キー）
      Kconfig.shield
      proto_direct.overlay
      proto_direct.keymap
      proto_direct.conf
    boards/shields/proto_cplex/      Task 2: チャープレックス検証用（単体）
      Kconfig.shield
      proto_cplex.overlay
      proto_cplex.keymap
      proto_cplex.conf
    boards/shields/hhkb_split/       Task 3 以降: 本番シールド（左右）
      Kconfig.shield
      hhkb_split.dtsi                左右共通（チャープレックス・電池・トランスフォーム）
      hhkb_split_left.overlay
      hhkb_split_right.overlay
      hhkb_split_left.conf
      hhkb_split_right.conf
      hhkb_split.keymap              左右共通のキーマップ
docs/
  hardware/charlieplex-mapping.md    Task 2 の実測結果（ピン組合せ → 位置の対応表）
  hardware/power-measurements.md     Task 4・5 の実測結果
  hardware/wireless-latency.md       Task 3 の体感評価記録
```

検証用シールド（`proto_direct` / `proto_cplex`）は本番シールドと分けて残す。後で不具合が出たときに最小構成へ戻れるため、消さずに保持する。

---

## Task 1: ZMK ビルド環境と最小疎通

XIAO 1個・キー2個で「ファームを作って書き込むとキー入力になる」ところまでを通す。以降のタスクはすべてこの往復の上に乗る。

**Files:**
- Create: `.github/workflows/build.yml`
- Create: `firmware/build.yaml`
- Create: `firmware/config/west.yml`
- Create: `firmware/config/boards/shields/proto_direct/Kconfig.shield`
- Create: `firmware/config/boards/shields/proto_direct/proto_direct.overlay`
- Create: `firmware/config/boards/shields/proto_direct/proto_direct.keymap`
- Create: `firmware/config/boards/shields/proto_direct/proto_direct.conf`

**Interfaces:**
- Produces: ビルド基盤（`.github/workflows/build.yml` と `firmware/build.yaml`）。以降の全タスクは `firmware/build.yaml` に `shield:` を追加するだけでビルド対象を増やせる。
- Produces: シールドディレクトリの置き場所 `firmware/config/boards/shields/<name>/`。

- [ ] **Step 1: XIAO にピンヘッダをはんだ付けする**

XIAO nRF52840 2 個の両側 7 ピンに、2.54mm ピンヘッダをはんだ付けする。ブレッドボードにピンヘッダを挿し、その上に XIAO を載せて固定してからはんだ付けすると、ピンが傾かない。

確認: ブレッドボードに挿してぐらつかず、隣接ピン同士がブリッジしていないこと（テスターの導通モードで隣接ピン間が導通しないことを見る）。

- [ ] **Step 2: GitHub リモートリポジトリを作成して接続する**

```bash
cd "/Users/m/Library/CloudStorage/OneDrive-個人用/workspace/2608042258_HHKB_devided"
gh repo create hhkb-split --private --source=. --remote=origin
git push -u origin master
```

`gh` が未インストールなら `brew install gh && gh auth login` を先に実行する。

期待: `git remote -v` で origin が表示され、GitHub 上にリポジトリが見えること。

- [ ] **Step 3: ビルドワークフローを作成する**

`.github/workflows/build.yml`:

```yaml
name: Build ZMK firmware

on:
  push:
  pull_request:
  workflow_dispatch:

jobs:
  build:
    uses: zmkfirmware/zmk/.github/workflows/build-user-config.yml@main
    with:
      build_matrix_path: firmware/build.yaml
      config_path: firmware/config
```

ZMK 公式の再利用ワークフローを呼ぶ。`config_path` と `build_matrix_path` を指定しているので、ZMK 標準のリポジトリ構成（ルート直下に `config/`）でなくても動く。

- [ ] **Step 4: ビルド対象と ZMK 本体の取得先を定義する**

`firmware/build.yaml`:

```yaml
include:
  - board: seeeduino_xiao_ble
    shield: proto_direct
```

`firmware/config/west.yml`:

```yaml
manifest:
  remotes:
    - name: zmkfirmware
      url-base: https://github.com/zmkfirmware
  projects:
    - name: zmk
      remote: zmkfirmware
      revision: main
      import: app/west.yml
  self:
    path: config
```

- [ ] **Step 5: 疎通確認用シールドを定義する**

`firmware/config/boards/shields/proto_direct/Kconfig.shield`:

```
config SHIELD_PROTO_DIRECT
	def_bool $(shields_list_contains,proto_direct)
```

`firmware/config/boards/shields/proto_direct/proto_direct.overlay`:

```dts
/ {
	chosen {
		zmk,kscan = &kscan0;
	};

	kscan0: kscan_0 {
		compatible = "zmk,kscan-gpio-direct";
		wakeup-source;
		input-gpios
			= <&xiao_d 0 (GPIO_ACTIVE_LOW | GPIO_PULL_UP)>
			, <&xiao_d 1 (GPIO_ACTIVE_LOW | GPIO_PULL_UP)>
			;
	};
};
```

`&xiao_d` は Zephyr の XIAO ボード定義にあるピンコネクタのラベルで、`<&xiao_d 0>` が基板シルクの D0 に対応する。P0.02 のような生のポート番号を書かなくてよい。

`firmware/config/boards/shields/proto_direct/proto_direct.keymap`:

```dts
#include <behaviors.dtsi>
#include <dt-bindings/zmk/keys.h>

/ {
	keymap {
		compatible = "zmk,keymap";

		default_layer {
			bindings = <&kp A &kp B>;
		};
	};
};
```

`firmware/config/boards/shields/proto_direct/proto_direct.conf`:

```
CONFIG_ZMK_KEYBOARD_NAME="proto direct"
```

- [ ] **Step 6: コミットしてビルドを走らせる**

```bash
git add .github firmware
git commit -m "feat: ZMK ビルド環境と疎通確認用シールドを追加"
git push
```

- [ ] **Step 7: ビルドの成功を確認してファームを取得する**

```bash
gh run watch
gh run download --name firmware --dir /tmp/zmk-firmware
ls /tmp/zmk-firmware
```

期待: `proto_direct-seeeduino_xiao_ble-zmk.uf2` が存在すること。

ビルドが失敗した場合は `gh run view --log-failed` でログを読む。よくある失敗は `west.yml` のインデント誤りと、シールド名とディレクトリ名の不一致（`Kconfig.shield` の `shields_list_contains` の引数はディレクトリ名と完全一致していなければならない）。

- [ ] **Step 8: 配線して書き込む**

ブレッドボード配線:
- タクトスイッチ 1: 片側を XIAO の `D0`、もう片側を `GND`
- タクトスイッチ 2: 片側を XIAO の `D1`、もう片側を `GND`

書き込み:
1. XIAO を USB-C で Mac に接続する
2. XIAO 上のリセットボタンを**素早く 2 回**押す
3. Finder に `XIAO-SENSE` という名前のドライブが現れる
4. `proto_direct-seeeduino_xiao_ble-zmk.uf2` をそのドライブにドラッグ&ドロップする
5. ドライブが自動的にアンマウントされ、XIAO が再起動する

- [ ] **Step 9: 動作を確認する**

テキストエディタを開き、タクトスイッチを押す。

期待: スイッチ 1 で `a`、スイッチ 2 で `b` が入力される。

入力されない場合の切り分け順序:
1. Bluetooth ではなく USB で入力されているか（USB 接続時は USB が優先される）
2. macOS の「キーボード設定アシスタント」が開いていないか（開いていたら一度閉じる）
3. スイッチの導通（テスターで、押したときに導通すること）
4. `GND` が XIAO の GND ピンか（XIAO は両側に GND がある）

- [ ] **Step 10: コミット**

```bash
git add -A
git commit -m "feat: XIAO 単体での ZMK 疎通確認が完了"
git push
```

---

## Task 2: チャープレックス配線の検証

**このフェーズで最も重要なタスク。** 7 ピンで 42 個のキーを読めることを実測し、「どのピンの組み合わせが (row, col) のどことして報告されるか」の対応表を作る。この表がないと PCB の配線を決められない。

**Files:**
- Create: `firmware/config/boards/shields/proto_cplex/Kconfig.shield`
- Create: `firmware/config/boards/shields/proto_cplex/proto_cplex.overlay`
- Create: `firmware/config/boards/shields/proto_cplex/proto_cplex.keymap`
- Create: `firmware/config/boards/shields/proto_cplex/proto_cplex.conf`
- Create: `docs/hardware/charlieplex-mapping.md`
- Modify: `firmware/build.yaml`

**Interfaces:**
- Consumes: Task 1 のビルド基盤。
- Produces: `docs/hardware/charlieplex-mapping.md` — ピン組み合わせと `(row, col)` の対応表。Task 6 のキーマップと、フェーズ2 の PCB 配線がこれを参照する。
- Produces: チャープレックスの devicetree 記述パターン（`zmk,kscan-gpio-charlieplex` ノードと 7×7 の `zmk,matrix-transform`）。Task 3 の本番シールドがこれを流用する。

- [ ] **Step 1: 検証用の 8 キーを配線する**

D2〜D8 の 7 本を使う。チャープレックスでは、1 つのキーは「タクトスイッチ + ダイオードの直列」で 2 本のピンの間を繋ぐ。ダイオードの向きが位置を決める。

配線の規約（PCB でもこの規約を踏襲する）:

```
  ピンX ──[タクトスイッチ]──[1N4148 アノード→カソード]── ピンY
```

つまり **ダイオードのアノード側を X、カソード側（帯のある側）を Y** に向ける。X と Y を入れ替えたものは別のキーになる。

検証用に、対応表の当たりをつけやすい 8 通りを配線する:

| 検証キー | X（アノード側） | Y（カソード側） |
|---|---|---|
| K1 | D2 | D3 |
| K2 | D3 | D2 |
| K3 | D2 | D4 |
| K4 | D2 | D8 |
| K5 | D8 | D2 |
| K6 | D5 | D6 |
| K7 | D7 | D8 |
| K8 | D8 | D7 |

K1/K2、K4/K5、K7/K8 はピンの組み合わせが同じで向きだけが逆。これが別々のキーとして認識されれば、チャープレックスが正しく機能している証拠になる。

- [ ] **Step 2: チャープレックス用シールドを定義する**

`firmware/config/boards/shields/proto_cplex/Kconfig.shield`:

```
config SHIELD_PROTO_CPLEX
	def_bool $(shields_list_contains,proto_cplex)
```

`firmware/config/boards/shields/proto_cplex/proto_cplex.overlay`:

```dts
#include <dt-bindings/zmk/matrix_transform.h>

/ {
	chosen {
		zmk,kscan = &kscan0;
		zmk,matrix-transform = &default_transform;
	};

	kscan0: kscan_0 {
		compatible = "zmk,kscan-gpio-charlieplex";
		wakeup-source;
		gpios
			= <&xiao_d 2 GPIO_ACTIVE_HIGH>
			, <&xiao_d 3 GPIO_ACTIVE_HIGH>
			, <&xiao_d 4 GPIO_ACTIVE_HIGH>
			, <&xiao_d 5 GPIO_ACTIVE_HIGH>
			, <&xiao_d 6 GPIO_ACTIVE_HIGH>
			, <&xiao_d 7 GPIO_ACTIVE_HIGH>
			, <&xiao_d 8 GPIO_ACTIVE_HIGH>
			;
	};

	default_transform: keymap_transform_0 {
		compatible = "zmk,matrix-transform";
		columns = <7>;
		rows = <7>;
		map = <
			RC(0,0) RC(0,1) RC(0,2) RC(0,3) RC(0,4) RC(0,5) RC(0,6)
			RC(1,0) RC(1,1) RC(1,2) RC(1,3) RC(1,4) RC(1,5) RC(1,6)
			RC(2,0) RC(2,1) RC(2,2) RC(2,3) RC(2,4) RC(2,5) RC(2,6)
			RC(3,0) RC(3,1) RC(3,2) RC(3,3) RC(3,4) RC(3,5) RC(3,6)
			RC(4,0) RC(4,1) RC(4,2) RC(4,3) RC(4,4) RC(4,5) RC(4,6)
			RC(5,0) RC(5,1) RC(5,2) RC(5,3) RC(5,4) RC(5,5) RC(5,6)
			RC(6,0) RC(6,1) RC(6,2) RC(6,3) RC(6,4) RC(6,5) RC(6,6)
		>;
	};
};
```

対角（`RC(0,0)` など）は物理的に存在しないが、トランスフォームには含めておく。存在しない位置は押されないので害はなく、番号がずれないぶん対応表を読み解きやすい。位置番号は左上から順に 0〜48 になる。

`firmware/config/boards/shields/proto_cplex/proto_cplex.conf`:

```
CONFIG_ZMK_KEYBOARD_NAME="proto cplex"
CONFIG_ZMK_USB_LOGGING=y
```

`CONFIG_ZMK_USB_LOGGING=y` にすると、USB シリアル経由でキー押下のログが出る。これが対応表を作る手段になる。

- [ ] **Step 3: キーマップを定義する**

`firmware/config/boards/shields/proto_cplex/proto_cplex.keymap`:

49 個の位置すべてに異なるキーコードを割り当て、押したときに何が入力されるかで位置を特定できるようにする。

```dts
#include <behaviors.dtsi>
#include <dt-bindings/zmk/keys.h>

/ {
	keymap {
		compatible = "zmk,keymap";

		default_layer {
			bindings = <
				&kp N0 &kp N1 &kp N2 &kp N3 &kp N4 &kp N5 &kp N6
				&kp A  &kp B  &kp C  &kp D  &kp E  &kp F  &kp G
				&kp H  &kp I  &kp J  &kp K  &kp L  &kp M  &kp N
				&kp O  &kp P  &kp Q  &kp R  &kp S  &kp T  &kp U
				&kp V  &kp W  &kp X  &kp Y  &kp Z  &kp F1 &kp F2
				&kp F3 &kp F4 &kp F5 &kp F6 &kp F7 &kp F8 &kp F9
				&kp F10 &kp F11 &kp F12 &kp MINUS &kp EQUAL &kp LBKT &kp RBKT
			>;
		};
	};
};
```

各行が `row`、各列が `col` に対応する。例えば `RC(2,4)` の位置を押すと `l` が入力される。

- [ ] **Step 4: ビルド対象に追加してビルドする**

`firmware/build.yaml` を次の内容に更新する:

```yaml
include:
  - board: seeeduino_xiao_ble
    shield: proto_direct
  - board: seeeduino_xiao_ble
    shield: proto_cplex
```

```bash
git add -A
git commit -m "feat: チャープレックス検証用シールドを追加"
git push
gh run watch
gh run download --name firmware --dir /tmp/zmk-firmware
```

期待: `proto_cplex-seeeduino_xiao_ble-zmk.uf2` が生成されること。

ビルドが `zmk,kscan-gpio-charlieplex` を認識せずに失敗する場合は、`west.yml` の `revision` が古い ZMK を指している可能性がある。`revision: main` になっていることを確認する。

- [ ] **Step 5: 書き込んで 8 キーを実測する**

Task 1 Step 8 と同じ手順で書き込む。テキストエディタを開き、K1〜K8 を 1 つずつ押して、入力された文字を記録する。

期待する結果の性質:
- 8 キーすべてが**それぞれ異なる文字**を入力する
- K1 と K2（D2↔D3 の向き違い）が異なる文字になる
- K4 と K5、K7 と K8 も同様に異なる

**このタスクの合否判定**: 上記 3 点がすべて満たされれば、チャープレックス方式は成立する。1 つでも満たされない（同じ文字が出る、何も出ない、複数文字が出る）場合は Step 8 の分岐へ進む。

- [ ] **Step 6: 対応表を書き起こす**

`docs/hardware/charlieplex-mapping.md` を作成する。実測した文字から `(row, col)` を逆引きし、次の形式で記録する。

```markdown
# チャープレックス配線 対応表

XIAO nRF52840 / ZMK `zmk,kscan-gpio-charlieplex`
`gpios` の並び順: D2, D3, D4, D5, D6, D7, D8（インデックス 0〜6）

配線規約: ピンX ──[スイッチ]──[1N4148 アノード→カソード]── ピンY

## 実測結果（2026-08-XX）

| 検証キー | X（アノード） | Y（カソード） | 入力された文字 | 対応する位置 |
|---|---|---|---|---|
| K1 | D2 | D3 | （実測値） | RC(?,?) |
| K2 | D3 | D2 | （実測値） | RC(?,?) |
| K3 | D2 | D4 | （実測値） | RC(?,?) |
| K4 | D2 | D8 | （実測値） | RC(?,?) |
| K5 | D8 | D2 | （実測値） | RC(?,?) |
| K6 | D5 | D6 | （実測値） | RC(?,?) |
| K7 | D7 | D8 | （実測値） | RC(?,?) |
| K8 | D8 | D7 | （実測値） | RC(?,?) |

## 導かれた規則

row = （実測から判明した規則を記述）
col = （実測から判明した規則を記述）

## 42 位置の全対応表

| row \ col | 0 (D2) | 1 (D3) | 2 (D4) | 3 (D5) | 4 (D6) | 5 (D7) | 6 (D8) |
|---|---|---|---|---|---|---|---|
| 0 (D2) | — | | | | | | |
| 1 (D3) | | — | | | | | |
| 2 (D4) | | | — | | | | |
| 3 (D5) | | | | — | | | |
| 4 (D6) | | | | | — | | |
| 5 (D7) | | | | | | — | |
| 6 (D8) | | | | | | | — |
```

8 点の実測から規則を導いたら、残る 34 位置は規則から埋める。**規則を導いたあと、必ず未検証の位置を 2 つ選んで配線し直し、予測どおりの文字が出ることを確かめる**（規則の外挿が正しいことの確認）。

- [ ] **Step 7: コミット**

```bash
git add -A
git commit -m "feat: チャープレックス配線を実測し対応表を作成"
git push
```

- [ ] **Step 8（Step 5 が失敗した場合のみ）: duplex マトリクスへの切替を判断する**

チャープレックスが動かない場合、仕様書の「既知のリスク」に従い duplex マトリクス（ダイオード 2 個/キー、`zmk,kscan-gpio-matrix` を 2 系統）へ切り替える。この場合:

- 右 34 キー: 4 行 × 5 列の duplex（実質 40 キー）で 9 ピン。空き 2 ピン。
- 左 27 キー: 3 行 × 5 列の duplex（実質 30 キー）で 8 ピン。空き 3 ピン。

切替を決めた場合はこの計画を中断し、仕様書 §4 のキースキャン方式を更新したうえで計画を書き直す。**独断で進めず、必ず判断を仰ぐこと。**

---

## Task 3: BLE 分割の検証

XIAO 2 個を左右に見立てて ZMK の分割構成を組み、左右同時押しが正しく扱われることと、無線の遅延が実用範囲であることを確認する。

**Files:**
- Create: `firmware/config/boards/shields/hhkb_split/Kconfig.shield`
- Create: `firmware/config/boards/shields/hhkb_split/hhkb_split.dtsi`
- Create: `firmware/config/boards/shields/hhkb_split/hhkb_split_left.overlay`
- Create: `firmware/config/boards/shields/hhkb_split/hhkb_split_right.overlay`
- Create: `firmware/config/boards/shields/hhkb_split/hhkb_split_left.conf`
- Create: `firmware/config/boards/shields/hhkb_split/hhkb_split_right.conf`
- Create: `firmware/config/boards/shields/hhkb_split/hhkb_split.keymap`
- Create: `docs/hardware/wireless-latency.md`
- Modify: `firmware/build.yaml`

**Interfaces:**
- Consumes: Task 2 の `docs/hardware/charlieplex-mapping.md`（トランスフォームの `map` を書くために必要）。
- Produces: 本番シールド `hhkb_split_left` / `hhkb_split_right`。Task 5〜7 はこのシールドを編集していく。
- Produces: キーマップの物理配置順（左 27 キー → 右 34 キーの計 61 個を、上段左から順に並べる）。Task 6 がこの順序でキーマップを書く。

- [ ] **Step 1: 本番シールドの骨格を作る**

`firmware/config/boards/shields/hhkb_split/Kconfig.shield`:

```
config SHIELD_HHKB_SPLIT_LEFT
	def_bool $(shields_list_contains,hhkb_split_left)

config SHIELD_HHKB_SPLIT_RIGHT
	def_bool $(shields_list_contains,hhkb_split_right)
```

`firmware/config/boards/shields/hhkb_split/hhkb_split.dtsi`（左右共通の土台）:

```dts
#include <dt-bindings/zmk/matrix_transform.h>

/ {
	chosen {
		zmk,kscan = &kscan0;
	};
};
```

- [ ] **Step 2: 左シールドを定義する**

`firmware/config/boards/shields/hhkb_split/hhkb_split_left.overlay`:

左は 6 ピン（D3〜D8）で 27 キー。検証段階ではキーを 4 個だけ配線するので、トランスフォームには 6×6 の全位置を並べておき、実際に配線した位置だけを押す。

```dts
#include "hhkb_split.dtsi"

/ {
	chosen {
		zmk,matrix-transform = &left_transform;
	};

	kscan0: kscan_0 {
		compatible = "zmk,kscan-gpio-charlieplex";
		wakeup-source;
		gpios
			= <&xiao_d 3 GPIO_ACTIVE_HIGH>
			, <&xiao_d 4 GPIO_ACTIVE_HIGH>
			, <&xiao_d 5 GPIO_ACTIVE_HIGH>
			, <&xiao_d 6 GPIO_ACTIVE_HIGH>
			, <&xiao_d 7 GPIO_ACTIVE_HIGH>
			, <&xiao_d 8 GPIO_ACTIVE_HIGH>
			;
	};

	left_transform: keymap_transform_l {
		compatible = "zmk,matrix-transform";
		columns = <6>;
		rows = <6>;
		map = <
			RC(0,1) RC(0,2) RC(0,3) RC(0,4) RC(0,5) RC(1,0)
			RC(1,2) RC(1,3) RC(1,4) RC(1,5) RC(2,0) RC(2,1)
			RC(2,3) RC(2,4) RC(2,5) RC(3,0) RC(3,1) RC(3,2)
			RC(3,4) RC(3,5) RC(4,0) RC(4,1) RC(4,2) RC(4,3)
			RC(4,5) RC(5,0) RC(5,1)
		>;
	};
};
```

対角（`RC(n,n)`）は物理的に存在しないため除外し、残る 30 位置のうち先頭 27 個を使う。**この `map` の並び順が、キーマップの左 27 キーの並び順（HHKB 配列の左半分を上段左から順に読んだ順序）に一対一で対応する。**

`firmware/config/boards/shields/hhkb_split/hhkb_split_left.conf`:

```
CONFIG_ZMK_KEYBOARD_NAME="HHKB Split"
CONFIG_ZMK_SPLIT=y
CONFIG_ZMK_SPLIT_ROLE_CENTRAL=y
```

- [ ] **Step 3: 右シールドを定義する**

`firmware/config/boards/shields/hhkb_split/hhkb_split_right.overlay`:

右は 7 ピン（D2〜D8）で 34 キー。

```dts
#include "hhkb_split.dtsi"

/ {
	chosen {
		zmk,matrix-transform = &right_transform;
	};

	kscan0: kscan_0 {
		compatible = "zmk,kscan-gpio-charlieplex";
		wakeup-source;
		gpios
			= <&xiao_d 2 GPIO_ACTIVE_HIGH>
			, <&xiao_d 3 GPIO_ACTIVE_HIGH>
			, <&xiao_d 4 GPIO_ACTIVE_HIGH>
			, <&xiao_d 5 GPIO_ACTIVE_HIGH>
			, <&xiao_d 6 GPIO_ACTIVE_HIGH>
			, <&xiao_d 7 GPIO_ACTIVE_HIGH>
			, <&xiao_d 8 GPIO_ACTIVE_HIGH>
			;
	};

	right_transform: keymap_transform_r {
		compatible = "zmk,matrix-transform";
		columns = <7>;
		rows = <7>;
		map = <
			RC(0,1) RC(0,2) RC(0,3) RC(0,4) RC(0,5) RC(0,6) RC(1,0)
			RC(1,2) RC(1,3) RC(1,4) RC(1,5) RC(1,6) RC(2,0) RC(2,1)
			RC(2,3) RC(2,4) RC(2,5) RC(2,6) RC(3,0) RC(3,1) RC(3,2)
			RC(3,4) RC(3,5) RC(3,6) RC(4,0) RC(4,1) RC(4,2) RC(4,3)
			RC(4,5) RC(4,6) RC(5,0) RC(5,1) RC(5,2) RC(5,3)
		>;
	};
};
```

`firmware/config/boards/shields/hhkb_split/hhkb_split_right.conf`:

```
CONFIG_ZMK_KEYBOARD_NAME="HHKB Split"
CONFIG_ZMK_SPLIT=y
```

右には `CONFIG_ZMK_SPLIT_ROLE_CENTRAL` を書かない。これにより右が周辺側（peripheral）になる。

- [ ] **Step 4: 検証用の暫定キーマップを書く**

`firmware/config/boards/shields/hhkb_split/hhkb_split.keymap`:

61 キー分の bindings が必要。この段階では Task 6 の本番キーマップではなく、同時押しの検証に必要なキーだけを意味のある割り当てにし、残りは順番に並べておく。**左 27 個 → 右 34 個の順**で並べる。

```dts
#include <behaviors.dtsi>
#include <dt-bindings/zmk/keys.h>

/ {
	keymap {
		compatible = "zmk,keymap";

		default_layer {
			bindings = <
			// 左 27 キー（先頭を LSHIFT と LCTRL にして同時押しの検証に使う）
			&kp LSHIFT &kp LCTRL &kp N3 &kp N4 &kp N5 &kp N6
			&kp Q &kp W &kp E &kp R &kp T &kp Y
			&kp U &kp I &kp O &kp P &kp N1 &kp N2
			&kp N7 &kp N8 &kp N9 &kp N0 &kp MINUS &kp EQUAL
			&kp LBKT &kp RBKT &kp BSLH
			// 右 34 キー（先頭を A にして左 Shift との同時押しを見る）
			&kp A &kp B &kp C &kp D &kp E &kp F &kp G
			&kp H &kp I &kp J &kp K &kp L &kp M &kp N
			&kp O &kp P &kp Q &kp R &kp S &kp T &kp U
			&kp V &kp W &kp X &kp Y &kp Z &kp COMMA &kp DOT
			&kp SLASH &kp SEMI &kp SQT &kp GRAVE &kp TAB
			>;
		};
	};
};
```

- [ ] **Step 5: ビルドしてブレッドボードに配線する**

`firmware/build.yaml` を次の内容に更新する:

```yaml
include:
  - board: seeeduino_xiao_ble
    shield: proto_direct
  - board: seeeduino_xiao_ble
    shield: proto_cplex
  - board: seeeduino_xiao_ble
    shield: hhkb_split_left
  - board: seeeduino_xiao_ble
    shield: hhkb_split_right
```

配線（Task 2 の対応表を見て、狙った位置になるようダイオードの向きを決める）:
- 左ブレッドボード: `map` の 1 番目（LSHIFT）と 2 番目（LCTRL）の位置に 2 キー
- 右ブレッドボード: `map` の 1 番目（A）と 2 番目（B）の位置に 2 キー

```bash
git add -A
git commit -m "feat: 分割シールドを追加"
git push
gh run watch
gh run download --name firmware --dir /tmp/zmk-firmware
```

期待: `hhkb_split_left-seeeduino_xiao_ble-zmk.uf2` と `hhkb_split_right-seeeduino_xiao_ble-zmk.uf2` の 2 つが生成されること。

- [ ] **Step 6: 左右に書き込んでペアリングする**

1. 左の XIAO に `hhkb_split_left-...uf2` を書き込む
2. 右の XIAO に `hhkb_split_right-...uf2` を書き込む
3. 両方に USB で給電した状態にする（この時点ではまだ乾電池を使わない）
4. 左右が自動的に接続されるのを待つ（数秒〜十数秒）
5. Mac の Bluetooth 設定を開き、`HHKB Split` を探してペアリングする

左右が繋がらない場合は、両方のリセットボタンを 1 回ずつ押して再起動する。それでも繋がらない場合は、両方をブートローダーモードにして `settings_reset` ファーム（ZMK 公式が配布）を書き込み、設定を消してからやり直す。

- [ ] **Step 7: 左右同時押しを検証する**

テキストエディタで以下を実行し、結果を記録する。

| 検証内容 | 操作 | 期待する結果 |
|---|---|---|
| 左修飾 + 右キー | 左 LSHIFT を押しながら 右 A | `A`（大文字） |
| 左修飾を離す前後 | 左 LSHIFT を押す → 右 A を押す → 右 A を離す → 左 LSHIFT を離す | `A` 1 文字のみ |
| 左修飾 2 つ + 右キー | 左 LSHIFT と 左 LCTRL を押しながら 右 B | Shift+Ctrl+B として認識される（エディタのショートカットで確認） |
| 高速な左右交互打鍵 | 左 LCTRL の位置と右 A を交互に 20 回以上高速で叩く | 取りこぼし・順序の入れ替わりが起きない |
| 右キー連打 | 右 A を 30 回連打 | 30 文字入力される |

- [ ] **Step 8: 遅延の体感を記録する**

`docs/hardware/wireless-latency.md` を作成し、Step 7 の結果と体感を記録する。

```markdown
# BLE 分割の遅延評価

測定日: 2026-08-XX
構成: XIAO nRF52840 ×2、左 central / 右 peripheral、ZMK revision main
ホスト: macOS（BLE 接続）

## 同時押しの検証結果

（Step 7 の表をそのまま貼り、各行に実測結果と OK/NG を追記する）

## 体感

- 左半分（central）の打鍵: （記述）
- 右半分（peripheral）の打鍵: （記述）
- 左右の差を感じるか: （記述）

## 判定

（実用に足るか。詰める必要があるか）
```

**判定が「詰める必要がある」の場合のみ** Step 9 に進む。問題なければ Step 9 を飛ばす。

- [ ] **Step 9（必要な場合のみ）: BLE 接続間隔を詰める**

`hhkb_split_right.conf` に以下を追加し、周辺側の接続間隔を最短（7.5ms）に寄せる。

```
CONFIG_BT_PERIPHERAL_PREF_MIN_INT=6
CONFIG_BT_PERIPHERAL_PREF_MAX_INT=6
CONFIG_BT_PERIPHERAL_PREF_LATENCY=0
CONFIG_BT_PERIPHERAL_PREF_TIMEOUT=400
```

値の単位は 1.25ms 刻みなので `6` = 7.5ms。再ビルド・再書き込みして Step 7 を再実行し、`docs/hardware/wireless-latency.md` に前後の比較を追記する。

**有線分割（TRRS）への切替は行わない**（Global Constraints 参照）。ここで解決できない場合は判断を仰ぐ。

- [ ] **Step 10: コミット**

```bash
git add -A
git commit -m "feat: BLE 分割の動作と左右同時押しを検証"
git push
```

---

## Task 4: 乾電池給電と逆流の実測

XIAO の 3V3 ピンに単3電池 2 本から給電し、USB を挿したときに電池側へ電流が逆流しないことを実測で確かめる。**仕様書で「検証必須項目」としている箇所。**

**Files:**
- Create: `docs/hardware/power-measurements.md`

**Interfaces:**
- Consumes: Task 3 で書き込み済みの左右ファーム（そのまま使う）。
- Produces: `docs/hardware/power-measurements.md` — 消費電流と逆流電流の実測値。フェーズ2 の電源回路設計がこの数値を根拠にする。

- [ ] **Step 1: 電池給電の回路を組む**

左の XIAO について、次の配線をブレッドボード上に作る。**まだ USB は挿さない。**

```
単3電池ボックス(+) ── スライドスイッチ ── 1N5817 (アノード) 
                                              │
                                        (カソード) ── XIAO の 3V3 ピン

単3電池ボックス(−) ── XIAO の GND ピン
```

1N5817 はショットキーダイオードで、順方向電圧降下が約 0.3V。アルカリ新品 3.2V なら XIAO には約 2.9V が供給される（nRF52840 の動作範囲 1.7〜3.6V 内）。

**向きを間違えないこと。** 帯のある側（カソード）が XIAO 側。

- [ ] **Step 2: 電池だけで動作することを確認する**

スライドスイッチを ON にする。

期待: 左の XIAO が起動し、Mac と BLE で接続され、配線済みのキーが入力できること。

動かない場合の切り分け:
1. 電池電圧をテスターで測る（2 本で 2.8V 以上あるか）
2. ダイオードの向き（3V3 ピン側で 2.9V 前後が測れるか）
3. GND が繋がっているか

- [ ] **Step 3: 消費電流を測る**

テスターを µA レンジにして、スライドスイッチと 1N5817 の間に直列に挿入する。以下の 3 条件で電流を読む。

| 条件 | 測り方 | 記録する値 |
|---|---|---|
| 接続中・無操作 | Mac と BLE 接続した状態で 1 分放置 | （µA） |
| 打鍵中 | キーを毎秒 2 回程度押し続ける | （µA） |
| スリープ | Mac の Bluetooth を切り、ZMK が待機状態に入るまで待つ（既定で 15 分） | （µA） |

スリープ時の測定は 15 分待つ必要がある。時間を短縮したい場合は `hhkb_split_left.conf` に `CONFIG_ZMK_IDLE_SLEEP_TIMEOUT=60000`（60 秒）を一時的に足してビルドし直す。**測定後は必ず元に戻すこと。**

- [ ] **Step 4: 電池寿命を試算する**

アルカリ単3 の実容量を 2000mAh として計算する。

```
想定寿命(時間) = 2000000 (µAh) ÷ 平均消費電流 (µA)
```

平均消費電流は「無操作時の値 × 0.7 + 打鍵中の値 × 0.3」程度を目安にする（1 日 8 時間使用、うち 3 割が実打鍵という想定）。

仕様書は 3〜8ヶ月（2200〜5800 時間）を見込んでいる。**試算がこれを大きく下回る場合は、仕様書の記述を実測値に合わせて訂正すること。**

- [ ] **Step 5: 逆流を実測する（このタスクの核心）**

テスターを µA レンジのまま Step 3 と同じ位置（スライドスイッチと 1N5817 の間）に挿入したまま、**USB-C ケーブルを XIAO に挿す**。

| 測定 | 期待する値 | 意味 |
|---|---|---|
| USB 接続中の電池側電流 | **0 に近い値（数 µA 以下）**、かつ**負の値にならない** | 電池が使われず、かつ充電方向に電流が流れ込んでいない |

さらに、スライドスイッチを OFF にした状態で USB を挿し、XIAO が正常に動くことも確認する（USB 単独給電での動作）。

**判定基準:**
- 電池側電流が数 µA 以下、かつ負でない → **合格**。1N5817 1 個で逆流が阻止できているため、仕様書に書いた P-MOSFET による自動切離し回路は不要になる可能性がある。フェーズ2 で回路を簡略化できる。
- 電池側に無視できない電流が流れる、または負の値になる → **不合格**。Step 7 の分岐へ。

- [ ] **Step 6: 実測結果を記録する**

`docs/hardware/power-measurements.md` を作成する。

```markdown
# 電源系の実測結果

測定日: 2026-08-XX
構成: 単3アルカリ ×2 → スライドスイッチ → 1N5817 → XIAO nRF52840 の 3V3 ピン
測定器: （テスターの型番）

## 電圧

| 測定点 | 実測値 |
|---|---|
| 電池ボックス出力 | （V） |
| 1N5817 通過後（XIAO の 3V3） | （V） |

## 消費電流

| 条件 | 実測値 |
|---|---|
| 接続中・無操作 | （µA） |
| 打鍵中 | （µA） |
| スリープ | （µA） |

## 電池寿命の試算

（計算過程と結論）

## 逆流の検証

| 条件 | 実測値 | 判定 |
|---|---|---|
| USB 接続中の電池側電流 | （µA） | 合格 / 不合格 |
| 電源 OFF + USB 単独給電での動作 | （動作したか） | — |

## 結論

（P-MOSFET による切離し回路が必要か不要か。フェーズ2 の回路設計への申し送り）
```

- [ ] **Step 7（Step 5 が不合格の場合のみ）: P-MOSFET 切離し回路を追加して再測定する**

仕様書 §4 の回路を実装する。P-MOSFET（例: DMG2301L）のゲートを USB の VBUS（XIAO の `5V` ピン）に接続し、USB 接続時に電池側の経路を遮断する。

```
電池(+) ── スライドスイッチ ── P-MOSFET (S) 
                                    (D) ── 1N5817 ── XIAO 3V3
                                    (G) ── XIAO 5V ピン（VBUS）
                                    (G) ── 100kΩ ── 電池(+) 側（プルアップ）
```

配線後、Step 5 を再実行して逆流が止まることを確認し、`docs/hardware/power-measurements.md` に追記する。

- [ ] **Step 8: コミット**

```bash
git add -A
git commit -m "feat: 乾電池給電と逆流を実測"
git push
```

---

## Task 5: 電池残量測定

XIAO 内蔵の電池電圧測定は BAT 端子（リポ用）に繋がっており使えないため、分圧抵抗を自前で組み、ZMK に電池残量を報告させる。

**Files:**
- Modify: `firmware/config/boards/shields/hhkb_split/hhkb_split.dtsi`
- Modify: `firmware/config/boards/shields/hhkb_split/hhkb_split_left.conf`
- Modify: `firmware/config/boards/shields/hhkb_split/hhkb_split_right.conf`
- Modify: `docs/hardware/power-measurements.md`

**Interfaces:**
- Consumes: Task 4 の電池給電回路。
- Produces: `vbatt` ノード（`zmk,battery-voltage-divider`）を含む `hhkb_split.dtsi`。フェーズ2 の PCB がこの分圧回路をそのまま実装する。

- [ ] **Step 1: 分圧回路を組む**

電池のプラス側（1N5817 の**手前**、つまり生の電池電圧）を 1MΩ 2 本で分圧し、中点を D0 に入れる。

```
電池(+) ── 1MΩ ──┬── 1MΩ ── GND
                  │
                  └── XIAO の D0 ピン
```

D0 は P0.02 = AIN0 で、XIAO で ADC が使える 6 本のうちの 1 本。分圧比 1/2 なので、電池 3.2V に対して D0 には 1.6V が入る。nRF52840 の ADC 入力上限（VDD）を超えない。

分圧抵抗による常時消費は 3.2V ÷ 2MΩ = 1.6µA。Task 4 で測った待機電流に対して無視できる大きさかどうかを Step 5 で確認する。

- [ ] **Step 2: devicetree に電池ノードを追加する**

`firmware/config/boards/shields/hhkb_split/hhkb_split.dtsi` を次の内容に置き換える:

```dts
#include <dt-bindings/zmk/matrix_transform.h>

/ {
	chosen {
		zmk,kscan = &kscan0;
		zmk,battery = &vbatt;
	};

	vbatt: vbatt {
		compatible = "zmk,battery-voltage-divider";
		io-channels = <&adc 0>;
		output-ohms = <1000000>;
		full-ohms = <2000000>;
	};
};

&adc {
	status = "okay";
};
```

`io-channels = <&adc 0>` の `0` は AIN0（= D0 = P0.02）を指す。`output-ohms` は分圧の下側（GND 側）の抵抗値、`full-ohms` は 2 本の合計。

- [ ] **Step 3: 電池レポートを有効にする**

`hhkb_split_left.conf` と `hhkb_split_right.conf` の両方に以下を追加する:

```
CONFIG_ZMK_BATTERY_REPORTING=y
```

分割構成では、周辺側（右）の電池残量も central 経由でホストへ報告される。

- [ ] **Step 4: ビルドして書き込み、値を確認する**

```bash
git add -A
git commit -m "feat: 電池電圧の分圧測定を追加"
git push
gh run watch
gh run download --name firmware --dir /tmp/zmk-firmware
```

左右に書き込んだあと、macOS の Bluetooth 設定でデバイスの電池残量を確認する（`システム設定 > Bluetooth` でデバイス名の横に表示される）。

期待: 新品のアルカリ電池で 90〜100% 付近が表示されること。

**値が明らかにおかしい場合の対処:**
- 0% や 100% に張り付く → `io-channels` のチャンネル番号が違う可能性。D0 以外のピンに繋いでいないか確認する
- 実際の電圧より低く/高く出る → テスターで電池電圧と D0 の電圧を実測し、実測比から `output-ohms` と `full-ohms` を補正する（抵抗の誤差 5% が乗るため）
- ZMK のリチウムイオン前提の残量換算により、アルカリの放電カーブとずれる → 電圧そのものが正しく読めていれば合格とする。残量表示の換算精度はこのプロジェクトの要件ではない

- [ ] **Step 5: 分圧回路の消費電流を確認する**

Task 4 Step 3 と同じ方法で待機電流を測り直し、分圧回路の追加前後で差を記録する。

期待: 増加分が 2µA 程度に収まること。

- [ ] **Step 6: 実測結果を追記してコミット**

`docs/hardware/power-measurements.md` に「電池残量測定」の節を追加し、表示された残量、実測電圧、分圧前後の待機電流を記録する。

```bash
git add -A
git commit -m "feat: 電池残量測定を実装し実測値を記録"
git push
```

---

## Task 6: HHKB キーマップの移植

HHKB の配列と Fn 面を ZMK のキーマップに落とす。**このタスクは実機からの情報が2つ揃うまで着手できない。**

**着手条件（未充足なら待つ）:**
1. PD-KB800WNS の Keymap Tool から書き出した現行設定
2. 実機裏面の DIP スイッチ SW1〜SW6 の現在値

**Files:**
- Modify: `firmware/config/boards/shields/hhkb_split/hhkb_split.keymap`
- Create: `docs/hardware/hhkb-reference-keymap.md`

**Interfaces:**
- Consumes: Task 3 で決めたキーマップの並び順（左 27 → 右 34）。
- Consumes: Global Constraints のレイヤー番号（0=BASE_MAC, 1=BASE_WIN, 2=FN, 3=SYS）。
- Produces: 本番キーマップ。フェーズ2 以降はこのファイルを編集するだけになる。

- [ ] **Step 1: 実機の設定を書き起こす**

`docs/hardware/hhkb-reference-keymap.md` を作成し、Keymap Tool の書き出しと DIP 設定を転記する。推測で埋めず、読み取れた事実だけを書く。

```markdown
# PD-KB800WNS の現行設定（移植元）

## DIP スイッチ

| SW | 設定 | 意味 |
|---|---|---|
| SW1 | ON/OFF | |
| SW2 | ON/OFF | |
| SW3 | ON/OFF | Delete → Backspace |
| SW4 | ON/OFF | 左◇と左 Alt の入替 |
| SW5 | ON/OFF | |
| SW6 | ON/OFF | |

判明した動作モード: （Mac / PC / HHKB / Lite Ext のいずれか）

## ベースレイヤー（Keymap Tool の書き出しより）

（キー位置ごとの割り当てを転記）

## Fn レイヤー（Keymap Tool の書き出しより）

（キー位置ごとの割り当てを転記）
```

- [ ] **Step 2: ベースレイヤーを書く**

`firmware/config/boards/shields/hhkb_split/hhkb_split.keymap` の `default_layer` を、HHKB 配列そのものに置き換える。並び順は Task 3 で決めた「左 27 → 右 34」。

```dts
#include <behaviors.dtsi>
#include <dt-bindings/zmk/keys.h>
#include <dt-bindings/zmk/bt.h>
#include <dt-bindings/zmk/outputs.h>

#define BASE_MAC 0
#define BASE_WIN 1
#define FN       2
#define SYS      3

/ {
	keymap {
		compatible = "zmk,keymap";

		base_mac {
			bindings = <
			// 左 27 キー
			&kp ESC   &kp N1 &kp N2 &kp N3 &kp N4 &kp N5
			&kp TAB   &kp Q  &kp W  &kp E  &kp R  &kp T
			&kp LCTRL &kp A  &kp S  &kp D  &kp F  &kp G
			&kp LSHFT &kp Z  &kp X  &kp C  &kp V  &kp B
			&kp LGUI  &kp LALT &kp SPACE
			// 右 34 キー
			&kp N6 &kp N7 &kp N8 &kp N9 &kp N0    &kp MINUS &kp EQUAL &kp BSLH &kp GRAVE
			&kp Y  &kp U  &kp I  &kp O  &kp P     &kp LBKT  &kp RBKT  &kp BSPC
			&kp H  &kp J  &kp K  &kp L  &kp SEMI  &kp SQT   &kp RET
			&kp N  &kp M  &kp COMMA &kp DOT &kp SLASH &kp RSHFT &mo FN
			&kp SPACE &kp RALT &kp RGUI
			>;
		};
	};
};
```

**注意点:**
- Mac モードでは `◇` = Command（`LGUI` / `RGUI`）、`Alt` = Option（`LALT` / `RALT`）。
- Backspace の位置は数字段右端（`&kp BSPC`）。DIP SW3 が「Delete のまま」の設定なら `&kp DEL` に変える。**Step 1 で書き起こした事実に従うこと。**
- 左◇と左 Alt の順序は DIP SW4 の設定に従う。上記は入替なし（◇ が左）の場合。

- [ ] **Step 3: ビルドが通ることを確認する**

```bash
git add -A
git commit -m "feat: HHKB ベースレイヤーを移植"
git push
gh run watch
```

期待: ビルド成功。

失敗した場合、最も多い原因は bindings の個数が `map` の要素数と一致していないこと。左 27 + 右 34 = **61 個ちょうど**であることを数えて確認する。

- [ ] **Step 4: Fn レイヤーを追加する**

`base_mac` の後ろに以下を追加する。判明済みの割り当て（F1〜F12、Insert、Delete、Caps Lock、矢印）を埋め、Step 1 で書き起こした残りの割り当てを反映する。`&trans` は「下のレイヤーに素通し」、`&none` は「無効」を意味する。

**Ctrl の位置に `&mo SYS` を置く**のがこのレイヤーの要点。これで `Fn + Ctrl` が `SYS` レイヤーへの入口になる。

```dts
		fn {
			bindings = <
			// 左 27 キー
			&none     &kp F1 &kp F2 &kp F3 &kp F4 &kp F5
			&kp CAPS  &trans &trans &trans &trans &trans
			&mo SYS   &trans &trans &trans &trans &trans
			&trans    &trans &trans &trans &trans &trans
			&trans    &trans &trans
			// 右 34 キー
			&kp F6 &kp F7 &kp F8 &kp F9 &kp F10 &kp F11 &kp F12 &kp INS &kp DEL
			&trans &trans &trans &trans &trans  &kp UP  &trans  &trans
			&trans &trans &trans &trans &kp LEFT &kp RIGHT &trans
			&trans &trans &trans &trans &kp DOWN &trans &trans
			&trans &trans &trans
			>;
		};
```

矢印の位置の確認: 右半分 2 行目の 6 番目が `[`（→ `&kp UP`）、3 行目の 5 番目が `;`（→ `&kp LEFT`）、6 番目が `'`（→ `&kp RIGHT`）、4 行目の 5 番目が `/`（→ `&kp DOWN`）。ベースレイヤーの並びと突き合わせて位置がずれていないことを数えて確認する。

- [ ] **Step 5: SYS レイヤーを追加する**

`fn` の後ろに追加する。BT 切替・USB 切替・OS モード切替を、HHKB と同じ打ち方で再現する。

```dts
		sys {
			bindings = <
			// 左 27 キー（1〜4 が BT プロファイル、0 は右半分にある）
			&none &bt BT_SEL 0 &bt BT_SEL 1 &bt BT_SEL 2 &bt BT_SEL 3 &none
			&none &none &to BASE_WIN &none &none &none
			&trans &none &none &none &none &none
			&none &none &none &none &none &none
			&none &none &none
			// 右 34 キー
			&none &none &none &none &out OUT_USB &none &none &none &bt BT_CLR
			&none &none &none &none &none &none &none &none
			&none &none &none &none &none &none &none
			&none &to BASE_MAC &none &none &none &none &trans
			&none &none &none
			>;
		};
```

対応:
- 左の数字段 `1`〜`4` → `&bt BT_SEL 0` 〜 `&bt BT_SEL 3`（HHKB の `Fn+Ctrl+1〜4`）
- 右の数字段 `0` → `&out OUT_USB`（HHKB の `Fn+Ctrl+0`）
- 左の `W` → `&to BASE_WIN`（HHKB の `Fn+Ctrl+W`）
- 右の `M` → `&to BASE_MAC`（HHKB の `Fn+Ctrl+M`）
- 右の `` ` `` → `&bt BT_CLR`（現在のプロファイルのペアリング情報を消す。HHKB には無い操作だが、無線キーボードの復旧手段として必要）

- [ ] **Step 6: Windows ベースレイヤーを追加する**

`base_mac` を複製し、◇ と Alt を入れ替えた `base_win` を `fn` の前に挿入する。**レイヤーの定義順がレイヤー番号になる**ため、`base_mac`（0）→ `base_win`（1）→ `fn`（2）→ `sys`（3）の順に並べること。

```dts
		base_win {
			bindings = <
			// 左 27 キー（◇ と Alt を入れ替え）
			&kp ESC   &kp N1 &kp N2 &kp N3 &kp N4 &kp N5
			&kp TAB   &kp Q  &kp W  &kp E  &kp R  &kp T
			&kp LCTRL &kp A  &kp S  &kp D  &kp F  &kp G
			&kp LSHFT &kp Z  &kp X  &kp C  &kp V  &kp B
			&kp LALT  &kp LGUI &kp SPACE
			// 右 34 キー
			&kp N6 &kp N7 &kp N8 &kp N9 &kp N0    &kp MINUS &kp EQUAL &kp BSLH &kp GRAVE
			&kp Y  &kp U  &kp I  &kp O  &kp P     &kp LBKT  &kp RBKT  &kp BSPC
			&kp H  &kp J  &kp K  &kp L  &kp SEMI  &kp SQT   &kp RET
			&kp N  &kp M  &kp COMMA &kp DOT &kp SLASH &kp RSHFT &mo FN
			&kp SPACE &kp RGUI &kp RALT
			>;
		};
```

- [ ] **Step 7: ビルドして書き込み、ブレッドボードで検証する**

ブレッドボードには数キーしか配線していないため、全キーの確認はフェーズ2 の実機組立まで持ち越す。この段階で確認できるのは以下。

配線を組み替え、左に `Fn`（右半分にあるため右ブレッドボードへ）・`Ctrl`・`1`・`W`、右に `M` を配線して検証する。

| 検証 | 操作 | 期待 |
|---|---|---|
| Fn レイヤー | Fn を押しながら `1` | F1 が入力される |
| Fn+Ctrl → SYS | Fn + Ctrl + `1` | BT プロファイル 0 に切り替わる（接続が切れる／別のプロファイルに移る） |
| OS モード切替 | Fn + Ctrl + `W` → 何か打つ | Windows 配列（◇ と Alt が入れ替わっている） |
| OS モード復帰 | Fn + Ctrl + `M` | Mac 配列に戻る |
| 再起動でリセット | 電源を切って入れ直す | Mac 配列（レイヤー 0）に戻っている |
| Ctrl 単独 | Fn を押さずに Ctrl + `1` | Ctrl+1 として認識される（レイヤーに入らない） |

最後の行が特に重要。`&mo SYS` は Fn レイヤー上にしか存在しないため、Ctrl 単独では通常の Ctrl として振る舞うはず。

- [ ] **Step 8: コミット**

```bash
git add -A
git commit -m "feat: HHKB のキーマップ一式（Base/Fn/SYS/Win）を移植"
git push
```

---

## Task 7: フェーズ1 の完了判定と申し送り

**Files:**
- Create: `docs/hardware/phase1-results.md`
- Modify: `docs/superpowers/specs/2026-08-04-hhkb-split-keyboard-design.md`

**Interfaces:**
- Consumes: Task 2〜6 の実測ドキュメント全部。
- Produces: フェーズ2（PCB 設計）の入力となる確定事項の一覧。

- [ ] **Step 1: 完了条件を照合する**

以下がすべて満たされていることを確認する。1 つでも欠けていれば、その原因となったタスクへ戻る。

| # | 完了条件 | 根拠となるドキュメント |
|---|---|---|
| 1 | チャープレックス 7 ピンで 42 位置が区別して読める | `docs/hardware/charlieplex-mapping.md` |
| 2 | ピン組み合わせと `(row, col)` の全対応表がある | `docs/hardware/charlieplex-mapping.md` |
| 3 | BLE 分割で左右同時押しが正しく扱われる | `docs/hardware/wireless-latency.md` |
| 4 | 無線の遅延が実用範囲である | `docs/hardware/wireless-latency.md` |
| 5 | 乾電池からの 3V3 給電で動作する | `docs/hardware/power-measurements.md` |
| 6 | USB 接続時に電池側へ逆流しない | `docs/hardware/power-measurements.md` |
| 7 | 電池寿命の試算が仕様の想定を満たす | `docs/hardware/power-measurements.md` |
| 8 | 電池残量が報告される | `docs/hardware/power-measurements.md` |
| 9 | HHKB のキーマップがビルドでき、Fn / SYS / OS 切替が動く | `firmware/config/boards/shields/hhkb_split/hhkb_split.keymap` |

- [ ] **Step 2: 仕様書を実測値で更新する**

実測の結果、仕様書の記述と食い違った箇所を訂正する。少なくとも以下を見直す。

- §4 電源: P-MOSFET 切離し回路が必要だったか不要だったか（Task 4 Step 5 の判定）
- §4 電源: 電池寿命の見込み「3〜8ヶ月」を実測ベースの数値に置き換える
- §3 キーマップ: レイヤー構成表を、実装したレイヤー番号（0=BASE_MAC, 1=BASE_WIN, 2=FN, 3=SYS）に合わせる
- §6 検証計画: 段階 1〜3 を完了としてマークする
- §8 未確定事項: 解消した項目を消す

- [ ] **Step 3: フェーズ2 への申し送りを書く**

`docs/hardware/phase1-results.md` を作成する。

```markdown
# フェーズ1 結果と、PCB 設計への申し送り

## 確定した事項

| 項目 | 確定内容 |
|---|---|
| キースキャン方式 | （チャープレックス / duplex マトリクス） |
| 左の GPIO 割り当て | （実際に使ったピン） |
| 右の GPIO 割り当て | （実際に使ったピン） |
| ダイオードの向きの規約 | （PCB 配線で守るべき規約） |
| 電源回路 | （1N5817 のみ / P-MOSFET 追加） |
| 電池電圧の分圧 | （抵抗値と接続先ピン） |
| 空き GPIO | 左: （） 右: （） |

## PCB 設計時に注意すること

（実測で分かった落とし穴を列挙）

## 積み残し

（フェーズ1 で解決できず、フェーズ2 以降に持ち越す事項）
```

- [ ] **Step 4: コミット**

```bash
git add -A
git commit -m "docs: フェーズ1 の完了判定と PCB 設計への申し送りをまとめる"
git push
```

---

## このあと

フェーズ1 が完了したら、以下の順に別々の計画を立てる。それぞれ、前のフェーズの実測結果が入力になる。

| フェーズ | 内容 | 入力 |
|---|---|---|
| 2 | KiCad での PCB 設計、JLCPCB への発注、組立 | `docs/hardware/phase1-results.md` |
| 3 | ケース設計（3Dプリント） | 実機採寸 3 項目 ＋ フェーズ2 の基板外形 |
