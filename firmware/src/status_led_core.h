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

/* --- 時定数（実機の表から来る）。**ここが唯一の出所** -------------------
 * status_led.c はこれを #define で引く。 */
#define SLC_BOOT_ON_MS 3000      /* 「青色に点灯したあと、消灯」 */
#define SLC_RECOVERED_ON_MS 1000 /* 復帰の合図 */
#define SLC_SLOW_BLINK_MS 250    /* 1 秒に 2 回。ボンド済み・未接続 */
#define SLC_FAST_BLINK_MS 125    /* 1 秒に 4 回。未ボンド */
#define SLC_PULSE_MS 120         /* 橙 1 回ぶんの点灯 */
#define SLC_PULSE_GAP_MS 280     /* 橙 2 回点滅の間隔 */
#define SLC_BATT_LOW_MS 30000    /* 橙 1 回点滅を 30 秒間隔 */
#define SLC_BATT_REPLACE_MS 15000 /* 橙 2 回点滅を 15 秒間隔 */

/* 表示を進めるための状態（work をまたいで持ち越す）。 */
struct slc_render {
    enum slc_state shown;
    uint8_t step;
    bool booting;            /* 起動直後の青を出し終えたら false */
    enum slc_color announce; /* 復帰の合図。出したら OFF に戻る */
};

/* 1 tick ぶんの出力。 */
struct slc_out {
    enum slc_color color;
    uint32_t next_ms;
};

/*
 * 3 段目: 状態から「何色を、次は何 ms 後か」を決める（元は `blink_work_cb`
 * の switch 文）。**Zephyr に依存しない。**
 *
 * 2026-10-15 の監査で、**この switch が自動検査でまったく実行されていない**
 * ことが分かった（3 つの表示退行を故意に入れて 32 件すべて緑だった）。
 */
static inline struct slc_out slc_tick(struct slc_render *r, enum slc_state st,
                                      const struct slc_in *in) {
    struct slc_out o = {SLC_COLOR_OFF, SLC_FAST_BLINK_MS * 4};

    if (st != r->shown) {
        r->shown = st;
        r->step = 0;
    }

    switch (st) {
    case SLC_BOOT:
        /* 実機の「青色に点灯したあと、消灯」。
         * **点灯しきるまで booting を降ろさない。** */
        o.color = SLC_COLOR_BLUE;
        if (r->step == 0) {
            r->step = 1;
            o.next_ms = SLC_BOOT_ON_MS;
        } else {
            r->booting = false;
            o.next_ms = 0; /* 次の tick で本来の状態を描く */
        }
        break;

    case SLC_RECOVERED:
        /* **色は復帰した系統**（分割＝緑・ホスト＝青）。 */
        o.color = r->announce;
        r->announce = SLC_COLOR_OFF;
        o.next_ms = SLC_RECOVERED_ON_MS;
        break;

    case SLC_IDLE:
        o.color = SLC_COLOR_OFF;
        o.next_ms = SLC_FAST_BLINK_MS * 4; /* 消えていても接続は見張る */
        break;

    case SLC_LINK_LOST: {
        /* **両方未接続なら交互に出す**（片方だけだと、もう片方の異常が
         * 見えない。2026-08-16 の利用者の判断）。 */
        enum slc_color c = SLC_COLOR_OFF;
        enum slc_link ls = SLC_LINK_CONNECTED;

        if (in->has_split_link && in->has_host_link) {
            bool split_bad = (in->split != SLC_LINK_CONNECTED);
            bool host_bad = (in->host != SLC_LINK_CONNECTED);
            bool show_split = split_bad && (!host_bad || ((r->step >> 1) & 1) == 0);
            c = show_split ? SLC_COLOR_GREEN : SLC_COLOR_BLUE;
            ls = show_split ? in->split : in->host;
        } else if (in->has_split_link) {
            c = SLC_COLOR_GREEN;
            ls = in->split;
        } else if (in->has_host_link) {
            c = SLC_COLOR_BLUE;
            ls = in->host;
        }

        bool on = (r->step & 1) == 0;
        o.color = on ? c : SLC_COLOR_OFF;
        /* **4 回/秒＝未ボンド / 2 回/秒＝ボンド済み・未接続。** */
        o.next_ms = (ls == SLC_LINK_UNBONDED) ? SLC_FAST_BLINK_MS : SLC_SLOW_BLINK_MS;
        r->step = (uint8_t)((r->step + 1) & 3);
        break;
    }

    case SLC_BATT_LOW:
    case SLC_BATT_REPLACE: {
        /* 橙 1 回（低下）／2 回（要交換）点滅して、長く休む。 */
        const uint8_t pulses = (st == SLC_BATT_REPLACE) ? 2 : 1;
        const uint32_t rest = (st == SLC_BATT_REPLACE) ? SLC_BATT_REPLACE_MS : SLC_BATT_LOW_MS;

        if (r->step >= pulses * 2) {
            r->step = 0;
        }
        bool on = (r->step % 2) == 0;
        o.color = on ? SLC_COLOR_AMBER : SLC_COLOR_OFF;
        r->step++;

        if (r->step >= pulses * 2) {
            o.next_ms = rest; /* 最後の消灯ぶんを休みに充てる */
            r->step = 0;
        } else {
            o.next_ms = on ? SLC_PULSE_MS : SLC_PULSE_GAP_MS;
        }
        break;
    }

    default:
        o.color = SLC_COLOR_OFF;
        o.next_ms = SLC_FAST_BLINK_MS * 4;
        break;
    }

    return o;
}

#endif /* HHKB_STATUS_LED_CORE_H */
