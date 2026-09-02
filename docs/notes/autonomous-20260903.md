# 自律改善セッションの記録（2026-09-03・ブランチ autonomous-20260903）

利用者の指示（2026-09-03 00:25）: 「ブランチを切って、今から 7 時間の間、可能な限りの
改善検討（テーマは何でも）と、基板発注前チェック」。**push はしない。**
1 項目 = 1 コミットで、利用者が cherry-pick で取捨選択できるように切る。

## 現在の状態（00:50）

- ブランチは main (e7a35cd) ＋ 2 コミット。検査 479 緑（main 時点）・3 基板 DRC 0・実形状干渉 0
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
| 7 | `firmware/src/low_battery_off.c`: 打ち止め判定を `zmk_battery_state_changed` 待ちから、`ZMK_BATTERY_REPORT_INTERVAL` と同周期の自前 `k_timer`（低優先 work）に変更。初回は 1 周待つ。`CONFIG_ZMK_USB` があれば USB 給電中は数えない | #25b の 2026-09-02 追記: upstream `battery.c` は `last_state_of_charge != val1` のときだけ事象を出す（raw.githubusercontent で再確認・L94）。0% 張り付きで止まらない。タイマー化すると「スイッチ OFF＋USB＝0mV」で即 soft off するので USB の門が要る | `test_firmware.py` 13 緑（静的検査のみ）。**⚠️ コンパイル未確認**——SDK が手元に無く、このブランチは push しない。**取り込むなら push 後の `Build ZMK firmware` の緑を見てから**。`zmk_usb_is_powered()` / `zmk_workqueue_lowprio_work_q()` の存在は upstream ヘッダで確認 | (下) | **要ビルド確認** |

## 方針

- 実測が要る項目（#52 の配置プレビュー・#50 の JLC 判定・#33 など）には触らない。記録だけ
- 触ったファイルだけ名指しで stage
- 検査の実行中はファイルを編集しない
