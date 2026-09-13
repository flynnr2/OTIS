#include <Arduino.h>
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pico/time.h>

#include "otis_config.h"

#include "OtisBootConfig.h"
#include "otis_board.h"
#include "otis_boot_capabilities.h"
#include "otis_boot_diag.h"
#include "otis_capture_irq.h"
#include "otis_capture_ring.h"
#include "otis_count_observation.h"
#include "otis_reference_acceptance_live.h"
#include "otis_reference_acceptance_format.h"
#include "otis_reference_acceptance_policy.generated.h"
#include "otis_regulation_actuator.h"
#include "otis_adaptive_hybrid_regulation_live.h"
#include "otis_regulation_dual_core_state.h"
#include "otis_frequency_regulation_live.h"
#include "otis_phase_preview_live.h"
#include "otis_phase_preview_transport.h"
#include "otis_dac_ad5693r.h"
#include "otis_dual_core_partition.h"
#include "otis_dual_core_receiver_gate.h"
#include "otis_emit.h"
#include "otis_env_sensors.h"
#include "otis_forwarded_clock_output.h"
#include "otis_forwarded_clock_monitor.h"
#include "otis_gnss_receiver.h"
#include "otis_memory_budget.h"
#include "otis_pps_count_boundary_ring.h"
#include "otis_pps_count_boundary.h"
#include "otis_pps_snapshot_backend.h"
#include "otis_protocol.h"
#include "otis_resource_registry.h"
#include "otis_runtime_state.h"
#include "otis_serial_frame_arbiter.h"
#include "otis_serial_command.h"
#include "otis_status_emit.h"
#include "otis_timebase.h"
#include "otis_monotonic_us_extension.h"
#include "otis_transport_serial.h"
#include "otis_transport_liveness.h"

// Arduino-Pico otherwise splits one 8 KiB stack between both cores.  The
// timing/estimator path has bounded local formatting buffers, so give Core 1
// its own full 8 KiB stack as supported by the pinned core.
bool core1_separate_stack = true;

namespace {

constexpr uint32_t kStatusPeriodMs = OTIS_PPS_GATE_STATUS_PERIOD_MS;
constexpr uint32_t kTcxoGatePeriodUs = OTIS_TCXO_GATE_PERIOD_US;
constexpr uint32_t kCountStartupInhibitMs = OTIS_COUNT_STARTUP_INHIBIT_MS;
constexpr uint32_t kCountControlReadyCleanWindows =
    OTIS_COUNT_CONTROL_READY_CLEAN_WINDOWS;

OtisRuntimeState runtime_state;
OtisReferenceAcceptanceLive reference_acceptance(OTIS_REFERENCE_ACCEPTANCE_POLICY);
OtisStatusEmitContext status_emit_context;
OtisSerialFrameCollector serial_command_collector;
bool deferred_serial_command_ready = false;
char deferred_serial_command[OTIS_SERIAL_COMMAND_BUFFER_SIZE] = {};
OtisSerialFrameEvent deferred_serial_error = OtisSerialFrameEvent::None;
bool deferred_serial_invalid = false;
bool deferred_abort_result_ready = false;
bool deferred_abort_queued = false;
OtisBootCapabilityTracker boot_capabilities;
bool resource_ownership_status_emitted = false;
bool boot_capability_status_emitted = false;
bool run_mode_status_emitted = false;
bool transport_started = false;
bool config_query_provenance_emitted = false;



constexpr uint32_t kDualCoreTimingTracePeriodMs = 250u;
bool dual_core_service_boot_ready = false;
bool dual_core_timing_boot_complete = false;
bool dual_core_timing_boot_in_progress = false;
bool dual_core_timing_loop_started = false;
constexpr uint32_t kDualCoreBootHandshakeTimeoutMs = 10000u;
uint32_t dual_core_service_sequence = 0u;
uint32_t dual_core_timing_telemetry_sequence = 0u;
uint32_t dual_core_diagnostic_snapshot_generation = 0u;
uint32_t dual_core_last_metadata_ms = 0u;
uint32_t dual_core_last_timing_status_ms = 0u;
bool dual_core_timing_trace_started = false;
uint32_t dual_core_last_timing_trace_ms = 0u;
uint32_t dual_core_association_loss_decision_sequence = 0u;
OtisRegulationStaticCodeState dual_core_static_code = {};
OtisReceiverQualificationMessage dual_core_receiver = {};
// Association-loss publication runs on the bounded timing-core stack. Keep
// its full evidence-frame formatter in static storage; Core 1 is the only
// producer and the publication is synchronous.
OtisEvidenceFrameMessage dual_core_association_loss_scratch = {};
OtisEvidenceFrameMessage dual_core_evidence_transport = {};
uint16_t dual_core_evidence_transport_sent = 0u;
bool dual_core_evidence_transport_active = false;
OtisSerialFrameArbiter dual_core_serial_frame_arbiter = {
    OtisSerialFrameOwner::None,
    static_cast<uint8_t>(OtisSerialFrameOwner::DualCoreEvidence),
};
OtisTransportLiveness dual_core_transport_liveness = {};
bool dual_core_transport_abort_queued = false;
uint32_t dual_core_pre_carrier_records_discarded = 0u;
uint32_t dual_core_carrier_loss_frames_abandoned = 0u;
uint32_t dual_core_periodic_service_deferred = 0u;
OtisStatusEmitContext dual_core_timing_status_context = {};
OtisActuatorTransactionGuard dual_core_service_actuator_guard = {};
OtisSetupAuthorityGuard dual_core_timing_setup_guard = {};
OtisSetupExecutionGuard dual_core_service_setup_guard = {};
bool dual_core_manual_start_consumed = false;

bool queue_dual_core_active_control(OtisRunControlKind kind,
                                    uint32_t first = 0u,
                                    uint32_t second = 0u,
                                    uint32_t third = 0u) {
  OtisServiceMessage control = {};
  control.kind = OtisServiceMessageKind::RunControl;
  control.run_control.sequence = dual_core_service_sequence++;
  control.run_control.published_ticks = otis_monotonic_us32_now();
  control.run_control.kind = kind;
  control.run_control.asserted = true;
  if (kind == OtisRunControlKind::CaptureLease)
    control.run_control.capture_lease_sequence = first;
  else if (kind == OtisRunControlKind::Arm) {
    control.run_control.authorization_sequence = first;
    control.run_control.nonce = second;
    control.run_control.expires_s = third;
  } else if (kind == OtisRunControlKind::EvidenceRelease) {
    control.run_control.request_sequence = first;
    control.run_control.evidence_phase = second;
  } else if (kind == OtisRunControlKind::DiagnosticConfigQuery ||
             kind == OtisRunControlKind::DiagnosticRuntimeQuery) {
    control.run_control.nonce = first;
  } else if (kind == OtisRunControlKind::StatusQuery) {
    control.run_control.nonce = first;
  }
  return otis_dual_core_publish_service(&control);
}

bool queue_dual_core_setup_authorization(
    OtisSetupAuthorityRequest &request) {
  OtisServiceMessage control = {};
  control.kind = OtisServiceMessageKind::RunControl;
  control.run_control.sequence = ++dual_core_service_sequence;
  if (control.run_control.sequence == 0u)
    control.run_control.sequence = ++dual_core_service_sequence;
  control.run_control.published_ticks = otis_monotonic_us32_now();
  control.run_control.kind = OtisRunControlKind::SetupAuthorize;
  control.run_control.asserted = true;
  control.run_control.setup_request = request;
  control.run_control.setup_request.command_sequence =
      control.run_control.sequence;
  const bool published = otis_dual_core_publish_service(&control);
  if (published) request.command_sequence = control.run_control.sequence;
  return published;
}

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

  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::PpsCapture,
                              OtisBootCapabilityRequirement::Required);

  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::OscillatorCount,
                              OtisBootCapabilityRequirement::Required);

  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::ForwardedOutput,
                              OtisBootCapabilityRequirement::Required);

  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::ForwardedMonitor,
                              OtisBootCapabilityRequirement::Optional);


  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Dac,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities, OtisBootCapability::Sensors,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::GnssReceiver,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::FrequencyRegulation,
                              OtisBootCapabilityRequirement::Required);
  otis_boot_capability_select(&boot_capabilities,
                              OtisBootCapability::PhaseFrequencyEstimate,
                              OtisBootCapabilityRequirement::Required);
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
  bool fatal_emitted = false;
  if (!transport_started) {
    transport_started = otis_transport_begin(kOtisSerialBaud);
    wait_for_serial_or_timeout();
  }
  if (otis_transport_ready()) {
    emit_protocol_banner_if_serial_ready();
    emit_selected_capability_status();
    emit_resource_ownership_status();
    emitOtisBootFatal(Serial, fatal, failed_phase);
    fatal_emitted = true;
  }

  while (true) {
    if (otis_transport_ready() && !fatal_emitted) {
      emit_protocol_banner_if_serial_ready();
      emit_selected_capability_status();
      emit_resource_ownership_status();
      emitOtisBootFatal(Serial, fatal, failed_phase);
      fatal_emitted = true;
    }
    delay(10);
  }
}

void enter_safe_mode(void) {
  runtime_state.boot.safe_mode_active = true;
  runtime_state.boot.safe_mode_warn_pending = true;
  enter_boot_phase(BootPhase::Fatal);
  otisBootBreadcrumbSetSafeModeFatal(BootFatal::RepeatedBootFailure);

  transport_started = otis_transport_begin(kOtisSerialBaud);
  wait_for_serial_or_timeout();
  emit_protocol_banner_if_serial_ready();
  emit_selected_capability_status();
  emit_resource_ownership_status();
}

const char *edge_string(char edge);
const char *osc_observation_domain(void);
OtisCountObservationConfig count_observation_config(void);

void emit_status(const char *component, const char *key, const char *value,
                 const char *severity, uint32_t flags) {
  if (__atomic_load_n(&dual_core_timing_boot_in_progress,
                      __ATOMIC_ACQUIRE)) {
    OtisTelemetryMessage message = {};
    message.timestamp_ticks = otis_monotonic_us32_now();
    message.flags = flags;
    snprintf(message.component, sizeof(message.component), "%s", component);
    snprintf(message.key, sizeof(message.key), "%s", key);
    snprintf(message.value, sizeof(message.value), "%s", value);
    snprintf(message.severity, sizeof(message.severity), "%s", severity);
    otis_dual_core_publish_boot_telemetry(&message);
    return;
  }
  otis_status_emit(&status_emit_context, component, key, value, severity,
                   flags);
}

void emit_status_direct(const char *component, const char *key,
                        const char *value, const char *severity,
                        uint32_t flags) {
  // Core 0 is the sole wire owner.  In particular, a record popped from the
  // Core 1 -> Core 0 telemetry queue must never be republished to that queue
  // while Core 1 boot publication is still active.
  otis_status_emit(&status_emit_context, component, key, value, severity,
                   flags);
}

