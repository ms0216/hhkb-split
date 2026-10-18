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
    /* ⚠️ **足し算が溢れると、向きが反転する。**
     * 2026-10-15 の監査で見つかった。`int8_t` に `+=` していたので、
     * 読み出しが遅れて 127 刻み溜まると **−128 に折り返して逆回転**になる。
     * ZMK は普通トリガで即座に読む（1〜2 刻み）が、スリープ中や
     * ワークキューが詰まったときは溜まりうる。
     * **型を広げても限界が遠のくだけ**なので、下限・上限で飽和させる
     * （EG_PULSES_MAX）。溢れるほど溜まったら、何刻みだったかはもう
     * 意味を持たない——**向きだけは絶対に間違えない**方を採る。 */
    int16_t pulses;
};

/* 飽和の限界。1 回転 20〜30 刻みのつまみで、これだけ溜まるのは
 * 読み出しが完全に止まっているとき。 */
#define EG_PULSES_MAX 4096

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
        /* 符号は ZMK 標準の alps,ec11 と同じにする: 規格書の図一の時計回り（a 閉 → b 閉 → a 開 → b 開）は
         * −1（ec11.c の表で 4 回とも −1）。同じ配線のまま A 案と B 案を入れ替えても、回す向きが変わらない。
         * 逆にしたいときは devicetree の invert。 */
        step = (c->b_at_close != invert) ? 1 : -1;
        /* **飽和させる。**溢れて符号が反転するより、頭打ちのほうが害が小さい。 */
        if (step > 0) {
            if (c->pulses < EG_PULSES_MAX) {
                c->pulses++;
            }
        } else {
            if (c->pulses > -EG_PULSES_MAX) {
                c->pulses--;
            }
        }
    }
    c->a_closed = a_closed_now;
    return step;
}

#endif
