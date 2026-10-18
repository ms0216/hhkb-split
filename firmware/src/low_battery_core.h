/*
 * 打ち止めの「止めるか否か」だけを切り出したもの。**Zephyr に依存しない。**
 *
 * 2026-10-15 の監査で、`low_battery_off.c` の判定ロジックが
 * **自動検査で一度も実行されていない**ことが分かった。
 * 既存の検査（tools/test_firmware.py）が見ていたのは
 * 「USB の門がどう書かれているか」という**文字列**だけで、
 * 数える／閾値を跨ぐ／リセットする、という挙動は走っていなかった。
 *
 * 作りは encoder_gated_core.h / status_led_core.h / button_latch_core.h と同じ。
 *
 * SPDX-License-Identifier: MIT
 */

#ifndef HHKB_LOW_BATTERY_CORE_H
#define HHKB_LOW_BATTERY_CORE_H

#include <stdbool.h>
#include <stdint.h>

/* 1 回の判定で何をすべきか。 */
enum lbc_action {
    LBC_WAIT,      /* まだ何もしない */
    LBC_POWER_OFF, /* 規定回数続いた。止める */
};

struct lbc_state {
    uint8_t consecutive;
};

/*
 * 1 周期ぶんの判定。
 *
 *   usb_powered … USB から給電されている（＝電池は減っていない）
 *   readable    … 電圧が読めたか（読めなければ判定を飛ばす）
 *   mv          … 読めた電圧（readable が false なら無視）
 *   empty_mv    … 打ち止め電圧（devicetree の empty-millivolts）
 *   samples     … 何回続けて下回ったら止めるか
 *
 * ⚠️ **「連続」の意味を崩さないこと。**
 *   - USB 給電中は**数えをリセットする**（電池で動いていないので）
 *   - 電圧が打ち止めより上なら**リセット**
 *   - 読めなかったときは**据え置き**（リセットもカウントもしない）。
 *     1 回の読み取り失敗で、それまで数えた連続を捨てない。
 */
static inline enum lbc_action lbc_step(struct lbc_state *s, bool usb_powered, bool readable,
                                       uint32_t mv, uint32_t empty_mv, uint8_t samples) {
    if (usb_powered) {
        s->consecutive = 0;
        return LBC_WAIT;
    }
    if (!readable) {
        /* **据え置き。**読めない回を「下回った」とも「回復した」とも取らない。 */
        return LBC_WAIT;
    }
    if (mv > empty_mv) {
        s->consecutive = 0;
        return LBC_WAIT;
    }

    /* 1 回では止めない。BLE 送信中は電池の内部抵抗ぶん一時的に下がる。 */
    if (s->consecutive < 0xFF) {
        s->consecutive++;
    }
    return (s->consecutive >= samples) ? LBC_POWER_OFF : LBC_WAIT;
}

#endif /* HHKB_LOW_BATTERY_CORE_H */