void emit_status_u32(const char *component, const char *key, uint32_t value,
                     const char *severity, uint32_t flags) {
  char buffer[24];
  snprintf(buffer, sizeof(buffer), "%lu", static_cast<unsigned long>(value));
  emit_status(component, key, buffer, severity, flags);
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

bool dual_core_timing_trace_due(uint32_t now_ms) {
  if (!dual_core_timing_trace_started ||
      (uint32_t)(now_ms - dual_core_last_timing_trace_ms) >=
          kDualCoreTimingTracePeriodMs) {
    dual_core_timing_trace_started = true;
    dual_core_last_timing_trace_ms = now_ms;
    return true;
  }
  return false;
}

uint16_t dual_core_hdop_hundredths(const char *text) {
  if (text == nullptr || *text == '\0') return 0u;
  const double parsed = strtod(text, nullptr);
  if (parsed <= 0.0) return 0u;
  const double scaled = parsed * 100.0;
  return scaled >= 65535.0 ? 65535u : static_cast<uint16_t>(scaled + 0.5);
}

bool dual_core_receiver_qualified_for_control(void) {
  return otis_dual_core_receiver_qualified_for_control_at(
      &dual_core_receiver, otis_monotonic_us32_now(),
      OTIS_GNSS_METADATA_MAX_AGE_MS);
}

void publish_dual_core_timing_status(const char *component, const char *key,
                                     const char *value,
                                     const char *severity, uint32_t flags) {
  OtisTelemetryMessage message = {};
  message.sequence = ++dual_core_timing_telemetry_sequence;
  message.timestamp_ticks = otis_monotonic_us32_now();
  message.flags = flags;
  snprintf(message.component, sizeof(message.component), "%s", component);
  snprintf(message.key, sizeof(message.key), "%s", key);
  snprintf(message.value, sizeof(message.value), "%s", value);
  snprintf(message.severity, sizeof(message.severity), "%s", severity);
  otis_dual_core_publish_telemetry(&message);
}

void publish_dual_core_timing_status_sink(
    void *, const char *component, const char *key, const char *value,
    const char *severity, uint32_t flags) {
  publish_dual_core_timing_status(component, key, value, severity, flags);
}

void publish_dual_core_timing_status_u32(const char *component,
                                         const char *key, uint32_t value,
                                         const char *severity,
                                         uint32_t flags);

void publish_forwarded_clock_monitor_status(void) {
  OtisForwardedClockMonitorStats monitor = {};
  otis_forwarded_clock_monitor_get_stats(&monitor);
  const char *severity = monitor.fault_latched ? OTIS_SEVERITY_WARN
                                               : OTIS_SEVERITY_INFO;
  const uint32_t flags = monitor.fault_latched
                             ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                             : OTIS_FLAG_NONE;
  publish_dual_core_timing_status(
      "forwarded_clock_monitor", "state",
      monitor.fault_latched
          ? "monitor_invalid_or_unavailable"
          : (monitor.running ? "monitoring_unqualified" : "disabled"),
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "configured", monitor.configured,
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "running", monitor.running, severity,
      flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "session", monitor.session, severity,
      flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "reference_service_count",
      monitor.reference_service_count, severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "snapshot_count", monitor.snapshot_count,
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "no_snapshot_count",
      monitor.no_snapshot_count, severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "fifo_backlog_count",
      monitor.fifo_backlog_count, severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "pio_rxstall_count",
      monitor.pio_rxstall_count, severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "fault_flags", monitor.fault_flags,
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "state_machine", monitor.state_machine,
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "program_offset", monitor.program_offset,
      severity, flags);
  publish_dual_core_timing_status_u32(
      "forwarded_clock_monitor", "program_length", monitor.program_length,
      severity, flags);
}

void publish_dual_core_diagnostic_snapshot(OtisRunControlKind kind,
                                           uint32_t query_sequence,
                                           uint32_t query_nonce) {
  const uint32_t generation = ++dual_core_diagnostic_snapshot_generation;
  publish_dual_core_timing_status_u32(
      "timing_diagnostic_snapshot", "snapshot_generation_begin", generation,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status(
      "timing_diagnostic_snapshot", "snapshot_contract",
      "core1_timing_diagnostic_snapshot_v1", OTIS_SEVERITY_INFO,
      OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "timing_diagnostic_snapshot", "query_sequence", query_sequence,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "timing_diagnostic_snapshot", "query_nonce", query_nonce,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  if (kind == OtisRunControlKind::DiagnosticConfigQuery) {
    publish_dual_core_timing_status(
        "timing_diagnostic_snapshot", "query_kind", "configuration",
        OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    otis_count_observation_emit_configuration_status(
        &dual_core_timing_status_context);
    publish_forwarded_clock_monitor_status();
  } else {
    publish_dual_core_timing_status(
        "timing_diagnostic_snapshot", "query_kind", "runtime",
        OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    const OtisCountObservationConfig config = count_observation_config();
    otis_count_observation_emit_runtime_status(
        &runtime_state, &dual_core_timing_status_context, &config);
    otis_count_observation_emit_status(&runtime_state,
                                       &dual_core_timing_status_context);
  }
  publish_dual_core_timing_status_u32(
      "timing_diagnostic_snapshot", "snapshot_generation_complete",
      generation, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
}

void publish_dual_core_timing_status_u32(const char *component,
                                         const char *key, uint32_t value,
                                         const char *severity,
                                         uint32_t flags) {
  char formatted[24];
  snprintf(formatted, sizeof(formatted), "%lu",
           static_cast<unsigned long>(value));
  publish_dual_core_timing_status(component, key, formatted, severity, flags);
}

void publish_dual_core_active_status_field(void *, const char *key,
                                           const char *value,
                                           const char *severity,
                                           uint32_t flags) {
  publish_dual_core_timing_status(OTIS_ADAPTIVE_HYBRID_STATUS_COMPONENT, key,
                                  value, severity, flags);
}

bool publish_dual_core_active_status(uint32_t now_ms) {
  // Every caller, including priority abort consumption, must either publish
  // the complete generation or defer it.  A partial active snapshot is not a
  // useful lossy summary because host decisions bind begin/complete identity.
  if (!otis_dual_core_telemetry_can_publish(
          OTIS_REGULATION_STATUS_TELEMETRY_BURST))
    return false;
  otis_adaptive_hybrid_regulation_live_visit_status(
      nullptr, publish_dual_core_active_status_field, now_ms / 1000u);
  return true;
}

OtisSetupAuthorityContext current_dual_core_setup_authority_context(
    uint32_t now_s) {
  OtisAdaptiveHybridRegulationLiveStatus active = {};
  otis_adaptive_hybrid_regulation_live_get_status(&active, now_s);
  return {
      now_s,
      otis_adaptive_hybrid_regulation_live_status_snapshot_generation(),
      active.query_nonce,
      active.session_id,
      active.expected_setup_code,
      OTIS_BUILD_CONFIG_SHA256,
      active.capture_lease_live,
      active.setup_gnss_eligible && dual_core_receiver_qualified_for_control() &&
          dual_core_receiver.identity_stable && dual_core_receiver.gsa_3d,
      active.setup_reference_eligible,
      active.setup_partition_healthy,
      active.state != nullptr && strcmp(active.state, "DISARMED") == 0,
      !active.manual_start_confirmed,
  };
}

OtisSetupExecutionContext current_dual_core_setup_execution_context(
    uint32_t now_s) {
  OtisDacAd5693rStatus dac = {};
  otis_dac_ad5693r_get_status(&dac);
  return {
      now_s,
      static_cast<uint16_t>(OTIS_ADAPTIVE_HYBRID_START_CODE),
      OTIS_BUILD_CONFIG_SHA256,
      !otis_dual_core_fail_static(),
      dac.enabled && dac.initialized,
  };
}

void publish_dual_core_setup_phase(const char *phase,
                                   const OtisSetupAuthorityRequest &request,
                                   const char *severity) {
  publish_dual_core_timing_status("adaptive_hybrid_setup", "phase", phase, severity,
                                  OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "adaptive_hybrid_setup", "command_sequence", request.command_sequence, severity,
      OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "adaptive_hybrid_setup", "authorization_sequence",
      request.authorization_sequence, severity, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "adaptive_hybrid_setup", "status_generation", request.status_generation,
      severity, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "adaptive_hybrid_setup", "query_nonce", request.query_nonce, severity,
      OTIS_FLAG_NONE);
}

void publish_dual_core_timing_health(uint32_t now_ms) {
  if ((uint32_t)(now_ms - dual_core_last_timing_status_ms) < kStatusPeriodMs)
    return;
  // Do not begin a complete-generation health capsule unless the queue can
  // retain every record. Retry from the same due boundary after Core 0 drains;
  // a missing completion marker is never a permissible lossy summary.
  if (!otis_dual_core_telemetry_can_publish(
          OTIS_TIMING_HEALTH_TELEMETRY_BURST))
    return;
  dual_core_last_timing_status_ms = now_ms;

  const uint32_t capture_dropped = otis_capture_ring_dropped_count();
  const uint32_t boundary_dropped =
      otis_pps_count_boundary_ring_dropped_count();
  const uint32_t drop_flags = capture_dropped || boundary_dropped
                                  ? OTIS_FLAG_CAPTURE_RING_OVERRUN
                                  : OTIS_FLAG_NONE;
  publish_dual_core_timing_status_u32(
      "capture", "event_count", runtime_state.capture.emitted_event_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "capture", "dropped_count", capture_dropped,
      capture_dropped ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO, drop_flags);
  publish_dual_core_timing_status_u32(
      "capture", "pps_count_boundary_dropped_count", boundary_dropped,
      boundary_dropped ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
      drop_flags);
  publish_dual_core_timing_status_u32(
      "capture", "error_flags", drop_flags,
      drop_flags ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO, drop_flags);

  otis_count_observation_emit_status(&runtime_state,
                                     &dual_core_timing_status_context);
  publish_forwarded_clock_monitor_status();

  OtisCaptureIrqReferenceStats d14;
  otis_capture_irq_get_reference_stats(&d14);
  publish_dual_core_timing_status_u32(
      "pps_d14", "raw_edge_count", d14.d14_raw_edge_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "pps_d14", "accepted_pps_count", d14.d14_accepted_pps_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "pps_d14", "rejected_short_count", d14.d14_rejected_short_count,
      d14.d14_rejected_short_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
      d14.d14_rejected_short_count ? OTIS_FLAG_PULSE_TOO_NARROW
                                   : OTIS_FLAG_NONE);
  publish_dual_core_timing_status_u32(
      "pps_d14", "rejected_long_count", d14.d14_rejected_long_count,
      d14.d14_rejected_long_count ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
      d14.d14_rejected_long_count ? OTIS_FLAG_PULSE_TOO_WIDE
                                  : OTIS_FLAG_NONE);

  publish_dual_core_active_status(now_ms);
}

void publish_dual_core_service_metadata(uint32_t now_ms) {
  if (!__atomic_load_n(&dual_core_timing_loop_started, __ATOMIC_ACQUIRE))
    return;
  if ((uint32_t)(now_ms - dual_core_last_metadata_ms) < 1000u) return;
  dual_core_last_metadata_ms = now_ms;

  OtisDualCoreQueueStats service_queues = {};
  otis_dual_core_get_stats(&service_queues);
  if (service_queues.service_to_timing_depth >
      OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH - 2u) {
    if (dual_core_periodic_service_deferred <= UINT32_MAX - 2u)
      dual_core_periodic_service_deferred += 2u;
    else
      dual_core_periodic_service_deferred = UINT32_MAX;
    return;
  }

  OtisGnssReceiverSnapshot gnss;
  otis_gnss_receiver_get_snapshot(now_ms, &gnss);
  OtisServiceMessage receiver = {};
  receiver.kind = OtisServiceMessageKind::ReceiverQualification;
  receiver.receiver.sequence = dual_core_service_sequence++;
  receiver.receiver.metadata_sequence = gnss.last_good_frame_sequence;
  receiver.receiver.published_ticks = otis_monotonic_us32_now();
  receiver.receiver.metadata_age_ms = gnss.metadata_age_ms;
  receiver.receiver.satellites = gnss.satellites;
  receiver.receiver.hdop_centihundredths =
      dual_core_hdop_hundredths(gnss.hdop);
  receiver.receiver.fix_quality = gnss.fix_quality;
  receiver.receiver.fix_type = gnss.fix_dimension;
  receiver.receiver.control_eligible = gnss.control_eligible;
  receiver.receiver.identity_stable = gnss.identity_stable;
  receiver.receiver.gsa_checksum_requalified =
      gnss.gsa_checksum_requalified;
  receiver.receiver.gsa_3d = gnss.gsa_3d;
  otis_dual_core_publish_service(&receiver);

  OtisDacAd5693rStatus dac;
  otis_dac_ad5693r_get_status(&dac);
  OtisServiceMessage applied = {};
  applied.kind = OtisServiceMessageKind::AppliedDacState;
  applied.dac.sequence = dual_core_service_sequence++;
  applied.dac.published_ticks = otis_monotonic_us32_now();
  applied.dac.requested_code = dac.last_requested_code;
  applied.dac.applied_code = dac.last_applied_code;
  applied.dac.initialized = dac.initialized;
  applied.dac.i2c_ok = dac.last_write_ok;
  applied.dac.requested_applied_match =
      dac.applied_code_known && dac.last_write_ok &&
      dac.last_requested_code == dac.last_applied_code;
  otis_dual_core_publish_service(&applied);
}

void propagate_regulation_applied_epoch_to_previews(uint16_t applied_code,
                                               uint32_t dac_epoch,
                                               uint32_t now_s) {
  otis_frequency_regulation_live_on_dac_applied_epoch(applied_code, dac_epoch,
                                               now_s);
  if (!otis_phase_preview_live_update_applied_code(applied_code, dac_epoch))
    otis_dual_core_latch_fault(OtisPartitionFault::PhasePreviewFault);
}

void propagate_regulation_applied_epoch_to_previews_exact(
    uint16_t applied_code, uint32_t dac_epoch, uint32_t now_s,
    uint64_t application_ticks, uint32_t capture_session) {
  otis_frequency_regulation_live_on_dac_applied_epoch_exact(
      applied_code, dac_epoch, now_s, application_ticks, capture_session);
  if (!otis_phase_preview_live_update_applied_code(applied_code, dac_epoch))
    otis_dual_core_latch_fault(OtisPartitionFault::PhasePreviewFault);
}

void service_dual_core_timing_inputs(void) {
  OtisServiceMessage message;
  for (uint32_t consumed = 0u;
       consumed < OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH; ++consumed) {
    if (!otis_dual_core_take_service(&message)) break;
    if (message.kind == OtisServiceMessageKind::ReceiverQualification) {
      dual_core_receiver = message.receiver;
      continue;
    }
    if (message.kind == OtisServiceMessageKind::Environment) {
      otis_frequency_regulation_live_on_temperature(
          message.environment.temperature_valid,
          message.environment.temperature_c,
          millis() / 1000u);
      continue;
    }
    if (message.kind == OtisServiceMessageKind::AppliedDacState) {
      const bool changed =
          otis_regulation_dual_core_static_state_on_periodic(
              &dual_core_static_code, &message.dac);
      if (changed) {
      }
      continue;
    }
    if (message.kind == OtisServiceMessageKind::ManualDacApplication) {
      continue;
    }
    if (message.kind ==
        OtisServiceMessageKind::ActuatorAcknowledgement) {
      const bool transaction_acknowledged =
          otis_adaptive_hybrid_regulation_live_on_cross_core_ack(
              &message.actuator_acknowledgement, millis() / 1000u);
      if (message.actuator_acknowledgement.kind ==
              OtisActuatorAckKind::Applied &&
          !otis_regulation_dual_core_static_state_on_applied_ack(
              &dual_core_static_code, &message.actuator_acknowledgement,
              transaction_acknowledged))
        otis_dual_core_latch_fault(
            OtisPartitionFault::ActuatorAcknowledgementMismatch);
      continue;
    }
    if (message.kind ==
        OtisServiceMessageKind::SetupApplicationAcknowledgement) {
      const OtisSetupApplicationAck &ack = message.setup_acknowledgement;
      const bool acknowledged = otis_setup_authority_acknowledge(
          &dual_core_timing_setup_guard, &ack);
      if (ack.kind == OtisSetupApplicationAck::Kind::Core0Accepted &&
          acknowledged) {
        OtisSetupAuthorization released = {};
        const OtisSetupAuthorityContext current =
            current_dual_core_setup_authority_context(millis() / 1000u);
        if (otis_setup_authority_release_execution(
                &dual_core_timing_setup_guard, &current, &released)) {
          OtisCriticalRecordMessage execute = {};
          execute.kind = OtisCriticalMessageKind::SetupExecute;
          execute.sequence = released.request.command_sequence;
          execute.timestamp_ticks = otis_monotonic_us32_now();
          execute.setup_authorization = released;
          snprintf(execute.component, sizeof(execute.component), "%s",
                   "adaptive_hybrid_setup");
          snprintf(execute.reason, sizeof(execute.reason), "%s",
                   "core1_execution_released_after_current_recheck");
          publish_dual_core_setup_phase("core1_execution_released",
                                        released.request,
                                        OTIS_SEVERITY_INFO);
          if (!otis_dual_core_publish_critical(&execute))
            otis_adaptive_hybrid_regulation_live_abort(
                "setup_execution_release_queue_fault");
        } else {
          publish_dual_core_setup_phase(
              "core1_rejected_authority_regression",
              dual_core_timing_setup_guard.pending.request,
              OTIS_SEVERITY_ERROR);
          otis_adaptive_hybrid_regulation_live_abort(
              "setup_authority_regressed_before_execution");
        }
      } else if (ack.kind == OtisSetupApplicationAck::Kind::Applied &&
                 acknowledged) {
        publish_dual_core_setup_phase(
            "applied", dual_core_timing_setup_guard.pending.request,
            OTIS_SEVERITY_INFO);
        uint64_t setup_application_extended_ticks = 0u;
        if (!otis_frequency_regulation_live_project_setup_monotonic_us(
                ack.application_timestamp_ticks, ack.session_id,
                &setup_application_extended_ticks) ||
            !otis_adaptive_hybrid_regulation_live_note_manual_start_exact(
                ack.applied_code, 1u, true,
                static_cast<uint32_t>(setup_application_extended_ticks / 1000000ull),
                setup_application_extended_ticks, ack.session_id)) {
          otis_dual_core_latch_fault(
              OtisPartitionFault::ActuatorAcknowledgementMismatch);
          continue;
        }
        propagate_regulation_applied_epoch_to_previews_exact(
            ack.applied_code, 1u,
            static_cast<uint32_t>(setup_application_extended_ticks / 1000000ull),
            setup_application_extended_ticks, ack.session_id);
        if (!otis_adaptive_hybrid_regulation_live_confirm_setup_consumers_exact(
                ack.applied_code, 1u, setup_application_extended_ticks,
                ack.session_id))
          otis_dual_core_latch_fault(
              OtisPartitionFault::ActuatorAcknowledgementMismatch);
      } else {
        publish_dual_core_setup_phase(
            ack.kind == OtisSetupApplicationAck::Kind::Failed
                ? "failed"
                : "core1_rejected",
            dual_core_timing_setup_guard.pending.request,
            OTIS_SEVERITY_ERROR);
        otis_adaptive_hybrid_regulation_live_abort(
            "manual_start_application_not_exact");
        if (!acknowledged &&
            strcmp(dual_core_timing_setup_guard.reason,
                   "setup_application_acknowledgement_mismatch") == 0)
          otis_dual_core_latch_fault(
              OtisPartitionFault::ActuatorAcknowledgementMismatch);
      }
      continue;
    }
    if (message.kind == OtisServiceMessageKind::RunControl) {
      OtisCriticalRecordMessage transition = {};
      transition.kind = OtisCriticalMessageKind::StateTransition;
      transition.sequence = message.run_control.sequence;
      transition.timestamp_ticks = message.run_control.published_ticks;
      if (message.run_control.kind == OtisRunControlKind::CaptureLease) {
        const bool accepted = otis_adaptive_hybrid_regulation_live_capture_lease(
            message.run_control.capture_lease_sequence,
            millis() / 1000u);
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "adaptive_hybrid_regulation");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 accepted ? "capture_lease_accepted_on_core1"
                          : "capture_lease_rejected_on_core1");
        otis_dual_core_publish_critical(&transition);
      } else if (message.run_control.kind == OtisRunControlKind::Arm) {
        const bool accepted = otis_adaptive_hybrid_regulation_live_arm(
            message.run_control.authorization_sequence,
            message.run_control.nonce, message.run_control.expires_s,
            millis() / 1000u);
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "adaptive_hybrid_regulation");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 accepted ? "arm_accepted_on_core1"
                          : "arm_rejected_on_core1");
        otis_dual_core_publish_critical(&transition);
      } else if (message.run_control.kind ==
                 OtisRunControlKind::SetupAuthorize) {
        OtisSetupAuthorization authorization = {};
        const OtisSetupAuthorityContext current =
            current_dual_core_setup_authority_context(millis() / 1000u);
        const bool accepted = otis_setup_authorize(
            &dual_core_timing_setup_guard,
            &message.run_control.setup_request, &current, &authorization);
        publish_dual_core_setup_phase(
            accepted ? "core1_authorized" : "core1_rejected",
            message.run_control.setup_request,
            accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR);
        if (accepted) {
          OtisCriticalRecordMessage setup = {};
          setup.kind = OtisCriticalMessageKind::SetupAuthorization;
          setup.sequence = authorization.request.command_sequence;
          setup.timestamp_ticks = otis_monotonic_us32_now();
          setup.setup_authorization = authorization;
          snprintf(setup.component, sizeof(setup.component), "%s",
                   "adaptive_hybrid_setup");
          snprintf(setup.reason, sizeof(setup.reason), "%s",
                   "core1_current_setup_authority_accepted");
          if (!otis_dual_core_publish_critical(&setup))
            otis_adaptive_hybrid_regulation_live_abort(
                "setup_authorization_queue_fault");
        } else {
          otis_adaptive_hybrid_regulation_live_abort(
              "setup_current_authority_rejected");
        }
      } else if (message.run_control.kind == OtisRunControlKind::Abort) {
        otis_adaptive_hybrid_regulation_live_abort("device_abort_command_via_core0");
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "adaptive_hybrid_regulation");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 "abort_accepted_on_core1");
        otis_dual_core_publish_critical(&transition);
        // Preserve the resulting consumer state before the sole serial owner
        // closes when capacity permits. If a prior burst occupies the queue,
        // the admitted periodic publisher retains the ABORTED state later;
        // producer-side command delivery is not proof of consumption.
        publish_dual_core_active_status(millis());
      } else if (message.run_control.kind ==
                 OtisRunControlKind::EvidenceRelease) {
        const bool accepted = otis_adaptive_hybrid_regulation_live_acknowledge_evidence(
            message.run_control.request_sequence,
            message.run_control.evidence_phase, millis() / 1000u);
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "adaptive_hybrid_regulation");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 accepted ? "evidence_release_accepted_on_core1"
                          : "evidence_release_rejected_on_core1");
        otis_dual_core_publish_critical(&transition);
      } else if (message.run_control.kind ==
                 OtisRunControlKind::StatusQuery) {
        otis_adaptive_hybrid_regulation_live_set_status_query_nonce(
            message.run_control.nonce);
        const bool snapshot_published =
            publish_dual_core_active_status(millis());
        snprintf(transition.component, sizeof(transition.component), "%s",
                 "adaptive_hybrid_regulation");
        snprintf(transition.reason, sizeof(transition.reason), "%s",
                 snapshot_published
                     ? "status_query_snapshot_published_on_core1"
                     : "status_query_snapshot_deferred_capacity_on_core1");
        otis_dual_core_publish_critical(&transition);
      } else if (message.run_control.kind ==
                     OtisRunControlKind::DiagnosticConfigQuery ||
                 message.run_control.kind ==
                     OtisRunControlKind::DiagnosticRuntimeQuery) {
        publish_dual_core_diagnostic_snapshot(
            message.run_control.kind, message.run_control.sequence,
            message.run_control.nonce);
      }
    }
  }
}

