# ファーム全機能の監査（2026-10-15）

**121 エージェント・39 分。指摘 38 件 → 確定 21 件 / 反証で落ちた 17 件。**

各指摘を `correctness` / `evidence` / `impact` の 3 観点で反証にかけ、
**2 票以上の反証で落とした**。下の「確定」は生き残ったものだけ。

> ⚠️ **反証が 17 件（45%）を落とした。**単独の監査ならそれも報告していた。

---

## 着手の状況

| | 深刻度 | 状態 |
|---|---|---|
| `test_the_warning_survives_idle` が検出力を失っていた | medium | **✅ 直した。**判断が在る場所（core）を見る形へ。退行を入れると落ちることを確認 |
| soft off で LED が消えない | high | **✅ 直した**（80f5c45）。変異 3 つで検出を確認・**実機で挙動不変を確認** |
| ZMK は idle で電池測定を止めるのに、こちらのタイマーは回り続ける | high | **⚠️ 裏取り済み・未修正**（087ea58 で記録）。下記 |
| 残り | — | 18 件 未着手 |

### ⚠️ idle の件は「記録だけ」で止めてある

ZMK の `app/src/battery.c:171-173` が `ZMK_ACTIVITY_IDLE`（既定 30 秒）で
`k_timer_stop(&battery_timer)` を呼ぶことを**ソースで確認した**。
こちらのタイマーは止まらないので、**止まったあとの古いキャッシュを読む。**

**これは 2026-10-15 の「#25b は実機で効いている」という報告を訂正する。**
あの確認は 3 分 48 秒で、**idle に入る前だった。**
示せたのは「USB 給電で誤発火しない」ことだけで、
**本来の仕事（電池が尽きたら止める）は未確認のまま。**

直し方は 2 つあり、**どちらも消費電流とのトレードオフ**なので利用者の判断待ち:
- activity の事象を受けて自分のタイマーも止める／起こす
- 自分で `sensor_sample_fetch()` を呼ぶ（ADC を余分に回す）

### soft off の LED は、直し方を一度間違えた

最初 `DEVICE_DEFINE` + `PM_DEVICE_DEFINE` にしたが、**ポッド無しの版で
ビルドが落ちた**（`PM_DEVICE` を select しているのは `HHKB_STICK_POD` だけ）。
直接呼び出しに変えて解決。**呼び出し元は `low_battery_off.c` の 1 箇所だけ**なので、
将来 soft off をキーに割り当てるなら**そこでも消すこと。**

**次にやる順（私の見立て）:**

1. **idle とタイマーの件**（high・bug 2 件）。`#25b` の前提に関わる。
   「ZMK は 30 秒の idle で電池測定を止めるのに、打ち止めタイマーは回り続けて
   固まったキャッシュを読む」——**今日の実機確認は 3 分 48 秒で、idle に入る前だった**
2. **`blink_work_cb` の切り出しと検査**（high・test-gap ＋ medium・refactor）。
   2026-10-15 の切り出しは判定部分だけで、表示側は未検査のまま
3. **検査ゼロのファイル**（`boot_layer` / `behavior_stick_recal` / `encoder_gated.c`）
4. 記録の食い違い 4 件（直すだけ）

---

## 確定した指摘


### high

#### [bug] `status_led.c:525` — soft off では LED が消えない（点いたまま System OFF に入り、空の電池を 1〜2mA で舐め続ける）

**検証**: 2/3 が本物と判定

消灯処理は status_led_listener の `activity == ZMK_ACTIVITY_SLEEP` 分岐（525-527 行）にしか無い。しかし ZMK 本体を読むと `ZMK_ACTIVITY_SLEEP` を raise するのは app/src/activity.c の activity_work_handler ただ 1 箇所で（/tmp/zmkq/app/src/activity.c:80、grep で他に raise 元が無いことを確認）、`zmk_pm_soft_off()`（/tmp/zmkq/app/src/pm.c:89-134）はこの事象を一切上げずに `sys_poweroff()` を呼ぶ。nRF52840 の GPIO ラッチは System OFF を越えて保持されるので、点灯フェーズの最中に soft off が走ると LED は点いたまま固定される。ZMK 自身の indicator_leds.c は同じ問題を `PM_DEVICE_ACTION_SUSPEND` ハンドラ（/tmp/zmkq/app/src/indicators/indicator_leds.c:161-177、`pm_suspended` で強制消灯）で塞いでいる。status_led.c にはその口が無い。このリポジトリ内にも先例があり、firmware/drivers/encoder_gated.c:190-199 は既に PM_DEVICE_ACTION_SUSPEND を実装している（PM_DEVICE は左右とも y・firmware/Kconfig:97）。実害の大きさ: provisional-values.md:27 が LED 点灯を 1〜2mA、待機を 20µA としており 50〜100 倍。しかも soft off を呼ぶ唯一の経路は low_battery_off.c:104（打ち止め電圧で止まる機能）で、キーマップに soft-off のバインドは無い。つまり「電池が尽きたので消費を止める」という機能そのものが、点きっぱなしの LED で台無しになる。

**壊れ方**: 電池が打ち止めに達して low_battery_off.c が zmk_pm_soft_off() を呼ぶ。このとき表示は STATE_BATT_REPLACE（橙 2 回点滅 / 15 秒）で、橙が点いている 120ms×2 の窓に soft off が入ると、橙が点いたまま System OFF に入る。以後、電源スイッチを切るか電池を抜くまで 1〜2mA が流れ続け（待機 20µA の 50〜100 倍）、既に空の電池を過放電させる。低電圧での flash 書き込みでペアリング情報が壊れうる（low_battery_off.c:10-11 が自分で挙げているリスク）状態に、むしろ近づける。利用者から見ると「電池が切れたのに橙が点きっぱなし」という故障に見える。

**直し方**: status_led.c に PM_DEVICE のフックを足し、SUSPEND で `k_work_cancel_delayable(&blink_work); set_color(COLOR_OFF);` を、RESUME で再スケジュールする。encoder_gated.c:190-199 と同じ形。ただし SYS_INIT では PM デバイスを持てないので、`DEVICE_DEFINE` / `PM_DEVICE_DEFINE` に移すか、簡易には low_battery_off.c が `zmk_pm_soft_off()` を呼ぶ直前に消灯 API（status_led.c が公開する `hhkb_status_led_off()`）を叩く。後者なら変更は小さいが、将来 soft-off をキーに割り当てたときに同じ穴が開くので、PM フックのほうが確実。どちらにしても、消したことを確かめる検査（soft off 経路が消灯を通るか）を併せて足すこと。

#### [bug] `low_battery_off.c:117` — ZMK は idle（既定 30 秒無操作）で電池タイマーを止めるのに、こちらのタイマーは回り続け、固まったキャッシュを読んで数える

**検証**: 3/3 が本物と判定

