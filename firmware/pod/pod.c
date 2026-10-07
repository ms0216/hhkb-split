/*
 * pod_fixed.c - stick pod firmware (K_SPEC.md v7, section 3), ATtiny1616, bare-metal avr-gcc.
 *
 * REVIEW COPY of pod.c.  Every change is marked "FIX n" (see the review report).
 *
 * DRY-RUN IMPLEMENTATION. Never run on hardware. Written strictly from K_SPEC.md,
 * proto_model_v6.py (frame layout) and the ATtiny1614/1616/1617 datasheet
 * (DS40002204A, "DS" below) + errata. Where the spec does not determine something
 * the choice is marked "DECISION n" and listed in NOTES.md (b).
 *
 * Tags:  DS = checked against datasheet text / header,  R = reasoned,  G = guess.
 *
 * Pins (spec section 1):
 *   PA0 UPDI (untouched)          PB0 SCL  (TWI0 client)
 *   PA1 reserved: input, buf off  PB1 SDA  (TWI0 client)
 *   IN-CASE PINOUT (build/joystick/pod_layout): PA6 click switch (async pin)  PB4+PB5 stick supply
 *   T is read on PB5 itself (AIN8), X = PA5 (AIN5), Y = PA7 (AIN7).  Lines below describe the old pinout:
 *   PA2 click switch (async pin)  PB4+PB5 stick supply (driven together)
 *   PA4 AIN4 stick top (T)        everything else: input buffer disabled
 *   PA5 AIN5 X,  PA6 AIN6 Y
 *
 * Build:
 *   avr-gcc -mmcu=attiny1616 -Os -std=gnu11 -Wall -Wextra -o pod.elf pod.c
 */

#define F_CPU 3333333UL /* 20 MHz / 6, reset default. DS 10.3.3, MCLKCTRLB reset 0x11 */

#include <avr/io.h>
#include <avr/interrupt.h>
#include <avr/sleep.h>
#include <avr/wdt.h>
#include <avr/fuse.h>
#include <util/crc16.h>
#include <util/delay.h>
#include <stdint.h>

/* ------------------------------------------------------------------ fuses
 * Spec section 3 gives WDTCFG, BODCFG, SYSCFG0, OSCCFG only.  The .fuse section
 * necessarily contains the others too, so they had to be chosen (DECISION 1).
 *
 *  fuse     value  meaning                                             source
 *  WDTCFG   0x0B   WINDOW=0 (off), PERIOD=0xB = 8KCLK = 8 s            spec; DS 19.5.1
 *  BODCFG   0x08   LVL=0 (1.8 V), SAMPFREQ=0 (1 kHz), ACTIVE=2 sampled,
 *                  SLEEP=0 disabled                                    spec; DS 6.10.4.2
 *  OSCCFG   0x02   FREQSEL=2 (20 MHz), OSCLOCK=0                       spec; DS 6.10.4.3
 *  TCD0CFG  0x00   all compare outputs off                             DECISION 1 (DS reset 0)
 *  SYSCFG0  0xC4   CRCSRC=NOCRC, RSTPINCFG=UPDI, EESAVE=0              spec; DS 6.10.4.5
 *  SYSCFG1  0x07   SUT=64 ms                                           DECISION 1 (DS reset 7)
 *  APPEND   0x00   no app-data section                                 DECISION 1
 *  BOOTEND  0x00   no boot section                                     DECISION 1
 *  LOCKBIT  (not emitted; stays 0xC5 = unlocked)
 */
FUSES = {
    .WDTCFG = 0x0B,
    .BODCFG = 0x08,
    .OSCCFG = 0x02,
    .reserved_1 = {0xFF},
    .TCD0CFG = 0x00,
    .SYSCFG0 = 0xC4,
    .SYSCFG1 = 0x07,
    .APPEND = 0x00,
    .BOOTEND = 0x00,
};