bool publish_dual_core_actuator_ack(const OtisCrossCoreActuatorAck &ack) {
  OtisServiceMessage service = {};
  service.kind = OtisServiceMessageKind::ActuatorAcknowledgement;
  service.actuator_acknowledgement = ack;
  return otis_dual_core_publish_service(&service);
}

void service_dual_core_actuator_request(
    const OtisCriticalRecordMessage &critical) {
  const OtisCrossCoreActuatorRequest &request = critical.request;
  OtisCrossCoreActuatorAck acknowledgement = {};
  acknowledgement.request_sequence = request.request_sequence;
  acknowledgement.decision_sequence = request.decision_sequence;
  acknowledgement.authorization_sequence = request.authorization_sequence;
  acknowledgement.nonce = request.nonce;
  acknowledgement.acknowledgement_ticks = otis_monotonic_us32_now();
  acknowledgement.requested_code = request.requested_code;
  // Every pre-application outcome carries the unchanged physical code.  This
  // makes an exact Core 0 rejection distinguishable from a silent or
  // contradictory outcome without inferring state from zero initialization.
  acknowledgement.applied_code = request.current_applied_code;

  if (critical.kind == OtisCriticalMessageKind::ActuatorRequest) {
    const bool platform_fail_static = otis_dual_core_fail_static();
    const bool guard_started =
        !platform_fail_static &&
        otis_actuator_guard_start(&dual_core_service_actuator_guard, &request,
                                  millis() / 1000u);
    acknowledgement.kind = guard_started ? OtisActuatorAckKind::Accepted
                                         : OtisActuatorAckKind::Rejected;
    acknowledgement.rejection_reason =
        guard_started
            ? OtisActuatorRejectionReason::NotRejected
            : (platform_fail_static
                   ? OtisActuatorRejectionReason::PlatformFailStatic
                   : OtisActuatorRejectionReason::GuardStartRejected);
    acknowledgement.accepted_code = guard_started
                                        ? request.requested_code
                                        : request.current_applied_code;
    if (guard_started && !otis_actuator_guard_acknowledge(
                        &dual_core_service_actuator_guard,
                        &acknowledgement)) {
      acknowledgement.kind = OtisActuatorAckKind::Rejected;
      acknowledgement.rejection_reason =
          OtisActuatorRejectionReason::GuardAcknowledgementRejected;
      acknowledgement.accepted_code = request.current_applied_code;
    }
    publish_dual_core_actuator_ack(acknowledgement);
    return;
  }

  OtisActuatorRejectionReason execution_rejection =
      OtisActuatorRejectionReason::NotRejected;
  if (critical.kind != OtisCriticalMessageKind::ActuatorExecute) {
    execution_rejection =
        OtisActuatorRejectionReason::InvalidExecutionPhase;
  } else if (otis_dual_core_fail_static()) {
    execution_rejection = OtisActuatorRejectionReason::PlatformFailStatic;
  } else if (dual_core_service_actuator_guard.state !=
             OtisActuatorGuardState::AwaitingApplication) {
    execution_rejection =
        OtisActuatorRejectionReason::InvalidExecutionPhase;
  } else if (!otis_actuator_guard_check_deadline(
                 &dual_core_service_actuator_guard, millis() / 1000u)) {
    execution_rejection =
        OtisActuatorRejectionReason::AcknowledgementDeadlineExpired;
  }
  if (execution_rejection != OtisActuatorRejectionReason::NotRejected) {
    acknowledgement.kind = OtisActuatorAckKind::Rejected;
    acknowledgement.rejection_reason = execution_rejection;
    acknowledgement.accepted_code = request.current_applied_code;
    publish_dual_core_actuator_ack(acknowledgement);
    return;
  }

  const OtisCrossCoreActuatorRequest &pending =
      dual_core_service_actuator_guard.pending;
  const bool exact_release =
      request.request_sequence == pending.request_sequence &&
      request.decision_sequence == pending.decision_sequence &&
      request.session_id == pending.session_id &&
      request.source_acceptance_epoch == pending.source_acceptance_epoch &&
      request.source_acceptance_epoch != 0u &&
      request.source_opening_accepted_boundary_ordinal ==
          pending.source_opening_accepted_boundary_ordinal &&
      request.source_closing_accepted_boundary_ordinal ==
          pending.source_closing_accepted_boundary_ordinal &&
      otis_exact_selected_accepted_span(
          request.source_opening_accepted_boundary_ordinal,
          request.source_closing_accepted_boundary_ordinal) &&
      request.decision_reference_ticks == pending.decision_reference_ticks &&
      request.monotonic_deadline_s == pending.monotonic_deadline_s &&
      request.authorization_sequence == pending.authorization_sequence &&
      request.nonce == pending.nonce &&
      request.requested_delta_codes == pending.requested_delta_codes &&
      request.requested_code == pending.requested_code &&
      request.current_applied_code == pending.current_applied_code &&
      request.correction_ordinal == pending.correction_ordinal;
  if (!exact_release) {
    acknowledgement.kind = OtisActuatorAckKind::Rejected;
    acknowledgement.rejection_reason =
        OtisActuatorRejectionReason::ExecutionIdentityMismatch;
    acknowledgement.accepted_code = pending.current_applied_code;
    publish_dual_core_actuator_ack(acknowledgement);
    otis_dual_core_latch_fault(
        OtisPartitionFault::ActuatorAcknowledgementMismatch);
    return;
  }

  const OtisRegulationActionableRequest actionable = {
      pending.request_sequence,
      pending.authorization_sequence,
      pending.nonce,
      pending.session_id,
      pending.decision_sequence,
      pending.source_acceptance_epoch,
      pending.source_opening_accepted_boundary_ordinal,
      pending.source_closing_accepted_boundary_ordinal,
      static_cast<uint32_t>(pending.decision_reference_ticks / 1000000ull),
      pending.current_applied_code,
      pending.requested_delta_codes,
      pending.requested_code,
      0.0,
      pending.correction_ordinal,
      0u,
      true,
  };
  const OtisRegulationAcceptedRequest accepted = {
      pending.request_sequence,
      pending.authorization_sequence,
      pending.nonce,
      pending.requested_code,
      static_cast<uint32_t>(acknowledgement.acknowledgement_ticks /
                            1000000ull),
      false,
  };
  const OtisRegulationAppliedAck applied = otis_regulation_actuator_apply_once(
      &actionable, &accepted, pending.correction_ordinal,
      static_cast<uint32_t>(acknowledgement.acknowledgement_ticks /
                            1000000ull));
  // Replace the pre-write/acceptance value with the first exact local
  // microsecond sample
  // after the sole DAC write attempt returns.
  acknowledgement.acknowledgement_ticks = otis_monotonic_us32_now();
  acknowledgement.kind = OtisActuatorAckKind::Applied;
  acknowledgement.rejection_reason =
      OtisActuatorRejectionReason::NotRejected;
  acknowledgement.accepted_code = applied.accepted_code;
  acknowledgement.applied_code = applied.applied_code;
  acknowledgement.i2c_ok = applied.i2c_ok;
  acknowledgement.clamped = applied.clamped;
  acknowledgement.ambiguous = applied.ambiguous;
  otis_actuator_guard_acknowledge(&dual_core_service_actuator_guard,
                                  &acknowledgement);
  otis_emit_dac_step(
      runtime_state.sequences.dac_seq++, millis(),
      static_cast<int32_t>(pending.request_sequence), pending.requested_code,
      applied.applied_code, applied.clamped, "", "", 0u,
      applied.i2c_ok && !applied.ambiguous ? "active_apply"
                                          : "active_write_failed",
      applied.i2c_ok && !applied.ambiguous
          ? OTIS_FLAG_NONE
          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  publish_dual_core_actuator_ack(acknowledgement);
}

bool publish_dual_core_setup_ack(const OtisSetupApplicationAck &ack) {
  OtisServiceMessage service = {};
  service.kind = OtisServiceMessageKind::SetupApplicationAcknowledgement;
  service.setup_acknowledgement = ack;
  return otis_dual_core_publish_service(&service);
}

void emit_dual_core_setup_phase_direct(
    const char *phase, const OtisSetupAuthorityRequest &request,
    const char *severity) {
  emit_status_direct("adaptive_hybrid_setup", "phase", phase, severity,
                     OTIS_FLAG_NONE);
  char value[24];
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(request.command_sequence));
  emit_status_direct("adaptive_hybrid_setup", "command_sequence", value, severity,
                     OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(request.authorization_sequence));
  emit_status_direct("adaptive_hybrid_setup", "authorization_sequence", value,
                     severity, OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(request.status_generation));
  emit_status_direct("adaptive_hybrid_setup", "status_generation", value, severity,
                     OTIS_FLAG_NONE);
  snprintf(value, sizeof(value), "%lu",
           static_cast<unsigned long>(request.query_nonce));
  emit_status_direct("adaptive_hybrid_setup", "query_nonce", value, severity,
                     OTIS_FLAG_NONE);
}

