/*
 * 止まっている間に電流を流さないロータリーエンコーダの読み取り（左手・B 案）。
 *
 * EC12PL（24 クリック / 24 パルス）は、クリックで止まった位置で **片方の相が必ず開いていて、
 * もう片方は開閉の境目にある**（規格書の図一）。ZMK 標準の alps,ec11 は両方の相を常に
 * プルアップして両方の変化で割り込むので、境目の相が閉じて止まると電流が流れ続ける
 * （内蔵 13kΩ で約 0.2mA、外付け 100kΩ でも約 29µA。寝ている間も）。
 *
 * ここでは:
 *   - 「止まると必ず開いている相」を a-gpios に置き、**a だけ**をプルアップして割り込みに使う
 *   - 「境目の相」b は、ふだんは切り離しておく（入力バッファも切る）。a が動いた瞬間だけ
 *     プルアップして読み、すぐ切り離す
 *   - a が閉じたときと開いたときの b を比べる。**違えば 1 刻み進んだ**（閉じたときの b が向き）。
 *     同じなら途中まで回して戻しただけなので数えない
 * 止まっている間の電流は 0（a は開いている・b は切り離し）。外付けの抵抗も要らない。
 * b では割り込まないので、境目でばたついても ZMK を起こさない（スリープを妨げない）。
 * 標準の alps,ec11 は、どちらの相が動いても（数が進まなくても）ZMK に知らせ、それが
 * 「活動」と数えられる。電源管理も持たないので、寝ている間も外付けの抵抗に電流が流れる。
 *
 * 割り込みは「レベル」を使う。nRF ではエッジ割り込みが GPIOTE のチャネルを使い、
 * レベルは SENSE（キー走査と同じ仕組み）で済む。レベルなら「読んでから構え直すまでの間に
 * 変わった」も取りこぼさない。
 *
 * ⚠️ どちらの相が「必ず開いている側」かは、規格書の図では決めきれない（時計回りの図は
 *    A、反時計回りの図は B がそう見える）。**現物をテスターで見て、a-gpios / b-gpios を決める。**
 *    向きが逆なら invert を付ける。**実機では未実行。**
 */
#define DT_DRV_COMPAT hhkb_encoder_gated

#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/pm/device.h>

LOG_MODULE_REGISTER(encoder_gated, CONFIG_SENSOR_LOG_LEVEL);

#define FULL_ROTATION 360

struct eg_config {
    struct gpio_dt_spec a;
    struct gpio_dt_spec b;
    uint16_t steps;      /* 1 回転の刻みの数 */
    uint16_t settle_us;  /* b をプルアップしてから読むまで */
    bool invert;
};

struct eg_data {
    const struct device *dev;
    struct gpio_callback a_cb;
    struct k_work work;
    sensor_trigger_handler_t handler;
    const struct sensor_trigger *trigger;
    int8_t pulses;
    bool a_closed;
    bool b_at_close;
    bool running;
};

/* b を一瞬だけプルアップして読む。読んだら切り離す（電流も入力バッファも止める）。 */
static bool eg_read_b(const struct eg_config *cfg) {
    gpio_pin_configure_dt(&cfg->b, GPIO_INPUT | GPIO_PULL_UP);
    k_busy_wait(cfg->settle_us);
    int v = gpio_pin_get_dt(&cfg->b);
    gpio_pin_configure(cfg->b.port, cfg->b.pin, GPIO_DISCONNECTED);
    return v > 0;
}

/* いまの a の反対側のレベルを待つ。 */
static void eg_arm(const struct device *dev) {
    const struct eg_config *cfg = dev->config;
    struct eg_data *data = dev->data;

    gpio_pin_interrupt_configure_dt(&cfg->a, data->a_closed ? GPIO_INT_LEVEL_INACTIVE
                                                            : GPIO_INT_LEVEL_ACTIVE);
}

/*
 * **a が変わったその場（割り込みの中）で b を読む。**待ってから読むと、速く回したとき b がもう
 * 次の状態へ進んでいて、取りこぼすか逆向きに数える（規格書の位相差は 360°/s で 3.5ms 以上。
 * 1 秒に 2 回転で 2ms を切る。最初の版は 2ms 待っていた・2026-10-07 の粗探しで発覚）。
 * チャタリングは待たずに全部数える: a がばたついても、その間 b が変わらなければ
 * 「閉じたときの b = 開いたときの b」で差し引き 0 になる。
 * 割り込みの中の仕事は、ピンの設定 3 回と settle-us の待ち（既定 50µs）だけ。
 */
static void eg_a_isr(const struct device *port, struct gpio_callback *cb, uint32_t pins) {
    struct eg_data *data = CONTAINER_OF(cb, struct eg_data, a_cb);
    const struct device *dev = data->dev;
    const struct eg_config *cfg = dev->config;

    /* レベル割り込みなので、まず止める（止めないと鳴り続ける）。最後に反対のレベルで構え直す。 */
    gpio_pin_interrupt_configure_dt(&cfg->a, GPIO_INT_DISABLE);
    if (!data->running) {
        return;
    }

    bool closed = gpio_pin_get_dt(&cfg->a) > 0;
    bool stepped = false;
    if (closed != data->a_closed) {
        bool b = eg_read_b(cfg);
        if (closed) {
            data->b_at_close = b;
        } else if (b != data->b_at_close) {
            data->pulses += (data->b_at_close != cfg->invert) ? 1 : -1;
            stepped = true;
        }
        data->a_closed = closed;
    }
    eg_arm(dev);

    if (stepped) {
        k_work_submit(&data->work); /* ZMK への知らせは割り込みの外で */
    }
}