/* ------------------------------------------------------------------ constants */
#define POD_ADDR 0x2A      /* 7-bit */
#define FRAME_MAGIC 0xC3
#define FRAME_VERSION 1    /* spec v7 section 2: version = 1 */
#define FRAME_LEN 11

#define STICK_PWR_bm (PIN4_bm | PIN5_bm) /* PB4 | PB5 = 0x30 */
#define SW_bm PIN6_bm                    /* PA6 (fully async, DS note under table 5-1) */

/* PA2 PINnCTRL values used by the click state machine (DS 16.5.11) */
#define SW_ARMED (PORT_PULLUPEN_bm | PORT_ISC_BOTHEDGES_gc) /* released: wake on both edges */
#define SW_QUIET (PORT_PULLUPEN_bm | PORT_ISC_INTDISABLE_gc) /* pull-up on, buffer on, no irq */
#define SW_OFF (PORT_ISC_INPUT_DISABLE_gc)                   /* held: pull-up off, buffer off */

#define TWI_SCTRLA_RUN (TWI_DIEN_bm | TWI_APIEN_bm | TWI_PIEN_bm | TWI_ENABLE_bm) /* no SMEN, no PMEN */
#define ADC_CTRLC_RUN (ADC_SAMPCAP_bm | ADC_REFSEL_VDDREF_gc | ADC_PRESC_DIV4_gc) /* 833 kHz */
/* DECISION 10: the spec fixes 31.25 ms but not the clock.  1.024 kHz / 32 is used
 * (rather than 32.768 kHz / 1024) because the spec's sleep-current budget quotes the
 * DS table 36-5 figure for "RTC running at 1.024 kHz from internal OSCULP32K". */
#define PIT_CLKSEL_RUN RTC_CLKSEL_INT1K_gc
#define PIT_CTRLA_RUN (RTC_PERIOD_CYC32_gc | RTC_PITEN_bm) /* 32 / 1024 Hz = 31.25 ms */

/* TCB one-shot tops at CLK_PER = 3.333 MHz, CLKDIV1.  CAPT when CNT == CCMP (DS table 21-6) */
#define TCB_TOP_5MS (16667 - 1)
#define TCB_TOP_4MS (13333 - 1)

/* ------------------------------------------------------------------ state */
static uint8_t boot_id __attribute__((section(".noinit"))); /* survives non-power resets */

static uint8_t reset_cause; /* 0 POR, 1 BOD, 2 WDT, 3 other */
static uint8_t seq;         /* measurement serial number; first frame carries 1 (model) */
static uint8_t press_cnt;   /* mod 16 */
static uint8_t release_cnt; /* mod 16 */

static volatile uint8_t btn_down;   /* debounced state */
static volatile uint8_t txn_active; /* TCB0 running: address match seen, no STOP/timeout yet */
static volatile uint8_t deb_active; /* TCB1 running: 4 ms debounce pending */

static uint8_t frame[9];
static uint16_t tx_crc;
static uint8_t tx_idx;
static uint8_t pit_div;
static uint8_t adc_fail;      /* FIX 1: any conversion of the current measurement timed out */
static uint16_t twi_irq_cnt;  /* FIX 4: TWI interrupts since the last 1 s tick (saturating) */

/* ------------------------------------------------------------------ TCB one-shots
 * DECISION 3: the spec says "TCB" for both the 5 ms transaction timeout and the 4 ms
 * debounce.  Both can be pending at once (click during a read), so two timers are
 * needed; the 1616 has TCB0 and TCB1 (DS 21, vectors 13/14).  TCB0 = transaction,
 * TCB1 = debounce.  Periodic-interrupt mode used as a one-shot: stop in the ISR. */
static inline void tcb_start(TCB_t *t)
{
    t->CTRLA = 0;
    t->CNT = 0;
    t->INTFLAGS = TCB_CAPT_bm;
    t->CTRLA = TCB_CLKSEL_CLKDIV1_gc | TCB_ENABLE_bm;
}

