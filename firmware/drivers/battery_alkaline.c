/*
 * アルカリ乾電池（直列）の残量計。
 *
 * ZMK 標準の zmk,battery-voltage-divider と**読み方は同じ**で、
 * 違うのは % の出し方だけ。標準は lithium_ion_mv_to_pct() で
 * 3.45V 以下を 0% とするので、乾電池 2 本（2.4〜3.2V）では常に 0% になる。
 * docs/hardware/open-gaps.md #13。
 *
 * ADC の読み取り部分は ZMK の battery_voltage_divider.c（MIT・The ZMK
 * Contributors）に倣っている。battery_common.h はモジュールの外から
 * include できないので、channel_get だけ持ち直した。
 *
 * SPDX-License-Identifier: MIT
 */

#define DT_DRV_COMPAT hhkb_battery_alkaline

#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/util.h>

LOG_MODULE_REGISTER(hhkb_battery, CONFIG_SENSOR_LOG_LEVEL);

struct alk_config {
    uint8_t io_channel;
    uint32_t output_ohm;
    uint32_t full_ohm;
    uint16_t empty_mv;
    uint16_t full_mv;
};

struct alk_data {
    const struct device *adc;
    struct adc_channel_cfg acc;
    struct adc_sequence as;
    int16_t adc_raw;
    uint16_t millivolts;
    uint8_t state_of_charge;
};

/* 使える電圧の窓（empty..full）の中で、どこにいるかを % にする。
 *
 * **これは「アルカリの放電曲線」ではない。**曲線はメーカー資料でも
 * グラフでしか公開されておらず、目で読むと数字を捏造することになる
 * （この案件で最も高くついた失敗の型）。
 *
 * いま入れているのは電圧に対して線形の写像で、次の性質だけを主張する:
 *   - 単調（減り続ける。増えたように見えない）
 *   - 0% ＝ **この回路が動かなくなる電圧**（tools/circuit.py の BATT_V_MIN）
 *   - 100% ＝ 新品の開路電圧
 *
 * **本物の曲線は Task C4/C5 の放電実測で置き換える。**軽負荷（0.66mA）の
 * アルカリは終盤まで比較的なだらかに下がるので線形は悪い近似ではないが、
 * 「測っていない」ことは open-gaps #13 に書いたままにする。
 */
static uint8_t alkaline_mv_to_pct(const struct alk_config *cfg, uint16_t mv) {
    if (mv >= cfg->full_mv) {
        return 100;
    }
    if (mv <= cfg->empty_mv) {
        return 0;
    }
    return (uint8_t)(((uint32_t)(mv - cfg->empty_mv) * 100U) /
                     (uint32_t)(cfg->full_mv - cfg->empty_mv));
}

static int alk_sample_fetch(const struct device *dev, enum sensor_channel chan) {
    struct alk_data *data = dev->data;
    const struct alk_config *cfg = dev->config;
    struct adc_sequence *as = &data->as;

    if (chan != SENSOR_CHAN_GAUGE_VOLTAGE && chan != SENSOR_CHAN_GAUGE_STATE_OF_CHARGE &&
        chan != SENSOR_CHAN_ALL) {
        LOG_DBG("Unsupported channel: %d", chan);
        return -ENOTSUP;
    }

    int rc = adc_read(data->adc, as);
    as->calibrate = false;
    if (rc != 0) {
        LOG_DBG("Failed to read ADC: %d", rc);
        return rc;
    }

    int32_t val = data->adc_raw;
    adc_raw_to_millivolts(adc_ref_internal(data->adc), data->acc.gain, as->resolution, &val);

    /* 電池を外すとノイズで負が返る。そのまま uint に上げると巨大値 →
     * uint16 に折り返して**高残量に化け**、打ち止めが効かなくなる。 */
    if (val < 0) {
        val = 0;
    }
    uint32_t mv = (uint32_t)((uint64_t)val * cfg->full_ohm / cfg->output_ohm);
    data->millivolts = (uint16_t)MIN(mv, UINT16_MAX);
    data->state_of_charge = alkaline_mv_to_pct(cfg, data->millivolts);
    LOG_DBG("ADC raw %d => %u mV => %u%%", data->adc_raw, data->millivolts,
            data->state_of_charge);
    return 0;
}

static int alk_channel_get(const struct device *dev, enum sensor_channel chan,
                           struct sensor_value *val) {
    const struct alk_data *data = dev->data;

    switch (chan) {
    case SENSOR_CHAN_GAUGE_VOLTAGE:
        val->val1 = data->millivolts / 1000;
        val->val2 = (data->millivolts % 1000) * 1000U;
        break;
    case SENSOR_CHAN_GAUGE_STATE_OF_CHARGE:
        val->val1 = data->state_of_charge;
        val->val2 = 0;
        break;
    default:
        return -ENOTSUP;
    }
    return 0;
}

static const struct sensor_driver_api alk_api = {
    .sample_fetch = alk_sample_fetch,
    .channel_get = alk_channel_get,
};

static int alk_init(const struct device *dev) {
    struct alk_data *data = dev->data;
    const struct alk_config *cfg = dev->config;

    if (!device_is_ready(data->adc)) {
        LOG_ERR("ADC device is not ready");
        return -ENODEV;
    }

    data->as = (struct adc_sequence){
        .channels = BIT(0),
        .buffer = &data->adc_raw,
        .buffer_size = sizeof(data->adc_raw),
        .oversampling = 4,
        .calibrate = true,
    };

#ifdef CONFIG_ADC_NRFX_SAADC
    data->acc = (struct adc_channel_cfg){
        .gain = ADC_GAIN_1_6,
        .reference = ADC_REF_INTERNAL,
        /* 40µs。**500kΩ の分圧に必要な値**（充電時間 = 抵抗 × 入力容量）。
         * 既定の 10µs だと読みが低く出る。ZMK 標準の driver と同じ。 */
        .acquisition_time = ADC_ACQ_TIME(ADC_ACQ_TIME_MICROSECONDS, 40),
        .input_positive = SAADC_CH_PSELP_PSELP_AnalogInput0 + cfg->io_channel,
    };
    data->as.resolution = 12;
#else
#error Unsupported ADC
#endif

    return adc_channel_setup(data->adc, &data->acc);
}

#define ALK_INST(n)                                                                                \
    BUILD_ASSERT(DT_INST_PROP(n, full_millivolts) > DT_INST_PROP(n, empty_millivolts),             \
                 "full-millivolts must be above empty-millivolts");                                \
    static struct alk_data alk_data_##n = {                                                        \
        .adc = DEVICE_DT_GET(DT_IO_CHANNELS_CTLR(DT_DRV_INST(n))),                                 \
    };                                                                                             \
    static const struct alk_config alk_cfg_##n = {                                                 \
        .io_channel = DT_IO_CHANNELS_INPUT(DT_DRV_INST(n)),                                        \
        .output_ohm = DT_INST_PROP(n, output_ohms),                                                \
        .full_ohm = DT_INST_PROP(n, full_ohms),                                                    \
        .empty_mv = DT_INST_PROP(n, empty_millivolts),                                             \
        .full_mv = DT_INST_PROP(n, full_millivolts),                                               \
    };                                                                                             \
    DEVICE_DT_INST_DEFINE(n, &alk_init, NULL, &alk_data_##n, &alk_cfg_##n, POST_KERNEL,            \
                          CONFIG_SENSOR_INIT_PRIORITY, &alk_api);

DT_INST_FOREACH_STATUS_OKAY(ALK_INST)
