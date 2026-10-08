/* Review harness: runs the draft stick_pod.c state machine (unmodified source,
 * author's stub header) against a scripted pod on a virtual clock.
 * Not a Zephyr build: proves logic only, not API correctness. */
#include "stub_all.h"
#include "stick_pod_proto.h"
#include <setjmp.h>
#include <stdlib.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

/* ---- virtual world ---- */
static int64_t now_ms = 1;
static int64_t end_ms;
static jmp_buf done;
static int verbose;

struct pod {
    bool present, pressed, prev_pressed;
    uint8_t boot_id, seq, pc, rc, version;
    uint16_t t, x, y;
} pod = {.present = true, .boot_id = 7, .version = 1, .t = 1000, .x = 500, .y = 500};

static void (*world)(int64_t now);
static void world_step(void) {
    if (world) world(now_ms);
    if (pod.pressed != pod.prev_pressed) {
        if (pod.pressed) pod.pc = (pod.pc + 1) & 15; else pod.rc = (pod.rc + 1) & 15;
        pod.prev_pressed = pod.pressed;
    }
}
/* fine-grained time advance so button edges scripted between polls are counted */
static void advance(int64_t ms) {
    while (ms-- > 0) { now_ms++; world_step(); }
    if (now_ms >= end_ms) longjmp(done, 1);
}

/* ---- recorded outputs ---- */
#define MAXEV 200000
static struct ev { int64_t t; int kind; int code; int val; } evs[MAXEV];
static int nev;
static int64_t last_read_ms;
static int n_reads, bus_active = 1, max_bus_active_outside;
static int64_t rel_x, rel_y;
static int zero_events;
static int fail_input; /* make input_report_key fail N times */

