/*
 * status_led.c が外へ出す唯一の口。
 *
 * **soft off の直前に LED を消すため**だけに在る（2026-10-15 の監査）。
 * 点いたまま System OFF に入ると、nRF52840 の GPIO は状態を保持するので
 * 1〜2mA を舐め続ける（待機 20µA の 50〜100 倍）。
 *
 * SPDX-License-Identifier: MIT
 */
#ifndef HHKB_STATUS_LED_H
#define HHKB_STATUS_LED_H

/* LED を消して、点滅の work も止める。何度呼んでもよい。 */
void hhkb_status_led_off(void);

#endif /* HHKB_STATUS_LED_H */
