#include <Arduino.h>
#include <stdio.h>
#include <string.h>

#include "otis_config.h"

#include "OtisBootConfig.h"
#include "otis_board.h"
#include "otis_boot_capabilities.h"
#include "otis_boot_diag.h"
#include "otis_capture_backend.h"
#include "otis_capture_irq.h"
#include "otis_capture_pio.h"
#include "otis_capture_ring.h"
#include "otis_count_observation.h"
#include "otis_dac_ad5693r.h"
#include "otis_emit.h"
#include "otis_env_sensors.h"
#include "otis_modes.h"
#include "otis_phase4_observe_preview.h"
#include "otis_pps_count_boundary_ring.h"
#include "otis_pps_dual_observer.h"
#include "otis_pps_snapshot_backend.h"
#include "otis_pseudo_pps.h"
#include "otis_protocol.h"
#include "otis_resource_registry.h"
#include "otis_runtime_state.h"
#include "otis_serial_command.h"
#include "otis_status_emit.h"
#include "otis_status_led.h"
#include "otis_timebase.h"
#include "otis_transport_serial.h"

#if OTIS_ENABLE_PPS_DUAL_OBSERVER && \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
#error "OTIS_ENABLE_PPS_DUAL_OBSERVER requires D10 as a PPS input; GPIO loopback drives/uses D10 incompatibly."
#endif

#if OTIS_ENABLE_PPS_DUAL_OBSERVER && \
    OTIS_CAPTURE_BACKEND != OTIS_CAPTURE_BACKEND_IRQ
#error "OTIS_ENABLE_PPS_DUAL_OBSERVER currently compares against D14 IRQ diagnostics; keep OTIS_CAPTURE_BACKEND_IRQ for this H1 witness run."
#endif

namespace {

#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
constexpr uint32_t kStatusPeriodMs = OTIS_PPS_GATE_STATUS_PERIOD_MS;
#else
constexpr uint32_t kStatusPeriodMs = OTIS_STATUS_PERIOD_MS;
#endif
constexpr uint32_t kLoopbackTogglePeriodMs = OTIS_LOOPBACK_TOGGLE_PERIOD_MS;
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE
constexpr uint32_t kTcxoGatePeriodUs = OTIS_H1_LONG_GATE_PERIOD_US;
#else
constexpr uint32_t kTcxoGatePeriodUs = OTIS_TCXO_GATE_PERIOD_US;
#endif
constexpr uint32_t kTcxoMeasurePeriodMs = OTIS_TCXO_MEASURE_PERIOD_MS;
constexpr uint32_t kFc0StartupInhibitMs = OTIS_FC0_STARTUP_INHIBIT_MS;
constexpr uint32_t kFc0ControlReadyCleanWindows =
    OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS;

OtisRuntimeState runtime_state;
OtisStatusEmitContext status_emit_context;
OtisSerialFrameCollector serial_command_collector;
OtisBootCapabilityTracker boot_capabilities;
bool resource_ownership_status_emitted = false;
bool boot_capability_status_emitted = false;
bool run_mode_status_emitted = false;
bool transport_started = false;
bool config_query_provenance_emitted = false;

void enter_boot_phase(BootPhase next_phase) {
  runtime_state.boot.phase = next_phase;
}

void begin_boot_phase(BootPhase next_phase) {
  enter_boot_phase(next_phase);
  otis_boot_capability_begin_phase(&boot_capabilities, next_phase);
}

void complete_boot_phase(BootPhase completed_phase) {
  otis_boot_capability_complete_phase(&boot_capabilities, completed_phase);
  otisBootBreadcrumbCompletePhase(completed_phase);
}

OtisBootCapabilityRequirement capability_requirement(
    OtisBootCapability capability) {
  const OtisBootCapabilityEntry *entry =
      otis_boot_capability_entry(&boot_capabilities, capability);
  return entry == nullptr ? OtisBootCapabilityRequirement::Disabled
                          : entry->requirement;
}

void record_capability_result(OtisBootCapability capability, bool ready) {
  otis_boot_capability_record(
      &boot_capabilities, capability,
      otis_boot_capability_result(capability_requirement(capability), ready));
}

bool capability_ready(OtisBootCapability capability) {
  const OtisBootCapabilityEntry *entry =
      otis_boot_capability_entry(&boot_capabilities, capability);
  return entry != nullptr && entry->reported &&
         entry->outcome == OtisBootCapabilityOutcome::Ready;
}

void configure_selected_capabilities(void) {
  otis_boot_capability_tracker_init(&boot_capabilities);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::ResourceRegistry,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Timebase,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::RingBuffers,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Transport,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::HostConnection,
                              OtisBootCapabilityRequirement::Optional);

#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::SparseCapture,
                              OtisBootCapabilityRequirement::Required);
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::SparseCapture,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::PpsCapture,
                              OtisBootCapabilityRequirement::Required);
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::PpsWitness,
                              OtisBootCapabilityRequirement::Optional);
#endif
#endif

#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::CountBackend,
                              OtisBootCapabilityRequirement::Required);
#endif

#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::PseudoPpsGenerator,
                              OtisBootCapabilityRequirement::Required);
#endif

#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE && \
    OTIS_ENABLE_DAC_AD5693R
  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Dac,
                              OtisBootCapabilityRequirement::Required);
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE && \
    OTIS_ENABLE_ENV_SENSORS && \
    (OTIS_ENABLE_ENV_SHT4X || OTIS_ENABLE_ENV_BMP280)
  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Sensors,
                              OtisBootCapabilityRequirement::Optional);
#endif
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::Phase4Preview,
                              OtisBootCapabilityRequirement::Required);
#endif
}

void emit_selected_capability_status();
void emit_resource_ownership_status();
void emit_protocol_banner_if_serial_ready();

void emit_boot_records_if_serial_ready(void) {
  if (runtime_state.boot.summary_emitted || !otis_transport_ready()) {
    return;
  }

  emitOtisBootSummary(Serial, runtime_state.boot.phase);
  if (runtime_state.boot.serial_absent_warn_pending) {
    emitOtisBootWarnSerialAbsent(Serial, kOtisSerialWaitMs);
    runtime_state.boot.serial_absent_warn_pending = false;
  }
  if (runtime_state.boot.safe_mode_warn_pending) {
    emitOtisBootWarnSafeMode(Serial);
    runtime_state.boot.safe_mode_warn_pending = false;
  }
  runtime_state.boot.summary_emitted = true;
}

void wait_for_serial_or_timeout(void) {
  uint32_t serial_wait_start_ms = millis();
  while (!otis_transport_ready() &&
         (uint32_t)(millis() - serial_wait_start_ms) < kOtisSerialWaitMs) {
    delay(1);
  }
  runtime_state.boot.serial_ready = otis_transport_ready();
  runtime_state.boot.serial_absent_warn_pending =
      !runtime_state.boot.serial_ready;
}

void halt_boot(BootFatal fatal, BootPhase failed_phase) {
  enter_boot_phase(BootPhase::Fatal);
  otisBootBreadcrumbSetFatal(fatal);
  otis_status_led_set(OTIS_SYSTEM_STATE_FATAL_CONFIG_FAULT);

  bool fatal_emitted = false;
  if (!transport_started) {
    transport_started = otis_transport_begin(kOtisSerialBaud);
    wait_for_serial_or_timeout();
  }
  if (otis_transport_ready()) {
    emit_protocol_banner_if_serial_ready();
    emit_selected_capability_status();
    emit_resource_ownership_status();
    otis_pseudo_pps_service();
    emitOtisBootFatal(Serial, fatal, failed_phase);
    fatal_emitted = true;
  }

  while (true) {
    if (otis_transport_ready() && !fatal_emitted) {
      emit_protocol_banner_if_serial_ready();
      emit_selected_capability_status();
      emit_resource_ownership_status();
      otis_pseudo_pps_service();
      emitOtisBootFatal(Serial, fatal, failed_phase);
      fatal_emitted = true;
    }
    otis_status_led_poll(millis());
    delay(10);
  }
}

void enter_safe_mode(void) {
  runtime_state.boot.safe_mode_active = true;
  runtime_state.boot.safe_mode_warn_pending = true;
  enter_boot_phase(BootPhase::Fatal);
  otisBootBreadcrumbSetSafeModeFatal(BootFatal::RepeatedBootFailure);

  otis_status_led_begin();
  transport_started = otis_transport_begin(kOtisSerialBaud);
  wait_for_serial_or_timeout();
  otis_status_led_set(OTIS_SYSTEM_STATE_FATAL_CONFIG_FAULT);
  emit_protocol_banner_if_serial_ready();
  emit_selected_capability_status();
  emit_resource_ownership_status();
}

const char *edge_string(char edge);
const char *osc_observation_domain(void);
OtisCountObservationConfig count_observation_config(void);
#if OTIS_ENABLE_H1_DAC_SWEEP && \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
void emit_h1_dac_sweep_fc0_window(void);
#endif

void emit_status(const char *component, const char *key, const char *value,
                 const char *severity, uint32_t flags) {
  otis_status_emit(&status_emit_context, component, key, value, severity,
                   flags);
}

void emit_status_u32(const char *component, const char *key, uint32_t value,
                     const char *severity, uint32_t flags) {
  otis_status_emit_u32(&status_emit_context, component, key, value, severity,
                       flags);
}

void emit_status_i32(const char *component, const char *key, int32_t value,
                     const char *severity, uint32_t flags) {
  char buffer[12];
  snprintf(buffer, sizeof(buffer), "%ld", (long)value);
  emit_status(component, key, buffer, severity, flags);
}

void emit_status_u16_hex(const char *component, const char *key, uint16_t value,
                         const char *severity, uint32_t flags) {
  char buffer[7];
  snprintf(buffer, sizeof(buffer), "0x%04X", value);
  emit_status(component, key, buffer, severity, flags);
}

void emit_status_u64_decimal(const char *component, const char *key,
                             uint64_t value, const char *severity,
                             uint32_t flags) {
  char buffer[21];
  snprintf(buffer, sizeof(buffer), "%llu",
           static_cast<unsigned long long>(value));
  emit_status(component, key, buffer, severity, flags);
}

void emit_captured_edge(const OtisCapturedEdge &record) {
  if (record.reference_record && record.edge == 'R') {
    otis_capture_irq_process_reference_foreground(record);
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
    const OtisPpsCountBoundaryObservation pending_reference = {
        0u,
        0u,
        record.source_sequence,
        record.timestamp_ticks,
        0u,
        0u,
        record.flags,
        OTIS_PPS_APERTURE_NONE,
    };
    otis_pps_count_boundary_ring_push_from_isr(pending_reference);
#endif
    OtisDacAd5693rStatus dac_status;
    otis_dac_ad5693r_get_status(&dac_status);
    OtisPhase4LiveDacState phase4_dac = {
        dac_status.last_write_ok &&
            dac_status.last_requested_code == dac_status.last_applied_code,
        dac_status.last_applied_code,
    };
    otis_phase4_observe_preview_on_reference(
        runtime_state.sequences.event_seq, record.timestamp_ticks, record.flags,
        &runtime_state, &phase4_dac);
  }

  otis_emit_raw_event(record.reference_record ? OTIS_RECORD_REF : OTIS_RECORD_EVT,
                      runtime_state.sequences.event_seq++, record.channel_id,
                      edge_string(record.edge), record.timestamp_ticks,
                      OTIS_DOMAIN_RP2040_TIMER0, record.flags);
  runtime_state.capture.emitted_event_count++;
}

