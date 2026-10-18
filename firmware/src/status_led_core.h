/*
 * LED の「どの状態を出すか」だけを切り出したもの。**Zephyr に依存しない。**
 *
 * 目的は机の上で検査できるようにすること。
 * `status_led.c` は実機でしか確かめられず、
 * **優先順位と遷移（純粋なロジック）が一度も自動で検査されていなかった。**
 * 既にある `encoder_gated_core.h` / `button_latch_core.h` と同じ作り。
 *
 * ⚠️ **決定は 2 段ある。**片方だけ切り出すと検査したつもりになる:
 *   1. `slc_state()`    … 入力から状態を畳む（元の `current_state()`）
 *   2. `slc_announce()` … 「復帰の合図」を割り込ませる
 *                         （元は `blink_work_cb` の中にあった）
 *
 * 決定表: docs/hardware/decisions/2026-08-16-led-state-table.md
 *
 * SPDX-License-Identifier: MIT
 */

#ifndef HHKB_STATUS_LED_CORE_H
#define HHKB_STATUS_LED_CORE_H

#include <stdbool.h>
#include <stdint.h>

/* 実機の表から来る閾値。**ここが唯一の出所**（status_led.c からも使う） */
#define SLC_BATT_LOW_PCT 15
#define SLC_BATT_REPLACE_PCT 5

enum slc_color {
    SLC_COLOR_OFF,
    SLC_COLOR_BLUE,  /* ホスト系。実機どおり */
    SLC_COLOR_AMBER, /* 電池系。実機どおり */
    SLC_COLOR_GREEN, /* 右手と繋がっていない。実機に無い・分割型固有 */
};

/* **上ほど優先。**同時に複数成立しうるので 1 つに畳む */
enum slc_state {
    SLC_BOOT,
    SLC_RECOVERED,
    SLC_BATT_REPLACE,
    SLC_BATT_LOW,
    SLC_LINK_LOST,
    SLC_IDLE,
};

enum slc_link {
    SLC_LINK_UNBONDED,
    SLC_LINK_DISCONNECTED,
    SLC_LINK_CONNECTED,
};

/* ZMK の activity に対応（この 3 つだけ使う） */
enum slc_activity {
    SLC_ACTIVE,
    SLC_IDLE_ACT,
    SLC_SLEEP,
};

struct slc_in {
    enum slc_activity activity;
    bool booting;
    uint8_t battery_pct;
    /* **持っているかどうかも入力。**右（ペリフェラル）にホストの接続は無い。
     * 2026-08-16 に、この囲いを忘れて右で青が点滅し続けた。 */
    bool has_split_link;
    enum slc_link split;
    bool has_host_link;
    enum slc_link host;
};

/* 1 段目: 入力から状態を畳む（元の `current_state()`） */
static inline enum slc_state slc_state(const struct slc_in *in) {
    /* **sleep のときだけ消す。idle では消さない。**
     * idle は 30 秒無操作で入るので、ここで消すと未接続の警告が
     * 30 秒で勝手に消える（2026-08-16 に利用者の指摘で直した）。 */
    if (in->activity == SLC_SLEEP) {
        return SLC_IDLE;
    }
    if (in->booting) {
        return SLC_BOOT;
    }
    if (in->battery_pct <= SLC_BATT_REPLACE_PCT) {
        return SLC_BATT_REPLACE;
    }
    if (in->battery_pct <= SLC_BATT_LOW_PCT) {
        return SLC_BATT_LOW;
    }
    if (in->has_split_link && in->split != SLC_LINK_CONNECTED) {
        return SLC_LINK_LOST;
    }
    if (in->has_host_link && in->host != SLC_LINK_CONNECTED) {
        return SLC_LINK_LOST;
    }
    return SLC_IDLE; /* 接続中は消灯。実機どおり */
}

/*
 * 2 段目: 「復帰の合図」を割り込ませる（元は `blink_work_cb` の中）。
 *
 * 合図は**全部繋がって消灯に落ちるときだけ**出す。まだ他が未接続なら
 * そちらの点滅を優先し、出しそびれた合図は捨てる。
 *
 * `announce` は入出力。捨てたら `SLC_COLOR_OFF` に書き換わる。
 */
static inline enum slc_state slc_announce(enum slc_state st, enum slc_color *announce) {
    if (*announce != SLC_COLOR_OFF && st == SLC_IDLE) {
        return SLC_RECOVERED;
    }
    if (st != SLC_IDLE && st != SLC_RECOVERED) {
        *announce = SLC_COLOR_OFF; /* 出しそびれたら捨てる */
    }
    return st;
}

#endif /* HHKB_STATUS_LED_CORE_H */
