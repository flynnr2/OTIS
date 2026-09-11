#ifndef OTIS_CONFIG_H
#define OTIS_CONFIG_H

// Fixed production configuration for the adaptive-hybrid oscillator
// regulator. This header contains implementation facts, not build selectors.

#include "otis_build_config.h"

// Firmware identity.
#define OTIS_FIRMWARE_NAME "otis_nano_rp2040_connect"
#define OTIS_FIRMWARE_VERSION "OTIS_ADAPTIVE_HYBRID_REGULATION_V1"
#define OTIS_FIRMWARE_GIT_COMMIT OTIS_BUILD_GIT_COMMIT
#define OTIS_OPERATING_MODE_NAME "ADAPTIVE_HYBRID_REGULATION"

// Fixed D14 reference / D8 oscillator-count topology.
#define OTIS_CAPTURE_MODE "irq_reconstructed"

// Receiver qualification and fail-static control hold.
#define OTIS_GNSS_UART_BAUD 115200u
#define OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS 1200u
#define OTIS_GNSS_SERVICE_TX_BYTE_BUDGET 8u
#define OTIS_GNSS_UART_TX_TIMEOUT_MS 500u
#define OTIS_GNSS_DISCOVERY_PASSIVE_DWELL_MS 1200u
#define OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS 750u
#define OTIS_GNSS_OUTPUT_OBSERVATION_MS 2500u
#define OTIS_GNSS_DISCOVERY_DEGRADED_MS 15000u
#define OTIS_GNSS_METADATA_MAX_AGE_MS 3000u
#define OTIS_GNSS_RECONNECT_GAP_MS 10000u

// Bounded actuation and selected controller policy.
#define OTIS_DAC_AD5693R_I2C_ADDRESS 0x4Cu
#define OTIS_DAC_MIN_CODE 0xA800u
#define OTIS_DAC_MAX_CODE 0xAB00u
#define OTIS_ADAPTIVE_HYBRID_START_CODE 0xA84Du
#define OTIS_ADAPTIVE_HYBRID_CORRECTION_LIMIT 144u
#define OTIS_ADAPTIVE_HYBRID_CUMULATIVE_LIMIT_CODES 3024u
#define OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS_CONFIG 600u
#define OTIS_COUNT_STARTUP_INHIBIT_MS 600000u
#define OTIS_COUNT_CONTROL_READY_CLEAN_WINDOWS 3u
#define OTIS_ADAPTIVE_HYBRID_STARTUP_WARMUP_S 1800u
#define OTIS_ADAPTIVE_HYBRID_SETTLING_EXCLUSION_S 900u
#define OTIS_ADAPTIVE_HYBRID_FULL_HISTORY_RESET_S 1500u
#define OTIS_ADAPTIVE_HYBRID_RECOVERY_FRESH_SUPPORT_S 600u
#define OTIS_ADAPTIVE_HYBRID_DECISION_CADENCE_S 1800u
#define OTIS_ADAPTIVE_HYBRID_MINIMUM_APPLIED_CADENCE_S 1800u

// Environmental context.
#define OTIS_ENV_SAMPLE_PERIOD_MS 1000u
#define OTIS_ENV_SHT4X_I2C_ADDRESS 0x44u
#define OTIS_ENV_BMP280_I2C_ADDRESS 0x77u
#define OTIS_TEMPERATURE_MAX_AGE_MS (3u * OTIS_ENV_SAMPLE_PERIOD_MS)
#define OTIS_COUNT_GATE_TOLERANCE_US 50000u