static inline void tcb_stop(TCB_t *t)
{
    t->CTRLA = 0;
    t->INTFLAGS = TCB_CAPT_bm;
}

/* ------------------------------------------------------------------ ADC */
static uint16_t adc_read(uint8_t muxpos)
{
    ADC0.MUXPOS = muxpos;
    ADC0.INTFLAGS = ADC_RESRDY_bm; /* FIX 1: drop a result left over from a timed-out
                                      conversion (write-1 clears, DS 30.5.11) */
    ADC0.COMMAND = ADC_STCONV_bm;
    /* Bounded poll (R): INITDLY+SAMPLEN+13 cycles worst case = 32+33+13 = 78 CLK_ADC
     * = 94 us = 312 CPU cycles; the loop is >= 5 cycles/iteration, 255 iterations is
     * > 1275 cycles.  On time-out return 0 -> T < 64 -> the host rejects the frame. */
    uint8_t guard = 255;
    while (!(ADC0.INTFLAGS & ADC_RESRDY_bm)) {
        if (--guard == 0) {
            adc_fail = 1; /* FIX 1 */
            return 0;
        }
    }
    return ADC0.RES; /* reading RES clears RESRDY (DS 30.3.2.3; errata 2.4.5: on RESH) */
}

static uint16_t adc_t, adc_x, adc_y;

/* Power the stick, measure T/X/Y against VDD, power off.  Called with interrupts off. */
static void stick_measure(void)
{
    adc_fail = 0;
    PORTB.OUTSET = STICK_PWR_bm;     /* PB4 and PB5 in one write (spec) */
    ADC0.CTRLA = ADC_ENABLE_bm;      /* 10 bit, single conversion.  DECISION 4: ADC is
                                        enabled only around a measurement */
    _delay_us(50);                   /* spec: 50 us settle */
    adc_t = adc_read(ADC_MUXPOS_AIN8_gc); /* PB5 = AIN8: the supply pin itself (R2 = 0, no sense wire) */
    adc_x = adc_read(ADC_MUXPOS_AIN5_gc); /* PA5 = AIN5 */
    adc_y = adc_read(ADC_MUXPOS_AIN7_gc); /* PA7 = AIN7 */
    PORTB.OUTCLR = STICK_PWR_bm;
    ADC0.CTRLA = 0;
    /* FIX 1: spec v7 "ADC failure -> T = 0".  The draft zeroed only the channel that
     * timed out, so a failed X or Y went out as a valid frame with X/Y = 0 (full
     * deflection) and, via the stale RESRDY, the next channel got the wrong result. */
    if (adc_fail) {
        adc_t = 0;
    }
    adc_t &= 0x3FF; /* keep the two spare frame bits 0 whatever RES returns */
    adc_x &= 0x3FF;
    adc_y &= 0x3FF;
}

/* ------------------------------------------------------------------ TWI client */
static void twi_init(void)
{
    /* FIX 2: clear DIF/APIF the way DS 26.5.11 documents (writing SCMD), while the
     * client is still enabled.  The draft relied on "disable" and on write-1-to-clear,
     * neither of which the DS states for DIF/APIF.  If a flag survived, the handler
     * would re-enter for ever (COLL path) or re-run as a phantom address match every
     * 5 ms (time-out path), with SCL held low and the watchdog still being kicked.
     * NACK so that nothing is acknowledged on the way out. */
    TWI0.SCTRLB = TWI_ACKACT_NACK_gc | TWI_SCMD_COMPTRANS_gc;
    TWI0.SCTRLA = 0;
    TWI0.SSTATUS = TWI_DIF_bm | TWI_APIF_bm | TWI_COLL_bm | TWI_BUSERR_bm; /* belt and braces */
    PORTB.OUTCLR = PIN0_bm | PIN1_bm; /* FIX 5: as megaTinyCore TWI0_ClearPins() (twi_pins.c:145) */
    TWI0.SADDR = POD_ADDR << 1; /* ADDR[7:1]; bit0 = 0: no general call (DS 26.5.12) */
    TWI0.SADDRMASK = 0;
    TWI0.SCTRLA = TWI_SCTRLA_RUN;
}

