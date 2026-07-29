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

// Declared before provenance so an explicit preview build names itself
// accurately in boot/status and derived-record provenance.
#ifndef OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
#define OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW 0
#endif

// Firmware provenance. Scripted builds may override these with -D flags; keep
// defaults stable so Arduino IDE builds remain deterministic.
#ifndef OTIS_FIRMWARE_NAME
#define OTIS_FIRMWARE_NAME "otis_nano_rp2040_connect"
#endif

#ifndef OTIS_FIRMWARE_VERSION
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
#define OTIS_FIRMWARE_VERSION "SW2_PHASE4_OBSERVE_PREVIEW"
#else
#define OTIS_FIRMWARE_VERSION "SW1"
#endif
#endif

// Literal experiment configuration identity for IDE-built firmware. Change
// this whenever the header-defined run configuration changes.
#ifndef OTIS_FIRMWARE_CONFIG_ID
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
#define OTIS_FIRMWARE_CONFIG_ID "phase4_observe_preview_v1"
#else
#define OTIS_FIRMWARE_CONFIG_ID "phase5_pps_gated_qualification_v1"
#endif
#endif

#ifndef OTIS_FIRMWARE_GIT_COMMIT
#define OTIS_FIRMWARE_GIT_COMMIT "1095a16dc0c4e6f9ce875032fbe64209c2832b41"
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

// TCXO observation backends. FC0/GPIN0 is the simple RP2040 clock-counter path;
// H1 long-gate PIO is the raw-edge metrology path for resolving sub-Hz VCOCXO
// DAC response; GPIO IRQ is only for deliberately divided, interrupt-safe test
// signals. PPS-gated ratio is a raw count-observation backend that uses PPS
// edges to bound the oscillator count window and leaves ratio/frequency
// derivation to host tooling.
#define OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0 1
#define OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ 2
#define OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE 3
#define OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO 4

#ifndef OTIS_TCXO_COUNTER_BACKEND
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
#define OTIS_TCXO_COUNTER_BACKEND OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
#else
#define OTIS_TCXO_COUNTER_BACKEND OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0
#endif
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

// Temporary H1 diagnostic scaffolding: when enabled, D10 is tied to the same
// physical PPS signal as D14 and observed as an independent rising-edge witness.
// It must remain disabled for normal generic-event or loopback work.
#ifndef OTIS_ENABLE_PPS_DUAL_OBSERVER
#define OTIS_ENABLE_PPS_DUAL_OBSERVER 1
#endif

#ifndef OTIS_PPS_DUAL_OBSERVER_SHORT_INTERVAL_TICKS
#define OTIS_PPS_DUAL_OBSERVER_SHORT_INTERVAL_TICKS 8000000ull
#endif

#ifndef OTIS_PPS_DUAL_OBSERVER_LONG_INTERVAL_TICKS
#define OTIS_PPS_DUAL_OBSERVER_LONG_INTERVAL_TICKS 19200000ull
#endif

#ifndef OTIS_PPS_DUAL_OBSERVER_BURST_SHORT_THRESHOLD
#define OTIS_PPS_DUAL_OBSERVER_BURST_SHORT_THRESHOLD 4u
#endif

#ifndef OTIS_PPS_DUAL_OBSERVER_BUFFER_SIZE
#define OTIS_PPS_DUAL_OBSERVER_BUFFER_SIZE 16u
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
#define OTIS_TCXO_GATE_PERIOD_US 10000000u
#endif

// FC0/GPIN0 publishes one CNT observation per gate period. The FC0 hardware
// helper itself is sampled at OTIS_TCXO_MEASURE_PERIOD_MS inside that span, so
// H1 long-gate captures should use a gate much longer than the sample cadence.
#ifndef OTIS_TCXO_MEASURE_PERIOD_MS
#define OTIS_TCXO_MEASURE_PERIOD_MS 1000u
#endif

// H1 slope-metrology long gate. A 300 s raw-edge gate gives about 0.0033 Hz
// edge quantization at 10 MHz and still stays below a 32-bit PIO edge counter.
#ifndef OTIS_H1_LONG_GATE_PERIOD_US
#define OTIS_H1_LONG_GATE_PERIOD_US 300000000u
#endif

#ifndef OTIS_PPS_GATE_MIN_INTERVAL_US
#define OTIS_PPS_GATE_MIN_INTERVAL_US 800000u
#endif

#ifndef OTIS_PPS_GATE_DUPLICATE_MAX_INTERVAL_US
#define OTIS_PPS_GATE_DUPLICATE_MAX_INTERVAL_US 100000u
#endif

#ifndef OTIS_PPS_GATE_MAX_INTERVAL_US
#define OTIS_PPS_GATE_MAX_INTERVAL_US 1200000u
#endif

