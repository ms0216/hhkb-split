# 改善バックログ（2026-08-13 監査・引き継ぎ）

3 回の読み取り専用監査（リポジトリ全域／decisions 整合／firmware・CI・検査品質）で
見つかった残作業。**上から順に着手すること。**各項目に根拠と具体的な手順を書いた。
証拠の行番号は 2026-08-13 時点。着手前に grep で現物を確かめること。

**済んだもの（この日に修正・コミット済み。二重にやらないこと）:**
OrcaSlicer ログの掃除／check_zmk_config の CI 組み込み／slice_check の stale 赤化と
孤児 STL 削除／README・CLAUDE.md の古い数字／テスト名衝突 3 組の改名／
preview_parts・preview_layout の削除／SVG 4 枚の生成器名の逆引き／
右 9 列・595×2 の決定記録への伝搬／gen_pcb・circuit の嘘コメント／
shopping-list の -G 統一と死んだ C&K 行／cost-estimate の丸めと「4 割」表現。

## 作法（このリポジトリの前提）

- 着手前に `CLAUDE.md` を読む。特に: **名指しで stage・`git add -A` 禁止・
  コミット前に `git diff --cached` を読む**
- **検査の実行中にファイルを編集しない**（偽の赤/緑が出た実績あり）
- 修正したら **故意に壊して検出されること**を確かめる（規則 2）
- 全部終えたら `.venv/bin/pytest tools -q` を 1 回（約 14 分・448 件）

---

## 1. 【高】battery_alkaline.c — 浮き/切断入力で高残量に化ける

`firmware/drivers/battery_alkaline.c:87-90`

```c
int32_t val = data->adc_raw;
adc_raw_to_millivolts(...);
data->millivolts = val * (uint64_t)cfg->full_ohm / cfg->output_ohm;  // millivolts は uint16_t
```

問題 2 つ:
1. **`val` が負になり得る**（ノイズ・電池切断で ADC が負を返す）。負の int32 が
   uint64 に変換されて巨大値 → uint16 に折り返し → **切断した電池を高残量と
   誤報告**し、打ち止め（low_battery_off）が効かない
2. 代入時の uint16 折り返しに飽和が無い（現在の分圧比では 3600mV が上限なので
   顕在化しないが、overlay の分圧を変えると壊れる）

**手順:** `adc_raw_to_millivolts` の後に `if (val < 0) val = 0;` を入れ、
乗除の結果を `uint32_t mv` で受けて `data->millivolts = MIN(mv, UINT16_MAX);`
とする。手元に Zephyr SDK は無い——**push して CI の ZMK ビルド（約 2 分半）で
コンパイル確認**（CLAUDE.md 参照）。

## 2. 【高】firmware/Kconfig — SAMPLES に range が無い

`firmware/Kconfig` の `HHKB_LOW_BATTERY_SOFT_OFF_SAMPLES`（default 2）。
0 や負を設定すると 1 回の電圧ディップで即 soft off し、help 文が警告している
誤動作そのものになる。**`range 1 255` を 1 行足す。**確認はビルド（CI）。

## 3. 【中】.github/workflows/build.yml — permissions と paths

- `permissions: contents: read` を足す（現状 GITHUB_TOKEN が既定スコープのまま
  サードパーティの reusable workflow に渡る）
- `on: push` に `paths:` フィルタを足す: `config/**`, `firmware/**`,
  `build.yaml`, `zephyr/**`, `.github/workflows/build.yml`。
  文書だけの push で 8 ターゲットのビルドが走り、キュー詰まりの実績がある
  （checks.yml:35 付近に記録）
- `@main` 固定は**変えない**（west.yml の zmk revision も main。揃っている）
- ⚠️ paths を足すと「ファームの日」以外は .uf2 が出ない。CLAUDE.md の
  「push → 2 分半 → .uf2」の記述と矛盾しないか確認し、必要なら追記

## 4. 【中】test_export_fab_gate.py — 自己参照の検査

