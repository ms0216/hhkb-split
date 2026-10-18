# `Failed to set output 0 to 0: -11`（595 の EAGAIN）

**2026-10-14 に RTT を入れた初日に見つかった。**実機では「普通に打てている」
ので、**ログを読めるようにするまで誰も気づいていなかった。**

**結論を先に: 実害は無い。ZMK 本体の構造の話で、このリポジトリの誤りではない。
直す必要も（いまは）無い。**

---

## 1. 何が出るか

```
<err> zmk: Failed to set output 0 to 0: -11
```

断続的に出る。観測した時刻: 起動 18 秒／3 分 47 秒／3 分 48 秒。
**キー入力は正常に動いている**（同じログに `Sending event at 3,5 state on` が出る）。

## 2. -11 の正体

**Zephyr では `EWOULDBLOCK` は `EAGAIN` と同じ 11**
（[lib/libc/minimal/include/errno.h](https://github.com/zephyrproject-rtos/zephyr/blob/main/lib/libc/minimal/include/errno.h)
`#define EAGAIN 11` / `#define EWOULDBLOCK EAGAIN`）。

595 のドライバが返している:

```c
/* app/module/drivers/gpio/gpio_595.c  reg_595_port_set_masked_raw() */
/* Can't do SPI bus operations from an ISR */
if (k_is_in_isr()) {
    return -EWOULDBLOCK;        /* = -EAGAIN = -11 */
}
```

**SPI は割り込みの中では叩けない。**ドライバは正しく拒否している。

## 3. なぜ割り込みの中から呼ばれるのか

ZMK の kscan が、**ISR の中で出力を落としにいく**:

```
キー押下 → GPIO 割り込み（ISR）
  └ kscan_matrix_irq_callback_handler()          ← ISR
      └ kscan_matrix_interrupt_disable()
          └ kscan_matrix_set_all_outputs(dev, 0)
              └ 595 の port_set_masked_raw()
                  └ if (k_is_in_isr()) return -EWOULDBLOCK;   ★ ここ
      └ LOG_ERR("Failed to set output %i to %i: %i", ...)
```

**GPIO が本物のピンなら成功する**（レジスタを書くだけ）。
**595 は SPI の先にいる**ので、ISR から書けない。
ZMK の kscan は「出力は即座に書ける」前提で書かれている。

## 4. なぜ実害が無いか

失敗した書き込みは**先回りの「全部 inactive にしておく」**で、
その意図はコメントに書いてある:

```c
// While interrupts are disabled, set all outputs inactive so
// kscan_matrix_read() can scan them one by one.
```

**`kscan_matrix_read()` はワークキューで走る**（ISR ではない）ので、
そこでの `gpio_pin_set_dt` は成功する。しかも読み取りは**列ごとに
active→inactive を自分でやる**ので、先回りの一括設定が無くても走査は成立する。

→ **エラーは出るが、機能は落ちない。**実機で普通に打てているのと一致する。

## 5. 直すとしたら（**いまはやらない**）

| 手 | 中身 | 代償 |
|---|---|---|
| **やらない**（いまの判断） | 実害が無い。上流の構造の話 | ログに `<err>` が出続ける。**本物のエラーを埋もれさせる** |
| ログを黙らせる | この 1 行だけ抑制 | **警告を隠すことになる**（この案件の作法に反する） |
| 上流へ PR | ISR から呼ぶ経路で、SPI 越しの GPIO を扱えるようにする（work に逃がす） | 取り込まれるかは相手次第 |

⚠️ **「ログに出るだけ」で放置すると、本物のエラーが見えなくなる**のが唯一の
実害。RTT を読むときは、この行が既知であることを思い出すこと。

## 6. 確かめた範囲

- [x] `-11` が `EWOULDBLOCK`=`EAGAIN` であること（Zephyr の errno.h）
- [x] 595 が ISR で弾いていること（gpio_595.c のソース）
- [x] ISR から呼ばれる経路（kscan_gpio_matrix.c のソース）
- [x] 走査がワークキューで走り、実害が無いこと（同上）
- [ ] **ポッド無しの版でも同じように出るか**（2026-10-15 に確認予定。
      ポッド付きの版を誤って焼いていたので、念のため）
