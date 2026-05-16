#ifndef OTIS_CONFIG_H
#define OTIS_CONFIG_H

// This is the Arduino IDE-friendly configuration surface for the OTIS SW1
// smoke firmware. Protocol constants and board pin contracts live elsewhere.

// SW1 bring-up modes.
#define OTIS_SW1_MODE_SYNTHETIC_USB 1
#define OTIS_SW1_MODE_GPIO_LOOPBACK 2
#define OTIS_SW1_MODE_GPS_PPS 3
#define OTIS_SW1_MODE_TCXO_OBSERVE 4
#define OTIS_SW1_MODE_H1_OCXO_OBSERVE 5

#ifndef OTIS_SW1_BRINGUP_MODE
#define OTIS_SW1_BRINGUP_MODE OTIS_SW1_MODE_H1_OCXO_OBSERVE
#endif

// Firmware provenance. Scripted builds may override these with -D flags; keep
// defaults stable so Arduino IDE builds remain deterministic.
#ifndef OTIS_FIRMWARE_NAME
#define OTIS_FIRMWARE_NAME "otis_nano_rp2040_connect"
#endif

#ifndef OTIS_FIRMWARE_VERSION
#define OTIS_FIRMWARE_VERSION "SW1"
#endif

#ifndef OTIS_FIRMWARE_GIT_COMMIT
#define OTIS_FIRMWARE_GIT_COMMIT "unknown"
#endif

// Edge capture backends. Keep IRQ as the default SW1 path; PIO FIFO is an
// opt-in SW1.5a experiment and still uses CPU-attached timestamps.
//
// Guardrail: the PIO FIFO backend is only for sparse edge streams such as PPS,
// slow GPIO loopback, or future low-rate event inputs. It must not be used to
// enqueue raw 10 MHz / 16 MHz CXO edges. Raw oscillator input on D8 / GPIO20 /
// GPIN0 should use the RP2040 frequency-counter / FC0 / gated-count path.
#define OTIS_CAPTURE_BACKEND_IRQ 1
#define OTIS_CAPTURE_BACKEND_PIO_FIFO 2

#ifndef OTIS_CAPTURE_BACKEND
#define OTIS_CAPTURE_BACKEND OTIS_CAPTURE_BACKEND_IRQ
#endif

#ifndef OTIS_CAPTURE_MODE
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
#define OTIS_CAPTURE_MODE "pio_fifo_cpu_timestamped"
#else
#define OTIS_CAPTURE_MODE "irq_reconstructed"
#endif
#endif

#ifndef OTIS_NOMINAL_CAPTURE_CLOCK_HZ
#define OTIS_NOMINAL_CAPTURE_CLOCK_HZ 16000000u
#endif

#ifndef OTIS_NOMINAL_TCXO_HZ
#define OTIS_NOMINAL_TCXO_HZ 16000000u
#endif

#ifndef OTIS_NOMINAL_OCXO_HZ
#define OTIS_NOMINAL_OCXO_HZ 10000000u
#endif

#ifndef OTIS_NOMINAL_PPS_HZ
#define OTIS_NOMINAL_PPS_HZ 1u
#endif

// TCXO observation backends. FC0/GPIN0 is the intended abstraction for raw
// CXO frequency observation; GPIO IRQ is only for deliberately divided,
// interrupt-safe test signals.
#define OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0 1
#define OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ 2

#ifndef OTIS_TCXO_COUNTER_BACKEND
#define OTIS_TCXO_COUNTER_BACKEND OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
#endif

// Boot and serial behavior.
#ifndef OTIS_BOOT_INITIAL_DELAY_MS
#define OTIS_BOOT_INITIAL_DELAY_MS 1500u
#endif

#ifndef OTIS_SERIAL_BAUD
#define OTIS_SERIAL_BAUD 115200u
#endif

#ifndef OTIS_SERIAL_WAIT_MS
#define OTIS_SERIAL_WAIT_MS 250u
#endif

#ifndef OTIS_SAFE_MODE_FAILURE_THRESHOLD
#define OTIS_SAFE_MODE_FAILURE_THRESHOLD 3u
#endif

// Diagnostics.
#ifndef OTIS_ENABLE_RP2040_BOOT_DIAG
#define OTIS_ENABLE_RP2040_BOOT_DIAG 1
#endif

// Status LED.
#ifndef OTIS_ENABLE_STATUS_LED
#define OTIS_ENABLE_STATUS_LED 0
#endif

#ifndef OTIS_ENABLE_STATUS_LED_BOOT_TEST
#define OTIS_ENABLE_STATUS_LED_BOOT_TEST OTIS_ENABLE_STATUS_LED
#endif

// Runtime sizing and timing.
#ifndef OTIS_CAPTURE_RING_SIZE
#define OTIS_CAPTURE_RING_SIZE 32u
#endif

#ifndef OTIS_STATUS_PERIOD_MS
#define OTIS_STATUS_PERIOD_MS 1000u
#endif

#ifndef OTIS_LOOPBACK_TOGGLE_PERIOD_MS
#define OTIS_LOOPBACK_TOGGLE_PERIOD_MS 250u
#endif

#ifndef OTIS_TCXO_GATE_PERIOD_US
#define OTIS_TCXO_GATE_PERIOD_US 1000000u
#endif

