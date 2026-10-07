/*
 * スティックの中心を取り直すキー（&stick_recal）。
 *
 * **左右どちらにポッドがあっても 1 つのキーで効かせる**ため、
 * locality を GLOBAL にしてある。キーマップを持つのは左（セントラル）だけ
 * なので、右のポッドには届かないと意味が無い。GLOBAL だと ZMK が
 * 「全ペリフェラルへ転送 ＋ 自分でも実行」する（app/src/behavior.c）。
 *
 * そのため **この behavior はポッドの無い側のファームにも入る**
 * （キーマップは左右共通で、ノードは両方の devicetree にある）。
 * ポッドが無い側では何もしない。
 *
 * ⚠️ ノード名は 15 文字以内にすること。右へ送る payload の名前欄が
 *    16 バイトで、長いと切り詰められて右で見つからない
 *    （app/include/zmk/split/transport/types.h の behavior_dev[16]）。
 *
 * SPDX-License-Identifier: MIT
 */

#define DT_DRV_COMPAT hhkb_behavior_stick_recal

#include <zephyr/device.h>
#include <zephyr/logging/log.h>

#include <drivers/behavior.h>
#include <zmk/behavior.h>

#include "../drivers/stick_pod.h"

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

#if DT_HAS_COMPAT_STATUS_OKAY(DT_DRV_COMPAT)

static int on_pressed(struct zmk_behavior_binding *binding, struct zmk_behavior_binding_event event) {
#if IS_ENABLED(CONFIG_HHKB_STICK_POD)
    int rc = hhkb_stick_pod_recalibrate();

    if (rc < 0) {
        LOG_WRN("スティックの中心を取り直せない (%d)", rc);
    }
#endif
    return ZMK_BEHAVIOR_OPAQUE;
}

/* 離しも受ける。無いと、右で「Failed to invoke behavior」が毎回ログに出る
 * （behavior_keymap_binding_released が -ENOTSUP を返す）。 */
static int on_released(struct zmk_behavior_binding *binding, struct zmk_behavior_binding_event event) {
    return ZMK_BEHAVIOR_OPAQUE;
}

static const struct behavior_driver_api stick_recal_api = {
    .binding_pressed = on_pressed,
    .binding_released = on_released,
    .locality = BEHAVIOR_LOCALITY_GLOBAL,
#if IS_ENABLED(CONFIG_ZMK_BEHAVIOR_METADATA)
    .get_parameter_metadata = zmk_behavior_get_empty_param_metadata,
#endif
};

#define RECAL_INST(n)                                                                              \
    BEHAVIOR_DT_INST_DEFINE(n, NULL, NULL, NULL, NULL, POST_KERNEL,                                \
                            CONFIG_KERNEL_INIT_PRIORITY_DEFAULT, &stick_recal_api);

DT_INST_FOREACH_STATUS_OKAY(RECAL_INST)

#endif /* DT_HAS_COMPAT_STATUS_OKAY(DT_DRV_COMPAT) */
