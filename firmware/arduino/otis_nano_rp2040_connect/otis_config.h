#ifndef OTIS_CONFIG_H
#define OTIS_CONFIG_H

// This is the Arduino IDE-friendly configuration surface for the OTIS SW1
// smoke firmware. Protocol constants and board pin contracts live elsewhere.

#include "otis_build_profile_config.h"

#ifndef OTIS_MINIMUM_FREE_STACK_BYTES
#define OTIS_MINIMUM_FREE_STACK_BYTES 1024u
#endif

#ifndef OTIS_MINIMUM_FREE_HEAP_BYTES
#define OTIS_MINIMUM_FREE_HEAP_BYTES 65536u
#endif

#if OTIS_MINIMUM_FREE_STACK_BYTES < 256u
#error "OTIS_MINIMUM_FREE_STACK_BYTES must preserve a material live margin."
#endif

#if OTIS_MINIMUM_FREE_HEAP_BYTES < 16384u
#error "OTIS_MINIMUM_FREE_HEAP_BYTES must preserve a material live margin."
#endif

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
#ifndef OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW
#define OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW 0
#endif

#ifndef OTIS_ENABLE_CX317_I_ONLY_PREVIEW
#define OTIS_ENABLE_CX317_I_ONLY_PREVIEW 0
#endif

// CX318 Stage 4 is a separate, non-actionable relative-phase/hybrid preview.
// Its static code is a build-bound preflight fact, never a write request.
#ifndef OTIS_ENABLE_CX318_STAGE4_PREVIEW
#define OTIS_ENABLE_CX318_STAGE4_PREVIEW 0
#endif

// Stage 5 reuses the selected CX318 relative-phase/hybrid preview alongside
// the bounded frequency-only active path.  The preview remains one-way and
// non-actionable; this separate identity prevents relaxing the Stage 4
// no-DAC/no-controller profile.
#ifndef OTIS_ENABLE_CX318_STAGE5_PREVIEW
#define OTIS_ENABLE_CX318_STAGE5_PREVIEW 0
#endif

// Select the stabilized tight-deadband capability. Programme identity and
// authority remain profile/manifest data rather than implementation names.
#ifndef OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW
#define OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW 0
#endif

// CX320 is the first profile in which the selected relative-phase estimate may
// influence the single existing bounded transaction path.  It still uses the
// stabilized integer-count tight band; the separate selector prevents any
// historical CX319 build from gaining phase authority.
#ifndef OTIS_ENABLE_CX320_ACTIVE_HYBRID
#define OTIS_ENABLE_CX320_ACTIVE_HYBRID 0
#endif

// CX321 retains the CX320 natural controller but requires one exact same-run
// 1,500-interval plant-sign identification transaction before natural phase
// authority can exist.
#ifndef OTIS_ENABLE_CX321_ACTIVE_HYBRID
#define OTIS_ENABLE_CX321_ACTIVE_HYBRID 0
#endif

// CX322 runs the unchanged natural hybrid controller directly. Valid response
// classifications are retained as observations rather than sign/magnitude
// admission gates; exact evidence and all physical bounds still fail closed.
#ifndef OTIS_ENABLE_CX322_DIRECT_HYBRID
#define OTIS_ENABLE_CX322_DIRECT_HYBRID 0
#endif

// Descriptive successor programme.  It retains the CX322 natural controller
// and adds one separately accounted reversal challenge inside the same bounded
// transaction and cumulative-movement envelope.
#ifndef OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION
#define OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION 0
#endif

#define OTIS_ENABLE_CX32X_EXACT_ACTIVE_TIMING \
  (OTIS_ENABLE_CX321_ACTIVE_HYBRID || OTIS_ENABLE_CX322_DIRECT_HYBRID || \
   OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION)

#ifndef OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS
#define OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS 4u
#endif

#ifndef OTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE
#define OTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE 0
#endif

// CX319 Part A keeps the selected frequency, relative-phase and hybrid
// engines live while an externally precommitted DAC scan owns every write.
// It has no automatic-control authority and is a distinct identity from the
// sealed static Stage 4 preview and the bounded active profiles.
#ifndef OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW
#define OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW 0
#endif

#ifndef OTIS_CX319_RANGE_MAP_INITIAL_CODE
#define OTIS_CX319_RANGE_MAP_INITIAL_CODE 0u
#endif

#ifndef OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE
#define OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE 0u
#endif

#ifndef OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH
#define OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH 0u
#endif

#define OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW \
  (OTIS_ENABLE_CX318_STAGE5_PREVIEW || OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW)

#define OTIS_ENABLE_TIGHT_DEADBAND_OBSERVATION \
  (OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW || \
   OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW)

#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
#define OTIS_TIGHT_DEADBAND_INITIAL_CODE OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE
#define OTIS_TIGHT_DEADBAND_INITIAL_DAC_EPOCH \
  OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH
#elif OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW
#define OTIS_TIGHT_DEADBAND_INITIAL_CODE OTIS_CX319_RANGE_MAP_INITIAL_CODE
#define OTIS_TIGHT_DEADBAND_INITIAL_DAC_EPOCH 0u
#else
#define OTIS_TIGHT_DEADBAND_INITIAL_CODE 0u
#define OTIS_TIGHT_DEADBAND_INITIAL_DAC_EPOCH 0u
#endif

#define OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW \
  (OTIS_ENABLE_CX318_STAGE4_PREVIEW || \
   OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW || \
   OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW)

#ifndef OTIS_CX318_STAGE4_STATIC_CODE
#define OTIS_CX318_STAGE4_STATIC_CODE 0u
#endif

#ifndef OTIS_CX318_STAGE4_DAC_EPOCH
#define OTIS_CX318_STAGE4_DAC_EPOCH 0u
#endif

// A short-lived, single-purpose profile may establish the operator-authorized
// Stage 4 premise code before the normal Stage 4 image is built.  This is not a
// controller: it admits one exact manual A828 attempt per boot and exposes no
// other DAC write surface.
#ifndef OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP
#define OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP 0
#endif

#ifndef OTIS_CX318_STAGE4_PREMISE_SETUP_CODE
#define OTIS_CX318_STAGE4_PREMISE_SETUP_CODE 0u
#endif

// Stage 6 dedicates Arduino-Pico Core 0 to services/I/O and Core 1 to timing,
// estimation and control preview.  It remains disabled for all legacy and
// single-core profiles.
#ifndef OTIS_ENABLE_DUAL_CORE_PARTITION
#define OTIS_ENABLE_DUAL_CORE_PARTITION 0
#endif

// Bounded active control is structurally available only in the exact Stage 5
// single-core and Stage 7 dual-core programme profiles. Existing/default/
// preview profiles leave this disabled and therefore have no controller-to-DAC
// call path.
#ifndef OTIS_ENABLE_CX317_BOUNDED_ACTIVE
#define OTIS_ENABLE_CX317_BOUNDED_ACTIVE 0
#endif

// Expose the finite Q2 transaction-case command surface only in its exact
// electrically inhibited diagnostic profile. The case engine cannot call the
// physical DAC driver; the separately authorized production setup path remains
// the sole physical write attempted by Q2.
#ifndef OTIS_ENABLE_Q2_TRANSACTION_REHEARSAL
#define OTIS_ENABLE_Q2_TRANSACTION_REHEARSAL 0
#endif

#define OTIS_CX317_ACTIVE_CAMPAIGN_NONE 0
#define OTIS_CX317_ACTIVE_CAMPAIGN_A 1
#define OTIS_CX317_ACTIVE_CAMPAIGN_B 2
#define OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_A 3
#define OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_B 4
#define OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL 5
#define OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_LOWER 6
#define OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_UPPER 7
#define OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_LOWER 8
#define OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_UPPER 9
#define OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_LOWER 10
#define OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER 11
#define OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER_COMPLETION 12
#define OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID 13
#define OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID 14
#define OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID 15
#define OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION 16