/* ---- stubs ---- */
int stub_log;
int stub_printf(const char *fmt, ...) {
    if (!verbose) return 0;
    va_list ap; va_start(ap, fmt);
    printf("    [%8lld] ", (long long)now_ms); vprintf(fmt, ap); printf("\n"); va_end(ap); return 0;
}
bool device_is_ready(const struct device *dev) { return true; }
static k_thread_entry_t t_entry; static void *t_p1;
k_tid_t k_thread_create(struct k_thread *t, k_thread_stack_t *s, size_t n, k_thread_entry_t e, void *p1, void *p2, void *p3, int prio, uint32_t o, k_timeout_t d) { t_entry = e; t_p1 = p1; return t; }
int k_thread_name_set(k_tid_t t, const char *s) { return 0; }
static int sem;
int k_sem_init(struct k_sem *s, unsigned int i, unsigned int l) { sem = 0; return 0; }
static int spin_guard; static int64_t spin_t;
int k_sem_take(struct k_sem *s, k_timeout_t to) {
    if (sem) { sem = 0; return 0; }
    if (to.t < 0) { if (verbose) printf("    [%8lld] thread blocked forever\n", (long long)now_ms); longjmp(done, 2); }
    if (to.t == 0) { if (spin_t == now_ms) { if (++spin_guard > 1000) { printf("!! BUSY LOOP at %lld\n", (long long)now_ms); longjmp(done, 3);} } else { spin_t = now_ms; spin_guard = 0; } }
    advance(to.t);
    return -1;
}
void k_sem_give(struct k_sem *s) { sem = 1; }
int k_mutex_init(struct k_mutex *m) { return 0; }
int k_mutex_lock(struct k_mutex *m, k_timeout_t t) { return 0; }
int k_mutex_unlock(struct k_mutex *m) { return 0; }
int64_t k_uptime_get(void) { return now_ms; }
static k_work_handler_t save_handler; static int64_t save_due = -1; static int n_saves;
void k_work_init_delayable(struct k_work_delayable *w, k_work_handler_t h) { save_handler = h; }
int k_work_schedule(struct k_work_delayable *w, k_timeout_t d) { if (save_due < 0) save_due = now_ms + d.t; return 0; }
int k_work_reschedule(struct k_work_delayable *w, k_timeout_t d) { save_due = now_ms + d.t; return 0; }
bool atomic_test_bit(const atomic_t *t, int b) { return (t[0] >> b) & 1; }
bool atomic_test_and_clear_bit(atomic_t *t, int b) { bool r = (t[0] >> b) & 1; t[0] &= ~(1L << b); return r; }
void atomic_clear_bit(atomic_t *t, int b) { t[0] &= ~(1L << b); }
void atomic_set_bit(atomic_t *t, int b) { t[0] |= (1L << b); }
void atomic_set_bit_to(atomic_t *t, int b, bool v) { if (v) atomic_set_bit(t, b); else atomic_clear_bit(t, b); }
bool i2c_is_ready_dt(const struct i2c_dt_spec *s) { return true; }
int i2c_read_dt(const struct i2c_dt_spec *s, uint8_t *b, uint32_t n) {
    n_reads++; last_read_ms = now_ms;
    if (!bus_active) { printf("!! read while bus suspended\n"); }
    world_step();
    if (!pod.present) return -5;
    pod.seq++;
    uint32_t p = ((uint32_t)pod.t << 20) | ((uint32_t)pod.x << 10) | pod.y;
    b[0] = SP_MAGIC; b[1] = (pod.version << 6) | (pod.pressed ? 1 : 0); b[2] = pod.boot_id;
    b[3] = (pod.pc << 4) | pod.rc; b[4] = pod.seq; b[5] = p >> 24; b[6] = p >> 16; b[7] = p >> 8; b[8] = p;
    uint16_t c = sp_crc16(b, 9); b[9] = c >> 8; b[10] = c & 0xff;
    return 0;
}
int pm_device_action_run(const struct device *d, enum pm_device_action a) {
    int want = (a == PM_DEVICE_ACTION_RESUME);
    if (bus_active == want) return -EALREADY;
    bus_active = want; return 0;
}
int input_report_key(const struct device *d, uint16_t code, int32_t v, bool sync, k_timeout_t to) {
    if (fail_input > 0) { fail_input--; return -11; }
    if (nev < MAXEV) evs[nev++] = (struct ev){now_ms, 1, code, v};
    if (verbose) printf("    [%8lld] BTN %s\n", (long long)now_ms, v ? "press" : "release");
    return 0;
}
int input_report_rel(const struct device *d, uint16_t code, int32_t v, bool sync, k_timeout_t to) {
    if (v == 0) zero_events++;
    if (nev < MAXEV) evs[nev++] = (struct ev){now_ms, 0, code, v};
    if (code == 0) rel_x += v; else rel_y += v;
    return 0;
}
static struct { uint16_t x, y; } stored; static int have_stored;
int settings_save_one(const char *name, const void *v, size_t n) { memcpy(&stored, v, n); have_stored = 1; n_saves++; return 0; }
int settings_name_steq(const char *name, const char *key, const char **next) { if (next) *next = NULL; return strcmp(name, key) == 0; }
static struct zmk_activity_state_changed *act_ev; static struct zmk_split_peripheral_status_changed *link_ev;
struct zmk_activity_state_changed *as_zmk_activity_state_changed(const zmk_event_t *eh) { return act_ev; }
struct zmk_split_peripheral_status_changed *as_zmk_split_peripheral_status_changed(const zmk_event_t *eh) { return link_ev; }

/* symbols exported by the stubbed macros in stick_pod.c */
extern int (*stub_init_0)(const struct device *);
extern int (*stub_pmcb_0)(const struct device *, enum pm_device_action);
extern int (*stub_set_hhkb_stick_pod)(const char *, size_t, settings_read_cb, void *);
extern int (*stub_commit_hhkb_stick_pod)(void);
extern zmk_listener_callback_t zmk_listener_hhkb_stick_pod;
int hhkb_stick_pod_recalibrate(void);

static ssize_t rd(void *arg, void *data, size_t len) { memcpy(data, &stored, len); return len; }
static void link(bool up) { struct zmk_split_peripheral_status_changed e = {up}; link_ev = &e; zmk_listener_hhkb_stick_pod(NULL); link_ev = NULL; }
static void activity(enum zmk_activity_state st) { struct zmk_activity_state_changed e = {st}; act_ev = &e; zmk_listener_hhkb_stick_pod(NULL); act_ev = NULL; }