static inline void txn_end(void)
{
    tcb_stop(&TCB0);
    txn_active = 0;
}

static void frame_build(void)
{
    /* Layout is NOT fully given by the spec text; taken from proto_model_v5.py
     * Pod.frame(): packed = T<<20 | X<<10 | Y, big-endian, top two bits 0. */
    seq++;
    frame[0] = FRAME_MAGIC;
    frame[1] = (uint8_t)(FRAME_VERSION << 6) | (uint8_t)(reset_cause << 4) | (btn_down ? 1 : 0);
    frame[2] = boot_id;
    frame[3] = (uint8_t)(press_cnt << 4) | release_cnt;
    frame[4] = seq;
    frame[5] = (uint8_t)(adc_t >> 4);                               /* T9..T4            */
    frame[6] = (uint8_t)((adc_t << 4) | (adc_x >> 6));              /* T3..T0 X9..X6     */
    frame[7] = (uint8_t)((adc_x << 2) | (adc_y >> 8));              /* X5..X0 Y9..Y8     */
    frame[8] = (uint8_t)adc_y;                                      /* Y7..Y0            */
    tx_idx = 0;
    tx_crc = 0xFFFF;
}

ISR(TWI0_TWIS_vect)
{
    uint8_t s = TWI0.SSTATUS;

    if (twi_irq_cnt != 0xFFFF) { /* FIX 4 */
        twi_irq_cnt++;
    }

    if (s & TWI_COLL_bm) {
        /* spec v7: COLL -> clear the flag and re-initialise; BUSERR is not handled
         * (cannot be set with the TWI master disabled, DS 26.5.11). */
        twi_init();
        txn_end();
        return;
    }

    if (s & TWI_APIF_bm) {
        if (s & TWI_AP_bm) {
            /* Address match.  SCL is held low by hardware while APIF is set
             * (DS 26.3.2.3), independent of what the CPU/ADC does meanwhile. */
            tcb_start(&TCB0); /* 5 ms from address match */
            txn_active = 1;
            if (s & TWI_DIR_bm) { /* host reads */
                stick_measure();
                frame_build();
            }
            /* (the poll in adc_read() is bounded: worst case 3 x ~0.7 ms of stretch) */
            /* ACK the address.  Read: followed by a data interrupt (DS table 26-3). */
            TWI0.SCTRLB = TWI_ACKACT_ACK_gc | TWI_SCMD_RESPONSE_gc;
        } else {
            /* STOP.  Writing SCMD clears APIF (DS 26.5.11, DIF method 2). */
            TWI0.SCTRLB = TWI_SCMD_COMPTRANS_gc;
            txn_end();
        }
        return;
    }

    if (s & TWI_DIF_bm) {
        if (s & TWI_DIR_bm) {
            /* Host reads.  RXACK is only meaningful after we have sent a byte: on the
             * first DIF after the address it still holds the NACK that ended the
             * previous read (R; DS 26.5.11 "most recent Acknowledge bit from the master"). */
            if (tx_idx != 0 && (s & TWI_RXACK_bm)) {
                TWI0.SCTRLB = TWI_SCMD_COMPTRANS_gc; /* spec: COMPTRANS after host NACK */
                return;
            }
            uint8_t b;
            if (tx_idx < 9) {
                b = frame[tx_idx];
            } else if (tx_idx == 9) {
                b = (uint8_t)(tx_crc >> 8); /* CRC high byte first (model) */
            } else if (tx_idx == 10) {
                b = (uint8_t)tx_crc;
            } else {
                b = 0xFF; /* spec: beyond 11 bytes */
            }
            TWI0.SDATA = b;
            /* DS is ambiguous whether the SDATA write alone restarts the bus with
             * SMEN = 0 (26.5.11 says it clears DIF; 26.5.9 SMEN says "the slave always
             * waits for a new slave command").  Issue RESPONSE as table 26-3 says. (R) */
            TWI0.SCTRLB = TWI_ACKACT_ACK_gc | TWI_SCMD_RESPONSE_gc;
            /* CRC is folded in while the byte is on the wire (spec: "compute during
             * transmission"), i.e. outside the clock stretch. */
            if (tx_idx < 9) {
                tx_crc = _crc_xmodem_update(tx_crc, b); /* poly 0x1021, MSB first */
            }
            if (tx_idx != 255) {
                tx_idx++;
            }
        } else {
            /* Host writes: ACK and discard (spec). */
            (void)TWI0.SDATA;
            TWI0.SCTRLB = TWI_ACKACT_ACK_gc | TWI_SCMD_RESPONSE_gc;
        }
    }
}