#ifndef OTIS_CX317_ACTIVE_CAMPAIGN
#define OTIS_CX317_ACTIVE_CAMPAIGN OTIS_CX317_ACTIVE_CAMPAIGN_NONE
#endif

#ifndef OTIS_CX317_ACTIVE_START_CODE
#define OTIS_CX317_ACTIVE_START_CODE 0u
#endif

#ifndef OTIS_CX317_ACTIVE_CORRECTION_LIMIT
#define OTIS_CX317_ACTIVE_CORRECTION_LIMIT 0u
#endif

#ifndef OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES
#define OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES 0u
#endif

// The exact Stage 7 qualification profiles retain the frozen production
// timings below.  The separately identified rehearsal profile overrides them
// to traverse the same live dual-core sequence quickly; its records are
// diagnostic-only and cannot satisfy a Stage 7 qualification identity.
#ifndef OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG
#define OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG 600u
#endif

#ifndef OTIS_CX317_STARTUP_WARMUP_S
#define OTIS_CX317_STARTUP_WARMUP_S 1800u
#endif

#ifndef OTIS_CX317_SETTLING_EXCLUSION_S
#define OTIS_CX317_SETTLING_EXCLUSION_S 900u
#endif

#ifndef OTIS_CX317_FULL_HISTORY_RESET_S
#define OTIS_CX317_FULL_HISTORY_RESET_S 1500u
#endif

#ifndef OTIS_CX317_RECOVERY_FRESH_SUPPORT_S
#define OTIS_CX317_RECOVERY_FRESH_SUPPORT_S 600u
#endif

#ifndef OTIS_CX317_DECISION_CADENCE_S
#define OTIS_CX317_DECISION_CADENCE_S 1800u
#endif

#ifndef OTIS_CX317_MINIMUM_APPLIED_CADENCE_S
#define OTIS_CX317_MINIMUM_APPLIED_CADENCE_S 1800u
#endif

#ifndef OTIS_ENABLE_GNSS_RECEIVER
#define OTIS_ENABLE_GNSS_RECEIVER 0
#endif

// Firmware provenance is supplied by the pinned matrix builder or its explicit
// Arduino IDE profile generator. A hand-maintained source literal is not
// evidence of the tree or toolchain that produced a binary. Host-only C++
// harnesses do not produce firmware and use a conspicuous non-firmware profile
// token so they can exercise shared logic.
#if defined(ARDUINO)
#ifndef OTIS_BUILD_PROFILE_GENERATED
#error "Build with tools/firmware_matrix.py or generate an IDE profile with --prepare-ide; generated provenance is required."
#endif

#ifndef OTIS_BUILD_PROVENANCE_FORMAT
#error "OTIS_BUILD_PROVENANCE_FORMAT must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_GIT_COMMIT
#error "OTIS_BUILD_GIT_COMMIT must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_SOURCE_STATE
#error "OTIS_BUILD_SOURCE_STATE must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_SOURCE_SHA256
#error "OTIS_BUILD_SOURCE_SHA256 must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_CONFIG_SHA256
#error "OTIS_BUILD_CONFIG_SHA256 must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_PROFILE_ID
#error "OTIS_BUILD_PROFILE_ID must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_FQBN
#error "OTIS_BUILD_FQBN must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_BOARD_ID
#error "OTIS_BUILD_BOARD_ID must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_BOARD_NAME
#error "OTIS_BUILD_BOARD_NAME must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_CORE_PROVIDER
#error "OTIS_BUILD_CORE_PROVIDER must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_CORE_VERSION
#error "OTIS_BUILD_CORE_VERSION must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_CORE_INSTALLED_SHA256
#error "OTIS_BUILD_CORE_INSTALLED_SHA256 must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_TOOLCHAIN
#error "OTIS_BUILD_TOOLCHAIN must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_COMPILER
#error "OTIS_BUILD_COMPILER must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256
#error "OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256 must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_ARDUINO_CLI_VERSION
#error "OTIS_BUILD_ARDUINO_CLI_VERSION must be generated by the firmware matrix builder."
#endif

#ifndef OTIS_BUILD_INVOCATION_ID
#error "OTIS_BUILD_INVOCATION_ID must be generated by the firmware matrix builder."
#endif
#else
#ifndef OTIS_BUILD_PROFILE_ID
#define OTIS_BUILD_PROFILE_ID "host_test_non_firmware"
#endif
#ifndef OTIS_BUILD_GIT_COMMIT
#define OTIS_BUILD_GIT_COMMIT "host_test_non_firmware"
#endif
#ifndef OTIS_BUILD_BOARD_ID
#define OTIS_BUILD_BOARD_ID "host_test_non_firmware"
#endif
#ifndef OTIS_BUILD_BOARD_NAME
#define OTIS_BUILD_BOARD_NAME "host_test_non_firmware"
#endif
#endif

#ifndef OTIS_FIRMWARE_NAME
#define OTIS_FIRMWARE_NAME "otis_nano_rp2040_connect"
#endif

#ifndef OTIS_FIRMWARE_VERSION
#if OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP
#define OTIS_FIRMWARE_VERSION "CX318_STAGE4_SINGLE_WRITE_PREMISE_SETUP_V1"
#elif OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION
#define OTIS_FIRMWARE_VERSION "OTIS_SUSTAINED_HYBRID_REGULATION_V1"
#elif OTIS_ENABLE_CX322_DIRECT_HYBRID
#define OTIS_FIRMWARE_VERSION "CX322_BOUNDED_HYBRID_FACT_GATHERING_V1"
#elif OTIS_ENABLE_CX321_ACTIVE_HYBRID
#define OTIS_FIRMWARE_VERSION "CX321_BOUNDED_ACTIVE_HYBRID_PLANT_SIGN_V2"
#elif OTIS_ENABLE_CX320_ACTIVE_HYBRID
#define OTIS_FIRMWARE_VERSION "CX320_BOUNDED_ACTIVE_HYBRID_TIGHT_V1"
#elif OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW
#define OTIS_FIRMWARE_VERSION \
  "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1"
#elif OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW
#define OTIS_FIRMWARE_VERSION "CX319_RANGE_MAP_ZERO_AUTHORITY_PREVIEW_V1"
#elif OTIS_ENABLE_CX318_STAGE5_PREVIEW
#define OTIS_FIRMWARE_VERSION "CX318_STAGE5_TIGHT_ACTIVE_FREQUENCY_ONLY_V1"
#elif OTIS_ENABLE_CX318_STAGE4_PREVIEW
#define OTIS_FIRMWARE_VERSION "CX318_RELATIVE_PHASE_HYBRID_PREVIEW_STAGE4_V1"
#elif OTIS_ENABLE_DUAL_CORE_PARTITION && OTIS_ENABLE_CX317_BOUNDED_ACTIVE
#define OTIS_FIRMWARE_VERSION "CX317_DUAL_CORE_ACTIVE_I_ONLY_V1"
#elif OTIS_ENABLE_CX317_BOUNDED_ACTIVE
#define OTIS_FIRMWARE_VERSION "CX317_BOUNDED_ACTIVE_I_ONLY_V2"
#elif OTIS_ENABLE_DUAL_CORE_PARTITION
#define OTIS_FIRMWARE_VERSION "CX317_DUAL_CORE_POST_CAMPAIGN_PREVIEW_V1"
#elif OTIS_ENABLE_CX317_I_ONLY_PREVIEW
#define OTIS_FIRMWARE_VERSION "CX317_PPS_GATED_I_ONLY_PREVIEW_V2"
#elif OTIS_ENABLE_GNSS_RECEIVER
#define OTIS_FIRMWARE_VERSION "CX317_PPS_GATED_GNSS_SMOKE_V1"
#elif OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW
#define OTIS_FIRMWARE_VERSION "SW2_PHASE4_OBSERVE_PREVIEW"
#else
#define OTIS_FIRMWARE_VERSION "SW1"
#endif
#endif