このファイルは「ZMK が同じ周期で fetch 済みなので、driver のキャッシュを読むだけでよい」（79〜80 行目のコメント）という前提で書かれている。だが外部事実として ZMK 本体 app/src/battery.c:164-184 の battery_event_listener は、ZMK_ACTIVITY_IDLE と ZMK_ACTIVITY_SLEEP で k_timer_stop(&battery_timer) を呼ぶ。idle の入り口は app/src/activity.c:91-93 の MAX_IDLE_MS = CONFIG_ZMK_IDLE_TIMEOUT で、既定は app/Kconfig:403-404 の 30000 ms。config/boards/shields/hhkb_split/*.conf はこれを上書きしていない（ZMK_IDLE_SLEEP_TIMEOUT=1800000 は書いてあるが ZMK_IDLE_TIMEOUT は無い）。一方 low_battery_off.c の k_timer は activity を一切購読しておらず、60 秒ごとに回り続ける。firmware/ 全体を grep しても、battery に対して sensor_sample_fetch を呼ぶコードは battery_alkaline.c 自身の実装以外に存在しない（唯一の fetch 元は停止した ZMK のタイマー）。つまり 30 秒無操作に入った瞬間から、alk_channel_get（battery_alkaline.c:122-140）が返す data->millivolts は更新が止まり、こちらは同じ古い値を何度も読んで consecutive を積む。

**壊れ方**: キーボードを 30 秒放置すると ZMK は idle に入り、電池の測定が止まる。その直前の測定が BLE 送信中の瞬時降下などでたまたま 2400mV 以下だった場合、キャッシュは 2400mV 以下のまま凍結する。こちらのタイマーは 60 秒ごとに同じ凍結値を読み続けるので、SAMPLES=2 なら放置から約 2 分で、電池が実際には十分残っていても soft off する（起こすには電源スイッチの入れ直しが要る）。逆向きの失敗も同じ原因で起きる: 本当に電池が尽きかけていても、最後の測定が打ち止めより上で idle に入れば、キャッシュは上のまま凍り、こちらは永久に 0 回のまま数えない。これは 2026-09-03 に「% が変わったときしか事象が出ない」を直したときに持ち込まれた、同じ型（ZMK 側の発火条件を外部確認せずに相乗りした）の再発。

**直し方**: キャッシュに相乗りするのをやめ、判定の直前に自分で sensor_sample_fetch_chan(battery, SENSOR_CHAN_GAUGE_VOLTAGE) を呼んでから channel_get する（60 秒に 1 回の ADC 1 発なので電池への影響はコメントが心配するほど大きくない。oversampling=4 の 1 変換ぶん）。それが嫌なら zmk_activity_state_changed を購読して、ZMK のタイマーと同じく idle/sleep で自分のタイマーも止め、ACTIVE 復帰で consecutive = 0 にして測り直しを待つ。どちらにせよ「ZMK が測っている」という前提をコード側で保証すること。あわせて 14-15 行目と 79-80 行目のコメント、docs/hardware/open-gaps.md の #25b の記述を実態に合わせる。

#### [bug] `battery_alkaline.c:106` — ZMK は 30 秒の idle で測定を止めるのに、打ち止め判定は止まった古いキャッシュを読み続ける

**検証**: 3/3 が本物と判定

battery_alkaline.c:106-120 のコメントは「読み手は ZMK が測った直後に呼ばれるので、キャッシュは常に新しい」と前提を置いている。しかし外部事実（/tmp/zmkq/app/src/battery.c:164-180 の battery_event_listener）では、ZMK は ZMK_ACTIVITY_IDLE と ZMK_ACTIVITY_SLEEP で k_timer_stop(&battery_timer) し、測定そのものを止める。CONFIG_ZMK_IDLE_TIMEOUT は上流既定 30000ms（/tmp/zmkq/app/Kconfig:403-405）で、hhkb_split_left.conf / hhkb_split_right.conf のどちらも上書きしていない（両 conf にあるのは ZMK_IDLE_SLEEP_TIMEOUT=1800000 だけ）。一方 firmware/src/low_battery_off.c:107-120 の K_TIMER は SYS_INIT で起動したきり誰も止めず、activity も購読していない。つまり 30 秒打鍵が無いと driver の data->millivolts は凍結し、low_battery_check() は 60 秒ごとに同じ凍結値を読み続ける。alk_sample_fetch() が呼ばれなくなるので、コメントが言う「測った直後」は成立しない。

**壊れ方**: (A) 止まらない側: 電池が打ち止め付近まで落ちたが、最後に測れたのが 2500mV（> EMPTY_MV 2400）だったとする。利用者が放置する（30 秒で idle）→ ZMK の測定停止 → 以後 low_battery_check は永久に 2500mV を読み、consecutive は 0 のまま。実電圧が 2.0V まで落ちてブラウンアウトループに入っても soft off に入らない。これは #25b が防ごうとしたもの（低電圧 flash 書き込みでペアリング情報が壊れる）そのもの。(B) 誤って止まる側: 最後の測定が BLE 送信中の瞬間的な降下で 2380mV（< 2400）だった直後に idle へ入ると、60 秒後と 120 秒後に同じ 2380mV を読んで consecutive が SAMPLES=2 に達し、電池がまだ十分あるのに soft off する。1 回で止めない仕組み（firmware/Kconfig:70-79「BLE 送信中の一時的な降下で落ちるのを防ぐ」）が、同じ 1 サンプルを 2 回数えているので完全に無効化されている。なお両者は同じ lowprio work queue（/tmp/zmkq/app/src/workqueue.c:14）で直列化されるので、値が裂ける競合ではなく「古い値」の問題。

**直し方**: driver 側に「キャッシュがいつのものか」を持たせる（fetch 成功時に k_uptime_get() を記録し、channel_get か専用 API でその時刻も返す）。読み手側（low_battery_off.c）は、キャッシュが ZMK_BATTERY_REPORT_INTERVAL の 2 倍より古ければ判定を飛ばす（consecutive は増やさず保持）。あるいは low_battery_off.c 側で zmk_activity_state_changed を購読し、ACTIVE 以外では自分のタイマーも止める（ZMK の battery.c と同じ条件にそろえる）。どちらにせよ battery_alkaline.c:106-120 のコメントは 2026-09-03 の変更（dc37e79: 事象待ち→周期タイマー）を反映していないので、同時に書き直す。

#### [bug] `encoder_gated_core.h:17` — pulses が int8_t なので、読み出しが遅れると 127 刻みで折り返して逆向きになる

**検証**: 2/3 が本物と判定

encoder_gated_core.h:17 で `int8_t pulses`。encoder_gated.c:134 は `int32_t pulses = data->core.pulses;` と int32 で受けるが、足し算は core 側（encoder_gated_core.h:39 `c->pulses += (int8_t)step`）で int8 のまま行われるので、受け側を広げても救えない。ドライバは ISR で数えるだけで、0 に戻るのは eg_channel_get（encoder_gated.c:133-136）が呼ばれたときだけ。その eg_channel_get までの経路は ISR → k_work_submit(data->work) → eg_work → ZMK の zmk_sensors_trigger_handler → atomic_set_bit + k_work_submit(sensor_data_work) → run_sensors_data_trigger → sensor_channel_get で、**システムワークキューを 2 回通る**（/private/tmp/zmkq/app/src/sensors.c:92-119）。設定の flash 書き込みや BLE の再接続でシステムワークキューが詰まっている間、ISR だけは走り続けて加算される。ZMK 標準の ec11 も int8_t だが（/private/tmp/zmkq/app/module/drivers/sensor/ec11/ec11.h:23）、あちらは割り込みごとに sample_fetch が走って毎回 channel_get で吐くので溜まる窓が桁違いに狭い。

**壊れ方**: 実際に走らせて確認した: eg_core_wrap.c を ctypes で叩き、ドレインせずに時計回り 200 クリック分の波形（4×200 の遷移）を流すと core.pulses が **+56** になる（-200 であるべき）。127 クリック = 24 クリック/回転のエンコーダで約 5.3 回転。システムワークキューが止まっている間にそれだけ回すと、音量ダウンのつもりが音量アップになる、という**向きの反転**が起きる。溢れの手前でも、-128..127 を超えた分は黙って消える。

**直し方**: `int8_t pulses` を `int16_t`（または `int32_t`）にする。encoder_gated_core.h:39 のキャストと tools/test_encoder_gated.py:22 の `C.c_int8`、tools/stick_pod/eg_core_wrap.c:5 の戻り値も合わせる。合わせて飽和（clamp）を入れて、溢れても符号が反転しないようにしておくとなお良い。

#### [test-gap] `status_led.c:383` — blink_work_cb の点滅パターン生成（383-476 行）は自動検査でまったく実行されていない。3 つの表示退行を故意に入れて 32 件全部が緑のままだった

**検証**: 3/3 が本物と判定

既存の検査を実際に読んだ結果: tools/test_status_led_core.py（13 件）は slc_state / slc_announce だけを ctypes で叩いており、色・点滅の速さ・パルス数・交互表示には一切触れない。tools/test_firmware.py の LED 系 6 件はすべて正規表現による原文 grep で、`set_color(announce_color)` という文字列があるか、`continue` が無いか、といった形しか見ていない。つまり switch 文が生む (色, next_ms, step) は一度も実行されていない。実際に 3 箇所を壊して `pytest tools/test_firmware.py tools/test_status_led_core.py` を回したところ 32 passed のままだった（CLAUDE.md の「通ったことは調べた証拠にならない」に従って故意破壊で確認済み）。

**壊れ方**: 次の 3 つを入れても検査は全部緑のまま通る。(1) 444 行の `(ls == LINK_UNBONDED) ? FAST_BLINK_MS : SLOW_BLINK_MS` を逆にする → 未ボンド（出荷直後）が 2 回/秒、ボンド済みが 4 回/秒になり、decisions/2026-08-16-led-state-table.md の「4 回＝未ボンド / 2 回＝ボンド済み」が丸ごと裏返る。利用者は出荷直後に「もうペアリング済み」と読み違える。(2) 453 行の `pulses` を常に 1 にする → 「電池を交換」が「電池残量が少ない」と同じ 1 回点滅になり、15 秒間隔か 30 秒間隔かでしか区別できなくなる（実機表 P3PC-6641-05 の 2 回点滅が消える）。(3) 431 行の `show_split` から交互の項を落とす → 両方未接続のとき緑しか出ず、ホスト未接続が永久に見えなくなる。これは decisions の L1〜L5「両方未接続なら交互に出す」という利用者自身の判断を破る退行で、しかも 2026-08-16 に一度潰した「片方だけ出すともう片方の異常が見えない」そのもの。

**直し方**: switch 文（383-476 行）を status_led_core.h に `slc_render(enum slc_state st, uint8_t *step, enum slc_link split, enum slc_link host, bool has_split, bool has_host, enum slc_color announce) -> {color, next_ms}` として切り出す（下の refactor 項と同一作業）。そのうえで tools/stick_pod/slc_wrap.c に皮を足し、tools/test_status_led_core.py に「決定表 L1〜L9・R1〜R3・C2・C3 を時系列で流して、色と next_ms の列が表どおりか」を突き合わせる検査を書く。期待値は decisions/2026-08-16-led-state-table.md から起こすこと（自分の生成物どうしの一致にしない）。足した検査は上の 3 つの変異で必ず落ちることを確かめてから入れる。

#### [test-gap] `test_firmware.py:352` — このファイルの判定ロジックは自動検査で一度も実行されていない。見ているのは USB の門の「書き方」だけ

**検証**: 3/3 が本物と判定

tools/ 全体を grep すると low_battery に触れる検査は tools/test_firmware.py だけで（他に 1 ファイルも無い）、その中身は 3 つ。(1) test_the_soft_off_is_enabled_on_both_halves（84 行目）は .conf に CONFIG_ZMK_PM_SOFT_OFF=y という文字列があるかだけ。(2) test_this_repository_is_registered_as_a_zmk_module（112 行目）はファイルが存在するかだけ。(3) test_low_battery_gate_also_covers_the_peripheral_half（352 行目）は正規表現で #if の条件文字列・中身・位置を見るだけ。_low_battery_gate（343 行目）がソースをテキストとして切り出していることからも、C のコードは一度もコンパイルも実行もされていない。結果として、EMPTY_MV との比較（89 行目の mv > EMPTY_MV が > か >= か）、mv の組み立て（88 行目の val1*1000 + val2/1000）、consecutive の増加・リセット・SAMPLES との比較（94-101 行目）、エラー経路（83-86 行目）のどれ 1 つとして、値を入れて結果を見る検査が存在しない。

**壊れ方**: 具体的に見逃すもの: 89 行目を mv > EMPTY_MV から mv >= EMPTY_MV に変えても（ちょうど 2400mV のときに止まらなくなる、あるいは止まるようになる、という打ち止めの境界がずれる変更）、既存の検査は全部緑のまま通る。94 行目の consecutive++ を消して常に 1 のままにしても、99 行目の < を <= に変えて必要回数を 1 つずらしても、88 行目の val2/1000 を val2*1000 にして mv を桁違いにしても、91 行目の consecutive = 0 を消して「一度でも下回ったら二度と 0 に戻らない」ようにしても、すべて通る。最後のものは「一瞬の降下を覚えていて、後で別の一瞬の降下と合わせて誤 soft off する」という実害のある壊れ方だが、どの検査も気づかない。CLAUDE.md の「検査対象に入っていない部品は、検査していないのと同じ」がそのまま当てはまる。

**直し方**: 次項のリファクタリングと組にして、判定部分を low_battery_core.h に切り出し、tools/test_low_battery_core.py を tools/test_encoder_gated.py・tools/test_status_led_core.py と同じ作り（cc で .so にして ctypes）で足す。流すべき入力: 打ち止めちょうど（2400mV）・1mV 上・1mV 下、USB あり／なし、下回る→上回る→下回る（リセットされること）、読み取りエラーを挟んだ列、SAMPLES=1 と 2 と 255。そのうえで CLAUDE.md の作法どおり、89 行目の比較や 94 行目の ++ を故意に壊して検査が赤くなることを確かめる（tools/mutate.py か、test_firmware.py の test_the_gate_check_notices_a_broken_gate と同じ parametrize の型）。

#### [test-gap] `battery_alkaline.c:61` — alkaline_mv_to_pct と ADC スケーリングは、自動検査で一度も実行されていない

**検証**: 3/3 が本物と判定

tools/test_firmware.py を全部読んだが、battery_alkaline.c のコードを 1 行も走らせていない。見ているのは (1) hhkb_split.dtsi のテキストから empty-millivolts / full-millivolts を正規表現で抜いて circuit.BATT_V_MIN / BATT_V_MAX と比べる（test_firmware.py:30-53）、(2) compatible 文字列と chosen の存在（:56-66）、(3) .conf の FETCH_MODE 文字列（:69-82）、(4) ファイルが存在すること（:110-115）だけ。つまり数字の出所の一致しか見ていない（冒頭の docstring:6-8 も自らそう宣言している）。grep -rn 'mv_to_pct' tools/ は 0 件。一方このリポジトリには同形の検査がすでに 4 つある（tools/test_encoder_gated.py / test_status_led_core.py / test_button_latch.py / test_stick_pod.py が cc → ctypes でロジックを実行する）。残量計だけがその型から漏れている。

**壊れ方**: 検査されていないのは次の 4 つで、どれを壊しても pytest tools は緑のまま通る。(1) 境界: mv >= full_mv で 100、mv <= empty_mv で 0（:62-67）。> と >= を取り違えても気づかない。(2) 単調性: open-gaps #13 が「主張している性質」として明記した 3 つのうちの 1 つなのに、どこでも確かめていない。式を (mv-empty)*100/(full-empty) から誤って (mv*100)/(full-empty) 等に書き換えても検出されない。(3) 負の ADC 読みのクランプ（:93-97）: この行は 87084c6「残量計が負の ADC 読みで高残量に化けるのを止めた」という実際に踏んだバグの修正なのに、回帰検査が無い。if (val < 0) val = 0; を消しても緑。消えると val が int32 の負 → (uint64_t) にキャストされて巨大値 → full_ohm 倍 → uint16 に折り返して、電池を抜いたのに高残量に化け、打ち止め（#25b）が効かなくなる。コメント自身が :93-94 でその壊れ方を書いているのに、それを検出する検査が存在しない。(4) 分圧のスケーリング（:98）: full_ohm と output_ohm を取り違えても（2000000/1000000 が逆になっても）緑。実測 2026-09-12 の「新品アルカリで 91%（逆算 3,219mV）」という外部の事実と突き合わせる検査も無い。

**直し方**: firmware/drivers/battery_alkaline_core.h を作り、alkaline_mv_to_pct() と「raw mV → 電池 mV（負クランプ＋分圧スケール）」を Zephyr に依らない static inline として切り出す（encoder_gated_core.h と同じ作り）。driver はそれを呼ぶだけにする。tools/stick_pod/ に bat_core_wrap.c を置き、tools/test_battery_alkaline.py で cc → ctypes。流すのは: 境界 4 点（empty-1 / empty / full / full+1）、単調性（empty..full を 1mV 刻みで全走査して非減少）、負の raw（-1 / -4096）で 0mV・0% になること、dtsi の実値（1MΩ+1MΩ・2400/3300）での 2026-09-12 の実測 3219mV → 91% の再現。そのうえで CLAUDE.md の作法どおり、クランプ行を消す・境界を > に変える等で故意に壊して落ちることを確かめてから入れる。

#### [test-gap] `encoder_gated.c:1` — encoder_gated.c は自動検査で一行も実行されていない（検査対象は core.h だけ）

**検証**: 2/3 が本物と判定

tools/test_encoder_gated.py:31 がコンパイルするのは tools/stick_pod/eg_core_wrap.c だけで、その中身は `#include "../../firmware/drivers/encoder_gated_core.h"` と 3 本の薄い皮（eg_start / eg_edge / eg_pulses）のみ。`grep -rn 'encoder_gated\.c\|eg_channel_get\|eg_arm\|eg_read_b\|FULL_ROTATION' tools/*.py` の結果はゼロ件。つまり **encoder_gated.c の eg_channel_get（度への換算）・eg_a_isr（a の変化判定と arm のやり直し）・eg_arm（レベルの向き）・eg_read_b（b の一瞬プルアップ）・eg_start / eg_stop / eg_pm_action / eg_init は、机の上でも CI でも一度も走っていない**。CI が見ているのは ZMK のビルドが通ることだけで、それはこれらの関数が正しいことを何も言わない。

**壊れ方**: 具体的に見逃す例: (1) eg_channel_get:139-144 の度への換算で steps を取り違えても（例: 96 を入れる）誰も気づかない。この換算は ZMK の behavior_sensor_rotate_common.c:42 の `360 / triggers_per_rotation` と噛み合って初めて 1 クリック = 1 トリガになるので、steps と triggers-per-rotation の不一致は実機で「2 クリックで 1 回しか動かない」として出る。(2) eg_arm:75-76 の三項演算子を反転させてしまうと、レベル割り込みが鳴りっぱなし（a が動かないのに CPU を焼き続ける）か、二度と鳴らない（エンコーダが完全に死ぬ）。どちらも検査は緑のまま。(3) eg_a_isr:100 の `closed != data->core.a_closed` を落とすと、レベル割り込みの取りこぼし対策が壊れる。

**直し方**: core.h と同じ型で、Zephyr の gpio / k_work / irq_lock を偽物に差し替えたヘッダを用意して encoder_gated.c そのものをホストでコンパイルし、ctypes から叩く。最低限 eg_channel_get の度換算（pulses → val1/val2 が steps と整合するか）と、eg_arm が「いまの a_closed の反対側」を選ぶことの 2 つ。前者は steps を故意に書き換えて赤になることを確かめてから入れる。

#### [test-gap] `test_button_latch.py:42` — bl_handle_event（.c 側）は自動検査で一行も実行されていない。core.h の 1 関数しか見ていない

**検証**: 3/3 が本物と判定

tools/test_button_latch.py:38 は -I firmware/src で button_latch_core.h だけをコンパイルし、bl_code を直接呼ぶ。input_button_latch.c はこの検査に入っていない（HARNESS の #include は button_latch_core.h のみ）。

他の検査も触っていない。tools/test_firmware.py を grep しても input_button_latch / button_latch / latch は 0 件。tools/*.py 全体を grep しても pod_remote.overlay・input-processors・input_processor は 0 件。

結果、.c の次のロジックは一度も実行されていない:
- 行 40-42 の型・コードの門（event->type != INPUT_EV_KEY || event->code != cfg->from で素通しする）
- 行 44-47 のレイヤーの OR ループ（cfg->layers_len 個の zmk_keymap_layer_active）
- 行 48 の event->value != 0 → press への変換
- 行 56-65 の DT からの config の組み立て（from / to / layers_len / layers[]）

**壊れ方**: 見逃すものが具体的にある。(1) 行 40 の門から `event->code != cfg->from` を落としても、bl_code だけの検査は緑のまま通る。実機では REL_X / REL_Y / BTN_1 まで書き換わり、ポインタが動かなくなる。(2) 行 45 のループを `i < cfg->layers_len` から `i < 1` に変えても緑。レイヤー 9（左 Ctrl）しか見なくなり、Fn＋押し込みの右クリックが黙って効かなくなる。(3) 行 48 の `event->value != 0` を `event->value == 0` と取り違えても緑。押し／離しが入れ替わる。(4) overlay の layers = <2 9> を <2 8> に変えても、どの検査も気づかない。

どれも「ビルドは通る・DRC 的な門も無い・実機で触るまで分からない」。

**直し方**: encoder_gated と同じ型にする。tools/stick_pod/eg_core_wrap.c と同様に、bl_handle_event 相当（型の門・レイヤーの OR・value→press）を Zephyr に依らない純関数へ切り出し（下のリファクタリング項）、ctypes でイベント列を流す検査を足す。最低限「KEY 以外は書き換えない」「from 以外のコードは書き換えない」「layers のどれが立っても置き換わる」「layers が空なら置き換えない」を見る。

あわせて tools/test_firmware.py に、status_led と同じ形の「積まれていること」の検査（Kconfig に config HHKB_INPUT_BUTTON_LATCH がある・CMakeLists が src/input_button_latch.c を足している・overlay の layers が keymap の #define FN / #define STK_SLOW と一致する）を足す。最後の 1 つは外部の事実（keymap）との突き合わせになる。

#### [test-gap] `boot_layer.c:1` — boot_layer は tools/ にも .github/ にも一度も登場しない。-win の版が本当に Windows 面で起動するかを誰も見ていない

**検証**: 2/3 が本物と判定

`grep -rn 'boot_layer\|BOOT_LAYER\|BASE_WIN' tools/ .github/` は 0 件（docs/superpowers/plans/ の古い計画書に BASE_WIN の記述があるだけ）。tools/test_firmware.py は profile_name.c については Kconfig・CMakeLists・左の .conf・ソース中の書式文字列まで突き合わせている（299-321 行）のに、boot_layer については同等の検査が存在しない。

**壊れ方**: 見逃すものが 3 つある。(1) **build.yaml の `-DCONFIG_HHKB_BOOT_LAYER=y` が効かなくなっても気づけない。**build.yaml 自身が「cmake-args では効かない設定がある」（CONFIG_ASSERT=n が select ASSERT に負けた、CONFIG_BT_CTLR_ASSERT_OVERHEAD_START=n が CI の Kconfig に無視された）と 2 件実例を記録している。HHKB_BOOT_LAYER は `depends on !ZMK_SPLIT || ZMK_SPLIT_ROLE_CENTRAL` を持つので、将来この依存が崩れれば同じく無言で n に落ちる。成果物は出来るので CI は緑のまま、-win.uf2 が Mac 面で起動するだけ。(2) **CONFIG_HHKB_BOOT_LAYER_ID の既定 1 と keymap の `#define BASE_WIN 1` の一致を誰も見ていない。**レイヤーを 1 枚挿入すれば Kconfig の 1 は別のレイヤーを指す。(3) **artifact-name に `-win` を持つ build.yaml の項目と、BOOT_LAYER を y にしている項目の対応**（-win でない版に誤って付く／-win に付け忘れる）。

**直し方**: tools/test_firmware.py に純テキストの検査を足す。(a) build.yaml を読み、`artifact-name` に `-win` を含む項目だけが `CONFIG_HHKB_BOOT_LAYER=y` を持つこと（両方向）。(b) firmware/Kconfig の `HHKB_BOOT_LAYER_ID` の default を正規表現で取り、hhkb_split.keymap の `#define BASE_WIN (\d+)` と一致すること。(c) keymap の keymap ノードの子の数を数え、default がその範囲内にあること。いずれも依存を増やさず数秒で回る。**足したら、わざと default を 1→2 に、`-win` を別の項目に移して、落ちることを確かめること。**


### medium

#### [bug] `status_led.c:253` — get_status を持たない transport があると、警告灯が「繋がっている」に倒れる（コメントが塞いだと主張している穴が、実際には塞がっていない）

**検証**: 2/3 が本物と判定

258-268 行のコメントは「available / enabled で continue しないこと。見るべき transport が 1 つも無い → 最後の return true に落ち、繋がっていないのに『繋がっている』と報告していた」と、2026-08-16 に実機で踏んだバグを明記している。ところが直前の 253-255 行 `if (t->api == NULL || t->api->get_status == NULL) { continue; }` は今も continue のままで、同じ落ち方をする。この continue だけが残ると、ループ本体が一度も回らず 284 行の `return LINK_CONNECTED` に素通りする。右（ペリフェラル側・214-238 行）も同型で、`bool connected = true;` で始まり同じ continue があるため、get_status を持つ transport が 0 個なら true のまま返る。現状の上流（/tmp/zmkq/app/src/split/bluetooth/central.c:1258-1266、peripheral.c:207-225）は両方とも get_status を実装しているので今日は顕在化しないが、「安全側＝未接続に倒す」という方針が片方の分岐にしか適用されていない。CLAUDE.md の「置き換えたら、置き換えられた方を消す」「判定材料なしを繋がっているに倒さない」に照らすと、直し残しである。

**壊れ方**: ZMK を更新して get_status を持たない split transport が追加される、あるいは ZMK_SPLIT_BLE を切って別の transport 構成にしたとき、STRUCT_SECTION_FOREACH の本体が一度も実行されずに LINK_CONNECTED が返る。その結果、右半分の電源が切れていても左の緑は出ず、利用者は「キーの右半分が反応しないのに LED は正常（消灯）」という、2026-08-16 に一度潰したのと同じ状態に戻る。ビルドは通り、DRC も CI も緑なので誰も気づけない。

**直し方**: 両方の read_split_link() で、`get_status` を持たない transport に出会ったら continue ではなく未接続側へ倒す（左は `return LINK_DISCONNECTED;`、右は `connected = false; break;`）。さらに「transport が 1 つも列挙されなかった」場合も未接続にするため、ループ前に `bool saw_any = false;` を置き、ループ後に `if (!saw_any) return LINK_DISCONNECTED;` を入れる。tools/test_firmware.py:259 の test_an_unusable_transport_counts_as_disconnected は available/enabled の分岐しか見ていないので、api/get_status の分岐についても同じ「continue を書いたら落ちる」検査を足すこと。

#### [bug] `encoder_gated.c:148` — eg_trigger_set が呼ばれる前に割り込みが走り、その刻みの通知が落ちる

**検証**: 2/3 が本物と判定

eg_init（encoder_gated.c:204-219）は POST_KERNEL / CONFIG_SENSOR_INIT_PRIORITY で走り、その末尾の eg_start:174 で `eg_arm(dev)` して**割り込みを有効にする**。一方 ZMK が eg_trigger_set を呼ぶ zmk_sensors_init は SYS_INIT(..., APPLICATION, ...)（/private/tmp/zmkq/app/src/sensors.c:139）なので**後**。その間に a が動くと eg_a_isr:101 で core.pulses は増えるが、eg_work:113 の `data->handler != NULL` が偽で通知が出ない。ZMK 標準の ec11 はそもそも trigger_set（ec11_trigger.c:98-112）の中で初めて割り込みを有効にするので、この窓が無い。

**壊れ方**: 電源投入直後（数十 ms〜数百 ms）にノブを回すと、その刻みは即座には反応しない。pulses には残るので、次に 1 刻み回したときにまとめて出る（例: 起動直後に 3 クリック回して無反応 → その後 1 クリック回したら 4 クリック分飛ぶ）。handler が NULL のまま溜め続ける経路なので、上の int8 の溢れとも重なる。

**直し方**: eg_init では arm せず、eg_trigger_set の中で初めて eg_arm する（ec11 と同じ形）。あるいは eg_trigger_set で handler を入れた直後に、pulses が 0 でなければ一度 k_work_submit して溜まっている分を吐かせる。

#### [doc-mismatch] `open-gaps.md:125` — open-gaps の一覧（冒頭の「いま残っているもの」）が、2026-09-03 に解決済みの「% が変わったときしか事象が出ない」を未解決として載せ続けている

**検証**: 2/3 が本物と判定

docs/hardware/open-gaps.md:125 の #25b の行は「⚠️ 2026-09-02: ZMK は % が変わったときしか事象を出さないので、いまの実装では 0% 張り付きで止まらない（節の冒頭）」と書いている。しかし本文の #25b 節（1966 行目から）には「✅ 2026-09-03 直した」とあり、firmware/src/low_battery_off.c:19-22 のコメントも、実際のコード（107-118 行目の k_timer）も、事象の待ち受けをやめて周期タイマーに替わっている。一覧だけが古い。さらに一覧の行は 2026-10-08 の CONFIG_ZMK_USB → CONFIG_USB_DEVICE_STACK の訂正（本文には書いてある）にも触れていない。CLAUDE.md が「節を直しても一覧を直さず、解決済みが 4 日間『未解決』で残ったことがある」と名指しで警告している、まさにその型の再発で、今回は 2026-09-03 から 2026-10-15 まで 6 週間残っている。

**壊れ方**: CLAUDE.md は「冒頭の『いま残っているもの』から読む」と指示している。その指示に従って一覧だけを読んだ人（や次のセッション）は、既に直っている問題を直しに行くか、逆に「どうせ止まらないと書いてある」と読んで、Task C4/C5 の実機試験で soft off が効かないことを想定内として流す。本当に残っている問題（上の idle でキャッシュが固まる件・実機未確認であること）は一覧のどこにも書かれていないので、一覧を信じるほど実態から遠ざかる。

**直し方**: 125 行目を本文の現状に合わせて書き直す。残っているのは (a) 実機で一度も動かしていない（Task C4/C5 待ち）、(b) 本監査で見つかった idle 中のキャッシュ凍結、(c) 判定ロジックに自動検査が無いこと、の 3 つ。解決済みの「% が変わったときしか」は一覧から落とす（本文の経緯には残す）。

#### [doc-mismatch] `low_battery_off.c:79` — 「ZMK が同じ周期で fetch 済み」というコメントが条件付きでしか成り立たない。battery_alkaline.c の前提コメントも 2026-09-03 の変更前のまま

**検証**: 2/3 が本物と判定

14-16 行目は「ZMK が電池を測る周期（ZMK_BATTERY_REPORT_INTERVAL・既定 60 秒）と同じ周期の自前タイマーで、driver がキャッシュしている電圧を読む」、79-80 行目は「**測り直さない。**ZMK が同じ周期で fetch 済みなので、driver のキャッシュを読むだけでよい」と書いている。外部事実と照らすと、既定 60 秒は正しい（ZMK app/Kconfig.defaults:112-113 で default 60）が、「同じ周期で fetch 済み」は条件付きでしか成り立たない。app/src/battery.c:164-184 が idle/sleep でタイマーを止めるからで、30 秒無操作（app/Kconfig:403-404 の既定 30000ms）でその条件は外れる。キーボードの通常の使われ方では、むしろ止まっている時間のほうが長い。コメントがこの条件に一言も触れていない。また battery_alkaline.c:108-120 のコメントも「読み手は zmk_battery_state_changed の listener で、ZMK が測った直後に呼ばれる（firmware/src/low_battery_off.c の冒頭のコメント）」と書いているが、これは 2026-09-03 の変更前の姿で、現在の low_battery_off.c は listener ではない。2 つのファイルが互いに古い記述で参照し合っている。

**壊れ方**: この 2 つのコメントがあるために、1 件目のバグ（idle でキャッシュが固まる）が「仕様どおり」に見えてレビューをすり抜ける。実際このコメントは 2026-09-03 の修正で「% が変わったときしか出ない」を外部確認して直したときに書かれたもので、同じ battery.c の 20 行下にある k_timer_stop は見ていない。次に誰かがこの機能を疑うときも、コメントを読んで「fetch は保証されている」と判断して、別の場所を探すことになる。battery_alkaline.c の側は、電圧と % の整合が要らない理由として「読み手は listener だから」を挙げているので、前提が変わったことに気づかず 2 値を使う読み手を足す危険がある。

**直し方**: 1 件目のバグを直したうえで、コメントを実態に合わせる。自分で fetch する方式にするなら 79-80 行目は削除して「ZMK のタイマーは idle で止まるので当てにできない」を理由として書く。activity を購読する方式にするなら、その購読があることをコメントに書く。あわせて battery_alkaline.c:108-120 の「読み手は zmk_battery_state_changed の listener」という記述も、現在の読み手（周期タイマー）に直す。

#### [refactor] `status_led.c:383` — 表示側の switch（383-476 行）は Zephyr 依存がゼロなのに core に出ていない。切り出せば既存の ctypes 治具でそのまま検査できる

**検証**: 3/3 が本物と判定

383-476 行を grep した結果、この範囲に gpio_ / zmk_ / k_work_ / STRUCT_SECTION の呼び出しは 1 つも無い。唯一の外部接触は set_color() で、これは 194-198 行の gpio_pin_set_dt 3 行だけの薄い変換。つまり switch 全体は (st, step, split_link, host_link, announce_color) から (色, next_ms, 新しい step, 新しい announce_color, 新しい booting) を作る純粋関数で、status_led_core.h に出ている slc_state / slc_announce とまったく同じ性質を持つ。切り出し先の型も治具も既に揃っている: firmware/drivers/encoder_gated_core.h は状態を struct に持たせて eg_core_edge() で 1 ステップ進める形を取っており、tools/stick_pod/eg_core_wrap.c + tools/test_encoder_gated.py がそれを ctypes で時系列に流している（test_random_walk_matches_net_detents は 200 試行の乱数列を回している）。status_led も同じ形にできる。切り出さない限り、上の test-gap で示した 3 つの退行は検出できないままになる。

**壊れ方**: 今のままだと、点滅パターンに関わる変更（時定数の調整・交互表示の条件・パルス数・STATE_BOOT の step 進行）を入れたとき、ビルドと 32 件の検査が全部緑でも表示が壊れている可能性がある。実際に 3 箇所を壊して確認済み（全部緑）。検証手段が「実機に焼いて目で見る」しかないので、push → 2 分半 → 焼く → 30 分待って電池表示を見る、という確認が毎回要る。BATT_LOW は 1 周 30 秒、未接続の交互表示は 1 周 1 秒なので、目視では取りこぼしやすい。

**直し方**: status_led_core.h に struct slc_render_state { uint8_t step; enum slc_state shown; enum slc_color announce; bool booting; } と、`static inline struct slc_out slc_render(struct slc_render_state *s, enum slc_state st, const struct slc_in *in)`（slc_out は {enum slc_color color; uint32_t next_ms;}）を足し、status_led.c 側は `struct slc_out o = slc_render(&render, st, &in); set_color((enum led_color)o.color); k_work_reschedule(&blink_work, K_MSEC(o.next_ms));` だけにする。時定数（BOOT_ON_MS〜BATT_REPLACE_MS）も core へ移し、status_led.c は #define で引く（BATT_LOW_PCT が SLC_BATT_LOW_PCT を引いているのと同じ形）。既に BUILD_ASSERT（318-328 行）で enum の並びを縛る作法があるので、色の enum にも同じ縛りを足すこと。tools/stick_pod/slc_wrap.c に slc_render_of() を足せば、tools/test_status_led_core.py から時系列で回せる。

#### [refactor] `low_battery_off.c:69` — 判定の純粋ロジックが Zephyr の API に埋まっていて、机の上で動かせない。このリポジトリには既に *_core.h の型がある

**検証**: 3/3 が本物と判定

low_battery_check()（69-105 行目）の中身は、実は 2 つが混ざっている。Zephyr に依る部分は zmk_usb_is_powered()・sensor_channel_get()・LOG_*・zmk_pm_soft_off() の 4 つだけ。残り（USB なら 0 にして抜ける、mv を組み立てる、EMPTY_MV と比べる、consecutive を増減する、SAMPLES と比べて止めるかを決める）は入力 3 つ（usb_powered, mv, 読めたか）と状態 1 つ（consecutive）から出力 1 つ（止めるか）を決めるだけの純粋関数で、Zephyr を 1 つも必要としない。このリポジトリには既にこの切り出しの型が 2 つあり（firmware/drivers/encoder_gated_core.h + tools/test_encoder_gated.py、firmware/src/status_led_core.h + tools/test_status_led_core.py。どちらも tools/stick_pod/*_wrap.c を cc でビルドして ctypes で叩く）、status_led_core.h のほうは「560 行が実機でしか確かめられておらず、優先順位と遷移が一度も自動で検査されていなかった」という、このファイルと同じ理由で作られている。さらに consecutive が関数内 static（70 行目）なので、仮に検査を書こうとしても外から初期化できず、検査どうしが状態を引き継いでしまう（切り出せば構造体のメンバーになり、この問題も消える）。

**壊れ方**: 切り出さない限り、前項の test-gap は埋められない。打ち止めの境界（2400mV ちょうど）も、SAMPLES の数え方も、USB の門の「数え直して抜ける」という副作用も、実機で電池を使い切る Task C4/C5 まで一度も実行されない。そして 31-32 行目が自ら書いているとおり、この機能は「ビルドが通っているだけで、実機では一度も動かしていない」。間違っていたと分かるのが、電池を使い切る試験のときになる。

**直し方**: firmware/src/low_battery_off_core.h に struct lbo_core { uint8_t consecutive; } と、int lbo_core_step(struct lbo_core *c, bool usb_powered, bool read_ok, uint32_t mv, uint32_t empty_mv, uint8_t samples) を置き、戻り値で「止める／止めない」を返す（encoder_gated_core.h と同じ static inline の作り）。low_battery_check() は Zephyr から 3 つの入力を集めて lbo_core_step を呼び、真なら LOG_ERR と zmk_pm_soft_off() を呼ぶだけにする。tools/stick_pod/ に wrap を足して tools/test_low_battery_core.py から叩く。切り出しの副産物として、上の 3 つのバグのうちエラー時の consecutive の扱いが検査可能になる。

#### [test-gap] `test_firmware.py:222` — test_the_warning_survives_idle が、core 切り出し後は本物の退行を検出できなくなっている（故意破壊で確認）

**検証**: 2/3 が本物と判定

222 行の `assert code.count("== ZMK_ACTIVITY_SLEEP") >= 2` は、コメントに「リスナ側と current_state 側の両方に要る（片方だけだと、もう片方が idle で消す）」と書いてある。しかし 2026-08-16 の判断（idle では消さない）は、98a82bf の切り出しで firmware/src/status_led_core.h:76 の `if (in->activity == SLC_SLEEP)` へ移った。status_led.c に残る 2 つの `== ZMK_ACTIVITY_SLEEP` は 299 行（ZMK の enum を SLC の enum に写すだけのマッピング）と 525 行（リスナ）で、299 行はもはや「idle で消さない」という判断を担っていない。つまりこの検査は、数は 2 で満たされているが中身を守っていない。実際に status_led_core.h:76 を `if (in->activity != SLC_ACTIVE)` に書き換えて tools/test_firmware.py を回したところ 19 passed で通った（検査が穴になっていることを故意破壊で確認済み）。CLAUDE.md の「検査対象に入っていない部品は、検査していないのと同じ」。

**壊れ方**: status_led_core.h の slc_state() を `in->activity != SLC_ACTIVE` に戻す（＝2026-08-16 に利用者の指摘で直したのと同じ退行）と、未接続の警告が 30 秒の無操作で勝手に消えるようになる。test_firmware.py はこの変更にまったく反応しない。救っているのは tools/test_status_led_core.py:64 の test_idle_does_not_hide_the_warning だけで、test_firmware.py の 203-224 行はコメントで「この検査が無いと同じ後退に誰も気づけない」と宣言しながら、実際には何も見ていない。2 つあるうち片方が空振りしていることに気づかないと、将来 core 側の検査を整理したときに両方失う。

**直し方**: test_the_warning_survives_idle の対象を status_led.c から status_led_core.h に移す（`!= SLC_ACTIVE` が無いこと、`== SLC_SLEEP` があることを見る）。あるいはこの検査自体を消して、tools/test_status_led_core.py の test_idle_does_not_hide_the_warning が唯一の出所だとコメントに書く（同じ規則を 2 か所に書かない、という status_led.c:292 の方針と揃う）。どちらにしても、直したあと status_led_core.h:76 を故意に壊して実際に落ちることを確かめること。

#### [test-gap] `sim.c:114` — settings_save_one が常に成功するので、F14（保存に失敗しても saved を動かさない）が検査されていない

**検証**: 2/3 が本物と判定

sim.c:114 の settings_save_one は無条件に 0 を返す。そのため stick_pod.c:308-312（rc < 0 のとき saved を動かさず LOG_ERR して return）は、26 場面すべてで一度も実行されない。同様に sp_settings_set の 2 つのエラー枝も走っていない: len != sizeof(c) → -EINVAL（889-891 行）と read_cb が負を返す枝（895-897 行）。sim.c:187 は必ず len=4 で、rd() は必ず len を返す。

**壊れ方**: この保護（F14）が壊れた場合、つまり rc < 0 でも data->saved = c を実行してしまう版にしても、既存の検査はすべて緑のまま通る。実機では『flash が一杯／NVS が壊れている』で保存に失敗した後、saved だけが RAM 上で進んでしまい、sp_track_centre の ±0.1 の窓（367 行）と sp_enter_stuck の再中心化の窓（450 行）が、実際には flash に無い値を基準にする。次の起動で保存値は古いままなので、中心が飛ぶ。私は sim.c を手元で書き換えて settings_save_one を失敗させ、現状のコードでは stored が 0,0 のまま動かないことを確認した（＝いまの実装は正しい）。正しいことと、検査がそれを守っていることは別。

**直し方**: sim.c に save_fail スイッチを足して場面を 1 つ増やし、『保存に失敗し続けても stored が動かないこと』と『次に 0.01 ずれたら再び予約されること』を見る。sp_settings_set には len=3 と len=8 を渡す場面も足す。

#### [test-gap] `behavior_stick_recal.c:1` — stick_recal も検査ゼロ。冒頭コメントが命綱にしている「ノード名 15 文字以内」を機械で見ていない

**検証**: 2/3 が本物と判定

`grep -rn 'stick_recal' tools/` は 0 件。behavior_stick_recal.c:13-15 は「⚠️ ノード名は 15 文字以内にすること。右へ送る payload の名前欄が 16 バイトで、長いと切り詰められて右で見つからない」と書いている。この主張自体は正しい（/tmp/zmkq/app/include/zmk/split/transport/types.h:76 の `char behavior_dev[16]`、/tmp/zmkq/app/src/split/central.c:103-107 の strlcpy で切り詰め）。現状の `stick_recal` は 11 文字で収まっている。だがこの制約を守らせる仕組みが**コメント 1 行しかない**。

**壊れ方**: keymap の behavior ノードを `stick_recalibrate`（17 文字）のように改名すると、左（セントラル）では invoke_locally で動くので**手元では完全に正常に見える**。右（ペリフェラル）だけが `stick_recalibra` に切り詰められた名前を受け取り、zmk_behavior_get_binding が NULL を返して peripheral.c:56 の `Failed to invoke behavior` を出す。ビルドは左右とも緑、左のログも無言。RTT を右に繋いでログを読むまで気づけない（その配線は docs/development/rtt-debugging.md が要るもので、常に繋がってはいない）。この behavior の存在理由そのもの（左右どちらのポッドにも 1 つのキーで届かせる）が静かに壊れる。

**直し方**: tools/test_firmware.py に、hhkb_split.keymap の `compatible = "hhkb,behavior-stick-recal"` を持つノードのラベル名を抜き出し `len(name) <= 15` を確かめる検査を足す。より広く、**GLOBAL locality の behavior すべて**（firmware/src/*.c を `BEHAVIOR_LOCALITY_GLOBAL` で grep → その DT_DRV_COMPAT → keymap のノード名）に掛けるほうがよい。足したあと、名前を 16 文字に伸ばして落ちることを確かめること。


### low

#### [doc-mismatch] `status_led.c:168` — 168-174 行のコメントが、既に存在しない bool 変数を説明している（「初期値は左右で違う」「true でよい」）

**検証**: 2/3 が本物と判定

168-174 行のブロックコメントは「『相手と繋がっているか』。左では右手、右では左（セントラル）を指す。⚠️ 初期値は左右で違う。左（セントラル）… 毎 tick に transport の get_status() で読み直すので初期値は事実上使われない。true でよい」と書かれている。だがこのコメントが現在かかっている宣言は 176-177 行の `static uint8_t battery_pct = 100;` と `static bool booting = true;` で、接続状態とは無関係。実際のリンク変数は 156 行 `static enum link_state host_link = LINK_DISCONNECTED;` と 164 行 `static enum link_state split_link = LINK_DISCONNECTED;` に移っており、どちらも同じ初期値（LINK_DISCONNECTED）なので「初期値は左右で違う」は成り立たず、enum なので「true でよい」も型として成り立たない。bool から enum link_state へ置き換えた際に、古い説明だけが残った。CLAUDE.md の「置き換えたら、置き換えられた方を消す。コード・生成物・記録の 3 つを、消した名前で grep する」の取りこぼし。

**壊れ方**: このファイルを次に読む人（あるいは次のセッション）が、接続状態の初期値が左右で非対称だと信じて読む。実際には両方 LINK_DISCONNECTED（＝安全側に倒してある）なのに「左は true で初期化されている」と誤認し、「左は初期値が繋がっている扱いだから危ない」という存在しないバグを追う、あるいは逆に「初期値は事実上使われない」を真に受けて 156/164 行の初期値を LINK_CONNECTED に変えてしまう。後者をやると、起動直後の最初の tick で read_split_link() が走る前に current_state() が評価される経路（refresh 経由）で、一瞬「繋がっている」と表示しうる。

**直し方**: 168-174 行のコメントを削るか、156/164 行の宣言の上へ移したうえで実態に書き換える（「左右とも LINK_DISCONNECTED で始める。警告灯の既定は安全側＝未接続。どちらも毎 tick に read_split_link() / zmk_ble_active_profile_is_connected() で読み直すので、初期値が見えるのは最初の tick の前だけ」）。あわせて `battery_pct` / `booting` にそれぞれの説明を付ける。

#### [doc-mismatch] `stick_pod.c:717` — F8 のコメントが『全デバイスを前から順に suspend する』と書いているが、SLEEP の経路は逆順

**検証**: 2/3 が本物と判定

717-718 行のコメントは「zmk_pm_soft_off() は全デバイスを**前から順に** suspend するので、i2c はこのデバイスより先に止められる」と書いている。ZMK の実物を読むと経路が 2 つあり、順番が逆である: (1) soft off の前半 app/src/pm.c:108-114 は i = 0 から昇順なので、コメントのとおり i2c（CONFIG_I2C_INIT_PRIORITY = KERNEL_INIT_PRIORITY_DEVICE = 50）が stick_pod（CONFIG_INPUT_INIT_PRIORITY = 90）より先。(2) しかし SLEEP の経路 app/src/activity.c:82 が呼ぶ zmk_pm_suspend_devices() は app/src/pm.c:38 で `for (dev = devs + devc - 1; dev >= devs; dev--)` と**降順**に回る。つまり SLEEP では stick_pod が先、i2c が後になる。

**壊れ方**: 実害は出ない（sp_stop の RESUME → SUSPEND のやり直しは、どちらの順番でも終点が同じになるので正しく働く）。危ないのは次に触る人で、『i2c は必ず先に止まっている』を前提に F8 のやり直しを「要らない」と判断して消すと、soft off の経路でだけピンが sleep 状態に戻らなくなり、TWIM の電流が残る。CLAUDE.md の「覆す前に読む」が効かない形で記録が間違っている。

**直し方**: コメントを 2 つの経路に分けて書き直す。soft off（pm.c:108 昇順・i2c が先）と SLEEP（pm.c:38 降順・stick_pod が先）の両方を挙げ、『どちらの順番でも終点を揃えるためにやり直している』と理由を書く。


---

## 反証で落ちた指摘（記録として）

「見つけたが、調べたら違った」もの。**同じ指摘を次も挙げないため**に残す。

- ~~ホストも未接続のときに右手が復帰すると、緑の復帰合図が捨てられて永久に出ない（決定表 L10 を満たさない）~~ （`status_led.c`・2/3 が反証）
- ~~zmk_pm_soft_off() の戻り値を捨てている。失敗して戻ってきても consecutive が上限のままで、以後毎周期 soft off を呼び続ける~~ （`low_battery_off.c`・3/3 が反証）
- ~~sensor_channel_get が失敗したときに consecutive を触らない。失敗を挟むと数え方が「連続」でなくなる~~ （`low_battery_off.c`・3/3 が反証）
- ~~コメントが書いている読み手（zmk_battery_state_changed の listener）は 2026-09-03 に廃止済み~~ （`battery_alkaline.c`・2/3 が反証）
- ~~I2C を起こせなかった回はどの数字にも出ない（SP_REJ_IO が一度も読まれていない）~~ （`stick_pod.c`・2/3 が反証）
- ~~模擬器の pm_device_action_run は絶対に失敗しないので、PM の失敗経路が一度も走っていない~~ （`sim.c`・3/3 が反証）
- ~~sp_on_frame の状態機械が Zephyr 依存と混ざっていて、*_core.h に切り出せていない~~ （`stick_pod.c`・3/3 が反証）
- ~~検査が int8 の溢れを「前提」として自分で避けている（上の実バグを構造的に見逃す）~~ （`test_encoder_gated.py`・3/3 が反証）
- ~~スリープからの復帰（eg_start）が、まだ読み出されていない刻みを捨てる~~ （`encoder_gated.c`・3/3 が反証）
- ~~「割り込みの中の仕事はピンの設定 3 回と settle-us の待ちだけ」が実際より少ない~~ （`encoder_gated.c`・3/3 が反証）
- ~~度への換算が eg_channel_get の中に埋まっていて、core.h 側で検査できない~~ （`encoder_gated.c`・3/3 が反証）
- ~~押下が落ちて離しだけが届くと、held_alt が前回のまま残り、逆のボタンが押されたままになる~~ （`input_button_latch.c`・2/3 が反証）
- ~~切り出しが浅い。Zephyr に依らない判断（型の門・レイヤーの OR・value→press）が .c 側に残っている~~ （`input_button_latch.c`・2/3 が反証）
- ~~layers が required: true なのに、空配列・範囲外の番号をビルドが止めない。binding の説明と実際の安全性が違う~~ （`hhkb,input-processor-button-latch.yaml`・2/3 が反証）
- ~~CONFIG_HHKB_BOOT_LAYER_ID が範囲外でも黙って無視される（Kconfig は 0〜31、実在するレイヤーは 0〜9）~~ （`boot_layer.c`・2/3 が反証）
- ~~名前が CONFIG_BT_DEVICE_NAME_MAX を超えると snprintf が黙って切り詰め、切り詰めた名前で広告してしまう~~ （`profile_name.c`・3/3 が反証）
- ~~名前を組み立てる部分を *_core.h に切り出せば、encoder_gated と同じ型で境界を検査できる~~ （`profile_name.c`・3/3 が反証）