/* run the thread until virtual time `until`; work items fire in between */
static int run_until(int64_t until) {
    end_ms = until;
    int r = setjmp(done);
    if (r == 0) { t_entry(t_p1, NULL, NULL); }
    return r;
}
/* helper: step in slices so that the delayed save work can fire */
static int run_for(int64_t ms) {
    int64_t stop = now_ms + ms; int r = 1;
    while (now_ms < stop) {
        int64_t slice = stop;
        if (save_due >= 0 && save_due > now_ms && save_due < slice) slice = save_due;
        r = run_until(slice);
        if (save_due >= 0 && now_ms >= save_due) { save_due = -1; save_handler(NULL); }
        if (r != 1) break;
    }
    return r;
}
static int count_btn(int from, int val) { int n = 0; for (int i = from; i < nev; i++) if (evs[i].kind == 1 && evs[i].val == val) n++; return n; }
static int count_rel(int from) { int n = 0; for (int i = from; i < nev; i++) if (evs[i].kind == 0) n++; return n; }
static int64_t min_btn_gap(int from) { int64_t last = -1, m = 1 << 30; for (int i = from; i < nev; i++) if (evs[i].kind == 1) { if (last >= 0 && evs[i].t - last < m) m = evs[i].t - last; last = evs[i].t; } return m; }
static int last_btn(void) { for (int i = nev - 1; i >= 0; i--) if (evs[i].kind == 1) return evs[i].val; return 0; }
#define SAY(...) do { printf(__VA_ARGS__); printf("\n"); } while (0)

/* ---- scenarios (world scripts) ---- */
static int64_t T0;
static void w_click_at_rest(int64_t n) { int64_t d = n - T0; pod.pressed = (d >= 1000 && d < 1040) || (d >= 1100 && d < 1140); }
static void w_tilt(int64_t n) { int64_t d = n - T0; pod.x = (d >= 1000 && d < 3000) ? 800 : 500; }
static void w_hold(int64_t n) { int64_t d = n - T0; pod.pressed = (d >= 1000 && d < 1000 + 12 * 60000); }
static void w_unplug_pressed(int64_t n) { int64_t d = n - T0; pod.pressed = d >= 1000; pod.present = d < 3000; }
static void w_burst_then_unplug(int64_t n) { int64_t d = n - T0; /* 6 fast clicks inside one rest period, then gone */
    pod.pressed = (d >= 1000 && d < 1240) && (((d - 1000) / 20) % 2 == 0); pod.present = d < 1300; }
static void w_tilt_forever(int64_t n) { int64_t d = n - T0; pod.x = d >= 1000 ? 545 : 500; }      /* 0.045 off: just outside dead zone, inside +-0.1 */
static void w_tilt_far_forever(int64_t n) { int64_t d = n - T0; pod.x = d >= 1000 ? 800 : 500; }
static void w_tilt_far_noise(int64_t n) { int64_t d = n - T0; pod.x = d >= 1000 ? 800 + (((n / 7000) % 2) ? 5 : 0) : 500; }
static void w_tiltstuck_then_press(int64_t n) { int64_t d = n - T0; pod.x = d >= 1000 ? 800 : 500; pod.pressed = d >= 8 * 60000; }
static void w_tiltstuck_then_clicks(int64_t n) { int64_t d = n - T0; pod.x = d >= 1000 ? 800 : 500; int64_t e = d - 8 * 60000; pod.pressed = e >= 0 && e < 20000 && ((e / 300) % 10 == 0); }

/* 7 clicks, 15 ms on / 15 ms off, starting 5 ms after a rest poll; pod vanishes 10 ms after the next poll */
static void w_aligned_burst_unplug(int64_t n) { int64_t d = n - T0; pod.pressed = (d >= 5 && d < 215) && (((d - 5) / 15) % 2 == 0); pod.present = d < 262; }
static void w_aligned_burst(int64_t n) { int64_t d = n - T0; pod.pressed = (d >= 5 && d < 215) && (((d - 5) / 15) % 2 == 0); }
/* S23: 倒れたまま固着 → 8 分に 3 秒押す（固着中は 2 秒ごとにしか読まないので、短いクリックは落ちる。移動は止まったまま）→ 9 分に傾きを変える（移動が戻る）→ 9 分半に離す */
static void w_tiltstuck_click_then_move(int64_t n) { int64_t d = n - T0; pod.x = d < 1000 ? 500 : d < 9 * 60000 ? 800 : d < 9 * 60000 + 30000 ? 700 : 500; int64_t e = d - 8 * 60000; pod.pressed = e >= 0 && e < 3000; }
static void w_aligned_click(int64_t n) { int64_t d = n - T0; pod.pressed = (d >= 5 && d < 60); }
static void dump_btn(int e0) { for (int i = e0; i < nev; i++) if (evs[i].kind == 1) SAY("     t=+%lld %s", (long long)(evs[i].t - T0), evs[i].val ? "press" : "release"); }
static void boot(bool with_saved) {
    stub_init_0(&stub_dev);
    if (with_saved) { stored.x = stored.y = 32768; have_stored = 1; stub_set_hhkb_stick_pod("centre", 4, rd, NULL); }
    stub_commit_hhkb_stick_pod();
    link(true);
}

