/*
 * 入力プロセッサ: ポインタの動き（REL_X / REL_Y）を、BLE では「1 個ずつ、届いてから次」を守って自分で送る。
 *
 * なぜ要るか（2026-10-13・ある Windows PC で BLE のときだけカクつき、止めてもすぐ止まらない）:
 * ZMK は動き 1 回ごとにレポートを 1 個作り、最大 20 個まで列に溜めて送る（app/src/hog.c）。
 * 相手が 1 秒に 27 個しか受け取れないのに 60〜80 個作ると、列が溜まって遅れ（最大 約 0.7 秒）、あふれた分は捨てられる。
 * ここでは動きを ZMK に渡さず（STOP）、足し算して、前の 1 個の送信完了を待ってからまとめて送る。
 *
 * - 効くのは BLE でホストへ送るときだけ。USB のとき・無効のとき・右手（ペリフェラル）では素通し。
 * - ボタンとホイールは素通し（ZMK のふつうの経路）。
 * - **listener の「いちばん最後」に置く**（向きや倍率を済ませた値を数えるため）。レイヤーの上書きの中に置くなら process-next を付ける
 *   （上書きの中の STOP は、process-next が無いと捨てられる: app/src/pointing/input_listener.c）。
 * - CONFIG_HHKB_BLE_POINTER_PACE_ACTIVE=n（既定）では素通し。試す版だけ y にする。
 *
 * SPDX-License-Identifier: MIT
 */

#define DT_DRV_COMPAT hhkb_input_processor_ble_pace

#include <zephyr/device.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <drivers/input_processor.h>

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#define BPP_ACTIVE                                                                                 \
    (IS_ENABLED(CONFIG_HHKB_BLE_POINTER_PACE_ACTIVE) && IS_ENABLED(CONFIG_ZMK_BLE) &&              \
     (!IS_ENABLED(CONFIG_ZMK_SPLIT) || IS_ENABLED(CONFIG_ZMK_SPLIT_ROLE_CENTRAL)))

#if BPP_ACTIVE

#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>

#include <zmk/ble.h>
#include <zmk/endpoints.h>
#include <zmk/hid.h>

#include "ble_pointer_pace_core.h"

#define BPP_WATCHDOG_MS 300 /* 「送れた」がこれだけ来なければ、切れたと見て待つのをやめる */
#define BPP_RETRY_MS 4      /* 送る場所が無かったときの、やり直しまでの間 */

static struct bpp st;
static struct k_spinlock lock;
static const struct bt_gatt_attr *mouse_attr;
static bool searched;
static int64_t sent_at;

static void pace_work_fn(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(pace_work, pace_work_fn);

/* HID サービスの中から「マウスの入力レポート」の値の属性を探す。番号で決め打ちしない
 * （ZMK は &hog_svc.attrs[13] と書いているが、設定で並びが変わる）。
 * 目印は Report Reference 記述子（id = マウス・type = 入力）。その 2 つ前が値。 */
static void find_mouse_attr(void) {
    searched = true;
    STRUCT_SECTION_FOREACH(bt_gatt_service_static, svc) {
        for (size_t i = 2; i < svc->attr_count; i++) {
            const struct bt_gatt_attr *a = &svc->attrs[i];
            const uint8_t *ref = a->user_data;
            if (bt_uuid_cmp(a->uuid, BT_UUID_HIDS_REPORT_REF) != 0 || ref == NULL) {
                continue;
            }
            if (ref[0] == ZMK_HID_REPORT_ID_MOUSE && ref[1] == 0x01 &&
                bt_uuid_cmp(svc->attrs[i - 2].uuid, BT_UUID_HIDS_REPORT) == 0) {
                mouse_attr = &svc->attrs[i - 2];
                return;
            }
        }
    }
    LOG_ERR("マウスの入力レポートの属性が見つからない。動きは ZMK のふつうの経路で送る");
}

static void sent_cb(struct bt_conn *conn, void *user_data) {
    K_SPINLOCK(&lock) { bpp_done(&st); }
    k_work_reschedule(&pace_work, K_NO_WAIT); /* 溜まった分があれば続けて送る。BT の文脈からは直接送らない */
}

static void try_send(void) {
    int16_t dx = 0, dy = 0;
    bool go = false;

    K_SPINLOCK(&lock) { go = bpp_take(&st, &dx, &dy); }
    if (!go) {
        return;
    }

    int err = -ENOTCONN;
    struct bt_conn *conn = zmk_ble_active_profile_conn();
    if (conn != NULL) {
        struct zmk_hid_mouse_report_body body = {
            .buttons = zmk_hid_get_mouse_report()->body.buttons,
            .d_x = dx,
            .d_y = dy,
        };
        struct bt_gatt_notify_params params = {
            .attr = mouse_attr,
            .data = &body,
            .len = sizeof(body),
            .func = sent_cb,
        };
        err = bt_gatt_notify_cb(conn, &params);
        if (err == -EPERM) {
            bt_conn_set_security(conn, BT_SECURITY_L2);
        }
        bt_conn_unref(conn);
    }

    if (err == 0) {
        sent_at = k_uptime_get();
        k_work_reschedule(&pace_work, K_MSEC(BPP_WATCHDOG_MS));
    } else if (err == -ENOMEM) {
        K_SPINLOCK(&lock) { bpp_undo(&st, dx, dy); }
        k_work_reschedule(&pace_work, K_MSEC(BPP_RETRY_MS));
    } else {
        /* つながっていない・購読されていない等。この分は捨てる（溜め続けて、つながった瞬間に飛ばさない） */
        K_SPINLOCK(&lock) {
            bpp_done(&st);
            st.ax = st.ay = 0;
        }
    }
}

static void pace_work_fn(struct k_work *work) {
    K_SPINLOCK(&lock) {
        if (st.in_flight && k_uptime_get() - sent_at >= BPP_WATCHDOG_MS) {
            bpp_done(&st);
        }
    }
    try_send();
}

#endif /* BPP_ACTIVE */

static int bpp_handle_event(const struct device *dev, struct input_event *event, uint32_t param1,
                            uint32_t param2, struct zmk_input_processor_state *state) {
#if BPP_ACTIVE
    if (event->type != INPUT_EV_REL ||
        (event->code != INPUT_REL_X && event->code != INPUT_REL_Y)) {
        return ZMK_INPUT_PROC_CONTINUE;
    }
    if (!searched) {
        find_mouse_attr();
    }
    if (mouse_attr == NULL || zmk_endpoint_get_selected().transport != ZMK_TRANSPORT_BLE) {
        return ZMK_INPUT_PROC_CONTINUE;
    }

    K_SPINLOCK(&lock) { bpp_add(&st, event->code == INPUT_REL_X, event->value); }
    if (event->sync) {
        try_send(); /* X と Y は別のイベントで来る。そろった所（sync）で 1 個にして送る */
    }
    return ZMK_INPUT_PROC_STOP;
#else
    return ZMK_INPUT_PROC_CONTINUE;
#endif
}

static struct zmk_input_processor_driver_api bpp_driver_api = {
    .handle_event = bpp_handle_event,
};

#define BPP_INST(n)                                                                                \
    DEVICE_DT_INST_DEFINE(n, NULL, NULL, NULL, NULL, POST_KERNEL,                                  \
                          CONFIG_KERNEL_INIT_PRIORITY_DEFAULT, &bpp_driver_api);

DT_INST_FOREACH_STATUS_OKAY(BPP_INST)
