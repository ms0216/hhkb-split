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
#include <stddef.h>
#include <stdint.h>

/* held_alt: 直前の押下を置き換えて出したか（呼び出し側が持つ）。戻り値: 出すコード */
static inline uint16_t bl_code(bool *held_alt, bool press, bool alt_now, uint16_t from, uint16_t to) {
    if (press) {
        *held_alt = alt_now;
    }
    return *held_alt ? to : from;
}

/*
 * **この入力を扱うか**（2026-10-15 に切り出し）。
 *
 * 元は `.c` 側の `if (event->type != INPUT_EV_KEY || event->code != cfg->from)`
 * にあったが、**そこは自動検査で一度も実行されていなかった**
 * （core の bl_code しか見ていなかった）。
 * 取り違えると、**関係ないイベントのコードまで書き換える**。
 *
 * ev_type / key_type … 呼び出し側が Zephyr の INPUT_EV_KEY を渡す
 */
static inline bool bl_applies(uint16_t ev_type, uint16_t key_type, uint16_t code, uint16_t from) {
    return ev_type == key_type && code == from;
}

/*
 * **どれか 1 つでもレイヤーが有効なら置き換える**（OR）。
 *
 * 元は `.c` 側のループ。`active` は呼び出し側が
 * `zmk_keymap_layer_active()` で埋めた配列。
 * ⚠️ **AND にすると、複数レイヤーを挙げたときに誰も踏めなくなる。**
 */
static inline bool bl_any_layer_active(const bool *active, size_t len) {
    for (size_t i = 0; i < len; i++) {
        if (active[i]) {
            return true;
        }
    }
    return false;
}