`tools/test_export_fab_gate.py:30-43`。`_UNRESOLVED`/`_ACCEPTED` の文字列を
自前で二重定義し、`export_fab.py` のソース文字列に含まれるかを見ている。
**両方とも自分の書いた文字列なので、規則そのものが間違っていても通る**
（CLAUDE.md 規則 3「自分の生成物どうしの一致は検証ではない」）。

**手順:** `export_fab.py` 側の定数を module 変数に切り出して import し、
テストはその実物を合成文書に当てて挙動で検証する（隣の
`test_the_gate_is_not_opened_by_prose...` と同じ流儀）。二重定義を消す。
**故意に export_fab 側の見出しを 1 字変えて、検査が落ちることを確認。**

## 5. 【中】rtree がコメントでしか守られていない

`requirements-dev.txt` の `rtree` は transitive 依存（trimesh の
`mesh.contains()` 用）で、`tools/test_requirements.py` の AST 走査には
見えない。行を消しても全テストが通ってしまう。matplotlib で 2 回踏んだ轍と同型。

**手順:** `test_requirements.py` に「`importlib.import_module("rtree")` ＋
小さな mesh で `contains()` を 1 回呼ぶ」テストを足す。
**`.venv` から rtree を一時的に外して落ちることを確認**してから戻す
（`pip uninstall -y rtree` → 確認 → `pip install -r requirements-dev.txt`）。

## 6. 【中】hhkb_split.dtsi のコメント 3 箇所が旧構成のまま

右 9 列・595×2 への変更が散文コメントに伝搬していない
（コードと decisions/ は 2026-08-13 に修正済み）:

- 「5 段 × 左 6 列 / 右 8 列」→ 右 9 列
- 「全体は 5 行 × 14 列。左が列 0..5、右が列 6..13」→ **5 行 × 15 列・右 6..14**
  （`columns = <15>` と map の RC(0,14) が正）
- shifter の「ngpios は 595 の出力本数。1 個なので 8」→
  「既定は左向けの 8。右は overlay で 16 に上書き（2 個数珠つなぎ）」

コメントのみの変更だがビルドと `pytest tools/test_firmware.py` で確認。

## 7. 【低】「74HC595」表記の一括改め

実部品は SN74LVC595APWR（74HC595 は動作電圧下限 2.0V で規格外→変更済み）。
`tools/circuit.py`・`hhkb_split.dtsi`・`hhkb_split_right.overlay` の
コメント内の「74HC595」を「595（SN74LVC595A）」へ。**例外:** 治具
（proto_shift・ブレッドボード）は本当に 74HC595 を使うので変えない。
build.yaml のコメントも治具側なのでそのまま。

## 8. 【低】blend_assembly.sh / refresh_view.sh の `$HALVES` 展開

`HALVES=${*:-"left right"}` を unquoted で word-split している。現状の
引数（left/right）では問題ないが、配列 `"$@"` ベースに直すと頑丈。壊れて
いないので暇なとき。

## 9. 【低】alk_channel_get の非同期読み

`battery_alkaline.c:97-114` は fetch と別コンテキストから millivolts と
state_of_charge を読むため、間に fetch が挟まると 2 値が不整合になり得る。
現状 low_battery_off は電圧しか読まないので実害なし。**直すより先に、
「event 直後に読む前提」への依存をコメントで明文化**（low_battery_off.c:59
付近の前提をドライバ側にも書く）。

## 10. 【判断待ち・エージェントは着手しない】

- **open-gaps #23（アンテナ）**: 手 0（アルミ箔で RSSI）は利用者の実測待ち。
  発注はこれが門で止まる（export_fab.py）
- **#39 C_RAIL の置き場所**: 高周波・EMC の判断。実測値は記録済み
- **SW_PWR_* の実測**: 部品が届いたらノギス。データシート公称との照合は
  2026-08-13 に済み（端子長 5.0 = 図面 8.5 − 本体 3.5。食い違い無し）

## 検証の締め

1〜7 を終えたら:
1. `.venv/bin/pytest tools -q`（全 448 件・約 14 分）
2. push して CI 2 本（ZMK ビルド・設計の自己検証）が緑であること
3. **この文書から済んだ項目を消す**（解決済みが「未解決」で残った事故が
   過去にある——open-gaps.md 冒頭参照）
