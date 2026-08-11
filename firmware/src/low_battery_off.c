/*
 * 打ち止め電圧を割ったら、自分から止まる（open-gaps #25b）。
 *
 * 何が起きるか:
 *   レールが 1.7V を割ると nRF52840 はブラウンアウトでリセットする。
 *   電池は負荷が消えると電圧が戻るので、リセット → 起動 → 広告 →
 *   電圧降下 → リセット を繰り返す。
 *     - 残り少ない電池を早く使い切る
 *     - 使う側からは故障に見える
 *     - **低電圧での flash 書き込みでペアリング情報が壊れうる**
 *       （nRF52840 の NVMC は VDD ≧ 1.7V が条件）
 *
 * どう止めるか:
 *   ZMK が電池を測るたび（ZMK_BATTERY_REPORT_INTERVAL・既定 60 秒）に
 *   出す zmk_battery_state_changed を待ち受け、**その場で driver が
 *   キャッシュしている電圧**を読む（ADC を余分に回さない）。
 *   打ち止め（devicetree の empty-millivolts）を下回った状態が
 *   規定回数続いたら zmk_pm_soft_off() に入る。
 *
 * 復帰:
 *   電池を替えれば、背面の電源スイッチが電池を機械的に切り離しているので
 *   入れ直しで起動する。soft off の wake ピンには依存しない。
 *
 * ⚠️ **これはビルドが通っているだけで、実機では一度も動かしていない。**
 *    確かめるのは Task C4/C5（電池を実際に使い切る試験）。
 *
 * SPDX-License-Identifier: MIT
 */

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <zmk/event_manager.h>
#include <zmk/events/battery_state_changed.h>
#include <zmk/pm.h>

LOG_MODULE_DECLARE(hhkb_battery, CONFIG_SENSOR_LOG_LEVEL);

#define BATTERY_NODE DT_CHOSEN(zmk_battery)

BUILD_ASSERT(DT_NODE_HAS_PROP(BATTERY_NODE, empty_millivolts),
             "chosen zmk,battery に empty-millivolts が無い。"
             "hhkb,battery-alkaline を使うこと");

#define EMPTY_MV DT_PROP(BATTERY_NODE, empty_millivolts)

static const struct device *const battery = DEVICE_DT_GET(BATTERY_NODE);

static int low_battery_listener(const zmk_event_t *eh) {
    static uint8_t consecutive;

    if (as_zmk_battery_state_changed(eh) == NULL) {
        return ZMK_EV_EVENT_BUBBLE;
    }

    /* **測り直さない。**この事象は ZMK が測った直後に出るので、
     * driver のキャッシュを読むだけでよい（sensor_channel_get は
     * fetch 済みの値を返す）。ADC をもう一度回すと電池を余分に使う。 */
    struct sensor_value voltage;
    int rc = sensor_channel_get(battery, SENSOR_CHAN_GAUGE_VOLTAGE, &voltage);
    if (rc != 0) {
        LOG_WRN("電池電圧が読めない (%d)。判定を飛ばす", rc);
        return ZMK_EV_EVENT_BUBBLE;
    }

    uint32_t mv = voltage.val1 * 1000U + voltage.val2 / 1000U;
    if (mv > EMPTY_MV) {
        consecutive = 0;
        return ZMK_EV_EVENT_BUBBLE;
    }

    consecutive++;
    LOG_WRN("電池が打ち止め %u mV を下回った（%u mV・%u 回目）", (unsigned)EMPTY_MV,
            (unsigned)mv, (unsigned)consecutive);

    /* 1 回では止めない。BLE 送信中は電池の内部抵抗ぶん一時的に下がる。 */
    if (consecutive < CONFIG_HHKB_LOW_BATTERY_SOFT_OFF_SAMPLES) {
        return ZMK_EV_EVENT_BUBBLE;
    }

    LOG_ERR("電池が尽きた。soft off に入る（電池を替えて電源を入れ直すこと）");
    zmk_pm_soft_off();
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(hhkb_low_battery, low_battery_listener);
ZMK_SUBSCRIPTION(hhkb_low_battery, zmk_battery_state_changed);