const char *edge_string(char edge) {
  if (edge == 'R') {
    return OTIS_EDGE_RISING;
  }
  if (edge == 'F') {
    return OTIS_EDGE_FALLING;
  }
  return OTIS_EDGE_BOTH_OR_UNSPECIFIED;
}

const char *osc_observation_domain(void) {
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  return OTIS_DOMAIN_H0_TCXO_16MHZ;
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  return OTIS_DOMAIN_H1_OCXO_OPEN_LOOP;
#else
  return OTIS_DOMAIN_H0_TCXO_16MHZ;
#endif
}

OtisCountObservationConfig count_observation_config(void) {
  return {
      kTcxoGatePeriodUs,
      kTcxoMeasurePeriodMs,
      kFc0StartupInhibitMs,
      kFc0ControlReadyCleanWindows,
      osc_observation_domain(),
  };
}

void drain_capture_ring(void) {
  OtisCapturedEdge record;
  while (otis_capture_ring_pop(&record)) {
    emit_captured_edge(record);
  }
}

void emit_pps_count_boundary(
    const OtisPpsCountBoundaryObservation &observation) {
  OtisCountObservationConfig count_config = count_observation_config();
  bool window_completed = otis_count_observation_on_pps_boundary(
      &runtime_state, &status_emit_context, &count_config, &observation);
  if (window_completed) {
    OtisDacAd5693rStatus dac_status;
    otis_dac_ad5693r_get_status(&dac_status);
    OtisPhase4LiveDacState phase4_dac = {
        dac_status.last_write_ok &&
            dac_status.last_requested_code == dac_status.last_applied_code,
        dac_status.last_applied_code,
    };
    otis_phase4_observe_preview_on_count(
        runtime_state.sequences.count_seq - 1u, &runtime_state, &phase4_dac);
    otis_count_observation_note_control_consumer(observation.session,
                                                 observation.sequence);
#if OTIS_ENABLE_H1_DAC_SWEEP && \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
    emit_h1_dac_sweep_fc0_window();
#endif
  }
}

void drain_pps_count_boundary_ring(void) {
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
  static bool have_pending_reference = false;
  static OtisPpsCountBoundaryObservation pending_reference = {};

  if (!have_pending_reference) {
    have_pending_reference =
        otis_pps_count_boundary_ring_pop(&pending_reference);
  }
  if (!have_pending_reference) {
    return;
  }

  OtisPpsSnapshotBackendStats stats;
  otis_pps_snapshot_backend_get_stats(&stats);
  uint64_t pending_age_ticks = otis_timer0_interval_ticks(
      pending_reference.pps_timestamp_ticks, otis_capture_ticks_now());
  uint64_t association_timeout_ticks =
      static_cast<uint64_t>(OTIS_PPS_GATE_MAX_INTERVAL_US) *
      OTIS_RP2040_TIMER0_TICKS_PER_US;
  bool another_reference_waiting =
      otis_pps_count_boundary_ring_depth() != 0u;
  if (stats.fault_latched || another_reference_waiting ||
      pending_age_ticks > association_timeout_ticks) {
    // A second physical REF before the first association closes is immediate
    // association loss, even if a word has since appeared. Queue/foreground
    // delay cannot prove that word belongs to the older REF, so it is never
    // paired retroactively with it.
    const char *association_reason =
        stats.fault_latched
            ? "snapshot_backend_fault"
            : (another_reference_waiting ? "ref_without_snapshot"
                                         : "snapshot_association_timeout");
    otis_count_observation_note_association_loss(
        &runtime_state, &status_emit_context,
        pending_reference.reference_sequence, association_reason);
    otis_pps_snapshot_backend_rearm();
    otis_pps_count_boundary_ring_reset();
    have_pending_reference = false;
    return;
  }

  OtisPpsHardwareSnapshot snapshot;
  if (!otis_pps_snapshot_backend_pop(&snapshot)) {
    return;
  }

  OtisPpsCountBoundaryObservation observation = pending_reference;
  observation.session = snapshot.session;
  observation.sequence = snapshot.sequence;
  observation.cumulative_down_counter = snapshot.cumulative_down_counter;
  if ((snapshot.status & OTIS_PPS_SNAPSHOT_STATUS_OVERWRITE_BEFORE) != 0u) {
    observation.aperture_flags |=
        OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW |
        OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE;
  }
  otis_emit_pps_snapshot(
      observation.session, observation.sequence,
      observation.cumulative_down_counter, observation.reference_sequence,
      observation.pps_timestamp_ticks, snapshot.status,
      "pio_wait_cumulative_snapshot_dma_v1");
  emit_pps_count_boundary(observation);
  have_pending_reference = false;
#endif
}