/* 5 ms after an address match with no STOP: let go of the bus (spec). */
ISR(TCB0_INT_vect)
{
    twi_init(); /* disable -> enable */
    txn_end();
}

/* ------------------------------------------------------------------ click */
static void sw_debounce_start(void)
{
    PORTA.PIN6CTRL = SW_QUIET; /* keep pull-up, stop further edge interrupts */
    VPORTA.INTFLAGS = SW_bm;
    tcb_start(&TCB1);
    deb_active = 1;
}

/* Go to the "released, waiting for an edge" configuration without losing an edge
 * that happened while the interrupt was masked. */
static void sw_arm_released(void)
{
    VPORTA.INTFLAGS = SW_bm;
    PORTA.PIN6CTRL = SW_ARMED;
    if (!(VPORTA.IN & SW_bm)) { /* already low again: treat as an edge */
        sw_debounce_start();
    }
}

ISR(PORTA_PORT_vect)
{
    VPORTA.INTFLAGS = 0xFF;
    /* Edges only mean something in the armed state.  DS 16.3.3 warns that re-enabling
     * a disabled input can raise a stale interrupt - ignore those here. */
    if (!btn_down && !deb_active) {
        sw_debounce_start();
    }
}

/* 4 ms after the first edge: read again. */
ISR(TCB1_INT_vect)
{
    tcb_stop(&TCB1);
    deb_active = 0;
    if (btn_down) {
        return; /* cannot happen: debounce only runs from the released state */
    }
    if (!(VPORTA.IN & SW_bm)) {
        /* DECISION 5: "matches" = level after 4 ms differs from the committed state. */
        btn_down = 1;
        press_cnt = (press_cnt + 1) & 0x0F;
        PORTA.PIN6CTRL = SW_OFF; /* pull-up off AND buffer off while held (spec) */
    } else {
        sw_arm_released(); /* bounce / glitch: nothing counted */
    }
}