// Runtime sizing and cadence.
#define OTIS_BOOT_INITIAL_DELAY_MS 1500u
#define OTIS_SERIAL_BAUD 115200u
#define OTIS_SERIAL_WAIT_MS 250u
#define OTIS_SAFE_MODE_FAILURE_THRESHOLD 3u
#define OTIS_CAPTURE_RING_SIZE 32u
#define OTIS_PPS_COUNT_BOUNDARY_RING_SIZE 128u
#define OTIS_STATUS_PERIOD_MS 1000u
#define OTIS_PPS_GATE_STATUS_PERIOD_MS 10000u
#define OTIS_TCXO_GATE_PERIOD_US 10000000u
#define OTIS_PPS_GATE_MIN_INTERVAL_US 800000u
#define OTIS_PPS_GATE_DUPLICATE_MAX_INTERVAL_US 100000u
#define OTIS_PPS_GATE_MAX_INTERVAL_US 1200000u
#define OTIS_PPS_GATE_MISSING_TIMEOUT_US 2500000u
#define OTIS_PPS_REFERENCE_SHORT_INTERVAL_US 500000ull
#define OTIS_PPS_REFERENCE_LONG_INTERVAL_US 1200000ull
#define OTIS_PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ 133000000u
#define OTIS_NOMINAL_PPS_HZ 1u
#define OTIS_MINIMUM_FREE_STACK_BYTES 1024u
#define OTIS_MINIMUM_FREE_HEAP_BYTES 65536u

// The builder must bind every production translation unit to exact source,
// toolchain, board and invocation identities.
#if defined(ARDUINO)
#ifndef OTIS_BUILD_MANIFEST_GENERATED
#error "Build the fixed firmware with tools/build_firmware.py."
#endif
#ifndef OTIS_BUILD_PROVENANCE_FORMAT
#error "Missing generated build provenance format."
#endif
#ifndef OTIS_BUILD_GIT_COMMIT
#error "Missing generated source revision."
#endif
#ifndef OTIS_BUILD_SOURCE_STATE
#error "Missing generated source state."
#endif
#ifndef OTIS_BUILD_SOURCE_SHA256
#error "Missing generated source identity."
#endif
#ifndef OTIS_BUILD_CONFIG_SHA256
#error "Missing generated configuration identity."
#endif
#ifndef OTIS_BUILD_IMAGE_ID
#error "Missing generated image identity."
#endif
#ifndef OTIS_BUILD_FQBN
#error "Missing generated board configuration."
#endif
#ifndef OTIS_BUILD_BOARD_ID
#error "Missing generated board identity."
#endif
#ifndef OTIS_BUILD_BOARD_NAME
#error "Missing generated board name."
#endif
#ifndef OTIS_BUILD_CORE_PROVIDER
#error "Missing generated core provider."
#endif
#ifndef OTIS_BUILD_CORE_VERSION
#error "Missing generated core version."
#endif
#ifndef OTIS_BUILD_CORE_INSTALLED_SHA256
#error "Missing generated core identity."
#endif
#ifndef OTIS_BUILD_TOOLCHAIN
#error "Missing generated toolchain name."
#endif
#ifndef OTIS_BUILD_COMPILER
#error "Missing generated compiler name."
#endif
#ifndef OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256
#error "Missing generated toolchain identity."
#endif
#ifndef OTIS_BUILD_ARDUINO_CLI_VERSION
#error "Missing generated Arduino CLI version."
#endif
#ifndef OTIS_BUILD_INVOCATION_ID
#error "Missing generated invocation identity."
#endif
#ifndef OTIS_BUILD_SOURCE_IDENTITY_SHA256
#error "Missing generated aggregate source identity."
#endif
#ifndef OTIS_BUILD_TARGET_IDENTITY_SHA256
#error "Missing generated aggregate target identity."
#endif
#ifndef OTIS_BUILD_TOOLCHAIN_IDENTITY_SHA256
#error "Missing generated aggregate toolchain identity."
#endif
#ifndef OTIS_BUILD_AUTHORITATIVE_INPUT_SET_SHA256
#error "Missing generated authoritative-input-set identity."
#endif
#ifndef OTIS_BUILD_PROVENANCE_SHA256
#error "Missing generated aggregate build provenance identity."
#endif
#ifndef OTIS_BUILD_GENERATED_HEADER_IDENTITY_SHA256
#error "Missing generated-header semantic identity."
#endif
#ifndef OTIS_BUILD_ADAPTIVE_POLICY_SHA256
#error "Missing generated adaptive-policy identity."
#endif
#ifndef OTIS_BUILD_FREQUENCY_ESTIMATOR_SHA256
#error "Missing generated frequency-estimator identity."
#endif
#ifndef OTIS_BUILD_PHASE_ESTIMATOR_SHA256
#error "Missing generated phase-estimator identity."
#endif
#ifndef OTIS_BUILD_PHASE_ESTIMATOR_ID
#error "Missing generated phase-estimator profile id."
#endif
#ifndef OTIS_BUILD_PHASE_RAW_METHOD_ID
#error "Missing generated phase raw-method id."
#endif
#ifndef OTIS_BUILD_PLANT_MODEL_SHA256
#error "Missing generated plant-model identity."
#endif
#ifndef OTIS_BUILD_RESPONSE_POLICY_SHA256
#error "Missing generated response-policy identity."
#endif
#ifndef OTIS_BUILD_FORWARDED_CLOCK_CONTRACT_ID
#error "Missing generated forwarded-clock contract identity."
#endif
#ifndef OTIS_BUILD_FORWARDED_CLOCK_CONTRACT_SHA256
#error "Missing generated forwarded-clock contract hash."
#endif
#ifndef OTIS_BUILD_FREQUENCY_ESTIMATOR_TAG_U64
#error "Missing generated frequency-estimator tag."
#endif
#else
#ifndef OTIS_BUILD_IMAGE_ID
#define OTIS_BUILD_IMAGE_ID "host_test_non_firmware"
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