#ifndef OTIS_FIRMWARE_CONFIG_ID
#define OTIS_FIRMWARE_CONFIG_ID OTIS_BUILD_PROFILE_ID
#endif

#ifndef OTIS_FIRMWARE_GIT_COMMIT
#define OTIS_FIRMWARE_GIT_COMMIT OTIS_BUILD_GIT_COMMIT
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

// Conservative full-wrap exclusion bound for the PPS snapshot counter. The
// PIO can execute at most one X decrement per 133 MHz system clock, so this is
// an architectural upper bound on captured edges, not an oscillator estimate
// or clean-run acceptance tolerance.
#ifndef OTIS_PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ
#define OTIS_PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ 133000000u
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

// Bench-only deterministic pseudo-PPS source. It is disabled in every normal
// profile, never starts on boot, and only drives D3 after an explicit ARM then
// START command. Idle, stop, reset, completion, and faults leave D3 high-Z.
#ifndef OTIS_ENABLE_PSEUDO_PPS_GENERATOR
#define OTIS_ENABLE_PSEUDO_PPS_GENERATOR 0
#endif

#ifndef OTIS_PPS_REFERENCE_SHORT_INTERVAL_TICKS
#define OTIS_PPS_REFERENCE_SHORT_INTERVAL_TICKS 8000000ull
#endif

#ifndef OTIS_PPS_REFERENCE_LONG_INTERVAL_TICKS
#define OTIS_PPS_REFERENCE_LONG_INTERVAL_TICKS 19200000ull
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

#ifndef OTIS_PPS_COUNT_BOUNDARY_RING_SIZE
#define OTIS_PPS_COUNT_BOUNDARY_RING_SIZE 128u
#endif

#ifndef OTIS_STATUS_PERIOD_MS
#define OTIS_STATUS_PERIOD_MS 1000u
#endif

#ifndef OTIS_PPS_GATE_STATUS_PERIOD_MS
#define OTIS_PPS_GATE_STATUS_PERIOD_MS 10000u
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

// This remains zero until the PIO-owned snapshot backend passes the focused
// bench contract. Raw REF/CNT evidence is still emitted while control
// eligibility is structurally inhibited.
#ifndef OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED
#define OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED 0
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
#ifndef OTIS_OBSERVE_ONLY_DISCIPLINE_PREVIEW_QUEUE_DEPTH
#define OTIS_OBSERVE_ONLY_DISCIPLINE_PREVIEW_QUEUE_DEPTH 4u
#endif

#ifndef OTIS_OBSERVE_ONLY_DISCIPLINE_ESTIMATOR_WINDOW
#define OTIS_OBSERVE_ONLY_DISCIPLINE_ESTIMATOR_WINDOW 5u
#endif

#ifndef OTIS_OBSERVE_ONLY_DISCIPLINE_MINIMUM_ESTIMATOR_SAMPLES
#define OTIS_OBSERVE_ONLY_DISCIPLINE_MINIMUM_ESTIMATOR_SAMPLES 3u
#endif

#ifndef OTIS_OBSERVE_ONLY_DISCIPLINE_RECOVERY_CLEAN_WINDOWS
#define OTIS_OBSERVE_ONLY_DISCIPLINE_RECOVERY_CLEAN_WINDOWS 3u
#endif

#ifndef OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_MAX_AGE_US
#define OTIS_OBSERVE_ONLY_DISCIPLINE_REFERENCE_MAX_AGE_US 1500000u
#endif

#ifndef OTIS_OBSERVE_ONLY_DISCIPLINE_COUNT_MAX_AGE_US
#define OTIS_OBSERVE_ONLY_DISCIPLINE_COUNT_MAX_AGE_US 450000000u
#endif

#ifndef OTIS_OBSERVE_ONLY_DISCIPLINE_MAXIMUM_DISPERSION_HZ
#define OTIS_OBSERVE_ONLY_DISCIPLINE_MAXIMUM_DISPERSION_HZ 0.25
#endif

// H1 open-loop lab instrument DAC support. This is deliberately opt-in and
// operator-initiated; firmware never steers the oscillator from PPS/count
// telemetry.
#ifndef OTIS_ENABLE_DAC_AD5693R
#define OTIS_ENABLE_DAC_AD5693R 0
#endif

// GNSS UART transmission is restricted to the fixed asynchronous discovery
// and configuration state machine. No host or runtime command surface can
// supply receiver bytes; successful configuration returns to transmit-quiescent
// service (the UART TX pin remains mapped and electrically idle-high).
#ifndef OTIS_GNSS_UART_TX_ENABLED
#define OTIS_GNSS_UART_TX_ENABLED 0
#endif

#ifndef OTIS_GNSS_UART_BAUD
#define OTIS_GNSS_UART_BAUD 9600u
#endif

#ifndef OTIS_GNSS_SERVICE_BYTE_BUDGET
#define OTIS_GNSS_SERVICE_BYTE_BUDGET 32u
#endif

#ifndef OTIS_GNSS_SERVICE_TX_BYTE_BUDGET
#define OTIS_GNSS_SERVICE_TX_BYTE_BUDGET 8u
#endif

#ifndef OTIS_GNSS_UART_TX_TIMEOUT_MS
#define OTIS_GNSS_UART_TX_TIMEOUT_MS 500u
#endif

#ifndef OTIS_GNSS_DISCOVERY_PASSIVE_DWELL_MS
#define OTIS_GNSS_DISCOVERY_PASSIVE_DWELL_MS 1200u
#endif

#ifndef OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS
#define OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS 750u
#endif

#ifndef OTIS_GNSS_OUTPUT_OBSERVATION_MS
#define OTIS_GNSS_OUTPUT_OBSERVATION_MS 2500u
#endif

#ifndef OTIS_GNSS_DISCOVERY_DEGRADED_MS
#define OTIS_GNSS_DISCOVERY_DEGRADED_MS 15000u
#endif

#ifndef OTIS_GNSS_METADATA_MAX_AGE_MS
#define OTIS_GNSS_METADATA_MAX_AGE_MS 3000u
#endif

#ifndef OTIS_GNSS_RECONNECT_GAP_MS
#define OTIS_GNSS_RECONNECT_GAP_MS 10000u
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

// Phase-4 model applicability treats the primary near-VCOCXO temperature as
// stale after three expected sample periods. This tolerates two consecutive
// delayed/missed low-rate reads without allowing an old value to remain a
// silent applicability input indefinitely.
#ifndef OTIS_OBSERVE_ONLY_DISCIPLINE_TEMPERATURE_MAX_AGE_MS
#define OTIS_OBSERVE_ONLY_DISCIPLINE_TEMPERATURE_MAX_AGE_MS (3u * OTIS_ENV_SAMPLE_PERIOD_MS)
#endif

// The PIO long gate is stopped by foreground service after its configured
// deadline. SHT4x high-precision sampling alone blocks that service for 10 ms.
// Allow five such intervals of aperture latency (0.017% of a 300 s gate);
// larger deviations are observation-quality failures, not model-identity
// mismatches.
#ifndef OTIS_OBSERVE_ONLY_DISCIPLINE_OBSERVED_GATE_TOLERANCE_US
#define OTIS_OBSERVE_ONLY_DISCIPLINE_OBSERVED_GATE_TOLERANCE_US 50000u
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

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO && \
    OTIS_CAPTURE_BACKEND != OTIS_CAPTURE_BACKEND_IRQ
#error "PPS_GATED_RATIO requires the GPIO IRQ backend for the independent D14 REF observer."
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

#if OTIS_OBSERVE_ONLY_DISCIPLINE_TEMPERATURE_MAX_AGE_MS < OTIS_ENV_SAMPLE_PERIOD_MS
#error "OTIS_OBSERVE_ONLY_DISCIPLINE_TEMPERATURE_MAX_AGE_MS must cover at least one sample period."
#endif