/* ------------------------------------------------------------------ PIT: 31.25 ms */
static uint8_t health_ok(void)
{
    /* DECISION 6: the spec says "TWI address, control register and port settings"
     * without a list.  Checked here: everything that is constant after init. */
    if (TWI0.SADDR != (POD_ADDR << 1)) return 0;
    if (TWI0.SCTRLA != TWI_SCTRLA_RUN) return 0;
    if (TWI0.MCTRLA != 0) return 0;
    if ((PORTB.DIR & (STICK_PWR_bm | PIN0_bm | PIN1_bm)) != STICK_PWR_bm) return 0;
    if (PORTA.DIR != 0) return 0;
    if (PORTA.PIN4CTRL != PORT_ISC_INPUT_DISABLE_gc) return 0;
    if (PORTA.PIN5CTRL != PORT_ISC_INPUT_DISABLE_gc) return 0;
    if (PORTA.PIN7CTRL != PORT_ISC_INPUT_DISABLE_gc) return 0;
    if (PORTB.PIN0CTRL != 0 || PORTB.PIN1CTRL != 0) return 0;
    uint8_t sw = PORTA.PIN6CTRL;
    if (btn_down ? (sw != SW_OFF) : (sw != (deb_active ? SW_QUIET : SW_ARMED))) return 0;
    if (ADC0.CTRLC != ADC_CTRLC_RUN) return 0;
    if (RTC.PITCTRLA != PIT_CTRLA_RUN) return 0;
    if (RTC.CLKSEL != PIT_CLKSEL_RUN) return 0;
    if (!(RTC.CTRLA & RTC_RTCEN_bm)) return 0;
    if (RTC.PITINTCTRL != RTC_PI_bm) return 0;
    if (CLKCTRL.MCLKCTRLB != (CLKCTRL_PDIV_6X_gc | CLKCTRL_PEN_bm)) return 0;
    /* FIX 3: states that drain the battery without stopping the PIT.  Interrupts are
     * off here, so every one of these is in its resting state unless something broke. */
    if (PORTB.OUT & (STICK_PWR_bm | PIN0_bm | PIN1_bm)) return 0; /* stick left powered (~1.5 mA) */
    if (ADC0.CTRLA != 0) return 0;                                /* ADC left enabled */
    if (ADC0.CTRLD != ADC_INITDLY_DLY16_gc || ADC0.SAMPCTRL != 0 || ADC0.CTRLB != 0) return 0;
    if (PORTMUX.CTRLB & PORTMUX_TWI0_bm) return 0;
    if (CPUINT.CTRLA != 0 || CPUINT.LVL1VEC != 0 || CPUINT.LVL0PRI != 0) return 0;
    /* The one-shots: "pending" must mean "timer really running with its interrupt on",
     * otherwise main() stays in Idle (~0.5 mA) for ever.  CCMP is deliberately NOT read
     * back: errata 2.8.2 - reading CCMPH clears CAPT, which would lose a time-out. */
    if (TCB0.CTRLB != TCB_CNTMODE_INT_gc || TCB0.INTCTRL != TCB_CAPT_bm) return 0;
    if (TCB1.CTRLB != TCB_CNTMODE_INT_gc || TCB1.INTCTRL != TCB_CAPT_bm) return 0;
    if (TCB0.CTRLA != (txn_active ? (TCB_CLKSEL_CLKDIV1_gc | TCB_ENABLE_bm) : 0)) return 0;
    if (TCB1.CTRLA != (deb_active ? (TCB_CLKSEL_CLKDIV1_gc | TCB_ENABLE_bm) : 0)) return 0;
    /* FIX 4: a TWI flag the handler cannot clear re-enters it ~20 000 times a second,
     * and the PIT (vector 7) still gets in ahead of TWI (vector 24), so without this
     * the watchdog would be kicked for ever.  Normal maximum: 100 reads/s x 14
     * interrupts = 1400/s. */
    if (twi_irq_cnt > 6000) return 0;
    return 1;
}

ISR(RTC_PIT_vect)
{
    RTC.PITINTFLAGS = RTC_PI_bm;

    if (btn_down) {
        /* strobe: pull-up + buffer on, 20 us, read, both off (spec) */
        PORTA.PIN6CTRL = SW_QUIET;
        _delay_us(20);
        if (VPORTA.IN & SW_bm) {
            btn_down = 0;
            release_cnt = (release_cnt + 1) & 0x0F;
            sw_arm_released(); /* spec: restore pull-up and interrupt */
        } else {
            PORTA.PIN6CTRL = SW_OFF;
        }
    }

    if (++pit_div >= 32) { /* 1 s */
        pit_div = 0;
        if (health_ok()) {
            wdt_reset();
        }
        twi_irq_cnt = 0;
        /* else: no kick -> watchdog reset within 8 s (spec gives no other action) */
    }
}