#ifndef OTIS_PPS_GATE_MISSING_TIMEOUT_US
#define OTIS_PPS_GATE_MISSING_TIMEOUT_US 2500000u
#endif

#if OTIS_PPS_GATE_MIN_INTERVAL_US == 0u || \
    OTIS_PPS_GATE_MIN_INTERVAL_US > OTIS_PPS_GATE_MAX_INTERVAL_US
#error "PPS gate interval limits must be nonzero and ordered."
#endif

#if OTIS_PPS_GATE_DUPLICATE_MAX_INTERVAL_US == 0u || \
    OTIS_PPS_GATE_DUPLICATE_MAX_INTERVAL_US >= OTIS_PPS_GATE_MIN_INTERVAL_US
#error "PPS duplicate threshold must be nonzero and below the minimum accepted interval."
#endif

#if OTIS_PPS_GATE_MISSING_TIMEOUT_US <= OTIS_PPS_GATE_MAX_INTERVAL_US
#error "PPS missing timeout must exceed the maximum accepted interval."
#endif

// SW2 architectural guardrail: FC0 observations remain visible during startup,
// but they are not eligible for future control/acquire logic until this inhibit
// window has elapsed and enough clean windows have followed it.
#ifndef OTIS_FC0_STARTUP_INHIBIT_MS
#define OTIS_FC0_STARTUP_INHIBIT_MS 600000u
#endif

#ifndef OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS
#define OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS 3u
#endif

// Phase 4 live discipline is an explicitly selected observe-only build.  It
// emits EST/CTL preview telemetry but has no actuation callback and never
// includes the DAC driver.  Manual DAC/sweep ownership remains in the sketch's
// command path.
#ifndef OTIS_PHASE4_PREVIEW_QUEUE_DEPTH
#define OTIS_PHASE4_PREVIEW_QUEUE_DEPTH 4u
#endif

#ifndef OTIS_PHASE4_ESTIMATOR_WINDOW
#define OTIS_PHASE4_ESTIMATOR_WINDOW 5u
#endif

#ifndef OTIS_PHASE4_MINIMUM_ESTIMATOR_SAMPLES
#define OTIS_PHASE4_MINIMUM_ESTIMATOR_SAMPLES 3u
#endif

#ifndef OTIS_PHASE4_RECOVERY_CLEAN_WINDOWS
#define OTIS_PHASE4_RECOVERY_CLEAN_WINDOWS 3u
#endif

#ifndef OTIS_PHASE4_REFERENCE_MAX_AGE_US
#define OTIS_PHASE4_REFERENCE_MAX_AGE_US 1500000u
#endif

#ifndef OTIS_PHASE4_COUNT_MAX_AGE_US
#define OTIS_PHASE4_COUNT_MAX_AGE_US 450000000u
#endif

#ifndef OTIS_PHASE4_MAXIMUM_DISPERSION_HZ
#define OTIS_PHASE4_MAXIMUM_DISPERSION_HZ 0.25
#endif

// H1 open-loop lab instrument DAC support. This is deliberately opt-in and
// operator-initiated; firmware never steers the oscillator from PPS/count
// telemetry.
#ifndef OTIS_ENABLE_DAC_AD5693R
#define OTIS_ENABLE_DAC_AD5693R 0
#endif

#ifndef OTIS_DAC_AD5693R_I2C_ADDRESS
#define OTIS_DAC_AD5693R_I2C_ADDRESS 0x4Cu
#endif

// run_020 IDE-native H1 crossing-characterization envelope. These values live
// in this header deliberately: the Arduino IDE is the required compile/upload
// path, and this run must not depend on command-line -D overrides. The midpoint
// of 0x6000..0xFC00 is 0xAE00, the run_019 broad-fit crossing region. The prior
// code/voltage fit predicts about 0.936..2.450 V across this envelope, within
// the CX317 0..3.3 V operating Vc range. These clamps bound manual commands and
// explicitly started open-loop sweeps; they do not auto-start a sweep, enable
// feedback steering, or authorize SW2 control.
#ifndef OTIS_DAC_MIN_CODE
#define OTIS_DAC_MIN_CODE 0x6000u
#endif

#ifndef OTIS_DAC_MAX_CODE
#define OTIS_DAC_MAX_CODE 0xFC00u
#endif

// Optional low-rate environmental telemetry for oscillator characterization.
// SHT4x is the preferred near-VCOCXO temperature source; BMP280 is primarily
// pressure context and secondary temperature.
#ifndef OTIS_ENABLE_ENV_SENSORS
#define OTIS_ENABLE_ENV_SENSORS 0
#endif

