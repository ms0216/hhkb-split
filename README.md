# hhkb-split

**HHKB Professional HYBRID Type-S（PD-KB800WNS / US配列 / 無刻印）の使い勝手を、
完全分割型で再現する自作キーボード。**

> **開発中です。** 実機での動作確認はまだ済んでいません。
> 現状は「CAD とファームウェアがビルドを通り、寸法と配列が実機調査で裏付けられている」段階です。
> 3Dプリント・基板発注・組み立ては未実施。

## 基本方針

**HHKB オリジナルの使い勝手を極力踏襲する。** 分割にするために必要な変更だけを加え、
それ以外は変えない。この方針は [tools/test_invariants.py](tools/test_invariants.py) に
テストとして書き下してあり、設計の都合で妥協しようとすると機械的に落ちる。

守っているもの:

| 項目 | 値 | 根拠 |
|---|---|---|
| キーピッチ | 19.05mm | 実機公称 |
| 打鍵面の傾斜 | 7.3° | 実機ノギス実測 |
| 手前端の高さ | 17.5mm | 実測 17mm と別レビュー約18mm の中間 |
| キートップ高さ（各段） | 26.7 / 29.2 / 31.6 / 35.6 / 40.0mm | 公称全高 40mm から導出 |
| チルト脚 | 0 / 3 / 6° の3段階 | 実機と同一 |
| 行ずれ | HHKB と同一（格子配列にしない） | 実機 |
| 最下段 | 外側 1u / スペース寄り 1.5u | QMK info.json + KLE 図 |
| 電源 | 単3 × 2 | 実機と同じ思想（リポにしない） |

変更したもの:

- **打鍵感** — 静電容量無接点（Topre）→ MX 互換 + ホットスワップソケット
- **分割** — 6u スペースを 3u + 3u に分割。**左右とも Space**。キーは増やさない（60 → 61）
- **Mac/Win 切替** — 実機の DIP スイッチ相当をソフトウェアで実現
- **無線** — 左右間も Bluetooth。TRRS 有線は障害時の予備でしかない

## 構成

```
layout/        HHKB オリジナルと分割版のキー配列（JSON）
tools/         配列読み込み・CAD生成・検証（Python / build123d）
config/        ZMK ファームウェア設定
docs/hardware/ 実機の寸法調査と、その出典・失敗した調査経路の記録
build/         生成された STL（未印刷）
```

### tools/

パラメトリック CAD。`build123d`（OCCT）でモデルを生成し、`trimesh` で
メッシュ健全性を、OrcaSlicer CLI で実際にスライスできるかを検証する。

```bash
python -m pytest tools          # 全検査（約 14 分。件数は --collect-only で数える）
python tools/gen_case.py        # ケースを生成
python tools/verify.py          # メッシュとスライスの検証
```

[tools/interface.py](tools/interface.py) は**プレート・ケース・基板が共有する境界**を
1 箇所に集めたもの。ケースは刷り直せるが基板は発注し直すと高くつくので、
ここを凍結してから発注する。

### config/

ZMK。ボードは **Seeed Studio XIAO nRF52840**（技適 211-220207）。
XIAO は GPIO が 11 本しかなく普通のマトリクスに 1 本足りないため、列の駆動に
シフトレジスタ **SN74LVC595APWR** を使う（ZMK 公式が推奨する手段）。**74HC595 では打ち止め時に規格外**（動作電圧の下限 2.0V に対し、レールは 1.8V まで下がる）と分かって差し替えた。キーごとにダイオード 1 個の
ごく普通の行×列マトリクスなので、同時押しでゴーストが出ない。
当初はチャープレックス方式で設計していたが、基板発注前に破棄した
（[判断根拠](docs/hardware/decisions/2026-08-07-keyscan.md)）。

| シールド | 用途 |
|---|---|
| `hhkb_split_left` / `hhkb_split_right` | 本番。4レイヤー × 61キー |
| `proto_direct` | 疎通確認（XIAO 1個・キー2個）（[手順書](docs/hardware/task-c1-smoke-test.md)）✅ 実機確認済 |
| `proto_matrix` | マトリクス配線とゴースト試験の治具（[手順書](docs/hardware/task-c2-keyscan.md)）✅ 実機確認済 |

ビルドは GitHub Actions（ZMK 公式の再利用ワークフロー）。Actions の成果物から
`.uf2` をダウンロードして書き込む。

### 検証タスクの手順書

実機で確かめる作業は、配置図と判定基準つきの手順書にしてある。

| タスク | 内容 | 状態 |
|---|---|---|
| [C1](docs/hardware/task-c1-smoke-test.md) | 疎通確認（XIAO・書き込み・ZMK が実機で動くか） | ✅ 合格 |
| [C2](docs/hardware/task-c2-keyscan.md) | キースキャン（マトリクス・ゴースト・シフトレジスタ。治具は 74HC595、本番は 74LVC595） | ✅ C2-a 合格 / ⬜ C2-b |
| [C3](docs/hardware/task-c3-ble-split.md) | BLE 分割（左右同時押しが崩れないか） | ⬜ |
| [C4・C5](docs/hardware/task-c4-c5-power.md) | 乾電池給電・逆流の測定・電池残量 | ⬜ |
| [C6](docs/hardware/task-c6-confirm-on-real-hhkb.md) | 実機の DIP スイッチとキーマップを確認 | ⬜ **部品不要** |
| [B3](docs/hardware/task-b3-print-and-compare.md) | 3Dプリントして実機と比べる | ⬜ **部品不要** |

書き込みでつまずいたときは [xiao-flash-recovery.md](docs/hardware/xiao-flash-recovery.md)。

### docs/hardware/

実機を分解せず、公開情報だけから寸法を確定させた記録。
[reference-sources.md](docs/hardware/reference-sources.md) には**失敗した調査経路 11 件**も
残してある（例: PFU 公式記事に載っていた側面写真 4 枚が、よく見ると HHKB ではなく
MX 軸のキーボードだった）。同じ穴に落ちないため。

## 進捗

| フェーズ | 状態 |
|---|---|
| A. 実機寸法の確定 | ✅ 完了 |
| B. 機構設計（プレート・ケース） | ✅ STL 生成・検証済み / ⬜ 未印刷（[B3](docs/hardware/task-b3-print-and-compare.md)） |
| C. 電気・ファームウェア検証 | 🔶 進行中（**C1・C2-a 合格**。C2-b は 74HC595（治具用。本番は 74LVC595）待ち、C3〜C5 は部品待ち） |
| D. 基板設計（KiCad → JLCPCB） | 🔶 D1・D2a 完了（外形・キー配置・マトリクス）。[詳細](pcb/README.md) |
| E. 組み立て・実機調整 | ⬜ 未着手 |

## ライセンス

未定。
