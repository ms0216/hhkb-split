# 右手ジョイスティック＋左手ロータリーエンコーダ（2026-10 の増設）

部品: アルプス RKJXV122400R（右・ATtiny1616 の帯で I2C）と EC12PL（左・XIAO 直結）。どちらも筐体の中。部品は 2026-10-07 に発注済み。

| 読む順 | ファイル |
|---|---|
| 1 | `NIGHT_REPORT.md` … 現状と、決めること |
| 2 | `BUILD.md` … 部品が届いたらやること（第 7 版） |
| 3 | `pod_layout/README.md` … 帯の作り方・マイコンへの書き込み |
| 4 | `SHOPPING.md` … 買った物と、大きさの条件 |
| 5 | `spec/K_SPEC.md` … 右の I2C ポッドの仕様（§9・§10 が筐体内の版） |

- `print/` … 刷る部品（プレート左右・受け皿左右・キャップ・つまみの予備）と出力スクリプト。`thin_check.py` で細い所の検査
- `scripts/` … 形の生成（`joystick_rkjxv.py`。main の筐体コードの上で動く）、干渉・線の道の検査
- `images/` … 絵（縮小版）。元の .blend と高解像度の絵は git の外 `build/joystick/`
- 検査: `tools/test_joystick_docs.py`（帯の配置の回路照合・受け皿の薄壁）、`tools/test_stick_pod.py`（ドライバの規則・机上の模擬 26 場面・ポッドのファーム）、`tools/test_encoder_gated.py`（左の B 案の数え方）

実機では未実行。
