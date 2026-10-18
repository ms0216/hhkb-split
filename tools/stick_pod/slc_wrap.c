/* tools/test_status_led.py から ctypes で呼ぶための薄い皮。
 * （tools/stick_pod/ は既存の eg_core_wrap.c と同じ置き場所） */
#include "../../firmware/src/status_led_core.h"

int slc_state_of(int activity, int booting, int pct,
                 int has_split, int split, int has_host, int host) {
    struct slc_in in = {
        .activity = (enum slc_activity)activity,
        .booting = booting != 0,
        .battery_pct = (uint8_t)pct,
        .has_split_link = has_split != 0,
        .split = (enum slc_link)split,
        .has_host_link = has_host != 0,
        .host = (enum slc_link)host,
    };
    return (int)slc_state(&in);
}

/* announce は入出力。戻り値は state、*out_announce に残った合図を返す */
int slc_announce_of(int st, int announce, int *out_announce) {
    enum slc_color a = (enum slc_color)announce;
    int r = (int)slc_announce((enum slc_state)st, &a);
    *out_announce = (int)a;
    return r;
}

/* --- 表示側（slc_tick） --- */
int slc_tick_of(struct slc_render *r, int st,
                int activity, int booting, int pct,
                int has_split, int split, int has_host, int host,
                unsigned *out_next_ms) {
    struct slc_in in = {
        .activity = (enum slc_activity)activity,
        .booting = booting != 0,
        .battery_pct = (uint8_t)pct,
        .has_split_link = has_split != 0,
        .split = (enum slc_link)split,
        .has_host_link = has_host != 0,
        .host = (enum slc_link)host,
    };
    struct slc_out o = slc_tick(r, (enum slc_state)st, &in);
    *out_next_ms = o.next_ms;
    return (int)o.color;
}