/* ------------------------------------------------------------------ boot */
static void pins_init(void)
{
    /* PA0 = UPDI: left alone (DS 16.3.1 "pins used to connect a debugger may be
     * configured differently").  PA2 handled by the click code.
     * PB0/PB1 = TWI: input buffer must stay ON, no internal pull-up (external 6.8k). */
    PORTA.PIN1CTRL = PORT_ISC_INPUT_DISABLE_gc; /* reserved */
    PORTA.PIN3CTRL = PORT_ISC_INPUT_DISABLE_gc;
    PORTA.PIN4CTRL = PORT_ISC_INPUT_DISABLE_gc; /* unused in the in-case build */
    PORTA.PIN5CTRL = PORT_ISC_INPUT_DISABLE_gc; /* AIN5 */
    PORTA.PIN2CTRL = PORT_ISC_INPUT_DISABLE_gc; /* unused in the in-case build */
    PORTA.PIN7CTRL = PORT_ISC_INPUT_DISABLE_gc; /* AIN7 */
    PORTB.PIN2CTRL = PORT_ISC_INPUT_DISABLE_gc;
    PORTB.PIN3CTRL = PORT_ISC_INPUT_DISABLE_gc;
    PORTB.PIN4CTRL = PORT_ISC_INPUT_DISABLE_gc; /* outputs: buffer not needed */
    PORTB.PIN5CTRL = PORT_ISC_INPUT_DISABLE_gc;
    PORTC.PIN0CTRL = PORT_ISC_INPUT_DISABLE_gc;
    PORTC.PIN1CTRL = PORT_ISC_INPUT_DISABLE_gc;
    PORTC.PIN2CTRL = PORT_ISC_INPUT_DISABLE_gc;
    PORTC.PIN3CTRL = PORT_ISC_INPUT_DISABLE_gc;
    /* G: PB6, PB7, PC4, PC5 are not bonded out on the 20-pin part; written anyway. */
    PORTB.PIN6CTRL = PORT_ISC_INPUT_DISABLE_gc;
    PORTB.PIN7CTRL = PORT_ISC_INPUT_DISABLE_gc;
    PORTC.PIN4CTRL = PORT_ISC_INPUT_DISABLE_gc;
    PORTC.PIN5CTRL = PORT_ISC_INPUT_DISABLE_gc;

    PORTB.OUTCLR = STICK_PWR_bm;
    PORTB.DIRSET = STICK_PWR_bm; /* DIR written once (spec) */
}

static void adc_init(void)
{
    ADC0.CTRLA = 0;
    ADC0.CTRLB = 0;                       /* no accumulation */
    ADC0.CTRLC = ADC_CTRLC_RUN;           /* VDD ref, CLK_PER/4, SAMPCAP=1 (DECISION 7) */
    ADC0.CTRLD = ADC_INITDLY_DLY16_gc;    /* spec; SAMPDLY=0, ASDV=0 */
    ADC0.SAMPCTRL = 0;
    VREF.CTRLA = 0;
}

/* Low bits of the temperature sensor, DS 30.3.2.6 recipe: 1.1 V reference,
 * INITDLY >= 32 us * 833 kHz = 26.7 -> DLY32, SAMPLEN >= 26.7 -> 31, SAMPCAP = 1.
 * (errata 2.4.1: SAMPDLY/ASDV must be 0 when SAMPLEN > 0 - they are.) */
static uint16_t temp_noise(void)
{
    uint16_t h = 0xFFFF;
    VREF.CTRLA = VREF_ADC0REFSEL_1V1_gc;
    ADC0.CTRLC = ADC_SAMPCAP_bm | ADC_REFSEL_INTREF_gc | ADC_PRESC_DIV4_gc;
    ADC0.CTRLD = ADC_INITDLY_DLY32_gc;
    ADC0.SAMPCTRL = 31;
    ADC0.CTRLA = ADC_ENABLE_bm;
    for (uint8_t i = 0; i < 8; i++) { /* DECISION 8: 8 samples, spec says only "low bits" */
        h = _crc_xmodem_update(h, (uint8_t)adc_read(ADC_MUXPOS_TEMPSENSE_gc));
    }
    ADC0.CTRLA = 0;
    adc_init(); /* spec: back to VDD reference / normal settings before TWI is enabled */
    return h;
}