static void eg_work(struct k_work *work) {
    struct eg_data *data = CONTAINER_OF(work, struct eg_data, work);

    if (data->running && data->handler != NULL) {
        data->handler(data->dev, data->trigger);
    }
}

static int eg_sample_fetch(const struct device *dev, enum sensor_channel chan) {
    ARG_UNUSED(dev);
    ARG_UNUSED(chan);
    return 0; /* 数えるのは割り込み側。ここですることは無い */
}

static int eg_channel_get(const struct device *dev, enum sensor_channel chan,
                          struct sensor_value *val) {
    const struct eg_config *cfg = dev->config;
    struct eg_data *data = dev->data;

    if (chan != SENSOR_CHAN_ROTATION) {
        return -ENOTSUP;
    }

    unsigned int key = irq_lock(); /* 割り込みの中で足している */
    int32_t pulses = data->pulses;
    data->pulses = 0;
    irq_unlock(key);

    /* alps,ec11 と同じ単位（度）で返す。ZMK は triggers-per-rotation で刻みに戻す。 */
    val->val1 = (pulses * FULL_ROTATION) / cfg->steps;
    val->val2 = (pulses * FULL_ROTATION) % cfg->steps;
    if (val->val2 != 0) {
        val->val2 *= 1000000;
        val->val2 /= cfg->steps;
    }
    return 0;
}

static int eg_trigger_set(const struct device *dev, const struct sensor_trigger *trig,
                          sensor_trigger_handler_t handler) {
    struct eg_data *data = dev->data;

    data->trigger = trig;
    data->handler = handler;
    return 0;
}

static const struct sensor_driver_api eg_api = {
    .trigger_set = eg_trigger_set,
    .sample_fetch = eg_sample_fetch,
    .channel_get = eg_channel_get,
};

static int eg_start(const struct device *dev) {
    const struct eg_config *cfg = dev->config;
    struct eg_data *data = dev->data;

    if (gpio_pin_configure_dt(&cfg->a, GPIO_INPUT) ||
        gpio_pin_configure(cfg->b.port, cfg->b.pin, GPIO_DISCONNECTED)) {
        return -EIO;
    }
    data->a_closed = gpio_pin_get_dt(&cfg->a) > 0;
    data->b_at_close = data->a_closed ? eg_read_b(cfg) : false;
    data->running = true;
    eg_arm(dev);
    return 0;
}

/* 寝る前に全部切り離す。a が閉じたまま止まっていても電流を流さず、System OFF からも起こさない。 */
static void eg_stop(const struct device *dev) {
    const struct eg_config *cfg = dev->config;
    struct eg_data *data = dev->data;

    data->running = false;
    gpio_pin_interrupt_configure_dt(&cfg->a, GPIO_INT_DISABLE);
    k_work_cancel(&data->work);
    gpio_pin_configure(cfg->a.port, cfg->a.pin, GPIO_DISCONNECTED);
    gpio_pin_configure(cfg->b.port, cfg->b.pin, GPIO_DISCONNECTED);
}

#if IS_ENABLED(CONFIG_PM_DEVICE)
static int eg_pm_action(const struct device *dev, enum pm_device_action action) {
    switch (action) {
    case PM_DEVICE_ACTION_SUSPEND:
        eg_stop(dev);
        return 0;
    case PM_DEVICE_ACTION_RESUME:
        return eg_start(dev);
    default:
        return -ENOTSUP;
    }
}
#endif

static int eg_init(const struct device *dev) {
    const struct eg_config *cfg = dev->config;
    struct eg_data *data = dev->data;

    if (!gpio_is_ready_dt(&cfg->a) || !gpio_is_ready_dt(&cfg->b)) {
        LOG_ERR("GPIO が使えない");
        return -ENODEV;
    }
    data->dev = dev;
    k_work_init(&data->work, eg_work);
    gpio_init_callback(&data->a_cb, eg_a_isr, BIT(cfg->a.pin));
    if (gpio_add_callback(cfg->a.port, &data->a_cb) < 0) {
        return -EIO;
    }
    return eg_start(dev);
}

#define EG_INST(n)                                                                                 \
    BUILD_ASSERT(DT_INST_PROP(n, steps) > 0, "steps は 1 以上");                                    \
    static struct eg_data eg_data_##n;                                                             \
    static const struct eg_config eg_config_##n = {                                                \
        .a = GPIO_DT_SPEC_INST_GET(n, a_gpios),                                                    \
        .b = GPIO_DT_SPEC_INST_GET(n, b_gpios),                                                    \
        .steps = DT_INST_PROP(n, steps),                                                           \
        .settle_us = DT_INST_PROP(n, settle_us),                                                   \
        .invert = DT_INST_PROP(n, invert),                                                         \
    };                                                                                             \
    PM_DEVICE_DT_INST_DEFINE(n, eg_pm_action);                                                     \
    DEVICE_DT_INST_DEFINE(n, eg_init, PM_DEVICE_DT_INST_GET(n), &eg_data_##n, &eg_config_##n,      \
                          POST_KERNEL, CONFIG_SENSOR_INIT_PRIORITY, &eg_api);

DT_INST_FOREACH_STATUS_OKAY(EG_INST)
