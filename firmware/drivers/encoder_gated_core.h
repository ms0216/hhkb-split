/*
 * encoder_gated.c の数える部分だけを切り出したもの。Zephyr に依らないので、普通の C コンパイラで
 * 模擬入力を流して確かめられる（tools/test_encoder_gated.py）。ドライバはこれを呼ぶ。
 *
 * 規則: a が変わるたびに b を読む。a が閉じたときの b を覚え、a が開いたときの b と違えば 1 刻み
 * （閉じたときの b が向き）。同じなら、途中まで回して戻したか、a がばたついただけ。
 */
#ifndef HHKB_ENCODER_GATED_CORE_H
#define HHKB_ENCODER_GATED_CORE_H

#include <stdbool.h>
#include <stdint.h>

struct eg_core {
    bool a_closed;
    bool b_at_close;
    int8_t pulses;
};

static inline void eg_core_start(struct eg_core *c, bool a_closed, bool b_now) {
    c->a_closed = a_closed;
    c->b_at_close = a_closed ? b_now : false;
    c->pulses = 0;
}

/* a の割り込みのたびに呼ぶ。a が本当に変わっていて 1 刻み進んだら +1/-1、それ以外は 0。 */
static inline int eg_core_edge(struct eg_core *c, bool a_closed_now, bool b_now, bool invert) {
    int step = 0;
    if (a_closed_now == c->a_closed) {
        return 0;
    }
    if (a_closed_now) {
        c->b_at_close = b_now;
    } else if (b_now != c->b_at_close) {
        /* 時計回り（規格書の図一: a 閉 → b 閉 → a 開 → b 開）は、a が閉じた時点で b が開いている → +1 */
        step = (c->b_at_close == invert) ? 1 : -1;
        c->pulses += (int8_t)step;
    }
    c->a_closed = a_closed_now;
    return step;
}

#endif