#if OTIS_OBSERVE_ONLY_DISCIPLINE_OBSERVED_GATE_TOLERANCE_US > 1000000u
#error "OTIS_OBSERVE_ONLY_DISCIPLINE_OBSERVED_GATE_TOLERANCE_US must not exceed one second."
#endif

#if OTIS_DAC_MIN_CODE > OTIS_DAC_MAX_CODE
#error "OTIS_DAC_MIN_CODE must be <= OTIS_DAC_MAX_CODE."
#endif

#if OTIS_DAC_MAX_CODE > 0xFFFFu
#error "OTIS_DAC_MAX_CODE must fit in 16 bits."
#endif

#if OTIS_ENABLE_DAC_AD5693R && \
    OTIS_SW1_BRINGUP_MODE != OTIS_SW1_MODE_H1_OCXO_OBSERVE
#error "AD5693R lab actuation is supported only in H1 OCXO observe mode."
#endif

#if OTIS_ENABLE_GNSS_RECEIVER && \
    OTIS_SW1_BRINGUP_MODE != OTIS_SW1_MODE_H1_OCXO_OBSERVE
#error "The GNSS metadata receiver is supported only in H1 OCXO observe mode."
#endif

#if OTIS_GNSS_UART_TX_ENABLED != 0 && OTIS_GNSS_UART_TX_ENABLED != 1
#error "OTIS_GNSS_UART_TX_ENABLED must be 0 or 1."
#endif

#if OTIS_ENABLE_GNSS_RECEIVER && !OTIS_GNSS_UART_TX_ENABLED
#error "The GNSS receiver requires its bounded discovery/configuration TX path."
#endif

#if OTIS_GNSS_UART_BAUD != 9600u && OTIS_GNSS_UART_BAUD != 115200u
#error "The GNSS receiver target must be 9600 or 115200 baud."
#endif

#if OTIS_GNSS_SERVICE_BYTE_BUDGET < 1u || \
    OTIS_GNSS_SERVICE_BYTE_BUDGET > 64u
#error "OTIS_GNSS_SERVICE_BYTE_BUDGET must be between 1 and 64 bytes."
#endif

#if OTIS_GNSS_SERVICE_TX_BYTE_BUDGET < 1u || \
    OTIS_GNSS_SERVICE_TX_BYTE_BUDGET > 16u
#error "OTIS_GNSS_SERVICE_TX_BYTE_BUDGET must be between 1 and 16 bytes."
#endif

#if OTIS_GNSS_UART_TX_TIMEOUT_MS < 100u || \
    OTIS_GNSS_UART_TX_TIMEOUT_MS > 1000u
#error "The GNSS UART TX timeout must be between 100 and 1000 ms."
#endif

#if OTIS_GNSS_DISCOVERY_PASSIVE_DWELL_MS < 1000u || \
    OTIS_GNSS_DISCOVERY_PASSIVE_DWELL_MS > 5000u
#error "GNSS passive discovery dwell must be between 1 and 5 seconds."
#endif

#if OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS < 100u || \
    OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS > 2000u
#error "GNSS command response timeout must be between 100 ms and 2 seconds."
#endif

#if OTIS_GNSS_OUTPUT_OBSERVATION_MS < 2000u || \
    OTIS_GNSS_OUTPUT_OBSERVATION_MS > 10000u
#error "GNSS output observation must be between 2 and 10 seconds."
#endif

#if OTIS_GNSS_DISCOVERY_DEGRADED_MS < 10000u || \
    OTIS_GNSS_DISCOVERY_DEGRADED_MS > 60000u
#error "GNSS degraded discovery deadline must be between 10 and 60 seconds."
#endif

#if OTIS_GNSS_METADATA_MAX_AGE_MS < 1000u || \
    OTIS_GNSS_METADATA_MAX_AGE_MS > 10000u
#error "OTIS_GNSS_METADATA_MAX_AGE_MS must be between 1 and 10 seconds."
#endif

#if OTIS_GNSS_RECONNECT_GAP_MS <= OTIS_GNSS_METADATA_MAX_AGE_MS
#error "GNSS reconnect gap must exceed the metadata freshness limit."
#endif

#if OTIS_ENABLE_H1_DAC_SWEEP && !OTIS_ENABLE_DAC_AD5693R
#error "The H1 DAC sweep requires the explicit AD5693R lab actuator profile."
#endif

#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR && \
    OTIS_SW1_BRINGUP_MODE != OTIS_SW1_MODE_H1_OCXO_OBSERVE
#error "The pseudo-PPS generator is supported only by the H1 loopback test profile."
#endif

#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR && \
    (OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO || \
     OTIS_CAPTURE_BACKEND != OTIS_CAPTURE_BACKEND_IRQ || \
     OTIS_ENABLE_DAC_AD5693R || OTIS_ENABLE_H1_DAC_SWEEP || \
     OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW || OTIS_ENABLE_ENV_SENSORS || \
     OTIS_ENABLE_GNSS_RECEIVER)
#error "The pseudo-PPS generator requires the isolated PPS-gated loopback test profile."
#endif

#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR != 0 && \
    OTIS_ENABLE_PSEUDO_PPS_GENERATOR != 1
#error "OTIS_ENABLE_PSEUDO_PPS_GENERATOR must be 0 or 1."
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

#if OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW != 0 && \
    OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW != 1
#error "OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW must be 0 or 1."
#endif

#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW != 0 && \
    OTIS_ENABLE_CX317_I_ONLY_PREVIEW != 1
#error "OTIS_ENABLE_CX317_I_ONLY_PREVIEW must be 0 or 1."
#endif

#if OTIS_ENABLE_CX318_STAGE4_PREVIEW != 0 && \
    OTIS_ENABLE_CX318_STAGE4_PREVIEW != 1
#error "OTIS_ENABLE_CX318_STAGE4_PREVIEW must be 0 or 1."
#endif

#if OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED != 0 && \
    OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED != 1
#error "OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED must be 0 or 1."
#endif

#if OTIS_ENABLE_CX318_STAGE5_PREVIEW != 0 && \
    OTIS_ENABLE_CX318_STAGE5_PREVIEW != 1
#error "OTIS_ENABLE_CX318_STAGE5_PREVIEW must be 0 or 1."
#endif

#if OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW != 0 && \
    OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW != 1
#error "OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW must be 0 or 1."
#endif

#if OTIS_ENABLE_CX320_ACTIVE_HYBRID != 0 && \
    OTIS_ENABLE_CX320_ACTIVE_HYBRID != 1
#error "OTIS_ENABLE_CX320_ACTIVE_HYBRID must be 0 or 1."
#endif

#if OTIS_ENABLE_CX321_ACTIVE_HYBRID != 0 && \
    OTIS_ENABLE_CX321_ACTIVE_HYBRID != 1
#error "OTIS_ENABLE_CX321_ACTIVE_HYBRID must be 0 or 1."
#endif

#if OTIS_ENABLE_CX322_DIRECT_HYBRID != 0 && \
    OTIS_ENABLE_CX322_DIRECT_HYBRID != 1
#error "OTIS_ENABLE_CX322_DIRECT_HYBRID must be 0 or 1."
#endif

#if OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION != 0 && \
    OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION != 1
#error "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION must be 0 or 1."
#endif

#if OTIS_ENABLE_CX320_ACTIVE_HYBRID && \
    (!OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW || \
     !OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW || \
     !OTIS_ENABLE_DUAL_CORE_PARTITION || \
     !OTIS_ENABLE_CX317_BOUNDED_ACTIVE || \
     (OTIS_CX317_ACTIVE_CAMPAIGN != \
          OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID && \
      OTIS_CX317_ACTIVE_CAMPAIGN != \
          OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID && \
      OTIS_CX317_ACTIVE_CAMPAIGN != \
          OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID && \
      OTIS_CX317_ACTIVE_CAMPAIGN != \
          OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION))
#error "CX320 active hybrid requires its exact dual-core tight-band campaign identity."
#endif

