/*
 * 入力プロセッサ: 指定したレイヤーのどれかが立っている間に押されたボタンを、別のボタンとして出す。
 * **離しは、押したときに決めたボタンで出す**（途中でレイヤーが変わっても、押したままにならない）。
 *
 * 使い道（2026-10-12・利用者と決めた割り当て）: スティックの押し込み = 左クリック。
 * 左 Ctrl を押している間（STK_SLOW）か Fn の間（FN）の押し込み = 右クリック。
 *
 * SPDX-License-Identifier: MIT
 */

#define DT_DRV_COMPAT hhkb_input_processor_button_latch

#include <zephyr/device.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <drivers/input_processor.h>
#include <zmk/keymap.h>

#include "button_latch_core.h"

LOG_MODULE_DECLARE(zmk, CONFIG_ZMK_LOG_LEVEL);

struct bl_config {
    uint16_t from;
    uint16_t to;
    size_t layers_len;
    uint8_t layers[];
};

struct bl_data {
    bool held_alt;
};

static int bl_handle_event(const struct device *dev, struct input_event *event, uint32_t param1,
                           uint32_t param2, struct zmk_input_processor_state *state) {
    const struct bl_config *cfg = dev->config;
    struct bl_data *data = dev->data;

    if (event->type != INPUT_EV_KEY || event->code != cfg->from) {
        return ZMK_INPUT_PROC_CONTINUE;
    }

    bool alt_now = false;
    for (size_t i = 0; i < cfg->layers_len; i++) {
        alt_now = alt_now || zmk_keymap_layer_active(cfg->layers[i]);
    }
    event->code = bl_code(&data->held_alt, event->value != 0, alt_now, cfg->from, cfg->to);
    return ZMK_INPUT_PROC_CONTINUE;
}

static struct zmk_input_processor_driver_api bl_driver_api = {
    .handle_event = bl_handle_event,
};

#define BL_INST(n)                                                                                 \
    static struct bl_data bl_data_##n;                                                             \
    static const struct bl_config bl_config_##n = {                                                \
        .from = DT_INST_PROP(n, from),                                                             \
        .to = DT_INST_PROP(n, to),                                                                 \
        .layers_len = DT_INST_PROP_LEN(n, layers),                                                 \
        .layers = DT_INST_PROP(n, layers),                                                         \
    };                                                                                             \
    DEVICE_DT_INST_DEFINE(n, NULL, NULL, &bl_data_##n, &bl_config_##n, POST_KERNEL,                \
                          CONFIG_KERNEL_INIT_PRIORITY_DEFAULT, &bl_driver_api);

DT_INST_FOREACH_STATUS_OKAY(BL_INST)