void emit_build_provenance_status(void) {
  emit_status("build", "provenance_format", OTIS_BUILD_PROVENANCE_FORMAT,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "git_commit", OTIS_FIRMWARE_GIT_COMMIT,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "source_state", OTIS_BUILD_SOURCE_STATE,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "source_hash", OTIS_BUILD_SOURCE_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "config_hash", OTIS_BUILD_CONFIG_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "board", OTIS_TARGET_BOARD, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "board_name", OTIS_TARGET_BOARD_NAME,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "fqbn", OTIS_BUILD_FQBN, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_provider", OTIS_BUILD_CORE_PROVIDER,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_version", OTIS_BUILD_CORE_VERSION,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_installed_hash",
              OTIS_BUILD_CORE_INSTALLED_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "profile_id", OTIS_BUILD_PROFILE_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "toolchain", OTIS_BUILD_TOOLCHAIN,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "compiler", OTIS_BUILD_COMPILER, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "toolchain_installed_hash",
              OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "arduino_cli_version",
              OTIS_BUILD_ARDUINO_CLI_VERSION, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "invocation_id", OTIS_BUILD_INVOCATION_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}

void emit_common_boot_status(void) {
  emit_build_provenance_status();
  emit_status("system", "boot", "true", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("protocol", "schema_version", OTIS_SCHEMA_VERSION_V1,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "name", OTIS_FIRMWARE_NAME, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "version", OTIS_FIRMWARE_VERSION, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "config_id", OTIS_FIRMWARE_CONFIG_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "git_commit", OTIS_FIRMWARE_GIT_COMMIT,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "source_state", OTIS_BUILD_SOURCE_STATE,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "source_hash", OTIS_BUILD_SOURCE_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("firmware", "config_hash", OTIS_BUILD_CONFIG_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "mode", otis_bringup_mode_name(), OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "mode", OTIS_CAPTURE_MODE, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  emit_status("capture", "timestamp_latch", "pio_edge_detect_cpu_timestamped",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "limitation",
              "pio_detects_rising_edges_cpu_attaches_drain_timestamp_dma_deferred",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
#else
  emit_status("capture", "timestamp_latch", "irq_micros_reconstructed",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "limitation",
              "bench_validation_not_final_pio_dma_metrology",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
#endif
  emit_status_u32("capture", "nominal_capture_clock_hz",
                  OTIS_NOMINAL_CAPTURE_CLOCK_HZ, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("reference", "nominal_pps_hz", OTIS_NOMINAL_PPS_HZ,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("reference", "nominal_tcxo_hz", OTIS_NOMINAL_TCXO_HZ,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("reference", "nominal_ocxo_hz", OTIS_NOMINAL_OCXO_HZ,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("capture", "fc0_measure_period_ms", kTcxoMeasurePeriodMs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("capture", "counter_gate_period_us", kTcxoGatePeriodUs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "measurement_mode",
              otis_count_observation_measurement_mode(),
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core", OTIS_TARGET_ARDUINO_CORE,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "board", OTIS_TARGET_BOARD, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "board_name", OTIS_TARGET_BOARD_NAME,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "fqbn", OTIS_BUILD_FQBN, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_provider", OTIS_BUILD_CORE_PROVIDER,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_version", OTIS_BUILD_CORE_VERSION,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("system", "arduino_core_installed_hash",
              OTIS_BUILD_CORE_INSTALLED_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "profile_id", OTIS_BUILD_PROFILE_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "toolchain", OTIS_BUILD_TOOLCHAIN,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "compiler", OTIS_BUILD_COMPILER, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "toolchain_installed_hash",
              OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "arduino_cli_version",
              OTIS_BUILD_ARDUINO_CLI_VERSION, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "invocation_id", OTIS_BUILD_INVOCATION_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_rp2040_boot_diag",
                  OTIS_ENABLE_RP2040_BOOT_DIAG, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_pps_dual_observer",
                  OTIS_ENABLE_PPS_DUAL_OBSERVER, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_status_led", OTIS_ENABLE_STATUS_LED,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "capture_backend", otis_capture_backend_name(),
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("build", "tcxo_counter_backend",
              otis_tcxo_counter_backend_name(),
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_dac_ad5693r", OTIS_ENABLE_DAC_AD5693R,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_phase4_observe_preview",
                  OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("phase4_preview", "actuation_authorized", "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_h1_dac_sweep", OTIS_ENABLE_H1_DAC_SWEEP,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_env_sensors", OTIS_ENABLE_ENV_SENSORS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_env_sht4x", OTIS_ENABLE_ENV_SHT4X,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("build", "enable_env_bmp280", OTIS_ENABLE_ENV_BMP280,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("environment", "sample_period_ms", OTIS_ENV_SAMPLE_PERIOD_MS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("environment", "sht4x_i2c_address",
                  OTIS_ENV_SHT4X_I2C_ADDRESS, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("environment", "bmp280_i2c_address",
                  OTIS_ENV_BMP280_I2C_ADDRESS, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("sweep", "default_dwell_ms",
                  OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("sweep", "slope_dwell_ms", OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex("sweep", "tiny_step_codes",
                      OTIS_H1_DAC_SWEEP_TINY_STEP_CODES, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex("sweep", "center_code",
                      (uint16_t)(((uint32_t)OTIS_DAC_MIN_CODE +
                                  (uint32_t)OTIS_DAC_MAX_CODE) /
                                 2u),
                      OTIS_SEVERITY_INFO,
                      OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("dac", "i2c_address", OTIS_DAC_AD5693R_I2C_ADDRESS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  emit_status("pps_dual_observer", "feature", "temporary_h1_diagnostic",
              OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "d14_pps_pin", "D14",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "d10_witness_pin", "D10",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "d14_capture_backend",
              otis_capture_backend_name(), OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "d10_observer_mechanism",
              "plain_gpio_irq_rising_dedicated_buffer", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "d10_input_mode", "INPUT_no_pull",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pps_dual_observer", "requested_edge", "R",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u64_decimal("pps_dual_observer", "short_interval_ticks",
                          OTIS_PPS_DUAL_OBSERVER_SHORT_INTERVAL_TICKS,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u64_decimal("pps_dual_observer", "long_interval_ticks",
                          OTIS_PPS_DUAL_OBSERVER_LONG_INTERVAL_TICKS,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("pps_dual_observer", "burst_short_threshold",
                  OTIS_PPS_DUAL_OBSERVER_BURST_SHORT_THRESHOLD,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
}

void emit_env_sensor_status(void) {
  OtisEnvSensorStatus status;
  otis_env_sensors_get_status(&status);
  emit_status("environment", "sht4x_enabled",
              status.sht4x_enabled ? "true" : "false", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("environment", "sht4x_initialized",
              status.sht4x_initialized ? "true" : "false",
              status.sht4x_initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.sht4x_initialized ? OTIS_FLAG_NONE
                                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("environment", "bmp280_enabled",
              status.bmp280_enabled ? "true" : "false", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("environment", "bmp280_initialized",
              status.bmp280_initialized ? "true" : "false",
              status.bmp280_initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.bmp280_initialized ? OTIS_FLAG_NONE
                                        : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("environment", "primary_temperature_source", "sht4x",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("environment", "primary_temperature_role", "vcocxo_near",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}

void emit_h0_pin_status(void) {
  emit_status("pins", "ch0_generic_event", "D10", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pins", "ch1_pps_reference", "D14", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("pins", "ch2_osc_observation", "D8_GPIO20_GPIN0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  emit_status("pins", "d10_pps_witness", "D10_input_rising_no_pull",
              OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
}

void emit_selected_capability_status(void) {
  if (boot_capability_status_emitted || !otis_transport_ready()) {
    return;
  }

  const OtisBootCapabilityOutcome overall =
      otis_boot_capability_overall_outcome(&boot_capabilities);
  const bool run_mode_ready = boot_capabilities.run_mode_marked;
  const bool degraded = otis_boot_capability_degraded(&boot_capabilities);
  emit_status("boot_capabilities", "selected_profile",
              otis_bringup_mode_name(), OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("boot_capabilities", "overall",
              otis_boot_capability_outcome_name(overall),
              overall == OtisBootCapabilityOutcome::Ready
                  ? OTIS_SEVERITY_INFO
                  : (overall == OtisBootCapabilityOutcome::OptionalDegraded
                         ? OTIS_SEVERITY_WARN
                         : OTIS_SEVERITY_FATAL),
              overall == OtisBootCapabilityOutcome::Ready
                  ? OTIS_FLAG_PROFILE_ASSUMPTION
                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("boot_capabilities", "run_mode",
              run_mode_ready ? "Ready" : "blocked",
              run_mode_ready ? (degraded ? OTIS_SEVERITY_WARN
                                         : OTIS_SEVERITY_INFO)
                             : OTIS_SEVERITY_FATAL,
              run_mode_ready && !degraded ? OTIS_FLAG_PROFILE_ASSUMPTION
                                          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("boot_capabilities", "degraded",
              degraded ? "true" : "false",
              degraded ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
              degraded ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                       : OTIS_FLAG_PROFILE_ASSUMPTION);

  uint32_t selected_count = 0u;
  for (uint8_t index = 0u;
       index < static_cast<uint8_t>(OtisBootCapability::Count); ++index) {
    const OtisBootCapability capability =
        static_cast<OtisBootCapability>(index);
    const OtisBootCapabilityEntry *entry =
        otis_boot_capability_entry(&boot_capabilities, capability);
    if (entry == nullptr ||
        entry->requirement == OtisBootCapabilityRequirement::Disabled) {
      continue;
    }
    selected_count++;
    char value[48];
    snprintf(value, sizeof(value), "%s:%s",
             otis_boot_capability_requirement_name(entry->requirement),
             entry->reported
                 ? otis_boot_capability_outcome_name(entry->outcome)
                 : "pending");
    const bool capability_ready =
        entry->reported &&
        (entry->outcome == OtisBootCapabilityOutcome::Ready ||
         entry->outcome == OtisBootCapabilityOutcome::OptionalDegraded);
    emit_status("boot_capabilities",
                otis_boot_capability_name(capability), value,
                entry->outcome == OtisBootCapabilityOutcome::OptionalDegraded
                    ? OTIS_SEVERITY_WARN
                    : (capability_ready ? OTIS_SEVERITY_INFO
                                        : OTIS_SEVERITY_FATAL),
                capability_ready && entry->outcome ==
                                        OtisBootCapabilityOutcome::Ready
                    ? OTIS_FLAG_PROFILE_ASSUMPTION
                    : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  emit_status_u32("boot_capabilities", "selected_count", selected_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  boot_capability_status_emitted = true;
}

void emit_resource_ownership_status(void) {
  if (resource_ownership_status_emitted || !otis_transport_ready()) {
    return;
  }

  bool valid = otis_resource_registry_valid();
  bool complete = otis_resource_registry_complete();
  uint32_t registry_flags =
      valid && complete ? OTIS_FLAG_PROFILE_ASSUMPTION
                        : OTIS_FLAG_SOURCE_HEALTH_SUSPECT;

  emit_status("resource_registry", "version", "1", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("resource_registry", "valid", valid ? "true" : "false",
              valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_FATAL,
              registry_flags);
  emit_status("resource_registry", "complete", complete ? "true" : "false",
              complete ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              registry_flags);
  emit_status_u32("resource_registry", "claim_count",
                  otis_resource_registry_claim_count(), OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("resource_registry", "conflict_count",
                  otis_resource_registry_conflict_count(),
                  valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_FATAL,
                  registry_flags);
  emit_status_u32("resource_registry", "binding_failure_count",
                  otis_resource_registry_binding_failure_count(),
                  otis_resource_registry_binding_failure_count() == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_ERROR,
                  registry_flags);
  emit_status_u32(
      "resource_registry", "gpio_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::Gpio),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "irq_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::GpioIrq),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "pio_sm_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::PioStateMachine),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "pio_imem_claim_count",
      otis_resource_registry_claim_count(
          OtisResourceType::PioInstructionMemory),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "dma_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::DmaChannel),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "timer_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::Timer),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "clock_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::Clock),
      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);

  uint8_t claim_count = otis_resource_registry_claim_count();
  for (uint8_t i = 0; i < claim_count; ++i) {
    const OtisResourceClaim *claim = otis_resource_registry_claim_at(i);
    if (claim == nullptr) {
      continue;
    }
    char key[16];
    char value[160];
    snprintf(key, sizeof(key), "claim_%02u", i);
    snprintf(value, sizeof(value), "%s:%u:%u:%u:%s:%s:%s",
             otis_resource_type_name(claim->type), claim->instance,
             claim->index, claim->span, claim->owner, claim->role,
             claim->bound ? "bound" : "pending");
    emit_status("resource_registry", key, value,
                claim->bound ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                claim->bound ? OTIS_FLAG_PROFILE_ASSUMPTION
                             : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  resource_ownership_status_emitted = true;
}

void emit_protocol_banner_if_serial_ready(void) {
  if (runtime_state.boot.protocol_banner_emitted ||
      !otis_transport_ready()) {
    return;
  }

  if (runtime_state.boot.serial_absent_warn_pending) {
    // Establish a fresh record boundary in case the USB core retained any
    // prefix from writes attempted before the late host opened the port.
    otis_transport_write_cstr("\r\n");
  }
  emit_boot_records_if_serial_ready();
#if OTIS_ENABLE_RP2040_BOOT_DIAG
  emitRp2040BootDiag(Serial);
#endif
  otis_emit_csv_headers();
  otis_phase4_observe_preview_emit_headers();
  runtime_state.boot.protocol_banner_emitted = true;
}

void emit_periodic_status(void) {
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.periodic.last_status_ms) <
      kStatusPeriodMs) {
    return;
  }
  runtime_state.periodic.last_status_ms = now_ms;

  uint32_t capture_dropped_count = otis_capture_ring_dropped_count();
  uint32_t boundary_dropped_count =
      otis_pps_count_boundary_ring_dropped_count();
  uint32_t drop_flag = OTIS_FLAG_NONE;
  if (capture_dropped_count || boundary_dropped_count) {
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
    drop_flag = OTIS_FLAG_CAPTURE_OVERFLOW_NEARBY;
#else
    drop_flag = OTIS_FLAG_CAPTURE_RING_OVERRUN;
#endif
  }

  emit_status_u32("system", "uptime_seconds", now_ms / 1000u,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("capture", "event_count",
                  runtime_state.capture.emitted_event_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("capture", "dropped_count", capture_dropped_count,
                  capture_dropped_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
                  drop_flag);
  emit_status_u32(
      "capture", "pps_count_boundary_dropped_count",
      boundary_dropped_count,
      boundary_dropped_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
      boundary_dropped_count ? OTIS_FLAG_CAPTURE_RING_OVERRUN
                             : OTIS_FLAG_NONE);
  emit_status_u32("capture", "error_flags", drop_flag,
                  capture_dropped_count || boundary_dropped_count
                      ? OTIS_SEVERITY_WARN
                      : OTIS_SEVERITY_INFO,
                  drop_flag);
  otis_count_observation_emit_status(&runtime_state, &status_emit_context);
  otis_phase4_observe_preview_emit_status(&status_emit_context);
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_IRQ
  OtisCaptureIrqReferenceStats d14_stats;
  otis_capture_irq_get_reference_stats(&d14_stats);
  emit_status_u32("pps_d14", "raw_edge_count", d14_stats.d14_raw_edge_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("pps_d14", "accepted_pps_count",
                  d14_stats.d14_accepted_pps_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("pps_d14", "rejected_short_count",
                  d14_stats.d14_rejected_short_count,
                  d14_stats.d14_rejected_short_count ? OTIS_SEVERITY_WARN
                                                     : OTIS_SEVERITY_INFO,
                  d14_stats.d14_rejected_short_count ? OTIS_FLAG_PULSE_TOO_NARROW
                                                     : OTIS_FLAG_NONE);
  emit_status_u32("pps_d14", "rejected_long_count",
                  d14_stats.d14_rejected_long_count,
                  d14_stats.d14_rejected_long_count ? OTIS_SEVERITY_WARN
                                                    : OTIS_SEVERITY_INFO,
                  d14_stats.d14_rejected_long_count ? OTIS_FLAG_PULSE_TOO_WIDE
                                                    : OTIS_FLAG_NONE);
  emit_status_u64_decimal("pps_d14", "last_raw_timestamp",
                          d14_stats.d14_last_raw_timestamp, OTIS_SEVERITY_INFO,
                          OTIS_FLAG_NONE);
  emit_status_u64_decimal("pps_d14", "last_raw_interval",
                          d14_stats.d14_last_raw_interval, OTIS_SEVERITY_INFO,
                          OTIS_FLAG_NONE);
  emit_status_u64_decimal("pps_d14", "last_accepted_timestamp",
                          d14_stats.d14_last_accepted_timestamp,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("pps_d14", "sampled_high_count",
                  d14_stats.d14_sampled_high_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("pps_d14", "sampled_low_count",
                  d14_stats.d14_sampled_low_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
#endif
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  OtisPpsDualObserverStats d10_stats;
  otis_pps_dual_observer_get_stats(&d10_stats);
  int32_t raw_delta = (int32_t)d14_stats.d14_raw_edge_count -
                      (int32_t)d10_stats.d10_raw_edge_count;
  const char *agreement = "MATCHING";
  if (d14_stats.d14_raw_edge_count == 0u || d10_stats.d10_raw_edge_count == 0u) {
    agreement = "INSUFFICIENT_DATA";
  } else if (raw_delta > 1) {
    agreement = "D14_EXCESS";
  } else if (raw_delta < -1) {
    agreement = "D10_EXCESS";
  } else if (d14_stats.d14_rejected_short_count && d10_stats.d10_short_interval_count) {
    agreement = "BOTH_BURSTING";
  }
  emit_status_u32("pps_d10", "raw_edge_count", d10_stats.d10_raw_edge_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal("pps_d10", "last_edge_timestamp",
                          d10_stats.d10_last_edge_timestamp, OTIS_SEVERITY_INFO,
                          OTIS_FLAG_NONE);
  emit_status_u64_decimal("pps_d10", "last_interval",
                          d10_stats.d10_last_interval, OTIS_SEVERITY_INFO,
                          OTIS_FLAG_NONE);
  emit_status_u32("pps_d10", "short_interval_count",
                  d10_stats.d10_short_interval_count,
                  d10_stats.d10_short_interval_count ? OTIS_SEVERITY_WARN
                                                     : OTIS_SEVERITY_INFO,
                  d10_stats.d10_short_interval_count ? OTIS_FLAG_PULSE_TOO_NARROW
                                                     : OTIS_FLAG_NONE);
  emit_status_u32("pps_d10", "sampled_high_count",
                  d10_stats.d10_sampled_high_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("pps_d10", "sampled_low_count",
                  d10_stats.d10_sampled_low_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("pps_d10", "buffer_overflow_count",
                  d10_stats.d10_buffer_overflow_count,
                  d10_stats.d10_buffer_overflow_count ? OTIS_SEVERITY_WARN
                                                      : OTIS_SEVERITY_INFO,
                  d10_stats.d10_buffer_overflow_count ? OTIS_FLAG_CAPTURE_RING_OVERRUN
                                                      : OTIS_FLAG_NONE);
  emit_status_i32("pps_dual_observer", "d14_raw_minus_d10_raw",
                  raw_delta, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("pps_dual_observer", "agreement_state", agreement,
              strcmp(agreement, "MATCHING") == 0 ? OTIS_SEVERITY_INFO
                                                 : OTIS_SEVERITY_WARN,
              strcmp(agreement, "MATCHING") == 0 ? OTIS_FLAG_NONE
                                                 : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
  emit_status("pps_dual_observer", "burst_active",
              d10_stats.pps_burst_active ? "true" : "false",
              d10_stats.pps_burst_active ? OTIS_SEVERITY_WARN
                                         : OTIS_SEVERITY_INFO,
              d10_stats.pps_burst_active ? OTIS_FLAG_RATE_TOO_HIGH
                                         : OTIS_FLAG_NONE);
  emit_status_u32("pps_dual_observer", "burst_count",
                  d10_stats.pps_burst_count,
                  d10_stats.pps_burst_count ? OTIS_SEVERITY_WARN
                                            : OTIS_SEVERITY_INFO,
                  d10_stats.pps_burst_count ? OTIS_FLAG_RATE_TOO_HIGH
                                            : OTIS_FLAG_NONE);
#endif
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  OtisCaptureBackendStats backend_stats;
  otis_capture_backend_get_stats(&backend_stats);
  emit_status_u32("capture", "pio_fifo_drained_event_count",
                  backend_stats.pio_edges, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("capture", "pio_fifo_empty_count",
                  backend_stats.pio_fifo_empty_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("capture", "pio_fifo_overflow_drop_count",
                  backend_stats.backend_overflows,
                  backend_stats.backend_overflows ? OTIS_SEVERITY_WARN
                                                  : OTIS_SEVERITY_INFO,
                  backend_stats.backend_overflows
                      ? OTIS_FLAG_CAPTURE_OVERFLOW_NEARBY
                      : OTIS_FLAG_NONE);
  emit_status_u32("capture", "pio_fifo_max_drain_batch",
                  backend_stats.pio_fifo_max_drain_batch, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
#endif
}

bool begin_edge_capture_backend(uint32_t gpio, uint32_t channel_id,
                                bool reference_record, int interrupt_mode) {
  OtisCaptureBackendConfig config = {
      gpio,
      channel_id,
      reference_record,
      interrupt_mode,
      emit_captured_edge,
  };
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  return otis_capture_backend_begin(OtisCaptureBackendKind::PioEdgeQueue,
                                    config);
#else
  return otis_capture_backend_begin(OtisCaptureBackendKind::GpioIrq, config);
#endif
}

bool begin_pps_dual_observer_if_enabled(void) {
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  bool ok = otis_pps_dual_observer_begin(OTIS_PIN_GENERIC_EVENT);
  emit_status("pps_dual_observer", "init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_PROFILE_ASSUMPTION : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  return ok;
#else
  return true;
#endif
}

void emit_synthetic_fixture(void) {
  otis_emit_raw_event(OTIS_RECORD_EVT, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_GENERIC_EVENT, OTIS_EDGE_RISING,
                      1600001234ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_EVT, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_GENERIC_EVENT, OTIS_EDGE_FALLING,
                      1600001872ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_REF, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_PPS_REFERENCE, OTIS_EDGE_RISING,
                      1616000000ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_raw_event(OTIS_RECORD_REF, runtime_state.sequences.event_seq++,
                      OTIS_CHANNEL_PPS_REFERENCE, OTIS_EDGE_RISING,
                      1632000000ull, OTIS_DOMAIN_RP2040_TIMER0,
                      OTIS_FLAG_NONE);
  otis_emit_count_observation(runtime_state.sequences.count_seq++,
                              OTIS_CHANNEL_OSC_OBSERVATION, 1600000000ull,
                              1616000000ull, OTIS_DOMAIN_RP2040_TIMER0,
                              16000000ull, OTIS_EDGE_RISING,
                              OTIS_DOMAIN_H0_TCXO_16MHZ, OTIS_FLAG_NONE);
  runtime_state.capture.emitted_event_count = 4;
}

void configure_synthetic_usb_mode(void) {
  emit_synthetic_fixture();
}

void configure_gpio_loopback_mode(void) {
  emit_status("pins", "gpio_loopback_output", "D7", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("wiring", "gpio_loopback", "D7_to_D10", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  bool ok = capability_ready(OtisBootCapability::SparseCapture);
  emit_status("capture", "pio_init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_PROFILE_ASSUMPTION : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("capture", "pio_gpio", OTIS_PIN_GENERIC_EVENT,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "pio_edge", "R", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  if (ok) {
    emit_status_u32("capture", "pio_block", 0u, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("capture", "pio_sm",
                    (uint32_t)otis_capture_pio_state_machine(),
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  }
#endif
}

void configure_gps_pps_mode(void) {
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  bool ok = capability_ready(OtisBootCapability::PpsCapture);
  emit_status("capture", "pio_init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_PROFILE_ASSUMPTION : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("capture", "pio_gpio", OTIS_PIN_PPS_REFERENCE,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "pio_edge", "R", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  if (ok) {
    emit_status_u32("capture", "pio_block", 0u, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("capture", "pio_sm",
                    (uint32_t)otis_capture_pio_state_machine(),
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  }
#endif
}

void configure_tcxo_observe_mode(void) {
  // In TCXO observe mode the edge-capture backend, including PIO FIFO when
  // enabled, remains on sparse PPS input. Raw CXO input on D8 / GPIO20 is
  // handled by the selected count-observation backend, not FIFO records.
#if OTIS_CAPTURE_BACKEND == OTIS_CAPTURE_BACKEND_PIO_FIFO
  bool ok = capability_ready(OtisBootCapability::PpsCapture);
  emit_status("capture", "pio_init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_PROFILE_ASSUMPTION : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("capture", "pio_gpio", OTIS_PIN_PPS_REFERENCE,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("capture", "pio_edge", "R", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  if (ok) {
    emit_status_u32("capture", "pio_block", 0u, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("capture", "pio_sm",
                    (uint32_t)otis_capture_pio_state_machine(),
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  }
#endif
}

void emit_dac_status(const char *component) {
  OtisDacAd5693rStatus status;
  otis_dac_ad5693r_get_status(&status);
  emit_status(component, "enabled", status.enabled ? "true" : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(component, "initialized", status.initialized ? "true" : "false",
              status.initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.enabled ? OTIS_FLAG_NONE : OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(component, "last_write_ok", status.last_write_ok ? "true" : "false",
              status.last_write_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status_u32(component, "i2c_address", status.i2c_address,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex(component, "min_code", status.min_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex(component, "max_code", status.max_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u16_hex(component, "last_requested_code",
                      status.last_requested_code, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_NONE);
  emit_status_u16_hex(component, "last_applied_code", status.last_applied_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status(component, "gain_mode", status.gain_mode, OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status(component, "reference_mode", status.reference_mode,
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}

#if OTIS_ENABLE_H1_DAC_SWEEP
struct H1DacSweepStep {
  uint16_t code;
  uint32_t dwell_ms;
};

struct H1DacSweepState {
  H1DacSweepStep steps[OTIS_H1_DAC_SWEEP_MAX_STEPS];
  uint8_t step_count;
  uint8_t active_step;
  bool running;
  bool pending_start;
  bool dwell_active;
  uint32_t dwell_started_ms;
  uint16_t last_requested_code;
  uint16_t last_applied_code;
  uint32_t last_dwell_ms;
  const char *profile_name;
};

H1DacSweepState h1_dac_sweep = {
    {},
    0,
    0,
    false,
    false,
    false,
    0,
    0,
    0,
    0,
    "none",
};

uint16_t h1_dac_sweep_center_code(void) {
  return (uint16_t)(((uint32_t)OTIS_DAC_MIN_CODE +
                    (uint32_t)OTIS_DAC_MAX_CODE) /
                   2u);
}

bool h1_dac_sweep_clamps_configured(void) {
  return OTIS_DAC_MIN_CODE > 0u && OTIS_DAC_MAX_CODE < 0xFFFFu &&
         OTIS_DAC_MIN_CODE <= OTIS_DAC_MAX_CODE;
}

void emit_sweep_record(int32_t step_index, uint16_t requested_code,
                       uint16_t applied_code, bool clamped,
                       uint32_t dwell_ms, const char *event,
                       uint32_t flags) {
  otis_emit_dac_step(runtime_state.sequences.dac_seq++, millis(), step_index,
                     requested_code, applied_code, clamped, "", "", dwell_ms,
                     event, flags);
}

void emit_sweep_status(void) {
  emit_status("sweep", "enabled", "true", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("sweep", "running", h1_dac_sweep.running ? "true" : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("sweep", "pending_start",
              h1_dac_sweep.pending_start ? "true" : "false",
              h1_dac_sweep.pending_start ? OTIS_SEVERITY_WARN
                                         : OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("sweep", "profile", h1_dac_sweep.profile_name,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("sweep", "step_count", h1_dac_sweep.step_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("sweep", "active_step", h1_dac_sweep.active_step,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("sweep", "clamps_configured",
              h1_dac_sweep_clamps_configured() ? "true" : "false",
              h1_dac_sweep_clamps_configured() ? OTIS_SEVERITY_INFO
                                               : OTIS_SEVERITY_WARN,
              OTIS_FLAG_PROFILE_ASSUMPTION);
}

bool h1_dac_sweep_add_step(uint16_t code, uint32_t dwell_ms) {
  if (!h1_dac_sweep_clamps_configured()) {
    emit_status("sweep", "add", "rejected_clamps_not_configured",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_sweep_record(-1, code, otis_dac_ad5693r_clamp_code(code), true,
                      dwell_ms, "safety_reject", OTIS_FLAG_PROFILE_ASSUMPTION);
    return false;
  }
  if (h1_dac_sweep.step_count >= OTIS_H1_DAC_SWEEP_MAX_STEPS) {
    emit_status("sweep", "add", "rejected_full", OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
    return false;
  }
  if (otis_dac_ad5693r_clamp_code(code) != code) {
    emit_sweep_record(-1, code, otis_dac_ad5693r_clamp_code(code), true,
                      dwell_ms, "safety_reject", OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("sweep", "add", "rejected_outside_clamps",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    return false;
  }
  h1_dac_sweep.steps[h1_dac_sweep.step_count++] = {code, dwell_ms};
  h1_dac_sweep.profile_name = "custom";
  emit_sweep_record((int32_t)(h1_dac_sweep.step_count - 1u), code, code, false,
                    dwell_ms, "step_added", OTIS_FLAG_NONE);
  return true;
}

void h1_dac_sweep_clear(void) {
  h1_dac_sweep.running = false;
  h1_dac_sweep.pending_start = false;
  h1_dac_sweep.dwell_active = false;
  h1_dac_sweep.active_step = 0;
  h1_dac_sweep.step_count = 0;
  h1_dac_sweep.profile_name = "none";
  emit_sweep_record(-1, 0, 0, false, 0, "clear", OTIS_FLAG_NONE);
}

bool h1_dac_sweep_load_profile(const char *profile_name) {
  if (!h1_dac_sweep_clamps_configured()) {
    emit_status("sweep", "load", "rejected_clamps_not_configured",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_sweep_record(-1, 0, 0, false, 0, "safety_reject",
                      OTIS_FLAG_PROFILE_ASSUMPTION);
    return false;
  }

  uint32_t candidate_codes[9];
  uint8_t count = 0;
  uint16_t center = h1_dac_sweep_center_code();
  uint32_t step = (uint32_t)OTIS_H1_DAC_SWEEP_TINY_STEP_CODES;
  const uint32_t dwell_ms = OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS;
  uint32_t profile_dwell_ms = dwell_ms;
  const char *loaded_name = nullptr;

  if (strcmp(profile_name, "CENTER_ONLY") == 0) {
    candidate_codes[count++] = center;
    loaded_name = "center_only";
  } else if (strcmp(profile_name, "TINY_PLUS_MINUS_1") == 0) {
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center + step;
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center - step;
    candidate_codes[count++] = center;
    loaded_name = "tiny_plus_minus_1";
  } else if (strcmp(profile_name, "TINY_PLUS_MINUS_2") == 0) {
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center + step;
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center - step;
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center + (2u * step);
    candidate_codes[count++] = center;
    candidate_codes[count++] = (uint32_t)center - (2u * step);
    candidate_codes[count++] = center;
    loaded_name = "tiny_plus_minus_2";
  } else if (strcmp(profile_name, "SLOPE_CENTER_EDGE_300S") == 0) {
    profile_dwell_ms = OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS;
    candidate_codes[count++] = center;
    candidate_codes[count++] = OTIS_DAC_MAX_CODE;
    candidate_codes[count++] = center;
    candidate_codes[count++] = OTIS_DAC_MIN_CODE;
    candidate_codes[count++] = center;
    loaded_name = "slope_center_edge_300s";
  } else if (strcmp(profile_name, "SLOPE_REPEAT_300S") == 0) {
    profile_dwell_ms = OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS;
    uint32_t half_high = (uint32_t)center + ((uint32_t)OTIS_DAC_MAX_CODE -
                                            (uint32_t)center) / 2u;
    uint32_t half_low = (uint32_t)center - ((uint32_t)center -
                                           (uint32_t)OTIS_DAC_MIN_CODE) / 2u;
    candidate_codes[count++] = center;
    candidate_codes[count++] = half_high;
    candidate_codes[count++] = center;
    candidate_codes[count++] = half_low;
    candidate_codes[count++] = center;
    candidate_codes[count++] = OTIS_DAC_MAX_CODE;
    candidate_codes[count++] = center;
    candidate_codes[count++] = OTIS_DAC_MIN_CODE;
    candidate_codes[count++] = center;
    loaded_name = "slope_repeat_300s";
  } else {
    emit_status("sweep", "load", "rejected_unknown_profile",
                OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
    return false;
  }

  for (uint8_t index = 0; index < count; ++index) {
    if (candidate_codes[index] > 0xFFFFu ||
        otis_dac_ad5693r_clamp_code((uint16_t)candidate_codes[index]) !=
            (uint16_t)candidate_codes[index]) {
      uint16_t requested = candidate_codes[index] > 0xFFFFu
                               ? 0xFFFFu
                               : (uint16_t)candidate_codes[index];
      emit_sweep_record(index, requested,
                        otis_dac_ad5693r_clamp_code(requested), true,
                        profile_dwell_ms, "safety_reject",
                        OTIS_FLAG_PROFILE_ASSUMPTION);
      emit_status("sweep", "load", "rejected_profile_exceeds_clamps",
                  OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
      return false;
    }
  }

  h1_dac_sweep_clear();
  for (uint8_t index = 0; index < count; ++index) {
    h1_dac_sweep.steps[index] = {(uint16_t)candidate_codes[index],
                                 profile_dwell_ms};
    emit_sweep_record(index, (uint16_t)candidate_codes[index],
                      (uint16_t)candidate_codes[index], false,
                      profile_dwell_ms, "profile_step", OTIS_FLAG_NONE);
  }
  h1_dac_sweep.step_count = count;
  h1_dac_sweep.profile_name = loaded_name;
  emit_status("sweep", "load", "ok", OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("sweep", "profile", loaded_name, OTIS_SEVERITY_INFO,
              OTIS_FLAG_NONE);
  emit_sweep_record(-1, center, center, false, profile_dwell_ms,
                    "profile_loaded", OTIS_FLAG_NONE);
  return true;
}

bool h1_dac_sweep_apply_active_step(const char *event_name) {
  if (h1_dac_sweep.active_step >= h1_dac_sweep.step_count) {
    emit_status("sweep", "step", "rejected_no_step", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
    return false;
  }
  H1DacSweepStep step = h1_dac_sweep.steps[h1_dac_sweep.active_step];
  uint16_t clamped = otis_dac_ad5693r_clamp_code(step.code);
  if (clamped != step.code) {
    emit_sweep_record(h1_dac_sweep.active_step, step.code, clamped, true,
                      step.dwell_ms, "safety_reject",
                      OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("sweep", "step", "rejected_outside_clamps",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    h1_dac_sweep.running = false;
    h1_dac_sweep.dwell_active = false;
    return false;
  }
  if (!otis_dac_ad5693r_is_enabled()) {
    emit_sweep_record(h1_dac_sweep.active_step, step.code, clamped, false,
                      step.dwell_ms, "rejected_disabled",
                      OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    return false;
  }
  if (!otis_dac_ad5693r_is_initialized()) {
    emit_sweep_record(h1_dac_sweep.active_step, step.code, clamped, false,
                      step.dwell_ms, "rejected_not_initialized",
                      OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    return false;
  }

  bool ok = otis_dac_ad5693r_set_raw(step.code);
  if (ok) {
    otis_phase4_observe_preview_on_dac_applied(
        clamped, otis_capture_ticks_now());
  }
  h1_dac_sweep.last_requested_code = step.code;
  h1_dac_sweep.last_applied_code = ok ? clamped : h1_dac_sweep.last_applied_code;
  h1_dac_sweep.last_dwell_ms = step.dwell_ms;
  h1_dac_sweep.dwell_started_ms = millis();
  h1_dac_sweep.dwell_active = ok;
  emit_sweep_record(h1_dac_sweep.active_step, step.code, clamped, false,
                    step.dwell_ms, ok ? event_name : "write_failed",
                    ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  if (ok) {
    emit_sweep_record(h1_dac_sweep.active_step, step.code, clamped, false,
                      step.dwell_ms, "dwell_start", OTIS_FLAG_NONE);
  }
  return ok;
}

void h1_dac_sweep_start(void) {
  if (h1_dac_sweep.step_count == 0u) {
    emit_status("sweep", "start", "rejected_no_profile", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
    return;
  }
  if (!runtime_state.tcxo.valid_for_control) {
    h1_dac_sweep.pending_start = true;
    h1_dac_sweep.running = false;
    h1_dac_sweep.dwell_active = false;
    h1_dac_sweep.active_step = 0;
    emit_sweep_record(-1, 0, 0, false, 0, "pending_fc0_valid_for_control",
                      OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("sweep", "start", "pending_fc0_valid_for_control",
                OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    return;
  }
  h1_dac_sweep.pending_start = false;
  h1_dac_sweep.running = true;
  h1_dac_sweep.active_step = 0;
  h1_dac_sweep.dwell_active = false;
  emit_sweep_record(-1, 0, 0, false, 0, "start", OTIS_FLAG_NONE);
  if (!h1_dac_sweep_apply_active_step("step_apply")) {
    h1_dac_sweep.running = false;
  }
}

void h1_dac_sweep_stop(const char *event_name) {
  if (h1_dac_sweep.dwell_active) {
    emit_sweep_record(h1_dac_sweep.active_step, h1_dac_sweep.last_requested_code,
                      h1_dac_sweep.last_applied_code, false,
                      h1_dac_sweep.last_dwell_ms, "dwell_complete",
                      OTIS_FLAG_NONE);
  }
  h1_dac_sweep.running = false;
  h1_dac_sweep.pending_start = false;
  h1_dac_sweep.dwell_active = false;
  emit_sweep_record(-1, h1_dac_sweep.last_requested_code,
                    h1_dac_sweep.last_applied_code, false,
                    h1_dac_sweep.last_dwell_ms, event_name, OTIS_FLAG_NONE);
}

void h1_dac_sweep_manual_step(void) {
  if (h1_dac_sweep.step_count == 0u) {
    emit_status("sweep", "step", "rejected_no_profile", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
    return;
  }
  if (h1_dac_sweep.dwell_active) {
    emit_sweep_record(h1_dac_sweep.active_step, h1_dac_sweep.last_requested_code,
                      h1_dac_sweep.last_applied_code, false,
                      h1_dac_sweep.last_dwell_ms, "dwell_complete",
                      OTIS_FLAG_NONE);
    h1_dac_sweep.active_step++;
    h1_dac_sweep.dwell_active = false;
  }
  if (h1_dac_sweep.active_step >= h1_dac_sweep.step_count) {
    h1_dac_sweep.active_step = 0;
  }
  h1_dac_sweep_apply_active_step("manual_step");
}

void service_h1_dac_sweep(void) {
  if (h1_dac_sweep.pending_start && runtime_state.tcxo.valid_for_control) {
    h1_dac_sweep.pending_start = false;
    h1_dac_sweep.running = true;
    h1_dac_sweep.active_step = 0;
    h1_dac_sweep.dwell_active = false;
    emit_sweep_record(-1, 0, 0, false, 0, "start_after_fc0_ready",
                      OTIS_FLAG_NONE);
    if (!h1_dac_sweep_apply_active_step("step_apply")) {
      h1_dac_sweep.running = false;
    }
    return;
  }
  if (!h1_dac_sweep.running || !h1_dac_sweep.dwell_active) {
    return;
  }
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - h1_dac_sweep.dwell_started_ms) <
      h1_dac_sweep.last_dwell_ms) {
    return;
  }

  emit_sweep_record(h1_dac_sweep.active_step, h1_dac_sweep.last_requested_code,
                    h1_dac_sweep.last_applied_code, false,
                    h1_dac_sweep.last_dwell_ms, "dwell_complete",
                    OTIS_FLAG_NONE);
  h1_dac_sweep.active_step++;
  h1_dac_sweep.dwell_active = false;
  if (h1_dac_sweep.active_step >= h1_dac_sweep.step_count) {
    h1_dac_sweep_stop("complete");
    return;
  }
  if (!h1_dac_sweep_apply_active_step("step_apply")) {
    h1_dac_sweep.running = false;
  }
}

void emit_h1_dac_sweep_fc0_window(void) {
  if (!h1_dac_sweep.running && !h1_dac_sweep.dwell_active) {
    return;
  }
  emit_sweep_record(h1_dac_sweep.active_step, h1_dac_sweep.last_requested_code,
                    h1_dac_sweep.last_applied_code, false,
                    h1_dac_sweep.last_dwell_ms, "fc0_window",
                    OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
}
#endif

void configure_h1_ocxo_observe_mode(void) {
  emit_status("system", "h1_open_loop", "true", OTIS_SEVERITY_WARN,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("control", "gpsdo_steering", "not_implemented",
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  configure_tcxo_observe_mode();

#if OTIS_ENABLE_DAC_AD5693R
  bool ok = capability_ready(OtisBootCapability::Dac);
  emit_status("dac", "init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
  emit_status("dac", "init", "disabled", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  emit_dac_status("dac");
#if OTIS_ENABLE_ENV_SENSORS
  bool env_ok = capability_ready(OtisBootCapability::Sensors);
  emit_status("environment", "init", env_ok ? "ok" : "failed",
              env_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              env_ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
#else
  emit_status("environment", "init", "disabled", OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  emit_env_sensor_status();
#if OTIS_ENABLE_H1_DAC_SWEEP
  emit_sweep_status();
#endif
}

void format_env_float(float value, char *buffer, size_t buffer_size) {
  if (buffer == nullptr || buffer_size == 0) {
    return;
  }
  snprintf(buffer, buffer_size, "%.3f", static_cast<double>(value));
}

void emit_env_sample(const OtisEnvSample &sample,
                     uint64_t timestamp_ticks) {
  if (!sample.valid) {
    return;
  }
  if (strcmp(sample.role, "vcocxo_near") == 0) {
    otis_phase4_observe_preview_on_temperature(
        true, sample.temperature_c, timestamp_ticks);
  }
  char temperature[16];
  char humidity[16];
  char pressure[16];
  format_env_float(sample.temperature_c, temperature, sizeof(temperature));
  if (sample.has_humidity) {
    format_env_float(sample.relative_humidity_pct, humidity, sizeof(humidity));
  } else {
    humidity[0] = '\0';
  }
  if (sample.has_pressure) {
    format_env_float(sample.pressure_pa, pressure, sizeof(pressure));
  } else {
    pressure[0] = '\0';
  }
  otis_emit_environment(runtime_state.sequences.env_seq++,
                        timestamp_ticks, OTIS_DOMAIN_RP2040_TIMER0,
                        sample.source, sample.role, temperature, humidity,
                        pressure, OTIS_FLAG_NONE);
}

void service_environment_sensors(void) {
#if OTIS_ENABLE_ENV_SENSORS
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.periodic.last_env_sample_ms) <
      OTIS_ENV_SAMPLE_PERIOD_MS) {
    return;
  }
  runtime_state.periodic.last_env_sample_ms = now_ms;
  OtisEnvSample sample;
#if OTIS_ENABLE_ENV_SHT4X
  if (otis_env_sensors_read_sht4x(&sample)) {
    const uint64_t timestamp_ticks = otis_capture_ticks_now();
    emit_env_sample(sample, timestamp_ticks);
  } else {
    otis_phase4_observe_preview_on_temperature(
        false, 0.0f, otis_capture_ticks_now());
  }
#endif
#if OTIS_ENABLE_ENV_BMP280
  if (otis_env_sensors_read_bmp280(&sample)) {
    emit_env_sample(sample, otis_capture_ticks_now());
  }
#endif
#endif
}

void setup_mode(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_SYNTHETIC_USB
  configure_synthetic_usb_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  configure_gpio_loopback_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS
  configure_gps_pps_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE
  configure_tcxo_observe_mode();
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  configure_h1_ocxo_observe_mode();
#endif
}

void emit_run_mode_status_if_ready(void) {
  if (run_mode_status_emitted || !boot_capabilities.run_mode_marked ||
      !runtime_state.boot.protocol_banner_emitted ||
      !otis_transport_ready()) {
    return;
  }
  emit_common_boot_status();
  emit_h0_pin_status();
  setup_mode();
  emit_selected_capability_status();
  emit_resource_ownership_status();
  run_mode_status_emitted = true;
}

void boot_phase_reset_entry(void) {
  begin_boot_phase(BootPhase::ResetEntry);
#if OTIS_ENABLE_RP2040_BOOT_DIAG
  captureRp2040BootDiag();
#endif
  otisBootBreadcrumbBegin(BootPhase::ResetEntry);
  delay(kOtisBootInitialDelayMs);  // boring but useful during bring-up
  complete_boot_phase(BootPhase::ResetEntry);
}

void boot_phase_early_init(void) {
  begin_boot_phase(BootPhase::EarlyInit);
  const bool valid = otis_resource_registry_begin();
  if (!valid) {
#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
    otis_pseudo_pps_latch_resource_fault();
#endif
    otis_boot_capability_record(
        &boot_capabilities, OtisBootCapability::ResourceRegistry,
        OtisBootCapabilityOutcome::FatalConflict);
  }
  complete_boot_phase(BootPhase::EarlyInit);
}

void boot_phase_clocks_init(void) {
  begin_boot_phase(BootPhase::ClocksInit);
#if OTIS_FORCE_BOOT_FAIL_BEFORE_CLOCKS
  halt_boot(BootFatal::ForcedBeforeClocks, BootPhase::ClocksInit);
#endif
  record_capability_result(OtisBootCapability::Timebase,
                           otis_timebase_begin());
  complete_boot_phase(BootPhase::ClocksInit);
}

void boot_phase_gpio_init(void) {
  begin_boot_phase(BootPhase::GpioInit);
  otis_status_led_begin();
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  pinMode(OTIS_PIN_GPIO_LOOPBACK_OUTPUT, OUTPUT);
  digitalWrite(OTIS_PIN_GPIO_LOOPBACK_OUTPUT, LOW);
  pinMode(OTIS_PIN_GENERIC_EVENT, INPUT_PULLDOWN);
#elif OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  pinMode(OTIS_PIN_PPS_REFERENCE, INPUT_PULLDOWN);
#endif
#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  pinMode(OTIS_PIN_PSEUDO_PPS_OUTPUT, INPUT);
#endif
  complete_boot_phase(BootPhase::GpioInit);
}

void boot_phase_capture_init(void) {
  begin_boot_phase(BootPhase::CaptureInit);
#if OTIS_FORCE_BOOT_FAIL_BEFORE_CAPTURE
  halt_boot(BootFatal::ForcedBeforeCapture, BootPhase::CaptureInit);
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  const bool ready =
      begin_edge_capture_backend(OTIS_PIN_GENERIC_EVENT,
                                 OTIS_CHANNEL_GENERIC_EVENT, false, CHANGE);
  record_capability_result(OtisBootCapability::SparseCapture, ready);
#endif
  complete_boot_phase(BootPhase::CaptureInit);
}

void boot_phase_timer_init(void) {
  begin_boot_phase(BootPhase::TimerInit);
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  runtime_state.tcxo.startup_inhibit_start_ms = millis();
  runtime_state.tcxo.startup_inhibit_active = true;
  runtime_state.tcxo.valid_for_control = false;
  runtime_state.tcxo.control_clean_window_count = 0;
  runtime_state.tcxo.fault_after_startup = false;
  OtisCountObservationConfig count_config = count_observation_config();
  const bool ready = otis_count_observation_begin(
      &runtime_state, &status_emit_context, &count_config);
  record_capability_result(OtisBootCapability::CountBackend, ready);
#endif
#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  const bool pseudo_pps_ready = otis_pseudo_pps_begin();
  record_capability_result(OtisBootCapability::PseudoPpsGenerator,
                           pseudo_pps_ready);
#endif
  complete_boot_phase(BootPhase::TimerInit);
}

void boot_phase_pps_input_init(void) {
  begin_boot_phase(BootPhase::PpsInputInit);
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  const bool pps_ready =
      begin_edge_capture_backend(OTIS_PIN_PPS_REFERENCE,
                                 OTIS_CHANNEL_PPS_REFERENCE, true, RISING);
  record_capability_result(OtisBootCapability::SparseCapture, pps_ready);
  record_capability_result(OtisBootCapability::PpsCapture, pps_ready);
#if OTIS_ENABLE_PPS_DUAL_OBSERVER
  const bool witness_ready = begin_pps_dual_observer_if_enabled();
  record_capability_result(OtisBootCapability::PpsWitness, witness_ready);
#endif
#endif
  complete_boot_phase(BootPhase::PpsInputInit);
}

void boot_phase_ring_buffers_init(void) {
  begin_boot_phase(BootPhase::RingBuffersInit);
  otis_capture_ring_reset();
  otis_pps_count_boundary_ring_reset();
  record_capability_result(OtisBootCapability::RingBuffers, true);
  complete_boot_phase(BootPhase::RingBuffersInit);
}

void boot_phase_serial_init(void) {
  begin_boot_phase(BootPhase::SerialInit);
  transport_started = otis_transport_begin(kOtisSerialBaud);
  wait_for_serial_or_timeout();
  record_capability_result(OtisBootCapability::Transport, transport_started);
  record_capability_result(OtisBootCapability::HostConnection,
                           runtime_state.boot.serial_ready);

  otis_status_led_boot_test();
  otis_status_led_set(OTIS_SYSTEM_STATE_BOOT_STARTING);
  otis_status_led_poll(millis());
  complete_boot_phase(BootPhase::SerialInit);
}

void boot_phase_protocol_banner(void) {
  begin_boot_phase(BootPhase::ProtocolBanner);
  emit_protocol_banner_if_serial_ready();
  complete_boot_phase(BootPhase::ProtocolBanner);
}

void boot_phase_peripherals_init(void) {
  begin_boot_phase(BootPhase::PeripheralsInit);
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE && \
    OTIS_ENABLE_DAC_AD5693R
  const bool dac_ready = otis_dac_ad5693r_begin();
  record_capability_result(OtisBootCapability::Dac, dac_ready);
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE && \
    OTIS_ENABLE_ENV_SENSORS && \
    (OTIS_ENABLE_ENV_SHT4X || OTIS_ENABLE_ENV_BMP280)
  const bool sensors_ready = otis_env_sensors_begin();
  record_capability_result(OtisBootCapability::Sensors, sensors_ready);
#endif
  complete_boot_phase(BootPhase::PeripheralsInit);
}

void boot_phase_preview_init(void) {
  begin_boot_phase(BootPhase::PreviewInit);
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  const bool preview_ready =
      otis_phase4_observe_preview_begin(otis_capture_ticks_now());
  record_capability_result(OtisBootCapability::Phase4Preview, preview_ready);
#endif
  complete_boot_phase(BootPhase::PreviewInit);
}

void boot_phase_capability_audit(void) {
  begin_boot_phase(BootPhase::CapabilityAudit);
  const bool registry_valid = otis_resource_registry_valid();
  const bool registry_complete = otis_resource_registry_complete();
  otis_boot_capability_record(
      &boot_capabilities, OtisBootCapability::ResourceRegistry,
      otis_boot_registry_outcome(registry_valid, registry_complete));
  complete_boot_phase(BootPhase::CapabilityAudit);
}

void boot_phase_run_mode(void) {
#if OTIS_FORCE_BOOT_FAIL_BEFORE_RUN_MODE
  halt_boot(BootFatal::ForcedBeforeRunMode, BootPhase::RunMode);
#endif
  if (!otis_boot_capability_mark_run_mode(&boot_capabilities)) {
    const BootFatal fatal =
        otis_boot_capability_has_fatal_conflict(&boot_capabilities)
            ? BootFatal::ResourceOwnershipConflict
            : BootFatal::RequiredCapabilityUnavailable;
    emit_selected_capability_status();
    emit_resource_ownership_status();
    halt_boot(fatal, BootPhase::CapabilityAudit);
  }
  enter_boot_phase(BootPhase::RunMode);
  runtime_state.boot.degraded =
      otis_boot_capability_degraded(&boot_capabilities);
  runtime_state.periodic.last_status_ms = millis();
  otis_status_led_set(OTIS_SYSTEM_STATE_USB_CONFIG_DEBUG);
  otisBootBreadcrumbMarkRunMode();
  emit_run_mode_status_if_ready();
}

void service_loopback_output(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.loopback.last_toggle_ms) >=
      kLoopbackTogglePeriodMs) {
    runtime_state.loopback.last_toggle_ms = now_ms;
    runtime_state.loopback.output_high = !runtime_state.loopback.output_high;
    digitalWrite(OTIS_PIN_GPIO_LOOPBACK_OUTPUT,
                 runtime_state.loopback.output_high ? HIGH : LOW);
  }
#endif
}

void service_tcxo_gate(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  OtisCountObservationConfig count_config = count_observation_config();
  if (otis_count_observation_service(&runtime_state, &status_emit_context,
                                     &count_config)) {
    OtisDacAd5693rStatus dac_status;
    otis_dac_ad5693r_get_status(&dac_status);
    OtisPhase4LiveDacState phase4_dac = {
        dac_status.last_write_ok &&
            dac_status.last_requested_code == dac_status.last_applied_code,
        dac_status.last_applied_code,
    };
    otis_phase4_observe_preview_on_count(
        runtime_state.sequences.count_seq - 1u, &runtime_state, &phase4_dac);
#if OTIS_ENABLE_H1_DAC_SWEEP && \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
    emit_h1_dac_sweep_fc0_window();
#endif
  }
#endif
}

void emit_fc0_status(void) {
  emit_status("fc0", "valid",
              runtime_state.tcxo.last_observation_valid ? "true" : "false",
              runtime_state.tcxo.last_observation_valid ? OTIS_SEVERITY_INFO
                                                        : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status("fc0", "fc0_observed_valid",
              runtime_state.tcxo.last_observation_valid ? "true" : "false",
              runtime_state.tcxo.last_observation_valid ? OTIS_SEVERITY_INFO
                                                        : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status("fc0", "measurement_mode",
              otis_count_observation_measurement_mode(),
              OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("fc0", "measure_period_ms", kTcxoMeasurePeriodMs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("fc0", "gate_period_us", kTcxoGatePeriodUs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("fc0", "last_measured_khz",
                  runtime_state.tcxo.last_measured_khz, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("fc0", "last_elapsed_us",
                  runtime_state.tcxo.last_elapsed_us, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u32("fc0", "last_sampled_elapsed_us",
                  runtime_state.tcxo.last_sampled_elapsed_us, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u32("fc0", "last_sample_count",
                  runtime_state.tcxo.last_sample_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("fc0", "last_zero_sample_count",
                  runtime_state.tcxo.last_zero_sample_count,
                  runtime_state.tcxo.last_zero_sample_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  runtime_state.tcxo.last_window_flags);
  emit_status_u32("fc0", "last_valid_sample_count",
                  runtime_state.tcxo.last_valid_sample_count, OTIS_SEVERITY_INFO,
                  runtime_state.tcxo.last_window_flags);
  emit_status_u32("fc0", "last_first_sample_khz",
                  runtime_state.tcxo.last_first_sample_khz, OTIS_SEVERITY_INFO,
                  runtime_state.tcxo.last_window_flags);
  emit_status_u32("fc0", "last_last_sample_khz",
                  runtime_state.tcxo.last_last_sample_khz, OTIS_SEVERITY_INFO,
                  runtime_state.tcxo.last_window_flags);
  emit_status_u32("fc0", "last_min_sample_khz",
                  runtime_state.tcxo.last_min_sample_khz,
                  runtime_state.tcxo.last_zero_sample_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  runtime_state.tcxo.last_window_flags);
  emit_status_u32("fc0", "last_max_sample_khz",
                  runtime_state.tcxo.last_max_sample_khz, OTIS_SEVERITY_INFO,
                  runtime_state.tcxo.last_window_flags);
  emit_status_u32("fc0", "last_window_flags",
                  runtime_state.tcxo.last_window_flags,
                  runtime_state.tcxo.last_observation_valid
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  runtime_state.tcxo.last_window_flags);
  emit_status("fc0", "last_window_invalid_reason",
              otis_count_observation_window_invalid_reason(&runtime_state),
              runtime_state.tcxo.last_observation_valid
                  ? OTIS_SEVERITY_INFO
                  : OTIS_SEVERITY_WARN,
              runtime_state.tcxo.last_window_flags);
  emit_status_u32("fc0", "consecutive_bad_windows",
                  runtime_state.tcxo.consecutive_bad_windows,
                  runtime_state.tcxo.consecutive_bad_windows == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  runtime_state.tcxo.last_window_flags);
  emit_status_u32("fc0", "total_bad_windows",
                  runtime_state.tcxo.total_bad_windows,
                  runtime_state.tcxo.total_bad_windows == 0u ? OTIS_SEVERITY_INFO
                                                             : OTIS_SEVERITY_WARN,
                  runtime_state.tcxo.last_window_flags);
  emit_status("fc0", "startup_inhibit_active",
              runtime_state.tcxo.startup_inhibit_active ? "true" : "false",
              runtime_state.tcxo.startup_inhibit_active ? OTIS_SEVERITY_WARN
                                                        : OTIS_SEVERITY_INFO,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("fc0", "startup_inhibit_elapsed_s",
                  runtime_state.tcxo.startup_inhibit_elapsed_s,
                  runtime_state.tcxo.startup_inhibit_active ? OTIS_SEVERITY_WARN
                                                            : OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("fc0", "fc0_valid_for_control",
              runtime_state.tcxo.valid_for_control ? "true" : "false",
              runtime_state.tcxo.valid_for_control ? OTIS_SEVERITY_INFO
                                                   : OTIS_SEVERITY_WARN,
              OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("fc0", "fc0_clean_window_count",
                  runtime_state.tcxo.control_clean_window_count,
                  runtime_state.tcxo.valid_for_control ? OTIS_SEVERITY_INFO
                                                       : OTIS_SEVERITY_WARN,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status("fc0", "fc0_fault",
              runtime_state.tcxo.fault_after_startup ? "true" : "false",
              runtime_state.tcxo.fault_after_startup ? OTIS_SEVERITY_WARN
                                                     : OTIS_SEVERITY_INFO,
              runtime_state.tcxo.last_window_flags);
  emit_status_u64_decimal("fc0", "last_counted_edges",
                          runtime_state.tcxo.last_counted_edges,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal("fc0", "last_gate_open_ticks",
                          runtime_state.tcxo.last_gate_open_ticks,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u64_decimal("fc0", "last_gate_close_ticks",
                          runtime_state.tcxo.last_gate_close_ticks,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
}

void handle_dac_set(uint16_t requested_code) {
  emit_status_u16_hex("dac", "requested_code", requested_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  if (!otis_dac_ad5693r_is_enabled()) {
    emit_status("dac", "set", "rejected_disabled", OTIS_SEVERITY_WARN,
                OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    return;
  }
  if (!otis_dac_ad5693r_is_initialized()) {
    emit_status("dac", "set", "rejected_not_initialized", OTIS_SEVERITY_WARN,
                OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    return;
  }
  uint16_t clamped = otis_dac_ad5693r_clamp_code(requested_code);
  if (clamped != requested_code) {
    emit_status_u16_hex("dac", "rejected_code", requested_code,
                        OTIS_SEVERITY_WARN, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("dac", "set", "rejected_outside_clamps", OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
    return;
  }
  bool ok = otis_dac_ad5693r_set_raw(requested_code);
  if (ok) {
    otis_phase4_observe_preview_on_dac_applied(
        requested_code, otis_capture_ticks_now());
  }
  emit_status_u16_hex("dac", ok ? "accepted_code" : "failed_code",
                      requested_code,
                      ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                      ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
}

#if OTIS_ENABLE_H1_DAC_SWEEP
void handle_sweep_add(const OtisParsedSerialCommand &command) {
  if (!command.arguments_valid) {
    emit_status("sweep", "add", "rejected_parse_error", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
    return;
  }
  h1_dac_sweep_add_step(command.code, command.dwell_ms);
}
#endif

void emit_pseudo_pps_status(void) {
  OtisPseudoPpsStatus status;
  otis_pseudo_pps_get_status(&status);
  emit_status("ppsgen", "state", otis_pseudo_pps_state_name(status.state),
              status.state == OtisPseudoPpsState::ResourceFault ||
                      status.state == OtisPseudoPpsState::UnderflowFault
                  ? OTIS_SEVERITY_ERROR
                  : OTIS_SEVERITY_INFO,
              status.state == OtisPseudoPpsState::ResourceFault ||
                      status.state == OtisPseudoPpsState::UnderflowFault
                  ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                  : OTIS_FLAG_NONE);
  emit_status("ppsgen", "profile", status.profile_id, OTIS_SEVERITY_INFO,
              OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "profile_version", status.profile_version,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("ppsgen", "session", status.session, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "step_count", status.step_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "truth_emitted", status.truth_emitted,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "pin_sample_count", status.pin_sample_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "output_high_sample_count",
                  status.output_high_sample_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "reference_high_sample_count",
                  status.reference_high_sample_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("ppsgen", "output_gpio", OTIS_GPIO_PSEUDO_PPS_OUTPUT,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  emit_status_u32("ppsgen", "pio_clock_hz", status.pio_clock_hz,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
}

void emit_pseudo_pps_profiles(void) {
  for (size_t index = 0u; index < otis_pseudo_pps_profile_count(); ++index) {
    const OtisPseudoPpsProfile *profile = otis_pseudo_pps_profile_at(index);
    if (profile != nullptr) {
      char key[20];
      snprintf(key, sizeof(key), "profile_%02u", static_cast<unsigned>(index));
      emit_status("ppsgen", key, profile->id, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_PROFILE_ASSUMPTION);
    }
  }
}

void execute_serial_command(const OtisParsedSerialCommand &command) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  if (command.kind == OtisSerialCommandKind::Help) {
    emit_status("command", "h1_help",
                "CONFIG?_DAC?_DAC_SET_code_DAC_MID_DAC_ZERO_DAC_LIMITS?_FC0?_SWEEP?_SWEEP_LOAD_name_SWEEP_START_SWEEP_STOP_SWEEP_STEP_SWEEP_CLEAR_SWEEP_ADD_code_dwell_ms_PPSGEN?_PPSGEN_PROFILES?_PPSGEN_ARM_name_PPSGEN_START_PPSGEN_STOP_HELP",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::ConfigQuery) {
    emit_status("command", "config_snapshot", "begin",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    // A capture opened after the boot banner still needs one complete
    // provenance block for evidence sealing.  Do not repeat the relatively
    // large block at CONFIG? service-load rates.
    if (!config_query_provenance_emitted) {
      emit_build_provenance_status();
      otis_count_observation_emit_configuration_status(
          &status_emit_context);
      config_query_provenance_emitted = true;
    }
    emit_status("firmware", "version", OTIS_FIRMWARE_VERSION,
                OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("firmware", "config_id", OTIS_FIRMWARE_CONFIG_ID,
                OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("system", "mode", otis_bringup_mode_name(),
                OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("build", "capture_backend", otis_capture_backend_name(),
                OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("build", "tcxo_counter_backend",
                otis_tcxo_counter_backend_name(), OTIS_SEVERITY_INFO,
                OTIS_FLAG_PROFILE_ASSUMPTION);
#if OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO
    emit_status("pps_gate", "boundary_owner", "pio_state_machine",
                OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("pps_gate", "aperture_backend",
                "pio_wait_cumulative_snapshot_dma_v1", OTIS_SEVERITY_INFO,
                OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("pps_gate", "backend_qualified",
                OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED ? "true" : "false",
                OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED ? OTIS_SEVERITY_INFO
                                                    : OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("pps_gate", "boundary_ring_capacity",
                    otis_pps_count_boundary_ring_capacity(),
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
    emit_status_u32("capture", "counter_gate_period_us", kTcxoGatePeriodUs,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_pps_dual_observer",
                    OTIS_ENABLE_PPS_DUAL_OBSERVER, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_pseudo_pps_generator",
                    OTIS_ENABLE_PSEUDO_PPS_GENERATOR, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_dac_ad5693r",
                    OTIS_ENABLE_DAC_AD5693R, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_h1_dac_sweep",
                    OTIS_ENABLE_H1_DAC_SWEEP, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_env_sensors", OTIS_ENABLE_ENV_SENSORS,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_env_sht4x", OTIS_ENABLE_ENV_SHT4X,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("build", "enable_env_bmp280", OTIS_ENABLE_ENV_BMP280,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("sweep", "default_dwell_ms",
                    OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u32("sweep", "slope_dwell_ms",
                    OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u16_hex("sweep", "tiny_step_codes",
                        OTIS_H1_DAC_SWEEP_TINY_STEP_CODES,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u16_hex(
        "sweep", "center_code",
        (uint16_t)(((uint32_t)OTIS_DAC_MIN_CODE +
                    (uint32_t)OTIS_DAC_MAX_CODE) /
                   2u),
        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status("command", "config_snapshot", "end",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::DacQuery) {
    emit_dac_status("dac");
  } else if (command.kind == OtisSerialCommandKind::DacLimitsQuery) {
    emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
    emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_PROFILE_ASSUMPTION);
  } else if (command.kind == OtisSerialCommandKind::DacMid) {
    uint16_t mid = (uint16_t)(((uint32_t)OTIS_DAC_MIN_CODE +
                              (uint32_t)OTIS_DAC_MAX_CODE) /
                             2u);
    handle_dac_set(mid);
  } else if (command.kind == OtisSerialCommandKind::DacZero) {
    handle_dac_set((uint16_t)OTIS_DAC_MIN_CODE);
  } else if (command.kind == OtisSerialCommandKind::DacSet) {
    if (command.arguments_valid) {
      handle_dac_set(command.code);
    } else {
      emit_status("dac", "set", "rejected_parse_error", OTIS_SEVERITY_WARN,
                  OTIS_FLAG_NONE);
    }
  } else if (command.kind == OtisSerialCommandKind::Fc0Query) {
    emit_fc0_status();
#if OTIS_ENABLE_PSEUDO_PPS_GENERATOR
  } else if (command.kind == OtisSerialCommandKind::PpsGenProfilesQuery) {
    emit_pseudo_pps_profiles();
  } else if (command.kind == OtisSerialCommandKind::PpsGenQuery) {
    emit_pseudo_pps_status();
  } else if (command.kind == OtisSerialCommandKind::PpsGenArm) {
    bool armed = command.arguments_valid &&
                 otis_pseudo_pps_arm(command.text_argument);
    emit_status("ppsgen", "arm", armed ? "accepted" : "rejected",
                armed ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                armed ? OTIS_FLAG_NONE : OTIS_FLAG_PROFILE_ASSUMPTION);
  } else if (command.kind == OtisSerialCommandKind::PpsGenStart) {
    bool started = otis_pseudo_pps_start();
    emit_status("ppsgen", "start", started ? "accepted" : "rejected",
                started ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                started ? OTIS_FLAG_NONE : OTIS_FLAG_PROFILE_ASSUMPTION);
  } else if (command.kind == OtisSerialCommandKind::PpsGenStop) {
    bool stopped = otis_pseudo_pps_stop();
    emit_status("ppsgen", "stop", stopped ? "accepted" : "rejected",
                stopped ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
                stopped ? OTIS_FLAG_NONE : OTIS_FLAG_PROFILE_ASSUMPTION);
  } else if (command.kind == OtisSerialCommandKind::PpsGenOther) {
    emit_status("ppsgen", "command", "rejected_unknown", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
#else
  } else if (command.kind == OtisSerialCommandKind::PpsGenProfilesQuery ||
             command.kind == OtisSerialCommandKind::PpsGenQuery ||
             command.kind == OtisSerialCommandKind::PpsGenArm ||
             command.kind == OtisSerialCommandKind::PpsGenStart ||
             command.kind == OtisSerialCommandKind::PpsGenStop ||
             command.kind == OtisSerialCommandKind::PpsGenOther) {
    emit_status("ppsgen", "command", "rejected_disabled", OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
#if OTIS_ENABLE_H1_DAC_SWEEP
  } else if (command.kind == OtisSerialCommandKind::SweepQuery) {
    emit_sweep_status();
  } else if (command.kind == OtisSerialCommandKind::SweepLoad) {
    h1_dac_sweep_load_profile(command.text_argument);
  } else if (command.kind == OtisSerialCommandKind::SweepStart) {
    h1_dac_sweep_start();
  } else if (command.kind == OtisSerialCommandKind::SweepStop) {
    h1_dac_sweep_stop("stop");
  } else if (command.kind == OtisSerialCommandKind::SweepStep) {
    h1_dac_sweep_manual_step();
  } else if (command.kind == OtisSerialCommandKind::SweepClear) {
    h1_dac_sweep_clear();
  } else if (command.kind == OtisSerialCommandKind::SweepAdd) {
    handle_sweep_add(command);
#else
  } else if (command.kind == OtisSerialCommandKind::SweepQuery ||
             command.kind == OtisSerialCommandKind::SweepLoad ||
             command.kind == OtisSerialCommandKind::SweepStart ||
             command.kind == OtisSerialCommandKind::SweepStop ||
             command.kind == OtisSerialCommandKind::SweepStep ||
             command.kind == OtisSerialCommandKind::SweepClear ||
             command.kind == OtisSerialCommandKind::SweepAdd ||
             command.kind == OtisSerialCommandKind::SweepOther) {
    emit_status("sweep", "command", "rejected_disabled", OTIS_SEVERITY_WARN,
                OTIS_FLAG_PROFILE_ASSUMPTION);
#endif
  } else if (command.kind != OtisSerialCommandKind::Empty) {
    emit_status("command", "unknown", "rejected_unknown", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
  }
#else
  (void)command;
#endif
}

void service_serial_commands(void) {
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  uint8_t byte_budget = 32u;
  while (Serial.available() > 0 && byte_budget-- > 0u) {
    OtisSerialFrameEvent event = otis_serial_frame_collect(
        &serial_command_collector, (char)Serial.read());
    if (event == OtisSerialFrameEvent::RejectedTooLong) {
      emit_status("command", "line", "rejected_too_long", OTIS_SEVERITY_WARN,
                  OTIS_FLAG_NONE);
      return;
    }
    if (event != OtisSerialFrameEvent::Complete) {
      continue;
    }

    if (otis_serial_frame_validate(&serial_command_collector) !=
        OtisSerialFrameValidation::Valid) {
      otis_serial_frame_collector_init(&serial_command_collector);
      emit_status("command", "line", "rejected_invalid_character",
                  OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
      return;
    }

    OtisParsedSerialCommand command =
        otis_serial_command_parse(serial_command_collector.line);
    execute_serial_command(command);
    otis_serial_frame_collector_init(&serial_command_collector);
    return;
  }
#endif
}

}  // namespace

void setup() {
  otis_runtime_state_init(&runtime_state);
  otis_serial_frame_collector_init(&serial_command_collector);
  otis_status_emit_init(&status_emit_context,
                        &runtime_state.sequences.status_seq);
  configure_selected_capabilities();
  boot_phase_reset_entry();
  boot_phase_early_init();
  if (otis_boot_capability_has_fatal_conflict(&boot_capabilities)) {
    halt_boot(BootFatal::ResourceOwnershipConflict, BootPhase::EarlyInit);
  }
  if (otisBootSafeModeRequested()) {
    enter_safe_mode();
    return;
  }

  boot_phase_clocks_init();
  boot_phase_gpio_init();
  boot_phase_ring_buffers_init();
  boot_phase_serial_init();
  boot_phase_protocol_banner();
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  // The count boundary handler must exist before the primary PPS IRQ is armed.
  boot_phase_timer_init();
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPIO_LOOPBACK
  boot_phase_capture_init();
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_GPS_PPS || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_TCXO_OBSERVE || \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  boot_phase_pps_input_init();
#endif
#if OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE && \
    (OTIS_ENABLE_DAC_AD5693R ||                                   \
     (OTIS_ENABLE_ENV_SENSORS &&                                 \
      (OTIS_ENABLE_ENV_SHT4X || OTIS_ENABLE_ENV_BMP280)))
  boot_phase_peripherals_init();
#endif
#if OTIS_ENABLE_PHASE4_OBSERVE_PREVIEW
  boot_phase_preview_init();
#endif
  boot_phase_capability_audit();
  boot_phase_run_mode();
}

void loop() {
  if (runtime_state.boot.safe_mode_active) {
    emit_boot_records_if_serial_ready();
    otis_status_led_poll(millis());
    return;
  }

  // Capture service always runs first. While a queued EST/CTL pair is being
  // transmitted in bounded chunks, no other record producer may interleave
  // bytes into that CSV frame; IRQ/PIO capture continues into its own ring.
  otis_pps_dual_observer_service();
  otis_capture_backend_service();
  if (otis_phase4_observe_preview_transport_busy()) {
    otis_phase4_observe_preview_service_transport();
    otis_status_led_poll(millis());
    return;
  }

  emit_protocol_banner_if_serial_ready();
  emit_run_mode_status_if_ready();
  emit_resource_ownership_status();
  otis_pseudo_pps_service();
  drain_pps_count_boundary_ring();
  drain_capture_ring();
  service_tcxo_gate();
  service_serial_commands();
  service_loopback_output();
#if OTIS_ENABLE_H1_DAC_SWEEP && \
    OTIS_SW1_BRINGUP_MODE == OTIS_SW1_MODE_H1_OCXO_OBSERVE
  service_h1_dac_sweep();
#endif
  OtisDacAd5693rStatus phase4_dac_status;
  otis_dac_ad5693r_get_status(&phase4_dac_status);
  OtisPhase4LiveDacState phase4_dac = {
      phase4_dac_status.last_write_ok &&
          phase4_dac_status.last_requested_code ==
              phase4_dac_status.last_applied_code,
      phase4_dac_status.last_applied_code,
  };
  otis_phase4_observe_preview_poll(otis_capture_ticks_now(), &runtime_state,
                                   &phase4_dac);
  service_environment_sensors();
  emit_periodic_status();
  otis_phase4_observe_preview_service_transport();
  otis_status_led_poll(millis());
}
