/*
 * ポインタの動きを「溜めない・捨てない」で BLE へ送るための、数える部分だけ。
 * Zephyr に依らない（tools/test_ble_pointer_pace.py が普通の C コンパイラで通す）。
 *
 * 決まり: 送ったレポートが相手に届く（送信完了）まで、次を送らない。その間に来た動きは足し算しておき、
 * 完了したらまとめて 1 個で送る。だから、通信が遅い相手でも「順番待ちの列」ができず、動きも減らない。
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

struct bpp {
    int32_t ax, ay; /* まだ送っていない動き */
    bool in_flight; /* 送って、完了を待っている */
};

static inline void bpp_add(struct bpp *p, bool is_x, int32_t v) {
    if (is_x) {
        p->ax += v;
    } else {
        p->ay += v;
    }
}

static inline int32_t bpp_clamp16(int32_t v) { return v > 32767 ? 32767 : (v < -32767 ? -32767 : v); }

/* 送ってよければ、送る量を取り出して true。送信中、または送る物が無ければ false。 */
static inline bool bpp_take(struct bpp *p, int16_t *dx, int16_t *dy) {
    if (p->in_flight || (p->ax == 0 && p->ay == 0)) {
        return false;
    }
    int32_t x = bpp_clamp16(p->ax), y = bpp_clamp16(p->ay);
    p->ax -= x;
    p->ay -= y;
    *dx = (int16_t)x;
    *dy = (int16_t)y;
    p->in_flight = true;
    return true;
}

/* 送信完了（または、つながっていないので諦めた）。 */
static inline void bpp_done(struct bpp *p) { p->in_flight = false; }

/* 送れなかった（送る場所が一時的に無い）。量を足し戻して、あとでやり直す。 */
static inline void bpp_undo(struct bpp *p, int16_t dx, int16_t dy) {
    p->ax += dx;
    p->ay += dy;
    p->in_flight = false;
}
