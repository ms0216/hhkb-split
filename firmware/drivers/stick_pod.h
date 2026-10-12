/*
 * スティックポッドのドライバが外へ出している関数。
 * SPDX-License-Identifier: MIT
 */
#pragma once

/*
 * 中心を取り直す（キー操作から呼ぶ。firmware/src/behavior_stick_recal.c）。
 *
 * 呼ぶと、次の連続 8 フレームがそろって 0.5±0.2 に入った時点の平均を新しい
 * 中心として採用・保存する。**スティックから手を離して押すこと。**
 * 5 秒でそろわなければ諦めて前の中心に戻る。取り直しの間は移動を出さない。
 *
 * 戻り値: 0 = 受け付けた、-ENODEV = ドライバが初期化に失敗している。
 */
int hhkb_stick_pod_recalibrate(void);
