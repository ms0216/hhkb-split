# 自律改善セッションの記録（2026-09-03・ブランチ autonomous-20260903）

利用者の指示（2026-09-03 00:25）: 「ブランチを切って、今から 7 時間の間、可能な限りの
改善検討（テーマは何でも）と、基板発注前チェック」。**push はしない。**
1 項目 = 1 コミットで、利用者が cherry-pick で取捨選択できるように切る。

## 現在の状態（00:50）

- ブランチは main (e7a35cd) ＋ コミット多数。検査 481 緑（01:00・このブランチで `pytest tools` 全件）・3 基板 DRC 0・実形状干渉 0
- 発注をせき止めるものは利用者側の #52（配置プレビュー目視）だけ

## 一覧

| # | 何をしたか | 動機 | 検証 | コミット | 採否 |
|---|---|---|---|---|---|
| 1 | 裏面のキー名シルクが「最寄りのスイッチ＝自分」であることを見る検査を追加（`test_every_key_name_on_the_silk_sits_under_its_own_switch`） | #56 で右の名札が 21mm 離れたまま DRC が黙っていた。部品を動かす操作は今後もある | 故意に R-Space の名札を 21mm ずらして赤、戻して緑。板の sha 不変を確認 | 4294baf | |
| 2 | fab-checklist §6 の結線検証（`tools/fab_check/` 3 本）と 1:1 PDF 6 本を、#53/#56 後の板で出し直し。595 48・XIAO 14・キー 61 経路すべて一致。実寸は Edge.Cuts だけで測る注意を追記（全層だと F.Fab の文字で 147.4mm に見える） | 証拠が 08-30/31 の板のままだった（発注前資料が古い） | evidence.json の 3 つの ok が true・外形実測 138.51 / 171.79 / 21.08 | — | |
| 3 | #56 後の板で、実形状の組み立て干渉（REQUIRE_KICAD=1 nothing_bites）**左右とも 0**（9分45秒）。ネジ頭 φ3.8 → 最寄りの裏面部品も再計算: 動かした 左 H2 3.9mm・右 H4 18.5mm、全体の最小は 1.1mm（左 H(-41.5,-38)・変化なし）。fab-checklist 8c の数字は生きている | 柱 2 本とスイッチ 2 個を動かした後の全体裏取り | gen_assembly 実形状・pcb_parts.json の STEP bbox | — | 記録のみ |
| 4 | 本番の板 3 枚で Fabrication Toolkit が読むフィールドを pcbnew から読み直した。ソケット 61 個すべて `LCSC`=C49352235 ＋ `FT Layer Override`=bottom、ダイオードは B 面で C54110、スタビ・穴・XIAO は BOM/CPL 除外（左 27/1/1/27/1＋除外 8、右 34/2/2/34/1＋除外 10、子基板 C17514×2・C8598・C88360＋除外 5） | #52 で見つかった「BOM が空・ソケットが top」が、#53/#56 の finalize で再生成した板にも入っているか | 板の実データ（`HasField`/`GetFieldText`）。生成側の `fab_fields.py` は読まず結果だけ見た | — | 記録のみ |
| 5 | `tools/refresh_view.sh` で STL と `.blend` を出し直した（left/right とも 00:36〜37）。`interface.py` の柱を動かした（左 H2・右 H4）後、`left_plate.stl` 23:17 / `right_plate.stl` 23:40 と絵が古かった | CLAUDE.md「CAD を変えたら必ず refresh_view」。古い絵は嘘の検証 | exit=0・4 ファイルの時刻・`right_blender.png` を目で見た（R-Space とスタビの位置が確定配置） | — | 生成物のみ・コミット対象外 |
| 6 | open-gaps 冒頭の一覧で、節は済なのに一覧が古かった 2 行を直した: #53 の旧行（「発注前に利用者が決める」が残っていた）と #43（「発注前に方針だけ決める」が残っていたが 2026-08-24 に小窓で決定済み・基板に影響なし） | この文書の冒頭自身が警告している状態。発注をせき止める表に決着済みが「未決」で残ると読み手が止まる | 節本文と「承知した差」の表を読んで照合 | 3dc198b | |
| 7 | `firmware/src/low_battery_off.c`: 打ち止め判定を `zmk_battery_state_changed` 待ちから、`ZMK_BATTERY_REPORT_INTERVAL` と同周期の自前 `k_timer`（低優先 work）に変更。初回は 1 周待つ。`CONFIG_ZMK_USB` があれば USB 給電中は数えない | #25b の 2026-09-02 追記: upstream `battery.c` は `last_state_of_charge != val1` のときだけ事象を出す（raw.githubusercontent で再確認・L94）。0% 張り付きで止まらない。タイマー化すると「スイッチ OFF＋USB＝0mV」で即 soft off するので USB の門が要る | `test_firmware.py` 13 緑（静的検査のみ）。**⚠️ コンパイル未確認**——SDK が手元に無く、このブランチは push しない。**取り込むなら push 後の `Build ZMK firmware` の緑を見てから**。`zmk_usb_is_powered()` / `zmk_workqueue_lowprio_work_q()` の存在は upstream ヘッダで確認 | dc37e79 | **要ビルド確認** |
| 8 | Task C4-4 の手順に、上の変更の影響（USB 給電中は判定が走らない → ログを読むなら VBUS 切りケーブル B のみ／事象の有無は気にしなくてよい）を追記 | 記録が古い機構を前提にしたままだと、試験で「止まらない」の切り分けを誤る | 文書の照合のみ | 6302709 | |
| — | ~~#7 の残り論点: `CONFIG_ZMK_USB` が無いビルドでは「スイッチ OFF＋USB」で 0mV を数えて soft off する~~ **解消: `xiao_ble//zmk` の board defconfig（upstream `app/boards/seeed/xiao_ble/xiao_ble_zmk_defconfig`）が `CONFIG_ZMK_USB=y` で、hhkb_split の左右どちらの .conf も上書きしていない**（grep 0 件）。左右とも USB の門が効く | | | | |
| 9 | `tools/explain_overlap.py`（分割で幅が増える理由の説明図）が配列の写しを自前で持ち、最下段が 3u+3u のままだった。`layout/` の JSON（原機＋分割）から読むよう変更。右の島は数字段のキー数で原機の位置へ戻す | CLAUDE.md の作法 3「自分の生成物どうし」＋作法 8「置き換えたら古い方を消す」。`3u` の grep で見つけた唯一の取り残し | 図を出して目で見た（最下段が 2.75u×2＋空き）。数字は不変（7.25＋9.0＝16.25u・+23.8mm） | b6f06cf | |
| 10 | 3 枚の設計規則と実配線の数字を読み直した: 規則 clr/trk 0.127・via 0.45/drill 0.2/annular 0.13・hole2hole 0.45・銅–板端 0.3・シルク間 0.15。実物は配線幅 0.2（子基板は 0.6 も）・ビア 0.3/0.6（右に 0.56 が 1 個・8b 既知） | JLCPCB 2 層（trace/space 0.127・via 0.3/0.5・annular 0.13）に対する余裕の再確認 | pcbnew で全 track/via を集計 | — | 記録のみ |
| 11 | Fn レイヤーの **A/S が逆**だった（A=Vol Up・S=Vol Dn）。PFU 取扱説明書 P3PC-6641-05EN p.15 は **A=Vol Dn・S=Vol Up・D=Mute**。keymap と dimensions.md を訂正 | 「実機の刻印をそのまま移植」の出所が KLE 図の読み取りだけで、外の事実（取説）と突き合わせていなかった。他の Fn 割当（F1〜F12・Ins/Del・矢印・Home/PgUp/End/PgDn・*・/・+・-・PrtSc/ScrLk/Pause・Caps・Power・Eject）は取説どおり | 取説 PDF を pdftotext で読んだ。`test_firmware / test_keyscan` 30 緑 | 6f9ae81 | |
| 12 | 取説 P3PC-6641-05EN の Fn 表（p.13/15）を全行、keymap の fn レイヤーと照合。A/S 以外は一致（1〜= F1〜F12・\ Ins・` Del・I PSc・O ScrLk・P Pause・K Home・L PgUp・, End・. PgDn・Tab Caps・Return Enter・N +・M −・H *・J /・[ ↑・/ ↓・; ←・' →・D Mute・F Eject・Esc Power・右◇ Stop）。LED の表（青 2 回/秒＝ペアリング待機・橙 1 回/30 秒＝残量低・橙 2 回/15 秒＝交換）も Kconfig の記述と一致 | #11 の裏取りを A/S だけで止めない | 取説 PDF（pdftotext） | — | 記録のみ |
| 13 | provisional-values.md の 45 定数の「現在値」を、`tools/` の実際の定数と機械で突き合わせ: **45/45 一致** | 表と設計値のずれ（open-gaps 冒頭の教訓）が暫定値の表にも起きていないか | 正規表現で表を読み、各モジュールの属性と比較 | — | 記録のみ |
| 14 | open-gaps #43 の節本体が「窓は未設計」のままだった（一覧も「実装はケースの改善サイクルで」）。窓は 2026-08-24 の f94a2ca で `gen_case.py` に入っている。節と一覧を「実装済み・残るは刷って透けるか」に直した | 冒頭の教訓（節と一覧のずれ）が節の内側でも起きていた。#43 の CAD 化を「改善テーマ」として着手しかけて気づいた | `git log -S LED_WIN_D`・`gen_case.py` L295〜 | de0556f | |
| 15 | `mutate.py` を 01:15 に再実行（9/1 の 106/0 以後に interface.py・circuit.py が変わったため）。**41/106 まで走って生存 0**。1 変異あたり約 10 分で終わらず、07:55 に利用者の了解で kill。変異中だった `circuit.py` `interface.py` は `git checkout` で復元（作業ツリー clean・右の板 sha f5866a892afd 不変） | 検査の検出力が変更後も保たれているか | mutate.log（検出 41・生存 0） | (下) | 途中まで |

## 方針

- 実測が要る項目（#52 の配置プレビュー・#50 の JLC 判定・#33 など）には触らない。記録だけ
- 触ったファイルだけ名指しで stage
- 検査の実行中はファイルを編集しない