#if OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW != 0 && \
    OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW != 1
#error "OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW must be 0 or 1."
#endif

#if OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW && \
    (OTIS_ENABLE_CX318_STAGE4_PREVIEW || \
     OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW)
#error "CX319 range-map preview has a separate programme identity."
#endif

#if OTIS_ENABLE_CX318_STAGE5_PREVIEW && OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW
#error "Historical CX318 and current CX319 active-preview identities are mutually exclusive."
#endif

#if OTIS_ENABLE_CX318_STAGE4_PREVIEW && \
    OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW
#error "CX318 Stage 4 and tight active-preview identities are mutually exclusive."
#endif

#if OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP != 0 && \
    OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP != 1
#error "OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP must be 0 or 1."
#endif

#if OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP && \
    (OTIS_CX318_STAGE4_PREMISE_SETUP_CODE != 0xA828u || \
     !OTIS_ENABLE_DAC_AD5693R || OTIS_DAC_MIN_CODE != 0xA828u || \
     OTIS_DAC_MAX_CODE != 0xA828u || OTIS_ENABLE_H1_DAC_SWEEP)
#error "CX318 Stage 4 premise setup requires the single exact A828 DAC surface."
#endif

#if OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP && \
    (OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW || \
     OTIS_ENABLE_CX317_I_ONLY_PREVIEW || OTIS_ENABLE_CX318_STAGE4_PREVIEW || \
     OTIS_ENABLE_CX317_BOUNDED_ACTIVE || OTIS_ENABLE_DUAL_CORE_PARTITION)
#error "CX318 Stage 4 premise setup excludes every preview, controller, and dual-core authority path."
#endif

#if OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP && \
    (OTIS_SW1_BRINGUP_MODE != OTIS_SW1_MODE_H1_OCXO_OBSERVE || \
     OTIS_CAPTURE_BACKEND != OTIS_CAPTURE_BACKEND_IRQ || \
     OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO || \
     !OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED || !OTIS_ENABLE_GNSS_RECEIVER || \
     !OTIS_GNSS_UART_TX_ENABLED || !OTIS_ENABLE_ENV_SENSORS || \
     OTIS_ENABLE_PSEUDO_PPS_GENERATOR)
#error "CX318 Stage 4 premise setup requires qualified PPS, bounded GNSS discovery, and environment telemetry."
#endif

#if OTIS_ENABLE_DUAL_CORE_PARTITION != 0 && \
    OTIS_ENABLE_DUAL_CORE_PARTITION != 1
#error "OTIS_ENABLE_DUAL_CORE_PARTITION must be 0 or 1."
#endif

#if OTIS_ENABLE_DUAL_CORE_PARTITION && !OTIS_ENABLE_CX317_I_ONLY_PREVIEW && \
    !OTIS_ENABLE_PHASE_FREQUENCY_PREVIEW
#error "The dual-core partition requires an explicit protected timing preview."
#endif

#if OTIS_ENABLE_CX318_STAGE4_PREVIEW && !OTIS_ENABLE_DUAL_CORE_PARTITION
#error "CX318 Stage 4 preview requires the dual-core partition."
#endif

#if OTIS_ENABLE_CX318_STAGE4_PREVIEW && \
    (OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW || \
     OTIS_ENABLE_CX317_I_ONLY_PREVIEW || \
     OTIS_ENABLE_CX317_BOUNDED_ACTIVE)
#error "CX318 Stage 4 preview is mutually exclusive with legacy and active control paths."
#endif

#if OTIS_ENABLE_CX318_STAGE4_PREVIEW && \
    (OTIS_ENABLE_DAC_AD5693R || OTIS_ENABLE_H1_DAC_SWEEP)
#error "CX318 Stage 4 preview structurally excludes every DAC and sweep path."
#endif

#if OTIS_ENABLE_CX318_STAGE4_PREVIEW && \
    (OTIS_SW1_BRINGUP_MODE != OTIS_SW1_MODE_H1_OCXO_OBSERVE || \
     OTIS_CAPTURE_BACKEND != OTIS_CAPTURE_BACKEND_IRQ || \
     OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO || \
     !OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED || !OTIS_ENABLE_GNSS_RECEIVER || \
     !OTIS_GNSS_UART_TX_ENABLED || !OTIS_ENABLE_ENV_SENSORS || \
     OTIS_ENABLE_PSEUDO_PPS_GENERATOR)
#error "CX318 Stage 4 preview requires qualified D14 PPS capture, bounded GNSS discovery, and environment telemetry."
#endif

#if OTIS_ENABLE_CX318_STAGE4_PREVIEW && \
    (OTIS_CX318_STAGE4_STATIC_CODE < 0xA800u || \
     OTIS_CX318_STAGE4_STATIC_CODE > 0xAB00u)
#error "CX318 Stage 4 preview requires an exact preflight-bound static DAC code in A800..AB00."
#endif

#if OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW && \
    (!OTIS_ENABLE_DUAL_CORE_PARTITION || !OTIS_ENABLE_CX317_I_ONLY_PREVIEW || \
     OTIS_ENABLE_CX317_BOUNDED_ACTIVE || !OTIS_ENABLE_DAC_AD5693R || \
     OTIS_ENABLE_H1_DAC_SWEEP || !OTIS_ENABLE_GNSS_RECEIVER || \
     !OTIS_GNSS_UART_TX_ENABLED || !OTIS_ENABLE_ENV_SENSORS || \
     !OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED || \
     OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO || \
     OTIS_CX319_RANGE_MAP_INITIAL_CODE < 0xA800u || \
     OTIS_CX319_RANGE_MAP_INITIAL_CODE > 0xAB00u || \
     OTIS_DAC_MIN_CODE != 0xA800u || OTIS_DAC_MAX_CODE != 0xAB00u)
#error "CX319 range-map preview requires exact zero-active dual-core preview and characterized DAC topology."
#endif

#if OTIS_ENABLE_TIGHT_DEADBAND_ACTIVE_PREVIEW && \
    (!OTIS_ENABLE_DUAL_CORE_PARTITION || !OTIS_ENABLE_CX317_I_ONLY_PREVIEW || \
     !OTIS_ENABLE_CX317_BOUNDED_ACTIVE || !OTIS_ENABLE_DAC_AD5693R || \
     OTIS_ENABLE_H1_DAC_SWEEP || !OTIS_ENABLE_GNSS_RECEIVER || \
     !OTIS_GNSS_UART_TX_ENABLED || !OTIS_ENABLE_ENV_SENSORS || \
     !OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED || \
     OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO)
#error "The tight active preview requires the exact dual-core frequency-only active, bounded GNSS discovery, qualified count, environment, and nonsweep DAC topology."
#endif

#if OTIS_ENABLE_CX318_STAGE5_PREVIEW && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_LOWER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_UPPER
#error "CX318 Stage 5 preview requires an exact Stage 5 leg identity."
#endif

#if OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_LOWER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_UPPER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_LOWER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER_COMPLETION && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION
#error "CX319 tight preview requires an exact successor leg identity."
#endif

#if OTIS_ENABLE_CX318_STAGE5_PREVIEW && \
    (OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE != 0xA828u || \
     OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH != 0u)
#error "CX318 Stage 5 rehearsal/live handoff requires the reconfirmed pre-setup A828 code at local DAC epoch zero."
#endif

#if OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW && \
    (OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE != 0xA828u || \
     OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH != 0u)
#error "Tight-band setup handoff requires the historical A828 preview context at local DAC epoch zero."
#endif

#if OTIS_ENABLE_DUAL_CORE_PARTITION && OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN != OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_A && \
    OTIS_CX317_ACTIVE_CAMPAIGN != OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_B && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_LOWER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_UPPER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_LOWER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_UPPER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_LOWER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER_COMPLETION && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION
#error "Dual-core bounded authority is restricted to exact historical or current programme profiles."
#endif