void service_dual_core_setup_transaction(
    const OtisCriticalRecordMessage &critical) {
  const OtisSetupAuthorization &authorization =
      critical.setup_authorization;
  const OtisSetupAuthorityRequest &request = authorization.request;
  OtisSetupApplicationAck acknowledgement = {};
  acknowledgement.command_sequence = request.command_sequence;
  acknowledgement.authorization_sequence = request.authorization_sequence;
  acknowledgement.status_generation = request.status_generation;
  acknowledgement.query_nonce = request.query_nonce;
  acknowledgement.session_id = request.session_id;
  acknowledgement.requested_code = request.requested_code;
  acknowledgement.one_shot_ordinal = request.one_shot_ordinal;

  const OtisSetupExecutionContext current =
      current_dual_core_setup_execution_context(millis() / 1000u);
  if (critical.kind == OtisCriticalMessageKind::SetupAuthorization) {
    const bool accepted = otis_setup_execution_accept(
        &dual_core_service_setup_guard, &authorization, &current);
    acknowledgement.kind =
        accepted ? OtisSetupApplicationAck::Kind::Core0Accepted
                 : OtisSetupApplicationAck::Kind::Core0Rejected;
    acknowledgement.i2c_ok = accepted;
    emit_dual_core_setup_phase_direct(
        accepted ? "request_accepted" : "core0_rejected", request,
        accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR);
    publish_dual_core_setup_ack(acknowledgement);
    return;
  }

  if (critical.kind != OtisCriticalMessageKind::SetupExecute ||
      !otis_setup_execution_consume(&dual_core_service_setup_guard,
                                    &authorization, &current)) {
    acknowledgement.kind = OtisSetupApplicationAck::Kind::Failed;
    acknowledgement.i2c_ok = false;
    emit_dual_core_setup_phase_direct("failed_before_i2c", request,
                                      OTIS_SEVERITY_ERROR);
    publish_dual_core_setup_ack(acknowledgement);
    return;
  }

  // The authority is consumed before the sole physical attempt. A failed or
  // ambiguous I2C call is terminal for this boot and is never retried.
  dual_core_manual_start_consumed = true;
  const bool ok = otis_dac_ad5693r_set_raw(request.requested_code);
  acknowledgement.application_timestamp_ticks = otis_monotonic_us32_now();
  acknowledgement.kind = ok ? OtisSetupApplicationAck::Kind::Applied
                            : OtisSetupApplicationAck::Kind::Failed;
  acknowledgement.applied_code = ok ? request.requested_code : 0u;
  acknowledgement.i2c_ok = ok;
  otis_emit_dac_step(
      runtime_state.sequences.dac_seq++, millis(),
      static_cast<int32_t>(request.command_sequence), request.requested_code,
      request.requested_code, false, "", "", 0u,
      ok ? "manual_apply" : "manual_write_failed",
      ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_dual_core_setup_phase_direct(ok ? "applied" : "failed", request,
                                    ok ? OTIS_SEVERITY_INFO
                                       : OTIS_SEVERITY_ERROR);
  publish_dual_core_setup_ack(acknowledgement);
}

void service_dual_core_outputs(void) {
  OtisObservationMessage observation;
  uint8_t raw_budget = 24u;
  while (raw_budget-- > 0u &&
         otis_dual_core_take_observation(&observation)) {
    if (observation.kind == OtisObservationMessageKind::RawEdge) {
      const OtisRawEdgeMessage &edge = observation.raw_edge;
      otis_emit_raw_event(edge.reference_record ? OTIS_RECORD_REF
                                                : OTIS_RECORD_EVT,
                          edge.sequence, edge.channel_id,
                          edge_string(edge.edge), edge.timestamp_ticks,
                          OTIS_DOMAIN_RP2040_MONOTONIC_US32, edge.flags);
    } else if (observation.kind ==
               OtisObservationMessageKind::PpsSnapshot) {
      const OtisPpsSnapshotMessage &snapshot = observation.snapshot;
      otis_emit_pps_snapshot(
          snapshot.session, snapshot.sequence,
          snapshot.cumulative_down_counter, snapshot.reference_sequence,
          snapshot.reference_timestamp_ticks, snapshot.status,
          "pio_wait_cumulative_snapshot_dma_v1");
    } else if (observation.kind ==
               OtisObservationMessageKind::CountObservation) {
      const OtisCountObservationMessage &count = observation.count;
      otis_emit_count_observation(
          count.sequence, count.channel_id, count.gate_open_ticks,
          count.gate_close_ticks, OTIS_DOMAIN_RP2040_MONOTONIC_US32,
          count.counted_edges, OTIS_EDGE_RISING, count.source_domain,
          count.flags);
    }
  }

  OtisMonitorObservationMessage monitor_observation;
  uint8_t monitor_budget = 8u;
  while (monitor_budget-- > 0u &&
         otis_dual_core_take_monitor_observation(&monitor_observation)) {
    otis_emit_forwarded_monitor_snapshot(
        monitor_observation.session, monitor_observation.reference_session,
        monitor_observation.sequence,
        monitor_observation.cumulative_down_counter,
        monitor_observation.reference_sequence,
        monitor_observation.reference_timestamp_ticks,
        monitor_observation.status,
        "pio_wait_cumulative_snapshot_cpu_v1",
        monitor_observation.channel_id);
  }

  OtisCriticalRecordMessage critical;
  uint8_t critical_budget = 8u;
  while (critical_budget-- > 0u &&
         otis_dual_core_take_critical(&critical)) {
    if (critical.kind == OtisCriticalMessageKind::ActuatorRequest ||
        critical.kind == OtisCriticalMessageKind::ActuatorExecute) {
      service_dual_core_actuator_request(critical);
    } else if (critical.kind ==
                   OtisCriticalMessageKind::SetupAuthorization ||
               critical.kind == OtisCriticalMessageKind::SetupExecute) {
      service_dual_core_setup_transaction(critical);
    }
    emit_status_direct(critical.component[0] == '\0' ? "dual_core"
                                                      : critical.component,
                       "critical_record", critical.reason,
                       critical.kind == OtisCriticalMessageKind::Fault
                           ? OTIS_SEVERITY_ERROR
                           : OTIS_SEVERITY_INFO,
                       critical.flags);
  }

  OtisTelemetryMessage telemetry;
  uint8_t telemetry_budget = 12u;
  while (telemetry_budget-- > 0u &&
         otis_dual_core_take_telemetry(&telemetry)) {
    emit_status_direct(telemetry.component, telemetry.key, telemetry.value,
                       telemetry.severity, telemetry.flags);
    if (__atomic_load_n(&dual_core_timing_boot_in_progress,
                        __ATOMIC_ACQUIRE)) {
      otis_gnss_receiver_service(millis());
    }
  }
}

void service_forwarded_clock_monitor_boundary(
    const OtisPpsCountBoundaryObservation &authoritative) {
  if (!otis_forwarded_clock_monitor_service(
          authoritative.session, authoritative.reference_sequence)) {
    return;
  }
  OtisForwardedClockMonitorSnapshot snapshot = {};
  if (!otis_forwarded_clock_monitor_read(&snapshot)) return;

  OtisMonitorObservationMessage raw = {};
  raw.kind = OtisMonitorObservationKind::Snapshot;
  raw.session = snapshot.session;
  raw.reference_session = snapshot.reference_session;
  raw.sequence = snapshot.sequence;
  raw.cumulative_down_counter = snapshot.cumulative_down_counter;
  raw.reference_sequence = snapshot.reference_sequence;
  raw.reference_timestamp_ticks = authoritative.pps_timestamp_ticks;
  raw.status = snapshot.status;
  raw.channel_id = OTIS_CHANNEL_FORWARDED_CLOCK_MONITOR;
  otis_dual_core_publish_monitor_observation(&raw);
}

bool dual_core_evidence_transport_busy(void) {
  return dual_core_evidence_transport_active;
}

bool dual_core_evidence_transport_pending(void) {
  if (dual_core_evidence_transport_active) return true;
  OtisDualCoreQueueStats stats = {};
  otis_dual_core_get_stats(&stats);
  return stats.evidence_depth != 0u;
}

void service_dual_core_evidence_transport(void) {
  if (!dual_core_evidence_transport_active) {
    if (!otis_dual_core_take_evidence(&dual_core_evidence_transport)) return;
    dual_core_evidence_transport_sent = 0u;
    dual_core_evidence_transport_active = true;
  }
  size_t available = otis_transport_available_for_write();
  if (available == 0u) return;
  size_t remaining = static_cast<size_t>(
      dual_core_evidence_transport.length - dual_core_evidence_transport_sent);
  size_t chunk = remaining < available ? remaining : available;
  if (chunk > 192u) chunk = 192u;
  dual_core_evidence_transport_sent = static_cast<uint16_t>(
      dual_core_evidence_transport_sent + otis_transport_write_bytes(
          reinterpret_cast<const uint8_t *>(dual_core_evidence_transport.data) +
              dual_core_evidence_transport_sent,
          chunk));
  if (dual_core_evidence_transport_sent ==
      dual_core_evidence_transport.length) {
    dual_core_evidence_transport = {};
    dual_core_evidence_transport_sent = 0u;
    dual_core_evidence_transport_active = false;
  }
}

bool service_dual_core_serial_frame_transport(void) {
  const OtisSerialFrameReadiness readiness = {
      dual_core_evidence_transport_pending(),
      otis_frequency_regulation_live_transport_pending(),
      otis_phase_preview_transport_busy(),
  };
  const OtisSerialFrameOwner owner = otis_serial_frame_arbiter_claim(
      &dual_core_serial_frame_arbiter, readiness);
  if (owner == OtisSerialFrameOwner::None) return false;

  bool frame_active = false;
  switch (owner) {
    case OtisSerialFrameOwner::DualCoreEvidence:
      service_dual_core_evidence_transport();
      frame_active = dual_core_evidence_transport_busy();
      break;
    case OtisSerialFrameOwner::FrequencyRegulation:
      otis_frequency_regulation_live_service_transport();
      frame_active = otis_frequency_regulation_live_transport_busy();
      break;
    case OtisSerialFrameOwner::PhasePreview:
      otis_phase_preview_transport_service();
      frame_active = otis_phase_preview_transport_frame_active();
      break;
    case OtisSerialFrameOwner::None:
      return false;
  }
  if (!frame_active)
    otis_serial_frame_arbiter_release(&dual_core_serial_frame_arbiter, owner);
  return frame_active;
}

void discard_dual_core_outputs_after_transport_fault(void) {
  // The byte stream is quarantined after a partial-frame timeout. Continue
  // bounded queue consumption without executing actuator requests or
  // pretending the discarded records are durable evidence. Reset/new session
  // is the only supported recovery.
  OtisObservationMessage observation;
  for (uint8_t budget = 24u;
       budget-- > 0u && otis_dual_core_take_observation(&observation);) {}
  OtisMonitorObservationMessage monitor_observation;
  for (uint8_t budget = 8u;
       budget-- > 0u &&
       otis_dual_core_take_monitor_observation(&monitor_observation);) {}
  OtisCriticalRecordMessage critical;
  for (uint8_t budget = 8u;
       budget-- > 0u && otis_dual_core_take_critical(&critical);) {}
  OtisTelemetryMessage telemetry;
  for (uint8_t budget = 12u;
       budget-- > 0u && otis_dual_core_take_telemetry(&telemetry);) {}
  OtisEvidenceFrameMessage evidence;
  (void)otis_dual_core_take_evidence(&evidence);
  OtisPhasePreviewRecordMessage phase_preview;
  (void)otis_dual_core_take_phase_preview(&phase_preview);
}

void note_pre_carrier_discard(void) {
  if (dual_core_pre_carrier_records_discarded != UINT32_MAX)
    dual_core_pre_carrier_records_discarded++;
}

void discard_dual_core_outputs_before_first_carrier(void) {
  // Core 0 owns every outbound SPSC consumer before and after attachment.
  // Core 1 continues producing; changing USB state never transfers ownership.
  OtisObservationMessage observation;
  for (uint8_t budget = 24u;
       budget-- > 0u && otis_dual_core_take_observation(&observation);)
    note_pre_carrier_discard();
  OtisMonitorObservationMessage monitor_observation;
  for (uint8_t budget = 8u;
       budget-- > 0u &&
       otis_dual_core_take_monitor_observation(&monitor_observation);)
    note_pre_carrier_discard();
  OtisCriticalRecordMessage critical;
  for (uint8_t budget = 8u;
       budget-- > 0u && otis_dual_core_take_critical(&critical);)
    note_pre_carrier_discard();
  OtisTelemetryMessage telemetry;
  for (uint8_t budget = 24u;
       budget-- > 0u && otis_dual_core_take_telemetry(&telemetry);)
    note_pre_carrier_discard();
  OtisEvidenceFrameMessage evidence;
  if (otis_dual_core_take_evidence(&evidence)) note_pre_carrier_discard();
  OtisPhasePreviewRecordMessage phase_preview;
  if (otis_dual_core_take_phase_preview(&phase_preview))
    note_pre_carrier_discard();
}

void abandon_dual_core_serial_frames_on_carrier_loss(void) {
  uint32_t abandoned = 0u;
  if (dual_core_evidence_transport_active) {
    dual_core_evidence_transport = {};
    dual_core_evidence_transport_sent = 0u;
    dual_core_evidence_transport_active = false;
    abandoned++;
  }
  if (otis_phase_preview_transport_abandon_active_frame()) abandoned++;
  otis_serial_frame_arbiter_reset(&dual_core_serial_frame_arbiter);
  // CONFIG? must re-establish a complete build-provenance block for the next
  // evidence segment even though this firmware boot and DAC state continue.
  config_query_provenance_emitted = false;
  const uint32_t remaining = UINT32_MAX -
                             dual_core_carrier_loss_frames_abandoned;
  dual_core_carrier_loss_frames_abandoned +=
      abandoned < remaining ? abandoned : remaining;
}

void publish_dual_core_association_loss_decision(
    const char *reason, uint64_t decision_ticks,
    const OtisPpsCountBoundaryObservation &pending_reference,
    uint64_t pending_age_ticks, uint32_t boundary_depth,
    uint32_t boundary_dropped_count,
    const OtisPpsCountBoundaryObservation *next_reference,
    const OtisPpsSnapshotBackendStats &snapshot_stats,
    const OtisPpsSnapshotFrozenDiagnostic &frozen) {
  OtisDualCoreQueueStats queue_stats = {};
  otis_dual_core_get_stats(&queue_stats);
  const bool unread_snapshot = snapshot_stats.backlog_depth != 0u;
  const char *classification =
      snapshot_stats.fault_latched
          ? "backend_fault"
          : (unread_snapshot
                 ? "unread_snapshot_present_when_decision_made"
                 : (reason != nullptr &&
                            strcmp(reason, "snapshot_association_timeout") == 0
                        ? "timeout_no_snapshot"
                        : "no_unread_snapshot_healthy_backend"));

  dual_core_association_loss_scratch = {};
  dual_core_association_loss_scratch.sequence =
      dual_core_association_loss_decision_sequence++;
  const int used = snprintf(
      dual_core_association_loss_scratch.data,
      sizeof(dual_core_association_loss_scratch.data),
      "ASL,2,%lu,%s,%s,%llu,%lu,%llu,%llu,%lu,%lu,%s,%lu,%llu,%s,%s,%s,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%s,%llu,%llu,%s,%lu,%lu,%lu,%lu,%lu,%s,%lu\r\n",
      static_cast<unsigned long>(dual_core_association_loss_scratch.sequence),
      reason == nullptr ? "association_loss_unspecified" : reason,
      classification, static_cast<unsigned long long>(decision_ticks),
      static_cast<unsigned long>(pending_reference.reference_sequence),
      static_cast<unsigned long long>(pending_reference.pps_timestamp_ticks),
      static_cast<unsigned long long>(pending_age_ticks),
      static_cast<unsigned long>(boundary_depth),
      static_cast<unsigned long>(boundary_dropped_count),
      next_reference == nullptr ? "false" : "true",
      static_cast<unsigned long>(next_reference == nullptr
                                     ? 0u
                                     : next_reference->reference_sequence),
      static_cast<unsigned long long>(
          next_reference == nullptr ? 0u : next_reference->pps_timestamp_ticks),
      snapshot_stats.initialized ? "true" : "false",
      snapshot_stats.running ? "true" : "false",
      snapshot_stats.fault_latched ? "true" : "false",
      static_cast<unsigned long>(snapshot_stats.fault_flags),
      static_cast<unsigned long>(snapshot_stats.session),
      static_cast<unsigned long>(snapshot_stats.producer_ordinal),
      static_cast<unsigned long>(snapshot_stats.consumer_ordinal),
      static_cast<unsigned long>(snapshot_stats.backlog_depth),
      static_cast<unsigned long>(snapshot_stats.backlog_high_water),
      static_cast<unsigned long>(snapshot_stats.overwrite_count),
      static_cast<unsigned long>(snapshot_stats.continuity_loss_count),
      static_cast<unsigned long>(snapshot_stats.pio_rxstall_count),
      static_cast<unsigned long>(snapshot_stats.dma_error_count),
      static_cast<unsigned long>(snapshot_stats.dma_stopped_count),
      static_cast<unsigned long>(queue_stats.timing_progress.loop_sequence),
      static_cast<unsigned long>(queue_stats.timing_progress.last_snapshot_session),
      static_cast<unsigned long>(queue_stats.timing_progress.last_snapshot_sequence),
      otis_timing_progress_phase_name(queue_stats.timing_progress.phase),
      static_cast<unsigned long long>(
          queue_stats.timing_progress.phase_enter_ticks),
      static_cast<unsigned long long>(
          queue_stats.timing_progress.last_progress_ticks),
      frozen.frozen ? "true" : "false",
      static_cast<unsigned long>(frozen.session),
      static_cast<unsigned long>(frozen.producer_ordinal),
      static_cast<unsigned long>(frozen.consumer_ordinal),
      static_cast<unsigned long>(frozen.backlog_depth),
      static_cast<unsigned long>(frozen.pio_fifo_depth),
      frozen.front_word_present ? "true" : "false",
      static_cast<unsigned long>(frozen.front_word));
  if (used <= 0 || static_cast<size_t>(used) >=
                       sizeof(dual_core_association_loss_scratch.data)) {
    otis_dual_core_latch_fault(OtisPartitionFault::EvidenceExhausted);
    return;
  }
  dual_core_association_loss_scratch.length = static_cast<uint16_t>(used);
  otis_dual_core_publish_evidence(&dual_core_association_loss_scratch);
}

void emit_captured_edge(const OtisCapturedEdge &record) {
  if (record.reference_record && record.edge == 'R') {
    otis_capture_irq_process_reference_foreground(record);
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
  }

  OtisObservationMessage message = {};
  message.kind = OtisObservationMessageKind::RawEdge;
  message.raw_edge.sequence = runtime_state.sequences.event_seq++;
  message.raw_edge.timestamp_ticks = record.timestamp_ticks;
  message.raw_edge.flags = record.flags;
  message.raw_edge.channel_id = record.channel_id;
  message.raw_edge.edge = record.edge;
  message.raw_edge.reference_record = record.reference_record;
  otis_dual_core_publish_observation(&message);
  runtime_state.capture.emitted_event_count++;
}

OtisRegulationStaticCodeState regulation_static_code_state(void) {
  return dual_core_static_code;
}

void update_adaptive_hybrid_regulation_health(void) {
  const uint32_t now_ms = millis();
  OtisPpsSnapshotBackendStats snapshot;
  otis_pps_snapshot_backend_get_stats(&snapshot);
  OtisCaptureIrqReferenceStats d14;
  otis_capture_irq_get_reference_stats(&d14);
  // D14 is the sole PPS/reference authority and the PIO snapshot backend
  // counts only D8 oscillator edges at D14 boundaries. D10 is the independent
  // external-event input; this fixed image does not claim it and no D10 observation
  // may validate or veto this control-health predicate.
  // Raw aperture rejection remains diagnostic. Accepted-reference continuity
  // and freshness own measurement/control admission; receiver metadata is an
  // independent actuation gate and cannot erase the measurement histories.
  reference_acceptance.service(time_us_64());
  const auto &accepted = reference_acceptance.status();
  otis_count_observation_update_reference_acceptance(accepted);
  const bool raw_pps_valid = d14.d14_accepted_pps_count > 0u;
  const bool reference_integrity_valid =
      otis_capture_ring_dropped_count() == 0u &&
      otis_pps_count_boundary_ring_dropped_count() == 0u &&
      !snapshot.fault_latched;
  OtisFrequencyRegulationAuthorityState preview;
  otis_frequency_regulation_live_get_authority_state(&preview);
  const bool applied_confirmed =
      dual_core_static_code.available &&
      dual_core_static_code.requested_applied_match &&
      dual_core_static_code.i2c_ok;
  OtisAdaptiveHybridRegulationLiveHealth health = {};
  health.session_id = snapshot.session;
  health.acceptance_epoch = accepted.acceptance_epoch;
  health.accepted_boundary_ordinal = accepted.accepted_boundary_ordinal;
  health.reference_acceptance_policy_sha256 = OTIS_REFERENCE_ACCEPTANCE_POLICY_SHA256;
  health.reference_acceptance_state = accepted.state;
  health.accepted_anchor_current = accepted.anchor_current;
  health.gnss_metadata_sequence = dual_core_receiver.metadata_sequence;
  health.gnss_metadata_valid = dual_core_receiver_qualified_for_control();
  health.gnss_identity_stable = dual_core_receiver.identity_stable;
  health.gnss_3d_evidence = dual_core_receiver.gsa_3d;
  health.raw_pps_valid = raw_pps_valid;
  health.reference_integrity_valid = reference_integrity_valid;
  health.count_valid = accepted.tracking && accepted.anchor_current &&
      accepted.capture_session == snapshot.session &&
      uint32_t(now_ms - runtime_state.tcxo.startup_inhibit_start_ms) >= kCountStartupInhibitMs;
  health.estimator_valid = preview.estimator_valid;
  health.model_applicable = preview.model_applicable;
  health.temperature_valid = preview.temperature_valid;
  health.applied_code_confirmed = applied_confirmed;
  health.applied_code = dual_core_static_code.applied_code;
  health.abort_path_live = !otis_dual_core_fail_static();
  health.selected_interval_count = preview.selected_interval_count;
  otis_adaptive_hybrid_regulation_live_update_health_at_ticks(
      &health, now_ms / 1000u, otis_monotonic_us32_now());
}

void service_adaptive_hybrid_regulation_health(void) {
  update_adaptive_hybrid_regulation_health();
  otis_adaptive_hybrid_regulation_live_service(millis() / 1000u);
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
  return OTIS_DOMAIN_H1_OSCILLATOR_10MHZ;
}

OtisCountObservationConfig count_observation_config(void) {
  return {
      kTcxoGatePeriodUs,
      kCountStartupInhibitMs,
      kCountControlReadyCleanWindows,
      osc_observation_domain(),
  };
}

void drain_capture_ring(void) {
  OtisCapturedEdge record;
  // A hostile/noisy input may continue refilling the ISR ring while Core 1
  // drains it. One full declared ring per pass bounds the phase and guarantees
  // later service/control phases receive CPU time.
  uint32_t budget = OTIS_CAPTURE_RING_SIZE - 1u;
  while (budget-- > 0u && otis_capture_ring_pop(&record)) {
    emit_captured_edge(record);
  }
}

void emit_pps_count_boundary(
    const OtisPpsCountBoundaryObservation &observation,
    uint32_t snapshot_status) {
  // timerawl/micros() and time_us_64() are two widths of the same RP2040
  // hardware microsecond counter. Project the captured low word into its
  // nearest past 64-bit coordinate, with an explicit bounded service age.
  const uint64_t now_ticks = time_us_64();
  const uint32_t capture_age = uint32_t(now_ticks) -
      uint32_t(observation.pps_timestamp_ticks);
  const uint64_t closing_extended_ticks =
      now_ticks >= capture_age ? now_ticks - capture_age : UINT64_MAX;
  const OtisReferenceAcceptanceObservation paired = {
      observation.session, observation.sequence, observation.reference_sequence,
      uint32_t(observation.pps_timestamp_ticks),
      observation.cumulative_down_counter, snapshot_status, observation.capture_flags};
  OtisReferenceAcceptanceOutcome selection = reference_acceptance.observe(
      paired, closing_extended_ticks, now_ticks,
      OTIS_ESTIMATE_TO_DECISION_MAXIMUM_LAG_TICKS);
  otis_count_observation_update_reference_acceptance(reference_acceptance.status());

  // Canonical raw CNT production remains independent of accepted selection.
  // Its shorter rejected fragments are retained before derived APS evidence.
  OtisCountObservationConfig count_config = count_observation_config();
  const bool window_completed = otis_count_observation_on_pps_boundary(
      &runtime_state, &status_emit_context, &count_config, &observation);
  if (selection.has_span) {
    // Reuse the timing owner's existing sequential evidence scratch buffer.
    // Association-loss and accepted-span formatting cannot be concurrent.
    auto &frame = dual_core_association_loss_scratch;
    frame = {};
    if (!otis_reference_acceptance_format_span(selection,
            OTIS_REFERENCE_ACCEPTANCE_POLICY_SHA256, frame.data,
            sizeof(frame.data), &frame.length) ||
        !otis_dual_core_publish_evidence(&frame)) {
      selection = reference_acceptance.invalidate(
          OtisReferenceAcceptanceReason::CaptureIntegrity);
      otis_count_observation_update_reference_acceptance(reference_acceptance.status());
      otis_dual_core_latch_fault(OtisPartitionFault::EvidenceExhausted);
    }
  }
  const OtisRegulationStaticCodeState regulation_code = regulation_static_code_state();
  OtisAdaptiveHybridRegulationLiveOutcome active_outcome = {};
  // Both consumers receive the identical immutable selection. Publishing phase
  // before the frequency decision binds its first dependent control consumer.
  otis_phase_preview_live_on_reference_selection(
      &selection, closing_extended_ticks, false);
  update_adaptive_hybrid_regulation_health();
  otis_frequency_regulation_live_on_reference_selection(
      &selection, closing_extended_ticks, millis() / 1000u,
      otis_monotonic_us32_now(), &regulation_code, &active_outcome);
  if (active_outcome.application_attempted) {
    otis_emit_dac_step(
        runtime_state.sequences.dac_seq++, millis(),
        static_cast<int32_t>(active_outcome.request_sequence),
        active_outcome.requested_code, active_outcome.applied_code, false, "",
        "", 0u,
        active_outcome.applied ? "active_apply" : "active_write_failed",
        active_outcome.applied ? OTIS_FLAG_NONE
                               : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  if (window_completed) {
    otis_dual_core_note_timing_count(runtime_state.sequences.count_seq - 1u);
    otis_count_observation_note_control_consumer(observation.session,
                                                 observation.sequence);
  }
}

void service_adaptive_hybrid_regulation_application_outcome(void) {
  OtisAdaptiveHybridRegulationLiveOutcome active_outcome;
  if (!otis_adaptive_hybrid_regulation_live_take_application_outcome(&active_outcome)) return;
  if (active_outcome.applied) {
    propagate_regulation_applied_epoch_to_previews_exact(
        active_outcome.applied_code, active_outcome.dac_epoch,
        millis() / 1000u, active_outcome.application_timestamp_ticks,
        active_outcome.capture_session);
  }
  otis_adaptive_hybrid_regulation_live_complete_application_evidence(
      active_outcome.request_sequence, active_outcome.applied,
      millis() / 1000u);
}

void drain_pps_count_boundary_ring(void) {
  static bool have_pending_reference = false;
  static OtisPpsCountBoundaryObservation pending_reference = {};
  static OtisPpsSnapshotAssociationGuard snapshot_association_guard = {};

  if (!have_pending_reference) {
    have_pending_reference =
        otis_pps_count_boundary_ring_pop(&pending_reference);
  }
  if (!have_pending_reference) {
    return;
  }

  OtisPpsSnapshotBackendStats stats;
  otis_pps_snapshot_backend_get_stats(&stats);
  uint64_t pending_age_ticks = otis_monotonic_us32_interval(
      pending_reference.pps_timestamp_ticks, otis_monotonic_us32_now());
  uint64_t association_timeout_ticks =
      static_cast<uint64_t>(OTIS_PPS_GATE_MAX_INTERVAL_US);
  bool another_reference_waiting =
      otis_pps_count_boundary_ring_depth() != 0u;
  const OtisPpsSnapshotAssociationDecision association_decision =
      otis_pps_snapshot_association_decide(
          &snapshot_association_guard, stats.backlog_depth != 0u,
          stats.session, stats.consumer_ordinal, another_reference_waiting);
  if (stats.fault_latched ||
      association_decision ==
          OtisPpsSnapshotAssociationDecision::AssociationLoss ||
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
    OtisPpsCountBoundaryObservation next_reference = {};
    const bool have_next_reference =
        otis_pps_count_boundary_ring_peek(&next_reference);
    const uint64_t decision_ticks = otis_monotonic_us32_now();
    // Recovery clears the DMA ring. Freeze its unread front as diagnostic
    // evidence only; it must never become a paired SNP or control input.
    OtisPpsSnapshotFrozenDiagnostic frozen = {};
    otis_pps_snapshot_backend_freeze_diagnostic(&frozen);
    publish_dual_core_association_loss_decision(
        association_reason, decision_ticks, pending_reference,
        pending_age_ticks, otis_pps_count_boundary_ring_depth(),
        otis_pps_count_boundary_ring_dropped_count(),
        have_next_reference ? &next_reference : nullptr, stats, frozen);
    reference_acceptance.invalidate(OtisReferenceAcceptanceReason::CaptureIntegrity);
    otis_count_observation_update_reference_acceptance(reference_acceptance.status());
    otis_count_observation_note_association_loss(
        &runtime_state, &status_emit_context,
        pending_reference.reference_sequence, association_reason);
    const OtisRegulationStaticCodeState regulation_code = regulation_static_code_state();
    otis_frequency_regulation_live_on_capture_fault(
        association_reason, millis() / 1000u, &regulation_code);
    otis_phase_preview_live_note_reset();
    otis_pps_snapshot_association_guard_reset(&snapshot_association_guard);
    otis_pps_snapshot_backend_rearm();
    otis_pps_count_boundary_ring_reset();
    have_pending_reference = false;
    return;
  }

  // The capture drain follows this service phase.  Defer a newly visible PIO
  // word for one complete loop so a CPU-only short REF followed by the genuine
  // same-boundary REF cannot consume and shift otherwise valid PIO snapshots.
  if (association_decision !=
      OtisPpsSnapshotAssociationDecision::Pair) {
    return;
  }

  OtisPpsHardwareSnapshot snapshot;
  if (!otis_pps_snapshot_backend_pop(&snapshot)) {
    return;
  }
  otis_pps_snapshot_association_guard_reset(&snapshot_association_guard);

  OtisPpsCountBoundaryObservation observation = pending_reference;
  observation.session = snapshot.session;
  observation.sequence = snapshot.sequence;
  observation.cumulative_down_counter = snapshot.cumulative_down_counter;
  if ((snapshot.status & OTIS_PPS_SNAPSHOT_STATUS_OVERWRITE_BEFORE) != 0u) {
    observation.aperture_flags |=
        OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW |
        OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE;
  }
  OtisObservationMessage snapshot_message = {};
  snapshot_message.kind = OtisObservationMessageKind::PpsSnapshot;
  snapshot_message.snapshot.session = observation.session;
  snapshot_message.snapshot.sequence = observation.sequence;
  snapshot_message.snapshot.cumulative_down_counter =
      observation.cumulative_down_counter;
  snapshot_message.snapshot.reference_sequence =
      observation.reference_sequence;
  snapshot_message.snapshot.reference_timestamp_ticks =
      observation.pps_timestamp_ticks;
  snapshot_message.snapshot.status = snapshot.status;
  otis_dual_core_note_timing_snapshot(observation.session,
                                      observation.sequence);
  otis_dual_core_publish_observation(&snapshot_message);
  emit_pps_count_boundary(observation, snapshot.status);
  service_forwarded_clock_monitor_boundary(observation);
  have_pending_reference = false;
}

void emit_build_provenance_status(void) {
  emit_status("build", "provenance_format", OTIS_BUILD_PROVENANCE_FORMAT,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("protocol", "contract_id",
              OTIS_BUILD_FIRMWARE_HOST_CONTRACT_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("protocol", "contract_sha256",
              OTIS_BUILD_FIRMWARE_HOST_CONTRACT_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("firmware", "git_commit", OTIS_FIRMWARE_GIT_COMMIT,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("firmware", "source_state", OTIS_BUILD_SOURCE_STATE,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("firmware", "source_hash", OTIS_BUILD_SOURCE_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("firmware", "config_hash", OTIS_BUILD_CONFIG_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("system", "board", OTIS_TARGET_BOARD, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("system", "board_name", OTIS_TARGET_BOARD_NAME,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("system", "fqbn", OTIS_BUILD_FQBN, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("system", "arduino_core_provider", OTIS_BUILD_CORE_PROVIDER,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("system", "arduino_core_version", OTIS_BUILD_CORE_VERSION,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("system", "arduino_core_installed_hash",
              OTIS_BUILD_CORE_INSTALLED_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "image_id", OTIS_BUILD_IMAGE_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "toolchain", OTIS_BUILD_TOOLCHAIN,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "compiler", OTIS_BUILD_COMPILER, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "toolchain_installed_hash",
              OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "arduino_cli_version",
              OTIS_BUILD_ARDUINO_CLI_VERSION, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "invocation_id", OTIS_BUILD_INVOCATION_ID,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "source_identity_hash",
              OTIS_BUILD_SOURCE_IDENTITY_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "target_identity_hash",
              OTIS_BUILD_TARGET_IDENTITY_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "toolchain_identity_hash",
              OTIS_BUILD_TOOLCHAIN_IDENTITY_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "authoritative_input_set_hash",
              OTIS_BUILD_AUTHORITATIVE_INPUT_SET_SHA256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "provenance_hash", OTIS_BUILD_PROVENANCE_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "generated_header_identity_hash",
              OTIS_BUILD_GENERATED_HEADER_IDENTITY_SHA256,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
}

void emit_common_boot_status(void) {
  emit_build_provenance_status();
  emit_status("system", "boot", "true", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("protocol", "schema_version", OTIS_SCHEMA_VERSION_V1,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("firmware", "name", OTIS_FIRMWARE_NAME, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("firmware", "version", OTIS_FIRMWARE_VERSION, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("system", "mode", OTIS_OPERATING_MODE_NAME, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("capture", "mode", OTIS_CAPTURE_MODE, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("capture", "timestamp_latch", "irq_micros_reconstructed",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "limitation",
              "bench_validation_not_final_pio_dma_metrology",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "timestamp_domain",
              OTIS_DOMAIN_RP2040_MONOTONIC_US32, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("capture", "timestamp_coordinate_hz",
                  OTIS_RP2040_MONOTONIC_US_PER_SECOND, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("capture", "timestamp_source_counter_hz",
                  OTIS_RP2040_MONOTONIC_US_PER_SECOND, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u32("capture", "timestamp_quantum_us",
                  OTIS_RP2040_MONOTONIC_TIMESTAMP_QUANTUM_US,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u32("capture", "timestamp_quantum_ns",
                  OTIS_RP2040_MONOTONIC_TIMESTAMP_QUANTUM_NS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "timestamp_coordinate_semantics",
              "native_local_non_metrological", OTIS_SEVERITY_WARN,
              OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status("capture", "timestamp_provenance",
              "rp2040_timerawl_or_arduino_micros_1mhz_native_us",
              OTIS_SEVERITY_WARN, OTIS_FLAG_TIMESTAMP_RECONSTRUCTED);
  emit_status_u32("reference", "nominal_pps_hz", OTIS_NOMINAL_PPS_HZ,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("capture", "counter_gate_period_us", kTcxoGatePeriodUs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("capture", "measurement_mode",
              otis_count_observation_measurement_mode(),
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("system", "arduino_core", OTIS_TARGET_ARDUINO_CORE,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "capture_backend", "d14_irq_reference",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("build", "tcxo_counter_backend", "d14_gated_d8_snapshot",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("external_event", "capture_status", "not_implemented",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("external_event", "control_authority", "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("environment", "sample_period_ms", OTIS_ENV_SAMPLE_PERIOD_MS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("environment", "sht4x_i2c_address",
                  OTIS_ENV_SHT4X_I2C_ADDRESS, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("environment", "bmp280_i2c_address",
                  OTIS_ENV_BMP280_I2C_ADDRESS, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("dac", "i2c_address", OTIS_DAC_AD5693R_I2C_ADDRESS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
}

void emit_env_sensor_status(void) {
  OtisEnvSensorStatus status;
  otis_env_sensors_get_status(&status);
  emit_status("environment", "sht4x_enabled",
              status.sht4x_enabled ? "true" : "false", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("environment", "sht4x_initialized",
              status.sht4x_initialized ? "true" : "false",
              status.sht4x_initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.sht4x_initialized ? OTIS_FLAG_NONE
                                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("environment", "bmp280_enabled",
              status.bmp280_enabled ? "true" : "false", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("environment", "bmp280_initialized",
              status.bmp280_initialized ? "true" : "false",
              status.bmp280_initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.bmp280_initialized ? OTIS_FLAG_NONE
                                        : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("environment", "primary_temperature_source", "sht4x",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("environment", "primary_temperature_role", "vcocxo_near",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
}


void emit_gnss_receiver_status(void) {
  // Status bursts deliberately service UART0 after every complete STS frame.
  // Take the freshness anchor here, after any preceding burst service, so a
  // newly parsed sentence cannot appear a few milliseconds in the future and
  // wrap its unsigned age to nearly UINT32_MAX.
  const uint32_t now_ms = millis();
  OtisGnssReceiverSnapshot status;
  otis_gnss_receiver_get_snapshot(now_ms, &status);
  bool raw_pps_control_eligible = false;
  OtisCaptureIrqReferenceStats pps_status;
  otis_capture_irq_get_reference_stats(&pps_status);
  raw_pps_control_eligible =
      runtime_state.tcxo.valid_for_control &&
      pps_status.d14_accepted_pps_count > 0u &&
      otis_capture_ring_dropped_count() == 0u &&
      otis_pps_count_boundary_ring_dropped_count() == 0u;
  const bool combined_control_eligible =
      status.control_eligible && raw_pps_control_eligible;
  const uint32_t health_flags = status.control_eligible
                                    ? OTIS_FLAG_NONE
                                    : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT;
  const char *health_severity =
      status.control_eligible ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN;
  const char *link_severity =
      status.link_online || !status.discovery_degraded
          ? OTIS_SEVERITY_INFO
          : OTIS_SEVERITY_WARN;
  const uint32_t link_flags = status.link_online
                                  ? OTIS_FLAG_NONE
                                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT;
  emit_status("gnss_receiver", "enabled",
              "true",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "initialized",
              status.initialized ? "true" : "false",
              status.initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.initialized ? OTIS_FLAG_NONE
                                 : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("gnss_receiver", "link_state",
              status.link_health_state[0] == '\0'
                  ? "disabled"
                  : status.link_health_state,
              link_severity, link_flags);
  emit_status("gnss_receiver", "link_phase",
              status.link_phase[0] == '\0' ? "disabled" : status.link_phase,
              link_severity, link_flags);
  emit_status("gnss_receiver", "link_online",
              status.link_online ? "true" : "false", link_severity,
              link_flags);
  emit_status("gnss_receiver", "receiver_identity",
              status.receiver_identity_available
                  ? status.receiver_release
                  : "unavailable",
              link_severity, link_flags);
  emit_status("gnss_receiver", "configuration_confirmed",
              status.configuration_confirmed ? "true" : "false",
              link_severity, link_flags);
  emit_status("gnss_receiver", "uart_configuration",
              "uart0_configuration_blind_default_or_retained_115200_v1",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "operational_baud_policy",
              "configuration_blind_default_or_retained_115200_v1",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "operational_bootstrap_state",
              status.operational_bootstrap_failed
                  ? "failed"
                  : (status.operational_bootstrap_complete ? "complete"
                                                           : "in_progress"),
              status.operational_bootstrap_failed ? OTIS_SEVERITY_ERROR
                                                  : OTIS_SEVERITY_INFO,
              status.operational_bootstrap_failed
                  ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                  : OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "operational_bootstrap_ordered_source_bauds",
              "9600,115200",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("gnss_receiver", "operational_bootstrap_settle_ms",
                  OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("gnss_receiver", "operational_bootstrap_attempt_count",
                  status.operational_bootstrap_attempt_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "target_baud_command_attempt_count",
                  status.target_baud_command_attempt_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(
      "gnss_receiver", "post_bootstrap_target_baud_command_attempt_count",
      status.post_bootstrap_target_baud_command_attempt_count,
      status.post_bootstrap_target_baud_command_attempt_count == 0u
          ? OTIS_SEVERITY_INFO
          : OTIS_SEVERITY_ERROR,
      status.post_bootstrap_target_baud_command_attempt_count == 0u
          ? OTIS_FLAG_NONE
          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32(
      "gnss_receiver", "operational_bootstrap_peripheral_complete_count",
      status.operational_bootstrap_peripheral_complete_count,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "operational_bootstrap_completed_rate_mask",
                  status.operational_bootstrap_completed_rate_mask,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "operational_bootstrap_first_completed_baud",
                  status.operational_bootstrap_first_completed_baud,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "operational_bootstrap_second_completed_baud",
                  status.operational_bootstrap_second_completed_baud,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "local_uart_baud",
                  status.local_uart_baud, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "local_uart_baud_epoch",
                  status.local_uart_baud_epoch, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "post_bootstrap_baud_change_count",
                  status.post_bootstrap_baud_change_count,
                  status.post_bootstrap_baud_change_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_ERROR,
                  status.post_bootstrap_baud_change_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "operational_bootstrap_rx_discarded_count",
                  status.operational_bootstrap_rx_discarded_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "autodiscovery_enabled", "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("gnss_receiver", "candidate_baud", status.candidate_baud,
                  link_severity, link_flags);
  if (status.confirmed_baud == 0u) {
    emit_status("gnss_receiver", "confirmed_baud", "unavailable",
                link_severity, link_flags);
  } else {
    emit_status_u32("gnss_receiver", "confirmed_baud",
                    status.confirmed_baud, link_severity, link_flags);
  }
  if (status.last_identity_response_baud == 0u) {
    emit_status("gnss_receiver", "last_identity_response_baud",
                "unavailable", link_severity, link_flags);
  } else {
    emit_status_u32("gnss_receiver", "last_identity_response_baud",
                    status.last_identity_response_baud, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_NONE);
  }
  emit_status("gnss_receiver", "output_confirmation_method",
              status.output_confirmation_method[0] == '\0'
                  ? "none"
                  : status.output_confirmation_method,
              link_severity, link_flags);
  emit_status_u32("gnss_receiver", "identity_response_count",
                  status.identity_response_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "pmtk605_peripheral_complete_count",
                  status.pmtk605_peripheral_complete_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal(
      "gnss_receiver", "pmtk605_last_peripheral_complete_ticks",
      status.pmtk605_last_peripheral_complete_ticks,
      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver",
              "pmtk605_last_peripheral_complete_ticks_available",
              status.pmtk605_last_peripheral_complete_ticks_available
                  ? "true"
                  : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver",
              "pmtk605_last_peripheral_complete_ticks_domain",
              "rp2040_monotonic_us64", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("gnss_receiver", "output_response_count",
                  status.output_response_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_query_timeout_count",
                  status.output_query_timeout_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_configuration_ack_count",
                  status.output_configuration_ack_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_observation_success_count",
                  status.output_observation_success_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_observed_sentence_mask",
                  status.output_observed_sentence_mask,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_unexpected_sentence_mask",
                  status.output_unexpected_sentence_mask,
                  status.output_unexpected_sentence_mask == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  status.output_unexpected_sentence_mask == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "last_command_ack_packet_type",
                  status.last_command_ack_packet_type,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "last_command_ack_flag",
                  status.last_command_ack_flag,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "output_configuration_field_count",
                  status.output_configuration_field_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "output_configuration_signature",
              status.output_configuration_signature[0] == '\0'
                  ? "unavailable"
                  : status.output_configuration_signature,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "rx_pin", "D0_GPIO1_UART0_RX",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "tx_pin", "D1_GPIO0_UART0_TX",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "tx_policy",
              "fixed_discovery_configuration_only",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("gnss_receiver", "rx_only",
              status.rx_only ? "true" : "false",
              link_severity, link_flags);
  emit_status_u32("gnss_receiver", "discovery_cycle",
                  status.discovery_cycle, link_severity, link_flags);
  if (status.link_last_valid_frame_age_ms == UINT32_MAX) {
    emit_status("gnss_receiver", "link_last_valid_frame_age_ms",
                "unavailable", link_severity, link_flags);
  } else {
    emit_status_u32("gnss_receiver", "link_last_valid_frame_age_ms",
                    status.link_last_valid_frame_age_ms, link_severity,
                    link_flags);
  }
  emit_status_u32("gnss_receiver", "link_checksum_valid_count",
                  status.link_checksum_valid_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "link_checksum_failure_count",
                  status.link_checksum_failure_count,
                  status.link_checksum_failure_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  status.link_checksum_failure_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "link_oversize_count",
                  status.link_oversize_count,
                  status.link_oversize_count == 0u ? OTIS_SEVERITY_INFO
                                                   : OTIS_SEVERITY_WARN,
                  status.link_oversize_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "configuration_failure_count",
                  status.configuration_failure_count,
                  status.configuration_failure_count == 0u
                      ? OTIS_SEVERITY_INFO
                      : OTIS_SEVERITY_WARN,
                  status.configuration_failure_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "transmit_failure_count",
                  status.transmit_failure_count,
                  status.transmit_failure_count == 0u ? OTIS_SEVERITY_INFO
                                                      : OTIS_SEVERITY_WARN,
                  status.transmit_failure_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status_u32("gnss_receiver", "link_loss_count",
                  status.link_loss_count,
                  status.link_loss_count == 0u ? OTIS_SEVERITY_INFO
                                               : OTIS_SEVERITY_WARN,
                  status.link_loss_count == 0u
                      ? OTIS_FLAG_NONE
                      : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("gnss_receiver", "talker",
              status.talker[0] == '\0' ? "unavailable" : status.talker,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "rmc_seen",
              status.rmc_seen ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "rmc_valid",
              status.rmc_valid ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "gga_seen",
              status.gga_seen ? "true" : "false", health_severity,
              health_flags);
  emit_status_u32("gnss_receiver", "gga_fix_quality", status.fix_quality,
                  health_severity, health_flags);
  emit_status_u32("gnss_receiver", "satellite_count", status.satellites,
                  health_severity, health_flags);
  emit_status("gnss_receiver", "gsa_seen",
              status.gsa_seen ? "true" : "false", OTIS_SEVERITY_INFO,
              OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "gsa_fix_dimension",
                  status.fix_dimension, OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "gsa_3d_fresh",
              status.gsa_3d ? "true" : "false",
              status.gsa_3d ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.gsa_3d ? OTIS_FLAG_NONE
                            : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
  emit_status("gnss_receiver", "gsa_checksum_requalified",
              status.gsa_checksum_requalified ? "true" : "false",
              status.gsa_checksum_requalified ? OTIS_SEVERITY_INFO
                                              : OTIS_SEVERITY_WARN,
              status.gsa_checksum_requalified
                  ? OTIS_FLAG_NONE
                  : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
  emit_status("gnss_receiver", "hdop",
              status.hdop[0] == '\0' ? "unavailable" : status.hdop,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "utc_available",
              status.utc_available ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "date_available",
              status.date_available ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "utc",
              status.utc[0] == '\0' ? "unavailable" : status.utc,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("gnss_receiver", "date",
              status.date[0] == '\0' ? "unavailable" : status.date,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  if (status.metadata_age_ms == UINT32_MAX) {
    emit_status("gnss_receiver", "metadata_age_ms", "unavailable",
                health_severity, health_flags);
  } else {
    emit_status_u32("gnss_receiver", "metadata_age_ms",
                    status.metadata_age_ms, health_severity, health_flags);
  }
  emit_status("gnss_receiver", "metadata_fresh",
              status.metadata_fresh ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "checksum_requalified",
              status.checksum_requalified ? "true" : "false",
              health_severity, health_flags);
  emit_status("gnss_receiver", "identity_stable",
              status.identity_stable ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "disconnected",
              status.disconnected ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "metadata_control_eligible",
              status.control_eligible ? "true" : "false", health_severity,
              health_flags);
  emit_status("gnss_receiver", "raw_pps_control_eligible",
              raw_pps_control_eligible ? "true" : "false",
              raw_pps_control_eligible ? OTIS_SEVERITY_INFO
                                       : OTIS_SEVERITY_WARN,
              raw_pps_control_eligible ? OTIS_FLAG_NONE
                                       : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
  emit_status("gnss_receiver", "control_eligible",
              combined_control_eligible ? "true" : "false",
              combined_control_eligible ? OTIS_SEVERITY_INFO
                                        : OTIS_SEVERITY_WARN,
              combined_control_eligible ? OTIS_FLAG_NONE
                                        : OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT);
  emit_status_u32("gnss_receiver", "identity_epoch", status.identity_epoch,
                  health_severity, health_flags);
  emit_status_u32("gnss_receiver", "checksum_valid_count",
                  status.checksum_valid_count, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "checksum_failure_count",
                  status.checksum_failure_count,
                  status.checksum_failure_count ? OTIS_SEVERITY_WARN
                                                : OTIS_SEVERITY_INFO,
                  status.checksum_failure_count ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                                : OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "parser_drop_count",
                  status.parser_drop_count,
                  status.parser_drop_count ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
                  status.parser_drop_count ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                           : OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "truncated_count", status.truncated_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "oversize_count", status.oversize_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "rmc_count", status.rmc_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "gga_count", status.gga_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("gnss_receiver", "gsa_count", status.gsa_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
}

void emit_h0_pin_status(void) {
  emit_status("pins", "ch0_generic_event", "D10", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("pins", "ch1_pps_reference", "D14", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("pins", "ch2_osc_observation", "D8_GPIO20_GPIN0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  OtisForwardedClockOutputStatus output = {};
  otis_forwarded_clock_output_get_status(&output);
  emit_status("forwarded_clock_output", "contract_id", output.contract_id,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("forwarded_clock_output", "contract_sha256",
              output.contract_sha256, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("forwarded_clock_output", "state", output.reason,
              output.valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              output.valid ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                           : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("forwarded_clock_output", "source", "D8_GPIO20_GPIN0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("forwarded_clock_output", "destination", "D9_GPIO21_GPOUT0",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "integer_divider",
                  output.integer_divider, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "fractional_divider",
                  output.fractional_divider, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "applied_auxsrc",
                  output.applied_auxsrc, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "applied_integer_divider",
                  output.applied_integer_divider, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "applied_fractional_divider",
                  output.applied_fractional_divider, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "source_gpio_function",
                  output.source_gpio_function, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "destination_gpio_function",
                  output.destination_gpio_function, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "inversion",
                  output.inversion, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "drive_strength_ma",
                  output.drive_strength_ma, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("forwarded_clock_output", "slew_rate",
              output.slew_rate_fast ? "fast" : "slow",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32("forwarded_clock_output", "nominal_frequency_hz",
                  output.nominal_frequency_hz, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u64_decimal("forwarded_clock_output", "first_valid_ticks",
                          output.first_valid_ticks, OTIS_SEVERITY_INFO,
                          OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("forwarded_clock_output", "readback_valid",
              output.readback_valid ? "true" : "false",
              output.readback_valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              output.readback_valid ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                                    : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
}

void emit_selected_capability_status(void) {
  if (boot_capability_status_emitted || !otis_transport_ready()) {
    return;
  }

  const OtisBootCapabilityOutcome overall =
      otis_boot_capability_overall_outcome(&boot_capabilities);
  const bool run_mode_ready = boot_capabilities.run_mode_marked;
  const bool degraded = otis_boot_capability_degraded(&boot_capabilities);
  emit_status("boot_capabilities", "selected_image",
              OTIS_OPERATING_MODE_NAME, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("boot_capabilities", "overall",
              otis_boot_capability_outcome_name(overall),
              overall == OtisBootCapabilityOutcome::Ready
                  ? OTIS_SEVERITY_INFO
                  : (overall == OtisBootCapabilityOutcome::OptionalDegraded
                         ? OTIS_SEVERITY_WARN
                         : OTIS_SEVERITY_FATAL),
              overall == OtisBootCapabilityOutcome::Ready
                  ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                  : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("boot_capabilities", "run_mode",
              run_mode_ready ? "Ready" : "blocked",
              run_mode_ready ? (degraded ? OTIS_SEVERITY_WARN
                                         : OTIS_SEVERITY_INFO)
                             : OTIS_SEVERITY_FATAL,
              run_mode_ready && !degraded ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                                          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("boot_capabilities", "degraded",
              degraded ? "true" : "false",
              degraded ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_INFO,
              degraded ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                       : OTIS_FLAG_CONFIGURATION_ASSUMPTION);

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
                    ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                    : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  emit_status_u32("boot_capabilities", "selected_count", selected_count,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  boot_capability_status_emitted = true;
}

void emit_resource_ownership_status(void) {
  if (resource_ownership_status_emitted || !otis_transport_ready()) {
    return;
  }

  bool valid = otis_resource_registry_valid();
  bool complete = otis_resource_registry_complete();
  uint32_t registry_flags =
      valid && complete ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
                        : OTIS_FLAG_SOURCE_HEALTH_SUSPECT;

  emit_status("resource_registry", "version", "1", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("resource_registry", "valid", valid ? "true" : "false",
              valid ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_FATAL,
              registry_flags);
  emit_status("resource_registry", "complete", complete ? "true" : "false",
              complete ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              registry_flags);
  emit_status_u32("resource_registry", "claim_count",
                  otis_resource_registry_claim_count(), OTIS_SEVERITY_INFO,
                  OTIS_FLAG_CONFIGURATION_ASSUMPTION);
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
      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "irq_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::GpioIrq),
      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "pio_sm_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::PioStateMachine),
      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "pio_imem_claim_count",
      otis_resource_registry_claim_count(
          OtisResourceType::PioInstructionMemory),
      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "dma_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::DmaChannel),
      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "timer_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::Timer),
      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u32(
      "resource_registry", "clock_claim_count",
      otis_resource_registry_claim_count(OtisResourceType::Clock),
      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);

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
                claim->bound ? OTIS_FLAG_CONFIGURATION_ASSUMPTION
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
  emitRp2040BootDiag(Serial);
  otis_emit_csv_headers();
  otis_frequency_regulation_live_emit_headers();
  otis_adaptive_hybrid_regulation_live_emit_headers();
  otis_phase_preview_transport_emit_headers();
  runtime_state.boot.protocol_banner_emitted = true;
}

void emit_periodic_status(void) {
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.periodic.last_status_ms) <
      kStatusPeriodMs) {
    return;
  }
  runtime_state.periodic.last_status_ms = now_ms;

  emit_status_u32("system", "uptime_seconds", now_ms / 1000u,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  OtisDualCoreQueueStats queues;
  otis_dual_core_get_stats(&queues);
  emit_status_u32("dual_core", "service_to_timing_depth",
                  queues.service_to_timing_depth, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_to_timing_high_water",
                  queues.service_to_timing_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "observation_depth", queues.observation_depth,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "observation_high_water",
                  queues.observation_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "critical_depth", queues.critical_depth,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "critical_high_water",
                  queues.critical_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "evidence_depth", queues.evidence_depth,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "evidence_high_water",
                  queues.evidence_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "telemetry_depth", queues.telemetry_depth,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "telemetry_high_water",
                  queues.telemetry_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "phase_frequency_estimate_depth",
                  queues.phase_preview_depth, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "phase_frequency_estimate_high_water",
                  queues.phase_preview_high_water, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "telemetry_dropped",
                  queues.telemetry_dropped,
                  queues.telemetry_dropped ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
                  queues.telemetry_dropped
                      ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                      : OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "pre_carrier_records_discarded",
                  dual_core_pre_carrier_records_discarded,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "periodic_service_deferred",
                  dual_core_periodic_service_deferred,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_publish_attempts",
                  queues.service_activity.publish_attempts,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_publish_successes",
                  queues.service_activity.publish_successes,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32(
      "dual_core", "service_publish_failures",
      queues.service_activity.publish_failures,
      queues.service_activity.publish_failures ? OTIS_SEVERITY_ERROR
                                               : OTIS_SEVERITY_INFO,
      queues.service_activity.publish_failures
          ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
          : OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_take_successes",
                  queues.service_activity.take_successes,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "service_take_accounting", "successful_only",
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_drain_budget_per_loop",
                  OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "service_last_published_kind",
              otis_service_message_kind_name(
                  queues.service_activity.last_published_kind),
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_last_published_sequence",
                  queues.service_activity.last_published_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal("dual_core", "service_last_published_ticks",
                          queues.service_activity.last_published_ticks,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "service_last_taken_kind",
              otis_service_message_kind_name(
                  queues.service_activity.last_taken_kind),
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "service_last_taken_sequence",
                  queues.service_activity.last_taken_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal("dual_core", "service_last_taken_ticks",
                          queues.service_activity.last_taken_ticks,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "core1_trace_sampling", "bounded_coarse",
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_trace_period_ms",
                  kDualCoreTimingTracePeriodMs,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_trace_sequence",
                  queues.timing_progress.loop_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "core1_progress_phase",
              otis_timing_progress_phase_name(queues.timing_progress.phase),
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u64_decimal("dual_core", "core1_phase_enter_ticks",
                          queues.timing_progress.phase_enter_ticks,
                          OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_last_snapshot_session",
                  queues.timing_progress.last_snapshot_session,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_last_snapshot_sequence",
                  queues.timing_progress.last_snapshot_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_last_count_sequence",
                  queues.timing_progress.last_count_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("dual_core", "core1_last_estimate_sequence",
                  queues.timing_progress.last_estimate_sequence,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("dual_core", "service_fault_capsule",
              queues.service_fault.valid ? "frozen" : "clear",
              queues.service_fault.valid ? OTIS_SEVERITY_ERROR
                                         : OTIS_SEVERITY_INFO,
              queues.service_fault.valid ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                         : OTIS_FLAG_NONE);
  if (queues.service_fault.valid) {
    emit_status("dual_core", "fault_failing_service_kind",
                otis_service_message_kind_name(
                    queues.service_fault.failing_kind),
                OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_failing_service_sequence",
                    queues.service_fault.failing_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u64_decimal(
        "dual_core", "fault_failing_publish_ticks",
        queues.service_fault.failing_published_ticks,
        OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_service_queue_depth",
                    queues.service_fault.queue_depth,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status("dual_core", "fault_breadcrumb_coherent",
                queues.service_fault.breadcrumb_coherent ? "true" : "false",
                queues.service_fault.breadcrumb_coherent
                    ? OTIS_SEVERITY_ERROR
                    : OTIS_SEVERITY_WARN,
                OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_breadcrumb_generation",
                    queues.service_fault.breadcrumb_generation,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status("dual_core", "fault_last_taken_kind",
                otis_service_message_kind_name(
                    queues.service_fault.last_taken_kind),
                OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_last_taken_sequence",
                    queues.service_fault.last_taken_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u64_decimal("dual_core", "fault_last_taken_ticks",
                            queues.service_fault.last_taken_ticks,
                            OTIS_SEVERITY_ERROR,
                            OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status("dual_core", "fault_core1_progress_phase",
                otis_timing_progress_phase_name(
                    queues.service_fault.timing_phase),
                OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_core1_trace_sequence",
                    queues.service_fault.timing_loop_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u64_decimal(
        "dual_core", "fault_core1_last_progress_ticks",
        queues.service_fault.timing_last_progress_ticks,
        OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_last_snapshot_sequence",
                    queues.service_fault.last_snapshot_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_last_snapshot_session",
                    queues.service_fault.last_snapshot_session,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_last_count_sequence",
                    queues.service_fault.last_count_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    emit_status_u32("dual_core", "fault_last_estimate_sequence",
                    queues.service_fault.last_estimate_sequence,
                    OTIS_SEVERITY_ERROR, OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  }
  emit_status("dual_core", "partition_fault",
              otis_partition_fault_name(queues.fault),
              queues.fail_static ? OTIS_SEVERITY_ERROR : OTIS_SEVERITY_INFO,
              queues.fail_static ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                 : OTIS_FLAG_NONE);
  emit_status("dual_core", "fail_static",
              queues.fail_static ? "true" : "false",
              queues.fail_static ? OTIS_SEVERITY_ERROR : OTIS_SEVERITY_INFO,
              queues.fail_static ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                 : OTIS_FLAG_NONE);
  emit_status("dual_core", "core0_role",
              "service_io_actuator_execution", OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status("dual_core", "core1_role", "protected_timing_discipline",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  otis_frequency_regulation_live_emit_status(&status_emit_context);
  emit_gnss_receiver_status();
  OtisPhasePreviewLiveStatus phase_frequency = {};
  otis_phase_preview_live_get_status(&phase_frequency);
  emit_status("phase_frequency_estimate", "initialized",
              phase_frequency.initialized ? "true" : "false",
              phase_frequency.initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              phase_frequency.initialized ? OTIS_FLAG_NONE
                                : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_status("phase_frequency_estimate", "applied_code_bound",
              phase_frequency.applied_code_bound ? "true" : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  char phase_applied_code[16] = "unavailable";
  char phase_dac_epoch[16] = "unavailable";
  if (phase_frequency.applied_code_bound) {
    snprintf(phase_applied_code, sizeof(phase_applied_code), "0x%04X",
             phase_frequency.applied_code);
    snprintf(phase_dac_epoch, sizeof(phase_dac_epoch), "%lu",
             static_cast<unsigned long>(phase_frequency.dac_epoch));
  }
  emit_status("phase_frequency_estimate", "applied_code", phase_applied_code,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status("phase_frequency_estimate", "dac_epoch", phase_dac_epoch,
              OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  emit_status_u32("phase_frequency_estimate", "published_records",
                  phase_frequency.published_records, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("phase_frequency_estimate", "last_phase_epoch",
                  phase_frequency.last_phase_epoch, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
  emit_status_u32("phase_frequency_estimate", "last_observation_sequence",
                  phase_frequency.last_observation_sequence, OTIS_SEVERITY_INFO,
                  OTIS_FLAG_NONE);
}

void emit_dac_status(const char *component) {
  OtisDacAd5693rStatus status;
  otis_dac_ad5693r_get_status(&status);
  emit_status(component, "enabled", status.enabled ? "true" : "false",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(component, "initialized", status.initialized ? "true" : "false",
              status.initialized ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              status.enabled ? OTIS_FLAG_NONE : OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(component, "last_write_ok", status.last_write_ok ? "true" : "false",
              status.last_write_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status(component, "applied_code_known",
              status.applied_code_known ? "true" : "false",
              status.applied_code_known ? OTIS_SEVERITY_INFO
                                        : OTIS_SEVERITY_WARN,
              OTIS_FLAG_NONE);
  emit_status_u32(component, "i2c_address", status.i2c_address,
                  OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u16_hex(component, "min_code", status.min_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u16_hex(component, "max_code", status.max_code,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status_u16_hex(component, "last_requested_code",
                      status.last_requested_code, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_NONE);
  if (status.applied_code_known) {
    emit_status_u16_hex(component, "last_applied_code", status.last_applied_code,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  } else {
    emit_status(component, "last_applied_code", "unavailable",
                OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
  }
  emit_status(component, "gain_mode", status.gain_mode, OTIS_SEVERITY_INFO,
              OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  emit_status(component, "reference_mode", status.reference_mode,
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
}


void configure_adaptive_hybrid_regulation(void) {
  emit_status("control", "adaptive_hybrid_regulation", "configured",
              OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  bool ok = capability_ready(OtisBootCapability::Dac);
  emit_status("dac", "init", ok ? "ok" : "failed",
              ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
              ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_dac_status("dac");
  bool env_ok = capability_ready(OtisBootCapability::Sensors);
  emit_status("environment", "init", env_ok ? "ok" : "failed",
              env_ok ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_WARN,
              env_ok ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  emit_env_sensor_status();
  emit_gnss_receiver_status();
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
    OtisDualCoreQueueStats service_queues = {};
    otis_dual_core_get_stats(&service_queues);
    if (service_queues.service_to_timing_depth >=
        OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH) {
      if (dual_core_periodic_service_deferred != UINT32_MAX)
        dual_core_periodic_service_deferred++;
    } else {
    OtisServiceMessage environment = {};
    environment.kind = OtisServiceMessageKind::Environment;
    environment.environment.sequence = dual_core_service_sequence++;
    environment.environment.timestamp_ticks = timestamp_ticks;
    environment.environment.temperature_c = sample.temperature_c;
    environment.environment.relative_humidity_pct =
        sample.relative_humidity_pct;
    environment.environment.pressure_pa = sample.pressure_pa;
    environment.environment.temperature_valid = true;
    environment.environment.humidity_valid = sample.has_humidity;
    environment.environment.pressure_valid = sample.has_pressure;
    otis_dual_core_publish_service(&environment);
    }
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
                        timestamp_ticks, OTIS_DOMAIN_RP2040_MONOTONIC_US32,
                        sample.source, sample.role, temperature, humidity,
                        pressure, OTIS_FLAG_NONE);
}

void service_environment_sensors(void) {
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - runtime_state.periodic.last_env_sample_ms) <
      OTIS_ENV_SAMPLE_PERIOD_MS) {
    return;
  }
  runtime_state.periodic.last_env_sample_ms = now_ms;
  OtisEnvSample sample;
  if (otis_env_sensors_read_sht4x(&sample)) {
    const uint64_t timestamp_ticks = otis_monotonic_us32_now();
    emit_env_sample(sample, timestamp_ticks);
  } else {
    OtisDualCoreQueueStats service_queues = {};
    otis_dual_core_get_stats(&service_queues);
    if (service_queues.service_to_timing_depth >=
        OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH) {
      if (dual_core_periodic_service_deferred != UINT32_MAX)
        dual_core_periodic_service_deferred++;
    } else {
    OtisServiceMessage environment = {};
    environment.kind = OtisServiceMessageKind::Environment;
    environment.environment.sequence = dual_core_service_sequence++;
    environment.environment.timestamp_ticks = otis_monotonic_us32_now();
    environment.environment.temperature_valid = false;
    otis_dual_core_publish_service(&environment);
    }
  }
  if (otis_env_sensors_read_bmp280(&sample)) {
    emit_env_sample(sample, otis_monotonic_us32_now());
  }
}

void emit_run_mode_status_if_ready(void) {
  if (run_mode_status_emitted || !boot_capabilities.run_mode_marked ||
      !runtime_state.boot.protocol_banner_emitted ||
      !otis_transport_ready()) {
    return;
  }
  emit_common_boot_status();
  emit_h0_pin_status();
  configure_adaptive_hybrid_regulation();
  emit_selected_capability_status();
  emit_resource_ownership_status();
  run_mode_status_emitted = true;
}

void boot_phase_reset_entry(void) {
  begin_boot_phase(BootPhase::ResetEntry);
  captureRp2040BootDiag();
  otisBootBreadcrumbBegin(BootPhase::ResetEntry);
  delay(kOtisBootInitialDelayMs);
  complete_boot_phase(BootPhase::ResetEntry);
}

void boot_phase_early_init(void) {
  begin_boot_phase(BootPhase::EarlyInit);
  const bool valid = otis_resource_registry_begin();
  if (!valid) {
    otis_boot_capability_record(
        &boot_capabilities, OtisBootCapability::ResourceRegistry,
        OtisBootCapabilityOutcome::FatalConflict);
  }
  complete_boot_phase(BootPhase::EarlyInit);
}

void boot_phase_clocks_init(void) {
  begin_boot_phase(BootPhase::ClocksInit);
  record_capability_result(OtisBootCapability::Timebase,
                           otis_timebase_begin());
  complete_boot_phase(BootPhase::ClocksInit);
}

void boot_phase_gpio_init(void) {
  begin_boot_phase(BootPhase::GpioInit);
  // Preserve D10/CH0 as the optional external-event seam, but do not claim an
  // active capture backend. The current backend is a singleton owned by the
  // D14/CH1 reference observer; reusing it here would violate fail-local D10
  // isolation. A distinct backend, ring, and owner are required first.
  pinMode(OTIS_PIN_EXTERNAL_EVENT, INPUT);
  pinMode(OTIS_PIN_PPS_REFERENCE, INPUT_PULLDOWN);
  complete_boot_phase(BootPhase::GpioInit);
}

void boot_phase_capture_init(void) {
  begin_boot_phase(BootPhase::CaptureInit);
  complete_boot_phase(BootPhase::CaptureInit);
}

void boot_phase_timer_init(void) {
  begin_boot_phase(BootPhase::TimerInit);
  runtime_state.tcxo.startup_inhibit_start_ms = millis();
  runtime_state.tcxo.startup_inhibit_active = true;
  runtime_state.tcxo.valid_for_control = false;
  runtime_state.tcxo.control_clean_window_count = 0;
  runtime_state.tcxo.fault_after_startup = false;
  OtisCountObservationConfig count_config = count_observation_config();
  const bool ready = otis_count_observation_begin(
      &runtime_state, &status_emit_context, &count_config);
  record_capability_result(OtisBootCapability::OscillatorCount, ready);
  complete_boot_phase(BootPhase::TimerInit);
}

void boot_phase_pps_input_init(void) {
  begin_boot_phase(BootPhase::PpsInputInit);
  const bool pps_ready = otis_capture_irq_begin_d14_reference();
  record_capability_result(OtisBootCapability::PpsCapture, pps_ready);
  complete_boot_phase(BootPhase::PpsInputInit);
}

void boot_phase_forwarded_output_init(void) {
  begin_boot_phase(BootPhase::ForwardedOutputInit);
  const bool ready = otis_forwarded_clock_output_begin();
  record_capability_result(OtisBootCapability::ForwardedOutput, ready);
  complete_boot_phase(BootPhase::ForwardedOutputInit);
}

void boot_phase_forwarded_monitor_init(void) {
  begin_boot_phase(BootPhase::ForwardedMonitorInit);
  const bool ready = otis_forwarded_clock_monitor_begin();
  record_capability_result(OtisBootCapability::ForwardedMonitor, ready);
  complete_boot_phase(BootPhase::ForwardedMonitorInit);
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

  complete_boot_phase(BootPhase::SerialInit);
}

void boot_phase_protocol_banner(void) {
  begin_boot_phase(BootPhase::ProtocolBanner);
  emit_protocol_banner_if_serial_ready();
  complete_boot_phase(BootPhase::ProtocolBanner);
}

void boot_phase_peripherals_init(void) {
  begin_boot_phase(BootPhase::PeripheralsInit);
  const bool dac_ready = otis_dac_ad5693r_begin();
  record_capability_result(OtisBootCapability::Dac, dac_ready);
  const bool sensors_ready = otis_env_sensors_begin();
  record_capability_result(OtisBootCapability::Sensors, sensors_ready);
  const bool gnss_receiver_ready = otis_gnss_receiver_begin();
  record_capability_result(OtisBootCapability::GnssReceiver,
                           gnss_receiver_ready);
  complete_boot_phase(BootPhase::PeripheralsInit);
}

void boot_phase_preview_init(void) {
  begin_boot_phase(BootPhase::PreviewInit);
  const bool preview_ready =
      otis_frequency_regulation_live_begin(millis() / 1000u) &&
      otis_adaptive_hybrid_regulation_live_begin();
  record_capability_result(OtisBootCapability::FrequencyRegulation,
                           preview_ready);
  const bool phase_preview_ready = otis_phase_preview_live_begin();
  record_capability_result(OtisBootCapability::PhaseFrequencyEstimate,
                           phase_preview_ready);
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
  otisBootBreadcrumbMarkRunMode();
}

void service_tcxo_gate(void) {
  OtisCountObservationConfig count_config = count_observation_config();
  otis_count_observation_service(&runtime_state, &status_emit_context,
                                 &count_config);
}

void execute_serial_command(const OtisParsedSerialCommand &command) {
  if (command.kind == OtisSerialCommandKind::Help) {
    emit_status("command", "h1_help",
                "CONFIG?_DUALCORE?_DAC?_DAC_LIMITS?_COUNT?_ACTIVE?_ACTIVE_SNAPSHOT_nonce_ACTIVE_SETUP_authority_ACTIVE_LEASE_seq_ACTIVE_ARM_seq_nonce_expiry_ACTIVE_ABORT_ACTIVE_EVIDENCE_request_HELP",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::ConfigQuery) {
    emit_status("command", "config_snapshot", "begin",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "pre_carrier_records_discarded",
                    dual_core_pre_carrier_records_discarded,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "carrier_loss_frames_abandoned",
                    dual_core_carrier_loss_frames_abandoned,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "periodic_service_deferred",
                    dual_core_periodic_service_deferred,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    // A capture opened after the boot banner still needs one complete
    // provenance block for evidence sealing.  Do not repeat the relatively
    // large block at CONFIG? service-load rates.
    if (!config_query_provenance_emitted) {
      emit_build_provenance_status();
      config_query_provenance_emitted = true;
    }
    emit_status("firmware", "version", OTIS_FIRMWARE_VERSION,
                OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_status("system", "mode", OTIS_OPERATING_MODE_NAME,
                OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_status("build", "capture_backend", "d14_irq_reference",
                OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_status("build", "tcxo_counter_backend", "d14_gated_d8_snapshot",
                OTIS_SEVERITY_INFO,
                OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    // Core 1 owns PPS/ACTIVE status cohorts. CONFIG? can interrupt their
    // serial drainage, so core 0 must not repeat fields in those namespaces.
    // DiagnosticConfigQuery below requests timing configuration from its owner.
    emit_status_u32("capture", "counter_gate_period_us", kTcxoGatePeriodUs,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_h0_pin_status();
    otis_memory_budget_emit_status(&status_emit_context);
    emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_status("command", "config_snapshot", "end",
                OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    const uint32_t nonce = dual_core_service_sequence + 1u;
    const bool requested = queue_dual_core_active_control(
        OtisRunControlKind::DiagnosticConfigQuery, nonce);
    emit_status("command", "timing_config_snapshot",
                requested ? "queued_to_core1" : "rejected_queue_fault",
                requested ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                requested ? OTIS_FLAG_NONE
                          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  } else if (command.kind == OtisSerialCommandKind::DualCoreQuery) {
    OtisDualCoreQueueStats queues;
    otis_dual_core_get_stats(&queues);
    emit_status_u32("dual_core", "service_to_timing_depth",
                    queues.service_to_timing_depth, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "observation_depth",
                    queues.observation_depth, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "monitor_observation_depth",
                    queues.monitor_observation_depth, OTIS_SEVERITY_INFO,
                    OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "monitor_observation_high_water",
                    queues.monitor_observation_high_water,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    emit_status_u32(
        "dual_core", "monitor_observation_dropped",
        queues.monitor_observation_dropped,
        queues.monitor_observation_dropped ? OTIS_SEVERITY_WARN
                                           : OTIS_SEVERITY_INFO,
        queues.monitor_observation_dropped
            ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
            : OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "critical_depth", queues.critical_depth,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "evidence_depth", queues.evidence_depth,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "telemetry_depth", queues.telemetry_depth,
                    OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    emit_status_u32("dual_core", "telemetry_dropped",
                    queues.telemetry_dropped,
                    queues.telemetry_dropped ? OTIS_SEVERITY_WARN
                                             : OTIS_SEVERITY_INFO,
                    queues.telemetry_dropped
                        ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                        : OTIS_FLAG_NONE);
    emit_status("dual_core", "fail_static",
                queues.fail_static ? "true" : "false",
                queues.fail_static ? OTIS_SEVERITY_ERROR
                                   : OTIS_SEVERITY_INFO,
                queues.fail_static ? OTIS_FLAG_SOURCE_HEALTH_SUSPECT
                                   : OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::DacQuery) {
    emit_dac_status("dac");
  } else if (command.kind == OtisSerialCommandKind::DacLimitsQuery) {
    emit_status_u16_hex("dac", "min_code", OTIS_DAC_MIN_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
    emit_status_u16_hex("dac", "max_code", OTIS_DAC_MAX_CODE,
                        OTIS_SEVERITY_INFO, OTIS_FLAG_CONFIGURATION_ASSUMPTION);
  } else if (command.kind == OtisSerialCommandKind::CountQuery) {
    const uint32_t nonce = dual_core_service_sequence + 1u;
    const bool requested = queue_dual_core_active_control(
        OtisRunControlKind::DiagnosticRuntimeQuery, nonce);
    emit_status("command", "timing_runtime_snapshot",
                requested ? "queued_to_core1" : "rejected_queue_fault",
                requested ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                requested ? OTIS_FLAG_NONE
                          : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  } else if (command.kind == OtisSerialCommandKind::ActiveQuery) {
    const bool accepted = queue_dual_core_active_control(
        OtisRunControlKind::StatusQuery);
    emit_status("adaptive_hybrid_regulation", "status_query",
                accepted ? "queued_to_core1" : "rejected_queue_fault",
                accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                accepted ? OTIS_FLAG_NONE
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  } else if (command.kind == OtisSerialCommandKind::ActiveSnapshot) {
    uint32_t values[OTIS_COMMAND_ACTIVE_SNAPSHOT_ARGUMENT_COUNT];
    const bool parsed = command.arguments_valid &&
                        otis_serial_command_parse_nonzero_decimal_u32_fields(
                            command.text_argument, values,
                            OTIS_COMMAND_ACTIVE_SNAPSHOT_ARGUMENT_COUNT) &&
                        values[0] != 0u;
    const bool accepted = parsed && queue_dual_core_active_control(
                                      OtisRunControlKind::StatusQuery,
                                      values[0]);
    emit_status("adaptive_hybrid_regulation", "snapshot_firmware_received",
                accepted ? "queued_to_core1" : "rejected",
                accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                accepted ? OTIS_FLAG_NONE
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  } else if (command.kind == OtisSerialCommandKind::ActiveSetup) {
    OtisSetupAuthorityRequest request = {};
    const bool parsed = command.arguments_valid &&
                        otis_setup_authority_parse_request(
                            command.text_argument, &request);
    const bool accepted = parsed &&
                          queue_dual_core_setup_authorization(request);
    emit_status("adaptive_hybrid_setup", "phase",
                accepted ? "firmware_received" : "firmware_rejected",
                accepted ? OTIS_SEVERITY_INFO : OTIS_SEVERITY_ERROR,
                accepted ? OTIS_FLAG_NONE
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    if (accepted) {
      emit_status_u32("adaptive_hybrid_setup", "command_sequence",
                      request.command_sequence, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_NONE);
      emit_status_u32("adaptive_hybrid_setup", "authorization_sequence",
                      request.authorization_sequence, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_NONE);
      emit_status_u32("adaptive_hybrid_setup", "status_generation",
                      request.status_generation, OTIS_SEVERITY_INFO,
                      OTIS_FLAG_NONE);
      emit_status_u32("adaptive_hybrid_setup", "query_nonce", request.query_nonce,
                      OTIS_SEVERITY_INFO, OTIS_FLAG_NONE);
    }
  } else if (command.kind == OtisSerialCommandKind::ActiveLease) {
    uint32_t values[OTIS_COMMAND_ACTIVE_LEASE_ARGUMENT_COUNT];
    const bool parsed = command.arguments_valid &&
                        otis_serial_command_parse_nonzero_decimal_u32_fields(
                            command.text_argument, values,
                            OTIS_COMMAND_ACTIVE_LEASE_ARGUMENT_COUNT);
    const bool accepted = parsed &&
                          queue_dual_core_active_control(
                              OtisRunControlKind::CaptureLease, values[0]);
    emit_status("adaptive_hybrid_regulation", "capture_lease",
                accepted ? "accepted" : "rejected", accepted
                    ? OTIS_SEVERITY_INFO
                    : OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::ActiveArm) {
    uint32_t values[OTIS_COMMAND_ACTIVE_ARM_ARGUMENT_COUNT];
    const bool parsed = command.arguments_valid &&
                        otis_serial_command_parse_nonzero_decimal_u32_fields(
                            command.text_argument, values,
                            OTIS_COMMAND_ACTIVE_ARM_ARGUMENT_COUNT);
    const bool accepted = parsed &&
                          queue_dual_core_active_control(
                              OtisRunControlKind::Arm, values[0], values[1],
                              values[2]);
    emit_status("adaptive_hybrid_regulation", "arm",
                accepted ? "accepted" : "rejected", accepted
                    ? OTIS_SEVERITY_INFO
                    : OTIS_SEVERITY_ERROR,
                OTIS_FLAG_NONE);
  } else if (command.kind == OtisSerialCommandKind::ActiveAbort) {
    const bool accepted =
        queue_dual_core_active_control(OtisRunControlKind::Abort);
    emit_status("adaptive_hybrid_regulation", "abort",
                accepted ? "queued_to_core1" : "rejected_queue_fault",
                accepted ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_ERROR,
                accepted ? OTIS_FLAG_NONE
                         : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
  } else if (command.kind == OtisSerialCommandKind::ActiveEvidence) {
    uint32_t values[OTIS_COMMAND_ACTIVE_EVIDENCE_ARGUMENT_COUNT];
    const bool parsed = command.arguments_valid &&
                        otis_serial_command_parse_active_evidence(
                            command.text_argument, &values[0], &values[1]);
    const bool accepted = parsed && queue_dual_core_active_control(
                                        OtisRunControlKind::EvidenceRelease,
                                        values[0], values[1]);
    emit_status("adaptive_hybrid_regulation", "evidence_ack",
                accepted ? "accepted" : "rejected", accepted
                    ? OTIS_SEVERITY_INFO
                    : OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
  } else if (command.kind != OtisSerialCommandKind::Empty) {
    emit_status("command", "unknown", "rejected_unknown", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
  }
}

void service_serial_commands(bool output_allowed = true) {
  if (output_allowed && deferred_serial_error ==
                            OtisSerialFrameEvent::RejectedTooLong) {
    deferred_serial_error = OtisSerialFrameEvent::None;
    emit_status("command", "line", "rejected_too_long", OTIS_SEVERITY_WARN,
                OTIS_FLAG_NONE);
    return;
  }
  if (output_allowed && deferred_serial_invalid) {
    deferred_serial_invalid = false;
    emit_status("command", "line", "rejected_invalid_character",
                OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
    return;
  }
  if (output_allowed && deferred_abort_result_ready) {
    const bool queued = deferred_abort_queued;
    deferred_abort_result_ready = false;
    deferred_abort_queued = false;
    emit_status("adaptive_hybrid_regulation", "abort_firmware_received",
                queued ? "queued_to_core1" : "rejected_queue_fault",
                queued ? OTIS_SEVERITY_WARN : OTIS_SEVERITY_ERROR,
                queued ? OTIS_FLAG_NONE : OTIS_FLAG_SOURCE_HEALTH_SUSPECT);
    return;
  }
  if (output_allowed && deferred_serial_command_ready) {
    OtisParsedSerialCommand command =
        otis_serial_command_parse(deferred_serial_command);
    deferred_serial_command_ready = false;
    execute_serial_command(command);
    return;
  }
  // One complete non-abort command may wait behind the current wire frame.
  // Leave later bytes in the USB RX buffer until that command is executed.
  if (!output_allowed && deferred_serial_command_ready) return;

  uint8_t byte_budget = 32u;
  while (Serial.available() > 0 && byte_budget-- > 0u) {
    OtisSerialFrameEvent event = otis_serial_frame_collect(
        &serial_command_collector, (char)Serial.read());
    if (event == OtisSerialFrameEvent::RejectedTooLong) {
      if (output_allowed)
        emit_status("command", "line", "rejected_too_long",
                    OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
      else
        deferred_serial_error = OtisSerialFrameEvent::RejectedTooLong;
      return;
    }
    if (event != OtisSerialFrameEvent::Complete) {
      continue;
    }

    if (otis_serial_frame_validate(&serial_command_collector) !=
        OtisSerialFrameValidation::Valid) {
      otis_serial_frame_collector_init(&serial_command_collector);
      if (output_allowed)
        emit_status("command", "line", "rejected_invalid_character",
                    OTIS_SEVERITY_WARN, OTIS_FLAG_NONE);
      else
        deferred_serial_invalid = true;
      return;
    }

    char complete_line[OTIS_SERIAL_COMMAND_BUFFER_SIZE] = {};
    snprintf(complete_line, sizeof(complete_line), "%s",
             serial_command_collector.line);
    OtisParsedSerialCommand command =
        otis_serial_command_parse(serial_command_collector.line);
    otis_serial_frame_collector_init(&serial_command_collector);
    if (!output_allowed) {
      if (command.kind == OtisSerialCommandKind::ActiveAbort) {
        deferred_abort_queued = queue_dual_core_active_control(
            OtisRunControlKind::Abort);
        deferred_abort_result_ready = true;
        return;
      }
      snprintf(deferred_serial_command, sizeof(deferred_serial_command), "%s",
               complete_line);
      deferred_serial_command_ready = true;
      return;
    }
    execute_serial_command(command);
    return;
  }
}

}  // namespace

void setup() {
  otis_memory_budget_note_current_core();
  otis_runtime_state_init(&runtime_state);
  otis_dual_core_partition_reset();
  otis_transport_liveness_reset(&dual_core_transport_liveness, millis(),
                                otis_transport_written_bytes());
  dual_core_transport_abort_queued = false;
  otis_actuator_guard_init(&dual_core_service_actuator_guard);
  otis_setup_execution_guard_init(&dual_core_service_setup_guard);
  dual_core_manual_start_consumed = false;
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
    __atomic_store_n(&dual_core_timing_boot_complete, true,
                     __ATOMIC_RELEASE);
    __atomic_store_n(&dual_core_service_boot_ready, true,
                     __ATOMIC_RELEASE);
    return;
  }

  boot_phase_clocks_init();
  boot_phase_gpio_init();
  boot_phase_ring_buffers_init();
  boot_phase_serial_init();
  boot_phase_protocol_banner();
  // The count boundary handler must exist before the primary PPS IRQ is armed.
  boot_phase_peripherals_init();
  __atomic_store_n(&dual_core_service_boot_ready, true, __ATOMIC_RELEASE);
  const uint32_t timing_boot_wait_started_ms = millis();
  while (!__atomic_load_n(&dual_core_timing_boot_complete,
                          __ATOMIC_ACQUIRE) &&
         (uint32_t)(millis() - timing_boot_wait_started_ms) <
             kDualCoreBootHandshakeTimeoutMs) {
    // The receiver is already live at this point; drain its small UART FIFO
    // while Core 1 completes boot so startup cannot manufacture a truncated
    // NMEA frame or a false receiver-identity outage.
    otis_gnss_receiver_service(millis());
    if (otis_transport_ready()) {
      service_dual_core_outputs();
    } else {
      discard_dual_core_outputs_before_first_carrier();
    }
    delay(1);
  }
  if (!__atomic_load_n(&dual_core_timing_boot_complete,
                       __ATOMIC_ACQUIRE)) {
    otis_dual_core_latch_fault(OtisPartitionFault::BootHandshakeTimeout);
    halt_boot(BootFatal::DualCoreHandshakeTimeout,
              BootPhase::CapabilityAudit);
  }
}

void setup1() {
  otis_memory_budget_note_current_core();
  otis_status_emit_init_with_sink(&dual_core_timing_status_context, nullptr,
                                  publish_dual_core_timing_status_sink);
  otis_setup_authority_guard_init(&dual_core_timing_setup_guard);
  const uint32_t service_boot_wait_started_ms = millis();
  while (!__atomic_load_n(&dual_core_service_boot_ready, __ATOMIC_ACQUIRE) &&
         (uint32_t)(millis() - service_boot_wait_started_ms) <
             kDualCoreBootHandshakeTimeoutMs) {
    delay(1);
  }
  if (!__atomic_load_n(&dual_core_service_boot_ready, __ATOMIC_ACQUIRE))
    return;
  if (runtime_state.boot.safe_mode_active) {
    __atomic_store_n(&dual_core_timing_boot_complete, true,
                     __ATOMIC_RELEASE);
    return;
  }
  __atomic_store_n(&dual_core_timing_boot_in_progress, true,
                   __ATOMIC_RELEASE);
  otis_dual_core_set_timing_owner_active(true);
  boot_phase_timer_init();
  boot_phase_forwarded_output_init();
  boot_phase_forwarded_monitor_init();
  boot_phase_pps_input_init();
  boot_phase_preview_init();
  boot_phase_capability_audit();
  boot_phase_run_mode();
  // Do not overlap the first large periodic timing-health burst with the
  // final bounded boot-status drain on Core 0.
  dual_core_last_timing_status_ms = millis();
  __atomic_store_n(&dual_core_timing_boot_in_progress, false,
                   __ATOMIC_RELEASE);
  __atomic_store_n(&dual_core_timing_boot_complete, true,
                   __ATOMIC_RELEASE);
}

void loop1() {
  otis_memory_budget_note_current_core();
  if (!__atomic_load_n(&dual_core_timing_boot_complete,
                       __ATOMIC_ACQUIRE) ||
      runtime_state.boot.safe_mode_active) {
    return;
  }
  __atomic_store_n(&dual_core_timing_loop_started, true,
                   __ATOMIC_RELEASE);
  const uint32_t now_ms = millis();
  // Host attachment controls only delivery of the timing plane's outbound
  // records. It must never gate capture, witness, boundary, estimator, or
  // health service: those producers are already live and their finite queues
  // must remain continuously drained even when USB attaches late.
  // Progress instrumentation is deliberately bounded to four complete trace
  // samples per second.  The empty service-queue poll carries no diagnostic
  // atomic accounting, so the protected timing core's hot path stays lean.
  const bool trace_timing_loop = dual_core_timing_trace_due(now_ms);
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::LoopEnter,
                                        otis_monotonic_us32_now());
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::ServiceInput,
                                        otis_monotonic_us32_now());
  service_dual_core_timing_inputs();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::BoundaryDrain,
                                        otis_monotonic_us32_now());
  drain_pps_count_boundary_ring();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::CaptureDrain,
                                        otis_monotonic_us32_now());
  drain_capture_ring();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::GateService,
                                        otis_monotonic_us32_now());
  service_tcxo_gate();
  service_adaptive_hybrid_regulation_health();
  service_adaptive_hybrid_regulation_application_outcome();
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::TimingHealth,
                                        otis_monotonic_us32_now());
  publish_dual_core_timing_health(now_ms);
  if (trace_timing_loop)
    otis_dual_core_note_timing_progress(OtisTimingProgressPhase::LoopIdle,
                                        otis_monotonic_us32_now());
}

void loop() {
  otis_memory_budget_note_current_core();
  if (runtime_state.boot.safe_mode_active) {
    emit_boot_records_if_serial_ready();
    return;
  }

  // Core 0 is the sole GNSS UART/link-state owner. Core 1 must never service
  // this mutable state, including before the first USB carrier attaches.
  // Core 0 remains live in the carrier-absent branch below, so attachment is
  // not required for bounded UART drainage or bootstrap progress.
  // The USB byte stream has one chunked-frame owner. A producer keeps
  // ownership through its complete frame, but ownership no longer suppresses
  // input-only command collection indefinitely. Total pending-frame time is
  // bounded by the carrier contract; timeout quarantines the partial stream,
  // inhibits actuation, and drains internal queues as explicitly lost until a
  // reset starts a new evidence session.
  const uint32_t now_ms = millis();
  otis_gnss_receiver_service(now_ms);
  // Receiver/DAC state is an internal Core 0 -> Core 1 service, independent
  // of carrier presence and outbound frame progress. Its own cadence and
  // queue reservation bound publication on every transport path.
  publish_dual_core_service_metadata(now_ms);
  if (!otis_transport_ready()) {
    if (!otis_transport_liveness_note_carrier_absent(
            &dual_core_transport_liveness, now_ms,
            otis_transport_written_bytes())) {
      otis_dual_core_latch_fault(OtisPartitionFault::TransportObstructed);
      discard_dual_core_outputs_after_transport_fault();
    } else {
      abandon_dual_core_serial_frames_on_carrier_loss();
      // Continue bounded internal drainage on the sole consumer core even
      // before USB attaches. Core 1 must never pop its own outbound queues.
      discard_dual_core_outputs_before_first_carrier();
    }
    service_serial_commands(false);
    return;
  }
  bool frame_active = dual_core_transport_liveness.state ==
                      OtisTransportLivenessState::FrameObstructed;
  bool transport_live = otis_transport_liveness_observe(
      &dual_core_transport_liveness, now_ms, frame_active,
      otis_transport_written_bytes());
  // Once a frame is pending, enforce its total horizon before attempting any
  // further write. This prevents a final byte at the deadline from hiding a
  // carrier violation and prevents all writes after Faulted is latched.
  if (transport_live) {
    frame_active = service_dual_core_serial_frame_transport();
    transport_live = otis_transport_liveness_observe(
        &dual_core_transport_liveness, now_ms, frame_active,
        otis_transport_written_bytes());
  }
  if (!transport_live) {
    otis_dual_core_latch_fault(OtisPartitionFault::TransportObstructed);
    if (!dual_core_transport_abort_queued) {
      dual_core_transport_abort_queued = queue_dual_core_active_control(
          OtisRunControlKind::Abort);
    }
    service_serial_commands(false);
    discard_dual_core_outputs_after_transport_fault();
    return;
  }
  if (frame_active) {
    // RX and explicit abort remain bounded even while no other writer may
    // interleave bytes with the active frame.
    service_serial_commands(false);
    return;
  }
  service_dual_core_outputs();
  emit_protocol_banner_if_serial_ready();
  emit_run_mode_status_if_ready();
  emit_resource_ownership_status();
  service_serial_commands();
  service_environment_sensors();
  emit_periodic_status();
}