// Fixed-image invariants. A source edit that changes one of these facts must
// fail at compile time instead of silently creating another image variant.
#if OTIS_DAC_MIN_CODE != 0xA800u || OTIS_DAC_MAX_CODE != 0xAB00u
#error "The fixed actuator envelope is A800..AB00."
#endif
#if OTIS_ADAPTIVE_HYBRID_START_CODE != 0xA84Du || \
    OTIS_ADAPTIVE_HYBRID_CORRECTION_LIMIT != 144u || \
    OTIS_ADAPTIVE_HYBRID_CUMULATIVE_LIMIT_CODES != 3024u
#error "Adaptive-hybrid actuator bounds differ from the selected policy."
#endif
#if OTIS_FREQUENCY_ESTIMATOR_SPAN_INTERVALS_CONFIG != 600u || \
    OTIS_ADAPTIVE_HYBRID_STARTUP_WARMUP_S != 1800u || \
    OTIS_ADAPTIVE_HYBRID_SETTLING_EXCLUSION_S != 900u || \
    OTIS_ADAPTIVE_HYBRID_FULL_HISTORY_RESET_S != 1500u || \
    OTIS_ADAPTIVE_HYBRID_RECOVERY_FRESH_SUPPORT_S != 600u || \
    OTIS_ADAPTIVE_HYBRID_DECISION_CADENCE_S != 1800u || \
    OTIS_ADAPTIVE_HYBRID_MINIMUM_APPLIED_CADENCE_S != 1800u
#error "Adaptive-hybrid timing differs from the selected policy."
#endif
#if OTIS_PPS_GATE_MIN_INTERVAL_US == 0u || \
    OTIS_PPS_GATE_MIN_INTERVAL_US > OTIS_PPS_GATE_MAX_INTERVAL_US || \
    OTIS_PPS_GATE_DUPLICATE_MAX_INTERVAL_US >= OTIS_PPS_GATE_MIN_INTERVAL_US || \
    OTIS_PPS_GATE_MISSING_TIMEOUT_US <= OTIS_PPS_GATE_MAX_INTERVAL_US
#error "PPS interval limits are inconsistent."
#endif
#if OTIS_CAPTURE_RING_SIZE < 2u || OTIS_CAPTURE_RING_SIZE > 255u
#error "Capture ring capacity is invalid."
#endif
#if OTIS_PPS_COUNT_BOUNDARY_RING_SIZE < 3u || \
    OTIS_PPS_COUNT_BOUNDARY_RING_SIZE > 255u || \
    (OTIS_PPS_COUNT_BOUNDARY_RING_SIZE & \
     (OTIS_PPS_COUNT_BOUNDARY_RING_SIZE - 1u)) != 0u
#error "PPS boundary ring capacity must be a power of two in 3..255."
#endif
#if OTIS_GNSS_RECONNECT_GAP_MS <= OTIS_GNSS_METADATA_MAX_AGE_MS
#error "GNSS reconnect gap must exceed metadata freshness."
#endif

#endif
