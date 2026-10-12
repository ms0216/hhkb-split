/*
 * 起動したときの土台のレイヤーを選ぶ（CONFIG_HHKB_BOOT_LAYER_ID）。
 *
 * キーマップは Mac 面（0）が先頭で、ZMK は先頭を既定にする。Windows 面（1）で起動する版が要る
 * （利用者・2026-10-12）。レイヤーの並びを入れ替えると番号で書いてある所（conditional-layers・
 * listener の上書き・tools/test_invariants.py）が全部ずれるので、起動時に &to と同じことをする。
 * スリープからの復帰も再起動なので、毎回ここを通る。Fn+Ctrl の &to BASE_MAC で Mac 面へ戻れる
 * （次に起動するとまた Windows 面）。
 *
 * SPDX-License-Identifier: MIT
 */

#include <zephyr/init.h>
#include <zephyr/kernel.h>

#include <zmk/keymap.h>

static int hhkb_boot_layer_init(void) {
    return zmk_keymap_layer_to(CONFIG_HHKB_BOOT_LAYER_ID, false);
}

SYS_INIT(hhkb_boot_layer_init, APPLICATION, 99);
