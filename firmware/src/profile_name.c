/*
 * 広告するデバイス名に、登録先の番号を付ける（実機の再現）。
 *
 * 実機は「HHKB-Hybrid_n」（n = 登録先の数字キー 1〜4）で広告する
 * （PFU 取扱説明書 P3PC-6641-05 の接続手順の注記 *1
 * 「n にはペアリング情報を登録するキーの数字（1〜4）が表示されます」）。ホストの一覧で
 * 「どの番号に登録しようとしているか」が見える。こちらは SSKB_n。
 *
 * 仕組み:
 *   ZMK の広告は BT_LE_ADV_OPT_USE_NAME で、**広告を始めるたびに
 *   bt_get_name() を読む**。zmk_ble_set_device_name() が名前を変えて
 *   広告を張り直す（app/src/ble.c）。番号が変わるたびにそれを呼ぶ。
 *
 *   bt_set_name() は BT_SETTINGS で名前を保存するので、再起動後も
 *   前回の名前で広告する。最初の起動（何も保存されていない）は枠 0 なので、
 *   conf の CONFIG_BT_DEVICE_NAME を「<名前>_1」にしてある
 *   （tools/test_firmware.py が一致を見る）。
 *
 * ponytail: プロファイルの保存は ZMK が 60 秒遅らせる（SETTINGS_SAVE_DEBOUNCE）ので、
 *   切り替え直後に電池を抜くと名前と番号がずれて起動しうる。この事象は
 *   接続・切断のたびにも飛ぶので、次にそれが起きたときに直る。
 *
 * SPDX-License-Identifier: MIT
 */

#include <stdio.h>
#include <string.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/kernel.h>

#include <zmk/ble.h>
#include <zmk/event_manager.h>
#include <zmk/events/ble_active_profile_changed.h>

BUILD_ASSERT(IS_ENABLED(CONFIG_BT_DEVICE_NAME_DYNAMIC),
             "名前を実行中に変えるには CONFIG_BT_DEVICE_NAME_DYNAMIC が要る");

static int profile_name_listener(const zmk_event_t *eh) {
    const struct zmk_ble_active_profile_changed *ev = as_zmk_ble_active_profile_changed(eh);
    if (ev == NULL) {
        return ZMK_EV_EVENT_BUBBLE;
    }

    char name[CONFIG_BT_DEVICE_NAME_MAX + 1];
    snprintf(name, sizeof(name), "%s_%d", CONFIG_ZMK_KEYBOARD_NAME, ev->index + 1);

    /* 接続・切断でも飛ぶ。同じ名前なら張り直さない（接続中の広告を乱さない）。 */
    if (strcmp(name, bt_get_name()) != 0) {
        zmk_ble_set_device_name(name);
    }
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(hhkb_profile_name, profile_name_listener);
ZMK_SUBSCRIPTION(hhkb_profile_name, zmk_ble_active_profile_changed);