#ifndef OTIS_ENABLE_ENV_SHT4X
#define OTIS_ENABLE_ENV_SHT4X OTIS_ENABLE_ENV_SENSORS
#endif

#ifndef OTIS_ENABLE_ENV_BMP280
#define OTIS_ENABLE_ENV_BMP280 OTIS_ENABLE_ENV_SENSORS
#endif

#ifndef OTIS_ENV_SAMPLE_PERIOD_MS
#define OTIS_ENV_SAMPLE_PERIOD_MS 1000u
#endif

#ifndef OTIS_ENV_SHT4X_I2C_ADDRESS
#define OTIS_ENV_SHT4X_I2C_ADDRESS 0x44u
#endif

#ifndef OTIS_ENV_BMP280_I2C_ADDRESS
#define OTIS_ENV_BMP280_I2C_ADDRESS 0x77u
#endif

// Deterministic H1 open-loop DAC sweep support. This is lab automation only:
// sweeps never start on boot and never steer from count/frequency telemetry.
#ifndef OTIS_ENABLE_H1_DAC_SWEEP
#define OTIS_ENABLE_H1_DAC_SWEEP 0
#endif

#ifndef OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS
#define OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS 2400000u
#endif

#ifndef OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS
#define OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS 2400000u
#endif

#ifndef OTIS_H1_DAC_SWEEP_TINY_STEP_CODES
#define OTIS_H1_DAC_SWEEP_TINY_STEP_CODES 0x0300u
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
    OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ && \
    OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE && \
    OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
#error "OTIS_TCXO_COUNTER_BACKEND must be FC0_GPIN0, GPIO_IRQ, PIO_LONG_GATE, or PPS_GATED_RATIO."
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

#if OTIS_ENV_SHT4X_I2C_ADDRESS != 0x44u && \
    OTIS_ENV_SHT4X_I2C_ADDRESS != 0x45u && \
    OTIS_ENV_SHT4X_I2C_ADDRESS != 0x46u
#error "OTIS_ENV_SHT4X_I2C_ADDRESS must be 0x44, 0x45, or 0x46."
#endif

#if OTIS_ENV_BMP280_I2C_ADDRESS != 0x76u && \
    OTIS_ENV_BMP280_I2C_ADDRESS != 0x77u
#error "OTIS_ENV_BMP280_I2C_ADDRESS must be 0x76 or 0x77."
#endif

#if OTIS_ENV_SAMPLE_PERIOD_MS < 100u
#error "OTIS_ENV_SAMPLE_PERIOD_MS must be at least 100 ms."
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

#if OTIS_H1_LONG_GATE_PERIOD_US < 1000000u || \
    OTIS_H1_LONG_GATE_PERIOD_US > 400000000u
#error "OTIS_H1_LONG_GATE_PERIOD_US must be between 1 s and 400 s."
#endif

#if OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS < 2u * (OTIS_H1_LONG_GATE_PERIOD_US / 1000u)
#error "OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS must allow at least two long gates per dwell."
#endif

#if OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS < 1u
#error "OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS must be at least 1."
#endif

#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW != 0 && \
    OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW != 1
#error "OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW must be 0 or 1."
#endif

#if OTIS_PHASE4_PREVIEW_QUEUE_DEPTH < 2u || \
    OTIS_PHASE4_PREVIEW_QUEUE_DEPTH > 8u
#error "OTIS_PHASE4_PREVIEW_QUEUE_DEPTH must be between 2 and 8."
#endif

#if OTIS_PHASE4_ESTIMATOR_WINDOW < 3u || \
    OTIS_PHASE4_ESTIMATOR_WINDOW > 8u
#error "OTIS_PHASE4_ESTIMATOR_WINDOW must be between 3 and 8."
#endif

#if OTIS_PHASE4_MINIMUM_ESTIMATOR_SAMPLES < 1u || \
    OTIS_PHASE4_MINIMUM_ESTIMATOR_SAMPLES > OTIS_PHASE4_ESTIMATOR_WINDOW
#error "OTIS_PHASE4_MINIMUM_ESTIMATOR_SAMPLES must fit the estimator window."
#endif

#if OTIS_PHASE4_RECOVERY_CLEAN_WINDOWS < 1u
#error "OTIS_PHASE4_RECOVERY_CLEAN_WINDOWS must be at least 1."
#endif

#if OTIS_CAPTURE_RING_SIZE < 2u || OTIS_CAPTURE_RING_SIZE > 255u
#error "OTIS_CAPTURE_RING_SIZE must be between 2 and 255."
#endif

#if OTIS_SAFE_MODE_FAILURE_THRESHOLD > 255u
#error "OTIS_SAFE_MODE_FAILURE_THRESHOLD must fit in uint8_t."
#endif

#endif