// FC0/GPIN0 publishes one CNT observation per gate period. The FC0 hardware
// helper itself is sampled at OTIS_TCXO_MEASURE_PERIOD_MS inside that span, so
// H1 long-gate captures should use a gate much longer than the sample cadence.
#ifndef OTIS_TCXO_MEASURE_PERIOD_MS
#define OTIS_TCXO_MEASURE_PERIOD_MS 1000u
#endif

// H1 open-loop lab instrument DAC support. This is deliberately opt-in and
// manual-only; firmware never steers the oscillator from PPS/count telemetry.
#ifndef OTIS_ENABLE_DAC_AD5693R
#define OTIS_ENABLE_DAC_AD5693R 1
#endif

#ifndef OTIS_DAC_AD5693R_I2C_ADDRESS
#define OTIS_DAC_AD5693R_I2C_ADDRESS 0x4Cu
#endif

#ifndef OTIS_DAC_MIN_CODE
#define OTIS_DAC_MIN_CODE 0x7000u
#endif

#ifndef OTIS_DAC_MAX_CODE
#define OTIS_DAC_MAX_CODE 0x9000u
#endif

// Deterministic H1 open-loop DAC sweep support. This is lab automation only:
// sweeps never start on boot and never steer from count/frequency telemetry.
#ifndef OTIS_ENABLE_H1_DAC_SWEEP
#define OTIS_ENABLE_H1_DAC_SWEEP 1
#endif

#ifndef OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS
#define OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS 5000u
#endif

#ifndef OTIS_H1_DAC_SWEEP_TINY_STEP_CODES
#define OTIS_H1_DAC_SWEEP_TINY_STEP_CODES 0x0400u
#endif

#ifndef OTIS_H1_DAC_SWEEP_MAX_STEPS
#define OTIS_H1_DAC_SWEEP_MAX_STEPS 16u
#endif

// Boot-hardening test injection. Leave disabled for normal firmware.
#ifndef OTIS_FORCE_BOOT_FAIL_BEFORE_CLOCKS
#define OTIS_FORCE_BOOT_FAIL_BEFORE_CLOCKS 0
#endif

#ifndef OTIS_FORCE_BOOT_FAIL_BEFORE_CAPTURE
#define OTIS_FORCE_BOOT_FAIL_BEFORE_CAPTURE 0
#endif

#ifndef OTIS_FORCE_BOOT_FAIL_BEFORE_RUN_MODE
#define OTIS_FORCE_BOOT_FAIL_BEFORE_RUN_MODE 0
#endif

#if OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0 && \
    OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ
#error "OTIS_TCXO_COUNTER_BACKEND must be FC0_GPIN0 or GPIO_IRQ."
#endif

#if OTIS_CAPTURE_BACKEND != OTIS_CAPTURE_BACKEND_IRQ && \
    OTIS_CAPTURE_BACKEND != OTIS_CAPTURE_BACKEND_PIO_FIFO
#error "OTIS_CAPTURE_BACKEND must be OTIS_CAPTURE_BACKEND_IRQ or OTIS_CAPTURE_BACKEND_PIO_FIFO."
#endif

#if OTIS_SW1_BRINGUP_MODE != OTIS_SW1_MODE_SYNTHETIC_USB && \
    OTIS_SW1_BRINGUP_MODE != OTIS_SW1_MODE_GPIO_LOOPBACK && \
    OTIS_SW1_BRINGUP_MODE != OTIS_SW1_MODE_GPS_PPS && \
    OTIS_SW1_BRINGUP_MODE != OTIS_SW1_MODE_TCXO_OBSERVE && \
    OTIS_SW1_BRINGUP_MODE != OTIS_SW1_MODE_H1_OCXO_OBSERVE
#error "OTIS_SW1_BRINGUP_MODE must be one of the OTIS_SW1_MODE_* constants."
#endif

#if OTIS_DAC_AD5693R_I2C_ADDRESS != 0x4Cu && \
    OTIS_DAC_AD5693R_I2C_ADDRESS != 0x4Eu
#error "OTIS_DAC_AD5693R_I2C_ADDRESS must be 0x4C or 0x4E."
#endif

#if OTIS_DAC_MIN_CODE > OTIS_DAC_MAX_CODE
#error "OTIS_DAC_MIN_CODE must be <= OTIS_DAC_MAX_CODE."
#endif

#if OTIS_DAC_MAX_CODE > 0xFFFFu
#error "OTIS_DAC_MAX_CODE must fit in 16 bits."
#endif

#if OTIS_H1_DAC_SWEEP_MAX_STEPS < 9u || OTIS_H1_DAC_SWEEP_MAX_STEPS > 32u
#error "OTIS_H1_DAC_SWEEP_MAX_STEPS must be between 9 and 32."
#endif

#if OTIS_H1_DAC_SWEEP_TINY_STEP_CODES < 1u
#error "OTIS_H1_DAC_SWEEP_TINY_STEP_CODES must be at least 1."
#endif

#if OTIS_CAPTURE_RING_SIZE < 2u || OTIS_CAPTURE_RING_SIZE > 255u
#error "OTIS_CAPTURE_RING_SIZE must be between 2 and 255."
#endif

#if OTIS_SAFE_MODE_FAILURE_THRESHOLD > 255u
#error "OTIS_SAFE_MODE_FAILURE_THRESHOLD must fit in uint8_t."
#endif

#endif