#if !OTIS_ENABLE_DUAL_CORE_PARTITION && OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    (OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_A || \
     OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_B || \
     OTIS_CX317_ACTIVE_CAMPAIGN == \
         OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL)
#error "Stage 7 bounded authority requires the dual-core partition."
#endif

#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW && OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW
#error "The CX317 selected preview and legacy Phase 4 preview are mutually exclusive."
#endif

#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW && \
    (OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO || \
     !OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED || !OTIS_ENABLE_ENV_SENSORS)
#error "The CX317 preview requires the qualified PPS-gated backend and environment context."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE != 0 && \
    OTIS_ENABLE_CX317_BOUNDED_ACTIVE != 1
#error "OTIS_ENABLE_CX317_BOUNDED_ACTIVE must be 0 or 1."
#endif

#if OTIS_ENABLE_Q2_TRANSACTION_REHEARSAL != 0 && \
    OTIS_ENABLE_Q2_TRANSACTION_REHEARSAL != 1
#error "OTIS_ENABLE_Q2_TRANSACTION_REHEARSAL must be 0 or 1."
#endif

#if OTIS_ENABLE_Q2_TRANSACTION_REHEARSAL && \
    (!OTIS_ENABLE_DUAL_CORE_PARTITION || !OTIS_ENABLE_CX317_BOUNDED_ACTIVE || \
     OTIS_CX317_ACTIVE_CAMPAIGN != \
         OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_LOWER)
#error "Q2 transaction rehearsal requires the exact dual-core CX319 lower profile."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    (!OTIS_ENABLE_CX317_I_ONLY_PREVIEW || !OTIS_ENABLE_GNSS_RECEIVER || \
     !OTIS_ENABLE_DAC_AD5693R || OTIS_ENABLE_H1_DAC_SWEEP || \
     !OTIS_ENABLE_ENV_SENSORS || !OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED || \
     OTIS_TCXO_COUNTER_BACKEND != OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO)
#error "Bounded active control requires the dedicated preview, bounded GNSS discovery, qualified count, environment, and nonsweep DAC topology."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    (OTIS_DAC_MIN_CODE != 0xA800u || OTIS_DAC_MAX_CODE != 0xAB00u)
#error "Bounded active control requires the immutable A800..AB00 DAC range."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_A && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA950u || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 16u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 336u)
#error "Campaign A active parameters differ from the immutable programme envelope."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_B && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA800u || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 8u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 168u)
#error "Campaign B active parameters differ from the immutable programme envelope."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_A && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA800u || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 4u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 84u)
#error "Stage 7 Part A parameters differ from the immutable programme envelope."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_B && \
    (OTIS_CX317_ACTIVE_START_CODE < 0xA800u || \
     OTIS_CX317_ACTIVE_START_CODE > 0xAB00u || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 32u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 672u)
#error "Stage 7 Part B parameters differ from the immutable programme envelope."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA800u || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 2u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 42u || \
     OTIS_FC0_STARTUP_INHIBIT_MS != 60000u || \
     OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS != 3u || \
     OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG != 120u || \
     OTIS_CX317_STARTUP_WARMUP_S != 60u || \
     OTIS_CX317_SETTLING_EXCLUSION_S != 60u || \
     OTIS_CX317_FULL_HISTORY_RESET_S != 180u || \
     OTIS_CX317_RECOVERY_FRESH_SUPPORT_S != 120u || \
     OTIS_CX317_DECISION_CADENCE_S != 240u || \
     OTIS_CX317_MINIMUM_APPLIED_CADENCE_S != 240u)
#error "Stage 7 rehearsal parameters differ from the diagnostic-only contract."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_LOWER && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA808u || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 4u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 84u)
#error "CX318 Stage 5 lower-leg parameters differ from the immutable programme envelope."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_UPPER && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA848u || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 4u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 84u)
#error "CX318 Stage 5 upper-leg parameters differ from the immutable programme envelope."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_LOWER && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA808u || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 4u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 84u)
#error "CX319 lower-leg parameters differ from the frozen offline candidate."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_UPPER && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA848u || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 4u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 84u)
#error "CX319 upper-leg parameters differ from the frozen offline candidate."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_LOWER && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA800u || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 9u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 189u)
#error "CX319 range Part B lower parameters differ from the conditional campaign."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA890u || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 9u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 189u)
#error "CX319 range Part B upper parameters differ from the conditional campaign."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER_COMPLETION && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA83Cu || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 2u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 42u)
#error "CX319 range Part B upper-completion parameters differ from the continuation contract."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA83Cu || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 4u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 84u)
#error "CX320 active-hybrid parameters differ from the frozen candidate."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA83Cu || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 4u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 84u)
#error "CX321 active-hybrid parameters differ from the frozen candidate."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA83Cu || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 4u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 84u)
#error "CX322 direct-hybrid parameters differ from the frozen candidate."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN == \
        OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION && \
    (OTIS_CX317_ACTIVE_START_CODE != 0xA83Cu || \
     OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 13u || \
     OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 84u || \
     OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS != 12u || \
     OTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE != 1)
#error "Sustained hybrid regulation parameters differ from the frozen candidate."
#endif

#if OTIS_ENABLE_CX321_ACTIVE_HYBRID && \
    (!OTIS_ENABLE_CX320_ACTIVE_HYBRID || \
     OTIS_CX317_ACTIVE_CAMPAIGN != \
         OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID)
#error "CX321 plant-sign authority requires its exact CX320-derived profile."
#endif

#if OTIS_ENABLE_CX322_DIRECT_HYBRID && \
    (!OTIS_ENABLE_CX320_ACTIVE_HYBRID || OTIS_ENABLE_CX321_ACTIVE_HYBRID || \
     (OTIS_CX317_ACTIVE_CAMPAIGN != \
          OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID && \
      OTIS_CX317_ACTIVE_CAMPAIGN != \
          OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION))
#error "CX322 direct hybrid requires its exact CX320-derived profile without CX321 identification."
#endif


#if OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION && \
    (!OTIS_ENABLE_CX320_ACTIVE_HYBRID || !OTIS_ENABLE_CX322_DIRECT_HYBRID || \
     OTIS_ENABLE_CX321_ACTIVE_HYBRID || \
     OTIS_CX317_ACTIVE_CAMPAIGN != \
         OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION)
#error "Sustained hybrid regulation requires its exact descriptive CX322-derived profile."
#endif

#if OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_LOWER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER_COMPLETION && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION
#error "External DAC-epoch candidate reseed is restricted to conditional Part B and active-hybrid profiles."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL && \
    (OTIS_FC0_STARTUP_INHIBIT_MS != 600000u || \
     OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS != 3u || \
     OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG != 600u || \
     OTIS_CX317_STARTUP_WARMUP_S != 1800u || \
     OTIS_CX317_SETTLING_EXCLUSION_S != 900u || \
     OTIS_CX317_FULL_HISTORY_RESET_S != 1500u || \
     OTIS_CX317_RECOVERY_FRESH_SUPPORT_S != 600u || \
     OTIS_CX317_DECISION_CADENCE_S != 1800u || \
     OTIS_CX317_MINIMUM_APPLIED_CADENCE_S != 1800u)
#error "Qualification active timing differs from the frozen programme policy."
#endif

#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE && \
    OTIS_CX317_ACTIVE_CAMPAIGN != OTIS_CX317_ACTIVE_CAMPAIGN_A && \
    OTIS_CX317_ACTIVE_CAMPAIGN != OTIS_CX317_ACTIVE_CAMPAIGN_B && \
    OTIS_CX317_ACTIVE_CAMPAIGN != OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_A && \
    OTIS_CX317_ACTIVE_CAMPAIGN != OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_B && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_LOWER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX318_STAGE5_UPPER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_LOWER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_TIGHT_DEADBAND_UPPER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_LOWER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_RANGE_PART_B_UPPER_COMPLETION && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID && \
    OTIS_CX317_ACTIVE_CAMPAIGN != \
        OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION
#error "Bounded active control requires an exact programme campaign identity."
#endif

#if OTIS_OBSERVE_ONLY_DISCIPLINE_PREVIEW_QUEUE_DEPTH < 2u || \
    OTIS_OBSERVE_ONLY_DISCIPLINE_PREVIEW_QUEUE_DEPTH > 8u
#error "OTIS_OBSERVE_ONLY_DISCIPLINE_PREVIEW_QUEUE_DEPTH must be between 2 and 8."
#endif

#if OTIS_OBSERVE_ONLY_DISCIPLINE_ESTIMATOR_WINDOW < 3u || \
    OTIS_OBSERVE_ONLY_DISCIPLINE_ESTIMATOR_WINDOW > 8u
#error "OTIS_OBSERVE_ONLY_DISCIPLINE_ESTIMATOR_WINDOW must be between 3 and 8."
#endif

#if OTIS_OBSERVE_ONLY_DISCIPLINE_MINIMUM_ESTIMATOR_SAMPLES < 1u || \
    OTIS_OBSERVE_ONLY_DISCIPLINE_MINIMUM_ESTIMATOR_SAMPLES > OTIS_OBSERVE_ONLY_DISCIPLINE_ESTIMATOR_WINDOW
#error "OTIS_OBSERVE_ONLY_DISCIPLINE_MINIMUM_ESTIMATOR_SAMPLES must fit the estimator window."
#endif

#if OTIS_OBSERVE_ONLY_DISCIPLINE_RECOVERY_CLEAN_WINDOWS < 1u
#error "OTIS_OBSERVE_ONLY_DISCIPLINE_RECOVERY_CLEAN_WINDOWS must be at least 1."
#endif

#if OTIS_CAPTURE_RING_SIZE < 2u || OTIS_CAPTURE_RING_SIZE > 255u
#error "OTIS_CAPTURE_RING_SIZE must be between 2 and 255."
#endif

#if OTIS_PPS_COUNT_BOUNDARY_RING_SIZE < 3u || \
    OTIS_PPS_COUNT_BOUNDARY_RING_SIZE > 255u
#error "OTIS_PPS_COUNT_BOUNDARY_RING_SIZE must be between 3 and 255."
#endif

#if (OTIS_PPS_COUNT_BOUNDARY_RING_SIZE & \
     (OTIS_PPS_COUNT_BOUNDARY_RING_SIZE - 1u)) != 0u
#error "OTIS_PPS_COUNT_BOUNDARY_RING_SIZE must be a power of two."
#endif

#if OTIS_PPS_GATE_STATUS_PERIOD_MS < 1000u
#error "OTIS_PPS_GATE_STATUS_PERIOD_MS must be at least 1000 ms."
#endif

#if OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED != 0 && \
    OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED != 1
#error "OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED must be 0 or 1."
#endif

#if OTIS_SAFE_MODE_FAILURE_THRESHOLD > 255u
#error "OTIS_SAFE_MODE_FAILURE_THRESHOLD must fit in uint8_t."
#endif

