/* 構文と型だけを見るための最小の代役。**シグネチャは上流（_upstream/）から写した。**
 * これで通っても「Zephyr で通る」ことにはならない（マクロの展開・リンクは見ていない）。 */
#pragma once
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
#define IS_ENABLED(x) (x)
#define BUILD_ASSERT(c, ...) _Static_assert(c, "" __VA_ARGS__)
#define ARG_UNUSED(x) (void)(x)
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define CLAMP(val, low, high) (((val) <= (low)) ? (low) : MIN(val, high))
#define BIT(n) (1UL << (n))
struct device { const char *name; const void *config; void *data; };
bool device_is_ready(const struct device *dev);
extern const struct device stub_dev;
#define DT_DRV_INST(n) n
#define DEVICE_DT_GET(n) (&stub_dev)
#define DT_NUM_INST_STATUS_OKAY(c) 1
#define DT_HAS_COMPAT_STATUS_OKAY(c) 1
#define DT_INST_PROP(n, p) STUB_##p
#define STUB_full_scale_permille 300
#define STUB_dead_zone_permille 40
#define STUB_curve_exponent 2
#define STUB_rest_period_ms 250
#define STUB_active_period_ms 12
#define STUB_absent_period_ms 2000
#define STUB_stuck_period_ms 2000
#define STUB_active_hold_ms 300
#define STUB_replay_gap_ms 16
#define STUB_stuck_after_seconds 300
#define STUB_centre_stable_lsb 3
#ifndef STUB_stuck_stable_lsb
#define STUB_stuck_stable_lsb 3
#endif
#define STUB_max_speed 1200
#define DT_INST_FOREACH_STATUS_OKAY(fn) fn(0)
#define POST_KERNEL 0
#define DEVICE_DT_INST_DEFINE(n, init, pm, data, cfg, lvl, prio, api) \
    const struct device stub_dev = {"stub", cfg, data}; int (*stub_init_##n)(const struct device *) = init; void *stub_pm_##n = pm
/* kernel */
typedef struct { int64_t t; } k_timeout_t;
#define K_MSEC(x) ((k_timeout_t){(x)})
#define K_SECONDS(x) K_MSEC((x) * 1000)
#define K_MINUTES(m) K_SECONDS((m) * 60)
#define K_NO_WAIT ((k_timeout_t){0})
#define K_FOREVER ((k_timeout_t){-1})
struct k_thread { int x; }; struct k_sem { int x; }; struct k_mutex { int x; };
struct k_work { int x; }; struct k_work_delayable { struct k_work work; };
typedef struct k_thread *k_tid_t; typedef char k_thread_stack_t;
typedef void (*k_thread_entry_t)(void *p1, void *p2, void *p3);
typedef void (*k_work_handler_t)(struct k_work *work);
#define K_THREAD_STACK_DEFINE(sym, size) char sym[size]
#define K_THREAD_STACK_SIZEOF(sym) sizeof(sym)
#define K_PRIO_PREEMPT(x) (x)
k_tid_t k_thread_create(struct k_thread *new_thread, k_thread_stack_t *stack, size_t stack_size, k_thread_entry_t entry, void *p1, void *p2, void *p3, int prio, uint32_t options, k_timeout_t delay);
int k_thread_name_set(k_tid_t thread, const char *str);
int k_sem_init(struct k_sem *sem, unsigned int initial_count, unsigned int limit);
int k_sem_take(struct k_sem *sem, k_timeout_t timeout);
void k_sem_give(struct k_sem *sem);
int k_mutex_init(struct k_mutex *mutex);
int k_mutex_lock(struct k_mutex *mutex, k_timeout_t timeout);
int k_mutex_unlock(struct k_mutex *mutex);
int64_t k_uptime_get(void);
void k_work_init_delayable(struct k_work_delayable *dwork, k_work_handler_t handler);
int k_work_schedule(struct k_work_delayable *dwork, k_timeout_t delay);
int k_work_reschedule(struct k_work_delayable *dwork, k_timeout_t delay);
/* atomic */
typedef long atomic_t;
#define ATOMIC_DEFINE(name, num_bits) atomic_t name[1 + ((num_bits) - 1) / 32]
bool atomic_test_bit(const atomic_t *target, int bit);
bool atomic_test_and_clear_bit(atomic_t *target, int bit);
void atomic_clear_bit(atomic_t *target, int bit);
void atomic_set_bit(atomic_t *target, int bit);
void atomic_set_bit_to(atomic_t *target, int bit, bool val);
/* log */
#define LOG_MODULE_REGISTER(...) extern int stub_log
#define LOG_MODULE_DECLARE(...) extern int stub_log
int stub_printf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
#define LOG_INF(...) stub_printf(__VA_ARGS__)
#define LOG_WRN(...) stub_printf(__VA_ARGS__)
#define LOG_ERR(...) stub_printf(__VA_ARGS__)
#define LOG_DBG(...) stub_printf(__VA_ARGS__)
#define CONFIG_INPUT_LOG_LEVEL 3
#define CONFIG_ZMK_LOG_LEVEL 3
#define CONFIG_INPUT_INIT_PRIORITY 90
#define CONFIG_KERNEL_INIT_PRIORITY_DEFAULT 40
#define CONFIG_I2C_NRFX_TRANSFER_TIMEOUT 10
#define CONFIG_HHKB_STICK_POD_STACK_SIZE 1024
#define CONFIG_HHKB_STICK_POD_THREAD_PRIORITY 8
#define CONFIG_HHKB_STICK_POD 1
#define CONFIG_SETTINGS 1
#define CONFIG_ZMK_SPLIT 1
#ifndef CONFIG_ZMK_SPLIT_ROLE_CENTRAL
#define CONFIG_ZMK_SPLIT_ROLE_CENTRAL 0
#endif
#define CONFIG_ZMK_BEHAVIOR_METADATA 0
/* i2c */
struct i2c_dt_spec { const struct device *bus; uint16_t addr; };
#define I2C_DT_SPEC_INST_GET(n) {.bus = &stub_dev, .addr = 0x2a}
bool i2c_is_ready_dt(const struct i2c_dt_spec *spec);
int i2c_read_dt(const struct i2c_dt_spec *spec, uint8_t *buf, uint32_t num_bytes);
/* pm */
enum pm_device_action { PM_DEVICE_ACTION_SUSPEND, PM_DEVICE_ACTION_RESUME, PM_DEVICE_ACTION_TURN_OFF, PM_DEVICE_ACTION_TURN_ON };
int pm_device_action_run(const struct device *dev, enum pm_device_action action);
#define PM_DEVICE_DT_INST_DEFINE(n, cb) int (*stub_pmcb_##n)(const struct device *, enum pm_device_action) = cb
#define PM_DEVICE_DT_INST_GET(n) ((void *)&stub_pmcb_##n)
/* input */
#define INPUT_BTN_0 0x100
#define INPUT_REL_X 0
#define INPUT_REL_Y 1
int input_report_key(const struct device *dev, uint16_t code, int32_t value, bool sync, k_timeout_t timeout);
int input_report_rel(const struct device *dev, uint16_t code, int32_t value, bool sync, k_timeout_t timeout);
/* settings */
typedef ssize_t (*settings_read_cb)(void *cb_arg, void *data, size_t len);
int settings_save_one(const char *name, const void *value, size_t val_len);
int settings_name_steq(const char *name, const char *key, const char **next);
#define SETTINGS_STATIC_HANDLER_DEFINE(_hname, _tree, _get, _set, _commit, _export) \
    int (*stub_set_##_hname)(const char *, size_t, settings_read_cb, void *) = _set; int (*stub_commit_##_hname)(void) = _commit
/* zmk */
typedef struct { int x; } zmk_event_t;
#define ZMK_EV_EVENT_BUBBLE 0
typedef int (*zmk_listener_callback_t)(const zmk_event_t *eh);
#define ZMK_LISTENER(mod, cb) zmk_listener_callback_t zmk_listener_##mod = cb;
#define ZMK_SUBSCRIPTION(mod, ev) extern int stub_sub_##mod##ev;
enum zmk_activity_state { ZMK_ACTIVITY_ACTIVE, ZMK_ACTIVITY_IDLE, ZMK_ACTIVITY_SLEEP };
struct zmk_activity_state_changed { enum zmk_activity_state state; };
struct zmk_activity_state_changed *as_zmk_activity_state_changed(const zmk_event_t *eh);
struct zmk_split_peripheral_status_changed { bool connected; };
struct zmk_split_peripheral_status_changed *as_zmk_split_peripheral_status_changed(const zmk_event_t *eh);
/* behavior */
struct zmk_behavior_binding { const char *behavior_dev; uint32_t param1, param2; };
struct zmk_behavior_binding_event { int layer; uint32_t position; int64_t timestamp; uint8_t source; };
typedef int (*behavior_keymap_binding_callback_t)(struct zmk_behavior_binding *binding, struct zmk_behavior_binding_event event);
enum behavior_locality { BEHAVIOR_LOCALITY_CENTRAL, BEHAVIOR_LOCALITY_EVENT_SOURCE, BEHAVIOR_LOCALITY_GLOBAL };
struct behavior_driver_api { enum behavior_locality locality; behavior_keymap_binding_callback_t binding_convert_central_state_dependent_params, binding_pressed, binding_released; };
#define ZMK_BEHAVIOR_OPAQUE 0
#define BEHAVIOR_DT_INST_DEFINE(n, init, pm, data, cfg, lvl, prio, api) const void *stub_beh_##n = api
