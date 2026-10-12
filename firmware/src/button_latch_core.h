/*
 * 「押した瞬間のレイヤーで、どのボタンとして出すかを決め、離すときも同じボタンで出す」の中身。
 * Zephyr に依らない（tools/test_button_latch.py が普通の C コンパイラで通す）。
 *
 * なぜ要るか: ZMK の listener のレイヤー上書きは、イベントが来た**その時点**のレイヤーで処理を選ぶ。
 * 「左 Ctrl ＋ 押し込み = 右ボタン」を上書きだけで作ると、**Ctrl を先に離す → 押し込みを離す**の順で
 * 離しが左ボタンとして出て、右ボタンが押されたまま残る。
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/* held_alt: 直前の押下を置き換えて出したか（呼び出し側が持つ）。戻り値: 出すコード */
static inline uint16_t bl_code(bool *held_alt, bool press, bool alt_now, uint16_t from, uint16_t to) {
    if (press) {
        *held_alt = alt_now;
    }
    return *held_alt ? to : from;
}