static void boot_id_update(uint8_t rstfr)
{
    uint8_t id = boot_id + 1; /* +1 on every start; garbage + 1 after power loss */
    if (rstfr & RSTCTRL_PORF_bm) {
        /* DECISION 8: the spec does not define the mixing function. */
        uint16_t h = temp_noise();
        stick_measure(); /* does not advance seq (model: seq starts at 0 per boot) */
        h = _crc_xmodem_update(h, (uint8_t)adc_t);
        h = _crc_xmodem_update(h, (uint8_t)adc_x);
        h = _crc_xmodem_update(h, (uint8_t)adc_y);
        h = _crc_xmodem_update(h, (uint8_t)((adc_t >> 8) | ((adc_x >> 8) << 2) | ((adc_y >> 8) << 4)));
        id += (uint8_t)h ^ (uint8_t)(h >> 8);
    }
    boot_id = id;
}

static void rtc_init(void)
{
    /* DS 23.4.1.2 note: the RTC is used during start-up, wait for the busy flags. */
    while (RTC.STATUS != 0) {
    }
    RTC.CLKSEL = PIT_CLKSEL_RUN;
    RTC.CTRLA = RTC_RTCEN_bm; /* written exactly once (spec; errata 2.6.1 / 2.6.2) */
    while (RTC.PITSTATUS & RTC_CTRLBUSY_bm) {
    }
    RTC.PITINTCTRL = RTC_PI_bm;
    RTC.PITCTRLA = PIT_CTRLA_RUN; /* PITEN never cleared afterwards */
}

static void click_init(void)
{
    /* spec: only read the present state, do not count. */
    PORTA.PIN6CTRL = SW_QUIET;
    _delay_us(50); /* pull-up 20..50 k (DS table 36-16) into a few tens of pF */
    if (!(VPORTA.IN & SW_bm)) {
        btn_down = 1;
        PORTA.PIN6CTRL = SW_OFF;
    } else {
        btn_down = 0;
        sw_arm_released();
    }
}

int main(void)
{
    /* Reset cause: read, then clear by writing the same bits back (DS 12.5.1). */
    uint8_t rstfr = RSTCTRL.RSTFR;
    RSTCTRL.RSTFR = rstfr;
    if (rstfr & RSTCTRL_PORF_bm) {
        reset_cause = 0;
    } else if (rstfr & RSTCTRL_BORF_bm) {
        reset_cause = 1; /* DECISION 9: BOD before WDT when both are set */
    } else if (rstfr & RSTCTRL_WDRF_bm) {
        reset_cause = 2;
    } else {
        reset_cause = 3;
    }

    /* Clock: nothing to do, 20 MHz / 6 is the reset default. */

    pins_init();
    adc_init();
    boot_id_update(rstfr);

    TCB0.CTRLB = TCB_CNTMODE_INT_gc;
    TCB0.CCMP = TCB_TOP_5MS;
    TCB0.INTCTRL = TCB_CAPT_bm;
    TCB1.CTRLB = TCB_CNTMODE_INT_gc;
    TCB1.CCMP = TCB_TOP_4MS;
    TCB1.INTCTRL = TCB_CAPT_bm;

    rtc_init();
    click_init();
    twi_init();
    wdt_reset();
    sei();

    for (;;) {
        cli();
        /* spec: Power-Down only when no TCB timing is pending (TCB halts in
         * Power-Down, DS 21.3.6); otherwise Idle. */
        if (txn_active || deb_active) {
            SLPCTRL.CTRLA = SLPCTRL_SMODE_IDLE_gc | SLPCTRL_SEN_bm;
        } else {
            SLPCTRL.CTRLA = SLPCTRL_SMODE_PDOWN_gc | SLPCTRL_SEN_bm;
        }
        sei(); /* the instruction after SEI runs before any pending interrupt (R) */
        sleep_cpu();
    }
}