#if defined(ARDUINO)
#ifndef OTIS_BUILD_EXPECTED_OTIS_SW1_BRINGUP_MODE
#error "Generated profile is missing OTIS_SW1_BRINGUP_MODE."
#elif OTIS_SW1_BRINGUP_MODE != OTIS_BUILD_EXPECTED_OTIS_SW1_BRINGUP_MODE
#error "Effective OTIS_SW1_BRINGUP_MODE differs from the generated profile."
#endif
#ifndef OTIS_BUILD_EXPECTED_OTIS_CAPTURE_BACKEND
#error "Generated profile is missing OTIS_CAPTURE_BACKEND."
#elif OTIS_CAPTURE_BACKEND != OTIS_BUILD_EXPECTED_OTIS_CAPTURE_BACKEND
#error "Effective OTIS_CAPTURE_BACKEND differs from the generated profile."
#endif
#ifndef OTIS_BUILD_EXPECTED_OTIS_TCXO_COUNTER_BACKEND
#error "Generated profile is missing OTIS_TCXO_COUNTER_BACKEND."
#elif OTIS_TCXO_COUNTER_BACKEND != OTIS_BUILD_EXPECTED_OTIS_TCXO_COUNTER_BACKEND
#error "Effective OTIS_TCXO_COUNTER_BACKEND differs from the generated profile."
#endif
#ifndef OTIS_BUILD_EXPECTED_OTIS_ENABLE_PSEUDO_PPS_GENERATOR
#error "Generated profile is missing OTIS_ENABLE_PSEUDO_PPS_GENERATOR."
#elif OTIS_ENABLE_PSEUDO_PPS_GENERATOR != OTIS_BUILD_EXPECTED_OTIS_ENABLE_PSEUDO_PPS_GENERATOR
#error "Effective OTIS_ENABLE_PSEUDO_PPS_GENERATOR differs from the generated profile."
#endif
#ifndef OTIS_BUILD_EXPECTED_OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED
#error "Generated profile is missing OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED."
#elif OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED != OTIS_BUILD_EXPECTED_OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED
#error "Effective OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED differs from the generated profile."
#endif
#ifndef OTIS_BUILD_EXPECTED_OTIS_PPS_GATE_MIN_INTERVAL_US
#error "Generated profile is missing OTIS_PPS_GATE_MIN_INTERVAL_US."
#elif OTIS_PPS_GATE_MIN_INTERVAL_US != OTIS_BUILD_EXPECTED_OTIS_PPS_GATE_MIN_INTERVAL_US
#error "Effective OTIS_PPS_GATE_MIN_INTERVAL_US differs from the generated profile."
#endif
#ifndef OTIS_BUILD_EXPECTED_OTIS_PPS_GATE_MAX_INTERVAL_US
#error "Generated profile is missing OTIS_PPS_GATE_MAX_INTERVAL_US."
#elif OTIS_PPS_GATE_MAX_INTERVAL_US != OTIS_BUILD_EXPECTED_OTIS_PPS_GATE_MAX_INTERVAL_US
#error "Effective OTIS_PPS_GATE_MAX_INTERVAL_US differs from the generated profile."
#endif
#ifndef OTIS_BUILD_EXPECTED_OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW
#error "Generated profile is missing OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW."
#elif OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW != OTIS_BUILD_EXPECTED_OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW
#error "Effective OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW differs from the generated profile."
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX317_I_ONLY_PREVIEW
#if OTIS_ENABLE_CX317_I_ONLY_PREVIEW != OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX317_I_ONLY_PREVIEW
#error "Effective OTIS_ENABLE_CX317_I_ONLY_PREVIEW differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX318_STAGE4_PREVIEW
#if OTIS_ENABLE_CX318_STAGE4_PREVIEW != OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX318_STAGE4_PREVIEW
#error "Effective OTIS_ENABLE_CX318_STAGE4_PREVIEW differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX318_STAGE5_PREVIEW
#if OTIS_ENABLE_CX318_STAGE5_PREVIEW != OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX318_STAGE5_PREVIEW
#error "Effective OTIS_ENABLE_CX318_STAGE5_PREVIEW differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW
#if OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW != OTIS_BUILD_EXPECTED_OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW
#error "Effective OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW
#if OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW != OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW
#error "Effective OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX319_RANGE_MAP_INITIAL_CODE
#if OTIS_CX319_RANGE_MAP_INITIAL_CODE != OTIS_BUILD_EXPECTED_OTIS_CX319_RANGE_MAP_INITIAL_CODE
#error "Effective OTIS_CX319_RANGE_MAP_INITIAL_CODE differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX318_STAGE5_INITIAL_CODE
#if OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE != OTIS_BUILD_EXPECTED_OTIS_CX318_STAGE5_INITIAL_CODE
#error "Effective OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX318_STAGE5_INITIAL_DAC_EPOCH
#if OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH != OTIS_BUILD_EXPECTED_OTIS_CX318_STAGE5_INITIAL_DAC_EPOCH
#error "Effective OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE
#if OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE != OTIS_BUILD_EXPECTED_OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE
#error "Effective OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH
#if OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH != OTIS_BUILD_EXPECTED_OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH
#error "Effective OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX318_STAGE4_STATIC_CODE
#if OTIS_CX318_STAGE4_STATIC_CODE != OTIS_BUILD_EXPECTED_OTIS_CX318_STAGE4_STATIC_CODE
#error "Effective OTIS_CX318_STAGE4_STATIC_CODE differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX318_STAGE4_DAC_EPOCH
#if OTIS_CX318_STAGE4_DAC_EPOCH != OTIS_BUILD_EXPECTED_OTIS_CX318_STAGE4_DAC_EPOCH
#error "Effective OTIS_CX318_STAGE4_DAC_EPOCH differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP
#if OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP != OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP
#error "Effective OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX318_STAGE4_PREMISE_SETUP_CODE
#if OTIS_CX318_STAGE4_PREMISE_SETUP_CODE != OTIS_BUILD_EXPECTED_OTIS_CX318_STAGE4_PREMISE_SETUP_CODE
#error "Effective OTIS_CX318_STAGE4_PREMISE_SETUP_CODE differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_ENABLE_DUAL_CORE_PARTITION
#if OTIS_ENABLE_DUAL_CORE_PARTITION != OTIS_BUILD_EXPECTED_OTIS_ENABLE_DUAL_CORE_PARTITION
#error "Effective OTIS_ENABLE_DUAL_CORE_PARTITION differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX317_BOUNDED_ACTIVE
#if OTIS_ENABLE_CX317_BOUNDED_ACTIVE != OTIS_BUILD_EXPECTED_OTIS_ENABLE_CX317_BOUNDED_ACTIVE
#error "Effective OTIS_ENABLE_CX317_BOUNDED_ACTIVE differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX317_ACTIVE_CAMPAIGN
#if OTIS_CX317_ACTIVE_CAMPAIGN != OTIS_BUILD_EXPECTED_OTIS_CX317_ACTIVE_CAMPAIGN
#error "Effective OTIS_CX317_ACTIVE_CAMPAIGN differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX317_ACTIVE_START_CODE
#if OTIS_CX317_ACTIVE_START_CODE != OTIS_BUILD_EXPECTED_OTIS_CX317_ACTIVE_START_CODE
#error "Effective OTIS_CX317_ACTIVE_START_CODE differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX317_ACTIVE_CORRECTION_LIMIT
#if OTIS_CX317_ACTIVE_CORRECTION_LIMIT != OTIS_BUILD_EXPECTED_OTIS_CX317_ACTIVE_CORRECTION_LIMIT
#error "Effective OTIS_CX317_ACTIVE_CORRECTION_LIMIT differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES
#if OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != OTIS_BUILD_EXPECTED_OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES
#error "Effective OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG
#if OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG != OTIS_BUILD_EXPECTED_OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG
#error "Effective OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX317_STARTUP_WARMUP_S
#if OTIS_CX317_STARTUP_WARMUP_S != OTIS_BUILD_EXPECTED_OTIS_CX317_STARTUP_WARMUP_S
#error "Effective OTIS_CX317_STARTUP_WARMUP_S differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX317_SETTLING_EXCLUSION_S
#if OTIS_CX317_SETTLING_EXCLUSION_S != OTIS_BUILD_EXPECTED_OTIS_CX317_SETTLING_EXCLUSION_S
#error "Effective OTIS_CX317_SETTLING_EXCLUSION_S differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX317_FULL_HISTORY_RESET_S
#if OTIS_CX317_FULL_HISTORY_RESET_S != OTIS_BUILD_EXPECTED_OTIS_CX317_FULL_HISTORY_RESET_S
#error "Effective OTIS_CX317_FULL_HISTORY_RESET_S differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX317_RECOVERY_FRESH_SUPPORT_S
#if OTIS_CX317_RECOVERY_FRESH_SUPPORT_S != OTIS_BUILD_EXPECTED_OTIS_CX317_RECOVERY_FRESH_SUPPORT_S
#error "Effective OTIS_CX317_RECOVERY_FRESH_SUPPORT_S differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX317_DECISION_CADENCE_S
#if OTIS_CX317_DECISION_CADENCE_S != OTIS_BUILD_EXPECTED_OTIS_CX317_DECISION_CADENCE_S
#error "Effective OTIS_CX317_DECISION_CADENCE_S differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_CX317_MINIMUM_APPLIED_CADENCE_S
#if OTIS_CX317_MINIMUM_APPLIED_CADENCE_S != OTIS_BUILD_EXPECTED_OTIS_CX317_MINIMUM_APPLIED_CADENCE_S
#error "Effective OTIS_CX317_MINIMUM_APPLIED_CADENCE_S differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_FC0_STARTUP_INHIBIT_MS
#if OTIS_FC0_STARTUP_INHIBIT_MS != OTIS_BUILD_EXPECTED_OTIS_FC0_STARTUP_INHIBIT_MS
#error "Effective OTIS_FC0_STARTUP_INHIBIT_MS differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS
#if OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS != OTIS_BUILD_EXPECTED_OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS
#error "Effective OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_ENABLE_GNSS_RECEIVER
#if OTIS_ENABLE_GNSS_RECEIVER != OTIS_BUILD_EXPECTED_OTIS_ENABLE_GNSS_RECEIVER
#error "Effective OTIS_ENABLE_GNSS_RECEIVER differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_GNSS_UART_TX_ENABLED
#if OTIS_GNSS_UART_TX_ENABLED != OTIS_BUILD_EXPECTED_OTIS_GNSS_UART_TX_ENABLED
#error "Effective OTIS_GNSS_UART_TX_ENABLED differs from the generated profile."
#endif
#endif
#ifndef OTIS_BUILD_EXPECTED_OTIS_ENABLE_DAC_AD5693R
#error "Generated profile is missing OTIS_ENABLE_DAC_AD5693R."
#elif OTIS_ENABLE_DAC_AD5693R != OTIS_BUILD_EXPECTED_OTIS_ENABLE_DAC_AD5693R
#error "Effective OTIS_ENABLE_DAC_AD5693R differs from the generated profile."
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_DAC_MIN_CODE
#if OTIS_DAC_MIN_CODE != OTIS_BUILD_EXPECTED_OTIS_DAC_MIN_CODE
#error "Effective OTIS_DAC_MIN_CODE differs from the generated profile."
#endif
#endif
#ifdef OTIS_BUILD_EXPECTED_OTIS_DAC_MAX_CODE
#if OTIS_DAC_MAX_CODE != OTIS_BUILD_EXPECTED_OTIS_DAC_MAX_CODE
#error "Effective OTIS_DAC_MAX_CODE differs from the generated profile."
#endif
#endif
#ifndef OTIS_BUILD_EXPECTED_OTIS_ENABLE_H1_DAC_SWEEP
#error "Generated profile is missing OTIS_ENABLE_H1_DAC_SWEEP."
#elif OTIS_ENABLE_H1_DAC_SWEEP != OTIS_BUILD_EXPECTED_OTIS_ENABLE_H1_DAC_SWEEP
#error "Effective OTIS_ENABLE_H1_DAC_SWEEP differs from the generated profile."
#endif
#ifndef OTIS_BUILD_EXPECTED_OTIS_ENABLE_ENV_SENSORS
#error "Generated profile is missing OTIS_ENABLE_ENV_SENSORS."
#elif OTIS_ENABLE_ENV_SENSORS != OTIS_BUILD_EXPECTED_OTIS_ENABLE_ENV_SENSORS
#error "Effective OTIS_ENABLE_ENV_SENSORS differs from the generated profile."
#endif
#endif

#endif