int main(int argc, char **argv) {
    verbose = argc > 2;
    int sc = argc > 1 ? atoi(argv[1]) : 0;
    int e0, r;
    switch (sc) {
    case 1: /* first boot, no saved centre: adoption, no motion, no events at rest */
        boot(false); r = run_for(10000);
        SAY("S1 first boot: saves=%d stored=%u,%u events=%d reads=%d (10 s; expect ~40 at 4 Hz + adoption)", n_saves, stored.x, stored.y, nev, n_reads);
        e0 = nev; n_reads = 0; r = run_for(600000);
        SAY("S1 idle 10 min: input events=%d zero-events=%d reads=%d (expect 0 / 0 / ~2400)", nev - e0, zero_events, n_reads);
        break;
    case 2: /* tilt 2 s at 0.3 full scale => ~1200 c/s * 2 s */
        boot(true); run_for(3000); T0 = now_ms; world = w_tilt; e0 = nev; n_reads = 0; run_for(6000);
        SAY("S2 tilt 2 s full: rel_x=%lld rel_y=%lld rel events=%d reads=%d (expect ~2400 counts, minus up-to-250 ms entry latency)", (long long)rel_x, (long long)rel_y, count_rel(e0), n_reads);
        break;
    case 3: /* two 40 ms clicks inside one rest period */
        boot(true); run_for(3000); T0 = now_ms; world = w_click_at_rest; e0 = nev; run_for(5000);
        SAY("S3 double click at rest: presses=%d releases=%d min gap=%lld ms (expect 2/2, >=16)", count_btn(e0, 1), count_btn(e0, 0), (long long)min_btn_gap(e0));
        break;
    case 4: /* hold 12 min */
        boot(true); run_for(3000); T0 = now_ms; world = w_hold; e0 = nev; n_reads = 0; run_for(11 * 60000);
        SAY("S4 hold 11 min: presses=%d releases=%d last=%d reads=%d (expect 1/1/0; 5 min*83Hz=25000 + 6min/2s=180)", count_btn(e0, 1), count_btn(e0, 0), last_btn(), n_reads);
        e0 = nev; run_for(3 * 60000);
        SAY("S4 after real release: new presses=%d releases=%d", count_btn(e0, 1), count_btn(e0, 0));
        T0 = now_ms; world = w_click_at_rest; e0 = nev; run_for(5000);
        SAY("S4 clicks work again: presses=%d releases=%d", count_btn(e0, 1), count_btn(e0, 0));
        break;
    case 5: /* unplug while pressed */
        boot(true); run_for(3000); T0 = now_ms; world = w_unplug_pressed; e0 = nev; run_for(10000);
        SAY("S5 unplug while pressed: presses=%d releases=%d last=%d (expect 1/1/0)", count_btn(e0, 1), count_btn(e0, 0), last_btn());
        for (int i = e0; i < nev; i++) if (evs[i].kind == 1) SAY("     t=+%lld %s", (long long)(evs[i].t - T0), evs[i].val ? "press" : "release");
        break;
    case 6: /* burst of clicks queued, then pod vanishes: are queued edges dropped? */
        boot(true); run_for(3000); T0 = now_ms; world = w_burst_then_unplug; e0 = nev; run_for(10000);
        SAY("S6 burst then unplug: presses=%d releases=%d last=%d", count_btn(e0, 1), count_btn(e0, 0), last_btn());
        for (int i = e0; i < nev; i++) if (evs[i].kind == 1) SAY("     t=+%lld %s", (long long)(evs[i].t - T0), evs[i].val ? "press" : "release");
        SAY("     (pod absent from +1300; host declares absent ~+1900..2050. Edges after that = queue not dropped)");
        break;
    case 7: /* stuck tilt inside +-0.1 : recentre */
        boot(true); run_for(3000); T0 = now_ms; world = w_tilt_forever; e0 = nev; n_reads = 0; run_for(5 * 60000 + 5000);
        { int64_t a = rel_x; int ea = nev; int ra = n_reads; run_for(20 * 60000);
          SAY("S7 small stuck tilt: counts in first 5 min=%lld, in next 20 min=%lld (events %d), reads %d then %d, saves=%d stored=%u", (long long)a, (long long)(rel_x - a), nev - ea, ra, n_reads - ra, n_saves, stored.x); }
        break;
    case 8: /* stuck tilt far outside +-0.1 */
        boot(true); run_for(3000); T0 = now_ms; world = w_tilt_far_forever; n_reads = 0; run_for(5 * 60000 + 5000);
        { int64_t a = rel_x; int ea = nev; int ra = n_reads; run_for(30 * 60000);
          SAY("S8 far stuck tilt (no noise): counts first 5 min=%lld, next 30 min=%lld (events %d), reads %d then %d", (long long)a, (long long)(rel_x - a), nev - ea, ra, n_reads - ra); }
        break;
    case 9: /* same with 5 LSB wobble every 7 s */
        boot(true); run_for(3000); T0 = now_ms; world = w_tilt_far_noise; n_reads = 0; run_for(5 * 60000 + 5000);
        { int64_t a = rel_x; int ea = nev; int ra = n_reads; run_for(30 * 60000);
          SAY("S9 far stuck tilt + 5 LSB wobble/7 s: counts first 5 min=%lld, next 30 min=%lld (events %d), reads %d then %d", (long long)a, (long long)(rel_x - a), nev - ea, ra, n_reads - ra); }
        break;
    case 10: /* tilt-stuck, then button pressed and held forever */
        boot(true); run_for(3000); T0 = now_ms; world = w_tiltstuck_then_press; e0 = nev; run_for(40 * 60000);
        SAY("S10 tilt-stuck then button held 32 min: presses=%d releases=%d last=%d (1/1/0 would mean the hold is cut)", count_btn(e0, 1), count_btn(e0, 0), last_btn());
        break;
    case 11: /* tilt-stuck, then 7 clicks of 300 ms every 3 s */
        boot(true); run_for(3000); T0 = now_ms; world = w_tiltstuck_then_clicks; e0 = nev; run_for(10 * 60000);
        SAY("S11 tilt-stuck then 7 clicks (300 ms each): presses=%d releases=%d", count_btn(e0, 1), count_btn(e0, 0));
        break;
    case 12: /* SLEEP while a release is still queued */
        boot(true); run_for(3000); T0 = now_ms; world = w_click_at_rest; e0 = nev;
        run_until(T0 + 1260); /* first poll after both clicks at ~+1250: press out, 3 edges queued */
        SAY("S12 before SLEEP: presses=%d releases=%d", count_btn(e0, 1), count_btn(e0, 0));
        activity(ZMK_ACTIVITY_SLEEP); stub_pmcb_0(&stub_dev, PM_DEVICE_ACTION_SUSPEND);
        r = run_for(5000);
        SAY("S12 after SLEEP stop: presses=%d releases=%d last=%d bus_active=%d thread=%s", count_btn(e0, 1), count_btn(e0, 0), last_btn(), bus_active, r == 2 ? "blocked" : "running");
        break;
    case 13: /* press report fails once */
        boot(true); run_for(3000); T0 = now_ms; world = w_click_at_rest; e0 = nev; fail_input = 0;
        run_until(T0 + 1245); fail_input = 1; run_for(5000);
        SAY("S13 one input_report failure: presses=%d releases=%d (unbalanced => unmatched release reaches HID)", count_btn(e0, 1), count_btn(e0, 0));
        break;
    case 14: /* recalibrate */
        boot(true); run_for(3000); pod.x = 560; pod.y = 470; e0 = nev; hhkb_stick_pod_recalibrate(); run_for(3000);
        SAY("S14 recal at x=560,y=470: saves=%d stored=%u,%u (expect 36700,30802) events=%d", n_saves, stored.x, stored.y, nev - e0);
        break;
    case 16: /* queued edges, then pod vanishes */
        boot(true); run_for(3000); T0 = now_ms; world = w_aligned_burst_unplug; e0 = nev; run_for(6000);
        SAY("S16 7 clicks queued in one rest period, pod vanishes at +262: presses=%d releases=%d last=%d", count_btn(e0, 1), count_btn(e0, 0), last_btn());
        dump_btn(e0);
        break;
    case 17: /* queued edges, then SLEEP/PM suspend */
        boot(true); run_for(3000); T0 = now_ms; world = w_aligned_burst; e0 = nev; run_until(T0 + 290);
        SAY("S17 at SLEEP (+290): presses=%d releases=%d last=%d", count_btn(e0, 1), count_btn(e0, 0), last_btn());
        activity(ZMK_ACTIVITY_SLEEP); stub_pmcb_0(&stub_dev, PM_DEVICE_ACTION_SUSPEND);
        SAY("S17 right after stop: presses=%d releases=%d last=%d bus_active=%d", count_btn(e0, 1), count_btn(e0, 0), last_btn(), bus_active);
        r = run_for(3000);
        SAY("S17 3 s later: thread=%s presses=%d releases=%d last=%d", r == 2 ? "blocked" : "running", count_btn(e0, 1), count_btn(e0, 0), last_btn());
        stub_pmcb_0(&stub_dev, PM_DEVICE_ACTION_RESUME); activity(ZMK_ACTIVITY_ACTIVE); world = NULL; pod.pressed = false; r = run_for(3000);
        SAY("S17 after failed-sleep resume: presses=%d releases=%d last=%d", count_btn(e0, 1), count_btn(e0, 0), last_btn());
        dump_btn(e0);
        break;
    case 18: /* the press report itself is dropped */
        boot(true); run_for(3000); T0 = now_ms; world = w_aligned_click; e0 = nev; fail_input = 1; run_for(3000);
        SAY("S18 press report dropped once: presses=%d releases=%d (1 release without press => unmatched release into HID refcount)", count_btn(e0, 1), count_btn(e0, 0));
        break;
    case 19: /* link drops while pressed, comes back */
        boot(true); run_for(3000); T0 = now_ms; pod.pressed = true; e0 = nev; run_for(1000);
        link(false); run_for(5000);
        SAY("S19 link down while pressed: presses=%d releases=%d", count_btn(e0, 1), count_btn(e0, 0));
        { int e1 = nev; int64_t t1 = now_ms; link(true); run_for(5000);
          SAY("S19 link up, still pressed: presses=%d releases=%d", count_btn(e1, 1), count_btn(e1, 0));
          for (int i = e1; i < nev; i++) if (evs[i].kind == 1) SAY("     %lld ms after link-up: %s", (long long)(evs[i].t - t1), evs[i].val ? "press" : "release"); }
        break;
    case 20: /* rest at the dead-zone edge with 2 LSB dither */
        boot(true); run_for(3000); T0 = now_ms; pod.x = 541; n_reads = 0; e0 = nev; run_for(30 * 60000);
        SAY("S20 parked 0.041 off-centre (1 LSB outside dead zone), 30 min: counts=%lld events=%d reads=%d", (long long)rel_x, nev - e0, n_reads);
        break;
    case 21: /* tilt-stuck far outside, then one click: does the cursor start drifting again? */
        boot(true); run_for(3000); T0 = now_ms; world = w_tiltstuck_then_clicks; run_for(7 * 60000);
        { int64_t a = rel_x; int nr = n_reads; run_for(10 * 60000);
          SAY("S21 tilt-stuck, then clicks at +8 min: counts emitted in the 10 min after = %lld, reads=%d", (long long)(rel_x - a), n_reads - nr); }
        break;
    case 23: /* tilt-stuck, one 3 s press (still muted), then the stick really moves: motion must come back */
        boot(true); run_for(3000); T0 = now_ms; world = w_tiltstuck_click_then_move; run_for(7 * 60000);
        { int64_t a = rel_x; int e1 = nev; run_until(T0 + 9 * 60000 - 100); int64_t b = rel_x; int pr = count_btn(e1, 1); run_until(T0 + 9 * 60000 + 30000); int64_t c = rel_x; run_for(60000);
          SAY("S23 tilt-stuck, 3 s press at +8 min, real move at +9 min: counts while still stuck=%lld (expect 0) click presses=%d (expect 1) counts after the move=%lld (expect >0) counts after release=%lld (expect 0)", (long long)(b - a), pr, (long long)(c - b), (long long)(rel_x - c)); }
        break;
    case 22: /* the release report is dropped once */
        boot(true); run_for(3000); T0 = now_ms; world = w_aligned_click; e0 = nev; run_until(T0 + 255); fail_input = 1; run_for(3000);
        SAY("S22 release report dropped once: presses=%d releases=%d last=%d", count_btn(e0, 1), count_btn(e0, 0), last_btn());
        break;
    case 15: /* version mismatch */
        pod.version = 2; boot(true); run_for(3000); T0 = now_ms; world = w_click_at_rest; e0 = nev; run_for(5000);
        SAY("S15 frame version 2: presses=%d (spec v7: must be discarded => 0)", count_btn(e0, 1));
        break;
    }
    return 0;
}
